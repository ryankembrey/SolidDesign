# SPDX-License-Identifier: LGPL-2.1-or-later
"""Features toolbar. Added material green, removed material red, a change to
existing material (a round, a bevel, a lean) blue. See tools/icon_kit.py."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icon_kit import *   # noqa: E402,F401,F403


def extrude_add():
    s = Scene()
    s.box(0, 0, 0, 16, 12, 12, ADD)
    s.arrow((8, 6, 12.5), (8, 6, 25))
    return s.render()


def extrude_cut():
    s = Scene()
    hole = rect(5, 4, 15, 12, 8)
    s.box(0, 0, 0, 20, 16, 8, NEUTRAL, holes=[hole])
    s.walls(hole, 5, CUT)
    s.arrow((10, 8, 22), (10, 8, 9))
    return s.render()


def fillet():
    s = Scene()
    w, h, r = 18, 14, 7
    arc = [(w - r + r * math.cos(math.radians(a)), h - r + r * math.sin(math.radians(a)))
           for a in range(6, 90, 6)]
    prof = [(0, 0), (w, 0), (w, h - r)] + arc + [(w - r, h), (0, h)]
    s.prism_y(prof, 0, 14, NEUTRAL, accent=set(range(2, 3 + len(arc))), accent_pal=FEATURE)
    return s.render()


def chamfer():
    s = Scene()
    w, h, c = 18, 14, 7
    s.prism_y([(0, 0), (w, 0), (w, h - c), (w - c, h), (0, h)], 0, 14, NEUTRAL,
              accent={2}, accent_pal=FEATURE)
    return s.render()



# ---------------------------------------------------------------- helpers

def _ring_bar(s, outer, inner, z0, z1, pal, layer=1):
    """A bar bent round the z axis (an annular sector, *outer*/*inner* arcs as
    (x, y)) from z0 to z1: its top, its curved sides and its two ends."""
    top = [(x, y, z1) for x, y in outer] + [(x, y, z1) for x, y in reversed(inner)]
    s.add(Face([top], pal, hint=(0, 0, 1), layer=layer))
    for ring, sgn in ((outer, 1), (inner, -1)):
        for (xa, ya), (xb, yb) in zip(ring[:-1], ring[1:]):
            q = [(xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1)]
            m = centroid(q)
            s.add(Face([q], pal, hint=(sgn * m[0], sgn * m[1], 0), layer=layer))
    for k in (0, -1):
        (xo, yo), (xi, yi) = outer[k], inner[k]
        q = [(xo, yo, z0), (xi, yi, z0), (xi, yi, z1), (xo, yo, z1)]
        m, o = centroid(q), centroid([(x, y, 0) for x, y in outer + inner])
        s.add(Face([q], pal, hint=(m[0] - o[0], m[1] - o[1], 0), layer=layer))


def _ring_groove(s, outer, inner, ox, oy, z, depth, pal):
    """The walls and floor of a curved groove under a top face at z (seen from
    inside); the arcs are round (ox, oy). Returns the opening loop."""
    outer = [(x + ox, y + oy) for x, y in outer]
    inner = [(x + ox, y + oy) for x, y in inner]
    for ring, sgn in ((outer, -1), (inner, 1)):
        for (xa, ya), (xb, yb) in zip(ring[:-1], ring[1:]):
            q = [(xa, ya, z), (xb, yb, z), (xb, yb, z - depth), (xa, ya, z - depth)]
            m = centroid(q)
            s.add(Face([q], pal, hint=(sgn * (m[0] - ox), sgn * (m[1] - oy), 0), layer=0))
    mid = centroid([(x, y, 0) for x, y in outer + inner])
    for k in (0, -1):
        (xo, yo), (xi, yi) = outer[k], inner[k]
        q = [(xo, yo, z), (xi, yi, z), (xi, yi, z - depth), (xo, yo, z - depth)]
        m = centroid(q)
        s.add(Face([q], pal, hint=(mid[0] - m[0], mid[1] - m[1], 0), layer=0))
    loop = [(x, y, z) for x, y in outer] + [(x, y, z) for x, y in reversed(inner)]
    s.add(Face([[(x, y, z - depth) for x, y, _z in loop]], pal, hint=(0, 0, 1), layer=0))
    return loop


def _pillow(cx, cy, z, half, bulge, n=48):
    """A square whose sides bulge out by *bulge* (0 = a plain square), as *n*
    points starting on the same side as circle()."""
    pts = []
    for i in range(n):
        a = math.radians(360.0 * i / n)
        c, sn = math.cos(a), math.sin(a)
        k = half / max(abs(c), abs(sn)) * (1 + bulge * math.cos(2 * a) ** 2)
        pts.append((cx + c * k, cy + sn * k, z))
    return pts


def _dome(s, cx, cy, z, r, h, pal, layer=2, n=48, rings=12):
    """A round cap of height *h* over a circle of radius *r* at height z."""
    loops = []
    for k in range(rings):
        t = k / float(rings)
        loops.append(circle(cx, cy, z + h * math.sin(t * math.pi / 2),
                            r * math.cos(t * math.pi / 2), n))
    apex = (cx, cy, z + h)
    for a, b in zip(loops, loops[1:] + [None]):
        for i in range(n):
            j = (i + 1) % n
            q = [a[i], a[j], b[j], b[i]] if b else [a[i], a[j], apex]
            m = centroid(q)
            s.add(Face([q], pal, hint=(m[0] - cx, m[1] - cy, m[2] - z + 0.01), layer=layer))


def _counterbore(s, cx, cy, z, r1, d1, r2, d2, pal):
    """A counterbored hole under a top face at z. Returns the opening loop."""
    top = circle(cx, cy, z, r1)
    step = circle(cx, cy, z - d1, r2)
    s.walls(top, d1, pal, floor=False)
    s.add(Face([circle(cx, cy, z - d1, r1), step], pal, hint=(0, 0, 1), layer=0))
    s.walls(step, d2, pal)
    return top


def _helix_front(s, r, z0, z1, turns, color, width):
    """A helix round the z axis, drawn only where it faces the viewer."""
    steps = int(turns * 36)
    run = []
    for i in range(steps + 1):
        a = math.radians(i * 10.0 - 45.0)
        q = (r * math.cos(a), r * math.sin(a), z0 + (z1 - z0) * i / float(steps))
        if q[0] + q[1] > 0.0:
            run.append(q)
        elif run:
            s.line(run, color, width, layer=10)
            run = []
    if run:
        s.line(run, color, width, layer=10)


def _bolt(s):
    """A grey bolt: a round head and a shaft. Returns the shaft radius and top."""
    s.cylinder(0, 0, 0, 5, 10, NEUTRAL)
    s.cylinder(0, 0, 5, 22, 6.5, NEUTRAL, layer=2)
    return 6.5, 22.0


# ---------------------------------------------------------------- sketch tools

def revolve_add():
    """A green stepped round part, its INK centre axis and a turning arrow."""
    s = Scene()
    s.cylinder(0, 0, 0, 5, 10, ADD)
    s.cylinder(0, 0, 5, 14, 6, ADD, layer=2)
    axis_mark(s, (0, 0, -3), (0, 0, 20))
    s.arc_arrow(circle(0, 0, 2.5, 13.5, 24, -40, 120, closed=False))
    return s.render()


def revolve_cut():
    """A grey round part with a red groove turned round it, its INK axis."""
    s = Scene()
    s.cylinder(0, 0, 0, 4, 10, NEUTRAL, top=False)
    s.add(Face([circle(0, 0, 4, 10), circle(0, 0, 4, 5)], CUT, hint=(0, 0, 1), layer=2))
    s.cylinder(0, 0, 4, 12, 5, CUT, layer=3, top=False)
    s.cylinder(0, 0, 12, 16, 10, NEUTRAL, layer=4)
    axis_mark(s, (0, 0, -3), (0, 0, 22))
    return s.render()


def sweep_add():
    """A green bar bent along a path, the path an INK dashed line."""
    s = Scene()
    outer, inner = bend(9, 15, -90, 0)
    prof = [(x, z + 15) for x, z in outer] + [(x, z + 15) for x, z in reversed(inner)]
    s.prism_y(prof, 0, 6, ADD)
    path_mark(s, [(12 * math.cos(math.radians(a)), 6.05, 15 + 12 * math.sin(math.radians(a)))
                  for a in range(-90, 1, 6)])
    return s.render()


def sweep_cut():
    """A grey block with a red curved groove swept into its top."""
    s = Scene()
    z = 8
    outer, inner = bend(7, 13, 0, 90)
    loop = _ring_groove(s, outer, inner, 2, 2, z, 5, CUT)
    s.box(0, 0, 0, 18, 18, z, NEUTRAL, holes=[loop])
    return s.render()


def loft_add():
    """A green solid lofted from a square up to a circle."""
    s = Scene()
    n = 48
    s.ruled(square_ring(0, 0, 0, 9, n), circle(0, 0, 15, 5.5, n), ADD, axis=(0, 0, 7))
    return s.render()


def loft_cut():
    """A grey block with a red pocket tapering from a square to a circle."""
    s = Scene()
    n, z = 48, 10
    opening = square_ring(0, 0, z, 7, n)
    floor = circle(0, 0, z - 7, 3.5, n)
    s.box(-10, -10, 0, 10, 10, z, NEUTRAL, holes=[opening])
    s.ruled(opening, floor, CUT, cap_top=False, inward=True, layer=0, axis=(0, 0, z))
    s.add(Face([floor], CUT, hint=(0, 0, 1), layer=0))
    return s.render()


def _boundary_sections(z0, z1, half0, half1, swell, bulge, count=8, n=48):
    """Sections of a solid whose sides swell out between its two end profiles."""
    rings = []
    for k in range(count + 1):
        t = k / float(count)
        half = half0 + (half1 - half0) * t + swell * math.sin(t * math.pi)
        rings.append(_pillow(0, 0, z0 + (z1 - z0) * t, half, bulge, n))
    return rings


def boundary_add():
    """A green solid between bulging profiles: its sides swell out."""
    s = Scene()
    rings = _boundary_sections(0, 17, 6.5, 5, 3.0, 0.18)
    for a, b in zip(rings[:-1], rings[1:]):
        s.ruled(a, b, ADD, cap_top=(b is rings[-1]), axis=(0, 0, 7))
    return s.render()


def boundary_cut():
    """A grey block with a red pocket: a bulging opening, walls curving down like a bowl."""
    s = Scene()
    z = 10
    rings = []
    for k in range(9):
        t = k / 8.0
        rings.append(_pillow(0, 0, z - 7 * math.sin(t * math.pi / 2),
                             3 + 4 * math.cos(t * math.pi / 2), 0.18))
    s.box(-10, -10, 0, 10, 10, z, NEUTRAL, holes=[rings[0]])
    for a, b in zip(rings[:-1], rings[1:]):
        s.ruled(a, b, CUT, cap_top=False, inward=True, layer=0, axis=(0, 0, z))
    s.add(Face([rings[-1]], CUT, hint=(0, 0, 1), layer=0))
    return s.render()


def rib():
    """A grey L bracket with a green rib (gusset) across its corner."""
    s = Scene()
    s.prism_y([(0, 0), (18, 0), (18, 5), (5, 5), (5, 18), (0, 18)], 0, 16, NEUTRAL)
    s.prism_y([(5, 5), (16, 5), (5, 16)], 5.5, 10.5, ADD, layer=2)
    return s.render()


# ---------------------------------------------------------------- applied features

def wrap():
    """A grey cylinder with a blue patch wrapped (embossed) onto its side."""
    s = Scene()
    r, t = 9.0, 1.8
    s.cylinder(0, 0, 0, 20, r, NEUTRAL)
    a0, a1, z0, z1, n = 5.0, 85.0, 5.0, 15.0, 12
    arc = [math.radians(a0 + (a1 - a0) * i / n) for i in range(n + 1)]
    outer = [((r + t) * math.cos(a), (r + t) * math.sin(a)) for a in arc]
    inner = [(r * math.cos(a), r * math.sin(a)) for a in arc]
    _ring_bar(s, outer, inner, z0, z1, FEATURE, layer=2)
    return s.render()


def draft():
    """A grey block whose side faces lean in (blue), the upright edge dashed."""
    s = Scene()
    z, t = 12, 3.5
    bottom = rect(0, 0, 18, 16, 0)
    top = rect(t, t, 18 - t, 16 - t, z)
    s.ruled(bottom, top, FEATURE, cap_top=False)
    s.add(Face([top], NEUTRAL, hint=(0, 0, 1)))
    s.add(Face([bottom], NEUTRAL, hint=(0, 0, -1)))
    s.line([(18, 0, 0), (18, 0, z), (18 - t, t, z)], INK, dash="3.5 2.5")
    return s.render()


def shell():
    """A grey block hollowed out: the removed inside red, thin walls left."""
    s = Scene()
    t, z = 2.2, 12
    opening = rect(t, t, 18 - t, 16 - t, z)
    s.box(0, 0, 0, 18, 16, z, NEUTRAL, holes=[opening])
    s.walls(opening, z - t, CUT)
    return s.render()


def dome():
    """A grey block with a green dome on its top."""
    s = Scene()
    s.box(-9, -9, 0, 9, 9, 8, NEUTRAL)
    _dome(s, 0, 0, 8, 7.5, 7, ADD)
    return s.render()


def intersect():
    """Two overlapping grey blocks (faint) and, solid blue, the part they share."""
    s = Scene()
    s.box(0, 0, 0, 14, 14, 14, NEUTRAL, opacity=0.5)
    s.box(7, 7, 7, 21, 21, 21, NEUTRAL, opacity=0.5, layer=3)
    s.box(7, 7, 7, 14, 14, 14, FEATURE, layer=2)
    return s.render()


def hole_wizard():
    """A grey block with a red counterbored hole."""
    s = Scene()
    z = 9
    top = _counterbore(s, 10, 8, z, 6, 3, 3.2, 5, CUT)
    s.box(0, 0, 0, 20, 16, z, NEUTRAL, holes=[top])
    return s.render()


def thread():
    """A grey bolt with a blue helical thread wound round its shaft."""
    s = Scene()
    r, h = _bolt(s)
    _helix_front(s, r, 8.5, h - 1.5, 3.0, stroke(FEATURE), MARK + 0.6)
    return s.render()


def cosmetic_thread():
    """A grey bolt with its thread only drawn on (blue dashed lines), not modelled."""
    s = Scene()
    r, h = _bolt(s)
    blue, rr = stroke(FEATURE), r * 0.7
    s.line(circle(0, 0, h, rr, 36) + [circle(0, 0, h, rr, 36)[0]], blue, 2.4,
           dash="3.5 2.5", layer=10)
    for a in (0.0, 90.0):
        x, y = r * math.cos(math.radians(a)), r * math.sin(math.radians(a))
        s.line([(x, y, 8.5), (x, y, h)], blue, 2.4, dash="3.5 2.5", layer=10)
    return s.render()


# ---------------------------------------------------------------- fastening features

def mounting_boss():
    """A grey plate with a green round boss on it, a hole down the boss."""
    s = Scene()
    s.box(-10, -10, 0, 10, 10, 4, NEUTRAL)
    hole = circle(0, 0, 16, 2.6)
    s.walls(hole, 6, ADD, floor=True, layer=2)
    s.cylinder(0, 0, 4, 16, 6.5, ADD, layer=3, top_holes=[hole])
    return s.render()


def snap_hook():
    """A grey base with a green beam rising from it, a catch on its tip."""
    s = Scene()
    s.box(-9, -7, 0, 9, 7, 3, NEUTRAL)
    s.prism_y([(-2, 3), (2, 3), (2, 15), (8, 15), (8, 17), (2, 24), (-2, 24)],
              -2.5, 2.5, ADD, layer=2)
    return s.render()


def lip_groove():
    """Two grey wall edges side by side: a green lip on one, a red groove in the other."""
    s = Scene()
    s.prism_y([(0, 0), (7.5, 0), (7.5, 9), (0, 9)], 0, 10, NEUTRAL)
    s.prism_y([(2, 9), (5.5, 9), (5.5, 13), (2, 13)], 0, 10, ADD, layer=2)
    s.prism_y([(11.5, 0), (19, 0), (19, 9), (17.5, 9), (17.5, 5), (13.5, 5), (13.5, 9),
               (11.5, 9)], 0, 10, NEUTRAL, accent={3, 4, 5}, accent_pal=CUT)
    return s.render()


def vent():
    """A grey plate with red vent slots cut through it."""
    s = Scene()
    z = 4
    slots = [rect(4, y, 16, y + 2.6, z) for y in (3.5, 8.2, 12.9)]
    for slot in slots:
        s.walls(slot, z, CUT, floor=False)
    s.box(0, 0, 0, 20, 19, z, NEUTRAL, holes=slots)
    return s.render()


ICONS = {
    "ExtrudeAdd": extrude_add, "ExtrudeCut": extrude_cut,
    "Fillet": fillet, "Chamfer": chamfer,
    "RevolveAdd": revolve_add, "RevolveCut": revolve_cut,
    "SweepAdd": sweep_add, "SweepCut": sweep_cut,
    "LoftAdd": loft_add, "LoftCut": loft_cut,
    "BoundaryAdd": boundary_add, "BoundaryCut": boundary_cut,
    "Rib": rib, "Wrap": wrap, "Draft": draft, "Shell": shell, "Dome": dome,
    "Intersect": intersect, "HoleWizard": hole_wizard,
    "Thread": thread, "CosmeticThread": cosmetic_thread,
    "MountingBoss": mounting_boss, "SnapHook": snap_hook, "LipGroove": lip_groove,
    "Vent": vent,
}
