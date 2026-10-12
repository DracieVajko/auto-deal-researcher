#!/usr/bin/env bash
# scripts/install_cron.sh - Install cron jobs for Auto Deal Searcher
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

python -m src.cli schedule-install