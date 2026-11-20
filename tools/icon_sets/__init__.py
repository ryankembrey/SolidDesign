# SPDX-License-Identifier: LGPL-2.1-or-later
"""The icons, one module per toolbar. GROUPS gives the sheet's row order."""

from . import features, patterns, bodies, reference, surfaces, curves, evaluate

GROUPS = [
    ("Features (green adds, red removes, blue changes)", features),
    ("Patterns and Mirror (blue)", patterns),
    ("Bodies (violet)", bodies),
    ("Reference Geometry (amber)", reference),
    ("Surfaces (teal)", surfaces),
    ("Curves (magenta)", curves),
    ("Evaluate, tree and UI (slate)", evaluate),
]
