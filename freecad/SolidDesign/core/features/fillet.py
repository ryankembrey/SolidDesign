# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fillet (SolidWorks' Fillet): Constant Size, Variable Size, Face Fillet and
Full Round Fillet.

- **Constant Size:** one radius on the picked edges (a face fillets all its edges).
- **Variable Size:** the radius runs from a start to an end radius along each chain
  of tangent edges.
- **Face Fillet:** rounds where two sets of faces meet.
- **Full Round Fillet:** replaces a centre face with a round that meets the two
  side faces tangentially (a rib's top); straight ribs between parallel planar
  sides in this version.

Edges on several bodies are filleted body by body; each body keeps its ID.
"""

import FreeCAD as App
import Part

from .. import topo
from . import common, edges as edgemod

CONSTANT = "Constant Size"
VARIABLE = "Variable Size"
FACE = "Face Fillet"
FULL_ROUND = "Full Round Fillet"
TYPES = [CONSTANT, VARIABLE, FACE, FULL_ROUND]


class Params(object):
    def __init__(self):
        self.kind = CONSTANT
        self.items = []             # picked edges/faces (shapes from the model before)
        self.radius = 1.0
        self.start_radius = 1.0     # Variable Size
        self.end_radius = 3.0
        self.reverse = False        # Variable Size: swap which end is the start
        self.faces1 = []            # Face Fillet: face set 1; Full Round: side face set 1
        self.faces2 = []            # Face Fillet: face set 2; Full Round: side face set 2
        self.centre = []            # Full Round: centre face set
        self.tangent = True         # Tangent propagation
        self.feature = "Fillet"
        self.tag = 1


def compute(p, base):
    """Returns (Result, preview)."""
    if p.kind == FULL_ROUND:
        return _full_round(p, base)
    if p.kind == FACE:
        groups = _shared_edges(p, base)
    else:
        if not p.items:
            raise topo.GeometryError("Pick the edges or faces to fillet.")
        groups = edgemod.by_body(base, p.items)
    if p.kind == VARIABLE:
        if p.start_radius <= 0 or p.end_radius <= 0:
            raise topo.GeometryError("Both radii must be greater than zero.")
    elif p.radius <= 0:
        raise topo.GeometryError("The radius must be greater than zero.")
    out = base.copy()
    res = common.Result(out)
    changed = []
    for bid, picked in groups.items():
        body = base.get(bid)
        es = [e for e in picked if e.ShapeType == "Edge"]
        if not es:
            continue
        if p.tangent:
            es = edgemod.tangent_chain(body.shape, es)
        shape = topo.tagged(body.shape, p.tag)
        try:
            if p.kind == VARIABLE:
                r = _variable(shape, es, p)
            else:
                r = shape.makeFillet(p.radius, es)
        except topo.GeometryError:
            raise
        except Exception:
            r = None
        if r is None or r.isNull() or not r.isValid() or (body.kind == "solid" and not r.Solids):
            what = "{:g} to {:g}".format(p.start_radius, p.end_radius) \
                if p.kind == VARIABLE else "{:g}".format(p.radius)
            raise topo.GeometryError(
                "The fillet failed on {} body. The radius ({}) may be too large for the "
                "selected edges, or the edges may meet at a corner it can't blend. Try a "
                "smaller radius.".format(_name(bid), what))
        if r.ShapeType == "Compound" and len(r.Solids) == 1:
            r = r.Solids[0]
        out.replace(bid, r, p.feature)
        res.touched.append(bid)
        changed.append(r)
    preview = topo.compound(changed, p.tag) if changed else None
    return res, preview


def _name(bid):
    return "the" if not bid else "the {}".format(bid.split(":")[0])


# ------------------------------------------------------------------ variable size

def _chains(es):
    """Group edges into connected chains, each in order from one end."""
    left = list(es)
    chains = []
    while left:
        chain = [left.pop(0)]
        grown = True
        while grown:
            grown = False
            for e in list(left):
                ends = [chain[0].Vertexes[0], chain[0].Vertexes[-1],
                        chain[-1].Vertexes[0], chain[-1].Vertexes[-1]]
                if any(v.isSame(w) for v in e.Vertexes for w in ends):
                    left.remove(e)
                    chain.append(e)
                    grown = True
        chains.append(Part.__sortEdges__(chain))
    return chains


def _variable(shape, es, p):
    """Per-edge (start, end) radii, linear along each chain's length."""
    r0, r1 = (p.end_radius, p.start_radius) if p.reverse else (p.start_radius, p.end_radius)
    radii = []
    for chain in _chains(es):
        total = sum(e.Length for e in chain)
        # Where the chain starts: the end of the first edge not shared with the next.
        if len(chain) > 1:
            shared = [v for v in chain[0].Vertexes
                      if any(v.isSame(w) for w in chain[1].Vertexes)]
            start = [v for v in chain[0].Vertexes if not v.isSame(shared[0])][0].Point \
                if shared else chain[0].Vertexes[0].Point
        else:
            start = chain[0].valueAt(chain[0].FirstParameter)
        run = 0.0
        here = start
        for e in chain:
            a, b = e.valueAt(e.FirstParameter), e.valueAt(e.LastParameter)
            fwd = (a - here).Length <= (b - here).Length
            ra = r0 + (r1 - r0) * (run / total)
            rb = r0 + (r1 - r0) * ((run + e.Length) / total)
            radii.append((e, ra, rb) if fwd else (e, rb, ra))
            run += e.Length
            here = b if fwd else a
    if len(radii) == 1:
        e, ra, rb = radii[0]
        return shape.makeFillet(ra, rb, [e])
    with topo._Scratch() as doc:
        base = doc.addObject("Part::Feature", "Base")
        base.Shape = shape
        f = doc.addObject("Part::Fillet", "Fillet")
        f.Base = base
        idx = []
        for e, ra, rb in radii:
            i = next((k for k, x in enumerate(shape.Edges, 1) if x.isSame(e)), None)
            if i is None:
                raise topo.GeometryError("An edge to fillet isn't on its body. Re-pick it.")
            idx.append((i, ra, rb))
        f.Edges = idx
        base.recompute()
        f.recompute()
        if f.Shape.isNull():
            return None
        out = Part.Shape()
        out.importBrepFromString(f.Shape.exportBrepToString())
    out.Tag = int(p.tag)
    return out


# ------------------------------------------------------------------ face fillet

def _shared_edges(p, base):
    """Face Fillet: the edges where face set 1 meets face set 2, by body."""
    if not p.faces1 or not p.faces2:
        raise topo.GeometryError("Pick the faces of Face Set 1 and Face Set 2.")
    g1 = edgemod.faces_by_body(base, p.faces1)
    g2 = edgemod.faces_by_body(base, p.faces2)
    out = {}
    for bid, fs1 in g1.items():
        fs2 = g2.get(bid, [])
        es = []
        for f1 in fs1:
            for e in f1.Edges:
                if any(any(e.isSame(x) for x in f2.Edges) for f2 in fs2) and \
                        not any(e.isSame(x) for x in es):
                    es.append(e)
        if es:
            out[bid] = es
    if not out:
        raise topo.GeometryError("The two face sets don't meet. A face fillet across a gap "
                                 "isn't supported yet: pick faces that share edges.")
    return out


# ------------------------------------------------------------------ full round

def _plane(face, what):
    if face.Surface.TypeId != "Part::GeomPlane":
        raise topo.GeometryError("A full round needs planar {} in this version.".format(what))
    u0, u1, v0, v1 = face.ParameterRange
    n = face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
    return face.Vertexes[0].Point, n


def _full_round(p, base):
    if not (p.faces1 and p.centre and p.faces2):
        raise topo.GeometryError("Pick Side Face Set 1, the Centre Face Set and Side Face "
                                 "Set 2.")
    if len(p.faces1) != 1 or len(p.faces2) != 1 or len(p.centre) != 1:
        raise topo.GeometryError("A full round takes one face in each set in this version.")
    groups = edgemod.faces_by_body(base, list(p.faces1) + list(p.centre) + list(p.faces2))
    if len(groups) != 1:
        raise topo.GeometryError("The three faces must be on one body.")
    bid = list(groups)[0]
    body = base.get(bid)
    find = lambda f: edgemod.find_in(body.shape, f)          # noqa: E731
    s1, c, s2 = find(p.faces1[0]), find(p.centre[0]), find(p.faces2[0])
    p1, n1 = _plane(s1, "side faces")
    p2, n2 = _plane(s2, "side faces")
    pc, nc = _plane(c, "centre face")
    if abs(abs(n1.dot(n2)) - 1) > 1e-6:
        raise topo.GeometryError("The side faces must be parallel in this version.")
    if abs(nc.dot(n1)) > 1e-6:
        raise topo.GeometryError("The centre face must be square to the side faces.")
    w = abs((p2 - p1).dot(n1))
    if w < 1e-6:
        raise topo.GeometryError("The side faces are in the same plane.")
    r = w / 2.0
    e = nc.cross(n1)
    e.normalize()
    mid = p1 + n1 * ((p2 - p1).dot(n1) / 2.0)
    # Axis: in the mid-plane, a radius below the centre face.
    a0 = pc + n1 * ((mid - pc).dot(n1)) - nc * r
    ts = [(v.Point - a0).dot(e) for v in c.Vertexes]
    lo, hi = min(ts), max(ts)
    if hi - lo < 1e-6:
        raise topo.GeometryError("The centre face has no length along the round.")
    shape = topo.tagged(body.shape, p.tag)
    prism = c.extrude(nc * -r)
    cyl = Part.makeCylinder(r, hi - lo, a0 + e * lo, e)
    remove = topo.cut(prism, [cyl], p.tag)
    res_shape = topo.refine(topo.cut(shape, [remove], p.tag), p.tag)
    if not res_shape.Solids or not res_shape.isValid():
        raise topo.GeometryError("The full round failed. The side faces may not reach the "
                                 "centre face's edges.")
    r_out = res_shape.Solids[0] if len(res_shape.Solids) == 1 else res_shape
    out = base.copy()
    out.replace(bid, r_out, p.feature)
    res = common.Result(out)
    res.touched.append(bid)
    return res, topo.compound([r_out], p.tag)
