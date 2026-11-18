import unittest
from unittest import mock

from fpm import core, sensor


class ConfigTests(unittest.TestCase):
    def test_invalid_values_are_ignored(self):
        cfg = core._merge_valid(core.DEFAULT_CONFIG, {
            'battery': {'epp': 'not-a-real-mode', 'turbo': False},
            'ac': {'gnome_profile': 'balanced'},
        })
        self.assertEqual(cfg['battery']['epp'], 'balance_power')
        self.assertFalse(cfg['battery']['turbo'])
        self.assertEqual(cfg['ac']['gnome_profile'], 'balanced')

    def test_presets_use_allowed_values(self):
        for modes in core.PRESETS.values():
            for preset in modes.values():
                for key, value in preset.items():
                    self.assertIn(value, core.ALLOWED[key])

    @mock.patch('fpm.core.glob.glob')
    @mock.patch('fpm.core.read_text')
    def test_mains_detection(self, read_text, glob_):
        glob_.side_effect = [
            ['/sys/class/power_supply/ACAD'],
            [],
        ]
        read_text.side_effect = lambda p: 'Mains' if str(p).endswith('/type') else '1'
        self.assertFalse(core.on_battery_from_sysfs())

    def test_adaptive_silence_never_below_floor(self):
        self.assertEqual(sensor.adaptive_silence_timeout(4.0, [1.0, 1.0, 1.0]), 4.0)
        self.assertGreaterEqual(sensor.adaptive_silence_timeout(4.0, [1.0, 1.1, 1.2, 2.5, 1.0]), 4.0)

    def test_adaptive_silence_expands_for_bursty_reports(self):
        value = sensor.adaptive_silence_timeout(4.0, [0.8, 0.9, 1.0, 2.8, 1.1, 1.0])
        self.assertGreater(value, 4.0)
        self.assertLessEqual(value, 60.0)

    @mock.patch('fpm.core.read_text')
    def test_current_refresh_rate_formatting(self, mock_read):
        mock_read.return_value = '2880x1800@60.000'
        with mock.patch.object(core.pathlib.Path, 'exists', return_value=True):
            self.assertEqual(core.current_refresh_rate(), '60 Hz (Power Saver)')

        mock_read.return_value = '2880x1800@120.000+vrr'
        with mock.patch.object(core.pathlib.Path, 'exists', return_value=True):
            self.assertEqual(core.current_refresh_rate(), '120 Hz + VRR (Smooth)')

    @mock.patch('fpm.core.subprocess.run')
    @mock.patch('fpm.core.pathlib.Path.exists', return_value=True)
    def test_save_and_apply_delegates_to_helper(self, mock_exists, mock_run):
        mock_proc = mock.MagicMock()
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc
        with mock.patch('os.geteuid', return_value=1000):
            core.save_and_apply_config(core.DEFAULT_CONFIG)
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            self.assertIn(args[0], ('sudo', 'pkexec'))
            self.assertIn('save-and-apply', args)


    def test_decode_report_4(self):
        # Empty or short packet returns None
        self.assertEqual(sensor.decode_report_4(b''), (None, None))
        
        # Valid packet with Report ID 4, presence = 1, distance = 750 mm (0.75m <= 1.2m)
        buf_present = bytearray(35)
        buf_present[0] = 4
        buf_present[27:29] = (750).to_bytes(2, 'little')
        buf_present[31] = 100
        buf_present[32] = 1 # present flag = 1
        is_pres, dist = sensor.decode_report_4(bytes(buf_present))
        self.assertTrue(is_pres)
        self.assertEqual(dist, 750)

        # Presence flag 1, but user stepped away to 1500 mm (1.5m > 1.2m) -> Absent!
        buf_far = bytearray(35)
        buf_far[0] = 4
        buf_far[27:29] = (1500).to_bytes(2, 'little')
        buf_far[31] = 50
        buf_far[32] = 1
        is_pres, dist = sensor.decode_report_4(bytes(buf_far))
        self.assertFalse(is_pres)
        self.assertEqual(dist, 1500)

        # Valid packet with Report ID 4 and presence = 0
        buf_absent = bytearray(35)
        buf_absent[0] = 4
        buf_absent[32] = 0
        is_pres, dist = sensor.decode_report_4(bytes(buf_absent))
        self.assertFalse(is_pres)

    @mock.patch('fpm.core.read_text')
    def test_telemetry_helpers(self, mock_read):
        # PCIe ASPM parser
        mock_read.return_value = 'default performance powersave [powersupersave]'
        self.assertEqual(core.pcie_aspm_current(), 'powersupersave')

        # TCP CC parser
        mock_read.return_value = 'bbr\n'
        self.assertEqual(core.tcp_cc_current(), 'BBR (Google Low Latency)')

        # ZRAM parser
        mock_read.return_value = '[zstd] lzo-rle lzo lz4'
        with mock.patch('os.path.exists', return_value=True):
            self.assertEqual(core.zram_current(), 'ZRAM (zstd) Active')

    @mock.patch('fpm.core.read_text')
    def test_gpu_min_freq_helper(self, mock_read):
        mock_read.return_value = '800\n'
        self.assertIn('800 MHz', core.gpu_min_freq_current())

    def test_lenovo_and_battery_health_structures(self):
        lenovo = core.get_lenovo_features()
        self.assertIsInstance(lenovo, dict)
        self.assertIn('supported', lenovo)
        self.assertIn('conservation_mode', lenovo)

    def test_apply_extreme_performance_profile(self):
        with mock.patch('fpm.core.set_profile'), \
             mock.patch('fpm.core.set_epp') as mock_epp, \
             mock.patch('fpm.core.set_turbo'), \
             mock.patch('fpm.core.set_cpu_freq_floor') as mock_cpu, \
             mock.patch('fpm.core.set_gpu') as mock_gpu, \
             mock.patch('fpm.core.set_wifi_ps'), \
             mock.patch('fpm.core.set_nvme'), \
             mock.patch('fpm.core.set_pcie_aspm'), \
             mock.patch('fpm.core.apply_kernel_tunings'):
            core.apply('extreme_performance', core.DEFAULT_CONFIG)
            mock_epp.assert_called_with('performance')
            mock_cpu.assert_called_with('extreme_performance')
            mock_gpu.assert_called_with('auto', 'extreme_performance')

    @mock.patch('glob.glob')
    @mock.patch('builtins.open', new_callable=mock.mock_open, read_data='cyberpunk2077.e\n')
    def test_auto_boost_detects_exe_games(self, mock_file, mock_glob):
        from fpm import auto_boost
        mock_glob.return_value = ['/proc/12345/comm']
        detected = auto_boost.find_heavy_process()
        self.assertEqual(detected, 'cyberpunk2077.e')

    @mock.patch('glob.glob')
    @mock.patch('builtins.open', new_callable=mock.mock_open, read_data='llama-server\n')
    def test_auto_boost_llama_server_idle_aware(self, mock_file, mock_glob):
        from fpm import auto_boost
        mock_glob.return_value = ['/proc/54321/comm']
        # Idle llama-server (< 10% CPU) should NOT trigger boost, active (>= 10% CPU) should
        self.assertIsNone(auto_boost.find_heavy_process(cpu_usage=2.5))
        self.assertEqual(auto_boost.find_heavy_process(cpu_usage=42.0), 'llama-server')

    @mock.patch('os.setpriority')
    @mock.patch('os.getpriority', return_value=0)
    @mock.patch('fpm.core.glob.glob', return_value=['/proc/3684/comm'])
    @mock.patch('builtins.open', new_callable=mock.mock_open, read_data='antigravity\n')
    def test_optimize_desktop_responsiveness(self, mock_file, mock_glob, mock_getprio, mock_setprio):
        core.optimize_desktop_responsiveness()
        mock_setprio.assert_called_once_with(core.os.PRIO_PROCESS, 3684, -8)

    def test_presence_config_includes_media_inhibit(self):
        from fpm import presence
        cfg = presence.load_config()
        self.assertIn('inhibit_on_media', cfg)
        self.assertTrue(cfg['inhibit_on_media'])

    def test_presence_is_media_active_detection(self):
        from fpm import presence
        with mock.patch('gi.repository.Gio.bus_get_sync') as mock_bus_sync, \
             mock.patch('gi.repository.Gio.File.new_for_path'), \
             mock.patch('pathlib.Path.read_text', return_value='present'):
            mock_session = mock.MagicMock()
            mock_bus_sync.return_value = mock_session

            # Create dummy PresenceController
            with mock.patch.object(presence.PresenceController, '_fs_changed'), \
                 mock.patch.object(presence.PresenceController, '_set_dimming'), \
                 mock.patch.object(presence.PresenceController, '_read_state'), \
                 mock.patch.object(presence.PresenceController, '_read_power_mode_once'), \
                 mock.patch('gi.repository.GLib.timeout_add_seconds'):
                ctrl = presence.PresenceController()

            # Test 1: Active MPRIS player returns True
            mock_list = mock.MagicMock()
            mock_list.unpack.return_value = (['org.mpris.MediaPlayer2.vlc'],)
            mock_prop = mock.MagicMock()
            mock_prop.unpack.return_value = ('Playing',)
            mock_session.call_sync.side_effect = [mock_list, mock_prop]

            self.assertTrue(ctrl._is_media_active())

            # Test 2: Inactive MPRIS, no inhibitors, and no RUNNING /proc/asound PCM returns False
            mock_list.unpack.return_value = ()
            mock_session.call_sync.side_effect = [
                mock_list, # ListNames
                mock.MagicMock(unpack=lambda: ([],)), # GetInhibitors
            ]
            with mock.patch('pathlib.Path.glob', return_value=[]):
                self.assertFalse(ctrl._is_media_active())

    @mock.patch('fpm.core.glob.glob', return_value=[])
    @mock.patch('fpm.core.write_if_changed')
    def test_apply_kernel_tunings_syncs_byte_writeback_and_vm(self, mock_write, mock_glob):
        core.apply_kernel_tunings('ac')
        calls = {c.args[0]: c.args[1] for c in mock_write.call_args_list}
        self.assertEqual(calls['/proc/sys/vm/dirty_background_bytes'], '67108864')
        self.assertEqual(calls['/proc/sys/vm/dirty_bytes'], '268435456')
        self.assertEqual(calls['/proc/sys/vm/dirty_writeback_centisecs'], '500')
        self.assertEqual(calls['/proc/sys/vm/swappiness'], '40')
        self.assertEqual(calls['/proc/sys/vm/vfs_cache_pressure'], '100')
        self.assertEqual(calls['/proc/sys/vm/extfrag_threshold'], '750')
        self.assertEqual(calls['/sys/kernel/mm/lru_gen/min_ttl_ms'], '1000')

    @mock.patch('fpm.core.write_if_changed')
    @mock.patch('fpm.core.read_text')
    @mock.patch('fpm.core.os.path.exists', return_value=True)
    @mock.patch('fpm.core.glob.glob')
    def test_set_gpu_clamps_min_freq_to_rpn_and_uses_power_saving_on_battery(
        self, mock_glob, _mock_exists, mock_read, mock_write
    ):
        mock_glob.side_effect = [
            [],
            ['/sys/devices/pci0000:00/0000:00:02.0/tile0/gt0/freq0'],
            [],
        ]
        mock_read.side_effect = lambda p: '800' if str(p).endswith('rpn_freq') else '2350'
        core.set_gpu('auto', 'battery')
        calls = {c.args[0]: c.args[1] for c in mock_write.call_args_list}
        base = '/sys/devices/pci0000:00/0000:00:02.0/tile0/gt0/freq0'
        self.assertEqual(calls[f'{base}/power_profile'], 'power_saving')
        self.assertEqual(calls[f'{base}/min_freq'], '800')
        self.assertEqual(calls[f'{base}/max_freq'], '1600')

    @mock.patch('fpm.core.write_if_changed')
    @mock.patch('fpm.core.read_text')
    @mock.patch('fpm.core.glob.glob')
    def test_pci_runtime_pm_allows_thunderbolt_and_empty_usb_auto(self, mock_glob, mock_read, mock_write):
        def fake_glob(pattern):
            if pattern == '/sys/bus/pci/devices/*/power/control':
                return [
                    '/sys/bus/pci/devices/0000:00:0d.2/power/control',
                    '/sys/bus/pci/devices/0000:00:0d.0/power/control',
                    '/sys/bus/pci/devices/0000:00:14.0/power/control',
                ]
            if '0000:00:14.0' in pattern:
                return ['/sys/bus/pci/devices/0000:00:14.0/usb3/3-10']
            return []

        mock_glob.side_effect = fake_glob
        mock_read.side_effect = lambda p: '0x0c0340' if '0d.2' in str(p) else '0x0c0330'
        core.set_pci_runtime_pm('auto')
        calls = {c.args[0]: c.args[1] for c in mock_write.call_args_list}
        self.assertEqual(calls['/sys/bus/pci/devices/0000:00:0d.2/power/control'], 'auto')
        self.assertEqual(calls['/sys/bus/pci/devices/0000:00:0d.0/power/control'], 'auto')
        self.assertEqual(calls['/sys/bus/pci/devices/0000:00:14.0/power/control'], 'on')

    @mock.patch('fpm.core.write_if_changed')
    def test_set_rapl_limits_battery_boost(self, mock_write):
        with mock.patch.object(core.pathlib.Path, 'exists', return_value=True), \
             mock.patch.object(core.pathlib.Path, 'glob', return_value=[core.pathlib.Path('/sys/class/powercap/intel-rapl/intel-rapl:0')]):
            core.set_rapl_limits('battery_boost')
            calls = {str(c.args[0]): c.args[1] for c in mock_write.call_args_list}
            self.assertEqual(calls[str(core.PLATFORM_PROFILE_PATH)], 'balanced')
            self.assertEqual(calls['/sys/class/powercap/intel-rapl/intel-rapl:0/constraint_0_power_limit_uw'], '35000000')
            self.assertEqual(calls['/sys/class/powercap/intel-rapl/intel-rapl:0/constraint_1_power_limit_uw'], '55000000')

    def test_detect_cpu_topology_universal(self):
        # 3-tier hybrid (Intel Core Ultra Arrow Lake: 6 P, 8 E, 2 LP-E)
        fake_freqs = {}
        for i in range(6): fake_freqs[f'/sys/devices/system/cpu/cpu{i}/cpufreq/cpuinfo_max_freq'] = '5400000'
        for i in range(6, 14): fake_freqs[f'/sys/devices/system/cpu/cpu{i}/cpufreq/cpuinfo_max_freq'] = '4500000'
        for i in range(14, 16): fake_freqs[f'/sys/devices/system/cpu/cpu{i}/cpufreq/cpuinfo_max_freq'] = '2500000'

        with mock.patch('fpm.core.glob.glob', side_effect=[list(fake_freqs.keys()), []]):
            with mock.patch.object(core.pathlib.Path, 'read_text', lambda p, *a, **kw: fake_freqs[str(p)]):
                p_c, e_c, lpe_c = core.detect_cpu_topology()
                self.assertEqual(p_c, [0, 1, 2, 3, 4, 5])
                self.assertEqual(e_c, [6, 7, 8, 9, 10, 11, 12, 13])
                self.assertEqual(lpe_c, [14, 15])

        # Symmetric AMD Ryzen / non-hybrid 8-core
        sym_freqs = {f'/sys/devices/system/cpu/cpu{i}/cpufreq/cpuinfo_max_freq': '5100000' for i in range(8)}
        with mock.patch('fpm.core.glob.glob', side_effect=[list(sym_freqs.keys()), []]):
            with mock.patch.object(core.pathlib.Path, 'read_text', lambda p, *a, **kw: sym_freqs[str(p)]):
                p_c, e_c, lpe_c = core.detect_cpu_topology()
                self.assertEqual(p_c, list(range(8)))
                self.assertEqual(e_c, [])
                self.assertEqual(lpe_c, [])

    def test_apply_cool_quiet_and_max_battery_modes(self):
        with mock.patch('fpm.core.set_profile') as mock_prof, \
             mock.patch('fpm.core.set_epp') as mock_epp, \
             mock.patch('fpm.core.set_turbo') as mock_turbo, \
             mock.patch('fpm.core.set_hwp_dynamic_boost'), \
             mock.patch('fpm.core.set_cpu_freq_floor'), \
             mock.patch('fpm.core.set_wifi_ps'), \
             mock.patch('fpm.core.set_nvme'), \
             mock.patch('fpm.core.set_pci_runtime_pm'), \
             mock.patch('fpm.core.set_gpu'), \
             mock.patch('fpm.core.set_pcie_aspm') as mock_aspm, \
             mock.patch('fpm.core.set_usb'), \
             mock.patch('fpm.core.set_audio'), \
             mock.patch('fpm.core.apply_kernel_tunings'), \
             mock.patch('fpm.core.set_rapl_limits'), \
             mock.patch('fpm.core.optimize_sd_card'), \
             mock.patch('fpm.core.optimize_desktop_responsiveness'), \
             mock.patch('fpm.core.pin_interactive_irqs'):
            core.apply('cool_quiet', core.DEFAULT_CONFIG)
            mock_prof.assert_called_with('balanced')
            mock_epp.assert_called_with('balance_power')

            core.apply('max_battery', core.DEFAULT_CONFIG)
            mock_prof.assert_called_with('power-saver')
            mock_epp.assert_called_with('power')
            mock_turbo.assert_called_with(False)
            mock_aspm.assert_called_with('powersupersave')


if __name__ == '__main__':
    unittest.main()
