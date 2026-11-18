# FF Power Manager v2.2.0

**FF Power Manager v2.2.0** adds live wakeup blame profiling, suspend drain analytics, Multi-DE adaptive refresh support, focus-aware battery throttling, Waybar/RPM support, and a full Cosmic Space GTK4 desktop UI.

### Highlights
- **Cosmic Space GTK4 Control Center (`ff-power-manager`):** Layered Cairo cosmic space backdrop (nebula glow, rotating ringed planet, orbiting satellite, twinkling starfield, and shooting stars with automatic ~9 FPS battery frame-pacing + header toggle), translucent frosted-glass hero cards, live Wattage & Temperature sparkline graph (`TelemetrySparklineChart`), and custom SVG desktop icon.
- **Wakeup & Energy Blame Profiler (`ffctl blame [--json]`):** 250ms native C procfs sampler ranking top processes by CPU % and context-switch wakeups/sec alongside active non-suspended PCI/USB hardware blockers — integrated both in CLI and a dedicated **Blame Profiler** GUI tab.
- **Suspend Drain Tracker (`ffctl sleep-report [--json]`):** Enhanced `/lib/systemd/system-sleep/ff-sleep-guard` records pre/post `energy_now` (`Wh`) and computes exact sleep duration, average standby wattage (`W`), and `%/hr` lost per suspend cycle (`/var/lib/ff-power-manager/last_sleep.json`).
- **Live Telemetry History Ring Buffer (`auto_boost.py`):** Captures rolling wattage and CPU package temperature history into `/run/ff-power-manager/telemetry_history.json` plus focus-aware battery throttling for unfocused background browsers/Electron apps.
- **Multi-DE ARR & Packaging:** Added Hyprland (`hyprctl`) and KDE Plasma (`kscreen-doctor`) Adaptive Refresh backends in `presence.py`, ready-to-use `contrib/waybar/` config, and Fedora RPM spec (`packaging/ff-power-manager.spec`).
