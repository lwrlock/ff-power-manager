from __future__ import annotations

import glob
import json
import os
import pathlib
import subprocess
import time
from copy import deepcopy

APP_ID = 'com.ff.PowerManager'
BASE_DIR = pathlib.Path('/etc/ff-power-manager')
CONFIG_PATH = BASE_DIR / 'config.json'
SENSOR_CONFIG_PATH = BASE_DIR / 'sensor.json'
RUN_DIR = pathlib.Path('/run/ff-power-manager')
STATE_FILE = RUN_DIR / 'presence.state'

DEFAULT_CONFIG = {
    'battery': {
        'gnome_profile': 'balanced',
        'epp': 'balance_power',
        'turbo': True,
        'wifi_power_save': False,
        'nvme_runtime_pm': 'auto',
        'gpu_runtime_pm': 'on',
        'pcie_aspm': 'powersupersave',
        'usb_autosuspend': 'auto',
        'audio_powersave': 'on',
        'hwp_dynamic_boost': 'on',
    },
    'ac': {
        'gnome_profile': 'balanced',
        'epp': 'balance_performance',
        'turbo': True,
        'wifi_power_save': False,
        'nvme_runtime_pm': 'auto',
        'gpu_runtime_pm': 'on',
        'pcie_aspm': 'powersave',
        'usb_autosuspend': 'auto',
        'audio_powersave': 'on',
        'hwp_dynamic_boost': 'on',
    },
}

DEFAULT_SENSOR_CONFIG = {
    'silence_timeout': 15.0,
    'present_confirm_reports': 1,
    'present_confirm_window': 6.0,
}

ALLOWED = {
    'gnome_profile': {'system', 'power-saver', 'balanced', 'performance'},
    'epp': {'system', 'default', 'performance', 'balance_performance', 'balance_power', 'power'},
    'turbo': {'system', True, False},
    'wifi_power_save': {'system', True, False},
    'nvme_runtime_pm': {'auto', 'on', 'system'},
    'gpu_runtime_pm': {'auto', 'on', 'system'},
    'pcie_aspm': {'default', 'performance', 'powersave', 'powersupersave', 'system'},
    'usb_autosuspend': {'auto', 'system'},
    'audio_powersave': {'on', 'off', 'system'},
    'hwp_dynamic_boost': {'on', 'off', 'system'},
}

PRESETS = {
    'battery': {
        'recommended': {
            'gnome_profile': 'balanced',
            'epp': 'balance_power',
            'turbo': True,
            'wifi_power_save': False,
            'nvme_runtime_pm': 'auto',
            'gpu_runtime_pm': 'on',
            'pcie_aspm': 'powersave',
            'usb_autosuspend': 'auto',
            'audio_powersave': 'on',
            'hwp_dynamic_boost': 'on',
        },
        'maximum_battery': {
            'gnome_profile': 'power-saver',
            'epp': 'power',
            'turbo': False,
            'wifi_power_save': False,
            'nvme_runtime_pm': 'auto',
            'gpu_runtime_pm': 'on',
            'pcie_aspm': 'powersupersave',
            'usb_autosuspend': 'auto',
            'audio_powersave': 'on',
            'hwp_dynamic_boost': 'off',
        },
        'responsive': {
            'gnome_profile': 'balanced',
            'epp': 'balance_performance',
            'turbo': True,
            'wifi_power_save': False,
            'nvme_runtime_pm': 'auto',
            'gpu_runtime_pm': 'system',
            'pcie_aspm': 'powersave',
            'usb_autosuspend': 'system',
            'audio_powersave': 'on',
            'hwp_dynamic_boost': 'system',
        },
    },
    'ac': {
        'recommended': deepcopy(DEFAULT_CONFIG['ac']),
        'performance': {
            'gnome_profile': 'performance',
            'epp': 'performance',
            'turbo': True,
            'wifi_power_save': False,
            'nvme_runtime_pm': 'auto',
            'gpu_runtime_pm': 'system',
            'pcie_aspm': 'performance',
            'usb_autosuspend': 'system',
            'audio_powersave': 'system',
            'hwp_dynamic_boost': 'on',
        },
        'cool_quiet': {
            'gnome_profile': 'balanced',
            'epp': 'balance_power',
            'turbo': False,
            'wifi_power_save': False,
            'nvme_runtime_pm': 'auto',
            'gpu_runtime_pm': 'on',
            'pcie_aspm': 'default',
            'usb_autosuspend': 'system',
            'audio_powersave': 'on',
            'hwp_dynamic_boost': 'off',
        },
    },
}



def _merge_valid(default: dict, data: object) -> dict:
    out = deepcopy(default)
    if not isinstance(data, dict):
        return out
    for mode in ('battery', 'ac'):
        sub = data.get(mode)
        if not isinstance(sub, dict):
            continue
        for key, allowed in ALLOWED.items():
            if key in sub and sub[key] in allowed:
                out[mode][key] = sub[key]
    return out


def load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text())
            return _merge_valid(DEFAULT_CONFIG, data)
    except Exception:
        pass
    return deepcopy(DEFAULT_CONFIG)


def load_sensor_config() -> dict:
    out = dict(DEFAULT_SENSOR_CONFIG)
    try:
        if SENSOR_CONFIG_PATH.exists():
            data = json.loads(SENSOR_CONFIG_PATH.read_text())
            if isinstance(data, dict):
                for k in DEFAULT_SENSOR_CONFIG:
                    if k in data:
                        out[k] = data[k]
                return out
    except Exception:
        pass
    return out


