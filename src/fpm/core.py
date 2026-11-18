from __future__ import annotations

import glob
import json
import os
import pathlib
import signal
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
        # Thunderbolt / USB4 NHI (0x0c0340) can safely enter D3cold when idle
        if cls == '0x0c0340':
            write_if_changed(ctrl, 'auto')
            continue
        # Keep xHCI USB controllers (0x0c03xx) on only when a child USB device (e.g. BT/HID) is attached
        if cls.startswith('0x0c03'):
            has_usb_child = any(glob.glob(os.path.join(dev_dir, 'usb*', '[0-9]*-[0-9]*')))
            write_if_changed(ctrl, 'on' if has_usb_child else 'auto')
            continue
        write_if_changed(ctrl, 'auto')



def detect_cpu_topology() -> tuple[list[int], list[int], list[int]]:
    """Dynamically classify online CPUs into (p_cores, e_cores, lpe_cores) on any Intel/AMD CPU."""
    freqs = {}
    for p in glob.glob('/sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_max_freq'):
        try:
            cid = int(pathlib.Path(p).parts[-3][3:])
            freqs[cid] = int(pathlib.Path(p).read_text().strip())
        except Exception:
            pass
    if not freqs:
        all_cpus = sorted(int(p.split('/cpu')[-1]) for p in glob.glob('/sys/devices/system/cpu/cpu[0-9]*') if p.split('/cpu')[-1].isdigit())
        return all_cpus, [], []
    unique_f = sorted(set(freqs.values()), reverse=True)
    if len(unique_f) >= 3:
        p_t, lpe_t = unique_f[0], unique_f[-1]
        p_cores = sorted(c for c, f in freqs.items() if f >= p_t - 200000)
        lpe_cores = sorted(c for c, f in freqs.items() if f <= lpe_t + 100000)
        e_cores = sorted(c for c in freqs if c not in p_cores and c not in lpe_cores)
        return p_cores, e_cores, lpe_cores
    elif len(unique_f) == 2 and (unique_f[0] - unique_f[1]) >= 400000:
        p_t = unique_f[0]
        p_cores = sorted(c for c, f in freqs.items() if f >= p_t - 200000)
        e_cores = sorted(c for c in freqs if c not in p_cores)
        return p_cores, e_cores, []
    return sorted(freqs.keys()), [], []

def _parse_cpu_list(spec: str | None) -> list[int]:
    """Parse Linux sysfs CPU range strings such as '0-5,8,10-15' into sorted CPU IDs."""
    if not spec:
        return []
    cpus: list[int] = []
    for part in spec.strip().split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            lo_s, hi_s = part.split('-', 1)
            if lo_s.isdigit() and hi_s.isdigit():
                lo, hi = int(lo_s), int(hi_s)
                if hi >= lo:
                    cpus.extend(range(lo, hi + 1))
        elif part.isdigit():
            cpus.append(int(part))
    return sorted(set(cpus))


def _clamp_cpu_freq(cpu_dir: str, desired_khz: int, fallback_min: int = 400000) -> int:
    """Clamp target CPU frequency (kHz) to hardware [cpuinfo_min_freq, cpuinfo_max_freq]."""
    hw_min_s = read_text(f'{cpu_dir}/cpufreq/cpuinfo_min_freq')
    hw_max_s = read_text(f'{cpu_dir}/cpufreq/cpuinfo_max_freq')
    hw_min = int(hw_min_s) if hw_min_s and hw_min_s.isdigit() else fallback_min
    hw_max = int(hw_max_s) if hw_max_s and hw_max_s.isdigit() else desired_khz
    return max(hw_min, min(hw_max, desired_khz))


