# SPDX-License-Identifier: LGPL-2.1-or-later
"""Live preview on the command line: as you type a tool's line, the feature it
would make shows in the 3D view (green where it adds, red where it takes away),
and the reason it can't be made shows under the line, before Enter.

The feature is made for real, in a transaction that is then aborted: the
document ends as it was (nothing in the undo history), and what it would have
looked like is kept as coin nodes, as a panel's preview is.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import preview as pv

#: Tools never tried in the background: they open dialogs of their own, or make
#: nothing to show.
NO_PREVIEW = {"SD_Part", "SD_Sketch", "SD_CommandSearch", "SD_CommandLine",
              "SD_RepeatLast", "SD_ContextToolbar", "SD_ReferenceLabels", "SD_WhatsWrong",
              "SD_Rebuild"}
_refused = set()            # tools found this session to leave something behind


def _selection():
    out = []
    for s in Gui.Selection.getSelectionEx():
        subs = s.SubElementNames or [""]
        for sub in subs:
            out.append((s.DocumentName, s.ObjectName, sub))
    return out


def _restore(keys):
    Gui.Selection.clearSelection()
    for k in keys:
        try:
            Gui.Selection.addSelection(*k)
        except Exception:
            pass


def dry_run(cmd, line, under=None):
    """Make ``cmd`` with a parsed ``line`` and undo it. Returns (node or None,
    problem or "")."""
    from . import command_line as cl
    from . import viewproviders
    if cmd in NO_PREVIEW or cmd in _refused or cl._proxy_classes().get(cmd) is None:
        return None, ""
    c = Gui.Command.get(cmd)
    doc = App.ActiveDocument
    if c is None or doc is None:
        return None, ""
    kept = _selection()
    if not kept and under is None:
        return None, ""
    if not kept:
        try:
            Gui.Selection.addSelection(*under)
        except Exception:
            return None, ""
    names = set(o.Name for o in doc.Objects)
    undo0 = doc.UndoCount
    made = []

    def hold(obj):
        made.append(obj)
        return True
    node, problem = None, ""
    if not c.isActive():
        _restore(kept)
        return None, ""
    try:
        viewproviders.run_held(cmd, hold)
    except Exception as e:
        problem = str(e)
    try:
        if made:
            obj = made[0]
            try:
                line = _with_defaults(cmd, line)
                assigns = cl.assignments(line, cl.settable(obj), cl.variables(doc),
                                         cl._main(cmd, obj))
                cl.apply(obj, assigns)
                doc.recompute()
                problem = obj.ErrorMessage or ""
            except ValueError as e:
                problem = str(e)
            if not problem:
                node = _node(obj)
    finally:
        doc.abortTransaction()
        _settle(doc, cmd, names, undo0)
        _restore(kept)
        try:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
                _refused.add(cmd)
        except Exception:
            pass
    return node, problem


def _settle(doc, cmd, names, undo0):
    """After a try: the document as it was. Rebuilt as a panel's Cancel does (the
    body views follow the bodies again); anything the tool committed itself is
    undone, and that tool isn't tried again."""
    if doc.UndoCount > undo0:
        _refused.add(cmd)
        while doc.UndoCount > undo0:
            doc.undo()
    left = [o for o in doc.Objects if o.Name not in names]
    if left:
        _refused.add(cmd)
        for o in left:
            try:
                doc.removeObject(o.Name)
            except Exception:
                pass
    if any("Touched" in o.State for o in doc.Objects):
        doc.recompute()


def _with_defaults(cmd, line):
    from . import line_ex
    return line_ex.with_defaults(cmd, line)


def dry_edit(obj, words):
    """A feature edit (``Fillet1 r=3``) tried and undone: (node, problem)."""
    from . import command_line as cl
    from . import line_ex
    if not words:
        return None, ""
    try:
        assigns = line_ex.feature_assigns(obj, words)
    except ValueError as e:
        return None, str(e)
    doc = obj.Document
    node, problem = None, ""
    undo0 = doc.UndoCount
    doc.openTransaction("Preview")
    try:
        cl.apply(obj, assigns)
        doc.recompute()
        problem = obj.ErrorMessage or ""
        if not problem:
            node = _node(obj)
    except Exception as e:
        problem = str(e)
    finally:
        doc.abortTransaction()
        _settle(doc, None, set(o.Name for o in doc.Objects), undo0)
    return node, problem


def _node(obj):
    """What the feature would add (green) or take away (red), as coin nodes made
    from copies of its shapes (the feature is about to go)."""
    try:
        base = getattr(obj, "BaseFeature", None)
        after = obj.Shape.copy() if not obj.Shape.isNull() else None
        before = base.Shape.copy() if base is not None and not base.Shape.isNull() else None
        tool = getattr(obj, "AddSubShape", None)
        tool = tool.copy() if tool is not None and not tool.isNull() else None
    except Exception:
        return None
    if tool is None:
        if after is None:
            return None
        return pv.shape_node(after, pv.ADD_COLOR, pv.RESULT_TRANSPARENCY)
    add = True
    try:
        if after is not None and before is not None:
            va = sum(s.Volume for s in after.Solids)
            vb = sum(s.Volume for s in before.Solids)
            if after.Solids or before.Solids:
                add = va >= vb - 1e-9
            else:
                add = after.Area >= before.Area - 1e-9
    except Exception:
        pass
    faces = pv.new_faces(tool, before) if before is not None else tool
    if faces is None or faces.isNull():
        faces = tool
    return pv.result_node(faces, add)
