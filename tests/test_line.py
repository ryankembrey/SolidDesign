# SPDX-License-Identifier: LGPL-2.1-or-later
"""The command line's grammar, without a view: what sel= picks (gui/line_select.py),
the line's own commands (gui/line_ex.py), completion (gui/line_complete.py) and
the cheat sheet (gui/line_help.py)."""

import unittest

import FreeCAD as App

from freecad.SolidDesign.app import part as app_part
from freecad.SolidDesign.app import refs
from freecad.SolidDesign.core.features import edges as core_edges
from freecad.SolidDesign.gui import command_line as cl
from freecad.SolidDesign.gui import line_complete, line_ex, line_help, line_select, line_store

from helpers import V, circle, extrude, new_doc, plane, rect, sketch

LISTING = [("SD_Fillet", "fillet", "Fillet", ""), ("SD_Extrude", "extrude", "Extrude", ""),
           ("SD_Chamfer", "chamfer", "Chamfer", "")]
EXTRUDE = {"Depth": ("num", None), "Depth2": ("num", None), "Reverse": ("bool", None),
           "Mode": ("enum", ["Add", "Cut", "Surface"])}


class _Model(unittest.TestCase):
    """A 40 x 30 x 10 plate with a round boss (r 4, 5 high) on top."""

    def setUp(self):
        self.doc, self.part = new_doc("Ln")
        sk = sketch(self.doc, plane(self.part, "Top Plane"))
        rect(sk, 0, 0, 40, 30)
        self.doc.recompute()
        self.plate = extrude(self.doc, self.part, sk, Depth=10)
        sk2 = sketch(self.doc, plane(self.part, "Top Plane"),
                     attach_offset=App.Placement(V(0, 0, 10), App.Rotation()))
        circle(sk2, 20, 15, 4)
        self.doc.recompute()
        self.boss = extrude(self.doc, self.part, sk2, Depth=5)
        self.views = app_part.body_views(self.part)
        # Headless there are no view providers to say what's shown: all of it.
        self._saved = (line_select.bodies, cl.tools, cl.command_for)
        line_select.bodies = lambda doc: self.views
        cl.tools = lambda: LISTING
        cl.command_for = lambda obj: "SD_Extrude"

    def tearDown(self):
        line_select.bodies, cl.tools, cl.command_for = self._saved
        App.closeDocument(self.doc.Name)

    def pick(self, text, codes=None):
        ctx = line_select.Context(self.doc, None, codes or {}, kinds=("Face", "Edge"))
        keys, problems = line_select.resolve(text.split(","), ctx)
        return keys, problems

    def els(self, text, codes=None):
        keys, problems = self.pick(text, codes)
        self.assertEqual(problems, [], text)
        body = self.views[0].Shape
        return [body.getElement(k[2]) for k in keys]


class TestSources(_Model):
    def test_new_is_what_the_boss_made(self):
        els = self.els("new")
        self.assertTrue(els)
        self.assertTrue(all(e.BoundBox.ZMax >= 10 - 1e-6 for e in els))

    def test_last_faces(self):
        top = self.els("last.top")
        self.assertEqual(len(top), 1)
        self.assertAlmostEqual(top[0].CenterOfMass.z, 15, 6)
        self.assertEqual(len(self.els("last.caps")), 2)
        sides = self.els("last.sides")
        self.assertEqual([type(f.Surface).__name__ for f in sides], ["Cylinder"])

    def test_everything_and_kinds(self):
        body = self.views[0].Shape
        self.assertEqual(len(self.els("edges")), len(body.Edges))
        self.assertEqual(len(self.els("faces")), len(body.Faces))
        self.assertEqual(len(self.els("*")), len(body.Faces) + len(body.Edges))

    def test_a_label_and_its_edges(self):
        k = self.pick("last.top")[0][0]
        els = self.els("jk:edges", {"jk": k})
        self.assertEqual(len(els), 1)
        self.assertEqual(type(els[0].Curve).__name__, "Circle")
        self.assertEqual(self.pick("jj")[1], ['No label "jj" in view.'])
        self.assertEqual(self.pick("zz")[1], ['No label or name "zz".'])


