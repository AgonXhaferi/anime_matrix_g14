"""Where things live, which lid this is, and which GIFs to show. No GTK in here."""
import os
from dataclasses import dataclass

APP_ID = "io.github.agonxhaferi.AnimeMatrixSelector"
# The repo (or install) folder that holds animations/ and data/ next to this package
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ORIGINALS_DIR = os.path.join(ROOT_DIR, "animations")
ICONS_DIR = os.path.join(ROOT_DIR, "data", "icons")
SERVICE = "anime-matrix.service"

CUSTOM_CATEGORY = "Custom"
STOCK_FOLDERS = [
    ("asus/rog", "ROG (Stock)"),
    ("asus/gaming", "Gaming (Stock)"),
    ("asus/music", "Music (Stock)"),
    ("asus/trend", "Trend (Stock)"),
    ("asus/festive", "Festive (Stock)"),
    ("custom", "Custom (Stock)"),
]
# ASUS's Armoury Crate animations (the Windows app's AniMe Matrix library), which asusd
# doesn't ship. They live in their own repo, which install.sh offers to download into
# <data dir>/anime-matrix/armoury-crate. Subfolder there, section name.
ARMOURY_CRATE_REPO = "https://github.com/AgonXhaferi/anime_matrix_animations"
ARMOURY_CRATE_FOLDERS = [
    ("normal", "Armoury Crate"),
    ("patterns", "Armoury Crate Patterns"),
    ("alan-walker", "Armoury Crate × Alan Walker"),
]
LID_MODELS = ("GA401", "GA402", "GU604")
# Native diagonal GIF sizes: ASUS's stock art is 74x36, the GA402 lid itself reads 74x39
STOCK_NATIVE_SIZE = (74, 36)
GA402_NATIVE_SIZE = (74, 39)

FOLDERS_TEMPLATE = """\
# Extra folders of GIFs for the AniMe Matrix Selector, one per line, shown in this order
# after the stock and Armoury Crate animations, before the Originals. Optionally name the section:
#   My GIFs = ~/Pictures/lid-gifs
#   ~/Pictures/lid-gifs          (shown as "lid-gifs")
"""


def default_config_dir():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "anime-matrix")


def system_data_dirs():
    data_dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [d for d in data_dirs.split(":") if d] + ["/usr/local/share", "/usr/share"]


def default_stock_dir():
    """asusd's bundled GIFs: /usr/share/asusd/anime, or wherever the distro put it."""
    for base in system_data_dirs():
        path = os.path.join(base, "asusd", "anime")
        if os.path.isdir(path):
            return path
    return "/usr/share/asusd/anime"


def default_armoury_crate_dir():
    """The downloaded Armoury Crate animations, this user's copy first; "" if none."""
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    for base in [data_home] + system_data_dirs():
        path = os.path.join(base, "anime-matrix", "armoury-crate")
        if os.path.isdir(path):
            return path
    return ""


def read_board_name():
    try:
        with open("/sys/class/dmi/id/board_name") as f:
            return f.read().strip()
    except OSError:
        return ""


def lid_model_for(board):
    """The AniMe panel type for a board name, matched the same way asusd does."""
    return next((model for model in LID_MODELS if board.startswith(model)), None)


@dataclass(frozen=True)
class Config:
    config_dir: str
    stock_dir: str
    board_name: str = ""
    originals_dir: str = ORIGINALS_DIR
    armoury_crate_dir: str = ""  # "" when the Armoury Crate animations aren't installed

    @classmethod
    def detect(cls):
        return cls(default_config_dir(), default_stock_dir(), read_board_name(),
                   armoury_crate_dir=default_armoury_crate_dir())

    @property
    def lid_model(self):
        return lid_model_for(self.board_name)

    @property
    def lid_simulated(self):
        """The lid preview and the Originals are drawn for the GA402's LED layout."""
        return self.lid_model == "GA402"

    @property
    def native_sizes(self):
        if self.lid_simulated:
            return frozenset({STOCK_NATIVE_SIZE, GA402_NATIVE_SIZE})
        return frozenset({STOCK_NATIVE_SIZE})

    @property
    def originals_category(self):
        return "Originals" if self.lid_simulated else "Originals (made for the GA402)"

    @property
    def active_symlink(self):
        return os.path.join(self.config_dir, "active.gif")

    @property
    def mode_env(self):
        return os.path.join(self.config_dir, "mode.env")

    @property
    def custom_list(self):
        return os.path.join(self.config_dir, "custom-gifs.txt")  # one path per line

    @property
    def folders_list(self):
        return os.path.join(self.config_dir, "folders.conf")  # extra GIF folders to show

    @property
    def default_target(self):
        return os.path.join(self.stock_dir, "asus/rog/Sunset.gif")


def parse_folders(text):
    """(folder, category) pairs from the lines of a folders.conf."""
    folders = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, path = line.partition(" = ")
        if not sep:
            name, path = "", line
        path = os.path.expanduser(os.path.expandvars(path.strip()))
        folders.append((path, name.strip() or os.path.basename(path.rstrip("/"))))
    return folders


def load_user_folders(cfg):
    """folders.conf's folders, writing it as a commented template if it is missing."""
    try:
        with open(cfg.folders_list) as f:
            return parse_folders(f.read())
    except FileNotFoundError:
        pass
    try:
        os.makedirs(cfg.config_dir, exist_ok=True)
        with open(cfg.folders_list, "w") as f:
            f.write(FOLDERS_TEMPLATE)
    except OSError:
        pass  # a read-only config folder just means no template
    return []


def search_directories(cfg):
    """Every (folder, category) to show, in display order."""
    armoury_crate = ARMOURY_CRATE_FOLDERS if cfg.armoury_crate_dir else []
    return ([(os.path.join(cfg.stock_dir, sub), name) for sub, name in STOCK_FOLDERS]
            + [(os.path.join(cfg.armoury_crate_dir, sub), name) for sub, name in armoury_crate]
            + load_user_folders(cfg)
            # Made for the GA402 by animations/make_animations.py
            + [(cfg.originals_dir, cfg.originals_category)])


def get_current_active_path(cfg):
    """The GIF the service plays, or asusd's default when none has been picked."""
    if os.path.islink(cfg.active_symlink):
        target = os.path.realpath(cfg.active_symlink)
        if os.path.exists(target):
            return target
    return cfg.default_target


def load_custom_gifs(cfg):
    try:
        with open(cfg.custom_list) as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []


def remember_custom_gif(cfg, path):
    """Add a GIF picked with Browse to custom-gifs.txt. May raise OSError."""
    paths = load_custom_gifs(cfg)
    if path not in paths:
        os.makedirs(cfg.config_dir, exist_ok=True)
        with open(cfg.custom_list, "w") as f:
            f.write("\n".join(paths + [path]) + "\n")


def is_animation_file(name):
    # Armoury Crate ships a small _thumbnail copy next to each GIF
    return name.endswith(".gif") and not name.endswith("_thumbnail.gif")


def scan_animations(cfg, directories):
    """(category, path) for every GIF in `directories`, then Browse picks and the active GIF."""
    results = []
    seen = set()
    for folder, category in directories:
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if is_animation_file(name) and path not in seen:
                seen.add(path)
                results.append((category, path))

    # GIFs added via Browse live outside the scanned folders
    for path in load_custom_gifs(cfg) + [get_current_active_path(cfg)]:
        if path not in seen and os.path.exists(path):
            seen.add(path)
            results.append((CUSTOM_CATEGORY, path))
    return results
