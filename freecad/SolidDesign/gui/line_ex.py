# SPDX-License-Identifier: LGPL-2.1-or-later
"""The command line's own commands, besides tools: working on the tree by name
(as Vim's ex commands), customising the line, registers, marks and yanking.

    Fillet1 r=3                 change a feature without opening it
    last d=+2                   the last feature; + and - add to what it is
    edit Fillet1                open a feature (or: edit jk, the one that made face jk)
    suppress /Fillet/           every feature whose name matches; unsuppress the same
    rollto Boss-Extrude2        the rollback bar to just after it (rollto end)
    hide Body2 · show Body2 · isolate Body1 · showall
    set r=2->3 /Fillet/         every 2 mm fillet radius to 3 mm (set r=3 /Fillet/: all)
    set fillet.r=1              what a tool uses unless the line says otherwise
    alias m6 = holewizard size=m6 type=counterbore
    bind gf = fillet 1 sel=new  keys typed in the 3D view run a line
    mark a · 'a                 save the view, jump back to it
    yank sel=jk · yank Fillet1.Radius     copy a measurement or a value
    registers · delreg a        the named selections (sel=jk,dl >a)

Each command is a function taking the words after its name and returning a
message, or an Action for the bar to carry out (help, the toolbar's labels).
"""

import re

import FreeCAD as App
import FreeCADGui as Gui

from . import line_store

#: Words that start a line and aren't tools: name -> (usage, what it does).
COMMANDS = {}
_HANDLERS = {}


class Action(object):
    """Something for the bar to do (it holds the window and the labels)."""

    def __init__(self, kind, arg=None):
        self.kind, self.arg = kind, arg


def command(name, usage, summary, aliases=()):
    def deco(fn):
        for n in (name,) + tuple(aliases):
            COMMANDS[n] = (usage, summary)
            _HANDLERS[n] = fn
        return fn
    return deco


def norm(s):
    return "".join(c for c in s.lower() if c.isalnum())


# ------------------------------------------------------------------ the model

def _doc():
    return App.ActiveDocument


def _part(doc=None):
    from .line_select import _part as part_of_doc
    return part_of_doc(doc or _doc())


def clean(label):
    from ..app import part as part_mod
    return part_mod.clean_label(label)


def tree_objects(part):
    """What the tree lists in a part, by name: features, sketches, reference
    geometry, in order."""
    from ..app import util
    out = []
    for o in getattr(part, "Group", []) or []:
        if util.is_feature(o) or util.role(o) == "refgeom" or \
                o.TypeId.startswith("Sketcher::SketchObject"):
            out.append(o)
    return out


def features(part):
    from ..app import util
    return util.features(part) if part is not None else []


def last(part):
    from .line_select import last_feature
    return last_feature(part.Document) if part is not None else None


def by_name(name, objs):
    """The object a typed name means: exact (any case, spaces and punctuation
    ignored), then the only one it starts, else None."""
    n = norm(name)
    if not n:
        return None
    exact = [o for o in objs if norm(clean(o.Label)) == n]
    if exact:
        return exact[0]
    starts = [o for o in objs if norm(clean(o.Label)).startswith(n)]
    return starts[0] if len(starts) == 1 else None


def targets(words, objs):
    """The objects named by words: names (comma-separated or not) and /patterns/.
    Returns (objects, [names not found])."""
    out, missing = [], []
    for w in words:
        if len(w) > 1 and w.startswith("/") and w.endswith("/"):
            try:
                rx = re.compile(w[1:-1], re.I)
            except re.error:
                missing.append(w)
                continue
            hits = [o for o in objs if rx.search(clean(o.Label))]
            if not hits:
                missing.append(w)
            out += [o for o in hits if o not in out]
            continue
        for name in [x for x in w.split(",") if x]:
            o = by_name(name, objs)
            if o is None:
                missing.append(name)
            elif o not in out:
                out.append(o)
    return out, missing


def bodies(part):
    from ..app import part as part_mod
    return part_mod.body_views(part) if part is not None else []


def feature_line(text):
    """(feature, the rest of the line) when a line starts with a feature's name
    or "last", else None."""
    words = text.strip().lstrip(":").split()
    if not words:
        return None
    part = _part()
    if part is None:
        return None
    if words[0].lower() == "last":
        f = last(part)
        return (f, words[1:]) if f is not None else None
    n = norm(words[0])
    for o in features(part):
        if norm(clean(o.Label)) == n:
            return o, words[1:]
    return None


