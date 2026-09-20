# FF Power Manager Architecture

FF Power Manager deliberately separates privileged hardware control from the GNOME session.

## Power path

`AC adapter udev event -> ff-power-apply.service -> fpm.power_apply -> sysfs / powerprofilesctl / iw`

There is no long-running power polling daemon. The service is a short `oneshot`.

## Presence path

`Intel ISH 8087:0AC2 -> hidraw Report 4 -> ff-presence-sensor.service -> /run/ff-power-manager/presence.state -> Gio file monitor -> ff-presence-session.service -> Mutter PowerSaveMode`

The root sensor process blocks in `select(2)` waiting for HID reports. It does not poll the sensor. The per-user GNOME process uses `GFileMonitor` and therefore also does not poll.

The validated sensor feature report contains the ST `VL53L1_HOD` / `ST_MICRO` signature. FPM only changes two standard HID Sensor feature fields while active:

- Reporting state: `NO_EVENTS -> ALL_EVENTS`
- Power state: `D4_POWER_OFF -> D0_FULL_POWER`

The original feature report is restored on normal shutdown. `ExecStopPost` also performs a best-effort D4/NO_EVENTS restore.

## Why presence uses report activity

On the tested Lenovo 83JK firmware, Report 4 traffic is emitted while the firmware considers a person present, stops several seconds after departure, and resumes on approach. Because the vendor-specific payload is not documented, production logic uses report activity rather than guessing a private data byte.
