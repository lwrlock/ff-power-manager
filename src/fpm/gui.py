from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import time
from collections import deque
from copy import deepcopy

# Engage GTK4 OpenGL renderer unless overridden by the caller to cut CPU compositing load.
os.environ.setdefault("GSK_RENDERER", "gl")

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .core import (
    CONFIG_PATH,
    PRESETS,
    RUN_DIR,
    SENSOR_CONFIG_PATH,
    _run_helper,
    dgpu_zombie_report,
    load_config,
    load_sensor_config,
    save_and_apply_config,
    save_config,
    save_sensor_config,
    set_lenovo_feature,
    status_snapshot,
)
from .cosmic_ui import CosmicBackdrop, TelemetrySparklineChart
from .tools import create_diagnostics_bundle, hardware_setup_scan

USER_CFG = pathlib.Path.home() / '.config/ff-power-manager/presence.json'
SYSTEM_SENSOR = 'ff-presence-sensor.service'
USER_PRESENCE = 'ff-presence-session.service'
AUTOBOOST_SERVICE = 'ff-power-autoboost.service'
TELEMETRY_FILE = pathlib.Path('/run/ff-power-manager/sensor_telemetry.json')
HIST_FILE = pathlib.Path('/run/ff-power-manager/telemetry_history.json')
SLEEP_FILE = pathlib.Path('/var/lib/ff-power-manager/last_sleep.json')

DEFAULT_PRESENCE = {
    'enabled': True,
    'away_confirm': 5.0,
    'away_delay': 45,
    'wake_on_approach': True,
    'wake_only_if_fpm_off': False,
    'screen_off_on_away': True,
    'lock_on_away': False,
    'auto_refresh_rate': True,
    'promotion_120hz': True,
    'oled_screen_care': False,
    'oled_dim_inactive_sec': 0,
    'inhibit_on_media': True,
    'tof_gesture_mode': 'off',
}

COSMIC_CSS = b"""
window, window.background, AdwApplicationWindow {
    background-color: #070312;
    color: #f5f3ff;
}
headerbar, AdwHeaderBar {
    background: rgba(10, 6, 24, 0.80);
    border-bottom: 1px solid rgba(167, 139, 250, 0.18);
    color: #f5f3ff;
}
scrolledwindow, viewport, clamp {
    background: transparent;
}
.bento-card {
    background: rgba(15, 10, 34, 0.93);
    border: 1px solid rgba(167, 139, 250, 0.24);
    border-radius: 18px;
    padding: 16px 18px;
}
.bento-card-accent {
    background: rgba(24, 14, 52, 0.94);
    border: 1px solid rgba(192, 132, 252, 0.36);
    border-radius: 18px;
    padding: 16px 18px;
}
.hero-card {
    background: rgba(16, 11, 36, 0.94);
    border: 1px solid rgba(167, 139, 250, 0.26);
    border-radius: 16px;
    padding: 14px 16px;
}
.hero-label {
    font-size: 10.5px;
    font-weight: 700;
    color: #a78bfa;
    letter-spacing: 0.7px;
}
.hero-value {
    font-size: 24px;
    font-weight: 800;
    color: #e0f2fe;
}
.hero-value-warm {
    font-size: 24px;
    font-weight: 800;
    color: #f9a8d4;
}
.hero-value-green {
    font-size: 24px;
    font-weight: 800;
    color: #6ee7b7;
}
.hero-sub {
    font-size: 11.5px;
    color: #94a3b8;
}
.section-title {
    font-size: 14px;
    font-weight: 700;
    color: #f5f3ff;
}
.section-sub {
    font-size: 11.5px;
    color: #94a3b8;
}
.kv-key {
    font-size: 11.5px;
    color: #94a3b8;
}
.kv-val {
    font-size: 12.5px;
    font-weight: 600;
    color: #f1f5f9;
}
.ctrl-row {
    padding: 6px 0px;
    border-bottom: 1px solid rgba(167, 139, 250, 0.10);
}
.floating-dock {
    background: rgba(14, 9, 32, 0.95);
    border: 1px solid rgba(192, 132, 252, 0.38);
    border-radius: 9999px;
    padding: 6px 10px;
    margin-bottom: 12px;
}
.dock-tab {
    border-radius: 9999px;
    padding: 6px 13px;
    font-size: 12.5px;
    font-weight: 600;
    color: #cbd5e1;
    background: transparent;
}
.dock-tab:hover {
    background: rgba(139, 92, 246, 0.22);
    color: #ffffff;
}
.dock-tab:checked {
    background: linear-gradient(135deg, #7c3aed, #0284c7);
    color: #ffffff;
}
.dock-handle {
    background: rgba(192, 132, 252, 0.50);
    border-radius: 9999px;
    min-width: 56px;
    min-height: 4px;
    margin-bottom: 6px;
}
.badge-active {
    background-color: rgba(16, 185, 129, 0.22);
    color: #6ee7b7;
    border: 1px solid rgba(52, 211, 153, 0.35);
    border-radius: 9999px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 700;
}
.badge-standby {
    background-color: rgba(245, 158, 11, 0.22);
    color: #fcd34d;
    border: 1px solid rgba(251, 191, 36, 0.35);
    border-radius: 9999px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 700;
}
.badge-disabled {
    background-color: rgba(148, 163, 184, 0.16);
    color: #cbd5e1;
    border-radius: 9999px;
    padding: 3px 10px;
    font-size: 11px;
}
.pill-btn {
    border-radius: 9999px;
    padding: 6px 14px;
    font-weight: 600;
}
.profile-pill {
    border-radius: 9999px;
    padding: 6px 13px;
    font-weight: 600;
    background: rgba(139, 92, 246, 0.16);
    border: 1px solid rgba(167, 139, 250, 0.28);
}
.profile-pill:hover {
    background: rgba(139, 92, 246, 0.32);
}
"""


def _read_pkg_temp_c() -> int:
    for hdir in pathlib.Path('/sys/class/hwmon').glob('hwmon*'):
        try:
            name = (hdir / 'name').read_text().strip()
            if name in ('coretemp', 'k10temp', 'zenpower'):
                mc = int((hdir / 'temp1_input').read_text().strip())
                if 10000 < mc < 120000:
                    return mc // 1000
        except Exception:
            pass
    return 0


def load_user_presence() -> dict:
    out = dict(DEFAULT_PRESENCE)
    try:
        if USER_CFG.exists():
            data = json.loads(USER_CFG.read_text())
            if isinstance(data, dict):
                out.update({k: data[k] for k in DEFAULT_PRESENCE if k in data})
                return out
    except Exception:
        pass
    return out


def load_sensor_telemetry() -> dict | None:
    try:
        if TELEMETRY_FILE.exists():
            data = json.loads(TELEMETRY_FILE.read_text())
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return None


def is_active(unit: str, user: bool = False) -> bool:
    if not user:
        return os.path.lexists(f'/run/systemd/units/invocation:{unit}')
    return subprocess.run(
        ['/usr/bin/systemctl', '--user', 'is-active', '--quiet', unit],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0


class _CompatToolbarView(Gtk.Box):
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._top_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True, hexpand=True)
        self.append(self._top_box)
        self.append(self._content_box)

    def add_top_bar(self, widget):
        self._top_box.append(widget)

    def set_content(self, widget):
        widget.set_vexpand(True)
        widget.set_hexpand(True)
        self._content_box.append(widget)


