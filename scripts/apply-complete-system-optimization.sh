#!/usr/bin/env bash
set -e

echo "=========================================================="
echo "  FF Power Manager - MacBook-Grade Hardware Optimization"
echo "  and GDM Login Screen Polish"
echo "=========================================================="

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: This operation requires root privileges."
    echo "Please run with 'sudo bash $0'."
    exit 1
fi

REAL_USER="${SUDO_USER:-furkan}"
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)
FPM_DIR="$REAL_HOME/ff-power-manager"

echo "[1/6] Building ff-power-manager native binaries and Python modules..."
cd "$FPM_DIR"
make build

# Install Python modules
install -d -m755 /usr/local/lib/ff-power-manager/fpm
install -m644 src/fpm/*.py /usr/local/lib/ff-power-manager/fpm/

# Install native binaries
install -m755 ff-presence-sensor /usr/local/bin/ff-presence-sensor
install -m4755 ffctl /usr/local/bin/ffctl
install -m755 ff-tui /usr/local/bin/ff-tui

# Update configuration with stutter-free battery tuning
cat <<'JSON' > /etc/ff-power-manager/config.json
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
chown -R root:wheel /etc/ff-power-manager
chmod 664 /etc/ff-power-manager/*.json 2>/dev/null || true

echo "[2/6] Applying hardware power saving and performance rules (PCIe, Wi-Fi 7, NVMe, ZRAM, TCP BBR)..."

# 1. PCIe Runtime Power Management (D3hot/cold sleep for idle PCI devices)
cat <<'EOF' > /etc/udev/rules.d/98-pci-pm.rules
# Auto runtime power management for all PCI devices
ACTION=="add", SUBSYSTEM=="pci", ATTR{power/control}="auto"
EOF

# 2. Intel Wi-Fi 7 Power Management # 2. Intel Wi-Fi 7 Güç Yönetimi ve U-APSD U-APSD
cat <<'EOF' > /etc/modprobe.d/iwlwifi.conf
# Intel Wi-Fi 7 power save & U-APSD
options iwlwifi power_save=1 uapsd_disable=0
EOF

# 3. NVMe APST Deep Sleep (PS4) Support
cat <<'EOF' > /etc/modprobe.d/nvme.conf
# NVMe Autonomous Power State Transition (APST)
options nvme_core default_ps_max_latency_us=5500
EOF

# Write current NVMe APST latency immediately
if [ -f /sys/module/nvme_core/parameters/default_ps_max_latency_us ]; then
    echo 5500 > /sys/module/nvme_core/parameters/default_ps_max_latency_us 2>/dev/null || true
fi

# 4. ZRAM Modern zstd Compression
cat <<'EOF' > /etc/systemd/zram-generator.conf
[zram0]
zram-size = ram / 2
compression-algorithm = zstd
EOF

# 5. Kernel TCP BBR # 5. Çekirdek TCP BBR ve VFS Önbellek İyileştirmesi VFS Cache Optimization
cat <<'EOF' > /etc/sysctl.d/99-ff-system-tuning.conf
# High performance networking and snappy desktop caching
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
vm.vfs_cache_pressure = 50
vm.max_map_count = 2147483642
fs.file-max = 2097152
EOF
sysctl --system >/dev/null 2>&1 || true

# 6. Hardware Video Acceleration (VA-API Intel iHD Driver)
if ! grep -q "LIBVA_DRIVER_NAME=iHD" /etc/environment 2>/dev/null; then
    echo "LIBVA_DRIVER_NAME=iHD" >> /etc/environment
fi

# Reload udev rules and trigger PCI power states
udevadm control --reload-rules
for pci in /sys/bus/pci/devices/*/power/control; do
    echo auto > "$pci" 2>/dev/null || true
done

