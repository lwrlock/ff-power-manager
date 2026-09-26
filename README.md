# FF Power Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%2F%20Fedora-teal.svg)](https://getfedora.org)
[![Desktop: GNOME](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)
[![Engine: C & x86_64 ASM](https://img.shields.io/badge/Engine-C%20%26%20ASM-success.svg)](#)

[ English | [Türkçe](README.tr.md) ]

Ultra-low-latency Linux power profile manager and Lenovo ToF presence sensor automation tool built in **C and x86_64 Assembly** for Fedora / GNOME / Wayland.

Tested Hardware: **Lenovo IdeaPad Pro 5 14IAH10 / Yoga Pro** (Intel Core Ultra 9 285H, Samsung 2.8K 120Hz OLED, 87 Wh battery).

---

## Key Features

- **C & x86_64 Assembly Engine (0.0% CPU Overhead):** Direct Linux syscalls and hand-optimized assembly routines parse sensor packets in sub-microseconds without runtime overhead.
- **Live ToF Presence Radar:** Reads ST VL53L1 HID packets directly from Intel ISH (`8087:0AC2`). Measures distance in real-time centimeters (`68 cm / 120 cm`). Dims OLED screen when away (> 1.2m) and instantly wakes upon return.
- **Dynamic 60 Hz / 120 Hz + VRR Automation:** Automatically switches display to **60 Hz** on battery, and returns to **120 Hz + VRR** on AC mains.
- **GNOME Stutter Protection:** Prevents GNOME from entering sluggish `power-saver` mode (which locks CPU clocks at 400 MHz); maintains smooth 60 FPS on battery using `balanced` mode.
- **btop-Style Dynamic TUI Dashboard (`ff-tui`):** Auto-resizing terminal UI with 3 tabs (`[1] Overview`, `[2] Battery`, `[3] AC Power`) and verified hardware profile application.
- **Systemd Boot Autostart:** Automatically enabled on boot and login with zero manual intervention required.

---

## Installation

```bash
cd ff-power-manager
sudo ./install.sh
```

All services start and enable automatically on boot.

---

## Usage

### 1. Interactive TUI Dashboard (`ff-tui` or `ffctl tui`)
```bash
ff-tui
```
* `1` / `2` / `3` or `Tab` : Switch tabs (Overview / Battery / AC Power)
* `P` : Toggle ToF Sensor on / off
* `T` : Toggle Intel Turbo Boost (Verified in hardware)
* `A` / `B` / `C` : Apply and verify profile from current tab
* `Q` : Quit

### 2. High-Speed CLI (`ffctl`)
```bash
# View instant system, battery, and presence status (< 1 ms)
ffctl status

# Stream live real-time ToF distance and packet counter
ffctl sensor live

# Check ToF sensor status and total packet telemetry
ffctl sensor status

# Apply power profile with hardware verification
ffctl apply battery
ffctl apply ac
```

### 3. Desktop Application (GTK4 / Libadwaita)
Launch **FF Power Manager** from your desktop application launcher or run `ff-power-manager`.

---

## License

MIT License. Copyright (c) 2026 lwrlock. See [LICENSE](LICENSE) for details.