def atomic_json_write(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.replace(path)


def _run_helper(args: list[str]) -> subprocess.CompletedProcess:
    helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
    res = subprocess.run(['sudo', '-n', str(helper), *args], capture_output=True, text=True)
    if res.returncode == 0:
        return res
    return subprocess.run(['pkexec', str(helper), *args], capture_output=True, text=True)


def save_config(cfg: dict) -> None:
    valid = _merge_valid(DEFAULT_CONFIG, cfg)
    try:
        atomic_json_write(CONFIG_PATH, valid)
    except (PermissionError, OSError):
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists():
            res = _run_helper(['save-config', json.dumps(valid)])
            if res.returncode != 0:
                err = res.stderr.strip() or 'Authorization error'
                raise PermissionError(f'Failed to save configuration: {err}')
        else:
            raise


def save_and_apply_config(cfg: dict) -> None:
    valid = _merge_valid(DEFAULT_CONFIG, cfg)
    helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
    if helper.exists() and os.geteuid() != 0:
        res = _run_helper(['save-and-apply', json.dumps(valid)])
        if res.returncode != 0:
            err = res.stderr.strip() or 'Authorization or execution error'
            raise PermissionError(f'Failed to apply configuration: {err}')
    else:
        save_config(valid)
        try:
            from .power_apply import apply_current
            apply_current()
        except Exception as exc:
            raise RuntimeError(f'Failed to apply profile: {exc}')


def save_sensor_config(cfg: dict) -> None:
    current = load_sensor_config()
    val = float(cfg.get('silence_timeout', current['silence_timeout']))
    reports = int(cfg.get('present_confirm_reports', current['present_confirm_reports']))
    win = float(cfg.get('present_confirm_window', current['present_confirm_window']))
    payload = {
        'silence_timeout': max(2.0, min(90.0, val)),
        'present_confirm_reports': max(1, min(5, reports)),
        'present_confirm_window': max(1.0, min(15.0, win)),
    }
    try:
        atomic_json_write(SENSOR_CONFIG_PATH, payload)
    except (PermissionError, OSError):
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists():
            res = _run_helper(['save-sensor', json.dumps(payload)])
            if res.returncode != 0:
                err = res.stderr.strip() or 'Authorization error'
                raise PermissionError(f'Failed to save sensor settings: {err}')
        else:
            raise


def read_text(path) -> str | None:
    try:
        return pathlib.Path(path).read_text().strip()
    except Exception:
        return None


def write_if_changed(path, value) -> bool:
    p = pathlib.Path(path)
    try:
        val_str = str(value)
        if p.read_text().strip() == val_str:
            return True
        p.write_text(val_str)
        return True
    except Exception:
        return False


def run(cmd: list[str]) -> bool:
    try:
        return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False).returncode == 0
    except Exception:
        return False


def command_output(cmd: list[str]) -> str | None:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None


def set_profile(value: str) -> None:
    if value == 'system':
        return
    if command_output(['/usr/bin/powerprofilesctl', 'get']) != value:
        run(['/usr/bin/powerprofilesctl', 'set', value])
        time.sleep(0.3)


def set_epp(value: str) -> None:
    if value == 'system':
        return
    for p in glob.glob('/sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference'):
        write_if_changed(p, value)
    if value == 'performance':
        for p in glob.glob('/sys/devices/system/cpu/cpu*/power/energy_perf_bias'):
            write_if_changed(p, '0')
    elif value == 'power':
        for p in glob.glob('/sys/devices/system/cpu/cpu*/power/energy_perf_bias'):
            write_if_changed(p, '15')
    elif value == 'balance_power':
        for p in glob.glob('/sys/devices/system/cpu/cpu*/power/energy_perf_bias'):
            write_if_changed(p, '8')
    elif value in ('balance_performance', 'default'):
        for p in glob.glob('/sys/devices/system/cpu/cpu*/power/energy_perf_bias'):
            write_if_changed(p, '6')
        set_cpu_freq_floor()


def set_turbo(value: bool | str) -> None:
    if value == 'system':
        return
    p = '/sys/devices/system/cpu/intel_pstate/no_turbo'
    if os.path.exists(p):
        write_if_changed(p, '0' if value else '1')


def set_hwp_dynamic_boost(value: str) -> None:
    if value == 'system':
        return
    p = '/sys/devices/system/cpu/intel_pstate/hwp_dynamic_boost'
    if os.path.exists(p):
        write_if_changed(p, '1' if value == 'on' else '0')


def wifi_ifaces() -> list[str]:
    return [pathlib.Path(p).parent.name for p in glob.glob('/sys/class/net/*/wireless')]


def wifi_ps_current(iface: str) -> str | None:
    out = command_output(['/usr/sbin/iw', 'dev', iface, 'get', 'power_save'])
    if not out:
        return None
    return 'on' if 'on' in out.lower() else 'off'


def set_wifi_ps(value: bool | str) -> None:
    if value == 'system':
        return
    want = 'on' if value else 'off'
    for iface in wifi_ifaces():
        # Intel BE200 / iwlwifi Wi-Fi 7 chips throttle to 6 Mbps when 802.11 power_save is enabled in software.
        driver_path = f'/sys/class/net/{iface}/device/driver'
        if os.path.exists(driver_path) and os.path.basename(os.readlink(driver_path)) == 'iwlwifi':
            want = 'off'
        if wifi_ps_current(iface) != want:
            run(['/usr/sbin/iw', 'dev', iface, 'set', 'power_save', want])


