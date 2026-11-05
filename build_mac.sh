#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3.12}"
"$PYTHON" -m venv .venv-mac
source .venv-mac/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-desktop.txt
python -m PyInstaller --clean --noconfirm desktop.spec
echo "Ready: dist/COVERAGEDIAGRAMS.app"
echo "Unsigned / unnotarized developer build: macOS Gatekeeper may require manual approval."
