# SPDX-License-Identifier: LGPL-2.1-or-later
"""What's Wrong's engine: repaired and lost references are remembered with where
they were; a repair stays a warning until it is checked; problems that follow
from others nest under them; the feature that changed the model there is named;
broken sketches and troublesome geometry are found."""

import json
import unittest

import FreeCAD as App

from freecad.SolidDesign.app import dressup, health, refs
from helpers import V, extrude, new_doc, plane, rect, sketch


def edge_at(obj, p0, p1):
    for i, e in enumerate(obj.Shape.Edges, 1):
        a, b = e.Vertexes[0].Point, e.Vertexes[-1].Point
        if ((a - p0).Length < 1e-6 and (b - p1).Length < 1e-6) or \
                ((a - p1).Length < 1e-6 and (b - p0).Length < 1e-6):
            return "Edge%d" % i
    raise AssertionError((p0, p1))


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Health")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 40, 30)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=10)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def fillet_front_top(self):
        e = edge_at(self.box, V(0, 0, 10), V(40, 0, 10))
        f = dressup.create_fillet(self.doc, self.part, [e])
        f.Radius = 2
        self.doc.recompute()
        self.assertEqual(f.ErrorMessage, "")
        return f

    def lose_name(self, f, fp_change=None):
        """The edge's name goes stale (as after an upstream edit), its fingerprint
        stays (or is changed by ``fp_change``)."""
        target, _subs = f.Items
        if fp_change is not None:
            m = dict(f.RefFingerprints)
            fp = json.loads(m["Items"])
            fp_change(fp)
            m["Items"] = json.dumps(fp)
            f.RefFingerprints = m
        f.Items = (target, ["Edge999"])
        self.doc.recompute()


class TestRepairs(Case):
    def test_repair_is_remembered_and_stays_until_checked(self):
        f = self.fillet_front_top()
        self.lose_name(f)
        self.assertEqual(f.ErrorMessage, "")
        self.assertIn("repaired from its fingerprint", f.WarningMessage)
        r = refs.repairs(f)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["prop"], "Items")
        self.assertGreater(len(r[0]["old"]["pts"]), 2)      # where it was, drawable
        self.assertTrue(r[0]["new"]["pts"])
        # Rebuilt again: the reference resolves cleanly now, but it hasn't been checked.
        f.touch()
        self.doc.recompute()
        self.assertIn("repaired", f.WarningMessage)
        refs.accept_repairs(f)
        f.touch()
        self.doc.recompute()
        self.assertEqual(f.WarningMessage, "")

    def test_picking_it_again_counts_as_checked(self):
        f = self.fillet_front_top()
        self.lose_name(f)
        refs.set_ref(f, "Items", f.BaseFeature, [edge_at(self.box, V(0, 0, 10),
                                                         V(40, 0, 10))])
        self.doc.recompute()
        self.assertEqual(refs.repairs(f), [])
        self.assertEqual(f.WarningMessage, "")

    def test_lost_reference_keeps_where_it_was(self):
        f = self.fillet_front_top()
        self.lose_name(f, lambda fp: fp.update(type="Part::GeomBSplineCurve"))
        self.assertIn("no longer exists", f.ErrorMessage)
        lost = refs.lost(f)
        self.assertEqual(len(lost), 1)
        self.assertTrue(lost[0]["old"]["pts"])
        # Fixed: forgotten at the next recompute.
        refs.set_ref(f, "Items", f.BaseFeature, [edge_at(self.box, V(0, 0, 10),
                                                         V(40, 0, 10))])
        self.doc.recompute()
        self.assertEqual((f.ErrorMessage, refs.lost(f)), ("", []))


class TestIssues(Case):
    def test_repair_issue_says_what_to_do(self):
        f = self.fillet_front_top()
        self.lose_name(f)
        items = health.issues(self.doc)
        self.assertEqual([i.obj for i in items], [f])
        i = items[0]
        self.assertFalse(i.is_error())
        self.assertTrue(i.repaired and "Looks Right" in i.hint)
        self.assertEqual(health.counts(self.doc), (0, 1))

    def test_the_feature_that_changed_it_is_named(self):
        """A cut takes away the corner the fillet's edge was on: the lost edge's
        culprit is the cut."""
        e = edge_at(self.box, V(0, 0, 10), V(40, 0, 10))
        csk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(csk, -1, -1, 41, 5)
        self.doc.recompute()
        cut = extrude(self.doc, self.part, csk, "Cut", Depth=20, Reverse=False,
                      EndCondition="Through All")
        self.assertEqual(cut.ErrorMessage, "")
        f = dressup.create_fillet(self.doc, self.part, [])
        # The fillet was picked on the box's edge, before the cut took it away.
        refs.set_ref(f, "Items", self.box, [e])
        f.Radius = 1
        self.doc.recompute()
        self.assertTrue(f.ErrorMessage, "the edge is gone")
        items = health.flat(health.issues(self.doc))
        i = [x for x in items if x.obj is f][0]
        self.assertTrue(i.lost)
        self.assertIs(i.culprit, cut)
        self.assertIn(cut.Label, i.why)

    def test_a_lost_reference_after_an_error_nests_under_it(self):
        bad = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(bad, 5, 5, 10, 10)
        self.doc.recompute()
        cut = extrude(self.doc, self.part, bad, "Cut", Depth=0)
        self.assertTrue(cut.ErrorMessage)
        f = self.fillet_front_top()
        self.lose_name(f, lambda fp: fp.update(type="Part::GeomBSplineCurve"))
        top = health.issues(self.doc)
        self.assertEqual([i.obj for i in top], [cut])
        self.assertEqual([c.obj for c in top[0].children], [f])
        self.assertIn(cut.Label, top[0].children[0].why)
        self.assertEqual(health.counts(self.doc), (2, 0))

    def test_a_broken_sketch(self):
        sk = sketch(self.doc, (self.box, "Face99"))
        rect(sk, 1, 1, 5, 5)
        self.doc.recompute()
        from freecad.SolidDesign.app import part as app_part
        app_part.add_to_part(self.part, sk)
        self.doc.recompute()
        items = [i for i in health.flat(health.issues(self.doc)) if i.obj is sk]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "sketch")
        self.assertIn("attachment", items[0].hint)


class TestGeometryCheck(Case):
    def test_clean_body(self):
        self.assertEqual(health.check_geometry(self.doc), [])

    def test_tiny_edges_and_slivers(self):
        """A boss 0.005 mm wider than the block: a sliver face and tiny edges."""
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 40.005, 20)
        self.doc.recompute()
        boss = extrude(self.doc, self.part, sk, Depth=10)
        self.assertEqual(boss.ErrorMessage, "")
        found = health.check_geometry(self.doc)
        kinds = sorted(i.message.split(" (")[0] for i in found)
        self.assertTrue(any("tiny edge" in k for k in kinds), kinds)
        self.assertTrue(any("sliver" in k for k in kinds), kinds)
        tiny = [i for i in found if "tiny" in i.message][0]
        self.assertTrue(tiny.elements and tiny.culprit is boss)
