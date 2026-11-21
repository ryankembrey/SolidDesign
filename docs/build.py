# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Ryan Kembrey <ryan.FreeCAD@gmail.com>
# SPDX-FileNotice: Part of the Solid Design addon.

"""Regenerate everything in docs/ that is made from the workbench's code.

    python docs/build.py            write what changed
    python docs/build.py --check    write nothing; exit 1 if anything is out of date
    python docs/build.py --no-shots leave the screenshots as they are
    python docs/build.py --shots    retake every screenshot
    python docs/build.py --only=tool-fillet,interface   retake only these

Usually run as ``pixi run docs`` (this, then the site build). It reads the
workbench in FreeCAD's command line (freecadcmd) and takes the screenshots in
FreeCAD on a virtual display, both from the pixi environment.

What it writes, and from where, is listed in docs/README.md.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _pipeline.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
