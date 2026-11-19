# SPDX-License-Identifier: LGPL-2.1-or-later
"""View providers: the FeatureManager-style tree (spec section 6).

Part1
├── Solid Bodies (2)        folders: views of the tip's bodies, hidden when empty
├── Surface Bodies (1)
├── Front Plane / Top Plane / Right Plane / Origin
├── Boss-Extrude1
│   └── Sketch1             a feature's own sketch sits under it
├── ─── Rollback bar ───    drag it onto a feature, or use Rollback
└── Cut-Extrude1            rolled back: greyed

Errors and warnings show as badges on a feature's icon and on the Part's.
View providers restore without errors when the addon is missing because their
proxies hold no state (dumps/loads return None).
"""

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

from .. import icon
from ..app import part as part_mod
from ..app import util


def _state_icon(base, obj):
    if getattr(obj, "RolledBack", False):
        return icon(base + "_rolled")
    if getattr(obj, "ErrorMessage", ""):
        return icon(base + "_error")
    if getattr(obj, "WarningMessage", ""):
        return icon(base + "_warning")
    return icon(base)


def _refresh_icon(vobj):
    try:
        vobj.signalChangeIcon()
    except Exception:
        pass


class _Stateless(object):
    def dumps(self):
        return None

    def loads(self, state):
        return None

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        return None


class _DrawsNothing(_Stateless):
    """For tree items that stay visible (not greyed, as in SolidWorks) but draw
    nothing: the part, features, folders and the rollback bar. Bodies are drawn by
    the body views; previews by the panels."""

    MODE = "Nothing"

    def _add_group_mode(self, vobj):
        # listDisplayModes() already lists the proxy's declared modes, so it can't
        # tell whether the node was registered: track it on the proxy instead.
        if getattr(self, "_node", None) is not None:
            return
        try:
            from pivy import coin
            self._node = coin.SoSeparator()
            vobj.addDisplayMode(self._node, self.MODE)
        except Exception:
            self._node = None

    def getDisplayModes(self, vobj):
        return [self.MODE]

    def getDefaultDisplayMode(self):
        return self.MODE

    def setDisplayMode(self, mode):
        return mode


def _show_nothing(vobj):
    try:
        vobj.Proxy._add_group_mode(vobj)
        if "DisplayMode" in vobj.PropertiesList:
            vobj.DisplayMode = _DrawsNothing.MODE
    except Exception:
        pass
    try:
        vobj.Visibility = True
    except Exception:
        pass


# =================================================================== Part

class PartVP(_DrawsNothing):
    """The part draws nothing itself: its bodies are drawn by the body views. It
    stays visible (not greyed in the tree); hiding it hides its bodies."""

    def __init__(self, vobj):
        self.Object = vobj.Object
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        self._add_group_mode(vobj)
        QtCore.QTimer.singleShot(0, lambda: _add_origin_folder(vobj.Object))

    def getIcon(self):
        obj = getattr(self, "Object", None)
        if obj is not None:
            feats = util.features(obj)
            if any(f.ErrorMessage for f in feats):
                return icon("Part_error")
            if any(f.WarningMessage for f in feats):
                return icon("Part_warning")
        return icon("Part")

    def claimChildren(self):
        obj = self.Object
        out = []
        for kind in ("solid", "surface"):
            f = part_mod.folder(obj, kind)
            if f is not None:
                out.append(f)       # an empty folder is hidden (ShowInTree), as in SolidWorks
        origin = list(obj.Origin)
        of = part_mod.folder(obj, part_mod.ORIGIN_FOLDER)
        if of is not None:
            out.append(of)          # the planes and origin, in their own folder
        else:
            out.extend(o for o in origin if o.TypeId == "Part::DatumPlane")
            out.extend(o for o in origin if o.TypeId == "Part::DatumPoint")
            out.extend(o for o in origin if o.TypeId == "Part::DatumLine")   # hidden
        claimed = set()
        for f in util.features(obj):
            for c in FeatureVP.own_children(f):
                claimed.add(c.Name)
        bar = part_mod.rollback_bar(obj)
        group = list(obj.Group)
        bar_at = part_mod._bar_index(obj, group)    # the bar sits before this item
        for i, o in enumerate(group):
            if i == bar_at and bar is not None:
                out.append(bar)
            if o in origin or o.Name in claimed:
                continue
            out.append(o)
        if bar is not None and bar not in out:
            out.append(bar)         # at the end: the bar sits below everything
        return out

    def onChanged(self, vobj, prop):
        if prop == "Visibility":
            for v in part_mod.body_views(vobj.Object):
                if v.ViewObject.Visibility != vobj.Visibility:
                    v.ViewObject.Visibility = vobj.Visibility

    def updateData(self, obj, prop):
        if prop in ("Tip", "Group", "BodyIds"):
            _refresh_icon(obj.ViewObject)

    def setupContextMenu(self, vobj, menu):
        part = vobj.Object
        a = menu.addAction("Roll to End")
        a.triggered.connect(lambda: _roll(part, "end"))
        a = menu.addAction("Roll to Start")
        a.triggered.connect(lambda: _roll(part, None))
        a = menu.addAction("Set as Active Part")
        a.triggered.connect(lambda: _set_active(part))

    def canDragObjects(self):
        return True

    def canDragObject(self, obj):
        return util.role(obj) == "rollback" or util.is_feature(obj)

    def dragObject(self, vobj, obj):
        pass

    def canDragAndDropObject(self, obj):
        # Dropping the bar moves the bar; it never moves the object into a group.
        return util.role(obj) not in ("rollback", "folder", "body")

    def canDropObjects(self):
        return True

    def canDropObject(self, obj):
        return util.role(obj) == "rollback"

    def dropObject(self, vobj, obj):
        _roll(vobj.Object, None)

    def canDelete(self, obj):
        """The part only holds its features and sketches; deleting one doesn't
        break it."""
        return True

    def onDelete(self, vobj, sub):
        """Deleting a part deletes everything in it."""
        part_mod.delete_contents(vobj.Object)
        return True

    def doubleClicked(self, vobj):
        _set_active(vobj.Object)
        return True