class TestNames(_Model):
    def test_origin_planes(self):
        for word, label in (("front", "Front Plane"), ("top", "Top Plane"),
                            ("right", "Right Plane")):
            keys = self.pick(word)[0]
            self.assertEqual(len(keys), 1)
            obj = self.doc.getObject(keys[0][1])
            self.assertEqual(app_part.clean_label(obj.Label), label)
            self.assertEqual(keys[0][2], "")

    def test_by_name(self):
        k = self.pick("FrontPlane")[0]
        self.assertEqual(k, self.pick("front")[0])
        self.assertEqual(self.pick("front plane".replace(" ", ""))[0], k)
        body = self.views[0]
        # A body is named after its last feature: the name means the body.
        self.assertEqual(self.pick("Boss-Extrude2")[0], [(self.doc.Name, body.Name, "")])
        self.assertEqual(self.pick("Sketch")[0][0][1], "Sketch")
        name = line_select.token_name(body)
        self.assertEqual(self.pick(name + ".Edge3")[0], [(self.doc.Name, body.Name, "Edge3")])
        self.assertEqual(self.pick(name + ".edge3")[0], [(self.doc.Name, body.Name, "Edge3")])
        self.assertTrue(self.pick(name + ".Edge999")[1])
        # A name and a filter: the body's circular edges.
        self.assertEqual(len(self.pick(name + ":edges:circular")[0]), 2)

    def test_completion_lists_names(self):
        saved = cl.tools
        cl.tools = lambda: LISTING + [("SD_Split", "split", "Split", "")]
        try:
            c = [p for p, _s in line_complete.completions("split 1 sel=")]
            self.assertEqual(c[:3], ["sel=front,", "sel=top,", "sel=right,"])
            c = [p for p, _s in line_complete.completions("split sel=fr")]
            self.assertEqual(c[0], "sel=front,")
            c = [p for p, _s in line_complete.completions("fillet 1 sel=Boss")]
            self.assertIn("sel=Boss-Extrude2,", c)
        finally:
            cl.tools = saved


class TestWords(_Model):
    def test_words_add_from_the_pick(self):
        from freecad.SolidDesign.gui import pick_tools
        body = self.views[0]
        e = next(i for i, x in enumerate(body.Shape.Edges, 1)
                 if abs(x.CenterOfMass.z - 10) < 1e-6 and abs(x.CenterOfMass.y) < 1e-6)
        sub = "Edge%d" % e
        key = (self.doc.Name, body.Name, sub)
        both = set(pick_tools.expand(body, sub, "loop")) | \
            set(pick_tools.expand(body, sub, "otherloop")) | {sub}
        keys = self.pick("jk,loop,otherloop", {"jk": key})[0]
        self.assertEqual(sorted(k[2] for k in keys), sorted(both))
        self.assertEqual(self.pick("loop")[1],
                         ['"loop" adds edges from an edge: pick one before it.'])


class TestFilters(_Model):
    def test_types(self):
        self.assertEqual(len(self.els("edges:circular")), 2)
        self.assertTrue(all(type(f.Surface).__name__ == "Plane" for f in self.els("faces:planar")))

    def test_corners(self):
        inside = self.els("edges:concave")
        self.assertEqual(len(inside), 1)
        self.assertAlmostEqual(inside[0].CenterOfMass.z, 10, 6)
        self.assertEqual(len(self.els("edges:convex:circular")), 1)

    def test_extremes_and_measures(self):
        top = self.els("edges:top")
        self.assertEqual(len(top), 1)
        self.assertAlmostEqual(top[0].BoundBox.ZMax, 15, 6)
        self.assertEqual(len(self.els("edges:r<5")), 2)
        self.assertEqual(len(self.els("edges:len>35")), 4)    # the plate's long edges
        big = self.els("faces:largest")
        self.assertEqual(len(big), 1)
        self.assertAlmostEqual(big[0].Area, 1200, 6)          # the plate's bottom

    def test_directions(self):
        flat = self.els("faces:par:z")
        self.assertEqual(len(flat), 3)                          # bottom, plate top, boss top
        walls = self.els("faces:perp:z")
        self.assertEqual(len(walls), 5)                         # four sides and the boss
        up = self.els("edges:linear:par:z")
        self.assertEqual(len(up), 5)                    # the plate's corners, the boss's seam

    def test_nothing_picked_says_so(self):
        keys, problems = self.pick("edges:r<1")
        self.assertEqual(keys, [])
        self.assertTrue(problems)


class TestMotions(_Model):
    def test_step_round_the_plate(self):
        body = self.views[0]
        e = next(i for i, x in enumerate(body.Shape.Edges, 1)
                 if abs(x.CenterOfMass.z - 10) < 1e-6 and abs(x.CenterOfMass.y) < 1e-6)
        key = (self.doc.Name, body.Name, "Edge%d" % e)
        nxt = self.pick("jk]", {"jk": key})[0]
        back = self.pick("jk[", {"jk": key})[0]
        self.assertEqual(len(nxt), 1)
        self.assertEqual(len(back), 1)
        self.assertNotEqual(nxt, [key])
        self.assertNotEqual(nxt, back)
        self.assertEqual(self.pick("jk][", {"jk": key})[0], [key])

    def test_codes_and_motions(self):
        self.assertEqual(line_select.code_and_motions("jk]]"), ("jk", "]]"))
        self.assertEqual(line_select.code_and_motions("jk+"), ("jk", "+"))
        self.assertTrue(line_select.is_code("jk]"))
        self.assertFalse(line_select.is_code("new"))
        self.assertFalse(line_select.is_code("jk:edges"))


