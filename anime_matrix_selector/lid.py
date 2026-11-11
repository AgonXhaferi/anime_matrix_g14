"""GA402 lid simulation: which pixels light which LED, and drawing the LEDs as dots.

Geometry and sampling follow asusctl 6.3.8 (rog-anime/src/image.rs and diagonal.rs,
MPL-2.0), so the preview shows what asusctl actually sends to each LED. No GTK in here.
"""
from PIL import Image, ImageChops, ImageDraw, ImageOps

LED_ROWS = 61                      # physical rows, top to bottom
DIAG_HEIGHT = 39                   # pixel-gif reads a 74x39 diagonal grid on this lid
CM_PER_LED_X, CM_PER_LED_Y = 0.77, 0.283   # LED spacing within a row / between rows


def led_row_start(r):
    """First LED's x position; rows below 11 start further right (diagonal bottom-left cut)."""
    return 0 if r <= 11 else (r + 1) // 2 - 5


def led_row_length(r):
    return 34 if r <= 11 else 39 - r // 2


# Every LED as (row, index in row, x position); odd rows sit half an LED to the left
LEDS = [(r, i, led_row_start(r) + i - 0.5 * (r % 2))
        for r in range(LED_ROWS) for i in range(led_row_length(r))]


def diagonal_pixel(r, i):
    """Image pixel (x, y) that pixel-gif shows on LED i of row r."""
    x0, y0 = ((r + 1) // 2, 5 - r // 2) if r <= 11 else (r - 5, 0)
    return x0 + i, DIAG_HEIGHT - 1 - y0 - i


def scaled_samples(w, h):
    """Per LED, the in-bounds pixel indices asusctl gif averages (scale 1, no rotation)."""
    base = min(35.5 * CM_PER_LED_X / w, LED_ROWS * CM_PER_LED_Y / h)
    sx, sy = CM_PER_LED_X / base, CM_PER_LED_Y / base   # image px per LED step
    du, dv = (-0.5 * sx, 0.5 * sy), (0.5 * sx, 0.5 * sy)
    steps = (0.0, 0.5, 1.0, 1.5)
    result = []
    for r, i, x in LEDS:
        ox, oy = (x - 20) * sx + w / 2, (r - 0.5 - 20) * sy + h / 2   # LED (20, 20) is the center
        samples = []
        for u in steps:
            for v in steps:
                px, py = int(ox + u * du[0] + v * dv[0]), int(oy + u * du[1] + v * dv[1])
                if 0 <= px < w and 0 <= py < h:
                    samples.append(px + py * w)
        result.append(samples)
    return result


class LedSampler:
    """Turns RGBA frames of one GIF into per-LED brightness (bytes, one per LED).

    `native_sizes` are the sizes asusctl plays pixel-for-pixel (pixel-gif); anything else
    is scaled to fit like `asusctl anime gif` does.
    """

    def __init__(self, size, native_sizes):
        w, h = size
        self.native = size in native_sizes
        if self.native:
            # pixel-gif uses the red channel of opaque pixels
            self.offsets = []
            for r, i, _ in LEDS:
                x, y = diagonal_pixel(r, i)
                self.offsets.append((x + y * w) * 4 if 0 <= x < w and 0 <= y < h else -1)
        else:
            self.samples = [[p * 4 for p in s] for s in scaled_samples(w, h)]

    def sample(self, data):
        if self.native:
            return bytes(data[o] if o >= 0 and data[o + 3] == 255 else 0 for o in self.offsets)
        out = bytearray(len(self.samples))
        for n, samples in enumerate(self.samples):
            if not samples:
                continue
            total = lit = 0
            for o in samples:
                if data[o + 3] == 255:   # asusctl ignores pixels that aren't fully opaque
                    total += (data[o] + data[o + 1] + data[o + 2]) // 3
                    lit += 1
            k = len(samples)
            out[n] = int((total / k) * (lit / k))
        return bytes(out)


class LidRenderer:
    """Draws per-LED brightness as round dots in the lid's physical layout.

    Rows of each parity (even/odd) form a regular grid, so each is drawn by enlarging a
    tiny one-pixel-per-LED image and masking it with pre-drawn dots. That keeps the
    per-frame work in Pillow's C code instead of drawing 1700 circles in Python.
    """
    CELL_W, ROW_H = 16, 6          # px per LED horizontally / per row (~1.4x the preview size)
    DOT_RADIUS = 4.5
    OFF_LEVEL = 26                 # unlit LEDs stay faintly visible to show the lid's shape
    SUPERSAMPLE = 4                # dots are drawn this much larger, then shrunk, for smooth edges

    def __init__(self):
        cw, rh, ss = self.CELL_W, self.ROW_H, self.SUPERSAMPLE
        self.size = (35 * cw, (LED_ROWS + 1) * rh)
        self.lut = bytes(self.OFF_LEVEL + v * (255 - self.OFF_LEVEL) // 255 for v in range(256))
        self.parities = []
        for p in (0, 1):
            ncols, nrows = (34, 31) if p == 0 else (35, 30)
            index = [-1] * (ncols * nrows)   # grid cell -> LED number
            mask = Image.new("L", (self.size[0] * ss, self.size[1] * ss), 0)
            draw = ImageDraw.Draw(mask)
            for n, (r, i, x) in enumerate(LEDS):
                if r % 2 != p:
                    continue
                index[(r // 2) * ncols + int(x + 0.5 * p)] = n
                cx, cy, rad = (x + 1) * cw * ss, (r + 1) * rh * ss, self.DOT_RADIUS * ss
                draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=255)
            mask = mask.resize(self.size, Image.Resampling.BOX)
            offset = (cw // 2, 0) if p == 0 else (0, rh)
            self.parities.append((ncols, nrows, index, mask, offset))

    def render(self, levels):
        """Greyscale PIL image of the lid, as seen from outside, for one frame of per-LED levels.

        asusctl numbers rows from the inside of the lid, so the result is flipped top to
        bottom; that is the orientation in which ASUS's stock text animations read correctly.
        """
        lut = self.lut
        layers = []
        for ncols, nrows, index, mask, offset in self.parities:
            grid = bytes(lut[levels[n]] if n >= 0 else 0 for n in index)
            small = Image.frombytes("L", (ncols, nrows), grid)
            big = small.resize((ncols * self.CELL_W, nrows * 2 * self.ROW_H), Image.Resampling.NEAREST)
            canvas = Image.new("L", self.size, 0)
            canvas.paste(big, offset)
            layers.append(ImageChops.multiply(canvas, mask))
        return ImageOps.flip(ImageChops.lighter(*layers))
