# SPDX-License-Identifier: LGPL-2.1-or-later
"""Runs inside ``freecadcmd`` to read what the workbench offers, from its code.

Started by catalog.py with:

    SD_REPO          the repository
    SD_CATALOG_OUT   the JSON file to write

FreeCAD's command line has no GUI module, so ``FreeCADGui`` is replaced here by a
stand-in that records what the workbench registers: its commands, toolbars and
menus. Nothing is drawn and no document is made. The feature classes declare
their properties to a recorder (as the command line's completion does), which
gives each tool's options with their types, choices, defaults and help text.

The output is plain data (see catalog.py for its shape). Writes ``{"error": ...}``
when something fails, so the build can say what.
"""

import json
import os
import sys
import traceback
import types

REPO = os.environ["SD_REPO"]
OUT = os.environ["SD_CATALOG_OUT"]


# -- the FreeCADGui stand-in -------------------------------------------------------

class _Any(object):
    """Anything: every attribute is another _Any, calling one returns one."""

    def __init__(self, name="Gui"):
        object.__setattr__(self, "_name", name)

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any(self._name + "." + name)

    def __setattr__(self, name, value):
        pass

    def __call__(self, *a, **k):
        return _Any(self._name + "()")

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    def __len__(self):
        return 0


#: Tools that make the same feature as another (a surface from Sweep...).
SAME_FEATURE = {"SD_SweptSurface": "SD_Sweep", "SD_LoftedSurface": "SD_Loft",
                "SD_BoundarySurface": "SD_Boundary"}
#: Tools whose feature class the command line can't find by TYPE or KIND.
FEATURE_CLASSES = {
    "SD_Point": ("app.refgeom", "RefPointProxy"),
    "SD_CenterOfMass": ("app.refgeom", "CenterOfMassProxy"),
    "SD_ProjectedCurve": ("app.refgeom", "ProjectedCurveProxy"),
    "SD_CompositeCurve": ("app.refgeom", "CompositeCurveProxy"),
    "SD_CurveXYZ": ("app.refgeom", "XYZCurveProxy"),
    "SD_CurvePoints": ("app.refgeom", "PointsCurveProxy"),
}

COMMANDS = {}           # name -> the command object, in registration order
WORKBENCHES = []


class _Workbench(object):
    """Records what a workbench's Initialize lays out."""

    def __init__(self):
        self.toolbars = []      # [(name, [commands])]
        self.menus = []         # [(path, [commands])]

    def appendToolbar(self, name, cmds):
        self.toolbars.append((name, list(cmds)))

    def appendMenu(self, path, cmds):
        path = [path] if isinstance(path, str) else list(path)
        self.menus.append((path, list(cmds)))

    def appendContextMenu(self, *a, **k):
        pass


class _CommandInfo(object):
    def __init__(self, name):
        self.name = name

    def getInfo(self):
        res = COMMANDS[self.name].GetResources()
        return {"name": self.name, "menuText": res.get("MenuText", ""),
                "toolTip": res.get("ToolTip", ""), "pixmap": res.get("Pixmap", ""),
                "shortcut": res.get("Accel", "")}

    def getAction(self):
        return []

    def isActive(self):
        return False


def _gui_module():
    gui = types.ModuleType("FreeCADGui")
    anything = _Any()

    def getattr_(name):
        return getattr(anything, name)

    gui.__getattr__ = getattr_
    gui.Workbench = _Workbench
    gui.addWorkbench = WORKBENCHES.append
    gui.addCommand = lambda name, cmd: COMMANDS.__setitem__(name, cmd)
    gui.listCommands = lambda: list(COMMANDS)
    gui.Command = types.SimpleNamespace(get=lambda name: _CommandInfo(name) if name in COMMANDS
                                        else None)
    gui.ActiveDocument = None
    gui.addIconPath = gui.addLanguagePath = gui.addPreferencePage = lambda *a, **k: None
    return gui


def _install_stand_ins():
    sys.modules["FreeCADGui"] = _gui_module()
    # The sketch tool imports Sketcher's GUI for its icon; there is none here.
    sys.modules["SketcherGui"] = types.ModuleType("SketcherGui")
    sys.path.insert(0, REPO)
    import freecad  # FreeCAD's own namespace package: add the workbench to it

    if os.path.join(REPO, "freecad") not in list(freecad.__path__):
        freecad.__path__.insert(0, os.path.join(REPO, "freecad"))


# -- reading it ------------------------------------------------------------------------

def _initialize(wb):
    """Run the workbench's Initialize with the GUI hooks (observers, view
    filters, the badge...) turned off: only its toolbars, menus and commands
    are wanted."""
    import importlib

    for mod in ("ref_labels", "health_badge", "sketch_edit", "temp_axis", "instant3d",
                "context_bar", "command_line", "view_menus", "reveal"):
        m = importlib.import_module("freecad.SolidDesign.gui." + mod)
        if hasattr(m, "install"):
            m.install = lambda *a, **k: None
    from freecad.SolidDesign.app import part

    part.install_observer = lambda *a, **k: None
    wb.Initialize()


