"""The animation library: a search box over grids of animated thumbnails, one per category."""
import math
import os
import queue
import threading

from gi.repository import GLib, Gtk, Pango
from PIL import Image, ImageSequence

from ..config import CUSTOM_CATEGORY
from .preview import PixelPaintable, frame_duration, rgba_texture

THUMB_SIZE = (148, 72)    # 2x the matrix, so native GIFs scale by a whole number
THUMB_MAX_FRAMES = 120    # longer GIFs skip frames in thumbnails to bound memory
TICK_MS = 33              # thumbnail animation timer
HEADING_ROOM = 40         # px kept above a revealed tile so its category heading shows


def decode_thumbnail(path):
    """Frames as (w, h, rgba bytes, duration ms), shrunk to THUMB_SIZE and capped in count."""
    frames = []
    with Image.open(path) as im:
        step = math.ceil(getattr(im, "n_frames", 1) / THUMB_MAX_FRAMES)
        shrink = im.width > THUMB_SIZE[0] or im.height > THUMB_SIZE[1]
        for i, frame in enumerate(ImageSequence.Iterator(im)):
            if i % step == 0:
                rgba = frame.convert("RGBA")
                if shrink:
                    rgba.thumbnail(THUMB_SIZE, Image.Resampling.LANCZOS)
                frames.append([rgba.width, rgba.height, rgba.tobytes(), 0])
            # a kept frame also lasts as long as the frames skipped after it
            frames[-1][3] += frame_duration(frame)
    return frames


class ThumbnailLoader:
    """Decodes thumbnails one at a time on a background thread, on request."""

    def __init__(self, on_ready):
        self.on_ready = on_ready  # called on the UI thread as on_ready(path, frames)
        self.requested = set()
        self.jobs = queue.Queue()
        threading.Thread(target=self._work, daemon=True).start()

    def request(self, path):
        if path not in self.requested:
            self.requested.add(path)
            self.jobs.put(path)

    def _work(self):
        while True:
            path = self.jobs.get()
            try:
                frames = decode_thumbnail(path)
            except Exception as e:  # a broken GIF must not stop the thumbnails after it
                print(f"Error loading thumbnail for {path}: {e}")
                frames = []
            GLib.idle_add(self._deliver, path, frames)

    def _deliver(self, path, frames):
        self.on_ready(path, [(rgba_texture(w, h, data), dur) for w, h, data, dur in frames])
        return False


class AnimationTile(Gtk.FlowBoxChild):
    """One grid entry: an animated thumbnail with the file name under it."""

    def __init__(self, category, path):
        super().__init__()
        self.category = category
        self.path = path
        name = os.path.basename(path)
        self.search_text = f"{name} {category}".lower()
        self.frames = None  # None until the loader delivers them
        self.frame_idx = 0
        self.next_change = 0

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.paintable = PixelPaintable()
        art = Gtk.Picture(paintable=self.paintable, can_shrink=True)
        art.set_size_request(*THUMB_SIZE)
        art.add_css_class("thumb-art")
        box.append(art)
        label = Gtk.Label(label=os.path.splitext(name)[0], max_width_chars=16,
                          ellipsize=Pango.EllipsizeMode.END)
        label.add_css_class("path-label")
        box.append(label)
        self.set_child(box)
        self.set_tooltip_text(f"{name}\n{category}")
        self.add_css_class("anim-tile")

    def matches(self, words):
        return all(word in self.search_text for word in words)

    def set_frames(self, frames):
        self.frames = frames
        self.frame_idx = 0
        self.next_change = 0
        if frames:
            self.paintable.set_texture(frames[0][0])

    def advance(self, now_ms):
        if not self.frames or len(self.frames) < 2 or now_ms < self.next_change:
            return
        self.frame_idx = (self.frame_idx + 1) % len(self.frames)
        tex, dur = self.frames[self.frame_idx]
        self.paintable.set_texture(tex)
        self.next_change = now_ms + dur


class Section:
    """A category heading and the grid of its tiles."""

    def __init__(self, category, on_selected, filter_func):
        self.category = category
        self.heading = Gtk.Label(label=category, xalign=0)
        self.heading.add_css_class("section-heading")
        self.flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.SINGLE, homogeneous=True,
                                max_children_per_line=12, row_spacing=4, column_spacing=4,
                                valign=Gtk.Align.START)
        self.flow.set_filter_func(filter_func)
        self.flow.connect("selected-children-changed", on_selected)
        self.tiles = []

    def set_visible(self, visible):
        self.heading.set_visible(visible)
        self.flow.set_visible(visible)


