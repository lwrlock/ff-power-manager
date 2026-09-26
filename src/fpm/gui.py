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
    PRESETS,
)

USER_CFG = pathlib.Path.home() / '.config/ff-power-manager/presence.json'
SYSTEM_SENSOR = 'ff-presence-sensor.service'
USER_PRESENCE = 'ff-presence-session.service'
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
}

CUSTOM_CSS = b"""
.card-hero {
    background: alpha(@theme_selected_bg_color, 0.12);
    border-radius: 12px;
    border: 1px solid alpha(@theme_selected_bg_color, 0.25);
    padding: 10px;
}
.badge-active {
    background-color: alpha(@success_color, 0.2);
    color: @success_color;
    border-radius: 9999px;
    padding: 3px 10px;
    font-weight: bold;
}
.badge-standby {
    background-color: alpha(@warning_color, 0.2);
    color: @warning_color;
    border-radius: 9999px;
    padding: 3px 10px;
    font-weight: bold;
}
.badge-disabled {
    background-color: alpha(@view_fg_color, 0.1);
    color: alpha(@view_fg_color, 0.6);
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
        super().__init__(application=app, title='FF Power Manager', default_width=940, default_height=780)
        self.cfg = load_config()
        self.scfg = load_sensor_config()
        self.pcfg = load_user_presence()
        self.live_source = 0
        self.mode_controls = {}
        self._presence_syncing = False

        self.overlay = Adw.ToastOverlay()
        self.set_content(self.overlay)
        toolbar = Adw.ToolbarView()
        self.overlay.set_child(toolbar)

        self.stack = Adw.ViewStack()
        title = Adw.ViewSwitcherTitle(stack=self.stack, title='FF Power Manager')
        header = Adw.HeaderBar(title_widget=title)

        # Launch TUI button in header bar
        tui_btn = Gtk.Button(icon_name='utilities-terminal-symbolic', tooltip_text='btop Tarzı Terminal Panelini Aç (ff-tui)')
        tui_btn.add_css_class('flat')
        tui_btn.connect('clicked', lambda *_: self._launch_tui())
        header.pack_start(tui_btn)

        # Refresh button in header bar
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Durumu Yenile')
        refresh.add_css_class('flat')
        refresh.connect('clicked', lambda *_: self.refresh_status())
        header.pack_end(refresh)

        toolbar.add_top_bar(header)
        toolbar.set_content(self.stack)

        switcher = Adw.ViewSwitcherBar(stack=self.stack)
        switcher.set_reveal(True)
        toolbar.add_bottom_bar(switcher)

        self.stack.add_titled_with_icon(self._overview_page(), 'overview', 'Durum', 'view-dashboard-symbolic')
        self.stack.add_titled_with_icon(self._mode_page('battery'), 'battery', 'Batarya', 'battery-good-symbolic')
        self.stack.add_titled_with_icon(self._mode_page('ac'), 'ac', 'Adaptör', 'power-profile-performance-symbolic')
        self.stack.add_titled_with_icon(self._presence_page(), 'presence', 'Ekran & Presence', 'system-lock-screen-symbolic')
        self.stack.add_titled_with_icon(self._diagnostics_page(), 'diagnostics', 'Tanılama', 'utilities-system-monitor-symbolic')

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
                self.toast('Terminal Dashboard (ff-tui) açıldı.')
                break
            except (FileNotFoundError, OSError):
                continue
        if not launched:
            self.toast('Terminal açılamadı. Terminalde "ff-tui" çalıştırabilirsiniz.')

    def _overview_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Durum', icon_name='view-dashboard-symbolic')

        # Hero Banner: Quick TUI Launch
        hero_group = Adw.PreferencesGroup()
        page.add(hero_group)

        hero_row = Adw.ActionRow(
            title='Terminal Dashboard (C & x86_64 Assembly Engine)',
            subtitle='btop tarzı dinamik sekmeli arayüz, canlı ToF radarı ve 0.0% CPU yükü.'
        )
        hero_row.add_css_class('card-hero')
        hero_row.add_prefix(Gtk.Image.new_from_icon_name('utilities-terminal-symbolic'))

        open_tui_btn = Gtk.Button(label='TUI’yi Aç', valign=Gtk.Align.CENTER)
        open_tui_btn.add_css_class('suggested-action')
        open_tui_btn.add_css_class('pill-btn')
        open_tui_btn.connect('clicked', lambda *_: self._launch_tui())
        hero_row.add_suffix(open_tui_btn)
        hero_group.add(hero_row)

        # Group 1: Real-time Power & Hardware Status
        group = Adw.PreferencesGroup(
            title='Canlı Güç ve Donanım Durumu',
            description='Kernel sysfs donanım yazmaçlarından doğrudan okunur.'
        )
        page.add(group)

        self.rows = {}
        for key, title, icon in [
            ('mode', 'Güç Kaynağı', 'ac-adapter-symbolic'),
            ('watts', 'Anlık Tüketim', 'energy-battery-symbolic'),
            ('battery_percent', 'Batarya Doluluğu', 'battery-level-80-symbolic'),
            ('refresh_rate', 'Ekran Yenileme Hızı', 'video-display-symbolic'),
            ('gnome_profile', 'GNOME Güç Profili', 'preferences-system-symbolic'),
            ('epp', 'CPU EPP Ölçeği', 'applications-science-symbolic'),
            ('turbo', 'Intel Turbo Boost', 'speedometer-symbolic'),
            ('pcie_aspm', 'PCIe ASPM Tasarruf', 'drive-harddisk-symbolic'),
        ]:
            row = self._action_row(title, '—', icon)
            self.rows[key] = row
            group.add(row)

        # Group 2: ST VL53L1 ToF Presence Radar
        radar_group = Adw.PreferencesGroup(
            title='ST VL53L1 ToF Varlık Radarı & Mesafe',
            description='Lenovo Intel ISH kızılötesi sensörü (0.0% CPU yükü, milimetre hassasiyet).'
        )
        page.add(radar_group)

        self.tof_status_row = self._action_row('Sensör Durumu', 'Algılanıyor...', 'system-lock-screen-symbolic')
        self.tof_badge = Gtk.Label(label='BEKLENİYOR')
        self.tof_badge.add_css_class('badge-standby')
        self.tof_badge.set_valign(Gtk.Align.CENTER)
        self.tof_status_row.add_suffix(self.tof_badge)
        radar_group.add(self.tof_status_row)

        self.tof_distance_row = self._action_row('Ekrana Olan Canlı Mesafe', 'Ölçülüyor...', 'camera-photo-symbolic')
        self.tof_bar = Gtk.ProgressBar(valign=Gtk.Align.CENTER)
        self.tof_bar.set_size_request(140, -1)
        self.tof_bar.set_fraction(0.5)
        self.tof_distance_row.add_suffix(self.tof_bar)
        radar_group.add(self.tof_distance_row)

        self.tof_telemetry_row = self._action_row('Telemetri Akışı', 'Paketler bekleniyor...', 'network-transmit-receive-symbolic')
        radar_group.add(self.tof_telemetry_row)

        # Group 3: Quick Action Controls
        actions = Adw.PreferencesGroup(title='Hızlı Kontroller')
        page.add(actions)

        apply_row = self._action_row('Mevcut Profili Yeniden Uygula', 'Aktif güç kaynağına (AC/Batarya) göre donanım politikalarını tetikler ve doğrular.')
        btn = Gtk.Button(label='Şimdi Uygula', valign=Gtk.Align.CENTER)
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
        label = 'Batarya' if mode == 'battery' else 'Adaptör'
        icon = 'battery-good-symbolic' if mode == 'battery' else 'power-profile-performance-symbolic'
        page = Adw.PreferencesPage(title=label, icon_name=icon)

        presets = Adw.PreferencesGroup(title='Hazır Profiller', description='Donanım için test edilmiş dengeli profiller.')
        page.add(presets)
        preset_row = self._action_row('Profil Seç')
        box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        names = [('Önerilen', 'recommended')]
        if mode == 'battery':
            names += [('Maksimum Pil', 'maximum_battery'), ('Daha Tepkisel', 'responsive')]
        else:
            names += [('Performans', 'performance'), ('Serin / Sessiz', 'cool_quiet')]
        for text, name in names:
            b = Gtk.Button(label=text)
            b.add_css_class('pill-btn')
            b.connect('clicked', self._apply_preset, mode, name)
            box.append(b)
        preset_row.add_suffix(box)
        presets.add(preset_row)

        core_group = Adw.PreferencesGroup(title='Temel Güç Ayarları')
        page.add(core_group)
        s = self.cfg[mode]
        controls = {}

        p_row = self._combo_row('GNOME Güç Profili', ['system', 'power-saver', 'balanced', 'performance'], s['gnome_profile'])
        controls['gnome_profile'] = p_row
        core_group.add(p_row)

        epp_row = self._combo_row('CPU EPP (Enerji/Performans)', ['system', 'power', 'balance_power', 'balance_performance', 'performance'], s['epp'])
        controls['epp'] = epp_row
        core_group.add(epp_row)

        turbo_row = Adw.SwitchRow(title='Intel Turbo Boost', subtitle='Kapatılması ağır işlerde gecikmeye yol açabilir; önerilen açıktır.')
        turbo_row.set_active(bool(s['turbo']))
        controls['turbo'] = turbo_row
        core_group.add(turbo_row)

        wifi_row = Adw.SwitchRow(title='Wi-Fi Güç Tasarrufu', subtitle='İnternet boştayken kablosuz yongayı uykuya geçirir.')
        wifi_row.set_active(bool(s['wifi_power_save']))
        controls['wifi_power_save'] = wifi_row
        core_group.add(wifi_row)

        advanced = Adw.PreferencesGroup(title='Gelişmiş Donanım Güç Yönetimi')
        page.add(advanced)
        specs = [
            ('hwp_dynamic_boost', 'HWP Dynamic Boost', ['system', 'off', 'on']),
            ('nvme_runtime_pm', 'NVMe Runtime PM', ['system', 'auto', 'on']),
            ('gpu_runtime_pm', 'Intel GPU Runtime PM', ['system', 'auto', 'on']),
            ('pcie_aspm', 'PCIe ASPM', ['system', 'default', 'powersave', 'powersupersave', 'performance']),
            ('usb_autosuspend', 'USB Autosuspend', ['system', 'auto']),
            ('audio_powersave', 'Ses Kartı Güç Tasarrufu', ['system', 'on', 'off']),
        ]
        for key, title, vals in specs:
            row = self._combo_row(title, vals, s[key])
            controls[key] = row
            advanced.add(row)

        save_group = Adw.PreferencesGroup()
        page.add(save_group)
        save_row = self._action_row(f'{label} Ayarlarını Kaydet', 'Yapılan değişiklikler aktif güç kaynağında anında geçerli olur.')
        save_btn = Gtk.Button(label='Kaydet ve Uygula', valign=Gtk.Align.CENTER)
        save_btn.add_css_class('suggested-action')
        save_btn.add_css_class('pill-btn')
        save_btn.connect('clicked', self._save_mode, mode)
        save_row.add_suffix(save_btn)
        save_group.add(save_row)
        self.mode_controls[mode] = controls
        return page

    def _presence_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Ekran & Presence', icon_name='system-lock-screen-symbolic')
        
        display_grp = Adw.PreferencesGroup(title='Akıllı Ekran Yenileme (Samsung 2.8K OLED)', description='Batarya kullanımını ve akıcılığı optimize eder.')
        page.add(display_grp)
        self.refresh_switch = Adw.SwitchRow(title='Dinamik Ekran Yenileme', subtitle='Pilde 60 Hz, prizde 120 Hz + VRR moduna otomatik geçer.')
        self.refresh_switch.set_active(bool(self.pcfg.get('auto_refresh_rate', True)))
        display_grp.add(self.refresh_switch)

        status = Adw.PreferencesGroup(title='Lenovo İnsan Varlığı Algılama (ToF)', description='ST VL53L1 ToF sensörü (0.0% CPU yükü). Kamera kesinlikle kullanılmaz.')
        page.add(status)
        self.presence_service_row = Adw.SwitchRow(title='Presence + OLED Otomasyonu', subtitle='Uzaklaşınca ekranı karart, yaklaşınca geri aç.')
        is_sensor_active = is_active(SYSTEM_SENSOR)
        enabled_setting = bool(self.pcfg.get('enabled', True))
        self.presence_service_row.set_active(enabled_setting and is_sensor_active)
        self.presence_service_row.connect('notify::active', self._presence_toggle)
        status.add(self.presence_service_row)

        tuning = Adw.PreferencesGroup(title='Zaman Aşımı ve Mesafe Yapılandırması')
        page.add(tuning)

        self.silence_spin = Gtk.SpinButton.new_with_range(5.0, 90.0, 1.0)
        self.silence_spin.set_value(float(self.scfg.get('silence_timeout', 30.0)))
        silence_row = self._action_row('Sensör Sessizlik Eşiği (saniye)', 'Kullanıcı hareketsiz kaldığında ekranın hemen kapanmasını önler (Önerilen 30 sn).')
        silence_row.add_suffix(self.silence_spin)
        tuning.add(silence_row)

        self.confirm_reports_spin = Gtk.SpinButton.new_with_range(1, 5, 1)
        self.confirm_reports_spin.set_value(int(self.scfg.get('present_confirm_reports', 1)))
        confirm_row = self._action_row('Geliş Doğrulama Rapor Sayısı', 'Kullanıcı masaya yaklaştığında kaç paketle ekranın anında uyanacağını belirler (Önerilen 1).')
        confirm_row.add_suffix(self.confirm_reports_spin)
        tuning.add(confirm_row)

        self.away_delay_spin = Gtk.SpinButton.new_with_range(3, 120, 1)
        self.away_delay_spin.set_value(int(self.pcfg.get('away_delay', 10)))
        delay_row = self._action_row('Masadan Ayrılma Gecikmesi (sn)', 'Sensör uzaklaşma bildirdikten sonra ekranı karartmak için beklenecek süre.')
        delay_row.add_suffix(self.away_delay_spin)
        tuning.add(delay_row)

        self.presence_switches = {}
        for key, title, sub, defval in [
            ('wake_on_approach', 'Yaklaşınca Anında Uyandır', 'Masaya oturduğunuz anda OLED ekranı açar.', True),
            ('screen_off_on_away', 'Uzaklaşınca Ekranı Kapat', '1.2 metreden uzaklaştığınızda paneli kapatıp güç tasarrufu sağlar.', True),
            ('lock_on_away', 'Uzaklaşınca Ekranı Kilitle', 'Güvenlik için ekran karardığında GNOME oturumunu kilitler.', False),
        ]:
            sw = Adw.SwitchRow(title=title, subtitle=sub)
            sw.set_active(bool(self.pcfg.get(key, defval)))
            self.presence_switches[key] = sw
            tuning.add(sw)

        save_group = Adw.PreferencesGroup()
        page.add(save_group)
        save_btn = Gtk.Button(label='Sensör Ayarlarını Kaydet', valign=Gtk.Align.CENTER)
        save_btn.add_css_class('suggested-action')
        save_btn.add_css_class('pill-btn')
        save_btn.connect('clicked', self._save_presence)
        save_row = self._action_row('Ayarları Uygula', 'Değişiklikleri kaydeder ve ToF donanım servisini günceller.')
        save_row.add_suffix(save_btn)
        save_group.add(save_row)

        return page

    def _diagnostics_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Tanılama', icon_name='utilities-system-monitor-symbolic')
        group = Adw.PreferencesGroup(title='Sistem Servisleri ve Durum')
        page.add(group)
        rows = [
            ('Güç Uygulama Servisi', 'ff-power-apply.service', False),
            ('ToF Sensör Donanım Servisi (Native C/ASM)', SYSTEM_SENSOR, False),
            ('GNOME Presence ve Ekran Servisi', USER_PRESENCE, True),
        ]
        self.diag_rows = []
        for title, unit, user in rows:
            row = self._action_row(title)
            row._unit = unit
            row._user = user
            group.add(row)
            self.diag_rows.append(row)

        safety = Adw.PreferencesGroup(title='Güvenlik ve Varsayılanlar')
        page.add(safety)
        reset = self._action_row('Önerilen Ayarlara Sıfırla', 'Tüm konfigürasyonları test edilmiş optimum fabrika ayarlarına döndürür.')
        b = Gtk.Button(label='Sıfırla', valign=Gtk.Align.CENTER)
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
            'present': 'Kullanıcı Masada (Algılandı)',
            'absent': 'Kullanıcı Uzakta (Beklemede)',
            'disabled': 'Devre Dışı',
            'unknown': 'Algılanıyor...',
            'error': 'Sensör Hatası',
        }
        raw_pres = s.get('presence_state') or 'disabled'

        values = {
            'mode': 'Batarya (Deşarj)' if s['mode'] == 'battery' else 'Adaptör (Şebeke Online)',
            'watts': '—' if s['watts'] is None else f"{s['watts']:.2f} W",
            'battery_percent': '—' if s['battery_percent'] is None else f"%{s['battery_percent']}",
            'refresh_rate': s.get('refresh_rate', '—'),
            'gnome_profile': s['gnome_profile'] or '—',
            'epp': s['epp'] or '—',
            'turbo': 'Açık (Dynamic Boost)' if s['turbo'] else ('Kapalı' if s['turbo'] is not None else '—'),
            'pcie_aspm': s.get('pcie_aspm', '—'),
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
                self.tof_badge.set_label('MASADA (AKTİF)')
                self.tof_badge.set_css_classes(['badge-active'])
                self.tof_status_row.set_subtitle('Kullanıcı masada algılandı (OLED Açık)')
            elif st == 'absent':
                self.tof_badge.set_label('UZAKTA (BEKLEMEDE)')
                self.tof_badge.set_css_classes(['badge-standby'])
                self.tof_status_row.set_subtitle('Kullanıcı masadan uzaklaştı (> 1.2m)')
            else:
                self.tof_badge.set_label('DEVRE DIŞI')
                self.tof_badge.set_css_classes(['badge-disabled'])
                self.tof_status_row.set_subtitle('Sensör kapalı veya bekleniyor')

            # Update Distance & ProgressBar
            self.tof_distance_row.set_subtitle(f"{dist_cm} cm / {thresh_cm} cm (1.2m Masa Eşiği)")
            frac = min(1.0, max(0.0, dist_cm / thresh_cm)) if thresh_cm > 0 else 0.5
            self.tof_bar.set_fraction(frac)

            # Update Telemetry packet stream
            self.tof_telemetry_row.set_subtitle(f"{pkts} paket alındı ({sec_ago:.1f} sn önce) • C/Assembly Motoru")
        elif hasattr(self, 'tof_status_row'):
            self.tof_status_row.set_subtitle(presence_map.get(raw_pres, raw_pres))

        if hasattr(self, 'diag_rows'):
            for row in self.diag_rows:
                row.set_subtitle('Çalışıyor (Aktif)' if is_active(row._unit, row._user) else 'Durduruldu (Pasif)')

    def _apply_now(self, _btn) -> None:
        try:
            save_and_apply_config(self.cfg)
            self.refresh_status()
            self.toast('✓ Aktif güç profili uygulandı ve donanımda doğrulandı.')
        except Exception as exc:
            self.toast(f'Uygulama hatası: {exc}')

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
        preset_tr = {
            'recommended': 'Önerilen',
            'maximum_battery': 'Maksimum Pil',
            'responsive': 'Daha Tepkisel',
            'performance': 'Performans',
            'cool_quiet': 'Serin / Sessiz',
        }
        mode_label = 'Batarya' if mode == 'battery' else 'Adaptör'
        preset_label = preset_tr.get(name, name)
        self.toast(f'{mode_label} için “{preset_label}” profili seçildi.')

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
            mode_tr = 'Batarya' if mode == 'battery' else 'Adaptör'
            self.toast(f'✓ {mode_tr} ayarları başarıyla kaydedildi ve uygulandı.')
        except Exception as e:
            self.toast(f'Kaydetme hatası: {e}')

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
            self.toast(f'Sensör ayar hatası: {exc}')
            return

        self.pcfg['away_delay'] = int(self.away_delay_spin.get_value())
        self.pcfg['auto_refresh_rate'] = self.refresh_switch.get_active()
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
            self.toast('✓ Ekran ve presence ayarları güncellendi ve uygulandı.')
        except Exception as e:
            self.toast(f'Hata: {e}')

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
            self.toast('✓ Ayarlar optimum fabrika ayarlarına sıfırlandı.')
        except Exception as e:
            self.toast(f'Sıfırlama hatası: {e}')


def main():
    return PowerManagerApp().run(None)


if __name__ == '__main__':
    raise SystemExit(main())
