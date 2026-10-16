#!/usr/bin/env bash
# Auto Deal Searcher - first-run setup for macOS / Linux.
#
#   ./scripts/setup.sh            interactive setup
#   ./scripts/setup.sh --check    just verify what is in place
#
# Safe to re-run: every step is skipped when it is already done.
# Everything that needs quoting lives in scripts/_setup_helper.py.

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
say()  { printf "${BLUE}==>${NC} %s\n" "$1"; }
ok()   { printf "${GREEN}  ok${NC}  %s\n" "$1"; }
warn() { printf "${YELLOW}  !!${NC}  %s\n" "$1"; }
die()  { printf "${RED}  xx${NC}  %s\n" "$1"; exit 1; }

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for candidate in python3 python py; do
    if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
  done
fi
[ -n "$PY" ] || die "Python not found. Install Python 3.11-3.13, or set PYTHON=/path/to/python."

HELPER="scripts/_setup_helper.py"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

echo
echo "Auto Deal Searcher - setup"
echo "==========================="

say "Python"
"$PY" "$HELPER" python-version || die "cannot run Python"

VENV=".venv"
if [ "$CHECK_ONLY" -eq 0 ]; then
  if [ -f "$VENV/bin/activate" ]; then
    ok "virtualenv already present"
  else
    say "Creating virtualenv"
    "$PY" -m venv "$VENV" && ok "created .venv" || warn "venv failed; using the current interpreter"
  fi
  [ -f "$VENV/bin/activate" ] && . "$VENV/bin/activate"

  say "Installing dependencies"
  "$PY" -m pip install --upgrade pip >/dev/null 2>&1
  "$PY" -m pip install -r requirements.txt || die "pip install failed"
  ok "requirements installed"

  say "Installing Playwright browsers"
  "$PY" -m playwright install chromium >/dev/null 2>&1 \
    && ok "chromium installed" || warn "playwright install failed; run it manually"
fi

if [ ! -f config.yaml ]; then
  cp config.example.yaml config.yaml && ok "config.yaml created from the example"
else
  ok "config.yaml already present"
fi
if [ ! -f .env ]; then
  cp .env.example .env && ok ".env created - add your API keys inside it"
else
  ok ".env already present"
fi

if [ "$CHECK_ONLY" -eq 0 ]; then
  say "Browsers"
  "$PY" "$HELPER" list-browsers
  printf "\n  Which one? (id such as brave/chrome/msedge, Enter for auto-detect): "
  read -r bchoice || bchoice=""
  if [ -n "$bchoice" ]; then "$PY" "$HELPER" set-browser "$bchoice"; else ok "left on auto-detect"; fi
fi

say "Verifying"
"$PY" -m src.cli config-check || warn "config-check reported a problem"
"$PY" "$HELPER" login-status
"$PY" "$HELPER" doctor-hint

echo
ok "setup finished"
echo
echo "  Next:"
echo "    . scripts/$VENV/bin/activate"
echo "    python scripts/login.py --all     # log in to sites that need it"
echo "    python -m src.cli doctor          # check the sites work"
echo "    python -m src.cli run --prompt \"dji drone under 350\""
echo