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
    optimize_desktop_responsiveness,
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

# Processes that stay resident in RAM when idle and should only trigger boost under active CPU/GPU load
IDLE_AWARE_HEAVY_PROCESSES = {
    'llama-server',
    'llama-cli',
    'llama-bench',
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


def find_heavy_process(cpu_usage: float = 0.0) -> str | None:
    """Lightweight procfs scanner (< 15ms) to identify running heavy workloads and games."""
    for comm_path in glob.glob('/proc/[0-9]*/comm'):
        try:
            with open(comm_path, 'r', encoding='utf-8', errors='ignore') as f:
                name = f.read().strip().lower()
                if not name:
                    continue
                if name in HEAVY_PROCESSES or name in KNOWN_GAMES:
                    return name
                if name in IDLE_AWARE_HEAVY_PROCESSES and cpu_usage >= 10.0:
                    return name
                # Windows games running via Wine/Proton (.exe or truncated to 15 chars e.g. .e)
                if name.endswith('.exe') or name.endswith('.e') or '.exe' in name:
                    if name not in ('wsl.exe',):
                        return name
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return None


def get_cpu_load(prev_idle: float, prev_total: float) -> tuple[float, float, float]:
    """Lightweight procfs load calculation (< 0.2ms) from /proc/stat."""
    try:
        with open('/proc/stat', 'r', encoding='utf-8') as f:
            line = f.readline()
            if not line.startswith('cpu '):
                return 0.0, prev_idle, prev_total
            fields = [float(x) for x in line.split()[1:5]]
            idle = fields[3]
            total = sum(fields)
            if prev_total == 0:
                return 0.0, idle, total
            idle_delta = idle - prev_idle
            total_delta = total - prev_total
            if total_delta <= 0:
                return 0.0, idle, total
            usage = 100.0 * (1.0 - (idle_delta / total_delta))
            return max(0.0, min(100.0, usage)), idle, total
    except Exception:
        return 0.0, prev_idle, prev_total


def run_watcher(poll_interval: float = 2.0, grace_period: float = 5.0) -> None:
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    boosted = False
    smart_media_active = False
    dynamic_cores_unparked = False
    last_seen_time = 0.0
    last_high_load_time = 0.0
    last_tune_time = 0.0
    prev_idle = 0.0
    prev_total = 0.0

    sys.stdout.write("FF Power Manager: Auto Dynamic Boost engine started.\n")
    sys.stdout.flush()

    while _running:
        on_bat = on_battery_from_sysfs()
        media_file = RUN_DIR / 'media.active'
        is_media_playing = media_file.exists() and on_bat

        # Calculate live CPU usage from /proc/stat
        cpu_usage, prev_idle, prev_total = get_cpu_load(prev_idle, prev_total)
        now = time.monotonic()

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

        heavy = find_heavy_process(cpu_usage) if not is_media_playing else None

        if on_bat:
            # Dynamic Responsiveness on Battery: All 16 cores remain online.
            # Idle cores enter C6/C10 autonomously (0W). No stop_machine() hotplug freezes!
            is_high_load = (heavy is not None) or (cpu_usage >= 45.0)

            if is_high_load:
                last_high_load_time = now
                if not dynamic_cores_unparked:
                    dynamic_cores_unparked = True
                    reason = f"heavy process '{heavy}'" if heavy else f"CPU load {cpu_usage:.1f}%"
                    sys.stdout.write(f"Auto Dynamic Boost: Demand spike detected ({reason}). Boosting CPU & GPU frequencies.\n")
                    sys.stdout.flush()
                    try:
                        set_cpu_freq_floor('extreme_performance', high_load=True)
                        set_gpu('auto', 'extreme_performance')
                        optimize_desktop_responsiveness()
                    except Exception as exc:
                        sys.stderr.write(f"Failed to engage high load boost: {exc}\n")
            else:
                if dynamic_cores_unparked and (now - last_high_load_time >= 5.0):
                    dynamic_cores_unparked = False
                    sys.stdout.write(f"Auto Dynamic Boost: Load normalized ({cpu_usage:.1f}%). Restoring ProMotion battery caps.\n")
                    sys.stdout.flush()
                    try:
                        set_cpu_freq_floor('battery', high_load=False)
                        set_gpu('auto', 'battery')
                    except Exception as exc:
                        sys.stderr.write(f"Failed to return to battery profile: {exc}\n")

            if not is_high_load and not dynamic_cores_unparked and (now - last_tune_time >= 120.0):
                last_tune_time = now
                try:
                    active_mode = read_text(RUN_DIR / 'power.mode') or 'battery'
                    set_cpu_freq_floor(active_mode, high_load=False)
                    set_gpu('auto', active_mode)
                    optimize_desktop_responsiveness()
                except Exception as exc:
                    sys.stderr.write(f"Background hybrid topology tuning failed: {exc}\n")

            sleep_time = 2.5 if (not dynamic_cores_unparked and not is_media_playing) else 1.2
        else:
            # On AC: All 16 cores always online. Engage extreme_performance for heavy games/compiles.
            dynamic_cores_unparked = True
            if heavy:
                last_seen_time = now
                if not boosted:
                    boosted = True
                    cfg = load_config()
                    sys.stdout.write(
                        f"Auto Dynamic Boost: Activated by '{heavy}'. Engaging 'extreme_performance' mode.\n"
                    )
                    sys.stdout.flush()
                    try:
                        apply('extreme_performance', cfg)
                    except Exception as exc:
                        sys.stderr.write(f"Failed to engage boost: {exc}\n")
            else:
                if boosted and (now - last_seen_time >= grace_period):
                    boosted = False
                    cfg = load_config()
                    sys.stdout.write(
                        "Auto Dynamic Boost: Heavy workload finished. Grace period elapsed; restoring 'ac' profile.\n"
                    )
                    sys.stdout.flush()
                    try:
                        apply('ac', cfg)
                    except Exception as exc:
                        sys.stderr.write(f"Failed to restore power profile: {exc}\n")

                if not boosted and (now - last_tune_time >= 120.0):
                    last_tune_time = now
                    try:
                        active_mode = read_text(RUN_DIR / 'power.mode') or 'ac'
                        set_cpu_freq_floor(active_mode, high_load=True)
                        set_gpu('auto', active_mode)
                        optimize_desktop_responsiveness()
                    except Exception as exc:
                        sys.stderr.write(f"Background hybrid topology tuning failed: {exc}\n")

            sleep_time = poll_interval

        time.sleep(sleep_time)

    sys.stdout.write("FF Power Manager: Auto Dynamic Boost engine stopped.\n")


def main():
    run_watcher()
    return 0


if __name__ == '__main__':
    sys.exit(main())
