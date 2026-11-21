# SPDX-License-Identifier: LGPL-2.1-or-later
"""Command search's fuzzy matching (gui/command_search.py)."""

import unittest

from freecad.SolidDesign.gui.command_search import fuzzy, rank

TOOLS = [(n, n, t) for n, t in (
    ("Extrude", "Extrudes a sketch: a boss, a cut or a surface."),
    ("Fillet", "Rounds edges."), ("Flex", "Bends, twists, tapers or stretches bodies."),
    ("Linear Pattern", "Copies along one or two directions."),
    ("Circular Pattern", "Copies round an axis."), ("Split", "Splits bodies."),
    ("Split Line", "Splits faces."), ("Plane", "A reference plane."),
    ("Planar Surface", "A flat surface from a sketch."), ("Shell", "Hollows a body."))]


def names(q):
    return [e[0] for e in rank(q, TOOLS)]


class TestFuzzy(unittest.TestCase):
    def test_letters_in_order(self):
        self.assertIsNotNone(fuzzy("fil", "Fillet"))
        self.assertIsNone(fuzzy("lif", "Fillet"))
        self.assertIsNone(fuzzy("filx", "Fillet"))

    def test_word_starts_beat_letters_inside_words(self):
        self.assertEqual(names("lp")[0], "Linear Pattern")
        self.assertEqual(names("cp")[0], "Circular Pattern")
        self.assertEqual(names("ps")[0], "Planar Surface")

    def test_a_prefix_ranks_first(self):
        self.assertEqual(names("fil")[0], "Fillet")
        self.assertEqual(names("fl")[:2], ["Flex", "Fillet"])
        self.assertEqual(names("split")[:2], ["Split", "Split Line"])
        self.assertEqual(names("pla")[0], "Plane")

    def test_case_and_spaces_dont_matter(self):
        self.assertEqual(names("LIN pat")[0], "Linear Pattern")

    def test_a_tooltip_word_finds_a_tool_below_label_matches(self):
        self.assertEqual(names("boss"), ["Extrude"])
        self.assertEqual(names("hollow"), ["Shell"])
        self.assertEqual(names("qqq"), [])


if __name__ == "__main__":
    unittest.main()
