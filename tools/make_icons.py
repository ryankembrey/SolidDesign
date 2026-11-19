# SPDX-License-Identifier: LGPL-2.1-or-later
"""Generate the SVG icons: one isometric set, readable at 16 px.

    python3 tools/make_icons.py

Writes freecad/SolidDesign/resources/icons/*.svg, including the state variants
used in the tree: <name>_error, <name>_warning (badges) and <name>_rolled (faded).

Every icon is drawn by the same small renderer, so they share one projection,
one light, one palette and one line weight:

- true isometric projection, seen from (1, 1, 1);
- solids are built from planar faces; faces turned away are dropped, the rest
  are drawn far to near, each shaded by its normal (top light, the two side
  directions mid and dark);
- outlines only where the surface turns sharply or at the silhouette, so
  curved faces read smooth;
- colour says what a tool does: blue adds material, red removes it, grey is
  existing material, orange is reference geometry and accents, green is a
  surface body.

The sketch tool uses the Sketcher workbench's icon and the tree's body folders
FreeCAD's folder icon, so neither is drawn here.
"""

import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "freecad", "SolidDesign", "resources", "icons")

INK = "#2e3436"
LINE = 2.0              # outline width at 64 px
# (top, side facing +y, side facing +x): light, mid, dark.
GREY = ("#f3f4f1", "#c9cdc5", "#9ca197")
BLUE = ("#b3d0f2", "#5b8fd1", "#2f62a8")
RED = ("#f7aaaa", "#e04848", "#ad1d1d")
ORANGE = ("#fdd9a6", "#f8a33d", "#d9730b")
GREEN = ("#cdeea6", "#8ae234", "#5a9f1c")

C30 = math.cos(math.radians(30))
VIEW = (1 / math.sqrt(3),) * 3


# ---------------------------------------------------------------- vectors

def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a):
    n = math.sqrt(dot(a, a)) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def newell(loop):
    nx = ny = nz = 0.0
    for i, p in enumerate(loop):
        q = loop[(i + 1) % len(loop)]
        nx += (p[1] - q[1]) * (p[2] + q[2])
        ny += (p[2] - q[2]) * (p[0] + q[0])
        nz += (p[0] - q[0]) * (p[1] + q[1])
    return norm((nx, ny, nz))


def centroid(loop):
    n = float(len(loop))
    return (sum(p[0] for p in loop) / n, sum(p[1] for p in loop) / n,
            sum(p[2] for p in loop) / n)


def project(p):
    """Isometric: +x to the lower right, +y to the lower left, +z up."""
    return ((p[0] - p[1]) * C30, (p[0] + p[1]) * 0.5 - p[2])


def hexrgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def mix(a, b, t):
    a, b = hexrgb(a), hexrgb(b)
    return "#%02x%02x%02x" % tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def shade(pal, n):
    """The colour of a face with normal *n*: the top colour facing up, the
    side colours by which way a side faces, blended for sloping faces."""
    top, left, right = pal
    t = max(0.0, min(1.0, (n[0] - n[1] + 1) / 2.0))       # +y -> 0, +x -> 1
    side = mix(left, right, t)
    up = max(0.0, min(1.0, n[2]))
    return mix(side, top, up ** 0.8)


# ---------------------------------------------------------------- scene

class Face(object):
    def __init__(self, loops, pal, hint=None, color=None, opacity=1.0, layer=1,
                 two_sided=False, normal=None):
        self.loops = [list(l) for l in loops]
        n = normal or newell(self.loops[0])
        if hint is not None and dot(n, hint) < 0:
            n = (-n[0], -n[1], -n[2])
            self.loops = [list(reversed(l)) for l in self.loops]
        self.n = n
        self.pal = pal
        self.color = color
        self.opacity = opacity
        self.layer = layer
        self.two_sided = two_sided

    def visible(self):
        return self.two_sided or dot(self.n, VIEW) > 1e-6

    def fill(self):
        if self.color:
            return self.color
        n = self.n
        if self.two_sided and dot(n, VIEW) < 0:
            n = (-n[0], -n[1], -n[2])
        return shade(self.pal, n)

    def depth(self):
        c = centroid(self.loops[0])
        return c[0] + c[1] + c[2]

    def edges(self):
        for loop in self.loops:
            for i, p in enumerate(loop):
                yield p, loop[(i + 1) % len(loop)]


def _key(p):
    return (round(p[0], 3), round(p[1], 3), round(p[2], 3))