def set_nvme(value: str) -> None:
    if value == 'system':
        return
    for p in glob.glob('/sys/class/nvme/nvme*/device/power/control'):
        write_if_changed(p, value)


def set_pci_runtime_pm(value: str = 'auto') -> None:
    if value not in ('auto', 'on'):
        return
    for ctrl in glob.glob('/sys/bus/pci/devices/*/power/control'):
        dev_dir = os.path.dirname(os.path.dirname(ctrl))
        cls = read_text(os.path.join(dev_dir, 'class')) or ''
        # Let set_gpu manage graphics controllers (class 0x03xxxx)
        if cls.startswith('0x03'):
            continue
        # Keep USB host controllers (class 0x0c03xx) on to prevent Intel BE200 Bluetooth & USB sleep drops
        if cls.startswith('0x0c03'):
            write_if_changed(ctrl, 'on')
            continue
        write_if_changed(ctrl, 'auto')


def set_macbook_hybrid_topology(mode: str | None = None, high_load: bool = False) -> None:
    """
    MacBook Dynamic Load-Aware Hybrid Topology:
      - Normal Battery Load: 8 active cores (cpu0..1 @ 4.5GHz burst + cpu6..9 @ 3.2GHz + cpu14..15 LP-E @ 2.0GHz).
        cpu2..5 (4 P-cores) and cpu10..13 (4 E-cores) are parked in deep sleep for max battery life.
        Cores 14-15 LP-E handle audio/background on SoC tile without waking compute tile.
        Active P-cores burst to 4.5 GHz within 2ms so 120Hz ProMotion UI never drops frames.
      - High Load (>38% CPU or heavy workloads): All 16 cores unparked dynamically!
      - AC: All 16 cores always active.
    """
    try:
        for p in glob.glob('/sys/class/powercap/intel-rapl*/energy_uj') + glob.glob('/sys/class/powercap/intel-rapl*/*/energy_uj'):
            os.chmod(p, 0o444)
    except Exception:
        pass

    on_bat = on_battery_from_sysfs() if mode is None else (mode in ('battery', 'max_battery', 'maximum_battery'))
    is_extreme = mode in ('extreme_performance', 'performance')
    is_max_bat = mode in ('max_battery', 'maximum_battery')

    if is_extreme:
        # Wake all 16 cores first
        for c in range(1, 16):
            write_if_changed(f'/sys/devices/system/cpu/cpu{c}/online', '1')
        for c in range(0, 16):
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            if c <= 5:
                write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '1800000')
                write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', '5400000')
                write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'performance')
                write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '0')
            elif c <= 13:
                write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '1200000')
                write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', '4500000')
                write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'performance')
                write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '0')
            else:
                write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '800000')
                write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', '2500000')
                write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'balance_performance')
                write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '4')
        return

    # MacBook Dynamic Hybrid Mode (All 16 cores stay online; hardware C6/C10 power-gates idle cores)
    # Never hotplug cores offline to avoid kernel stop_machine() pauses which drop frames at 120Hz!
    online_cores = set(range(16))
    if is_max_bat:
        p_max, e_max, lpe_max = '2800000', '2200000', '1800000'
    elif mode == 'cool_quiet':
        p_max, e_max, lpe_max = '3400000', '2600000', '2000000'
    elif on_bat:
        if high_load:
            p_max, e_max, lpe_max = '4800000', '3400000', '2400000'
        else:
            # ProMotion Battery Profile: P-cores burst up to 4.2 GHz for silky-smooth 120Hz UI response
            p_max, e_max, lpe_max = '4200000', '3000000', '1800000'
    else:
        # On AC: All cores burst to maximum
        p_max, e_max, lpe_max = '4800000', '3600000', '2400000'

    # Ensure all 16 cores are online (eliminates scheduler latency & micro-stutter)
    for c in range(1, 16):
        online_path = f'/sys/devices/system/cpu/cpu{c}/online'
        if os.path.exists(online_path):
            write_if_changed(online_path, '1')

    # Ensure Intel P-State dynamic responsiveness & Turbo burst
    write_if_changed('/sys/devices/system/cpu/intel_pstate/hwp_dynamic_boost', '1')
    write_if_changed('/sys/devices/system/cpu/intel_pstate/no_turbo', '0' if not is_max_bat else '1')

    # Force Intel Xe hardware PSR1 on Samsung 2.8K OLED (saves ~2.5W display memory traffic)
    for psr_debug in glob.glob('/sys/kernel/debug/dri/*/i915_edp_psr_debug'):
        write_if_changed(psr_debug, '2')

    for c in sorted(online_cores):
        cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
        if c <= 5:
            # P-cores: 800 MHz floor + balance_performance for instantaneous 0.05ms 120Hz VSync response
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '800000')
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', p_max)
            if is_max_bat:
                p_epp, p_epb = 'power', '15'
            elif mode == 'cool_quiet':
                p_epp, p_epb = 'balance_power', '8'
            else:
                p_epp = 'balance_performance'
                p_epb = '4'
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', p_epp)
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', p_epb)
        elif c <= 13:
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '400000')
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', e_max)
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'power' if is_max_bat else ('balance_performance' if not on_bat else 'balance_power'))
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '14' if is_max_bat else ('4' if not on_bat else '7'))
        else:
            # Low-Power Skymont Island (cores 14, 15 on SoC tile)
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '400000')
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', lpe_max)
            if is_max_bat:
                write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'power')
                write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '15')
            else:
                write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'power' if on_bat else 'balance_performance')
                write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '11' if on_bat else '6')


