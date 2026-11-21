from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import time

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

from .core import RUN_DIR, STATE_FILE, on_battery_from_sysfs

CONF = pathlib.Path.home() / '.config/ff-power-manager/presence.json'
BACKLIGHT_PATH = pathlib.Path('/sys/class/backlight/intel_backlight/brightness')
DEFAULT = {
    'enabled': True,
    'away_confirm': 3.0,
    'away_delay': 20,
    'wake_on_approach': True,
    'wake_only_if_fpm_off': False,
    'lock_on_away': False,
    'auto_refresh_rate': True,
    'promotion_120hz': False,
    'force_120hz_on_battery': True,
    'oled_screen_care': False,
    'oled_dim_inactive_sec': 0,
    'inhibit_on_media': True,
    'tof_gesture_mode': 'off',
}

TOF_GESTURE_MODES = ('off', 'media_pause', 'privacy_dim', 'lock_screen')
TELEMETRY_FILE = RUN_DIR / 'sensor_telemetry.json'



def _find_battery_dir() -> pathlib.Path | None:
    for p in sorted(pathlib.Path('/sys/class/power_supply').glob('BAT*')):
        if (p / 'capacity').exists():
            return p
    return None

def load_config() -> dict:
    out = dict(DEFAULT)
    try:
        if CONF.exists():
            data = json.loads(CONF.read_text())
            if isinstance(data, dict):
                for key in DEFAULT:
                    if key in data:
                        out[key] = data[key]
    except Exception:
        pass
    try:
        out['away_confirm'] = max(0.0, min(30.0, float(out['away_confirm'])))
    except Exception:
        out['away_confirm'] = 3.0
    try:
        out['away_delay'] = max(0, min(300, int(out['away_delay'])))
    except Exception:
        out['away_delay'] = 20
    out['promotion_120hz'] = bool(out.get('promotion_120hz', True))
    out['force_120hz_on_battery'] = bool(out.get('force_120hz_on_battery', True))
    out['oled_screen_care'] = bool(out.get('oled_screen_care', False))
    out['inhibit_on_media'] = bool(out.get('inhibit_on_media', True))
    try:
        out['oled_dim_inactive_sec'] = max(0, min(300, int(out.get('oled_dim_inactive_sec', 0))))
    except Exception:
        out['oled_dim_inactive_sec'] = 0
    gmode = str(out.get('tof_gesture_mode', 'off'))
    out['tof_gesture_mode'] = gmode if gmode in TOF_GESTURE_MODES else 'off'
    return out


