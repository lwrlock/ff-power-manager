#!/usr/bin/env bash
set -euo pipefail
systemctl --user disable --now ff-presence-session.service >/dev/null 2>&1 || true
sudo /usr/local/bin/ffctl safe-reset
