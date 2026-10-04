from __future__ import annotations

import glob
import json
import os
import pathlib
import subprocess
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
        'epp': 'balance_performance',
        'turbo': True,
        'wifi_power_save': True,
        'nvme_runtime_pm': 'auto',
        'gpu_runtime_pm': 'auto',
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
        'gpu_runtime_pm': 'system',
        'pcie_aspm': 'system',
        'usb_autosuspend': 'system',
        'audio_powersave': 'on',
        'hwp_dynamic_boost': 'system',
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
            'epp': 'balance_performance',
            'turbo': True,
            'wifi_power_save': True,
            'nvme_runtime_pm': 'auto',
            'gpu_runtime_pm': 'auto',
            'pcie_aspm': 'powersupersave',
            'usb_autosuspend': 'auto',
            'audio_powersave': 'on',
            'hwp_dynamic_boost': 'on',
        },
        'maximum_battery': {
            'gnome_profile': 'power-saver',
            'epp': 'power',
            'turbo': False,
            'wifi_power_save': True,
            'nvme_runtime_pm': 'auto',
            'gpu_runtime_pm': 'auto',
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
            'wifi_power_save': True,
            'nvme_runtime_pm': 'auto',
            'gpu_runtime_pm': 'auto',
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


def save_config(cfg: dict) -> None:
    valid = _merge_valid(DEFAULT_CONFIG, cfg)
    try:
        atomic_json_write(CONFIG_PATH, valid)
    except (PermissionError, OSError):
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists():
            cmd = ['pkexec', str(helper), 'save-config', json.dumps(valid)]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                err = res.stderr.strip() or 'Authorization error'
                raise PermissionError(f'Failed to save configuration: {err}')
        else:
            raise


def save_and_apply_config(cfg: dict) -> None:
    valid = _merge_valid(DEFAULT_CONFIG, cfg)
    helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
    if helper.exists() and os.geteuid() != 0:
        cmd = ['pkexec', str(helper), 'save-and-apply', json.dumps(valid)]
        res = subprocess.run(cmd, capture_output=True, text=True)
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
        'silence_timeout': max(2.0, min(10.0, val)),
        'present_confirm_reports': max(1, min(5, reports)),
        'present_confirm_window': max(1.0, min(8.0, win)),
    }
    try:
        atomic_json_write(SENSOR_CONFIG_PATH, payload)
    except (PermissionError, OSError):
        helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
        if helper.exists():
            cmd = ['pkexec', str(helper), 'save-sensor', json.dumps(payload)]
            res = subprocess.run(cmd, capture_output=True, text=True)
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


def set_epp(value: str) -> None:
    if value == 'system':
        return
    for p in glob.glob('/sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference'):
        write_if_changed(p, value)
    bias_map = {
        'power': '15',
        'balance_power': '8',
        'default': '6',
        'balance_performance': '4',
        'performance': '0',
    }
    if value in bias_map:
        for p in glob.glob('/sys/devices/system/cpu/cpu*/power/energy_perf_bias'):
            write_if_changed(p, bias_map[value])


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
        if wifi_ps_current(iface) != want:
            run(['/usr/sbin/iw', 'dev', iface, 'set', 'power_save', want])


def set_nvme(value: str) -> None:
    if value == 'system':
        return
    for p in glob.glob('/sys/class/nvme/nvme*/device/power/control'):
        write_if_changed(p, value)
    # Enable Autonomous Power State Transition (APST) for deepest NVMe PS4 (0.005W) sleep
    apst_node = '/sys/module/nvme_core/parameters/default_ps_max_latency_us'
    if os.path.exists(apst_node):
        write_if_changed(apst_node, '5500' if value == 'auto' else '0')


def set_pci_runtime_pm(value: str = 'auto') -> None:
    if value not in ('auto', 'on'):
        return
    for ctrl in glob.glob('/sys/bus/pci/devices/*/power/control'):
        write_if_changed(ctrl, value)


def set_cpu_freq_floor() -> None:
    # Ensure CPU minimum frequency floor is at least 800 MHz (never 400 MHz), preventing stutter
    for f in glob.glob('/sys/devices/system/cpu/cpu*/cpufreq/scaling_min_freq'):
        try:
            cur = int(pathlib.Path(f).read_text().strip())
            if cur < 800000:
                write_if_changed(f, '800000')
        except Exception:
            pass


