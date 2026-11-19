# SPDX-License-Identifier: LGPL-2.1-or-later
"""Which Part new features go into."""

import FreeCAD as App
import FreeCADGui as Gui

from ..app import part as part_mod
from ..app import util

_active = {}    # document name -> part name


def set_active(part):
    _active[part.Document.Name] = part.Name
    App.Console.PrintMessage("Solid Design: active part is {}\n".format(part.Label))


def active_part(doc, create=True):
    """The active Part: the one holding the selection, the one set active, the only
    one in the document, or a new one."""
    if doc is None:
        return None
    for s in Gui.Selection.getSelection(doc.Name):
        p = util.part_of(s) if not util.is_body_view(s) else part_mod.source_part(s)
        if p is not None:
            _active[doc.Name] = p.Name
            return p
    name = _active.get(doc.Name)
    if name:
        p = doc.getObject(name)
        if p is not None and util.is_part(p):
            return p
    parts = part_mod.find_parts(doc)
    if len(parts) == 1:
        return parts[0]
    if parts:
        return parts[-1]
    if not create:
        return None
    p = part_mod.create(doc)
    _active[doc.Name] = p.Name
    return p
