# SPDX-License-Identifier: LGPL-2.1-or-later
"""The rollback bar, as SolidWorks has it: everything below the bar is as if
suppressed; rolling forward brings it back unchanged.

A model where each step builds on the one before (the owner's report): a sketch
attached to a face of the feature above it, then a fillet on an edge. Moving the
bar anywhere, in any order, must leave no errors, show exactly the model at that
point, and rolling to the end must give back the same model and attachments.
"""

import unittest

import FreeCAD as App

from freecad.SolidDesign.app import dressup
from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import util

from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch


def total_volume(part):
    return round(sum(b.shape.Volume for b in app_part.tip_bodies(part)), 4)


class TestRollback(unittest.TestCase):
    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.Label)

    def tearDown(self):
        try:
            App.closeDocument(self.doc.Name)
        except Exception:
            pass

    def setUp(self):
        self.doc, self.part = new_doc("Roll")
        doc, part = self.doc, self.part
        self.stages = [(None, 0.0)]
        s1 = sketch(doc, plane(part, "Top Plane"))
        rect(s1, 0, 0, 40, 30)
        app_part.add_to_part(part, s1)
        doc.recompute()
        f1 = extrude(doc, part, s1, Depth=10)
        self.stages.append((f1, total_volume(part)))
        # A sketch on the plate's top face, as Extrude does when a face is picked.
        top = face_at(f1, V(20, 15, 10), V(0, 0, 1))
        s2 = sketch(doc, (f1, top))
        circle(s2, 20, 15, 6)
        app_part.add_to_part(part, s2)
        doc.recompute()
        f2 = extrude(doc, part, s2, Depth=15)
        self.stages.append((f2, total_volume(part)))
        top2 = face_at(f2, V(20, 15, 25), V(0, 0, 1))
        s3 = sketch(doc, (f2, top2))
        circle(s3, 20, 15, 2)
        app_part.add_to_part(part, s3)
        doc.recompute()
        f3 = extrude(doc, part, s3, "Cut", Depth=20, Reverse=True)
        self.stages.append((f3, total_volume(part)))
        edge = None
        for i, e in enumerate(f3.Shape.Edges, 1):
            a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
            if abs(a.z) < 1e-6 and abs(b.z) < 1e-6 and abs(a.y) < 1e-6 and abs(b.y) < 1e-6:
                edge = "Edge%d" % i
        f4 = dressup.create_fillet(doc, part, [edge])
        f4.Radius = 2
        doc.recompute()
        self.stages.append((f4, total_volume(part)))
        self.sketches = [s1, s2, s3]
        self.feats = [f1, f2, f3, f4]
        self.attach = {s.Name: [(o.Name, list(subs)) for o, subs in s.AttachmentSupport]
                       for s in self.sketches}
        for f in self.feats:
            self.ok(f)

    def check_clean(self, where):
        for s in self.sketches:
            self.assertNotIn("Invalid", s.State, "%s: %s is broken" % (where, s.Label))
            self.assertEqual([(o.Name, list(subs)) for o, subs in s.AttachmentSupport],
                             self.attach[s.Name], "%s: %s re-attached" % (where, s.Label))
        for f in self.feats:
            if not f.RolledBack:
                self.assertEqual(f.ErrorMessage, "", "%s: %s" % (where, f.Label))

    def roll(self, feat):
        app_part.roll_to(self.part, feat)
        self.doc.recompute()

    def test_every_position_shows_that_stage(self):
        for feat, vol in self.stages:
            self.roll(feat)
            where = "bar after %s" % (feat.Label if feat else "nothing")
            self.check_clean(where)
            self.assertAlmostEqual(total_volume(self.part), vol, 3, where)
            n = 0 if feat is None else self.feats.index(feat) + 1
            self.assertEqual([f.RolledBack for f in self.feats],
                             [i >= n for i in range(len(self.feats))], where)

    def test_roll_forward_gives_back_the_model(self):
        final = total_volume(self.part)
        for order in ([None, self.feats[3]], [self.feats[0], self.feats[3]],
                      [None, self.feats[1], self.feats[0], self.feats[2], self.feats[3]]):
            for feat in order:
                self.roll(feat)
                self.check_clean("rolling")
            self.assertAlmostEqual(total_volume(self.part), final, 3)
            self.check_clean("at the end")

    def test_one_feature_back(self):
        final = total_volume(self.part)
        self.roll(self.feats[2])
        self.check_clean("one back")
        self.assertAlmostEqual(total_volume(self.part), self.stages[3][1], 3)
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        self.check_clean("forward")
        self.assertAlmostEqual(total_volume(self.part), final, 3)

    def test_edit_while_rolled_back_then_forward(self):
        """Changing a feature above the bar: rolling forward rebuilds the rest on it."""
        self.roll(self.feats[0])
        self.feats[0].Depth = 20
        self.doc.recompute()
        self.check_clean("edited above the bar")
        self.assertAlmostEqual(total_volume(self.part), 40 * 30 * 20, 3)
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        self.check_clean("forward after the edit")
        bb = self.part.Shape.BoundBox
        self.assertAlmostEqual(bb.ZMax, 35, 6)

    def test_bar_dropped_between_items(self):
        """FreeCAD's tree can drop the bar between two items (into the part's
        group): the bar goes there, and nothing else changes."""
        bar = app_part.rollback_bar(self.part)
        group = list(self.part.Group)
        f2 = self.feats[1]
        group.insert(group.index(f2) + 1, bar)
        self.part.Group = group
        self.doc.recompute()
        self.assertIs(self.part.Tip, f2)
        self.assertNotIn(bar, self.part.Group)
        self.check_clean("dropped")
        self.assertAlmostEqual(total_volume(self.part), self.stages[2][1], 3)
        group = list(self.part.Group)
        group.insert(0, bar)
        self.part.Group = group
        self.doc.recompute()
        self.assertIsNone(self.part.Tip)
        self.check_clean("dropped at the top")

    def test_undo_a_roll(self):
        final = total_volume(self.part)
        self.doc.UndoMode = 1
        self.doc.openTransaction("Roll")
        app_part.roll_to(self.part, None)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.doc.undo()
        self.doc.recompute()
        self.check_clean("undone")
        self.assertAlmostEqual(total_volume(self.part), final, 3)

    def test_save_and_reopen_rolled_back(self):
        import os
        import tempfile
        self.roll(self.feats[1])
        path = os.path.join(tempfile.mkdtemp(), "rolled.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        part = app_part.find_parts(self.doc)[0]
        feats = util.features(part)
        self.doc.recompute()
        self.assertEqual([f.RolledBack for f in feats], [False, False, True, True])
        app_part.roll_to_end(part)
        self.doc.recompute()
        for f in feats:
            self.assertEqual(f.ErrorMessage, "", f.Label)
        self.assertAlmostEqual(round(sum(b.shape.Volume for b in app_part.tip_bodies(part)), 4),
                               self.stages[4][1], 3)


if __name__ == "__main__":
    unittest.main()
