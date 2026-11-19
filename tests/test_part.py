# SPDX-License-Identifier: LGPL-2.1-or-later
"""app/: the Part, history, rollback bar, failure pass-through, body folders, files."""

import os
import tempfile
import unittest

import FreeCAD as App

from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import util
from helpers import circle, extrude, new_doc, plane, rect, sketch, volumes


class PartCase(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("PartT")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.boss = extrude(self.doc, self.part, sk, Depth=5)
        sk2 = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk2, 5, 5, 2)
        self.doc.recompute()
        self.cut = extrude(self.doc, self.part, sk2, "Cut", EndCondition="Through All")
        sk3 = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk3, 30, 0, 40, 10)
        self.doc.recompute()
        self.boss2 = extrude(self.doc, self.part, sk3, Depth=3)

    def tearDown(self):
        App.closeDocument(self.doc.Name)


class TestPart(PartCase):
    def test_structure(self):
        labels = [o.Label for o in self.part.Origin]
        self.assertEqual(labels[:4], ["Front Plane", "Top Plane", "Right Plane", "Origin"])
        # Front Plane = XZ, seen from FreeCAD's Front view: its normal is -Y.
        n = plane(self.part, "Front Plane").Placement.Rotation.multVec(App.Vector(0, 0, 1))
        self.assertAlmostEqual(n.y, -1.0)
        self.assertEqual([f.Label for f in util.features(self.part)],
                         ["Boss-Extrude1", "Cut-Extrude1", "Boss-Extrude2"])
        self.assertIs(self.cut.BaseFeature, self.boss)
        self.assertIs(self.part.Tip, self.boss2)
        self.assertEqual(len(self.part.BodyIds), 2)

    def test_folders(self):
        views = app_part.body_views(self.part)
        self.assertEqual(sorted(app_part.clean_label(v.Label) for v in views),
                         ["Boss-Extrude2", "Cut-Extrude1"])
        self.assertEqual(app_part.folder(self.part, "solid").Label, "Solid Bodies (2)")
        self.assertEqual(app_part.folder(self.part, "surface").Label, "Surface Bodies (0)")
        # The user renames a body: the name sticks through recomputes and new features.
        v = [v for v in views if app_part.clean_label(v.Label) == "Cut-Extrude1"][0]
        v.Label = "Plate"
        self.boss.Depth = 6
        self.doc.recompute()
        v = [x for x in app_part.body_views(self.part) if x.BodyId == v.BodyId][0]
        self.assertEqual(app_part.clean_label(v.Label), "Plate")

    def test_undo_is_not_a_rename(self):
        """Cancelling a panel restores body labels; that isn't the user renaming."""
        self.doc.UndoMode = 1
        self.doc.openTransaction("t")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 5, 5)
        self.doc.recompute()
        extrude(self.doc, self.part, sk, Depth=10)      # changes the first body's name
        self.doc.abortTransaction()
        self.doc.recompute()
        self.assertEqual(dict(self.part.BodyNames), {})
        self.boss.Depth = 6                              # the cut keeps changing that body
        self.doc.recompute()
        names = sorted(app_part.clean_label(v.Label) for v in app_part.body_views(self.part))
        self.assertEqual(names, ["Boss-Extrude2", "Cut-Extrude1"])

    def test_rollback(self):
        app_part.roll_to(self.part, self.boss)
        self.doc.recompute()
        self.assertEqual(len(self.part.BodyIds), 1)
        self.assertAlmostEqual(self.part.Shape.Volume, 1000.0)
        self.assertTrue(self.cut.RolledBack)
        # A new feature goes in at the rollback bar.
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 5, 5)
        self.doc.recompute()
        new = extrude(self.doc, self.part, sk, Depth=10)
        feats = util.features(self.part)
        self.assertEqual(feats.index(new), 1)
        self.assertIs(self.cut.BaseFeature, new)
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        self.assertFalse(self.cut.RolledBack)
        vols = sorted(volumes(self.part).values())
        self.assertAlmostEqual(vols[0], 300.0)

    def test_failure_passes_through(self):
        """SolidWorks: a failed feature keeps its error and passes its bodies on, so
        the features after it still compute."""
        self.cut.EndCondition = "Blind"
        self.cut.Depth = 0
        self.doc.recompute()
        self.assertIn("depth", self.cut.ErrorMessage.lower())
        self.assertAlmostEqual(self.cut.Shape.Volume, 1000.0)
        self.assertEqual(self.boss2.ErrorMessage, "")
        self.assertEqual(len(self.part.BodyIds), 2)
        self.cut.Depth = 2
        self.doc.recompute()
        self.assertEqual(self.cut.ErrorMessage, "")

    def test_suppress(self):
        self.cut.Suppressed = True
        self.doc.recompute()
        self.assertAlmostEqual(sum(volumes(self.part).values()), 1300.0)

    def test_delete_feature_relinks(self):
        self.doc.removeObject(self.cut.Name)
        self.doc.recompute()
        self.assertIs(self.boss2.BaseFeature, self.boss)
        self.assertAlmostEqual(sum(volumes(self.part).values()), 1300.0)

    def test_reorder(self):
        app_part.move_feature(self.part, self.boss2, 0)
        self.doc.recompute()
        self.assertEqual([f.Label for f in util.features(self.part)],
                         ["Boss-Extrude2", "Boss-Extrude1", "Cut-Extrude1"])
        self.assertIsNone(self.boss2.BaseFeature)
        self.assertAlmostEqual(sum(volumes(self.part).values()), 1300.0 - 3.14159265 * 4 * 5, 3)

    def test_save_reopen(self):
        path = os.path.join(tempfile.mkdtemp(), "part.FCStd")
        ids = list(self.part.BodyIds)
        vol = self.part.Shape.Volume
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        part = [o for o in self.doc.Objects if util.is_part(o)][0]
        for o in self.doc.Objects:
            o.touch()
        self.doc.recompute()
        self.assertEqual(list(part.BodyIds), ids)
        self.assertAlmostEqual(part.Shape.Volume, vol, 6)
        self.assertEqual([f.ErrorMessage for f in util.features(part)], ["", "", ""])
        self.assertEqual(part.Group[0].Label, "Front Plane")