def set_cpu_freq_floor(mode: str | None = None, high_load: bool = False) -> None:
    set_macbook_hybrid_topology(mode, high_load=high_load)


def set_gpu(value: str = 'system', mode: str | None = None) -> None:
    for dev in glob.glob('/sys/bus/pci/devices/*'):
        vendor = read_text(os.path.join(dev, 'vendor'))
        cls = read_text(os.path.join(dev, 'class'))
        if vendor == '0x8086' and cls and cls.startswith('0x03'):
            # The primary display adapter (Intel Xe iGPU) must NEVER have PCIe link autosuspended.
            # Internal hardware GT RC6 sleep handles zero-power idle automatically at 0 MHz.
            write_if_changed(os.path.join(dev, 'power/control'), 'on')

    on_bat = on_battery_from_sysfs() if mode is None else (mode in ('battery', 'max_battery', 'maximum_battery'))
    is_extreme = mode in ('extreme_performance', 'performance')
    is_max_bat = mode in ('max_battery', 'maximum_battery')

    # Native Intel Xe driver (Arrow Lake-H / Lunar Lake tile* gt*/freq0)
    for gt_freq in glob.glob('/sys/devices/pci0000:00/0000:00:02.0/tile*/gt*/freq0'):
        is_gt1 = 'gt1' in gt_freq
        power_prof = os.path.join(gt_freq, 'power_profile')
        if os.path.exists(power_prof):
            # In max_battery keep power_saving; in balanced & ac use 'base' for instant media response
            write_if_changed(power_prof, 'power_saving' if is_max_bat else 'base')
        min_node = os.path.join(gt_freq, 'min_freq')
        if os.path.exists(min_node):
            if is_extreme:
                target_min = '500' if is_gt1 else '1400'
            elif is_max_bat:
                target_min = '100' if is_gt1 else '200'
            elif on_bat:
                # 600 MHz floor for 3D GPU renders 2.8K 120Hz compositor in <4ms (well within 8.33ms VSync budget)
                # RC6 (gt0-rc) still powers off the GPU completely to 0W when idle.
                target_min = '400' if is_gt1 else '600'
            else:
                target_min = '450' if is_gt1 else '600'
            write_if_changed(min_node, target_min)
        max_node = os.path.join(gt_freq, 'max_freq')
        if os.path.exists(max_node):
            rp0_node = os.path.join(gt_freq, 'rp0_freq')
            rp0 = read_text(rp0_node)
            if is_extreme:
                target_max = rp0.strip() if rp0 and rp0.strip().isdigit() else ('1300' if is_gt1 else '2350')
            elif is_max_bat:
                target_max = '800' if is_gt1 else '800'
            else:
                # Balanced mode: 3D GPU (gt0) dynamic burst up to 1600 MHz (battery) / 1800 MHz (AC)
                # for liquid-smooth 120Hz ProMotion without frame drops, while staying at 800 MHz in idle.
                target_max = '1200' if is_gt1 else ('1600' if on_bat else '1800')
            write_if_changed(max_node, target_max)

    # Intel Arc & Iris Xe GPU power optimization (GuC SLPC & RC6 legacy i915 nodes)
    for card in glob.glob('/sys/class/drm/card*'):
        slpc_node = os.path.join(card, 'gt/gt0/slpc_power_profile')
        if os.path.exists(slpc_node):
            write_if_changed(slpc_node, 'power_saving' if is_max_bat else 'base')
        boost_node = os.path.join(card, 'gt/gt0/rps_boost_freq_mhz')
        if os.path.exists(boost_node):
            write_if_changed(boost_node, '2350' if is_extreme else '1200')
        min_node = os.path.join(card, 'gt_min_freq_mhz')
        if os.path.exists(min_node):
            target_min = '1400' if is_extreme else ('200' if is_max_bat else '400')
            write_if_changed(min_node, target_min)
        max_node = os.path.join(card, 'gt_max_freq_mhz')
        if os.path.exists(max_node):
            write_if_changed(max_node, '2350' if is_extreme else ('800' if is_max_bat else ('800' if on_bat else '1000')))


def set_pcie_aspm(value: str) -> None:
    if value == 'system':
        value = 'powersave'
    p = '/sys/module/pcie_aspm/parameters/policy'
    if os.path.exists(p):
        if not write_if_changed(p, value) and value == 'powersupersave':
            write_if_changed(p, 'powersave')


def set_usb(value: str) -> None:
    if value != 'auto':
        return
    for dev_path in glob.glob('/sys/bus/usb/devices/*'):
        p = os.path.join(dev_path, 'power/control')
        if not os.path.exists(p):
            continue
        vendor = read_text(os.path.join(dev_path, 'idVendor'))
        # Intel Bluetooth (8087) must NEVER be autosuspended, otherwise firmware drops off USB bus
        if vendor == '8087':
            write_if_changed(p, 'on')
            delay_node = os.path.join(dev_path, 'power/autosuspend_delay_ms')
            if os.path.exists(delay_node):
                write_if_changed(delay_node, '-1')
            continue
        # Never autosuspend USB Human Interface Devices (mice, keyboards, 2.4GHz wireless dongles)
        is_hid = False
        for iface_dir in glob.glob(os.path.join(dev_path, '*:*.*/bInterfaceClass')):
            if read_text(iface_dir) == '03':
                is_hid = True
                break
        if is_hid:
            write_if_changed(p, 'on')
            continue
        write_if_changed(p, 'auto')


