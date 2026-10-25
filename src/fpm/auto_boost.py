from __future__ import annotations

import glob
import os
import signal
import sys
import time

from .core import (
    apply,
    load_config,
    on_battery_from_sysfs,
    set_smart_media_mode,
    set_cpu_freq_floor,
    set_gpu,
    read_text,
    RUN_DIR,
)

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
    smart_media_active = False
    last_seen_time = 0.0
    last_profile = ''
    last_tune_time = 0.0

    sys.stdout.write("FF Power Manager: Auto Dynamic Boost engine started.\n")
    sys.stdout.flush()

    while _running:
        on_bat = on_battery_from_sysfs()
        media_file = RUN_DIR / 'media.active'
        is_media_playing = media_file.exists() and on_bat

        # Smart Media Mode: Lock low-power 2.2 GHz ceiling during battery video playback
        if is_media_playing and not smart_media_active and not boosted:
            smart_media_active = True
            try:
                set_smart_media_mode(True)
                sys.stdout.write("Auto Dynamic Boost: Smart Media Video Mode engaged (capping 2.2 GHz on battery).\n")
                sys.stdout.flush()
            except Exception as exc:
                sys.stderr.write(f"Failed to engage Smart Media Mode: {exc}\n")
        elif not is_media_playing and smart_media_active:
            smart_media_active = False
            try:
                set_smart_media_mode(False)
                sys.stdout.write("Auto Dynamic Boost: Media playback stopped. Restoring standard topology.\n")
                sys.stdout.flush()
            except Exception as exc:
                sys.stderr.write(f"Failed to exit Smart Media Mode: {exc}\n")

        heavy = find_heavy_process() if not is_media_playing else None
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

            # Periodically ensure MacBook-style hybrid topology & RAPL permissions are intact
            if not boosted and (now - last_tune_time >= 30.0):
                last_tune_time = now
                try:
                    active_mode = read_text(RUN_DIR / 'power.mode') or ('battery' if on_battery_from_sysfs() else 'ac')
                    set_cpu_freq_floor(active_mode)
                    set_gpu('auto', active_mode)
                except Exception as exc:
                    sys.stderr.write(f"Background hybrid topology tuning failed: {exc}\n")

        sleep_time = 6.0 if on_battery_from_sysfs() else poll_interval
        time.sleep(sleep_time)

    sys.stdout.write("FF Power Manager: Auto Dynamic Boost engine stopped.\n")


def main():
    run_watcher()
    return 0


if __name__ == '__main__':
    sys.exit(main())
