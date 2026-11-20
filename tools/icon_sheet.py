# SPDX-License-Identifier: LGPL-2.1-or-later
"""Draw every icon on one sheet, a row per toolbar, at toolbar sizes and at
64 px, on a light and a dark background, to check they read as one set.

    python3 tools/icon_sheet.py [out.png] [group ...]

Needs rsvg-convert and ImageMagick (montage, convert).
"""

import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from icon_sets import GROUPS   # noqa: E402


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/icon_sheet.png"
    only = set(sys.argv[2:])
    tmp = tempfile.mkdtemp()
    rows = []
    for title, module in GROUPS:
        if only and module.__name__.split(".")[-1] not in only:
            continue
        tiles = []
        for name, fn in module.ICONS.items():
            src = os.path.join(tmp, name + ".svg")
            with open(src, "w") as fh:
                fh.write(fn())
            parts = []
            for size, bg in ((24, "#ffffff"), (32, "#ffffff"), (24, "#3b3f45"), (64, "#ffffff")):
                png = os.path.join(tmp, "%s_%d_%s.png" % (name, size, bg[1:]))
                subprocess.check_call(["rsvg-convert", "-w", str(size), "-h", str(size),
                                       "-b", bg, src, "-o", png])
                parts.append(png)
            tdir = os.path.join(tmp, "tiles")
            os.makedirs(tdir, exist_ok=True)
            tile = os.path.join(tdir, name + ".png")
            subprocess.check_call(
                ["convert", "-background", "#ffffff",
                 "(", parts[0], parts[1], parts[2], "-gravity", "center", "-append", ")",
                 parts[3], "-gravity", "center", "+append", tile])
            tiles.append(tile)
        row = os.path.join(tmp, "row_%s.png" % len(rows))
        subprocess.check_call(["montage", "-label", "%t", "-pointsize", "10"] + tiles +
                              ["-tile", "8x", "-geometry", "+6+4",
                                                     "-background", "#ffffff",
                                                     "-title", title, row])
        rows.append(row)
    subprocess.check_call(["convert"] + rows + ["-background", "#ffffff", "-append", out])
    print(out)


if __name__ == "__main__":
    main()
