# SPDX-License-Identifier: LGPL-2.1-or-later
"""Body tools (spec 3.3): Combine, Delete/Keep Body, Split, Move/Copy Body.
Pure functions of a BodySet; IDs follow core/bodies.py."""

import FreeCAD as App
import Part

from . import topo
from .bodies import SOLID, pieces_of, split_pieces
from .features.common import Result

ADD = "Add"
SUBTRACT = "Subtract"
COMMON = "Common"
COMBINE_OPS = [ADD, SUBTRACT, COMMON]

DELETE = "Delete Bodies"
KEEP = "Keep Bodies"
DELETE_TYPES = [DELETE, KEEP]


def _need(base, ids, what):
    missing = [i for i in ids if i not in base]
    if missing:
        raise topo.GeometryError("{} body(ies) picked for {} no longer exist. Re-pick them."
                                 .format(len(missing), what))


# ------------------------------------------------------------------ Combine

def combine(base, op, main_id, tool_ids, feature, tag, alloc):
    """Add, Subtract or Common. Bodies used up disappear (SolidWorks)."""
    ids = ([main_id] if main_id else []) + [i for i in tool_ids if i != main_id]
    if op == SUBTRACT and not main_id:
        raise topo.GeometryError("Combine Subtract: pick the main body.")
    if len(ids) < 2:
        raise topo.GeometryError("Combine: pick at least two bodies." if op != SUBTRACT else
                                 "Combine Subtract: pick the bodies to subtract.")
    _need(base, ids, "Combine")
    for i in ids:
        if base.get(i).kind != SOLID:
            raise topo.GeometryError("Combine works on solid bodies only.")
    out = base.copy()
    res = Result(out)
    main = base.get(ids[0]).shape
    others = [base.get(i).shape for i in ids[1:]]
    if op == ADD:
        r = topo.refine(topo.fuse(main, others, tag), tag)
    elif op == SUBTRACT:
        r = topo.refine(topo.cut(main, others, tag), tag)
    else:
        r = main
        for o in others:
            r = topo.common(r, [o], tag)
        r = topo.refine(r, tag)
    parts = [p for p in pieces_of(r, SOLID) if p.Volume > 1e-9]
    if not parts:
        raise topo.GeometryError("Combine {}: nothing is left.".format(op))
    if op == ADD and len(parts) > 1:
        raise topo.GeometryError("Combine Add: the bodies don't touch. Pick bodies that touch "
                                 "or overlap.")
    for i in ids[1:]:
        out.remove(i)
    named = split_pieces(ids[0], parts, alloc)
    out.replace(ids[0], named[0][1], feature)
    prev = ids[0]
    for pid, s in named[1:]:
        out.insert_after(prev, pid, s, feature)
        res.created.append(pid)
        prev = pid
    res.touched.append(ids[0])
    return res, r


# ------------------------------------------------------------------ Delete/Keep

def delete_keep(base, kind, ids):
    if not ids:
        raise topo.GeometryError("Pick the bodies to {}.".format(
            "delete" if kind == DELETE else "keep"))
    _need(base, ids, "Delete/Keep Body")
    out = base.copy()
    res = Result(out)
    gone = ids if kind == DELETE else [b for b in base.ids() if b not in ids]
    if kind == KEEP and not gone:
        res.warnings.append("Every body is kept: nothing changes.")
    shapes = []
    for i in gone:
        shapes.append(base.get(i).shape)
        out.remove(i)
        res.touched.append(i)
    if not out.ids():
        res.warnings.append("No bodies are left.")
    return res, (topo.compound(shapes, 1) if shapes else None)


# ------------------------------------------------------------------ Split

def filled(face):
    """The face with its holes patched on its own surface."""
    if len(face.Wires) < 2:
        return face
    try:
        out = Part.Face(face.Surface, face.OuterWire)
        out.validate()
        if out.isValid() and out.Area > face.Area - 1e-9:
            return out
    except Exception:
        pass
    raise topo.GeometryError("Split: couldn't patch the holes in a curved trim face. "
                             "Use a plane or a surface body instead.")