def set_hybrid_topology(mode: str | None = None, high_load: bool = False) -> None:
    """Apply universal load-aware CPU frequency/EPP policy across P, E, and LP-E cores."""
    try:
        for p in glob.glob('/sys/class/powercap/intel-rapl*/energy_uj') + glob.glob('/sys/class/powercap/intel-rapl*/*/energy_uj'):
            os.chmod(p, 0o444)
    except Exception:
        pass

    p_cores, e_cores, lpe_cores = detect_cpu_topology()
    all_cores = sorted(set(p_cores + e_cores + lpe_cores))
    if not all_cores:
        return

    on_bat = on_battery_from_sysfs() if mode is None else (mode in ('battery', 'max_battery', 'maximum_battery'))
    is_extreme = mode in ('extreme_performance', 'performance')
    is_max_bat = mode in ('max_battery', 'maximum_battery')

    # Keep all cores online so C6/C10 power-gating works without stop_machine() hotplug stalls
    for c in all_cores:
        online_path = f'/sys/devices/system/cpu/cpu{c}/online'
        if os.path.exists(online_path):
            write_if_changed(online_path, '1')

    if os.path.exists('/sys/devices/system/cpu/intel_pstate'):
        write_if_changed('/sys/devices/system/cpu/intel_pstate/hwp_dynamic_boost', '1' if not is_max_bat else '0')
        write_if_changed('/sys/devices/system/cpu/intel_pstate/no_turbo', '0' if not is_max_bat else '1')

    if is_extreme:
        for c in p_cores:
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            hw_max_s = read_text(f'{cpu_dir}/cpufreq/cpuinfo_max_freq')
            hw_max = int(hw_max_s) if hw_max_s and hw_max_s.isdigit() else 5400000
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', str(_clamp_cpu_freq(cpu_dir, 1800000)))
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', str(hw_max))
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'performance')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '0')
        for c in e_cores:
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            hw_max_s = read_text(f'{cpu_dir}/cpufreq/cpuinfo_max_freq')
            hw_max = int(hw_max_s) if hw_max_s and hw_max_s.isdigit() else 4500000
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', str(_clamp_cpu_freq(cpu_dir, 1200000)))
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', str(hw_max))
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'performance')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '0')
        for c in lpe_cores:
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            hw_max_s = read_text(f'{cpu_dir}/cpufreq/cpuinfo_max_freq')
            hw_max = int(hw_max_s) if hw_max_s and hw_max_s.isdigit() else 2500000
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', str(_clamp_cpu_freq(cpu_dir, 800000)))
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', str(hw_max))
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'balance_performance')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '4')
        return

    if is_max_bat:
        p_cap, e_cap, lpe_cap = 2800000, 2200000, 1800000
    elif mode == 'cool_quiet':
        p_cap, e_cap, lpe_cap = 3400000, 2600000, 2000000
    elif on_bat:
        p_cap, e_cap, lpe_cap = (4800000, 3400000, 2400000) if high_load else (4400000, 2800000, 1800000)
    else:
        p_cap, e_cap, lpe_cap = 4800000, 3600000, 2400000

    # Intel PSR on battery reduces panel self-refresh power without AC wake-latency trade-offs
    psr_target = '2' if on_bat else '1'
    for psr_debug in glob.glob('/sys/kernel/debug/dri/*/i915_edp_psr_debug'):
        write_if_changed(psr_debug, psr_target)

    p_set = set(p_cores)
    e_set = set(e_cores)
    for c in all_cores:
        cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
        if c in p_set:
            c3_disable = f'{cpu_dir}/cpuidle/state3/disable'
            if os.path.exists(c3_disable):
                write_if_changed(c3_disable, '1' if (not on_bat and not is_max_bat) else '0')
            p_min = _clamp_cpu_freq(cpu_dir, 400000 if (on_bat and not high_load) else 800000)
            p_max = _clamp_cpu_freq(cpu_dir, p_cap)
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', str(p_min))
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', str(p_max))
            if is_max_bat:
                p_epp, p_epb = 'power', '15'
            elif mode == 'cool_quiet':
                p_epp, p_epb = 'balance_power', '8'
            elif on_bat and not high_load:
                p_epp, p_epb = 'balance_power', '9'
            else:
                p_epp, p_epb = 'balance_performance', '4'
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', p_epp)
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', p_epb)
        elif c in e_set:
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', str(_clamp_cpu_freq(cpu_dir, 400000)))
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', str(_clamp_cpu_freq(cpu_dir, e_cap)))
            if is_max_bat:
                e_epp, e_epb = 'power', '14'
            elif on_bat and not high_load:
                e_epp, e_epb = 'power', '12'
            else:
                e_epp, e_epb = 'balance_performance', '4'
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', e_epp)
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', e_epb)
        else:
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', str(_clamp_cpu_freq(cpu_dir, 400000)))
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', str(_clamp_cpu_freq(cpu_dir, lpe_cap)))
            is_bat_idle = is_max_bat or (on_bat and not high_load)
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'power' if is_bat_idle else 'balance_performance')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '15' if is_max_bat else ('15' if is_bat_idle else '6'))


set_macbook_hybrid_topology = set_hybrid_topology


