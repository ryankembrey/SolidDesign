# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fillet, Chamfer, Shell and Draft document objects.

Their edges, faces and vertices are one link (the feature before them, and the
sub-element names), so they follow the model like every other reference.
"""

import FreeCAD as App

from ..core import refgeom as core_ref
from ..core import topo
from ..core.features import chamfer as core_chamfer
from ..core.features import draft as core_draft
from ..core.features import fillet as core_fillet
from ..core.features import shell as core_shell
from . import feature, part as part_mod, refs, util


class _EdgeFeature(feature.FeatureProxy):
    ITEMS_WHAT = "edge"

    def setup(self, obj):
        super(_EdgeFeature, self).setup(obj)
        util.add_prop(obj, "App::PropertyLinkSub", "Items", self.TYPE,
                      "Edges, faces (all their edges) or vertices")
        util.add_prop(obj, "App::PropertyBool", "TangentPropagation", self.TYPE,
                      "Include edges tangent to the picked ones", True)

    def items(self, obj, warns):
        elems, w = refs.get_refs(obj, "Items", "{} {}".format(self.TYPE.lower(), self.ITEMS_WHAT),
                                 obj.BaseFeature)
        warns.extend(w)
        return elems


class FilletProxy(_EdgeFeature):
    TYPE = "Fillet"
    LABELS = ("Fillet",)

    def setup(self, obj):
        super(FilletProxy, self).setup(obj)
        a = util.add_prop
        g = "Fillet"
        a(obj, "App::PropertyEnumeration", "FilletType", g, "Fillet type",
          enum=core_fillet.TYPES)
        a(obj, "App::PropertyLength", "Radius", g, "Radius", 1.0)
        a(obj, "App::PropertyLength", "StartRadius", g, "Variable Size: radius at the start", 1.0)
        a(obj, "App::PropertyLength", "EndRadius", g, "Variable Size: radius at the end", 3.0)
        a(obj, "App::PropertyBool", "ReverseVariable", g,
          "Variable Size: swap which end gets the start radius", False)
        a(obj, "App::PropertyLinkSub", "FaceSet1", g,
          "Face Fillet: face set 1. Full Round: side face set 1")
        a(obj, "App::PropertyLinkSub", "FaceSet2", g,
          "Face Fillet: face set 2. Full Round: side face set 2")
        a(obj, "App::PropertyLinkSub", "CenterFaces", g, "Full Round: the centre face set")
        self._more(obj)

    @staticmethod
    def _more(obj):
        """Properties added after the first release (kept for older files)."""
        a = util.add_prop
        g = "Fillet"
        if "FilletMethod" not in obj.PropertiesList:
            a(obj, "App::PropertyEnumeration", "FilletMethod", g,
              "Symmetric: one radius. Asymmetric: a distance on each face",
              enum=core_fillet.METHODS)
            a(obj, "App::PropertyLength", "Distance2", g,
              "Asymmetric: the distance on the second face", 2.0)
            a(obj, "App::PropertyBool", "FlipAsymmetric", g,
              "Asymmetric: swap which face gets which distance", False)
            a(obj, "App::PropertyEnumeration", "Profile", g,
              "The round's shape across the edge", enum=core_fillet.PROFILES)
            a(obj, "App::PropertyFloatConstraint", "ConicRho", g,
              "Conic Rho: where the shoulder sits, 0.05 (flat) to 0.95 (sharp); 0.5 is a "
              "parabola", (0.5, 0.05, 0.95, 0.05))
            a(obj, "App::PropertyStringList", "VariablePoints", g,
              "Variable Size: radii along the edges, as percent|radius")
            a(obj, "App::PropertyLinkSub", "HoldLine", g,
              "Face Fillet: the edges the round stops at (the hold line)")

    def onDocumentRestored(self, obj):
        super(FilletProxy, self).onDocumentRestored(obj)
        self._more(obj)

    @staticmethod
    def variable_points(obj):
        """[(fraction, radius)] from VariablePoints."""
        out = []
        for t in getattr(obj, "VariablePoints", []):
            try:
                f, r = (float(x) for x in str(t).split("|"))
                out.append((f / 100.0, r))
            except ValueError:
                continue
        return sorted(out)

    def compute(self, obj, base):
        res, preview, _p = self.run(obj, base)
        return res, preview

    def params(self, obj, warns):
        p = core_fillet.Params()
        p.kind = obj.FilletType
        if p.kind in (core_fillet.CONSTANT, core_fillet.VARIABLE):
            p.items = self.items(obj, warns)
        for prop, attr, what in (("FaceSet1", "faces1", "face of set 1"),
                                 ("FaceSet2", "faces2", "face of set 2"),
                                 ("CenterFaces", "centre", "centre face")):
            if p.kind in (core_fillet.FACE, core_fillet.FULL_ROUND):
                got, w = refs.get_refs(obj, prop, what, obj.BaseFeature)
                warns.extend(w)
                setattr(p, attr, got)
        p.radius = obj.Radius.Value
        p.start_radius = obj.StartRadius.Value
        p.end_radius = obj.EndRadius.Value
        p.reverse = obj.ReverseVariable
        p.tangent = obj.TangentPropagation
        p.feature = obj.Name
        p.tag = obj.ID
        p.method = obj.FilletMethod
        p.distance2 = obj.Distance2.Value
        p.flip = obj.FlipAsymmetric
        p.profile = obj.Profile
        p.rho = obj.ConicRho
        if p.kind == core_fillet.VARIABLE:
            p.points = self.variable_points(obj)
        if p.kind == core_fillet.FACE and obj.HoldLine and obj.HoldLine[0] is not None:
            got, w = refs.get_refs(obj, "HoldLine", "hold line edge", obj.BaseFeature)
            warns.extend(w)
            p.hold = [e for g in got for e in g.Edges]
        return p

    def run(self, obj, base):
        warns = []
        p = self.params(obj, warns)
        res, preview = core_fillet.compute(p, base)
        res.warnings.extend(w for w in warns if w)
        return res, preview, p


class ChamferProxy(_EdgeFeature):
    TYPE = "Chamfer"
    LABELS = ("Chamfer",)

    def setup(self, obj):
        super(ChamferProxy, self).setup(obj)
        a = util.add_prop
        g = "Chamfer"
        a(obj, "App::PropertyEnumeration", "ChamferType", g, "Chamfer type",
          enum=core_chamfer.TYPES)
        a(obj, "App::PropertyLength", "Distance", g, "Distance (d1)", 1.0)
        a(obj, "App::PropertyLength", "Distance2", g, "Second distance (d2)", 1.0)
        a(obj, "App::PropertyLength", "Distance3", g, "Third distance (d3, Vertex)", 1.0)
        a(obj, "App::PropertyAngle", "Angle", g, "Angle (Angle Distance)", 45.0)
        a(obj, "App::PropertyBool", "EqualDistance", g, "Equal distance", True)
        a(obj, "App::PropertyBool", "FlipDirection", g, "Flip direction", False)

    def compute(self, obj, base):
        warns = []
        p = self.params(obj, warns)
        res, preview = core_chamfer.compute(p, base)
        res.warnings.extend(w for w in warns if w)
        return res, preview

    def params(self, obj, warns):
        p = core_chamfer.Params()
        p.kind = obj.ChamferType
        p.items = self.items(obj, warns)
        p.d1 = obj.Distance.Value
        p.d2 = obj.Distance2.Value
        p.d3 = obj.Distance3.Value
        p.angle = obj.Angle.Value
        p.equal = obj.EqualDistance
        p.flip = obj.FlipDirection
        p.tangent = obj.TangentPropagation
        p.feature = obj.Name
        p.tag = obj.ID
        return p


class ShellProxy(feature.FeatureProxy):
    TYPE = "Shell"
    LABELS = ("Shell",)

    def setup(self, obj):
        super(ShellProxy, self).setup(obj)
        a = util.add_prop
        g = "Shell"
        a(obj, "App::PropertyLength", "Thickness", g, "Wall thickness", 1.0)
        a(obj, "App::PropertyBool", "ShellOutward", g, "Shell outward", False)
        a(obj, "App::PropertyLinkSub", "Items", g, "Faces to remove")
        a(obj, "App::PropertyString", "Body", g, "Body to hollow when no face is removed", "")
        a(obj, "App::PropertyLinkSub", "MultiFaces", "Multi-thickness",
          "Faces with their own thickness")
        a(obj, "App::PropertyFloatList", "MultiThickness", "Multi-thickness",
          "Thickness of each multi-thickness face (mm)")

    def compute(self, obj, base):
        warns = []
        p = core_shell.Params()
        p.faces, w = refs.get_refs(obj, "Items", "face to remove", obj.BaseFeature)
        warns.extend(w)
        p.body = obj.Body or None
        p.thickness = obj.Thickness.Value
        p.outward = obj.ShellOutward
        mf, w = refs.get_refs(obj, "MultiFaces", "multi-thickness face", obj.BaseFeature)
        warns.extend(w)
        ts = list(obj.MultiThickness) + [p.thickness * 2] * len(mf)
        p.multi = list(zip(mf, ts[:len(mf)]))
        p.feature = obj.Name
        p.tag = obj.ID
        res, preview = core_shell.compute(p, base)
        res.warnings.extend(warns)
        return res, preview


class DraftProxy(feature.FeatureProxy):
    TYPE = "Draft"
    LABELS = ("Draft",)

    def setup(self, obj):
        super(DraftProxy, self).setup(obj)
        a = util.add_prop
        g = "Draft"
        a(obj, "App::PropertyEnumeration", "DraftType", g, "Neutral Plane or Parting Line",
          enum=core_draft.TYPES)
        a(obj, "App::PropertyAngle", "Angle", g, "Draft angle", 1.0)
        a(obj, "App::PropertyLinkSub", "NeutralPlane", g, "Neutral plane: a plane or planar face")
        a(obj, "App::PropertyLinkSub", "Items", g, "Faces to draft")
        a(obj, "App::PropertyLinkSub", "PartingLines", g, "Parting lines (edges)")
        a(obj, "App::PropertyLinkSub", "PullDirection", g,
          "Direction of pull: an edge, axis, plane or face (empty: from the plane)")
        a(obj, "App::PropertyBool", "ReverseDirection", g, "Reverse the direction of pull", False)
        a(obj, "App::PropertyBool", "OtherFace", g,
          "Parting Line: draft the faces on the other side", False)
        a(obj, "App::PropertyEnumeration", "FacePropagation", g, "Faces added to the picked ones",
          enum=core_draft.PROPAGATION)

    def compute(self, obj, base):
        warns = []
        p = core_draft.Params()
        p.kind = obj.DraftType
        p.angle = obj.Angle.Value
        if p.kind in (core_draft.NEUTRAL_PLANE, core_draft.DRAFTXPERT):
            s, w = refs.get_ref(obj, "NeutralPlane", "neutral plane", obj.BaseFeature)
            warns.append(w)
            if s is not None:
                pt, n, _x = core_ref.plane_of(s, "neutral plane")
                p.plane = (pt, n)
            p.faces, w = refs.get_refs(obj, "Items", "face to draft", obj.BaseFeature)
            warns.extend(w)
        else:
            p.edges, w = refs.get_refs(obj, "PartingLines", "parting line", obj.BaseFeature)
            warns.extend(w)
        s, w = refs.get_ref(obj, "PullDirection", "direction of pull", obj.BaseFeature)
        warns.append(w)
        if s is not None:
            try:
                p.pull = core_ref.line_of(s, "direction of pull")[1]
            except topo.GeometryError:
                p.pull = core_ref.plane_of(s, "direction of pull")[1]
        p.reverse = obj.ReverseDirection
        p.other_face = obj.OtherFace
        p.propagation = obj.FacePropagation
        if p.kind != core_draft.NEUTRAL_PLANE and p.propagation not in \
                core_draft.PROPAGATION_PARTING:
            p.propagation = core_draft.NONE
        p.feature = obj.Name
        p.tag = obj.ID
        res, preview = core_draft.compute(p, base)
        res.warnings.extend(x for x in warns if x)
        return res, preview


def _create(cls, doc, part, name, items=None):
    obj = doc.addObject("Part::FeaturePython", name)
    cls(obj)
    obj.AutoLabel = util.set_label(obj, cls.LABELS[0])
    part_mod.insert_feature(part, obj)
    if items:
        refs.set_ref(obj, "Items", obj.BaseFeature, items)
    if App.GuiUp:
        from ..gui import viewproviders
        viewproviders.attach_feature(obj)
    return obj


def create_fillet(doc, part, items=None):
    """``items``: sub-element names ("Edge3", "Face1") of the feature before it."""
    return _create(FilletProxy, doc, part, "Fillet", items)


def create_chamfer(doc, part, items=None):
    return _create(ChamferProxy, doc, part, "Chamfer", items)


def create_shell(doc, part, items=None):
    return _create(ShellProxy, doc, part, "Shell", items)


def create_draft(doc, part, items=None):
    """``items``: faces to draft (sub-element names of the feature before it)."""
    return _create(DraftProxy, doc, part, "Draft", items)
