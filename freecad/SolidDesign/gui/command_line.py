# SPDX-License-Identifier: LGPL-2.1-or-later
"""The command line (":") and repeat ("."): a keyboard layer for power users.

Neither touches normal use: both act only on a key typed in the 3D view, in Solid
Design, with no tool or sketch open.

":" opens a bar along the bottom of the 3D view. Type a tool and what to set:

    fillet 2                    the tool's main value(s), in order
    extrude 10 cut              a word picks an option (Mode: Cut)
    extrude throughall          ... spaces and case don't matter
    lp 20 4                     tools match fuzzily (Linear Pattern: spacing 20, 4 of them)
    chamfer d=1.5 flip          name=value sets any option; a yes/no option by its name
    fillet Width/2              a VarSet's variable makes a live expression
    fillet =Width/2 + 1mm       "=" for any FreeCAD expression; units work anywhere

What it works on: the selection; with nothing selected, what was under the pointer
when ":" was pressed; with neither, the tool's panel opens with the values in,
waiting for picks. When the feature builds cleanly it's made (one undo step) with
no panel; when it doesn't, its panel opens with the values in and the error shown.

Tab and Shift+Tab complete (tools, options, choices, variables); Up and Down go
through the history (kept between sessions); Escape closes.

"." repeats the last feature made (from the bar, or OK in a panel) with the same
settings, on the selection or what's under the pointer.
"""

import FreeCAD as App
import FreeCADGui as Gui

PARAMS = "User parameter:BaseApp/Preferences/Mod/SolidDesign"
HISTORY_MAX = 100

# The values a tool takes in order, without naming them.
MAIN = {
    "SD_Fillet": ["Radius"], "SD_Chamfer": ["Distance"],
    "SD_Extrude": ["Depth", "Depth2"], "SD_ExtrudedSurface": ["Depth", "Depth2"],
    "SD_Revolve": ["Angle", "Angle2"], "SD_RevolvedSurface": ["Angle", "Angle2"],
    "SD_Shell": ["Thickness"], "SD_Dome": ["Distance"], "SD_Draft": ["Angle"],
    "SD_Rib": ["Thickness"], "SD_Wrap": ["Depth"], "SD_HoleWizard": ["Depth"],
    "SD_Thread": ["Length"], "SD_CosmeticThread": ["Length"],
    "SD_LinearPattern": ["Spacing", "Instances"],
    "SD_CircularPattern": ["Angle", "Instances"], "SD_CurvePattern": ["Instances"],
    "SD_FillPattern": ["InstanceSpacing"], "SD_OffsetSurface": ["Distance"],
    "SD_MoveFace": ["Distance"], "SD_Thicken": ["Thickness"],
    "SD_ExtendSurface": ["Distance"], "SD_RuledSurface": ["Distance"],
    "SD_RadiateSurface": ["Distance"], "SD_MoveCopy": ["DeltaX", "DeltaY", "DeltaZ"],
    "SD_MountingBoss": ["Height"], "SD_SnapHook": ["Height"], "SD_Plane": ["Distance"],
    "SD_Helix": ["Height"], "SD_Deform": ["Distance"],
}

# Feature types whose command isn't "SD_" + the type (or + "Surface").
TYPE_COMMANDS = {"Hole": "SD_HoleWizard", "Flatten": "SD_SurfaceFlatten"}
KIND_COMMANDS = {"plane": "SD_Plane", "axis": "SD_Axis", "csys": "SD_CoordinateSystem",
                 "helix": "SD_Helix", "bbox": "SD_BoundingBox",
                 "cosmetic": "SD_CosmeticThread"}

# Properties never set from the line (the feature's own bookkeeping).
SKIP_GROUPS = ("Base", "Result")
VALUE_TYPES = ("Length", "Distance", "Angle", "Quantity", "Float", "Integer", "Percent",
               "Area", "Volume")


# ------------------------------------------------------------------ helpers

def norm(s):
    """Lower case, letters and digits only: "Through All - Both" -> "throughallboth"."""
    return "".join(c for c in s.lower() if c.isalnum())


def keyword(label):
    return norm(label)