def _add_origin_folder(part, tries=20):
    """Parts from older files get the Origin folder, once the file is loaded."""
    try:
        if part.Document.Restoring:
            if tries:
                QtCore.QTimer.singleShot(200, lambda: _add_origin_folder(part, tries - 1))
            return
        if part_mod.ensure_origin_folder(part) is not None:
            part.ViewObject.signalChangeIcon() if hasattr(part.ViewObject, "signalChangeIcon") \
                else None
    except Exception:
        pass


def _set_active(part):
    from . import active
    active.set_active(part)


def _roll(part, where):
    doc = part.Document
    doc.openTransaction("Rollback")
    if where == "end":
        part_mod.roll_to_end(part)
    else:
        part_mod.roll_to(part, where)
    doc.recompute()
    doc.commitTransaction()


# =================================================================== features

class FeatureVP(_DrawsNothing):
    ICON = "ExtrudeAdd"

    def __init__(self, vobj):
        self.Object = vobj.Object
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        self._add_group_mode(vobj)

    @staticmethod
    def own_children(feat):
        """The feature's sketch, unless another feature uses it too (SolidWorks shows
        shared sketches at the top level)."""
        out = []
        sk = getattr(feat, "Sketch", None)
        if sk is not None:
            users = [o for o in sk.InList if util.is_feature(o)]
            if users == [feat]:
                out.append(sk)
        return out

    def claimChildren(self):
        return self.own_children(self.Object)

    def icon_base(self):
        obj = self.Object
        t = getattr(getattr(obj, "Proxy", None), "TYPE", "Extrude")
        if t == "Hole":
            return "HoleWizard"
        if t == "Rib":
            return "Rib"            # adds only: one icon
        if t == "Thicken":
            return "ThickenCut" if obj.Mode == "Cut" else "Thicken"
        named = {"Planar": "PlanarSurface", "Filled": "FilledSurface", "Trim": "TrimSurface",
                 "Extend": "ExtendSurface", "Ruled": "RuledSurface",
                 "Radiate": "RadiateSurface", "Untrim": "UntrimSurface"}
        if t in named:
            return named[t]
        if "Mode" in obj.PropertiesList:
            return t + ("Add" if obj.Mode == "Add" else "Cut")
        return t

    def getIcon(self):
        obj = getattr(self, "Object", None)
        if obj is None:
            return icon(self.ICON)
        return _state_icon(self.icon_base(), obj)

    def updateData(self, obj, prop):
        if prop in ("ErrorMessage", "WarningMessage", "RolledBack", "Mode"):
            _refresh_icon(obj.ViewObject)
            label2 = ("Error: " + obj.ErrorMessage) if obj.ErrorMessage else (
                ("Warning: " + obj.WarningMessage) if obj.WarningMessage else "")
            if obj.Label2 != label2:
                obj.Label2 = label2
            part = util.part_of(obj)
            if part is not None:
                _refresh_icon(part.ViewObject)

    def onChanged(self, vobj, prop):
        pass

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        panel = panel_class(vobj.Object)
        if panel is None:
            return None
        try:
            dlg = panel(vobj.Object, getattr(self, "_new", False))
        except Exception:
            import traceback
            App.Console.PrintError("Solid Design: the {} panel failed to open:\n{}".format(
                vobj.Object.Label, traceback.format_exc()))
            try:
                vobj.Object.Document.abortTransaction()
            except Exception:
                pass
            return False
        Gui.Control.showDialog(dlg)
        self._new = False
        return True

    def unsetEdit(self, vobj, mode=0):
        return True

    def doubleClicked(self, vobj):
        if Gui.Control.activeDialog():
            return False
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def setupContextMenu(self, vobj, menu):
        obj = vobj.Object
        part = util.part_of(obj)
        a = menu.addAction(QtGui.QIcon(self.getIcon()), "Edit Feature")
        a.triggered.connect(lambda: Gui.ActiveDocument.setEdit(obj.Name, 0))
        if part is not None:
            a = menu.addAction("Rollback")
            a.triggered.connect(lambda: _roll(part, util.features(part)[
                max(0, util.features(part).index(obj) - 1)] if util.features(part).index(obj)
                else None))
            a = menu.addAction("Roll to End")
            a.triggered.connect(lambda: _roll(part, "end"))
        a = menu.addAction("Unsuppress" if obj.Suppressed else "Suppress")
        a.triggered.connect(lambda: _toggle_suppress(obj))
        if obj.ErrorMessage:
            a = menu.addAction("What's Wrong?")
            a.triggered.connect(lambda: _show_error(obj))
        return True

    def canDropObjects(self):
        return True

    def canDropObject(self, obj):
        """The rollback bar, or another feature of the part to reorder (as in
        SolidWorks: drop a feature on one to put it after that one), when no
        feature would come before one it uses."""
        if util.role(obj) == "rollback":
            return True
        me = getattr(self, "Object", None)
        part = util.part_of(me) if me is not None else None
        if part is None or obj is me or not util.is_feature(obj) or util.part_of(obj) is not part:
            return False
        return part_mod.can_move(part, obj, _index_after(part, obj, me))[0]

    def dropObject(self, vobj, obj):
        part = util.part_of(vobj.Object)
        if part is None:
            return
        if util.role(obj) == "rollback":
            _roll(part, vobj.Object)
            return
        doc = part.Document
        doc.openTransaction("Reorder")
        try:
            part_mod.move_feature(part, obj, _index_after(part, obj, vobj.Object))
        except ValueError as e:
            App.Console.PrintWarning("Solid Design: {}\n".format(e))
            doc.abortTransaction()
            return
        doc.recompute()
        doc.commitTransaction()

    def canDragAndDropObject(self, obj):
        # The drop does the whole move (reorder or roll); nothing is dragged out.
        return False

    def onDelete(self, vobj, subelements):
        part = util.part_of(vobj.Object)
        if part is not None:
            part_mod.remove_feature(part, vobj.Object)
        return True

    def canDelete(self, obj):
        """Deleting the feature before this one is safe: this one is relinked to
        the one before that (so FreeCAD needn't warn that it "might break")."""
        return _is_base_of(getattr(self, "Object", None), obj)


