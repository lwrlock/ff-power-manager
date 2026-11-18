# FF Power Manager v2.2

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Ubuntu | Debian | Fedora](https://img.shields.io/badge/Platform-Ubuntu%20%7C%20Debian%20%7C%20Fedora-teal.svg)](https://ubuntu.com)
[![Desktop: GNOME | Hyprland | Plasma](https://img.shields.io/badge/Desktop-GNOME%20%7C%20Hyprland%20%7C%20Plasma-orange.svg)](https://www.gnome.org)
[![Engine: C & x86_64 ASM](https://img.shields.io/badge/Engine-C%20%26%20x86__64%20ASM-success.svg)](#architecture)
[![AI-Assisted: Antigravity](https://img.shields.io/badge/AI--Assisted-Google%20DeepMind%20Antigravity-purple.svg)](#development--ai-collaboration)
[![Release: v2.2.0](https://img.shields.io/badge/Release-v2.2.0-blueviolet.svg)](https://github.com/lwrlock/ff-power-manager/releases/tag/v2.2.0)

[ English | [Türkçe](README.tr.md) ]

**Low-overhead Linux laptop power, Multi-DE Adaptive Refresh (`60↔Max Hz`), wakeup blame profiler (`ffctl blame`), `s2idle` sleep drain analytics (`ffctl sleep-report`), ToF presence automation, and a cosmic GTK4 desktop UI.**

Built with a native **C & x86_64 Assembly** telemetry/CLI core (`ffctl`, `ff-tui`, `ff-presence-sensor`) paired with **Python / GTK4 / Wayland** integration — featuring **Universal Hardware Auto-Discovery** across Intel & AMD laptops (`Ubuntu`, `Debian`, `Fedora`).

---

## Why FF Power Manager vs TLP / auto-cpufreq?

| Capability | TLP / auto-cpufreq | **FF Power Manager v2.2** |
| :--- | :---: | :---: |
| Hybrid P/E/LP-E & Symmetric CPU Topology Discovery | Partial | **Yes (`detect_cpu_topology()` + `cpuinfo_max_freq` clamping)** |
| **Energy & Wakeup Blame Profiler (`ffctl blame`)** | No (`powertop` separate) | **Yes (250ms C procfs sampler + active PCI/USB blocker scan)** |
| **Hardware Residency Audit (`ffctl doctor`)** | No | **Yes (`s2idle`, ACPI wakeups, PCI PM ratio, conflict check)** |
| **`s2idle` Suspend Drain Report (`ffctl sleep-report`)** | No | **Yes (Measures exact `Wh`, `W` & `%/hr` lost per sleep cycle)** |
| **Machine-Readable Telemetry (`--json`)** | Limited | **Yes (`status`, `health`, `doctor`, `blame`, `sleep-report`)** |
| **Multi-DE Battery Adaptive Refresh (`60↔Max Hz`)** | No | **Yes (`Mutter.IdleMonitor`, `hyprctl`, `kscreen-doctor`)** |
| **Focus-Aware Battery Throttling + Cinema/Focus Modes** | No | **Yes (Lowers unfocused browser weight on battery + MPRIS/Color lock)** |
| **ToF Human Presence Radar (Intel ISH HID)** | No | **Yes (C/x86_64 ASM `hidraw` parser + MPRIS/PCM inhibit)** |
| **Thermal Guardrail (`>=90°C`) & One-Shot 100% Charge** | No | **Yes (OEM TDP clamped RAPL + auto re-arming 80% limit)** |
| **Privilege Model** | Root daemon | **Non-setuid `ffctl` + scoped PolicyKit `ff-power-helper`** |

---

## Architecture

```
  [ST VL53L1 ToF HID] ──► ff-presence-sensor (C + x86_64 ASM) ──► /run/ff-power-manager/*
                                                                          │
  [GNOME Mutter / Hyprland / Plasma] ◄── ff-presence-session ◄────────────┤
  [/proc/[pid] + /proc/stat + hwmon] ───► ff-power-autoboost ──► core.py + telemetry_history.json
  [systemd-sleep pre/post]           ───► ff-sleep-guard     ──► /var/lib/ff-power-manager/last_sleep.json
  [Cosmic GTK4 UI / Waybar / ffctl]  ───► ff-power-helper (PolicyKit, zero setuid root binaries)
```

---

## Key Features (v2.2.0)

- **Energy & Wakeup Blame Profiler (`ffctl blame [--json]`):** Samples `/proc/[pid]/stat` and `/proc/[pid]/status` in 250ms native C to rank top processes by CPU + context-switch wakeups/sec while listing active non-suspended PCI/USB hardware — accessible both in CLI and the dedicated **Blame Profiler** tab in the GTK4 app.
- **`s2idle` Suspend Drain Telemetry (`ffctl sleep-report [--json]`):** `ff-sleep-guard` disables spurious USB/Thunderbolt wakeups before suspend, captures `energy_now` (`Wh`) and `%`, and computes exact standby consumption (`W` & `%/hr`) upon resume.
- **Hardware Residency Audit (`ffctl doctor [--json]`):** Verifies `[s2idle]`/`[deep]` hooks, armed ACPI wakeups (`/proc/acpi/wakeup`), PCI Runtime PM ratios, P-state/EPP drivers, and `tlp`/`auto-cpufreq` conflicts in `< 2 ms`.
- **Cosmic Space GTK4 Desktop App (`ff-power-manager`):** Translucent frosted-glass UI over a Cairo cosmic starfield (nebulae, rotating ringed planet, orbiting moon, shooting stars — auto-throttling to ~9 FPS on battery to preserve energy), featuring a **4-card Hero Telemetry Deck**, live **Wattage/Temp Sparkline Graph**, **Blame Profiler**, and custom SVG app icon.
- **Multi-DE Battery-Only Adaptive Refresh & Focus Throttling:** Supports GNOME (`Mutter.IdleMonitor` + `DisplayConfig`), Hyprland (`hyprctl`), and KDE Plasma (`kscreen-doctor`), plus battery-only scheduler priority throttling for unfocused background browsers/Electron apps.
- **Waybar Module, `.deb` & Fedora `.rpm` Packaging:** Ready-to-use JSON bar snippet in [contrib/waybar/](contrib/waybar/README.md), Debian package (`build-deb.sh`), and RPM spec ([packaging/ff-power-manager.spec](packaging/ff-power-manager.spec)).

---

## Hardware Compatibility Matrix

| Hardware / Feature | Discovery / Sysfs Path | Status |
| :--- | :--- | :---: |
| **Intel Core Ultra (Arrow/Meteor/Lunar Lake)** | `intel_pstate`, `intel-rapl`, hybrid `P+E+LP-E` `cpuinfo_max_freq` | **Verified Bare-Metal** |
| **AMD Ryzen Mobile** | `amd-pstate-epp`, `k10temp` / `zenpower`, `pp_dpm_sclk` | **Universal Discovery** |
| **Intel Xe / i915 & AMD Radeon iGPU** | `tile*/gt*/freq0`, `gt_min_freq_mhz`, `pp_dpm_sclk`, Mesa/iHD VA-API | **Supported** |
| **Charge Conservation (80% + One-Shot 100%)** | Lenovo `VPC2004/conservation_mode` & generic `charge_control_end_threshold` | **Verified Bare-Metal** |
| **ST VL53L1 ToF Human Presence (Intel ISH)** | `/dev/hidraw*` (`8087:0AC2`, 35-byte Report 4) | **Optional Auto-Detected** |

---

## Installation

### Option 1: `.deb` Package (Ubuntu / Debian)
Download `ff-power-manager_2.2.0_amd64.deb` from [Releases](https://github.com/lwrlock/ff-power-manager/releases) and run:
```bash
sudo apt install ./ff-power-manager_2.2.0_amd64.deb
```

### Option 2: Build & Install from Source (Ubuntu / Debian / Fedora)
```bash
git clone https://github.com/lwrlock/ff-power-manager.git
cd ff-power-manager
sudo ./install.sh
```

Or build packages locally:
```bash
bash build-deb.sh          # Produces dist/ff-power-manager_2.2.0_amd64.deb
# Fedora RPM spec: packaging/ff-power-manager.spec
```

---

## Usage

```bash
ffctl status [--json]        # Live wattage, temp, CPU cap, EPP, ARR Hz & ToF state
ffctl doctor [--json]        # Hardware residency, PCI PM, ACPI wakeups & conflict audit
ffctl blame [--json]         # Top CPU/wakeup processes + active PCI/USB hardware blockers
ffctl sleep-report [--json]  # Last s2idle/deep suspend duration, Wh and W standby draw
ffctl health [--json]        # Factory design capacity, full Wh, cycle count & health %
ffctl apply [profile]        # Apply battery|ac|extreme_performance|cool_quiet|max_battery
ffctl conservation on|off    # Toggle 80% battery conservation threshold
ffctl benchmark              # Benchmark native C + x86_64 assembly sysfs read latency
```

Launch interactive UIs anytime: `ff-power-manager` (Cosmic GTK4 App) or `ff-tui` (Terminal Dashboard).

---

## Development & AI Collaboration

FF Power Manager is built and maintained by **Furkan (`@lwrlock`)** with **AI-assisted engineering via Google DeepMind Antigravity** (used for HID Report 4 parsing optimization, C/x86_64 assembly routines, automated test coverage, UI rendering, and multi-distro hardening, while all real-hardware validation and kernel telemetry profiling are verified directly on bare-metal Linux hardware).

## Contributing & Support

Found a quirk on a ThinkPad, IdeaPad, Framework, ASUS, or AMD laptop? Open an [Issue](https://github.com/lwrlock/ff-power-manager/issues) with the output of `ffctl doctor --json` and `ffctl blame --json`. Pull requests, benchmarks, and GitHub Stars are always welcome!

## License

MIT License. Copyright (c) 2026 Furkan (**lwrlock**). See [LICENSE](LICENSE).
