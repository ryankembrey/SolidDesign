# SPDX-License-Identifier: LGPL-2.1-or-later
"""Small helpers shared by the document objects. No Qt here."""

import re

import FreeCAD as App

SCHEMA_VERSION = 1


def role(obj):
    """The Solid Design role of a document object, or None."""
    try:
        return getattr(obj.Proxy, "SD_ROLE", None)
    except Exception:
        return None


def is_part(obj):
    return role(obj) == "part"


def is_feature(obj):
    return role(obj) == "feature"


def is_body_view(obj):
    return role(obj) == "body"


def part_of(obj):
    """The Solid Design Part that holds a feature or sketch."""
    if obj is None:
        return None
    if is_part(obj):
        return obj
    for o in obj.InList:
        if is_part(o) and obj in o.Group:
            return o
    for o in obj.InList:
        if is_part(o):
            return o
    return None


def features(part):
    return [o for o in part.Group if is_feature(o)]


ZWSP = u"\u200b"


def next_label(doc, prefix, exclude=None):
    """SolidWorks numbering: Boss-Extrude1, Boss-Extrude2... per prefix.

    The lowest number not used by another object (so Cut-Extrude1 switched to Add
    and back gets Cut-Extrude1 again).
    """
    pat = re.compile(r"^" + re.escape(prefix) + r"(\d+)" + ZWSP + "*$")
    used = set()
    for o in doc.Objects:
        if o is exclude or is_body_view(o):
            continue
        m = pat.match(o.Label)
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return "{}{}".format(prefix, n)


def add_prop(obj, type_, name, group, doc, default=None, mode=0, enum=None):
    """Add a property if missing (used by migrations too)."""
    if name not in obj.PropertiesList:
        obj.addProperty(type_, name, group, doc, mode)
        if enum is not None:
            setattr(obj, name, enum)
        if default is not None:
            setattr(obj, name, default)
    return obj


def hide_prop(obj, name):
    try:
        obj.setEditorMode(name, 2)
    except Exception:
        pass


def readonly_prop(obj, name):
    try:
        obj.setEditorMode(name, 1)
    except Exception:
        pass


def in_recompute(doc):
    try:
        return doc.Recomputing
    except Exception:
        return False


def console_error(msg):
    App.Console.PrintError("Solid Design: " + msg + "\n")


def console_warning(msg):
    App.Console.PrintWarning("Solid Design: " + msg + "\n")


def set_label(obj, prefix):
    """Give ``obj`` the next SolidWorks-style label for ``prefix`` ("Cut-Extrude1").

    FreeCAD keeps a label reserved after an object made in an aborted
    transaction is gone (a cancelled feature), and refuses to give it out again.
    The number is free, so the label gets a zero-width space after it (as body
    names do) rather than becoming "Cut-Extrude2" or "Cut-Extrude001".
    """
    label = next_label(obj.Document, prefix, exclude=obj)
    n = int(label[len(prefix):])
    for _ in range(50):
        want = "{}{}".format(prefix, n)
        for k in range(4):
            obj.Label = want + ZWSP * k
            if obj.Label == want + ZWSP * k:
                return obj.Label
        n += 1
    return obj.Label


def is_curve(o):
    """A sketch, or a curve in the history (helix, projected, composite...)."""
    if o is None:
        return False
    if o.TypeId.startswith("Sketcher::SketchObject"):
        return True
    return role(o) == "refgeom" and getattr(o.Proxy, "KIND", "") in ("helix", "curve")
