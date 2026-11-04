"""asusd's live AniMe settings on the system bus (readable and writable without root)."""
from gi.repository import Gio, GLib

ASUSD_NAME = "xyz.ljones.Asusd"
ANIME_PATH = "/xyz/ljones/aura/anime"
ANIME_IFACE = "xyz.ljones.Anime"
BRIGHTNESS_LEVELS = ["Off", "Low", "Medium", "High"]  # asusd values 0-3
POWER_SWITCHES = [
    ("OffWhenUnplugged", "Off when unplugged"),
    ("OffWhenLidClosed", "Off when lid closed"),
    ("OffWhenSuspended", "Off when suspended"),
]


class AnimeSettings:
    """Reads and writes asusd's AniMe properties, and says when they change.

    on_changed(problem) runs on the UI thread whenever the values may have changed, also
    when they were changed elsewhere (asusctl, a restarted asusd). `problem` is None when
    asusd answered, else a message saying why the settings can't be shown.
    """

    def __init__(self, on_changed):
        self.on_changed = on_changed
        self.proxy = None

    def connect(self):
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None,
            ASUSD_NAME, ANIME_PATH, ANIME_IFACE, None, self._on_proxy_ready)

    def _on_proxy_ready(self, source, result):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error as e:
            self.on_changed(f"Unavailable: {e.message}")
            return
        self.proxy.connect("g-properties-changed", lambda *args: self.refresh())
        self.proxy.connect("notify::g-name-owner", lambda *args: self.refresh())
        self.refresh()

    def refresh(self):
        """Run on_changed with the current state, e.g. to undo a refused change."""
        if self.get("Brightness") is None:
            self.on_changed("asusd is not running (or is older than 6.0)")
        else:
            self.on_changed(None)

    def get(self, prop):
        value = self.proxy.get_cached_property(prop) if self.proxy else None
        return None if value is None else value.unpack()

    def set(self, prop, value, on_error):
        """Set `prop` to the GLib.Variant `value`; on_error(message) if asusd refuses."""
        def done(proxy, result):
            try:
                proxy.call_finish(result)
            except GLib.Error as e:
                on_error(f"Couldn't change {prop}: {e.message}")
        self.proxy.call(
            "org.freedesktop.DBus.Properties.Set",
            GLib.Variant("(ssv)", (ANIME_IFACE, prop, value)),
            Gio.DBusCallFlags.NONE, -1, None, done)
