# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fillet types: Variable Size, Face Fillet, Full Round Fillet."""

import math
import unittest

import FreeCAD as App

from freecad.SolidDesign.app import dressup, refs
from helpers import V, extrude, face_at, new_doc, plane, rect, sketch, volumes


def edge_at(obj, a, b):
    for i, e in enumerate(obj.Shape.Edges, 1):
        ps = sorted((round(v.Point.x, 6), round(v.Point.y, 6), round(v.Point.z, 6))
                    for v in e.Vertexes)
        want = sorted([(round(a.x, 6), round(a.y, 6), round(a.z, 6)),
                       (round(b.x, 6), round(b.y, 6), round(b.z, 6))])
        if ps == want:
            return "Edge%d" % i
    raise AssertionError("no edge")


class TestFilletTypes(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("FT")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 40, 6)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=20)
        self.v0 = self.total()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def total(self):
        return sum(volumes(self.part).values())

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def test_variable_one_edge(self):
        e = edge_at(self.box, V(0, 0, 20), V(40, 0, 20))
        f = dressup.create_fillet(self.doc, self.part, [e])
        f.FilletType = "Variable Size"
        f.StartRadius = 1
        f.EndRadius = 3
        self.doc.recompute()
        self.ok(f)
        removed = self.v0 - self.total()
        # The corner area (1 - pi/4) r^2 integrated with r linear from 1 to 3 over 40.
        k = 1 - math.pi / 4
        expect = k * 40 * (1 + 1 * 3 + 9) / 3.0
        self.assertAlmostEqual(removed / expect, 1.0, 1)     # OCC's law is near-linear

    def test_variable_chain_of_edges(self):
        es = [edge_at(self.box, V(0, 0, 20), V(40, 0, 20)),
              edge_at(self.box, V(40, 0, 20), V(40, 6, 20))]
        f = dressup.create_fillet(self.doc, self.part, es)
        f.FilletType = "Variable Size"
        f.TangentPropagation = False
        f.StartRadius = 0.5
        f.EndRadius = 1.5
        self.doc.recompute()
        self.ok(f)
        self.assertLess(self.total(), self.v0)
        f.ReverseVariable = True
        self.doc.recompute()
        self.ok(f)

    def test_face_fillet(self):
        top = face_at(self.box, V(20, 3, 20), V(0, 0, 1))
        front = face_at(self.box, V(20, 0, 10), V(0, -1, 0))
        f = dressup.create_fillet(self.doc, self.part)
        f.FilletType = "Face Fillet"
        f.Radius = 2
        refs.set_ref(f, "FaceSet1", self.box, [top])
        refs.set_ref(f, "FaceSet2", self.box, [front])
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.v0 - self.total(), (1 - math.pi / 4) * 4 * 40, 3)
        back_bottom = face_at(self.box, V(20, 3, 0), V(0, 0, -1))
        refs.set_ref(f, "FaceSet2", self.box, [back_bottom])
        self.doc.recompute()
        self.assertIn("don't meet", f.ErrorMessage)

    def test_full_round(self):
        top = face_at(self.box, V(20, 3, 20), V(0, 0, 1))
        front = face_at(self.box, V(20, 0, 10), V(0, -1, 0))
        back = face_at(self.box, V(20, 6, 10), V(0, 1, 0))
        f = dressup.create_fillet(self.doc, self.part)
        f.FilletType = "Full Round Fillet"
        refs.set_ref(f, "FaceSet1", self.box, [front])
        refs.set_ref(f, "CenterFaces", self.box, [top])
        refs.set_ref(f, "FaceSet2", self.box, [back])
        self.doc.recompute()
        self.ok(f)
        # The top becomes a half cylinder of radius 3.
        removed = self.v0 - self.total()
        self.assertAlmostEqual(removed, (6 * 3 - math.pi * 9 / 2) * 40, 3)
        s = list(volumes(self.part).keys())
        self.assertEqual(len(s), 1)


if __name__ == "__main__":
    unittest.main()
