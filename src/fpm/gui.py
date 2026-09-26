from __future__ import annotations

import json
import pathlib
import subprocess

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Adw, Gio, GLib, Gtk

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
        win = self.props.active_window
        if not win:
            win = MainWindow(self)
        win.present()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='FF Power Manager', default_width=920, default_height=760)
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
        refresh = Gtk.Button(icon_name='view-refresh-symbolic', tooltip_text='Durumu yenile')
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

        self.refresh_status()

    def toast(self, text: str) -> None:
        self.overlay.add_toast(Adw.Toast(title=text, timeout=3))

    def _action_row(self, title: str, subtitle: str = '') -> Adw.ActionRow:
        row = Adw.ActionRow(title=title)
        if subtitle:
            row.set_subtitle(subtitle)
        return row

    def _overview_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Durum', icon_name='view-dashboard-symbolic')
        group = Adw.PreferencesGroup(title='Canlı Güç ve Donanım Durumu', description='Sistem kaynaklarını tüketmemek için arka planda sürekli sorgu yapılmaz.')
        page.add(group)

        self.rows = {}
        for key, title in [
            ('mode', 'Güç Kaynağı'),
            ('watts', 'Anlık Tüketim'),
            ('battery_percent', 'Batarya Doluluğu'),
            ('refresh_rate', 'Ekran Yenileme Hızı'),
            ('gnome_profile', 'GNOME Güç Profili'),
            ('epp', 'CPU EPP Ölçeği'),
            ('turbo', 'Intel Turbo Boost'),
            ('wifi_power_save', 'Wi-Fi Güç Tasarrufu'),
            ('presence_state', 'Presence Sensör Durumu'),
        ]:
            row = self._action_row(title, '—')
            self.rows[key] = row
            group.add(row)

        actions = Adw.PreferencesGroup(title='Kontroller')
        page.add(actions)
        live = Adw.SwitchRow(title='Canlı İzleme', subtitle='Açıkken 5 saniyede bir ölçümleri canlı yeniler.')
        live.connect('notify::active', self._toggle_live)
        actions.add(live)

        apply_row = self._action_row('Mevcut Profili Yeniden Uygula', 'Aktif güç kaynağına (AC/Batarya) göre donanım politikalarını tetikler.')
        btn = Gtk.Button(label='Şimdi Uygula', valign=Gtk.Align.CENTER)
        btn.add_css_class('suggested-action')
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

        presets = Adw.PreferencesGroup(title='Hazır Profiller', description='Önceden test edilmiş güvenli ve dengeli profiller.')
        page.add(presets)
        preset_row = self._action_row('Profil Seç')
        box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        names = [('Önerilen', 'recommended')]
        if mode == 'battery':
            names += [('Maksimum Pil', 'maximum_battery'), ('Daha Tepkisel', 'responsive')]
        else:
            names += [('Performans', 'performance'), ('Serin / Sessiz', 'cool_quiet')]
        for text, name in names:
            b = Gtk.Button(label=text)
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
        save_btn.connect('clicked', self._save_mode, mode)
        save_row.add_suffix(save_btn)
        save_group.add(save_row)
        self.mode_controls[mode] = controls
        return page

    def _presence_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Ekran & Presence', icon_name='system-lock-screen-symbolic')
        
        display_grp = Adw.PreferencesGroup(title='Akıllı Ekran Yenileme (OLED)', description='Samsung 2.8K 120Hz panelde batarya kullanımını optimize eder.')
        page.add(display_grp)
        self.refresh_switch = Adw.SwitchRow(title='Dinamik Ekran Yenileme', subtitle='Pilde 60 Hz, prizde 120 Hz + VRR moduna otomatik geçer.')
        self.refresh_switch.set_active(bool(self.pcfg.get('auto_refresh_rate', True)))
        display_grp.add(self.refresh_switch)

        status = Adw.PreferencesGroup(title='Lenovo İnsan Varlığı Algılama (ToF)', description='Intel ISH 8087:0AC2 içindeki ST VL53L1 ToF sensörü. RGB kamera kesinlikle açılmaz.')
        page.add(status)
        self.presence_service_row = Adw.SwitchRow(title='Presence + OLED Otomasyonu', subtitle='Uzaklaşınca ekranı karart, yaklaşınca geri aç.')
        is_sensor_active = is_active(SYSTEM_SENSOR)
        enabled_setting = bool(self.pcfg.get('enabled', True))
        self.presence_service_row.set_active(enabled_setting and is_sensor_active)
        self.presence_service_row.connect('notify::active', self._presence_toggle)
        status.add(self.presence_service_row)

        timing = Adw.PreferencesGroup(title='Sensör Hassasiyet ve Zamanlama')
        page.add(timing)
        self.silence_spin = Gtk.SpinButton.new_with_range(4.0, 60.0, 1.0)
        self.silence_spin.set_digits(1)
        self.silence_spin.set_value(float(self.scfg.get('silence_timeout', 15.0)))
        row = self._action_row('Sensör Sessizlik Eşiği (sn)', 'Bu süre boyunca yeni hareket algılanmazsa uzaklaşma kontrolü başlar.')
        row.add_suffix(self.silence_spin)
        timing.add(row)

        self.confirm_reports_spin = Gtk.SpinButton.new_with_range(1, 5, 1)
        self.confirm_reports_spin.set_value(int(self.scfg.get('present_confirm_reports', 1)))
        row = self._action_row('Yaklaşma Doğrulama Paketleri', 'Ekranın anında açılması için gereken ToF sinyal sayısı (1 = anında açılış).')
        row.add_suffix(self.confirm_reports_spin)
        timing.add(row)

        self.away_delay_spin = Gtk.SpinButton.new_with_range(0.0, 120.0, 5.0)
        self.away_delay_spin.set_value(float(self.pcfg.get('away_delay', 10.0)))
        row = self._action_row('Uzaklaşma Bekleme Süresi (sn)', 'Sensör boş algıladıktan sonra ekranın kapanması için beklenecek süre.')
        row.add_suffix(self.away_delay_spin)
        timing.add(row)

        self.away_confirm_spin = Gtk.SpinButton.new_with_range(0.5, 30.0, 0.5)
        self.away_confirm_spin.set_digits(1)
        self.away_confirm_spin.set_value(float(self.pcfg.get('away_confirm', 3.0)))
        row = self._action_row('Uzaklaşma Kararlılık Doğrulaması (sn)', 'Ani baş hareketlerinde ekranın hemen kararmasını önleyen ek teyit süresi.')
        row.add_suffix(self.away_confirm_spin)
        timing.add(row)

        behaviour = Adw.PreferencesGroup(title='Otomasyon Davranışları')
        page.add(behaviour)
        self.presence_switches = {}
        for key, title, subtitle in [
            ('screen_off_on_away', 'Uzaklaşınca OLED Paneli Karart', 'Sistemi askıya (suspend) almaz; arka plan görevleri kesilmez.'),
            ('wake_on_approach', 'Yaklaşınca Ekranı Aç', 'Kullanıcı masaya döndüğünde ekranı aydınlatır.'),
            ('wake_only_if_fpm_off', 'Yalnız FPM Kapattıysa Aç', 'Kullanıcı ekranı elle kapattıysa ToF sensörü uyandırmaz.'),
            ('lock_on_away', 'Uzaklaşınca Oturumu Kilitle', 'İsteğe bağlı masaüstü güvenliği.'),
        ]:
            sw = Adw.SwitchRow(title=title, subtitle=subtitle)
            sw.set_active(bool(self.pcfg.get(key, DEFAULT_PRESENCE[key])))
            behaviour.add(sw)
            self.presence_switches[key] = sw

        save = Adw.PreferencesGroup()
        page.add(save)
        row = self._action_row('Ayarları Kaydet', 'Ekran ve presence ayarlarını kaydeder.')
        btn = Gtk.Button(label='Kaydet', valign=Gtk.Align.CENTER)
        btn.add_css_class('suggested-action')
        btn.connect('clicked', self._save_presence)
        row.add_suffix(btn)
        save.add(row)
        return page

    def _diagnostics_page(self) -> Adw.PreferencesPage:
        page = Adw.PreferencesPage(title='Tanılama', icon_name='utilities-system-monitor-symbolic')
        group = Adw.PreferencesGroup(title='Sistem Servisleri ve Durum')
        page.add(group)
        rows = [
            ('Güç Uygulama Servisi', 'ff-power-apply.service', False),
            ('ToF Sensör Donanım Servisi', SYSTEM_SENSOR, False),
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
        b.connect('clicked', self._safe_reset)
        reset.add_suffix(b)
        safety.add(reset)
        return page

    def _toggle_live(self, row, _pspec) -> None:
        if row.get_active() and not self.live_source:
            self.live_source = GLib.timeout_add_seconds(5, self._live_tick)
        elif not row.get_active() and self.live_source:
            GLib.source_remove(self.live_source)
            self.live_source = 0

    def _live_tick(self) -> bool:
        self.refresh_status()
        return GLib.SOURCE_CONTINUE

    def refresh_status(self) -> None:
        s = status_snapshot()
        values = {
            'mode': 'Batarya' if s['mode'] == 'battery' else 'Adaptör',
            'watts': '—' if s['watts'] is None else f"{s['watts']:.2f} W",
            'battery_percent': '—' if s['battery_percent'] is None else f"%{s['battery_percent']}",
            'refresh_rate': s.get('refresh_rate', '—'),
            'gnome_profile': s['gnome_profile'] or '—',
            'epp': s['epp'] or '—',
            'turbo': 'Açık' if s['turbo'] else ('Kapalı' if s['turbo'] is not None else '—'),
            'wifi_power_save': s['wifi_power_save'] or '—',
            'presence_state': s['presence_state'] or 'disabled',
        }
        for key, value in values.items():
            if hasattr(self, 'rows') and key in self.rows:
                self.rows[key].set_subtitle(value)
        if hasattr(self, 'diag_rows'):
            for row in self.diag_rows:
                row.set_subtitle('Aktif' if is_active(row._unit, row._user) else 'Pasif')

    def _apply_now(self, _btn) -> None:
        try:
            save_and_apply_config(self.cfg)
            self.refresh_status()
            self.toast('Aktif güç profili başarıyla uygulandı.')
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
        self.toast(f'{mode.capitalize()} için “{name}” profili yüklendi. Kaydetmeyi unutmayın.')

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
            self.toast(f'{mode_tr} ayarları başarıyla kaydedildi ve uygulandı.')
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

        self.pcfg['away_confirm'] = self.away_confirm_spin.get_value()
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
            self.toast('Ekran ve presence ayarları güncellendi ve uygulandı.')
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
            self.toast('Ayarlar fabrika ayarlarına sıfırlandı ve uygulandı.')
        except Exception as e:
            self.toast(f'Sıfırlama hatası: {e}')

def main():
    return PowerManagerApp().run(None)


if __name__ == '__main__':
    raise SystemExit(main())
