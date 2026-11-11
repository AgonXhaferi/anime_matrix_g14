"""Driving the lid through asusctl and the systemd user service.

Everything here blocks (it runs commands), so the UI calls it from a background thread.
No GTK in here.
"""
import os
import shutil
import subprocess
import time
from dataclasses import dataclass

from PIL import Image

from .config import SERVICE, get_current_active_path

COMMAND_TIMEOUT = 15  # seconds


def run_cmd(args):
    """Run a command, returning (ok, error message)."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    # asusctl reports some failures with exit code 0, so also look for its "Error:" line
    err = find_error(res.stdout + res.stderr)
    if res.returncode != 0 or err:
        return False, err or f"exit code {res.returncode}"
    return True, ""


def find_error(output):
    """The message of the first asusctl "Error..." line in `output`, or ""."""
    for line in output.splitlines():
        if line.startswith("Error"):
            return line.split(":", 1)[-1].strip()
    return ""


def check_asusctl():
    """None if asusctl can play GIFs the way the service does, else why not."""
    if not shutil.which("asusctl"):
        return "asusctl not found: install asusctl/asusd to drive the lid"
    try:
        res = subprocess.run(["asusctl", "anime", "--help"], capture_output=True, text=True,
                             timeout=COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"Couldn't run asusctl: {e}"
    if "pixel-gif" not in res.stdout + res.stderr:
        return "This asusctl is too old: the selector needs asusctl 6 or newer (anime pixel-gif)"
    return None


def anime_command_for(path, native_sizes):
    """pixel-gif only renders correctly for GIFs drawn for the diagonal LED grid."""
    try:
        with Image.open(path) as im:
            return "pixel-gif" if im.size in native_sizes else "gif"
    except (OSError, ValueError):
        return "gif"


def service_props():
    try:
        res = subprocess.run(
            ["systemctl", "--user", "show", SERVICE,
             "-p", "ActiveState,SubState,NRestarts,ConditionResult"],
            capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    return dict(line.split("=", 1) for line in res.stdout.splitlines() if "=" in line)


@dataclass(frozen=True)
class ServiceState:
    playing: bool
    active_path: str
    active_missing: bool  # active.gif points at a file that no longer exists


def service_state(cfg):
    playing = service_props().get("ActiveState") == "active"
    missing = os.path.islink(cfg.active_symlink) and not os.path.exists(cfg.active_symlink)
    return ServiceState(playing, get_current_active_path(cfg), missing)


def _replace_symlink(target, link):
    """Point `link` at `target` in one step, so the service never sees it missing."""
    tmp = f"{link}.new"
    if os.path.lexists(tmp):
        os.remove(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, link)


def _replace_file(path, text):
    tmp = f"{path}.new"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


@dataclass(frozen=True)
class StartCheck:
    """What to compare against a moment later to tell whether the start stuck."""
    restarts_before: str
    started_at: float


def apply_animation(cfg, path):
    """Make `path` the running animation. Returns (error or None, StartCheck or None)."""
    ok, err = run_cmd(["asusctl", "anime", "--enable-display", "true"])
    if not ok:
        return f"Couldn't enable the lid display: {err}", None

    # Point active.gif at the pick, and tell the service whether to play it
    # pixel-perfect or scaled
    try:
        os.makedirs(cfg.config_dir, exist_ok=True)
        _replace_symlink(path, cfg.active_symlink)
        _replace_file(cfg.mode_env, f"ANIME_CMD={anime_command_for(path, cfg.native_sizes)}\n")
    except OSError as e:
        return f"Couldn't save the pick in {cfg.config_dir}: {e.strerror or e}", None

    # Re-enable (Turn Off disables it) and restart the background service
    started_at = time.time()
    ok, err = run_cmd(["systemctl", "--user", "enable", SERVICE])
    if ok:
        ok, err = run_cmd(["systemctl", "--user", "restart", SERVICE])
    if not ok:
        return f"Couldn't restart the service: {err}", None
    return None, StartCheck(service_props().get("NRestarts", "0"), started_at)


def verify_started(check):
    """Called a moment after apply_animation: None if still playing, else why it stopped."""
    props = service_props()
    if props.get("SubState") == "running" and props.get("NRestarts", "0") == check.restarts_before:
        return None
    if props.get("ConditionResult") == "no":
        return "the GIF file is missing"
    return last_service_error(check.started_at) or props.get("ActiveState", "not running")


def last_service_error(since):
    """The last asusctl error the service logged since `since` (a timestamp), or ""."""
    try:
        res = subprocess.run(
            ["journalctl", "--user", "-u", SERVICE, "--since", f"@{int(since)}",
             "-o", "cat", "--no-pager"],
            capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    errors = [err for err in map(find_error, res.stdout.splitlines()) if err]
    return errors[-1] if errors else ""


def turn_off_matrix():
    """Stop the animation and keep it off across reboots. Returns an error or None."""
    for args in (["systemctl", "--user", "disable", "--now", SERVICE],
                 ["asusctl", "anime", "--clear"],
                 ["asusctl", "anime", "--enable-display", "false"]):
        ok, err = run_cmd(args)
        if not ok:
            return err
    return None
