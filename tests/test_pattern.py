# SPDX-License-Identifier: LGPL-2.1-or-later
"""Linear Pattern, Circular Pattern, Mirror: of features (repeating their
operation) and of bodies."""

import math
import unittest

import FreeCAD as App

from freecad.SolidDesign.app import dressup, pattern, refgeom
from freecad.SolidDesign.core import refgeom as core_ref
from helpers import circle, extrude, new_doc, plane, rect, sketch, volumes

PI = math.pi


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Pat")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 100, 40)
        self.doc.recompute()
        self.plate = extrude(self.doc, self.part, sk, Depth=5)
        hs = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(hs, 10, 10, 3)
        self.doc.recompute()
        self.hole = extrude(self.doc, self.part, hs, "Cut", EndCondition="Through All")
        self.hole_v = PI * 9 * 5

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def total(self):
        return sum(volumes(self.part).values())

    def axis(self, name):
        return (plane(self.part, name), [])


class TestLinear(Case):
    def test_holes_one_and_two_directions(self):
        f = pattern.create_linear(self.doc, self.part, Features=[self.hole], Spacing=20,
                                  Instances=4)
        f.Direction1Ref = self.axis("X Axis")
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "LPattern1")
        self.assertAlmostEqual(self.total(), 20000 - 4 * self.hole_v, 3)
        f.Direction2 = True
        f.Direction2Ref = self.axis("Y Axis")
        f.Spacing2 = 20
        f.Instances2 = 2
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.total(), 20000 - 8 * self.hole_v, 3)
        f.PatternSeedOnly = True
        self.doc.recompute()
        self.assertAlmostEqual(self.total(), 20000 - 5 * self.hole_v, 3)
        f.Reverse = True                     # instances fall off the plate: fewer holes
        self.doc.recompute()
        self.ok(f)
        self.assertGreater(self.total(), 20000 - 5 * self.hole_v)

    def test_body_copies_follow_seed_changes(self):
        f = pattern.create_linear(self.doc, self.part, Bodies=list(self.part.BodyIds),
                                  Spacing=150, Instances=3)
        f.Direction1Ref = self.axis("X Axis")
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(self.part.BodyIds), 3)
        self.assertAlmostEqual(self.total(), 3 * (20000 - self.hole_v), 2)
        self.hole.Depth = 1
        self.hole.EndCondition = "Blind"
        self.hole.Reverse = True
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(self.part.BodyIds), 3)

    def test_unrepeatable_feature(self):
        fil = dressup.create_fillet(self.doc, self.part, [])
        self.doc.recompute()
        f = pattern.create_linear(self.doc, self.part, Features=[fil])
        f.Direction1Ref = self.axis("X Axis")
        self.doc.recompute()
        self.assertIn("can't be repeated", f.ErrorMessage)


class TestCircular(Case):
    def test_holes_round_a_boss_axis(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 50, 20, 1)
        self.doc.recompute()
        boss = extrude(self.doc, self.part, sk, Depth=10)
        f = pattern.create_circular(self.doc, self.part, Features=[self.hole], Instances=4)
        cyl = [i for i, fc in enumerate(boss.Shape.Faces, 1)
               if fc.Surface.TypeId == "Part::GeomCylinder" and fc.Surface.Radius < 1.5][0]
        f.Axis = (boss, ["Face%d" % cyl])
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "CirPattern1")
        # Hole at (10, 10) round (50, 20): instances stay inside the 100 x 40 plate? Only
        # those that land on it cut; the radius is ~41, so some fall outside.
        self.assertLess(self.total(), 20000 + PI * 5 - self.hole_v)
        f.EqualSpacing = False
        f.Angle = 180
        f.Instances = 2
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.total(), 20000 + PI * 5 - 2 * self.hole_v, 2)   # boss adds pi*1*5 above the plate


