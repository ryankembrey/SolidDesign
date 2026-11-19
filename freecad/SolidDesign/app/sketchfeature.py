# SPDX-License-Identifier: LGPL-2.1-or-later
"""Base for sketch-based features with an Add | Cut mode (Extrude, Revolve...).

Holds what they share (spec 5.4): the profile sketch and Selected Contours, the
Thin Feature, Merge result, Feature scope, Bodies to Keep and Flip side to cut.
"""

from ..core import regions, topo
from ..core.bodies import IdAllocator
from ..core.features import common, profile, sheet
from . import feature, refs, util

SCOPES = ["All bodies", "Selected bodies"]


class SketchFeatureProxy(feature.FeatureProxy):
    LABELS = ("Boss", "Cut")
    CAP_ENDS = False        # Thin Feature with Cap ends (Extrude only)

    def setup(self, obj):
        super(SketchFeatureProxy, self).setup(obj)
        a = util.add_prop
        g = self.TYPE
        a(obj, "App::PropertyEnumeration", "Mode", g,
          "Add material, cut it, or make a surface body", enum=sheet.MODES)
        a(obj, "App::PropertyLink", "Sketch", g, "The profile sketch")
        a(obj, "App::PropertyStringList", "Contours", g,
          "Selected Contours: regions of the sketch (bounding geometry IDs + a point inside)")

        g = "Thin Feature"
        a(obj, "App::PropertyBool", "Thin", g, "Thin Feature on/off", False)
        a(obj, "App::PropertyEnumeration", "ThinType", g, "Thin type", enum=profile.THIN_TYPES)
        a(obj, "App::PropertyLength", "ThinThickness", g, "Thickness", 1.0)
        a(obj, "App::PropertyLength", "ThinThickness2", g, "Thickness 2 (Two-Direction)", 1.0)
        a(obj, "App::PropertyBool", "ThinReverse", g, "Reverse the thin direction", False)
        if self.CAP_ENDS:
            a(obj, "App::PropertyBool", "CapEnds", g, "Cap ends (closed profiles)", False)
            a(obj, "App::PropertyLength", "CapThickness", g, "Cap thickness", 1.0)

        g = "Bodies"
        a(obj, "App::PropertyBool", "MergeResult", g, "Merge result (Add mode)", True)
        a(obj, "App::PropertyEnumeration", "FeatureScope", g, "Feature scope", enum=SCOPES)
        a(obj, "App::PropertyBool", "AutoSelect", g, "Auto-select the bodies in scope", True)
        a(obj, "App::PropertyStringList", "ScopeBodies", g, "Body IDs in scope")
        a(obj, "App::PropertyEnumeration", "BodiesToKeep", g, "Bodies to Keep", enum=SCOPES)
        a(obj, "App::PropertyStringList", "KeepBodies", g, "Piece IDs to keep")
        a(obj, "App::PropertyBool", "FlipSideToCut", g, "Flip side to cut (Cut mode)", False)
        a(obj, "Part::PropertyPartShape", "ToolShape", "Result",
          "The material this feature adds or removes, repeated by patterns and mirrors")
        util.hide_prop(obj, "ToolShape")

    def onDocumentRestored(self, obj):
        super(SketchFeatureProxy, self).onDocumentRestored(obj)
        if "Mode" in obj.PropertiesList and \
                list(obj.getEnumerationsOfProperty("Mode")) != sheet.MODES:
            m = obj.Mode        # files from before Surface mode
            obj.Mode = sheet.MODES
            obj.Mode = m
        if self.TYPE == "Extrude" and "CapEnd" not in obj.PropertiesList:
            util.add_prop(obj, "App::PropertyBool", "CapEnd", "Surface",
                          "Surface mode: close both ends of a closed profile", False)

    # ------------------------------------------------------------------ naming
    def default_label(self, obj):
        return label_for(self.LABELS, obj.Mode)

    def onChanged(self, obj, prop):
        if prop == "Mode" and "AutoLabel" in obj.PropertiesList and obj.AutoLabel:
            self.rename_for_mode(obj)

    # ------------------------------------------------------------------ inputs
    def face_ref(self, obj, prop, what, warns):
        shape, warn = refs.get_ref(obj, prop, what, obj.BaseFeature)
        warns.append(warn)
        if shape is None:
            return None
        if shape.ShapeType != "Face":
            faces = shape.Faces
            if len(faces) != 1:
                raise topo.GeometryError("The {} must be one face or plane.".format(what))
            shape = faces[0]
        return shape

    def vertex_ref(self, obj, prop, what, warns):
        shape, warn = refs.get_ref(obj, prop, what, obj.BaseFeature)
        warns.append(warn)
        if shape is None:
            return None
        if shape.ShapeType != "Vertex":
            vs = shape.Vertexes
            if len(vs) != 1:
                raise topo.GeometryError("The {} must be one vertex or point.".format(what))
            shape = vs[0]
        return shape.Point

    def profile(self, obj, warns):
        """(faces, open wires) of the sketch, or of its selected contours."""
        sketch = obj.Sketch
        if sketch is None:
            raise topo.GeometryError("Pick a sketch to {}.".format(self.TYPE.lower()))
        if obj.Contours:
            faces, repaired = regions.resolve(list(obj.Contours), sketch, obj.ID)
            if repaired:
                warns.append("{} selected contour(s) changed and were found again by the "
                             "point inside them. Check them.".format(len(repaired)))
            return faces, []
        faces, open_wires = regions.default_profile(sketch, obj.ID)
        return (list(faces.Faces) if faces is not None else []), open_wires

    def thin(self, obj):
        if not obj.Thin:
            return None
        cap = getattr(obj, "CapEnds", False)
        cap_t = obj.CapThickness.Value if cap else 1.0
        return profile.Thin(obj.ThinType, obj.ThinThickness.Value, obj.ThinThickness2.Value,
                            obj.ThinReverse, cap, cap_t)

    def bodies_options(self, obj, base, warns):
        """(merge, scope, keep, flip, allocator)."""
        selected = obj.FeatureScope == "Selected bodies" and not obj.AutoSelect
        scope = common.Scope(not selected, list(obj.ScopeBodies))
        missing = scope.missing(base)
        if missing:
            warns.append("{} body(ies) in the feature scope no longer exist.".format(len(missing)))
        keep = common.Keep(obj.BodiesToKeep == "All bodies", list(obj.KeepBodies))
        alloc = IdAllocator(obj.Name, IdAllocator.loads(obj.IdMemory), taken=base.ids())
        return obj.MergeResult, scope, keep, obj.FlipSideToCut, alloc

    def finish(self, obj, res, alloc, warns, tool=None):
        if tool is not None:
            obj.ToolShape = tool
        mem = alloc.dumps()
        if obj.IdMemory != mem:
            obj.IdMemory = mem
        self.store_pieces(obj, res)
        res.warnings.extend(w for w in warns if w)


def label_for(labels, mode):
    """The label for a mode: (Add, Cut, Surface)."""
    i = sheet.MODES.index(mode) if mode in sheet.MODES else 0
    return labels[i] if i < len(labels) else labels[0]


def create(cls, doc, part, mode, sketch, name):
    """A new sketch feature in ``part`` at the rollback bar (Add mode by default)."""
    import FreeCAD as App
    from . import part as part_mod
    obj = doc.addObject("Part::FeaturePython", name)
    cls(obj)
    obj.Mode = mode
    obj.AutoLabel = util.set_label(obj, label_for(cls.LABELS, mode))
    if sketch is not None:
        obj.Sketch = sketch
    part_mod.insert_feature(part, obj, [sketch] if sketch is not None else [])
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_feature(obj)
    return obj
