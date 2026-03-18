#!/usr/bin/env bash
set -eu

python -m pip install --upgrade pip
python -m pip install pyinstaller

pyinstaller \
  --name RKA3000Desktop \
  --windowed \
  --noconfirm \
  --paths src \
  src/rka_desktop/main.py