class PresenceController:
    def __init__(self):
        self.cfg = load_config()
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.timer = 0
        self.last_state = None
        self.screen_off_by_fpm = False
        self.is_dimmed = False
        self.saved_brightness = None
        self._last_checked_mode = None
        self._promo_idle_60hz = False
        self._idle_watch_id = 0
        self._active_watch_id = 0
        self._gesture_timer_id = 0
        self._wave_enter_ts: float | None = None
        self._wave_cooldown_until = 0.0
        try:
            RUN_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.dir_file = Gio.File.new_for_path(str(RUN_DIR))
        self.monitor = self.dir_file.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect('changed', self._fs_changed)
        try:
            self.conf_file = Gio.File.new_for_path(str(CONF))
            self.conf_monitor = self.conf_file.monitor_file(Gio.FileMonitorFlags.NONE, None)
            self.conf_monitor.connect('changed', self._conf_changed)
        except Exception:
            self.conf_monitor = None
        try:
            self.session.signal_subscribe(
                'org.gnome.Mutter.IdleMonitor',
                'org.gnome.Mutter.IdleMonitor',
                'WatchFired',
                '/org/gnome/Mutter/IdleMonitor/Core',
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_idle_watch_fired,
            )
            self._arm_promo_idle_watch()
        except Exception:
            pass
        try:
            self.sys_bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            self.sys_bus.signal_subscribe(
                'org.freedesktop.UPower',
                'org.freedesktop.DBus.Properties',
                'PropertiesChanged',
                '/org/freedesktop/UPower',
                None,
                Gio.DBusSignalFlags.NONE,
                self._upower_changed,
            )
        except Exception:
            self.sys_bus = None
        self._set_dimming(False)
        self._read_state()
        self._read_power_mode_once()
        self._sync_gesture_timer()
        GLib.timeout_add_seconds(3, self._periodic_power_check)

    def _periodic_power_check(self) -> bool:
        self.cfg = load_config()
        mode = 'battery' if on_battery_from_sysfs() else 'ac'
        p = RUN_DIR / 'power.mode'
        if p.exists():
            try:
                txt = p.read_text().strip()
                if txt in ('battery', 'ac', 'max_battery', 'maximum_battery', 'extreme_performance', 'cool_quiet'):
                    mode = txt
            except Exception:
                pass
        # Record OLED & ProMotion energy savings (~3s tick)
        try:
            sav_p = RUN_DIR / 'savings.json'
            if not getattr(self, '_sav_loaded', False):
                self._sav_loaded = True
                if sav_p.exists():
                    d = json.loads(sav_p.read_text())
                    self._sav_off_sec = float(d.get('screen_off_sec', 0.0))
                    self._sav_wh = float(d.get('wh_saved', 0.0))
                else:
                    self._sav_off_sec = 0.0
                    self._sav_wh = 0.0
            if self.screen_off_by_fpm:
                self._sav_off_sec += 3.0
                self._sav_wh += (4.5 * 3.0) / 3600.0
            elif getattr(self, '_promo_idle_60hz', False):
                self._sav_wh += (1.2 * 3.0) / 3600.0
            sav_p.write_text(json.dumps({
                'screen_off_sec': round(self._sav_off_sec, 1),
                'wh_saved': round(self._sav_wh, 3),
            }))
        except Exception:
            pass

        # One-Shot 100% Charge Watchdog: restore %80 conservation when full
        oneshot_flag = CONF.parent / 'oneshot_100'
        if oneshot_flag.exists():
            try:
                _bd = _find_battery_dir()
                cap_p = (_bd / 'capacity') if _bd else pathlib.Path('/nonexistent')
                stat_p = (_bd / 'status') if _bd else pathlib.Path('/nonexistent')
                cap_val = int(cap_p.read_text().strip()) if cap_p.exists() else 0
                stat_val = stat_p.read_text().strip() if stat_p.exists() else ''
                if cap_val >= 99 or stat_val == 'Full':
                    oneshot_flag.unlink()
                    subprocess.run(['/usr/local/bin/ffctl', 'conservation', 'on'], check=False)
                    subprocess.run(['notify-send', 'FF Power Manager', '%100 şarj tamamlandı — %80 pil koruma tekrar aktif edildi.'], check=False)
            except Exception:
                pass

        # Smart battery < 30% check for automatic 60Hz power saving
        try:
            _bdir = _find_battery_dir(); cap_p = (_bdir / 'capacity') if _bdir else pathlib.Path('/nonexistent')
            if cap_p.exists() and on_battery_from_sysfs() and int(cap_p.read_text().strip()) <= 30:
                mode = 'max_battery'
        except Exception:
            pass
        self._poll_tick = getattr(self, '_poll_tick', 0) + 1
        scan_heavy = (self._poll_tick % 3 == 1)

        cinema_apps = {'stremio', 'mpv', 'vlc', 'celluloid', 'kodi', 'clapper'}
        if scan_heavy or getattr(self, '_last_cinema_active', None) is None:
            cinema_active = False
            try:
                for cp in pathlib.Path('/proc').glob('[0-9]*/comm'):
                    try:
                        cname = cp.read_text(encoding='utf-8', errors='ignore').strip().lower()
                        if cname in cinema_apps:
                            cinema_active = True
                            break
                    except Exception:
                        continue
            except Exception:
                pass
        else:
            cinema_active = bool(self._last_cinema_active)

        if cinema_active != getattr(self, '_last_cinema_active', None):
            self._last_cinema_active = cinema_active
            try:
                (RUN_DIR / 'active.context').write_text('cinema\n' if cinema_active else 'normal\n')
                gs = Gio.Settings.new('org.gnome.settings-daemon.plugins.color')
                if cinema_active:
                    self._saved_night_light = gs.get_boolean('night-light-enabled')
                    if self._saved_night_light:
                        gs.set_boolean('night-light-enabled', False)
                else:
                    if getattr(self, '_saved_night_light', False):
                        gs.set_boolean('night-light-enabled', True)
                        self._saved_night_light = False
            except Exception:
                pass
            self._last_checked_mode = None

        if cinema_active and mode in ('battery', 'max_battery'):
            mode = 'ac'

        if (not on_battery_from_sysfs() or cinema_active) and self._promo_idle_60hz:
            self._promo_idle_60hz = False
            self._last_checked_mode = None

        if self._promo_idle_60hz and on_battery_from_sysfs() and not cinema_active:
            pass
        elif self._last_checked_mode != mode:
            self._last_checked_mode = mode
            self._update_refresh_rate(mode)

        # Smart Media Tracking: Broadcast media state for low-power video playback
        if scan_heavy or getattr(self, '_last_media_active', None) is None:
            media_active = self._is_media_active()
        else:
            media_active = bool(self._last_media_active)
        if media_active != getattr(self, '_last_media_active', None):
            self._last_media_active = media_active
            try:
                media_file = RUN_DIR / 'media.active'
                if media_active:
                    media_file.write_text('playing\n')
                    if on_battery_from_sysfs():
                        self._update_refresh_rate('battery')
                else:
                    if media_file.exists():
                        media_file.unlink()
            except Exception:
                pass

        if not self.cfg.get('oled_screen_care', False):
            if self.is_dimmed:
                self._set_dimming(False)
                self.is_dimmed = False
        else:
            dim_sec = int(self.cfg.get('oled_dim_inactive_sec', 0))
            if dim_sec > 0:
                if self.cfg.get('inhibit_on_media', True) and self._is_media_active():
                    if self.is_dimmed:
                        self._set_dimming(False)
                        self.is_dimmed = False
                else:
                    idletime_ms = self._get_idletime_ms()
                    dim_ms = dim_sec * 1000
                    disp_mode = self._get_display_power_save()
                    if not self.is_dimmed and disp_mode == 0 and idletime_ms >= dim_ms:
                        self._set_dimming(True)
                        self.is_dimmed = self.saved_brightness is not None
                    elif self.is_dimmed and idletime_ms < 2500:
                        self._set_dimming(False)
                        self.is_dimmed = False
        return GLib.SOURCE_CONTINUE

    def _set_gsd_brightness(self, value: int) -> None:
        self.session.call_sync(
            'org.gnome.SettingsDaemon.Power',
            '/org/gnome/SettingsDaemon/Power',
            'org.freedesktop.DBus.Properties',
            'Set',
            GLib.Variant('(ssv)', (
                'org.gnome.SettingsDaemon.Power.Screen',
                'Brightness',
                GLib.Variant('i', int(value)),
            )),
            None, Gio.DBusCallFlags.NONE, 1000, None,
        )

    def _fade_gsd_brightness(self, start: int, end: int, steps: int = 12, delay_sec: float = 0.08, abort_on_activity: bool = False) -> bool:
        if start == end:
            return True
        for i in range(1, steps + 1):
            if abort_on_activity and self._get_idletime_ms() < 1500:
                return False
            val = round(start + (end - start) * (i / steps))
            self._set_gsd_brightness(val)
            if i < steps:
                time.sleep(delay_sec)
        return True

    def _set_dimming(self, dim: bool) -> None:
        try:
            res = self.session.call_sync(
                'org.gnome.SettingsDaemon.Power',
                '/org/gnome/SettingsDaemon/Power',
                'org.freedesktop.DBus.Properties',
                'Get',
                GLib.Variant('(ss)', ('org.gnome.SettingsDaemon.Power.Screen', 'Brightness')),
                GLib.VariantType('(v)'), Gio.DBusCallFlags.NONE, 1000, None,
            )
            cur = int(res.unpack()[0])
            if dim:
                if cur > 0:
                    if self.saved_brightness is None:
                        self.saved_brightness = cur
                    if not self._fade_gsd_brightness(cur, 0, steps=12, delay_sec=0.08, abort_on_activity=True):
                        restore = int(self.saved_brightness)
                        self.saved_brightness = None
                        self._set_gsd_brightness(restore)
                        self.is_dimmed = False
            elif self.saved_brightness is not None:
                restore = int(self.saved_brightness)
                self.saved_brightness = None
                self._fade_gsd_brightness(cur, restore, steps=5, delay_sec=0.025, abort_on_activity=False)
        except Exception:
            pass

    def _get_display_power_save(self) -> int:
        try:
            res = self.session.call_sync(
                'org.gnome.Mutter.DisplayConfig',
                '/org/gnome/Mutter/DisplayConfig',
                'org.freedesktop.DBus.Properties',
                'Get',
                GLib.Variant('(ss)', ('org.gnome.Mutter.DisplayConfig', 'PowerSaveMode')),
                None, Gio.DBusCallFlags.NONE, 1000, None,
            )
            return int(res.unpack()[0])
        except Exception:
            return 0

    def _get_idletime_ms(self) -> int:
        try:
            res = self.session.call_sync(
                'org.gnome.Mutter.IdleMonitor',
                '/org/gnome/Mutter/IdleMonitor/Core',
                'org.gnome.Mutter.IdleMonitor',
                'GetIdletime',
                None, None, Gio.DBusCallFlags.NONE, 1000, None,
            )
            return int(res.unpack()[0])
        except Exception:
            return 999999999

    def _set_display(self, on: bool) -> None:
        if on:
            if self.is_dimmed:
                self._set_dimming(False)
                self.is_dimmed = False
            # 1. Wake Mutter KMS display controller first
            try:
                self.session.call_sync(
                    'org.gnome.Mutter.DisplayConfig',
                    '/org/gnome/Mutter/DisplayConfig',
                    'org.freedesktop.DBus.Properties',
                    'Set',
                    GLib.Variant('(ssv)', (
                        'org.gnome.Mutter.DisplayConfig',
                        'PowerSaveMode',
                        GLib.Variant('i', 0),
                    )),
                    None, Gio.DBusCallFlags.NONE, 2000, None,
                )
            except Exception:
                pass
            # 2. Wake screensaver surface
            try:
                self.session.call_sync(
                    'org.gnome.ScreenSaver',
                    '/org/gnome/ScreenSaver',
                    'org.gnome.ScreenSaver',
                    'SetActive',
                    GLib.Variant('(b)', (False,)),
                    None, Gio.DBusCallFlags.NONE, 1000, None,
                )
            except Exception:
                pass
            try:
                self.session.call_sync(
                    'org.gnome.ScreenSaver',
                    '/org/gnome/ScreenSaver',
                    'org.gnome.ScreenSaver',
                    'WakeUpScreen',
                    None, None, Gio.DBusCallFlags.NONE, 1000, None,
                )
            except Exception:
                pass
        else:
            # Turn display OFF (Mutter DPMS OFF: cuts pixel power completely for OLED)
            try:
                self.session.call_sync(
                    'org.gnome.Mutter.DisplayConfig',
                    '/org/gnome/Mutter/DisplayConfig',
                    'org.freedesktop.DBus.Properties',
                    'Set',
                    GLib.Variant('(ssv)', (
                        'org.gnome.Mutter.DisplayConfig',
                        'PowerSaveMode',
                        GLib.Variant('i', 3),
                    )),
                    None, Gio.DBusCallFlags.NONE, 2000, None,
                )
            except Exception:
                pass

    def _update_refresh_rate(self, mode: str) -> None:
        if not self.cfg.get('auto_refresh_rate', True):
            return
        force_120_battery = self.cfg.get('force_120hz_on_battery', True)
        want_60hz = (mode in ('max_battery', 'maximum_battery')) or (mode == 'battery' and not force_120_battery)

        try:
            res = self.session.call_sync(
                'org.gnome.Mutter.DisplayConfig',
                '/org/gnome/Mutter/DisplayConfig',
                'org.gnome.Mutter.DisplayConfig',
                'GetCurrentState',
                None, None, Gio.DBusCallFlags.NONE, 2000, None
            )
            serial, monitors, logical_monitors, _ = res.unpack()
            if not logical_monitors or not monitors:
                return

            current_mode = None
            preferred_res = None
            for m in monitors[0][1]:
                if m[6].get('is-current'):
                    current_mode = m[0]
                    break
                if m[6].get('is-preferred') and preferred_res is None:
                    preferred_res = m[0].split('@')[0]
            active_res = current_mode.split('@')[0] if current_mode else preferred_res
            if not active_res:
                return

            mode_high = None
            high_hz = 0.0
            mode_low = None
            for m in monitors[0][1]:
                m_id = m[0]
                if not m_id.startswith(active_res + '@'):
                    continue
                try:
                    hz = float(m_id.split('@', 1)[1].split('+', 1)[0])
                except Exception:
                    continue
                if 58.0 <= hz <= 62.0 and mode_low is None:
                    mode_low = m_id
                if hz > high_hz + 1.0 or (abs(hz - high_hz) <= 1.0 and '+vrr' in m_id):
                    high_hz = hz
                    mode_high = m_id

            target_mode = (mode_low if want_60hz else mode_high) or current_mode
            if not target_mode:
                return
            high_label = f"{int(round(high_hz))} Hz (Adaptive)" if high_hz else "120 Hz"
            label_str = '60 Hz (Power Saver)' if want_60hz else high_label

            if current_mode == target_mode:
                try:
                    (RUN_DIR / 'refresh.rate').write_text(label_str)
                except Exception:
                    pass
                return

            lm = logical_monitors[0]
            x, y, scale, transform, primary, mons, _ = lm
            mon_assignment = [(mons[0][0], target_mode, {})]
            new_lm = [(int(x), int(y), float(scale), int(transform), bool(primary), mon_assignment)]

            self.session.call_sync(
                'org.gnome.Mutter.DisplayConfig',
                '/org/gnome/Mutter/DisplayConfig',
                'org.gnome.Mutter.DisplayConfig',
                'ApplyMonitorsConfig',
                GLib.Variant('(uua(iiduba(ssa{sv}))a{sv})', (
                    serial,
                    1,
                    new_lm,
                    {}
                )),
                None, Gio.DBusCallFlags.NONE, 2000, None
            )
            try:
                (RUN_DIR / 'refresh.rate').write_text(label_str)
            except Exception:
                pass
        except Exception:
            if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE') and shutil.which('hyprctl'):
                self._apply_refresh_hyprland(want_60hz)
            elif (os.environ.get('KDE_FULL_SESSION') or 'kde' in os.environ.get('XDG_CURRENT_DESKTOP', '').lower()) and shutil.which('kscreen-doctor'):
                self._apply_refresh_kde(want_60hz)

    def _apply_refresh_hyprland(self, want_60hz: bool) -> None:
        try:
            raw = subprocess.check_output(['hyprctl', 'monitors', '-j'], text=True, timeout=1.5)
            mons = json.loads(raw)
            if not mons:
                return
            mon = mons[0]
            name = mon.get('name', 'eDP-1')
            w = int(mon.get('width', 1920))
            h = int(mon.get('height', 1080))
            scale = mon.get('scale', 1)
            modes = mon.get('availableModes', [])
            rates = []
            for ms in modes:
                m = re.match(rf'^{w}x{h}@([0-9]+(?:\.[0-9]+)?)Hz', str(ms))
                if m:
                    rates.append(float(m.group(1)))
            if not rates:
                return
            low_hz = min((r for r in rates if 58.0 <= r <= 62.0), default=min(rates))
            high_hz = max(rates)
            target = low_hz if want_60hz else high_hz
            subprocess.run(
                ['hyprctl', 'keyword', 'monitor', f'{name},{w}x{h}@{target:.0f},auto,{scale}'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=1.5,
            )
            label_str = '60 Hz (Power Saver)' if want_60hz else f'{int(round(high_hz))} Hz (Hyprland ARR)'
            (RUN_DIR / 'refresh.rate').write_text(label_str)
        except Exception:
            pass

    def _apply_refresh_kde(self, want_60hz: bool) -> None:
        try:
            out = subprocess.check_output(['kscreen-doctor', '-o'], text=True, stderr=subprocess.DEVNULL, timeout=1.5)
            out_name = None
            best_low = (None, 999.0)
            best_high = (None, 0.0)
            for line in out.splitlines():
                line_s = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
                if line_s.startswith('Output:'):
                    parts = line_s.split()
                    if len(parts) >= 3:
                        out_name = parts[2]
                    continue
                if 'Modes:' in line_s or re.search(r'\b\d+:\d+x\d+@\d+', line_s):
                    for mid, hz_s in re.findall(r'(\d+):\d+x\d+@(\d+(?:\.\d+)?)', line_s):
                        hz = float(hz_s)
                        if 58.0 <= hz <= 62.0 and hz < best_low[1]:
                            best_low = (mid, hz)
                        if hz > best_high[1]:
                            best_high = (mid, hz)
            target_id = best_low[0] if want_60hz else best_high[0]
            if out_name and target_id:
                subprocess.run(['kscreen-doctor', f'output.{out_name}.mode.{target_id}'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False, timeout=1.5)
                label_str = '60 Hz (Power Saver)' if want_60hz else f'{int(round(best_high[1]))} Hz (Plasma ARR)'
                (RUN_DIR / 'refresh.rate').write_text(label_str)
        except Exception:
            pass

    def _upower_changed(self, _bus, _sender, _path, _iface, _signal, params) -> None:
        try:
            iface_name, changed_props, _invalidated = params.unpack()
            if 'OnBattery' in changed_props:
                on_bat = bool(changed_props['OnBattery'])
                mode = 'battery' if on_bat else 'ac'
                try:
                    (RUN_DIR / 'power.mode').write_text(mode)
                except Exception:
                    pass
                self._update_refresh_rate(mode)
        except Exception:
            pass

    def _arm_promo_idle_watch(self) -> None:
        if self._idle_watch_id:
            return
        try:
            res = self.session.call_sync(
                'org.gnome.Mutter.IdleMonitor',
                '/org/gnome/Mutter/IdleMonitor/Core',
                'org.gnome.Mutter.IdleMonitor',
                'AddIdleWatch',
                GLib.Variant('(t)', (8000,)),
                None, Gio.DBusCallFlags.NONE, 1000, None,
            )
            self._idle_watch_id = int(res.unpack()[0])
        except Exception:
            self._idle_watch_id = 0

    def _arm_promo_active_watch(self) -> None:
        if self._active_watch_id:
            return
        try:
            res = self.session.call_sync(
                'org.gnome.Mutter.IdleMonitor',
                '/org/gnome/Mutter/IdleMonitor/Core',
                'org.gnome.Mutter.IdleMonitor',
                'AddUserActiveWatch',
                None, None, Gio.DBusCallFlags.NONE, 1000, None,
            )
            self._active_watch_id = int(res.unpack()[0])
        except Exception:
            self._active_watch_id = 0

    def _on_idle_watch_fired(self, _bus, _sender, _path, _iface, _signal, params) -> None:
        try:
            watch_id = int(params.unpack()[0])
        except Exception:
            return
        if watch_id == self._idle_watch_id:
            if (
                on_battery_from_sysfs()
                and self.cfg.get('promotion_120hz', True)
                and self.cfg.get('force_120hz_on_battery', True)
                and not getattr(self, '_last_cinema_active', False)
                and self._get_display_power_save() == 0
                and not self._promo_idle_60hz
            ):
                self._promo_idle_60hz = True
                self._update_refresh_rate('max_battery')
                try:
                    (RUN_DIR / 'refresh.rate').write_text('60 Hz (ARR Idle)')
                except Exception:
                    pass
                self._arm_promo_active_watch()
        elif watch_id == self._active_watch_id:
            self._active_watch_id = 0
            if self._promo_idle_60hz:
                self._promo_idle_60hz = False
                self._last_checked_mode = None
                mode = 'ac' if not on_battery_from_sysfs() else 'battery'
                self._update_refresh_rate(mode)

    def _set_wireless_sleep(self, sleeping: bool) -> None:
        try:
            if sleeping:
                res = subprocess.run(['bluetoothctl', 'devices', 'Connected'], capture_output=True, text=True, timeout=1.0)
                if not res.stdout.strip():
                    subprocess.run(['bluetoothctl', 'power', 'off'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    self._bt_slept_by_fpm = True
            else:
                if getattr(self, '_bt_slept_by_fpm', False):
                    subprocess.run(['bluetoothctl', 'power', 'on'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1.0)
                    self._bt_slept_by_fpm = False
        except Exception:
            pass

    def _conf_changed(self, _monitor, _file, _other, _event_type) -> None:
        GLib.idle_add(self._apply_conf_now)

    def _apply_conf_now(self) -> bool:
        self.cfg = load_config()
        self._last_checked_mode = None
        self._sync_gesture_timer()
        self._periodic_power_check()
        return GLib.SOURCE_REMOVE

    def _sync_gesture_timer(self) -> None:
        want = self.cfg.get('tof_gesture_mode', 'off') != 'off'
        if want and not self._gesture_timer_id:
            self._gesture_timer_id = GLib.timeout_add(250, self._poll_tof_gesture)
        elif not want and self._gesture_timer_id:
            GLib.source_remove(self._gesture_timer_id)
            self._gesture_timer_id = 0
            self._wave_enter_ts = None

    def _toggle_mpris_playback(self) -> None:
        try:
            res = self.session.call_sync(
                'org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus',
                'ListNames', None, None, Gio.DBusCallFlags.NONE, 500, None
            )
            for name in res.unpack()[0]:
                if name.startswith('org.mpris.MediaPlayer2.'):
                    try:
                        self.session.call_sync(
                            name, '/org/mpris/MediaPlayer2', 'org.mpris.MediaPlayer2.Player',
                            'PlayPause', None, None, Gio.DBusCallFlags.NONE, 500, None
                        )
                    except Exception:
                        pass
        except Exception:
            pass

    def process_tof_wave_sample(self, distance_cm: float, now: float | None = None) -> str | None:
        """Detect a 0.15s-2.0s hand wave (<= 18 cm) and dispatch the configured privacy/media action."""
        mode = self.cfg.get('tof_gesture_mode', 'off')
        if mode == 'off':
            return None
        ts = time.monotonic() if now is None else now
        if 0 < distance_cm <= 18.0:
            if self._wave_enter_ts is None and ts >= self._wave_cooldown_until:
                self._wave_enter_ts = ts
            return None
        if distance_cm >= 22.0 and self._wave_enter_ts is not None:
            dur = ts - self._wave_enter_ts
            self._wave_enter_ts = None
            if 0.15 <= dur <= 2.0:
                self._wave_cooldown_until = ts + 4.0
                if mode == 'media_pause':
                    self._toggle_mpris_playback()
                elif mode == 'lock_screen':
                    self._lock()
                elif mode == 'privacy_dim':
                    self.is_dimmed = not self.is_dimmed
                    self._set_dimming(self.is_dimmed)
                return mode
        return None

    def _poll_tof_gesture(self) -> bool:
        if self.cfg.get('tof_gesture_mode', 'off') == 'off':
            self._gesture_timer_id = 0
            return GLib.SOURCE_REMOVE
        try:
            if TELEMETRY_FILE.exists():
                tel = json.loads(TELEMETRY_FILE.read_text())
                if float(tel.get('last_packet_sec_ago', 99.0)) <= 2.0:
                    self.process_tof_wave_sample(float(tel.get('distance_cm', 999.0)))
        except Exception:
            pass
        return GLib.SOURCE_CONTINUE

    def _lock(self) -> None:
        subprocess.run(['/usr/bin/loginctl', 'lock-session'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _cancel_timer(self) -> None:
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def _is_media_active(self) -> bool:
        # 1. Active media players via MPRIS (browsers, VLC, mpv, spotify, etc.)
        try:
            res = self.session.call_sync(
                'org.freedesktop.DBus',
                '/org/freedesktop/DBus',
                'org.freedesktop.DBus',
                'ListNames',
                None, None, Gio.DBusCallFlags.NONE, 500, None
            )
            names = [n for n in res.unpack()[0] if n.startswith('org.mpris.MediaPlayer2.')]
            for name in names:
                try:
                    prop = self.session.call_sync(
                        name,
                        '/org/mpris/MediaPlayer2',
                        'org.freedesktop.DBus.Properties',
                        'Get',
                        GLib.Variant('(ss)', ('org.mpris.MediaPlayer2.Player', 'PlaybackStatus')),
                        None, Gio.DBusCallFlags.NONE, 500, None
                    )
                    if prop.unpack()[0] == 'Playing':
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        # 2. GNOME SessionManager inhibitors (video / presentation / streaming)
        try:
            res = self.session.call_sync(
                'org.gnome.SessionManager',
                '/org/gnome/SessionManager',
                'org.gnome.SessionManager',
                'GetInhibitors',
                None, None, Gio.DBusCallFlags.NONE, 500, None
            )
            for p in res.unpack()[0]:
                try:
                    flags = self.session.call_sync(
                        'org.gnome.SessionManager', p,
                        'org.gnome.SessionManager.Inhibitor', 'GetFlags',
                        None, None, Gio.DBusCallFlags.NONE, 500, None
                    ).unpack()[0]
                    if not (flags & 8):
                        continue
                    app = self.session.call_sync(
                        'org.gnome.SessionManager', p,
                        'org.gnome.SessionManager.Inhibitor', 'GetAppId',
                        None, None, Gio.DBusCallFlags.NONE, 500, None
                    ).unpack()[0]
                    reason = self.session.call_sync(
                        'org.gnome.SessionManager', p,
                        'org.gnome.SessionManager.Inhibitor', 'GetReason',
                        None, None, Gio.DBusCallFlags.NONE, 500, None
                    ).unpack()[0]
                    app_lower = app.lower()
                    reason_lower = reason.lower()
                    if 'antigravity' in app_lower or reason_lower == 'electron':
                        continue
                    keywords = ('video', 'audio', 'media', 'play', 'movie', 'stream', 'webrtc', 'presentation', 'fullscreen', 'game')
                    if any(kw in reason_lower for kw in keywords):
                        return True
                    known_media_apps = ('vlc', 'mpv', 'totem', 'celluloid', 'clapper', 'kodi', 'firefox', 'chrome', 'brave', 'chromium')
                    if any(k in app_lower for k in known_media_apps):
                        return True
                except Exception:
                    pass
        except Exception:
            pass

        # 3. Native ALSA/PipeWire PCM stream check (zero subprocess fork every 3s)
        try:
            for pcm_status in pathlib.Path('/proc/asound').glob('card*/pcm*p/sub*/status'):
                if 'RUNNING' in pcm_status.read_text(encoding='utf-8', errors='ignore'):
                    return True
        except Exception:
            pass

        return False

    def _away_fire(self) -> bool:
        self.timer = 0
        try:
            current = STATE_FILE.read_text().strip()
        except Exception:
            current = 'disabled'
        if current != 'absent':
            return GLib.SOURCE_REMOVE

        # Safety check: if user was active on keyboard/touchpad, do not blank screen!
        idletime_ms = self._get_idletime_ms()
        min_idle_ms = max(5000, int(self.cfg.get('away_delay', 20) * 1000) - 2000)
        if idletime_ms < min_idle_ms:
            # User is active; postpone check
            self.timer = GLib.timeout_add(5000, self._away_fire)
            return GLib.SOURCE_REMOVE

        # Safety check: if media / video / presentation playback is active, do not turn off screen!
        if self.cfg.get('inhibit_on_media', True) and self._is_media_active():
            self.timer = GLib.timeout_add(10000, self._away_fire)
            return GLib.SOURCE_REMOVE

        if self.cfg.get('lock_on_away'):
            self._lock()
        return GLib.SOURCE_REMOVE

    def _handle(self, state: str) -> None:
        if state == self.last_state:
            return
        self.last_state = state
        self.cfg = load_config()

        if state == 'present':
            self._cancel_timer()
            if self.is_dimmed:
                self._set_dimming(False)
                self.is_dimmed = False
            allowed = bool(self.cfg.get('wake_on_approach', True))
            if allowed:
                try:
                    self._set_display(True)
                    self.screen_off_by_fpm = False
                    self._set_wireless_sleep(False)
                except Exception:
                    pass
        elif state == 'absent':
            self._cancel_timer()
            confirm = float(self.cfg.get('away_confirm', 3.0))
            extra = int(self.cfg.get('away_delay', 10))
            total = max(1.0, confirm + extra)
            self.timer = GLib.timeout_add(int(total * 1000), self._away_fire)
        elif state in ('disabled', 'error'):
            self._cancel_timer()

    def _read_state(self) -> None:
        try:
            state = STATE_FILE.read_text().strip()
        except Exception:
            state = 'disabled'
        self._handle(state)

    def _read_power_mode_once(self) -> bool:
        mode = 'battery' if on_battery_from_sysfs() else 'ac'
        try:
            p = RUN_DIR / 'power.mode'
            if p.exists():
                txt = p.read_text().strip()
                if txt in ('battery', 'ac'):
                    mode = txt
        except Exception:
            pass
        self._update_refresh_rate(mode)
        return GLib.SOURCE_REMOVE


    def _fs_changed(self, _monitor, file, _other, _event_type) -> None:
        name = pathlib.Path(file.get_path() or '').name if file else ''
        if name == STATE_FILE.name:
            GLib.idle_add(self._read_state_once)
        elif name == 'power.mode':
            GLib.idle_add(self._read_power_mode_once)

    def _read_state_once(self) -> bool:
        self._read_state()
        return GLib.SOURCE_REMOVE

    def close(self) -> None:
        self._cancel_timer()
        if getattr(self, '_gesture_timer_id', 0):
            GLib.source_remove(self._gesture_timer_id)
            self._gesture_timer_id = 0
        try:
            self.monitor.cancel()
        except Exception:
            pass


def main():
    app = PresenceController()
    loop = GLib.MainLoop()

    def stop(*_):
        app.close()
        loop.quit()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        loop.run()
    finally:
        app.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