def set_cpu_freq_floor(mode: str | None = None, high_load: bool = False) -> None:
    set_hybrid_topology(mode, high_load=high_load)


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
    for gt_freq in glob.glob('/sys/devices/pci0000:00/*/tile*/gt*/freq0'):
        is_gt1 = 'gt1' in gt_freq
        power_prof = os.path.join(gt_freq, 'power_profile')
        if os.path.exists(power_prof):
            # Battery uses power_saving SLPC for deep RC6 idle; AC and high-load boost use 'base'
            use_power_saving = is_max_bat or (on_bat and not is_extreme)
            write_if_changed(power_prof, 'power_saving' if use_power_saving else 'base')
        min_node = os.path.join(gt_freq, 'min_freq')
        if os.path.exists(min_node):
            # Respect hardware rpn_freq floor (e.g. 800 MHz on gt0) so writes after extreme_performance never fail EINVAL
            rpn_raw = read_text(os.path.join(gt_freq, 'rpn_freq'))
            rpn_val = int(rpn_raw.strip()) if rpn_raw and rpn_raw.strip().isdigit() else (100 if is_gt1 else 800)
            if is_extreme:
                desired_min = 500 if is_gt1 else 1400
            elif is_max_bat:
                desired_min = 100 if is_gt1 else rpn_val
            else:
                desired_min = 100 if is_gt1 else rpn_val
            write_if_changed(min_node, str(max(rpn_val, desired_min)))
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
                # for liquid-smooth 120Hz ProMotion without frame drops, while resting at RPN/RC6 in idle.
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
    auto_other = (value == 'auto')
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
            bus_num = os.path.basename(dev_path).split('-')[0].split(':')[0]
            if bus_num.isdigit():
                write_if_changed(f'/sys/bus/usb/devices/usb{bus_num}/power/control', 'on')
            continue
        # Never autosuspend USB Human Interface Devices (mice, keyboards, 2.4GHz wireless dongles)
        is_hid = False
        for iface_dir in glob.glob(os.path.join(dev_path, '*:*.*/bInterfaceClass')):
            if read_text(iface_dir) == '03':
                is_hid = True
                break
        if is_hid:
            write_if_changed(p, 'on')
            delay_node = os.path.join(dev_path, 'power/autosuspend_delay_ms')
            if os.path.exists(delay_node):
                write_if_changed(delay_node, '-1')
            # Keep parent USB root hub awake so 1000Hz wireless mouse dongles never suffer hub wake lag
            bus_num = os.path.basename(dev_path).split('-')[0].split(':')[0]
            if bus_num.isdigit():
                write_if_changed(f'/sys/bus/usb/devices/usb{bus_num}/power/control', 'on')
            continue
        if os.path.basename(dev_path).startswith('usb'):
            continue
        if auto_other:
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
    """Safely enable runtime PM for any discovered PCI SD Host Controller (class 0x0805xx)."""
    for dev in glob.glob('/sys/bus/pci/devices/*'):
        cls = read_text(os.path.join(dev, 'class')) or ''
        if cls.startswith('0x0805'):
            write_if_changed(os.path.join(dev, 'power/control'), 'auto')


def apply_kernel_tunings(mode: str) -> None:
    if mode in ('battery', 'max_battery', 'maximum_battery'):
        pass # vm.laptop_mode deprecated in Linux 6.12+
        write_if_changed('/proc/sys/vm/dirty_writeback_centisecs', '3000')
        write_if_changed('/proc/sys/vm/dirty_expire_centisecs', '6000')
        write_if_changed('/proc/sys/vm/dirty_bytes', '268435456')
        write_if_changed('/proc/sys/vm/dirty_background_bytes', '67108864')
        write_if_changed('/proc/sys/kernel/nmi_watchdog', '0')
        write_if_changed('/proc/sys/kernel/timer_migration', '1')
        for p in glob.glob('/sys/class/scsi_host/host*/link_power_management_policy'):
            write_if_changed(p, 'med_power_with_dipm')
    else:
        pass # vm.laptop_mode deprecated in Linux 6.12+
        write_if_changed('/proc/sys/vm/dirty_writeback_centisecs', '500')
        write_if_changed('/proc/sys/vm/dirty_expire_centisecs', '3000')
        write_if_changed('/proc/sys/vm/dirty_bytes', '268435456')
        write_if_changed('/proc/sys/vm/dirty_background_bytes', '67108864')
        write_if_changed('/proc/sys/kernel/nmi_watchdog', '0')
        write_if_changed('/proc/sys/kernel/timer_migration', '1')
        for p in glob.glob('/sys/class/scsi_host/host*/link_power_management_policy'):
            write_if_changed(p, 'max_performance')
    # Low-latency interactive scheduler, VM, ZRAM & NVMe I/O queue tunings
    write_if_changed('/proc/sys/kernel/sched_autogroup_enabled', '1')
    write_if_changed('/proc/sys/kernel/split_lock_mitigate', '0')
    write_if_changed('/proc/sys/vm/vfs_cache_pressure', '100')
    write_if_changed('/proc/sys/vm/swappiness', '40')
    write_if_changed('/proc/sys/vm/compaction_proactiveness', '0')
    write_if_changed('/proc/sys/vm/extfrag_threshold', '750')
    write_if_changed('/proc/sys/vm/watermark_boost_factor', '0')
    write_if_changed('/proc/sys/vm/watermark_scale_factor', '125')
    write_if_changed('/proc/sys/vm/page-cluster', '0')
    write_if_changed('/proc/sys/vm/stat_interval', '10')
    write_if_changed('/sys/kernel/mm/lru_gen/min_ttl_ms', '1000')
    write_if_changed('/sys/kernel/mm/transparent_hugepage/shmem_enabled', 'advise')
    for zram_ra in glob.glob('/sys/block/zram*/queue/read_ahead_kb'):
        write_if_changed(zram_ra, '0')
    for q_dir in glob.glob('/sys/block/nvme*/queue'):
        write_if_changed(os.path.join(q_dir, 'scheduler'), 'none')
        write_if_changed(os.path.join(q_dir, 'rq_affinity'), '2')
        write_if_changed(os.path.join(q_dir, 'read_ahead_kb'), '128')
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
    'easyeffects': -9,
    'pulseeffects': -9,
    'kitty': -5,
    'ptyxis': -5,
    'gnome-terminal-': -5,
    'firefox': -4,
    'obsidian': -4,
}

