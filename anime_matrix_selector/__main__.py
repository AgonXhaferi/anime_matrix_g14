"""Entry point: python3 -m anime_matrix_selector, or the anime-matrix-selector launcher."""
import sys

from . import ui  # noqa: F401  (pins the GTK version before Gtk is imported)
from gi.repository import Gtk

MIN_GTK = (4, 12)  # Gdk.MemoryFormat.G8, Gtk.Viewport.scroll_to


def main(argv=None):
    found = (Gtk.get_major_version(), Gtk.get_minor_version())
    if found < MIN_GTK:
        sys.exit("AniMe Matrix Selector needs GTK %d.%d or newer (found %d.%d)" % (*MIN_GTK, *found))
    from .config import Config
    from .ui.app import AniMeMatrixApp
    return AniMeMatrixApp(Config.detect()).run(sys.argv if argv is None else argv)


if __name__ == "__main__":
    sys.exit(main())
