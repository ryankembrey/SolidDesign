# SPDX-License-Identifier: LGPL-2.1-or-later
"""The only module that calls OpenCASCADE shape operations (spec section 7).

Every operation here:
- takes shapes that carry a non-zero ``Tag`` (it tags untagged inputs with the
  caller's tag, so element maps are produced);
- returns a shape whose element map is checked; operations known to produce no
  map in FreeCAD 1.1 (loft, 2D offset) are listed in ``UNMAPPED_OPS`` and are
  reported, not hidden;
- turns OCC exceptions into :class:`GeometryError` with a plain message, so a bad
  parameter never takes FreeCAD down.

Nothing in here imports FreeCADGui or Qt.
"""

import math
from collections import OrderedDict

import FreeCAD as App
import Part

TOL = 1e-7          # geometric tolerance for comparisons
LIN_TOL = 1e-6      # linear tolerance used to decide "touching"

# Operations that FreeCAD 1.1.3 does not give an element map to (checked with
# freecadcmd 1.1.3 on 2026-11-16). Results of these lose history-based names;
# the faces they make are named by index until a later mapped op re-tags them.
UNMAPPED_OPS = {"loft", "offset2d", "move-unnamed", "sweep", "draft", "offsetfaces"}

# Collected warnings about missing element maps (tests read and clear this).
map_warnings = []


class GeometryError(Exception):
    """A geometry operation failed. The message is meant for the user."""


# ---------------------------------------------------------------- tagging

def tagged(shape, tag):
    """Return ``shape`` with a non-zero Tag. Copies only if it must change the tag."""
    if shape is None or shape.isNull():
        raise GeometryError("An input shape is empty.")
    if not shape.Tag:
        shape = shape.copy(False) if hasattr(shape, "copy") else shape
        shape.Tag = int(tag)
    return shape


def _check_map(result, op, tag):
    """Check that an operation result carries an element map."""
    if result is None or result.isNull():
        raise GeometryError("The {} operation produced no geometry.".format(op))
    if op in UNMAPPED_OPS:
        return result
    if result.ElementMapSize == 0 and (result.Faces or result.Edges):
        map_warnings.append("{} produced no element map (tag {})".format(op, tag))
    return result


def _run(op, tag, fn):
    try:
        return _check_map(fn(), op, tag)
    except GeometryError:
        raise
    except Part.OCCError as e:
        raise GeometryError("{} failed in OpenCASCADE: {}".format(op.capitalize(), _msg(e)))
    except Exception as e:  # OCC raises a zoo of types through the bindings
        raise GeometryError("{} failed: {}".format(op.capitalize(), _msg(e)))


def _msg(e):
    s = str(e).strip()
    return s if s else e.__class__.__name__


# ---------------------------------------------------------------- inputs

def shape_of(obj, subname=None):
    """A shape from a document object, keeping its element map and tag."""
    try:
        if subname:
            return Part.getShape(obj, subname, needSubElement=True)
        return Part.getShape(obj)
    except Exception as e:
        raise GeometryError("Could not read the shape of {}: {}".format(obj.Label, _msg(e)))


# ---------------------------------------------------------------- booleans

def fuse(base, tools, tag, fuzzy=0.0):
    """``fuzzy``: a tolerance for shapes that touch tangentially (a fillet's tool)."""
    base = tagged(base, tag)
    tools = [tagged(t, tag) for t in tools]
    if not tools:
        return base
    if fuzzy:
        out = _run("fuse", tag, lambda: base.fuse(tools, fuzzy))
    else:
        out = _run("fuse", tag, lambda: base.fuse(tools))
    had = sum(len(x.Solids) for x in [base] + tools)
    if had and not out.Solids:
        # OpenCASCADE sometimes loses everything when faces only touch (a ring sitting
        # on a cylinder's rim): try again with a little tolerance, else say so.
        size = max(base.BoundBox.DiagonalLength, 1.0)
        try:
            out = _run("fuse", tag, lambda: base.fuse(tools, 1e-6 * size))
        except GeometryError:
            out = None
        if out is None or not out.Solids:
            raise GeometryError("Joining the bodies failed: they only touch along an edge or "
                                "a face. Overlap them a little, or keep them as separate "
                                "bodies (Merge result off).")
    return out


