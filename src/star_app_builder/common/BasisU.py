"""Resolver for the basisu binary bundled inside the installed package.

When the wheel is built, hatch_build.py embeds the compiled ``basisu``
executable at ``star_app_builder/bin/<basisu>``. This module locates it at
runtime so callers do not need to pass a deps directory on the command line.
"""

import os
import sys


def get_bundled_basisu_dir():
    """Absolute path to the ``bin`` directory shipped with the package."""
    package_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(package_root, "bin")


def get_bundled_basisu_path():
    """Return the bundled basisu executable path, or None if not present."""
    bin_dir = get_bundled_basisu_dir()
    names = (
        ("basisu.exe", "basisu")
        if sys.platform == "win32"
        else ("basisu", "basisu.exe")
    )
    for name in names:
        candidate = os.path.join(bin_dir, name)
        if os.path.isfile(candidate):
            return candidate
    return None
