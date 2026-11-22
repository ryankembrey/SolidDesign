# SPDX-License-Identifier: LGPL-2.1-or-later
"""Speed: how much is recomputed for each change (app/part.py), the tracing
(app/perf.py), and that faster code gives the same results as before."""

import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.app import dressup, perf, util
from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.core.features import edges as core_edges
from helpers import V, circle, extrude, new_doc, plane, rect, sketch


def build(doc, part):
    """A plate, three bosses, a cut, a fillet and a chamfer: seven features."""
    sk = sketch(doc, plane(part, "Top Plane"))
    rect(sk, 0, 0, 60, 40)
    doc.recompute()
    extrude(doc, part, sk, Depth=10)
    for x, y in ((10, 10), (30, 10), (50, 10)):
        s = sketch(doc, plane(part, "Top Plane"),
                   attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        circle(s, x, y, 4)
        doc.recompute()
        extrude(doc, part, s, Depth=6)
    s = sketch(doc, plane(part, "Top Plane"),
               attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
    circle(s, 30, 30, 3)
    doc.recompute()
    extrude(doc, part, s, mode="Cut", Depth=5, Reverse=True)
    last = util.features(part)[-1]
    edges = ["Edge%d" % i for i, e in enumerate(last.Shape.Edges, 1)
             if abs(e.CenterOfMass.z) < 1e-6][:4]
    fi = dressup.create_fillet(doc, part, edges)
    fi.Radius = 1
    doc.recompute()
    edges = ["Edge%d" % i for i, e in enumerate(fi.Shape.Edges, 1)
             if abs(e.CenterOfMass.z - 16) < 1e-6][:3]
    ch = dressup.create_chamfer(doc, part, edges)
    ch.Distance = 0.5
    doc.recompute()


class Counting(object):
    """The features executed inside the block, in order (from the trace: FreeCAD
    keeps the execute it found when each feature was made, so it can't be
    patched afterwards)."""

    def __enter__(self):
        self.names = []
        perf.start()
        return self

    def __exit__(self, *a):
        def walk(spans):
            for sp in spans:
                if sp.name == "feature":
                    yield sp
                for c in walk(sp.children):
                    yield c
        found = sorted(walk(perf._done), key=lambda sp: sp.t0)
        counts = perf.stats()[1]
        by_label = {}
        for (kind, key), _n in counts.items():
            if kind == "features recomputed":
                label, _s, name = key.rpartition(" [")
                by_label[label] = name.rstrip("]")
        for sp in found:
            label = sp.detail.rpartition(" (")[0]
            self.names.append(by_label.get(label, label))
        perf.stop()


class TestRecomputes(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Perf")
        build(self.doc, self.part)
        self.feats = util.features(self.part)
        self.assertEqual(len(self.feats), 7)
        self.assertTrue(all(not f.ErrorMessage for f in self.feats))

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def volume(self):
        return round(sum(b.shape.Volume for b in app_part.tip_bodies(self.part)), 6)

    def test_a_new_feature_rebuilds_only_itself(self):
        from freecad.SolidDesign.app import deform
        with Counting() as c:
            s = deform.create_scale(self.doc, self.part)
            self.doc.recompute()
        self.assertEqual(c.names, [s.Name])         # it was every feature before

    def test_nothing_changed_nothing_rebuilt(self):
        with Counting() as c:
            self.doc.recompute()
        self.assertEqual(c.names, [])

    def test_a_change_rebuilds_from_there_on(self):
        v0 = self.volume()
        with Counting() as c:
            self.feats[4].Depth = 4
            self.doc.recompute()
        self.assertEqual(c.names, [f.Name for f in self.feats[4:]])
        self.assertNotEqual(self.volume(), v0)

    def test_rolling_back_and_forward(self):
        v_end = self.volume()
        with Counting() as c:
            app_part.roll_to(self.part, self.feats[2])
            self.doc.recompute()
        # Those going below the bar only note it; they keep their results.
        self.assertEqual(sorted(c.names), sorted(f.Name for f in self.feats[3:]))
        self.assertTrue(all(f.RolledBack for f in self.feats[3:]))
        v_rolled = self.volume()
        # A change made while rolled back is picked up on the way forward.
        self.feats[0].Depth = 12
        self.doc.recompute()
        with Counting() as c:
            app_part.roll_to_end(self.part)
            self.doc.recompute()
        self.assertEqual(c.names, [f.Name for f in self.feats[3:]])
        self.assertFalse(any(f.RolledBack for f in self.feats))
        self.assertNotEqual(self.volume(), v_end)           # the deeper plate shows
        self.assertNotEqual(v_rolled, v_end)

    def test_same_results_as_rebuilding_everything(self):
        """Rebuilding only what changed gives what rebuilding every feature does."""
        self.feats[0].Depth = 12
        self.feats[5].Radius = 1.5
        app_part.roll_to(self.part, self.feats[3])
        self.doc.recompute()
        app_part.roll_to_end(self.part)
        self.doc.recompute()
        v = self.volume()
        n = len(self.part.Shape.Faces)
        for f in self.feats:
            f.touch()
        self.doc.recompute()
        self.assertEqual(self.volume(), v)
        self.assertEqual(len(self.part.Shape.Faces), n)

    def test_a_feature_moved_in_the_history(self):
        with Counting() as c:
            app_part.move_feature(self.part, self.feats[3], 1)
            self.doc.recompute()
        moved = util.features(self.part)
        self.assertEqual(moved[1], self.feats[3])
        # The first feature is before everything that moved: left alone.
        self.assertNotIn(self.feats[0].Name, c.names)
        self.assertTrue(all(not f.ErrorMessage for f in moved))


def _tangent_chain_reference(shape, edges, tol=1e-6):
    """tangent_chain as it was: every edge of the shape for every vertex."""
    out = list(edges)
    todo = list(edges)
    while todo:
        e = todo.pop()
        for v in e.Vertexes:
            t0 = core_edges._tangent_at(e, v)
            for f in shape.Edges:
                if any(f.isSame(x) for x in out):
                    continue
                if not any(fv.isSame(v) for fv in f.Vertexes):
                    continue
                t1 = core_edges._tangent_at(f, v)
                if abs(abs(t0.dot(t1)) - 1.0) < tol:
                    out.append(f)
                    todo.append(f)
    return out


class TestSameAnswers(unittest.TestCase):
    def shapes(self):
        box = Part.makeBox(20, 10, 5)
        filleted = box.makeFillet(2, [box.Edges[i] for i in (0, 2, 4, 6)])
        slot = Part.makeBox(30, 10, 5).fuse(Part.makeCylinder(5, 5, V(30, 5, 0))).fuse(
            Part.makeCylinder(5, 5, V(0, 5, 0))).removeSplitter()
        return [box, filleted, slot]

    def test_tangent_chain(self):
        for shape in self.shapes():
            for i in range(len(shape.Edges)):
                start = [shape.Edges[i]]
                new = core_edges.tangent_chain(shape, start)
                old = _tangent_chain_reference(shape, start)
                self.assertEqual(len(new), len(old))
                self.assertTrue(all(a.isSame(b) for a, b in zip(new, old)), i)

    def test_scale_centre_of_one_solid(self):
        from freecad.SolidDesign.core.features import deform
        box = Part.makeBox(10, 20, 30)
        self.assertTrue((deform.mass_centre(box) - box.CenterOfMass).Length < 1e-12)


class TestTracing(unittest.TestCase):
    def tearDown(self):
        if perf.enabled():
            perf.stop()

    def test_off_costs_nothing_and_records_nothing(self):
        perf.reset()
        self.assertFalse(perf.enabled())
        with perf.span("x"):
            pass
        perf.count("y")
        self.assertEqual(perf.stats(), ({}, {}))

    def test_spans_counts_and_report(self):
        perf.start()
        with perf.span("outer", "one"):
            with perf.span("inner"):
                pass
            with perf.span("inner"):
                pass
        perf.count("features recomputed", "Fillet1")

        @perf.traced("deco", lambda a: a)
        def f(a):
            return a * 2
        self.assertEqual(f(3), 6)
        totals, counts = perf.stats()
        self.assertEqual(totals["outer"][0], 1)
        self.assertEqual(totals["inner"][0], 2)
        self.assertEqual(totals["deco"][0], 1)
        self.assertEqual(counts[("features recomputed", "Fillet1")], 1)
        text = perf.stop()
        self.assertIn("outer one", text)
        self.assertIn("inner", text)
        self.assertIn("features recomputed", text)
        with open(perf.report_path(), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)

    def test_a_recompute_is_traced(self):
        doc, part = new_doc("PerfTrace")
        try:
            perf.start()
            sk = sketch(doc, plane(part, "Top Plane"))
            rect(sk, 0, 0, 10, 10)
            doc.recompute()
            extrude(doc, part, sk, Depth=5)
            totals, counts = perf.stats()
            self.assertIn("document.recompute", totals)
            self.assertIn("feature", totals)
            self.assertTrue(any(k[0] == "features recomputed" for k in counts))
            self.assertIn("document.recompute", perf.stop())
        finally:
            App.closeDocument(doc.Name)


if __name__ == "__main__":
    unittest.main()
