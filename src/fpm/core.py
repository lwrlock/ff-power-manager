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
        'epp': 'balance_power',
        'turbo': True,
        'wifi_power_save': False,
        'nvme_runtime_pm': 'auto',
        'gpu_runtime_pm': 'system',
        'pcie_aspm': 'powersupersave',
        'usb_autosuspend': 'system',
        'audio_powersave': 'on',
        'hwp_dynamic_boost': 'system',
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
            'epp': 'balance_power',
            'turbo': True,
            'wifi_power_save': False,
            'nvme_runtime_pm': 'auto',
            'gpu_runtime_pm': 'system',
            'pcie_aspm': 'powersupersave',
            'usb_autosuspend': 'system',
            'audio_powersave': 'on',
            'hwp_dynamic_boost': 'system',
        },
        'maximum_battery': {
            'gnome_profile': 'balanced',
            'epp': 'balance_power',
            'turbo': True,
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
            'turbo': True,
            'wifi_power_save': False,
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
                err = res.stderr.strip() or 'Yetkilendirme hatası'
                raise PermissionError(f'Kaydedilemedi: {err}')
        else:
            raise


def save_and_apply_config(cfg: dict) -> None:
    valid = _merge_valid(DEFAULT_CONFIG, cfg)
    helper = pathlib.Path('/usr/local/lib/ff-power-manager/ff-power-helper')
    if helper.exists() and os.geteuid() != 0:
        cmd = ['pkexec', str(helper), 'save-and-apply', json.dumps(valid)]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            err = res.stderr.strip() or 'Yetkilendirme veya uygulama hatası'
            raise PermissionError(f'Uygulanamadı: {err}')
    else:
        save_config(valid)
        try:
            from .power_apply import apply_current
            apply_current()
        except Exception as exc:
            raise RuntimeError(f'Profil uygulanamadı: {exc}')


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
                err = res.stderr.strip() or 'Yetkilendirme hatası'
                raise PermissionError(f'Sensor ayarları kaydedilemedi: {err}')
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


def set_gpu(value: str) -> None:
    if value == 'system':
        return
    for dev in glob.glob('/sys/bus/pci/devices/*'):
        vendor = read_text(os.path.join(dev, 'vendor'))
        cls = read_text(os.path.join(dev, 'class'))
        if vendor == '0x8086' and cls and cls.startswith('0x03'):
            write_if_changed(os.path.join(dev, 'power/control'), value)


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


def optimize_touchpad() -> None:
    patterns = [
        '/sys/bus/i2c/devices/i2c-SYNA*/power/control',
        '/sys/devices/pci0000:00/0000:00:15.*/power/control',
        '/sys/devices/pci0000:00/0000:00:15.*/i2c_designware.*/power/control',
    ]
    for pattern in patterns:
        for path in glob.glob(pattern):
            write_if_changed(path, 'on')


def apply(mode: str, cfg: dict | None = None) -> None:
    cfg = cfg or load_config()
    s = cfg[mode]
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        (RUN_DIR / 'power.mode').write_text(mode)
    except Exception:
        pass
    gnome_prof = s['gnome_profile']
    if mode == 'battery' and gnome_prof == 'power-saver':
        gnome_prof = 'balanced'
    set_profile(gnome_prof)
    set_epp(s['epp'])
    set_turbo(s['turbo'])
    set_hwp_dynamic_boost(s['hwp_dynamic_boost'])
    set_wifi_ps(s['wifi_power_save'])
    set_nvme(s['nvme_runtime_pm'])
    set_gpu(s['gpu_runtime_pm'])
    set_pcie_aspm(s['pcie_aspm'])
    set_usb(s['usb_autosuspend'])
    set_audio(s['audio_powersave'])
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
            return '60 Hz (Pil Tasarrufu)'
        elif '120' in raw:
            return '120 Hz + VRR (Akıcı)'
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
        'presence_state': read_text(STATE_FILE),
        'config': load_config(),
        'sensor': load_sensor_config(),
    }
