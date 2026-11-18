from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import time
from collections import deque
from copy import deepcopy

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
    load_config,
    load_sensor_config,
    save_and_apply_config,
    save_config,
    save_sensor_config,
    set_lenovo_feature,
    status_snapshot,
)
from .cosmic_ui import CosmicBackdrop, TelemetrySparklineChart

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
}

COSMIC_CSS = b"""
window, window.background, AdwApplicationWindow {
    background-color: #080412;
    color: #f5f3ff;
}
headerbar, AdwHeaderBar {
    background: rgba(12, 7, 26, 0.72);
    border-bottom: 1px solid rgba(167, 139, 250, 0.22);
    color: #f5f3ff;
}
viewswitcherbar, .bottom-bar {
    background: rgba(12, 7, 26, 0.78);
    border-top: 1px solid rgba(167, 139, 250, 0.22);
}
scrolledwindow, viewport, preferencespage, clamp {
    background: transparent;
}
list.boxed-list, .boxed-list {
    background-color: rgba(18, 11, 38, 0.72);
    border: 1px solid rgba(167, 139, 250, 0.24);
    border-radius: 16px;
}
list.boxed-list > row {
    background-color: transparent;
    border-bottom: 1px solid rgba(167, 139, 250, 0.10);
}
list.boxed-list > row:last-child {
    border-bottom: none;
}
.cosmic-card {
    background: rgba(20, 12, 42, 0.74);
    border: 1px solid rgba(167, 139, 250, 0.28);
    border-radius: 16px;
    padding: 14px 16px;
}
.cosmic-chart-box {
    background: rgba(14, 9, 32, 0.78);
    border: 1px solid rgba(139, 92, 246, 0.34);
    border-radius: 16px;
    padding: 10px 12px;
}
.hero-value {
    font-size: 23px;
    font-weight: 800;
    color: #e0f2fe;
}
.hero-label {
    font-size: 11px;
    font-weight: 600;
    color: #c4b5fd;
    letter-spacing: 0.4px;
}
.hero-sub {
    font-size: 11px;
    color: #94a3b8;
}
.card-hero {
    background: rgba(88, 28, 135, 0.32);
    border-radius: 14px;
    border: 1px solid rgba(192, 132, 252, 0.35);
    padding: 8px;
}
.badge-active {
    background-color: rgba(34, 197, 94, 0.22);
    color: #4ade80;
    border: 1px solid rgba(74, 222, 128, 0.35);
    border-radius: 9999px;
    padding: 3px 10px;
    font-weight: bold;
}
.badge-standby {
    background-color: rgba(245, 158, 11, 0.22);
    color: #fbbf24;
    border: 1px solid rgba(251, 191, 36, 0.35);
    border-radius: 9999px;
    padding: 3px 10px;
    font-weight: bold;
}
.badge-disabled {
    background-color: rgba(148, 163, 184, 0.16);
    color: #cbd5e1;
    border-radius: 9999px;
    padding: 3px 10px;
}
.pill-btn {
    border-radius: 9999px;
    padding: 6px 14px;
    font-weight: 600;
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
        self._bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.append(self._top_box)
        self.append(self._content_box)
        self.append(self._bottom_box)

    def add_top_bar(self, widget):
        self._top_box.append(widget)

    def set_content(self, widget):
        widget.set_vexpand(True)
        widget.set_hexpand(True)
        self._content_box.append(widget)

    def add_bottom_bar(self, widget):
        self._bottom_box.append(widget)


class _CompatSwitchRow(Adw.ActionRow):
    def __init__(self, title: str = '', subtitle: str = '', **kwargs):
        super().__init__(title=title, **kwargs)
        if subtitle:
            self.set_subtitle(subtitle)
        self._switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.add_suffix(self._switch)
        self.set_activatable_widget(self._switch)

    def get_active(self) -> bool:
        return self._switch.get_active()

    def set_active(self, active: bool) -> None:
        self._switch.set_active(bool(active))

    def connect(self, detailed_signal: str, handler, *args):
        if detailed_signal == 'notify::active':
            return self._switch.connect('notify::active', lambda _sw, pspec, *a: handler(self, pspec, *a), *args)
        return super().connect(detailed_signal, handler, *args)


ToolbarViewCls = getattr(Adw, 'ToolbarView', _CompatToolbarView)
SwitchRowCls = getattr(Adw, 'SwitchRow', _CompatSwitchRow)
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
        super().__init__(application=app, title='FF Power Manager', default_width=1020, default_height=840)
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

        # Layered desktop app layout: animated cosmic space canvas + translucent frosted glass UI
        root_overlay = Gtk.Overlay()
        self.backdrop = CosmicBackdrop()
        root_overlay.set_child(self.backdrop)

        self.toast_overlay = Adw.ToastOverlay()
        root_overlay.add_overlay(self.toast_overlay)
        self.set_content(root_overlay)

        toolbar = ToolbarViewCls()
        self.toast_overlay.set_child(toolbar)

        self.stack = Adw.ViewStack()
        win_title = Adw.WindowTitle(title='FF Power Manager', subtitle='Cosmic Control Center')
        header = Adw.HeaderBar(title_widget=win_title)

        self.menu_toggle_btn = Gtk.ToggleButton(
            icon_name='view-bottom-pane-symbolic',
            active=True,
            tooltip_text='Alt Menüyü Gizle / Göster (Ctrl+M)',
        )
        self.menu_toggle_btn.add_css_class('flat')
        header.pack_start(self.menu_toggle_btn)

        tui_btn = Gtk.Button(icon_name='utilities-terminal-symbolic', tooltip_text='Open Terminal Dashboard (ff-tui)')
        tui_btn.add_css_class('flat')
        tui_btn.connect('clicked', lambda *_: self._launch_tui())
        header.pack_start(tui_btn)

        fx_btn = Gtk.ToggleButton(label='Space FX', active=True, tooltip_text='Toggle cosmic space background')
        fx_btn.add_css_class('flat')
        fx_btn.connect('toggled', lambda btn: self.backdrop.set_enabled(btn.get_active()))
        header.pack_start(fx_btn)

        refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Refresh Hardware Telemetry')
        refresh.add_css_class('flat')
        refresh.connect('clicked', lambda *_: self.refresh_status())
        header.pack_end(refresh)

        about_btn = Gtk.Button(icon_name='help-about-symbolic', tooltip_text='About FF Power Manager')
        about_btn.add_css_class('flat')
        about_btn.connect('clicked', lambda *_: self._show_about())
        header.pack_end(about_btn)

        toolbar.add_top_bar(header)
        toolbar.set_content(self.stack)

        # Single collapsible bottom navigation bar (no duplicate top menu)
        self._nav_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
            transition_duration=200,
            reveal_child=True,
        )
        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.CENTER)
        nav_box.add_css_class('bottom-bar')
        nav_box.set_hexpand(True)
        switcher = Adw.ViewSwitcher(stack=self.stack, halign=Gtk.Align.CENTER)
        if hasattr(Adw, 'ViewSwitcherPolicy'):
            switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        nav_box.append(switcher)
        self._nav_revealer.set_child(nav_box)
        toolbar.add_bottom_bar(self._nav_revealer)

        self.menu_toggle_btn.connect('toggled', self._on_toggle_bottom_menu)
        key_ctrl = Gtk.EventControllerKey()
        key_ctrl.connect('key-pressed', self._on_key_pressed)
        self.add_controller(key_ctrl)

        for page_widget, name, title_str, icon_str in [
            (self._overview_page(), 'overview', 'Overview', 'view-dashboard-symbolic'),
            (self._profiler_page(), 'profiler', 'Blame', 'system-search-symbolic'),
            (self._mode_page('battery'), 'battery', 'Battery', 'battery-good-symbolic'),
            (self._mode_page('ac'), 'ac', 'AC Power', 'power-profile-performance-symbolic'),
            (self._presence_page(), 'presence', 'Display & Presence', 'system-lock-screen-symbolic'),
            (self._diagnostics_page(), 'diagnostics', 'Diagnostics', 'utilities-system-monitor-symbolic'),
        ]:
            if hasattr(self.stack, 'add_titled_with_icon'):
                self.stack.add_titled_with_icon(page_widget, name, title_str, icon_str)
            else:
                vp = self.stack.add_titled(page_widget, name, title_str)
                vp.set_icon_name(icon_str)

        self.live_source = GLib.timeout_add_seconds(3, self._live_tick)
        self.refresh_status()
        self._run_blame_async()

    def _on_toggle_bottom_menu(self, btn) -> None:
        self._nav_revealer.set_reveal_child(btn.get_active())

    def _on_key_pressed(self, _ctrl, keyval, _keycode, state) -> bool:
        ctrl_mask = Gdk.ModifierType.CONTROL_MASK
        if (state & ctrl_mask) and keyval in (Gdk.KEY_m, Gdk.KEY_M):
            self.menu_toggle_btn.set_active(not self.menu_toggle_btn.get_active())
            return True
        return False

    def toast(self, text: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=text, timeout=3))

    def _action_row(self, title: str, subtitle: str = '', icon: str = '') -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        if icon:
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
        return row

    def _hero_card(self, label_txt: str, value_txt: str, sub_txt: str) -> tuple[Gtk.Box, Gtk.Label, Gtk.Label]:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        box.add_css_class('cosmic-card')
        lbl = Gtk.Label(label=label_txt, xalign=0.0)
        lbl.add_css_class('hero-label')
        val = Gtk.Label(label=value_txt, xalign=0.0)
        val.add_css_class('hero-value')
        sub = Gtk.Label(label=sub_txt, xalign=0.0, ellipsize=3)
        sub.add_css_class('hero-sub')
        box.append(lbl)
        box.append(val)
        box.append(sub)
        return box, val, sub

    def _launch_tui(self) -> None:
        terminals = [
            ['gnome-terminal', '--', '/usr/local/bin/ff-tui'],
            ['ptyxis', '-e', '/usr/local/bin/ff-tui'],
            ['blackbox-terminal', '-e', '/usr/local/bin/ff-tui'],
            ['kgx', '-e', '/usr/local/bin/ff-tui'],
            ['x-terminal-emulator', '-e', '/usr/local/bin/ff-tui'],
        ]
        for cmd in terminals:
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
                version='2.2.0',
                website='https://lwrlock.github.io/ff-power-manager/',
                issue_url='https://github.com/lwrlock/ff-power-manager/issues',
                license_type=Gtk.License.MIT_X11,
                comments=(
                    "Universal Linux power management, dynamic CPU/GPU topology tuning, "
                    "battery-only adaptive refresh rate, wakeup blame profiler, s2idle drain telemetry, "
                    "and ST VL53L1 presence automation.\n\n"
                    "Built by Furkan (@lwrlock, 18-year-old CS/CE student) with AI-assisted engineering via Google DeepMind Antigravity."
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
                version='2.2.0',
                website='https://lwrlock.github.io/ff-power-manager/',
                license_type=Gtk.License.MIT_X11,
                comments="Universal Linux power, adaptive refresh & hardware residency suite.",
            )
            dialog.present()

    def _overview_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Overview', icon_name='view-dashboard-symbolic')

        # Cosmic Hero Telemetry Deck
        deck_grp = Adw.PreferencesGroup()
        page.add(deck_grp)

        hero_grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True, hexpand=True)
        c1, self.hero_watts, self.hero_watts_sub = self._hero_card('POWER DRAW', '-- W', 'Detecting...')
        c2, self.hero_temp, self.hero_temp_sub = self._hero_card('PACKAGE TEMP', '--°C', 'EPP: —')
        c3, self.hero_bat, self.hero_bat_sub = self._hero_card('BATTERY & HEALTH', '--%', 'Design: —')
        c4, self.hero_sleep, self.hero_sleep_sub = self._hero_card('LAST SUSPEND', 'No sample', 'ff-sleep-guard active')
        hero_grid.attach(c1, 0, 0, 1, 1)
        hero_grid.attach(c2, 1, 0, 1, 1)
        hero_grid.attach(c3, 2, 0, 1, 1)
        hero_grid.attach(c4, 3, 0, 1, 1)
        deck_grp.add(hero_grid)

        # Live Telemetry Sparkline Chart
        chart_grp = Adw.PreferencesGroup(
            title='Live Power &amp; Thermal Telemetry',
            description='Real-time wattage (cyan/violet) and CPU package temperature (magenta dashed).'
        )
        page.add(chart_grp)
        chart_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        chart_wrap.add_css_class('cosmic-chart-box')
        self.chart = TelemetrySparklineChart()
        chart_wrap.append(self.chart)
        chart_grp.add(chart_wrap)

        # Quick Profile Bar + Terminal Shortcut
        quick_grp = Adw.PreferencesGroup(title='Quick Profile &amp; Workspace Actions')
        page.add(quick_grp)
        quick_row = self._action_row('Instant Profile Switch', 'Applies CPU EPP, RAPL ceilings, ASPM, and refresh rules immediately.')
        qbox = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        for label, target in [
            ('Auto Balanced', 'auto'),
            ('Max Battery', 'max_battery'),
            ('Cool & Quiet', 'cool_quiet'),
            ('Extreme', 'extreme_performance'),
        ]:
            b = Gtk.Button(label=label)
            b.add_css_class('pill-btn')
            if target == 'auto':
                b.add_css_class('suggested-action')
            b.connect('clicked', self._quick_apply_profile, target)
            qbox.append(b)
        quick_row.add_suffix(qbox)
        quick_grp.add(quick_row)

        # Live Hardware Register Table
        group = Adw.PreferencesGroup(
            title='Hardware Registers &amp; Topology',
            description='Telemetry read directly from Linux kernel sysfs &amp; procfs.'
        )
        page.add(group)

        self.rows = {}
        for key, title, icon in [
            ('mode', 'Power Source', 'ac-adapter-symbolic'),
            ('cpu_topology', 'CPU Core Topology', 'processor-symbolic'),
            ('refresh_rate', 'Display Refresh Rate', 'video-display-symbolic'),
            ('gnome_profile', 'Desktop Power Profile', 'preferences-system-symbolic'),
            ('turbo', 'Turbo Boost', 'speedometer-symbolic'),
            ('pcie_aspm', 'PCIe ASPM Link Policy', 'drive-harddisk-symbolic'),
            ('gpu_perf', 'GPU Clock &amp; Power Profile', 'applications-graphics-symbolic'),
            ('vaapi', 'Hardware Video Acceleration', 'media-playback-start-symbolic'),
            ('net_opt', 'TCP Congestion Control', 'network-wireless-symbolic'),
            ('zram', 'Compressed Memory (ZRAM)', 'drive-multidisk-symbolic'),
        ]:
            row = self._action_row(title, '—', icon)
            self.rows[key] = row
            group.add(row)

        # ToF Presence Sensor Card
        radar_group = Adw.PreferencesGroup(
            title='ST VL53L1 ToF Human Presence Radar',
            description='Hardware HID proximity radar (zero webcam access).'
        )
        page.add(radar_group)

        self.tof_status_row = self._action_row('Sensor Status', 'Detecting...', 'system-lock-screen-symbolic')
        self.tof_badge = Gtk.Label(label='STANDBY')
        self.tof_badge.add_css_class('badge-standby')
        self.tof_badge.set_valign(Gtk.Align.CENTER)
        self.tof_status_row.add_suffix(self.tof_badge)
        radar_group.add(self.tof_status_row)

        self.tof_distance_row = self._action_row('Live Distance to Screen', 'Measuring...', 'camera-photo-symbolic')
        self.tof_bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER)
        self.tof_bar.set_size_request(140, -1)
        self.tof_bar.set_fraction(0.5)
        self.tof_distance_row.add_suffix(self.tof_bar)
        radar_group.add(self.tof_distance_row)

        self.tof_telemetry_row = self._action_row('Telemetry Stream', 'Waiting for packets...', 'network-transmit-receive-symbolic')
        radar_group.add(self.tof_telemetry_row)

        # Charge & OEM Hardware Controls
        lenovo_group = Adw.PreferencesGroup(
            title='Battery Conservation &amp; OEM Hardware Controls',
            description='80% charge threshold (Lenovo VPC2004 or standard sysfs charge_control_end_threshold).'
        )
        page.add(lenovo_group)

        self.lenovo_cm_row = SwitchRowCls(
            title='80% Battery Conservation Limit',
            subtitle='Limits charge at 80% on mains to maximize lithium cell cycle longevity.'
        )
        self.lenovo_cm_row.connect('notify::active', lambda row, _: self._toggle_lenovo('conservation_mode', row.get_active()))
        lenovo_group.add(self.lenovo_cm_row)

        self.lenovo_fn_row = SwitchRowCls(
            title='Fn-Lock (Primary Function Keys)',
            subtitle='Use F1-F12 hotkeys without holding Fn (Lenovo VPC2004).'
        )
        self.lenovo_fn_row.connect('notify::active', lambda row, _: self._toggle_lenovo('fn_lock', row.get_active()))
        lenovo_group.add(self.lenovo_fn_row)

        self.lenovo_usb_row = SwitchRowCls(
            title='Always-On USB Charging',
            subtitle='Keep powered USB ports active when suspended (Lenovo VPC2004).'
        )
        self.lenovo_usb_row.connect('notify::active', lambda row, _: self._toggle_lenovo('usb_charging', row.get_active()))
        lenovo_group.add(self.lenovo_usb_row)

        return page

    def _profiler_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Blame Profiler', icon_name='system-search-symbolic')

        ctrl_grp = Adw.PreferencesGroup(
            title='Energy &amp; C-State Wakeup Profiler (ffctl blame)',
            description='250ms native C procfs &amp; runtime-PM bus profiler identifying wakeup offenders and active PCI/USB hardware.'
        )
        page.add(ctrl_grp)
        sample_btn = Gtk.Button(label='Sample Now (250ms)', valign=Gtk.Align.CENTER)
        sample_btn.add_css_class('suggested-action')
        sample_btn.add_css_class('pill-btn')
        sample_btn.connect('clicked', lambda *_: self._run_blame_async())
        s_row = self._action_row('Run Live Wakeup Sample', 'Ranks top processes by CPU usage + context switches/sec and inspects active hardware.')
        s_row.add_suffix(sample_btn)
        ctrl_grp.add(s_row)

        self.blame_proc_grp = Adw.PreferencesGroup(title='Top Process Wakeup Offenders')
        page.add(self.blame_proc_grp)
        self.blame_proc_rows = []
        for i in range(6):
            r = self._action_row(f'#{i + 1} Sampling...', 'Click "Sample Now" or wait for initial probe.')
            self.blame_proc_grp.add(r)
            self.blame_proc_rows.append(r)

        self.blame_hw_grp = Adw.PreferencesGroup(title='Active Hardware Devices (Runtime Status = active)')
        page.add(self.blame_hw_grp)
        self.blame_pci_row = self._action_row('Active PCI Controllers', 'Scanning...')
        self.blame_usb_row = self._action_row('Active USB Peripherals', 'Scanning...')
        self.blame_hw_grp.add(self.blame_pci_row)
        self.blame_hw_grp.add(self.blame_usb_row)

        return page

    def _combo_row(self, title: str, values: list[str], current: str, subtitle: str = '') -> Adw.ComboRow:
        model = Gtk.StringList.new(values)
        row = Adw.ComboRow(title=title, model=model)
        if subtitle:
            row.set_subtitle(subtitle)
        row._values = values
        row.set_selected(values.index(current) if current in values else 0)
        return row

    def _mode_page(self, mode: str) -> Adw.PreferencesPage:
        label = 'Battery' if mode == 'battery' else 'AC Power'
        icon = 'battery-good-symbolic' if mode == 'battery' else 'power-profile-performance-symbolic'
        page = Adw.PreferencesPage(title=label, icon_name=icon)

        presets = Adw.PreferencesGroup(title='Hardware Presets', description='Calibrated power, EPP, and ASPM profiles.')
        page.add(presets)
        preset_row = self._action_row('Select Preset')
        box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        names = [('Recommended', 'recommended')]
        if mode == 'battery':
            names += [('Maximum Battery', 'maximum_battery'), ('Responsive', 'responsive')]
        else:
            names += [('Performance', 'performance'), ('Cool & Quiet', 'cool_quiet')]
        for text, name in names:
            b = Gtk.Button(label=text)
            b.add_css_class('pill-btn')
            b.connect('clicked', self._apply_preset, mode, name)
            box.append(b)
        preset_row.add_suffix(box)
        presets.add(preset_row)

        core_group = Adw.PreferencesGroup(title='Core Power Settings')
        page.add(core_group)
        s = self.cfg[mode]
        controls = {}
        for key, title, opts, sub in [
            ('gnome_profile', 'GNOME Power Profile', ['system', 'power-saver', 'balanced', 'performance'], 'Desktop profile applied on trigger.'),
            ('epp', 'CPU Energy Performance Preference (EPP)', ['system', 'default', 'power', 'balance_power', 'balance_performance', 'performance'], 'Hardware P-state power/latency bias.'),
            ('pcie_aspm', 'PCIe ASPM Link Policy', ['system', 'default', 'powersave', 'powersupersave', 'performance'], 'Active State Power Management for PCIe links.'),
            ('nvme_runtime_pm', 'NVMe SSD Runtime Power', ['system', 'auto', 'on'], 'Deep APST sleep when NVMe queue is idle.'),
            ('gpu_runtime_pm', 'Integrated GPU Power Policy', ['system', 'auto', 'on'], 'GPU frequency and runtime PM policy.'),
            ('usb_autosuspend', 'USB Controller Autosuspend', ['system', 'auto'], 'Excludes active HID peripherals automatically.'),
            ('audio_powersave', 'Audio Codec Power Save', ['system', 'on', 'off'], 'Lowers audio DSP draw when idle.'),
            ('hwp_dynamic_boost', 'Intel HWP Dynamic Boost', ['system', 'on', 'off'], 'Hardware frequency scaling responsiveness.'),
        ]:
            row = self._combo_row(title, opts, str(s.get(key, 'system')), sub)
            controls[key] = row
            core_group.add(row)

        for key, title, sub in [
            ('turbo', 'CPU Turbo Boost', 'Allows maximum single and multi-core boost frequencies.'),
            ('wifi_power_save', 'Wi-Fi 802.11 Power Save', 'Reduces radio idle power (automatically bypassed on iwlwifi 7 chips if throttling occurs).'),
        ]:
            sw = SwitchRowCls(title=title, subtitle=sub)
            sw.set_active(bool(s.get(key, True)))
            controls[key] = sw
            core_group.add(sw)

        if mode == 'ac':
            extra_grp = Adw.PreferencesGroup(title='Background Automation')
            page.add(extra_grp)
            ab_row = SwitchRowCls(
                title='Auto Dynamic Boost &amp; Telemetry Watcher',
                subtitle='Detects compilers, games &amp; local LLMs, logs telemetry graph samples, and clamps thermal spikes (>=90°C).'
            )
            ab_row.set_active(is_active(AUTOBOOST_SERVICE))
            ab_row.connect('notify::active', self._toggle_autoboost)
            extra_grp.add(ab_row)

        save_group = Adw.PreferencesGroup()
        page.add(save_group)
        btn = Gtk.Button(label='Save & Apply Configuration', valign=Gtk.Align.CENTER)
        btn.add_css_class('suggested-action')
        btn.add_css_class('pill-btn')
        btn.connect('clicked', self._save_mode, mode)
        save_row = self._action_row(f'Apply {label} Rules', 'Writes /etc/ff-power-manager/config.json via PolicyKit.')
        save_row.add_suffix(btn)
        save_group.add(save_row)
        self.mode_controls[mode] = controls
        return page

    def _presence_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Display & Presence', icon_name='system-lock-screen-symbolic')

        display_grp = Adw.PreferencesGroup(
            title='Adaptive Display Refresh Rate (GNOME / Hyprland / Plasma)',
            description='Automatically shifts refresh rate between 60 Hz idle and max Hz on battery.'
        )
        page.add(display_grp)
        self.promotion_switch = SwitchRowCls(
            title='Battery-Only Adaptive Refresh (60 ↔ Max Hz)',
            subtitle='Steps down to 60 Hz after 8s idle on battery and restores max refresh at 0ms on input.'
        )
        self.promotion_switch.set_active(bool(self.pcfg.get('promotion_120hz', True)))
        display_grp.add(self.promotion_switch)

        self.refresh_switch = SwitchRowCls(
            title='Dynamic Refresh Rate Switching',
            subtitle='Enables automatic display mode management via Mutter / Hyprland / Plasma backends.'
        )
        self.refresh_switch.set_active(bool(self.pcfg.get('auto_refresh_rate', True)))
        display_grp.add(self.refresh_switch)

        oled_grp = Adw.PreferencesGroup(
            title='Panel Screen Care &amp; Inactivity Dimming',
            description='Reduces static burn-in risk and lowers display draw when idle.'
        )
        page.add(oled_grp)

        self.oled_care_switch = SwitchRowCls(
            title='Idle Screen Dimming &amp; Zero-Touch DPMS Off',
            subtitle='Dims display on inactivity and turns off panel when user leaves range.'
        )
        self.oled_care_switch.set_active(bool(self.pcfg.get('oled_screen_care', True)))
        oled_grp.add(self.oled_care_switch)

        self.oled_dim_spin = Gtk.SpinButton.new_with_range(15.0, 180.0, 5.0)
        self.oled_dim_spin.set_value(float(self.pcfg.get('oled_dim_inactive_sec', 45)))
        dim_row = self._action_row(
            'Inactivity Dimming Delay (seconds)',
            'Delay before subtle panel dimming activates.'
        )
        dim_row.add_suffix(self.oled_dim_spin)
        oled_grp.add(dim_row)

        status = Adw.PreferencesGroup(
            title='ST VL53L1 ToF Human Presence Sensor',
            description='Hardware Time-of-Flight HID radar (optional IdeaPad/ISH hardware).'
        )
        page.add(status)
        self.presence_service_row = SwitchRowCls(
            title='Presence Automation Daemon',
            subtitle='Instant screen wake upon approach, zero-touch blanking when away.'
        )
        is_sensor_active = is_active(SYSTEM_SENSOR)
        enabled_setting = bool(self.pcfg.get('enabled', True))
        self.presence_service_row.set_active(enabled_setting and is_sensor_active)
        self.presence_service_row.connect('notify::active', self._presence_toggle)
        status.add(self.presence_service_row)

        tuning = Adw.PreferencesGroup(title='ToF Timing &amp; Media Safeguards')
        page.add(tuning)

        self.silence_spin = Gtk.SpinButton.new_with_range(5.0, 90.0, 1.0)
        self.silence_spin.set_value(float(self.scfg.get('silence_timeout', 15.0)))
        silence_row = self._action_row('Sensor Silence Floor (seconds)', 'Prevents false standby triggers while sitting still.')
        silence_row.add_suffix(self.silence_spin)
        tuning.add(silence_row)

        self.confirm_reports_spin = Gtk.SpinButton.new_with_range(1, 5, 1)
        self.confirm_reports_spin.set_value(int(self.scfg.get('present_confirm_reports', 1)))
        confirm_row = self._action_row('Approach Confirmation Packets', 'Consecutive reports needed to wake panel.')
        confirm_row.add_suffix(self.confirm_reports_spin)
        tuning.add(confirm_row)

        self.away_delay_spin = Gtk.SpinButton.new_with_range(3, 120, 1)
        self.away_delay_spin.set_value(int(self.pcfg.get('away_delay', 20)))
        delay_row = self._action_row('Departure Grace Delay (seconds)', 'Grace period after leaving &gt; 1.2m range.')
        delay_row.add_suffix(self.away_delay_spin)
        tuning.add(delay_row)

        self.presence_switches = {}
        for key, title, sub, defval in [
            ('wake_on_approach', 'Instant Wake on Approach', 'Wakes panel the moment you return to your desk.', True),
            ('screen_off_on_away', 'Turn Screen Off on Departure', 'Powers down display pixels when stepping away.', True),
            ('inhibit_on_media', 'Inhibit Screen Off During Media Playback', 'Respects MPRIS, session inhibitors, and PipeWire PCM streams.', True),
            ('lock_on_away', 'Lock Session on Departure', 'Secures GNOME session automatically on departure.', False),
        ]:
            sw = SwitchRowCls(title=title, subtitle=sub)
            sw.set_active(bool(self.pcfg.get(key, defval)))
            self.presence_switches[key] = sw
            tuning.add(sw)

        save_group = Adw.PreferencesGroup()
        page.add(save_group)
        save_btn = Gtk.Button(label='Save & Apply Settings', valign=Gtk.Align.CENTER)
        save_btn.add_css_class('suggested-action')
        save_btn.add_css_class('pill-btn')
        save_btn.connect('clicked', self._save_presence)
        save_row = self._action_row('Apply Display &amp; Presence Configuration', 'Updates session settings and hardware services.')
        save_row.add_suffix(save_btn)
        save_group.add(save_row)

        return page

    def _diagnostics_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Diagnostics', icon_name='utilities-system-monitor-symbolic')
        group = Adw.PreferencesGroup(title='Background System Services')
        page.add(group)
        rows = [
            ('Power Apply Engine', 'ff-power-apply.service', False),
            ('ToF Presence Sensor Daemon (Native C/ASM)', SYSTEM_SENSOR, False),
            ('Session Presence &amp; Display Manager', USER_PRESENCE, True),
            ('Auto Dynamic Boost &amp; Telemetry Watcher', AUTOBOOST_SERVICE, False),
        ]
        self.diag_rows = []
        for title, unit, user in rows:
            row = self._action_row(title)
            row._unit = unit
            row._user = user
            group.add(row)
            self.diag_rows.append(row)

        audit_grp = Adw.PreferencesGroup(
            title='Hardware &amp; Power Residency Audit (ffctl doctor)',
            description='Live kernel verification for S0ix sleep guard, ACPI wakeups, PCI Runtime PM, and daemon conflicts.'
        )
        page.add(audit_grp)
        self.audit_rows = {}
        for key, label in [
            ('sleep', 'Suspend &amp; s2idle Wakeup Guard'),
            ('sleep_report', 'Last Suspend Energy Report (ff-sleep-guard)'),
            ('cpu_driver', 'CPU Scaling Driver &amp; Active EPP'),
            ('pci_pm', 'PCI Runtime Power Management &amp; ASPM'),
            ('conflicts', 'Daemon Conflict Check (tlp / auto-cpufreq)'),
        ]:
            arow = self._action_row(label, 'Inspecting hardware state...')
            audit_grp.add(arow)
            self.audit_rows[key] = arow

        audit_btn = Gtk.Button(label='Run Audit Now', valign=Gtk.Align.CENTER)
        audit_btn.add_css_class('pill-btn')
        audit_btn.connect('clicked', lambda *_: (self._refresh_doctor_audit(), self.toast('Hardware residency audit updated.')))
        audit_action_row = self._action_row('Re-run Kernel &amp; PCI Residency Check', 'Executes native ffctl doctor --json probe in &lt; 2 ms.')
        audit_action_row.add_suffix(audit_btn)
        audit_grp.add(audit_action_row)

        safety = Adw.PreferencesGroup(title='Safety &amp; Factory Defaults')
        page.add(safety)
        reset = self._action_row(
            'Reset to Recommended Factory Defaults',
            'Restores balanced power profiles and sensor defaults cleanly.'
        )
        b = Gtk.Button(label='Reset', valign=Gtk.Align.CENTER)
        b.add_css_class('destructive-action')
        b.add_css_class('pill-btn')
        b.connect('clicked', self._safe_reset)
        reset.add_suffix(b)
        safety.add(reset)
        return page

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
            try:
                out = subprocess.check_output([ffctl_bin, 'blame', '--json'], text=True, stderr=subprocess.DEVNULL, timeout=3.0)
                data = json.loads(out)
            except Exception:
                data = None

            def _apply_ui():
                self._blame_busy = False
                if not hasattr(self, 'blame_proc_rows'):
                    return GLib.SOURCE_REMOVE
                if not data:
                    self.blame_proc_rows[0].set_title('Blame profiler unavailable')
                    self.blame_proc_rows[0].set_subtitle('Ensure ffctl binary is compiled/installed.')
                    return GLib.SOURCE_REMOVE

                procs = data.get('processes', [])
                for idx, row in enumerate(self.blame_proc_rows):
                    if idx < len(procs):
                        pr = procs[idx]
                        row.set_title(f"#{idx + 1} {pr.get('name', '?')} (PID {pr.get('pid', 0)})")
                        row.set_subtitle(f"CPU: {pr.get('cpu_pct', 0.0):.1f}%  •  Wakeups: {pr.get('wakeups_per_sec', 0.0):.1f}/sec")
                    else:
                        row.set_title(f'#{idx + 1} Idle')
                        row.set_subtitle('No additional active wakeup processes in window.')

                pci = data.get('active_pci', [])
                usb = data.get('active_usb', [])
                pci_txt = ', '.join(f"{d.get('slot', '')} ({d.get('driver', '').split()[0]})" for d in pci[:6]) or 'All suspended'
                usb_txt = ', '.join(f"{d.get('port', '')}: {d.get('product', '')}" for d in usb[:5]) or 'All autosuspended'
                self.blame_pci_row.set_subtitle(f"{len(pci)} active: {pci_txt}")
                self.blame_usb_row.set_subtitle(f"{len(usb)} active: {usb_txt}")
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

            svc_states = []
            if hasattr(self, 'diag_rows'):
                for row in self.diag_rows:
                    svc_states.append((row, is_active(row._unit, row._user)))

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

                self.hero_watts.set_label('-- W' if watts_val is None else f"{float(watts_val):.1f} W")
                self.hero_watts_sub.set_label(f"{mode_lbl} • {s.get('refresh_rate', 'Adaptive')}")
                self.hero_temp.set_label(f"{temp_c}°C" if temp_c > 0 else '—°C')
                self.hero_temp_sub.set_label(f"EPP: {s.get('epp') or '—'}")
                self.hero_bat.set_label(f"{bat_pct}%" if bat_pct is not None else '—%')
                hpct = health.get('health_pct', 100.0)
                cyc = health.get('cycle_count', 0)
                self.hero_bat_sub.set_label(f"Health {hpct:.1f}% • {cyc} cycles")

                if sleep_data:
                    dur_m = int(sleep_data.get('duration_sec', 0)) // 60
                    self.hero_sleep.set_label(f"{sleep_data.get('avg_watts', 0.0):.2f} W")
                    self.hero_sleep_sub.set_label(f"{dur_m}m • {sleep_data.get('pct_per_hour', 0.0):.2f}%/hr ({sleep_data.get('sleep_mode', 's2idle')})")

                chart_samples = samples
                if not chart_samples:
                    self._local_samples.append({
                        'ts': int(time.time()),
                        'watts': float(watts_val) if watts_val is not None else 0.0,
                        'temp_c': int(temp_c),
                    })
                    chart_samples = list(self._local_samples)
                if hasattr(self, 'chart'):
                    self.chart.set_samples(chart_samples)

                presence_map = {
                    'present': 'User Present (At Desk)',
                    'absent': 'User Away (Standby Mode)',
                    'disabled': 'Disabled',
                    'unknown': 'Detecting...',
                    'error': 'Sensor Hardware Error',
                }
                raw_pres = s.get('presence_state') or 'disabled'

                values = {
                    'mode': 'Battery (Discharging)' if s['mode'] == 'battery' else 'AC Power (Mains Online)',
                    'cpu_topology': s.get('cpu_topology', 'Dynamic Online'),
                    'refresh_rate': s.get('refresh_rate', '—'),
                    'gnome_profile': s['gnome_profile'] or '—',
                    'turbo': 'Enabled (Dynamic Boost)' if s['turbo'] else ('Disabled' if s['turbo'] is not None else '—'),
                    'pcie_aspm': s.get('pcie_aspm', '—'),
                    'gpu_perf': s.get('gpu_perf', '—'),
                    'vaapi': s.get('vaapi', '—'),
                    'net_opt': s.get('net_opt', '—'),
                    'zram': s.get('zram', '—'),
                }
                for key, value in values.items():
                    if hasattr(self, 'rows') and key in self.rows:
                        self.rows[key].set_subtitle(value)

                if tel and hasattr(self, 'tof_status_row'):
                    st = tel.get('state', 'unknown')
                    dist_cm = tel.get('distance_cm', 0)
                    thresh_cm = tel.get('threshold_cm', 120)
                    pkts = tel.get('packet_count', 0)
                    sec_ago = tel.get('last_packet_sec_ago', 0.0)

                    if st == 'present':
                        self.tof_badge.set_label('AT DESK')
                        self.tof_badge.set_css_classes(['badge-active'])
                        self.tof_status_row.set_subtitle('User detected at desk')
                    elif st == 'absent':
                        self.tof_badge.set_label('AWAY')
                        self.tof_badge.set_css_classes(['badge-standby'])
                        self.tof_status_row.set_subtitle('User departed (&gt; 1.2m threshold)')
                    else:
                        self.tof_badge.set_label('OFFLINE')
                        self.tof_badge.set_css_classes(['badge-disabled'])
                        self.tof_status_row.set_subtitle('Sensor offline or unavailable')

                    self.tof_distance_row.set_subtitle(f"{dist_cm} cm / {thresh_cm} cm (1.2m Threshold)")
                    frac = min(1.0, max(0.0, dist_cm / thresh_cm)) if thresh_cm > 0 else 0.5
                    self.tof_bar.set_fraction(frac)
                    self.tof_telemetry_row.set_subtitle(f"{pkts} packets received ({sec_ago:.1f}s ago) • Native ASM Engine")
                elif hasattr(self, 'tof_status_row'):
                    self.tof_status_row.set_subtitle(presence_map.get(raw_pres, raw_pres))

                lenovo = s.get('lenovo', {})
                if lenovo and hasattr(self, 'lenovo_cm_row'):
                    self._lenovo_syncing = True
                    if lenovo.get('conservation_mode') is not None:
                        self.lenovo_cm_row.set_active(bool(lenovo['conservation_mode']))
                    if lenovo.get('fn_lock') is not None:
                        self.lenovo_fn_row.set_active(bool(lenovo['fn_lock']))
                    if lenovo.get('usb_charging') is not None:
                        self.lenovo_usb_row.set_active(bool(lenovo['usb_charging']))
                    self._lenovo_syncing = False

                for row, active_flag in svc_states:
                    row.set_subtitle('Running (Active)' if active_flag else 'Stopped (Inactive)')

                if doctor_data is not None and hasattr(self, 'audit_rows'):
                    self._last_doctor_at = time.monotonic()
                    self._apply_doctor_ui(doctor_data if isinstance(doctor_data, dict) else None, sleep_data)

                return GLib.SOURCE_REMOVE

            GLib.idle_add(_apply_ui)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_doctor_ui(self, d: dict | None, sl: dict | None = None) -> None:
        if not d:
            for r in self.audit_rows.values():
                r.set_subtitle('ffctl doctor unavailable (run make build / install)')
            return
        guard = 'installed' if d.get('sleep_guard_hook') else 'missing'
        self.audit_rows['sleep'].set_subtitle(
            f"Mode: {d.get('mem_sleep', 'unknown')} | Sleep Guard: {guard} | {d.get('acpi_non_lid_wakeups_enabled', 0)} ACPI wake triggers"
        )
        if sl:
            self.audit_rows['sleep_report'].set_subtitle(
                f"Last sleep: {sl.get('duration_sec', 0) // 60}m • {sl.get('wh_used', 0.0):.3f} Wh ({sl.get('avg_watts', 0.0):.2f} W / {sl.get('pct_per_hour', 0.0):.2f}%/hr)"
            )
        else:
            self.audit_rows['sleep_report'].set_subtitle('No suspend cycle recorded yet (captured automatically after sleep).')
        self.audit_rows['cpu_driver'].set_subtitle(
            f"Driver: {d.get('scaling_driver', '—')} | EPP: {d.get('epp', '—')}"
        )
        self.audit_rows['pci_pm'].set_subtitle(
            f"{d.get('pci_devices_suspended', 0)}/{d.get('pci_devices_total', 0)} PCI devices suspended | ASPM: {d.get('pcie_aspm', '—')}"
        )
        if d.get('conflict_tlp') or d.get('conflict_auto_cpufreq'):
            conf = 'tlp.service' if d.get('conflict_tlp') else 'auto-cpufreq.service'
            self.audit_rows['conflicts'].set_subtitle(f"WARNING: Conflicting {conf} detected!")
        else:
            self.audit_rows['conflicts'].set_subtitle('OK — No conflicting power daemons active')

    def _refresh_doctor_audit(self) -> None:
        self._last_doctor_at = 0.0
        self.refresh_status()

    def _toggle_lenovo(self, feat: str, active: bool) -> None:
        if self._lenovo_syncing:
            return
        val = '1' if active else '0'
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists() and os.geteuid() != 0:
            _run_helper(['set-lenovo', feat, val])
        else:
            set_lenovo_feature(feat, val)
        self.refresh_status()
        feat_name = feat.replace('_', ' ').title()
        self.toast(f"✓ {feat_name} set to {'ON' if active else 'OFF'}.")

    def _toggle_autoboost(self, row, _pspec) -> None:
        active = row.get_active()
        subaction = 'enable-now' if active else 'disable-now'
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists() and os.geteuid() != 0:
            _run_helper(['autoboost-service', subaction])
        else:
            act = ['enable', '--now'] if active else ['disable', '--now']
            subprocess.run(['/usr/bin/systemctl', *act, AUTOBOOST_SERVICE],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.refresh_status()
        self.toast(f"✓ Auto Dynamic Boost {'enabled' if active else 'disabled'}.")

    def _apply_preset(self, _btn, mode: str, name: str) -> None:
        preset = PRESETS.get(mode, {}).get(name)
        if not preset:
            return
        ctrls = self.mode_controls.get(mode, {})
        for k, v in preset.items():
            row = ctrls.get(k)
            if not row:
                continue
            if isinstance(row, Adw.ComboRow):
                if v in row._values:
                    row.set_selected(row._values.index(v))
            elif isinstance(row, SwitchRowCls):
                row.set_active(bool(v))
        mode_label = 'Battery' if mode == 'battery' else 'AC Power'
        self.cfg[mode].update(preset)
        try:
            save_and_apply_config(self.cfg)
            self.refresh_status()
            self.toast(f'✓ {mode_label} preset "{name.replace("_", " ").title()}" applied.')
        except Exception as exc:
            self.toast(f'Preset error: {exc}')

    def _save_mode(self, _btn, mode: str) -> None:
        ctrls = self.mode_controls.get(mode, {})
        new_sub = {}
        for k, row in ctrls.items():
            if isinstance(row, Adw.ComboRow):
                new_sub[k] = row._values[row.get_selected()]
            elif isinstance(row, SwitchRowCls):
                new_sub[k] = row.get_active()
        self.cfg[mode] = new_sub
        try:
            save_and_apply_config(self.cfg)
            self.refresh_status()
            mode_label = 'Battery' if mode == 'battery' else 'AC Power'
            self.toast(f'✓ {mode_label} settings saved and applied.')
        except Exception as e:
            self.toast(f'Save error: {e}')

    def _presence_toggle(self, row, _pspec) -> None:
        if self._presence_syncing:
            return
        active = row.get_active()
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
        active = self.presence_service_row.get_active()
        self.pcfg['enabled'] = active
        self.scfg['silence_timeout'] = self.silence_spin.get_value()
        self.scfg['present_confirm_reports'] = int(self.confirm_reports_spin.get_value())
        try:
            save_sensor_config(self.scfg)
        except Exception as exc:
            self.toast(f'Sensor save error: {exc}')
            return

        self.pcfg['away_delay'] = int(self.away_delay_spin.get_value())
        self.pcfg['auto_refresh_rate'] = self.refresh_switch.get_active()
        self.pcfg['promotion_120hz'] = self.promotion_switch.get_active()
        self.pcfg['oled_screen_care'] = self.oled_care_switch.get_active()
        self.pcfg['oled_dim_inactive_sec'] = int(self.oled_dim_spin.get_value())
        for k, sw in self.presence_switches.items():
            self.pcfg[k] = sw.get_active()
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
            self.toast('✓ Display and presence configuration updated.')
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
            self.toast('✓ Configuration reset to recommended factory defaults.')
        except Exception as e:
            self.toast(f'Reset error: {e}')


def main():
    return PowerManagerApp().run(None)


if __name__ == '__main__':
    raise SystemExit(main())
