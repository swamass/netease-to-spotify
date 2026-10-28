#!/bin/sh
set -eu

PLIST_PATH="$HOME/Library/LaunchAgents/com.swamass.netease-to-spotify.plist"
REPO_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
PYTHON=${NETEASE_TO_SPOTIFY_PYTHON:-"$REPO_DIR/.venv/bin/python"}
"$PYTHON" "$REPO_DIR/scripts/local_launchd.py" uninstall "$PLIST_PATH"
echo "Uninstalled local sync."