def cut(base, tools, tag, fuzzy=0.0):
    base = tagged(base, tag)
    tools = [tagged(t, tag) for t in tools]
    if not tools:
        return base
    if fuzzy:
        return _run("cut", tag, lambda: base.cut(tools, fuzzy))
    return _run("cut", tag, lambda: base.cut(tools))


def common(base, tools, tag):
    base = tagged(base, tag)
    tools = [tagged(t, tag) for t in tools]
    return _run("common", tag, lambda: base.common(tools))


def refine(shape, tag):
    shape = tagged(shape, tag)
    return _run("refine", tag, lambda: shape.removeSplitter())


def compound(shapes, tag):
    shapes = [tagged(s, tag) for s in shapes]
    return _run("compound", tag, lambda: Part.makeCompound(shapes))


def slice_by(shape, tools, tag, mode="Split"):
    """Split ``shape`` with ``tools`` (faces/shells/planes) using BOPTools."""
    from BOPTools import SplitAPI
    shape = tagged(shape, tag)
    tools = [tagged(t, tag) for t in tools]
    return _run("split", tag, lambda: SplitAPI.slice(shape, tools, mode))


def general_fuse(shape, tools, tag):
    shape = tagged(shape, tag)
    tools = [tagged(t, tag) for t in tools]
    return _run("generalFuse", tag, lambda: shape.generalFuse(tools)[0])


# ---------------------------------------------------------------- shape making

def extrude(shape, vector, tag):
    shape = tagged(shape, tag)
    if vector.Length < TOL:
        raise GeometryError("The extrusion depth is zero.")
    return _run("extrude", tag, lambda: shape.extrude(vector))


def make_faces(wires, tag):
    """Faces from closed planar wires, nested wires becoming holes (bullseye)."""
    wires = [tagged(w, tag) for w in wires]
    return _run("face", tag, lambda: Part.makeFace(wires, "Part::FaceMakerBullseye"))


def loft(wires, tag, solid=True, ruled=True, closed=False):
    wires = [tagged(w, tag) if w.ShapeType != "Vertex" else w for w in wires]
    return _run("loft", tag, lambda: Part.makeLoft(wires, solid, ruled, closed))


def sweep(path, wire, tag, solid=True, fixed_normal=None, axis=None, ends=False):
    """Sweep a wire along a path wire. ``fixed_normal`` (a vector) keeps the
    profile's orientation constant (SolidWorks' Keep Normal Constant); ``axis``
    ((start, end) of a line) turns the profile about that line, as a helix needs
    (a spring, a thread); otherwise it follows the path (corrected Frenet).
    ``ends``: return where the profile ends up instead (the last section)."""
    def go():
        ps = Part.BRepOffsetAPI.MakePipeShell(path)
        if fixed_normal is not None:
            ps.setTrihedronMode(wire.BoundBox.Center, fixed_normal)
        elif axis is not None:
            spine = Part.Wire([Part.LineSegment(axis[0], axis[1]).toShape()])
            ps.setAuxiliarySpine(spine, True, 0)
        else:
            ps.setFrenetMode(False)
        ps.add(wire, False, False)
        ps.build()
        if ends:
            return ps.lastShape()
        if solid:
            ps.makeSolid()
        return ps.shape()
    if ends:
        return go()
    return tagged(_run("sweep", tag, go), tag)


def offset2d(shape, distance, tag, join=0, fill=False, open_result=False):
    shape = tagged(shape, tag)
    return _run("offset2d", tag,
                lambda: shape.makeOffset2D(distance, join, fill, open_result, False))


def transformed(shape, placement, tag):
    """Move a shape. In FreeCAD 1.1.3 a mapped shape keeps its map when moved.

    The moved shape shares the original's topology and geometry (as a clone
    does), with its own placement: 400 copies of a body are one body's worth of
    faces, and FreeCAD meshes them once. (``copy(False)`` made new topology for
    every copy.)"""
    had_map = shape.ElementMapSize > 0
    shape = tagged(shape, tag)

    def go():
        # transformed(identity, copy=False): a new handle on the same topology that
        # keeps its type (an Edge stays an Edge; Part.Shape() gives a plain Shape).
        s = shape.transformed(App.Matrix(), False)
        s.Placement = placement.multiply(s.Placement)
        _moved_copy(s, shape, placement)
        return s
    # A move can't lose names the shape never had (a primitive): don't report it.
    return _run("transform" if had_map else "move-unnamed", tag, go)