def _index_after(part, moving, target):
    """The index among the other features that puts *moving* right after *target*."""
    others = [f for f in util.features(part) if f is not moving]
    return others.index(target) + 1 if target in others else len(others)


def _is_base_of(feature, obj):
    try:
        return obj is not None and feature is not None and feature.BaseFeature is obj
    except Exception:
        return False


def panel_class(obj):
    t = getattr(getattr(obj, "Proxy", None), "TYPE", "")
    if t == "Extrude":
        from .extrude_panel import ExtrudePanel
        return ExtrudePanel
    if t == "Revolve":
        from .revolve_panel import RevolvePanel
        return RevolvePanel
    if t == "Fillet":
        from .dressup_panel import FilletPanel
        return FilletPanel
    if t == "Chamfer":
        from .dressup_panel import ChamferPanel
        return ChamferPanel
    if t == "Draft":
        from .draft_panel import DraftPanel
        return DraftPanel
    if t == "Rib":
        from .rib_panel import RibPanel
        return RibPanel
    if t == "Thread":
        from .thread_panel import ThreadPanel
        return ThreadPanel
    if t in ("CurvePattern", "SketchPattern", "TablePattern", "FillPattern"):
        from . import pattern_panels as pp
        return {"CurvePattern": pp.CurvePatternPanel, "SketchPattern": pp.SketchPatternPanel,
                "TablePattern": pp.TablePatternPanel, "FillPattern": pp.FillPatternPanel}[t]
    if t in ("Scale", "Flex"):
        from . import surface_panel as su
        return {"Scale": su.ScalePanel, "Flex": su.FlexPanel}[t]
    if t in ("Ruled", "Radiate", "Untrim", "MidSurface", "SurfaceCut", "ReplaceFace"):
        from . import surface_panel as su
        return {"Ruled": su.RuledPanel, "Radiate": su.RadiatePanel, "Untrim": su.UntrimPanel,
                "MidSurface": su.MidSurfacePanel, "SurfaceCut": su.CutWithSurfacePanel,
                "ReplaceFace": su.ReplaceFacePanel}[t]
    if t in ("Knit", "Planar", "Filled", "Trim", "Extend", "DeleteFace", "Thicken",
             "Intersect", "Dome", "Wrap"):
        from . import surface_panel as su
        return {"Knit": su.KnitPanel, "Planar": su.PlanarPanel, "Filled": su.FilledPanel,
                "Trim": su.TrimPanel, "Extend": su.ExtendPanel,
                "DeleteFace": su.DeleteFacePanel, "Thicken": su.ThickenPanel,
                "Intersect": su.IntersectPanel, "Dome": su.DomePanel,
                "Wrap": su.WrapPanel}[t]
    if t in ("OffsetSurface", "MoveFace", "SplitLine"):
        from . import faceops_panel as fp
        return {"OffsetSurface": fp.OffsetSurfacePanel, "MoveFace": fp.MoveFacePanel,
                "SplitLine": fp.SplitLinePanel}[t]
    from . import sweep_panel as sp
    from . import tool_panels as tp
    return {"Sweep": sp.SweepPanel, "Loft": sp.LoftPanel, "Shell": sp.ShellPanel,
            "Boundary": sp.BoundaryPanel,
            "Combine": tp.CombinePanel, "DeleteBody": tp.DeleteBodyPanel,
            "Split": tp.SplitPanel, "MoveCopy": tp.MoveCopyPanel,
            "LinearPattern": tp.LinearPatternPanel, "CircularPattern": tp.CircularPatternPanel,
            "Mirror": tp.MirrorPanel, "Hole": tp.HolePanel}.get(t)


