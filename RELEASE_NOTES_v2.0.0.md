# FF Power Manager v2.0.0 — Universal Linux & ProMotion Edition

## Highlights
- **Universal Hardware Auto-Discovery:** Works cleanly across Intel & AMD laptops (`Ubuntu`, `Debian`, `Fedora`) with dynamic CPU topology classification (`detect_cpu_topology()`), dynamic display resolution/refresh matching, automatic `BAT0/BAT1` discovery, Lenovo `conservation_mode` + standard `charge_control_end_threshold` fallback, Intel Xe / i915 / AMD GPU telemetry, and `hwmon` NVMe/Wi-Fi thermal monitoring.
- **Battery-Only ProMotion (`60 ↔ 120/144/165 Hz`):** Zero-polling `Mutter.IdleMonitor` drops refresh rate to `60 Hz` after 8s idle on battery and wakes instantaneously (`0 ms`) on input.
- **App-Aware Cinema & Study/Focus Profiles:** Automatically locks ProMotion high refresh & pauses Night Light for `stremio`/`mpv`/`vlc`; adds 1-click Study/Focus toggle (DND + Night Light + `cool_quiet`).
- **One-Shot 100% Charge Watchdog:** Re-arms 80% battery conservation automatically at `>=99%` with desktop notification.
- **Thermal Guardrail (`>=90°C`) + Zero-Fork Audio Monitor:** Prevents sustained thermal throttling in `auto_boost.py` and replaces 3s `pactl` subprocess polling with native `/proc/asound` checks.
- **`s2idle` Backpack Drain Guard (`/lib/systemd/system-sleep/ff-sleep-guard`):** Suppresses USB/Thunderbolt spurious wakeup sources during suspend and restores them cleanly on resume.
- **`.deb` Packaging & GitHub Actions CI:** Ships a reproducible `build-deb.sh` and automated test + package workflow.