def draft(shape, faces, point, normal, pull, angle, tag):
    """Draft ``faces`` (indices into ``shape.Faces``, from 1) by ``angle`` degrees
    about the neutral plane through ``point`` with ``normal``. The part narrows
    along ``pull`` (SolidWorks' positive draft).

    FreeCAD 1.1 has no draft in Python, so OpenCASCADE's DraftAngle is reached
    through a PartDesign::Draft in a hidden, temporary document. Its element
    names belong to that document, so the result comes back without a map
    ("draft" is in UNMAPPED_OPS): faces keep their order, so they are named by
    index, as with a sweep.
    """
    shape = tagged(shape, tag)
    if not faces:
        raise GeometryError("Pick the faces to draft.")

    def go():
        with _Scratch() as doc:
            base = doc.addObject("Part::Feature", "Base")
            base.Shape = shape
            body = doc.addObject("PartDesign::Body", "Body")
            body.BaseFeature = base
            first = [o for o in body.Group if o.TypeId == "PartDesign::FeatureBase"][0]
            plane = doc.addObject("PartDesign::Plane", "Neutral")
            body.addObject(plane)
            plane.MapMode = "Deactivated"
            plane.Placement = App.Placement(point, App.Rotation(App.Vector(0, 0, 1), normal))
            line = doc.addObject("PartDesign::Line", "Pull")
            body.addObject(line)
            line.MapMode = "Deactivated"
            line.Placement = App.Placement(App.Vector(), App.Rotation(App.Vector(0, 0, 1), pull))
            dr = doc.addObject("PartDesign::Draft", "Draft")
            body.addObject(dr)
            dr.Base = (first, ["Face%d" % i for i in faces])
            dr.NeutralPlane = (plane, [""])
            dr.PullDirection = (line, [""])
            dr.Angle = float(angle)
            dr.Reversed = False
            for o in (base, first, plane, line, dr):
                o.recompute()
            if dr.Shape.isNull() or "Invalid" in dr.State or "Error" in dr.State:
                raise GeometryError("OpenCASCADE couldn't draft these faces at {:g}°. A face "
                                    "may not cross or meet the neutral plane, or the angle is "
                                    "too steep for the faces next to it.".format(angle))
            out = Part.Shape()
            out.importBrepFromString(dr.Shape.exportBrepToString())
        out = out.Solids[0] if len(out.Solids) == 1 else out
        if not out.isValid():
            raise GeometryError("The draft made an invalid solid. Try a smaller angle.")
        out.Tag = int(tag)
        return out
    return _run("draft", tag, go)


def offset_faces(shape, offsets, tag):
    """Move faces of a solid along their normals (``offsets``: {face: distance},
    positive outwards); the faces around them extend or trim to follow. FreeCAD
    gives the result no element map ("offsetfaces" is in UNMAPPED_OPS)."""
    shape = tagged(shape, tag)
    if shape.ShapeType != "Solid" and len(shape.Solids) == 1:
        shape = shape.Solids[0]

    def go():
        r = shape.offsetFaces(dict(offsets))
        if r.isNull() or not r.isValid() or not r.Solids:
            raise GeometryError("The faces couldn't be moved that far: the faces around them "
                                "can't follow. Try a smaller distance.")
        r.Tag = int(tag)
        return r
    return _run("offsetfaces", tag, go)


SCRATCH = "SDScratch"


def scratch_doc():
    """A hidden document for operations FreeCAD only offers as document objects.
    It stays open for the session and is emptied after each use: closing a
    document ends the transaction the user has open in theirs (their Cancel and
    Undo would stop working)."""
    for d in App.listDocuments().values():
        if d.Name == SCRATCH:
            return d
    active = App.ActiveDocument
    d = App.newDocument(SCRATCH, "Solid Design scratch", True, True)
    try:
        d.UndoMode = 0
    except Exception:
        pass
    if active is not None and App.ActiveDocument is not active:
        try:
            App.setActiveDocument(active.Name)
        except Exception:
            pass
    return d


def clear_scratch(doc):
    for _round in range(3):
        names = [o.Name for o in doc.Objects]
        if not names:
            return
        for n in reversed(names):
            try:
                if doc.getObject(n) is not None:
                    doc.removeObject(n)
            except Exception:
                pass


