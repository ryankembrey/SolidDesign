# SPDX-License-Identifier: LGPL-2.1-or-later
"""surfaces icons. See tools/icon_kit.py for the rules."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icon_kit import *   # noqa: E402,F401,F403


# ---------------------------------------------------------------- helpers

def _sheet_pal(pal, t=0.4):
    """A sheet's palette: its top tone pulled toward the mid tone, so a flat
    sheet still shows its colour at 24 px."""
    return (mix(pal[0], pal[1], t), pal[1], pal[2])


TEAL = _sheet_pal(SURFACE)          # a surface sheet
GREY = _sheet_pal(NEUTRAL, 0.3)     # an existing (grey) sheet
RED = _sheet_pal(CUT, 0.3)          # a removed piece of sheet


def _strip(s, a, b, pal=TEAL, layer=2):
    """A two-sided sheet between two polylines of the same length (a ruled
    skin). Quads are wound the same way, so smooth sheets show no seams."""
    for i in range(len(a) - 1):
        s.add(Face([[a[i], a[i + 1], b[i + 1], b[i]]], pal, two_sided=True, layer=layer))


def _patch(s, f, nu, nv, pal=TEAL, layer=2):
    """A two-sided sheet over a grid: f(u, v) -> point, u and v in 0..1."""
    rows = [[f(i / float(nu), j / float(nv)) for i in range(nu + 1)] for j in range(nv + 1)]
    for j in range(nv):
        _strip(s, rows[j], rows[j + 1], pal, layer)


def _poly(s, loop, pal=TEAL, layer=2):
    """A flat two-sided sheet bounded by a horizontal loop."""
    s.add(Face([loop], pal, normal=(0, 0, 1), two_sided=True, layer=layer))


def _pale(s, loop, layer=2):
    """A restored or extended part of a teal sheet: paler, but the same sheet
    (no outline between them; mark the old edge with a dashed line)."""
    s.add(Face([loop], TEAL, normal=(0, 0, 1), two_sided=True, layer=layer,
               color=SURFACE[0]))


def _up(pts, dz):
    return [(p[0], p[1], p[2] + dz) for p in pts]


# ---------------------------------------------------------------- makers

def extrude_surface():
    """An open wavy profile extruded straight up into a teal sheet, an INK arrow up."""
    s = Scene()
    curve = [(16.0 * i / 16, 6 + 3.5 * math.sin(2 * math.pi * i / 16), 0) for i in range(17)]
    _strip(s, curve, _up(curve, 12))
    s.arrow((8, 6, 12.5), (8, 6, 25))
    return s.render()


def revolve_surface():
    """A slanted open profile revolved 270 degrees round an INK axis: a teal sleeve."""
    s = Scene()
    a0, a1, n = 90, 360, 36
    bottom = circle(0, 0, 0, 10, n, a0, a1, closed=False)
    top = circle(0, 0, 13, 6, n, a0, a1, closed=False)
    _strip(s, bottom, top)
    axis_mark(s, (0, 0, -3), (0, 0, 19))
    return s.render()


def sweep_surface():
    """An open profile swept along an INK dashed quarter-circle path: a bent teal wall."""
    s = Scene()
    n, r = 16, 12
    base = circle(0, 0, 0, r, n, 0, 90, closed=False)
    _strip(s, base, _up(base, 9))
    path_mark(s, _up(circle(0, 0, 0, r, n, 0, 90, closed=False), 4.5))
    return s.render()


def loft_surface():
    """An open teal skin lofted from a square to a circle, no end caps."""
    s = Scene()
    n = 48
    bottom = square_ring(0, 0, 0, 9, n)
    top = circle(0, 0, 14, 6, n)
    _strip(s, bottom + bottom[:1], top + top[:1])
    return s.render()


def boundary_surface():
    """A teal sheet bulging up between four curved boundary edges."""
    s = Scene()

    def f(u, v):
        return (18 * u, 14 * v, 4 * math.sin(math.pi * u) + 4 * math.sin(math.pi * v))
    _patch(s, f, 12, 12)
    return s.render()


def planar_surface():
    """A flat teal sheet filling a closed sketch outline (corner points)."""
    s = Scene()
    loop = [(0, 0, 0), (18, 0, 0), (18, 9, 0), (10, 16, 0), (0, 16, 0)]
    _poly(s, loop)
    dots(s, loop)
    return s.render()


def offset_surface():
    """A grey sheet and its teal copy offset above it, an INK arrow between."""
    s = Scene()
    sheet(s, 0, 0, 18, 14, 0, GREY, layer=1)
    sheet(s, 0, 0, 18, 14, 9, TEAL)
    s.arrow((9, 14, 0), (9, 14, 8.5))
    return s.render()


def filled_surface():
    """A teal patch spanning a hole in a grey plate, bounded by the hole's edge."""
    s = Scene()
    z, r = 6, 6
    hole = circle(9, 7, z, r, 32)
    s.box(0, 0, 0, 18, 14, z, NEUTRAL, holes=[hole])

    def f(u, v):
        a = 2 * math.pi * u
        rr = r * math.cos(v * math.pi / 2)
        return (9 + rr * math.cos(a), 7 + rr * math.sin(a), z + 3 * math.sin(v * math.pi / 2))
    _patch(s, f, 32, 5, layer=3)
    return s.render()