def _kind(type_id):
    """"enum", "bool", "int", "num", or None (not settable from the line)."""
    t = type_id.replace("App::Property", "")
    if t == "Enumeration":
        return "enum"
    if t == "Bool":
        return "bool"
    if t.startswith("Integer"):
        return "int"
    if any(t.startswith(v) for v in VALUE_TYPES):
        return "num"
    return None


# ------------------------------------------------------------------ tools

def tools():
    """[(command, keyword, label, tooltip)] for the tools the line can run."""
    from . import command_search
    return [(n, keyword(label), label, tip)
            for n, label, tip, _pix, _on in command_search.entries()
            if n not in ("SD_ContextToolbar",)]


def find_tool(token, listing=None):
    """The command a typed tool name means, or None."""
    from . import command_search
    listing = listing if listing is not None else tools()
    t = norm(token)
    if not t:
        return None
    for n, kw, _l, _t in listing:
        if kw == t:
            return n
    ranked = command_search.rank(token, [(n, label, "") for n, _kw, label, _tip in listing])
    return ranked[0][0] if ranked else None


def command_for(obj):
    """The command that makes features like ``obj``, or None."""
    proxy = getattr(obj, "Proxy", None)
    t = getattr(proxy, "TYPE", "")
    have = set(Gui.listCommands())
    if t and t != "Feature":
        for c in (TYPE_COMMANDS.get(t), "SD_" + t, "SD_" + t + "Surface"):
            if c and c in have:
                return c
    k = getattr(proxy, "KIND", "")
    return KIND_COMMANDS.get(k)


# ------------------------------------------------------------------ options

class _Recorder(object):
    """Stands in for a document object while a feature class declares its
    properties, so a tool's options are known before there is a feature."""

    def __init__(self):
        d = object.__setattr__
        d(self, "_types", {})
        d(self, "_groups", {})
        d(self, "_enums", {})
        d(self, "_values", {})
        d(self, "_hidden", set())

    @property
    def PropertiesList(self):
        return list(self._types)

    def addProperty(self, type_id, name, group="", doc="", mode=0, *a, **k):
        self._types[name] = type_id
        self._groups[name] = group
        if mode == 2:
            self._hidden.add(name)
        return self

    def setEditorMode(self, name, mode):
        if mode == 2 or (isinstance(mode, (list, tuple)) and "Hidden" in mode):
            self._hidden.add(name)

    def __setattr__(self, name, value):
        if self._types.get(name, "").endswith("Enumeration") and isinstance(value, list):
            self._enums[name] = [str(v) for v in value]
        else:
            self._values[name] = value

    def __getattr__(self, name):
        if name in self._values:
            return self._values[name]
        return lambda *a, **k: None


_catalogs = {}


def _proxy_classes():
    """{command: the feature class it makes}, from the classes' TYPE (or KIND)."""
    import importlib
    import pkgutil
    from .. import app as app_pkg
    have = set(Gui.listCommands())
    out = {}
    for m in pkgutil.iter_modules(app_pkg.__path__):
        try:
            mod = importlib.import_module("freecad.SolidDesign.app." + m.name)
        except Exception:
            continue
        for v in vars(mod).values():
            if not isinstance(v, type) or not hasattr(v, "setup"):
                continue
            t = vars(v).get("TYPE") or getattr(v, "TYPE", "")
            k = vars(v).get("KIND", "")
            cmds = []
            if t and t != "Feature":
                cmds = [c for c in (TYPE_COMMANDS.get(t), "SD_" + t, "SD_" + t + "Surface")
                        if c and c in have]
            elif k in KIND_COMMANDS:
                cmds = [KIND_COMMANDS[k]]
            for c in cmds[:1]:
                out.setdefault(c, v)
    out.setdefault("SD_ExtrudedSurface", out.get("SD_Extrude"))
    out.setdefault("SD_RevolvedSurface", out.get("SD_Revolve"))
    return out


