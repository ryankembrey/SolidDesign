# SPDX-License-Identifier: LGPL-2.1-or-later
"""The icon kit: one isometric renderer, one palette, one set of rules.

Every Solid Design icon is drawn with this, so they all share a projection, a
light, a line weight and a colour language.

THE RULES
=========

1. Simple. One idea per icon: the stock shape and the one thing the tool does to
   it. No badges, no text, no decoration. It must read at 16 px.

2. Isometric. True isometric, seen from (1, 1, 1): +x to the lower right, +y to
   the lower left, +z up. Solids are planar faces, shaded by the one light (tops
   lightest, the +y side mid, the +x side darkest). Outlines only at silhouettes
   and sharp edges.

3. Colour says what happens, and nothing else:

   - NEUTRAL (grey): what is already there - the part, the stock, the body.
   - ADD (green): material the tool adds (a boss, a rib, a dome, a thickened
     sheet). Green always means "adds".
   - CUT (red): material or things the tool removes (a cut, a hole, a deleted
     body or face). Red always means "removes".
   - Otherwise the accent of the tool's toolbar, for the part the tool works on
     or makes when it neither adds nor removes:
       FEATURE  blue    - Features toolbar (fillet, chamfer, draft, patterns...)
       BODY     violet  - Bodies toolbar (combine, split, move, deform...)
       REF      amber   - Reference Geometry (plane, axis, point...)
       SURFACE  teal    - Surfaces toolbar (the surface sheets)
       CURVE    magenta - Curves toolbar (the curves)
       EVAL     slate   - Evaluate and the workbench's own UI

   At most NEUTRAL plus one colour in an icon. The only exceptions: an icon that
   both adds and removes (green and red), and a surface tool that turns a teal
   sheet into material (teal and green, or teal and red).

4. Marks (arrows, axes, paths, dimensions) are INK, never coloured - except when
   the mark is the subject (a curve in the Curves toolbar is magenta). Helper
   geometry that is not the subject (a mirror plane, a cutting plane, a sketch)
   is an INK dashed outline, not a coloured face.

5. Consistent shapes: the stock block is about 18 x 14 x 10, a surface is a thin
   sheet, a curve is a 3 px line, arrows are INK with a filled head.
"""

import math

INK = "#2b3038"
LINE = 2.0              # outline width at 64 px
MARK = 3.0              # arrows, axes, paths

# (top, side facing +y, side facing +x): light, mid, dark.
NEUTRAL = ("#f5f6f8", "#d3d8de", "#a7aeb8")
ADD = ("#c8f0c3", "#5cc464", "#2e9441")
CUT = ("#ffd0cb", "#ef625a", "#bf322b")
FEATURE = ("#cfe2ff", "#5b9cf0", "#2c6ad0")
BODY = ("#e7dbff", "#9e76eb", "#6c45c2")
REF = ("#ffe4b0", "#f6aa2e", "#c97c08")
SURFACE = ("#c4eff1", "#2bb6c1", "#13838d")
CURVE = ("#ffd2ec", "#e2559f", "#ac2c72")
EVAL = ("#dde3ea", "#8a99ab", "#56667a")

PALETTES = {"NEUTRAL": NEUTRAL, "ADD": ADD, "CUT": CUT, "FEATURE": FEATURE, "BODY": BODY,
            "REF": REF, "SURFACE": SURFACE, "CURVE": CURVE, "EVAL": EVAL}


def stroke(pal):
    """The colour for a line or curve drawn in a palette: its dark tone."""
    return pal[2]


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
        # Outward side normals from the profile's winding, so concave profiles
        # (a hook, an L) shade and cull right.
        n = len(profile)
        area = sum(profile[i][0] * profile[(i + 1) % n][1] - profile[(i + 1) % n][0] * profile[i][1]
                   for i in range(n))
        sign = 1.0 if area > 0 else -1.0
        for y, s in ((y0, -1), (y1, 1)):
            self.add(Face([[(x, y, z) for x, z in profile]], pal, hint=(0, s, 0),
                          opacity=opacity, layer=layer))
        for i, (x, z) in enumerate(profile):
            x2, z2 = profile[(i + 1) % n]
            q = [(x, y0, z), (x2, y0, z2), (x2, y1, z2), (x, y1, z)]
            self.add(Face([q], accent_pal if i in accent else pal,
                          hint=(sign * (z2 - z), 0, -sign * (x2 - x)), opacity=opacity,
                          layer=layer))

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
    def arrow(self, a, b, color=INK, width=MARK, layer=9):
        self.marks.append((layer, "arrow", (a, b, color, width)))

    def line(self, pts, color=INK, width=2.0, dash=None, layer=9, opacity=1.0):
        self.marks.append((layer, "line", (pts, color, width, dash, opacity)))

    def dot(self, p, color=INK, r=2.4, layer=11):
        """A round point, *r* in pixels at 64 px."""
        self.marks.append((layer, "dot", (p, color, r)))

    def arc_arrow(self, pts, color=INK, width=MARK, layer=9):
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
            if kind == "arrow":
                pts = [data[0], data[1]]
            elif kind == "dot":
                pts = [data[0]]
            else:
                pts = data[0]
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
        if kind == "dot":
            p, color, r = data
            x, y = P(p)
            return '<circle cx="%.2f" cy="%.2f" r="%.2f" fill="%s" stroke="%s" stroke-width="1"/>' % (
                x, y, r, color, color)
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




# ---------------------------------------------------------------- shared shapes

def axis_mark(s, a, b, layer=10):
    """A centre line (dash-dot), for revolve axes and the like."""
    s.line([a, b], INK, 2.2, dash="6 3 1.5 3", layer=layer)


def path_mark(s, pts, layer=10):
    """A dashed path (a sweep's path, a pattern's curve)."""
    s.line(pts, INK, 2.2, dash="3.5 2.5", layer=layer)


def curve_mark(s, pts, pal=CURVE, width=MARK + 0.4, layer=10, dash=None):
    """A curve that is the subject of the icon: between its palette's mid and dark
    tones, so it holds up on light and dark toolbars alike."""
    s.line(pts, mix(pal[1], pal[2], 0.3), width, dash=dash, layer=layer)


def dots(s, pts, color=INK, r=2.4, layer=11):
    """Round points (a sketch's points, a curve's through points)."""
    for p in pts:
        s.dot(p, color, r, layer)


def sheet(s, x0, y0, x1, y1, z, pal=SURFACE, layer=2, opacity=1.0, holes=()):
    """A flat surface body: one face, seen from both sides."""
    s.add(Face([rect(x0, y0, x1, y1, z)] + list(holes), pal, normal=(0, 0, 1),
               two_sided=True, layer=layer, opacity=opacity))


def bend(r0, r1, a0, a1, n=16):
    """(outer, inner) arcs of an annular sector round the z axis, as (x, y)."""
    outer = [(r1 * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
              r1 * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
    inner = [(r0 * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
              r0 * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
    return outer, inner


def square_ring(cx, cy, z, half, n):
    """A square's outline as *n* points, starting on the same side as circle()."""
    pts = []
    for i in range(n):
        a = math.radians(360.0 * i / n)
        c, sn = math.cos(a), math.sin(a)
        k = half / max(abs(c), abs(sn))
        pts.append((cx + c * k, cy + sn * k, z))
    return pts


def flat(body):
    """A flat (non-isometric) icon from SVG markup: for UI icons only."""
    return svg(body)
