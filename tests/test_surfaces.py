# SPDX-License-Identifier: LGPL-2.1-or-later
"""Knit, Planar, Filled, Trim, Extend; Delete Face; Thicken."""

import unittest

import FreeCAD as App

from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import refgeom, surfaces
from freecad.SolidDesign.core import refgeom as core_ref
from helpers import V, circle, extrude, face_at, new_doc, plane, rect, sketch


def edges_at(obj, z):
    """Names of the edges of ``obj`` lying at height ``z``."""
    return ["Edge%d" % i for i, e in enumerate(obj.Shape.Edges, 1)
            if abs(e.BoundBox.ZMin - z) < 1e-6 and abs(e.BoundBox.ZMax - z) < 1e-6]


class Case(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Srf")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        self.box = extrude(self.doc, self.part, sk, Depth=10)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def ok(self, f):
        self.assertEqual(f.ErrorMessage, "", f.ErrorMessage)

    def bodies(self):
        return list(app_part.tip_bodies(self.part))

    def top(self):
        return face_at(self.box, V(5, 5, 10), V(0, 0, 1))


class TestDeleteFace(Case):
    def test_delete_makes_a_surface_then_fill_closes_it(self):
        d = surfaces.create_delete_face(self.doc, self.part, Items=[self.top()])
        self.doc.recompute()
        self.ok(d)
        self.assertEqual(d.Label, "DeleteFace1")
        b = self.bodies()
        self.assertEqual([x.kind for x in b], ["surface"])
        self.assertAlmostEqual(b[0].shape.Area, 2 * 200 + 2 * 100 + 200, 6)
        f = surfaces.create_filled(self.doc, self.part, Items=edges_at(d, 10))
        f.CreateSolid = True
        self.doc.recompute()
        self.ok(f)
        self.assertEqual(f.Label, "Surface-Fill1")
        b = self.bodies()
        self.assertEqual([x.kind for x in b], ["solid"])
        self.assertAlmostEqual(b[0].shape.Volume, 2000, 3)
        f.MergeResult = False
        self.doc.recompute()
        self.assertEqual(sorted(x.kind for x in self.bodies()), ["surface", "surface"])

    def test_delete_and_fill(self):
        d = surfaces.create_delete_face(self.doc, self.part, Items=[self.top()],
                                        DeleteType="Delete and Fill")
        self.doc.recompute()
        self.ok(d)
        b = self.bodies()
        self.assertEqual(b[0].kind, "solid")
        self.assertAlmostEqual(b[0].shape.Volume, 2000, 3)

    def test_delete_and_patch_removes_a_boss(self):
        bs = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        circle(bs, 10, 5, 2)
        self.doc.recompute()
        boss = extrude(self.doc, self.part, bs, Depth=4)
        self.assertAlmostEqual(self.bodies()[0].shape.Volume, 2000 + 3.14159265 * 16, 3)
        faces = [face_at(boss, V(12, 5, 12)), face_at(boss, V(10, 5, 14))]
        d = surfaces.create_delete_face(self.doc, self.part, Items=faces,
                                        DeleteType="Delete and Patch")
        self.doc.recompute()
        self.ok(d)
        b = self.bodies()
        self.assertEqual(b[0].kind, "solid")
        self.assertAlmostEqual(b[0].shape.Volume, 2000, 3)
        self.assertEqual(len(b[0].shape.Faces), 6)


class TestSurfaces(Case):
    def open_box(self):
        d = surfaces.create_delete_face(self.doc, self.part, Items=[self.top()])
        self.doc.recompute()
        self.ok(d)
        return d

    def test_planar_then_knit_into_a_solid(self):
        d = self.open_box()
        pl = surfaces.create_planar(self.doc, self.part, Items=edges_at(d, 10))
        self.doc.recompute()
        self.ok(pl)
        self.assertEqual(pl.Label, "Surface-Plane1")
        ids = [b.id for b in self.bodies()]
        self.assertEqual(len(ids), 2)
        k = surfaces.create_knit(self.doc, self.part, Bodies=ids, CreateSolid=True)
        self.doc.recompute()
        self.ok(k)
        b = self.bodies()
        self.assertEqual([x.kind for x in b], ["solid"])
        self.assertAlmostEqual(b[0].shape.Volume, 2000, 3)
        self.assertEqual(b[0].id, ids[0])

    def test_planar_from_a_sketch(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 30), App.Rotation()))
        rect(sk, 0, 0, 4, 5)
        circle(sk, 2, 2.5, 1)
        self.doc.recompute()
        pl = surfaces.create_planar(self.doc, self.part, Sketch=sk)
        self.doc.recompute()
        self.ok(pl)
        s = [b for b in self.bodies() if b.kind == "surface"][0]
        self.assertAlmostEqual(s.shape.Area, 20 - 3.14159265, 5)

    def flat(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 30), App.Rotation()))
        rect(sk, 0, 0, 20, 10)
        self.doc.recompute()
        pl = surfaces.create_planar(self.doc, self.part, Sketch=sk)
        self.doc.recompute()
        self.ok(pl)
        return pl, [b.id for b in self.bodies() if b.kind == "surface"][0]

    def test_trim_keep_and_remove(self):
        pl, sid = self.flat()
        cut = refgeom.create_plane(self.doc, self.part, core_ref.OFFSET,
                                   [(plane(self.part, "Right Plane"), "")])
        cut.Distance = 5
        self.doc.recompute()
        t = surfaces.create_trim(self.doc, self.part, TrimTools=[cut],
                                 PickedPoints=[surfaces.vec_text(V(2, 5, 30))])
        self.doc.recompute()
        self.ok(t)
        self.assertEqual(t.Label, "Surface-Trim1")
        s = [b for b in self.bodies() if b.id == sid][0]
        self.assertAlmostEqual(s.shape.Area, 50, 6)
        t.KeepSelections = False
        self.doc.recompute()
        self.ok(t)
        s = [b for b in self.bodies() if b.id == sid][0]
        self.assertAlmostEqual(s.shape.Area, 150, 6)
        self.assertGreater(s.shape.BoundBox.XMin, 4.99)
        t.PickedPoints = []
        self.doc.recompute()
        self.assertIn("Click the pieces", t.ErrorMessage)

    def test_extend_and_thicken(self):
        pl, sid = self.flat()
        e = [n for n in edges_at(pl, 30)
             if abs(pl.Shape.getElement(n).CenterOfMass.x - 20) < 1e-6][0]
        x = surfaces.create_extend(self.doc, self.part, Items=[e], Distance=5)
        self.doc.recompute()
        self.ok(x)
        s = [b for b in self.bodies() if b.id == sid][0]
        self.assertAlmostEqual(s.shape.Area, 250, 6)
        self.assertAlmostEqual(s.shape.BoundBox.XMax, 25, 6)
        t = surfaces.create_thicken(self.doc, self.part, Body=sid, Thickness=2)
        self.doc.recompute()
        self.ok(t)
        self.assertEqual(t.Label, "Thicken1")
        kinds = sorted(b.kind for b in self.bodies())
        self.assertEqual(kinds, ["solid", "solid"])            # the surface is used up
        vols = sorted(round(b.shape.Volume, 3) for b in self.bodies())
        self.assertEqual(vols, [500.0, 2000.0])
        t.ThickenSide = "Both Sides"
        self.doc.recompute()
        self.ok(t)
        thick = [b for b in self.bodies() if abs(b.shape.Volume - 500) < 1e-3][0]
        self.assertAlmostEqual(thick.shape.BoundBox.ZMin, 29, 6)

    def test_thickened_cut(self):
        sk = sketch(self.doc, plane(self.part, "Top Plane"),
                    attach_offset=App.Placement(V(0, 0, 5), App.Rotation()))
        rect(sk, -5, -5, 30, 20)
        self.doc.recompute()
        pl = surfaces.create_planar(self.doc, self.part, Sketch=sk)
        self.doc.recompute()
        sid = [b.id for b in self.bodies() if b.kind == "surface"][0]
        t = surfaces.create_thicken(self.doc, self.part, Body=sid, Thickness=2, Mode="Cut")
        self.doc.recompute()
        self.ok(t)
        self.assertEqual(t.Label, "Thicken-Cut1")
        vols = sorted(round(b.shape.Volume, 3) for b in self.bodies())
        self.assertEqual(vols, [600.0, 1000.0])                # split in two by the slab
        t.Mode = "Add"
        self.doc.recompute()
        self.assertEqual(t.Label, "Thicken1")
        _ = pl