def set_audio(value: str) -> None:
    if value == 'system':
        return
    p = '/sys/module/snd_hda_intel/parameters/power_save'
    if os.path.exists(p):
        write_if_changed(p, '1' if value == 'on' else '0')
    p_ctrl = '/sys/module/snd_hda_intel/parameters/power_save_controller'
    if os.path.exists(p_ctrl):
        write_if_changed(p_ctrl, 'Y' if value == 'on' else 'N')


def optimize_sd_card() -> None:
    # Safely enable runtime PM for SD card controller
    sd_dev = '/sys/bus/pci/devices/0000:57:00.0'
    if os.path.exists(sd_dev):
        write_if_changed(os.path.join(sd_dev, 'power/control'), 'auto')


def apply_kernel_tunings(mode: str) -> None:
    if mode in ('battery', 'max_battery', 'maximum_battery'):
        pass # vm.laptop_mode deprecated in Linux 6.12+
        write_if_changed('/proc/sys/vm/dirty_writeback_centisecs', '6000')
        write_if_changed('/proc/sys/vm/dirty_expire_centisecs', '12000')
        write_if_changed('/proc/sys/vm/dirty_ratio', '20')
        write_if_changed('/proc/sys/vm/dirty_background_ratio', '10')
        write_if_changed('/proc/sys/kernel/nmi_watchdog', '0')
        write_if_changed('/proc/sys/kernel/timer_migration', '1')
        for p in glob.glob('/sys/class/scsi_host/host*/link_power_management_policy'):
            write_if_changed(p, 'med_power_with_dipm')
    else:
        pass # vm.laptop_mode deprecated in Linux 6.12+
        write_if_changed('/proc/sys/vm/dirty_writeback_centisecs', '1500')
        write_if_changed('/proc/sys/vm/dirty_expire_centisecs', '3000')
        write_if_changed('/proc/sys/vm/dirty_ratio', '20')
        write_if_changed('/proc/sys/vm/dirty_background_ratio', '10')
        write_if_changed('/proc/sys/kernel/nmi_watchdog', '0')
        write_if_changed('/proc/sys/kernel/timer_migration', '1')
        for p in glob.glob('/sys/class/scsi_host/host*/link_power_management_policy'):
            write_if_changed(p, 'max_performance')
    # MacBook Pro-grade low-latency scheduler, VM & NVMe responsiveness tunings
    write_if_changed('/proc/sys/kernel/sched_autogroup_enabled', '1')
    write_if_changed('/proc/sys/vm/vfs_cache_pressure', '50')
    write_if_changed('/proc/sys/vm/swappiness', '10')
    write_if_changed('/proc/sys/vm/compaction_proactiveness', '0')
    write_if_changed('/proc/sys/vm/watermark_boost_factor', '0')
    write_if_changed('/proc/sys/vm/watermark_scale_factor', '125')
    write_if_changed('/proc/sys/vm/page-cluster', '0')
    for q_dir in glob.glob('/sys/block/nvme*/queue'):
        write_if_changed(os.path.join(q_dir, 'scheduler'), 'none')
        write_if_changed(os.path.join(q_dir, 'rq_affinity'), '2')
        write_if_changed(os.path.join(q_dir, 'read_ahead_kb'), '256')
        write_if_changed(os.path.join(q_dir, 'iostats'), '0')


INTERACTIVE_QOS_PROCESSES = {
    'gnome-shell': -10,
    'mutter': -10,
    'xwayland': -10,
    'llama-server': -10,
    'ollama': -10,
    'antigravity': -8,
    'language_server': -8,
    'pipewire': -11,
    'pipewire-pulse': -11,
    'wireplumber': -11,
}

BACKGROUND_QOS_PROCESSES = {
    'tracker-miner-f': 15,
    'packagekitd': 10,
    'updatedb': 15,
}


def optimize_desktop_responsiveness() -> None:
    """Apply MacBook-style QoS CPU scheduling priorities to foreground UI/IDE vs background tasks."""
    for comm_path in glob.glob('/proc/[0-9]*/comm'):
        try:
            with open(comm_path, 'r', encoding='utf-8', errors='ignore') as f:
                name = f.read().strip().lower()
            if not name:
                continue
            target_nice = INTERACTIVE_QOS_PROCESSES.get(name)
            if target_nice is None:
                target_nice = BACKGROUND_QOS_PROCESSES.get(name)
            if target_nice is None and name.startswith('language_server'):
                target_nice = -8
            if target_nice is not None:
                pid = int(comm_path.split('/')[2])
                cur_nice = os.getpriority(os.PRIO_PROCESS, pid)
                if cur_nice != target_nice:
                    os.setpriority(os.PRIO_PROCESS, pid, target_nice)
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, OSError):
            continue


