## 🚀 FF Power Manager v1.1.0 — MacBook-Grade Optimization & Zero-Stutter Architecture

A major milestone release introducing hardware-level latency tuning, video playback zero-stutter fixes, an overhauled GTK4/Libadwaita interface with full real-time telemetry, and Wine/Flowgorithm Hi-DPI integration for Fedora / GNOME Wayland.

---

### 🌟 Key Highlights & Improvements

#### 1. 🎬 Zero-Stutter Video & Media Playback
* **Intel Arc GPU 800 MHz Floor:** Dynamically maintains a minimum 800 MHz frequency floor (`/sys/class/drm/card1/gt_min_freq_mhz`) during video playback in balanced mode, completely eliminating dropouts and frame stutters without inflating battery drain.
* **Native Intel iHD VA-API Acceleration:** Configures hardware-accelerated video decoding (`LIBVA_DRIVER_NAME=iHD`) across all browsers and media players.
* **No Forced Power-Saver Stutter on Battery:** Re-tuned governor parameters to keep smooth 60 Hz/120 Hz animation frame pacing even on battery power.

#### 2. ⚡ MacBook-Grade Power Efficiency & System Tuning
* **PCIe ASPM `powersupersave`:** Enforces deep active state power management across all PCIe links and bus controllers.
* **PCI Runtime PM Across 60+ Devices:** Automatically suspends idle PCIe root ports, bridges, and peripherals.
* **Intel Wi-Fi 7 Power Saving:** Enabled `uapsd_disable=0` and hardware sleep timers for Intel BE200 / AX wireless chipsets.
* **NVMe APST Autonomous Transitions:** Configured deep autonomous power state transitions (`PS4`) with ultra-low latency wake-up.
* **Modern ZRAM with `zstd`:** Switched to high-throughput `zstd` compression for instantaneous app switching under load.
* **Google TCP BBR & VFS Tuning:** Lower network latency and snappier file system caching.

#### 3. 🎨 GTK4 / Libadwaita GUI Overhaul (`ff-power-manager`)
* **Live Hardware Telemetry Grid:** Real-time display of GPU frequency floor, VA-API hardware driver, Google TCP BBR algorithm, and ZRAM compression state.
* **Zero Markup & CSS Warnings:** Fixed Pango XML character entity encoding and modernized styling for modern Libadwaita themes.
* **Native About Dialog:** Added Libadwaita `AboutDialog` celebrating the developer's journey, project architecture, and transparent open-source AI collaboration.

#### 4. 🪟 Wine & Flowgorithm Hi-DPI & OLED Suite
* **200% Hi-DPI Auto-Scaler:** Dedicated script (`set-dpi.sh 200`) providing crystal-clear scaling on 2.8K / 4K displays for Windows applications.
* **OLED Midnight Slate Theme:** High-contrast, glare-free dark theme crafted for Samsung OLED panels.

---

### 💻 Installation & Upgrade

```bash
git clone https://github.com/lwrlock/ff-power-manager.git
cd ff-power-manager
./install.sh
```

To launch the GUI:
```bash
ff-power-manager
```
Or launch the terminal dashboard:
```bash
ff-tui
```

---

*Developed by Furkan ([@lwrlock](https://github.com/lwrlock)), 17-year-old Computer Engineering student, in collaboration with Google DeepMind Antigravity.*