BACKGROUND_QOS_PROCESSES = {
    'tracker-miner-f': 15,
    'packagekitd': 10,
    'updatedb': 15,
}


def optimize_desktop_responsiveness() -> None:
    """Apply interactive CPU scheduling priorities and P-core affinity to compositor/audio/UI processes."""
    p_cores, _, _ = detect_cpu_topology()
    p_set = set(p_cores) if p_cores else None
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
                if p_set and name in ('gnome-shell', 'mutter', 'xwayland'):
                    try:
                        os.sched_setaffinity(pid, p_set)
                    except OSError:
                        pass
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, OSError):
            continue


def pin_interactive_irqs() -> None:
    """Pin USB HID (xhci_hcd) and GPU IRQs (xe/i915/amdgpu) to detected performance cores."""
    p_cores, _, _ = detect_cpu_topology()
    if not p_cores:
        return
    aff_spec = (
        f'{p_cores[0]}-{p_cores[-1]}'
        if p_cores == list(range(p_cores[0], p_cores[-1] + 1))
        else ','.join(str(c) for c in p_cores)
    )
    try:
        with open('/proc/interrupts', 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
    except OSError:
        return
    for line in lines:
        stripped = line.rstrip()
        if 'xhci_hcd' in line or stripped.endswith((' xe', ' i915', ' amdgpu')):
            irq_str = line.split(':', 1)[0].strip()
            if irq_str.isdigit():
                write_if_changed(f'/proc/irq/{irq_str}/smp_affinity_list', aff_spec)


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
        p_cores, e_cores, lpe_cores = detect_cpu_topology()
        for c in p_cores:
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '400000')
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', '3600000')
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'balance_power')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '6')
        for c in e_cores:
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '400000')
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', '2600000')
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'balance_power')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '8')
        for c in lpe_cores:
            cpu_dir = f'/sys/devices/system/cpu/cpu{c}'
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_min_freq', '400000')
            write_if_changed(f'{cpu_dir}/cpufreq/scaling_max_freq', '1800000')
            write_if_changed(f'{cpu_dir}/cpufreq/energy_performance_preference', 'power')
            write_if_changed(f'{cpu_dir}/power/energy_perf_bias', '12')
        for gt1_p in glob.glob('/sys/devices/pci0000:00/*/tile*/gt1/freq0/min_freq'):
            write_if_changed(gt1_p, '400')
        for gt0_dir in glob.glob('/sys/devices/pci0000:00/*/tile*/gt0/freq0'):
            gt0_rpn = read_text(os.path.join(gt0_dir, 'rpn_freq')) or '800'
            write_if_changed(os.path.join(gt0_dir, 'min_freq'), gt0_rpn)
        try:
            state_file.write_text('active\n')
        except Exception:
            pass
    else:
        mode = 'battery' if on_bat else 'ac'
        set_hybrid_topology(mode)
        set_gpu('auto', mode)
        try:
            if state_file.exists():
                state_file.unlink()
        except Exception:
            pass


def set_rapl_limits(mode: str) -> None:
    if mode in ('extreme_performance', 'performance'):
        pl1, pl2 = 65000000, 100000000
    elif mode == 'battery_boost':
        pl1, pl2 = 35000000, 55000000
    elif mode in ('max_battery', 'maximum_battery'):
        pl1, pl2 = 12000000, 20000000
    elif mode == 'battery':
        pl1, pl2 = 15000000, 32000000
    elif mode == 'cool_quiet':
        pl1, pl2 = 18000000, 30000000
    else:  # ac balanced sustained TDP
        pl1, pl2 = 35000000, 55000000

    if PLATFORM_PROFILE_PATH.exists():
        if mode in ('extreme_performance', 'performance'):
            write_if_changed(PLATFORM_PROFILE_PATH, 'performance')
        elif mode == 'battery_boost':
            write_if_changed(PLATFORM_PROFILE_PATH, 'balanced')
        elif mode in ('battery', 'max_battery', 'maximum_battery', 'cool_quiet'):
            write_if_changed(PLATFORM_PROFILE_PATH, 'low-power')
        else:
            write_if_changed(PLATFORM_PROFILE_PATH, 'balanced')

    rapl_base = pathlib.Path('/sys/class/powercap/intel-rapl')
    for d in rapl_base.glob('intel-rapl:*'):
        c0 = d / 'constraint_0_power_limit_uw'
        c1 = d / 'constraint_1_power_limit_uw'
        c0_max_raw = read_text(d / 'constraint_0_max_power_uw')
        c1_max_raw = read_text(d / 'constraint_1_max_power_uw')
        eff_pl1 = pl1
        eff_pl2 = pl2
        if c0_max_raw and c0_max_raw.isdigit() and int(c0_max_raw) > 5_000_000:
            eff_pl1 = min(pl1, int(c0_max_raw))
        if c1_max_raw and c1_max_raw.isdigit() and int(c1_max_raw) > 5_000_000:
            eff_pl2 = min(pl2, int(c1_max_raw))
        if c0.exists():
            write_if_changed(c0, str(eff_pl1))
        if c1.exists():
            write_if_changed(c1, str(eff_pl2))


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
    elif mode in ('max_battery', 'maximum_battery'):
        base_mode = 'battery'
        s = deepcopy(cfg['battery'])
        s['gnome_profile'] = 'power-saver'
        s['epp'] = 'power'
        s['pcie_aspm'] = 'powersupersave'
        s['turbo'] = False
    elif mode == 'cool_quiet':
        base_mode = 'battery' if on_battery_from_sysfs() else 'ac'
        s = deepcopy(cfg[base_mode])
        s['gnome_profile'] = 'balanced'
        s['epp'] = 'balance_power'
        s['pcie_aspm'] = 'powersave'
        s['hwp_dynamic_boost'] = 'off'
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
    set_hwp_dynamic_boost(s['hwp_dynamic_boost'])
    set_cpu_freq_floor(mode)
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
    pin_interactive_irqs()




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
_LAST_RAPL_WATTS: float | None = None


