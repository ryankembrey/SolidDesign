# SPDX-License-Identifier: LGPL-2.1-or-later
"""core/: tagged TopoShape layer, body IDs, sketch regions."""

import unittest

import FreeCAD as App
import Part

from freecad.SolidDesign.core import bodies, regions, topo
from helpers import V, circle, new_doc, plane, rect, sketch


class TestTopo(unittest.TestCase):
    def setUp(self):
        del topo.map_warnings[:]

    def test_mapped_ops(self):
        """Every op the features rely on produces an element map from tagged inputs."""
        b = Part.makeBox(10, 10, 10)
        c = Part.makeCylinder(2, 30, V(5, 5, -5))
        self.assertGreater(topo.cut(b, [c], 7).ElementMapSize, 0)
        self.assertGreater(topo.fuse(b, [Part.makeBox(5, 5, 5, V(10, 0, 0))], 7).ElementMapSize, 0)
        self.assertGreater(topo.common(b, [c], 7).ElementMapSize, 0)
        f = Part.Face(Part.Wire(Part.makePolygon([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 0, 0)])))
        self.assertGreater(topo.extrude(f, V(0, 0, 2), 7).ElementMapSize, 0)
        self.assertGreater(topo.compound([b, c], 7).ElementMapSize, 0)
        sl = topo.slice_by(b, [Part.makePlane(30, 30, V(-5, -5, 3))], 7)
        self.assertEqual(len(sl.Solids), 2)
        self.assertGreater(sl.ElementMapSize, 0)
        self.assertEqual(topo.map_warnings, [])

    def test_move_keeps_map(self):
        """FreeCAD 1.1.3: moving a mapped shape keeps its element map (checked here
        so Move/Copy Body can rely on it)."""
        r = topo.cut(Part.makeBox(10, 10, 10), [Part.makeCylinder(2, 30, V(5, 5, -5))], 3)
        m = topo.transformed(r, App.Placement(V(5, 0, 0), App.Rotation(V(0, 0, 1), 30)), 3)
        self.assertEqual(m.ElementMapSize, r.ElementMapSize)
        self.assertEqual(m.getElementMappedName("Face1"), r.getElementMappedName("Face1"))

    def test_occ_error_is_plain(self):
        with self.assertRaises(topo.GeometryError):
            topo.extrude(Part.Face(Part.Wire(Part.makeCircle(1))), V(0, 0, 0), 3)


class TestBodyIds(unittest.TestCase):
    def test_new_ids_stable(self):
        """IDs of new bodies are kept across recomputes, even if shapes reorder."""
        a = Part.makeBox(1, 1, 1)
        b = Part.makeBox(1, 1, 1, V(10, 0, 0))
        al = bodies.IdAllocator("F")
        ids = al.take([a, b])
        self.assertEqual(ids, ["F:1", "F:2"])
        al2 = bodies.IdAllocator("F", bodies.IdAllocator.loads(al.dumps()))
        # Same bodies, other order, slightly moved: same IDs.
        b2 = Part.makeBox(1, 1, 1, V(10.5, 0, 0))
        self.assertEqual(al2.take([b2, a]), ["F:2", "F:1"])

    def test_split_largest_keeps(self):
        """SolidWorks keeps the body's ID on the largest piece of a split."""
        small = Part.makeBox(1, 1, 1)
        large = Part.makeBox(3, 1, 1, V(5, 0, 0))
        out = bodies.split_pieces("B", [small, large], bodies.IdAllocator("F"))
        self.assertEqual(out[0][0], "B")
        self.assertAlmostEqual(out[0][1].Volume, 3.0)
        self.assertEqual(out[1][0], "B:1")

    def test_overlap(self):
        a = Part.makeBox(2, 2, 2)
        b = Part.makeBox(2, 2, 2, V(5, 0, 0))
        r1 = Part.makeBox(2, 2, 2, V(5.5, 0, 0))
        r2 = Part.makeBox(2, 2, 2, V(0.2, 0, 0))
        out = bodies.assign_by_overlap([("A", a), ("B", b)], [r1, r2], bodies.IdAllocator("F"))
        self.assertEqual([i for i, _ in out], ["B", "A"])


class TestRegions(unittest.TestCase):
    def setUp(self):
        self.doc, self.part = new_doc("Regions")
        self.sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(self.sk, 0, 0, 10, 10)
        self.inner = circle(self.sk, 5, 5, 2)
        self.over = circle(self.sk, 10, 5, 3)
        import Sketcher
        self.cx = self.sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, self.over, 3, 10.0))
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def test_arrangement(self):
        regs = regions.regions(self.sk)
        self.assertEqual(len(regs), 4)
        areas = sorted(round(r.face.Area, 2) for r in regs)
        self.assertEqual(areas, sorted([12.57, 14.14, 14.14, round(100 - 12.566 - 14.137, 2)]))
        # Every region is bounded by sketch geometry IDs, never by index.
        gid_inner = self.sk.getGeometryId(self.inner) if hasattr(self.sk, "getGeometryId") else None
        disk = [r for r in regs if abs(r.face.Area - 12.566) < 0.01][0]
        if gid_inner is not None:
            self.assertEqual(disk.geo_ids, frozenset([gid_inner]))

    def test_resolve_survives_edits(self):
        """A stored region is found again after unrelated geometry is added and the
        sketch is changed (spec section 7)."""
        regs = regions.regions(self.sk)
        lens = [r for r in regs if abs(r.face.Area - 14.137) < 0.01
                and r.face.CenterOfMass.x < 10][0]
        key = lens.key()
        circle(self.sk, 30, 30, 1)          # unrelated region, changes region order
        self.sk.setDatum(self.cx, App.Units.Quantity("10.5 mm"))   # move the overlapping circle
        self.doc.recompute()
        faces, repaired = regions.resolve([key], self.sk)
        self.assertEqual(len(faces), 1)
        self.assertLess(faces[0].CenterOfMass.x, 10.0)
        self.assertEqual(repaired, [])

    def test_default_profile_rules(self):
        with self.assertRaises(topo.GeometryError):
            regions.default_profile(self.sk, 5)     # overlapping circle
        self.sk.delGeometry(self.over)
        self.doc.recompute()
        faces, open_ = regions.default_profile(self.sk, 5)
        self.assertEqual(len(faces.Faces), 1)
        self.assertAlmostEqual(faces.Faces[0].Area, 100 - 12.566370614, 4)
        self.assertEqual(open_, [])
