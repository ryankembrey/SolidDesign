# SPDX-License-Identifier: LGPL-2.1-or-later
"""Reference Point and Coordinate System."""

import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import refgeom
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch


def edge_at(obj, a, b):
    for i, e in enumerate(obj.Shape.Edges, 1):
        ps = [v.Point for v in e.Vertexes]
        if len(ps) == 2 and ({(round(p.x, 6), round(p.y, 6), round(p.z, 6)) for p in ps} ==
                             {(round(a.x, 6), round(a.y, 6), round(a.z, 6)),
                              (round(b.x, 6), round(b.y, 6), round(b.z, 6))}):
            return "Edge%d" % i
    raise AssertionError("no edge %s %s" % (a, b))


class TestRefPoint(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("RP")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        circle(sk, 10, 5, 3)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=8)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, o):
        self.assertEqual(o.ErrorMessage, "", o.ErrorMessage)

    def pt(self, kind, refs, **props):
        p = refgeom.create_point(self.doc, self.part, kind, refs)
        for k, v in props.items():
            setattr(p, k, v)
        self.doc.recompute()
        self.ok(p)
        self.assertEqual(len(p.Shape.Vertexes), 1)
        return p.Shape.Vertexes[0].Point

    def test_point_types(self):
        hole_edge = None
        for i, e in enumerate(self.box.Shape.Edges, 1):
            if hasattr(e.Curve, "Radius") and abs(e.BoundBox.ZMax - 8) < 1e-6:
                hole_edge = "Edge%d" % i
        q = self.pt("Arc Center", [(self.box, hole_edge)])
        self.assertTrue(q.isEqual(V(10, 5, 8), 1e-6))
        top = face_at(self.box, V(1, 1, 8), V(0, 0, 1))
        q = self.pt("Center of Face", [(self.box, top)])
        self.assertAlmostEqual(q.z, 8, 6)
        self.assertAlmostEqual(q.x, 10, 6)
        q = self.pt("On Point", [(self.box, "Vertex1")])
        self.assertTrue(q.isEqual(self.box.Shape.Vertexes[0].Point, 1e-9))
        e = edge_at(self.box, V(0, 0, 0), V(0, 0, 8))
        q = self.pt("Along Curve Distance", [(self.box, e)], Distance=3)
        self.assertAlmostEqual(min(q.z, 8 - q.z), 3, 6)
        mid = self.doc.addObject("Part::Feature", "Mid")
        mid.Shape = Part.makePlane(100, 100, V(-50, -50, 5))
        q = self.pt("Intersection", [(self.box, e), (mid, "Face1")])
        self.assertTrue(q.isEqual(V(0, 0, 5), 1e-6))
        q = self.pt("Projection", [(self.box, "Vertex1"), (mid, "Face1")])
        self.assertAlmostEqual(q.z, 5, 6)

    def test_point_follows_the_model(self):
        top = face_at(self.box, V(1, 1, 8), V(0, 0, 1))
        p = refgeom.create_point(self.doc, self.part, "Center of Face", [(self.box, top)])
        self.doc.recompute()
        self.box.Depth = 12
        self.doc.recompute()
        self.ok(p)
        self.assertAlmostEqual(p.Shape.Vertexes[0].Point.z, 12, 6)

    def test_errors(self):
        p = refgeom.create_point(self.doc, self.part, "Arc Center",
                                 [(self.box, edge_at(self.box, V(0, 0, 0), V(0, 0, 8)))])
        self.doc.recompute()
        self.assertIn("circular", p.ErrorMessage)

    def test_coordinate_system(self):
        c = refgeom.create_csys(self.doc, self.part)
        self.doc.recompute()
        self.ok(c)
        self.assertTrue(c.Placement.isSame(App.Placement(), 1e-9))
        self.assertNotIn("Touched", c.State)
        # Origin at a vertex, X along a side edge (Z up), Y along the top's short edge.
        e = edge_at(self.box, V(20, 0, 8), V(20, 10, 8))
        z_edge = edge_at(self.box, V(20, 0, 0), V(20, 0, 8))
        v = [i for i, x in enumerate(self.box.Shape.Vertexes, 1)
             if x.Point.isEqual(V(20, 0, 8), 1e-9)][0]
        c2 = refgeom.create_csys(self.doc, self.part, None,
                                 [(self.box, "Vertex%d" % v), (self.box, z_edge), (self.box, e)])
        self.doc.recompute()
        self.ok(c2)
        pl = c2.Placement
        self.assertTrue(pl.Base.isEqual(V(20, 0, 8), 1e-9))
        x = pl.Rotation.multVec(V(1, 0, 0))
        y = pl.Rotation.multVec(V(0, 1, 0))
        z = pl.Rotation.multVec(V(0, 0, 1))
        self.assertAlmostEqual(abs(x.z), 1, 9)
        self.assertAlmostEqual(abs(y.y), 1, 9)
        self.assertAlmostEqual(z.dot(x.cross(y)), 1, 9)
        self.assertNotIn("Touched", c2.State)
        c2.FlipX = True
        self.doc.recompute()
        self.assertAlmostEqual(c2.Placement.Rotation.multVec(V(1, 0, 0)).dot(x), -1, 9)
        # A sketch attaches to it (ObjectXY) and sits at its origin.
        sk = sketch(self.doc, c2, mapmode="ObjectXY")
        self.doc.recompute()
        self.assertTrue(sk.Placement.Base.isEqual(V(20, 0, 8), 1e-6))


if __name__ == "__main__":
    unittest.main()
