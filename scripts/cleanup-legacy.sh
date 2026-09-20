#!/usr/bin/env bash
set -euo pipefail

APPLY=0
PURGE_CONFIG=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --purge-config) PURGE_CONFIG=1 ;;
    -h|--help)
      echo "Usage: $0 [--apply] [--purge-config]"
      echo "Without --apply this is a dry run."
      exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
run() {
  if (( APPLY )); then
    "$@"
  else
    printf '[dry-run]'; printf ' %q' "$@"; printf '\n'
  fi
}

say '== Legacy FF Power Manager cleanup =='

# User services from older builds.
for unit in fpm-presence.service fpm-power-manager-presence.service; do
  run systemctl --user disable --now "$unit" >/dev/null 2>&1 || true
done

# System services from older builds.
for unit in fpm-sensor.service fpm-power-apply.service fpm-power.service; do
  run sudo systemctl disable --now "$unit" >/dev/null 2>&1 || true
done

# Explicit old paths to clean up.
OLD_PATHS=(
  /usr/local/lib/fpm
  /usr/local/bin/auto_power.sh
  /usr/local/lib/systemd/user/fpm-presence.service
  /etc/systemd/system/fpm-sensor.service
  /etc/systemd/system/fpm-power-apply.service
  /etc/systemd/system/fpm-power.service
  /etc/udev/rules.d/90-fpm-power.rules
  /run/fpm
)
for path in "${OLD_PATHS[@]}"; do
  if [[ -e "$path" || -L "$path" ]]; then
    run sudo rm -rf -- "$path"
  fi
done

run sudo systemctl daemon-reload
run systemctl --user daemon-reload
run sudo udevadm control --reload-rules

if (( APPLY )); then
  say 'Legacy cleanup complete.'
else
  say 'Dry run only. Re-run with --apply to make these changes.'
fi
