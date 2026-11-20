# SPDX-License-Identifier: LGPL-2.1-or-later
"""patterns icons. See tools/icon_kit.py for the rules."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icon_kit import *   # noqa: E402,F401,F403

# The seed (the feature being patterned) is NEUTRAL, the copies the tool makes are
# FEATURE blue; paths, axes and arrows are INK.


def _cube(s, x, y, a, pal, h=None, layer=1):
    """A block of side *a* (height *h*) standing on the ground at (x, y)."""
    s.box(x, y, 0, x + a, y + a, a if h is None else h, pal, layer=layer)


def _seed(k):
    return NEUTRAL if k == 0 else FEATURE


def linear_pattern():
    """A grey cube and two blue copies in a row along an arrow."""
    s = Scene()
    for k in range(3):
        _cube(s, k * 13, 0, 8, _seed(k), layer=1 + k)
    s.arrow((0, 13, 0), (36, 13, 0))
    return s.render()


def circular_pattern():
    """A grey cube and three blue copies round an axis."""
    s = Scene()
    for k in range(4):
        a = math.radians(135 + 90 * k)
        x, y = 12 * math.cos(a), 12 * math.sin(a)
        _cube(s, x - 3.5, y - 3.5, 7, _seed(k), layer=1 + int(x + y + 20))
    axis_mark(s, (0, 0, 0), (0, 0, 24))
    return s.render()


def curve_pattern():
    """A grey cube and blue copies along a dashed arching curve."""
    s = Scene()

    def at(t):
        a = math.radians(180 - 180 * t)
        r = 10 * math.cos(a)
        return (r, -r, 15 * math.sin(a))

    path_mark(s, [at(i / 30.0) for i in range(31)], layer=0)
    for k, t in enumerate((0.0, 0.5, 1.0)):
        x, y, z = at(t)
        s.box(x - 3.5, y - 3.5, z - 3.5, x + 3.5, y + 3.5, z + 3.5, _seed(k), layer=1 + k)
    return s.render()


def sketch_pattern():
    """A grey cube and blue copies on scattered sketch points, inside a dashed
    sketch outline; one point still bare."""
    s = Scene()
    s.line([(0, 0, 0), (34, 0, 0), (34, 28, 0), (0, 28, 0), (0, 0, 0)], dash="3.5 2.5",
           layer=0)
    pts = ((7, 6), (25, 9), (10, 21), (26, 22))
    for k, (x, y) in enumerate(pts[:3]):
        _cube(s, x - 3.5, y - 3.5, 7, _seed(k), layer=1 + k)
    dots(s, [(pts[3][0], pts[3][1], 0)], r=3.2, layer=0)
    return s.render()


def table_pattern():
    """A small table (rows of X, Y) beside a grey cube and its blue copies."""
    s = Scene()
    for k, (x, y) in enumerate(((0, 0), (11, 3), (4, 13))):
        _cube(s, x, y, 7, _seed(k), layer=1 + k)
    out = s.render(box=(26, 8, 62, 58))
    rows = "".join('<path d="M4 %d L24 %d"/>' % (y, y) for y in (24, 34, 44))
    table = ('<rect x="4" y="14" width="20" height="40" rx="2" fill="#ffffff" stroke="%s" '
             'stroke-width="%.1f"/><g stroke="%s" stroke-width="%.1f">%s'
             '<path d="M14 14 L14 54"/></g>' % (INK, LINE, INK, LINE, rows))
    return out.replace("\n</svg>", "\n" + table + "\n</svg>")


def fill_pattern():
    """A grey plate whose top face is filled with blue studs, the seed grey."""
    s = Scene()
    s.box(0, 0, 0, 28, 28, 4, NEUTRAL)
    k = 0
    for j in range(3):
        for i in range(3):
            s.cylinder(5 + i * 9, 5 + j * 9, 4, 7, 3, _seed(k), n=24, layer=2 + i + j)
            k += 1
    return s.render()


def variable_pattern():
    """A grey block and blue copies, each taller than the last, along an arrow."""
    s = Scene()
    for k, h in enumerate((6, 10, 15)):
        _cube(s, k * 13, 0, 8, _seed(k), h=h, layer=1 + k)
    s.arrow((0, 13, 0), (36, 13, 0))
    return s.render()


def mirror():
    """A grey L-block, a dashed mirror plane, and the blue mirrored copy."""
    s = Scene()
    prof = [(-16, 0), (-5, 0), (-5, 5), (-11, 5), (-11, 12), (-16, 12)]
    s.prism_y(prof, 0, 10, NEUTRAL, layer=1)
    s.line([(0, -2, 0), (0, 12, 0), (0, 12, 14), (0, -2, 14), (0, -2, 0)],
           dash="3.5 2.5", layer=2)
    s.prism_y([(-x, z) for x, z in reversed(prof)], 0, 10, FEATURE, layer=3)
    return s.render()


ICONS = {
    "LinearPattern": linear_pattern, "CircularPattern": circular_pattern,
    "CurvePattern": curve_pattern, "SketchPattern": sketch_pattern,
    "TablePattern": table_pattern, "FillPattern": fill_pattern,
    "VariablePattern": variable_pattern, "Mirror": mirror,
}