ToolbarViewCls = getattr(Adw, 'ToolbarView', _CompatToolbarView)
APP_FLAGS = getattr(Gio.ApplicationFlags, 'DEFAULT_FLAGS', Gio.ApplicationFlags.FLAGS_NONE)


class PowerManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.ff.PowerManager', flags=APP_FLAGS)

    def do_activate(self):
        self._load_styles()
        win = self.props.active_window
        if not win:
            win = MainWindow(self)
        win.present()

    def _load_styles(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(COSMIC_CSS)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='FF Power Manager', default_width=1060, default_height=820)
        self.cfg = load_config()
        self.scfg = load_sensor_config()
        self.pcfg = load_user_presence()
        self.live_source = 0
        self.mode_controls = {}
        self._presence_syncing = False
        self._lenovo_syncing = False
        self._local_samples: deque = deque(maxlen=90)
        self._blame_busy = False
        self._refresh_busy = False
        self._last_doctor_at = 0.0
        self._dock_pinned = False
        self._dock_hide_id = 0
        self._dock_buttons = {}

        # 3-layer spatial cockpit: VRAM cosmic space + Bento content + Auto-hide bottom hover dock
        root_overlay = Gtk.Overlay()
        self.backdrop = CosmicBackdrop()
        root_overlay.set_child(self.backdrop)

        self.toast_overlay = Adw.ToastOverlay()
        root_overlay.add_overlay(self.toast_overlay)
        self.set_content(root_overlay)

        toolbar = ToolbarViewCls()
        self.toast_overlay.set_child(toolbar)

        self._header_title = Adw.WindowTitle(title='FF Power Manager', subtitle='Cosmic Telemetry Cockpit')
        header = Adw.HeaderBar(title_widget=self._header_title)

        tui_btn = Gtk.Button(icon_name='utilities-terminal-symbolic', tooltip_text='Open Terminal Dashboard (ff-tui)')
        tui_btn.add_css_class('flat')
        tui_btn.connect('clicked', lambda *_: self._launch_tui())
        header.pack_start(tui_btn)

        fx_btn = Gtk.ToggleButton(label='Space FX', active=True, tooltip_text='Toggle cosmic space background')
        fx_btn.add_css_class('flat')
        fx_btn.connect('toggled', lambda btn: self.backdrop.set_enabled(btn.get_active()))
        header.pack_start(fx_btn)

        refresh_btn = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Refresh Telemetry Now')
        refresh_btn.add_css_class('flat')
        refresh_btn.connect('clicked', lambda *_: self.refresh_status())
        header.pack_end(refresh_btn)

        about_btn = Gtk.Button(icon_name='help-about-symbolic', tooltip_text='About FF Power Manager')
        about_btn.add_css_class('flat')
        about_btn.connect('clicked', lambda *_: self._show_about())
        header.pack_end(about_btn)

        toolbar.add_top_bar(header)

        self.stack = Gtk.Stack(
            transition_type=Gtk.StackTransitionType.CROSSFADE,
            transition_duration=160,
            vexpand=True,
            hexpand=True,
        )
        toolbar.set_content(self.stack)

        pages = [
            ('overview', 'Overview', 'view-dashboard-symbolic', self._overview_page()),
            ('blame', 'Blame Profiler', 'system-search-symbolic', self._profiler_page()),
            ('profiles', 'Profiles', 'battery-good-symbolic', self._profiles_page()),
            ('display', 'Display & ToF', 'system-lock-screen-symbolic', self._presence_page()),
            ('diagnostics', 'Diagnostics', 'utilities-system-monitor-symbolic', self._diagnostics_page()),
        ]
        for pid, _lbl, _ico, widget in pages:
            self.stack.add_named(widget, pid)

        # Single collapsible auto-hide bottom hover dock (appears on bottom edge hover or Ctrl+M)
        dock_zone = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            valign=Gtk.Align.END,
            halign=Gtk.Align.FILL,
        )
        self._nav_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            transition_duration=200,
            reveal_child=True,
        )
        dock_pill = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, halign=Gtk.Align.CENTER)
        dock_pill.add_css_class('floating-dock')

        first_btn = None
        for pid, lbl, ico, _w in pages:
            btn = Gtk.ToggleButton()
            btn.add_css_class('dock-tab')
            if first_btn is not None:
                btn.set_group(first_btn)
            else:
                first_btn = btn
                btn.set_active(True)
            inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
            inner.append(Gtk.Image.new_from_icon_name(ico))
            inner.append(Gtk.Label(label=lbl))
            btn.set_child(inner)
            btn.connect('toggled', self._on_dock_tab, pid)
            dock_pill.append(btn)
            self._dock_buttons[pid] = btn

        self._pin_btn = Gtk.ToggleButton(
            icon_name='view-pin-symbolic',
            active=False,
            tooltip_text='Pin Bottom Menu Open (or auto-hide on hover)',
        )
        self._pin_btn.add_css_class('dock-tab')
        self._pin_btn.connect('toggled', self._on_pin_dock)
        dock_pill.append(self._pin_btn)
        self._nav_revealer.set_child(dock_pill)

        # Subtle bottom hover handle visible when dock auto-hides
        self._handle_strip = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, halign=Gtk.Align.FILL)
        self._handle_strip.set_size_request(-1, 22)
        handle_bar = Gtk.Box(halign=Gtk.Align.CENTER, valign=Gtk.Align.END)
        handle_bar.add_css_class('dock-handle')
        self._handle_strip.append(handle_bar)

        dock_zone.append(self._nav_revealer)
        dock_zone.append(self._handle_strip)
        root_overlay.add_overlay(dock_zone)

        motion = Gtk.EventControllerMotion()
        motion.connect('enter', self._on_dock_hover_enter)
        motion.connect('leave', self._on_dock_hover_leave)
        dock_zone.add_controller(motion)

        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_ctrl)

        # Show dock briefly on launch, then auto-hide cleanly unless hovered/pinned
        self._schedule_dock_hide(2600)
        self.live_source = GLib.timeout_add_seconds(3, self._live_tick)
        self.refresh_status()
        self._run_blame_async()

    def _on_dock_tab(self, btn: Gtk.ToggleButton, page_id: str) -> None:
        if btn.get_active():
            self.stack.set_visible_child_name(page_id)

    def _on_pin_dock(self, btn: Gtk.ToggleButton) -> None:
        self._dock_pinned = btn.get_active()
        if self._dock_pinned:
            self._cancel_dock_hide()
            self._nav_revealer.set_reveal_child(True)
        else:
            self._schedule_dock_hide(700)

    def _cancel_dock_hide(self) -> None:
        if self._dock_hide_id:
            GLib.source_remove(self._dock_hide_id)
            self._dock_hide_id = 0

    def _schedule_dock_hide(self, delay_ms: int) -> None:
        self._cancel_dock_hide()
        if self._dock_pinned:
            return
        self._dock_hide_id = GLib.timeout_add(delay_ms, self._hide_dock_cb)

    def _hide_dock_cb(self) -> bool:
        self._dock_hide_id = 0
        if not self._dock_pinned:
            self._nav_revealer.set_reveal_child(False)
        return GLib.SOURCE_REMOVE

    def _on_dock_hover_enter(self, *_args) -> None:
        self._cancel_dock_hide()
        self._nav_revealer.set_reveal_child(True)

    def _on_dock_hover_leave(self, *_args) -> None:
        self._schedule_dock_hide(550)

    def _on_key_pressed(self, _ctrl, keyval, _keycode, state) -> bool:
        if (state & Gdk.ModifierType.CONTROL_MASK) and keyval in (Gdk.KEY_m, Gdk.KEY_M):
            self._pin_btn.set_active(not self._pin_btn.get_active())
            return True
        return False

    def toast(self, text: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=text, timeout=3))

    def _wrap_scroll(self, child: Gtk.Widget) -> Gtk.ScrolledWindow:
        sw = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.get_vadjustment().connect('value-changed', lambda *_: self.backdrop.notify_scroll())
        clamp = Adw.Clamp(maximum_size=1100, margin_top=14, margin_bottom=44, margin_start=18, margin_end=18)
        clamp.set_child(child)
        sw.set_child(clamp)
        return sw

    def _card(self, title: str = '', subtitle: str = '', accent: bool = False) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class('bento-card-accent' if accent else 'bento-card')
        if title:
            hdr = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            t = Gtk.Label(label=title, xalign=0.0)
            t.add_css_class('section-title')
            hdr.append(t)
            if subtitle:
                s = Gtk.Label(label=subtitle, xalign=0.0, wrap=True)
                s.add_css_class('section-sub')
                hdr.append(s)
            box.append(hdr)
        return box

    def _kv_row(self, key: str, val: str = '—') -> tuple[Gtk.Box, Gtk.Label]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.add_css_class('ctrl-row')
        kl = Gtk.Label(label=key, xalign=0.0, hexpand=True)
        kl.add_css_class('kv-key')
        vl = Gtk.Label(label=val, xalign=1.0, ellipsize=3)
        vl.add_css_class('kv-val')
        row.append(kl)
        row.append(vl)
        return row, vl

    def _switch_ctrl(self, title: str, subtitle: str = '', active: bool = False, callback=None) -> tuple[Gtk.Box, Gtk.Switch]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class('ctrl-row')
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        tl = Gtk.Label(label=title, xalign=0.0, wrap=True)
        tl.add_css_class('kv-val')
        txt.append(tl)
        if subtitle:
            sl = Gtk.Label(label=subtitle, xalign=0.0, wrap=True)
            sl.add_css_class('section-sub')
            txt.append(sl)
        sw = Gtk.Switch(valign=Gtk.Align.CENTER, active=bool(active))
        if callback:
            sw.connect('notify::active', callback)
        row.append(txt)
        row.append(sw)
        return row, sw

    def _combo_ctrl(self, title: str, values: list[str], current: str, subtitle: str = '') -> tuple[Gtk.Box, Gtk.DropDown]:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.add_css_class('ctrl-row')
        txt = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        tl = Gtk.Label(label=title, xalign=0.0)
        tl.add_css_class('kv-val')
        txt.append(tl)
        if subtitle:
            sl = Gtk.Label(label=subtitle, xalign=0.0, wrap=True)
            sl.add_css_class('section-sub')
            txt.append(sl)
        dd = Gtk.DropDown.new_from_strings(values)
        dd.set_valign(Gtk.Align.CENTER)
        dd._values = values
        dd.set_selected(values.index(current) if current in values else 0)
        row.append(txt)
        row.append(dd)
        return row, dd

    def _hero_card(self, label_txt: str, value_txt: str, sub_txt: str, val_cls: str = 'hero-value') -> tuple[Gtk.Box, Gtk.Label, Gtk.Label]:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        box.add_css_class('hero-card')
        lbl = Gtk.Label(label=label_txt, xalign=0.0)
        lbl.add_css_class('hero-label')
        val = Gtk.Label(label=value_txt, xalign=0.0)
        val.add_css_class(val_cls)
        sub = Gtk.Label(label=sub_txt, xalign=0.0, ellipsize=3)
        sub.add_css_class('hero-sub')
        box.append(lbl)
        box.append(val)
        box.append(sub)
        return box, val, sub

    def _launch_tui(self) -> None:
        for cmd in (
            ['gnome-terminal', '--', '/usr/local/bin/ff-tui'],
            ['ptyxis', '-e', '/usr/local/bin/ff-tui'],
            ['blackbox-terminal', '-e', '/usr/local/bin/ff-tui'],
            ['kgx', '-e', '/usr/local/bin/ff-tui'],
            ['x-terminal-emulator', '-e', '/usr/local/bin/ff-tui'],
        ):
            try:
                subprocess.Popen(cmd)
                self.toast('Terminal Dashboard (ff-tui) launched.')
                return
            except (FileNotFoundError, OSError):
                continue
        self.toast('Run "ff-tui" in your terminal.')

    def _show_about(self) -> None:
        if hasattr(Adw, 'AboutDialog'):
            dialog = Adw.AboutDialog(
                application_name='FF Power Manager',
                application_icon='ff-power-manager',
                developer_name='Furkan (@lwrlock)',
                version='2.3.0',
                website='https://lwrlock.github.io/ff-power-manager/',
                issue_url='https://github.com/lwrlock/ff-power-manager/issues',
                license_type=Gtk.License.MIT_X11,
                comments=(
                    "Universal Linux power, thermal, Adaptive Refresh, wakeup blame, "
                    "and s2idle residency telemetry suite.\n\n"
                    "Built by Furkan (@lwrlock) with Google DeepMind Antigravity."
                ),
            )
            dialog.present(self)
        else:
            dialog = Gtk.AboutDialog(
                transient_for=self,
                modal=True,
                program_name='FF Power Manager',
                logo_icon_name='ff-power-manager',
                authors=['Furkan (@lwrlock)'],
                version='2.3.0',
                website='https://lwrlock.github.io/ff-power-manager/',
                license_type=Gtk.License.MIT_X11,
                comments='Universal Linux power, adaptive refresh & hardware residency suite.',
            )
            dialog.present()

    def _overview_page(self) -> Gtk.Widget:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        # Row 1: 4 Hero Cards
        hero_grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True, hexpand=True)
        c1, self.hero_watts, self.hero_watts_sub = self._hero_card('POWER DRAW', '-- W', 'Sampling...', 'hero-value')
        c2, self.hero_temp, self.hero_temp_sub = self._hero_card('PACKAGE TEMP', '--°C', 'EPP: —', 'hero-value-warm')
        c3, self.hero_bat, self.hero_bat_sub = self._hero_card('BATTERY HEALTH', '--%', 'Cycles: —', 'hero-value-green')
        c4, self.hero_sleep, self.hero_sleep_sub = self._hero_card('LAST SUSPEND', 'Standby Ready', 'ff-sleep-guard active', 'hero-value')
        hero_grid.attach(c1, 0, 0, 1, 1)
        hero_grid.attach(c2, 1, 0, 1, 1)
        hero_grid.attach(c3, 2, 0, 1, 1)
        hero_grid.attach(c4, 3, 0, 1, 1)
        root.append(hero_grid)

        # Row 2: 2-Column Asymmetric Bento (Chart & Quick Profiles | ToF Radar & Hardware Specs)
        split = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True, hexpand=True)

        left_card = self._card('Live Power & Thermal Telemetry', 'Cyan: System Watts • Dashed Pink: CPU Package °C', accent=True)
        self.chart = TelemetrySparklineChart()
        left_card.append(self.chart)

        prof_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=6)
        prof_lbl = Gtk.Label(label='Profile:', xalign=0.0, hexpand=True)
        prof_lbl.add_css_class('kv-key')
        prof_bar.append(prof_lbl)
        for label, target in [
            ('Auto Balanced', 'auto'),
            ('Max Battery', 'max_battery'),
            ('Cool & Quiet', 'cool_quiet'),
            ('Extreme', 'extreme_performance'),
        ]:
            b = Gtk.Button(label=label)
            b.add_css_class('profile-pill')
            b.connect('clicked', self._quick_apply_profile, target)
            prof_bar.append(b)
        left_card.append(prof_bar)

        right_card = self._card('ST VL53L1 ToF Radar & Hardware State', 'Direct kernel sysfs + Intel ISH presence telemetry')
        radar_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.tof_status_lbl = Gtk.Label(label='Detecting sensor...', xalign=0.0, hexpand=True)
        self.tof_status_lbl.add_css_class('kv-val')
        self.tof_badge = Gtk.Label(label='STANDBY')
        self.tof_badge.add_css_class('badge-standby')
        radar_top.append(self.tof_status_lbl)
        radar_top.append(self.tof_badge)
        right_card.append(radar_top)

        self.tof_bar = Gtk.ProgressBar()
        self.tof_bar.set_fraction(0.5)
        right_card.append(self.tof_bar)

        self.tof_meta_lbl = Gtk.Label(label='Waiting for packets...', xalign=0.0)
        self.tof_meta_lbl.add_css_class('section-sub')
        right_card.append(self.tof_meta_lbl)

        self.rows = {}
        for key, k_label in [
            ('mode', 'Power Source'),
            ('charger_pd', 'USB-C PD / Charger'),
            ('cpu_topology', 'CPU Topology'),
            ('refresh_rate', 'Display Refresh'),
            ('gpu_perf', 'GPU Clock'),
            ('dgpu_state', 'Discrete GPU (Zombies)'),
            ('pcie_aspm', 'PCIe ASPM'),
            ('turbo', 'Turbo Boost'),
        ]:
            r, vl = self._kv_row(k_label, '—')
            self.rows[key] = vl
            right_card.append(r)

        split.attach(left_card, 0, 0, 3, 1)
        split.attach(right_card, 3, 0, 2, 1)
        root.append(split)

        # Row 3: Bottom 2-Card Strip (Kernel & I/O Stack | Battery Conservation & OEM)
        bot_grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True, hexpand=True)

        sys_card = self._card('Kernel, Media & Network Tunings')
        for key, k_label in [
            ('gnome_profile', 'Desktop Power Profile'),
            ('vaapi', 'Video Acceleration (VA-API)'),
            ('net_opt', 'TCP Congestion Control'),
            ('zram', 'Compressed Swap (ZRAM)'),
        ]:
            r, vl = self._kv_row(k_label, '—')
            self.rows[key] = vl
            sys_card.append(r)

        oem_card = self._card('Charge Protection & Hardware Switches')
        r_cm, self.lenovo_cm_sw = self._switch_ctrl(
            '80% Battery Conservation', 'Stops charging at 80% on AC', False,
            lambda sw, _: self._toggle_lenovo('conservation_mode', sw.get_active()),
        )
        r_fn, self.lenovo_fn_sw = self._switch_ctrl(
            'Fn-Lock Keys', 'Primary media/hotkey row', False,
            lambda sw, _: self._toggle_lenovo('fn_lock', sw.get_active()),
        )
        r_usb, self.lenovo_usb_sw = self._switch_ctrl(
            'Always-On USB Charging', 'Charge devices while suspended', False,
            lambda sw, _: self._toggle_lenovo('usb_charging', sw.get_active()),
        )
        oem_card.append(r_cm)
        oem_card.append(r_fn)
        oem_card.append(r_usb)

        bot_grid.attach(sys_card, 0, 0, 1, 1)
        bot_grid.attach(oem_card, 1, 0, 1, 1)
        root.append(bot_grid)

        return self._wrap_scroll(root)

    def _profiler_page(self) -> Gtk.Widget:
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)

        top_card = self._card('Energy & C-State Wakeup Blame Profiler', '250ms native C sampler over /proc/[pid]/stat, context switches & PCI/USB PM.', accent=True)
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        info = Gtk.Label(label='Identifies wakeups preventing deep C-states and devices stuck active.', xalign=0.0, hexpand=True)
        info.add_css_class('section-sub')
        sample_btn = Gtk.Button(label='Sample Now (250ms)')
        sample_btn.add_css_class('suggested-action')
        sample_btn.add_css_class('pill-btn')
        sample_btn.connect('clicked', lambda *_: self._run_blame_async())
        bar.append(info)
        bar.append(sample_btn)
        top_card.append(bar)
        root.append(top_card)

        split = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True, hexpand=True)

        proc_card = self._card('Top Process Offenders')
        self.blame_proc_rows = []
        for i in range(6):
            row_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            row_box.add_css_class('ctrl-row')
            top_l = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title_l = Gtk.Label(label=f'#{i + 1} Sampling...', xalign=0.0, hexpand=True)
            title_l.add_css_class('kv-val')
            meta_l = Gtk.Label(label='0.0% • 0/s', xalign=1.0)
            meta_l.add_css_class('kv-key')
            top_l.append(title_l)
            top_l.append(meta_l)
            pbar = Gtk.ProgressBar()
            pbar.set_fraction(0.0)
            row_box.append(top_l)
            row_box.append(pbar)
            proc_card.append(row_box)
            self.blame_proc_rows.append((title_l, meta_l, pbar))

        hw_card = self._card('Active Bus Devices & dGPU Watch')
        r_dgpu, self.blame_dgpu_lbl = self._kv_row('Discrete GPU (D0)', 'Scanning...')
        r_pci, self.blame_pci_lbl = self._kv_row('PCI Devices', 'Scanning...')
        r_usb, self.blame_usb_lbl = self._kv_row('USB Peripherals', 'Scanning...')
        self.blame_dgpu_list = Gtk.Label(label='—', xalign=0.0, wrap=True)
        self.blame_dgpu_list.add_css_class('section-sub')
        self.blame_pci_list = Gtk.Label(label='—', xalign=0.0, wrap=True)
        self.blame_pci_list.add_css_class('section-sub')
        self.blame_usb_list = Gtk.Label(label='—', xalign=0.0, wrap=True)
        self.blame_usb_list.add_css_class('section-sub')
        hw_card.append(r_dgpu)
        hw_card.append(self.blame_dgpu_list)
        hw_card.append(r_pci)
        hw_card.append(self.blame_pci_list)
        hw_card.append(r_usb)
        hw_card.append(self.blame_usb_list)

        split.attach(proc_card, 0, 0, 1, 1)
        split.attach(hw_card, 1, 0, 1, 1)
        root.append(split)

        return self._wrap_scroll(root)

    def _build_mode_column(self, mode: str) -> Gtk.Box:
        is_bat = (mode == 'battery')
        card = self._card(
            'Battery Mode Rules' if is_bat else 'AC Power Rules',
            'Side-by-side policy editor applied by udev & helper',
            accent=(not is_bat),
        )

        pbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        names = [('Recommended', 'recommended')] + (
            [('Max Battery', 'maximum_battery'), ('Responsive', 'responsive')] if is_bat
            else [('Performance', 'performance'), ('Cool & Quiet', 'cool_quiet')]
        )
        for txt, pname in names:
            pb = Gtk.Button(label=txt)
            pb.add_css_class('profile-pill')
            pb.connect('clicked', self._apply_preset, mode, pname)
            pbox.append(pb)
        card.append(pbox)

        s = self.cfg[mode]
        controls = {}
        for key, title, opts in [
            ('gnome_profile', 'Desktop Profile', ['system', 'power-saver', 'balanced', 'performance']),
            ('epp', 'CPU EPP Bias', ['system', 'default', 'power', 'balance_power', 'balance_performance', 'performance']),
            ('pcie_aspm', 'PCIe ASPM', ['system', 'default', 'powersave', 'powersupersave', 'performance']),
            ('nvme_runtime_pm', 'NVMe PM', ['system', 'auto', 'on']),
            ('gpu_runtime_pm', 'GPU PM', ['system', 'auto', 'on']),
            ('usb_autosuspend', 'USB Suspend', ['system', 'auto']),
            ('audio_powersave', 'Audio Save', ['system', 'on', 'off']),
            ('hwp_dynamic_boost', 'HWP Boost', ['system', 'on', 'off']),
        ]:
            row, dd = self._combo_ctrl(title, opts, str(s.get(key, 'system')))
            controls[key] = dd
            card.append(row)

        for key, title in [('turbo', 'CPU Turbo Boost'), ('wifi_power_save', 'Wi-Fi Power Save')]:
            row, sw = self._switch_ctrl(title, '', bool(s.get(key, True)))
            controls[key] = sw
            card.append(row)

        if not is_bat:
            ab_row, _ab_sw = self._switch_ctrl(
                'Auto Dynamic Boost Service',
                'Auto-boosts compilers/games, records chart telemetry & caps >=90°C',
                is_active(AUTOBOOST_SERVICE),
                self._toggle_autoboost,
            )
            card.append(ab_row)

        save_btn = Gtk.Button(label=f"Save & Apply {'Battery' if is_bat else 'AC'} Rules", margin_top=6)
        save_btn.add_css_class('suggested-action')
        save_btn.add_css_class('pill-btn')
        save_btn.connect('clicked', self._save_mode, mode)
        card.append(save_btn)

        self.mode_controls[mode] = controls
        return card

    def _profiles_page(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True, hexpand=True)
        grid.attach(self._build_mode_column('battery'), 0, 0, 1, 1)
        grid.attach(self._build_mode_column('ac'), 1, 0, 1, 1)
        return self._wrap_scroll(grid)

    def _presence_page(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True, hexpand=True)

        left = self._card('Adaptive Refresh & Screen Care', 'Multi-DE 60↔Max Hz (Mutter / Hyprland / Plasma)', accent=True)
        r_pr, self.promotion_sw = self._switch_ctrl(
            'Battery-Only Adaptive Refresh (60 ↔ Max Hz)',
            'Steps to 60 Hz after 8s idle on battery; wakes at 0ms on input.',
            bool(self.pcfg.get('promotion_120hz', True)),
        )
        r_dyn, self.refresh_sw = self._switch_ctrl(
            'Dynamic Refresh Switching',
            'Auto-negotiate modes via active Wayland compositor.',
            bool(self.pcfg.get('auto_refresh_rate', True)),
        )
        r_oled, self.oled_care_sw = self._switch_ctrl(
            'Panel Inactivity Dim & DPMS Off',
            'Dims panel on idle and cuts pixel draw when absent.',
            bool(self.pcfg.get('oled_screen_care', True)),
        )
        left.append(r_pr)
        left.append(r_dyn)
        left.append(r_oled)

        dim_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        dim_row.add_css_class('ctrl-row')
        dl = Gtk.Label(label='Inactivity Dimming Delay (s)', xalign=0.0, hexpand=True)
        dl.add_css_class('kv-val')
        self.oled_dim_spin = Gtk.SpinButton.new_with_range(15.0, 180.0, 5.0)
        self.oled_dim_spin.set_value(float(self.pcfg.get('oled_dim_inactive_sec', 45)))
        dim_row.append(dl)
        dim_row.append(self.oled_dim_spin)
        left.append(dim_row)

        right = self._card('ST VL53L1 ToF Human Presence Tuning', 'Hardware HID infrared proximity sensor')
        r_srv, self.presence_service_sw = self._switch_ctrl(
            'ToF Presence Sensor Daemon',
            'Enables real-time approach wake & away blanking.',
            bool(self.pcfg.get('enabled', True)) and is_active(SYSTEM_SENSOR),
            self._presence_toggle,
        )
        right.append(r_srv)

        for lbl_txt, attr_name, lo, hi, val in [
            ('Sensor Silence Floor (s)', 'silence_spin', 5.0, 90.0, float(self.scfg.get('silence_timeout', 15.0))),
            ('Approach Confirm Packets', 'confirm_reports_spin', 1.0, 5.0, float(self.scfg.get('present_confirm_reports', 1))),
            ('Departure Grace Delay (s)', 'away_delay_spin', 3.0, 120.0, float(self.pcfg.get('away_delay', 20))),
        ]:
            rbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            rbox.add_css_class('ctrl-row')
            rl = Gtk.Label(label=lbl_txt, xalign=0.0, hexpand=True)
            rl.add_css_class('kv-val')
            sp = Gtk.SpinButton.new_with_range(lo, hi, 1.0)
            sp.set_value(val)
            setattr(self, attr_name, sp)
            rbox.append(rl)
            rbox.append(sp)
            right.append(rbox)

        self.presence_switches = {}
        for key, title, defval in [
            ('wake_on_approach', 'Instant Wake on Approach', True),
            ('screen_off_on_away', 'Turn Screen Off on Departure', True),
            ('inhibit_on_media', 'Inhibit During Media / Video Playback', True),
            ('lock_on_away', 'Lock Session on Departure', False),
        ]:
            rsw, sw = self._switch_ctrl(title, '', bool(self.pcfg.get(key, defval)))
            self.presence_switches[key] = sw
            right.append(rsw)

        gesture_row, self.gesture_combo = self._combo_ctrl(
            'ToF Wave Gesture (<=18cm)',
            ['off', 'media_pause', 'privacy_dim', 'lock_screen'],
            str(self.pcfg.get('tof_gesture_mode', 'off')),
        )
        right.append(gesture_row)

        save_btn = Gtk.Button(label='Save & Apply Display + Presence Config', margin_top=6)
        save_btn.add_css_class('suggested-action')
        save_btn.add_css_class('pill-btn')
        save_btn.connect('clicked', self._save_presence)
        right.append(save_btn)

        grid.attach(left, 0, 0, 1, 1)
        grid.attach(right, 1, 0, 1, 1)
        return self._wrap_scroll(grid)

    def _diagnostics_page(self) -> Gtk.Widget:
        grid = Gtk.Grid(column_spacing=14, row_spacing=14, column_homogeneous=True, hexpand=True)

        svc_card = self._card('Background Services & Defaults')
        self.diag_rows = []
        for title, unit, user in [
            ('Power Apply Engine', 'ff-power-apply.service', False),
            ('ToF Sensor Daemon (C/ASM)', SYSTEM_SENSOR, False),
            ('Session Presence & ARR', USER_PRESENCE, True),
            ('Auto Dynamic Boost & Graph', AUTOBOOST_SERVICE, False),
        ]:
            row, vl = self._kv_row(title, 'Checking...')
            row._unit = unit
            row._user = user
            row._val_lbl = vl
            svc_card.append(row)
            self.diag_rows.append(row)

        reset_btn = Gtk.Button(label='Reset All Settings to Recommended Defaults', margin_top=10)
        reset_btn.add_css_class('destructive-action')
        reset_btn.add_css_class('pill-btn')
        reset_btn.connect('clicked', self._safe_reset)
        svc_card.append(reset_btn)

        setup_btn = Gtk.Button(label='Run Hardware Setup Wizard (ffctl setup --apply)', margin_top=6)
        setup_btn.add_css_class('profile-pill')
        setup_btn.connect('clicked', self._run_setup_wizard)
        svc_card.append(setup_btn)

        audit_card = self._card('Kernel & Power Residency Audit (ffctl doctor)', 'Hardware verification under < 2ms native C probe', accent=True)
        self.audit_rows = {}
        for key, label in [
            ('sleep', 'Suspend & s2idle Guard'),
            ('sleep_report', 'Last Suspend Energy Report'),
            ('cpu_driver', 'CPU P-State & EPP'),
            ('pci_pm', 'PCI Runtime PM & ASPM'),
            ('conflicts', 'Daemon Conflict Check'),
        ]:
            r, vl = self._kv_row(label, 'Inspecting...')
            self.audit_rows[key] = vl
            audit_card.append(r)

        btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=8)
        audit_btn = Gtk.Button(label='Run Hardware Audit Now', hexpand=True)
        audit_btn.add_css_class('suggested-action')
        audit_btn.add_css_class('pill-btn')
        audit_btn.connect('clicked', lambda *_: (self._refresh_doctor_audit(), self.toast('Hardware residency audit refreshed.')))
        bundle_btn = Gtk.Button(label='Export Diagnostics Bundle (.tar.gz)', hexpand=True)
        bundle_btn.add_css_class('profile-pill')
        bundle_btn.connect('clicked', self._export_bundle)
        btn_row.append(audit_btn)
        btn_row.append(bundle_btn)
        audit_card.append(btn_row)

        grid.attach(svc_card, 0, 0, 1, 1)
        grid.attach(audit_card, 1, 0, 1, 1)
        return self._wrap_scroll(grid)

    def _live_tick(self) -> bool:
        self.refresh_status()
        return GLib.SOURCE_CONTINUE

    def _quick_apply_profile(self, _btn, target: str) -> None:
        ffctl_bin = '/usr/local/bin/ffctl' if os.path.exists('/usr/local/bin/ffctl') else './ffctl'
        cmd = [ffctl_bin, 'apply'] if target == 'auto' else [ffctl_bin, 'apply', target]

        def _worker():
            rc = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
            def _done():
                self.refresh_status()
                self.toast(f"✓ Applied '{target}' profile." if rc == 0 else f"Apply exited with code {rc}.")
                return GLib.SOURCE_REMOVE
            GLib.idle_add(_done)

        threading.Thread(target=_worker, daemon=True).start()

    def _run_blame_async(self) -> None:
        if self._blame_busy:
            return
        self._blame_busy = True
        ffctl_bin = '/usr/local/bin/ffctl' if os.path.exists('/usr/local/bin/ffctl') else './ffctl'

        def _worker():
            data = None
            dgpu = None
            try:
                out = subprocess.check_output([ffctl_bin, 'blame', '--json'], text=True, stderr=subprocess.DEVNULL, timeout=3.0)
                data = json.loads(out)
            except Exception:
                data = None
            try:
                dgpu = dgpu_zombie_report()
            except Exception:
                dgpu = None

            def _apply_ui():
                self._blame_busy = False
                if not hasattr(self, 'blame_proc_rows'):
                    return GLib.SOURCE_REMOVE
                if dgpu is not None and hasattr(self, 'blame_dgpu_lbl'):
                    devs = dgpu.get('dgpus', [])
                    awake = dgpu.get('awake_count', 0)
                    blockers = dgpu.get('blockers', [])
                    if not devs:
                        self.blame_dgpu_lbl.set_label('Integrated GPU Only')
                        self.blame_dgpu_list.set_label('No secondary discrete GPU detected')
                    elif awake == 0:
                        self.blame_dgpu_lbl.set_label(f"{len(devs)} dGPU Suspended (D3cold)")
                        self.blame_dgpu_list.set_label('Discrete GPU asleep — 0W zombie draw')
                    else:
                        self.blame_dgpu_lbl.set_label(f"{awake} dGPU AWAKE (D0!)")
                        if blockers:
                            self.blame_dgpu_list.set_label(', '.join(f"{b['name']} (PID {b['pid']})" for b in blockers[:5]))
                        else:
                            self.blame_dgpu_list.set_label(f"Slot {', '.join(g['slot'] for g in devs if g.get('awake'))} active")
                if not data:
                    self.blame_proc_rows[0][0].set_label('Blame profiler unavailable')
                    return GLib.SOURCE_REMOVE

                procs = data.get('processes', [])
                for idx, (tl, ml, pb) in enumerate(self.blame_proc_rows):
                    if idx < len(procs):
                        pr = procs[idx]
                        cpu = float(pr.get('cpu_pct', 0.0) or 0.0)
                        csw = float(pr.get('wakeups_per_sec', 0.0) or 0.0)
                        tl.set_label(f"#{idx + 1}  {pr.get('name', '?')}  (PID {pr.get('pid', 0)})")
                        ml.set_label(f"{cpu:.1f}% CPU  •  {csw:.0f}/s wakeups")
                        pb.set_fraction(max(0.02, min(1.0, (cpu * 0.7 + min(csw / 20.0, 30.0)) / 100.0)))
                    else:
                        tl.set_label(f'#{idx + 1}  Idle')
                        ml.set_label('0.0%')
                        pb.set_fraction(0.0)

                pci = data.get('active_pci', [])
                usb = data.get('active_usb', [])
                self.blame_pci_lbl.set_label(f"{len(pci)} active")
                self.blame_usb_lbl.set_label(f"{len(usb)} active")
                self.blame_pci_list.set_label(', '.join(f"{d.get('slot', '')} [{d.get('driver', '').split()[0]}]" for d in pci[:6]) or 'All suspended')
                self.blame_usb_list.set_label(', '.join(f"{d.get('port', '')}: {d.get('product', '')}" for d in usb[:5]) or 'All autosuspended')
                return GLib.SOURCE_REMOVE

            GLib.idle_add(_apply_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def refresh_status(self) -> None:
        if self._refresh_busy:
            return
        self._refresh_busy = True
        want_doctor = (time.monotonic() - self._last_doctor_at) >= 12.0 or self._last_doctor_at == 0.0

        def _worker():
            s = status_snapshot()
            temp_c = _read_pkg_temp_c()
            tel = load_sensor_telemetry()

            sleep_data = None
            try:
                if SLEEP_FILE.exists():
                    sleep_data = json.loads(SLEEP_FILE.read_text(encoding='utf-8'))
            except Exception:
                pass

            samples = []
            try:
                if HIST_FILE.exists():
                    parsed = json.loads(HIST_FILE.read_text(encoding='utf-8'))
                    if isinstance(parsed, list) and len(parsed) >= 2:
                        samples = parsed
            except Exception:
                pass

            svc_states = [(row, is_active(row._unit, row._user)) for row in getattr(self, 'diag_rows', [])]

            doctor_data = None
            if want_doctor:
                ffctl_bin = '/usr/local/bin/ffctl' if os.path.exists('/usr/local/bin/ffctl') else './ffctl'
                try:
                    out = subprocess.check_output([ffctl_bin, 'doctor', '--json'], text=True, stderr=subprocess.DEVNULL, timeout=2.0)
                    doctor_data = json.loads(out)
                except Exception:
                    doctor_data = False

            def _apply_ui():
                self._refresh_busy = False
                watts_val = s.get('watts')
                if (watts_val is None or watts_val <= 0.1) and samples:
                    watts_val = samples[-1].get('watts')
                bat_pct = s.get('battery_percent')
                health = s.get('battery_health', {}) or {}
                mode_lbl = 'Battery' if s.get('mode') == 'battery' else 'AC Mains'

                self._header_title.set_subtitle(f"{mode_lbl} • {s.get('refresh_rate', 'Adaptive')} • EPP: {s.get('epp') or '—'}")
                self.hero_watts.set_label('-- W' if watts_val is None else f"{float(watts_val):.1f} W")
                self.hero_watts_sub.set_label(f"{mode_lbl} • {s.get('refresh_rate', 'Adaptive')}")
                self.hero_temp.set_label(f"{temp_c}°C" if temp_c > 0 else '—°C')
                self.hero_temp_sub.set_label(f"EPP: {s.get('epp') or '—'}")
                self.hero_bat.set_label(f"{bat_pct}%" if bat_pct is not None else '—%')
                self.hero_bat_sub.set_label(f"Health {health.get('health_pct', 100.0):.1f}% • {health.get('cycle_count', 0)} cycles")

                if sleep_data:
                    dur_m = int(sleep_data.get('duration_sec', 0)) // 60
                    self.hero_sleep.set_label(f"{sleep_data.get('avg_watts', 0.0):.2f} W")
                    self.hero_sleep_sub.set_label(f"{dur_m}m • {sleep_data.get('pct_per_hour', 0.0):.2f}%/hr")

                chart_samples = samples
                if not chart_samples:
                    self._local_samples.append({
                        'ts': int(time.time()),
                        'watts': float(watts_val) if watts_val is not None else 0.0,
                        'temp_c': int(temp_c),
                    })
                    chart_samples = list(self._local_samples)
                self.chart.set_samples(chart_samples)

                pd = s.get('charger_pd', {}) or {}
                dgpu = s.get('dgpu', {}) or {}
                dgpus = dgpu.get('dgpus', [])
                if not dgpus:
                    dgpu_txt = 'iGPU Only (Optimal)'
                elif dgpu.get('awake_count', 0) == 0:
                    dgpu_txt = f"{len(dgpus)} dGPU Asleep (D3cold)"
                else:
                    blks = dgpu.get('blockers', [])
                    blk_s = f" ({blks[0]['name']})" if blks else ''
                    dgpu_txt = f"{dgpu['awake_count']} AWAKE (D0){blk_s}"

                values = {
                    'mode': 'Battery (Discharging)' if s['mode'] == 'battery' else 'AC Power (Mains)',
                    'charger_pd': pd.get('label', '—'),
                    'cpu_topology': s.get('cpu_topology', 'Dynamic Online'),
                    'refresh_rate': s.get('refresh_rate', '—'),
                    'gnome_profile': s['gnome_profile'] or '—',
                    'turbo': 'Enabled' if s['turbo'] else ('Disabled' if s['turbo'] is not None else '—'),
                    'pcie_aspm': s.get('pcie_aspm', '—'),
                    'gpu_perf': s.get('gpu_perf', '—'),
                    'dgpu_state': dgpu_txt,
                    'vaapi': s.get('vaapi', '—'),
                    'net_opt': s.get('net_opt', '—'),
                    'zram': s.get('zram', '—'),
                }
                for key, value in values.items():
                    if key in self.rows:
                        self.rows[key].set_label(value)

                if tel:
                    st = tel.get('state', 'unknown')
                    dist_cm = tel.get('distance_cm', 0)
                    thresh_cm = tel.get('threshold_cm', 120)
                    pkts = tel.get('packet_count', 0)
                    sec_ago = tel.get('last_packet_sec_ago', 0.0)
                    if st == 'present':
                        self.tof_badge.set_label('AT DESK')
                        self.tof_badge.set_css_classes(['badge-active'])
                        self.tof_status_lbl.set_label('User Detected in Range')
                    elif st == 'absent':
                        self.tof_badge.set_label('AWAY')
                        self.tof_badge.set_css_classes(['badge-standby'])
                        self.tof_status_lbl.set_label('Away (> 1.2m Standby)')
                    else:
                        self.tof_badge.set_label('OFFLINE')
                        self.tof_badge.set_css_classes(['badge-disabled'])
                        self.tof_status_lbl.set_label('Sensor Offline')
                    self.tof_bar.set_fraction(min(1.0, max(0.0, dist_cm / thresh_cm)) if thresh_cm > 0 else 0.5)
                    self.tof_meta_lbl.set_label(f"{dist_cm} / {thresh_cm} cm  •  {pkts} packets ({sec_ago:.1f}s ago)")

                lenovo = s.get('lenovo', {})
                if lenovo:
                    self._lenovo_syncing = True
                    if lenovo.get('conservation_mode') is not None:
                        self.lenovo_cm_sw.set_active(bool(lenovo['conservation_mode']))
                    if lenovo.get('fn_lock') is not None:
                        self.lenovo_fn_sw.set_active(bool(lenovo['fn_lock']))
                    if lenovo.get('usb_charging') is not None:
                        self.lenovo_usb_sw.set_active(bool(lenovo['usb_charging']))
                    self._lenovo_syncing = False

                for row, active_flag in svc_states:
                    row._val_lbl.set_label('Running' if active_flag else 'Stopped')

                if doctor_data is not None:
                    self._last_doctor_at = time.monotonic()
                    self._apply_doctor_ui(doctor_data if isinstance(doctor_data, dict) else None, sleep_data)

                return GLib.SOURCE_REMOVE

            GLib.idle_add(_apply_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_doctor_ui(self, d: dict | None, sl: dict | None = None) -> None:
        if not d:
            for r in self.audit_rows.values():
                r.set_label('Unavailable')
            return
        guard = 'installed' if d.get('sleep_guard_hook') else 'missing'
        self.audit_rows['sleep'].set_label(f"{d.get('mem_sleep', '?')} • Guard: {guard} • {d.get('acpi_non_lid_wakeups_enabled', 0)} wakeups")
        if sl:
            self.audit_rows['sleep_report'].set_label(f"{sl.get('duration_sec', 0) // 60}m • {sl.get('avg_watts', 0.0):.2f} W ({sl.get('pct_per_hour', 0.0):.2f}%/hr)")
        else:
            self.audit_rows['sleep_report'].set_label('Awaiting next suspend')
        self.audit_rows['cpu_driver'].set_label(f"{d.get('scaling_driver', '—')} / {d.get('epp', '—')}")
        self.audit_rows['pci_pm'].set_label(f"{d.get('pci_devices_suspended', 0)}/{d.get('pci_devices_total', 0)} suspended ({d.get('pcie_aspm', '—')})")
        if d.get('conflict_tlp') or d.get('conflict_auto_cpufreq'):
            conf = 'tlp.service' if d.get('conflict_tlp') else 'auto-cpufreq.service'
            self.audit_rows['conflicts'].set_label(f"CONFLICT: {conf}")
        else:
            self.audit_rows['conflicts'].set_label('OK (No conflicts)')

    def _refresh_doctor_audit(self) -> None:
        self._last_doctor_at = 0.0
        self.refresh_status()

    def _toggle_lenovo(self, feat: str, active: bool) -> None:
        if self._lenovo_syncing:
            return
        val = '1' if active else '0'
        threading.Thread(target=lambda: (
            _run_helper(['set-lenovo', feat, val]) if (pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper').exists() and os.geteuid() != 0)
            else set_lenovo_feature(feat, val),
            GLib.idle_add(self.refresh_status),
        ), daemon=True).start()
        self.toast(f"✓ {feat.replace('_', ' ').title()} set to {'ON' if active else 'OFF'}.")

    def _toggle_autoboost(self, sw, _pspec) -> None:
        active = sw.get_active()
        subaction = 'enable-now' if active else 'disable-now'
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists() and os.geteuid() != 0:
            _run_helper(['autoboost-service', subaction])
        else:
            act = ['enable', '--now'] if active else ['disable', '--now']
            subprocess.run(['/usr/bin/systemctl', *act, AUTOBOOST_SERVICE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.refresh_status()
        self.toast(f"✓ Auto Dynamic Boost {'enabled' if active else 'disabled'}.")

    def _apply_preset(self, _btn, mode: str, name: str) -> None:
        preset = PRESETS.get(mode, {}).get(name)
        if not preset:
            return
        ctrls = self.mode_controls.get(mode, {})
        for k, v in preset.items():
            w = ctrls.get(k)
            if isinstance(w, Gtk.DropDown) and v in w._values:
                w.set_selected(w._values.index(v))
            elif isinstance(w, Gtk.Switch):
                w.set_active(bool(v))
        self.cfg[mode].update(preset)
        try:
            save_and_apply_config(self.cfg)
            self.refresh_status()
            self.toast(f'✓ Applied {mode} preset "{name}".')
        except Exception as exc:
            self.toast(f'Preset error: {exc}')

    def _save_mode(self, _btn, mode: str) -> None:
        ctrls = self.mode_controls.get(mode, {})
        new_sub = {}
        for k, w in ctrls.items():
            if isinstance(w, Gtk.DropDown):
                new_sub[k] = w._values[w.get_selected()]
            elif isinstance(w, Gtk.Switch):
                new_sub[k] = w.get_active()
        self.cfg[mode] = new_sub
        try:
            save_and_apply_config(self.cfg)
            self.refresh_status()
            self.toast(f"✓ {'Battery' if mode == 'battery' else 'AC'} rules saved & applied.")
        except Exception as e:
            self.toast(f'Save error: {e}')

    def _presence_toggle(self, sw, _pspec) -> None:
        if self._presence_syncing:
            return
        active = sw.get_active()
        self.pcfg['enabled'] = active
        try:
            USER_CFG.parent.mkdir(parents=True, exist_ok=True)
            USER_CFG.write_text(json.dumps(self.pcfg, indent=2) + '\n')
        except Exception:
            pass
        sys_action = 'enable-now' if active else 'disable-now'
        user_action = 'enable' if active else 'disable'
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists() and os.geteuid() != 0:
            _run_helper(['sensor-service', sys_action])
        else:
            act = ['enable', '--now'] if active else ['disable', '--now']
            subprocess.run(['/usr/bin/systemctl', *act, SYSTEM_SENSOR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['/usr/bin/systemctl', '--user', user_action, '--now', USER_PRESENCE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.refresh_status()

    def _save_presence(self, _btn) -> None:
        active = self.presence_service_sw.get_active()
        self.pcfg['enabled'] = active
        self.scfg['silence_timeout'] = self.silence_spin.get_value()
        self.scfg['present_confirm_reports'] = int(self.confirm_reports_spin.get_value())
        try:
            save_sensor_config(self.scfg)
        except Exception as exc:
            self.toast(f'Sensor save error: {exc}')
            return

        self.pcfg['away_delay'] = int(self.away_delay_spin.get_value())
        self.pcfg['auto_refresh_rate'] = self.refresh_sw.get_active()
        self.pcfg['promotion_120hz'] = self.promotion_sw.get_active()
        self.pcfg['oled_screen_care'] = self.oled_care_sw.get_active()
        self.pcfg['oled_dim_inactive_sec'] = int(self.oled_dim_spin.get_value())
        for k, sw in self.presence_switches.items():
            self.pcfg[k] = sw.get_active()
        if hasattr(self, 'gesture_combo'):
            self.pcfg['tof_gesture_mode'] = self.gesture_combo._values[self.gesture_combo.get_selected()]
        try:
            USER_CFG.parent.mkdir(parents=True, exist_ok=True)
            USER_CFG.write_text(json.dumps(self.pcfg, indent=2) + '\n')
            sys_action = 'enable-now' if active else 'disable-now'
            user_action = 'enable' if active else 'disable'
            helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
            if helper.exists() and os.geteuid() != 0:
                _run_helper(['sensor-service', sys_action])
                if active:
                    _run_helper(['sensor-service', 'restart'])
            else:
                act = ['enable', '--now'] if active else ['disable', '--now']
                subprocess.run(['/usr/bin/systemctl', *act, SYSTEM_SENSOR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if active:
                    subprocess.run(['/usr/bin/systemctl', 'restart', SYSTEM_SENSOR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            subprocess.run(['/usr/bin/systemctl', '--user', user_action, '--now', USER_PRESENCE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if active:
                subprocess.run(['/usr/bin/systemctl', '--user', 'restart', USER_PRESENCE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.refresh_status()
            self.toast('✓ Display & presence settings saved.')
        except Exception as e:
            self.toast(f'Error: {e}')

    def _safe_reset(self, _btn) -> None:
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists() and os.geteuid() != 0:
            _run_helper(['sensor-service', 'stop'])
        else:
            subprocess.run(['/usr/bin/systemctl', 'stop', SYSTEM_SENSOR], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(['/usr/bin/systemctl', '--user', 'stop', USER_PRESENCE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pcfg = deepcopy(DEFAULT_PRESENCE)
        try:
            USER_CFG.write_text(json.dumps(self.pcfg, indent=2) + '\n')
        except Exception:
            pass
        self.cfg['battery'] = deepcopy(PRESETS['battery']['recommended'])
        self.cfg['ac'] = deepcopy(PRESETS['ac']['recommended'])
        try:
            save_and_apply_config(self.cfg)
            self.refresh_status()
            self.toast('✓ Reset to recommended factory defaults.')
        except Exception as e:
            self.toast(f'Reset error: {e}')

    def _run_setup_wizard(self, _btn) -> None:
        def _worker():
            ffctl_bin = '/usr/local/bin/ffctl' if os.path.exists('/usr/local/bin/ffctl') else None
            msg = ''
            try:
                res = hardware_setup_scan(apply_recommended=True)
                if not res.get('applied') and ffctl_bin:
                    # Fallback via elevated apply if direct write lacked privileges
                    subprocess.run([ffctl_bin, 'apply'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                rec = res['recommendations']
                msg = f"✓ Setup complete: battery={rec['battery_preset']}, ac={rec['ac_preset']}"
            except Exception as exc:
                msg = f"Setup error: {exc}"
            GLib.idle_add(lambda: (self.refresh_status(), self.toast(msg), GLib.SOURCE_REMOVE)[-1])

        threading.Thread(target=_worker, daemon=True).start()

    def _export_bundle(self, _btn) -> None:
        def _worker():
            try:
                res = create_diagnostics_bundle()
                msg = f"✓ Saved bundle: {pathlib.Path(res['path']).name} ({res['size_bytes']} B)"
            except Exception as exc:
                msg = f"Bundle error: {exc}"
            GLib.idle_add(lambda: (self.toast(msg), GLib.SOURCE_REMOVE)[-1])

        threading.Thread(target=_worker, daemon=True).start()


def main():
    return PowerManagerApp().run(None)


if __name__ == '__main__':
    raise SystemExit(main())
