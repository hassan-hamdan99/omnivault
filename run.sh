#!/usr/bin/env bash
# Omnivault — launcher para Linux/macOS (no Windows usa start.bat)
set -e
cd "$(dirname "$0")/backend"

PY="${PYTHON:-python3}"

echo "Omnivault — a verificar dependências..."
"$PY" -m pip install -r requirements.txt -q

PORT="${PORT:-8000}"
echo "Servidor em http://localhost:${PORT}"
exec "$PY" main.py
