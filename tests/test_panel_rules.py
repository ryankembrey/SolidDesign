# SPDX-License-Identifier: LGPL-2.1-or-later
"""The panel rules that can be checked without a GUI (the tooltip rule is
checked in tests/gui, on every panel the smoke tests open).

- No stylesheets outside gui/panel/parts.py: panels take FreeCAD's theme.
- Panels are built from the parts: no hand-made group boxes or bare lists of
  picks in the panel modules.
"""

import os
import re
import unittest

import freecad.SolidDesign as sd

GUI = os.path.join(sd.PACKAGE_DIR, "gui")


def gui_sources():
    for root, _dirs, files in os.walk(GUI):
        for f in files:
            if f.endswith(".py"):
                path = os.path.join(root, f)
                with open(path, encoding="utf-8") as fh:
                    yield os.path.relpath(path, GUI), fh.read()


class TestPanelRules(unittest.TestCase):
    def test_stylesheets_only_in_parts(self):
        offenders = [name for name, text in gui_sources()
                     if "setStyleSheet" in text and name != os.path.join("panel", "parts.py")]
        self.assertEqual(offenders, [], "setStyleSheet outside panel/parts.py")

    def test_groups_come_from_parts(self):
        offenders = [name for name, text in gui_sources()
                     if re.search(r"QGroupBox\(", text) and
                     name != os.path.join("panel", "parts.py")]
        self.assertEqual(offenders, [], "a QGroupBox not made by parts.Group")

    def test_old_widgets_gone(self):
        self.assertFalse(os.path.exists(os.path.join(GUI, "panel", "widgets.py")))
        offenders = [name for name, text in gui_sources()
                     if re.search(r"\bwidgets as w\b|\bSelectionBox\b|\bSection\(", text)]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
