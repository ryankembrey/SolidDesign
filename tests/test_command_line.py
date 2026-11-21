# SPDX-License-Identifier: LGPL-2.1-or-later
"""The command line's parsing (gui/command_line.py), without a view."""

import unittest

from freecad.SolidDesign.gui import command_line as cl

LISTING = [("SD_Fillet", "fillet", "Fillet", ""), ("SD_Extrude", "extrude", "Extrude", ""),
           ("SD_LinearPattern", "linearpattern", "Linear Pattern", ""),
           ("SD_Chamfer", "chamfer", "Chamfer", "")]
VARS = {"Width": "VarSet.Width", "Wall": "Params.Wall"}
EXTRUDE = {"Depth": ("num", None), "Depth2": ("num", None), "Reverse": ("bool", None),
           "Mode": ("enum", ["Add", "Cut", "Surface"]),
           "EndCondition": ("enum", ["Blind", "Through All", "Through All - Both", "Mid Plane"]),
           "Draft": ("bool", None), "DraftAngle": ("num", None)}


def assigns(text, options=EXTRUDE, main=("Depth", "Depth2")):
    return cl.assignments(cl.parse(text, LISTING), options, VARS, list(main))


class TestValues(unittest.TestCase):
    def test_numbers_and_units(self):
        self.assertEqual(cl.value_of("2", VARS), ("num", 2.0))
        self.assertAlmostEqual(cl.value_of("1in", VARS)[1], 25.4)
        self.assertAlmostEqual(cl.value_of("30deg", VARS)[1], 30.0)
        self.assertIsNone(cl.value_of("cut", VARS))

    def test_variables_become_live_expressions(self):
        self.assertEqual(cl.value_of("Width", VARS), ("expr", "VarSet.Width"))
        self.assertEqual(cl.value_of("Width/2", VARS), ("expr", "VarSet.Width/2"))
        self.assertEqual(cl.value_of("=Wall*2 + 1mm", VARS), ("expr", "Params.Wall*2 + 1mm"))
        self.assertEqual(cl.value_of("=VarSet.Width", VARS), ("expr", "VarSet.Width"))


class TestParsing(unittest.TestCase):
    def test_tools_match_by_keyword_or_fuzzily(self):
        self.assertEqual(cl.parse("fillet 2", LISTING).cmd, "SD_Fillet")
        self.assertEqual(cl.parse(":lp 20 4", LISTING).cmd, "SD_LinearPattern")
        self.assertTrue(cl.parse("zzz 2", LISTING).error)

    def test_values_in_order_then_options(self):
        self.assertEqual(assigns("extrude 10"), [("Depth", "num", 10.0)])
        self.assertEqual(assigns("extrude 10 5"), [("Depth", "num", 10.0),
                                                   ("Depth2", "num", 5.0)])
        a = assigns("extrude 10 cut")
        self.assertEqual(a, [("Mode", "enum", "Cut"), ("Depth", "num", 10.0)])

    def test_option_words(self):
        self.assertIn(("EndCondition", "enum", "Through All"), assigns("extrude throughall"))
        self.assertIn(("EndCondition", "enum", "Mid Plane"), assigns("extrude mid"))
        self.assertIn(("Reverse", "bool", True), assigns("extrude reverse"))
        self.assertIn(("Reverse", "bool", False), assigns("extrude noreverse"))
        with self.assertRaises(ValueError):
            assigns("extrude sideways")

    def test_named_options(self):
        self.assertIn(("DraftAngle", "num", 3.0), assigns("extrude dra=3"))
        self.assertIn(("Mode", "enum", "Surface"), assigns("extrude mode=surf"))
        self.assertIn(("Draft", "bool", True), assigns("extrude draft=yes"))
        self.assertIn(("Depth", "expr", "VarSet.Width/2"), assigns("extrude depth=Width/2"))
        with self.assertRaises(ValueError):            # Depth or Depth2?
            assigns("extrude dep=3")
        with self.assertRaises(ValueError):
            assigns("extrude 1 2 3")                   # only two values go in order


class TestChanges(unittest.TestCase):
    def test_what_a_panel_changed_options_first(self):
        before = {"Depth": ("num", 10.0), "Mode": ("enum", "Add"), "Reverse": ("bool", False)}
        after = {"Depth": ("num", 4.0), "Mode": ("enum", "Cut"), "Reverse": ("bool", False)}
        self.assertEqual(cl.changes(before, after), [("Mode", "enum", "Cut"),
                                                     ("Depth", "num", 4.0)])


if __name__ == "__main__":
    unittest.main()