def trim_shapes(planes=(), faces=(), sketches=(), surfaces=(), big=1000.0):
    """Turn trim tools into cutting faces: planes become large faces, sketches are
    swept both ways along their normal (as SolidWorks does), surface bodies are
    used as they are. A face has its inner loops filled: a protrusion whose
    every edge on the face is bounded by the face (a cylinder standing on a cube
    top) is cut off as if the face were a plane there. Loops that touch the
    face's outer boundary aren't inner loops, so they are not filled."""
    out = []
    for f in planes:
        s = f.Surface
        n = f.normalAt(0, 0) if f.BoundBox.DiagonalLength < 1e9 else App.Vector(s.Axis)
        p = App.Vector(s.Position) if hasattr(s, "Position") else f.CenterOfMass
        out.append(Part.Plane(p, n).toShape(-big, big, -big, big))
    for sk, normal in sketches:
        if not sk.Edges:
            raise topo.GeometryError("A sketch used to split is empty.")
        moved = sk.copy()
        moved.translate(normal * (-big))
        for e in moved.Edges:
            out.append(e.extrude(normal * (2 * big)))
    out.extend(filled(f) for f in faces)
    out.extend(surfaces)
    if not out:
        raise topo.GeometryError("Split: pick trim tools (planes, faces, surface bodies or "
                                 "sketches).")
    return out


def split(base, tools, target_ids, consume, keep_ids, feature, tag, alloc, refine=False):
    """Split bodies with trim tools.

    ``refine``: merge the faces the cut leaves split on one surface (a trim face
    with patched holes leaves the patch's outline on the face around it).

    ``keep_ids``: None to keep every piece, else the piece IDs to keep. With
    ``consume`` the largest piece keeps the body's ID (spec 5.2); without it the
    body stays and every piece is a new body.
    Returns (Result with .pieces, preview).
    """
    targets = target_ids or base.ids(SOLID)
    _need(base, targets, "Split")
    out = base.copy()
    res = Result(out)
    any_cut = False
    for bid in targets:
        body = base.get(bid)
        if not any(topo.touches(body.shape, t) for t in tools):
            continue
        r = topo.slice_by(body.shape, tools, tag)
        parts = [p for p in pieces_of(r, body.kind) if topo.size_of(p) > 1e-9]
        if refine and len(parts) > 1:
            parts = [topo.refine(p, tag) for p in parts]
        if len(parts) < 2:
            continue
        any_cut = True
        if consume:
            named = split_pieces(bid, parts, alloc)
            out.replace(bid, named[0][1], feature)
            prev = bid
            for pid, s in named[1:]:
                out.insert_after(prev, pid, s, feature)
                prev = pid
        else:
            ids = alloc.take(parts, prefix="{}:{}".format(feature, bid))
            named = list(zip(ids, parts))
            prev = bid
            for pid, s in named:
                out.insert_after(prev, pid, s, feature)
                prev = pid
        res.pieces.extend((pid, s, bid) for pid, s in named)
        res.touched.append(bid)
    if not any_cut:
        raise topo.GeometryError("Split: the trim tools don't cut any of the bodies.")
    if keep_ids is not None:
        known = {p[0] for p in res.pieces}
        keep = set(keep_ids) & known
        if not keep:
            res.warnings.append("None of the pieces picked to keep exist any more; every "
                                "piece was kept. Pick them again.")
        else:
            for pid, _s, _parent in res.pieces:
                if pid not in keep:
                    out.remove(pid)
    preview = topo.compound([p[1] for p in res.pieces], tag)
    return res, preview


# ------------------------------------------------------------------ Move/Copy

def move_copy(base, ids, step, copy, copies, feature, tag, alloc):
    """Move bodies by ``step`` (an App.Placement), or make ``copies`` copies, copy k
    moved k times (SolidWorks). Moved bodies keep their IDs."""
    if not ids:
        raise topo.GeometryError("Pick the bodies to move or copy.")
    _need(base, ids, "Move/Copy Body")
    out = base.copy()
    res = Result(out)
    moved = []
    for bid in ids:
        body = base.get(bid)
        if not copy:
            s = topo.transformed(body.shape, step, tag)
            out.replace(bid, s, feature)
            res.touched.append(bid)
            moved.append(s)
            continue
        if copies < 1:
            raise topo.GeometryError("The number of copies must be at least 1.")
        pl = App.Placement()
        shapes = []
        for _k in range(copies):
            pl = step.multiply(pl)
            shapes.append(topo.transformed(body.shape, pl, tag))
        new_ids = alloc.take(shapes, prefix="{}:{}".format(feature, bid))
        prev = bid
        for nid, s in zip(new_ids, shapes):
            out.insert_after(prev, nid, s, feature)
            res.created.append(nid)
            prev = nid
        moved.extend(shapes)
    return res, (topo.compound(moved, tag) if moved else None)


def step_placement(delta=App.Vector(), axis_point=None, axis_dir=None, angle=0.0):
    """One Move/Copy step: rotate about an axis by ``angle`` degrees, then translate."""
    pl = App.Placement(delta, App.Rotation())
    if axis_dir is not None and abs(angle) > 1e-12:
        rot = App.Placement(App.Vector(), App.Rotation(axis_dir, angle), axis_point)
        pl = pl.multiply(rot)
    return pl

