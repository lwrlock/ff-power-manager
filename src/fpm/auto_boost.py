from __future__ import annotations

import glob
import os
import signal
import sys
import time
from pathlib import Path

from .core import apply, load_config, on_battery_from_sysfs

HEAVY_PROCESSES = {
    # Gaming & Launchers
    'steam',
    'steamwebhelper',
    'gamescope',
    'lutris',
    'heroic',
    'gamemoded',
    'wine',
    'wine64',
    'wineserver',
    'proton',
    # Content Creation & Renderers
    'blender',
    'obs',
    'ffmpeg',
    'kdenlive',
    'davinci-resolve',
    # Compilers & Build Systems
    'gcc',
    'g++',
    'clang',
    'clang++',
    'rustc',
    'cargo',
    'make',
    'ninja',
}

_running = True


def _sig_handler(signum, frame):
    global _running
    _running = False


def find_heavy_process() -> str | None:
    """Lightweight procfs scanner (< 2ms) to identify running heavy workloads."""
    for comm_path in glob.glob('/proc/[0-9]*/comm'):
        try:
            with open(comm_path, 'r', encoding='utf-8', errors='ignore') as f:
                name = f.read().strip().lower()
                if name in HEAVY_PROCESSES:
                    return name
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return None


def run_watcher(poll_interval: float = 2.5, grace_period: float = 5.0) -> None:
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    boosted = False
    last_seen_time = 0.0

    sys.stdout.write("FF Power Manager: Auto Dynamic Boost engine started.\n")
    sys.stdout.flush()

    while _running:
        heavy = find_heavy_process()
        now = time.monotonic()

        if heavy:
            last_seen_time = now
            if not boosted:
                boosted = True
                cfg = load_config()
                sys.stdout.write(
                    f"Auto Dynamic Boost: Activated by '{heavy}'. Engaging maximum hardware performance.\n"
                )
                sys.stdout.flush()
                try:
                    apply('ac' if not on_battery_from_sysfs() else 'battery', cfg)
                    helper = Path('/usr/local/lib/ff-power-manager/ff-power-helper')
                    if helper.exists():
                        import subprocess
                        subprocess.run(['pkexec', str(helper), 'set-epp', 'performance'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except Exception as exc:
                    sys.stderr.write(f"Failed to engage boost: {exc}\n")
        else:
            if boosted and (now - last_seen_time >= grace_period):
                boosted = False
                cfg = load_config()
                mode = 'battery' if on_battery_from_sysfs() else 'ac'
                sys.stdout.write(
                    f"Auto Dynamic Boost: Heavy workload finished. Grace period elapsed; restoring '{mode}' profile.\n"
                )
                sys.stdout.flush()
                try:
                    apply(mode, cfg)
                except Exception as exc:
                    sys.stderr.write(f"Failed to restore power profile: {exc}\n")

        time.sleep(poll_interval)

    sys.stdout.write("FF Power Manager: Auto Dynamic Boost engine stopped.\n")


def main():
    run_watcher()
    return 0


if __name__ == '__main__':
    sys.exit(main())
