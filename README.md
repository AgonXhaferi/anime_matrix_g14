# AniMe Matrix Selector

A small GTK4 app for picking the animation on the AniMe Matrix lid display of an
ASUS ROG Zephyrus G14 (tested on a GA402RK), on top of [asusctl](https://gitlab.com/asus-linux/asusctl).

## How it works

- `anime-matrix-selector` (the app) lists GIFs from the stock asusd folders, your
  `~/Pictures/ArmouryCrate_GIFs` folders and any GIF you add with *Browse*, with a live preview.
- *Set as Main* points `~/.config/anime-matrix/active.gif` at your pick and restarts
  `anime-matrix.service`, a systemd user service that plays it with `asusctl` on a loop.
- GIFs drawn for the native 74×36 LED grid play pixel-perfect (`asusctl anime pixel-gif`);
  any other size is scaled to fit (`asusctl anime gif`). The choice is saved in `mode.env`.
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
