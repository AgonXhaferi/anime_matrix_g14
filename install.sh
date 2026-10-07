#!/usr/bin/env bash
# Installs (or removes) the AniMe Matrix selector. Safe to run again after changes.
#
#   ./install.sh                 for this user, run from this folder: the app is a link back
#                                here, so edits take effect on the next launch. The service and
#                                launcher are copies, so re-run after editing those.
#   ./install.sh --prefix DIR    a copy for all users under DIR, e.g. sudo ./install.sh --prefix
#                                /usr/local. Honours DESTDIR, for building distro packages.
#   --uninstall                  removes what the matching install put in place. Your settings
#                                (picked animation, folders.conf) are kept.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID=io.github.agonxhaferi.AnimeMatrixSelector
SERVICE=anime-matrix.service
PREFIX=""
UNINSTALL=0

usage() { sed -n '2,11s/^# \{0,1\}//p' "$0"; }
while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="${2:?--prefix needs a folder}"; shift 2 ;;
        --prefix=*) PREFIX="${1#*=}"; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
if [ -n "$PREFIX" ]; then
    ROOT="${DESTDIR:-}$PREFIX"
    BIN_DIR="$ROOT/bin"
    EXEC_DIR="$PREFIX/bin"                 # what the launcher runs, without DESTDIR
    SHARE_DIR="$ROOT/share/anime-matrix-selector"
    UNIT_DIR="$ROOT/lib/systemd/user"
    DATA_DIR="$ROOT/share"
    STATE_DIR="%E/anime-matrix"            # each user's $XDG_CONFIG_HOME, filled in by systemd
else
    BIN_DIR="$HOME/.local/bin"
    EXEC_DIR="$BIN_DIR"
    UNIT_DIR="$CONFIG_HOME/systemd/user"
    DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
    STATE_DIR="$CONFIG_HOME/anime-matrix"
fi
APP_DIR="$DATA_DIR/applications"
ICON_DIR="$DATA_DIR/icons/hicolor/scalable/apps"

refresh_caches() {
    update-desktop-database "$APP_DIR" 2>/dev/null || true
    gtk-update-icon-cache -q -t "$DATA_DIR/icons/hicolor" 2>/dev/null || true
}

if [ "$UNINSTALL" = 1 ]; then
    if [ -z "$PREFIX" ]; then
        systemctl --user disable --now "$SERVICE" 2>/dev/null || true
        if command -v asusctl >/dev/null; then asusctl anime --clear >/dev/null 2>&1 || true; fi
    fi
    rm -f "$BIN_DIR/anime-matrix-selector" "$UNIT_DIR/$SERVICE" \
          "$APP_DIR/$APP_ID.desktop" "$APP_DIR/anime-matrix-selector.desktop" \
          "$ICON_DIR/$APP_ID.svg"
    if [ -n "$PREFIX" ]; then
        rm -rf "$SHARE_DIR"
    else
        systemctl --user daemon-reload 2>/dev/null || true
    fi
    [ -z "${DESTDIR:-}" ] && refresh_caches
    echo "Uninstalled. Your settings are still in $CONFIG_HOME/anime-matrix; delete that folder to remove them too."
    exit 0
fi

# The service runs asusctl wherever this system installed it
ASUSCTL="$(command -v asusctl || true)"
if [ -z "$ASUSCTL" ]; then
    ASUSCTL=/usr/bin/asusctl
    echo "warning: asusctl not found; install asusctl/asusd first, then re-run this script" >&2
elif ! "$ASUSCTL" anime --help 2>&1 | grep -q pixel-gif; then
    echo "warning: this asusctl is too old; the selector needs asusctl 6 or newer" >&2
fi
python3 - <<'EOF' 2>/dev/null || echo "warning: missing Python deps; see the README for your distro's packages (needs GTK 4.12+ and Pillow)" >&2
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
import PIL
assert (Gtk.get_major_version(), Gtk.get_minor_version()) >= (4, 12)
EOF
command -v systemctl >/dev/null || echo "warning: systemd not found; the animation can't keep playing in the background" >&2

mkdir -p "$BIN_DIR" "$UNIT_DIR" "$APP_DIR" "$ICON_DIR"

if [ -n "$PREFIX" ]; then
    # App and Originals copied together: the app finds animations/ next to its real path
    install -d "$SHARE_DIR/animations"
    install -m 755 "$SRC/anime-matrix-selector" "$SHARE_DIR/anime-matrix-selector"
    install -m 644 "$SRC"/animations/*.gif "$SHARE_DIR/animations/"
    ln -sfn ../share/anime-matrix-selector/anime-matrix-selector "$BIN_DIR/anime-matrix-selector"
else
    # Replace any old copy with a link back to this folder
    ln -sfn "$SRC/anime-matrix-selector" "$BIN_DIR/anime-matrix-selector"
    rm -f "$APP_DIR/anime-matrix-selector.desktop"   # launcher's name before it took the app ID
fi

sed -e "s|@ASUSCTL@|$ASUSCTL|" -e "s|@CONFIG_DIR@|$STATE_DIR|g" "$SRC/$SERVICE" > "$UNIT_DIR/$SERVICE"
chmod 644 "$UNIT_DIR/$SERVICE"
sed "s|@BIN_DIR@|$EXEC_DIR|" "$SRC/$APP_ID.desktop" > "$APP_DIR/$APP_ID.desktop"
chmod 644 "$APP_DIR/$APP_ID.desktop"
install -m 644 "$SRC/data/icons/hicolor/scalable/apps/$APP_ID.svg" "$ICON_DIR/$APP_ID.svg"
[ -z "${DESTDIR:-}" ] && refresh_caches

if [ -n "$PREFIX" ]; then
    echo "Installed under $ROOT. Each user starts it from 'AniMe Matrix Selector'; picking an animation enables their service."
    exit 0
fi

systemctl --user daemon-reload
# Start playing only if an animation has already been picked; otherwise the app does it
if [ -e "$STATE_DIR/active.gif" ]; then
    systemctl --user enable --now "$SERVICE"
    echo "Installed. Animation service is running."
else
    echo "Installed. Open 'AniMe Matrix Selector' and pick an animation to start."
fi
