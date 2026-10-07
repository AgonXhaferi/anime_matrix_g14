# AniMe Matrix Selector

A small GTK4 app for picking the animation on the AniMe Matrix lid display of an
ASUS ROG Zephyrus G14 (tested on a GA402RK), on top of [asusctl](https://gitlab.com/asus-linux/asusctl).

## How it works

- `anime-matrix-selector` (the app) shows GIFs from the stock asusd folders, your
  `~/Pictures/ArmouryCrate_GIFs` folders and any GIF you add with *Browse* as a grid of
  animated thumbnails, grouped by folder. Start typing anywhere to search by name or
  category. The playing animation has a green outline, and the window opens on it.
- Thumbnails load only when scrolled into view, keep at most 120 frames each, and pause
  while the window isn't focused, to keep memory and battery use down.
- *Set as Main* points `~/.config/anime-matrix/active.gif` at your pick and restarts
  `anime-matrix.service`, a systemd user service that plays it with `asusctl` on a loop.
- GIFs drawn for the native 74×36 LED grid play pixel-perfect (`asusctl anime pixel-gif`);
  any other size is scaled to fit (`asusctl anime gif`). The choice is saved in `mode.env`.
- The preview has an *On the lid* view that simulates the GA402's 1,449 LEDs as seen from
  outside the lid, using asusctl 6.3.8's own geometry and sampling (diagonal mapping for
  native GIFs, 16-sample averaging for scaled ones). *Plain GIF* shows the file itself.
  Native means 74×36 (ASUS's stock art) or 74×39 (the GA402's full diagonal grid).
- *Display Settings* shows asusd's brightness and "off when unplugged / lid closed /
  suspended" options and changes them instantly over D-Bus. It also updates when they
  are changed elsewhere, e.g. with `asusctl anime --brightness`.
- *Turn Off* stops and disables the service and blanks the display, so it stays off
  across reboots until you pick an animation again.

## Install

Needs `asusctl`/`asusd`, Python 3 with GTK4 bindings (`python3-gobject`, `gtk4`) and Pillow
(`python3-pillow`).

```sh
./install.sh
```

The app in `~/.local/bin` is a link to this folder, so edits here apply on the next launch.
The service and launcher are copies: re-run `./install.sh` after changing them.

## Files outside this folder

Your settings live in `~/.config/anime-matrix/` and are not part of the repo:

| File | Purpose |
|---|---|
| `active.gif` | Link to the animation currently playing |
| `mode.env` | `pixel-gif` or `gif`, written by the app for the service |
| `custom-gifs.txt` | GIFs added with *Browse*, one path per line |
