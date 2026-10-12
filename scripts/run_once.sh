#!/usr/bin/env bash
# scripts/run_once.sh - Run Auto Deal Searcher once
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ARGS=("python" "-m" "src.cli" "run")
while [[ $# -gt 0 ]]; do
    case $1 in
        --prompt) ARGS+=("--prompt" "$2"); shift 2 ;;
        --prompt-file) ARGS+=("--prompt-file" "$2"); shift 2 ;;
        --condition) ARGS+=("--condition" "$2"); shift 2 ;;
        --category) ARGS+=("--category" "$2"); shift 2 ;;
        --winners) ARGS+=("--winners" "$2"); shift 2 ;;
        --format) ARGS+=("--format" "$2"); shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

exec "${ARGS[@]}"