# SPDX-License-Identifier: LGPL-2.1-or-later
"""What the right-click menus rely on: which feature made a face, edge or vertex,
and tangent faces."""

import unittest

import FreeCAD as App

from freecad.SolidDesign.app import dressup, part as app_part
from freecad.SolidDesign.core.features import edges as core_edges
from helpers import V, extrude, new_doc, plane, rect, sketch


class TestFeatureOfElement(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("VM")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 40, 30)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=10)
        hs = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        rect(hs, 5, 5, 15, 15)
        self.doc.recompute()
        self.pocket = extrude(self.doc, self.part, hs, "Cut", Depth=4, Reverse=True)
        top = [n for n, e in self.edges() if abs(e.CenterOfMass.z - 10) < 1e-6
               and abs(e.CenterOfMass.y - 30) < 1e-6][0]
        self.fillet = dressup.create_fillet(self.doc, self.part, [top])
        self.fillet.Radius = 2
        self.doc.recompute()
        self.shape = list(app_part.tip_bodies(self.part))[0].shape

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def edges(self):
        return [("Edge%d" % i, e) for i, e in enumerate(self.box.Shape.Edges, 1)]

    def face_at(self, p):
        return [f for f in self.shape.Faces if f.isInside(p, 1e-6, True)][0]

    def made(self, elem):
        return app_part.feature_of_element(self.part, elem)

    def test_faces(self):
        self.assertIs(self.made(self.face_at(V(30, 10, 10))), self.box)      # the top
        self.assertIs(self.made(self.face_at(V(10, 10, 6))), self.pocket)    # its floor
        self.assertIs(self.made(self.face_at(V(10, 5, 8))), self.pocket)     # a wall
        rounds = [f for f in self.shape.Faces if f.Surface.TypeId == "Part::GeomCylinder"]
        self.assertEqual(len(rounds), 1)
        self.assertIs(self.made(rounds[0]), self.fillet)

    def test_edges_and_vertices(self):
        bottom = [e for e in self.shape.Edges if abs(e.CenterOfMass.z) < 1e-6][0]
        self.assertIs(self.made(bottom), self.box)
        rim = [e for e in self.shape.Edges if abs(e.CenterOfMass.z - 6) < 1e-6][0]
        self.assertIs(self.made(rim), self.pocket)
        corner = [v for v in self.shape.Vertexes if (v.Point - V(40, 0, 0)).Length < 1e-6][0]
        self.assertIs(self.made(corner), self.box)

    def test_tangent_faces(self):
        rnd = [f for f in self.shape.Faces if f.Surface.TypeId == "Part::GeomCylinder"][0]
        got = core_edges.tangent_faces(self.shape, [rnd])
        self.assertEqual(len(got), 3)                   # the round, the top, the back
        top = self.face_at(V(30, 10, 10))
        self.assertEqual(len(core_edges.tangent_faces(self.shape, [top])), 3)


if __name__ == "__main__":
    unittest.main()
