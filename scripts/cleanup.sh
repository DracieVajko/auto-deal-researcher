#!/usr/bin/env bash
# cleanup.sh - Cleanup script for Auto Deal Searcher (Linux/macOS)
# Removes debug files, cache, outputs, runs, and temporary files
#
# Usage:
#   ./scripts/cleanup.sh          # Standard cleanup (preserves config, data, sessions)
#   ./scripts/cleanup.sh --deep   # Deep clean (also removes database and sessions)

set -euo pipefail

# Colors
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

say()  { printf "${BLUE}==>${NC} %s\n" "$1"; }
ok()   { printf "${GREEN}  ok${NC}  %s\n" "$1"; }
warn() { printf "${YELLOW}  !!${NC} %s\n" "$1"; }
die()  { printf "${RED}  xx${NC}  %s\n" "$1"; exit 1; }

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

DEEP_CLEAN=0
if [[ "${1:-}" == "--deep" ]]; then
    DEEP_CLEAN=1
fi

say "Auto Deal Searcher - Cleanup"
echo "============================"
echo

# 1. Python cache files
say "[1/6] Cleaning Python cache files..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null && ok "Removed __pycache__ directories"
find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null && ok "Removed .pytest_cache"
find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null && ok "Removed .mypy_cache"
find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null && ok "Removed .ruff_cache"
ok "Python cache cleaned"

# 2. Test artifacts
say "[2/6] Cleaning test artifacts..."
[ -f .coverage ] && rm -f .coverage && ok "Removed .coverage"
[ -d .pytest_cache ] && rm -rf .pytest_cache && ok "Removed .pytest_cache"
[ -d htmlcov ] && rm -rf htmlcov && ok "Removed htmlcov"
find . -name ".coverage.*" -delete 2>/dev/null && ok "Removed .coverage.*"
ok "Test artifacts cleaned"

# 3. Output directories
say "[3/6] Cleaning output directories..."
if [ -d "results" ]; then
    rm -rf results
    ok "Removed results/"
fi
if [ -d "data" ]; then
    if [ "$DEEP_CLEAN" -eq 1 ]; then
        rm -rf data
        ok "Removed data/ (deep clean)"
    else
        warn "Preserving data/ (contains deals.db and sessions)"
        echo "         Use --deep to also remove data/"
    fi
fi

# 4. Browser profiles
say "[4/6] Cleaning browser profiles..."
for profile in browser_profile browser_profile_brave browser_profile_*; do
    if [ -d "$profile" ]; then
        rm -rf "$profile" 2>/dev/null && ok "Removed $profile/"
    fi
done

# 5. Temporary files
say "[5/6] Cleaning temporary files..."
find . -maxdepth 1 -name "*.tmp" -o -name "*.log" -o -name "*.tmp.py" -o -name "*.bak" | while read -r f; do
    [ -f "$f" ] && rm -f "$f"
done
ok "Temporary files cleaned"

# 6. Editor/IDE artifacts
say "[6/6] Cleaning editor/IDE artifacts..."
[ -d ".vscode" ] && rm -rf .vscode && ok "Removed .vscode/"
[ -d ".idea" ] && rm -rf .idea && ok "Removed .idea/"
find . -maxdepth 1 -name "*.swp" -o -name "*.swo" -o -name "*~" | while read -r f; do
    [ -f "$f" ] && rm -f "$f"
done
ok "Editor artifacts cleaned"

echo
echo "============================"
echo -e "${GREEN}Cleanup complete!${NC}"
echo "============================"
echo
echo "Preserved (not removed):"
echo "  - config.yaml, .env (your configuration)"
echo "  - data/deals.db (deal database)"
echo "  - data/sessions/ (login sessions)"
echo "  - config.yaml, .env.example"
echo
if [ "$DEEP_CLEAN" -eq 0 ]; then
    echo "To also remove database and sessions, run: $0 --deep"
fi

if [ "$DEEP_CLEAN" -eq 1 ]; then
    echo "Deep clean complete - database and sessions removed."
fi