class _Recorder(object):
    """Stands in for a document object while a feature class declares its
    properties (see command_line._Recorder), keeping their help text too."""

    def __init__(self):
        d = object.__setattr__
        d(self, "props", {})     # name -> dict, in declaration order
        d(self, "values", {})

    @property
    def PropertiesList(self):
        return list(self.props)

    def addProperty(self, type_id, name, group="", doc="", mode=0, *a, **k):
        self.props[name] = {"type": type_id.replace("App::Property", ""), "group": group or "",
                            "doc": doc or "", "hidden": mode == 2, "readonly": mode == 1}
        return self

    def setEditorMode(self, name, mode):
        p = self.props.get(name)
        if p is None:
            return
        modes = [mode] if not isinstance(mode, (list, tuple)) else list(mode)
        if 2 in modes or "Hidden" in modes:
            p["hidden"] = True
        if 1 in modes or "ReadOnly" in modes:
            p["readonly"] = True

    def setPropertyStatus(self, name, status):
        self.setEditorMode(name, status)

    def getPropertyByName(self, name):
        return self.values.get(name)

    def __setattr__(self, name, value):
        p = self.props.get(name)
        if p is not None and p["type"] == "Enumeration" and isinstance(value, (list, tuple)):
            p["choices"] = [str(v) for v in value]
            return
        self.values[name] = value

    def __getattr__(self, name):
        if name in self.values:
            return self.values[name]
        return lambda *a, **k: None


def _plain(value):
    """A default value as JSON: numbers, text, yes/no; quantities as their number."""
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, str)):
        return value
    v = getattr(value, "Value", None)
    if isinstance(v, (int, float)):
        return v
    if isinstance(value, (list, tuple)) and all(isinstance(x, (int, float, str)) for x in value):
        return list(value)
    return None


def _properties(cls):
    rec = _Recorder()
    try:
        cls.setup(cls.__new__(cls), rec)
    except Exception:
        pass                        # what was declared before it stopped still counts
    out = []
    for name, p in rec.props.items():
        entry = dict(p, name=name)
        if name in rec.values:
            d = _plain(rec.values[name])
            if d is not None:
                entry["default"] = d
            elif p["type"] == "Enumeration" and isinstance(rec.values[name], str):
                entry["default"] = rec.values[name]
        if p["type"] == "Enumeration" and "default" not in entry and p.get("choices"):
            entry["default"] = p["choices"][0]
        out.append(entry)
    return out


def _command(name, cmd):
    try:
        res = cmd.GetResources() or {}
    except Exception as e:
        res = {"MenuText": name, "ToolTip": "", "_error": str(e)}
    entry = {
        "name": name,
        "label": str(res.get("MenuText", "")).replace("&", ""),
        "tooltip": str(res.get("ToolTip", "")),
        "pixmap": str(res.get("Pixmap", "")),
        "shortcut": str(res.get("Accel", "")),
        "checkable": "Checkable" in res,
        "class": type(cmd).__name__,
        "doc": (type(cmd).__doc__ or "").strip(),
    }
    if hasattr(cmd, "GetCommands"):
        try:
            entry["group"] = list(cmd.GetCommands())
        except Exception:
            entry["group"] = []
    pix = entry["pixmap"]
    if pix.startswith(REPO):
        entry["pixmap"] = os.path.relpath(pix, REPO)
    return entry


def main():
    _install_stand_ins()
    import freecad.SolidDesign as sd
    import freecad.SolidDesign.init_gui  # noqa: F401  defines and adds the workbench

    wb = WORKBENCHES[0]
    _initialize(wb)

    from freecad.SolidDesign.app import health
    from freecad.SolidDesign.gui import command_line, command_search, line_ex, line_help

    commands = [_command(n, c) for n, c in COMMANDS.items()]
    by_tool = command_line._proxy_classes()
    for cmd, same in SAME_FEATURE.items():
        by_tool.setdefault(cmd, by_tool.get(same))
    import importlib

    for cmd, (mod, name) in FEATURE_CLASSES.items():
        by_tool.setdefault(cmd, getattr(importlib.import_module("freecad.SolidDesign." + mod), name))
    features = {}
    for cmd, cls in by_tool.items():
        if cls is None:
            continue
        features[cmd] = {"class": cls.__name__, "module": cls.__module__,
                         "type": getattr(cls, "TYPE", "") or "", "kind": getattr(cls, "KIND", "") or "",
                         "doc": (cls.__doc__ or "").strip(),
                         "properties": _properties(cls)}
    data = {
        "version": sd.__version__,
        "workbench": {"name": wb.MenuText, "tooltip": wb.ToolTip,
                      "icon": os.path.relpath(wb.Icon, REPO),
                      "toolbars": [{"name": n, "commands": c} for n, c in wb.toolbars],
                      "menus": [{"path": p, "commands": c} for p, c in wb.menus]},
        "commands": commands,
        "features": features,
        "command_line": {
            "main": command_line.MAIN,
            "keywords": {n: kw for n, kw, _l, _t in command_line.tools()},
            "skip_groups": list(command_line.SKIP_GROUPS),
            "value_types": list(command_line.VALUE_TYPES),
            "search_shortcut": command_search.SHORTCUT,
            "cheat_sheet": [{"topic": t, "title": title, "rows": [list(r) for r in rows]}
                            for t, title, rows in line_help.HELP],
            "commands": {n: list(v) for n, v in sorted(line_ex.COMMANDS.items())},
        },
        "health": {"tiny_edge": health.TINY_EDGE, "sliver": health.SLIVER},
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, sort_keys=False)


try:
    main()
except Exception:
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"error": traceback.format_exc()}, f)
os._exit(0)
