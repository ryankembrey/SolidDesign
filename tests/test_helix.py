# SPDX-License-Identifier: LGPL-2.1-or-later
"""Helix/Spiral, and a sweep along a helix (a spring)."""

import math
import unittest

import FreeCAD as App

from freecad.SolidDesign.app import refgeom, sweep as app_sweep
from freecad.SolidDesign.core import curves
from helpers import V, circle, extrude, new_doc, plane, sketch, volumes


class TestHelix(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Hx")
        self.sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(self.sk, 0, 0, 10)
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def helix(self, **props):
        h = refgeom.create_helix(self.doc, self.part, None, [(self.sk, "")])
        for k, v in props.items():
            setattr(h, k, v)
        self.doc.recompute()
        self.assertEqual(h.ErrorMessage, "", h.ErrorMessage)
        return h

    def test_pitch_and_revolutions(self):
        h = self.helix(Pitch=4, Revolutions=5)
        self.assertEqual(h.Label, "Helix/Spiral1")
        bb = h.Shape.BoundBox
        self.assertAlmostEqual(bb.ZMin, 0, 6)
        self.assertAlmostEqual(bb.ZMax, 20, 6)
        expect = 5 * math.hypot(2 * math.pi * 10, 4)
        self.assertAlmostEqual(h.Shape.Length, expect, 0)
        h.Flip = True
        self.doc.recompute()
        self.assertAlmostEqual(h.Shape.BoundBox.ZMin, -20, 6)

    def test_height_types_and_taper(self):
        h = self.helix(Type="Height and Revolution", Height=30, Revolutions=3)
        self.assertAlmostEqual(h.Shape.BoundBox.ZMax, 30, 6)
        h.Type = "Height and Pitch"
        h.Pitch = 6
        self.doc.recompute()
        self.assertAlmostEqual(h.Shape.BoundBox.ZMax, 30, 6)
        h.TaperHelix = True
        h.TaperAngle = 10
        h.TaperOutward = True
        self.doc.recompute()
        self.assertGreater(h.Shape.BoundBox.XLength, 2 * 10 + 2 * 30 * math.tan(
            math.radians(10)) - 1)

    def test_start_angle_and_hand(self):
        h = self.helix(Pitch=4, Revolutions=1, StartAngle=90)
        start = h.Shape.OrderedVertexes[0].Point if hasattr(h.Shape, "OrderedVertexes") \
            else h.Shape.Vertexes[0].Point
        self.assertAlmostEqual(abs(start.y), 10, 4)
        e = h.Shape.Edges[0]
        t = e.tangentAt(e.FirstParameter)
        h.Clockwise = True
        self.doc.recompute()
        e2 = h.Shape.Edges[0]
        t2 = e2.tangentAt(e2.FirstParameter)
        self.assertLess(t.dot(t2), 0.5)      # turning the other way

    def test_spiral(self):
        h = self.helix(Type="Spiral", Pitch=2, Revolutions=3)
        bb = h.Shape.BoundBox
        self.assertAlmostEqual(bb.ZLength, 0, 6)
        self.assertGreater(bb.XLength, 2 * 14)

    def test_spring_sweep(self):
        h = self.helix(Pitch=5, Revolutions=3)
        s = app_sweep.create_sweep(self.doc, self.part, "Add", None)
        s.ProfileType = "Circular Profile"
        s.Diameter = 2
        s.Path = (h, [])
        self.doc.recompute()
        self.assertEqual(s.ErrorMessage, "", s.ErrorMessage)
        vol = sum(volumes(self.part).values())
        expect = math.pi * 1 ** 2 * h.Shape.Length
        self.assertAlmostEqual(vol / expect, 1.0, 2)

    def test_circle_from_a_model_edge(self):
        body = extrude(self.doc, self.part, self.sk, Depth=5)
        rim = [("Edge%d" % i) for i, e in enumerate(body.Shape.Edges, 1)
               if hasattr(e.Curve, "Radius") and abs(e.BoundBox.ZMax - 5) < 1e-6][0]
        h = refgeom.create_helix(self.doc, self.part, None, [(body, rim)])
        self.doc.recompute()
        self.assertEqual(h.ErrorMessage, "", h.ErrorMessage)
        self.assertAlmostEqual(h.Shape.BoundBox.ZMin, 5, 5)

    def test_errors(self):
        self.assertRaises(Exception, curves.numbers, curves.PITCH_REVS, 0, 3, 0)


if __name__ == "__main__":
    unittest.main()