def _read_rapl_compute_uj() -> tuple[int, int] | None:
    """Read (energy_uj, max_energy_range_uj) from primary package RAPL node or fallback sub-domains."""
    p_path = pathlib.Path('/sys/class/powercap/intel-rapl:0/energy_uj')
    p_max = pathlib.Path('/sys/class/powercap/intel-rapl:0/max_energy_range_uj')
    try:
        if p_path.exists():
            e = int(p_path.read_text().strip())
            mx = int(p_max.read_text().strip()) if p_max.exists() else 262143328850
            return e, mx
    except Exception:
        pass
    c_path = pathlib.Path('/sys/class/powercap/intel-rapl:0:0/energy_uj')
    try:
        if c_path.exists():
            return int(c_path.read_text().strip()), 262143328850
    except Exception:
        pass
    return None


def power_now_watts() -> float | None:
    global _LAST_RAPL_UJ, _LAST_RAPL_TS, _LAST_RAPL_WATTS
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
    # Fallback to Intel RAPL Package + 1.8W platform baseline when on AC
    rapl = _read_rapl_compute_uj()
    if rapl is not None:
        now_uj, max_uj = rapl
        try:
            now_ts = time.monotonic()
            if _LAST_RAPL_UJ is not None and _LAST_RAPL_TS is not None:
                dt = now_ts - _LAST_RAPL_TS
                if dt >= 0.08:
                    delta = (now_uj - _LAST_RAPL_UJ) if now_uj >= _LAST_RAPL_UJ else ((max_uj - _LAST_RAPL_UJ) + now_uj)
                    w = 1.80 + delta / (dt * 1_000_000.0)
                    _LAST_RAPL_UJ, _LAST_RAPL_TS = now_uj, now_ts
                    if 0.5 <= w <= 220.0:
                        _LAST_RAPL_WATTS = round(w, 2)
                        return _LAST_RAPL_WATTS
                return _LAST_RAPL_WATTS
            # First sample over 90ms
            time.sleep(0.09)
            rapl2 = _read_rapl_compute_uj()
            now2_ts = time.monotonic()
            if rapl2 is not None and (now2_ts - now_ts) > 0:
                now2_uj, _ = rapl2
                delta = (now2_uj - now_uj) if now2_uj >= now_uj else ((max_uj - now_uj) + now2_uj)
                _LAST_RAPL_UJ, _LAST_RAPL_TS = now2_uj, now2_ts
                w = 1.80 + delta / ((now2_ts - now_ts) * 1_000_000.0)
                if 0.5 <= w <= 220.0:
                    _LAST_RAPL_WATTS = round(w, 2)
                    return _LAST_RAPL_WATTS
        except Exception:
            pass
    return _LAST_RAPL_WATTS


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
    for node in glob.glob('/sys/devices/pci0000:00/*/tile*/gt*/freq0/act_freq'):
        txt = read_text(node)
        if txt and txt.strip():
            return f"{txt.strip()} MHz (Intel Xe SLPC)"
    for node in glob.glob('/sys/devices/pci0000:00/*/tile*/gt*/freq0/cur_freq'):
        txt = read_text(node)
        if txt and txt.strip():
            return f"{txt.strip()} MHz (Intel Xe SLPC)"
    for node in sorted(glob.glob('/sys/class/drm/card*/device/pp_dpm_sclk')):
        txt = read_text(node) or ''
        for line in txt.splitlines():
            if '*' in line:
                return f"{line.replace('*', '').strip()} (AMD Radeon DPM)"
    for node in ['/sys/class/drm/card1/gt_min_freq_mhz', '/sys/class/drm/card0/gt_min_freq_mhz']:
        txt = read_text(node)
        if txt and txt.strip():
            return f"{txt.strip()} MHz (Intel i915)"
    return 'Dynamic'


