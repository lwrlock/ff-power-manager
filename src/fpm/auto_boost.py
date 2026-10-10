from __future__ import annotations

import glob
import os
import signal
import sys
import time

from .core import apply, load_config, on_battery_from_sysfs

HEAVY_PROCESSES = {
    # Gaming & Wine / Proton
    'gamescope',
    'lutris',
    'heroic',
    'wine',
    'wine64',
    'wineserver',
    'wine-preloader',
    'wine64-preloader',
    'proton',
    # Emulators
    'rpcs3',
    'yuzu',
    'ryujinx',
    'retroarch',
    'dolphin-emu',
    'cemu',
    'pcsx2',
    # Content Creation & Renderers
    'blender',
    'obs',
    'ffmpeg',
    'kdenlive',
    'davinci-resolve',
    'handbrake',
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

KNOWN_GAMES = {
    'cs2',
    'dota2',
    'hl2_linux',
    'portal2_linux',
    'valheim.x86_64',
    'factorio',
    'deadcells',
    'celeste',
    'hollow_knight.x',
    'rustclient',
    'terraria.bin.x8',
    'minecraft',
    'javaw',
    'sober',
    'warframe.x64.ex',
}

_running = True


def _sig_handler(signum, frame):
    global _running
    _running = False


def find_heavy_process() -> str | None:
    """Lightweight procfs scanner (< 15ms) to identify running heavy workloads and games."""
    for comm_path in glob.glob('/proc/[0-9]*/comm'):
        try:
            with open(comm_path, 'r', encoding='utf-8', errors='ignore') as f:
                name = f.read().strip().lower()
                if not name:
                    continue
                if name in HEAVY_PROCESSES or name in KNOWN_GAMES:
                    return name
                # Windows games running via Wine/Proton (.exe or truncated to 15 chars e.g. .e)
                if name.endswith('.exe') or name.endswith('.e') or '.exe' in name:
                    if name not in ('wsl.exe',):
                        return name
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return None


def run_watcher(poll_interval: float = 2.5, grace_period: float = 5.0) -> None:
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    boosted = False
    last_seen_time = 0.0
    last_profile = ''
    last_tune_time = 0.0

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
                on_bat = on_battery_from_sysfs()
                # On battery, strictly preserve power saving; only engage extreme_performance on AC
                target_mode = 'extreme_performance' if not on_bat else 'battery'
                sys.stdout.write(
                    f"Auto Dynamic Boost: Activated by '{heavy}'. Engaging '{target_mode}' mode.\n"
                )
                sys.stdout.flush()
                try:
                    apply(target_mode, cfg)
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

            # On AC, continuously ensure zero-stutter hardware floors (P-cores 1.2GHz, EPB 3).
            # On battery, allow the CPU and GPU to enter deep sleep without forced floors.
            if not boosted:
                on_bat = on_battery_from_sysfs()
                if not on_bat:
                    needs_tune = False
                    try:
                        with open('/sys/devices/system/cpu/cpu0/power/energy_perf_bias', 'r') as f:
                            if int(f.read().strip()) > 3:
                                needs_tune = True
                    except Exception:
                        pass
                    if not needs_tune:
                        try:
                            with open('/sys/devices/system/cpu/cpu0/cpufreq/scaling_min_freq', 'r') as f:
                                if int(f.read().strip()) < 1200000:
                                    needs_tune = True
                        except Exception:
                            pass
                    if not needs_tune and (now - last_tune_time >= 30.0):
                        needs_tune = True

                    if needs_tune:
                        last_tune_time = now
                        try:
                            from .core import set_cpu_freq_floor, set_gpu
                            set_cpu_freq_floor('ac')
                            set_gpu('system')
                        except Exception as exc:
                            sys.stderr.write(f"Background AC floor tuning failed: {exc}\n")

        time.sleep(poll_interval)

    sys.stdout.write("FF Power Manager: Auto Dynamic Boost engine stopped.\n")


def main():
    run_watcher()
    return 0


if __name__ == '__main__':
    sys.exit(main())
