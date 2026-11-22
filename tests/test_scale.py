# SPDX-License-Identifier: LGPL-2.1-or-later
"""Many bodies: the shortcuts taken for models of hundreds of bodies (shared
topology for copies, cached measures, indexes over a feature's elements, box
tests before booleans) give what the plain way gave."""

import json
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import dressup, pattern, refs, util
from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.core import bodies as core_bodies
from freecad.SolidDesign.core import topo
from freecad.SolidDesign.core.features import common as core_common
from freecad.SolidDesign.core.features import edges as core_edges
from freecad.SolidDesign.gui import selection as selmod
from helpers import V, circle, extrude, new_doc, plane, rect, sketch

N = 4                       # a 4 x 4 pattern: 16 bodies


def build(doc, part):
    """A drilled, filleted block patterned 4 x 4, then a fillet on the last."""
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, 8, 8)
    doc.recompute()
    extrude(doc, part, sk, Depth=4)
    hs = sketch(doc, plane(part, "Top Plane"))
    circle(hs, 4, 4, 1.5)
    doc.recompute()
    extrude(doc, part, hs, "Cut", EndCondition="Through All")
    last = util.features(part)[-1]
    edges = ["Edge%d" % i for i, e in enumerate(last.Shape.Edges, 1)
             if abs(e.CenterOfMass.z - 4) < 1e-6 and e.Curve.TypeId == "Part::GeomLine"]
    fi = dressup.create_fillet(doc, part, edges)
    fi.Radius = 0.5
    doc.recompute()
    f = pattern.create_linear(doc, part, Bodies=list(part.BodyIds), Spacing=12, Instances=N,
                              Direction2=True, Spacing2=12, Instances2=N)
    f.Direction1Ref = (plane(part, "X Axis"), [])
    f.Direction2Ref = (plane(part, "Y Axis"), [])
    doc.recompute()
    return f


# The plain ways, as they were, to compare with.

def old_body_of_element(obj, elem):
    ids = list(obj.BodyIds)
    shape = obj.Shape
    children = shape.childShapes() if shape.ShapeType == "Compound" else [shape]
    for i, ch in enumerate(children):
        elems = ch.Faces if elem.ShapeType == "Face" else ch.Edges \
            if elem.ShapeType == "Edge" else ch.Vertexes
        if any(e.isSame(elem) for e in elems):
            return ids[i]
    for i, ch in enumerate(children):
        if core_edges.find_in(ch, elem) is not None:
            return ids[i]
    return ""


def old_follow(target, sub, base):
    kind = refs._elem_kind(sub)
    old = refs._mapped(target.Shape, sub)
    if not old or kind is None:
        return None
    shape = base.Shape
    n = len(shape.Faces if kind == "Face" else shape.Edges if kind == "Edge" else shape.Vertexes)
    hits = []
    for i in range(1, n + 1):
        name = "{}{}".format(kind, i)
        m = refs._mapped(shape, name)
        if m == old or (m.startswith(old) and m[len(old):len(old) + 1] == ";"):
            hits.append(name)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        for i in range(1, n + 1):
            name = "{}{}".format(kind, i)
            m = refs._mapped(shape, name)
            h = shape.getElementHistory(m) if m else None
            if h and (h[1] == old or old in (h[2] or [])):
                hits.append(name)
        if len(hits) == 1:
            return hits[0]
    return None


def old_map_to_feature(elem, feature):
    shape = feature.Shape
    kind = elem.ShapeType
    elems = shape.Faces if kind == "Face" else shape.Edges if kind == "Edge" else shape.Vertexes
    for i, e in enumerate(elems, 1):
        if e.isSame(elem):
            return "{}{}".format(kind, i)
    for i, e in enumerate(elems, 1):
        if selmod._same_geometry(e, elem):
            return "{}{}".format(kind, i)
    return None