def catalog(cmd):
    """{option: (kind, choices or None)} that a tool's features take, for
    completion. Learned once, by letting the feature class declare its properties
    to a recorder (nothing is made)."""
    if cmd in _catalogs:
        return _catalogs[cmd]
    out = {}
    cls = _proxy_classes().get(cmd)
    if cls is not None:
        rec = _Recorder()
        try:
            cls.setup(cls.__new__(cls), rec)
        except Exception:
            pass                        # what was declared before it stopped still counts
        for name, type_id in rec._types.items():
            kind = _kind(type_id)
            if kind is None or rec._groups.get(name) in SKIP_GROUPS or name in rec._hidden:
                continue
            out[name] = (kind, rec._enums.get(name))
    _catalogs[cmd] = out
    return out


def settable(obj):
    """{option: (kind, choices or None)} of a feature."""
    out = {}
    for name in obj.PropertiesList:
        kind = _kind(obj.getTypeIdOfProperty(name))
        if kind is None or obj.getGroupOfProperty(name) in SKIP_GROUPS:
            continue
        try:
            if "Hidden" in obj.getEditorMode(name):
                continue
        except Exception:
            pass
        choices = None
        if kind == "enum":
            try:
                choices = list(obj.getEnumerationsOfProperty(name))
            except Exception:
                choices = []
        out[name] = (kind, choices)
    return out


# ------------------------------------------------------------------ values

def variables(doc):
    """{variable name: expression path} for the document's VarSets' variables."""
    out = {}
    if doc is None:
        return out
    base = {"Label", "Label2", "ExpressionEngine", "Visibility", "ExposedProperties"}
    for o in doc.Objects:
        if o.TypeId != "App::VarSet":
            continue
        for p in o.PropertiesList:
            if p not in base:
                out.setdefault(p, "{}.{}".format(o.Name, p))
    return out


def _identifiers(text):
    import re
    return re.findall(r"[A-Za-z_][A-Za-z_0-9]*", text)


def value_of(token, vars_):
    """("num", value in mm or degrees) for a number or quantity, ("expr", FreeCAD
    expression) for an expression or a variable, or None (not a value: a word)."""
    t = token.strip()
    if not t:
        return None
    if t.startswith("="):
        return ("expr", _bind(t[1:], vars_))
    try:
        return ("num", float(t))
    except ValueError:
        pass
    if t[0].isdigit() or t[0] in ".-+(":
        try:
            return ("num", float(App.Units.Quantity(t).Value))
        except Exception:
            return ("expr", _bind(t, vars_))
    if any(i in vars_ for i in _identifiers(t)):
        return ("expr", _bind(t, vars_))
    return None


def _bind(expr, vars_):
    """``expr`` with each VarSet variable named by its object (Width -> VarSet.Width)."""
    import re

    def sub(m):
        name = m.group(0)
        before = expr[:m.start()]
        if before.endswith("."):        # already qualified: VarSet.Width
            return name
        return vars_.get(name, name)
    return re.sub(r"[A-Za-z_][A-Za-z_0-9]*", sub, expr).strip()


# ------------------------------------------------------------------ parsing

class Line(object):
    """A parsed command line: ``cmd`` and what to set, still by name and word."""

    def __init__(self, text):
        self.text = text.strip()
        self.cmd = None
        self.values = []        # positional value tokens
        self.named = []         # (name, value token)
        self.words = []         # option words
        self.error = ""


def parse(text, listing=None):
    import shlex
    line = Line(text)
    t = line.text[1:] if line.text.startswith(":") else line.text
    try:
        tokens = shlex.split(t)
    except ValueError:
        tokens = t.split()
    if not tokens:
        line.error = "Type a tool's name, then its values."
        return line
    line.cmd = find_tool(tokens[0], listing)
    if line.cmd is None:
        line.error = "No tool called \"{}\".".format(tokens[0])
        return line
    for tok in tokens[1:]:
        if "=" in tok and not tok.startswith("=") and tok.split("=", 1)[0].strip():
            name, v = tok.split("=", 1)
            line.named.append((name.strip(), v.strip()))
        else:
            line.values.append(tok)
    return line