class TestMirror(Case):
    def test_mirror_feature(self):
        mid = refgeom.create_plane(self.doc, self.part, core_ref.OFFSET,
                                   [(plane(self.part, "Right Plane"), "")])
        mid.Distance = 50
        self.doc.recompute()
        m = pattern.create_mirror(self.doc, self.part, Features=[self.hole])
        m.MirrorPlane = (mid, [])
        self.doc.recompute()
        self.ok(m)
        self.assertEqual(m.Label, "Mirror1")
        self.assertAlmostEqual(self.total(), 20000 - 2 * self.hole_v, 3)

    def test_mirror_body_merge(self):
        right = refgeom.create_plane(self.doc, self.part, core_ref.OFFSET,
                                     [(plane(self.part, "Right Plane"), "")])
        right.Distance = 100
        self.doc.recompute()
        m = pattern.create_mirror(self.doc, self.part, Bodies=list(self.part.BodyIds))
        m.MirrorPlane = (right, [])
        self.doc.recompute()
        self.ok(m)
        self.assertEqual(len(self.part.BodyIds), 1)            # merged across the face
        self.assertAlmostEqual(self.total(), 2 * (20000 - self.hole_v), 2)
        m.MergeSolids = False
        self.doc.recompute()
        self.assertEqual(len(self.part.BodyIds), 2)


class TestFacesToRepeat(Case):
    """Faces to Mirror/Pattern: a boss is added, a hole is cut."""

    def setUp(self):
        super(TestFacesToRepeat, self).setUp()
        from helpers import V
        self.V = V
        bs = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        circle(bs, 20, 30, 2)
        self.doc.recompute()
        self.boss = extrude(self.doc, self.part, bs, Depth=4)
        self.boss_v = PI * 4 * 4
        mp = refgeom.create_plane(self.doc, self.part, core_ref.OFFSET,
                                  [(plane(self.part, "Right Plane"), "")])
        mp.Distance = 50
        self.doc.recompute()
        self.mp = mp

    def faces(self, *points):
        from helpers import face_at
        return [face_at(self.boss, p) for p in points]

    def test_mirror_a_hole_and_a_boss(self):
        V = self.V
        before = self.total()
        m = pattern.create_mirror(self.doc, self.part, MirrorPlane=(self.mp, []))
        from freecad.SolidDesign.app import refs
        refs.set_ref(m, "Faces", self.boss, self.faces(V(13, 10, 2.5)))     # the hole's wall
        self.doc.recompute()
        self.ok(m)
        self.assertAlmostEqual(self.total(), before - self.hole_v, 3)
        refs.set_ref(m, "Faces", self.boss, self.faces(V(22, 30, 7), V(20, 30, 9)))  # the boss
        self.doc.recompute()
        self.ok(m)
        self.assertAlmostEqual(self.total(), before + self.boss_v, 3)
        self.assertEqual(len(volumes(self.part)), 1)        # merged into the plate
        bb = self.part.Document.getObject(m.Name).Shape.BoundBox
        self.assertAlmostEqual(bb.ZMax, 9, 6)

    def test_pattern_faces_and_incomplete_pick(self):
        V = self.V
        before = self.total()
        lp = pattern.create_linear(self.doc, self.part, Direction1Ref=self.axis("Right Plane"),
                                   Spacing=10, Instances=3)
        from freecad.SolidDesign.app import refs
        refs.set_ref(lp, "Faces", self.boss, self.faces(V(22, 30, 7), V(20, 30, 9)))
        self.doc.recompute()
        self.ok(lp)
        self.assertAlmostEqual(self.total(), before + 2 * self.boss_v, 3)
        refs.set_ref(lp, "Faces", self.boss, self.faces(V(22, 30, 7)))   # the wall alone
        self.doc.recompute()
        self.ok(lp)            # its open ends are capped: the same boss
        self.assertAlmostEqual(self.total(), before + 2 * self.boss_v, 3)


