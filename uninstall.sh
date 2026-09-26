#!/usr/bin/env bash
set -euo pipefail

# Disable user services
systemctl --user disable --now ff-presence-session.service >/dev/null 2>&1 || true

# Disable system services
sudo systemctl disable --now ff-presence-sensor.service >/dev/null 2>&1 || true
sudo systemctl disable --now ff-power-apply.service >/dev/null 2>&1 || true

# Remove binaries and services
sudo rm -f \
  /etc/systemd/system/ff-power-apply.service \
  /etc/systemd/system/ff-presence-sensor.service \
  /usr/local/lib/systemd/user/ff-presence-session.service \
  /etc/udev/rules.d/90-ff-power-manager.rules \
  /usr/share/polkit-1/actions/com.ff.powermanager.policy \
  /etc/polkit-1/rules.d/50-ff-power-manager.rules \
  /etc/sudoers.d/50-ff-power-manager \
  /usr/local/bin/ff-power-manager \

  /usr/local/bin/ffctl \
  /usr/local/bin/ff-tui \
  /usr/local/bin/ff-presence-sensor \
  /usr/local/sbin/fpmctl \
  /usr/local/share/applications/com.ff.PowerManager.desktop \
  /usr/local/share/applications/com.ff.PowerManager.TUI.desktop \
  /usr/local/share/metainfo/com.ff.PowerManager.metainfo.xml

sudo rm -rf \
  /usr/local/lib/ff-power-manager \
  /run/ff-power-manager

if [[ "${1:-}" == "--purge-config" ]]; then
  sudo rm -rf /etc/ff-power-manager
  rm -rf "$HOME/.config/ff-power-manager"
fi

sudo systemctl daemon-reload
systemctl --user daemon-reload 2>/dev/null || true
sudo udevadm control --reload-rules

echo 'FF Power Manager sistemden kaldırıldı.'
