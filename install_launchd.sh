#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_TEMPLATE="$SCRIPT_DIR/com.lucifer.logement.daily.plist"
TARGET_DIR="$HOME/Library/LaunchAgents"
TARGET_PLIST="$TARGET_DIR/com.lucifer.logement.daily.plist"

mkdir -p "$TARGET_DIR"
mkdir -p "$SCRIPT_DIR/logs" "$SCRIPT_DIR/state"
sed "s#__LOGEMENT_DIR__#$SCRIPT_DIR#g" "$PLIST_TEMPLATE" > "$TARGET_PLIST"
launchctl unload "$TARGET_PLIST" >/dev/null 2>&1 || true
launchctl load "$TARGET_PLIST"
echo "Automation installed: $TARGET_PLIST"