def vaapi_current() -> str:
    drv = os.environ.get('LIBVA_DRIVER_NAME')
    if drv:
        return f"{drv} (Hardware)"
    if os.path.exists('/etc/profile.d/vaapi-intel.sh'):
        return 'Intel iHD (Hardware)'
    for v_path in glob.glob('/sys/bus/pci/devices/*/vendor'):
        cls_path = os.path.join(os.path.dirname(v_path), 'class')
        cls_v = read_text(cls_path) or ''
        if not cls_v.startswith('0x03'):
            continue
        vendor = read_text(v_path) or ''
        if vendor == '0x8086':
            return 'Intel iHD (Hardware)'
        if vendor == '0x1002':
            return 'AMD Mesa RadeonSI (Hardware)'
    return 'Auto (DRM/Mesa)'


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
        on = value in (True, 1, '1', 'on')
        node = LENOVO_VPC_PATH / 'conservation_mode'
        if node.exists():
            return write_if_changed(node, '1' if on else '0')
        for bat_thresh in sorted(glob.glob('/sys/class/power_supply/BAT*/charge_control_end_threshold')):
            return write_if_changed(bat_thresh, '80' if on else '100')
        return False
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


def _read_int_or_none(path: pathlib.Path) -> int | None:
    txt = read_text(path)
    if txt is None:
        return None
    try:
        return int(txt.strip())
    except ValueError:
        return None


def _active_usb_protocol(usb_type_raw: str | None) -> str:
    if not usb_type_raw:
        return 'USB-C'
    for tok in usb_type_raw.split():
        if tok.startswith('[') and tok.endswith(']'):
            inner = tok[1:-1]
            if inner == 'PD_PPS':
                return 'USB-PD PPS'
            if inner == 'PD':
                return 'USB-PD'
            if inner == 'C':
                return 'USB-C'
            return f'USB-{inner}'
    return 'USB-PD' if 'PD' in usb_type_raw else 'USB-C'


def dgpu_zombie_report(
    sysfs_pci: str | pathlib.Path = '/sys/bus/pci/devices',
    proc_root: str | pathlib.Path = '/proc',
) -> dict:
    """Detect discrete GPUs held in D0/active state and blame processes holding their device nodes."""
    pci_dir = pathlib.Path(sysfs_pci)
    if not pci_dir.exists():
        return {'dgpus': [], 'awake_count': 0, 'blockers': []}

    candidates = []
    for dev in sorted(pci_dir.iterdir()):
        cls = read_text(dev / 'class') or ''
        if not (cls.startswith('0x0300') or cls.startswith('0x0302')):
            continue
        vendor = read_text(dev / 'vendor') or ''
        device = read_text(dev / 'device') or ''
        boot_vga = read_text(dev / 'boot_vga') or '0'
        try:
            driver = (dev / 'driver').resolve().name
        except Exception:
            driver = 'unknown'
        runtime_status = read_text(dev / 'power' / 'runtime_status') or 'unknown'
        power_state = read_text(dev / 'power_state') or 'unknown'
        drm_nodes: set[str] = set()
        drm_dir = dev / 'drm'
        if drm_dir.is_dir():
            for child in drm_dir.iterdir():
                if child.name.startswith(('renderD', 'card')):
                    drm_nodes.add(f'/dev/dri/{child.name}')
        candidates.append({
            'slot': dev.name,
            'class': cls,
            'vendor': vendor,
            'device': device,
            'boot_vga': boot_vga,
            'driver': driver,
            'runtime_status': runtime_status,
            'power_state': power_state,
            'drm_nodes': drm_nodes,
        })

    dgpus = []
    match_nodes: set[str] = set()
    match_nvidia = False
    for g in candidates:
        is_dgpu = g['class'].startswith('0x0302') or (
            g['boot_vga'] != '1' and (len(candidates) > 1 or g['vendor'] != '0x8086')
        )
        if not is_dgpu:
            continue
        awake = g['runtime_status'] == 'active' or g['power_state'] == 'D0'
        if awake:
            match_nodes.update(g['drm_nodes'])
            if 'nvidia' in g['driver'].lower():
                match_nvidia = True
        dgpus.append({
            'slot': g['slot'],
            'vendor': g['vendor'],
            'device': g['device'],
            'driver': g['driver'],
            'runtime_status': g['runtime_status'],
            'power_state': g['power_state'],
            'awake': awake,
        })

    blockers = []
    if dgpus and any(g['awake'] for g in dgpus):
        p_root = pathlib.Path(proc_root)
        seen: set[tuple[int, str]] = set()
        if p_root.is_dir():
            for p_entry in p_root.iterdir():
                if not p_entry.name.isdigit():
                    continue
                fd_dir = p_entry / 'fd'
                if not fd_dir.is_dir():
                    continue
                try:
                    fds = list(fd_dir.iterdir())
                except OSError:
                    continue
                pid = int(p_entry.name)
                for fd_entry in fds:
                    try:
                        target = os.readlink(fd_entry)
                    except OSError:
                        continue
                    is_match = (target in match_nodes) or (match_nvidia and target.startswith('/dev/nvidia'))
                    if not is_match or (pid, target) in seen:
                        continue
                    seen.add((pid, target))
                    comm = read_text(p_entry / 'comm') or f'pid:{pid}'
                    blockers.append({'pid': pid, 'name': comm.strip(), 'node': target})
                    if len(blockers) >= 12:
                        break
                if len(blockers) >= 12:
                    break

    return {
        'dgpus': dgpus,
        'awake_count': sum(1 for g in dgpus if g['awake']),
        'blockers': blockers,
    }


