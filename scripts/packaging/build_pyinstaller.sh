#!/usr/bin/env bash
set -eu

python -m pip install --upgrade pip
python -m pip install pyinstaller

python -m PyInstaller \
  --noconfirm \
  --clean \
  scripts/packaging/rka_desktop.spec

cp .env.example dist/RKA3000Desktop/.env.example
