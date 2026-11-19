# SPDX-License-Identifier: LGPL-2.1-or-later
"""Move/Copy Body, Constraints mode."""

import unittest

import FreeCAD as App

from freecad.SolidDesign.app import bodytools
from freecad.SolidDesign.app import part as app_part
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch


class TestMates(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Mates")
        self.a = self.box(0, 0, 10, 10, 10)                 # fixed: z 0..10
        self.b = self.box(30, 3, 35, 8, 5)                  # moving: 5 cube at x 30
        self.ida, self.idb = self.part.BodyIds

    def box(self, x0, y0, x1, y1, h):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, x0, y0, x1, y1)
        self.doc.recompute()
        return extrude(self.doc, self.part, sk, Depth=h, MergeResult=False)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def move(self, **mates):
        f = bodytools.create_move(self.doc, self.part, Bodies=[self.idb], MoveMode="Constraints")
        base = f.BaseFeature
        for i, (kind, moving, fixed, value, flip) in enumerate(mates["m"], 1):
            setattr(f, "MateType%d" % i, kind)
            from freecad.SolidDesign.app import refs
            refs.set_ref(f, "MateMoving%d" % i, base, moving)
            if isinstance(fixed, tuple):
                refs.set_ref(f, "MateFixed%d" % i, fixed[0], fixed[1])
            else:
                refs.set_ref(f, "MateFixed%d" % i, base, fixed)
            setattr(f, "MateValue%d" % i, value)
            setattr(f, "MateFlip%d" % i, flip)
        self.doc.recompute()
        return f

    def bb(self, bid):
        return app_part.tip_bodies(self.part).get(bid).shape.BoundBox

    def faces(self):
        base = self.b
        return {
            "b_bottom": face_at(base, V(32.5, 5.5, 0), V(0, 0, -1)),
            "b_left": face_at(base, V(30, 5.5, 2.5), V(-1, 0, 0)),
            "b_front": face_at(base, V(32.5, 3, 2.5), V(0, -1, 0)),
            "a_top": face_at(base, V(5, 5, 10), V(0, 0, 1)),
            "a_left": face_at(base, V(0, 5, 5), V(-1, 0, 0)),
            "a_front": face_at(base, V(5, 0, 5), V(0, -1, 0)),
        }

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def test_coincident_on_top(self):
        F = self.faces()
        f = self.move(m=[("Coincident", F["b_bottom"], F["a_top"], 0, False)])
        self.ok(f)
        bb = self.bb(self.idb)
        self.assertAlmostEqual(bb.ZMin, 10, 5)              # sits on A's top
        self.assertAlmostEqual(bb.XMin, 30, 4)              # and otherwise stays put
        self.assertAlmostEqual(bb.ZLength, 5, 5)

    def test_fully_placed_and_flush(self):
        F = self.faces()
        f = self.move(m=[("Coincident", F["b_bottom"], F["a_top"], 0, False),
                         ("Coincident", F["b_left"], F["a_left"], 0, True),     # flush: aligned
                         ("Coincident", F["b_front"], F["a_front"], 0, True)])
        self.ok(f)
        bb = self.bb(self.idb)
        self.assertAlmostEqual(bb.XMin, 0, 5)
        self.assertAlmostEqual(bb.YMin, 0, 5)
        self.assertAlmostEqual(bb.ZMin, 10, 5)

    def test_distance_and_follow(self):
        F = self.faces()
        f = self.move(m=[("Distance", F["b_bottom"], F["a_top"], 5.0, False)])
        self.ok(f)
        self.assertAlmostEqual(self.bb(self.idb).ZMin, 15, 5)
        self.a.Depth = 20                                     # A grows: B follows
        self.doc.recompute()
        self.ok(f)
        self.assertAlmostEqual(self.bb(self.idb).ZMin, 25, 5)

    def test_angle(self):
        F = self.faces()
        f = self.move(m=[("Angle", F["b_bottom"], (plane(self.part, "Top Plane"), ""), 30.0,
                          False)])
        self.ok(f)
        sh = app_part.tip_bodies(self.part).get(self.idb).shape
        n = [fc for fc in sh.Faces if abs(fc.Area - 25) < 1e-6]
        angles = sorted(round(fc.normalAt(0, 0).getAngle(V(0, 0, 1)) * 57.29578, 3) for fc in n)
        self.assertTrue(any(abs(a - 30) < 1e-3 or abs(a - 150) < 1e-3 for a in angles), angles)

    def test_concentric(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 50, 50, 2)
        self.doc.recompute()
        cyl = extrude(self.doc, self.part, sk, Depth=4, MergeResult=False)
        cid = [i for i in self.part.BodyIds if i not in (self.ida, self.idb)][0]
        side = [i for i, fc in enumerate(cyl.Shape.Faces, 1)
                if fc.Surface.TypeId == "Part::GeomCylinder"][0]
        f = bodytools.create_move(self.doc, self.part, Bodies=[cid], MoveMode="Constraints")
        from freecad.SolidDesign.app import refs
        f.MateType1 = "Concentric"
        refs.set_ref(f, "MateMoving1", f.BaseFeature, "Face%d" % side)
        refs.set_ref(f, "MateFixed1", plane(self.part, "Z Axis"), "")
        self.doc.recompute()
        self.ok(f)
        bb = self.bb(cid)
        self.assertAlmostEqual(bb.Center.x, 0, 5)
        self.assertAlmostEqual(bb.Center.y, 0, 5)

    def test_conflict(self):
        F = self.faces()
        f = self.move(m=[("Coincident", F["b_bottom"], F["a_top"], 0, False),
                         ("Distance", F["b_bottom"], F["a_top"], 7.0, False)])
        self.assertIn("can't all be met", f.ErrorMessage)