class _Scratch(object):
    """The scratch document, emptied afterwards; the active document is put back."""

    def __enter__(self):
        self.active = App.ActiveDocument
        self.doc = scratch_doc()
        clear_scratch(self.doc)
        return self.doc

    def __exit__(self, *exc):
        clear_scratch(self.doc)
        if self.active is not None and App.ActiveDocument is not self.active:
            try:
                App.setActiveDocument(self.active.Name)
            except Exception:
                pass
        return False


# ---------------------------------------------------------------- queries

def solids(shape):
    return list(shape.Solids) if shape and not shape.isNull() else []


# ---------------------------------------------------------------- measures, kept
#
# A body that no feature changes is the same shape (same topology, same place)
# from one feature to the next, and features measure it again and again: its
# volume and centre for its ID, its box to see what a tool touches. Each is
# worked out once per shape now. Shapes don't change once made, so a measure
# kept for a shape is the measure of that shape. A moved copy (topology shared,
# placed elsewhere: patterns) takes its volume from the original, its centre
# moved with it, and its box moved with it when the move has no rotation.

_MEASURES = OrderedDict()       # _key -> [(own handle on the shape, {what: value})]
_MEASURES_KEPT = 20000
measure_stats = {"hit": 0, "miss": 0}


def same_shape(a, b):
    """The same topology placed the same way: the same shape, even when FreeCAD
    gave the placement as a new location (isSame compares locations by identity,
    and a shape read back from a feature has a new one)."""
    try:
        return a.isPartner(b) and a.Placement.isSame(b.Placement, 1e-15)
    except Exception:
        return False


def _key(shape):
    """A key that the same shape always gets, wherever FreeCAD read it back from:
    its type, its counts of faces and edges, and where it is placed. (A shape's
    own hashCode takes in its location's identity, which is new each time a
    feature's shape is read; the same shapes still share a key with others,
    and same_shape tells them apart.)"""
    pl = shape.Placement
    b, q = pl.Base, pl.Rotation.Q
    return (shape.ShapeType, shape.countElement("Face"), shape.countElement("Edge"),
            round(b.x, 6), round(b.y, 6), round(b.z, 6),
            round(q[0], 9), round(q[1], 9), round(q[2], 9), round(q[3], 9))


# A quicker way in for a shape seen before through the very same location (most
# shapes: a body nothing moved): its hashCode, checked with isSame (which implies
# same_shape). Counting faces and edges for _key costs more than the lookup.
_BY_HASH = {}


def _remember(shape, held, d):
    try:
        h = shape.hashCode()
    except Exception:
        return
    if len(_BY_HASH) > 2 * _MEASURES_KEPT:
        _BY_HASH.clear()
    _BY_HASH.setdefault(h, []).append((held, d))


def _entry(shape, make=True):
    try:
        h = shape.hashCode()
    except Exception:
        h = None
    for s, d in _BY_HASH.get(h, ()):
        if s.isSame(shape):
            return d
    try:
        key = _key(shape)
    except Exception:
        return None
    bucket = _MEASURES.get(key)
    if bucket is not None:
        _MEASURES.move_to_end(key)
        for s, d in bucket:
            if same_shape(s, shape):
                _remember(shape, Part.Shape(shape), d)
                return d
    if not make:
        return None
    d = {}
    # Its own handle: a caller moving its shape object later can't move this one.
    held = Part.Shape(shape)
    _MEASURES.setdefault(key, []).append((held, d))
    _remember(shape, held, d)
    while len(_MEASURES) > _MEASURES_KEPT:
        _MEASURES.popitem(last=False)
    return d


def _measure(shape, what, fn):
    d = _entry(shape)
    if d is None:
        return fn()
    if what in d:
        measure_stats["hit"] += 1
        return d[what]
    src = d.get("_from")
    v = None
    if src is not None:
        original, pl = src
        if what == "size":
            v = size_of(original)
        elif what == "centroid":
            v = pl.multVec(centroid(original))
        elif what == "bbox" and pl.Rotation.isIdentity():
            v = bbox(original)
            v.move(pl.Base)
    if v is None:
        measure_stats["miss"] += 1
        v = fn()
    d[what] = v
    return v


