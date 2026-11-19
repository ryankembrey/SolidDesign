# SPDX-License-Identifier: LGPL-2.1-or-later
"""Offset Surface and Move Face."""

import math
import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import faceops, part as app_part, refs
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch, volumes


class TestFaceOps(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("FO")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        circle(sk, 10, 5, 2)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=10)
        self.v0 = self.total()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def total(self):
        return sum(volumes(self.part).values())

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def top(self):
        return face_at(self.box, V(1, 1, 10), V(0, 0, 1))

    def test_offset_surface_makes_a_surface_body(self):
        f = faceops.create_offset_surface(self.doc, self.part, [self.top()])
        f.Distance = 5
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "Surface-Offset1")
        kinds = list(f.BodyKinds)
        self.assertEqual(kinds.count("surface"), 1)
        surf = [b for b in app_part.tip_bodies(self.part) if b.kind == "surface"][0].shape
        self.assertAlmostEqual(surf.BoundBox.ZMin, 15, 5)
        self.assertAlmostEqual(surf.Area, 200 - math.pi * 4, 4)
        f.Distance = 0
        self.doc.recompute()
        self.ok(f)
        surf = [b for b in app_part.tip_bodies(self.part) if b.kind == "surface"][0].shape
        self.assertAlmostEqual(surf.BoundBox.ZMin, 10, 6)

    def test_move_face_offset_and_hole(self):
        m = faceops.create_move_face(self.doc, self.part, [self.top()])
        m.Distance = 3
        self.doc.recompute()
        self.ok(m)
        a = 200 - math.pi * 4
        self.assertAlmostEqual(self.total() - self.v0, a * 3, 3)
        hole = face_at(self.box, V(12, 5, 5))
        refs.set_ref(m, "Items", self.box, [hole])
        m.Distance = 1      # the hole face moves along its normal: into the hole
        self.doc.recompute()
        self.ok(m)
        self.assertAlmostEqual(self.total() - self.v0, math.pi * (4 - 1) * 10, 3)

    def test_move_face_translate(self):
        m = faceops.create_move_face(self.doc, self.part, [self.top()])
        m.MoveType = "Translate"
        m.Distance = 4
        e = [("Edge%d" % i) for i, x in enumerate(self.box.Shape.Edges, 1)
             if abs(x.BoundBox.XLength) < 1e-6 and abs(x.BoundBox.YLength) < 1e-6 and
             x.BoundBox.ZLength > 1][0]          # a vertical edge: straight up
        refs.set_ref(m, "Direction", self.box, [e])
        self.doc.recompute()
        self.ok(m)
        self.assertAlmostEqual(abs(self.total() - self.v0), (200 - math.pi * 4) * 4, 3)

    def test_move_face_rotate(self):
        side = face_at(self.box, V(20, 5, 5), V(1, 0, 0))
        m = faceops.create_move_face(self.doc, self.part, [side])
        m.MoveType = "Rotate"
        m.Angle = 10
        axis = self.doc.addObject("Part::Feature", "Ax")
        axis.Shape = Part.LineSegment(V(20, -5, 0), V(20, 15, 0)).toShape()  # along y, at the bottom
        refs.set_ref(m, "Axis", axis, ["Edge1"])
        self.doc.recompute()
        self.ok(m)
        # The end face leans: a wedge 10 high, 10 deep, tan(10°)*10 wide is added or removed.
        wedge = 0.5 * 10 * math.tan(math.radians(10)) * 10 * 10
        self.assertAlmostEqual(abs(self.total() - self.v0), wedge, 2)

    def test_errors(self):
        m = faceops.create_move_face(self.doc, self.part)
        self.doc.recompute()
        self.assertIn("Pick the faces", m.ErrorMessage)
        hole = face_at(self.box, V(12, 5, 5))
        refs.set_ref(m, "Items", self.box, [hole])
        m.MoveType = "Rotate"
        self.doc.recompute()
        self.assertIn("axis", m.ErrorMessage)


if __name__ == "__main__":
    unittest.main()
