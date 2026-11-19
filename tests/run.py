# SPDX-License-Identifier: LGPL-2.1-or-later
"""Run the headless tests in freecadcmd.

    freecadcmd tests/run.py                 # everything
    SD_TESTS=test_extrude freecadcmd tests/run.py   # one module (comma-separated)
    SD_TESTS=test_extrude.TestEnd.test_blind ...    # one test

The addon must be importable as freecad.SolidDesign (installed in the Mod
folder, or linked there).
"""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

names = [n.strip() for n in os.environ.get("SD_TESTS", "").split(",") if n.strip()]
loader = unittest.TestLoader()
if names:
    suite = loader.loadTestsFromNames(names)
else:
    suite = loader.discover(HERE, pattern="test_*.py", top_level_dir=HERE)
stream = open(1, "w", encoding="utf-8", closefd=False)   # FreeCAD's stdout may be ASCII
result = unittest.TextTestRunner(verbosity=2, stream=stream).run(suite)
stream.flush()
os._exit(0 if result.wasSuccessful() else 1)
