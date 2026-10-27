#!/usr/bin/env bash
# Prompt-only deal search - entry point.
exec "$(dirname "${BASH_SOURCE[0]}")/scripts/search.sh" "$@"
