#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .git ]]; then
  git init
fi
git add .
git status --short
cat <<'MSG'

Repository initialized and files staged.
Next:
  git commit -m "FF Power Manager"
  git branch -M main
  git remote add origin https://github.com/lwrlock/ff-power-manager.git
  git push -u origin main
MSG
