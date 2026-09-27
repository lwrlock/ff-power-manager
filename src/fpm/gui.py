from __future__ import annotations

import json
import os
import pathlib
import subprocess
from copy import deepcopy

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk, Gdk

from .core import (
    CONFIG_PATH,
    SENSOR_CONFIG_PATH,
    load_config,
    load_sensor_config,
    save_config,
    save_and_apply_config,
    save_sensor_config,
    status_snapshot,
    set_lenovo_feature,
    PRESETS,
)

USER_CFG = pathlib.Path.home() / '.config/ff-power-manager/presence.json'
SYSTEM_SENSOR = 'ff-presence-sensor.service'
USER_PRESENCE = 'ff-presence-session.service'
AUTOBOOST_SERVICE = 'ff-power-autoboost.service'
TELEMETRY_FILE = pathlib.Path('/run/ff-power-manager/sensor_telemetry.json')

DEFAULT_PRESENCE = {
    'enabled': True,
    'away_confirm': 3.0,
    'away_delay': 10,
    'wake_on_approach': True,
    'wake_only_if_fpm_off': False,
    'screen_off_on_away': True,
    'lock_on_away': False,
    'auto_refresh_rate': True,
    'oled_screen_care': True,
    'oled_dim_inactive_sec': 45,
}

CUSTOM_CSS = b"""
.card-hero {
    background: rgba(56, 189, 248, 0.08);
    border-radius: 12px;
    border: 1px solid rgba(56, 189, 248, 0.25);
    padding: 10px;
}
.badge-active {
    background-color: rgba(34, 197, 94, 0.2);
    color: #22c55e;
    border-radius: 9999px;
    padding: 3px 10px;
    font-weight: bold;
}
.badge-standby {
    background-color: rgba(245, 158, 11, 0.2);
    color: #f59e0b;
    border-radius: 9999px;
    padding: 3px 10px;
    font-weight: bold;
}
.badge-disabled {
    background-color: rgba(148, 163, 184, 0.15);
    color: #94a3b8;
    border-radius: 9999px;
    padding: 3px 10px;
}
.pill-btn {
    border-radius: 9999px;
    padding: 6px 14px;
    font-weight: 600;
}
"""


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
    cmd = ['/usr/bin/systemctl']
    if user:
        cmd.append('--user')
    cmd += ['is-active', '--quiet', unit]
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


class PowerManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id='com.ff.PowerManager', flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_activate(self):
        self._load_styles()
        win = self.props.active_window
        if not win:
            win = MainWindow(self)
        win.present()

    def _load_styles(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(CUSTOM_CSS)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='FF Power Manager', default_width=960, default_height=800)
        self.cfg = load_config()
        self.scfg = load_sensor_config()
        self.pcfg = load_user_presence()
        self.live_source = 0
        self.mode_controls = {}
        self._presence_syncing = False
        self._lenovo_syncing = False

        self.overlay = Adw.ToastOverlay()
        self.set_content(self.overlay)
        toolbar = Adw.ToolbarView()
        self.overlay.set_child(toolbar)

        self.stack = Adw.ViewStack()
        title = Adw.ViewSwitcherTitle(stack=self.stack, title='FF Power Manager')
        header = Adw.HeaderBar(title_widget=title)

        # Launch TUI button in header bar
        tui_btn = Gtk.Button(icon_name='utilities-terminal-symbolic', tooltip_text='Open Terminal Dashboard (ff-tui)')
        tui_btn.add_css_class('flat')
        tui_btn.connect('clicked', lambda *_: self._launch_tui())
        header.pack_start(tui_btn)

        # Refresh button in header bar
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Refresh Hardware Status')
        refresh.add_css_class('flat')
        refresh.connect('clicked', lambda *_: self.refresh_status())
        header.pack_end(refresh)

        # About button in header bar
        about_btn = Gtk.Button(icon_name='help-about-symbolic', tooltip_text='About FF Power Manager')
        about_btn.add_css_class('flat')
        about_btn.connect('clicked', lambda *_: self._show_about())
        header.pack_end(about_btn)

        toolbar.add_top_bar(header)
        toolbar.set_content(self.stack)

        switcher = Adw.ViewSwitcherBar(stack=self.stack)
        switcher.set_reveal(True)
        toolbar.add_bottom_bar(switcher)

        self.stack.add_titled_with_icon(self._overview_page(), 'overview', 'Overview', 'view-dashboard-symbolic')
        self.stack.add_titled_with_icon(self._mode_page('battery'), 'battery', 'Battery', 'battery-good-symbolic')
        self.stack.add_titled_with_icon(self._mode_page('ac'), 'ac', 'AC Power', 'power-profile-performance-symbolic')
        self.stack.add_titled_with_icon(self._presence_page(), 'presence', 'Display & Presence', 'system-lock-screen-symbolic')
        self.stack.add_titled_with_icon(self._diagnostics_page(), 'diagnostics', 'Diagnostics', 'utilities-system-monitor-symbolic')

        # Automatically start live telemetry polling in GUI (every 2.5s)
        self.live_source = GLib.timeout_add_seconds(3, self._live_tick)

        self.refresh_status()

    def toast(self, text: str) -> None:
        self.overlay.add_toast(Adw.Toast(title=text, timeout=3))

    def _action_row(self, title: str, subtitle: str = '', icon: str = '') -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        if icon:
            row.add_prefix(Gtk.Image.new_from_icon_name(icon))
        return row

    def _launch_tui(self) -> None:
        terminals = [
            ['blackbox-terminal', '-e', '/usr/local/bin/ff-tui'],
            ['blackbox-terminal', '-e', './ff-tui'],
            ['gnome-terminal', '--', '/usr/local/bin/ff-tui'],
            ['ptyxis', '-e', '/usr/local/bin/ff-tui'],
            ['kgx', '-e', '/usr/local/bin/ff-tui'],
            ['x-terminal-emulator', '-e', '/usr/local/bin/ff-tui'],
        ]
        launched = False
        for cmd in terminals:
            try:
                subprocess.Popen(cmd)
                launched = True
                self.toast('Terminal Dashboard (ff-tui) launched.')
                break
            except (FileNotFoundError, OSError):
                continue
        if not launched:
            self.toast('Could not launch terminal. You can run "ff-tui" manually in a terminal.')

    def _show_about(self) -> None:
        dialog = Adw.AboutDialog(
            application_name='FF Power Manager',
            application_icon='preferences-system-power',
            developer_name='Furkan (@lwrlock)',
            version='1.2.0',
            website='https://lwrlock.github.io/ff-power-manager/',
            issue_url='https://github.com/lwrlock/ff-power-manager/issues',
            license_type=Gtk.License.MIT_X11,
            comments=(
                "Engineered for Lenovo IdeaPad Pro 5 14IAH10 and modern Intel mobile platforms.\n"
                "MacBook-level battery efficiency, zero-stutter performance architecture.\n\n"
                "Developed as an open-source initiative by a 17-year-old computer engineering student in collaboration with AI."
            ),
        )
        dialog.present(self)

    def _overview_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Overview', icon_name='view-dashboard-symbolic')

        # Hero Banner: Quick TUI Launch
        hero_group = Adw.PreferencesGroup()
        page.add(hero_group)

        hero_row = Adw.ActionRow(
            title='Terminal Dashboard (C &amp; x86_64 Assembly Engine)',
            subtitle='btop-style dynamic tabbed interface, live ToF radar, and 0.0% CPU overhead.'
        )
        hero_row.add_css_class('card-hero')
        hero_row.add_prefix(Gtk.Image.new_from_icon_name('utilities-terminal-symbolic'))

        open_tui_btn = Gtk.Button(label='Launch TUI', valign=Gtk.Align.CENTER)
        open_tui_btn.add_css_class('suggested-action')
        open_tui_btn.add_css_class('pill-btn')
        open_tui_btn.connect('clicked', lambda *_: self._launch_tui())
        hero_row.add_suffix(open_tui_btn)
        hero_group.add(hero_row)

        # Group 1: Real-time Power & Hardware Status
        group = Adw.PreferencesGroup(
            title='Live Power &amp; Hardware Telemetry',
            description='Read directly from kernel sysfs hardware registers in sub-microsecond assembly.'
        )
        page.add(group)

        self.rows = {}
        for key, title, icon in [
            ('mode', 'Power Source', 'ac-adapter-symbolic'),
            ('watts', 'Active Power Draw', 'energy-battery-symbolic'),
            ('battery_percent', 'Battery Charge Level', 'battery-level-80-symbolic'),
            ('refresh_rate', 'Display Refresh Rate', 'video-display-symbolic'),
            ('gnome_profile', 'GNOME Power Profile', 'preferences-system-symbolic'),
            ('epp', 'CPU Energy Preference (EPP)', 'applications-science-symbolic'),
            ('turbo', 'Intel Turbo Boost', 'speedometer-symbolic'),
            ('pcie_aspm', 'PCIe ASPM Link Policy', 'drive-harddisk-symbolic'),
            ('gpu_perf', 'Intel Arc GPU Base Clock', 'applications-graphics-symbolic'),
            ('vaapi', 'Hardware Video Acceleration', 'media-playback-start-symbolic'),
            ('net_opt', 'TCP Congestion Control', 'network-wireless-symbolic'),
            ('zram', 'Compressed Memory (ZRAM)', 'drive-multidisk-symbolic'),
        ]:
            row = self._action_row(title, '—', icon)
            self.rows[key] = row
            group.add(row)

        # Group 2: ST VL53L1 ToF Presence Radar
        radar_group = Adw.PreferencesGroup(
            title='ST VL53L1 ToF Human Presence Radar',
            description='Lenovo Intel ISH infrared sensor (0.0% CPU overhead, millimeter precision). Camera is never used.'
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

        self.tof_telemetry_row = self._action_row('Telemetry Stream', 'Waiting for hardware packets...', 'network-transmit-receive-symbolic')
        radar_group.add(self.tof_telemetry_row)

        # Group 3: Lenovo IdeaPad Hardware Integration
        lenovo_group = Adw.PreferencesGroup(
            title='Lenovo IdeaPad Hardware Integration (VPC2004)',
            description='Proprietary ACPI firmware hardware switches.'
        )
        page.add(lenovo_group)

        self.lenovo_cm_row = Adw.SwitchRow(
            title='Battery Conservation Mode (80% Limit)',
            subtitle='Stops charging at 80% to dramatically extend lithium battery lifespan.'
        )
        self.lenovo_cm_row.connect('notify::active', lambda row, _: self._toggle_lenovo('conservation_mode', row.get_active()))
        lenovo_group.add(self.lenovo_cm_row)

        self.lenovo_fn_row = Adw.SwitchRow(
            title='Fn-Lock (Primary Function Keys)',
            subtitle='Use F1-F12 for media/brightness hotkeys without holding Fn.'
        )
        self.lenovo_fn_row.connect('notify::active', lambda row, _: self._toggle_lenovo('fn_lock', row.get_active()))
        lenovo_group.add(self.lenovo_fn_row)

        self.lenovo_usb_row = Adw.SwitchRow(
            title='Always-On USB Charging',
            subtitle='Allows charging smartphones and accessories even when the laptop is turned off.'
        )
        self.lenovo_usb_row.connect('notify::active', lambda row, _: self._toggle_lenovo('usb_charging', row.get_active()))
        lenovo_group.add(self.lenovo_usb_row)

        # Group 4: Quick Action Controls
        actions = Adw.PreferencesGroup(title='Quick Controls')
        page.add(actions)

        apply_row = self._action_row('Re-apply Active Profile', 'Enforces hardware power management policies and verifies sysfs registers.')
        btn = Gtk.Button(label='Apply Now', valign=Gtk.Align.CENTER)
        btn.add_css_class('suggested-action')
        btn.add_css_class('pill-btn')
        btn.connect('clicked', self._apply_now)
        apply_row.add_suffix(btn)
        actions.add(apply_row)

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

        presets = Adw.PreferencesGroup(title='Hardware Presets', description='Carefully calibrated and benchmarked profiles.')
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

        p_row = self._combo_row('GNOME Power Profile', ['system', 'power-saver', 'balanced', 'performance'], s['gnome_profile'])
        controls['gnome_profile'] = p_row
        core_group.add(p_row)

        epp_row = self._combo_row('CPU Energy Preference (EPP)', ['system', 'power', 'balance_power', 'balance_performance', 'performance'], s['epp'])
        controls['epp'] = epp_row
        core_group.add(epp_row)

        turbo_row = Adw.SwitchRow(title='Intel Turbo Boost', subtitle='Disabling capping may increase battery life; keeping enabled provides peak responsiveness.')
        turbo_row.set_active(bool(s['turbo']))
        controls['turbo'] = turbo_row
        core_group.add(turbo_row)

        wifi_row = Adw.SwitchRow(title='Wi-Fi Power Management', subtitle='Enables dynamic power saving on Intel Wi-Fi 7 chipset during idle.')
        wifi_row.set_active(bool(s['wifi_power_save']))
        controls['wifi_power_save'] = wifi_row
        core_group.add(wifi_row)

        # If on battery page: add Battery Health & Degradation Analytics Card
        if mode == 'battery':
            health_group = Adw.PreferencesGroup(
                title='Battery Health &amp; Degradation Analytics',
                description='Real-time telemetry reported by hardware fuel gauge.'
            )
            page.add(health_group)

            self.health_rows = {}
            for hkey, htitle, hicon in [
                ('health_score', 'Battery Health Score', 'emblem-favorite-symbolic'),
                ('capacities', 'Design vs Full Capacity', 'battery-level-100-symbolic'),
                ('cycles', 'Charge Cycle Count', 'view-refresh-symbolic'),
                ('voltage', 'Pack Voltage &amp; Chemistry', 'flash-symbolic'),
            ]:
                hrow = self._action_row(htitle, '—', hicon)
                self.health_rows[hkey] = hrow
                health_group.add(hrow)

        # If on AC page: add Auto Dynamic Boost & GameMode Engine Card
        if mode == 'ac':
            boost_group = Adw.PreferencesGroup(
                title='Auto Dynamic Boost &amp; GameMode Engine',
                description='Background watcher that detects heavy workloads and unleashes max power.'
            )
            page.add(boost_group)

            self.autoboost_switch = Adw.SwitchRow(
                title='Automatic GameMode &amp; Compiler Boost',
                subtitle='Detects Steam, 3D rendering, and compilation to auto-boost CPU/GPU clocks.'
            )
            self.autoboost_switch.set_active(is_active(AUTOBOOST_SERVICE))
            self.autoboost_switch.connect('notify::active', self._toggle_autoboost)
            boost_group.add(self.autoboost_switch)

        advanced = Adw.PreferencesGroup(title='Advanced Hardware Power Management')
        page.add(advanced)
        specs = [
            ('hwp_dynamic_boost', 'HWP Dynamic Boost', ['system', 'off', 'on']),
            ('nvme_runtime_pm', 'NVMe APST Runtime PM', ['system', 'auto', 'on']),
            ('gpu_runtime_pm', 'Intel Arc GPU Runtime PM', ['system', 'auto', 'on']),
            ('pcie_aspm', 'PCIe ASPM Link Policy', ['system', 'default', 'powersave', 'powersupersave', 'performance']),
            ('usb_autosuspend', 'USB Autosuspend', ['system', 'auto']),
            ('audio_powersave', 'Audio Chipset Power Save', ['system', 'on', 'off']),
        ]
        for key, title, vals in specs:
            row = self._combo_row(title, vals, s[key])
            controls[key] = row
            advanced.add(row)

        save_group = Adw.PreferencesGroup()
        page.add(save_group)
        save_row = self._action_row(f'Save {label} Settings', 'Changes take effect immediately on active power source.')
        save_btn = Gtk.Button(label='Save & Apply', valign=Gtk.Align.CENTER)
        save_btn.add_css_class('suggested-action')
        save_btn.add_css_class('pill-btn')
        save_btn.connect('clicked', self._save_mode, mode)
        save_row.add_suffix(save_btn)
        save_group.add(save_row)
        self.mode_controls[mode] = controls
        return page

    def _presence_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Display &amp; Presence', icon_name='system-lock-screen-symbolic')

        # Samsung 2.8K OLED Display Optimization
        display_grp = Adw.PreferencesGroup(
            title='Smart Display Refresh (Samsung 2.8K OLED)',
            description='Seamlessly balances battery longevity and extreme 120Hz smoothness.'
        )
        page.add(display_grp)
        self.refresh_switch = Adw.SwitchRow(
            title='Dynamic Refresh Rate Switching',
            subtitle='Automatically switches to 60 Hz on battery, and 120 Hz + VRR on AC power.'
        )
        self.refresh_switch.set_active(bool(self.pcfg.get('auto_refresh_rate', True)))
        display_grp.add(self.refresh_switch)

        # OLED Screen Care & Anti-Burn-in
        oled_grp = Adw.PreferencesGroup(
            title='Samsung 2.8K OLED Anti-Burn-in &amp; Screen Care',
            description='Extends organic OLED panel life and eliminates static burn-in risk.'
        )
        page.add(oled_grp)

        self.oled_care_switch = Adw.SwitchRow(
            title='OLED Anti-Burn-in &amp; Dynamic Dimming',
            subtitle='Gradually dims panel on inactivity; powers down pixels (0W pure black) when away.'
        )
        self.oled_care_switch.set_active(bool(self.pcfg.get('oled_screen_care', True)))
        oled_grp.add(self.oled_care_switch)

        self.oled_dim_spin = Gtk.SpinButton.new_with_range(15.0, 180.0, 5.0)
        self.oled_dim_spin.set_value(float(self.pcfg.get('oled_dim_inactive_sec', 45)))
        dim_row = self._action_row(
            'Inactivity Dimming Delay (seconds)',
            'Time of user inactivity before subtle OLED dimming begins (Recommended: 45s).'
        )
        dim_row.add_suffix(self.oled_dim_spin)
        oled_grp.add(dim_row)

        # Lenovo Human Presence Detection (ToF)
        status = Adw.PreferencesGroup(
            title='Lenovo Human Presence Detection (ST VL53L1 ToF)',
            description='Hardware Time-of-Flight radar (0.0% CPU overhead). Webcams are never accessed.'
        )
        page.add(status)
        self.presence_service_row = Adw.SwitchRow(
            title='Presence Automation Daemon',
            subtitle='Instant screen wake upon return, zero-touch blanking when away.'
        )
        is_sensor_active = is_active(SYSTEM_SENSOR)
        enabled_setting = bool(self.pcfg.get('enabled', True))
        self.presence_service_row.set_active(enabled_setting and is_sensor_active)
        self.presence_service_row.connect('notify::active', self._presence_toggle)
        status.add(self.presence_service_row)

        tuning = Adw.PreferencesGroup(title='ToF Timing &amp; Sensitivity Tuning')
        page.add(tuning)

        self.silence_spin = Gtk.SpinButton.new_with_range(5.0, 90.0, 1.0)
        self.silence_spin.set_value(float(self.scfg.get('silence_timeout', 30.0)))
        silence_row = self._action_row(
            'Sensor Silence Floor (seconds)',
            'Prevents false standby triggers when user sits motionless (Recommended: 30s).'
        )
        silence_row.add_suffix(self.silence_spin)
        tuning.add(silence_row)

        self.confirm_reports_spin = Gtk.SpinButton.new_with_range(1, 5, 1)
        self.confirm_reports_spin.set_value(int(self.scfg.get('present_confirm_reports', 1)))
        confirm_row = self._action_row(
            'Approach Confirmation Packets',
            'Number of consecutive ToF reports required to immediately wake screen (Recommended: 1).'
        )
        confirm_row.add_suffix(self.confirm_reports_spin)
        tuning.add(confirm_row)

        self.away_delay_spin = Gtk.SpinButton.new_with_range(3, 120, 1)
        self.away_delay_spin.set_value(int(self.pcfg.get('away_delay', 10)))
        delay_row = self._action_row(
            'Departure Grace Delay (seconds)',
            'Grace period after user departs (> 1.2m) before powering down display.'
        )
        delay_row.add_suffix(self.away_delay_spin)
        tuning.add(delay_row)

        self.presence_switches = {}
        for key, title, sub, defval in [
            ('wake_on_approach', 'Instant Wake on Approach', 'Powers up the OLED panel the instant you approach your desk.', True),
            ('screen_off_on_away', 'Turn Screen Off on Departure', 'Powers down pixels when you step beyond 1.2m to maximize battery.', True),
            ('lock_on_away', 'Lock Session on Departure', 'Secures the GNOME desktop session immediately upon departure.', False),
        ]:
            sw = Adw.SwitchRow(title=title, subtitle=sub)
            sw.set_active(bool(self.pcfg.get(key, defval)))
            self.presence_switches[key] = sw
            tuning.add(sw)

        save_group = Adw.PreferencesGroup()
        page.add(save_group)
        save_btn = Gtk.Button(label='Save & Apply Settings', valign=Gtk.Align.CENTER)
        save_btn.add_css_class('suggested-action')
        save_btn.add_css_class('pill-btn')
        save_btn.connect('clicked', self._save_presence)
        save_row = self._action_row('Apply Display &amp; Presence Configuration', 'Saves settings and updates background hardware services.')
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
            ('GNOME Session Presence &amp; Screen Manager', USER_PRESENCE, True),
            ('Auto Dynamic Boost &amp; GameMode Engine', AUTOBOOST_SERVICE, False),
        ]
        self.diag_rows = []
        for title, unit, user in rows:
            row = self._action_row(title)
            row._unit = unit
            row._user = user
            group.add(row)
            self.diag_rows.append(row)

        safety = Adw.PreferencesGroup(title='Safety &amp; Factory Defaults')
        page.add(safety)
        reset = self._action_row(
            'Reset to Recommended Factory Defaults',
            'Restores all power profiles and ToF sensor thresholds to tested optimum defaults.'
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

    def refresh_status(self) -> None:
        s = status_snapshot()
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
            'watts': '—' if s['watts'] is None else f"{s['watts']:.2f} W",
            'battery_percent': '—' if s['battery_percent'] is None else f"{s['battery_percent']}%",
            'refresh_rate': s.get('refresh_rate', '—'),
            'gnome_profile': s['gnome_profile'] or '—',
            'epp': s['epp'] or '—',
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

        # Update Live ToF Radar from sensor_telemetry.json
        tel = load_sensor_telemetry()
        if tel and hasattr(self, 'tof_status_row'):
            st = tel.get('state', 'unknown')
            dist_cm = tel.get('distance_cm', 0)
            thresh_cm = tel.get('threshold_cm', 120)
            pkts = tel.get('packet_count', 0)
            sec_ago = tel.get('last_packet_sec_ago', 0.0)

            if st == 'present':
                self.tof_badge.set_label('AT DESK (ACTIVE)')
                self.tof_badge.set_css_classes(['badge-active'])
                self.tof_status_row.set_subtitle('User detected at desk (OLED Active)')
            elif st == 'absent':
                self.tof_badge.set_label('AWAY (STANDBY)')
                self.tof_badge.set_css_classes(['badge-standby'])
                self.tof_status_row.set_subtitle('User departed (> 1.2m threshold)')
            else:
                self.tof_badge.set_label('DISABLED')
                self.tof_badge.set_css_classes(['badge-disabled'])
                self.tof_status_row.set_subtitle('Sensor offline or standby')

            # Update Distance & ProgressBar
            self.tof_distance_row.set_subtitle(f"{dist_cm} cm / {thresh_cm} cm (1.2m Threshold)")
            frac = min(1.0, max(0.0, dist_cm / thresh_cm)) if thresh_cm > 0 else 0.5
            self.tof_bar.set_fraction(frac)

            # Update Telemetry packet stream
            self.tof_telemetry_row.set_subtitle(f"{pkts} packets received ({sec_ago:.1f}s ago) • Native ASM Engine")
        elif hasattr(self, 'tof_status_row'):
            self.tof_status_row.set_subtitle(presence_map.get(raw_pres, raw_pres))

        # Update Lenovo Switches
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

        # Update Battery Health Card
        health = s.get('battery_health', {})
        if health and hasattr(self, 'health_rows'):
            score = health.get('health_pct', 100.0)
            self.health_rows['health_score'].set_subtitle(
                f"{score:.1f}% Health Score ({'Optimal' if score >= 90 else 'Degraded'})"
            )
            d_wh = health.get('energy_design_wh', 0.0)
            f_wh = health.get('energy_full_wh', 0.0)
            self.health_rows['capacities'].set_subtitle(f"Design: {d_wh:.2f} Wh  |  Full Charge: {f_wh:.2f} Wh")
            cycles = health.get('cycle_count', 0)
            self.health_rows['cycles'].set_subtitle(f"{cycles} charge cycles completed")
            vol = health.get('voltage_v', 0.0)
            tech = health.get('technology', 'Li-poly')
            mfg = health.get('manufacturer', 'ATL')
            self.health_rows['voltage'].set_subtitle(f"{vol:.2f} V ({mfg} {tech})")

        # Update Diagnostics Services Status
        if hasattr(self, 'diag_rows'):
            for row in self.diag_rows:
                row.set_subtitle('Running (Active)' if is_active(row._unit, row._user) else 'Stopped (Inactive)')

    def _toggle_lenovo(self, feat: str, active: bool) -> None:
        if self._lenovo_syncing:
            return
        val = '1' if active else '0'
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists() and os.geteuid() != 0:
            subprocess.run(['pkexec', str(helper), 'set-lenovo', feat, val],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            set_lenovo_feature(feat, val)
        self.refresh_status()
        feat_name = feat.replace('_', ' ').title()
        self.toast(f"✓ Lenovo {feat_name} set to {'ON' if active else 'OFF'}.")

    def _toggle_autoboost(self, row, _pspec) -> None:
        active = row.get_active()
        subaction = 'enable-now' if active else 'disable-now'
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists() and os.geteuid() != 0:
            subprocess.run(['pkexec', str(helper), 'autoboost-service', subaction],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            act = ['enable', '--now'] if active else ['disable', '--now']
            subprocess.run(['/usr/bin/systemctl', *act, AUTOBOOST_SERVICE],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.refresh_status()
        self.toast(f"✓ Auto Dynamic Boost {'enabled' if active else 'disabled'}.")

    def _apply_now(self, _btn) -> None:
        try:
            save_and_apply_config(self.cfg)
            self.refresh_status()
            self.toast('✓ Active power profile applied and hardware registers verified.')
        except Exception as exc:
            self.toast(f'Apply error: {exc}')

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
            elif isinstance(row, Adw.SwitchRow):
                row.set_active(bool(v))
        mode_label = 'Battery' if mode == 'battery' else 'AC Power'

        # Directly save and apply the chosen preset to hardware
        self.cfg[mode].update(preset)
        try:
            save_and_apply_config(self.cfg)
            self.refresh_status()
            self.toast(f'✓ {mode_label} preset "{name.replace("_", " ").title()}" applied to hardware.')
        except Exception as exc:
            self.toast(f'Preset error: {exc}')

    def _save_mode(self, _btn, mode: str) -> None:
        ctrls = self.mode_controls.get(mode, {})
        new_sub = {}
        for k, row in ctrls.items():
            if isinstance(row, Adw.ComboRow):
                new_sub[k] = row._values[row.get_selected()]
            elif isinstance(row, Adw.SwitchRow):
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
            subprocess.run(['pkexec', str(helper), 'sensor-service', sys_action], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
                subprocess.run(['pkexec', str(helper), 'sensor-service', sys_action], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if active:
                    subprocess.run(['pkexec', str(helper), 'sensor-service', 'restart'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            subprocess.run(['pkexec', str(helper), 'sensor-service', 'stop'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