def _toggle_suppress(obj):
    doc = obj.Document
    doc.openTransaction("Suppress")
    obj.Suppressed = not obj.Suppressed
    doc.recompute()
    doc.commitTransaction()


def _show_error(obj):
    # Shown in place: the panel opens with the error at the top and the
    # offending box highlighted (spec 4.1: no separate "What's Wrong" dialog).
    Gui.ActiveDocument.setEdit(obj.Name, 0)


# =================================================================== folders, bodies, bar

class FolderVP(_DrawsNothing):
    def __init__(self, vobj):
        self.Object = vobj.Object
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        self._add_group_mode(vobj)
        self._live = False
        from PySide6 import QtCore
        QtCore.QTimer.singleShot(0, self._go_live)

    def _go_live(self):
        self._live = True

    def getIcon(self):
        return ":/icons/folder.svg"        # FreeCAD's own folder

    def claimChildren(self):
        obj = self.Object
        part = part_mod.owner_part(obj)
        if part is None:
            return []
        if obj.Kind == part_mod.ORIGIN_FOLDER:
            # The planes, then the origin point; the axes too (hidden in the tree).
            origin = list(part.Origin)
            return [o for o in origin if o.TypeId == "Part::DatumPlane"] + \
                [o for o in origin if o.TypeId == "Part::DatumPoint"] + \
                [o for o in origin if o.TypeId == "Part::DatumLine"]
        ids = list(part.BodyIds)
        views = [v for v in part_mod.body_views(part) if v.Kind == obj.Kind or
                 (not v.Kind and obj.Kind == "solid")]
        views.sort(key=lambda v: ids.index(v.BodyId) if v.BodyId in ids else 1e9)
        return views

    def onChanged(self, vobj, prop):
        """Hiding or showing the folder hides or shows its bodies, as in SolidWorks."""
        if prop != "Visibility" or not getattr(self, "_live", False):
            return      # not while FreeCAD sets the folder up (it would show the planes)
        obj = getattr(self, "Object", None)
        try:
            if obj is None or obj.Document.Restoring:     # loading a file
                return
        except Exception:
            return
        try:
            on = vobj.Visibility
            for v in self.claimChildren():
                if v.TypeId == "Part::DatumLine":
                    continue        # the origin axes stay hidden
                if v.ViewObject is not None and v.ViewObject.Visibility != on:
                    v.ViewObject.Visibility = on
        except Exception:
            pass

    def onDelete(self, vobj, sub):
        return False