def set_gpu(value: str) -> None:
    if value == 'system':
        return
    for dev in glob.glob('/sys/bus/pci/devices/*'):
        vendor = read_text(os.path.join(dev, 'vendor'))
        cls = read_text(os.path.join(dev, 'class'))
        if vendor == '0x8086' and cls and cls.startswith('0x03'):
            write_if_changed(os.path.join(dev, 'power/control'), value)

    # Native Intel Xe driver (Arrow Lake-H / Lunar Lake tile* gt*/freq0)
    for gt_freq in glob.glob('/sys/devices/pci0000:00/0000:00:02.0/tile*/gt*/freq0'):
        power_prof = os.path.join(gt_freq, 'power_profile')
        if os.path.exists(power_prof):
            write_if_changed(power_prof, 'power_saving' if value == 'auto' else 'base')
        min_node = os.path.join(gt_freq, 'min_freq')
        if os.path.exists(min_node):
            write_if_changed(min_node, '800')
        max_node = os.path.join(gt_freq, 'max_freq')
        if os.path.exists(max_node):
            rp0_node = os.path.join(gt_freq, 'rp0_freq')
            rp0 = read_text(rp0_node)
            target_max = rp0.strip() if rp0 and rp0.strip().isdigit() else '2350'
            write_if_changed(max_node, target_max)

    # Intel Arc & Iris Xe GPU power optimization (GuC SLPC & RC6 legacy i915 nodes)
    for card in glob.glob('/sys/class/drm/card*'):
        slpc_node = os.path.join(card, 'gt/gt0/slpc_power_profile')
        if os.path.exists(slpc_node):
            write_if_changed(slpc_node, 'power_saving' if value == 'auto' else 'base')
        boost_node = os.path.join(card, 'gt/gt0/rps_boost_freq_mhz')
        if os.path.exists(boost_node):
            write_if_changed(boost_node, '2350')
        min_node = os.path.join(card, 'gt_min_freq_mhz')
        if os.path.exists(min_node):
            # Keep minimum GPU frequency at hardware RP1 (800 MHz) or 500 MHz, never 100 MHz,
            # preventing video stuttering and UI lag in GNOME Wayland while consuming negligible idle power
            rp1_node = os.path.join(card, 'gt_RP1_freq_mhz')
            rp1 = read_text(rp1_node)
            target_min = rp1 if rp1 and rp1.isdigit() else '500'
            write_if_changed(min_node, target_min)
        max_node = os.path.join(card, 'gt_max_freq_mhz')
        if os.path.exists(max_node):
            write_if_changed(max_node, '2350')


def set_pcie_aspm(value: str) -> None:
    if value == 'system':
        return
    p = '/sys/module/pcie_aspm/parameters/policy'
    if os.path.exists(p):
        write_if_changed(p, value)


def set_usb(value: str) -> None:
    if value != 'auto':
        return
    for p in glob.glob('/sys/bus/usb/devices/*/power/control'):
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


def optimize_touchpad() -> None:
    # Only keep the touchpad device itself awake to prevent lag,
    # without blocking the Intel LPSS host controller from low-power states
    for path in glob.glob('/sys/bus/i2c/devices/i2c-SYNA*/power/control'):
        write_if_changed(path, 'on')


def apply_kernel_tunings(mode: str) -> None:
    if mode == 'battery':
        write_if_changed('/proc/sys/vm/laptop_mode', '5')
        write_if_changed('/proc/sys/vm/dirty_writeback_centisecs', '6000')
        write_if_changed('/proc/sys/kernel/nmi_watchdog', '0')
        for p in glob.glob('/sys/class/scsi_host/host*/link_power_management_policy'):
            write_if_changed(p, 'med_power_with_dipm')
    else:
        write_if_changed('/proc/sys/vm/laptop_mode', '0')
        write_if_changed('/proc/sys/vm/dirty_writeback_centisecs', '1500')
        for p in glob.glob('/sys/class/scsi_host/host*/link_power_management_policy'):
            write_if_changed(p, 'max_performance')
    # Always keep VFS cache pressure optimized for snappy desktop responsiveness
    write_if_changed('/proc/sys/vm/vfs_cache_pressure', '50')


def apply(mode: str, cfg: dict | None = None) -> None:
    cfg = cfg or load_config()
    s = cfg[mode]
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
    set_cpu_freq_floor()
    set_hwp_dynamic_boost(s['hwp_dynamic_boost'])
    set_wifi_ps(s['wifi_power_save'])
    set_nvme(s['nvme_runtime_pm'])
    set_pci_runtime_pm('auto' if s['gpu_runtime_pm'] == 'auto' else 'on')
    set_gpu(s['gpu_runtime_pm'])
    set_pcie_aspm(s['pcie_aspm'])
    set_usb(s['usb_autosuspend'])
    set_audio(s['audio_powersave'])
    apply_kernel_tunings(mode)
    optimize_touchpad()



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


def power_now_watts() -> float | None:
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