def charger_pd_report(
    psy_root: str | pathlib.Path = '/sys/class/power_supply',
    typec_root: str | pathlib.Path = '/sys/class/typec',
) -> dict:
    """Inspect AC mains and USB-C Power Delivery supplies for negotiated V/A/W and slow-charger warnings."""
    psy_dir = pathlib.Path(psy_root)
    usb_supplies = []
    mains_online = False

    if psy_dir.is_dir():
        for entry in sorted(psy_dir.iterdir()):
            if entry.name.startswith('BAT'):
                continue
            ptype = (read_text(entry / 'type') or '').strip()
            if ptype == 'Battery':
                continue
            online = (read_text(entry / 'online') or '0').strip() == '1'
            if ptype == 'Mains':
                if online:
                    mains_online = True
                continue
            if not (ptype.startswith('USB') or entry.name.startswith('ucsi')):
                continue
            if not online:
                continue
            vmax = _read_int_or_none(entry / 'voltage_max') or 0
            vnow = _read_int_or_none(entry / 'voltage_now') or 0
            imax = _read_int_or_none(entry / 'current_max') or 0
            inow = _read_int_or_none(entry / 'current_now') or 0
            pnow = _read_int_or_none(entry / 'power_now') or 0
            volts_uv = vmax if vmax > 0 else vnow
            amps_ua = imax if imax > 0 else inow
            volts = round(volts_uv / 1_000_000.0, 2) if volts_uv > 0 else None
            amps = round(amps_ua / 1_000_000.0, 2) if amps_ua > 0 else None
            watts = None
            if pnow > 0:
                watts = round(pnow / 1_000_000.0, 1)
            elif volts is not None and amps is not None:
                watts = round(volts * amps, 1)
            proto = _active_usb_protocol(read_text(entry / 'usb_type'))
            usb_supplies.append({
                'name': entry.name,
                'protocol': proto,
                'volts': volts,
                'amps': amps,
                'watts': watts,
                'manufacturer': read_text(entry / 'manufacturer'),
                'model': read_text(entry / 'model_name'),
            })

    typec_pd_sink = False
    tc_dir = pathlib.Path(typec_root)
    if tc_dir.is_dir():
        for port in sorted(tc_dir.glob('port*')):
            if '-' in port.name:
                continue
            role = read_text(port / 'power_role') or ''
            opmode = read_text(port / 'power_operation_mode') or ''
            if '[sink]' in role and 'usb_power_delivery' in opmode:
                typec_pd_sink = True
                break

    if usb_supplies:
        best = max(usb_supplies, key=lambda x: x['watts'] or 0.0)
        watts = best['watts']
        slow = watts is not None and 0.0 < watts < 45.0
        if watts is not None and best['volts'] is not None and best['amps'] is not None:
            label = f"{best['protocol']} • {watts:.1f}W ({best['volts']:.0f}V/{best['amps']:.2f}A)"
        elif watts is not None:
            label = f"{best['protocol']} • {watts:.1f}W"
        else:
            label = f"{best['protocol']} Sink (Negotiated)"
        if slow:
            label = f"{label} [Slow <45W]"
        return {
            'source': 'usb_pd',
            'pd_active': 'PD' in best['protocol'] or typec_pd_sink,
            'protocol': best['protocol'],
            'volts': best['volts'],
            'amps': best['amps'],
            'watts': watts,
            'slow_charger': slow,
            'port': best['name'],
            'label': label,
        }

    if mains_online:
        return {
            'source': 'usb_pd' if typec_pd_sink else 'ac_mains',
            'pd_active': typec_pd_sink,
            'protocol': 'USB-PD' if typec_pd_sink else 'AC Mains',
            'volts': None,
            'amps': None,
            'watts': None,
            'slow_charger': False,
            'port': 'ACAD',
            'label': 'USB-PD Sink Active' if typec_pd_sink else 'AC Mains Adapter',
        }

    return {
        'source': 'battery',
        'pd_active': False,
        'protocol': 'Battery',
        'volts': None,
        'amps': None,
        'watts': None,
        'slow_charger': False,
        'port': None,
        'label': 'On Battery',
    }


