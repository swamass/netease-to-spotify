#!/bin/sh
set -eu

REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${NETEASE_TO_SPOTIFY_PYTHON:-"$REPO_DIR/.venv/bin/python"}
SCRIPT_PATH="$REPO_DIR/scripts/local_sync.py"
LAUNCHD_HELPER="$REPO_DIR/scripts/local_launchd.py"
PLIST_PATH="$HOME/Library/LaunchAgents/com.swamass.netease-to-spotify.plist"
LOG_DIR="$HOME/Library/Logs/netease-to-spotify"

if [ ! -x "$PYTHON" ]; then
    echo "Missing Python 3.12 environment: $PYTHON" >&2
    exit 1
fi

"$PYTHON" "$LAUNCHD_HELPER" install \
    "$PLIST_PATH" "$PYTHON" "$SCRIPT_PATH" "$REPO_DIR" "$LOG_DIR"
echo "Installed: $PLIST_PATH"
