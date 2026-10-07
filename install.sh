#!/usr/bin/env bash
# Installs the AniMe Matrix selector from this folder. Safe to run again after changes.
#   - the app is symlinked, so edits here take effect on the next launch
#   - the service and launcher are copied (systemd and GNOME want real files), so re-run
#     this script after editing anime-matrix.service or anime-matrix-selector.desktop
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="$HOME/.config/systemd/user"
APP_DIR="$HOME/.local/share/applications"
STATE_DIR="$HOME/.config/anime-matrix"
SERVICE=anime-matrix.service

command -v asusctl >/dev/null || echo "warning: asusctl not found; install asusctl/asusd first" >&2
python3 -c 'import gi; gi.require_version("Gtk", "4.0"); from gi.repository import Gtk; import PIL' 2>/dev/null \
    || echo "warning: missing Python deps; install python3-gobject, gtk4 and python3-pillow" >&2

mkdir -p "$BIN_DIR" "$UNIT_DIR" "$APP_DIR" "$STATE_DIR"

# App: replace any old copy with a link back to this folder
ln -sfn "$SRC/anime-matrix-selector" "$BIN_DIR/anime-matrix-selector"

# Service
install -m 644 "$SRC/$SERVICE" "$UNIT_DIR/$SERVICE"
systemctl --user daemon-reload

# Launcher, pointed at this user's bin directory
sed "s|@BIN_DIR@|$BIN_DIR|" "$SRC/anime-matrix-selector.desktop" > "$APP_DIR/anime-matrix-selector.desktop"
update-desktop-database "$APP_DIR" 2>/dev/null || true

# Start playing only if an animation has already been picked; otherwise the app does it
if [ -e "$STATE_DIR/active.gif" ]; then
    systemctl --user enable --now "$SERVICE"
    echo "Installed. Animation service is running."
else
    echo "Installed. Open 'AniMe Matrix Selector' and pick an animation to start."
fi
