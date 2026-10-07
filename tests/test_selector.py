"""Checks that need no display or AniMe hardware: lid geometry and config parsing.

Run with: python3 -m unittest discover tests
"""
import importlib.machinery
import importlib.util
import os
import tempfile
import unittest

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load_app():
    # The app is a script without a .py extension, so load it by path
    loader = importlib.machinery.SourceFileLoader("selector", os.path.join(ROOT, "anime-matrix-selector"))
    spec = importlib.util.spec_from_loader("selector", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


app = load_app()


class Geometry(unittest.TestCase):
    def test_led_count(self):
        # The GA402 lid has 1,449 LEDs in 61 rows
        self.assertEqual(app.LED_ROWS, 61)
        self.assertEqual(len(app.LEDS), 1449)

    def test_diagonal_pixels_fit_the_native_grid_once(self):
        pixels = [app.diagonal_pixel(r, i) for r, i, _ in app.LEDS]
        self.assertEqual(len(set(pixels)), len(pixels), "two LEDs read the same pixel")
        for x, y in pixels:
            self.assertTrue(0 <= x < 74 and 0 <= y < app.DIAG_HEIGHT, (x, y))

    def test_every_led_samples_a_scaled_gif(self):
        for size in [(74, 36), (128, 128), (640, 360)]:
            samples = app.scaled_samples(*size)
            self.assertEqual(len(samples), len(app.LEDS))
            self.assertTrue(any(samples), size)

    def test_lid_render_size_matches_led_count(self):
        # 74x39 only counts as native on a GA402, which CI machines aren't
        self.addCleanup(setattr, app, "NATIVE_SIZES", app.NATIVE_SIZES)
        app.NATIVE_SIZES = {(74, 36), (74, 39)}
        frame = Image.new("RGBA", (74, 39), (255, 255, 255, 255)).tobytes()
        levels = app.LedSampler((74, 39)).sample(frame)
        self.assertEqual(len(levels), 1449)
        self.assertTrue(all(v == 255 for v in levels))

    def test_originals_are_native_size(self):
        folder = os.path.join(ROOT, "animations")
        gifs = [f for f in os.listdir(folder) if f.endswith(".gif")]
        self.assertTrue(gifs)
        for name in gifs:
            with Image.open(os.path.join(folder, name)) as im:
                self.assertIn(im.size, {(74, 36), (74, 39)}, name)


class FoldersConf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "folders.conf")
        self.addCleanup(setattr, app, "FOLDERS_LIST", app.FOLDERS_LIST)
        self.addCleanup(setattr, app, "CONFIG_DIR", app.CONFIG_DIR)
        app.FOLDERS_LIST, app.CONFIG_DIR = self.path, self.tmp.name

    def test_missing_file_is_created_as_template(self):
        self.assertEqual(app.load_user_folders(), [])
        with open(self.path) as f:
            self.assertTrue(all(not l.strip() or l.startswith("#") for l in f))

    def test_named_and_plain_lines(self):
        with open(self.path, "w") as f:
            f.write("# comment\n\nMy GIFs = ~/Pictures/lid\n/srv/gifs/\n")
        self.assertEqual(app.load_user_folders(), [
            (os.path.expanduser("~/Pictures/lid"), "My GIFs"),
            ("/srv/gifs/", "gifs"),
        ])


if __name__ == "__main__":
    unittest.main()