class Scene(object):
    """Faces, plus 2D marks (arrows, axes, dashed paths) drawn over them."""

    def __init__(self):
        self.faces = []
        self.marks = []         # (layer, kind, data)

    def add(self, face):
        self.faces.append(face)
        return face

    # -- solids ---------------------------------------------------------------
    def box(self, x0, y0, z0, x1, y1, z1, pal, holes=(), opacity=1.0, layer=1, top_pal=None):
        """A box; *holes*: loops cut through its top face (pockets go under)."""
        c = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
        quads = [
            [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
            [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)],
            [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
            [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)],
            [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
            [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
        ]
        for i, q in enumerate(quads):
            loops = [q] + (list(holes) if i == 0 else [])
            self.add(Face(loops, top_pal if (i == 0 and top_pal) else pal,
                          hint=sub(centroid(q), c), opacity=opacity, layer=layer))

    def prism_y(self, profile, y0, y1, pal, accent=None, accent_pal=None, opacity=1.0,
                layer=1):
        """A 2D profile [(x, z)] extruded along y from y0 to y1. Edges whose index
        is in *accent* get *accent_pal* (a fillet's round, a chamfer's bevel)."""
        accent = set(accent or ())
        cx = sum(p[0] for p in profile) / len(profile)
        cz = sum(p[1] for p in profile) / len(profile)
        for y, s in ((y0, -1), (y1, 1)):
            self.add(Face([[(x, y, z) for x, z in profile]], pal, hint=(0, s, 0),
                          opacity=opacity, layer=layer))
        for i, (x, z) in enumerate(profile):
            x2, z2 = profile[(i + 1) % len(profile)]
            q = [(x, y0, z), (x2, y0, z2), (x2, y1, z2), (x, y1, z)]
            m = centroid(q)
            self.add(Face([q], accent_pal if i in accent else pal,
                          hint=(m[0] - cx, 0, m[2] - cz), opacity=opacity, layer=layer))

    def cylinder(self, cx, cy, z0, z1, r, pal, n=48, opacity=1.0, layer=1, top_holes=(),
                 top=True):
        ring0 = circle(cx, cy, z0, r, n)
        ring1 = circle(cx, cy, z1, r, n)
        for i in range(n):
            j = (i + 1) % n
            q = [ring0[i], ring0[j], ring1[j], ring1[i]]
            m = centroid(q)
            self.add(Face([q], pal, hint=(m[0] - cx, m[1] - cy, 0), opacity=opacity,
                          layer=layer))
        if top:
            self.add(Face([ring1] + list(top_holes), pal, hint=(0, 0, 1), opacity=opacity,
                          layer=layer))
        self.add(Face([ring0], pal, hint=(0, 0, -1), opacity=opacity, layer=layer))

    def walls(self, loop, depth, pal, floor=True, floor_holes=(), layer=0):
        """A pocket under an opening *loop* (on a top face): its walls, seen from
        inside, and its floor."""
        c = centroid(loop)
        down = [(p[0], p[1], p[2] - depth) for p in loop]
        for i in range(len(loop)):
            j = (i + 1) % len(loop)
            q = [loop[i], loop[j], down[j], down[i]]
            m = centroid(q)
            self.add(Face([q], pal, hint=(c[0] - m[0], c[1] - m[1], 0), layer=layer))
        if floor:
            self.add(Face([down] + list(floor_holes), pal, hint=(0, 0, 1), layer=layer))
        return down

    def ruled(self, bottom, top, pal, cap_top=True, inward=False, layer=1, axis=None):
        """Side faces between two loops of the same length (a loft), and the top."""
        c = axis or centroid(bottom + top)
        for i in range(len(bottom)):
            j = (i + 1) % len(bottom)
            q = [bottom[i], bottom[j], top[j], top[i]]
            m = centroid(q)
            h = (m[0] - c[0], m[1] - c[1], 0)
            if inward:
                h = (-h[0], -h[1], 0)
            self.add(Face([q], pal, hint=h, layer=layer))
        if cap_top:
            self.add(Face([top], pal, hint=(0, 0, -1 if inward else 1), layer=layer))

    # -- marks ---------------------------------------------------------------
    def arrow(self, a, b, color=INK, width=3.2, layer=9):
        self.marks.append((layer, "arrow", (a, b, color, width)))

    def line(self, pts, color=INK, width=2.0, dash=None, layer=9, opacity=1.0):
        self.marks.append((layer, "line", (pts, color, width, dash, opacity)))

    def arc_arrow(self, pts, color=INK, width=3.0, layer=9):
        self.marks.append((layer, "arcarrow", (pts, color, width)))

    # -- output --------------------------------------------------------------
    def render(self, box=(4, 4, 60, 60), badge=None):
        faces = [f for f in self.faces if f.visible()]
        faces.sort(key=lambda f: (f.layer, f.depth()))
        # Every edge's neighbours, to outline only sharp and silhouette edges.
        owners = {}
        for f in self.faces:
            for a, b in f.edges():
                owners.setdefault(frozenset((_key(a), _key(b))), []).append(f)

        pts2 = []
        for f in faces:
            for l in f.loops:
                pts2 += [project(p) for p in l]
        for _layer, kind, data in self.marks:
            pts = data[0] if kind != "arrow" else [data[0], data[1]]
            pts2 += [project(p) for p in pts]
        minx = min(p[0] for p in pts2)
        maxx = max(p[0] for p in pts2)
        miny = min(p[1] for p in pts2)
        maxy = max(p[1] for p in pts2)
        bx0, by0, bx1, by1 = box
        s = min((bx1 - bx0) / (maxx - minx or 1), (by1 - by0) / (maxy - miny or 1))
        ox = bx0 + ((bx1 - bx0) - (maxx - minx) * s) / 2 - minx * s
        oy = by0 + ((by1 - by0) - (maxy - miny) * s) / 2 - miny * s

        def P(p):
            u, v = project(p)
            return (ox + u * s, oy + v * s)

        def d_of(loops):
            parts = []
            for l in loops:
                q = [P(p) for p in l]
                parts.append("M" + " L".join("%.2f %.2f" % xy for xy in q) + " Z")
            return " ".join(parts)

        out = []
        items = [(f.layer, f.depth(), "face", f) for f in faces]
        items += [(m[0], 1e9, "mark", m) for m in self.marks]
        items.sort(key=lambda it: (it[0], it[1]))
        for _l, _d, kind, it in items:
            if kind == "mark":
                out.append(self._mark(it, P))
                continue
            f = it
            fill = f.fill()
            op = ' opacity="%.2f"' % f.opacity if f.opacity < 1 else ""
            out.append('<path d="%s" fill="%s" fill-rule="evenodd" stroke="%s" '
                       'stroke-width="0.6" stroke-linejoin="round"%s/>' % (
                           d_of(f.loops), fill, fill, op))
            segs = []
            for a, b in f.edges():
                others = [g for g in owners.get(frozenset((_key(a), _key(b))), [])
                          if g is not f and g.visible()]
                sharp = not others or any(dot(f.n, g.n) < 0.82 or g.pal is not f.pal
                                          for g in others)
                if sharp:
                    pa, pb = P(a), P(b)
                    segs.append("M%.2f %.2f L%.2f %.2f" % (pa[0], pa[1], pb[0], pb[1]))
            if segs:
                out.append('<path d="%s" fill="none" stroke="%s" stroke-width="%.2f" '
                           'stroke-linecap="round" stroke-linejoin="round"%s/>' % (
                               " ".join(segs), INK, LINE, op))
        if badge:
            out.append(badge)
        return svg("\n".join(out))

    @staticmethod
    def _mark(m, P):
        _layer, kind, data = m
        if kind == "line":
            pts, color, width, dash, opacity = data
            q = [P(p) for p in pts]
            da = ' stroke-dasharray="%s"' % dash if dash else ""
            op = ' opacity="%.2f"' % opacity if opacity < 1 else ""
            return ('<path d="M%s" fill="none" stroke="%s" stroke-width="%.2f" '
                    'stroke-linecap="round" stroke-linejoin="round"%s%s/>' % (
                        " L".join("%.2f %.2f" % xy for xy in q), color, width, da, op))
        if kind in ("arrow", "arcarrow"):
            if kind == "arrow":
                a, b, color, width = data
                q = [P(a), P(b)]
            else:
                pts, color, width = data
                q = [P(p) for p in pts]
            (x1, y1), (x2, y2) = q[-2], q[-1]
            ang = math.atan2(y2 - y1, x2 - x1)
            hl = width * 2.6
            hw = width * 2.0
            # Shorten the shaft so its end hides under the head.
            q[-1] = (x2 - math.cos(ang) * hl * 0.6, y2 - math.sin(ang) * hl * 0.6)
            shaft = ('<path d="M%s" fill="none" stroke="%s" stroke-width="%.2f" '
                     'stroke-linecap="round" stroke-linejoin="round"/>' % (
                         " L".join("%.2f %.2f" % xy for xy in q), color, width))
            bx, by = x2 - math.cos(ang) * hl, y2 - math.sin(ang) * hl
            nx, ny = -math.sin(ang) * hw, math.cos(ang) * hw
            head = ('<path d="M%.2f %.2f L%.2f %.2f L%.2f %.2f Z" fill="%s" stroke="%s" '
                    'stroke-width="1" stroke-linejoin="round"/>' % (
                        x2, y2, bx + nx, by + ny, bx - nx, by - ny, color, color))
            return shaft + head
        return ""


def circle(cx, cy, z, r, n=48, start=0.0, end=360.0, closed=True):
    count = n if closed else n + 1
    step = (end - start) / n
    return [(cx + r * math.cos(math.radians(start + i * step)),
             cy + r * math.sin(math.radians(start + i * step)), z) for i in range(count)]


def rect(x0, y0, x1, y1, z):
    return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]


def svg(body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" '
            'viewBox="0 0 64 64">\n<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->\n'
            + body + "\n</svg>\n")


def sign_badge(mark, color):
    """A round badge in the lower right: + (combine), x (delete)."""
    paths = {"+": "M48 41 L48 55 M41 48 L55 48",
             "x": "M43 43 L53 53 M53 43 L43 53"}
    return ('<circle cx="48" cy="48" r="11" fill="%s" stroke="#ffffff" stroke-width="2.5"/>'
            '<path d="%s" stroke="#ffffff" stroke-width="3.6" stroke-linecap="round"/>'
            % (color, paths[mark]))


SMALL = (2, 2, 50, 50)          # content area when a badge takes the lower right


# ---------------------------------------------------------------- the icons

def extrude_add():
    s = Scene()
    s.box(0, 0, 0, 16, 11, 12, BLUE)
    s.arrow((8, 5.5, 12.5), (8, 5.5, 25))
    return s.render()


def extrude_cut():
    s = Scene()
    hole = rect(5, 4, 15, 12, 8)
    s.box(0, 0, 0, 20, 16, 8, GREY, holes=[hole])
    s.walls(hole, 5, RED)
    s.arrow((10, 8, 22), (10, 8, 9))
    return s.render()


def _axis(s, x, y, z0, z1):
    s.line([(x, y, z0), (x, y, z1)], ORANGE[2], 2.2, dash="6 3 1.5 3", layer=10)


def revolve_add():
    s = Scene()
    s.cylinder(0, 0, 0, 4, 11, BLUE)
    s.cylinder(0, 0, 4, 13, 6.5, BLUE)
    _axis(s, 0, 0, -3, 19)
    s.arc_arrow(circle(0, 0, 2, 14.5, 24, 110, 330, closed=False))
    return s.render()


def revolve_cut():
    s = Scene()
    s.cylinder(0, 0, 0, 5, 10, GREY)
    s.cylinder(0, 0, 5, 10, 6.5, RED)
    s.cylinder(0, 0, 10, 15, 10, GREY)
    _axis(s, 0, 0, -3, 21)
    return s.render()


def _bend(r0, r1, a0, a1, z0, z1, n=16):
    """Faces of a bar bent round the z axis: an annular sector, z0 to z1."""
    outer = [(r1 * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
              r1 * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
    inner = [(r0 * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
              r0 * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
    return outer, inner


def sweep_add():
    s = Scene()
    outer, inner = _bend(9, 15, 0, 90, 0, 6)
    z0, z1 = 0, 6
    top = [(x, y, z1) for x, y in outer] + [(x, y, z1) for x, y in reversed(inner)]
    s.add(Face([top], BLUE, hint=(0, 0, 1)))
    for ring, sgn in ((outer, 1), (inner, -1)):
        for i in range(len(ring) - 1):
            (xa, ya), (xb, yb) = ring[i], ring[i + 1]
            q = [(xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1)]
            m = centroid(q)
            s.add(Face([q], BLUE, hint=(sgn * m[0], sgn * m[1], 0)))
    for k, h in ((0, (0, -1, 0)), (-1, (-1, 0, 0))):
        (xo, yo), (xi, yi) = outer[k], inner[k]
        s.add(Face([[(xo, yo, z0), (xi, yi, z0), (xi, yi, z1), (xo, yo, z1)]], BLUE, hint=h))
    # The path, carried on past the start.
    path = [(12 * math.cos(math.radians(a)), 12 * math.sin(math.radians(a)), z1 + 0.1)
            for a in range(0, 91, 6)]
    s.line(path, ORANGE[2], 2.0, dash="3 2.5", layer=10)
    return s.render()


def sweep_cut():
    s = Scene()
    outer, inner = _bend(7, 13, 0, 90, 0, 0)
    z = 8
    loop = [(x + 2, y + 2, z) for x, y in outer] + [(x + 2, y + 2, z) for x, y in reversed(inner)]
    s.box(0, 0, 0, 18, 18, z, GREY, holes=[loop])
    # The groove's walls, seen from inside.
    d = 4
    c = (2, 2)
    for ring, inward in ((outer, -1), (inner, 1)):
        for i in range(len(ring) - 1):
            (xa, ya), (xb, yb) = ring[i], ring[i + 1]
            xa, ya, xb, yb = xa + 2, ya + 2, xb + 2, yb + 2
            q = [(xa, ya, z), (xb, yb, z), (xb, yb, z - d), (xa, ya, z - d)]
            m = centroid(q)
            s.add(Face([q], RED, hint=(inward * (m[0] - c[0]), inward * (m[1] - c[1]), 0),
                       layer=0))
    for k, h in ((0, (0, 1, 0)), (-1, (1, 0, 0))):
        (xo, yo), (xi, yi) = outer[k], inner[k]
        s.add(Face([[(xo + 2, yo + 2, z), (xi + 2, yi + 2, z), (xi + 2, yi + 2, z - d),
                     (xo + 2, yo + 2, z - d)]], RED, hint=h, layer=0))
    s.add(Face([[(p[0], p[1], z - d) for p in loop]], RED, hint=(0, 0, 1), layer=0))
    return s.render()


def _square_ring(cx, cy, z, half, n):
    """A square's outline as *n* points, starting on the same side as circle()."""
    pts = []
    for i in range(n):
        a = math.radians(360.0 * i / n)
        c, sn = math.cos(a), math.sin(a)
        k = half / max(abs(c), abs(sn))
        pts.append((cx + c * k, cy + sn * k, z))
    return pts


def loft_add():
    s = Scene()
    n = 48
    bottom = _square_ring(0, 0, 0, 10, n)
    top = circle(0, 0, 16, 6, n)
    s.ruled(bottom, top, BLUE, axis=(0, 0, 8))
    return s.render()


def loft_cut():
    s = Scene()
    n = 48
    z = 10
    opening = _square_ring(0, 0, z, 7, n)
    floor = circle(0, 0, z - 7, 3.5, n)
    s.box(-11, -11, 0, 11, 11, z, GREY, holes=[opening])
    s.ruled(opening, floor, RED, cap_top=False, inward=True, layer=0, axis=(0, 0, z))
    s.add(Face([floor], RED, hint=(0, 0, 1), layer=0))
    return s.render()


def fillet():
    s = Scene()
    w, h, r = 18, 14, 7
    prof = [(0, 0), (w, 0), (w, h - r)]
    arc = [(w - r + r * math.cos(math.radians(a)), h - r + r * math.sin(math.radians(a)))
           for a in range(6, 90, 6)]
    prof += arc + [(w - r, h), (0, h)]
    acc = set(range(2, 2 + len(arc) + 1))
    s.prism_y(prof, 0, 14, GREY, accent=acc, accent_pal=BLUE)
    return s.render()


def chamfer():
    s = Scene()
    w, h, c = 18, 14, 7
    prof = [(0, 0), (w, 0), (w, h - c), (w - c, h), (0, h)]
    s.prism_y(prof, 0, 14, GREY, accent={2}, accent_pal=BLUE)
    return s.render()


def shell():
    s = Scene()
    t = 2.2
    z = 13
    opening = rect(t, t, 18 - t, 16 - t, z)
    s.box(0, 0, 0, 18, 16, z, GREY, holes=[opening])
    s.walls(opening, z - t, RED)
    return s.render()


def rib():
    """An L bracket with a blue rib (gusset) between its two walls."""
    s = Scene()
    s.prism_y([(0, 0), (20, 0), (20, 5), (5, 5), (5, 20), (0, 20)], 0, 16, GREY)
    s.prism_y([(5, 5), (18, 5), (5, 18)], 0, 4.5, BLUE, layer=2)
    return s.render()


def draft():
    """A block whose walls lean in (blue), the original upright edge dashed."""
    s = Scene()
    z, t = 14, 3.5
    bottom = rect(0, 0, 18, 16, 0)
    top = rect(t, t, 18 - t, 16 - t, z)
    s.ruled(bottom, top, BLUE, cap_top=False)
    s.add(Face([top], GREY, hint=(0, 0, 1)))
    s.add(Face([bottom], GREY, hint=(0, 0, -1)))
    s.line([(18, 0, 0), (18, 0, z)], INK, width=2.0, dash="3 2.5")
    s.line([(18 - t, t, z), (18, 0, z)], INK, width=2.0, dash="3 2.5")
    return s.render()


def _counterbore(s, cx, cy, z, r1, d1, r2, d2, pal=RED):
    """A counterbored hole under a top face at z: returns the opening loop."""
    top = circle(cx, cy, z, r1)
    step = circle(cx, cy, z - d1, r2)
    s.walls(top, d1, pal, floor=False)
    s.add(Face([circle(cx, cy, z - d1, r1), step], pal, hint=(0, 0, 1), layer=0))
    s.walls(step, d2, pal)
    return top


def hole_wizard():
    s = Scene()
    z = 9
    top = circle(10, 9, z, 6.5)
    s.box(0, 0, 0, 20, 18, z, GREY, holes=[top])
    _counterbore(s, 10, 9, z, 6.5, 3, 3.5, 5)
    return s.render()


def workbench():
    s = Scene()
    z = 13
    top = circle(9, 8, z, 5.5)
    s.box(0, 0, 0, 18, 16, z, BLUE, holes=[top])
    _counterbore(s, 9, 8, z, 5.5, 3, 3, 6)
    return s.render()


def _cube(s, x, y, z, a, pal, opacity=1.0, layer=1):
    s.box(x, y, z, x + a, y + a, z + a, pal, opacity=opacity, layer=layer)


def linear_pattern():
    s = Scene()
    for i in range(3):
        _cube(s, i * 15, 0, 0, 8, BLUE, 1.0 if i == 0 else 0.5)
    s.arrow((0, 13, 0), (38, 13, 0), width=2.8)
    return s.render()


def circular_pattern():
    s = Scene()
    n = 4
    for i in range(n):
        a = math.radians(360.0 * i / n + 45)
        x, y = 11 * math.cos(a), 11 * math.sin(a)
        _cube(s, x - 4, y - 4, 0, 8, BLUE, 1.0 if i == 0 else 0.5)
    _axis(s, 0, 0, -6, 14)
    return s.render()


def mirror():
    s = Scene()
    _cube(s, -16, 2, 0, 9, BLUE, 1.0, layer=1)
    s.add(Face([[(0, -4, -3), (0, 16, -3), (0, 16, 14), (0, -4, 14)]], ORANGE,
               hint=(1, 0, 0), opacity=0.7, layer=2))
    _cube(s, 7, 2, 0, 9, BLUE, 0.45, layer=3)
    return s.render()


def combine():
    s = Scene()
    s.box(0, 0, 0, 13, 13, 13, GREY)
    s.box(7, -9, 0, 20, 4, 10, GREY, layer=2)
    return s.render(SMALL, sign_badge("+", BLUE[2]))


def delete_body():
    s = Scene()
    s.box(0, 0, 0, 16, 16, 16, GREY)
    return s.render(SMALL, sign_badge("x", RED[2]))


def split():
    s = Scene()
    s.box(0, 0, 0, 9, 16, 14, GREY, layer=1)
    s.add(Face([[(10.5, -3, -3), (10.5, 19, -3), (10.5, 19, 17), (10.5, -3, 17)]], ORANGE,
               hint=(1, 0, 0), opacity=0.7, layer=2))
    s.box(12, 0, 0, 21, 16, 14, GREY, layer=3)
    return s.render()


def move_copy():
    s = Scene()
    _cube(s, 0, 14, 0, 10, GREY, 0.45, layer=1)
    _cube(s, 14, 0, 0, 10, GREY, layer=1)
    s.arrow((5, 17, 12), (17, 5, 12), width=2.8)
    return s.render()


def plane():
    s = Scene()
    s.add(Face([rect(0, 0, 22, 22, 0)], ORANGE, hint=(0, 0, 1), color="#fbc274"))
    return s.render()


def axis():
    s = Scene()
    s.cylinder(0, 0, 5, 7, 8, GREY)
    s.line([(0, 0, -8), (0, 0, 22)], ORANGE[2], 3.2, dash="7 3 2 3", layer=10)
    return s.render()


def point():
    """A reference point (an orange star) on a grey block's top face."""
    s = Scene()
    s.box(0, 0, 0, 20, 20, 9, GREY)
    c, r = (10, 10, 9), 7
    for d in ((1, 0, 0), (0, 1, 0), (0.7, -0.7, 0)):
        s.line([(c[0] - d[0] * r, c[1] - d[1] * r, c[2]), (c[0] + d[0] * r, c[1] + d[1] * r,
                                                          c[2])], ORANGE[2], 3.4, layer=10)
    s.line([(c[0], c[1], c[2]), (c[0], c[1], c[2] + r)], ORANGE[2], 3.4, layer=10)
    return s.render()


def coordinate_system():
    """X red, Y green, Z blue arrows from an origin, as FreeCAD's axis cross."""
    s = Scene()
    o, r = (0, 0, 0), 20
    s.arrow(o, (r, 0, 0), "#d93025", 3.4)
    s.arrow(o, (0, r, 0), "#3c9a2e", 3.4)
    s.arrow(o, (0, 0, r), "#2f62a8", 3.4)
    return s.render()


def thread():
    """A grey shaft with a blue thread wound round its top."""
    s = Scene()
    r, h = 8.0, 24.0
    s.cylinder(0, 0, 0, h, r, GREY)
    turns, z0, z1 = 3.0, 8.0, 22.0
    pts = []
    for i in range(int(turns * 36) + 1):
        a = math.radians(i * 10.0 - 60.0)
        pts.append((r * math.cos(a), r * math.sin(a), z0 + (z1 - z0) * i / (turns * 36.0)))
    # Only the front half of each turn shows.
    front = []
    for q in pts:
        if q[0] + q[1] > -1.0:
            front.append(q)
        elif front:
            s.line(front, BLUE[2], 3.6, layer=10)
            front = []
    if front:
        s.line(front, BLUE[2], 3.6, layer=10)
    return s.render()


def offset_surface():
    """A grey block with a blue surface floating above its top face."""
    s = Scene()
    s.box(0, 0, 0, 20, 18, 8, GREY)
    s.add(Face([rect(0, 0, 20, 18, 16)], BLUE, hint=(0, 0, 1), opacity=0.9, layer=3))
    s.arrow((10, 9, 8), (10, 9, 15), INK, 2.6)
    return s.render()


def move_face():
    """A block whose top face (blue) has moved up, the old top dashed."""
    s = Scene()
    s.box(0, 0, 0, 20, 18, 14, GREY, top_pal=BLUE)
    s.line([(0, 18, 9), (20, 18, 9), (20, 0, 9)], INK, 1.8, dash="3 2.5", layer=9)
    s.arrow((10, 9, 14), (10, 9, 21), INK, 2.6)
    return s.render()


def split_line():
    """A block whose top face is split by an orange line."""
    s = Scene()
    s.box(0, 0, 0, 20, 18, 12, GREY)
    s.line([(0, 9, 12), (20, 9, 12), (20, 9, 0)], ORANGE[2], 3.6, layer=10)
    return s.render()


def helix():
    """An orange helix round a dashed axis."""
    s = Scene()
    pts = []
    turns, r, h = 3.0, 9.0, 22.0
    for i in range(int(turns * 36) + 1):
        a = math.radians(i * 10.0)
        pts.append((r * math.cos(a), r * math.sin(a), h * i / (turns * 36.0)))
    s.line([(0, 0, -2), (0, 0, h + 2)], INK, 1.6, dash="4 3", layer=8)
    s.line(pts, ORANGE[2], 3.4, layer=10)
    return s.render()


def part():
    s = Scene()
    s.box(0, 0, 0, 20, 16, 7, GREY)
    s.box(0, 0, 7, 9, 16, 17, GREY, layer=2)
    return s.render()


def body_solid():
    s = Scene()
    s.box(0, 0, 0, 16, 16, 16, GREY)
    return s.render()


def body_surface():
    s = Scene()
    n = 24
    xs = [i * 22.0 / n for i in range(n + 1)]
    zs = [5 * math.sin(x / 22.0 * 2 * math.pi) for x in xs]
    for i in range(n):
        q = [(xs[i], 0, zs[i]), (xs[i + 1], 0, zs[i + 1]), (xs[i + 1], 18, zs[i + 1]),
             (xs[i], 18, zs[i])]
        s.add(Face([q], GREEN, two_sided=True))
    return s.render()


def rollback_bar():
    stripes = "".join('<path d="M%d 24 L%d 40" stroke="%s" stroke-width="3"/>' % (
        x, x - 8, ORANGE[2]) for x in range(14, 60, 9))
    return svg('<rect x="3" y="24" width="58" height="16" rx="3" fill="%s"/>%s'
               '<rect x="3" y="24" width="58" height="16" rx="3" fill="none" stroke="%s" '
               'stroke-width="%.1f"/>' % (ORANGE[0], stripes, INK, LINE))


# ---------------------------------------------------------------- surfaces

def _sheet(s, x0, y0, x1, y1, z, pal=GREEN, layer=2, opacity=1.0):
    s.add(Face([rect(x0, y0, x1, y1, z)], pal, hint=(0, 0, 1), two_sided=True, layer=layer,
               opacity=opacity))


def _dome(s, cx, cy, z, r, h, pal=GREEN, layer=3):
    """A green patch bulging up over a circle."""
    rings = []
    for k in range(4):
        t = k / 4.5
        rr = r * math.cos(t * math.pi / 2)
        zz = z + h * math.sin(t * math.pi / 2)
        rings.append(circle(cx, cy, zz, rr, 24))
    s.add(Face([rings[-1]], pal, hint=(0, 0, 1), layer=layer))
    for a, b in zip(rings[:-1], rings[1:]):
        for i in range(24):
            j = (i + 1) % 24
            q = [a[i], a[j], b[j], b[i]]
            m = centroid(q)
            s.add(Face([q], pal, hint=(m[0] - cx, m[1] - cy, m[2] - z + 0.01), layer=layer))


def planar_surface():
    """A flat green sheet inside an orange loop."""
    s = Scene()
    _sheet(s, 0, 0, 22, 18, 0)
    s.line(rect(0, 0, 22, 18, 0) + [(0, 0, 0)], ORANGE[2], 2.2, layer=10)
    return s.render()


def knit():
    """Two green sheets meeting at a stitched edge."""
    s = Scene()
    s.add(Face([[(0, 0, 0), (20, 0, 0), (20, 0, 14), (0, 0, 14)]], GREEN, hint=(0, -1, 0),
               two_sided=True, layer=2))
    s.add(Face([[(0, 0, 14), (20, 0, 14), (20, 18, 14), (0, 18, 14)]], GREEN, hint=(0, 0, 1),
               two_sided=True, layer=2))
    s.line([(0, 0, 14), (20, 0, 14)], ORANGE[2], 3.6, dash="3 2", layer=10)
    return s.render()


def filled_surface():
    """A green patch filling an orange boundary loop."""
    s = Scene()
    _dome(s, 10, 10, 0, 10, 7)
    s.line(circle(10, 10, 0, 10, 48) + [circle(10, 10, 0, 10, 48)[0]], ORANGE[2], 3.2,
           layer=10)
    return s.render()


def trim_surface():
    """A green sheet trimmed by an orange line; the trimmed part dashed."""
    s = Scene()
    _sheet(s, 0, 0, 12, 18, 0)
    s.line([(12, 0, 0), (22, 0, 0), (22, 18, 0), (12, 18, 0)], INK, 1.6, dash="3 2.5",
           layer=9)
    s.line([(12, -3, 0), (12, 21, 0)], ORANGE[2], 3.4, layer=10)
    return s.render()


def extend_surface():
    """A green sheet carried on past its edge (dashed), with an arrow."""
    s = Scene()
    _sheet(s, 0, 0, 14, 18, 0)
    _sheet(s, 14, 0, 22, 18, 0, opacity=0.35, layer=1)
    s.line([(14, 0, 0), (22, 0, 0), (22, 18, 0), (14, 18, 0)], INK, 1.6, dash="3 2.5",
           layer=9)
    s.arrow((12, 9, 0), (22, 9, 0), INK, 2.6)
    return s.render()


def delete_face():
    """A grey block with its top face gone."""
    s = Scene()
    top = rect(0, 0, 18, 16, 14)
    s.walls(top, 14, GREY, floor=True, layer=0)
    for q, h in (([(18, 0, 0), (18, 16, 0), (18, 16, 14), (18, 0, 14)], (1, 0, 0)),
                 ([(0, 0, 0), (18, 0, 0), (18, 0, 14), (0, 0, 14)], (0, -1, 0))):
        s.add(Face([q], GREY, hint=h, layer=1))
    return s.render(SMALL, sign_badge("x", RED[2]))


def thicken():
    """A blue slab grown under a green surface."""
    s = Scene()
    s.box(0, 0, 0, 22, 18, 6, BLUE, top_pal=GREEN)
    return s.render()


def thicken_cut():
    """A grey block with a red slab cut out under a green surface."""
    s = Scene()
    s.box(0, 0, 0, 22, 18, 7, GREY)
    s.box(0, 0, 7, 22, 18, 12, RED, top_pal=GREEN, layer=2)
    return s.render()


# ---------------------------------------------------------------- stage 4

def _bulge_loop(z, r, bulge, n=48):
    pts = []
    for i in range(n):
        a = math.radians(360.0 * i / n)
        rr = r * (1 + bulge * math.cos(2 * a))
        pts.append((rr * math.cos(a), rr * math.sin(a), z))
    return pts


def boundary_add():
    """A blue body through a network: two profiles one way, curves the other."""
    s = Scene()
    n = 48
    rings = [_bulge_loop(0, 9, 0.0, n), _bulge_loop(8, 7, 0.25, n), _bulge_loop(16, 6, 0.0, n)]
    for a, b in zip(rings[:-1], rings[1:]):
        s.ruled(a, b, BLUE, cap_top=(b is rings[-1]), axis=(0, 0, 8))
    for ring in rings:
        s.line(ring + [ring[0]], ORANGE[2], 2.2, layer=10)
    for i in (6, 30):
        s.line([rings[0][i], rings[1][i], rings[2][i]], ORANGE[2], 2.2, layer=10)
    return s.render()


def boundary_cut():
    s = Scene()
    n = 48
    z = 10
    opening = _bulge_loop(z, 7, 0.2, n)
    floor = circle(0, 0, z - 7, 3.5, n)
    s.box(-11, -11, 0, 11, 11, z, GREY, holes=[opening])
    s.ruled(opening, floor, RED, cap_top=False, inward=True, layer=0, axis=(0, 0, z))
    s.add(Face([floor], RED, hint=(0, 0, 1), layer=0))
    s.line(opening + [opening[0]], ORANGE[2], 2.2, layer=10)
    return s.render()


def _open_loop(s, ring, z0, z1, pal=GREEN, layer=2):
    """Walls (two-sided, no caps) standing on an open or closed curve."""
    c = centroid(ring)
    for i in range(len(ring) - 1):
        q = [(ring[i][0], ring[i][1], z0), (ring[i + 1][0], ring[i + 1][1], z0),
             (ring[i + 1][0], ring[i + 1][1], z1), (ring[i][0], ring[i][1], z1)]
        m = centroid(q)
        s.add(Face([q], pal, hint=(m[0] - c[0], m[1] - c[1], 0), two_sided=True,
                   layer=layer))


def extrude_surface():
    """A green wall rising off an orange open curve, an arrow up."""
    s = Scene()
    curve = [(-12 + 24 * i / 16.0, 6 * math.sin(math.pi * i / 8.0), 0) for i in range(17)]
    _open_loop(s, curve, 0, 14)
    s.line(curve, ORANGE[2], 2.4, layer=10)
    s.arrow((0, 0, 14.5), (0, 0, 24))
    return s.render()


def revolve_surface():
    """An open green sleeve (no ends) round a dashed axis."""
    s = Scene()
    ring0 = circle(0, 0, 0, 10, 48)
    ring1 = circle(0, 0, 14, 6, 48)
    for i in range(48):
        j = (i + 1) % 48
        q = [ring0[i], ring0[j], ring1[j], ring1[i]]
        m = centroid(q)
        s.add(Face([q], GREEN, hint=(m[0], m[1], 0.4), two_sided=True, layer=2))
    _axis(s, 0, 0, -3, 19)
    s.arc_arrow(circle(0, 0, 2, 14.5, 24, 110, 330, closed=False))
    return s.render()


def sweep_surface():
    """A green bent strip (one wall) along a dashed path."""
    s = Scene()
    outer, _inner = _bend(11, 15, 0, 90, 0, 0)
    ring = [(x, y) for x, y in outer]
    _open_loop(s, [(x, y, 0) for x, y in ring], 0, 9)
    path = [(12 * math.cos(math.radians(a)), 12 * math.sin(math.radians(a)), 9.1)
            for a in range(0, 91, 6)]
    s.line(path, ORANGE[2], 2.0, dash="3 2.5", layer=10)
    return s.render()


def loft_surface():
    """An open green skin from a square to a circle (no ends)."""
    s = Scene()
    n = 48
    s.ruled(_square_ring(0, 0, 0, 10, n), circle(0, 0, 16, 6, n), GREEN, cap_top=False,
            axis=(0, 0, 8))
    return s.render()


def boundary_surface():
    """An open green skin through a network of orange curves."""
    s = Scene()
    n = 48
    rings = [_bulge_loop(0, 9, 0.0, n), _bulge_loop(8, 7, 0.25, n), _bulge_loop(16, 6, 0.0, n)]
    for a, b in zip(rings[:-1], rings[1:]):
        s.ruled(a, b, GREEN, cap_top=False, axis=(0, 0, 8))
    for ring in rings:
        s.line(ring + [ring[0]], ORANGE[2], 2.2, layer=10)
    for i in (6, 30):
        s.line([rings[0][i], rings[1][i], rings[2][i]], ORANGE[2], 2.2, layer=10)
    return s.render()


def intersect():
    """Two crossing blocks, their shared region blue."""
    s = Scene()
    s.box(0, 0, 0, 14, 14, 14, GREY, opacity=0.55, layer=1)
    s.box(7, 7, 7, 21, 21, 21, GREY, opacity=0.55, layer=3)
    s.box(7, 7, 7, 14, 14, 14, BLUE, layer=2)
    return s.render()


def dome():
    """A grey block with a blue dome on top."""
    s = Scene()
    s.box(-11, -11, 0, 11, 11, 8, GREY)
    _dome(s, 0, 0, 8, 9, 7, pal=BLUE)
    return s.render()


def wrap():
    """A grey cylinder with a blue patch raised on its side."""
    s = Scene()
    s.cylinder(0, 0, 0, 22, 9, GREY)
    r1 = 10.6
    for i in range(10):
        a0 = math.radians(-20 + 6 * i)
        a1 = math.radians(-20 + 6 * (i + 1))
        for z0, z1 in ((6, 16),):
            q = [(r1 * math.cos(a0), r1 * math.sin(a0), z0),
                 (r1 * math.cos(a1), r1 * math.sin(a1), z0),
                 (r1 * math.cos(a1), r1 * math.sin(a1), z1),
                 (r1 * math.cos(a0), r1 * math.sin(a0), z1)]
            m = centroid(q)
            s.add(Face([q], BLUE, hint=(m[0], m[1], 0), layer=3))
    return s.render()


# ---------------------------------------------------------------- patterns II

def curve_pattern():
    """Cubes along an orange arc."""
    s = Scene()
    pts = [(22 * math.cos(math.radians(a)) - 2, 22 * math.sin(math.radians(a)) - 14, 0)
           for a in range(30, 151, 5)]
    s.line(pts, ORANGE[2], 2.6, layer=0)
    for k, a in enumerate((45, 90, 135)):
        x, y = 22 * math.cos(math.radians(a)) - 2, 22 * math.sin(math.radians(a)) - 14
        _cube(s, x - 3.5, y - 3.5, 0, 7, BLUE, 1.0 if k == 0 else 0.5, layer=2)
    return s.render()


def sketch_pattern():
    """Cubes on scattered orange sketch points."""
    s = Scene()
    for k, (x, y) in enumerate(((0, 0), (16, 4), (6, 18), (22, 20))):
        _cube(s, x - 3, y - 3, 0, 6, BLUE, 1.0 if k == 0 else 0.5, layer=2)
    s.line([(0, 0, 0), (16, 4, 0), (22, 20, 0), (6, 18, 0), (0, 0, 0)], ORANGE[2], 2.4,
           dash="3 2", layer=0)
    return s.render()


def table_pattern():
    """A little table beside a column of cubes."""
    body = ('<rect x="6" y="8" width="26" height="40" rx="2" fill="#ffffff" stroke="%s" '
            'stroke-width="2"/>' % INK)
    for y in (18, 28, 38):
        body += '<path d="M6 %d L32 %d" stroke="%s" stroke-width="1.6"/>' % (y, y, INK)
    body += '<path d="M19 8 L19 48" stroke="%s" stroke-width="1.6"/>' % INK
    s = Scene()
    for k in range(2):
        _cube(s, 0, k * 12, 0, 9, BLUE, 1.0 if k == 0 else 0.5)
    inner = s.render((30, 4, 62, 60))
    return inner.replace("\n</svg>", body + "\n</svg>")


def fill_pattern():
    """A grey plate filled with red holes."""
    s = Scene()
    holes = []
    for i in range(3):
        for j in range(3):
            holes.append(circle(4 + i * 8, 4 + j * 8, 4, 2.2, 16))
    s.box(-2, -2, 0, 26, 26, 4, GREY, holes=holes)
    for h in holes:
        s.walls(h, 3, RED, floor=True, layer=0)
    return s.render()


# ---------------------------------------------------------------- curves

def _dots(s, pts, color=INK, r=1.2):
    for p in pts:
        s.line([p, (p[0] + 0.01, p[1], p[2])], color, 5.0, layer=11)


def projected_curve():
    """A curve on a block's top, projected down from a flat sketch line above."""
    s = Scene()
    s.box(0, 0, 0, 22, 18, 8, GREY)
    top = [(2 + 18 * t / 20.0, 9 + 5 * math.sin(t / 20.0 * 2 * math.pi), 8) for t in range(21)]
    s.line(top, ORANGE[2], 3.0, layer=10)
    above = [(p[0], p[1], 20) for p in top]
    s.line(above, ORANGE[2], 1.6, dash="3 2", layer=10)
    s.arrow((11, 9, 19), (11, 9, 10), INK, 2.2)
    return s.render()


def composite_curve():
    """Three orange pieces joined end to end."""
    s = Scene()
    a = [(0, 0, 0), (12, 0, 0)]
    b = [(12 + 6 * math.sin(math.radians(t)), 6 - 6 * math.cos(math.radians(t)), 0)
         for t in range(0, 181, 15)]
    c = [(12, 12, 0), (12, 12, 14)]
    for seg in (a, b, c):
        s.line(seg, ORANGE[2], 3.4, layer=10)
    _dots(s, [(12, 0, 0), (12, 12, 0)])
    return s.render()


def curve_xyz():
    """A smooth orange curve through four points."""
    s = Scene()

    def at(t):
        return (24 * t, 10 * math.sin(t * math.pi * 1.5), 14 * t)
    curve = [at(k / 40.0) for k in range(41)]
    s.line(curve, ORANGE[2], 3.2, layer=10)
    _dots(s, [at(t) for t in (0.0, 1 / 3.0, 2 / 3.0, 1.0)])
    return s.render()


def curve_points():
    """An orange curve through the corners of a grey block."""
    s = Scene()
    s.box(0, 0, 0, 20, 16, 10, GREY)
    pts = [(0, 16, 10), (20, 16, 10), (20, 0, 10), (20, 0, 0)]
    s.line(pts, ORANGE[2], 3.0, layer=10)
    _dots(s, pts, ORANGE[2])
    return s.render()


# ---------------------------------------------------------------- surfaces II

def ruled_surface():
    """A grey block with a green strip standing off its top edge."""
    s = Scene()
    s.box(0, 0, 0, 22, 16, 8, GREY)
    s.add(Face([[(0, 0, 8), (22, 0, 8), (22, -4, 18), (0, -4, 18)]], GREEN, hint=(0, -1, 0.4),
               two_sided=True, layer=3))
    return s.render()


def radiate_surface():
    """A grey block with a flat green skirt spreading from its top edges."""
    s = Scene()
    s.box(5, 5, 0, 19, 17, 10, GREY, layer=2)
    outer = rect(-2, -2, 26, 24, 5)
    inner = rect(5, 5, 19, 17, 5)
    s.add(Face([outer, inner], GREEN, hint=(0, 0, 1), two_sided=True, layer=1))
    return s.render()


def untrim_surface():
    """A green face with its hole filled (dashed), grown past its edge."""
    s = Scene()
    s.add(Face([rect(0, 0, 22, 18, 0)], GREEN, hint=(0, 0, 1), two_sided=True, layer=2))
    s.line(circle(11, 9, 0, 4, 32) + [circle(11, 9, 0, 4, 32)[0]], INK, 1.6, dash="3 2",
           layer=9)
    s.line([(22, 0, 0), (27, 0, 0), (27, 23, 0), (0, 23, 0), (0, 18, 0)], INK, 1.6,
           dash="3 2", layer=9)
    return s.render()


def mid_surface():
    """A grey plate, faded, with a green sheet through its middle."""
    s = Scene()
    s.box(0, 0, 0, 22, 18, 8, GREY, opacity=0.4, layer=1)
    s.add(Face([rect(0, 0, 22, 18, 4)], GREEN, hint=(0, 0, 1), two_sided=True, layer=2))
    return s.render()


def surface_cut():
    """A grey block cut by a green sheet, the part above gone (dashed)."""
    s = Scene()
    s.box(0, 0, 0, 20, 16, 8, GREY, top_pal=RED)
    s.add(Face([rect(-3, -3, 23, 19, 8)], GREEN, hint=(0, 0, 1), two_sided=True,
               opacity=0.7, layer=3))
    s.line([(0, 0, 8), (0, 0, 16), (20, 0, 16), (20, 0, 8)], INK, 1.6, dash="3 2", layer=9)
    return s.render()


def replace_face():
    """A grey block whose top is now a curved green surface."""
    s = Scene()
    n = 12
    xs = [22.0 * i / n for i in range(n + 1)]
    zs = [8 + 4 * math.sin(math.pi * x / 22.0) for x in xs]
    prof = [(0, 0)] + [(x, z) for x, z in zip(xs, zs)] + [(22, 0)]
    s.prism_y(prof, 0, 16, GREY, accent=range(1, n + 1), accent_pal=GREEN)
    return s.render()


# ---------------------------------------------------------------- deform

def flex():
    """A blue bar bent over."""
    s = Scene()
    n = 12
    inner, outer = [], []
    for k in range(n + 1):
        a = math.radians(90.0 * k / n)
        inner.append((14 - 8 * math.cos(a), 0, 8 * math.sin(a)))
        outer.append((14 - 16 * math.cos(a), 0, 16 * math.sin(a)))
    prof = [(p[0], p[2]) for p in inner] + [(p[0], p[2]) for p in reversed(outer)]
    s.prism_y(prof, 0, 10, BLUE)
    return s.render()


def scale_icon():
    """A small grey cube and a big blue one, an arrow between."""
    s = Scene()
    _cube(s, 0, 0, 0, 13, BLUE, layer=1)
    _cube(s, 17, 17, 0, 6, GREY, layer=2)
    s.arrow((19, 19, 7), (12, 12, 13), INK, 2.2)
    return s.render()


def deform_icon():
    """A grey slab with a blue bump pushed up out of it, an arrow up."""
    s = Scene()
    s.box(0, 0, 0, 24, 20, 5, GREY)
    _dome(s, 12, 10, 5, 7, 7, pal=BLUE, layer=3)
    s.arrow((12, 10, 13), (12, 10, 22), INK, 2.6)
    return s.render()


def indent_icon():
    """A blue plate bent over a grey ball pressed up into it."""
    s = Scene()
    n = 16
    prof = [(-15, 0), (-7, 0)]
    for k in range(1, n):
        a = math.pi * k / n
        prof.append((-7 * math.cos(a), 7 * math.sin(a)))
    prof += [(7, 0), (15, 0), (15, 2.5)]
    for k in range(n + 1):
        a = math.pi * k / n
        x, y = 9.5 * math.cos(a), 9.5 * math.sin(a)
        prof.append((x, max(y, 2.5)))
    prof += [(-15, 2.5)]
    s.cylinder(0, 7, -6, 0, 6.2, GREY, layer=1)
    s.prism_y(prof, 0, 14, BLUE, layer=2)
    return s.render()


def freeform_icon():
    """A grey block whose top is a blue wave, with control dots."""
    s = Scene()
    s.box(0, 0, 0, 22, 18, 6, GREY, top_pal=GREY)
    _dome(s, 11, 9, 6, 8, 6, pal=BLUE, layer=3)
    _dots(s, [(11, 9, 12.2), (5, 4, 6.4), (17, 14, 6.4)], ORANGE[2])
    return s.render()


def surface_flatten():
    """A curved green sheet and the same sheet laid flat beside it."""
    s = Scene()
    for i in range(8):
        a0 = math.radians(-70 + 140 * i / 8.0)
        a1 = math.radians(-70 + 140 * (i + 1) / 8.0)
        p0 = (-6 + 8 * math.sin(a0), -8 * math.cos(a0) + 4)
        p1 = (-6 + 8 * math.sin(a1), -8 * math.cos(a1) + 4)
        q = [(p0[0], p0[1], 8), (p1[0], p1[1], 8), (p1[0], p1[1], 20), (p0[0], p0[1], 20)]
        m = centroid(q)
        s.add(Face([q], GREEN, hint=(m[0] + 6, m[1] - 4, 0.3), two_sided=True, layer=2))
    _sheet(s, 2, 2, 22, 14, 0, pal=GREEN, layer=1)
    s.arrow((0, 0, 7), (9, 6, 1), INK, 2.4)
    return s.render()


def rebuild():
    """A block with two arrows chasing round it."""
    s = Scene()
    s.box(0, 0, 0, 14, 14, 10, GREY)
    out = s.render(box=(14, 16, 50, 52))
    arrows = ('<path d="M12 30 A20 20 0 0 1 46 14" fill="none" stroke="#2f62a8" '
              'stroke-width="4.2" stroke-linecap="round"/>'
              '<path d="M47 5 L48 17 L37 15 Z" fill="#2f62a8"/>'
              '<path d="M52 34 A20 20 0 0 1 18 50" fill="none" stroke="#2f62a8" '
              'stroke-width="4.2" stroke-linecap="round"/>'
              '<path d="M17 59 L16 47 L27 49 Z" fill="#2f62a8"/>')
    return out.replace("\n</svg>", "\n" + arrows + "\n</svg>")


def whats_wrong():
    """A sheet with a red error mark and a yellow warning mark."""
    body = ('<rect x="9" y="6" width="46" height="52" rx="4" fill="#ffffff" stroke="#2e3436" '
            'stroke-width="2.4"/>'
            '<circle cx="22" cy="21" r="8" fill="#e04848"/>'
            '<path d="M22 16 L22 22 M22 25 L22 25.5" stroke="#ffffff" stroke-width="2.8" '
            'stroke-linecap="round"/>'
            '<path d="M35 18 L48 18 M35 24 L45 24" stroke="#9ca197" stroke-width="2.6" '
            'stroke-linecap="round"/>'
            '<path d="M22 34 L30 48 L14 48 Z" fill="#f8c33d" stroke="#d9730b" '
            'stroke-width="1.6" stroke-linejoin="round"/>'
            '<path d="M22 38 L22 43 M22 45.5 L22 46" stroke="#2e3436" stroke-width="2.2" '
            'stroke-linecap="round"/>'
            '<path d="M35 41 L48 41 M35 47 L45 47" stroke="#9ca197" stroke-width="2.6" '
            'stroke-linecap="round"/>')
    return svg(body)


def context_toolbar():
    """A pointer with a small bar of three tools beside it."""
    body = ('<rect x="20" y="8" width="40" height="18" rx="3" fill="#ffffff" stroke="#2e3436" '
            'stroke-width="2.2"/>'
            '<rect x="24" y="12" width="9" height="10" rx="1.5" fill="#5b8fd1"/>'
            '<rect x="35.5" y="12" width="9" height="10" rx="1.5" fill="#8ae234"/>'
            '<rect x="47" y="12" width="9" height="10" rx="1.5" fill="#f8a33d"/>'
            '<path d="M8 30 L8 58 L15 51 L20 61 L25 58 L20 49 L29 48 Z" fill="#ffffff" '
            'stroke="#2e3436" stroke-width="2.4" stroke-linejoin="round"/>')
    return svg(body)


ICONS = {
    "SolidDesign": workbench,
    "Part": part,
    "ExtrudeAdd": extrude_add, "ExtrudeCut": extrude_cut, "ExtrudeSurface": extrude_surface,
    "RevolveSurface": revolve_surface, "SweepSurface": sweep_surface,
    "LoftSurface": loft_surface, "BoundarySurface": boundary_surface,
    "RevolveAdd": revolve_add, "RevolveCut": revolve_cut,
    "SweepAdd": sweep_add, "SweepCut": sweep_cut,
    "LoftAdd": loft_add, "LoftCut": loft_cut,
    "Fillet": fillet, "Chamfer": chamfer, "Shell": shell, "Draft": draft, "Rib": rib,
    "HoleWizard": hole_wizard,
    "LinearPattern": linear_pattern, "CircularPattern": circular_pattern, "Mirror": mirror,
    "Combine": combine, "Split": split, "DeleteBody": delete_body, "MoveCopy": move_copy,
    "Plane": plane, "Axis": axis, "Point": point, "CoordinateSystem": coordinate_system,
    "Helix": helix, "Thread": thread, "OffsetSurface": offset_surface,
    "MoveFace": move_face, "SplitLine": split_line,
    "PlanarSurface": planar_surface, "Knit": knit, "FilledSurface": filled_surface,
    "TrimSurface": trim_surface, "ExtendSurface": extend_surface, "DeleteFace": delete_face,
    "Thicken": thicken, "ThickenCut": thicken_cut,
    "BoundaryAdd": boundary_add, "BoundaryCut": boundary_cut, "Intersect": intersect,
    "Dome": dome, "Wrap": wrap,
    "CurvePattern": curve_pattern, "SketchPattern": sketch_pattern,
    "TablePattern": table_pattern, "FillPattern": fill_pattern,
    "ProjectedCurve": projected_curve, "CompositeCurve": composite_curve,
    "CurveXYZ": curve_xyz, "CurvePoints": curve_points,
    "RuledSurface": ruled_surface, "RadiateSurface": radiate_surface,
    "UntrimSurface": untrim_surface, "MidSurface": mid_surface, "SurfaceCut": surface_cut,
    "ReplaceFace": replace_face, "Flex": flex, "Scale": scale_icon,
    "Rebuild": rebuild, "Deform": deform_icon, "Indent": indent_icon,
    "Freeform": freeform_icon, "SurfaceFlatten": surface_flatten,
    "WhatsWrong": whats_wrong, "ContextToolbar": context_toolbar,
    "BodySolid": body_solid, "BodySurface": body_surface,
    "RollbackBar": rollback_bar,
}


def badge(src, color):
    b = ('<circle cx="49" cy="49" r="13" fill="{}" stroke="#ffffff" stroke-width="3"/>'
         '<path d="M49 41 L49 51" stroke="#ffffff" stroke-width="4.5" stroke-linecap="round"/>'
         '<circle cx="49" cy="56.5" r="2.4" fill="#ffffff"/>').format(color)
    return src.replace("\n</svg>", b + "\n</svg>")


def faded(src):
    return src.replace('viewBox="0 0 64 64">', 'viewBox="0 0 64 64"><g opacity="0.35">', 1) \
        .replace("\n</svg>", "</g>\n</svg>")


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):                 # drop icons no longer made
        if f.endswith(".svg"):
            os.remove(os.path.join(OUT, f))
    for name, fn in ICONS.items():
        src = fn()
        for suffix, text in (("", src), ("_error", badge(src, "#d93025")),
                             ("_warning", badge(src, "#e8a200")),
                             ("_rolled", faded(src))):
            with open(os.path.join(OUT, name + suffix + ".svg"), "w") as fh:
                fh.write(text)
    print("wrote", len(os.listdir(OUT)), "icons to", os.path.normpath(OUT))


if __name__ == "__main__":
    main()