class Library(Gtk.Box):
    """Searchable, sectioned grid of animations.

    on_selected(path) runs when the user picks a tile. Thumbnails animate only while
    is_paused() is false and only for tiles in view, to save battery.
    """

    def __init__(self, categories, animations, on_selected, key_capture_widget, is_paused):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        self.on_selected = on_selected
        self.is_paused = is_paused
        self.tiles = {}            # path -> AnimationTile
        self.sections = {}         # category -> Section, in display order
        self.query_words = []
        self.syncing_selection = False  # True while selection is changed by code, not the user
        self.last_tile_y = None    # reveal(): where the tile was on the previous frame
        self.tick_id = None

        self.search = Gtk.SearchEntry(placeholder_text="Search animations (just start typing)")
        self.search.set_key_capture_widget(key_capture_widget)
        self.search.connect("search-changed", self._on_search_changed)
        self.append(self.search)

        self.scroller = Gtk.ScrolledWindow(vexpand=True)
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(self.scroller)

        self.sections_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.scroller.set_child(self.sections_box)
        self.lbl_no_results = Gtk.Label(label="No animations match", visible=False, margin_top=40)
        self.lbl_no_results.add_css_class("dim-label")
        self.sections_box.append(self.lbl_no_results)

        for category in dict.fromkeys(list(categories) + [CUSTOM_CATEGORY]):
            section = Section(category, self._on_tile_selected, self._tile_visible)
            self.sections[category] = section
            self.sections_box.append(section.heading)
            self.sections_box.append(section.flow)
        for category, path in animations:
            self.add_tile(category, path)
        self.thumbs = ThumbnailLoader(self._on_thumbnail_ready)
        self._refresh_sections()

    # ---- tiles and search --------------------------------------------------------------

    def add_tile(self, category, path):
        tile = AnimationTile(category, path)
        self.tiles[path] = tile
        section = self.sections[category]
        section.tiles.append(tile)
        section.flow.append(tile)
        return tile

    def _tile_visible(self, tile):
        return tile.matches(self.query_words)

    def _refresh_sections(self):
        """Hide categories with nothing to show, and say so when nothing matches at all."""
        any_shown = False
        for section in self.sections.values():
            shown = any(tile.matches(self.query_words) for tile in section.tiles)
            section.set_visible(shown)
            any_shown = any_shown or shown
        self.lbl_no_results.set_visible(not any_shown)

    def _on_search_changed(self, entry):
        self.query_words = entry.get_text().strip().lower().split()
        for section in self.sections.values():
            section.flow.invalidate_filter()
        self._refresh_sections()

    # ---- selection ---------------------------------------------------------------------

    def _on_tile_selected(self, flow):
        if self.syncing_selection:
            return
        selected = flow.get_selected_children()
        if not selected:
            return
        self._select_only(selected[0])
        self.on_selected(selected[0].path)

    def _select_only(self, tile):
        """Select `tile` without telling on_selected; each category is its own grid, so
        clear the selection in the others."""
        self.syncing_selection = True
        try:
            for section in self.sections.values():
                if section.flow is tile.get_parent():
                    section.flow.select_child(tile)
                else:
                    section.flow.unselect_all()
        finally:
            self.syncing_selection = False

    def add_custom(self, path):
        """Show a GIF picked with Browse (adding a tile if it's new), select it and scroll
        to it. Returns True if it was new."""
        tile = self.tiles.get(path)
        is_new = tile is None
        if is_new:
            tile = self.add_tile(CUSTOM_CATEGORY, path)
        self.search.set_text("")  # make sure the tile isn't filtered out
        self._on_search_changed(self.search)
        tile.get_parent().select_child(tile)  # runs _on_tile_selected, so on_selected
        GLib.timeout_add(100, self._scroll_to, tile)
        return is_new

    def _scroll_to(self, tile):
        self.scroller.get_child().scroll_to(tile, None)  # the child is the auto-added Viewport
        return False

    def reveal(self, path):
        """Select the tile for `path` and scroll it into view once the grid is laid out."""
        tile = self.tiles.get(path)
        if tile is not None:
            self.last_tile_y = None
            self.scroller.add_tick_callback(lambda widget, clock: self._reveal_tick(tile))

    def _reveal_tick(self, tile):
        ok, rect = tile.compute_bounds(self.sections_box)
        if not ok or self.scroller.get_height() == 0 or rect.origin.y != self.last_tile_y:
            # not laid out yet, or still moving while the window settles on its size
            self.last_tile_y = rect.origin.y if ok else None
            return GLib.SOURCE_CONTINUE
        self._select_only(tile)
        # Focus first: focusing scrolls on its own, and our position should win
        tile.grab_focus()
        self.scroller.get_vadjustment().set_value(max(0, rect.origin.y - HEADING_ROOM))
        return GLib.SOURCE_REMOVE

    def mark_active(self, active_path):
        """Outline the tile of the animation playing on the lid (None: nothing playing)."""
        for path, tile in self.tiles.items():
            if path == active_path:
                tile.add_css_class("active-anim")
            else:
                tile.remove_css_class("active-anim")

    # ---- thumbnails --------------------------------------------------------------------

    def start_thumbnails(self):
        if self.tick_id is None:
            self.tick_id = GLib.timeout_add(TICK_MS, self._tick_thumbnails)

    def stop_thumbnails(self):
        if self.tick_id is not None:
            GLib.source_remove(self.tick_id)
            self.tick_id = None

    def _tick_thumbnails(self):
        """Animate the thumbnails currently in view, and request ones not loaded yet."""
        if self.is_paused():
            return GLib.SOURCE_CONTINUE
        now = GLib.get_monotonic_time() // 1000
        view_height = self.scroller.get_height()
        for tile in self.tiles.values():
            if not tile.is_drawable():  # filtered out, hidden section or window minimised
                continue
            ok, rect = tile.compute_bounds(self.scroller)
            if not ok or rect.origin.y + rect.size.height < 0 or rect.origin.y > view_height:
                continue
            if tile.frames is None:
                self.thumbs.request(tile.path)
            else:
                tile.advance(now)
        return GLib.SOURCE_CONTINUE

    def _on_thumbnail_ready(self, path, frames):
        if path in self.tiles:
            self.tiles[path].set_frames(frames)
