from __future__ import annotations

import json
import pathlib
import signal
import subprocess

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

from .core import RUN_DIR, STATE_FILE, on_battery_from_sysfs

CONF = pathlib.Path.home() / '.config/ff-power-manager/presence.json'
BACKLIGHT_PATH = pathlib.Path('/sys/class/backlight/intel_backlight/brightness')
DEFAULT = {
    'enabled': True,
    'away_confirm': 5.0,
    'away_delay': 60,
    'wake_on_approach': True,
    'wake_only_if_fpm_off': False,
    'screen_off_on_away': False,
    'lock_on_away': False,
    'auto_refresh_rate': True,
    'promotion_120hz': True,
    'force_120hz_on_battery': True,
    'oled_screen_care': False,
    'oled_dim_inactive_sec': 0,
    'inhibit_on_media': True,
}


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
        out['away_delay'] = 10
    out['promotion_120hz'] = bool(out.get('promotion_120hz', True))
    out['force_120hz_on_battery'] = bool(out.get('force_120hz_on_battery', True))
    out['screen_off_on_away'] = bool(out.get('screen_off_on_away', False))
    out['oled_screen_care'] = bool(out.get('oled_screen_care', False))
    out['inhibit_on_media'] = bool(out.get('inhibit_on_media', True))
    try:
        out['oled_dim_inactive_sec'] = max(0, min(300, int(out.get('oled_dim_inactive_sec', 0))))
    except Exception:
        out['oled_dim_inactive_sec'] = 0
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
        try:
            RUN_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self.dir_file = Gio.File.new_for_path(str(RUN_DIR))
        self.monitor = self.dir_file.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect('changed', self._fs_changed)
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
        GLib.timeout_add_seconds(3, self._periodic_power_check)

    def _periodic_power_check(self) -> bool:
        self.cfg = load_config()
        mode = 'battery' if on_battery_from_sysfs() else 'ac'
        p = RUN_DIR / 'power.mode'
        if p.exists():
            try:
                txt = p.read_text().strip()
                if txt in ('battery', 'ac'):
                    mode = txt
            except Exception:
                pass
        if self._last_checked_mode != mode:
            self._last_checked_mode = mode
            self._update_refresh_rate(mode)

        if not self.cfg.get('oled_screen_care', False):
            if self.is_dimmed:
                self._set_dimming(False)
                self.is_dimmed = False
        else:
            idletime_ms = self._get_idletime_ms()
            dim_sec = int(self.cfg.get('oled_dim_inactive_sec', 0))
            if dim_sec > 0:
                dim_ms = dim_sec * 1000
                disp_mode = self._get_display_power_save()
                if not self.is_dimmed and disp_mode == 0 and idletime_ms >= dim_ms:
                    self._set_dimming(True)
                    self.is_dimmed = True
                elif self.is_dimmed and idletime_ms < 2500:
                    self._set_dimming(False)
                    self.is_dimmed = False
        return GLib.SOURCE_CONTINUE

    def _set_dimming(self, dim: bool) -> None:
        try:
            self.session.call_sync(
                'org.gnome.Shell.Brightness',
                '/org/gnome/Shell/Brightness',
                'org.gnome.Shell.Brightness',
                'SetDimming',
                GLib.Variant('(b)', (dim,)),
                None, Gio.DBusCallFlags.NONE, 1000, None,
            )
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
            # Ensure backlight is never stuck at 0
            try:
                if BACKLIGHT_PATH.exists() and int(BACKLIGHT_PATH.read_text().strip()) == 0:
                    BACKLIGHT_PATH.write_text('220')
            except Exception:
                pass
            # Wake screensaver surface
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
            # Ensure Mutter display is awake
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
                    None, Gio.DBusCallFlags.NONE, 1000, None,
                )
            except Exception:
                pass

    def _update_refresh_rate(self, mode: str) -> None:
        if not self.cfg.get('auto_refresh_rate', True):
            return
        # Automatic refresh rate switching:
        # - Battery: 120Hz + VRR (dynamic 48-120Hz adaptive clocking for silky smooth 120 FPS without battery penalty)
        # - AC (Plugged in): 120Hz + VRR (full 120 FPS buttery smooth ProMotion)
        force_120_battery = self.cfg.get('force_120hz_on_battery', True)
        if mode == 'battery' and not force_120_battery:
            target_mode = '2880x1800@60.000'
        else:
            target_mode = '2880x1800@120.000+vrr'

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
            for m in monitors[0][1]:
                if m[6].get('is-current'):
                    current_mode = m[0]
                    break
            if current_mode == target_mode:
                try:
                    (RUN_DIR / 'refresh.rate').write_text(target_mode)
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
                    2,
                    new_lm,
                    {'layout-mode': GLib.Variant('u', 1)}
                )),
                None, Gio.DBusCallFlags.NONE, 2000, None
            )
            try:
                (RUN_DIR / 'refresh.rate').write_text(target_mode)
            except Exception:
                pass
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

        # 3. Active audio sink output check (PipeWire / PulseAudio)
        try:
            p = subprocess.run(['pactl', 'list', 'sinks', 'short'], capture_output=True, text=True, timeout=0.5)
            if 'RUNNING' in p.stdout:
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
        min_idle_ms = max(10000, int(self.cfg.get('away_delay', 10) * 1000))
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
        if self.cfg.get('screen_off_on_away'):
            try:
                self._set_display(False)
                self.screen_off_by_fpm = True
            except Exception:
                pass
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