# Bodies are drawn finer than FreeCAD's default (0.5 % of the size, 28.5 degrees),
# which leaves small holes and fillets visibly faceted.
BODY_DEVIATION = 0.05           # percent of the body's size
BODY_ANGULAR = 8.0              # degrees


def fine_tessellation(vobj):
    """Draw a body finer, once: the marker property says it was done, so a value
    the user sets afterwards is kept."""
    try:
        if "SDFineMesh" in vobj.PropertiesList:
            return
        vobj.Deviation = min(vobj.Deviation, BODY_DEVIATION)
        vobj.AngularDeflection = min(float(vobj.AngularDeflection), BODY_ANGULAR)
        vobj.addProperty("App::PropertyBool", "SDFineMesh", "Display Options",
                         "Solid Design has set a fine tessellation", 0, False, True)
        vobj.SDFineMesh = True
    except Exception:
        pass


class BodyVP(_Stateless):
    def __init__(self, vobj):
        self.Object = vobj.Object
        vobj.Proxy = self
        fine_tessellation(vobj)

    def attach(self, vobj):
        self.Object = vobj.Object
        # Bodies from older files: once their properties are restored.
        QtCore.QTimer.singleShot(0, lambda: fine_tessellation(vobj))

    def getIcon(self):
        obj = getattr(self, "Object", None)
        kind = getattr(obj, "Kind", "solid") if obj is not None else "solid"
        return icon("BodySolid" if kind != "surface" else "BodySurface")

    def setupContextMenu(self, vobj, menu):
        obj = vobj.Object
        # SolidWorks' body context menu: the body tools, with this body picked.
        for cmd, text in (("SD_DeleteBody", "Delete/Keep Body"),
                          ("SD_MoveCopy", "Move/Copy Body"), ("SD_Combine", "Combine"),
                          ("SD_Split", "Split")):
            a = menu.addAction(QtGui.QIcon(icon(cmd[3:])), text)
            a.triggered.connect(lambda _checked=False, c=cmd: _run_on(obj, c))
        menu.addSeparator()
        a = menu.addAction("Hide" if vobj.Visibility else "Show")
        a.triggered.connect(lambda: setattr(vobj, "Visibility", not vobj.Visibility))
        a = menu.addAction("Isolate")
        a.triggered.connect(lambda: _isolate(obj))
        a = menu.addAction("Rename")
        a.triggered.connect(lambda: Gui.runCommand("Std_Rename"))
        return True

    def canDelete(self, obj):
        # Deleting the part removes its bodies too.
        return obj is part_mod.source_part(getattr(self, "Object", None))

    def onDelete(self, vobj, sub):
        # Bodies are removed with Delete/Keep Body, a feature in the history: the
        # Delete key opens it with the body picked, as in SolidWorks.
        if not Gui.Control.activeDialog():
            if not _to_delete:
                QtCore.QTimer.singleShot(0, _delete_bodies)
            _to_delete.append(vobj.Object)
        return False


_to_delete = []


def _delete_bodies():
    """Delete/Keep Body with every body the Delete key was pressed on."""
    bodies = list(_to_delete)
    del _to_delete[:]
    try:
        Gui.Selection.clearSelection()
        for b in bodies:
            Gui.Selection.addSelection(b.Document.Name, b.Name)
        Gui.runCommand("SD_DeleteBody")
    except Exception:
        pass


def _run_on(body, cmd):
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(body.Document.Name, body.Name)
    Gui.runCommand(cmd)


