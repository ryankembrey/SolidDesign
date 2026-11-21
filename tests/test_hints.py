# SPDX-License-Identifier: LGPL-2.1-or-later
"""Link hints on the command line: the labels, reading sel= out of a line, and
what each tool labels."""

import unittest

from freecad.SolidDesign.gui import hints


class _H(hints.Hint):
    """A hint without a document (assign only needs a key and a place)."""

    def __init__(self, name, x, y):
        self.obj, self.sub, self.kind, self.x, self.y = None, name, "Edge", x, y
        self.code = ""

    def key(self):
        return ("D", "Body", self.sub)


class TestCodes(unittest.TestCase):
    def test_two_home_row_letters_at_least(self):
        c = hints.codes(5)
        self.assertEqual(len(c), 5)
        self.assertTrue(all(len(x) == 2 and set(x) <= set(hints.ALPHABET) for x in c))
        self.assertEqual(c[0], "jj")            # both index fingers at rest

    def test_none_starts_another(self):
        for n in (1, 9, 81, 82, 300):
            c = hints.codes(n)
            self.assertEqual(len(set(c)), n)
            self.assertEqual(len({len(x) for x in c}), 1, n)
        self.assertEqual(len(hints.codes(82)[0]), 3)    # 81 two-letter labels, then three

    def test_easy_ones_first(self):
        c = hints.codes(81)
        self.assertLess(c.index("jf"), c.index("gh"))
        self.assertLess(c.index("kd"), c.index("ag"))


class TestLine(unittest.TestCase):
    def test_split(self):
        rest, sels = hints.split_selection("fillet 2 sel=jk,dl, r=3")
        self.assertEqual(rest, "fillet 2 r=3")
        self.assertEqual(sels, [("sel", ["jk", "dl"])])
        rest, sels = hints.split_selection(":sel=jj")
        self.assertEqual((rest, sels), ("", [("sel", ["jj"])]))
        self.assertEqual(hints.split_selection("extrude 10")[1], [])

    def test_kinds(self):
        self.assertEqual(hints.sel_kinds("sel", "SD_Fillet"), ("Edge",))
        self.assertEqual(hints.sel_kinds("sel", "SD_Shell"), ("Face",))
        self.assertEqual(hints.sel_kinds("sel", "SD_Sketch"), ("Plane",))
        self.assertEqual(hints.sel_kinds("sel", None), hints.DEFAULT_KINDS)
        self.assertEqual(hints.sel_kinds("v", "SD_Fillet"), ("Vertex",))
        self.assertIsNone(hints.sel_kinds("radius", "SD_Fillet"))

    def test_parse_ignores_picks(self):
        from freecad.SolidDesign.gui import command_line
        listing = [("SD_Fillet", "fillet", "Fillet", "")]
        line = command_line.parse("fillet 2 sel=jk,dl,", listing)
        self.assertEqual((line.error, line.values, line.named), ("", ["2"], []))


class TestAssign(unittest.TestCase):
    def test_nearest_the_middle_gets_the_easiest(self):
        hs = [_H("Edge1", 900, 900), _H("Edge2", 500, 500), _H("Edge3", 0, 0)]
        hints.assign(hs, centre=(500, 500))
        self.assertEqual(hs[1].code, "jj")

    def test_picked_keep_their_labels(self):
        """After the view turns, what was picked keeps its label; the rest get
        others."""
        hs = [_H("Edge%d" % i, i * 10, 0) for i in range(1, 6)]
        hints.assign(hs, keep={("D", "Body", "Edge4"): "jj"}, centre=(0, 0))
        self.assertEqual(hs[3].code, "jj")
        self.assertEqual(len({h.code for h in hs}), 5)
