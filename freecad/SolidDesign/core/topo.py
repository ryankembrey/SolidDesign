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

def fuse(base, tools, tag):
    base = tagged(base, tag)
    tools = [tagged(t, tag) for t in tools]
    if not tools:
        return base
    return _run("fuse", tag, lambda: base.fuse(tools))


def cut(base, tools, tag):
    base = tagged(base, tag)
    tools = [tagged(t, tag) for t in tools]
    if not tools:
        return base
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
    """Move a shape. In FreeCAD 1.1.3 a mapped shape keeps its map when moved."""
    had_map = shape.ElementMapSize > 0
    shape = tagged(shape, tag)

    def go():
        s = shape.copy(False)
        s.Placement = placement.multiply(s.Placement)
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


class _Scratch(object):
    """A hidden, temporary document for operations FreeCAD only offers as
    document objects. The active document is put back afterwards."""
    _n = [0]

    def __enter__(self):
        self.active = App.ActiveDocument
        _Scratch._n[0] += 1
        self.doc = App.newDocument("SDScratch%d" % _Scratch._n[0], "Solid Design scratch",
                                   True, True)
        return self.doc

    def __exit__(self, *exc):
        try:
            App.closeDocument(self.doc.Name)
        except Exception:
            pass
        if self.active is not None:
            try:
                App.setActiveDocument(self.active.Name)
            except Exception:
                pass
        return False


# ---------------------------------------------------------------- queries

def solids(shape):
    return list(shape.Solids) if shape and not shape.isNull() else []


def touches(a, b, tol=LIN_TOL):
    """True when two shapes overlap or touch."""
    if not a.BoundBox.intersect(b.BoundBox):
        # BoundBox.intersect is strict; allow touching boxes through the gap test.
        ga = a.BoundBox
        gb = b.BoundBox
        if (ga.XMin - gb.XMax > tol or gb.XMin - ga.XMax > tol or
                ga.YMin - gb.YMax > tol or gb.YMin - ga.YMax > tol or
                ga.ZMin - gb.ZMax > tol or gb.ZMin - ga.ZMax > tol):
            return False
    try:
        return a.distToShape(b)[0] <= tol
    except Exception:
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
    if shape.Solids:
        return abs(shape.Volume)
    return abs(shape.Area)


def centroid(shape):
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