def _relative(obj, line):
    """Values written +2 or -2 in a feature edit add to what the feature has."""
    from . import command_line as cl
    opts = cl.settable(obj)
    main = [m for m in cl._main(cl.command_for(obj) or "", obj) if m in opts]

    def add(prop, tok):
        cur = getattr(obj, prop, None)
        cur = getattr(cur, "Value", cur)
        try:
            d = float(App.Units.Quantity(tok[1:]).Value)     # (the parser takes no "+")
            return str(float(cur) + (d if tok[0] == "+" else -d))
        except Exception:
            return tok
    pos = 0
    vals = []
    for tok in line.values:
        if cl.value_of(tok, {}) is not None and pos < len(main):
            vals.append(add(main[pos], tok) if tok[:1] in "+-" else tok)
            pos += 1
        else:
            vals.append(tok)
    line.values = vals
    named = []
    for name, tok in line.named:
        prop = cl.option_for(name, opts, main, ("num", "int"))
        named.append((name, add(prop, tok) if tok[:1] in "+-" and prop in opts else tok))
    line.named = named
    return line


def feature_assigns(obj, words):
    """The assignments a feature edit's words make (``r=3``, ``+2``), or raise
    ValueError saying what's wrong."""
    from . import command_line as cl
    line = cl.Line(" ".join(["x"] + words))
    for tok in words:
        if "=" in tok and not tok.startswith("=") and tok.split("=", 1)[0].strip():
            n, v = tok.split("=", 1)
            line.named.append((n.strip(), v.strip()))
        else:
            line.values.append(tok)
    line = _relative(obj, line)
    return cl.assignments(line, cl.settable(obj), cl.variables(obj.Document),
                          cl._main(cl.command_for(obj) or "", obj))


def edit_feature(obj, words):
    """``Fillet1 r=3``: set values on a feature without opening it."""
    from . import command_line as cl
    if not words:
        return _open(obj)
    try:
        assigns = feature_assigns(obj, words)
    except ValueError as e:
        return str(e)
    doc = obj.Document
    doc.openTransaction("Change " + clean(obj.Label))
    try:
        cl.apply(obj, assigns)
        doc.recompute()
    finally:
        doc.commitTransaction()
    if obj.ErrorMessage:
        return "{}: {}".format(clean(obj.Label), obj.ErrorMessage)
    return "{} changed.".format(clean(obj.Label))


def _open(obj):
    try:
        Gui.Selection.clearSelection()
        if obj.TypeId.startswith("Sketcher::SketchObject"):
            Gui.ActiveDocument.setEdit(obj.Name)
        else:
            Gui.ActiveDocument.setEdit(obj.Name, 0)
    except Exception as e:
        return "Couldn't open {}: {}".format(clean(obj.Label), e)
    return ""


# ------------------------------------------------------------------ commands

@command("help", "help [topic]", "this cheat sheet (Esc closes it)", aliases=("h",))
def _help(words, ctx):
    return Action("help", words[0] if words else None)


@command("edit", "edit Fillet1 · edit jk", "open a feature; with a face's label, the "
         "feature that made it")
def _edit(words, ctx):
    if not words:
        return "Edit what? Type a feature's name, or a label in the view."
    part = _part()
    obj = by_name(words[0], tree_objects(part)) if part is not None else None
    if obj is None and ctx is not None:
        obj = ctx.feature_from_code(words[0])
    if obj is None:
        return "No feature \"{}\".".format(words[0])
    return _open(obj) or Action("close")


def _suppress(words, on):
    part = _part()
    objs, missing = targets(words, features(part))
    if missing:
        return "No feature {}.".format(", ".join("\"%s\"" % m for m in missing))
    if not objs:
        return "Which features? Name them, or /a pattern/."
    doc = part.Document
    doc.openTransaction("Suppress" if on else "Unsuppress")
    try:
        for o in objs:
            o.Suppressed = on
        doc.recompute()
    finally:
        doc.commitTransaction()
    return "{} {}.".format(", ".join(clean(o.Label) for o in objs),
                           "suppressed" if on else "unsuppressed")


@command("suppress", "suppress Fillet1 · suppress /Fillet/", "skip features (names or "
         "/pattern/)", aliases=("sup",))
def _sup(words, ctx):
    return _suppress(words, True)


@command("unsuppress", "unsuppress /Fillet/", "bring suppressed features back",
         aliases=("unsup",))
def _unsup(words, ctx):
    return _suppress(words, False)


@command("rollto", "rollto Boss-Extrude2 · rollto end", "move the rollback bar to just "
         "after a feature")
