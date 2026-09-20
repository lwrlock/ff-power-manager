from __future__ import annotations

import json
import os
import subprocess
import sys

from .core import (
    ALLOWED, PRESETS, apply, load_config, on_battery_from_sysfs,
    save_config, save_sensor_config, status_snapshot,
)

SYSTEM_SENSOR = 'ff-presence-sensor.service'


def parse_value(key, value):
    if key in ('turbo', 'wifi_power_save'):
        if value == 'system':
            return 'system'
        if value.lower() not in ('true', 'false'):
            raise ValueError('true/false/system expected')
        return value.lower() == 'true'
    return value


def validate(mode, key, value):
    return mode in ('battery', 'ac') and key in ALLOWED and value in ALLOWED[key]


def systemctl(*args):
    return subprocess.run(['/usr/bin/systemctl', *args], check=False).returncode


def usage():
    print('''Usage:
  ffctl status
  ffctl apply
  ffctl set-bulk MODE key=value [...]
  ffctl preset MODE NAME
  ffctl sensor-enable
  ffctl sensor-disable
  ffctl sensor-timeout SECONDS
  ffctl sensor-stability SILENCE REPORTS WINDOW
  ffctl safe-reset''')


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        usage(); return 2
    cmd = argv[0]
    if os.geteuid() != 0 and cmd != 'status':
        print('Bu komut root/pkexec ile çalıştırılmalı.', file=sys.stderr)
        return 1

    if cmd == 'status':
        print(json.dumps(status_snapshot(), indent=2, ensure_ascii=False))
        return 0

    if cmd == 'apply':
        mode = 'battery' if on_battery_from_sysfs() else 'ac'
        apply(mode, load_config())
        print(f'applied {mode}')
        return 0

    if cmd == 'set-bulk':
        if len(argv) < 3:
            usage(); return 2
        mode = argv[1]
        cfg = load_config()
        for item in argv[2:]:
            if '=' not in item:
                print(f'bad pair: {item}', file=sys.stderr); return 2
            key, raw = item.split('=', 1)
            try:
                val = parse_value(key, raw)
            except ValueError as exc:
                print(str(exc), file=sys.stderr); return 2
            if not validate(mode, key, val):
                print(f'invalid {mode}.{key}={raw}', file=sys.stderr); return 2
            cfg[mode][key] = val
        save_config(cfg)
        apply('battery' if on_battery_from_sysfs() else 'ac', cfg)
        print('saved and applied')
        return 0

    if cmd == 'preset':
        if len(argv) != 3:
            usage(); return 2
        mode, name = argv[1], argv[2]
        if mode not in PRESETS or name not in PRESETS[mode]:
            print('unknown preset', file=sys.stderr); return 2
        cfg = load_config()
        cfg[mode].update(PRESETS[mode][name])
        save_config(cfg)
        apply('battery' if on_battery_from_sysfs() else 'ac', cfg)
        print(f'preset {mode}/{name} saved')
        return 0

    if cmd == 'sensor-enable':
        return systemctl('enable', '--now', SYSTEM_SENSOR)

    if cmd == 'sensor-disable':
        rc = systemctl('disable', '--now', SYSTEM_SENSOR)
        subprocess.run(
            ['/usr/bin/python3', '-m', 'fpm.sensor', '--disable'], check=False,
            env={**os.environ, 'PYTHONPATH': '/usr/local/lib/ff-power-manager'},
        )
        return rc

    if cmd == 'sensor-timeout':
        if len(argv) != 2:
            usage(); return 2
        value = float(argv[1])
        if not 2.0 <= value <= 10.0:
            print('timeout 2.0-10.0 saniye olmalı', file=sys.stderr); return 2
        save_sensor_config({'silence_timeout': value})
        if systemctl('is-active', '--quiet', SYSTEM_SENSOR) == 0:
            systemctl('restart', SYSTEM_SENSOR)
        print('sensor timeout saved')
        return 0


    if cmd == 'sensor-stability':
        if len(argv) != 4:
            usage(); return 2
        silence = float(argv[1])
        reports = int(argv[2])
        window = float(argv[3])
        if not 2.0 <= silence <= 10.0:
            print('silence 2.0-10.0 saniye olmalı', file=sys.stderr); return 2
        if not 1 <= reports <= 5:
            print('reports 1-5 olmalı', file=sys.stderr); return 2
        if not 1.0 <= window <= 8.0:
            print('window 1.0-8.0 saniye olmalı', file=sys.stderr); return 2
        save_sensor_config({
            'silence_timeout': silence,
            'present_confirm_reports': reports,
            'present_confirm_window': window,
        })
        if systemctl('is-active', '--quiet', SYSTEM_SENSOR) == 0:
            systemctl('restart', SYSTEM_SENSOR)
        print('sensor stability saved')
        return 0

    if cmd == 'safe-reset':
        systemctl('disable', '--now', SYSTEM_SENSOR)
        subprocess.run(
            ['/usr/bin/python3', '-m', 'fpm.sensor', '--disable'], check=False,
            env={**os.environ, 'PYTHONPATH': '/usr/local/lib/ff-power-manager'},
        )
        cfg = load_config()
        cfg['battery'].update(PRESETS['battery']['recommended'])
        cfg['ac'].update(PRESETS['ac']['recommended'])
        save_config(cfg)
        apply('battery' if on_battery_from_sysfs() else 'ac', cfg)
        print('safe reset applied; sensor disabled')
        return 0

    usage(); return 2


if __name__ == '__main__':
    raise SystemExit(main())
