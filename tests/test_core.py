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
            self.assertEqual(args[0], 'pkexec')
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
            mock_gpu.assert_called_with('system', 'extreme_performance')

    @mock.patch('glob.glob')
    @mock.patch('builtins.open', new_callable=mock.mock_open, read_data='cyberpunk2077.e\n')
    def test_auto_boost_detects_exe_games(self, mock_file, mock_glob):
        from fpm import auto_boost
        mock_glob.return_value = ['/proc/12345/comm']
        detected = auto_boost.find_heavy_process()
        self.assertEqual(detected, 'cyberpunk2077.e')

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

            # Test 2: Inactive MPRIS and no inhibitors returns False
            mock_list.unpack.return_value = ()
            mock_session.call_sync.side_effect = [
                mock_list, # ListNames
                mock.MagicMock(unpack=lambda: ([],)), # GetInhibitors
            ]
            with mock.patch('subprocess.run', return_value=mock.MagicMock(stdout='SUSPENDED')):
                self.assertFalse(ctrl._is_media_active())


if __name__ == '__main__':
    unittest.main()
