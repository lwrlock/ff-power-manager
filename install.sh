#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PRESENCE_WAS_ENABLED=0
if systemctl --user is-enabled --quiet ff-presence-session.service 2>/dev/null && \
   systemctl is-enabled --quiet ff-presence-sensor.service 2>/dev/null; then
  PRESENCE_WAS_ENABLED=1
fi

step() { printf '\n[%s] %s\n' "$1" "$2"; }

step '1/10' 'Bağımlılıklar'
sudo dnf install -y python3-gobject gtk4 libadwaita iw power-profiles-daemon polkit intel-media-driver libva-utils

step '2/10' 'Eski sürümleri temizleme'
./scripts/cleanup-legacy.sh --apply

step '3/10' 'Dizinler ve İzinler'
sudo install -d -m755 \
  /usr/local/lib/ff-power-manager/fpm \
  /usr/local/bin /usr/local/sbin \
  /usr/local/share/applications /usr/local/share/metainfo \
  /usr/local/lib/systemd/user /etc/systemd/system /etc/udev/rules.d \
  /usr/share/polkit-1/actions /etc/polkit-1/rules.d

# /etc/ff-power-manager dizinini root:wheel 2775 yaparak wheel grubundaki kullanıcılara güvenli erişim sağla
sudo install -d -m2775 -g wheel /etc/ff-power-manager

step '4/10' 'Program ve Yardımcı Dosyaları'
sudo install -m644 src/fpm/*.py /usr/local/lib/ff-power-manager/fpm/

# Privileged helper
cat <<'SH' | sudo tee /usr/local/lib/ff-power-manager/ff-power-helper >/dev/null
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.helper "$@"
SH
sudo chmod 755 /usr/local/lib/ff-power-manager/ff-power-helper

# CLI aracı (ffctl ve geriye uyumlu fpmctl)
cat <<'SH' | sudo tee /usr/local/bin/ffctl >/dev/null
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.cli "$@"
SH
sudo chmod 755 /usr/local/bin/ffctl
sudo ln -sf /usr/local/bin/ffctl /usr/local/sbin/fpmctl

# GUI başlatıcı (ff-power-manager)
cat <<'SH' | sudo tee /usr/local/bin/ff-power-manager >/dev/null
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.gui "$@"
SH
sudo chmod 755 /usr/local/bin/ff-power-manager

step '5/10' 'Polkit Yetkilendirme Kuralları'
sudo install -m644 polkit/com.ff.powermanager.policy /usr/share/polkit-1/actions/
sudo install -m644 polkit/50-ff-power-manager.rules /etc/polkit-1/rules.d/

step '6/10' 'Varsayılan Yapılandırma'
if [[ ! -f /etc/ff-power-manager/config.json ]]; then
  cat <<'JSON' | sudo tee /etc/ff-power-manager/config.json >/dev/null
{
  "battery": {
    "gnome_profile": "balanced",
    "epp": "balance_power",
    "turbo": true,
    "wifi_power_save": false,
    "nvme_runtime_pm": "auto",
    "gpu_runtime_pm": "system",
    "pcie_aspm": "powersupersave",
    "usb_autosuspend": "system",
    "audio_powersave": "on",
    "hwp_dynamic_boost": "system"
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
fi
if [[ ! -f /etc/ff-power-manager/sensor.json ]]; then
  echo '{"silence_timeout":4.0,"present_confirm_reports":2,"present_confirm_window":3.0}' | sudo tee /etc/ff-power-manager/sensor.json >/dev/null
fi
sudo chown -R root:wheel /etc/ff-power-manager
sudo chmod 664 /etc/ff-power-manager/*.json 2>/dev/null || true

step '7/10' 'systemd, udev ve Masaüstü Dosyaları'
sudo install -m644 systemd/ff-power-apply.service /etc/systemd/system/
sudo install -m644 systemd/ff-presence-sensor.service /etc/systemd/system/
sudo install -m644 systemd/ff-presence-session.service /usr/local/lib/systemd/user/
sudo install -m644 udev/90-ff-power-manager.rules /etc/udev/rules.d/
sudo install -m644 applications/com.ff.PowerManager.desktop /usr/local/share/applications/
sudo install -m644 applications/com.ff.PowerManager.metainfo.xml /usr/local/share/metainfo/

step '8/10' 'Kendi Kendini Sınama (Self-test)'
PYTHONPATH=src python3 -m py_compile src/fpm/*.py
sudo env PYTHONPATH=/usr/local/lib/ff-power-manager /usr/bin/python3 -m fpm.cli status >/dev/null
echo 'Python ve modül kontrolü: Başarılı'

step '9/10' 'Servisleri Yükleme ve Güç Profilini Uygulama'
sudo systemctl daemon-reload
systemctl --user daemon-reload 2>/dev/null || true
sudo udevadm control --reload-rules
sudo systemctl enable ff-power-apply.service >/dev/null
sudo systemctl enable --now ff-presence-sensor.service >/dev/null
systemctl --user enable --now ff-presence-session.service >/dev/null 2>&1 || true
sudo /usr/local/bin/ffctl apply

step '10/10' 'Tamamlandı'
echo 'FF Power Manager ve Lenovo ToF Presence servisi etkinleştirildi.'
echo 'Uygulama: ff-power-manager'
echo 'CLI kontrol: ffctl status'
echo 'Kaldırma: ./uninstall.sh'