def _resolve(name, options):
    """The option a typed name means (exact, then a unique start, then the best
    fuzzy match), or an error string."""
    from . import command_search
    n = norm(name)
    by_norm = {norm(o): o for o in options}
    if n in by_norm:
        return by_norm[n]
    starts = [o for o in options if norm(o).startswith(n)]
    if len(starts) == 1:
        return starts[0]
    ranked = command_search.rank(name, [(o, o, "") for o in options])
    if ranked and (len(ranked) == 1 or not starts):
        return ranked[0][0]
    cands = starts or [r[0] for r in ranked]
    if not cands:
        return "No option \"{}\".".format(name)
    return "\"{}\" could be {}.".format(name, ", ".join(sorted(cands)[:5]))


def assignments(line, options, vars_, main):
    """[(option, kind, value)] for a parsed line against a feature's ``options``
    ({name: (kind, choices)}), or raise ValueError saying what's wrong. Options
    (choices and yes/no) come first: they decide which values count."""
    out_opts, out_vals = [], []
    main = [m for m in main if m in options]
    pos = 0
    for tok in line.values:
        v = value_of(tok, vars_)
        if v is not None:
            if pos >= len(main):
                raise ValueError("Too many values: name the rest (option=value).")
            out_vals.append((main[pos], v[0], v[1]))
            pos += 1
            continue
        out_opts.append(_word(tok, options))
    for name, tok in line.named:
        # The value says what kind of option it's for ("dra=3": DraftAngle, not Draft).
        if value_of(tok, vars_) is not None:
            kinds = ("num", "int")
        elif norm(tok) in ("true", "yes", "on", "false", "no", "off"):
            kinds = ("bool",)
        else:
            kinds = ("enum", "num", "int")
        fit = [o for o, (k, _c) in options.items() if k in kinds]
        prop = _resolve(name, fit) if fit else None
        if prop not in options:
            prop = _resolve(name, options)
        if prop not in options:
            raise ValueError(prop)
        kind, choices = options[prop]
        if kind == "enum":
            out_opts.append((prop, "enum", _choice(tok, choices, prop)))
        elif kind == "bool":
            b = norm(tok)
            if b not in ("true", "yes", "on", "1", "false", "no", "off", "0"):
                raise ValueError("{} is yes or no.".format(prop))
            out_opts.append((prop, "bool", b in ("true", "yes", "on", "1")))
        else:
            v = value_of(tok, vars_) or ("expr", _bind(tok, vars_))
            out_vals.append((prop, v[0], v[1]))
    return out_opts + out_vals


def _choice(tok, choices, prop):
    n = norm(tok)
    exact = [c for c in choices if norm(c) == n]
    starts = [c for c in choices if norm(c).startswith(n)]
    if exact:
        return exact[0]
    if len(starts) == 1:
        return starts[0]
    raise ValueError("{} is one of: {}.".format(prop, ", ".join(choices)))


def _word(tok, options):
    """An option word: a choice of one of the options (the first that has it), or a
    yes/no option by name ("no" in front for no)."""
    n = norm(tok)
    for prop, (kind, choices) in options.items():
        if kind == "enum" and any(norm(c) == n for c in choices or ()):
            return (prop, "enum", [c for c in choices if norm(c) == n][0])
    flag = n[2:] if n.startswith("no") else n
    for prop, (kind, _c) in options.items():
        if kind == "bool" and norm(prop) == flag:
            return (prop, "bool", not n.startswith("no") or norm(prop) == n)
    for prop, (kind, choices) in options.items():
        if kind == "enum":
            starts = [c for c in choices or () if norm(c).startswith(n)]
            if len(starts) == 1:
                return (prop, "enum", starts[0])
    raise ValueError("\"{}\" isn't a value, an option or a variable.".format(tok))


def apply(obj, assigns):
    """Set ``assigns`` on a feature."""
    for prop, kind, v in assigns:
        if kind == "expr":
            obj.setExpression(prop, v)
            continue
        obj.setExpression(prop, None)
        if kind == "int":
            v = int(round(v))
        elif kind == "num" and _kind(obj.getTypeIdOfProperty(prop)) == "int":
            v = int(round(v))
        setattr(obj, prop, v)


