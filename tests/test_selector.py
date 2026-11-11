"""Checks that need no display, GTK or AniMe hardware.

Run with: python3 -m unittest discover tests
"""
import dataclasses
import os
import sys
import tempfile
import unittest
from unittest import mock

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from anime_matrix_selector import backend, config, lid  # noqa: E402
from anime_matrix_selector.config import Config  # noqa: E402

GA402 = frozenset({config.STOCK_NATIVE_SIZE, config.GA402_NATIVE_SIZE})


class Geometry(unittest.TestCase):
    def test_led_count(self):
        # The GA402 lid has 1,449 LEDs in 61 rows
        self.assertEqual(lid.LED_ROWS, 61)
        self.assertEqual(len(lid.LEDS), 1449)

    def test_diagonal_pixels_fit_the_native_grid_once(self):
        pixels = [lid.diagonal_pixel(r, i) for r, i, _ in lid.LEDS]
        self.assertEqual(len(set(pixels)), len(pixels), "two LEDs read the same pixel")
        for x, y in pixels:
            self.assertTrue(0 <= x < 74 and 0 <= y < lid.DIAG_HEIGHT, (x, y))

    def test_every_led_samples_a_scaled_gif(self):
        for size in [(74, 36), (128, 128), (640, 360)]:
            samples = lid.scaled_samples(*size)
            self.assertEqual(len(samples), len(lid.LEDS))
            self.assertTrue(any(samples), size)

    def test_native_frame_lights_every_led(self):
        frame = Image.new("RGBA", (74, 39), (255, 255, 255, 255)).tobytes()
        levels = lid.LedSampler((74, 39), GA402).sample(frame)
        self.assertEqual(len(levels), 1449)
        self.assertTrue(all(v == 255 for v in levels))

    def test_lid_render_is_the_renderer_size(self):
        img = lid.LidRenderer().render(bytes([255]) * len(lid.LEDS))
        self.assertEqual(img.size, lid.LidRenderer().size)

    def test_originals_are_native_size(self):
        gifs = [f for f in os.listdir(config.ORIGINALS_DIR) if f.endswith(".gif")]
        self.assertTrue(gifs)
        for name in gifs:
            with Image.open(os.path.join(config.ORIGINALS_DIR, name)) as im:
                self.assertIn(im.size, GA402, name)


class LidModel(unittest.TestCase):
    def test_board_names(self):
        self.assertEqual(config.lid_model_for("GA402RK"), "GA402")
        self.assertEqual(config.lid_model_for("GU604VI"), "GU604")
        self.assertIsNone(config.lid_model_for("FX506HM"))

    def test_74x39_is_native_only_on_a_ga402(self):
        self.assertIn((74, 39), Config("", "", "GA402RK").native_sizes)
        self.assertNotIn((74, 39), Config("", "", "GA401QM").native_sizes)


class TempConfig(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.cfg = Config(os.path.join(self.tmp, "config"), os.path.join(self.tmp, "stock"),
                          "GA402RK", originals_dir=os.path.join(self.tmp, "originals"))

    def write(self, path, text=""):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)
        return path


class FoldersConf(TempConfig):
    def test_missing_file_is_created_as_template(self):
        self.assertEqual(config.load_user_folders(self.cfg), [])
        with open(self.cfg.folders_list) as f:
            self.assertTrue(all(not line.strip() or line.startswith("#") for line in f))

    def test_named_and_plain_lines(self):
        self.write(self.cfg.folders_list, "# comment\n\nMy GIFs = ~/Pictures/lid\n/srv/gifs/\n")
        self.assertEqual(config.load_user_folders(self.cfg), [
            (os.path.expanduser("~/Pictures/lid"), "My GIFs"),
            ("/srv/gifs/", "gifs"),
        ])


class ArmouryCrate(TempConfig):
    def test_found_in_the_users_data_folder_first(self):
        mine = os.path.join(self.tmp, "home", "anime-matrix", "armoury-crate")
        system = os.path.join(self.tmp, "usr", "anime-matrix", "armoury-crate")
        os.makedirs(mine)
        os.makedirs(system)
        env = {"XDG_DATA_HOME": os.path.join(self.tmp, "home"),
               "XDG_DATA_DIRS": os.path.join(self.tmp, "usr")}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(config.default_armoury_crate_dir(), mine)
            os.rmdir(mine)
            self.assertEqual(config.default_armoury_crate_dir(), system)
            os.rmdir(system)
            self.assertEqual(config.default_armoury_crate_dir(), "")

    def test_sections_shown_only_when_installed(self):
        names = [name for _, name in config.search_directories(self.cfg)]
        self.assertNotIn("Armoury Crate", names)
        cfg = dataclasses.replace(self.cfg, armoury_crate_dir="/ac")
        dirs = config.search_directories(cfg)
        self.assertIn(("/ac/normal", "Armoury Crate"), dirs)
        self.assertEqual(len(dirs), len(names) + len(config.ARMOURY_CRATE_FOLDERS))


class Scanning(TempConfig):
    def test_categories_thumbnails_and_custom(self):
        self.write(os.path.join(self.cfg.originals_dir, "b.gif"))
        self.write(os.path.join(self.cfg.originals_dir, "a.gif"))
        self.write(os.path.join(self.cfg.originals_dir, "a_thumbnail.gif"))
        picked = self.write(os.path.join(self.tmp, "elsewhere", "mine.gif"))
        config.remember_custom_gif(self.cfg, picked)
        config.remember_custom_gif(self.cfg, picked)  # remembered once

        found = config.scan_animations(self.cfg, config.search_directories(self.cfg))
        self.assertEqual(found, [
            ("Originals", os.path.join(self.cfg.originals_dir, "a.gif")),
            ("Originals", os.path.join(self.cfg.originals_dir, "b.gif")),
            (config.CUSTOM_CATEGORY, picked),
        ])


class ApplyAnimation(TempConfig):
    def test_points_active_gif_at_the_pick_and_picks_the_mode(self):
        old = self.write(os.path.join(self.tmp, "old.gif"))
        new = os.path.join(self.tmp, "new.gif")
        Image.new("RGBA", (74, 39)).save(new)
        os.makedirs(self.cfg.config_dir)
        os.symlink(old, self.cfg.active_symlink)

        with mock.patch.object(backend, "run_cmd", return_value=(True, "")), \
                mock.patch.object(backend, "service_props", return_value={"NRestarts": "3"}):
            err, check = backend.apply_animation(self.cfg, new)

        self.assertIsNone(err)
        self.assertEqual(check.restarts_before, "3")
        self.assertEqual(os.readlink(self.cfg.active_symlink), new)
        with open(self.cfg.mode_env) as f:
            self.assertEqual(f.read(), "ANIME_CMD=pixel-gif\n")
        self.assertEqual(sorted(os.listdir(self.cfg.config_dir)), ["active.gif", "mode.env"])

    def test_unwritable_config_is_an_error_not_a_crash(self):
        self.write(self.cfg.config_dir)  # a file where the folder should be
        with mock.patch.object(backend, "run_cmd", return_value=(True, "")):
            err, check = backend.apply_animation(self.cfg, os.path.join(self.tmp, "x.gif"))
        self.assertIn("Couldn't save the pick", err)
        self.assertIsNone(check)


class Errors(unittest.TestCase):
    def test_find_error(self):
        self.assertEqual(backend.find_error("ok\nError: no such file\n"), "no such file")
        self.assertEqual(backend.find_error("all good"), "")


if __name__ == "__main__":
    unittest.main()
