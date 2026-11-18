#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VER="2.0.0"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
PKG="ff-power-manager_${VER}_${ARCH}"
STAGE="$ROOT/.stage/$PKG"

make build

rm -rf "$STAGE" "$ROOT/dist"
mkdir -p "$ROOT/dist"
mkdir -p "$STAGE/DEBIAN"
mkdir -p "$STAGE/usr/local/bin"
mkdir -p "$STAGE/usr/local/lib/ff-power-manager/fpm"
mkdir -p "$STAGE/usr/local/lib/systemd/user"
mkdir -p "$STAGE/etc/systemd/system"
mkdir -p "$STAGE/lib/systemd/system-sleep"
mkdir -p "$STAGE/etc/udev/rules.d"
mkdir -p "$STAGE/usr/share/polkit-1/actions"
mkdir -p "$STAGE/etc/polkit-1/rules.d"
mkdir -p "$STAGE/usr/local/share/applications"
mkdir -p "$STAGE/usr/share/ff-power-manager/gnome-extension"

install -m4755 "$ROOT/ffctl" "$STAGE/usr/local/bin/ffctl"
install -m755 "$ROOT/ff-tui" "$STAGE/usr/local/bin/ff-tui"
install -m755 "$ROOT/ff-presence-sensor" "$STAGE/usr/local/bin/ff-presence-sensor"
install -m644 "$ROOT"/src/fpm/*.py "$STAGE/usr/local/lib/ff-power-manager/fpm/"

cat > "$STAGE/usr/local/lib/ff-power-manager/ff-power-helper" <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.helper "$@"
EOF
chmod 755 "$STAGE/usr/local/lib/ff-power-manager/ff-power-helper"

cat > "$STAGE/usr/local/bin/ff-power-manager" <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.gui "$@"
EOF
chmod 755 "$STAGE/usr/local/bin/ff-power-manager"

install -m644 "$ROOT"/systemd/ff-power-apply.service "$STAGE/etc/systemd/system/"
install -m644 "$ROOT"/systemd/ff-power-autoboost.service "$STAGE/etc/systemd/system/"
install -m644 "$ROOT"/systemd/ff-presence-sensor.service "$STAGE/etc/systemd/system/"
install -m644 "$ROOT"/systemd/ff-presence-session.service "$STAGE/usr/local/lib/systemd/user/"
install -m755 "$ROOT/sleep-hook/ff-sleep-guard" "$STAGE/lib/systemd/system-sleep/ff-sleep-guard"
install -m644 "$ROOT/udev/90-ff-power-manager.rules" "$STAGE/etc/udev/rules.d/"
install -m644 "$ROOT/polkit/com.ff.powermanager.policy" "$STAGE/usr/share/polkit-1/actions/"
install -m644 "$ROOT/polkit/50-ff-power-manager.rules" "$STAGE/etc/polkit-1/rules.d/"
install -m644 "$ROOT/applications/com.ff.PowerManager.desktop" "$STAGE/usr/local/share/applications/"
install -m644 "$ROOT/applications/com.ff.PowerManager.TUI.desktop" "$STAGE/usr/local/share/applications/"
cp -a "$ROOT"/gnome-extension/ff-power-indicator@furkan.github.io/* "$STAGE/usr/share/ff-power-manager/gnome-extension/"

cat > "$STAGE/DEBIAN/control" <<EOF
Package: ff-power-manager
Version: $VER
Section: utils
Priority: optional
Architecture: $ARCH
Depends: python3, python3-gi, gir1.2-glib-2.0, power-profiles-daemon, iw
Maintainer: Furkan <lwrlock@users.noreply.github.com>
Homepage: https://github.com/lwrlock/ff-power-manager
Description: MacBook ProMotion, OLED Guard & Intelligent Laptop Power for Linux
 Hybrid C/x86_64 Assembly + Python/GTK4 laptop power optimizer featuring
 universal CPU/GPU/battery auto-discovery, battery-only Mutter ProMotion
 (60<->120Hz at 0ms wake), ToF human presence radar, Cinema/Focus context
 automation, One-Shot 100% charge watchdog, Thermal Guardrail, and s2idle
 backpack drain protection.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
systemctl daemon-reload || true
udevadm control --reload-rules 2>/dev/null || true
systemctl enable --now ff-power-apply.service ff-power-autoboost.service 2>/dev/null || true
if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    USER_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6 || echo "/home/$SUDO_USER")"
    EXT_DST="$USER_HOME/.local/share/gnome-shell/extensions/ff-power-indicator@furkan.github.io"
    mkdir -p "$EXT_DST"
    cp -a /usr/share/ff-power-manager/gnome-extension/* "$EXT_DST/"
    chown -R "$SUDO_USER:$SUDO_USER" "$EXT_DST"
fi
exit 0
EOF
chmod 755 "$STAGE/DEBIAN/postinst"

dpkg-deb --build --root-owner-group "$STAGE" "$ROOT/dist/${PKG}.deb"
rm -rf "$ROOT/.stage"
echo "Built: $ROOT/dist/${PKG}.deb"
dpkg-deb -I "$ROOT/dist/${PKG}.deb"