def snapshot(obj):
    """{option: (kind, value)} of a feature now (expressions as ("expr", text))."""
    exprs = dict(obj.ExpressionEngine)
    out = {}
    for prop, (kind, _c) in settable(obj).items():
        if prop in exprs:
            out[prop] = ("expr", exprs[prop])
            continue
        v = getattr(obj, prop)
        out[prop] = (kind, v.Value if hasattr(v, "Value") else v)
    return out


def changes(before, after):
    """The assignments that take a feature from ``before`` to ``after`` snapshots."""
    out = [(p, k, v) for p, (k, v) in after.items() if before.get(p) != (k, v)]
    order = {"enum": 0, "bool": 0}
    return sorted(out, key=lambda a: order.get(a[1], 1))


# ------------------------------------------------------------------ running

_last = [None]              # (command, assignments): what "." repeats
_under = [None]             # (doc, object, sub) under the pointer when ":" was pressed


def remember(cmd, assigns):
    if cmd:
        _last[0] = (cmd, list(assigns))


def remember_panel(obj, before):
    """A panel's OK made a feature: "." repeats it."""
    try:
        remember(command_for(obj), changes(before, snapshot(obj)))
    except Exception:
        pass


def _say(text):
    try:
        Gui.getMainWindow().statusBar().showMessage(text, 8000)
    except Exception:
        pass


def _pointer_target():
    """(doc, object, sub) under the pointer now, or None."""
    try:
        p = Gui.Selection.getPreselection()
        if p is not None and p.Object is not None:
            return (p.DocumentName, p.ObjectName, p.SubElementNames[0] if p.SubElementNames
                    else "")
    except Exception:
        pass
    return None


def _target(under):
    """With nothing selected, select what was under the pointer."""
    if Gui.Selection.getSelectionEx() or under is None:
        return
    try:
        Gui.Selection.addSelection(*under)
    except Exception:
        pass


def run(text, under=None):
    """Run a command line. Returns (feature or None, message)."""
    line = parse(text)
    if line.error:
        return None, line.error
    return execute(line.cmd, line=line, under=under)


def execute(cmd, line=None, assigns=None, under=None):
    """Run ``cmd`` on the selection (or ``under``), setting either a parsed ``line``
    or ready ``assigns``. With no feature panel to hold back (a tool that makes
    nothing), it just runs."""
    from . import viewproviders
    c = Gui.Command.get(cmd)
    if c is None:
        return None, "No such tool."
    _target(under)
    if not c.isActive():
        return None, "{} can't run now.".format(c.getInfo().get("menuText", cmd))
    made = []

    def hold(obj):
        made.append(obj)
        return True                     # don't open the panel yet
    viewproviders.EDIT_HOOK[0] = hold
    try:
        Gui.runCommand(cmd)
    finally:
        viewproviders.EDIT_HOOK[0] = None
    label = c.getInfo().get("menuText", cmd).replace("&", "")
    if not made:
        has = line is not None and (line.values or line.named)
        return None, ("{} takes no values." if has else "{}.").format(label)
    obj = made[0]
    doc = obj.Document
    before = snapshot(obj)
    try:
        if assigns is None:
            assigns = assignments(line, settable(obj), variables(doc), _main(cmd, obj))
        apply(obj, assigns)
        doc.recompute()
        err = obj.ErrorMessage
    except Exception as e:
        err = str(e) or type(e).__name__
    if err:
        _open(obj, before)
        return obj, "{}: {}".format(obj.Label, err)
    try:
        obj.ViewObject.Proxy._new = False
    except Exception:
        pass
    doc.commitTransaction()
    remember(cmd, assigns)
    Gui.Selection.clearSelection()
    return obj, "{} made.".format(obj.Label)


def _main(cmd, obj):
    main = MAIN.get(cmd)
    if main:
        return main
    try:
        from . import handles
        from ..app import util
        part = util.part_of(obj)
        specs = handles.SPECS.get(handles.spec_key(obj))
        return [s.prop for s in specs(obj, part)] if specs else []
    except Exception:
        return []