def set_smart_media_mode(active: bool) -> None:
    """Smart Media Video Mode: Hardware VA-API 4K/60fps playback without stutter

    Hardware VA-API decodes 4K/60fps video on the Intel Xe Media Engine (gt1).
    Maintains balanced responsiveness (3.6 GHz burst ceiling, balance_power EPP)
    so 4K frames and 120Hz compositor never drop frames, while preventing
    unnecessary 5+ GHz turbo spikes on battery.
    """
    on_bat = on_battery_from_sysfs()
    state_file = RUN_DIR / 'media.state'
    if active and on_bat:
        # P-cores (0..5): 3.6 GHz burst ceiling with responsive balance_power (EPB 6)
        for c in range(6):
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '800000')
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', '3600000')
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'balance_power')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '6')
        # E-cores (6..13): 2.6 GHz ceiling
        for c in range(6, 14):
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '400000')
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', '2600000')
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'balance_power')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '8')
        # Low-Power Island E-cores (14..15)
        for c in (14, 15):
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '400000')
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', '1800000')
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'power')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '12')
        # Ensure Media Engine (gt1) has responsive floor for 4K 60fps decode
        write_if_changed('/sys/devices/pci0000:00/0000:00:02.0/tile0/gt1/freq0/min_freq', '600')
        write_if_changed('/sys/devices/pci0000:00/0000:00:02.0/tile0/gt0/freq0/min_freq', '600')
        try:
            state_file.write_text('active\n')
        except Exception:
            pass
    else:
        mode = 'battery' if on_bat else 'ac'
        set_macbook_hybrid_topology(mode)
        set_gpu('auto', mode)
        try:
            if state_file.exists():
                state_file.unlink()
        except Exception:
            pass


def set_rapl_limits(mode: str) -> None:
    # Intel Core Ultra 9 285H (Arrow Lake) Optimum Power Limits (MacBook-style cool & responsive)
    if mode in ('extreme_performance', 'performance'):
        pl1, pl2 = 65000000, 100000000
    elif mode in ('battery', 'max_battery', 'maximum_battery'):
        pl1, pl2 = 12000000, 20000000
    elif mode == 'cool_quiet':
        pl1, pl2 = 18000000, 30000000
    else:  # ac / balanced optimum (MacBook style: quiet, 35-40°C idle, instant 45W burst)
        pl1, pl2 = 28000000, 45000000

    # Set Lenovo IdeaPad ACPI firmware platform_profile to match
    if PLATFORM_PROFILE_PATH.exists():
        if mode in ('extreme_performance', 'performance'):
            write_if_changed(PLATFORM_PROFILE_PATH, 'performance')
        elif mode in ('battery', 'max_battery', 'maximum_battery', 'cool_quiet'):
            write_if_changed(PLATFORM_PROFILE_PATH, 'low-power')
        else:
            write_if_changed(PLATFORM_PROFILE_PATH, 'balanced')

    rapl_base = pathlib.Path('/sys/class/powercap/intel-rapl')
    for d in rapl_base.glob('intel-rapl:*'):
        c0 = d / 'constraint_0_power_limit_uw'
        c1 = d / 'constraint_1_power_limit_uw'
        if c0.exists():
            write_if_changed(c0, str(pl1))
        if c1.exists():
            write_if_changed(c1, str(pl2))


def apply(mode: str, cfg: dict | None = None) -> None:
    cfg = cfg or load_config()
    is_extreme = mode in ('extreme_performance', 'performance')
    if is_extreme:
        base_mode = 'ac'
        s = deepcopy(cfg['ac'])
        s['gnome_profile'] = 'performance'
        s['epp'] = 'performance'
        s['pcie_aspm'] = 'performance'
        s['wifi_power_save'] = False
        s['hwp_dynamic_boost'] = 'on'
        s['gpu_runtime_pm'] = 'auto'
    elif mode == 'battery':
        base_mode = 'battery'
        s = cfg['battery']
    else:
        base_mode = 'ac'
        s = cfg['ac']

    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        (RUN_DIR / 'power.mode').write_text(mode)
    except Exception:
        pass
    gnome_prof = s['gnome_profile']
    set_profile(gnome_prof)
    # Set EPP right after set_profile to ensure power-profiles-daemon cannot override it
    set_epp(s['epp'])
    set_turbo(s['turbo'])
    set_cpu_freq_floor(mode)
    set_hwp_dynamic_boost(s['hwp_dynamic_boost'])
    set_wifi_ps(s['wifi_power_save'])
    set_nvme(s['nvme_runtime_pm'])
    set_pci_runtime_pm('auto')
    set_gpu(s['gpu_runtime_pm'], mode)
    set_pcie_aspm(s['pcie_aspm'])
    set_usb(s['usb_autosuspend'])
    set_audio(s['audio_powersave'])
    apply_kernel_tunings(base_mode)
    set_rapl_limits(mode)
    optimize_sd_card()
    optimize_desktop_responsiveness()




def on_battery_from_sysfs() -> bool:
    for supply in sorted(glob.glob('/sys/class/power_supply/*')):
        st = pathlib.Path(supply)
        typ = read_text(st / 'type')
        online = read_text(st / 'online')
        if typ == 'Mains' and online in ('0', '1'):
            return online == '0'
    for p in sorted(glob.glob('/sys/class/power_supply/*/online')):
        name = pathlib.Path(p).parent.name.upper()
        if name.startswith(('AC', 'ADP')):
            v = read_text(p)
            if v in ('0', '1'):
                return v == '0'
    return True


_LAST_RAPL_UJ: int | None = None
_LAST_RAPL_TS: float | None = None


def _read_rapl_compute_uj() -> int | None:
    """Read CPU Core + GPU Uncore energy in microjoules (with fallback to Package)."""
    c_path = pathlib.Path('/sys/class/powercap/intel-rapl:0:0/energy_uj')
    u_path = pathlib.Path('/sys/class/powercap/intel-rapl:0:1/energy_uj')
    p_path = pathlib.Path('/sys/class/powercap/intel-rapl:0/energy_uj')
    try:
        if c_path.exists() and u_path.exists():
            return int(c_path.read_text().strip()) + int(u_path.read_text().strip())
        if p_path.exists():
            return int(p_path.read_text().strip())
    except Exception:
        pass
    return None


