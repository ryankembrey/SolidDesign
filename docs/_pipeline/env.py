# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the Solid Design addon.

"""Paths, and finding FreeCAD.

The page writers need no FreeCAD: everything they say about the workbench comes
from two files made in FreeCAD from its code, ``_data/catalog.json`` (commands,
toolbars, menus, feature properties; made by ``freecadcmd`` on every build) and
``_data/panels.json`` (each tool's panel, made with the screenshots).
"""

import os
import shutil
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
REPO = DOCS.parent
CONTENT = DOCS / "content"
DATA = DOCS / "_data"
AUTHORED = DOCS / "_authored"
CONFIG = DOCS / "zensical.toml"
PACKAGE = REPO / "freecad" / "SolidDesign"
ICONS = PACKAGE / "resources" / "icons"
LOGO = ICONS / "SolidDesign.svg"

SITE = "https://ryankembrey.github.io/SolidDesign/"
REPO_URL = "https://github.com/ryankembrey/SolidDesign"


def freecad(gui: bool) -> str | None:
    """FreeCAD (``gui``) or its command line, from the pixi environment when
    there is one, else from PATH."""
    names = ("freecad", "FreeCAD") if gui else ("freecadcmd", "FreeCADCmd")
    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        for n in names:
            p = Path(prefix) / "bin" / n
            if p.exists():
                return str(p)
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return None


def sealed_env(**extra) -> dict:
    """The environment FreeCAD runs in for the docs: no user site packages, no
    PYTHONPATH, no machine-specific locale or time zone."""
    e = dict(os.environ)
    e.update({"LC_ALL": "C.UTF-8", "TZ": "UTC", "PYTHONPATH": "", "PYTHONNOUSERSITE": "1"})
    e.update(extra)
    return e
