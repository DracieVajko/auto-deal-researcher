#!/usr/bin/env bash
# Prompt-only deal search - Linux/macOS launcher.
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "python3 not found. Install Python 3.11+ or run ./scripts/setup.sh first." >&2
    exit 1
fi

exec "$PY" -m src.cli ask
