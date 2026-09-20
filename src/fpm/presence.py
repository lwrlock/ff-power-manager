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
DEFAULT = {
    'away_confirm': 2.0,
    'away_delay': 0,
    'wake_on_approach': True,
    'wake_only_if_fpm_off': True,
    'screen_off_on_away': True,
    'lock_on_away': False,
    'auto_refresh_rate': True,
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
        out['away_confirm'] = max(0.0, min(10.0, float(out['away_confirm'])))
    except Exception:
        out['away_confirm'] = 2.0
    try:
        out['away_delay'] = max(0, min(120, int(out['away_delay'])))
    except Exception:
        out['away_delay'] = 0
    return out


class PresenceController:
    def __init__(self):
        self.cfg = load_config()
        self.session = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.timer = 0
        self.last_state = None
        self.screen_off_by_fpm = False
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        self.dir_file = Gio.File.new_for_path(str(RUN_DIR))
        self.monitor = self.dir_file.monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect('changed', self._fs_changed)
        self._read_state()
        self._read_power_mode_once()

    def _set_display(self, on: bool) -> None:
        self.session.call_sync(
            'org.gnome.Mutter.DisplayConfig',
            '/org/gnome/Mutter/DisplayConfig',
            'org.freedesktop.DBus.Properties',
            'Set',
            GLib.Variant('(ssv)', (
                'org.gnome.Mutter.DisplayConfig',
                'PowerSaveMode',
                GLib.Variant('i', 0 if on else 3),
            )),
            None, Gio.DBusCallFlags.NONE, 3000, None,
        )

    def _update_refresh_rate(self, mode: str) -> None:
        if not self.cfg.get('auto_refresh_rate', True):
            return
        target_mode = '2880x1800@60.000' if mode == 'battery' else '2880x1800@120.000+vrr'
        try:
            res = self.session.call_sync(
                'org.gnome.Mutter.DisplayConfig',
                '/org/gnome/Mutter/DisplayConfig',
                'org.gnome.Mutter.DisplayConfig',
                'GetCurrentState',
                None, None, Gio.DBusCallFlags.NONE, 2000, None
            )
            serial, monitors, logical_monitors, _ = res.unpack()
            if not logical_monitors:
                return
            lm = logical_monitors[0]
            x, y, scale, transform, primary, mons, _ = lm
            current_mode = mons[0][1]
            if current_mode == target_mode:
                return

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
                    {}
                )),
                None, Gio.DBusCallFlags.NONE, 2000, None
            )
            try:
                (RUN_DIR / 'refresh.rate').write_text(target_mode)
            except Exception:
                pass
        except Exception:
            pass

    def _lock(self) -> None:
        subprocess.run(['/usr/bin/loginctl', 'lock-session'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _cancel_timer(self) -> None:
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def _away_fire(self) -> bool:
        self.timer = 0
        try:
            current = STATE_FILE.read_text().strip()
        except Exception:
            current = 'disabled'
        if current != 'absent':
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
            allowed = bool(self.cfg.get('wake_on_approach', True))
            only_ours = bool(self.cfg.get('wake_only_if_fpm_off', True))
            if allowed and (self.screen_off_by_fpm or not only_ours):
                try:
                    self._set_display(True)
                    self.screen_off_by_fpm = False
                except Exception:
                    pass
        elif state == 'absent':
            self._cancel_timer()
            confirm = float(self.cfg.get('away_confirm', 2.0))
            extra = int(self.cfg.get('away_delay', 0))
            total = max(0.0, confirm + extra)
            if total <= 0:
                self._away_fire()
            else:
                self.timer = GLib.timeout_add(max(1, int(total * 1000)), self._away_fire)
        elif state in ('disabled', 'error'):
            self._cancel_timer()

    def _read_state(self) -> None:
        try:
            state = STATE_FILE.read_text().strip()
        except Exception:
            state = 'disabled'
        self._handle(state)

    def _read_power_mode_once(self) -> bool:
        mode = 'ac'
        try:
            p = RUN_DIR / 'power.mode'
            if p.exists():
                mode = p.read_text().strip()
            else:
                mode = 'battery' if on_battery_from_sysfs() else 'ac'
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
