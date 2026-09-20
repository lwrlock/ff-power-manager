from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

from .core import (
    CONFIG_PATH,
    SENSOR_CONFIG_PATH,
    atomic_json_write,
    load_config,
    load_sensor_config,
    _merge_valid,
    DEFAULT_CONFIG,
    DEFAULT_SENSOR_CONFIG,
)
from .power_apply import apply_current


SYSTEM_SENSOR_UNIT = "ff-presence-sensor.service"


def cmd_apply() -> int:
    applied = apply_current()
    sys.stdout.write(f"Applied profile: {applied}\n")
    return 0


def cmd_save_config(data_str: str | None = None) -> int:
    if not data_str:
        data_str = sys.stdin.read()
    try:
        data = json.loads(data_str)
        if not isinstance(data, dict):
            raise ValueError("Config root must be a JSON object")
        valid = _merge_valid(DEFAULT_CONFIG, data)
        atomic_json_write(CONFIG_PATH, valid)
        return 0
    except Exception as exc:
        sys.stderr.write(f"Error saving config: {exc}\n")
        return 1


def cmd_save_and_apply(data_str: str | None = None) -> int:
    if cmd_save_config(data_str) != 0:
        return 1
    return cmd_apply()


def cmd_save_sensor(data_str: str | None = None) -> int:
    if not data_str:
        data_str = sys.stdin.read()
    try:
        data = json.loads(data_str)
        if not isinstance(data, dict):
            raise ValueError("Sensor config must be a JSON object")
        cur = load_sensor_config()
        val = float(data.get("silence_timeout", cur["silence_timeout"]))
        reports = int(data.get("present_confirm_reports", cur["present_confirm_reports"]))
        win = float(data.get("present_confirm_window", cur["present_confirm_window"]))
        atomic_json_write(
            SENSOR_CONFIG_PATH,
            {
                "silence_timeout": max(2.0, min(10.0, val)),
                "present_confirm_reports": max(1, min(5, reports)),
                "present_confirm_window": max(1.0, min(8.0, win)),
            },
        )
        return 0
    except Exception as exc:
        sys.stderr.write(f"Error saving sensor config: {exc}\n")
        return 1


def cmd_sensor_service(action: str) -> int:
    allowed = ("start", "stop", "restart", "status", "enable", "disable", "enable-now", "disable-now")
    if action not in allowed:
        sys.stderr.write(f"Invalid service action: {action}\n")
        return 1
    if action == "enable-now":
        cmd = ["/usr/bin/systemctl", "enable", "--now", SYSTEM_SENSOR_UNIT]
    elif action == "disable-now":
        cmd = ["/usr/bin/systemctl", "disable", "--now", SYSTEM_SENSOR_UNIT]
    else:
        cmd = ["/usr/bin/systemctl", action, SYSTEM_SENSOR_UNIT]
    res = subprocess.run(cmd)
    return res.returncode


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        sys.stderr.write("Usage: ff-power-helper <save-and-apply|save-config|save-sensor|apply|sensor-service> [args]\n")
        return 2

    action = args[0]
    if action == "apply":
        return cmd_apply()
    elif action == "save-config":
        data_arg = args[1] if len(args) > 1 else None
        return cmd_save_config(data_arg)
    elif action == "save-and-apply":
        data_arg = args[1] if len(args) > 1 else None
        return cmd_save_and_apply(data_arg)
    elif action == "save-sensor":
        data_arg = args[1] if len(args) > 1 else None
        return cmd_save_sensor(data_arg)
    elif action == "sensor-service":
        subaction = args[1] if len(args) > 1 else "restart"
        return cmd_sensor_service(subaction)
    else:
        sys.stderr.write(f"Unknown action: {action}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
