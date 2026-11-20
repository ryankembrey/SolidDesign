# SPDX-License-Identifier: LGPL-2.1-or-later
"""curves icons. See tools/icon_kit.py for the rules."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icon_kit import *   # noqa: E402,F401,F403


def _wave(t):
    """A gentle S across the top of the stock block, t in 0..1."""
    return (2 + 14 * t, 7 + 3.5 * math.sin(2 * math.pi * t), 0)


def _bow(t):
    """A single bow across the top of the stock block, bulging toward the
    viewer, t in 0..1."""
    a, c, b = (15, 1), (15, 14), (1, 13)
    return tuple((1 - t) ** 2 * a[j] + 2 * t * (1 - t) * c[j] + t * t * b[j] for j in (0, 1)) + (0,)


def _at(p, z):
    return (p[0], p[1], z)


def split_line():
    """A grey block whose top and front faces are split by a magenta line."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 10, NEUTRAL)
    curve_mark(s, [(9, 0, 10), (9, 14, 10), (9, 14, 0)], width=MARK + 0.6)
    return s.render()


def projected_curve():
    """A sketch curve above a grey block (INK), projected down along INK dashed
    lines onto its top face as a magenta curve."""
    s = Scene()
    z = 8
    s.box(0, 0, 0, 18, 14, z, NEUTRAL)
    pts = [_bow(i / 20.0) for i in range(21)]
    s.line([_at(p, z + 12) for p in pts], INK, 2.2, layer=10)
    for i in (0, 10, 20):
        path_mark(s, [_at(pts[i], z + 12), _at(pts[i], z)], layer=9)
    curve_mark(s, [_at(p, z) for p in pts], width=MARK + 0.6)
    return s.render()


def composite_curve():
    """A straight, an arc and a straight joined into one magenta curve; INK dots
    at the joints."""
    s = Scene()
    r = 6
    arc = [(10 + r * math.sin(math.radians(a)), r - r * math.cos(math.radians(a)), 0)
           for a in range(0, 181, 10)]
    curve_mark(s, [(0, 0, 0)] + arc + [(0, 2 * r, 0)], width=MARK + 0.6)
    dots(s, [(10, 0, 0), (10, 2 * r, 0)], INK, 3.6)
    return s.render()


def curve_xyz():
    """A magenta 3D curve through INK points, rising through an INK x/y/z triad."""
    s = Scene()

    def at(t):
        return (2 + 14 * t, 13 - 12 * t, 2 + 14 * t + 4 * math.sin(2 * math.pi * t))
    curve_mark(s, [at(k / 40.0) for k in range(41)], width=MARK + 0.6)
    dots(s, [at(t) for t in (0.0, 0.33, 0.67, 1.0)], INK, 3.4)
    for d in ((10, 0, 0), (0, 10, 0), (0, 0, 10)):
        s.arrow((0, 0, 0), d, INK, 2.2)
    return s.render()


def curve_points():
    """A magenta curve through reference points (INK dots) on a grey block's top."""
    s = Scene()
    z = 10
    s.box(0, 0, 0, 18, 14, z, NEUTRAL)
    pts = [_at(_wave(i / 24.0), z) for i in range(25)]
    curve_mark(s, pts, width=MARK + 0.6)
    dots(s, [pts[0], pts[6], pts[18], pts[24]], INK, 3.4)
    return s.render()


def helix():
    """A magenta helix round an INK axis."""
    s = Scene()
    turns, r, h = 3.0, 8.0, 20.0
    pts = []
    for i in range(int(turns * 36) + 1):
        a = math.radians(i * 10.0)
        pts.append((r * math.cos(a), r * math.sin(a), h * i / (turns * 36.0)))
    axis_mark(s, (0, 0, -3), (0, 0, h + 3), layer=8)
    curve_mark(s, pts, width=MARK + 0.6)
    return s.render()


ICONS = {
    "SplitLine": split_line, "ProjectedCurve": projected_curve,
    "CompositeCurve": composite_curve, "CurveXYZ": curve_xyz, "CurvePoints": curve_points,
    "Helix": helix,
}
