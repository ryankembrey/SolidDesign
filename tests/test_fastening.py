# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fastening features: Mounting Boss, Snap Hook, Lip/Groove, Vent."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import fastening as app_f
from freecad.SolidDesign.app import part as app_part
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch

PI = math.pi


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Fa")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 60, 40)
        self.doc.recompute()
        self.plate = extrude(self.doc, self.part, sk, Depth=3)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def bodies(self):
        return list(app_part.tip_bodies(self.part))


class TestBoss(Case):
    def test_boss_with_hole_and_fins(self):
        top = face_at(self.plate, V(20, 20, 3))
        f = app_f.create_mounting_boss(self.doc, self.part, Items=[top], Position="20,20,3",
                                       Height=10, Diameter=8, Draft=0, HoleDiameter=3,
                                       HoleDepth=8, HoleDraft=0)
        self.doc.recompute()
        self.ok(f)
        s = self.bodies()[0].shape
        self.assertTrue(s.isValid())
        self.assertEqual(len(self.bodies()), 1)
        self.assertAlmostEqual(s.BoundBox.ZMax, 13, 6)
        boss = PI * 16 * 10 - PI * 2.25 * 8
        self.assertAlmostEqual(s.Volume, 60 * 40 * 3 + boss, 0)
        self.assertFalse(s.isInside(V(20, 20, 12), 1e-6, True))        # the hole
        f.Fins = 4
        f.FinLength = 4
        f.FinHeight = 6
        f.FinThickness = 1
        self.doc.recompute()
        self.ok(f)
        s = self.bodies()[0].shape
        self.assertTrue(s.isInside(V(26, 20, 5), 1e-6, True))           # a fin along X
        f.BossType = "Pin"
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.bodies()[0].shape.BoundBox.ZMax, 17, 6)

    def test_boss_on_a_curved_face_joins_it(self):
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        circle(sk, 30, 25, 15)
        self.doc.recompute()
        tube = extrude(self.doc, self.part, sk, Depth=30, MergeResult=False)
        side = face_at(tube, V(30, -15, 40))
        f = app_f.create_mounting_boss(self.doc, self.part, Items=[side],
                                       Position="30,-15,40", Height=5, Diameter=8)
        self.doc.recompute()
        self.ok(f)
        tb = [b for b in self.bodies() if b.shape.BoundBox.ZMax > 39][0].shape
        self.assertTrue(tb.isValid())
        self.assertEqual(len(tb.Solids), 1)
        self.assertGreater(tb.BoundBox.ZMax, 44.9)


class TestSnapHook(Case):
    def test_hook(self):
        top = face_at(self.plate, V(40, 20, 3))
        f = app_f.create_snap_hook(self.doc, self.part, Items=[top], Position="40,20,3",
                                   Height=15, Thickness=2, Width=6, Overhang=1.5,
                                   LipHeight=3)
        self.doc.recompute()
        self.ok(f)
        s = self.bodies()[0].shape
        self.assertTrue(s.isValid())
        self.assertEqual(len(self.bodies()), 1)
        self.assertAlmostEqual(s.BoundBox.ZMax, 18, 6)
        self.assertTrue(s.isInside(V(41.6, 20, 15.2), 1e-6, True))      # the hook, along X
        f.HookAngle = 90
        self.doc.recompute()
        self.ok(f)
        s = self.bodies()[0].shape
        self.assertTrue(s.isInside(V(40, 21.6, 15.2), 1e-6, True))      # now along Y


class TestLipGroove(Case):
    def ring(self, z0, h):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, z0), App.Rotation()))
        rect(sk, 100, 0, 140, 30)
        rect(sk, 102, 2, 138, 28)
        self.doc.recompute()
        return extrude(self.doc, self.part, sk, Depth=h, MergeResult=False)

    def test_lip_and_groove(self):
        low = self.ring(0, 10)
        self.ring(10, 10)
        ids = list(self.part.BodyIds)
        lower, upper = ids[1], ids[2]
        face = face_at(low, V(101, 15, 10))
        v0 = {b.id: b.shape.Volume for b in self.bodies()}
        f = app_f.create_lip_groove(self.doc, self.part, LipBody=lower, GrooveBody=upper,
                                    Items=[face], LipOffset=0.5, LipWidth=1, LipHeight=1.5,
                                    Gap=0.1)
        self.doc.recompute()
        self.ok(f)
        b = {x.id: x.shape for x in self.bodies()}
        self.assertTrue(b[lower].isValid() and b[upper].isValid())
        self.assertGreater(b[lower].Volume, v0[lower] + 100)        # the lip
        self.assertLess(b[upper].Volume, v0[upper] - 100)           # the groove
        self.assertLess(b[lower].common(b[upper]).Volume, 1e-6)     # they still fit
        self.assertTrue(b[lower].isInside(V(101, 15, 11), 1e-6, True))   # in the wall


class TestVent(Case):
    def test_vent_with_rib_and_spar(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 3), App.Rotation()))
        rect(sk, 10, 10, 50, 30)
        sk.addGeometry(Part.LineSegment(V(30, 10, 0), V(30, 30, 0)))
        sk.addGeometry(Part.LineSegment(V(10, 20, 0), V(50, 20, 0)))
        self.doc.recompute()
        f = app_f.create_vent(self.doc, self.part, Sketch=sk, Depth=3, RibWidth=1)
        self.doc.recompute()
        self.ok(f)
        s = self.bodies()[0].shape
        self.assertTrue(s.isValid())
        self.assertEqual(len(self.bodies()), 1)
        open_area = 40 * 20 - (20 + 40 - 1)
        self.assertAlmostEqual(s.Volume, 60 * 40 * 3 - 3 * open_area, 3)
        self.assertTrue(s.isInside(V(30, 15, 1.5), 1e-6, True))       # a rib stays
        self.assertFalse(s.isInside(V(20, 15, 1.5), 1e-6, True))      # the opening


if __name__ == "__main__":
    unittest.main()
