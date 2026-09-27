#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

step() { printf '\n[%s] %s\n' "$1" "$2"; }

step '1/10' 'System Dependencies & Toolchains (C/ASM compilers, Python, GTK4)'
sudo dnf install -y gcc make python3-gobject gtk4 libadwaita iw power-profiles-daemon polkit intel-media-driver libva-utils

step '2/10' 'Cleaning Legacy Components'
./scripts/cleanup-legacy.sh --apply

step '3/10' 'Directories & System Permissions'
sudo install -d -m755 \
  /usr/local/lib/ff-power-manager/fpm \
  /usr/local/bin /usr/local/sbin \
  /usr/local/share/applications /usr/local/share/metainfo \
  /usr/local/lib/systemd/user /etc/systemd/system /etc/udev/rules.d \
  /usr/share/polkit-1/actions /etc/polkit-1/rules.d \
  /usr/share/gnome-shell/extensions

# Secure wheel group access to /etc/ff-power-manager
sudo install -d -m2775 -g wheel /etc/ff-power-manager

step '4/10' 'Building & Installing C & x86_64 Assembly Engine'
make build

# High performance native binaries (ffctl with setuid root for zero-latency sysfs writes)
sudo install -m755 ff-presence-sensor /usr/local/bin/ff-presence-sensor
sudo install -m4755 ffctl /usr/local/bin/ffctl
sudo install -m755 ff-tui /usr/local/bin/ff-tui
sudo ln -sf /usr/local/bin/ffctl /usr/local/sbin/fpmctl

