from __future__ import annotations

import getpass
import io
import json
import os
import pathlib
import platform
import re
import socket
import subprocess
import sys
import tarfile
import time

from .core import (
    CONFIG_PATH,
    DEFAULT_CONFIG,
    PRESETS,
    RUN_DIR,
    charger_pd_report,
    detect_cpu_topology,
    dgpu_zombie_report,
    load_config,
    on_battery_from_sysfs,
    read_text,
    save_and_apply_config,
    set_lenovo_feature,
    status_snapshot,
    throttle_process,
)

_MAC_RE = re.compile(r'\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b')
_IP_RE = re.compile(r'\b(?!127\.0\.0\.1\b)(?:\d{1,3}\.){3}\d{1,3}\b')
_UUID_RE = re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b')
_BLOCKED_BUNDLE_PREFIXES = ('/etc', '/usr', '/bin', '/sbin', '/lib', '/lib64', '/boot', '/sys', '/proc', '/dev', '/root')


def sanitize_diagnostics_text(raw: str) -> str:
    """Scrub usernames, hostnames, MACs, UUIDs, home paths, and non-loopback IPs from bundle text."""
    if not raw:
        return ''
    out = raw
    try:
        user = getpass.getuser()
        if user and len(user) > 2:
            out = out.replace(f'/home/{user}', '/home/<USER>')
            out = re.sub(rf'\b{re.escape(user)}\b', '<USER>', out)
    except Exception:
        pass
    try:
        host = socket.gethostname()
        if host and len(host) > 2:
            out = re.sub(rf'\b{re.escape(host)}\b', '<HOST>', out)
    except Exception:
        pass
    out = _MAC_RE.sub('<MAC>', out)
    out = _IP_RE.sub('<IP>', out)
    out = _UUID_RE.sub('<UUID>', out)
    return out


def _detect_tof_hardware() -> bool:
    if (RUN_DIR / 'sensor_telemetry.json').exists():
        return True
    hid_root = pathlib.Path('/sys/class/hidraw')
    if hid_root.is_dir():
        for dev in hid_root.iterdir():
            uev = read_text(dev / 'device' / 'uevent') or ''
            if '8087' in uev and '0AC2' in uev.upper():
                return True
    return False


def _detect_desktop_env() -> str:
    if os.environ.get('HYPRLAND_INSTANCE_SIGNATURE'):
        return 'Hyprland'
    de = os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
    if 'KDE' in de or 'PLASMA' in de:
        return 'KDE Plasma'
    if 'GNOME' in de:
        return 'GNOME'
    return de or 'Unknown'


def hardware_setup_scan(apply_recommended: bool = False) -> dict:
    """Inspect machine capabilities and recommend/apply tailored power & presence settings."""
    p_c, e_c, lpe_c = detect_cpu_topology()
    snap = status_snapshot()
    pd = snap.get('charger_pd') or charger_pd_report()
    dgpu = snap.get('dgpu') or dgpu_zombie_report()
    tof_detected = _detect_tof_hardware()
    desktop = _detect_desktop_env()
    mem_sleep = read_text('/sys/power/mem_sleep') or 'unknown'
    vendor = read_text('/sys/class/dmi/id/sys_vendor') or 'Generic'
    product = read_text('/sys/class/dmi/id/product_name') or 'Laptop'

    bat_preset = 'balanced' if (e_c or lpe_c) else 'maximum_battery'
    if pd.get('slow_charger'):
        ac_preset = 'cool_quiet'
    else:
        ac_preset = 'balanced'

    recommendations = {
        'battery_preset': bat_preset,
        'ac_preset': ac_preset,
        'conservation_mode': bool(snap.get('lenovo', {}).get('supported')),
        'adaptive_refresh': desktop in ('GNOME', 'Hyprland', 'KDE Plasma'),
        'tof_presence': tof_detected,
    }

    applied = False
    apply_error = None
    if apply_recommended:
        try:
            cfg = load_config()
            cfg['battery'].update(PRESETS['battery'][bat_preset])
            cfg['ac'].update(PRESETS['ac'].get(ac_preset, DEFAULT_CONFIG['ac']))
            save_and_apply_config(cfg)
            if recommendations['conservation_mode']:
                set_lenovo_feature('conservation_mode', True)
            applied = True
        except Exception as exc:
            apply_error = str(exc)

    return {
        'hardware': {
            'vendor': vendor,
            'model': product,
            'desktop': desktop,
            'cpu_topology': snap.get('cpu_topology'),
            'cpu_tiers': {'p': len(p_c), 'e': len(e_c), 'lpe': len(lpe_c)},
            'gpu_clock': snap.get('gpu_perf'),
            'vaapi': snap.get('vaapi'),
            'dgpu_awake': dgpu.get('awake_count', 0),
            'dgpu_count': len(dgpu.get('dgpus', [])),
            'charger_pd': pd,
            'tof_sensor': tof_detected,
            'mem_sleep': mem_sleep,
            'lenovo_acpi': bool(snap.get('lenovo', {}).get('supported')),
        },
        'recommendations': recommendations,
        'applied': applied,
        'apply_error': apply_error,
    }


def _safe_run_text(cmd: list[str], timeout: float = 2.5) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=timeout)
    except Exception as exc:
        return f'<unavailable: {exc}>'