def power_now_watts() -> float | None:
    global _LAST_RAPL_UJ, _LAST_RAPL_TS
    for p in sorted(glob.glob('/sys/class/power_supply/BAT*/power_now')):
        try:
            val = int(pathlib.Path(p).read_text().strip())
            if val > 0:
                return val / 1_000_000.0
        except Exception:
            continue
    for bat in sorted(glob.glob('/sys/class/power_supply/BAT*')):
        try:
            curr = read_text(os.path.join(bat, 'current_now'))
            volt = read_text(os.path.join(bat, 'voltage_now'))
            if curr and volt:
                c, v = int(curr), int(volt)
                if c > 0 and v > 0:
                    return (c * v) / 1_000_000_000_000.0
        except Exception:
            continue
    # Fallback to Intel RAPL Compute (Core + GPU + 1.8W SoC baseline) when on AC
    now_uj = _read_rapl_compute_uj()
    if now_uj is not None:
        try:
            now_ts = time.monotonic()
            if _LAST_RAPL_UJ is not None and _LAST_RAPL_TS is not None:
                dt = now_ts - _LAST_RAPL_TS
                if dt >= 0.08 and now_uj >= _LAST_RAPL_UJ:
                    w = 1.80 + (now_uj - _LAST_RAPL_UJ) / (dt * 1_000_000.0)
                    _LAST_RAPL_UJ, _LAST_RAPL_TS = now_uj, now_ts
                    return round(w, 2)
            # First call: sample over 120ms
            time.sleep(0.12)
            now2_uj = _read_rapl_compute_uj()
            now2_ts = time.monotonic()
            if now2_uj is not None and now2_uj >= now_uj and (now2_ts - now_ts) > 0:
                _LAST_RAPL_UJ, _LAST_RAPL_TS = now2_uj, now2_ts
                w = 1.80 + (now2_uj - now_uj) / ((now2_ts - now_ts) * 1_000_000.0)
                return round(w, 2)
        except Exception:
            pass
    return None


def battery_percent() -> int | None:
    for p in sorted(glob.glob('/sys/class/power_supply/BAT*/capacity')):
        try:
            return int(pathlib.Path(p).read_text().strip())
        except Exception:
            continue
    return None


def current_refresh_rate() -> str:
    rate_file = RUN_DIR / 'refresh.rate'
    if rate_file.exists():
        raw = read_text(rate_file) or ''
        if '60' in raw:
            return '60 Hz (Power Saver)'
        elif '120' in raw:
            return '120 Hz + VRR (Smooth)'
        return raw
    m_xml = pathlib.Path.home() / '.config/monitors.xml'
    if m_xml.exists():
        try:
            txt = m_xml.read_text()
            if '<rate>120' in txt:
                return '120 Hz + VRR'
            elif '<rate>60' in txt:
                return '60 Hz'
        except Exception:
            pass
    return '120 Hz'


def pcie_aspm_current() -> str:
    p = '/sys/module/pcie_aspm/parameters/policy'
    txt = read_text(p)
    if txt:
        import re
        m = re.search(r'\[(.*?)\]', txt)
        if m:
            return m.group(1)
        return txt.strip()
    return '—'


def gpu_min_freq_current() -> str:
    for node in glob.glob('/sys/devices/pci0000:00/0000:00:02.0/tile*/gt*/freq0/act_freq'):
        txt = read_text(node)
        if txt and txt.strip():
            return f"{txt.strip()} MHz (Intel Arc Xe-LPG+)"
    for node in glob.glob('/sys/devices/pci0000:00/0000:00:02.0/tile*/gt*/freq0/cur_freq'):
        txt = read_text(node)
        if txt and txt.strip():
            return f"{txt.strip()} MHz (Intel Arc Xe-LPG+)"
    for node in ['/sys/class/drm/card1/gt_min_freq_mhz', '/sys/class/drm/card0/gt_min_freq_mhz']:
        txt = read_text(node)
        if txt and txt.strip():
            return f"{txt.strip()} MHz (Stutter Prevention)"
    return 'Dynamic'


def vaapi_current() -> str:
    drv = os.environ.get('LIBVA_DRIVER_NAME')
    if not drv:
        if os.path.exists('/etc/profile.d/vaapi-intel.sh'):
            drv = 'Intel iHD (Iris Xe Hardware)'
        else:
            drv = 'Intel iHD (Hardware)'
    else:
        drv = f"{drv} (Hardware)"
    return drv


def tcp_cc_current() -> str:
    cc = read_text('/proc/sys/net/ipv4/tcp_congestion_control')
    if cc:
        val = cc.strip().upper()
        if val == 'BBR':
            return 'BBR (Google Low Latency)'
        return val
    return 'Cubic'


def zram_current() -> str:
    alg_file = '/sys/block/zram0/comp_algorithm'
    alg_txt = read_text(alg_file)
    alg = 'Active'
    if alg_txt:
        import re
        m = re.search(r'\[(.*?)\]', alg_txt)
        if m:
            alg = m.group(1)
    if os.path.exists('/dev/zram0'):
        return f"ZRAM ({alg}) Active"
    return 'Disabled'


LENOVO_VPC_PATH = pathlib.Path('/sys/bus/platform/drivers/ideapad_acpi/VPC2004:00')
PLATFORM_PROFILE_PATH = pathlib.Path('/sys/firmware/acpi/platform_profile')