def extend_surface():
    """A teal sheet carried on past its old edge (dashed) into a pale extension,
    an INK arrow out."""
    s = Scene()
    sheet(s, 0, 0, 11, 14, 0, TEAL)
    _pale(s, rect(11, 0, 21, 14, 0))
    s.line([(11, 0, 0), (11, 14, 0)], INK, 2.0, dash="3.5 2.5", layer=9)
    s.arrow((6, 7, 0), (20, 7, 0))
    return s.render()


def trim_surface():
    """A teal sheet with the piece trimmed away in red."""
    s = Scene()
    sheet(s, 0, 0, 11, 14, 0, TEAL)
    sheet(s, 11, 0, 20, 14, 0, RED)
    return s.render()


def knit():
    """Two teal sheets, a wall and a floor, stitched along one edge into one."""
    s = Scene()
    s.add(Face([[(0, 0, 0), (18, 0, 0), (18, 0, 12), (0, 0, 12)]], TEAL, two_sided=True,
               layer=2))
    s.add(Face([[(0, 0, 0), (18, 0, 0), (18, 14, 0), (0, 14, 0)]], TEAL, two_sided=True,
               layer=2))
    for x in (3, 7, 11, 15):
        s.line([(x, 0, 2.5), (x, 2.5, 0)], INK, 2.2, layer=10)
    return s.render()


def ruled_surface():
    """A teal ruled strip standing off the back top edge of a grey block."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 8, NEUTRAL)
    s.add(Face([[(0, 0, 8), (18, 0, 8), (18, -4, 17), (0, -4, 17)]], TEAL,
               two_sided=True, layer=0))
    return s.render()


def radiate_surface():
    """A flat teal flange spreading out from the top edges of a grey block."""
    s = Scene()
    s.box(5, 5, 0, 17, 15, 11, NEUTRAL, layer=1)
    s.add(Face([rect(0, 0, 22, 20, 11), rect(5, 5, 17, 15, 11)], TEAL, normal=(0, 0, 1),
               two_sided=True, layer=2))
    return s.render()


def untrim_surface():
    """A teal face grown back to its full sheet: the filled hole and the strip
    past the old edge pale, their old edges dashed."""
    s = Scene()
    hole = circle(7, 7, 0, 4, 32)
    s.add(Face([rect(0, 0, 13, 14, 0), hole], TEAL, normal=(0, 0, 1), two_sided=True,
               layer=2))
    _pale(s, hole)
    _pale(s, rect(13, 0, 20, 14, 0))
    s.line(hole + hole[:1], INK, 2.0, dash="3.5 2.5", layer=9)
    s.line([(13, 0, 0), (13, 14, 0)], INK, 2.0, dash="3.5 2.5", layer=9)
    return s.render()


def mid_surface():
    """A grey thin plate, seen through, with its teal mid-surface inside."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 8, NEUTRAL, opacity=0.45)
    sheet(s, 0, 0, 18, 14, 4, TEAL)
    return s.render()


def surface_flatten():
    """A curved teal sheet laid out flat in front of it, an INK arrow between."""
    s = Scene()
    n = 12
    arc = [(-6 + 8 * math.sin(math.radians(-90 + 180.0 * i / n)), 0,
            10 + 8 * (1 - math.cos(math.radians(-90 + 180.0 * i / n)))) for i in range(n + 1)]
    _strip(s, arc, [(p[0], p[1] + 12, p[2]) for p in arc], layer=2)
    sheet(s, 6, 4, 26, 16, 0, TEAL, layer=1)
    s.arrow((2, 14, 10), (10, 14, 1.5))
    return s.render()


def thicken():
    """A teal sheet grown into a green slab under it."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 6, ADD, top_pal=TEAL)
    return s.render()


def thicken_cut():
    """A grey block with a red slab cut away under a teal sheet."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 6, NEUTRAL)
    s.box(0, 0, 6, 18, 14, 11, CUT, top_pal=TEAL, layer=2)
    return s.render()


def surface_cut():
    """A grey block sliced by a sloping teal sheet; the wedge above it, removed, red."""
    s = Scene()
    lo, hi, top = 4.0, 9.0, 12.0
    s.prism_y([(0, 0), (18, 0), (18, lo), (0, hi)], 0, 14, NEUTRAL)

    def z(x):
        return hi + (lo - hi) * x / 18.0
    x0, x1, y0, y1 = -3, 22, -3, 18
    s.add(Face([[(x0, y0, z(x0)), (x1, y0, z(x1)), (x1, y1, z(x1)), (x0, y1, z(x0))]], TEAL,
               two_sided=True, layer=2))
    s.prism_y([(0, hi), (18, lo), (18, top), (0, top)], 0, 14, CUT, layer=3)
    return s.render()


ICONS = {
    "ExtrudeSurface": extrude_surface, "RevolveSurface": revolve_surface,
    "SweepSurface": sweep_surface, "LoftSurface": loft_surface,
    "BoundarySurface": boundary_surface, "PlanarSurface": planar_surface,
    "OffsetSurface": offset_surface, "FilledSurface": filled_surface,
    "ExtendSurface": extend_surface, "TrimSurface": trim_surface, "Knit": knit,
    "RuledSurface": ruled_surface, "RadiateSurface": radiate_surface,
    "UntrimSurface": untrim_surface, "MidSurface": mid_surface,
    "SurfaceFlatten": surface_flatten, "Thicken": thicken, "ThickenCut": thicken_cut,
    "SurfaceCut": surface_cut,
}
