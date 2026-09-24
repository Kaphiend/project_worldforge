"""Resolve bundled resources and writable per-user data locations.

Source runs read resources beside this file and keep saves in the project
folder. PyInstaller builds read bundled resources from ``sys._MEIPASS`` and
write saves and user mods to the operating system's per-user data directory.
"""
import os
from pathlib import Path
import sys


def resource_path(*parts):
    """Return an absolute path to a bundled project resource."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root.joinpath(*parts)


def user_data_root():
    """Return the root directory for writable per-user Worldforge data."""
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
        elif sys.platform == "darwin":
            base = Path.home() / "Library/Application Support"
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
        root = base / "Worldforge"
    else:
        root = resource_path()
    return root


def user_data_path(*parts):
    """Return a writable Worldforge path and create its directory."""
    path = user_data_root().joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def asset_path(path):
    """Resolve an art asset from the bundle, then the user data directory."""
    bundled = resource_path(path)
    if bundled.is_file():
        return bundled
    return user_data_root() / path
