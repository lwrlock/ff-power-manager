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
            self.assertEqual(core.current_refresh_rate(), '60 Hz (Pil Tasarrufu)')

        mock_read.return_value = '2880x1800@120.000+vrr'
        with mock.patch.object(core.pathlib.Path, 'exists', return_value=True):
            self.assertEqual(core.current_refresh_rate(), '120 Hz + VRR (Akıcı)')

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


if __name__ == '__main__':
    unittest.main()
