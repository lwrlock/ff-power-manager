# FF Power Manager v2.1

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Ubuntu | Debian | Fedora](https://img.shields.io/badge/Platform-Ubuntu%20%7C%20Debian%20%7C%20Fedora-teal.svg)](https://ubuntu.com)
[![Desktop: GNOME Wayland](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)
[![Engine: C & x86_64 ASM](https://img.shields.io/badge/Engine-C%20%26%20x86__64%20ASM-success.svg)](#architecture)
[![AI-Assisted: Antigravity](https://img.shields.io/badge/AI--Assisted-Google%20DeepMind%20Antigravity-purple.svg)](#development--ai-collaboration)
[![Release: v2.1.0](https://img.shields.io/badge/Release-v2.1.0-blueviolet.svg)](https://github.com/lwrlock/ff-power-manager/releases/tag/v2.1.0)

[ English | [Türkçe](README.tr.md) ]

**Low-overhead Linux laptop power, thermal, Adaptive Refresh (`60↔Max Hz`), OLED Care, ToF presence automation, and `s2idle` sleep-drain guard.**

Built with a native **C & x86_64 Assembly** telemetry/CLI core (`ffctl`, `ff-tui`, `ff-presence-sensor`) paired with **Python / GTK4 / GNOME Shell Wayland** integration — featuring **Universal Hardware Auto-Discovery** across Intel & AMD laptops (`Ubuntu`, `Debian`, `Fedora`).

---

## Why FF Power Manager vs TLP / auto-cpufreq?

| Capability | TLP / auto-cpufreq | **FF Power Manager v2.1** |
| :--- | :---: | :---: |
| Hybrid P/E/LP-E & Symmetric CPU Topology Discovery | Partial | **Yes (`detect_cpu_topology()` + `cpuinfo_max_freq` clamping)** |
| **Hardware & Power Residency Audit (`ffctl doctor`)** | No | **Yes (`s2idle`, ACPI wakeups, PCI PM ratio, conflict check)** |
| **Machine-Readable Telemetry (`--json`)** | Limited | **Yes (`ffctl status/health/doctor --json` in native C)** |
| **Battery-Only Adaptive Refresh (`60↔Max Hz` at 0ms wake)** | No | **Yes (`Mutter.IdleMonitor.AddUserActiveWatch`)** |
| **App-Aware Cinema & Study/Focus Contexts** | No | **Yes (Stremio/mpv/VLC color lock + DND/Night Light toggle)** |
| **Panel OLED Care & Zero-Touch Blanking** | No | **Yes (HiDPI Pixel Shift + 15s Dim + 0W DPMS OFF)** |
| **ToF Human Presence Radar (Intel ISH HID)** | No | **Yes (C/x86_64 ASM `hidraw` parser + MPRIS/PCM inhibit)** |
| **`s2idle` Suspend Wakeup Guard** | No | **Yes (`systemd-sleep` USB/Thunderbolt wakeup suppressor)** |
| **Thermal Guardrail (`>=90°C` PL1 step-down)** | No | **Yes (OEM TDP clamped RAPL controller)** |
| **One-Shot 100% Charge Watchdog** | No | **Yes (Auto re-arms 80% protection at 99% charge)** |
| **Privilege Model** | Root daemon | **Non-setuid `ffctl` + scoped PolicyKit `ff-power-helper`** |

---

## Architecture

```
  [ST VL53L1 ToF HID] ──► ff-presence-sensor (C + x86_64 ASM) ──► /run/ff-power-manager/*
                                                                          │
  [Mutter IdleMonitor / DisplayConfig D-Bus] ◄─── ff-presence-session ◄───┘
  [/proc/[pid]/comm + /proc/stat + hwmon]    ───► ff-power-autoboost ──► core.py (sysfs / RAPL / GPU / IRQ)
  [systemd-sleep pre/post]                   ───► ff-sleep-guard     ──► /proc/acpi/wakeup & ACPI profile
  [GTK4 GUI / GNOME Top-Bar / ffctl / ff-tui]──► ff-power-helper (PolicyKit, zero setuid root binaries)
```

---

## Key Features (v2.1.0)

- **Hardware Residency Audit (`ffctl doctor`) & `--json` Output:** Verifies `[s2idle]`/`[deep]` sleep hook status, counts armed ACPI wake triggers (`/proc/acpi/wakeup`), audits PCI runtime PM suspended/active device ratios, detects conflicting power daemons (`tlp`, `auto-cpufreq`), and exports clean JSON for scripts, Waybar, or status bars.
- **Zero-Latency Battery-Only Adaptive Refresh (`60 ↔ 120/144/165 Hz`):** Steps down to `60 Hz` after `8s` of reading/inactivity *only while on battery* (disabled on AC and during video playback), snapping back to max refresh rate via `Mutter.IdleMonitor.AddUserActiveWatch` the millisecond input occurs.
- **Universal Intel & AMD Hardware Discovery:** Dynamically detects P/E/LP-E CPU tiers, clamps scaling frequencies to `cpuinfo_min/max_freq` and RAPL limits to `constraint_0_max_power_uw`, pins interactive compositor & HID/GPU IRQs to performance cores, discovers PCI SD controllers (`0x0805*`), supports both Lenovo `conservation_mode` and generic `charge_control_end_threshold`, and detects Intel `xe`/`i915` and AMD Radeon `pp_dpm_sclk` / `k10temp` sensors.
- **Security Hardened Privilege Boundary:** Eliminates setuid-root wrappers; `ffctl` and `ff-tui` execute unprivileged (`0755`) and delegate sysfs mutations strictly to `/usr/local/lib/ff-power-manager/ff-power-helper` via `fork()` + `execv()` (`pkexec` / `sudo -n`) with explicit Polkit rules supporting both Debian/Ubuntu (`sudo`) and Fedora (`wheel`).
- **`s2idle` Suspend Wakeup Guard (`/lib/systemd/system-sleep/ff-sleep-guard`):** Disables spurious USB/Thunderbolt wakeup events (`XHCI`, `TXHC`, `TDM0`, `TRP0`, `TRP1`), sets `low-power` ACPI profile and Wi-Fi `power_save` on suspend, and restores state on wake.
- **One-Shot 100% Charge Watchdog & Thermal Guardrail (`>=90°C`):** Keep `80%` battery conservation enabled daily; flip **1 Kerelik %100 Şarj** before traveling and it automatically re-arms 80% protection once full (`99%`), while `auto_boost.py` preserves custom battery modes after load bursts and tapers PL1 if package temperatures reach `90°C`.

---

## Installation

### Option 1: `.deb` Package (Ubuntu / Debian)
Download `ff-power-manager_2.1.0_amd64.deb` from [Releases](https://github.com/lwrlock/ff-power-manager/releases) and run:
```bash
sudo apt install ./ff-power-manager_2.1.0_amd64.deb
```

### Option 2: Build & Install from Source (Ubuntu / Debian / Fedora)
```bash
git clone https://github.com/lwrlock/ff-power-manager.git
cd ff-power-manager
sudo ./install.sh
```

Or build the `.deb` package locally:
```bash
bash build-deb.sh
```

---

## Usage

- **Native CLI (`ffctl`):**
  ```bash
  ffctl status [--json]
  ffctl doctor [--json]
  ffctl health [--json]
  ffctl apply [battery|ac|extreme_performance|cool_quiet|max_battery]
  ffctl conservation on|off
  ffctl sensor live
  ffctl benchmark
  ```
- **Terminal Dashboard & Desktop App:** Run `ff-tui` for interactive terminal monitoring or `ff-power-manager` for the GTK4 / Libadwaita control center (includes live `ffctl doctor` hardware audit tab).
- **GNOME Top-Bar Popover:** Live package wattage, CPU/SSD/Wi-Fi thermals, Intel Xe / AMD GPU clocks, battery ETA & cycle count, active profile switcher, Adaptive Refresh, OLED Dimming, Focus Mode, One-Shot 100%, ToF Radar toggles, and MPRIS media controls.

---

## Development & AI Collaboration

FF Power Manager is built and maintained by **Furkan (`@lwrlock`)** with **AI-assisted engineering via Google DeepMind Antigravity** (used for HID Report 4 parsing optimization, C/x86_64 assembly boilerplate, automated test coverage, and multi-distro hardening, while all real-hardware validation and kernel telemetry profiling are verified directly on bare-metal Linux hardware).

## Contributing & Support

Found a quirk on a ThinkPad, IdeaPad, Framework, ASUS, or AMD laptop? Open an [Issue](https://github.com/lwrlock/ff-power-manager/issues) with the output of `ffctl doctor --json` and `ffctl status --json`. Pull requests, benchmarks, and GitHub Stars are always appreciated!

## License

MIT License. Copyright (c) 2026 Furkan (**lwrlock**). See [LICENSE](LICENSE).
