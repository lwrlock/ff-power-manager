# FF Power Manager v2.0

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/lwrlock/ff-power-manager/actions/workflows/ci.yml/badge.svg)](https://github.com/lwrlock/ff-power-manager/actions/workflows/ci.yml)
[![Platform: Ubuntu & Fedora](https://img.shields.io/badge/Platform-Ubuntu%20%7C%20Fedora-teal.svg)](https://ubuntu.com)
[![Desktop: GNOME Wayland](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)
[![Engine: C & x86_64 ASM](https://img.shields.io/badge/Engine-C%20%26%20x86__64%20ASM-success.svg)](#)
[![Release: v2.0.0](https://img.shields.io/badge/Release-v2.0.0-blueviolet.svg)](https://github.com/lwrlock/ff-power-manager/releases/tag/v2.0.0)

[ English | [Türkçe](README.tr.md) ]

**Bring MacBook Pro battery life, 0ms Battery-Only ProMotion (`60↔120 Hz`), OLED Burn-In Guard, ToF Presence Radar, and `s2idle` Backpack Drain Protection to Linux laptops.**

Powered by a zero-overhead **C & x86_64 Assembly** native engine paired with **Python / GTK4 / GNOME Shell Wayland** integration — now with **Universal Auto-Discovery** across Intel & AMD laptops (`Ubuntu`, `Debian`, `Fedora`).

---

## Why FF Power Manager vs TLP / auto-cpufreq?

| Capability | TLP / auto-cpufreq | **FF Power Manager v2.0** |
| :--- | :---: | :---: |
| CPU EPP / RAPL / Hybrid P+E Topology Auto-Discovery | Partial | **Yes (`detect_cpu_topology()` Intel & AMD)** |
| **Battery-Only ProMotion (`60↔120 Hz` at 0ms wake)** | No | **Yes (`Mutter.IdleMonitor` D-Bus)** |
| **App-Aware Cinema & Study/Focus Profiles** | No | **Yes (Auto P3 120Hz for Video / DND + Night Light)** |
| **OLED Care & Burn-In Prevention** | No | **Yes (HiDPI Pixel Shift + 15s Dim + 0W Walk-Away)** |
| **ToF Human Presence Radar + Smart BT Sleep** | No | **Yes (Native C/x86_64 ASM Intel ISH HID)** |
| **`s2idle` Backpack Battery Drain Guard** | No | **Yes (`systemd-sleep` USB/TB wakeup suppressor)** |
| **Thermal Guardrail (`>=90°C` PL1 step-down)** | No | **Yes** |
| **One-Shot 100% Charge Watchdog** | No | **Yes (Auto re-arms 80% conservation at 99%)** |
| **GNOME Top-Bar Live Telemetry** | No | **Yes (Watts, Intel Xe/AMD GPU, SSD/Wi-Fi °C, ETA, Wh Saved)** |

---

## Key Features (v2.0.0)

- **True Battery-Only Apple ProMotion (`60 ↔ 120/144/165 Hz`):** Automatically drops refresh rate to `60 Hz` after `8s` of reading/inactivity *only while on battery* (and never during AC or video playback), jumping back to max refresh rate at **0ms** via `Mutter.IdleMonitor.AddUserActiveWatch` the instant you touch the touchpad or keyboard.
- **Universal Laptop Auto-Discovery:** Dynamically detects CPU P/E/LP-E core topology, active display resolution & refresh rates, `BAT0/BAT1` fuel gauges, Lenovo `conservation_mode` or standard `charge_control_end_threshold`, Intel Xe / i915 / AMD Radeon GPU clocks, `hwmon` NVMe/Wi-Fi thermals, and all wireless interfaces.
- **App-Aware Cinema & Study/Focus Engine:** Detects `stremio`, `mpv`, `vlc`, `celluloid`, `kodi` to lock smooth high refresh rate and pause Night Light for accurate cinema colors. One-click **Focus / Study Mode** enables Do Not Disturb, Night Light, and quiet `balance_power`.
- **One-Shot 100% Charge Watchdog:** Keep 80% battery conservation enabled daily; flip **1-Shot 100% Charge** before traveling and FF Power Manager automatically re-enables 80% protection + sends a desktop notification as soon as the battery reaches `99%`.
- **Thermal Guardrail (`>=90°C`):** `auto_boost.py` monitors CPU package sensors during heavy compilation, gaming, or AI workloads (`llama-server`, `python3`, `cmake`, `cargo`, `.exe` Proton games) and smoothly tapers PL1 limits before thermal throttling occurs.
- **`s2idle` Backpack Drain Guard (`/lib/systemd/system-sleep/ff-sleep-guard`):** Disables spurious USB/Thunderbolt wakeup events (`XHCI`, `TXHC`, `TDM0`, `TRP0`, `TRP1`), sets `low-power` ACPI profile and Wi-Fi `power_save` on suspend, and restores everything cleanly on wake.
- **Live Energy & OLED Savings Tracker:** Tracks daily screen-off minutes & ProMotion `Wh` savings right inside the GNOME top-bar popover.

---

## Installation

### Option 1: `.deb` Package (Ubuntu / Debian)
Download `ff-power-manager_2.0.0_amd64.deb` from [Releases](https://github.com/lwrlock/ff-power-manager/releases) and run:
```bash
sudo apt install ./ff-power-manager_2.0.0_amd64.deb
```

### Option 2: Build & Install from Source (Ubuntu / Fedora)
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

- **GNOME Top-Bar Popover:** Live Wattage, CPU/SSD/Wi-Fi thermals, Intel Xe / AMD GPU clocks, Battery ETA & health, active profile switcher, ProMotion / OLED Dimming / Focus Mode / One-Shot 100% / ToF Radar toggles, and MPRIS media controls.
- **High-Speed Native CLI (`ffctl`):**
  ```bash
  ffctl status
  ffctl health
  ffctl apply [battery|ac|extreme_performance|cool_quiet|max_battery]
  ffctl conservation on|off
  ffctl sensor live
  ```
- **btop-style TUI & GTK4 GUI:** Run `ff-tui` or `ff-power-manager`.

---

## Support the Project

If **FF Power Manager** saved your laptop battery or OLED display, consider starring the repo or sponsoring development via [GitHub Sponsors](https://github.com/sponsors/lwrlock).

## License

MIT License. Copyright (c) 2026 Furkan (**lwrlock**). See [LICENSE](LICENSE).
