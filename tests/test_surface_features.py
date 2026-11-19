# SPDX-License-Identifier: LGPL-2.1-or-later
"""Surface mode of Extrude, Revolve, Sweep, Loft and Boundary (SolidWorks'
Extruded, Revolved, Swept, Lofted and Boundary Surface)."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import revolve as app_revolve
from freecad.SolidDesign.app import sweep as app_sweep
from helpers import V, circle, extrude, new_doc, plane, rect, sketch

PI = math.pi


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Srf")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def bodies(self, kind=None):
        return [b for b in app_part.tip_bodies(self.part) if kind is None or b.kind == kind]

    def top_sketch(self, z=0.0):
        return sketch(self.doc, plane(self.part, "Top Plane"),
                      attach_offset=App.Placement(V(0, 0, z), App.Rotation()))


class TestExtrudedSurface(Case):
    def test_closed_sketch_makes_walls_not_a_solid(self):
        sk = self.top_sketch()
        rect(sk, 0, 0, 10, 20)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, "Surface", Depth=5)
        self.ok(f)
        self.assertEqual(f.Label, "Surface-Extrude1")
        bs = self.bodies()
        self.assertEqual([b.kind for b in bs], ["surface"])
        self.assertAlmostEqual(bs[0].shape.Area, 2 * (10 + 20) * 5, 6)
        f.CapEnd = True
        self.doc.recompute()
        self.ok(f)
        s = self.bodies()[0].shape
        self.assertEqual(self.bodies()[0].kind, "surface")
        self.assertAlmostEqual(s.Area, 2 * (10 + 20) * 5 + 2 * 200, 6)
        self.assertTrue(s.Shells[0].isClosed())

    def test_mode_switches_label_and_body_kind(self):
        sk = self.top_sketch()
        rect(sk, 0, 0, 10, 10)
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, "Add", Depth=5)
        self.assertEqual(f.Label, "Boss-Extrude1")
        f.Mode = "Surface"
        self.doc.recompute()
        self.ok(f)
        self.assertTrue(f.Label.startswith("Surface-Extrude"))
        self.assertEqual([b.kind for b in self.bodies()], ["surface"])

    def test_open_sketch_up_to_surface_and_draft(self):
        block = self.top_sketch()
        rect(block, -20, -20, 20, 20)
        self.doc.recompute()
        extrude(self.doc, self.part, block, "Add", Depth=30)
        sk = self.top_sketch(-10)
        sk.addGeometry(Part.LineSegment(V(-5, 0, 0), V(5, 0, 0)))
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, "Surface", EndCondition="Up To Next")
        self.ok(f)
        srf = self.bodies("surface")[0].shape
        self.assertAlmostEqual(srf.BoundBox.ZMax, 0.0, 6)
        self.assertAlmostEqual(srf.Area, 10 * 10, 6)
        rect_sk = self.top_sketch(40)
        rect(rect_sk, 0, 0, 10, 10)
        self.doc.recompute()
        g = extrude(self.doc, self.part, rect_sk, "Surface", Depth=10, Draft=True,
                    DraftAngle=10)
        self.ok(g)
        top = 10 - 2 * 10 * math.tan(math.radians(10))
        bb = [b for b in self.bodies("surface") if b.shape.BoundBox.ZMin > 39][0].shape.BoundBox
        self.assertAlmostEqual(bb.ZMax, 50, 6)
        self.assertAlmostEqual(bb.XLength, 10, 6)
        g.Reverse = True
        self.doc.recompute()
        self.ok(g)
        self.assertGreater(top, 0)

    def test_cap_end_needs_closed_profile(self):
        sk = self.top_sketch()
        sk.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        self.doc.recompute()
        f = extrude(self.doc, self.part, sk, "Surface", Depth=5, CapEnd=True)
        self.assertIn("Cap end needs a closed sketch", f.ErrorMessage)


class TestRevolvedSurface(Case):
    def test_open_profile_revolves_to_a_surface(self):
        sk = sketch(self.doc, plane(self.part, "Front Plane"))
        sk.addGeometry(Part.LineSegment(V(5, 0, 0), V(5, 10, 0)))
        sk.addGeometry(Part.LineSegment(V(0, -10, 0), V(0, 20, 0)), True)
        self.doc.recompute()
        f = app_revolve.create(self.doc, self.part, "Surface", sk)
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "Surface-Revolve1")
        bs = self.bodies()
        self.assertEqual([b.kind for b in bs], ["surface"])
        self.assertAlmostEqual(bs[0].shape.Area, 2 * PI * 5 * 10, 4)
        f.Angle = 90
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.bodies()[0].shape.Area, 2 * PI * 5 * 10 / 4, 4)


class TestSweptLoftedBoundarySurface(Case):
    def test_sweep_loft_boundary(self):
        path = sketch(self.doc, plane(self.part, "Front Plane"))
        path.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, 20, 0)))
        prof = self.top_sketch()
        circle(prof, 0, 0, 2)
        self.doc.recompute()
        s = app_sweep.create_sweep(self.doc, self.part, "Surface", prof)
        s.Path = (path, [])
        self.doc.recompute()
        self.ok(s)
        self.assertEqual(s.Label, "Surface-Sweep1")
        self.assertAlmostEqual(self.bodies("surface")[0].shape.Area, 2 * PI * 2 * 20, 4)
        self.assertFalse(self.bodies("solid"))

        a = self.top_sketch(50)
        circle(a, 0, 0, 5)
        b = self.top_sketch(60)
        circle(b, 0, 0, 5)
        self.doc.recompute()
        lo = app_sweep.create_loft(self.doc, self.part, "Surface", profiles=[a, b])
        self.doc.recompute()
        self.ok(lo)
        self.assertEqual(lo.Label, "Surface-Loft1")
        srf = [x for x in self.bodies("surface") if x.shape.BoundBox.ZMin > 49]
        self.assertEqual(len(srf), 1)
        self.assertAlmostEqual(srf[0].shape.Area, 2 * PI * 5 * 10, 2)
        self.assertFalse(self.bodies("solid"))

        c = self.top_sketch(80)
        rect(c, 0, 0, 10, 10)
        d = self.top_sketch(90)
        rect(d, 0, 0, 10, 10)
        self.doc.recompute()
        bd = app_sweep.create_boundary(self.doc, self.part, "Surface", profiles=[c, d])
        self.doc.recompute()
        self.ok(bd)
        self.assertEqual(bd.Label, "Boundary-Surface1")
        srf = [x for x in self.bodies("surface") if x.shape.BoundBox.ZMin > 79]
        self.assertAlmostEqual(srf[0].shape.Area, 4 * 10 * 10, 2)
        self.assertFalse(self.bodies("solid"))


if __name__ == "__main__":
    unittest.main()
