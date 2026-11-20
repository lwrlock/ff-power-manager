from __future__ import annotations

import glob
import json
import os
import select
import signal
import sys
import threading
import time
from collections import deque

from .core import (
    apply,
    battery_percent,
    detect_cpu_topology,
    load_config,
    on_battery_from_sysfs,
    optimize_desktop_responsiveness,
    power_now_watts,
    set_smart_media_mode,
    set_cpu_freq_floor,
    set_gpu,
    set_rapl_limits,
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
    'python3',
    'node',
    'cmake',
    'ld',
    'lld',
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
_UNFOCUSED_TIMERS: dict[int, float] = {}
_FROZEN_PIDS: set[int] = set()

# Freeze threshold: 5 minutes (300 seconds) unfocused on battery with no media playback
FREEZE_UNFOCUSED_SECONDS = 300.0
FREEZE_SAFE_CANDIDATES = {
    'chrome', 'chromium', 'brave', 'isolated web co', 'web content', 'discord', 'slack', 'teams',
}


def _sig_handler(signum, frame):
    global _running
    _running = False
    for p in list(_FROZEN_PIDS):
        try:
            os.kill(p, signal.SIGCONT)
        except OSError:
            pass


class InputBurstListener(threading.Thread):
    """Listens for hardware touchpad/keyboard events and applies instantaneous micro-bursts."""
    def __init__(self, p_cores: list[int] | None = None):
        super().__init__(daemon=True, name="InputBurstListener")
        self.p_cores = p_cores or [0, 1, 2, 3, 4, 5]
        self._running = True
        self._last_burst = 0.0
        self._burst_active = False
        self._burst_until = 0.0

    def stop(self):
        self._running = False

    def run(self):
        dev_paths = []
        for p in sorted(glob.glob('/dev/input/event*')):
            try:
                fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
                dev_paths.append((p, fd))
            except (PermissionError, FileNotFoundError, OSError):
                continue

        if not dev_paths:
            return

        try:
            epoll = select.epoll()
        except Exception:
            for _, fd in dev_paths:
                try:
                    os.close(fd)
                except OSError:
                    pass
            return

        fd_map = {}
        for p, fd in dev_paths:
            try:
                epoll.register(fd, select.EPOLLIN)
                fd_map[fd] = p
            except OSError:
                try:
                    os.close(fd)
                except OSError:
                    pass

        try:
            while self._running:
                now = time.monotonic()
                if self._burst_active and now >= self._burst_until:
                    self._burst_active = False
                    self._restore_epp()

                try:
                    events = epoll.poll(0.04)
                except (InterruptedError, OSError):
                    continue

                if not events:
                    continue

                for fd, _ in events:
                    try:
                        os.read(fd, 256)
                    except OSError:
                        pass

                if on_battery_from_sysfs():
                    now = time.monotonic()
                    if now - self._last_burst >= 0.12:
                        self._last_burst = now
                        self._burst_active = True
                        self._burst_until = now + 0.080
                        self._trigger_burst()
        finally:
            if self._burst_active:
                self._restore_epp()
            for fd in fd_map:
                try:
                    epoll.unregister(fd)
                except Exception:
                    pass
                try:
                    os.close(fd)
                except OSError:
                    pass
            try:
                epoll.close()
            except Exception:
                pass

    def _trigger_burst(self):
        for c in self.p_cores:
            p = f'/sys/devices/system/cpu/cpu{c}/cpufreq/energy_performance_preference'
            try:
                with open(p, 'w') as f:
                    f.write('balance_performance')
            except OSError:
                pass

    def _restore_epp(self):
        for c in self.p_cores:
            p = f'/sys/devices/system/cpu/cpu{c}/cpufreq/energy_performance_preference'
            try:
                with open(p, 'w') as f:
                    f.write('balance_power')
            except OSError:
                pass


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



_CACHED_TOPOLOGY = None


def _get_cpu_topology_sets():
    global _CACHED_TOPOLOGY
    if _CACHED_TOPOLOGY is None:
        try:
            p, e, lpe = detect_cpu_topology()
            all_cores = set(p + e + lpe) if (p or e or lpe) else None
            e_island = set(e + lpe) if (e or lpe) else all_cores
            lpe_island = set(lpe) if lpe else (e_island or all_cores)
            _CACHED_TOPOLOGY = (all_cores, e_island, lpe_island)
        except Exception:
            _CACHED_TOPOLOGY = (None, None, None)
    return _CACHED_TOPOLOGY


def _apply_focus_battery_throttle(on_bat: bool, is_media_playing: bool) -> None:
    """Lower scheduler weight and migrate unfocused/indexer processes to E/LPE cores on battery."""
    throttle_targets = {
        'chrome', 'chromium', 'brave', 'firefox', 'discord', 'slack', 'teams', 'spotify',
    }
    background_heavy_services = {
        'tracker-miner-f', 'tracker-miner-fs-3', 'tracker-extract', 'tracker-extract-3',
        'updatedb', 'updatedb.mlocat', 'plocate', 'packagekitd',
    }
    all_cores, e_island, lpe_island = _get_cpu_topology_sets()
    focused_pid = 0
    focused_name = ''
    try:
        fpath = RUN_DIR / 'focused.json'
        if fpath.exists():
            fdata = json.loads(fpath.read_text(encoding='utf-8'))
            focused_pid = int(fdata.get('pid', 0) or 0)
            focused_name = str(fdata.get('wm_class', '') or '').lower()
    except Exception:
        pass

    for comm_path in glob.glob('/proc/[0-9]*/comm'):
        try:
            pid = int(comm_path.split('/')[2])
            with open(comm_path, 'r', encoding='utf-8', errors='ignore') as f:
                cname = f.read().strip().lower()

            if cname in background_heavy_services:
                want_nice = 19 if on_bat else 0
                if os.getpriority(os.PRIO_PROCESS, pid) != want_nice:
                    os.setpriority(os.PRIO_PROCESS, pid, want_nice)
                if hasattr(os, 'sched_setaffinity') and lpe_island and all_cores:
                    target_aff = lpe_island if on_bat else all_cores
                    try:
                        os.sched_setaffinity(pid, target_aff)
                    except (PermissionError, ProcessLookupError, OSError):
                        pass
                continue

            if cname not in throttle_targets:
                continue

            is_focused = (pid == focused_pid) or (focused_name and cname in focused_name)
            want_nice = 10 if (on_bat and not is_media_playing and not is_focused and focused_pid > 0) else 0
            if os.getpriority(os.PRIO_PROCESS, pid) != want_nice:
                os.setpriority(os.PRIO_PROCESS, pid, want_nice)

            if hasattr(os, 'sched_setaffinity') and e_island and all_cores:
                target_aff = e_island if (want_nice > 0 and e_island) else all_cores
                try:
                    os.sched_setaffinity(pid, target_aff)
                except (PermissionError, ProcessLookupError, OSError):
                    pass

            # Stale background tab/app freezing on battery (SIGSTOP / SIGCONT)
            now_mono = time.monotonic()
            if on_bat and not is_media_playing and not is_focused and focused_pid > 0:
                if pid not in _UNFOCUSED_TIMERS:
                    _UNFOCUSED_TIMERS[pid] = now_mono
                elif (now_mono - _UNFOCUSED_TIMERS[pid] >= FREEZE_UNFOCUSED_SECONDS) and (cname in FREEZE_SAFE_CANDIDATES):
                    if pid not in _FROZEN_PIDS:
                        try:
                            os.kill(pid, signal.SIGSTOP)
                            _FROZEN_PIDS.add(pid)
                        except (PermissionError, ProcessLookupError, OSError):
                            pass
            else:
                _UNFOCUSED_TIMERS.pop(pid, None)
                if pid in _FROZEN_PIDS:
                    try:
                        os.kill(pid, signal.SIGCONT)
                    except (PermissionError, ProcessLookupError, OSError):
                        pass
                    _FROZEN_PIDS.discard(pid)
        except (FileNotFoundError, ProcessLookupError, PermissionError, ValueError, OSError):
            continue

    if not on_bat and _FROZEN_PIDS:
        for p in list(_FROZEN_PIDS):
            try:
                os.kill(p, signal.SIGCONT)
            except (PermissionError, ProcessLookupError, OSError):
                pass
        _FROZEN_PIDS.clear()
        _UNFOCUSED_TIMERS.clear()


def _record_telemetry_sample(history: deque, on_bat: bool) -> None:
    """Record rolling wattage and CPU package temperature history for GUI/TUI graphs."""
    try:
        watts = power_now_watts()
        temp_c = get_max_pkg_temp_c()
        cap = battery_percent()
        mode = read_text(RUN_DIR / 'power.mode') or ('battery' if on_bat else 'ac')
        history.append({
            'ts': int(time.time()),
            'watts': round(float(watts), 2) if watts is not None else 0.0,
            'temp_c': int(temp_c) if temp_c > 0 else 0,
            'cap': int(cap) if cap is not None else 0,
            'mode': mode,
            'on_bat': bool(on_bat),
        })
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        tmp_p = RUN_DIR / 'telemetry_history.json.tmp'
        final_p = RUN_DIR / 'telemetry_history.json'
        tmp_p.write_text(json.dumps(list(history)), encoding='utf-8')
        os.chmod(tmp_p, 0o644)
        tmp_p.replace(final_p)
    except Exception:
        pass


def get_max_pkg_temp_c() -> int:
    max_c = 0
    for p in glob.glob('/sys/class/hwmon/hwmon*/temp*_input'):
        try:
            name_p = os.path.join(os.path.dirname(p), 'name')
            if os.path.exists(name_p):
                dev = open(name_p).read().strip()
                if dev not in ('coretemp', 'k10temp', 'zenpower'):
                    continue
            val = int(open(p).read().strip()) // 1000
            if 20 <= val <= 115 and val > max_c:
                max_c = val
        except Exception:
            pass
    return max_c

def run_watcher(poll_interval: float = 2.0, grace_period: float = 5.0) -> None:
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    boosted = False
    smart_media_active = False
    dynamic_cores_unparked = False
    pre_boost_battery_mode = 'battery'
    last_seen_time = 0.0
    last_high_load_time = 0.0
    last_tune_time = 0.0
    last_hist_time = 0.0
    last_focus_time = 0.0
    prev_idle = 0.0
    prev_total = 0.0
    telemetry_history: deque = deque(maxlen=180)

    sys.stdout.write("FF Power Manager: Auto Dynamic Boost engine started.\n")
    sys.stdout.flush()

    input_listener = None
    try:
        p_cores, _, _ = detect_cpu_topology()
        input_listener = InputBurstListener(p_cores)
        input_listener.start()
    except Exception:
        pass

    while _running:
        on_bat = on_battery_from_sysfs()
        media_file = RUN_DIR / 'media.active'
        is_media_playing = media_file.exists() and on_bat

        # Calculate live CPU usage from /proc/stat
        cpu_usage, prev_idle, prev_total = get_cpu_load(prev_idle, prev_total)
        now = time.monotonic()

        # Smart Media Mode: Balance GPU & CPU ceilings during battery video playback
        if is_media_playing and not smart_media_active and not boosted:
            smart_media_active = True
            try:
                set_smart_media_mode(True)
                sys.stdout.write("Auto Dynamic Boost: Smart Media Video Mode engaged (balanced clocks + GPU RPN floor on battery).\n")
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
            # Dynamic Responsiveness on Battery: keep all cores online for C6/C10 power-gating
            # and burst into battery_boost on sustained load or detected workloads.
            is_high_load = (heavy is not None) or (cpu_usage >= 30.0)

            if is_high_load:
                last_high_load_time = now
                if not dynamic_cores_unparked:
                    dynamic_cores_unparked = True
                    cur_mode = (read_text(RUN_DIR / 'power.mode') or 'battery').strip()
                    if cur_mode in ('battery', 'max_battery', 'maximum_battery', 'cool_quiet'):
                        pre_boost_battery_mode = cur_mode
                    else:
                        pre_boost_battery_mode = 'battery'
                    reason = f"heavy process '{heavy}'" if heavy else f"CPU load {cpu_usage:.1f}%"
                    sys.stdout.write(f"Auto Dynamic Boost: Demand spike detected ({reason}). Boosting CPU, GPU & RAPL on battery.\n")
                    sys.stdout.flush()
                    try:
                        set_rapl_limits('battery_boost')
                        set_cpu_freq_floor('extreme_performance', high_load=True)
                        set_gpu('auto', 'extreme_performance')
                        optimize_desktop_responsiveness()
                    except Exception as exc:
                        sys.stderr.write(f"Failed to engage high load boost: {exc}\n")
                elif get_max_pkg_temp_c() >= 90 and not getattr(run_watcher, '_bat_thermal_capped', False):
                    run_watcher._bat_thermal_capped = True
                    sys.stdout.write("Auto Dynamic Boost: Battery Thermal Guardrail (>=90C). Softening PL1 to battery limits.\n")
                    sys.stdout.flush()
                    try:
                        set_rapl_limits('battery')
                    except Exception:
                        pass
            else:
                if dynamic_cores_unparked and (now - last_high_load_time >= 4.0):
                    dynamic_cores_unparked = False
                    run_watcher._bat_thermal_capped = False
                    restore_mode = pre_boost_battery_mode
                    sys.stdout.write(f"Auto Dynamic Boost: Load normalized ({cpu_usage:.1f}%). Restoring '{restore_mode}' caps.\n")
                    sys.stdout.flush()
                    try:
                        set_cpu_freq_floor(restore_mode, high_load=False)
                        set_gpu('auto', restore_mode)
                        set_rapl_limits(restore_mode)
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
            # On AC: All detected cores remain online. Engage extreme_performance for heavy games/compiles.
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

            if boosted and get_max_pkg_temp_c() >= 90:
                if not getattr(run_watcher, '_thermal_capped', False):
                    run_watcher._thermal_capped = True
                    sys.stdout.write("Auto Dynamic Boost: Thermal Guardrail (>=90C). Softening PL1 to 'ac' sustained limits.\n")
                    sys.stdout.flush()
                    try:
                        set_rapl_limits('ac')
                    except Exception:
                        pass
            elif getattr(run_watcher, '_thermal_capped', False) and get_max_pkg_temp_c() <= 78:
                run_watcher._thermal_capped = False
                if boosted:
                    try:
                        set_rapl_limits('extreme_performance')
                    except Exception:
                        pass

            sleep_time = poll_interval

        if now - last_hist_time >= 5.0:
            last_hist_time = now
            _record_telemetry_sample(telemetry_history, on_bat)

        if now - last_focus_time >= 4.0:
            last_focus_time = now
            _apply_focus_battery_throttle(on_bat, is_media_playing)

        time.sleep(sleep_time)

    if input_listener:
        try:
            input_listener.stop()
        except Exception:
            pass

    sys.stdout.write("FF Power Manager: Auto Dynamic Boost engine stopped.\n")


def main():
    run_watcher()
    return 0


if __name__ == '__main__':
    sys.exit(main())