def _open(obj, before):
    """Open a feature's panel to finish it (the values are in). Its OK then makes
    "." repeat the line's values as well as what's changed in the panel."""
    try:
        obj.ViewObject.Proxy._new = True
    except Exception:
        pass
    Gui.ActiveDocument.setEdit(obj.Name, 0)
    from .sketch_panel import LAST
    p = LAST[0]
    if p is not None and getattr(p, "obj", None) is obj:
        p._before = before


def repeat():
    """"." : the last feature again, on the selection or what's under the pointer."""
    if _last[0] is None:
        _say("Nothing to repeat yet: make a feature first.")
        return None
    cmd, assigns = _last[0]
    obj, msg = execute(cmd, assigns=assigns, under=_pointer_target())
    _say(msg)
    return obj


# ------------------------------------------------------------------ completion

def completions(text):
    """[(text to put in place of the last word, what to show)] for the line so far."""
    from . import command_search
    parts = text.lstrip(":").split(" ")
    word = parts[-1]
    listing = tools()
    if len(parts) == 1:
        ranked = command_search.rank(word, [(n, label, tip) for n, _kw, label, tip in listing]) \
            if word else []
        kws = {n: kw for n, kw, _l, _t in listing}
        return [(kws[e[0]] + " ", u"{}  —  {}".format(kws[e[0]], e[1])) for e in ranked[:12]]
    cmd = find_tool(parts[0], listing)
    if cmd is None:
        return []
    opts = catalog(cmd)
    vars_ = variables(App.ActiveDocument)
    out = []
    if "=" in word:
        name, part = word.split("=", 1)
        prop = _resolve(name, opts) if opts else name
        kind, choices = opts.get(prop, (None, None))
        cands = [(c, "") for c in (choices or [])] if kind == "enum" else \
            [("yes", ""), ("no", "")] if kind == "bool" else []
        cands += [(v, "variable") for v in sorted(vars_)]
        for c, what in cands:
            if not part or norm(c).startswith(norm(part)) or command_search.fuzzy(part, c):
                shown = u"{}={}".format(prop, c) + (u"  —  " + what if what else "")
                out.append(("{}={} ".format(name, norm(c) if what == "" and kind == "enum"
                                            else c), shown))
        return out[:12]
    main = [m for m in MAIN.get(cmd, []) if m in opts]
    for prop, (kind, choices) in sorted(opts.items(), key=lambda kv: (kv[0] not in main, kv[0])):
        if not word or command_search.fuzzy(word, prop) is not None:
            out.append((prop + "=", u"{}=  —  {}{}".format(
                prop, kind, " (in order: %d)" % (main.index(prop) + 1) if prop in main else "")))
        if kind == "enum":
            for c in choices or ():
                if word and norm(c).startswith(norm(word)):
                    out.append((norm(c) + " ", u"{}  —  {}".format(c, prop)))
        if kind == "bool" and word and norm(prop).startswith(norm(word)):
            out.append((norm(prop) + " ", u"{}  —  yes".format(prop)))
    for v in sorted(vars_):
        if word and command_search.fuzzy(word, v) is not None:
            out.insert(0, (v + " ", u"{}  —  variable ({})".format(v, vars_[v])))
    return out[:12]


# ------------------------------------------------------------------ history

def history():
    try:
        text = App.ParamGet(PARAMS).GetString("CommandHistory", "")
    except Exception:
        return []
    return [h for h in text.split("\n") if h.strip()]


def add_history(line):
    h = [x for x in history() if x != line] + [line]
    try:
        App.ParamGet(PARAMS).SetString("CommandHistory", "\n".join(h[-HISTORY_MAX:]))
    except Exception:
        pass


# ------------------------------------------------------------------ the bar

_bar = [None]


def _alive(w):
    """Whether a Qt widget still exists on the C++ side (Qt deletes a widget with
    its parent: the bar goes with its 3D view's widget, which FreeCAD can replace)."""
    if w is None:
        return False
    try:
        import shiboken6
        return shiboken6.isValid(w)
    except ImportError:
        pass
    try:
        w.objectName()
        return True
    except RuntimeError:
        return False


