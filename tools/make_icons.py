# SPDX-License-Identifier: LGPL-2.1-or-later
"""Generate the SVG icons.

    python3 tools/make_icons.py            # write the icons
    python3 tools/icon_sheet.py            # and look at them all together

Writes freecad/SolidDesign/resources/icons/*.svg, including the state variants
used in the tree: <name>_error, <name>_warning (badges) and <name>_rolled (faded).

The drawing kit and the rules every icon follows (isometric, simple, green adds,
red removes, otherwise the toolbar's accent) are in tools/icon_kit.py. The icons
themselves are in tools/icon_sets/, one module per toolbar.

The sketch tool uses the Sketcher workbench's icon and the tree's body folders
FreeCAD's folder icon, so neither is drawn here.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "..", "freecad", "SolidDesign", "resources", "icons")

from icon_sets import GROUPS   # noqa: E402


def all_icons():
    icons = {}
    for _title, module in GROUPS:
        for name, fn in module.ICONS.items():
            if name in icons:
                raise SystemExit("icon %s is drawn twice" % name)
            icons[name] = fn
    return icons


def badge(src, color):
    b = ('<circle cx="49" cy="49" r="13" fill="{}" stroke="#ffffff" stroke-width="3"/>'
         '<path d="M49 41 L49 51" stroke="#ffffff" stroke-width="4.5" stroke-linecap="round"/>'
         '<circle cx="49" cy="56.5" r="2.4" fill="#ffffff"/>').format(color)
    return src.replace("\n</svg>", b + "\n</svg>")


def faded(src):
    return src.replace('viewBox="0 0 64 64">', 'viewBox="0 0 64 64"><g opacity="0.35">', 1) \
        .replace("\n</svg>", "</g>\n</svg>")


def main():
    icons = all_icons()
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):                 # drop icons no longer made
        if f.endswith(".svg"):
            os.remove(os.path.join(OUT, f))
    for name, fn in icons.items():
        src = fn()
        for suffix, text in (("", src), ("_error", badge(src, "#d93025")),
                             ("_warning", badge(src, "#e8a200")),
                             ("_rolled", faded(src))):
            with open(os.path.join(OUT, name + suffix + ".svg"), "w") as fh:
                fh.write(text)
    print("wrote", len(os.listdir(OUT)), "icons to", os.path.normpath(OUT))


if __name__ == "__main__":
    main()
