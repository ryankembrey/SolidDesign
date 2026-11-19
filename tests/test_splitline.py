# SPDX-License-Identifier: LGPL-2.1-or-later
"""Split Line: projection, intersection, silhouette; then a draft on a split face."""

import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import dressup, faceops, part as app_part, refs
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch, volumes


class TestSplitLine(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("SL")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=10)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def body(self):
        return list(app_part.tip_bodies(self.part))[0].shape

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def test_projection(self):
        s = sketch(self.doc, plane(self.part, "Top Plane"),
                   attach_offset=App.Placement(V(0, 0, 20), App.Rotation()))
        rect(s, 5, 2, 15, 8)
        self.doc.recompute()
        top = face_at(self.box, V(1, 1, 10), V(0, 0, 1))
        f = faceops.create_split_line(self.doc, self.part, [top], s)
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "Split Line1")
        b = self.body()
        self.assertEqual(len(b.Faces), 7)
        self.assertAlmostEqual(b.Volume, 2000, 6)
        f.SingleDirection = True    # along the sketch's normal: up, away from the box
        self.doc.recompute()
        self.assertIn("doesn't land", f.ErrorMessage)
        f.Reverse = True            # down onto it
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(self.body().Faces), 7)

    def test_intersection_then_draft_on_the_split(self):
        mid = self.doc.addObject("Part::Feature", "Mid")
        mid.Shape = Part.makePlane(60, 60, V(-20, -20, 5))
        sides = [face_at(self.box, V(10, 0, 5), V(0, -1, 0)),
                 face_at(self.box, V(20, 5, 5), V(1, 0, 0)),
                 face_at(self.box, V(10, 10, 5), V(0, 1, 0)),
                 face_at(self.box, V(0, 5, 5), V(-1, 0, 0))]
        f = faceops.create_split_line(self.doc, self.part, sides)
        f.SplitType = "Intersection"
        f.Tools = [(mid, ["Face1"])]
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(len(self.body().Faces), 10)
        # The split's edges at z = 5 are a parting line: draft the faces above them.
        es = [("Edge%d" % i) for i, e in enumerate(f.Shape.Edges, 1)
              if abs(e.BoundBox.ZMin - 5) < 1e-6 and abs(e.BoundBox.ZMax - 5) < 1e-6]
        self.assertEqual(len(es), 4)
        d = dressup.create_draft(self.doc, self.part)
        d.DraftType = "Parting Line"
        refs.set_ref(d, "PartingLines", f, es)
        d.Angle = 3
        self.doc.recompute()
        self.ok(d)
        self.assertLess(sum(volumes(self.part).values()), 2000)

    def test_silhouette(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 40, 5, 4)
        self.doc.recompute()
        cyl = extrude(self.doc, self.part, sk, Depth=10)
        side = face_at(cyl, V(44, 5, 5))
        f = faceops.create_split_line(self.doc, self.part, [side])
        f.SplitType = "Silhouette"
        front = face_at(self.box, V(10, 0, 5), V(0, -1, 0))   # pull along -y
        refs.set_ref(f, "PullDirection", cyl, [front])
        self.doc.recompute()
        self.ok(f)
        cylb = [b for b in app_part.tip_bodies(self.part) if b.shape.BoundBox.XMin > 30][0]
        rounds = [x for x in cylb.shape.Faces if x.Surface.TypeId == "Part::GeomCylinder"]
        self.assertEqual(len(rounds), 2)
        self.assertAlmostEqual(rounds[0].Area, rounds[1].Area, 4)


if __name__ == "__main__":
    unittest.main()