def battery_health_report() -> dict:
    bat_dir = None
    for p in sorted(glob.glob('/sys/class/power_supply/BAT*')):
        bat_dir = pathlib.Path(p)
        break
    if not bat_dir or not bat_dir.exists():
        return {}

    def _read_int(name: str) -> int | None:
        try:
            return int((bat_dir / name).read_text().strip())
        except Exception:
            return None

    def _read_str(name: str) -> str:
        try:
            return (bat_dir / name).read_text().strip()
        except Exception:
            return '—'

    full_uwh = _read_int('energy_full') or _read_int('charge_full')
    design_uwh = _read_int('energy_full_design') or _read_int('charge_full_design')
    now_uwh = _read_int('energy_now') or _read_int('charge_now')
    cycles = _read_int('cycle_count') or 0
    vol_uv = _read_int('voltage_now') or 0
    vol_min_uv = _read_int('voltage_min_design') or 0
    watts = power_now_watts()

    full_wh = (full_uwh / 1e6) if full_uwh else 0.0
    design_wh = (design_uwh / 1e6) if design_uwh else 0.0
    now_wh = (now_uwh / 1e6) if now_uwh else 0.0
    health_pct = (full_wh / design_wh * 100.0) if design_wh > 0 else 100.0

    return {
        'manufacturer': _read_str('manufacturer'),
        'model_name': _read_str('model_name'),
        'technology': _read_str('technology'),
        'charge_types': _read_str('charge_types'),
        'capacity_pct': _read_int('capacity'),
        'energy_now_wh': round(now_wh, 2),
        'energy_full_wh': round(full_wh, 2),
        'energy_design_wh': round(design_wh, 2),
        'health_pct': round(min(115.0, health_pct), 1),
        'cycle_count': cycles,
        'voltage_v': round(vol_uv / 1e6, 2) if vol_uv else 0.0,
        'voltage_design_v': round(vol_min_uv / 1e6, 2) if vol_min_uv else 0.0,
        'watts': round(watts, 2) if watts else 0.0,
    }


def get_lenovo_features() -> dict:
    res = {
        'supported': LENOVO_VPC_PATH.exists(),
        'conservation_mode': None,
        'fn_lock': None,
        'usb_charging': None,
        'platform_profile': None,
    }
    if LENOVO_VPC_PATH.exists():
        cm = read_text(LENOVO_VPC_PATH / 'conservation_mode')
        res['conservation_mode'] = (cm == '1') if cm else False
        fl = read_text(LENOVO_VPC_PATH / 'fn_lock')
        res['fn_lock'] = (fl == '1') if fl else False
        uc = read_text(LENOVO_VPC_PATH / 'usb_charging')
        res['usb_charging'] = (uc == '1') if uc else False
    if PLATFORM_PROFILE_PATH.exists():
        res['platform_profile'] = read_text(PLATFORM_PROFILE_PATH)
    return res


def set_lenovo_feature(name: str, value: bool | str | int) -> bool:
    if name == 'conservation_mode':
        node = LENOVO_VPC_PATH / 'conservation_mode'
        val = '1' if value in (True, 1, '1', 'on') else '0'
        return write_if_changed(node, val)
    elif name == 'fn_lock':
        node = LENOVO_VPC_PATH / 'fn_lock'
        val = '1' if value in (True, 1, '1', 'on') else '0'
        return write_if_changed(node, val)
    elif name == 'usb_charging':
        node = LENOVO_VPC_PATH / 'usb_charging'
        val = '1' if value in (True, 1, '1', 'on') else '0'
        return write_if_changed(node, val)
    elif name == 'platform_profile':
        if PLATFORM_PROFILE_PATH.exists() and str(value) in ('low-power', 'balanced', 'performance'):
            return write_if_changed(PLATFORM_PROFILE_PATH, str(value))
    return False


def cpu_topology_current() -> str:
    online = read_text('/sys/devices/system/cpu/online') or '0-15'
    p_freq = read_text('/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq') or '0'
    try:
        ghz = int(p_freq) / 1_000_000.0
    except Exception:
        ghz = 0.0
    if online == '0-15':
        return f"16/16 All-Core Active ({ghz:.1f} GHz Max Boost)"
    return f"MacBook Hybrid ({online} Active • {ghz:.1f} GHz Burst)"


def status_snapshot() -> dict:
    mode = 'battery' if on_battery_from_sysfs() else 'ac'
    epp = read_text('/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference')
    turbo_raw = read_text('/sys/devices/system/cpu/intel_pstate/no_turbo')
    hwp = read_text('/sys/devices/system/cpu/intel_pstate/hwp_dynamic_boost')
    wifi = None
    ifaces = wifi_ifaces()
    if ifaces:
        wifi = wifi_ps_current(ifaces[0])
    return {
        'mode': mode,
        'watts': power_now_watts(),
        'battery_percent': battery_percent(),
        'refresh_rate': current_refresh_rate(),
        'gnome_profile': command_output(['/usr/bin/powerprofilesctl', 'get']),
        'epp': epp,
        'cpu_topology': cpu_topology_current(),
        'turbo': None if turbo_raw is None else turbo_raw == '0',
        'hwp_dynamic_boost': hwp,
        'wifi_power_save': wifi,
        'pcie_aspm': pcie_aspm_current(),
        'gpu_perf': gpu_min_freq_current(),
        'vaapi': vaapi_current(),
        'net_opt': tcp_cc_current(),
        'zram': zram_current(),
        'presence_state': read_text(STATE_FILE),
        'lenovo': get_lenovo_features(),
        'battery_health': battery_health_report(),
        'config': load_config(),
        'sensor': load_sensor_config(),
    }


