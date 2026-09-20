# FF Power Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux%20%2F%20Fedora-teal.svg)](https://getfedora.org)
[![Desktop: GNOME](https://img.shields.io/badge/Desktop-GNOME%20%2F%20Wayland-orange.svg)](https://www.gnome.org)

[ English | [Türkçe](README.tr.md) ]

Lightweight, event-driven power profile manager and Lenovo ToF presence automation tool for Linux (Fedora / GNOME / Wayland).

Tested on **Lenovo IdeaPad Pro 5 14IAH10** (Intel Core Ultra 9 285H, Samsung 2.8K 120Hz OLED, 87 Wh battery).

---

## Features

- **Dynamic OLED Refresh Rate:** Automatically drops to **60 Hz** on battery and restores **120 Hz + VRR** on AC power via GNOME Mutter DBus without screen flickering or resets.
- **Lenovo ToF Presence Automation:** Reads raw HID reports from the ST VL53L1 infrared sensor inside Intel ISH (`8087:0AC2`). Blanks the OLED when you step away and wakes it up instantly upon return. 100% hardware infrared, no camera stream, completely private and offline.
- **Touchpad Wake Lag Fix:** Keeps the Synaptics I2C touchpad and Intel DesignWare controller responsive, completely eliminating the 50–100ms first-touch stutter after idle.
- **Hardware Power Profiles:** Configures PCIe ASPM (`powersupersave`), NVMe runtime PM (`auto`), Intel EPP (`balance_power` on battery, `performance` on AC), and audio codec powersave.
- **Zero Background Polling Loops:** No heavy daemons burning CPU to monitor battery. Everything is strictly event-driven via `udev`, `sysfs`, and DBus.
- **GTK4 / Libadwaita GUI & CLI:** Clean native GNOME desktop interface (`ff-power-manager`) with presets, plus a fast console tool (`ffctl`).

---

## Real-World Battery Life (87 Wh Battery)

Tested under Fedora 44 (Linux 7.x, GNOME Wayland, ~30–40% OLED brightness):

| Workload | Average Draw | Approximate Runtime |
| :--- | :---: | :---: |
| **Light Work** (Web browsing, VS Code, terminal, docs at 60Hz) | ~8.0 – 9.0 W | **~9.5 – 10.5 Hours** |
| **Mixed / Heavy** (Multi-tasking, local compiles, background music) | ~11.0 – 12.5 W | **~7.0 – 8.5 Hours** |
| **Plugged In (AC)** | — | 120 Hz + VRR, Full Boost |

---

## Prerequisites

On Fedora Workstation:

```bash
sudo dnf install -y python3-gobject gtk4 libadwaita iw power-profiles-daemon polkit intel-media-driver libva-utils
```

---

## Installation

Clone the repository and run the installer:

```bash
git clone https://github.com/lwrlock/ff-power-manager.git
cd ff-power-manager
chmod +x install.sh
sudo ./install.sh
```

Launch the desktop app from your application menu or terminal:

```bash
ff-power-manager
```

Or check system status from the terminal:

```bash
ffctl status
```

---

## Browser Hardware Video Acceleration

To prevent high CPU usage while streaming video on battery, enable hardware video decoding in your browser:

In Brave or Chrome, navigate to `brave://flags` (or `chrome://flags`), enable **Hardware-accelerated video decode**, and restart your browser.

---

## Contributing

Check out [CONTRIBUTING.md](CONTRIBUTING.md) for testing guidelines on other Lenovo laptops, reporting hardware compatibility, and submitting pull requests.

---

## License

MIT License. Copyright (c) 2026 lwrlock. See [LICENSE](LICENSE) for details.
