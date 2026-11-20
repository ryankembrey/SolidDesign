# SPDX-License-Identifier: LGPL-2.1-or-later
"""bodies icons. See tools/icon_kit.py for the rules."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icon_kit import *   # noqa: E402,F401,F403

# The body the tool makes or changes is BODY violet, a body or face it removes is
# CUT red, what it leaves alone NEUTRAL; arrows and helper planes are INK.


def _quad(s, pts, pal, hint, layer):
    s.add(Face([pts], pal, hint=hint, layer=layer))


def _sides(s, x0, y0, x1, y1, z, pal, layer=1):
    """A block's four sides and bottom, from z=0 up to z, without its top."""
    c = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, z / 2.0)
    for q in ([(x1, y0, 0), (x1, y1, 0), (x1, y1, z), (x1, y0, z)],
              [(x0, y0, 0), (x0, y1, 0), (x0, y1, z), (x0, y0, z)],
              [(x0, y1, 0), (x1, y1, 0), (x1, y1, z), (x0, y1, z)],
              [(x0, y0, 0), (x1, y0, 0), (x1, y0, z), (x0, y0, z)],
              rect(x0, y0, x1, y1, 0)):
        s.add(Face([q], pal, hint=sub(centroid(q), c), layer=layer))


def _bumpy_top(s, x0, y0, x1, y1, z, bump, pal, n=12, layer=1):
    """A top face at z raised by bump(u, v) (u, v in 0..1, zero on the border)."""
    def P(i, j):
        u, v = i / float(n), j / float(n)
        return (x0 + (x1 - x0) * u, y0 + (y1 - y0) * v, z + bump(u, v))

    for i in range(n):
        for j in range(n):
            q = [P(i, j), P(i + 1, j), P(i + 1, j + 1), P(i, j + 1)]
            s.add(Face([q], pal, hint=(0, 0, 1), layer=layer))


