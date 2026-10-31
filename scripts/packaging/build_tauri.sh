#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$repo_root"

python_bin="${RKA_PYTHON:-$repo_root/.venv/bin/python}"
if ! "$python_bin" -m PyInstaller --version >/dev/null 2>&1; then
  echo "PyInstaller is required: $python_bin -m pip install pyinstaller" >&2
  exit 1
fi

"$python_bin" -m PyInstaller --noconfirm --clean --onefile \
  --name rka-backend --paths "$repo_root/src" \
  --distpath "$repo_root/frontend/sidecar-dist" \
  --workpath "$repo_root/build/tauri-backend" \
  --specpath "$repo_root/build/tauri-backend" \
  "$repo_root/src/rka_desktop/desktop_bridge.py"

cd "$repo_root/frontend"
npm ci
npm run check
npm run tauri -- build --config src-tauri/tauri.release.macos.conf.json --bundles app
