# SPDX-License-Identifier: LGPL-2.1-or-later
"""Draft: neutral plane, parting line, face propagation."""

import math
import unittest

import FreeCAD as App

from freecad.SolidDesign.app import dressup, part as app_part, refs
from freecad.SolidDesign.core.features import draft as core_draft
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch, volumes


def width_at(shape, z, axis="x"):
    """Section width of a shape at height z, along x (or y)."""
    wires = shape.slice(V(0, 0, 1), z)
    box = App.BoundBox()
    for w in wires:
        box.add(w.BoundBox)
    return box.XLength if axis == "x" else box.YLength


class TestDraft(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Dr")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=10)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def body(self):
        return list(app_part.tip_bodies(self.part))[0].shape

    def sides(self):
        return [face_at(self.box, V(10, 0, 5), V(0, -1, 0)),
                face_at(self.box, V(20, 5, 5), V(1, 0, 0)),
                face_at(self.box, V(10, 10, 5), V(0, 1, 0)),
                face_at(self.box, V(0, 5, 5), V(-1, 0, 0))]

    def neutral(self, faces, plane_sub=None, angle=3.0, **props):
        d = dressup.create_draft(self.doc, self.part, faces)
        bottom = plane_sub or face_at(self.box, V(10, 5, 0), V(0, 0, -1))
        refs.set_ref(d, "NeutralPlane", self.box, [bottom])
        d.Angle = angle
        for k, v in props.items():
            setattr(d, k, v)
        self.doc.recompute()
        return d

    def test_draftxpert_finds_the_faces_that_need_draft(self):
        d = self.neutral([], DraftType="DraftXpert")
        self.ok(d)
        s = self.body()
        top = 10 * 2 * math.tan(math.radians(3.0))
        self.assertAlmostEqual(width_at(s, 9.999), 20 - top, 2)
        self.assertAlmostEqual(width_at(s, 9.999, "y"), 10 - top, 2)
        a = core_draft.analysis(s, V(0, 0, 1), 3.0)
        self.assertEqual(a[core_draft.NEEDS], [])          # every wall drafted now
        d.Angle = 1.0
        self.doc.recompute()
        self.ok(d)

    def test_analysis(self):
        s = self.box.Shape
        a = core_draft.analysis(s, V(0, 0, 1), 1.0)
        self.assertEqual(len(a[core_draft.NEEDS]), 4)
        self.assertEqual(len(a[core_draft.POSITIVE]), 1)   # the top
        self.assertEqual(len(a[core_draft.NEGATIVE]), 1)   # the bottom

    def test_neutral_plane_at_the_base_tapers_upwards(self):
        d = self.neutral(self.sides())
        self.ok(d)
        self.assertEqual(d.Label, "Draft1")
        s = self.body()
        self.assertTrue(s.isValid())
        shrink = 2 * 10 * math.tan(math.radians(3))
        self.assertAlmostEqual(width_at(s, 0.001), 20, 2)
        self.assertAlmostEqual(width_at(s, 9.999), 20 - shrink, 2)
        self.assertLess(s.Volume, 2000)
        self.assertEqual(list(self.part.BodyIds), list(self.box.BodyIds))
        d.ReverseDirection = True
        self.doc.recompute()
        self.ok(d)
        self.assertAlmostEqual(width_at(self.body(), 9.999), 20 + shrink, 2)

    def test_neutral_plane_at_the_top_still_tapers_away_from_it(self):
        top = face_at(self.box, V(10, 5, 10), V(0, 0, 1))
        d = self.neutral(self.sides(), plane_sub=top)
        self.ok(d)
        s = self.body()
        shrink = 2 * 10 * math.tan(math.radians(3))
        self.assertAlmostEqual(width_at(s, 9.999), 20, 2)
        self.assertAlmostEqual(width_at(s, 0.001), 20 - shrink, 2)

    def test_datum_plane_through_the_middle(self):
        d = dressup.create_draft(self.doc, self.part, self.sides())
        mid = self.doc.addObject("Part::Feature", "Mid")
        import Part
        mid.Shape = Part.makePlane(100, 100, V(-50, -50, 5))
        refs.set_ref(d, "NeutralPlane", mid, ["Face1"])
        d.Angle = 2
        self.doc.recompute()
        self.ok(d)
        s = self.body()
        t = 5 * math.tan(math.radians(2))
        self.assertAlmostEqual(width_at(s, 5), 20, 3)
        lo, hi = width_at(s, 0.001), width_at(s, 9.999)
        self.assertAlmostEqual(abs(hi - lo), 4 * t, 2)

    def test_one_face_only(self):
        d = self.neutral(self.sides()[1:2])
        self.ok(d)
        s = self.body()
        self.assertAlmostEqual(width_at(s, 9.999), 20 - 10 * math.tan(math.radians(3)), 2)
        self.assertAlmostEqual(width_at(s, 9.999, "y"), 10, 4)

    def test_all_inner_outer_faces(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        circle(sk, 10, 5, 2)
        self.doc.recompute()
        hole = extrude(self.doc, self.part, sk, mode="Cut", EndCondition="Through All")
        self.ok(hole)
        bottom = face_at(hole, V(15, 5, 0), V(0, 0, -1))
        hole_face = face_at(hole, V(12, 5, 5))

        def run(prop, picks):
            d = dressup.create_draft(self.doc, self.part, picks)
            refs.set_ref(d, "NeutralPlane", hole, [bottom])
            d.Angle = 3
            d.FacePropagation = prop
            self.doc.recompute()
            self.ok(d)
            s = self.body()
            out = (width_at(s, 9.999), _hole_width(s, 9.999))
            app_part.remove_feature(self.part, d)
            self.doc.removeObject(d.Name)
            self.doc.recompute()
            return out

        shrink = 2 * 10 * math.tan(math.radians(3))
        outer_w, hole_w = run("Outer Faces", [])
        self.assertAlmostEqual(outer_w, 20 - shrink, 2)
        self.assertAlmostEqual(hole_w, 4, 3)
        outer_w, hole_w = run("Inner Faces", [hole_face])
        self.assertAlmostEqual(outer_w, 20, 3)
        self.assertAlmostEqual(hole_w, 4 + shrink, 2)     # a hole opens up along the pull
        outer_w, hole_w = run("All Faces", [])
        self.assertAlmostEqual(outer_w, 20 - shrink, 2)
        self.assertAlmostEqual(hole_w, 4 + shrink, 2)

    def test_parting_line(self):
        top_edges = []
        for i, e in enumerate(self.box.Shape.Edges, 1):
            if abs(e.BoundBox.ZMin - 10) < 1e-6 and abs(e.BoundBox.ZMax - 10) < 1e-6:
                top_edges.append("Edge%d" % i)
        self.assertEqual(len(top_edges), 4)
        d = dressup.create_draft(self.doc, self.part)
        d.DraftType = "Parting Line"
        refs.set_ref(d, "PartingLines", self.box, top_edges)
        d.Angle = 3
        self.doc.recompute()
        self.ok(d)
        s = self.body()
        shrink = 2 * 10 * math.tan(math.radians(3))
        # Parting line at the top, pulled down into the part: it narrows downwards.
        self.assertAlmostEqual(width_at(s, 9.999), 20, 2)
        self.assertAlmostEqual(width_at(s, 0.001), 20 - shrink, 2)
        d.OtherFace = True          # nothing but the top on the other side
        self.doc.recompute()
        self.assertIn("Other face", d.ErrorMessage)

    def test_non_planar_parting_line_is_refused(self):
        es = []
        for i, e in enumerate(self.box.Shape.Edges, 1):
            bb = e.BoundBox
            if abs(bb.ZMin - 10) < 1e-6 and abs(bb.ZMax - 10) < 1e-6 and bb.YLength > 1:
                es.append("Edge%d" % i)
                break
        for i, e in enumerate(self.box.Shape.Edges, 1):
            bb = e.BoundBox
            if abs(bb.ZMax) < 1e-6 and bb.XLength > 1 and abs(bb.YMin) < 1e-6:
                es.append("Edge%d" % i)
                break
        d = dressup.create_draft(self.doc, self.part)
        d.DraftType = "Parting Line"
        refs.set_ref(d, "PartingLines", self.box, es)
        self.doc.recompute()
        self.assertIn("one plane", d.ErrorMessage)
        self.assertEqual(volumes(self.part)[self.box.BodyIds[0]], 2000)

    def test_bad_angle_and_missing_input(self):
        d = self.neutral(self.sides(), angle=0)
        self.assertIn("angle", d.ErrorMessage)
        d.Angle = 3
        refs.set_ref(d, "NeutralPlane", None)
        self.doc.recompute()
        self.assertIn("neutral plane", d.ErrorMessage)

    def test_follows_an_upstream_edit(self):
        """The draft (and a fillet after it) keep working when the box grows."""
        d = self.neutral(self.sides())
        self.ok(d)
        top = face_at(d, V(10, 5, 10), V(0, 0, 1))
        f = dressup.create_fillet(self.doc, self.part, [top])
        f.Radius = 1
        self.doc.recompute()
        self.ok(f)
        v0 = volumes(self.part)
        self.box.Depth = 15
        self.doc.recompute()
        self.ok(d)
        self.ok(f)
        self.assertGreater(list(volumes(self.part).values())[0], list(v0.values())[0])

    def test_step_draft(self):
        """A plate with a boss: the plate's sides turn about its base, the boss's sides
        about the boss's base; the step between them stays."""
        doc, part = self.doc, self.part
        sk = sketch(doc, plane(part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        rect(sk, 5, 2, 15, 8)
        doc.recompute()
        boss = extrude(doc, part, sk, Depth=6)
        self.ok(boss)
        es = []
        for i, e in enumerate(boss.Shape.Edges, 1):
            bb = e.BoundBox
            flat = abs(bb.ZLength) < 1e-6
            if flat and abs(bb.ZMin) < 1e-6:
                es.append("Edge%d" % i)                  # the plate's base
            if flat and abs(bb.ZMin - 10) < 1e-6 and bb.XMin > 4.9 and bb.XMax < 15.1 and \
                    bb.YMin > 1.9 and bb.YMax < 8.1:
                es.append("Edge%d" % i)                  # the boss's base
        self.assertEqual(len(es), 8)
        d = dressup.create_draft(self.doc, self.part)
        d.DraftType = "Step Draft"
        refs.set_ref(d, "PartingLines", boss, es)
        d.Angle = 3
        top = face_at(boss, V(10, 5, 16), V(0, 0, 1))
        refs.set_ref(d, "PullDirection", boss, [top])
        self.doc.recompute()
        self.ok(d)
        s = self.body()
        t = math.tan(math.radians(3))
        self.assertAlmostEqual(width_at(s, 9.999), 20 - 2 * 10 * t, 2)    # plate top
        self.assertAlmostEqual(width_at(s, 15.999), 10 - 2 * 6 * t, 2)   # boss top
        self.assertAlmostEqual(width_at(s, 10.001), 10, 2)                # boss base

    def test_no_scratch_documents_left(self):
        before = set(App.listDocuments())
        self.neutral(self.sides())
        self.assertEqual(set(App.listDocuments()), before)
        self.assertIs(App.ActiveDocument, self.doc)


def _hole_width(shape, z):
    """Width of the inner (hole) wire of a section."""
    wires = shape.slice(V(0, 0, 1), z)
    inner = [w for w in wires if w.BoundBox.XLength < 15]
    return inner[0].BoundBox.XLength if inner else 0.0


if __name__ == "__main__":
    unittest.main()