# Python libraries and daemons
sudo install -m644 src/fpm/*.py /usr/local/lib/ff-power-manager/fpm/

# Privileged helper (for Polkit integration)
cat <<'HELPER_SH' | sudo tee /usr/local/lib/ff-power-manager/ff-power-helper >/dev/null
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.helper "$@"
HELPER_SH
sudo chmod 755 /usr/local/lib/ff-power-manager/ff-power-helper

# GUI launcher (ff-power-manager)
cat <<'GUI_SH' | sudo tee /usr/local/bin/ff-power-manager >/dev/null
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.gui "$@"
GUI_SH
sudo chmod 755 /usr/local/bin/ff-power-manager

step '5/10' 'Privilege Policies (Polkit & Sudoers)'
sudo install -m644 polkit/com.ff.powermanager.policy /usr/share/polkit-1/actions/
sudo install -m644 polkit/50-ff-power-manager.rules /etc/polkit-1/rules.d/

# Wheel group passwordless execution rule for hardware managers
cat <<'SUDOERS' | sudo tee /etc/sudoers.d/50-ff-power-manager >/dev/null
%wheel ALL=(ALL) NOPASSWD: /usr/local/lib/ff-power-manager/ff-power-helper, /usr/local/bin/ffctl, /usr/local/bin/ff-presence-sensor
SUDOERS
sudo chmod 440 /etc/sudoers.d/50-ff-power-manager

step '6/10' 'Writing Default Hardware Configurations'
cat <<'JSON' | sudo tee /etc/ff-power-manager/config.json >/dev/null
{
  "battery": {
    "gnome_profile": "balanced",
    "epp": "balance_performance",
    "turbo": true,
    "wifi_power_save": true,
    "nvme_runtime_pm": "auto",
    "gpu_runtime_pm": "auto",
    "pcie_aspm": "powersupersave",
    "usb_autosuspend": "auto",
    "audio_powersave": "on",
    "hwp_dynamic_boost": "off"
  },
  "ac": {
    "gnome_profile": "balanced",
    "epp": "balance_performance",
    "turbo": true,
    "wifi_power_save": false,
    "nvme_runtime_pm": "auto",
    "gpu_runtime_pm": "system",
    "pcie_aspm": "system",
    "usb_autosuspend": "system",
    "audio_powersave": "on",
    "hwp_dynamic_boost": "system"
  }
}
JSON

# Sensor default thresholds (1.2m desk distance, 30s silence window)
cat <<'JSON' | sudo tee /etc/ff-power-manager/sensor.json >/dev/null
{
  "silence_timeout": 30.0,
  "present_confirm_reports": 1,
  "present_confirm_window": 6.0,
  "distance_threshold": 12
}
JSON

sudo chown -R root:wheel /etc/ff-power-manager
sudo chmod 664 /etc/ff-power-manager/*.json 2>/dev/null || true

step '7/10' 'System Services, Udev Rules, Kernel Tuning & GNOME Extension'
sudo install -m644 systemd/ff-power-apply.service /etc/systemd/system/
sudo install -m644 systemd/ff-presence-sensor.service /etc/systemd/system/
sudo install -m644 systemd/ff-power-autoboost.service /etc/systemd/system/
sudo install -m644 systemd/ff-presence-session.service /usr/local/lib/systemd/user/
sudo install -m644 udev/90-ff-power-manager.rules /etc/udev/rules.d/
sudo install -m644 applications/com.ff.PowerManager.desktop /usr/local/share/applications/
sudo install -m644 applications/com.ff.PowerManager.TUI.desktop /usr/local/share/applications/
sudo install -m644 applications/com.ff.PowerManager.metainfo.xml /usr/local/share/metainfo/
sudo update-desktop-database /usr/local/share/applications/ 2>/dev/null || true

# Install GNOME Top Bar Quick Power Indicator Extension
sudo install -d -m755 /usr/share/gnome-shell/extensions/ff-power-indicator@furkan.github.io
sudo cp -r gnome-extension/ff-power-indicator@furkan.github.io/* /usr/share/gnome-shell/extensions/ff-power-indicator@furkan.github.io/

# Also install to user's local extensions directory
ACTUAL_USER="${SUDO_USER:-}"
if [[ -z "$ACTUAL_USER" || "$ACTUAL_USER" == "root" || "$ACTUAL_USER" == "nobody" ]]; then
  ACTUAL_USER="$(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $3}' | grep -v 'root\|nobody' | head -n1 || true)"
fi
if [[ -z "$ACTUAL_USER" ]]; then
  ACTUAL_USER="${USER:-furkan}"
fi

USER_HOME="$(getent passwd "$ACTUAL_USER" | cut -d: -f6 || echo "/home/$ACTUAL_USER")"
if [[ -d "$USER_HOME" ]]; then
  USER_EXT_DIR="$USER_HOME/.local/share/gnome-shell/extensions/ff-power-indicator@furkan.github.io"
  mkdir -p "$USER_EXT_DIR"
  cp -r gnome-extension/ff-power-indicator@furkan.github.io/* "$USER_EXT_DIR/"
  chown -R "$ACTUAL_USER":"$ACTUAL_USER" "$USER_EXT_DIR"
fi

# 1. PCIe Runtime Power Management
cat <<'EOF' | sudo tee /etc/udev/rules.d/98-pci-pm.rules >/dev/null
# Auto runtime power management for all PCI devices
ACTION=="add", SUBSYSTEM=="pci", ATTR{power/control}="auto"
EOF

# 2. Intel Wi-Fi 7 Power Management & U-APSD
cat <<'EOF' | sudo tee /etc/modprobe.d/iwlwifi.conf >/dev/null
# Intel Wi-Fi 7 power save & U-APSD
options iwlwifi power_save=1 uapsd_disable=0
EOF

# 3. NVMe APST Deep Sleep (PS4)
cat <<'EOF' | sudo tee /etc/modprobe.d/nvme.conf >/dev/null
# NVMe Autonomous Power State Transition (APST)
options nvme_core default_ps_max_latency_us=5500
EOF

# 4. ZRAM Modern zstd Compression
cat <<'EOF' | sudo tee /etc/systemd/zram-generator.conf >/dev/null
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
EOF

# 5. Kernel TCP BBR & Desktop Caching Tuning
cat <<'EOF' | sudo tee /etc/sysctl.d/99-ff-system-tuning.conf >/dev/null
# High performance networking and snappy desktop caching
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
vm.vfs_cache_pressure = 50
vm.max_map_count = 2147483642
fs.file-max = 2097152
EOF
sudo sysctl --system >/dev/null 2>&1 || true

# 6. Hardware Video Acceleration (VA-API Intel iHD Driver)
if ! grep -q "LIBVA_DRIVER_NAME=iHD" /etc/environment 2>/dev/null; then
    echo "LIBVA_DRIVER_NAME=iHD" | sudo tee -a /etc/environment >/dev/null
fi

step '8/10' 'Running Automated Native and Python Test Suite'
./test_native
PYTHONPATH=src python3 -m unittest discover -s tests -v
echo 'All native C, assembly, and Python unit tests: PASSED'

step '9/10' 'Enabling and Starting Background Services'
sudo systemctl daemon-reload
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw 2>/dev/null || true

# System services on boot
sudo systemctl enable --now ff-power-apply.service >/dev/null
sudo systemctl enable --now ff-presence-sensor.service >/dev/null
sudo systemctl restart ff-presence-sensor.service >/dev/null 2>&1 || true
sudo systemctl enable --now ff-power-autoboost.service >/dev/null

# User session presence service
if id "$ACTUAL_USER" >/dev/null 2>&1; then
  USER_UID="$(id -u "$ACTUAL_USER")"
  sudo -u "$ACTUAL_USER" XDG_RUNTIME_DIR="/run/user/${USER_UID}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" systemctl --user daemon-reload 2>/dev/null || true
  sudo -u "$ACTUAL_USER" XDG_RUNTIME_DIR="/run/user/${USER_UID}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" systemctl --user enable --now ff-presence-session.service 2>/dev/null || true
  sudo -u "$ACTUAL_USER" XDG_RUNTIME_DIR="/run/user/${USER_UID}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" systemctl --user restart ff-presence-session.service 2>/dev/null || true
fi

# Apply active hardware power profile immediately
/usr/local/bin/ffctl apply

step '10/10' 'Complete'
echo '==================================================================='
echo '  FF Power Manager (v1.2.0 - Native C & Assembly) Installed!      '
echo '==================================================================='
echo '  ✓ Terminal Dashboard      : ff-tui  (or ffctl tui)'
echo '  ✓ Hardware Power Status   : ffctl status'
echo '  ✓ Battery Health Report   : ffctl health'
echo '  ✓ Lenovo IdeaPad Control  : ffctl lenovo'
echo '  ✓ Live ToF Radar Stream   : ffctl sensor live'
echo '  ✓ GTK4 / Libadwaita GUI   : ff-power-manager'
echo '  ✓ Auto Dynamic Boost      : Enabled (GameMode & Compiler Detection)'
echo '  ✓ GNOME Top Bar Widget    : Installed in GNOME Shell'
echo '  ✓ Uninstaller             : ./uninstall.sh'
echo '==================================================================='
