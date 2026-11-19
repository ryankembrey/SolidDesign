# SPDX-License-Identifier: LGPL-2.1-or-later
"""Solid Design: a SolidWorks-style, multi-body part modelling workbench for FreeCAD."""

import os

__version__ = "0.1.0"

PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
ICON_DIR = os.path.join(PACKAGE_DIR, "resources", "icons")


def icon(name):
    """Absolute path of an icon in resources/icons (name without extension)."""
    return os.path.join(ICON_DIR, name + ".svg")
