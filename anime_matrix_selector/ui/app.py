"""The application window: library on the left, preview, actions and settings on the right."""
import os
import subprocess
import threading
import traceback

from gi.repository import Gdk, Gio, GLib, Gtk

from .. import backend
from ..config import (APP_ID, ICONS_DIR, get_current_active_path,
                      remember_custom_gif, scan_animations, search_directories)
from .library import Library
from .preview import GifPlayer
from .settings import SettingsCard

STYLE_CSS = os.path.join(os.path.dirname(__file__), "style.css")
VERIFY_DELAY_MS = 2500  # asusctl can fail a moment after starting; check again after this
STATUS_CLASSES = ("status-success", "status-error", "status-info")


def run_in_background(work, done, failed):
    """Run blocking `work()` off the UI thread so the window stays responsive.

    Then, on the UI thread, done(result), or failed(exception) if work raised.
    """
    def worker():
        try:
            result = work()
        except Exception as e:
            traceback.print_exc()
            GLib.idle_add(lambda: failed(e) and False)
            return
        GLib.idle_add(lambda: done(result) and False)
    threading.Thread(target=worker, daemon=True).start()


class AniMeMatrixApp(Gtk.Application):
    def __init__(self, cfg):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.cfg = cfg
        self.directories = search_directories(cfg)
        self.selected_path = get_current_active_path(cfg)
        self.window = None
        self.library = None
        self.gif_player = None
        self.busy = False
        self.asusctl_problem = None  # why the lid can't be driven, once checked

    # ---- building the window -----------------------------------------------------------

    def do_activate(self):
        # Launching the app again while it runs activates this instance; bring the window
        # forward instead of building a second one over the same tiles
        if self.window is not None:
            self.window.present()
            return
        win = Gtk.ApplicationWindow(application=self, title="AniMe Matrix Selector")
        win.set_default_size(1100, 760)
        self.window = win
        self.load_style()
        win.set_icon_name(APP_ID)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14,
                           margin_top=18, margin_bottom=18, margin_start=20, margin_end=20)
        win.set_child(main_box)
        main_box.append(self.build_header())

        # Two columns: animation library on the left, preview and controls on the right
        body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20, vexpand=True)
        main_box.append(body)
        self.library = Library(
            [category for _, category in self.directories],
            scan_animations(self.cfg, self.directories),
            on_selected=self.on_tile_selected,
            key_capture_widget=win,
            is_paused=self.is_paused)  # thumbnails pause while you're in another window
        body.append(self.library)

        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        side.set_size_request(420, -1)
        side.set_hexpand(False)  # labels inside want to expand; give the extra width to the grid
        body.append(side)
        side.append(self.build_preview_card())
        self.lbl_status = Gtk.Label(label="", xalign=0.5, wrap=True)
        side.append(self.lbl_status)
        side.append(self.build_main_actions())
        side.append(self.build_secondary_actions())
        side.append(SettingsCard(on_error=self.show_error))

        self.update_preview()
        self.refresh_service_status()
        run_in_background(backend.check_asusctl, self.on_asusctl_checked, self.on_background_error)

        win.connect("destroy", self.on_window_destroy)
        win.present()
        # Start on the playing animation, once the grid has been laid out
        self.library.reveal(self.selected_path)
        self.library.start_thumbnails()

    def load_style(self):
        display = Gdk.Display.get_default()
        css = Gtk.CssProvider()
        css.load_from_path(STYLE_CSS)
        Gtk.StyleContext.add_provider_for_display(display, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # Finds the icon when run from a checkout, before install.sh has put it in place
        Gtk.IconTheme.get_for_display(display).add_search_path(ICONS_DIR)

    def build_header(self):
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        title = Gtk.Label(label="AniMe Matrix Animation Selector", xalign=0)
        title.add_css_class("title-label")
        model = self.cfg.board_name or "unknown model"
        if not self.cfg.lid_model:
            model += " (no AniMe Matrix asusd knows of)"
        subtitle = Gtk.Label(label=f"AniMe Matrix Manager  •  {model}", xalign=0)
        subtitle.add_css_class("path-label")
        titles.append(title)
        titles.append(subtitle)
        header.append(titles)

        self.lbl_badge = Gtk.Label()
        self.set_badge("○ Checking…", "off")
        header.append(self.lbl_badge)
        return header

    def build_preview_card(self):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("preview-card")

        view_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, halign=Gtk.Align.END)
        view_row.add_css_class("linked")
        view_row.add_css_class("view-toggle")
        btn_lid = Gtk.ToggleButton(label="On the lid", active=True)
        btn_lid.set_tooltip_text("Simulate the lid's LEDs, as seen from outside")
        btn_plain = Gtk.ToggleButton(label="Plain GIF", group=btn_lid)
        view_row.append(btn_lid)
        view_row.append(btn_plain)
        # Other lids have a different LED layout, so only the GIF itself can be shown
        view_row.set_visible(self.cfg.lid_simulated)
        card.append(view_row)

        picture = Gtk.Picture(can_shrink=True)
        picture.set_size_request(380, 245)  # fits the lid's shape; 74x36 GIFs show at 5x
        card.append(picture)

        # Drawing the lid costs some CPU, so like the thumbnails it pauses when unfocused
        self.gif_player = GifPlayer(picture, self.cfg.native_sizes, is_paused=self.is_paused)
        btn_lid.connect("toggled", lambda b: self.gif_player.set_lid_view(b.get_active()))
        self.gif_player.set_lid_view(self.cfg.lid_simulated)

        self.lbl_current_path = Gtk.Label(xalign=0.5)
        self.lbl_current_path.add_css_class("path-label")
        card.append(self.lbl_current_path)
        return card

    def build_main_actions(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, homogeneous=True)
        self.btn_apply = Gtk.Button(label="★ Set as Main Running Animation")
        self.btn_apply.add_css_class("suggested-action")
        self.btn_apply.connect("clicked", self.on_apply_clicked)
        box.append(self.btn_apply)
        self.btn_off = Gtk.Button(label="⏹ Turn Off Lid Display")
        self.btn_off.connect("clicked", self.on_turn_off_clicked)
        box.append(self.btn_off)
        return box

    def build_secondary_actions(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_open_folder = Gtk.Button(label="📁 Open Folder")
        btn_open_folder.connect("clicked", self.on_open_folder_clicked)
        box.append(btn_open_folder)
        btn_browse = Gtk.Button(label="➕ Browse Custom GIF...")
        btn_browse.connect("clicked", self.on_browse_clicked)
        box.append(btn_browse)
        return box

    # ---- state shown in the window -----------------------------------------------------

    def is_paused(self):
        return not self.window.is_active()

    def set_status(self, text, css_class):
        self.lbl_status.set_text(text)
        for cls in STATUS_CLASSES:
            self.lbl_status.remove_css_class(cls)
        self.lbl_status.add_css_class(css_class)

    def show_error(self, text):
        self.set_status(text, "status-error")

    def set_busy(self, busy):
        self.busy = busy
        usable = not busy and not self.asusctl_problem
        self.btn_apply.set_sensitive(usable)
        self.btn_off.set_sensitive(usable)

    def on_background_error(self, error):
        """A background job raised: say so and give the buttons back."""
        self.show_error(f"Something went wrong: {error}")
        self.set_busy(False)

    def on_asusctl_checked(self, problem):
        self.asusctl_problem = problem
        if problem:
            self.show_error(problem)
        self.set_busy(self.busy)

    def on_tile_selected(self, path):
        if path != self.selected_path:
            self.selected_path = path
            self.update_preview()
            self.lbl_status.set_text("")

    def update_preview(self):
        path = self.selected_path
        if not path or not os.path.exists(path):
            self.gif_player.stop()
            self.lbl_current_path.set_text("File not found")
            return
        name = os.path.basename(path)
        self.lbl_current_path.set_text(f"{name}  •  loading…")
        self.gif_player.load(path, lambda info: self.lbl_current_path.set_text(
            f"{name}  •  {info}" if info else name))

    def refresh_service_status(self):
        run_in_background(lambda: backend.service_state(self.cfg), self.show_service_state,
                          self.on_background_error)

    def set_badge(self, text, state):
        """state is "playing", "off" or "warning", which picks the badge's colour."""
        self.lbl_badge.set_text(text)
        self.lbl_badge.set_css_classes(["status-badge", state])

    def show_service_state(self, state):
        if state.active_missing:
            self.set_badge("⚠ Active GIF missing, pick another", "warning")
        elif state.playing:
            self.set_badge(f"● Active: {os.path.basename(state.active_path)}", "playing")
        else:
            self.set_badge("○ Matrix Inactive", "off")
        self.library.mark_active(state.active_path if state.playing else None)

    # ---- actions -----------------------------------------------------------------------

    def on_apply_clicked(self, button):
        path = self.selected_path
        if not path or not os.path.exists(path):
            self.show_error("Selected file does not exist")
            return
        name = os.path.basename(path)
        self.set_busy(True)
        self.set_status(f"Starting '{name}'…", "status-info")
        run_in_background(lambda: backend.apply_animation(self.cfg, path),
                          lambda result: self.on_apply_done(name, *result),
                          self.on_background_error)

    def on_apply_done(self, name, err, check):
        if err:
            self.show_error(err)
            self.set_busy(False)
            self.refresh_service_status()
            return
        GLib.timeout_add(VERIFY_DELAY_MS, self.verify_playing, name, check)

    def verify_playing(self, name, check):
        run_in_background(lambda: backend.verify_started(check),
                          lambda problem: self.on_verified(name, problem),
                          self.on_background_error)
        return False

    def on_verified(self, name, problem):
        if problem:
            self.show_error(f"'{name}' failed to play: {problem}")
        else:
            self.set_status(f"✓ '{name}' is now active & playing on your lid!", "status-success")
        self.set_busy(False)
        self.refresh_service_status()

    def on_turn_off_clicked(self, button):
        self.set_busy(True)
        self.set_status("Turning off…", "status-info")
        run_in_background(backend.turn_off_matrix, self.on_turn_off_done, self.on_background_error)

    def on_turn_off_done(self, err):
        if err:
            self.show_error(f"Couldn't turn off the lid display: {err}")
        else:
            self.set_status("Matrix display turned off (stays off until you pick an animation)",
                            "status-info")
        self.set_busy(False)
        self.refresh_service_status()

    def on_open_folder_clicked(self, button):
        if not self.selected_path:
            return
        try:
            subprocess.Popen(["xdg-open", os.path.dirname(self.selected_path)])
        except OSError as e:
            self.show_error(f"Couldn't open the folder: {e.strerror or e}")

    def on_browse_clicked(self, button):
        gif_filter = Gtk.FileFilter(name="GIF Animations")
        gif_filter.add_pattern("*.gif")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(gif_filter)
        dialog = Gtk.FileDialog(title="Select a GIF for AniMe Matrix", filters=filters)
        dialog.open(self.window, None, self.on_browse_done)

    def on_browse_done(self, dialog, result):
        try:
            gfile = dialog.open_finish(result)
        except GLib.Error as e:
            if not e.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self.show_error(f"Couldn't open the file: {e.message}")
            return
        path = gfile.get_path() if gfile else None
        if not path or not path.endswith(".gif"):
            self.show_error("Pick a .gif file on this computer")
            return
        name = os.path.basename(path)
        # Selecting the tile clears the status line, so add it before saying anything
        if not self.library.add_custom(path):
            return
        try:
            remember_custom_gif(self.cfg, path)
        except OSError as e:
            # it is still shown for now; it just won't be listed next time
            self.show_error(f"Couldn't remember '{name}' for next time: {e.strerror or e}")
            return
        self.set_status(f"Added '{name}'", "status-info")

    def on_window_destroy(self, window):
        self.gif_player.stop()
        self.library.stop_thumbnails()