def _moved_copy(copy, original, move):
    """Note that ``copy`` is ``original`` (same topology) moved by ``move``."""
    d = _entry(copy)
    if d is not None and not d:
        # Its own handle, of its own type (Part.Shape() gives a plain Shape, which
        # has no CenterOfMass: its centre was taken as its box's centre).
        d["_from"] = (_typed(original), App.Placement(move))


def clear_measures():
    _MEASURES.clear()
    _BY_HASH.clear()


def bbox(shape):
    """The shape's bounding box (a copy: change it freely)."""
    return App.BoundBox(_measure(shape, "bbox", lambda: shape.BoundBox))


def _apart(ga, gb, tol):
    if ga.intersect(gb):
        return False
    # BoundBox.intersect is strict; allow touching boxes through the gap test.
    return (ga.XMin - gb.XMax > tol or gb.XMin - ga.XMax > tol or
            ga.YMin - gb.YMax > tol or gb.YMin - ga.YMax > tol or
            ga.ZMin - gb.ZMax > tol or gb.ZMin - ga.ZMax > tol)


def box_gap(ga, gb, tol=LIN_TOL):
    """True when two boxes are more than ``tol`` apart."""
    return _apart(ga, gb, tol)


def boxes_apart(a, b, tol=LIN_TOL):
    """True when two shapes' boxes are more than ``tol`` apart: then the shapes
    can't touch (a quick test before a boolean that could only come out empty)."""
    return _apart(bbox(a), bbox(b), tol)


def touches(a, b, tol=LIN_TOL):
    """True when two shapes overlap or touch."""
    if _apart(bbox(a), bbox(b), tol):
        return False
    try:
        return a.distToShape(b)[0] <= tol
    except Exception:
        return False


def tool_parts(tool):
    """The pieces of a compound tool (a pattern of holes: one compound whose box
    spans the whole pattern), for touches_any; None for a single shape."""
    try:
        if tool.ShapeType == "Compound":
            parts = tool.childShapes()
            if len(parts) > 1:
                return parts
    except Exception:
        pass
    return None


def touches_any(a, tool, parts, tol=LIN_TOL):
    """touches(a, tool) for a tool split into ``parts`` (tool_parts): the distance
    to a compound is the least distance to its pieces, and only the pieces whose
    boxes come near ``a`` are measured."""
    if parts is None:
        return touches(a, tool, tol)
    ga = bbox(a)
    if _apart(ga, bbox(tool), tol):
        return False
    for p in parts:
        if not _apart(ga, bbox(p), tol):
            try:
                if a.distToShape(p)[0] <= tol:
                    return True
            except Exception:
                pass
    return False


def overlap_volume(a, b):
    try:
        if not touches(a, b):
            return 0.0
        return abs(a.common(b).Volume)
    except Exception:
        return 0.0


def size_of(shape):
    """Volume for solids, area for faces/shells."""
    return _measure(shape, "size", lambda: _size_of(shape))


def _size_of(shape):
    if shape.Solids:
        return abs(shape.Volume)
    return abs(shape.Area)


def centroid(shape):
    """(A copy: change it freely.)"""
    return App.Vector(_measure(shape, "centroid", lambda: _centroid(shape)))


def _typed(shape):
    """A handle on the same shape (same topology and place) of its own type: a
    Solid has CenterOfMass, a plain Shape doesn't."""
    try:
        return shape.transformed(App.Matrix(), False)
    except Exception:
        return Part.Shape(shape)


def _centroid(shape):
    if not hasattr(shape, "CenterOfMass") and shape.ShapeType in ("Solid", "CompSolid",
                                                                    "Shell", "Face", "Edge"):
        shape = _typed(shape)
    try:
        if shape.Solids:
            return shape.CenterOfMass
        if shape.Faces:
            return shape.CenterOfGravity if hasattr(shape, "CenterOfGravity") else shape.BoundBox.Center
    except Exception:
        pass
    return shape.BoundBox.Center


def big_length(*shapes):
    """A length longer than anything in the model: used for Through All."""
    box = App.BoundBox()
    for s in shapes:
        if s is not None and not s.isNull():
            box.add(s.BoundBox)
    if not box.isValid():
        return 1000.0
    return max(100.0, 4.0 * box.DiagonalLength + 4.0 * max(
        abs(box.XMin), abs(box.XMax), abs(box.YMin), abs(box.YMax), abs(box.ZMin), abs(box.ZMax)))


def deg(a):
    return a * math.pi / 180.0
