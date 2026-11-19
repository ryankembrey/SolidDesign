# SPDX-License-Identifier: LGPL-2.1-or-later
"""Topological naming tests (spec section 7, point 7).

Model: a box (width W from a sketch dimension), a blind pocket, then a boss
sketched at x = 50 on an offset Right Plane and extruded Up To Surface onto the
box's right face (x = W). Each case changes the history; the boss must still end
on the face at x = W, or fail with a clear message.
"""

import os
import tempfile
import unittest

import FreeCAD as App
import Sketcher

from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import refs, util
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch


class Naming(unittest.TestCase):
    W = 20.0

    def setUp(self):
        self.doc, self.part = new_doc("TNP")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, self.W, 10)
        self.width = sk.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, self.W))
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 2))
        sk.addConstraint(Sketcher.Constraint("Vertical", 1))
        sk.addConstraint(Sketcher.Constraint("Vertical", 3))
        sk.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 10.0))
        self.base_sketch = sk
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=5)
        psk = sketch(self.doc, plane(self.part, "Top Plane"),
                     attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        rect(psk, 4, 3, 8, 7)
        self.pocket_sketch = psk
        self.doc.recompute()
        self.pocket = extrude(self.doc, self.part, psk, "Cut", Depth=2, Reverse=True)
        bsk = sketch(self.doc, plane(self.part, "Right Plane"),
                     attach_offset=App.Placement(V(0, 0, 50), App.Rotation()))
        rect(bsk, 2, 1, 8, 4)
        self.doc.recompute()
        self.boss = extrude(self.doc, self.part, bsk, EndCondition="Up To Surface",
                            Reverse=True)
        refs.set_ref(self.boss, "UpToFace", self.pocket,
                     face_at(self.pocket, V(self.W, 5, 2.5), V(1, 0, 0)))
        self.doc.recompute()
        self.check(self.W)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def check(self, w):
        self.assertEqual(self.boss.ErrorMessage, "", self.boss.ErrorMessage)
        bb = self.part.Shape.BoundBox
        self.assertAlmostEqual(bb.XMax, 50.0)
        # The boss is merged into the box and ends exactly on the face at x = w.
        self.assertEqual(len(self.part.BodyIds), 1)
        self.assertAlmostEqual(self.boss.AddSubShape.BoundBox.XMin, w, 6)
        self.assertAlmostEqual(self.boss.AddSubShape.Volume, (50 - w) * 6 * 3, 6)

    def face_count(self):
        return len(self.pocket.Shape.Faces)

    def test_upstream_change_adds_and_removes_faces(self):
        n = self.face_count()
        self.pocket.EndCondition = "Through All"      # the pocket's floor face goes away
        self.doc.recompute()
        self.assertEqual(self.face_count(), n - 1)
        self.check(self.W)
        self.pocket.EndCondition = "Blind"            # and comes back
        self.doc.recompute()
        self.check(self.W)
        self.base_sketch.setDatum(self.width, App.Units.Quantity("25 mm"))
        self.doc.recompute()
        self.check(25.0)
        circle(self.pocket_sketch, 14, 5, 1)          # more faces in the referenced feature
        self.doc.recompute()
        self.check(25.0)

    def test_insert_before(self):
        app_part.roll_to(self.part, self.box)
        self.doc.recompute()
        self.assertTrue(self.boss.RolledBack)
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 15, 5, 2)
        self.doc.recompute()
        hole = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All - Both")
        self.assertEqual(util.features(self.part).index(hole), 1)
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        self.check(self.W)

    def test_suppress_before(self):
        self.pocket.Suppressed = True
        self.doc.recompute()
        self.check(self.W)
        self.pocket.Suppressed = False
        self.doc.recompute()
        self.check(self.W)

    def test_reorder(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 15, 5, 2)
        self.doc.recompute()
        hole = extrude(self.doc, self.part, sk, "Cut", EndCondition="Through All - Both")
        app_part.move_feature(self.part, hole, 1)        # before the pocket
        self.doc.recompute()
        self.assertEqual([f.Label for f in util.features(self.part)],
                         ["Boss-Extrude1", "Cut-Extrude2", "Cut-Extrude1", "Boss-Extrude2"])
        self.check(self.W)
        # The boss uses the pocket's face: it can't move above the pocket.
        ok, why = app_part.can_move(self.part, self.boss, 1)
        self.assertFalse(ok)
        self.assertIn("Cut-Extrude1", why)

    def test_roll_back_and_forward(self):
        for f in util.features(self.part):
            app_part.roll_to(self.part, f)
            self.doc.recompute()
        self.check(self.W)
        app_part.roll_to(self.part, None)
        self.doc.recompute()
        self.assertEqual(len(self.part.BodyIds), 0)
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        self.check(self.W)

    def test_save_reopen(self):
        path = os.path.join(tempfile.mkdtemp(), "tnp.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.part = [o for o in self.doc.Objects if util.is_part(o)][0]
        feats = util.features(self.part)
        self.box, self.pocket, self.boss = feats
        self.base_sketch = self.box.Sketch
        for o in self.doc.Objects:
            o.touch()
        self.doc.recompute()
        self.check(self.W)
        self.pocket.EndCondition = "Through All"
        self.doc.recompute()
        self.check(self.W)

    def test_lost_reference_fails_clearly(self):
        """When the face is gone and nothing unique replaces it, fail and say so;
        never pick silently between candidates."""
        g = self.pocket_sketch
        g.delGeometries([0, 1, 2, 3])
        rect(g, self.W - 2, -5, self.W + 5, 15)      # cut the whole right end away
        self.pocket.EndCondition = "Through All"
        self.doc.recompute()
        self.assertNotEqual(self.boss.ErrorMessage, "")
        self.assertIn("Re-pick", self.boss.ErrorMessage)
        # The bodies before it pass through unchanged.
        self.assertAlmostEqual(self.part.Shape.Volume, self.pocket.Shape.Volume)
