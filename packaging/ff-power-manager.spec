Name:           ff-power-manager
Version:        2.2.0
Release:        1%{?dist}
Summary:        Universal Linux Power, Adaptive Refresh, Wakeup Blame & Telemetry Suite

License:        MIT
URL:            https://github.com/lwrlock/ff-power-manager
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  gcc, binutils, make, python3-devel
Requires:       python3, python3-gobject, gtk4, libadwaita, power-profiles-daemon, iw, polkit

%description
Hybrid C/x86_64 Assembly + Python/GTK4 laptop power manager featuring universal
Intel/AMD CPU/GPU auto-discovery, battery-only Adaptive Refresh Rate (Mutter,
Hyprland, Plasma), ffctl doctor residency audit, ffctl blame wakeup profiler,
s2idle drain tracker, and ST VL53L1 HID presence radar.

%prep
%setup -q

%build
make build

%install
rm -rf %{buildroot}
install -d -m755 \
    %{buildroot}%{_prefix}/local/bin \
    %{buildroot}%{_prefix}/local/lib/ff-power-manager/fpm \
    %{buildroot}%{_sysconfdir}/systemd/system \
    %{buildroot}%{_prefix}/local/lib/systemd/user \
    %{buildroot}/usr/lib/systemd/system-sleep \
    %{buildroot}%{_sysconfdir}/udev/rules.d \
    %{buildroot}%{_datadir}/polkit-1/actions \
    %{buildroot}%{_sysconfdir}/polkit-1/rules.d \
    %{buildroot}%{_datadir}/applications \
    %{buildroot}%{_datadir}/icons/hicolor/scalable/apps \
    %{buildroot}%{_datadir}/ff-power-manager/gnome-extension \
    %{buildroot}/var/lib/ff-power-manager

install -m755 ffctl %{buildroot}%{_prefix}/local/bin/ffctl
install -m755 ff-tui %{buildroot}%{_prefix}/local/bin/ff-tui
install -m755 ff-presence-sensor %{buildroot}%{_prefix}/local/bin/ff-presence-sensor
install -m644 src/fpm/*.py %{buildroot}%{_prefix}/local/lib/ff-power-manager/fpm/
install -m644 systemd/ff-power-apply.service %{buildroot}%{_sysconfdir}/systemd/system/
install -m644 systemd/ff-power-autoboost.service %{buildroot}%{_sysconfdir}/systemd/system/
install -m644 systemd/ff-presence-sensor.service %{buildroot}%{_sysconfdir}/systemd/system/
install -m644 systemd/ff-presence-session.service %{buildroot}%{_prefix}/local/lib/systemd/user/
install -m755 sleep-hook/ff-sleep-guard %{buildroot}/usr/lib/systemd/system-sleep/ff-sleep-guard
install -m644 udev/90-ff-power-manager.rules %{buildroot}%{_sysconfdir}/udev/rules.d/
install -m644 polkit/com.ff.powermanager.policy %{buildroot}%{_datadir}/polkit-1/actions/
install -m644 polkit/50-ff-power-manager.rules %{buildroot}%{_sysconfdir}/polkit-1/rules.d/
install -m644 applications/com.ff.PowerManager.desktop %{buildroot}%{_datadir}/applications/
install -m644 applications/com.ff.PowerManager.TUI.desktop %{buildroot}%{_datadir}/applications/
install -m644 applications/ff-power-manager.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/ff-power-manager.svg
cp -a gnome-extension/ff-power-indicator@furkan.github.io/* %{buildroot}%{_datadir}/ff-power-manager/gnome-extension/

cat > %{buildroot}%{_prefix}/local/lib/ff-power-manager/ff-power-helper <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.helper "$@"
EOF
chmod 755 %{buildroot}%{_prefix}/local/lib/ff-power-manager/ff-power-helper

cat > %{buildroot}%{_prefix}/local/bin/ff-power-manager <<'EOF'
#!/bin/sh
export PYTHONPATH=/usr/local/lib/ff-power-manager
exec /usr/bin/python3 -m fpm.gui "$@"
EOF
chmod 755 %{buildroot}%{_prefix}/local/bin/ff-power-manager

%files
%license LICENSE
%doc README.md
%{_prefix}/local/bin/*
%{_prefix}/local/lib/ff-power-manager/*
%{_prefix}/local/lib/systemd/user/*
%{_sysconfdir}/systemd/system/*
/usr/lib/systemd/system-sleep/ff-sleep-guard
%{_sysconfdir}/udev/rules.d/*
%{_datadir}/polkit-1/actions/*
%{_sysconfdir}/polkit-1/rules.d/*
%{_datadir}/applications/*
%{_datadir}/icons/hicolor/scalable/apps/ff-power-manager.svg
%{_datadir}/ff-power-manager/gnome-extension/*
%dir /var/lib/ff-power-manager

%post
systemctl daemon-reload >/dev/null 2>&1 || :
udevadm control --reload-rules >/dev/null 2>&1 || :
systemctl enable --now ff-power-apply.service ff-power-autoboost.service >/dev/null 2>&1 || :

%preun
if [ $1 -eq 0 ]; then
    systemctl disable --now ff-power-apply.service ff-power-autoboost.service ff-presence-sensor.service >/dev/null 2>&1 || :
fi

%changelog
* Wed Nov 18 2026 Furkan <lwrlock@users.noreply.github.com> - 2.2.0-1
- Add cosmic space GTK4 GUI, live telemetry chart, ffctl blame, ffctl sleep-report, Multi-DE ARR, and focus throttling
