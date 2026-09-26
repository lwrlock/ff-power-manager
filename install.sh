#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

step() { printf '\n[%s] %s\n' "$1" "$2"; }

step '1/10' 'Bağımlılıklar (C/ASM derleyicileri ve sistem araçları)'
sudo dnf install -y gcc make python3-gobject gtk4 libadwaita iw power-profiles-daemon polkit intel-media-driver libva-utils

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

step '4/10' 'C & x86_64 Assembly Motorunu Derleme ve Kurma'
make build

# Native yüksek performanslı ikililer (ffctl setuid root yetkisiyle anında ve şifresiz donanıma yazar)
sudo install -m755 ff-presence-sensor /usr/local/bin/ff-presence-sensor
sudo install -m4755 ffctl /usr/local/bin/ffctl
sudo install -m755 ff-tui /usr/local/bin/ff-tui
sudo ln -sf /usr/local/bin/ffctl /usr/local/sbin/fpmctl

# Python kütüphaneleri ve yardımcı betikler
sudo install -m644 src/fpm/*.py /usr/local/lib/ff-power-manager/fpm/

# Privileged helper (Polkit entegrasyonu için)
cat <<'SH' | sudo tee /usr/local/lib/ff-power-manager/ff-power-helper >/dev/null
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.helper "$@"
SH
sudo chmod 755 /usr/local/lib/ff-power-manager/ff-power-helper

# GUI başlatıcı (ff-power-manager)
cat <<'SH' | sudo tee /usr/local/bin/ff-power-manager >/dev/null
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.gui "$@"
SH
sudo chmod 755 /usr/local/bin/ff-power-manager

step '5/10' 'Yetkilendirme Kuralları (Polkit ve Sudoers)'
sudo install -m644 polkit/com.ff.powermanager.policy /usr/share/polkit-1/actions/
sudo install -m644 polkit/50-ff-power-manager.rules /etc/polkit-1/rules.d/

# Wheel grubu için şifresiz donanım profili uygulama kuralı
cat <<'SUDOERS' | sudo tee /etc/sudoers.d/50-ff-power-manager >/dev/null
%wheel ALL=(ALL) NOPASSWD: /usr/local/lib/ff-power-manager/ff-power-helper, /usr/local/bin/ffctl, /usr/local/bin/ff-presence-sensor
SUDOERS
sudo chmod 440 /etc/sudoers.d/50-ff-power-manager

step '6/10' 'Varsayılan Yapılandırma'
cat <<'JSON' | sudo tee /etc/ff-power-manager/config.json >/dev/null
{
  "battery": {
    "gnome_profile": "balanced",
    "epp": "balance_power",
    "turbo": false,
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

# Sensör eşiklerini 1.2m normal masa mesafesi ve 30s sessizlik süresi olarak garantiye al
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


step '7/10' 'systemd, udev ve Masaüstü Dosyaları'
sudo install -m644 systemd/ff-power-apply.service /etc/systemd/system/
sudo install -m644 systemd/ff-presence-sensor.service /etc/systemd/system/
sudo install -m644 systemd/ff-presence-session.service /usr/local/lib/systemd/user/
sudo install -m644 udev/90-ff-power-manager.rules /etc/udev/rules.d/
sudo install -m644 applications/com.ff.PowerManager.desktop /usr/local/share/applications/
sudo install -m644 applications/com.ff.PowerManager.TUI.desktop /usr/local/share/applications/
sudo install -m644 applications/com.ff.PowerManager.metainfo.xml /usr/local/share/metainfo/
sudo update-desktop-database /usr/local/share/applications/ 2>/dev/null || true

step '8/10' 'Kendi Kendini Sınama (Test Suite)'
./test_native
PYTHONPATH=src python3 -m py_compile src/fpm/*.py
echo 'C & x86_64 Assembly ve Python kontrolleri: Başarılı'

step '9/10' 'Servisleri Yükleme ve Başlatma (Autostart on Boot)'
sudo systemctl daemon-reload
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw 2>/dev/null || true

# Boot sırasında otomatik başlayacak servisler
sudo systemctl enable --now ff-power-apply.service >/dev/null
sudo systemctl enable --now ff-presence-sensor.service >/dev/null
sudo systemctl restart ff-presence-sensor.service >/dev/null 2>&1 || true

# Kullanıcı oturumu açıldığında otomatik başlayacak servis
ACTUAL_USER="${SUDO_USER:-}"
if [[ -z "$ACTUAL_USER" || "$ACTUAL_USER" == "root" || "$ACTUAL_USER" == "nobody" ]]; then
  ACTUAL_USER="$(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $3}' | grep -v 'root\|nobody' | head -n1 || true)"
fi
if [[ -z "$ACTUAL_USER" ]]; then
  ACTUAL_USER="${USER:-furkan}"
fi

if id "$ACTUAL_USER" >/dev/null 2>&1; then
  USER_UID="$(id -u "$ACTUAL_USER")"
  sudo -u "$ACTUAL_USER" XDG_RUNTIME_DIR="/run/user/${USER_UID}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" systemctl --user daemon-reload 2>/dev/null || true
  sudo -u "$ACTUAL_USER" XDG_RUNTIME_DIR="/run/user/${USER_UID}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" systemctl --user enable --now ff-presence-session.service 2>/dev/null || true
  sudo -u "$ACTUAL_USER" XDG_RUNTIME_DIR="/run/user/${USER_UID}" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/${USER_UID}/bus" systemctl --user restart ff-presence-session.service 2>/dev/null || true
fi


# İlk güç profilini hemen uygula
/usr/local/bin/ffctl apply

step '10/10' 'Tamamlandı'
echo '==================================================================='
echo '  FF Power Manager (C & x86_64 Assembly Sürümü) Başarıyla Kuruldu! '
echo '==================================================================='
echo '  ✓ Canlı Terminal Arayüzü  : ff-tui  (veya ffctl tui)'
echo '  ✓ Hızlı Donanım Durumu     : ffctl status'
echo '  ✓ Canlı ToF Telemetrisi    : ffctl sensor live'
echo '  ✓ GTK4 / Libadwaita GUI    : ff-power-manager'
echo '  ✓ Otomatik Başlangıç       : Etkin (Bilgisayar açılışında devrede)'
echo '  ✓ Kaldırma                 : ./uninstall.sh'
echo '==================================================================='