def _isolate(body):
    part = part_mod.source_part(body)
    for v in part_mod.body_views(part):
        v.ViewObject.Visibility = v is body


class RollbackVP(_DrawsNothing):
    def __init__(self, vobj):
        self.Object = vobj.Object
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        self._add_group_mode(vobj)

    def getIcon(self):
        return icon("RollbackBar")

    def setupContextMenu(self, vobj, menu):
        """SolidWorks' rollback bar menu."""
        part = part_mod.owner_part(vobj.Object)
        if part is None:
            return
        feats = util.features(part)
        tip = part.Tip
        i = feats.index(tip) if tip in feats else -1      # -1: before every feature
        if i >= 0:
            a = menu.addAction("Roll to Previous")
            a.setToolTip("Move the bar up past one feature")
            a.triggered.connect(lambda _c=False: _roll(part, feats[i - 1] if i > 0 else None))
        if i < len(feats) - 1:
            a = menu.addAction("Roll Forward")
            a.setToolTip("Move the bar down past one feature")
            a.triggered.connect(lambda _c=False: _roll(part, feats[i + 1]))
            a = menu.addAction("Roll to End")
            a.setToolTip("Move the bar below every feature")
            a.triggered.connect(lambda _c=False: _roll(part, feats[-1]))

    def onDelete(self, vobj, sub):
        return False


# =================================================================== attaching

AXIS_COLOR = (0.15, 0.35, 0.75)


def _dashed(vobj):
    """Axes from older files: dashed, once loaded (a style the user chose stays)."""
    try:
        if vobj.DrawStyle == "Solid":
            vobj.DrawStyle = "Dashed"
            vobj.LineColor = AXIS_COLOR + (0.0,)
    except Exception:
        pass


class RefGeomVP(_Stateless):
    """Plane and Axis: drawn (translucent plane, axis line), editable like features."""

    def __init__(self, vobj):
        self.Object = vobj.Object
        vobj.Proxy = self
        self.attach(vobj)       # FreeCAD calls attach() only when a file is opened

    def attach(self, vobj):
        self.Object = vobj.Object
        if getattr(self, "_overlay", None) is not None:
            return
        self._overlay = None
        if getattr(vobj.Object.Proxy, "KIND", "") == "axis":
            self._make_overlay(vobj)
            QtCore.QTimer.singleShot(0, lambda: _dashed(vobj))

    # An axis is a dashed line drawn on top of everything, so it shows through
    # the bodies (as a centerline does). The overlay goes in every display mode,
    # so hiding the axis hides it too.
    def _make_overlay(self, vobj):
        try:
            from pivy import coin
            ov = coin.SoAnnotation()
            col = coin.SoBaseColor()
            col.rgb.setValue(*AXIS_COLOR)
            style = coin.SoDrawStyle()
            style.lineWidth = 2.0
            style.linePattern = 0xF0F0
            pick = coin.SoPickStyle()
            pick.style = coin.SoPickStyle.UNPICKABLE
            self._coords = coin.SoCoordinate3()
            line = coin.SoLineSet()
            for n in (pick, col, style, self._coords, line):
                ov.addChild(n)
            sw = vobj.SwitchNode
            for i in range(sw.getNumChildren()):
                sw.getChild(i).addChild(ov)
            self._overlay = ov
            self._update_overlay(vobj.Object)
        except Exception as e:
            App.Console.PrintLog("Solid Design: axis overlay: {}\n".format(e))
            self._overlay = None

    def _update_overlay(self, obj):
        if getattr(self, "_overlay", None) is None:
            return
        try:
            edges = obj.Shape.Edges
            if not edges:
                self._coords.point.setNum(0)
                return
            inv = obj.Placement.inverse()
            pts = [inv.multVec(edges[0].Vertexes[0].Point), inv.multVec(edges[0].Vertexes[-1].Point)]
            self._coords.point.setValues(0, 2, [(p.x, p.y, p.z) for p in pts])
        except Exception:
            pass

    def canDelete(self, obj):
        return _is_base_of(getattr(self, "Object", None), obj)

    def claimChildren(self):
        """A helix holds its circle's sketch (when nothing else uses it)."""
        obj = getattr(self, "Object", None)
        if obj is None or getattr(obj.Proxy, "KIND", "") != "helix":
            return []
        v = obj.Reference1
        sk = v[0] if v and v[0] is not None else None
        if sk is None or not sk.TypeId.startswith("Sketcher::SketchObject"):
            return []
        users = [o for o in sk.InList if util.is_feature(o) or util.role(o) == "refgeom"]
        return [sk] if users == [obj] else []

    def getIcon(self):
        obj = getattr(self, "Object", None)
        kind = getattr(getattr(obj, "Proxy", None), "KIND", "plane")
        base = {"plane": "Plane", "axis": "Axis", "point": "Point",
                "csys": "CoordinateSystem", "helix": "Helix"}.get(kind, "Plane")
        if kind == "curve":
            base = {"projected": "ProjectedCurve", "composite": "CompositeCurve",
                    "xyz": "CurveXYZ", "points": "CurvePoints"}.get(obj.Proxy.CURVE, "Helix")
        return _state_icon(base, obj) if obj is not None else icon(base)

    def updateData(self, obj, prop):
        if prop in ("ErrorMessage", "WarningMessage", "RolledBack"):
            _refresh_icon(obj.ViewObject)
            if prop == "RolledBack":
                obj.ViewObject.Visibility = not obj.RolledBack
        elif prop in ("Shape", "Placement"):
            self._update_overlay(obj)
            if prop == "Shape" and getattr(obj.Proxy, "KIND", "") == "csys":
                _csys_colours(obj.ViewObject)

    def setEdit(self, vobj, mode=0):
        if mode != 0:
            return None
        if getattr(vobj.Object.Proxy, "KIND", "") == "curve":
            from .curve_panel import panel_for
            Gui.Control.showDialog(panel_for(vobj.Object)(vobj.Object,
                                                          getattr(self, "_new", False)))
        else:
            from .refgeom_panel import RefGeomPanel
            Gui.Control.showDialog(RefGeomPanel(vobj.Object, getattr(self, "_new", False)))
        self._new = False
        return True

    def unsetEdit(self, vobj, mode=0):
        return True

    def doubleClicked(self, vobj):
        if Gui.Control.activeDialog():
            return False
        Gui.ActiveDocument.setEdit(vobj.Object.Name, 0)
        return True

    def setupContextMenu(self, vobj, menu):
        obj = vobj.Object
        a = menu.addAction(QtGui.QIcon(self.getIcon()), "Edit Feature")
        a.triggered.connect(lambda: Gui.ActiveDocument.setEdit(obj.Name, 0))
        return True