def _ball(s, cx, cy, cz, r, pal, n=24, m=10, layer=1):
    """A sphere."""
    rings = []
    for k in range(m + 1):
        a = math.pi * k / m - math.pi / 2
        rings.append(circle(cx, cy, cz + r * math.sin(a), max(r * math.cos(a), 1e-3), n))
    for a, b in zip(rings[:-1], rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            q = [a[i], a[j], b[j], b[i]]
            m_ = centroid(q)
            s.add(Face([q], pal, hint=sub(m_, (cx, cy, cz)), layer=layer))


def combine():
    """A tall violet block and a low one merged where they overlap: one body."""
    s = Scene()
    s.box(0, 0, 0, 9, 9, 15, BODY, layer=1)
    # The low block's visible faces, less what lies inside the tall one.
    top = [(9, 4, 7), (20, 4, 7), (20, 20, 7), (4, 20, 7), (4, 9, 7), (9, 9, 7)]
    _quad(s, top, BODY, (0, 0, 1), 2)
    _quad(s, [(20, 4, 0), (20, 20, 0), (20, 20, 7), (20, 4, 7)], BODY, (1, 0, 0), 2)
    _quad(s, [(4, 20, 0), (20, 20, 0), (20, 20, 7), (4, 20, 7)], BODY, (0, 1, 0), 2)
    return s.render()


def split():
    """A violet body cut in two by a dashed cutting plane, the halves apart."""
    s = Scene()
    s.box(0, 0, 0, 8, 14, 12, BODY, layer=1)
    s.line([(11, -3, -2), (11, 17, -2), (11, 17, 15), (11, -3, 15), (11, -3, -2)],
           dash="3.5 2.5", layer=2)
    s.box(14, 0, 0, 22, 14, 12, BODY, layer=3)
    return s.render()


def delete_body():
    """A grey body, and beside it a red body being removed."""
    s = Scene()
    s.box(0, 0, 0, 10, 10, 10, NEUTRAL, layer=1)
    s.box(14, 6, 0, 24, 16, 10, CUT, layer=2)
    return s.render()


def move_copy():
    """A grey body and its violet copy, moved along an arrow."""
    s = Scene()
    s.box(0, 0, 0, 10, 10, 10, NEUTRAL, layer=1)
    s.box(13, -11, 0, 23, -1, 10, BODY, layer=2)
    s.arrow((3, 7, 17), (17, -7, 17))
    return s.render()


def flex():
    """A violet bar bent over."""
    s = Scene()
    inner, outer = [], []
    for k in range(13):
        a = math.radians(90.0 * k / 12)
        inner.append((14 - 8 * math.cos(a), 8 * math.sin(a)))
        outer.append((14 - 16 * math.cos(a), 16 * math.sin(a)))
    s.prism_y(inner + list(reversed(outer)), 0, 10, BODY)
    return s.render()


def deform():
    """A violet block whose top is pulled up into a bump, an arrow up."""
    s = Scene()

    def bump(u, v):
        d = math.hypot(u - 0.5, v - 0.5) / 0.5
        return 9 * (0.5 + 0.5 * math.cos(math.pi * d)) if d < 1 else 0.0

    _sides(s, 0, 0, 20, 20, 7, BODY)
    _bumpy_top(s, 0, 0, 20, 20, 7, bump, BODY)
    s.arrow((10, 10, 17), (10, 10, 26))
    return s.render()


def indent():
    """A violet ball above the dent it pressed into a grey block."""
    s = Scene()
    rd, d = 6.0, 3.0
    big = (rd * rd + d * d) / (2 * d)
    z = 8
    top = circle(10, 10, z, rd, 32)
    s.box(0, 0, 0, 20, 20, z, NEUTRAL, holes=[top], layer=1)
    rings = []
    for k in range(5):
        h = d * k / 4.0                     # depth below the top
        r = math.sqrt(max(big * big - (big - d + h) ** 2, 0)) if k < 4 else 0.01
        rings.append(circle(10, 10, z - h, r, 32))
    for a, b in zip(rings[:-1], rings[1:]):
        for i in range(32):
            j = (i + 1) % 32
            q = [a[i], a[j], b[j], b[i]]
            m = centroid(q)
            s.add(Face([q], NEUTRAL, hint=(10 - m[0], 10 - m[1], 0.5), layer=0))
    _ball(s, 10, 10, z + big + 3, big, BODY, layer=2)
    return s.render()


def freeform():
    """A grey block whose top is a violet face pushed and pulled at INK
    control points."""
    s = Scene()
    n, w, h = 24, 20, 9

    def z(x):
        return h + 3.5 * math.sin(2 * math.pi * x / w)

    wave = [(w * i / n, z(w * i / n)) for i in range(n + 1)]
    s.prism_y([(0, 0)] + wave + [(w, 0)], 0, 14, NEUTRAL, accent=range(1, n + 1),
              accent_pal=BODY)
    dots(s, [(w * 0.25, 7, z(w * 0.25)), (w * 0.75, 7, z(w * 0.75))], r=3.2)
    s.arrow((w * 0.25, 7, z(w * 0.25) + 2), (w * 0.25, 7, z(w * 0.25) + 9))
    return s.render()


def scale():
    """A small grey block and its bigger violet copy, an arrow between."""
    s = Scene()
    s.box(0, 15, 0, 7, 22, 6, NEUTRAL, layer=1)
    s.box(11, 0, 0, 25, 14, 12, BODY, layer=2)
    s.arrow((5, 16, 8), (12, 9, 15))
    return s.render()


def move_face():
    """A grey block whose violet top face has moved up an arrow; the old top
    dashed."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 14, NEUTRAL, top_pal=BODY)
    s.line([(0, 14, 8), (18, 14, 8), (18, 0, 8)], dash="3.5 2.5")
    s.arrow((9, 7, 14.5), (9, 7, 23))
    return s.render()


def delete_face():
    """A grey block with its top open, the red top face lifted away."""
    s = Scene()
    x1, y1, z = 18, 14, 10
    s.add(Face([[(x1, 0, 0), (x1, y1, 0), (x1, y1, z), (x1, 0, z)]], NEUTRAL,
               hint=(1, 0, 0), layer=1))
    s.add(Face([[(0, y1, 0), (x1, y1, 0), (x1, y1, z), (0, y1, z)]], NEUTRAL,
               hint=(0, 1, 0), layer=1))
    s.walls(rect(0, 0, x1, y1, z), z, NEUTRAL, layer=0)
    sheet(s, 0, 0, x1, y1, z + 8, pal=CUT, layer=2)
    return s.render()


def replace_face():
    """A grey block whose flat top (dashed) is replaced by a violet curved face."""
    s = Scene()
    n = 12
    w, h = 18, 9
    arc = [(w * i / n, h + 5 * math.sin(math.pi * i / n)) for i in range(n + 1)]
    s.prism_y([(0, 0)] + arc + [(w, 0)], 0, 14, NEUTRAL, accent=range(1, n + 1),
              accent_pal=BODY)
    s.line([(0, 14, h), (w, 14, h)], dash="3.5 2.5")
    return s.render()


def body_solid():
    """Tree icon for a solid body: a plain violet block."""
    s = Scene()
    s.box(0, 0, 0, 16, 14, 12, BODY)
    return s.render()


ICONS = {
    "Combine": combine, "Split": split, "DeleteBody": delete_body, "MoveCopy": move_copy,
    "Flex": flex, "Deform": deform, "Indent": indent, "Freeform": freeform,
    "Scale": scale, "MoveFace": move_face, "DeleteFace": delete_face,
    "ReplaceFace": replace_face, "BodySolid": body_solid,
}
