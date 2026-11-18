# FF Power Manager v2.0 — Launch & Promotion Kit

Everything below is ready to copy-paste onto communities once the public GitHub repository and `v2.0.0` Release are live at:
`https://github.com/lwrlock/ff-power-manager`

---

## 1. Hacker News (`Show HN`)
- **Title:** `Show HN: FF Power Manager v2.0 – MacBook ProMotion (60↔120Hz), OLED Guard & ToF Radar for Linux`
- **Text:**
  > I built FF Power Manager (hybrid C + x86_64 Assembly + Python/GTK4 + GNOME Shell extension) to bring Apple Silicon–grade battery life and smoothness to Linux laptops.
  >
  > Features in v2.0:
  > - **Battery-only ProMotion (`60 ↔ 120/144Hz`)**: Uses `org.gnome.Mutter.IdleMonitor` (`AddIdleWatch` + `AddUserActiveWatch`) so the panel drops to 60Hz when reading static content on battery and jumps back to 120Hz at 0ms on mouse/keyboard touch (never active on AC or during video playback).
  > - **ToF Human Presence Radar**: Sub-microsecond C/ASM parser for Intel ISH HID packets (ST VL53L1) that turns off OLED pixels (DPMS) when you step away and puts idle Bluetooth to sleep safely.
  > - **`s2idle` Backpack Drain Guard**: `systemd-sleep` hook that suppresses spurious USB/Thunderbolt wakeup sources during suspend.
  > - **Universal Auto-Discovery + `.deb` package**: Auto-detects CPU P/E/LP-E core topology, Intel Xe / i915 / AMD GPUs, `BAT0/BAT1`, NVMe/Wi-Fi thermals, and ships a native GNOME top-bar popover with One-Shot 100% Charge Watchdog & Cinema/Focus modes.
  >
  > Source & `.deb` download: https://github.com/lwrlock/ff-power-manager

---

## 2. Reddit (`r/linux`, `r/Ubuntu`, `r/thinkpad`, `r/Lenovo`)
- **Title:** `[Open Source] FF Power Manager v2.0 – Battery-Only ProMotion (60↔120Hz at 0ms), OLED Care, s2idle Sleep Guard & Live Top-Bar Telemetry for Linux (.deb + Source)`
- **Body:**
  > Hey everyone! I just open-sourced **v2.0** of **FF Power Manager** — an all-in-one Linux power, OLED care, and performance engine written in **C / x86_64 Assembly + Python + GNOME Shell JS**.
  >
  > **What makes it different from TLP / auto-cpufreq?**
  > - **True Battery-Only ProMotion:** Automatically drops to `60 Hz` after 8s idle on battery and snaps back to `120 Hz+` in `0 ms` on any touchpad/keyboard movement via Mutter `IdleMonitor` D-Bus (disabled on AC or while watching video).
  > - **s2idle Backpack Drain Guard:** Stops spurious USB/Thunderbolt wakeups and enforces ACPI `low-power` during suspend so your laptop doesn't cook inside your backpack.
  > - **OLED Burn-In & Care Suite:** HiDPI-safe pixel shift, 15s idle dim, ToF presence radar screen-off, and Cinema Mode (locks 120Hz & temporarily pauses Night Light when Stremio/mpv/VLC runs).
  > - **Thermal Guardrail (`>=90°C`) & Hybrid Core QoS:** Boosts compilers/AI/games automatically while softening PL1 above 90°C to avoid endless fan noise.
  > - **One-Shot 100% Charge Watchdog:** Temporarily charge to 100% before traveling; auto-restores 80% battery conservation once full.
  > - **Universal Intel/AMD Support & Easy `.deb` Install:** Auto-discovers CPU cores, GPU nodes (Intel Xe / i915 / AMD), `BAT0/BAT1`, and SSD/Wi-Fi thermals.
  >
  > Repo & `.deb` release: https://github.com/lwrlock/ff-power-manager
  > Feedback, benchmarks, and PRs are super welcome!

---

## 3. X (Twitter) Thread
1. I just open-sourced **FF Power Manager v2.0** — bringing MacBook-level battery life, **0ms Battery-Only ProMotion (`60↔120Hz`)**, **OLED burn-in protection**, and **`s2idle` sleep drain fix** to Linux laptops. 🧵👇 https://github.com/lwrlock/ff-power-manager
2. Most Linux power tools only tweak CPU governors. FF Power Manager combines a C/x86_64 ASM sensor engine + `Mutter.IdleMonitor` D-Bus + systemd sleep hooks + a native GNOME top-bar telemetry HUD (Watts, Xe/AMD GPU MHz, SSD/Wi-Fi temps, ETA, Wh saved).
3. Download the `.deb` release or build from source in 1 command: `sudo apt install ./ff-power-manager_2.0.0_amd64.deb` ⭐ Star on GitHub if you run Linux on an OLED or Intel/AMD laptop!

---

## 4. LinkedIn (EN / TR)
> Built & open-sourced **FF Power Manager v2.0** — a low-level Linux laptop power, thermal, and display engine built with **C, x86_64 Assembly, Python, GTK4, and GNOME Shell JS**.
> Highlights: Zero-polling `Mutter.IdleMonitor` ProMotion (`60↔120Hz`), Intel/AMD hybrid topology discovery, `sysfs` RAPL/GPU/thermal telemetry, `s2idle` ACPI wakeup guard, and automated CI + `.deb` packaging.
> GitHub: https://github.com/lwrlock/ff-power-manager