echo "[3/6] Applying Intel Arc GPU frequency limits to prevent stutter..."
for card in /sys/class/drm/card*; do
    if [ -f "$card/gt_min_freq_mhz" ]; then
        rp1=$(cat "$card/gt_RP1_freq_mhz" 2>/dev/null || echo "500")
        echo "$rp1" > "$card/gt_min_freq_mhz" 2>/dev/null || true
    fi
    if [ -f "$card/gt/gt0/rps_boost_freq_mhz" ]; then
        echo 2350 > "$card/gt/gt0/rps_boost_freq_mhz" 2>/dev/null || true
    fi
    if [ -f "$card/gt_max_freq_mhz" ]; then
        echo 2350 > "$card/gt_max_freq_mhz" 2>/dev/null || true
    fi
done

echo "[4/6] Polishing GDM login screen with user wallpaper..."
WALLPAPER="$REAL_HOME/.config/background"
if [ -f "$WALLPAPER" ]; then
    GDM_WORK="/tmp/gdm-theme-build"
    rm -rf "$GDM_WORK"
    mkdir -p "$GDM_WORK"
    cd "$GDM_WORK"

    # Extract original theme
    gresource list /usr/share/gnome-shell/gnome-shell-theme.gresource | while read -r r; do
        fn="${r#/org/gnome/shell/theme/}"
        mkdir -p "$(dirname "$fn")"
        gresource extract /usr/share/gnome-shell/gnome-shell-theme.gresource "$r" > "$fn"
    done

    # Copy wallpaper
    cp "$WALLPAPER" gdm-wallpaper.jpg

    # Generate XML
    cat <<'XML' > gnome-shell-theme.gresource.xml
<?xml version="1.0" encoding="UTF-8"?>
<gresources>
  <gresource prefix="/org/gnome/shell/theme">
    <file>calendar-today-light.svg</file>
    <file>calendar-today.svg</file>
    <file>gnome-shell-dark.css</file>
    <file>gnome-shell-high-contrast.css</file>
    <file>gnome-shell-light.css</file>
    <file>gnome-shell-start.svg</file>
    <file>pad-osd.css</file>
    <file>workspace-placeholder.svg</file>
    <file>gdm-wallpaper.jpg</file>
  </gresource>
</gresources>
XML

    # Update CSS rules for lock screen background
    sed -i "s|#lockDialogGroup {|#lockDialogGroup {\n  background: #222226 url('resource:///org/gnome/shell/theme/gdm-wallpaper.jpg');\n  background-repeat: no-repeat;\n  background-size: cover;\n  background-position: center;|g" gnome-shell-dark.css gnome-shell-light.css

    # Yeni gresource'u derle
    glib-compile-resources gnome-shell-theme.gresource.xml --target=gnome-shell-theme-new.gresource

    # Backup and apply
    if [ ! -f /usr/share/gnome-shell/gnome-shell-theme.gresource.orig ]; then
        cp /usr/share/gnome-shell/gnome-shell-theme.gresource /usr/share/gnome-shell/gnome-shell-theme.gresource.orig
    fi
    cp gnome-shell-theme-new.gresource /usr/share/gnome-shell/gnome-shell-theme.gresource
    chmod 644 /usr/share/gnome-shell/gnome-shell-theme.gresource
    rm -rf "$GDM_WORK"
    echo "✓ GDM theme applied successfully."
fi

# GDM Wayland configuration
sed -i 's/^#WaylandEnable=false/WaylandEnable=true/' /etc/gdm/custom.conf
if ! grep -q "WaylandEnable" /etc/gdm/custom.conf; then
    sed -i '/\[daemon\]/a WaylandEnable=true' /etc/gdm/custom.conf
fi

echo "[5/6] Reloading systemd and restarting services..."
systemctl daemon-reload
systemctl restart ff-presence-sensor.service 2>/dev/null || true

echo "[6/6] Applying active power profile to hardware sysfs registers..."
/usr/local/bin/ffctl apply

echo "=========================================================="
echo "  All system optimizations completed successfully!"
echo "=========================================================="