def _rollto(words, ctx):
    from ..app import part as part_mod
    part = _part()
    if part is None:
        return "No part."
    if not words:
        return "Roll to which feature? (rollto end for all)"
    doc = part.Document
    if words[0].lower() == "end":
        target = None
    else:
        target = by_name(words[0], features(part))
        if target is None:
            return "No feature \"{}\".".format(words[0])
    doc.openTransaction("Roll back")
    try:
        if target is None:
            part_mod.roll_to_end(part)
        else:
            part_mod.roll_to(part, target)
        doc.recompute()
    finally:
        doc.commitTransaction()
    return "Rolled to the end." if target is None else \
        "Rolled back to {}.".format(clean(target.Label))


def _show(words, how):
    part = _part()
    views = bodies(part)
    if how == "all":
        for v in views:
            v.ViewObject.Visibility = True
        return "All bodies shown."
    objs, missing = targets(words, views)
    if missing:
        return "No body {}.".format(", ".join("\"%s\"" % m for m in missing))
    if not objs:
        return "Which bodies?"
    if how == "isolate":
        for v in views:
            v.ViewObject.Visibility = v in objs
        return "Only {} shown.".format(", ".join(clean(o.Label) for o in objs))
    for o in objs:
        o.ViewObject.Visibility = how == "show"
    return "{} {}.".format(", ".join(clean(o.Label) for o in objs),
                           "shown" if how == "show" else "hidden")


@command("hide", "hide Body2", "hide bodies")
def _hide(words, ctx):
    return _show(words, "hide")


@command("show", "show Body2", "show bodies")
def _showc(words, ctx):
    return _show(words, "show")


@command("isolate", "isolate Body1", "show only these bodies")
def _isolate(words, ctx):
    return _show(words, "isolate")


@command("showall", "showall", "show every body")
def _showall(words, ctx):
    return _show(words, "all")


# ------------------------------------------------------------------ set

def _tool_of(word):
    from . import command_line as cl
    return cl.find_tool(word)


@command("set", "set fillet.r=1 · set r=2->3 /Fillet/", "a tool's default; or values on "
         "every feature named")
def _set(words, ctx):
    from . import command_line as cl
    if not words:
        d = line_store.defaults()
        if not d:
            return "No defaults set. (set fillet.r=1)"
        return "Defaults: " + "; ".join("{} {}".format(_label(c), " ".join(
            "{}={}".format(p, v) for p, v in sorted(pv.items()))) for c, pv in sorted(d.items()))
    assigns = [w for w in words if "=" in w]
    rest = [w for w in words if "=" not in w]
    if not assigns:
        return "Set what? name=value"
    if not rest and all("." in a.split("=", 1)[0] for a in assigns):
        out = []
        for a in assigns:
            name, value = a.split("=", 1)
            tool, opt = name.split(".", 1)
            cmd = _tool_of(tool)
            if cmd is None:
                return "No tool \"{}\".".format(tool)
            opts = cl.catalog(cmd)
            prop = cl._resolve(opt, opts) if opts else None
            if prop not in opts:
                return prop or "{} has no option \"{}\".".format(_label(cmd), opt)
            line_store.set_default(cmd, prop, value)
            out.append("{} {}={}".format(_label(cmd), prop, value))
        return "Default: " + "; ".join(out) + "."
    part = _part()
    objs, missing = targets(rest, features(part))
    if missing:
        return "No feature {}.".format(", ".join("\"%s\"" % m for m in missing))
    if not objs:
        return "On which features? Name them, or /a pattern/."
    doc = part.Document
    changed = []
    doc.openTransaction("Set values")
    try:
        for o in objs:
            opts = cl.settable(o)
            main = cl._main(cl.command_for(o) or "", o)
            done = False
            for a in assigns:
                name, value = a.split("=", 1)
                old = None
                if "->" in value:
                    old, value = [x.strip() for x in value.split("->", 1)]
                prop = cl.option_for(name, opts, main)
                if prop not in opts:
                    continue
                if old is not None:
                    cur = getattr(o, prop)
                    cur = getattr(cur, "Value", cur)
                    v = cl.value_of(old, {})
                    if v is None or v[0] != "num" or abs(float(cur) - v[1]) > 1e-6:
                        continue
                line = cl.Line("x")
                line.named = [(prop, value)]
                try:
                    cl.apply(o, cl.assignments(line, opts, cl.variables(doc), []))
                    done = True
                except ValueError:
                    continue
            if done:
                changed.append(o)
        doc.recompute()
    finally:
        doc.commitTransaction()
    if not changed:
        return "Nothing changed: no feature named has that value."
    return "Changed {}.".format(", ".join(clean(o.Label) for o in changed))


