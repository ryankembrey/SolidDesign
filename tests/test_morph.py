# SPDX-License-Identifier: LGPL-2.1-or-later
"""Indent, Deform (point, curve to curve, surface push), Freeform, Surface Flatten."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import deform as app_deform
from freecad.SolidDesign.app import part as app_part
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch

PI = math.pi


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Mo")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 60, 40)
        self.doc.recompute()
        self.plate = extrude(self.doc, self.part, sk, Depth=4)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def bodies(self):
        return list(app_part.tip_bodies(self.part))

    def body(self, i=0):
        return self.bodies()[i].shape

    def boss(self, z0=-6, h=10, r=6):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, z0), App.Rotation()))
        circle(sk, 30, 20, r)
        self.doc.recompute()
        return extrude(self.doc, self.part, sk, Depth=h, MergeResult=False)


class TestIndent(Case):
    def test_wall_round_the_kept_region(self):
        self.boss()                     # z -6..4: through the plate's bottom only
        ids = [b.id for b in self.bodies()]
        f = app_deform.create_indent(self.doc, self.part, TargetBody=ids[0], ToolBody=ids[1],
                                     Thickness=1.0, Clearance=0.0)
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(f.Proxy.regions), 1)       # the part under the plate
        t = self.body(0)
        self.assertTrue(t.isValid())
        self.assertAlmostEqual(t.BoundBox.ZMin, -7.0, 4)    # a wall 1 under the boss
        tool = self.body(1)
        self.assertAlmostEqual(tool.Volume, PI * 36 * 10, 3)   # the tool is untouched
        self.assertLess(t.common(tool).Volume, 1e-6)          # no overlap left
        f.Cut = True
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.body(0).Volume, 60 * 40 * 4 - PI * 36 * 4, 3)

    def test_excluded_region_is_only_cut(self):
        self.boss(z0=-6, h=16)          # through both faces: two regions
        ids = [b.id for b in self.bodies()]
        f = app_deform.create_indent(self.doc, self.part, TargetBody=ids[0], ToolBody=ids[1],
                                     Thickness=1.0)
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(f.Proxy.regions), 2)
        lo = f.Proxy.regions[0]
        f.ExcludedPoints = ["{},{},{}".format(lo[0].x, lo[0].y, lo[0].z)]
        self.doc.recompute()
        self.ok(f)
        bb = self.body(0).BoundBox
        self.assertAlmostEqual(bb.ZMin, 0.0, 4)
        self.assertAlmostEqual(bb.ZMax, 11.0, 4)

    def test_needs_touching_bodies(self):
        self.boss(z0=20, h=5)
        ids = [b.id for b in self.bodies()]
        f = app_deform.create_indent(self.doc, self.part, TargetBody=ids[0], ToolBody=ids[1])
        self.doc.recompute()
        self.assertIn("doesn't touch", f.ErrorMessage)


class TestDeform(Case):
    def test_point_pushes_a_bump(self):
        f = app_deform.create_deform(self.doc, self.part, DeformPoint=V(30, 20, 4),
                                     Distance=6, Radius=15)
        self.doc.recompute()
        self.ok(f)
        s = self.body()
        self.assertTrue(s.isValid())
        self.assertAlmostEqual(s.BoundBox.ZMax, 10.0, 3)    # square to the top face
        self.assertAlmostEqual(s.BoundBox.ZMin, 0.0, 6)     # the bottom stays
        self.assertGreater(s.Volume, 60 * 40 * 4 + 100)
        f.ReverseDirection = True
        self.doc.recompute()
        self.ok(f)
        self.assertLess(self.body().Volume, 60 * 40 * 4 - 100)

    def test_curve_to_curve(self):
        a = sketch(self.doc, plane(self.part, "Top Plane"),
                   attach_offset=App.Placement(V(0, 0, 4), App.Rotation()))
        a.addGeometry(Part.LineSegment(V(10, 20, 0), V(50, 20, 0)))
        b = sketch(self.doc, plane(self.part, "Top Plane"),
                   attach_offset=App.Placement(V(0, 0, 9), App.Rotation()))
        b.addGeometry(Part.LineSegment(V(10, 20, 0), V(50, 20, 0)))
        self.doc.recompute()
        f = app_deform.create_deform(self.doc, self.part, DeformType="Curve to curve",
                                     InitialCurves=[a], TargetCurves=[b], Radius=15)
        self.doc.recompute()
        self.ok(f)
        s = self.body()
        self.assertTrue(s.isValid())
        self.assertAlmostEqual(s.BoundBox.ZMax, 9.0, 2)

    def test_surface_push(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 2), App.Rotation()))
        circle(sk, 30, 20, 5)
        self.doc.recompute()
        extrude(self.doc, self.part, sk, Depth=10, MergeResult=False)
        ids = [b.id for b in self.bodies()]
        f = app_deform.create_deform(self.doc, self.part, DeformType="Surface push",
                                     ToolBody=ids[1])
        self.doc.recompute()
        self.ok(f)
        t = self.body(0)
        self.assertTrue(t.isValid())
        # Pushed out of the tool, to within the control net's spacing (it overlapped
        # PI * 25 * 2 = 157 mm^3).
        self.assertLess(t.common(self.body(1)).Volume, 0.05 * PI * 25 * 2)
        self.assertAlmostEqual(self.body(1).Volume, PI * 25 * 10, 3)


class TestFreeform(Case):
    def test_pull_a_point(self):
        top = face_at(self.plate, V(30, 20, 4))
        f = app_deform.create_freeform(self.doc, self.part, Items=[top],
                                       ControlPoints=["30,20,4|5"])
        self.doc.recompute()
        self.ok(f)
        s = self.body()
        self.assertTrue(s.isValid())
        self.assertAlmostEqual(s.BoundBox.ZMax, 9.0, 0)
        self.assertAlmostEqual(s.BoundBox.XLength, 60, 6)      # the edges stay put
        f.ControlPoints = ["30,20,4|-2"]
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.body().BoundBox.ZMax, 4.0, 6)

    def test_point_on_the_edge_is_refused(self):
        top = face_at(self.plate, V(30, 20, 4))
        f = app_deform.create_freeform(self.doc, self.part, Items=[top],
                                       ControlPoints=["0,20,4|5"])
        self.doc.recompute()
        self.assertIn("edge", f.ErrorMessage)


class TestFlatten(Case):
    def test_cylinder_patch_comes_out_true(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        circle(sk, 100, 0, 10)
        self.doc.recompute()
        cyl = extrude(self.doc, self.part, sk, Depth=20, MergeResult=False)
        side = face_at(cyl, V(110, 0, 20))
        f = app_deform.create_flatten(self.doc, self.part, Items=[side])
        self.doc.recompute()
        self.ok(f)
        srf = [b for b in self.bodies() if b.kind == "surface"]
        self.assertEqual(len(srf), 1)
        self.assertAlmostEqual(srf[0].shape.Area, 2 * PI * 10 * 20, 0)
        self.assertEqual(f.WarningMessage, "")
        self.assertIsNotNone(srf[0].shape.findPlane())


if __name__ == "__main__":
    unittest.main()