class TestRegisters(_Model):
    def test_kept_by_fingerprint(self):
        keys = self.pick("edges:circular")[0]
        line_store.set_register(self.doc, "a", line_select.to_items(keys))
        self.assertIn("a", line_store.registers(self.doc))
        self.assertEqual(sorted(self.pick("@a")[0]), sorted(keys))
        # Renumbered: the name points elsewhere, the fingerprint finds it.
        items = line_select.to_items(keys)
        other = next(i for i, e in enumerate(self.views[0].Shape.Edges, 1)
                     if type(e.Curve).__name__ != "Circle")
        items[0]["sub"] = "Edge%d" % other
        found, lost = line_select.from_items(self.doc, items)
        self.assertEqual(lost, 0)
        self.assertEqual(sorted(found), sorted(keys))
        self.assertTrue(line_store.remove_register(self.doc, "a"))
        self.assertEqual(self.pick("@a")[1], ['No register "a".'])

    def test_find_element(self):
        body = self.views[0]
        el = body.Shape.getElement("Face1")
        fp = refs.fingerprint(el)
        self.assertEqual(refs.find_element(body, "Face1", fp), "Face1")


class TestFeatureCommands(_Model):
    def test_by_name_and_last(self):
        self.assertIs(line_ex.feature_line("Boss-Extrude2 7")[0], self.boss)
        self.assertIs(line_ex.feature_line("last d=+2")[0], self.boss)
        self.assertIsNone(line_ex.feature_line("fillet 2"))
        self.assertEqual(line_ex.run("Boss-Extrude2 7"), "Boss-Extrude2 changed.")
        self.assertAlmostEqual(self.boss.Depth.Value, 7, 9)
        line_ex.run("last d=+2")
        self.assertAlmostEqual(self.boss.Depth.Value, 9, 9)
        line_ex.run("last -4")
        self.assertAlmostEqual(self.boss.Depth.Value, 5, 9)

    def test_patterns_and_batch(self):
        objs, missing = line_ex.targets(["/Extrude/"], line_ex.features(self.part))
        self.assertEqual(objs, [self.plate, self.boss])
        self.assertEqual(missing, [])
        self.assertEqual(line_ex.targets(["Nope"], line_ex.features(self.part))[1], ["Nope"])
        line_ex.run("set d=10->12 /Extrude/")
        self.assertAlmostEqual(self.plate.Depth.Value, 12, 9)
        self.assertAlmostEqual(self.boss.Depth.Value, 5, 9)      # wasn't 10
        line_ex.run("set d=6 /Extrude/")
        self.assertAlmostEqual(self.plate.Depth.Value, 6, 9)
        self.assertAlmostEqual(self.boss.Depth.Value, 6, 9)

    def test_suppress_and_rollback(self):
        self.assertIn("suppressed", line_ex.run("suppress /Extrude2/"))
        self.assertTrue(self.boss.Suppressed)
        line_ex.run("unsup Boss-Extrude2")
        self.assertFalse(self.boss.Suppressed)
        self.assertEqual(line_ex.run("rollto Boss-Extrude1"), "Rolled back to Boss-Extrude1.")
        self.assertEqual(line_ex.run("rollto end"), "Rolled to the end.")

    def test_help_is_an_action(self):
        a = line_ex.run("h sel")
        self.assertIsInstance(a, line_ex.Action)
        self.assertEqual((a.kind, a.arg), ("help", "sel"))
        self.assertIsNone(line_ex.run("fillet 2"))


class TestCustomising(unittest.TestCase):
    def setUp(self):
        self._saved = (line_store.aliases(), line_store.bindings(), line_store.defaults())
        self._tools = cl.tools, cl.catalog
        cl.tools = lambda: LISTING
        cl.catalog = lambda cmd: EXTRUDE

    def tearDown(self):
        cl.tools, cl.catalog = self._tools
        for k in list(line_store.aliases()):
            line_store.remove_alias(k)
        for k in list(line_store.bindings()):
            line_store.remove_binding(k)
        for c in list(line_store.defaults()):
            line_store.remove_default(c)
        a, b, d = self._saved
        for k, v in a.items():
            line_store.set_alias(k, v)
        for k, v in b.items():
            line_store.set_binding(k, v)
        for c, pv in d.items():
            for p, v in pv.items():
                line_store.set_default(c, p, v)

    def test_alias(self):
        line_ex.run("alias f2 = fillet 2")
        self.assertEqual(line_ex.expand_alias("f2 sel=jk"), "fillet 2 sel=jk")
        self.assertEqual(line_ex.expand_alias("fillet 3"), "fillet 3")
        self.assertIn("command", line_ex.run("alias set = fillet 1"))
        line_ex.run("unalias f2")
        self.assertEqual(line_ex.expand_alias("f2"), "f2")

    def test_bind(self):
        self.assertIn("runs", line_ex.run("bind gf = fillet 1 sel=new"))
        self.assertEqual(line_store.bindings()["gf"], "fillet 1 sel=new")
        self.assertIn("own keys", line_ex.run("bind g: = fillet 1"))
        line_ex.run("unbind gf")
        self.assertNotIn("gf", line_store.bindings())

    def test_defaults_fill_what_the_line_leaves(self):
        line_store.set_default("SD_Extrude", "Depth", "7")
        line_store.set_default("SD_Extrude", "Reverse", "yes")
        line = cl.parse("extrude 3", LISTING)
        extra = dict(line_ex.defaults_for("SD_Extrude", line))
        self.assertEqual(extra, {"Reverse": "yes"})              # 3 is the depth
        line = cl.parse("extrude", LISTING)
        self.assertEqual(dict(line_ex.defaults_for("SD_Extrude", line)),
                         {"Depth": "7", "Reverse": "yes"})
        self.assertEqual(line_ex.run("unset extrude"), "Default forgotten.")
        self.assertEqual(line_store.defaults(), {})