class ScaleModel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.doc, cls.part = new_doc("Scale")
        cls.pat = build(cls.doc, cls.part)
        cls.fill = util.features(cls.part)[2]

    @classmethod
    def tearDownClass(cls):
        App.closeDocument(cls.doc.Name)

    def test_pattern_made_every_body(self):
        self.assertEqual(self.pat.ErrorMessage, "")
        self.assertEqual(len(self.pat.BodyIds), N * N)

    def test_copies_share_the_seed_topology_and_keep_types(self):
        kids = self.pat.Shape.childShapes()
        self.assertTrue(all(k.isPartner(kids[0]) for k in kids[1:]))
        self.assertEqual(len({(round(k.Placement.Base.x), round(k.Placement.Base.y))
                              for k in kids}), N * N)
        moved = topo.transformed(self.fill.Shape.Edges[0], App.Placement(V(5, 0, 0),
                                                                        App.Rotation()), 7)
        self.assertEqual(moved.ShapeType, "Edge")
        self.assertTrue(hasattr(moved, "Curve"))

    def test_moved_copy_measures_match_opencascade(self):
        for k in self.pat.Shape.childShapes()[1:6]:
            fresh = k.copy()            # new topology: measured by OCC itself
            self.assertAlmostEqual(topo.size_of(k), abs(fresh.Volume), 6)
            self.assertLess((topo.centroid(k) - fresh.CenterOfMass).Length, 1e-6)
            bb, fb = topo.bbox(k), fresh.BoundBox
            for a, b in ((bb.XMin, fb.XMin), (bb.YMax, fb.YMax), (bb.ZMax, fb.ZMax)):
                self.assertAlmostEqual(a, b, 6)

    def test_cached_measures_are_copies(self):
        k = self.pat.Shape.childShapes()[3]
        c = topo.centroid(k)
        c.x += 100
        self.assertLess((topo.centroid(k) - k.CenterOfMass).Length, 1e-6)
        b = topo.bbox(k)
        b.enlarge(50)
        self.assertAlmostEqual(topo.bbox(k).XMin, k.BoundBox.XMin, 6)

    def test_a_moved_handle_is_not_the_cached_shape(self):
        k = self.pat.Shape.childShapes()[2]
        before = topo.centroid(k)
        k2 = Part.Shape(k)
        k2.Placement = App.Placement(V(0, 0, 50), App.Rotation()).multiply(k2.Placement)
        self.assertAlmostEqual(topo.centroid(k2).z - before.z, 50, 6)
        self.assertLess((topo.centroid(k) - before).Length, 1e-9)

    def test_body_of_element_as_before(self):
        shape = self.pat.Shape
        for kind, elems in (("Face", shape.Faces), ("Edge", shape.Edges),
                            ("Vertex", shape.Vertexes)):
            for i in range(0, len(elems), max(1, len(elems) // 23)):
                e = Part.getShape(self.pat, "{}{}".format(kind, i + 1), needSubElement=True)
                self.assertEqual(refs.body_of_element(self.pat, e),
                                 old_body_of_element(self.pat, e), (kind, i))
        far = Part.makeBox(1, 1, 1, V(500, 0, 0)).Faces[0]
        self.assertEqual(refs.body_of_element(self.pat, far), "")

    def test_fingerprints_as_before_and_unshared(self):
        e = Part.getShape(self.pat, "Face7", needSubElement=True)
        ix = refs._index(self.pat)
        a = refs.fingerprint(e, "x", ix)
        a["pts"][0][0] += 99
        a["c"][0] += 99
        b = refs.fingerprint(e, "x", ix)
        self.assertEqual(json.dumps(b), json.dumps(refs._fingerprint(e, "x")))

    def test_follow_as_before(self):
        seed = self.fill
        for kind, n in (("Face", len(seed.Shape.Faces)), ("Edge", len(seed.Shape.Edges))):
            for i in range(1, n + 1):
                sub = "{}{}".format(kind, i)
                self.assertEqual(refs.follow(seed, sub, self.pat),
                                 old_follow(seed, sub, self.pat), sub)

    def test_index_of_and_find_element_as_before(self):
        shape = self.pat.Shape
        for i in range(1, len(shape.Faces) + 1, 7):
            sub = "Face%d" % i
            e = shape.getElement(sub)
            self.assertEqual(refs._index_of(self.pat, e), sub)
            fp = refs._fingerprint_in(self.pat, e)
            self.assertEqual(refs.find_element(self.pat, sub, fp), sub)
            # A name that moved: found again by its fingerprint, when it is the only one.
            other = "Face%d" % (i % len(shape.Faces) + 1)
            cands = refs._match(self.pat, fp)
            want = refs._index_of(self.pat, cands[0]) if len(cands) == 1 else None
            if not any(c.isSame(shape.getElement(other)) for c in cands):
                self.assertEqual(refs.find_element(self.pat, other, fp), want)

    def test_index_follows_a_new_shape(self):
        ix = refs._index(self.pat)
        self.assertIs(refs._index(self.pat), ix)
        other = refs._index(self.fill)
        self.assertIsNot(other, ix)
        self.assertEqual(len(other.children), 1)

    def test_map_to_feature_as_before(self):
        views = app_part.body_views(self.part)
        for v in views[::3]:
            for sub in ("Face1", "Face5", "Edge3", "Edge11", "Vertex2"):
                e = v.Shape.getElement(sub)
                self.assertEqual(selmod.map_to_feature(e, self.pat),
                                 old_map_to_feature(e, self.pat), (v.Name, sub))
            self.assertEqual(selmod.map_to_feature(v.Shape.getElement("Face2"), self.fill),
                             old_map_to_feature(v.Shape.getElement("Face2"), self.fill))

    def test_body_holding_as_before(self):
        base = core_bodies.BodySet.from_columns(self.pat.Shape, list(self.pat.BodyIds),
                                                list(self.pat.BodyKinds),
                                                list(self.pat.BodyFeatures))
        for v in app_part.body_views(self.part)[::4]:
            e = v.Shape.getElement("Edge4")
            want = None
            for b in base:
                found = core_edges.find_in(b.shape, e)
                if found is not None:
                    want = (b.id, found)
                    break
            b, found = core_edges.body_holding(base, e)
            self.assertEqual(b.id, want[0])
            self.assertTrue(found.isSame(want[1]))

    def test_sync_reclaims_folders_only_on_change(self):
        f = app_part.folder(self.part, core_bodies.SOLID)
        app_part.sync(self.part)
        rev = f.Revision
        app_part.sync(self.part)
        self.assertEqual(f.Revision, rev)
        names = dict(self.part.BodyNames)
        bid = list(self.part.BodyIds)[0]
        self.part.BodyNames = dict(names, **{bid: "Renamed"})
        try:
            app_part.sync(self.part)
            self.assertEqual(f.Revision, rev + 1)
            v = [v for v in app_part.body_views(self.part) if v.BodyId == bid][0]
            self.assertEqual(app_part.clean_label(v.Label), "Renamed")
        finally:
            self.part.BodyNames = names
            app_part.sync(self.part)

    def test_views_show_their_bodies(self):
        kids = self.part.Shape.childShapes()
        ids = list(self.part.BodyIds)
        for v in app_part.body_views(self.part):
            k = kids[ids.index(v.BodyId)]
            self.assertTrue(v.Shape.isPartner(k))
            self.assertTrue(v.Placement.isSame(k.Placement, 1e-9))


class Pieces(unittest.TestCase):

    def test_insert_many_after_is_inserting_one_by_one(self):
        def fresh():
            bs = core_bodies.BodySet()
            for i in "abcd":
                bs.add(i, Part.makeBox(1, 1, 1), "F")
            return bs
        one, many = fresh(), fresh()
        prev = "b"
        for k in ("x", "y", "z"):
            one.insert_after(prev, k, Part.makeBox(1, 1, 1), "G")
            prev = k
        many.insert_many_after("b", [(k, Part.makeBox(1, 1, 1), "G") for k in "xyz"])
        self.assertEqual(one.ids(), many.ids())
        self.assertEqual(many.ids(), ["a", "b", "x", "y", "z", "c", "d"])

    def test_ids_taken_as_before(self):
        mem = {}
        for i in range(30):
            mem["F:%d" % (i + 1)] = [3.0 * i, 0, 0, 1.0]
            mem["G:%d" % (i + 1)] = [3.0 * i, 0, 0, 1.0]
        shapes = [Part.makeBox(1, 1, 1, V(3.0 * i - 0.5, -0.5, -0.5)) for i in (4, 9, 0, 29, 40)]
        a = core_bodies.IdAllocator("F", mem, taken={"F:10"})
        got = a.take(shapes)
        self.assertEqual(got[0], "F:5")
        self.assertEqual(got[2], "F:1")
        self.assertEqual(got[3], "F:30")
        self.assertNotIn("F:10", got)
        self.assertEqual(a.take([shapes[0]], prefix="G"), ["G:5"])

    def test_cut_with_a_pattern_of_tools(self):
        tag = 9
        base = core_bodies.BodySet()
        for i in range(6):
            base.add("b%d" % i, topo.tagged(Part.makeBox(4, 4, 4, V(10 * i, 0, 0)), 3), "F")
        tools = [Part.makeCylinder(0.5, 10, V(10 * i + 2, 2, -3)) for i in (0, 2, 4)]
        tool = topo.tagged(Part.makeCompound(tools), tag)

        def run(flip):
            alloc = core_bodies.IdAllocator("C")
            return core_common.apply_cut(base, tool, "C", tag, core_common.Scope(),
                                         core_common.Keep(), alloc, flip)
        r = run(False)
        self.assertEqual(sorted(r.contact), ["b0", "b2", "b4"])
        self.assertEqual(sorted(r.touched), ["b0", "b2", "b4"])
        vols = {b.id: b.shape.Volume for b in r.bodies}
        self.assertAlmostEqual(vols["b1"], 64, 6)
        self.assertAlmostEqual(vols["b0"], 64 - 3.141592653589793 * 0.25 * 4, 4)
        f = run(True)
        self.assertEqual(sorted(f.bodies.ids()), ["b0", "b2", "b4"])
        self.assertEqual(sorted(f.touched), ["b%d" % i for i in range(6)])

    def test_touches_any_is_touches(self):
        tools = [Part.makeBox(1, 1, 1, V(5 * i, 0, 0)) for i in range(5)]
        comp = Part.makeCompound(tools)
        parts = topo.tool_parts(comp)
        for x in (-3, 0.5, 2.5, 4.0, 10.999999, 30):
            b = Part.makeBox(1, 1, 1, V(x, 0, 0))
            self.assertEqual(topo.touches_any(b, comp, parts), topo.touches(b, comp), x)


if __name__ == "__main__":
    unittest.main()
