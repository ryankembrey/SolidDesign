# SPDX-License-Identifier: LGPL-2.1-or-later
"""reference icons. See tools/icon_kit.py for the rules."""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from icon_kit import *   # noqa: E402,F401,F403


# A reference plane's face: the amber top tone pulled toward the mid tone, so a
# flat plane still reads as amber at 24 px.
_PLANE = (mix(REF[0], REF[1], 0.45), REF[1], REF[2])


def _disc(s, c, r, n=32, layer=5):
    """The centre of mass mark: a disc facing the viewer, quartered amber and
    white, outlined in INK."""
    u = (1 / math.sqrt(2), -1 / math.sqrt(2), 0)
    v = (-1 / math.sqrt(6), -1 / math.sqrt(6), 2 / math.sqrt(6))
    k = n // 4
    for q in range(4):
        pts = [c]
        for i in range(k + 1):
            a = math.radians(90.0 * q + 90.0 * i / k)
            pts.append(tuple(c[j] + r * (math.cos(a) * u[j] + math.sin(a) * v[j])
                             for j in range(3)))
        amber = q % 2 == 0
        s.add(Face([pts], REF if amber else NEUTRAL, normal=VIEW, layer=layer,
                   color=REF[1] if amber else "#ffffff"))


def plane():
    """An amber reference plane."""
    s = Scene()
    s.add(Face([rect(0, 0, 20, 20, 0)], _PLANE, normal=(0, 0, 1), two_sided=True))
    return s.render()


def axis():
    """An amber dash-dot axis through a grey cylinder."""
    s = Scene()
    s.cylinder(0, 0, 0, 10, 7, NEUTRAL)
    s.line([(0, 0, -7), (0, 0, 19)], stroke(REF), MARK + 0.4, dash="7 3 2 3", layer=10)
    return s.render()


def point():
    """An amber point on the top face of a grey block."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 10, NEUTRAL)
    s.dot((9, 7, 10), INK, 7.0)
    s.dot((9, 7, 10), REF[1], 5.0, layer=12)
    return s.render()


def coordinate_system():
    """A coordinate system: three amber arrows from an origin."""
    s = Scene()
    o, r = (0, 0, 0), 18
    for d in ((r, 0, 0), (0, r, 0), (0, 0, r)):
        s.arrow(o, d, stroke(REF))
    s.dot(o, stroke(REF), 4.0)
    return s.render()


def bounding_box():
    """A grey part inside an amber dashed box."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 6, NEUTRAL)
    s.cylinder(9, 7, 6, 13, 4, NEUTRAL)
    x0, y0, z0, x1, y1, z1 = 0, 0, 0, 18, 14, 13
    c = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    for a, b in ((1, 2), (2, 3), (4, 5), (5, 6), (6, 7), (7, 4), (1, 5), (2, 6), (3, 7)):
        s.line([c[a], c[b]], stroke(REF), 2.6, dash="4 2.5", layer=10)
    return s.render()


def center_of_mass():
    """The quartered centre of mass disc, amber and white, over a grey block."""
    s = Scene()
    s.box(0, 0, 0, 18, 14, 10, NEUTRAL)
    _disc(s, (9, 7, 10), 7)
    return s.render()


ICONS = {
    "Plane": plane, "Axis": axis, "Point": point, "CoordinateSystem": coordinate_system,
    "BoundingBox": bounding_box, "CenterOfMass": center_of_mass,
}