def current():
    return _bar[0] if _alive(_bar[0]) else None


def open_bar(under=None):
    from .command_search import _view_widget
    view = _view_widget()
    if view is None:
        return None
    bar = current()
    if bar is None or bar.parent() is not view:
        if bar is not None:
            bar.list.deleteLater()
            bar.deleteLater()
        bar = _bar[0] = _make_bar(view)
    bar.start(under)
    return bar


def _make_bar(view):
    from PySide import QtCore, QtWidgets

    class CommandBar(QtWidgets.QFrame):
        def __init__(self, parent):
            super(CommandBar, self).__init__(parent)
            self.setObjectName("SD_CommandLine")
            self.setAutoFillBackground(True)
            self.setFrameShape(QtWidgets.QFrame.StyledPanel)
            lay = QtWidgets.QHBoxLayout(self)
            lay.setContentsMargins(6, 3, 6, 3)
            colon = QtWidgets.QLabel(":")
            f = colon.font()
            f.setBold(True)
            colon.setFont(f)
            self.edit = QtWidgets.QLineEdit()
            self.edit.setFrame(False)
            self.edit.setPlaceholderText(
                u"fillet 2   ·   extrude 10 cut   ·   chamfer d=Width/2   ·   "
                u"Tab completes, ↑ history, Esc closes")
            self.edit.installEventFilter(self)
            self.edit.textEdited.connect(lambda _t: self.suggest())
            lay.addWidget(colon)
            lay.addWidget(self.edit, 1)
            self.list = QtWidgets.QListWidget(parent)
            self.list.setFocusPolicy(QtCore.Qt.NoFocus)
            self.list.hide()
            self.under = None
            self.hist = []
            self.hpos = 0
            self.cands = []
            self.cpos = -1
            self.typed = ""
            parent.installEventFilter(self)

        def start(self, under):
            self.under = under
            self.hist = history()
            self.hpos = len(self.hist)
            self.edit.clear()
            self.place()
            self.show()
            self.raise_()
            self.edit.setFocus()
            self.suggest()

        def place(self):
            p = self.parentWidget()
            h = self.edit.sizeHint().height() + 8
            self.setGeometry(0, p.height() - h, p.width(), h)
            self._place_list()

        def _place_list(self):
            p = self.parentWidget()
            n = min(self.list.count(), 10)
            if not n:
                self.list.hide()
                return
            rh = max(self.list.sizeHintForRow(0), 18)
            h = rh * n + 6
            self.list.setGeometry(0, self.geometry().top() - h, min(p.width(), 560), h)
            self.list.show()
            self.list.raise_()

        def suggest(self):
            self.typed = self.edit.text()
            self.cands = completions(self.typed)
            self.cpos = -1
            self.list.clear()
            for _put, shown in self.cands:
                self.list.addItem(shown)
            self._place_list()

        def complete(self, d):
            if not self.cands:
                return
            self.cpos = (self.cpos + d) % len(self.cands)
            put = self.cands[self.cpos][0]
            parts = self.typed.split(" ")
            parts[-1] = put.rstrip(" ")
            text = " ".join(parts) + (" " if put.endswith(" ") else "")
            self.edit.setText(text)
            self.list.setCurrentRow(self.cpos)

        def eventFilter(self, obj, ev):
            if obj is self.parentWidget() and ev.type() == QtCore.QEvent.Resize:
                if self.isVisible():
                    self.place()
                return False
            if obj is self.edit and ev.type() == QtCore.QEvent.KeyPress:
                k = ev.key()
                if k == QtCore.Qt.Key_Tab:
                    self.complete(1)
                    return True
                if k == QtCore.Qt.Key_Backtab:
                    self.complete(-1)
                    return True
                if k in (QtCore.Qt.Key_Up, QtCore.Qt.Key_Down) and self.hist:
                    self.hpos = max(0, min(len(self.hist), self.hpos +
                                           (-1 if k == QtCore.Qt.Key_Up else 1)))
                    self.edit.setText(self.hist[self.hpos] if self.hpos < len(self.hist)
                                      else "")
                    self.suggest()
                    return True
                if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                    self.enter()
                    return True
                if k == QtCore.Qt.Key_Escape:
                    self.close_bar()
                    return True
            return super(CommandBar, self).eventFilter(obj, ev)

        def enter(self):
            text = self.edit.text().strip()
            if not text:
                self.close_bar()
                return
            line = parse(text)
            if line.error:
                _say(line.error)
                self.edit.selectAll()
                return
            add_history(text)
            self.close_bar()
            under = self.under
            QtCore.QTimer.singleShot(0, lambda: _say(run(text, under)[1]))

        def close_bar(self):
            self.list.hide()
            self.hide()
            try:
                self.parentWidget().setFocus()
            except Exception:
                pass

    return CommandBar(view)