def create_diagnostics_bundle(output_path: str | pathlib.Path | None = None) -> dict:
    """Create a sanitized .tar.gz diagnostics bundle suitable for GitHub issues or OEM review."""
    ts = time.strftime('%Y%m%d-%H%M%S')
    if output_path is None:
        out_path = pathlib.Path.home() / f'ff-power-diagnostics-{ts}.tar.gz'
    else:
        out_path = pathlib.Path(output_path).expanduser()
        if out_path.is_symlink():
            raise ValueError(f'Refusing symlink output path: {out_path}')
        resolved_str = str(out_path.resolve(strict=False))
        if any(resolved_str == p or resolved_str.startswith(p + '/') for p in _BLOCKED_BUNDLE_PREFIXES):
            raise ValueError(f'Refusing to write diagnostics bundle into system path: {resolved_str}')
    out_path.parent.mkdir(parents=True, exist_ok=True)

    setup_info = hardware_setup_scan(apply_recommended=False)
    snap = status_snapshot()
    ffctl_bin = '/usr/local/bin/ffctl' if pathlib.Path('/usr/local/bin/ffctl').exists() else 'ffctl'

    sleep_report = None
    sleep_file = pathlib.Path('/var/lib/ff-power-manager/last_sleep.json')
    if sleep_file.exists():
        try:
            sleep_report = json.loads(sleep_file.read_text(encoding='utf-8'))
        except Exception:
            sleep_report = None

    summary = {
        'generated_at': ts,
        'kernel': platform.release(),
        'arch': platform.machine(),
        'config_exists': CONFIG_PATH.exists(),
        'setup_scan': setup_info,
        'status': snap,
        'sleep_report': sleep_report,
    }

    sections = {
        'summary.json': sanitize_diagnostics_text(json.dumps(summary, indent=2, ensure_ascii=False)),
        'doctor.json': sanitize_diagnostics_text(_safe_run_text([ffctl_bin, 'doctor', '--json'])),
        'blame.json': sanitize_diagnostics_text(_safe_run_text([ffctl_bin, 'blame', '--json'])),
        'acpi_wakeup.txt': sanitize_diagnostics_text(read_text('/proc/acpi/wakeup') or '<unavailable>'),
        'autoboost_journal.txt': sanitize_diagnostics_text(
            _safe_run_text(['journalctl', '-u', 'ff-power-autoboost.service', '-n', '40', '--no-pager'])
        ),
    }

    with tarfile.open(out_path, 'w:gz') as tf:
        for fname, text in sections.items():
            raw = text.encode('utf-8', errors='replace')
            ti = tarfile.TarInfo(name=f'ff-power-diagnostics/{fname}')
            ti.size = len(raw)
            ti.mtime = int(time.time())
            tf.addfile(ti, io.BytesIO(raw))
    os.chmod(out_path, 0o600)

    return {
        'path': str(out_path),
        'size_bytes': out_path.stat().st_size,
        'sections': list(sections.keys()),
    }


def _print_setup_human(res: dict) -> None:
    hw = res['hardware']
    rec = res['recommendations']
    print('=== FF Power Manager Hardware Setup Wizard (ffctl setup) ===')
    print(f"  Machine         : {hw['vendor']} {hw['model']} ({hw['desktop']})")
    print(f"  CPU Topology    : {hw['cpu_topology']}")
    print(f"  iGPU / VA-API   : {hw['gpu_clock']} | {hw['vaapi']}")
    print(f"  Discrete GPU    : {hw['dgpu_count']} detected ({hw['dgpu_awake']} active)")
    print(f"  Charger / PD    : {hw['charger_pd'].get('label', '—')}")
    print(f"  ToF Radar (HID) : {'Detected (ST VL53L1)' if hw['tof_sensor'] else 'Not detected'}")
    print(f"  Sleep Modes     : {hw['mem_sleep']}")
    print('\nRecommended Settings:')
    print(f"  Battery Profile : {rec['battery_preset']} | AC Profile: {rec['ac_preset']}")
    print(f"  80% Conservation: {'Recommended ON' if rec['conservation_mode'] else 'N/A'}")
    print(f"  Adaptive Refresh: {'Recommended ON (60<->Max Hz)' if rec['adaptive_refresh'] else 'Manual'}")
    if res['applied']:
        print('\n✓ Recommended profile applied successfully.')
    elif res['apply_error']:
        print(f"\n! Apply skipped/failed: {res['apply_error']}")
    else:
        print('\nTip: Run `ffctl setup --apply` to apply these recommendations automatically.')


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print('Usage: python3 -m fpm.tools <setup|bundle> [--apply] [--json] [path]', file=sys.stderr)
        return 2
    cmd = argv[0]
    as_json = '--json' in argv or '-j' in argv
    if cmd == 'setup':
        do_apply = '--apply' in argv
        res = hardware_setup_scan(apply_recommended=do_apply)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            _print_setup_human(res)
        return 1 if res.get('apply_error') else 0

    if cmd == 'bundle':
        targets = [a for a in argv[1:] if not a.startswith('-')]
        out = targets[0] if targets else None
        res = create_diagnostics_bundle(out)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"✓ Diagnostics bundle saved: {res['path']} ({res['size_bytes']} bytes)")
        return 0

    if cmd == 'throttle':
        targets = [a for a in argv[1:] if not a.startswith('-')]
        if not targets or not targets[0].isdigit():
            print('Usage: ffctl throttle PID [pause|resume|lowprio] [--json]', file=sys.stderr)
            return 2
        pid = int(targets[0])
        action = targets[1] if len(targets) > 1 else 'pause'
        res = throttle_process(pid, action=action)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        elif res.get('ok'):
            print(f"✓ {res['action'].title()} applied to {res['name']} (PID {pid})")
        else:
            print(f"Error: {res.get('error', 'failed')}", file=sys.stderr)
        return 0 if res.get('ok') else 1

    print(f'Unknown command: {cmd}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
