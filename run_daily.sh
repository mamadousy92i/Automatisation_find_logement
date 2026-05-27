#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p "$SCRIPT_DIR/logs" "$SCRIPT_DIR/state"

/opt/homebrew/opt/python@3.14/bin/python3.14 "$SCRIPT_DIR/logement_bot.py" --env-file "$SCRIPT_DIR/.env" --state-file "$SCRIPT_DIR/state/last_run.json"
