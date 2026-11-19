# SPDX-License-Identifier: LGPL-2.1-or-later
"""Combine, Delete/Keep Body, Split and Move/Copy Body document objects.

Bodies are stored by ID (strings), never by index (spec 5.2). Geometry picked as
references (axes, edges, planes, faces) lives in link properties and follows
the model (app/refs.py).
"""

import FreeCAD as App

from ..core import bodyops, mates, regions, topo
from ..core import refgeom as core_ref
from ..core.bodies import IdAllocator
from . import feature, part as part_mod, refs, util


class _BodyTool(feature.FeatureProxy):
    def alloc(self, obj, base):
        return IdAllocator(obj.Name, IdAllocator.loads(obj.IdMemory), taken=base.ids())

    def done(self, obj, res, alloc, warns=()):
        mem = alloc.dumps()
        if obj.IdMemory != mem:
            obj.IdMemory = mem
        self.store_pieces(obj, res)
        res.warnings.extend(w for w in warns if w)


class CombineProxy(_BodyTool):
    TYPE = "Combine"
    LABELS = ("Combine",)

    def setup(self, obj):
        super(CombineProxy, self).setup(obj)
        a = util.add_prop
        a(obj, "App::PropertyEnumeration", "Operation", "Combine", "Operation",
          enum=bodyops.COMBINE_OPS)
        a(obj, "App::PropertyString", "MainBody", "Combine", "Main body (Subtract), by ID", "")
        a(obj, "App::PropertyStringList", "Bodies", "Combine",
          "Bodies to combine (Add, Common) or to subtract, by ID")

    def compute(self, obj, base):
        alloc = self.alloc(obj, base)
        main = obj.MainBody if obj.Operation == bodyops.SUBTRACT else ""
        ids = list(obj.Bodies)
        if not main and ids:
            main, ids = ids[0], ids[1:]
        res, preview = bodyops.combine(base, obj.Operation, main, ids, obj.Name, obj.ID, alloc)
        self.done(obj, res, alloc)
        return res, preview


class DeleteBodyProxy(_BodyTool):
    TYPE = "DeleteBody"
    LABELS = ("Body-Delete/Keep",)

    def setup(self, obj):
        super(DeleteBodyProxy, self).setup(obj)
        util.add_prop(obj, "App::PropertyEnumeration", "Type", "Bodies", "Delete or keep",
                      enum=bodyops.DELETE_TYPES)
        util.add_prop(obj, "App::PropertyStringList", "Bodies", "Bodies", "Bodies, by ID")

    def compute(self, obj, base):
        return bodyops.delete_keep(base, obj.Type, list(obj.Bodies))


class SplitProxy(_BodyTool):
    TYPE = "Split"
    LABELS = ("Split",)

    def setup(self, obj):
        super(SplitProxy, self).setup(obj)
        a = util.add_prop
        g = "Split"
        a(obj, "App::PropertyLinkList", "TrimTools", g, "Planes and sketches that cut")
        a(obj, "App::PropertyLinkSub", "TrimFaces", g, "Faces of the model that cut")
        a(obj, "App::PropertyStringList", "TrimBodies", g, "Surface bodies that cut, by ID")
        a(obj, "App::PropertyStringList", "TargetBodies", g, "Bodies to split (empty: all)")
        a(obj, "App::PropertyBool", "ConsumeCutBodies", g, "Consume the bodies that are cut",
          True)
        a(obj, "App::PropertyBool", "KeepAll", g, "Keep every piece", True)
        a(obj, "App::PropertyStringList", "KeepPieces", g, "Pieces to keep, by ID")
        a(obj, "App::PropertyMap", "PieceNames", g, "Names given to pieces (ID -> name)")

    def compute(self, obj, base):
        warns = []
        planes, sketches = [], []
        for o in obj.TrimTools:
            if o.TypeId.startswith("Sketcher::SketchObject"):
                sketches.append((topo.shape_of(o), regions.sketch_normal(o)))
            else:
                shape = topo.shape_of(o)
                core_ref.plane_of(shape, "trim plane")      # a plane, or a clear error
                planes.append(shape.Faces[0])
        faces, w = refs.get_refs(obj, "TrimFaces", "trim face", obj.BaseFeature)
        warns.extend(w)
        surfaces = []
        for bid in obj.TrimBodies:
            b = base.get(bid)
            if b is None:
                raise topo.GeometryError("A surface body used to split no longer exists.")
            surfaces.append(b.shape)
        targets = [i for i in obj.TargetBodies if i not in obj.TrimBodies]
        big = topo.big_length(*[b.shape for b in base])
        tools = bodyops.trim_shapes(planes, faces, sketches, surfaces, big)
        alloc = self.alloc(obj, base)
        keep = None if obj.KeepAll else list(obj.KeepPieces)
        patched = any(len(f.Wires) > 1 for f in faces)     # leaves the patch's outline
        res, preview = bodyops.split(base, tools, targets, obj.ConsumeCutBodies, keep,
                                     obj.Name, obj.ID, alloc, refine=patched)
        self.done(obj, res, alloc, warns)
        return res, preview


