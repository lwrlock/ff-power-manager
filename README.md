# FF Power Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%2F%20Fedora-teal.svg)](https://getfedora.org)
[![Desktop: GNOME](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)
[![Engine: C & x86_64 ASM](https://img.shields.io/badge/Engine-C%20%26%20ASM-success.svg)](#)
[![Version: v1.2.0](https://img.shields.io/badge/Release-v1.2.0-blueviolet.svg)](https://github.com/lwrlock/ff-power-manager/releases/tag/v1.2.0)
[![Developed with AI](https://img.shields.io/badge/Developed%20with-AI%20Assistance-blueviolet.svg)](#-developed-with-ai-assistance)

[ English | [Türkçe](README.tr.md) ]

Ultra-low-latency, zero-overhead Linux power profile manager, Lenovo IdeaPad hardware integration, and ToF human presence sensor automation engine built in **C and x86_64 Assembly** for Fedora / GNOME / Wayland.

Tested Hardware: **Lenovo IdeaPad Pro 5 14IAH10 / Yoga Pro** (Intel Core Ultra 9 285H Arrow Lake, Intel Arc Graphics, Samsung 2.8K 120Hz OLED, 87 Wh battery).

---

## 🌟 Key Features & Capabilities (v1.2.0)

- **⚡ C & x86_64 Assembly Engine (0.0% CPU Overhead, < 1 MB RAM):** Direct Linux syscalls and hand-optimized assembly routines parse ToF sensor packets in sub-microseconds with zero CPU overhead.
- **🛡️ Lenovo IdeaPad Hardware Integration (VPC2004):** Direct single-command and single-click control of proprietary ACPI nodes:
  - **80% Battery Conservation Mode:** Caps battery charging at 80% to dramatically extend cell lifespan.
  - **Fn-Lock:** Instant toggle for primary media/hotkey vs standard F1-F12 keys.
  - **Always-On USB Charging:** Charge external devices even when the laptop is completely powered off.
- **🔋 Battery Health & Degradation Analytics (`ffctl health`):** Real-time hardware fuel-gauge diagnostics reporting factory design capacity, full capacity, cycle count, degradation percentage, voltage, and charging profile modes.
- **⚡ GNOME Top Bar Quick Power Indicator Extension:** Minimalist GNOME Shell extension displaying real-time system power draw (`⚡ 5.2 W` / `🔌 AC`) with a quick popover menu for profile switching, ToF radar, and 80% conservation mode toggling.
- **🖥️ Samsung 2.8K OLED Screen Care & Anti-Burn-in:** Subtle inactivity dimming (45s timeout) and pure black (#000000) 0W pixel shutdown when walking away, eliminating static image burn-in while saving maximum battery.
- **🚀 Auto Dynamic Boost & GameMode Engine:** Background process monitor detecting gaming (Steam, Gamescope, Lutris), 3D renderers (Blender, OBS), and compilers (gcc, cargo, clang) to auto-engage extreme performance mode.
- **🔋 Idle ~5W Optimization (Windows-Level Battery Efficiency):**
  - **Deep Package C-States (Package C8/C10):** Intel LPSS PCI host controller constraints removed, allowing the Arrow Lake SoC to reach deep sleep states.
  - **Intel Arc GPU GuC SLPC Power Saving:** GPU switches to `power_saving` profile with render standby (RC6) deep sleep and throttled boost clocks on battery.
  - **TUI & Panel Self Refresh (PSR):** Terminal UI redraw rates optimized to allow the Samsung OLED display to engage Panel Self Refresh (PSR).
  - **Kernel & I/O Tuning:** `laptop_mode=5`, `dirty_writeback_centisecs=6000`, `nmi_watchdog=0`, SCSI ALPM `med_power_with_dipm`, and WiFi 802.11 power saving.
- **📡 Live ToF Presence Radar & Millimeter Precision:** Parses raw 35-byte HID packets directly from the ST VL53L1 infrared sensor. Accurately tracks distance in 16-bit millimeters (`70 cm / 120 cm`). Blanks OLED screen when absent (> 1.2m) and wakes instantly upon return.
- **🖥️ Dynamic 60 Hz / 120 Hz + VRR Automation:** Automatically steps Samsung 2.8K OLED down to **60 Hz** on battery (saving ~2W directly), and returns to **120 Hz + VRR** on AC power.
- **📊 btop-Style Dynamic Terminal Dashboard (`ff-tui`):** Multi-tabbed (`[1] Overview`, `[2] Battery`, `[3] AC Power`), auto-resizing interactive terminal UI with single-key profile switching and 80% conservation toggle (`[K]`).
- **🎨 Modern GTK4 / Libadwaita Desktop App (`ff-power-manager`):** Live ToF radar, animated distance progress bar, Lenovo hardware controls, Battery Health analytics card, and hero styling.
- **🔒 Secure & Instant Permissions:** Protected with `setuid root (4755)` on `ffctl` and Polkit rules for instant profile application without password prompts.

---

## 🚀 Installation & Setup

Build and install the entire suite with a single command:

```bash
cd ff-power-manager
sudo ./install.sh
```

All system services, permissions, GNOME top bar extension, and desktop launchers activate automatically upon installation.

---

## 🛠️ Usage

### 1. Interactive Terminal Dashboard (`ff-tui` or `ffctl tui`)
Launch from the desktop applications menu or run directly:
```bash
ff-tui
```
* `1` / `2` / `3` or `Tab` : Switch tabs (Overview / Battery / AC Power)
* `P` : Toggle ToF Sensor live
* `K` : Toggle Lenovo 80% Battery Conservation Mode
* `T` : Toggle Intel Turbo Boost (Verified in hardware)
* `A` / `B` / `C` : Instantly apply and verify active tab profile
* `Q` : Quit

### 2. High-Speed CLI (`ffctl`)
```bash
# View instant system, battery, EPP, and ToF status (< 1 ms)
ffctl status

# View battery health, degradation score, design Wh, and cycle count
ffctl health

# View Lenovo IdeaPad hardware integration status
ffctl lenovo

# Toggle 80% battery conservation mode
ffctl conservation on
ffctl conservation off

# Stream live real-time ToF distance and packet counter
ffctl sensor live

# Apply power profiles directly to hardware
ffctl apply battery
ffctl apply ac
ffctl apply extreme_performance
ffctl apply cool_quiet
ffctl apply max_battery
```

### 3. Modern Desktop GUI (GTK4 / Libadwaita)
Launch **FF Power Manager** from your desktop application launcher or run `ff-power-manager`.

---

## 🤖 Developed with AI Assistance

This project was engineered, optimized, and modernized in deep collaboration with Artificial Intelligence (Google DeepMind Antigravity):

- **Reverse Engineering & Protocol Decoding:** Deconstructed raw 35-byte HID packets from the ST VL53L1 ToF sensor to identify 16-bit millimeter distance formatting.
- **x86_64 Assembly & C Engine:** Developed hand-crafted assembly routines and low-level C syscall pipelines for sub-microsecond, 0.0% CPU sensor monitoring.
- **Hardware Power Tuning (~5W Idle):** Diagnosed Intel Core Ultra Arrow Lake Package C-State bottlenecks (LPSS PCI bridge), enabled Intel Arc GPU GuC SLPC energy saving, and implemented dynamic 2.8K OLED refresh rate automation.
- **Interface Engineering:** Modernized GTK4 Libadwaita GUI, built GNOME Top Bar power indicator, and crafted a btop-inspired curses terminal dashboard.

---

## 👨‍💻 About the Developer

Hi! I'm Furkan (**lwrlock**), a 17-year-old Computer Engineering student and Linux enthusiast. I built **FF Power Manager** to bridge the gap between cutting-edge laptop hardware (Intel Core Ultra, Intel Arc Pro, Samsung 2.8K OLED) and the Linux desktop experience — achieving true MacBook-like battery efficiency, instant responsiveness, and zero background CPU overhead on Fedora & GNOME.

---

## 📄 License

MIT License. Copyright (c) 2026 lwrlock. See [LICENSE](LICENSE) for details.