@command("unset", "unset fillet.r · unset fillet", "forget a tool's default")
def _unset(words, ctx):
    if not words:
        return "Unset what? (unset fillet.r)"
    tool, _dot, opt = words[0].partition(".")
    cmd = _tool_of(tool)
    if cmd is None:
        return "No tool \"{}\".".format(tool)
    if opt:
        d = line_store.defaults().get(cmd, {})
        from . import command_line as cl
        prop = cl._resolve(opt, {p: None for p in d}) if d else opt
        ok = line_store.remove_default(cmd, prop)
    else:
        ok = line_store.remove_default(cmd)
    return "Default forgotten." if ok else "No such default."


def _label(cmd):
    try:
        return Gui.Command.get(cmd).getInfo().get("menuText", cmd).replace("&", "")
    except Exception:
        return cmd


def defaults_for(cmd, line):
    """The named tokens a tool's defaults add to a parsed line: those for options
    the line doesn't set."""
    from . import command_line as cl
    d = line_store.defaults().get(cmd, {})
    if not d:
        return []
    opts = cl.catalog(cmd)
    main = [m for m in cl.MAIN.get(cmd, []) if m in opts]
    covered = set(main[:len([v for v in line.values if cl.value_of(v, {}) is not None])])
    for name, _v in line.named:
        r = cl._resolve(name, opts) if opts else name
        covered.add(r)
    for w in line.values:
        if cl.value_of(w, {}) is None:
            try:
                covered.add(cl._word(w, opts)[0])
            except ValueError:
                pass
    return [(p, v) for p, v in sorted(d.items()) if p not in covered]


def with_defaults(cmd, line):
    """A parsed line with the tool's defaults added for what it doesn't set."""
    from . import command_line as cl
    extra = defaults_for(cmd, line)
    if not extra:
        return line
    out = cl.Line(line.text)
    out.cmd = line.cmd
    out.values = list(line.values)
    out.named = list(extra) + list(line.named)
    return out


# ------------------------------------------------------------------ aliases and bindings

def _definition(words):
    text = " ".join(words)
    if "=" not in text:
        return None, None
    name, line = text.split("=", 1)
    return name.strip(), line.strip()


@command("alias", "alias m6 = holewizard size=m6", "a word of yours for a line")
def _alias(words, ctx):
    if not words:
        a = line_store.aliases()
        return ("Aliases: " + "; ".join("{} = {}".format(k, v) for k, v in sorted(a.items()))
                if a else "No aliases. (alias m6 = holewizard size=m6)")
    name, line = _definition(words)
    if not name or not line or " " in name:
        return "alias NAME = LINE"
    if name.lower() in COMMANDS:
        return "\"{}\" is a command already.".format(name)
    line_store.set_alias(name, line)
    return "{} = {}".format(name.lower(), line)


@command("unalias", "unalias m6", "forget an alias")
def _unalias(words, ctx):
    return "Alias forgotten." if words and line_store.remove_alias(words[0]) else "No such alias."


def expand_alias(text):
    """A line with its first word replaced by the alias it is (once)."""
    words = text.strip().lstrip(":").split(" ")
    a = line_store.aliases().get(words[0].lower()) if words and words[0] else None
    return " ".join([a] + words[1:]).strip() if a else text.strip().lstrip(":")


@command("bind", "bind gf = fillet 1 sel=new", "keys typed in the 3D view run a line")
def _bind(words, ctx):
    if not words:
        b = line_store.bindings()
        return ("Bindings: " + "; ".join("{} = {}".format(k, v) for k, v in sorted(b.items()))
                if b else "No bindings. (bind gf = fillet 1 sel=new)")
    keys, line = _definition(words)
    if not keys or not line or " " in keys:
        return "bind KEYS = LINE"
    if any(c in ":." for c in keys):
        return ": and . are the line's own keys."
    line_store.set_binding(keys, line)
    return "{} runs: {}".format(keys, line)


@command("unbind", "unbind gf", "forget a binding")
def _unbind(words, ctx):
    return "Binding forgotten." if words and line_store.remove_binding(words[0]) \
        else "No such binding."


# ------------------------------------------------------------------ marks

@command("mark", "mark a", "save the view as a (then 'a jumps back)")
def _mark(words, ctx):
    doc = _doc()
    if not words or doc is None:
        return "mark NAME"
    try:
        cam = Gui.ActiveDocument.ActiveView.getCamera()
    except Exception:
        return "No 3D view."
    line_store.set_mark(doc, words[0], cam)
    return "View saved as '{}.".format(words[0])


