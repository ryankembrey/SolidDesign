# SPDX-License-Identifier: LGPL-2.1-or-later
"""Insert > Curve: Projected, Composite, Through XYZ Points, Through Reference
Points; and using them as a sweep path."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import refgeom, sweep as app_sweep
from freecad.SolidDesign.app import part as app_part
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch

PI = math.pi


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Crv")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)


class TestCurves(Case):
    def test_projected_on_a_cylinder(self):
        sk0 = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk0, 0, 0, 10)
        self.doc.recompute()
        cyl = extrude(self.doc, self.part, sk0, Depth=30)
        side = face_at(cyl, V(10, 0, 15), V(1, 0, 0))
        line = sketch(self.doc, plane(self.part, "Right Plane"),
                      attach_offset=App.Placement(V(0, 0, 20), App.Rotation()))
        line.addGeometry(Part.LineSegment(V(-5, 5, 0), V(5, 25, 0)))
        self.doc.recompute()
        c = refgeom.create_projected_curve(self.doc, self.part, Sketch=line,
                                           _ref_Faces=(cyl, [side]), ReverseDirection=True)
        self.doc.recompute()
        self.ok(c)
        self.assertEqual(c.Label, "Curve1")
        for v in c.Shape.Vertexes:
            r = math.hypot(v.Point.x, v.Point.y)
            self.assertAlmostEqual(r, 10, 5)
            self.assertGreater(v.Point.x, 0)            # the near side only
        c.ReverseDirection = False
        self.doc.recompute()
        self.assertIn("doesn't land", c.ErrorMessage)

    def test_sketch_on_sketch(self):
        a = sketch(self.doc, plane(self.part, "Top Plane"))
        a.addGeometry(Part.LineSegment(V(0, 0, 0), V(20, 0, 0)))
        b = sketch(self.doc, plane(self.part, "Front Plane"))
        b.addGeometry(Part.LineSegment(V(0, 0, 0), V(20, 10, 0)))
        self.doc.recompute()
        c = refgeom.create_projected_curve(self.doc, self.part, Type="Sketch on sketch",
                                           Sketch=a, Sketch2=b)
        self.doc.recompute()
        self.ok(c)
        e = c.Shape.Edges[0]
        self.assertAlmostEqual(e.Length, math.hypot(20, 10), 5)

    def test_composite_xyz_points_and_sweep(self):
        a = sketch(self.doc, plane(self.part, "Top Plane"))
        a.addGeometry(Part.LineSegment(V(0, 0, 0), V(20, 0, 0)))
        b = sketch(self.doc, plane(self.part, "Front Plane"))
        b.addGeometry(Part.LineSegment(V(20, 0, 0), V(20, 20, 0)))
        self.doc.recompute()
        cc = refgeom.create_composite_curve(self.doc, self.part, Curves=[a, b])
        self.doc.recompute()
        self.ok(cc)
        self.assertEqual(cc.Label, "CompCurve1")
        self.assertAlmostEqual(cc.Shape.Length, 40, 6)
        self.assertEqual(len(cc.Shape.Wires), 1)
        x = refgeom.create_xyz_curve(self.doc, self.part,
                                     Points=["0,0,0", "10,5,2", "20,0,8", "30,-5,10"])
        self.doc.recompute()
        self.ok(x)
        e = x.Shape.Edges[0]
        for p in ((0, 0, 0), (10, 5, 2), (20, 0, 8)):
            self.assertLess(e.distToShape(Part.Vertex(V(*p)))[0], 1e-7)
        x.Points = ["0,0,0"]
        self.doc.recompute()
        self.assertIn("at least two", x.ErrorMessage)
        x.Points = ["0,0,0", "10,5,2", "20,0,8", "30,-5,10"]
        self.doc.recompute()
        # A pipe swept along the XYZ curve.
        prof = sketch(self.doc, plane(self.part, "Right Plane"))
        circle(prof, 0, 0, 1)
        self.doc.recompute()
        sw = app_sweep.create_sweep(self.doc, self.part, "Add", prof)
        sw.Path = (x, [])
        self.doc.recompute()
        self.ok(sw)
        b = list(app_part.tip_bodies(self.part))[0].shape
        self.assertTrue(b.isValid())
        self.assertGreater(b.Volume, 50)                 # the profile meets the path skewed

    def test_through_reference_points(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        box = extrude(self.doc, self.part, sk, Depth=10)
        names = []
        for p in (V(0, 0, 10), V(20, 0, 10), V(20, 10, 0)):
            for i, v in enumerate(box.Shape.Vertexes, 1):
                if (v.Point - p).Length < 1e-6:
                    names.append("Vertex%d" % i)
        c = refgeom.create_points_curve(self.doc, self.part, _ref_Vertices=(box, names))
        self.doc.recompute()
        self.ok(c)
        e = c.Shape.Edges[0]
        self.assertLess(e.distToShape(Part.Vertex(V(20, 10, 0)))[0], 1e-7)
        c.Closed = True
        self.doc.recompute()
        self.ok(c)
        self.assertTrue(c.Shape.Edges[0].isClosed())
