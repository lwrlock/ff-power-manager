# Contributing to FF Power Manager

[ English | [Türkçe](CONTRIBUTING.tr.md) ]

Thanks for checking out the project! Whether you want to fix a bug, suggest an improvement, or report how this behaves on your laptop, contributions are very welcome.

---

## Testing on Different Laptops & Hardware

This utility was built and fine-tuned on a **Lenovo IdeaPad Pro 5 14IAH10** (Intel Core Ultra 9 285H, Samsung 2.8K OLED, ST VL53L1 ToF sensor). 

Lenovo ships slightly different BIOS versions, sensor HID descriptors, and power tables across models. If you test FF Power Manager on another Lenovo laptop (or another Linux distribution), hardware reports are extremely helpful!

When reporting compatibility or issues, please include:
```bash
# Laptop model and BIOS version
cat /sys/class/dmi/id/product_name
cat /sys/class/dmi/id/product_version

# Kernel and distribution
uname -r
cat /etc/os-release | grep PRETTY_NAME

# Power manager status
ffctl status
```

If your laptop has a ToF sensor, you can check if `/dev/hidraw*` picks up HID packets from the Intel ISH sensor:
```bash
journalctl -u ff-presence-sensor.service -n 50 --no-pager
```

---

## Development Principles

When contributing code, please keep these core rules in mind:

1. **Zero unnecessary background polling:** A battery management tool should never burn battery itself. Do not introduce tight sleep loops. Everything should remain event-driven via `udev`, `select(2)` blocking on hardware interrupts, or `GFileMonitor`.
2. **100% offline & private:** No telemetry, no external network calls, no analytics. Everything must run locally on the machine.
3. **Safe file operations:** Configuration updates must use atomic writes (`.tmp` -> `replace`) and schema validation so configs never get corrupted if the machine powers down unexpectedly.
4. **Clean privilege separation:** The desktop GUI and session services run with normal user privileges. Privileged operations are strictly routed through the Polkit helper (`ff-power-helper`) with whitelisted actions.

---

## Running Tests

Before opening a pull request, make sure syntax checks and unit tests pass cleanly:

```bash
# Run test suite
PYTHONPATH=src python3 -m unittest discover -s tests -v

# Syntax compile check
python3 -m py_compile src/fpm/*.py
```

---

## Submitting Pull Requests

1. Fork the repository on GitHub.
2. Create a clean branch for your change:
   ```bash
   git checkout -b feature/my-improvement
   ```
3. Keep commits focused and write descriptive commit messages.
4. Push your branch to your fork and open a Pull Request.

If you're unsure about an idea or change, feel free to open an Issue first to discuss it!