def cpu_topology_current() -> str:
    online_raw = read_text('/sys/devices/system/cpu/online') or ''
    online_ids = _parse_cpu_list(online_raw)
    total_cpus = os.cpu_count() or len(online_ids) or 1
    online_count = len(online_ids) if online_ids else total_cpus
    p_freq = read_text('/sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq') or '0'
    try:
        ghz = int(p_freq) / 1_000_000.0
    except Exception:
        ghz = 0.0
    p_c, e_c, lpe_c = detect_cpu_topology()
    if e_c or lpe_c:
        tier = f"{len(p_c)}P+{len(e_c)}E+{len(lpe_c)}LP-E" if lpe_c else f"{len(p_c)}P+{len(e_c)}E"
        return f"{online_count}/{total_cpus} Online ({tier} • {ghz:.1f} GHz)"
    return f"{online_count}/{total_cpus} Online ({ghz:.1f} GHz Max)"


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
        'charger_pd': charger_pd_report(),
        'dgpu': dgpu_zombie_report(),
        'config': load_config(),
        'sensor': load_sensor_config(),
    }


SAFE_UNTOUCHABLE_PROCS = frozenset({
    'systemd', 'init', 'gnome-shell', 'mutter', 'xorg', 'xwayland',
    'dbus-daemon', 'dbus-broker', 'pipewire', 'wireplumber', 'pulseaudio',
    'hyprland', 'sway', 'kwin_wayland', 'kwin_x11',
    'kworker', 'irq/', 'rcu_', 'migration/', 'watchdog',
    'ff-power-manager', 'ff-presence-session', 'ff-presence-sensor',
})


def estimate_process_power_impact(
    procs: list[dict],
    sys_watts: float,
    energy_now_wh: float | None = None,
    total_score_override: float | None = None,
) -> list[dict]:
    """Attribute dynamic system watts and remaining battery minutes lost to active processes."""
    w_sys = max(0.0, float(sys_watts or 0.0))
    w_base = min(3.2, w_sys * 0.35) if w_sys > 0.0 else 0.0
    w_dyn = max(0.0, w_sys - w_base)
    weights = [
        max(0.0, float(p.get('cpu_pct', 0.0)) * 4.0 + float(p.get('wakeups_per_sec', 0.0)) * 0.05)
        for p in procs
    ]
    total_w = float(total_score_override) if (total_score_override and total_score_override > 0) else sum(weights)
    e_wh = float(energy_now_wh) if (energy_now_wh is not None and energy_now_wh > 0) else 0.0

    enriched = []
    for p, wt in zip(procs, weights):
        item = dict(p)
        est_w = round(min(w_sys, w_dyn * (wt / total_w)), 2) if (total_w > 0.0 and w_dyn > 0.0) else 0.0
        mins_lost = 0.0
        if e_wh > 0.0 and w_sys > 0.5 and est_w > 0.01:
            hrs_now = e_wh / w_sys
            hrs_without = e_wh / max(0.8, w_sys - est_w)
            mins_lost = round(min(600.0, max(0.0, (hrs_without - hrs_now) * 60.0)), 1)
        item['est_watts'] = est_w
        item['minutes_lost'] = mins_lost
        enriched.append(item)
    return enriched


def throttle_process(pid: int, action: str = 'pause', proc_root: str | pathlib.Path = '/proc') -> dict:
    """Safely pause (SIGSTOP), resume (SIGCONT), or deprioritize (nice+ionice) a background process."""
    if action not in ('pause', 'resume', 'lowprio'):
        return {'ok': False, 'error': f'Unsupported action: {action}'}
    if pid <= 1 or pid == os.getpid():
        return {'ok': False, 'error': f'Refusing to touch protected PID {pid}'}

    comm_path = pathlib.Path(proc_root) / str(pid) / 'comm'
    comm = (read_text(comm_path) or '').strip()
    if not comm:
        return {'ok': False, 'error': f'Process {pid} no longer exists'}
    comm_lc = comm.lower()
    if any(comm_lc == p or comm_lc.startswith(p) for p in SAFE_UNTOUCHABLE_PROCS):
        return {'ok': False, 'error': f'Refusing to throttle critical system process ({comm})'}

    try:
        if action == 'pause':
            os.kill(pid, signal.SIGSTOP)
        elif action == 'resume':
            os.kill(pid, signal.SIGCONT)
        elif action == 'lowprio':
            os.setpriority(os.PRIO_PROCESS, pid, 19)
            subprocess.run(['/usr/bin/ionice', '-c', '3', '-p', str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return {'ok': True, 'pid': pid, 'name': comm, 'action': action}
    except PermissionError:
        return {'ok': False, 'error': f'Permission denied for {comm} (PID {pid})'}
    except ProcessLookupError:
        return {'ok': False, 'error': f'Process {pid} exited'}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}