def attach_refgeom(obj, new=False):
    vp = RefGeomVP(obj.ViewObject)
    vp._new = new
    vo = obj.ViewObject
    kind = obj.Proxy.KIND
    try:
        vo.Transparency = 75 if kind == "plane" else 0
        vo.LineWidth = 2.0
        vo.LineColor = (0.2, 0.45, 0.85, 0.0) if kind == "plane" else AXIS_COLOR + (0.0,)
        vo.PointSize = 1.0
        if kind == "axis":
            vo.DrawStyle = "Dashed"
        if kind == "point":
            vo.PointSize = 7.0
            vo.PointColor = AXIS_COLOR + (0.0,)
        if kind == "csys":
            vo.LineWidth = 3.0
            _csys_colours(vo)
        if kind in ("helix", "curve"):
            vo.LineWidth = 2.5
            vo.LineColor = (0.85, 0.45, 0.05, 0.0)
    except Exception:
        pass


# X red, Y green, Z blue, as FreeCAD's own axis cross.
CSYS_COLOURS = [(0.85, 0.15, 0.15, 0.0), (0.15, 0.65, 0.2, 0.0), (0.15, 0.35, 0.85, 0.0)]


def _csys_colours(vo):
    try:
        if len(vo.Object.Shape.Edges) == 3:
            vo.LineColorArray = CSYS_COLOURS
    except Exception:
        pass


def attach_part(obj):
    PartVP(obj.ViewObject)
    _show_nothing(obj.ViewObject)


def attach_feature(obj, new=False):
    vp = FeatureVP(obj.ViewObject)
    vp._new = new
    _show_nothing(obj.ViewObject)


def attach_folder(obj):
    if obj is not None:
        FolderVP(obj.ViewObject)
        _show_nothing(obj.ViewObject)


def attach_body(obj):
    BodyVP(obj.ViewObject)


def attach_rollback(obj):
    RollbackVP(obj.ViewObject)
    _show_nothing(obj.ViewObject)
