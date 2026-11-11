"""The Display Settings card: brightness and power options, mirrored live from asusd."""
from gi.repository import GLib, Gtk

from ..asusd import BRIGHTNESS_LEVELS, POWER_SWITCHES, AnimeSettings


class SettingsCard(Gtk.Box):
    """on_error(message) runs when asusd refuses a change."""

    def __init__(self, on_error):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("settings-card")
        self.on_error = on_error
        self.syncing = False  # True while widgets are updated from asusd
        self.settings = AnimeSettings(self._on_settings_changed)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title = Gtk.Label(label="Display Settings", xalign=0, hexpand=True)
        title.add_css_class("heading")
        header.append(title)
        self.lbl_note = Gtk.Label(label="Connecting to asusd…")
        self.lbl_note.add_css_class("path-label")
        header.append(self.lbl_note)
        self.append(header)

        self.dd_brightness = Gtk.DropDown.new_from_strings(BRIGHTNESS_LEVELS)
        self.dd_brightness.connect("notify::selected", self._on_brightness_changed)
        self._add_row("Brightness", self.dd_brightness)

        self.power_switches = {}
        for prop, label in POWER_SWITCHES:
            switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            switch.connect("notify::active", self._on_power_switch_changed, prop)
            self._add_row(label, switch)
            self.power_switches[prop] = switch

        self.set_sensitive(False)  # until asusd answers
        self.settings.connect()

    def _add_row(self, label, control):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.append(Gtk.Label(label=label, xalign=0, hexpand=True))
        row.append(control)
        self.append(row)

    def _on_settings_changed(self, problem):
        """Show asusd's current values; grey out the card if asusd isn't there."""
        if problem:
            self.set_sensitive(False)
            self.lbl_note.set_text(problem)
            return
        self.syncing = True
        try:
            brightness = self.settings.get("Brightness")
            self.dd_brightness.set_selected(min(brightness, len(BRIGHTNESS_LEVELS) - 1))
            for prop, switch in self.power_switches.items():
                value = self.settings.get(prop)
                if value is not None:
                    switch.set_active(value)
        finally:
            self.syncing = False
        self.set_sensitive(True)
        self.lbl_note.set_text("")

    def _on_brightness_changed(self, dropdown, pspec):
        if not self.syncing:
            self._set("Brightness", GLib.Variant("u", dropdown.get_selected()))

    def _on_power_switch_changed(self, switch, pspec, prop):
        if not self.syncing:
            self._set(prop, GLib.Variant("b", switch.get_active()))

    def _set(self, prop, value):
        def failed(message):
            self.on_error(message)
            self.settings.refresh()  # put the controls back to asusd's real values
        self.settings.set(prop, value, failed)