class TestMorePatterns(Case):
    """Curve, Sketch, Table and Fill patterns; instances to skip."""

    def test_skip_instances(self):
        f = pattern.create_linear(self.doc, self.part, Features=[self.hole], Spacing=20,
                                  Instances=4, InstancesToSkip=["3,1"])
        f.Direction1Ref = self.axis("X Axis")
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.total(), 20000 - 3 * self.hole_v, 3)
        from freecad.SolidDesign.core.features import pattern as core_pat
        moves = core_pat.circular(App.Vector(), App.Vector(0, 0, 1), 360, 4, skip={2})
        self.assertEqual([round(m.Rotation.Angle * 180 / PI) for m in moves], [180, 270])

    def test_curve_driven(self):
        from helpers import V
        import Part
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        sk.addGeometry(Part.LineSegment(V(10, 10, 0), V(90, 10, 0)))
        self.doc.recompute()
        f = pattern.create_curve(self.doc, self.part, Features=[self.hole], CurveSketch=sk,
                                 Instances=5)
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "CrvPattern1")
        self.assertAlmostEqual(self.total(), 20000 - 5 * self.hole_v, 3)
        f.EqualSpacing = False
        f.Spacing = 30
        f.Instances = 4
        self.doc.recompute()
        self.assertIn("falls off the end", f.ErrorMessage)
        f.Instances = 3
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.total(), 20000 - 3 * self.hole_v, 3)

    def test_curve_driven_round_an_arc_turns(self):
        from helpers import V
        import Part
        b = sketch(self.doc, plane(self.part, "Top Plane"),
                   attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        rect(b, 48, 18, 52, 22)
        self.doc.recompute()
        boss = extrude(self.doc, self.part, b, Depth=4)
        arc = sketch(self.doc, plane(self.part, "Top Plane"),
                     attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        arc.addGeometry(Part.ArcOfCircle(Part.Circle(V(50, 0, 0), V(0, 0, 1), 20),
                                         math.radians(30), math.radians(150)))
        self.doc.recompute()
        before = self.total()
        f = pattern.create_curve(self.doc, self.part, Features=[boss], CurveSketch=arc,
                                 Instances=3, EqualSpacing=False, Spacing=20 * math.radians(30))
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.total(), before + 2 * 64, 2)

    def test_sketch_and_table_driven(self):
        from helpers import V
        import Part
        pts = sketch(self.doc, plane(self.part, "Top Plane"))
        for x, y in ((10, 10), (30, 25), (60, 30), (85, 12)):
            pts.addGeometry(Part.Point(V(x, y, 0)))
        self.doc.recompute()
        f = pattern.create_sketch_pattern(self.doc, self.part, Features=[self.hole], Sketch=pts)
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.total(), 20000 - 4 * self.hole_v, 3)
        t = pattern.create_table(self.doc, self.part, Features=[self.hole],
                                 Points=["50,20", "70,30"])
        self.doc.recompute()
        self.ok(t)
        self.assertAlmostEqual(self.total(), 20000 - 6 * self.hole_v, 3)

    def test_fill_with_a_seed_cut(self):
        from helpers import V, face_at
        top = face_at(self.hole, V(50, 20, 5), V(0, 0, 1))
        f = pattern.create_fill(self.doc, self.part, Layout="Square", InstanceSpacing=10,
                                Margin=2, SeedCut="Circle", SeedSize=4)
        from freecad.SolidDesign.app import refs
        refs.set_ref(f, "Boundary", self.hole, [top])
        self.doc.recompute()
        self.ok(f)
        holes = (20000 - self.hole_v - self.total()) / (PI * 4 * 5)
        self.assertAlmostEqual(holes, round(holes), 3)
        self.assertGreater(holes, 20)
        f.Layout = "Perforation"
        self.doc.recompute()
        self.ok(f)
        f.Layout = "Circular"
        self.doc.recompute()
        self.ok(f)

    def test_fill_with_features(self):
        from helpers import V, face_at
        top = face_at(self.hole, V(50, 20, 5), V(0, 0, 1))
        f = pattern.create_fill(self.doc, self.part, Features=[self.hole], Layout="Square",
                                InstanceSpacing=20, Margin=1)
        from freecad.SolidDesign.app import refs
        refs.set_ref(f, "Boundary", self.hole, [top])
        self.doc.recompute()
        self.ok(f)
        # A 20 mm grid from the hole at (10, 10), 3 + 1 mm clear of the edges.
        n = round((20000 - self.total()) / self.hole_v)
        self.assertEqual(n, 10)
