# SPDX-License-Identifier: LGPL-2.1-or-later
"""evaluate icons. See tools/icon_kit.py for the rules."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icon_kit import *   # noqa: E402,F401,F403

SLATE = stroke(EVAL)


def _overlay(out, body):
    """Add flat SVG markup over a rendered isometric icon."""
    return out.replace("\n</svg>", "\n" + body + "\n</svg>")


def _arc_arrow(cx, cy, r, a0, a1, color, width=4.2):
    """A flat circular arrow from angle a0 to a1 (degrees, clockwise on screen)."""
    pts = [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / 24.0)),
            cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / 24.0))) for i in range(25)]
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    ang = math.atan2(y2 - y1, x2 - x1)
    hl, hw = width * 2.4, width * 1.9
    tip = (x2 + math.cos(ang) * hl * 0.6, y2 + math.sin(ang) * hl * 0.6)
    bx, by = tip[0] - math.cos(ang) * hl, tip[1] - math.sin(ang) * hl
    nx, ny = -math.sin(ang) * hw, math.cos(ang) * hw
    return ('<path d="M%s" fill="none" stroke="%s" stroke-width="%.1f" '
            'stroke-linecap="round"/><path d="M%.2f %.2f L%.2f %.2f L%.2f %.2f Z" '
            'fill="%s" stroke="%s" stroke-width="1" stroke-linejoin="round"/>' % (
                " L".join("%.2f %.2f" % p for p in pts), color, width, tip[0], tip[1],
                bx + nx, by + ny, bx - nx, by - ny, color, color))


def rebuild():
    """A grey block with two slate arrows chasing round it."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 10, NEUTRAL)
    out = s.render(box=(17, 17, 47, 47))
    return _overlay(out, _arc_arrow(32, 32, 24, 200, 330, SLATE) +
                    _arc_arrow(32, 32, 24, 20, 150, SLATE))


def whats_wrong():
    """A grey block looked at through a slate magnifier."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 10, NEUTRAL)
    out = s.render(box=(4, 4, 44, 44))
    glass = ('<path d="M45 45 L58 58" stroke="%s" stroke-width="7" stroke-linecap="round"/>'
             '<circle cx="36" cy="36" r="13" fill="%s" fill-opacity="0.75" stroke="%s" '
             'stroke-width="4.5"/>'
             '<path d="M36 29 L36 37" stroke="%s" stroke-width="4" stroke-linecap="round"/>'
             '<circle cx="36" cy="43" r="2.2" fill="%s"/>' % (
                 SLATE, EVAL[0], SLATE, SLATE, SLATE))
    return _overlay(out, glass)


def context_toolbar():
    """A pointer with a small slate pop-up toolbar of three tools beside it."""
    tools = "".join('<rect x="%d" y="13" width="9" height="10" rx="1.5" fill="%s"/>' % (
        x, EVAL[1]) for x in (25, 36.5, 48))
    return flat(
        '<rect x="20" y="8" width="41" height="20" rx="3" fill="%s" stroke="%s" '
        'stroke-width="%.1f"/>%s'
        '<path d="M8 30 L8 58 L15 51 L20 61 L25 58 L20 49 L29 48 Z" fill="#ffffff" '
        'stroke="%s" stroke-width="%.1f" stroke-linejoin="round"/>' % (
            EVAL[0], SLATE, LINE + 0.4, tools, INK, LINE + 0.4))


def rollback_bar():
    """A feature tree with the slate rollback bar across it; the features
    below the bar are rolled back (faint)."""
    rows = ""
    for y, faint in ((10, False), (21, False), (43, True), (54, True)):
        op = ' opacity="0.4"' if faint else ""
        rows += ('<g%s fill="%s" stroke="%s" stroke-width="1.5">'
                 '<rect x="5" y="%d" width="9" height="9" rx="1.5"/>'
                 '<rect x="18" y="%d" width="38" height="6" rx="3"/></g>' % (
                     op, NEUTRAL[1], INK, y - 4.5, y - 3))
    bar = ('<rect x="3" y="28" width="58" height="8" rx="2" fill="%s" stroke="%s" '
           'stroke-width="1.5"/>' % (EVAL[1], SLATE))
    return flat(rows + bar)


def part():
    """The part container: a grey block inside slate corner marks."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 10, NEUTRAL)
    out = s.render(box=(11, 11, 53, 53))
    marks = "".join(
        '<path d="M%d %d L%d %d L%d %d" fill="none" stroke="%s" stroke-width="4" '
        'stroke-linecap="round" stroke-linejoin="round"/>' % (
            x + dx * 12, y, x, y, x, y + dy * 12, SLATE)
        for x, y, dx, dy in ((4, 4, 1, 1), (60, 4, -1, 1), (4, 60, 1, -1), (60, 60, -1, -1)))
    return _overlay(out, marks)


def solid_design():
    """The workbench: a grey block with a counterbored hole, its walls blue."""
    s = Scene()
    z, cx, cy = 12, 9, 8
    top = circle(cx, cy, z, 6)
    s.box(0, 0, 0, 18, 16, z, NEUTRAL, holes=[top])
    step = circle(cx, cy, z - 3.5, 3.2)
    s.walls(top, 3.5, FEATURE, floor=False)
    s.add(Face([circle(cx, cy, z - 3.5, 6), step], FEATURE, hint=(0, 0, 1), layer=0))
    s.walls(step, 6, FEATURE)
    return s.render()


def body_surface():
    """Tree icon for a surface body: a wavy teal sheet."""
    s = Scene()
    n = 24
    xs = [i * 20.0 / n for i in range(n + 1)]
    zs = [4 * math.sin(x / 20.0 * 2 * math.pi) for x in xs]
    for i in range(n):
        q = [(xs[i], 0, zs[i]), (xs[i + 1], 0, zs[i + 1]), (xs[i + 1], 16, zs[i + 1]),
             (xs[i], 16, zs[i])]
        s.add(Face([q], SURFACE, two_sided=True))
    return s.render()


ICONS = {
    "Rebuild": rebuild, "WhatsWrong": whats_wrong, "ContextToolbar": context_toolbar,
    "RollbackBar": rollback_bar, "Part": part, "SolidDesign": solid_design,
    "BodySurface": body_surface,
}
