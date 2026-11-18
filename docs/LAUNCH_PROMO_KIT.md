# FF Power Manager v2.1 — Launch & Community Notes

Everything below reflects the public GitHub repository and `v2.1.0` Release at:
`https://github.com/lwrlock/ff-power-manager`

---

## 1. Hacker News (`Show HN`)
- **Title:** `Show HN: FF Power Manager v2.1 – Adaptive Refresh (60↔120Hz), ffctl doctor & ToF Radar for Linux`
- **Text:**
  > I built FF Power Manager (C + x86_64 Assembly + Python/GTK4 + GNOME Shell extension) to solve modern Linux laptop power management, residency diagnostics, and dynamic display refresh quirks without shell-script daemon bloat.
  >
  > Features in v2.1:
  > - **Hardware & Residency Audit (`ffctl doctor --json`)**: Checks `s2idle` wakeup guards, `/proc/acpi/wakeup` armed triggers, PCI Runtime PM suspended/active ratios, P-state/EPP drivers, and conflicting daemons (`tlp`, `auto-cpufreq`) in < 2 ms.
  > - **Battery-Only Adaptive Refresh (`60 ↔ Max Hz`)**: Uses `org.gnome.Mutter.IdleMonitor` (`AddIdleWatch` + `AddUserActiveWatch`) so the panel drops to 60Hz when reading static content on battery and jumps back to max refresh rate at 0ms on mouse/keyboard touch (never active on AC or during video playback).
  > - **ToF Human Presence Radar**: Sub-microsecond C/ASM parser for Intel ISH HID packets (ST VL53L1) integrated with Mutter DPMS OFF & MPRIS/PipeWire media inhibition.
  > - **`s2idle` Suspend Wakeup Guard & Universal Auto-Discovery**: Dynamically discovers Intel/AMD topologies, clamps RAPL to OEM ceilings, pins interactive IRQs/compositors to P-cores, and runs unprivileged without setuid root binaries.
  >
  > Source & `.deb` download: https://github.com/lwrlock/ff-power-manager

---

## 2. Reddit (`r/linux`, `r/Ubuntu`, `r/thinkpad`, `r/Lenovo`)
- **Title:** `[Open Source] FF Power Manager v2.1 – Hardware Residency Audit (ffctl doctor), Battery-Only Adaptive Refresh (60↔Max Hz), s2idle Guard & GNOME Telemetry (.deb + Source)`
- **Body:**
  > Hey everyone! I just released **v2.1** of **FF Power Manager** — a Linux laptop power, thermal, and telemetry suite built in **C / x86_64 Assembly + Python/GTK4 + GNOME Shell JS**.
  >
  > **Highlights in v2.1:**
  > - **Hardware Residency Audit (`ffctl doctor --json`):** Audits `[s2idle]`/`[deep]` sleep guard state, armed ACPI wakeups, PCI runtime PM suspended/active ratios, active P-state/EPP drivers, and conflicting daemons in `< 2 ms`, with `--json` output across `status`, `health`, and `doctor`.
  > - **Battery-Only Adaptive Refresh (ARR):** Steps down to `60 Hz` after 8s idle strictly on battery and snaps back to `120 Hz+` on input via Mutter `IdleMonitor` D-Bus (disabled on AC or during video playback).
  > - **Universal Intel/AMD Support & Non-Setuid Security:** Dynamically detects P/E/LP-E cores (`detect_cpu_topology`), clamps frequencies/RAPL to hardware firmware ceilings, reads true `coretemp`/`k10temp`/`x86_pkg_temp` sensors, and uses scoped PolicyKit helpers with zero setuid root binaries.
  > - **`s2idle` Suspend Wakeup Guard & One-Shot 100% Charge Watchdog:** Suppresses USB/Thunderbolt spurious wakes on sleep, and lets you charge to 100% once before auto re-arming 80% protection.
  >
  > Repo & `.deb` release: https://github.com/lwrlock/ff-power-manager
  > Feedback, benchmarks, and `ffctl doctor --json` outputs from your laptops are welcome!

---

## 3. X (Twitter) Thread
1. I just released **FF Power Manager v2.1** — C/x86_64 ASM + GTK4 Linux power management with `ffctl doctor --json`, **0ms Battery-Only Adaptive Refresh (`60↔120Hz`)**, **OLED care**, and **`s2idle` sleep drain protection**. 🧵👇 https://github.com/lwrlock/ff-power-manager
2. Built without setuid root wrappers or hardcoded core counts: auto-discovers Intel/AMD topologies, clamps RAPL to OEM limits, audits PCI runtime PM ratios in `<2ms`, and ships a native GNOME top-bar telemetry HUD.
3. Download `ff-power-manager_2.1.0_amd64.deb` or build from source on Ubuntu/Debian/Fedora: `sudo apt install ./ff-power-manager_2.1.0_amd64.deb`

---

## 4. LinkedIn (EN / TR)
> Built & open-sourced **FF Power Manager v2.1** — a Linux laptop power, thermal, and residency diagnostics suite built with **C, x86_64 Assembly, Python, GTK4, and GNOME Shell JS**.
> Highlights: Zero-setuid PolicyKit architecture, `<2ms` hardware residency & PCI PM audit (`ffctl doctor --json`), `Mutter.IdleMonitor` Adaptive Refresh (`60↔Max Hz`), universal Intel/AMD topology discovery, and `s2idle` ACPI wakeup guard.
> GitHub: https://github.com/lwrlock/ff-power-manager
