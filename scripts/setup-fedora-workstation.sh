#!/usr/bin/env bash
# Fedora Workstation development setup for FF Power Manager.
# Run this after a clean Fedora GNOME install as your normal user.
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "Bu betigi sudo ile degil, normal kullanici olarak calistir."
  exit 1
fi

echo "[1/6] Fedora paketleri guncelleniyor..."
sudo dnf upgrade --refresh -y

echo "[2/6] Gelistirme ve FPM bagimliliklari kuruluyor..."
sudo dnf install -y \
  '@development-tools' \
  adw-gtk3-theme \
  gcc \
  git \
  glib2-devel \
  gnome-extensions-app \
  gnome-tweaks \
  gtk4 \
  libadwaita \
  make \
  python3-devel \
  python3-gobject \
  python3-pip \
  python3-pytest \
  python3-virtualenv \
  ripgrep \
  shellcheck

echo "[3/6] Visual Studio Code resmi Microsoft deposu ekleniyor..."
sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
sudo tee /etc/yum.repos.d/vscode.repo >/dev/null <<'REPO'
[code]
name=Visual Studio Code
baseurl=https://packages.microsoft.com/yumrepos/vscode
enabled=1
autorefresh=1
type=rpm-md
gpgcheck=1
gpgkey=https://packages.microsoft.com/keys/microsoft.asc
REPO
sudo dnf install -y code

echo "[4/6] Flathub, Spotify ve Extension Manager kuruluyor..."
flatpak remote-add --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install -y flathub com.spotify.Client com.mattjakeman.ExtensionManager

echo "[5/6] GNOME gorunumu ayarlaniyor..."
# Native libadwaita uygulamalari Fedora'nin Adwaita Dark gorunumunu kullanir.
# Bu ayar eski GTK3 uygulamalarini ayni gorunume yaklastirir.
gsettings set org.gnome.desktop.interface color-scheme 'prefer-dark'
gsettings set org.gnome.desktop.interface gtk-theme 'adw-gtk3-dark'

echo "[6/6] VS Code Python eklentileri kuruluyor..."
code --install-extension ms-python.python --force
code --install-extension ms-python.vscode-pylance --force
code --install-extension ms-python.debugpy --force
code --install-extension charliermarsh.ruff --force

cat <<'DONE'

Tamamlandi.

- GNOME Extensions uygulamasindan veya Extension Manager'dan sadece GNOME surumunle
  uyumlu eklentileri kur. Eklenti onerisi: AppIndicator, Clipboard Indicator,
  Dash to Dock. Birden fazla dock/panel eklentisini ayni anda kullanma.
- Bu proje icin once `make test`, sonra hazirsan `./install.sh` calistir.
- Projeyi GitHub'a yeni bir private repository olarak pushlamayi unutma.
DONE