# ------------------------------------------------------------------ keys

def _typing(w):
    """Whether keys typed now go into a text field."""
    from PySide import QtWidgets
    while w is not None:
        if isinstance(w, (QtWidgets.QLineEdit, QtWidgets.QTextEdit, QtWidgets.QPlainTextEdit,
                          QtWidgets.QAbstractSpinBox)):
            return True
        if isinstance(w, QtWidgets.QComboBox) and w.isEditable():
            return True
        if isinstance(w, QtWidgets.QAbstractItemView) and \
                w.state() == QtWidgets.QAbstractItemView.EditingState:
            return True
        if w.metaObject().className() in ("QOpenGLWidget", "Gui::View3DInventorViewer"):
            return False
        w = w.parentWidget() if w.isWindow() is False else None
    return False


def ready():
    """Whether ":" and "." are Solid Design's now: its workbench, a 3D view, no tool
    or sketch open, and not typing in a field."""
    from PySide import QtWidgets
    try:
        if type(Gui.activeWorkbench()).__name__ != "SolidDesignWorkbench":
            return False
        if Gui.Control.activeDialog() or Gui.ActiveDocument is None:
            return False
        if not hasattr(Gui.ActiveDocument.ActiveView, "getSceneGraph"):
            return False
    except Exception:
        return False
    return not _typing(QtWidgets.QApplication.focusWidget())


def _make_filter():
    from PySide import QtCore

    class Keys(QtCore.QObject):
        def eventFilter(self, obj, ev):
            t = ev.type()
            if t not in (QtCore.QEvent.KeyPress, QtCore.QEvent.ShortcutOverride):
                return False
            try:
                text = ev.text()
                mods = ev.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier |
                                         QtCore.Qt.MetaModifier)
            except Exception:
                return False
            if text not in (":", ".") or mods or ev.isAutoRepeat():
                return False
            from PySide import QtWidgets
            if obj is not QtWidgets.QApplication.focusWidget() or not ready():
                return False
            if t == QtCore.QEvent.ShortcutOverride:
                ev.accept()             # ours: not a shortcut
                return True
            if text == ":":
                open_bar(_pointer_target())
            else:
                QtCore.QTimer.singleShot(0, repeat)
            return True

    return Keys()


_filter = [None]


def install():
    from PySide import QtWidgets
    if _filter[0] is None:
        _filter[0] = _make_filter()
        QtWidgets.QApplication.instance().installEventFilter(_filter[0])


# ------------------------------------------------------------------ menu commands

class LineCommand(object):
    def GetResources(self):
        from .. import icon
        return {"Pixmap": icon("SolidDesign"), "MenuText": "Command Line",
                "ToolTip": "Type a tool and its values, e.g. \"fillet 2\" (press : in the 3D "
                           "view). Works on the selection, or what's under the pointer."}

    def IsActive(self):
        return not Gui.Control.activeDialog() and Gui.ActiveDocument is not None

    def Activated(self):
        open_bar(None)


class RepeatCommand(object):
    def GetResources(self):
        from .. import icon
        return {"Pixmap": icon("Rebuild"), "MenuText": "Repeat Last Feature",
                "ToolTip": "Make the last feature again with the same settings, on the "
                           "selection or what's under the pointer (press . in the 3D view)."}

    def IsActive(self):
        return _last[0] is not None and not Gui.Control.activeDialog()

    def Activated(self):
        repeat()