@command("marks", "marks · delmark a", "the saved views")
def _marks(words, ctx):
    m = line_store.marks(_doc())
    return ("Views: " + ", ".join("'" + k for k in sorted(m))) if m else "No saved views."


@command("delmark", "delmark a", "forget a saved view")
def _delmark(words, ctx):
    return "View forgotten." if words and line_store.remove_mark(_doc(), words[0]) \
        else "No such view."


def jump(name):
    """'a: the saved view a."""
    cam = line_store.marks(_doc()).get(name)
    if cam is None:
        return "No view '{}.".format(name)
    try:
        Gui.ActiveDocument.ActiveView.setCamera(cam)
    except Exception as e:
        return "Couldn't restore the view: {}".format(e)
    return ""


# ------------------------------------------------------------------ registers

@command("registers", "registers · delreg a", "the named selections (sel=jk,dl >a)",
         aliases=("reg",))
def _registers(words, ctx):
    r = line_store.registers(_doc())
    if not r:
        return "No registers. (sel=jk,dl >a keeps a selection in a)"
    return "Registers: " + ", ".join("@{} ({})".format(k, len(v)) for k, v in sorted(r.items()))


@command("delreg", "delreg a", "forget a register")
def _delreg(words, ctx):
    return "Register forgotten." if words and line_store.remove_register(_doc(), words[0]) \
        else "No such register."


def store_register(name, keys):
    from .line_select import to_items
    doc = _doc()
    items = to_items(keys)
    if not items:
        return "Nothing to keep in @{}.".format(name)
    line_store.set_register(doc, name, items)
    return "{} kept in @{}.".format(len(items), name)


# ------------------------------------------------------------------ yank

def _fmt(v):
    return ("%.6f" % v).rstrip("0").rstrip(".")


def measurement(key):
    """(text to copy, what it is) for an element."""
    from .line_select import _elem, surface_type
    e = _elem(key)
    if e is None:
        return None
    el = e.el
    if el.ShapeType == "Vertex":
        p = el.Point
        return "{}, {}, {}".format(_fmt(p.x), _fmt(p.y), _fmt(p.z)), "point"
    if el.ShapeType == "Edge":
        if surface_type(el) == "Circle":
            return _fmt(el.Curve.Radius), "radius (mm)"
        return _fmt(el.Length), "length (mm)"
    return _fmt(el.Area), "area (mm²)"


@command("yank", "yank sel=jk · yank Fillet1.Radius", "copy a measurement or a value")
def _yank(words, ctx):
    from PySide import QtWidgets
    text, what = None, ""
    if words and "." in words[0] and "=" not in words[0]:
        name, prop = words[0].split(".", 1)
        part = _part()
        obj = by_name(name, tree_objects(part)) if part is not None else None
        if obj is None:
            return "No feature \"{}\".".format(name)
        from . import command_line as cl
        opts = list(cl.settable(obj)) or obj.PropertiesList
        p = cl._resolve(prop, opts)
        if p not in obj.PropertiesList:
            return p
        v = getattr(obj, p)
        text, what = (_fmt(v.Value) if hasattr(v, "Value") else str(v)), p
    else:
        keys = ctx.selection_keys() if ctx is not None else []
        vals = [m for m in (measurement(k) for k in keys) if m]
        if not vals:
            return "Yank what? Pick with sel=, or name Feature.Property."
        text = "\n".join(v for v, _w in vals)
        what = vals[0][1] if len(vals) == 1 else "{} values".format(len(vals))
    QtWidgets.QApplication.clipboard().setText(text)
    return "Copied {}: {}".format(what, text.replace("\n", "; "))


# ------------------------------------------------------------------ the toolbar's labels

@command("toolbar", "toolbar", "labels on the toolbar buttons: type one to click it",
         aliases=("tb",))
def _toolbar(words, ctx):
    return Action("toolbar")


# ------------------------------------------------------------------ dispatch

def handler(word):
    return _HANDLERS.get((word or "").lower())


def run(text, ctx=None):
    """Run a line that isn't a tool. Returns None when it is a tool's line, else
    a message or an Action."""
    t = text.strip().lstrip(":")
    if not t:
        return None
    if t.startswith("'"):
        return jump(t[1:].strip()) or Action("close")
    words = [w for w in t.split(" ") if w]
    h = handler(words[0])
    if h is not None:
        return h(words[1:], ctx)
    fl = feature_line(t)
    if fl is not None:
        obj, rest = fl
        return edit_feature(obj, rest) or Action("close")
    return None