class MoveCopyProxy(_BodyTool):
    TYPE = "MoveCopy"
    LABELS = ("Body-Move/Copy",)

    def setup(self, obj):
        super(MoveCopyProxy, self).setup(obj)
        a = util.add_prop
        g = "Bodies"
        a(obj, "App::PropertyStringList", "Bodies", g, "Bodies to move or copy, by ID")
        a(obj, "App::PropertyBool", "Copy", g, "Copy instead of moving", False)
        a(obj, "App::PropertyInteger", "Copies", g, "Number of copies", 1)
        g = "Translate"
        a(obj, "App::PropertyLinkSub", "TranslateReference", g,
          "Edge or axis to translate along (instead of Delta X/Y/Z)")
        a(obj, "App::PropertyLength", "TranslateDistance", g, "Distance along the reference", 0.0)
        a(obj, "App::PropertyDistance", "DeltaX", g, "Delta X", 0.0)
        a(obj, "App::PropertyDistance", "DeltaY", g, "Delta Y", 0.0)
        a(obj, "App::PropertyDistance", "DeltaZ", g, "Delta Z", 0.0)
        a(obj, "App::PropertyBool", "ReverseTranslate", g, "Reverse direction", False)
        g = "Rotate"
        a(obj, "App::PropertyLinkSub", "RotateReference", g, "Axis or edge to rotate about")
        a(obj, "App::PropertyAngle", "Angle", g, "Rotation angle", 0.0)
        a(obj, "App::PropertyEnumeration", "MoveMode", "Bodies", "How the bodies are placed",
          enum=self.MODES)
        g = "Constraints"
        for i in range(1, self.MATES + 1):
            a(obj, "App::PropertyEnumeration", "MateType%d" % i, g, "Constraint %d" % i,
              enum=["None"] + mates.TYPES)
            a(obj, "App::PropertyLinkSub", "MateMoving%d" % i, g,
              "Constraint %d: face, edge or vertex of the moving bodies" % i)
            a(obj, "App::PropertyLinkSub", "MateFixed%d" % i, g,
              "Constraint %d: what it is placed against" % i)
            a(obj, "App::PropertyFloat", "MateValue%d" % i, g,
              "Constraint %d: distance (mm) or angle (degrees)" % i, 0.0)
            a(obj, "App::PropertyBool", "MateFlip%d" % i, g, "Constraint %d: flip alignment" % i,
              False)

    MODES = ["Translate/Rotate", "Constraints"]
    MATES = 6

    def mates(self, obj, warns):
        out = []
        base = obj.BaseFeature
        for i in range(1, self.MATES + 1):
            k = getattr(obj, "MateType%d" % i)
            if k == "None":
                continue
            mv, w1 = refs.get_ref(obj, "MateMoving%d" % i, "constraint %d entity" % i, base)
            fx, w2 = refs.get_ref(obj, "MateFixed%d" % i, "constraint %d target" % i, base)
            warns.extend([w1, w2])
            if mv is None or fx is None:
                raise topo.GeometryError("Constraint {} ({}): pick both entities.".format(i, k))
            out.append(mates.Mate(k, mates.entity(mv, "constraint %d entity" % i),
                                  mates.entity(fx, "constraint %d target" % i),
                                  getattr(obj, "MateValue%d" % i),
                                  getattr(obj, "MateFlip%d" % i)))
        return out
    def step(self, obj, warns):
        base = obj.BaseFeature
        ref, w = refs.get_ref(obj, "TranslateReference", "translation reference", base)
        warns.append(w)
        if ref is not None:
            _p, d = core_ref.line_of(ref, "translation reference")
            dist = obj.TranslateDistance.Value * (-1 if obj.ReverseTranslate else 1)
            delta = d * dist
        else:
            delta = App.Vector(obj.DeltaX.Value, obj.DeltaY.Value, obj.DeltaZ.Value)
        ax, w = refs.get_ref(obj, "RotateReference", "rotation axis", base)
        warns.append(w)
        if ax is not None:
            p, d = core_ref.line_of(ax, "rotation axis")
            return bodyops.step_placement(delta, p, d, obj.Angle.Value)
        if abs(obj.Angle.Value) > 1e-12:
            raise topo.GeometryError("Pick an axis or edge to rotate about.")
        return bodyops.step_placement(delta)

    def compute(self, obj, base):
        warns = []
        if obj.MoveMode == "Constraints":
            ids = list(obj.Bodies)
            if not ids or any(i not in base for i in ids):
                raise topo.GeometryError("Pick the bodies to move or copy.")
            centre = App.BoundBox()
            for i in ids:
                centre.add(base.get(i).shape.BoundBox)
            step = mates.solve(self.mates(obj, warns), centre.Center)
        else:
            step = self.step(obj, warns)
        if step.isIdentity() and not obj.Copy:
            warns.append("The move is zero: set a distance or an angle.")
        alloc = self.alloc(obj, base)
        # Placed by constraints, a copy goes to one place.
        copies = obj.Copies if obj.MoveMode != "Constraints" else 1
        res, preview = bodyops.move_copy(base, list(obj.Bodies), step, obj.Copy, copies,
                                         obj.Name, obj.ID, alloc)
        self.done(obj, res, alloc, warns)
        return res, preview


def _create(cls, doc, part, name, **props):
    obj = doc.addObject("Part::FeaturePython", name)
    cls(obj)
    obj.AutoLabel = util.set_label(obj, cls.LABELS[0])
    part_mod.insert_feature(part, obj)
    for k, v in props.items():
        setattr(obj, k, v)
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_feature(obj)
    return obj


def create_combine(doc, part, **props):
    return _create(CombineProxy, doc, part, "Combine", **props)


def create_delete(doc, part, **props):
    return _create(DeleteBodyProxy, doc, part, "DeleteBody", **props)


def create_split(doc, part, **props):
    return _create(SplitProxy, doc, part, "Split", **props)


def create_move(doc, part, **props):
    return _create(MoveCopyProxy, doc, part, "MoveCopy", **props)
