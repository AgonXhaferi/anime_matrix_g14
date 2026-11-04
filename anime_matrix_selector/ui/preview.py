"""Showing GIFs: a sharp-pixel paintable, and the big preview player with its lid view."""
import math
import threading

from gi.repository import Gdk, GLib, GObject, Graphene, Gsk
from PIL import Image, ImageSequence

from ..lid import LedSampler, LidRenderer

MIN_FRAME_MS = 20       # browsers and asusctl treat shorter GIF delays as this
DEFAULT_FRAME_MS = 40   # frames without a delay
PAUSED_POLL_MS = 250    # how often a paused player checks whether to resume


def frame_duration(frame):
    return max(frame.info.get("duration", DEFAULT_FRAME_MS), MIN_FRAME_MS)


def rgba_texture(w, h, data):
    return Gdk.MemoryTexture.new(w, h, Gdk.MemoryFormat.R8G8B8A8, GLib.Bytes.new(data), w * 4)


def grey_texture(img):
    return Gdk.MemoryTexture.new(img.width, img.height, Gdk.MemoryFormat.G8,
                                 GLib.Bytes.new(img.tobytes()), img.width)


class PixelPaintable(GObject.Object, Gdk.Paintable):
    """Draws a texture centered and fitted; enlarges by whole numbers with sharp pixels."""

    def __init__(self):
        super().__init__()
        self.texture = None

    def set_texture(self, texture):
        self.texture = texture
        self.invalidate_contents()

    def do_snapshot(self, snapshot, width, height):
        if self.texture is None:
            return
        tw, th = self.texture.get_width(), self.texture.get_height()
        scale = min(width / tw, height / th)
        if scale >= 1:
            scale, filt = math.floor(scale), Gsk.ScalingFilter.NEAREST
        else:
            filt = Gsk.ScalingFilter.TRILINEAR
        w, h = tw * scale, th * scale
        rect = Graphene.Rect().init((width - w) / 2, (height - h) / 2, w, h)
        snapshot.append_scaled_texture(self.texture, filt, rect)


class GifPlayer:
    """Decodes a GIF in the background and loops it inside a Gtk.Picture.

    is_paused() is checked each frame; paused frames don't advance. With the lid view on,
    each frame is drawn as the lid's LEDs instead of the GIF itself.
    """

    def __init__(self, picture_widget, native_sizes, is_paused=lambda: False):
        self.native_sizes = native_sizes
        self.is_paused = is_paused
        self.paintable = PixelPaintable()
        picture_widget.set_paintable(self.paintable)
        self.frames = []        # (plain texture, per-LED levels, duration ms)
        self.frame_idx = 0      # next frame to show
        self.shown_idx = 0
        self.lid_view = True
        self.lid = None         # LidRenderer, built on first use
        self.timer_id = None
        self.load_token = 0     # bumped per load so a slow decode can't overwrite a newer pick

    def stop(self):
        self.load_token += 1
        if self.timer_id:
            GLib.source_remove(self.timer_id)
            self.timer_id = None

    def load(self, path, on_loaded):
        """Decode `path` in a background thread, then start playback and call on_loaded(info).

        `info` describes the GIF (size, frames, how it plays), or is None if it can't be read.
        """
        self.stop()
        token = self.load_token
        threading.Thread(target=self._decode, args=(path, token, on_loaded), daemon=True).start()

    def _decode(self, path, token, on_loaded):
        frames, info = [], None
        try:
            with Image.open(path) as im:
                sampler = LedSampler(im.size, self.native_sizes)
                info = f"{im.size[0]} × {im.size[1]} px"
                if getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1:
                    info += f" • {im.n_frames} frames"
                info += " • pixel-perfect" if sampler.native else " • scaled to fit"
                for frame in ImageSequence.Iterator(im):
                    if token != self.load_token:
                        return  # a different GIF was picked meanwhile
                    rgba = frame.convert("RGBA")
                    data = rgba.tobytes()
                    frames.append((rgba.width, rgba.height, data, sampler.sample(data),
                                   frame_duration(frame)))
        except Exception as e:  # Pillow raises many kinds on broken GIFs; any must reach _show
            print(f"Error loading GIF preview for {path}: {e}")
            frames, info = [], None
        GLib.idle_add(self._show, token, frames, info, on_loaded)

    def _show(self, token, frames, info, on_loaded):
        if token != self.load_token:
            return False
        self.frames = [(rgba_texture(w, h, data), levels, dur) for w, h, data, levels, dur in frames]
        self.frame_idx = 0
        if self.frames:
            self._next_frame(first=True)
        on_loaded(info)
        return False

    def set_lid_view(self, on):
        self.lid_view = on
        if self.frames:
            self._paint(self.shown_idx)

    def _paint(self, idx):
        tex, levels, _ = self.frames[idx]
        if self.lid_view:
            if self.lid is None:
                self.lid = LidRenderer()
            tex = grey_texture(self.lid.render(levels))
        self.paintable.set_texture(tex)
        self.shown_idx = idx

    def _next_frame(self, first=False):
        self.timer_id = None
        if not self.frames:
            return False
        if self.is_paused() and not first:  # always show the first frame
            self.timer_id = GLib.timeout_add(PAUSED_POLL_MS, self._next_frame)
            return False
        self._paint(self.frame_idx)
        if len(self.frames) > 1:
            delay = self.frames[self.frame_idx][2]
            self.frame_idx = (self.frame_idx + 1) % len(self.frames)
            self.timer_id = GLib.timeout_add(delay, self._next_frame)
        return False
