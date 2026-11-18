# Official Engineering Outreach — Lenovo Linux Team Proposal

## Target Recipients
- **To:** `mpearson@lenovo.com`, `mpearson-lenovo@squebb.ca` (Mark Pearson — Senior Linux Developer / PC Linux Lead, Lenovo)
- **CC / Alternative:** Lenovo Linux Community Forum (`https://forums.lenovo.com` — Ubuntu / Fedora Linux Boards)

---

## Email Subject
`Open-Source Contribution & Collaboration: FF Power Manager v2.0 (Lenovo IdeaPad Pro 5 / Intel ISH ToF VL53L1 + 120Hz OLED ProMotion + s2idle Optimization)`

---

## Email Body (Ready to Send)

Hi Mark,

I hope you are doing well. My name is Furkan (`lwrlock` on GitHub), an 18-year-old Computer Engineering student and Linux enthusiast running Ubuntu/Fedora on a **Lenovo IdeaPad Pro 5 14IAH10 (83JK — Intel Core Ultra 9 285H, Intel Arc Graphics, 2.8K 120Hz OLED, Intel ISH ST VL53L1 ToF Sensor)**.

Over the past several weeks, I built and open-sourced **FF Power Manager v2.0** (MIT License) to solve several real-world power, thermal, and display gaps on modern Lenovo laptops under Linux/GNOME Wayland—and I would love to share the findings and contribute toward making official Lenovo/Linux support even better (upstream `power-profiles-daemon`, `ideapad-laptop`, or official Lenovo Linux guides/tools):

### Key Engineering Highlights & Technical Findings
1. **Intel ISH Human-Presence Sensor (`HID_ID=001F:00008087:00000AC2` / ST VL53L1):**
   - Decoded the raw 35-byte HID Feature/Input Report 4 format (16-bit millimeter distance layout + presence bit + D0/D4 power state transitions) in a zero-overhead C & x86_64 Assembly reader (`< 1 MB` RAM, `0.0%` CPU).
   - Paired with GNOME `Mutter.DisplayConfig` DPMS OFF + `Mutter.IdleMonitor` safety checks and MPRIS/PipeWire media inhibition so the OLED panel turns off cleanly when walking away and wakes on approach.
2. **Battery-Only ProMotion (`60 ↔ 120 Hz`) without Polling:**
   - Implemented an event-driven `org.gnome.Mutter.IdleMonitor` (`AddIdleWatch` + `AddUserActiveWatch`) controller that drops the 2.8K OLED panel to `60 Hz` after 8 seconds of inactivity *only on battery*, and snaps back to `120 Hz` at `0 ms` on mouse/keyboard touch (staying locked at `120 Hz` during AC power or video playback).
3. **Lenovo IdeaPad ACPI Integration (`VPC2004:00`) & Hybrid Topology Tuning:**
   - Integrated `conservation_mode` (plus a One-Shot 100% Charge Watchdog that automatically re-enables 80% conservation when full), `fn_lock`, `usb_charging`, `platform_profile`, and non-hotplug Intel Core Ultra P/E/LP-E EPP/EPB + Intel Xe GuC SLPC `rpn_freq` clamping so idle power drops near ~5W while maintaining crisp 120Hz UI responsiveness.
4. **`s2idle` Backpack Drain Prevention (`systemd-sleep` hook):**
   - Found that spurious USB/Thunderbolt wakeup nodes (`XHCI`, `TXHC`, `TDM0`, `TRP0`, `TRP1`) and elevated ACPI profiles drain battery during `s2idle` standby; added a clean `pre`/`post` sleep guard that preserves lid/`PWRB` wakeup while eliminating backpack heat/drain.

### Repository & Release Package
- **GitHub Repository (MIT):** https://github.com/lwrlock/ff-power-manager
- **v2.0.0 Release & `.deb` Package:** https://github.com/lwrlock/ff-power-manager/releases/tag/v2.0.0

I would be genuinely honored to help test patches, share HID descriptor / ACPI traces from the `14IAH10 (83JK)` platform, or help turn any of these components (like the ST VL53L1 presence daemon or ProMotion helper) into upstream/official Lenovo Linux tooling.

Thank you very much for all the work you and the Lenovo Linux team already do for the community!

Best regards,  
**Furkan** (`lwrlock`)  
GitHub: https://github.com/lwrlock  
Project: https://github.com/lwrlock/ff-power-manager
