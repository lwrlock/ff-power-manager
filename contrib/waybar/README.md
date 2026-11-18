# Waybar Integration

Because `ffctl status --json`, `ffctl blame --json`, and `ffctl doctor --json` run in sub-2ms native C, Waybar can poll power draw, battery %, package temperature, and EPP state with zero noticeable overhead.

Copy the snippet from `ff-power-waybar.jsonc` into `~/.config/waybar/config.jsonc` and add `"custom/ff-power"` to `modules-right`.

- Left click opens **FF Power Manager** (`ff-power-manager` GTK4 UI)
- Right click re-applies the active hardware profile (`ffctl apply`)