class TestCompletion(unittest.TestCase):
    def test_tab_target(self):
        tt = line_complete.tab_target
        self.assertEqual(tt("fil", [("fillet ", "")]), "fillet ")
        # The only one it starts, among loose matches.
        self.assertEqual(tt("fil", [("fillet ", ""), ("variablefillet ", "")]), "fillet ")
        # One that all the others begin with wins; else Tab goes down the list.
        self.assertEqual(tt("fi", [("fillet ", ""), ("Fillet1 ", ""), ("Fillet2 ", "")]),
                         "fillet ")
        self.assertIsNone(tt("fil", [("fillet ", ""), ("fillpattern ", "")]))
        self.assertEqual(tt("sel=jk,ta", [("sel=jk,tangent,", ""), ("sel=jk,tan,", "")]),
                         "sel=jk,tan,")
        self.assertEqual(tt("e", [("extrude ", ""), ("edit ", "")]), None)
        self.assertEqual(tt("", [("a", ""), ("b", "")]), None)

    def test_ghost(self):
        g = line_complete.ghost
        self.assertEqual(g("fil", [("fillet ", "")]), "let")
        self.assertEqual(g("sel=ne", [("sel=new,", ""), ("sel=tangent,", "")]), "w,")
        self.assertEqual(g("e", [("extrude ", ""), ("edit ", "")]), "")
        self.assertEqual(g("flt", [("fillet ", "")]), u"  → fillet")

    def test_line(self):
        saved = cl.tools
        cl.tools = lambda: LISTING
        try:
            c = line_complete.completions
            self.assertEqual(c("fil")[0][0], "fillet ")
            self.assertIn("help ", [p for p, _s in c("he")])
            self.assertTrue(all(p.startswith("sel=new:") for p, _s in c("fillet 1 sel=new:")))
            self.assertEqual(c("fillet 1 sel=jk"), [])         # a label: shown in the view
            self.assertEqual(c("fillet 1 sel=ne")[0][0], "sel=new,")
            self.assertIn("sel=jk,par:z", [p for p, _s in c("fillet 1 sel=jk,par:")])
            topics = [p for p, _s in c("h ")]
            self.assertEqual(topics, line_help.topics())
        finally:
            cl.tools = saved


class TestHelp(unittest.TestCase):
    def test_every_command_is_in_the_sheet(self):
        text = line_help.html()
        for name in line_ex.COMMANDS:
            if len(name) > 2:                   # short forms are named beside them
                self.assertIn(name, text, name)

    def test_every_filter_and_source(self):
        text = line_help.html()
        for f, _w in line_select.FILTERS:
            self.assertIn(f.rstrip(":<>="), text, f)
        for s, _w in line_select.SOURCES:
            self.assertIn(s, text, s)

    def test_topics(self):
        self.assertEqual(line_help.find("filter"), "filters")
        self.assertEqual(line_help.find("Key"), "keys")
        self.assertIsNone(line_help.find("zzz"))


class TestConcave(unittest.TestCase):
    def test_box_and_pocket(self):
        import Part
        box = Part.makeBox(10, 10, 10)
        self.assertTrue(all(core_edges.is_concave(box, e) is False for e in box.Edges))
        cut = box.cut(Part.makeBox(4, 4, 5, V(3, 3, 5)))
        bottom = [e for e in cut.Edges if abs(e.CenterOfMass.z - 5) < 1e-6 and
                  e.BoundBox.ZLength < 1e-6]
        self.assertEqual(len(bottom), 4)
        self.assertTrue(all(core_edges.is_concave(cut, e) is True for e in bottom))


if __name__ == "__main__":
    unittest.main()
