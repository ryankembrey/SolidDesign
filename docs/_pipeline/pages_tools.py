# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Ryan Kembrey <ryan.FreeCAD@gmail.com>
# SPDX-FileNotice: Part of the Solid Design addon.

"""The tool reference: an index, and a page per tool.

Every tool in the workbench's Solid Design menu gets a page, made from:

- the command (catalog.json): its name, tooltip, icon, shortcut, and where it
  is on the toolbars and in the menus;
- its panel (panels.json, recorded with the screenshots): each group and
  control, with the control's own tooltip;
- its feature's properties (catalog.json), for the command line and the
  Property editor;
- the hand-written ``docs/_authored/tools/<slug>.md``: what the tool is for and
  how to use it. Every tool must have one (the build fails without it).

Authored files may use ``{{ name }}`` for a value from the code: see VALUES.
"""

from __future__ import annotations

import json
import re

from . import env, md
from .catalog import Catalog, Tool
from .shots import path as shot_path
from .shots import tool_shot_id

FOLDER = "content/reference/tools"
AUTHORED = env.AUTHORED / "tools"
NAV = "tools"


# -- checks -------------------------------------------------------------------------


def problems(cat: Catalog, tools_module) -> list[str]:
    """What stops the tool pages being made: a tool with no hand-written page
    or no screenshot recipe, or a hand-written page for no tool."""
    out = []
    slugs = {t.slug for t in cat.documented}
    for t in cat.documented:
        if not (AUTHORED / f"{t.slug}.md").exists():
            out.append(f"{t.label} ({t.name}) has no docs/_authored/tools/{t.slug}.md: "
                       "write what it is for and how to use it")
        if t.name not in tools_module.RECIPES and t.name not in tools_module.NO_SHOT:
            out.append(f"{t.label} ({t.name}) has no screenshot recipe in "
                       "docs/_pipeline/shots/tools.py (RECIPES), and isn't in NO_SHOT")
    for f in sorted(AUTHORED.glob("*.md")) if AUTHORED.exists() else []:
        if f.stem not in slugs:
            out.append(f"docs/_authored/tools/{f.name} is for no tool (renamed or removed?)")
    for name in tools_module.RECIPES:
        if name not in cat.tools:
            out.append(f"docs/_pipeline/shots/tools.py has a recipe for {name}, which isn't a command")
    return out


# -- values for the authored pages ---------------------------------------------------


def values(cat: Catalog) -> dict[str, str]:
    """``{{ name }}`` in an authored page: numbers and names that come from the code."""
    d = cat.data
    out = {
        "version": d.get("version", ""),
        "health.tiny_edge": md.number(str(d["health"]["tiny_edge"])) + " mm",
        "health.sliver": md.number(str(d["health"]["sliver"])) + " mm",
        "search_key": d["command_line"]["search_shortcut"],
        "slow": md.number(str(d.get("perf", {}).get("slow", 0.5))),
    }
    for t in cat.tools.values():
        out[f"keyword.{t.name}"] = d["command_line"]["keywords"].get(t.name, "")
    return out


def fill(text: str, vals: dict[str, str], where: str) -> str:
    def sub(m):
        key = m.group(1)
        if key not in vals:
            raise SystemExit(f"{where}: no value called {{{{ {key} }}}}")
        return vals[key]

    return re.sub(r"\{\{\s*([\w.]+)\s*\}\}", sub, text)


# -- pieces of a page ----------------------------------------------------------------


def _toolbar(name: str) -> str:
    return name.replace("Solid Design ", "")


def _menu(path: list[str], label: str) -> str:
    return " → ".join(f"**{p}**" for p in path + [label])


def icon_rel(t: Tool) -> str | None:
    return f"assets/icons/{t.slug}.svg" if t.icon_file is not None else None


def where(t: Tool, cat: Catalog, line_section: bool = True) -> str:
    rows = []
    for tb, drop in t.toolbars:
        if drop:
            rows.append(f"- The **{_toolbar(tb)}** toolbar, in the **{drop}** drop-down.")
        else:
            rows.append(f"- The **{_toolbar(tb)}** toolbar.")
    for path in t.menus:
        rows.append(f"- {_menu(path, t.label)}")
    key = cat.data["command_line"]["search_shortcut"]
    rows.append(f"- Command search: press <kbd>{key}</kbd> in the 3D view and type its name.")
    kw = cat.data["command_line"]["keywords"].get(t.name)
    if kw and t.feature_type:
        more = " ([below](#on-the-command-line))" if line_section else ""
        rows.append(f"- The command line: <kbd>:</kbd> then `{kw}`{more}.")
    if t.shortcut:
        keys = " ".join(f"<kbd>{k.strip()}</kbd>" for k in t.shortcut.split(","))
        rows.append(f"- Keyboard: {keys}.")
    return "\n".join(rows) + "\n"


#: What a number field holds, from its property's type.
NUMBER_KINDS = {"Length": "A length", "Distance": "A length", "Angle": "An angle",
                "Percent": "A percentage", "Integer": "A count", "IntegerConstraint": "A count"}
_types: dict[str, str] = {}     # the page being written: property -> type


def _kind(c: dict) -> str:
    k = c.get("kind")
    if k == "number":
        return NUMBER_KINDS.get(_types.get(c.get("prop", ""), ""), "A number")
    if k == "count":
        return "A count"
    if k == "choice":
        return "One of: " + ", ".join(f"*{x}*" for x in c.get("choices", []) if x)
    if k == "switch":
        return "Buttons: " + " \\| ".join(f"*{x}*" for x in c.get("choices", []))
    if k in ("pick", "picks"):
        box = "Selection box" if k == "pick" else "Selection list"
        hint = (c.get("hint") or "").rstrip(".")
        return f"{box}: {hint[0].lower() + hint[1:]}" if hint else box
    if k == "check":
        return "A check box"
    if k == "table":
        cols = c.get("columns") or []
        return "A table" + (": " + ", ".join(cols) if cols else "")
    if k == "button":
        return "A button"
    if k == "list":
        return "A list"
    return ""


def _control_row(c: dict) -> list[str] | None:
    if c.get("kind") == "note":
        return None
    label = c.get("label") or c.get("text") or ""
    if not label and c.get("kind") in ("pick", "picks"):
        label = (c.get("what") or c.get("name") or "").capitalize()
    if c.get("kind") == "switch" and not label:
        label = " \\| ".join(c.get("choices", []))
    if c.get("kind") == "button" and c.get("text"):
        label = c["text"]
    tip = md.plain(re.sub(r"<[^>]+>", " ", c.get("tip", "")))
    kind = _kind(c)
    extra = []
    for w in c.get("with", []):
        if w.get("kind") == "button":
            extra.append("a flip button beside it" if not w.get("text") else f"a **{w['text']}** button")
    if c.get("optional"):
        extra.append("tick it to use it")
    if not c.get("shown", True):
        extra.append("shown for some choices only")
    what = tip
    if extra:
        what += f" *({'; '.join(extra)})*"
    return [f"**{label}**" if label else "", kind, what]


def panel_section(rec: dict) -> str:
    out = ""
    loose = []
    for item in rec.get("items", []):
        if "control" in item:
            loose.append(item["control"])
            continue
        if loose:
            rows = [r for r in (_control_row(c) for c in loose) if r]
            if rows:
                out += md.table(["Control", "Kind", "What it does"], rows)
            loose = []
        g = item["group"]
        title = g["title"] or "Options"
        out += f"### {title}\n\n"
        notes = []
        if g.get("optional"):
            notes.append("Optional: tick its title to use it.")
        if not g.get("shown", True):
            notes.append("Shown only for some choices above.")
        tip = md.plain(re.sub(r"<[^>]+>", " ", g.get("tip", "")))
        if tip:
            out += tip + "\n\n"
        if notes:
            out += "*" + " ".join(notes) + "*\n\n"
        rows = [r for r in (_control_row(c) for c in g.get("rows", [])) if r]
        if rows:
            out += md.table(["Control", "Kind", "What it does"], rows)
        for c in g.get("rows", []):
            if c.get("kind") == "note" and c.get("shown", True):
                out += f"> {c['text']}\n\n"
    if loose:
        rows = [r for r in (_control_row(c) for c in loose) if r]
        if rows:
            out += md.table(["Control", "Kind", "What it does"], rows)
    return out


def _value(p) -> str:
    v = p.default
    if v is None:
        return "–"
    if isinstance(v, bool):
        return "Yes" if v else "No"
    if isinstance(v, float):
        s = f"{v:g}"
        unit = {"Length": " mm", "Distance": " mm", "Angle": "°"}.get(p.type, "")
        return s + unit
    if isinstance(v, list):
        return "–"
    return md.cell(v)


def _ptype(p) -> str:
    t = p.type.replace("Part::Property", "").replace("Property", "")
    return {"LinkSub": "Picks", "LinkSubList": "Picks", "LinkList": "Objects", "Link": "Object",
            "Bool": "Yes/No", "Enumeration": "Choice", "Integer": "Whole number",
            "IntegerConstraint": "Whole number", "FloatConstraint": "Number", "Float": "Number",
            "StringList": "List", "String": "Text", "Length": "Length", "Distance": "Length",
            "Angle": "Angle", "Percent": "Percent", "Placement": "Placement",
            "VectorList": "Points", "Vector": "Vector"}.get(t, t)


CL_KINDS = {"Enumeration": "enum", "Bool": "bool", "Integer": "int", "IntegerConstraint": "int"}


def command_line_section(t: Tool, cat: Catalog) -> str:
    cl = cat.data["command_line"]
    kw = cl["keywords"].get(t.name)
    if not kw:
        return ""
    main = cl["main"].get(t.name, [])
    settable = [p for p in t.props if p.user and not p.readonly and
                (p.type in CL_KINDS or p.type.replace("Constraint", "") in cl["value_types"])]
    if not settable:
        return ""
    out = "## On the command line\n\n"
    out += (f"Press <kbd>:</kbd> in the 3D view and type `{kw}`, then what to set. "
            "See [the command line](../../guides/keyboard.md) for how it works.\n\n")
    if main:
        ex = " ".join(str(_example(next((p for p in t.props if p.name == m), None))) for m in main)
        out += (f"Values typed straight after the name set, in order: "
                + ", ".join(f"**{m}**" for m in main) + f". For example `:{kw} {ex}`.\n\n")
    rows = []
    for p in settable:
        kind = CL_KINDS.get(p.type)
        if kind == "enum":
            how = "a word: " + ", ".join(f"`{_norm(c)}`" for c in (p.choices or []))
        elif kind == "bool":
            how = f"`{p.name.lower()}` turns it on, `{p.name.lower()}=no` off"
        else:
            how = f"`{p.name.lower()}=`" + ("a whole number" if kind == "int" else "a value")
        rows.append([f"`{p.name}`", how, md.plain(p.doc)])
    out += md.admonition_collapsed("note", "Options it takes",
                                   md.table(["Option", "How to type it", "What it is"], rows))
    return out + "\n"


def _example(p) -> str:
    if p is None or p.default is None or isinstance(p.default, (bool, list)):
        return "10"
    if isinstance(p.default, float):
        return f"{p.default:g}"
    return str(p.default)


def _norm(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


def properties_section(t: Tool) -> str:
    props = [p for p in t.props if p.user]
    if not props:
        return ""
    rows = [[f"`{p.name}`", _ptype(p), _value(p), md.plain(p.doc) +
             (" Choices: " + ", ".join(f"*{c}*" for c in p.choices) + "." if p.choices else "")]
            for p in props]
    body = ("What the feature stores, as the **Property** editor shows it (select the feature "
            "in the tree, then the **Data** tab). The panel sets these for you.\n\n")
    body += md.table(["Property", "Kind", "Default", "What it is"], rows)
    return "## Properties\n\n" + md.admonition_collapsed("info", "All properties", body) + "\n"


def handles_section(rec: dict | None) -> str:
    if not rec or not rec.get("handles"):
        return ""
    names = ", ".join(f"**{h}**" for h in rec["handles"])
    return ("## Drag handles\n\n"
            f"While the panel is open, drag the handles in the 3D view to set {names}, or "
            "click a handle's value and type. The same handles show when you select the "
            "feature in the tree, so you can change it without opening the panel. See "
            "[drag handles](../../guides/drag-handles.md).\n\n")


# -- pages -----------------------------------------------------------------------------


def tool_page(t: Tool, cat: Catalog, panels: dict, shots: set[str], vals: dict) -> str:
    src = ["docs/_data/catalog.json", f"docs/_authored/tools/{t.slug}.md"]
    rec = panels.get(t.name)
    if rec:
        src.append("docs/_data/panels.json")
    out = md.header(*src)
    _types.clear()
    _types.update({p.name: p.type for p in t.props})
    out += f"# {t.label}\n\n"
    ic = icon_rel(t)
    if ic:
        out += f'![]({"../../" + ic}){{ .tool-icon }}\n'
    out += f"{t.tooltip}\n{{ .tool-lead }}\n\n"
    sid = tool_shot_id(t.slug)
    authored = fill((AUTHORED / f"{t.slug}.md").read_text(encoding="utf-8"), vals,
                    f"docs/_authored/tools/{t.slug}.md").strip()
    # The authored text's first part (before its first heading) introduces the tool;
    # the picture goes after it.
    m = re.search(r"^## ", authored, re.M)
    intro, rest = (authored[:m.start()], authored[m.start():]) if m else (authored, "")
    out += intro.strip() + "\n\n" if intro.strip() else ""
    if sid in shots:
        img = "../../" + shot_path(sid)
        out += f"[![The {t.label} panel, open on a sample part]({img})]({img})\n\n"
    out += rest.strip() + "\n\n" if rest.strip() else ""
    line = command_line_section(t, cat)
    out += "## Where to find it\n\n" + where(t, cat, bool(line)) + "\n"
    if rec and rec.get("items"):
        out += "## The panel\n\n"
        out += ("Every control's tooltip says the same as here: hover over it in FreeCAD. "
                "**OK** (or <kbd>Enter</kbd>) makes the feature, **Cancel** (or "
                "<kbd>Esc</kbd>) leaves the model as it was.\n\n")
        out += panel_section(rec)
    out += handles_section(rec)
    out += line
    out += properties_section(t)
    return out


def index_page(cat: Catalog) -> str:
    out = md.header("docs/_data/catalog.json")
    out += "# Tools\n\n"
    out += ("Every tool in the workbench, as the **Solid Design** menu groups them. Each page says "
            "what the tool does, how to use it, where to find it and what every control in its "
            "panel means.\n\n")
    seen = set()
    for section, names in cat.sections:
        rows = []
        for n in names:
            if n in seen:
                continue
            seen.add(n)
            t = cat.tools[n]
            ic = icon_rel(t)
            icon = f"![]({'../../' + ic}){{ .tool-icon-small }}" if ic else ""
            rows.append([icon, f"[{t.label}]({t.slug}.md)", t.tooltip])
        if rows:
            out += f"## {section}\n\n" + md.table(["", "Tool", "What it does"], rows)
    return out


def nav_lines(cat: Catalog) -> list[str]:
    lines = ['"reference/tools/index.md",']
    seen = set()
    for section, names in cat.sections:
        entries = []
        for n in names:
            if n in seen:
                continue
            seen.add(n)
            t = cat.tools[n]
            entries.append(f'  {{ "{t.label}" = "reference/tools/{t.slug}.md" }},')
        if entries:
            lines.append(f'{{ "{section}" = [')
            lines += entries
            lines.append("] },")
    return lines


def load_panels() -> dict:
    p = env.DATA / "panels.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def write(out, cat: Catalog) -> None:
    from .shots import REGISTRY

    panels = load_panels()
    shots = set(REGISTRY)
    vals = values(cat)
    out.write(f"{FOLDER}/index.md", index_page(cat))
    for t in cat.documented:
        out.write(f"{FOLDER}/{t.slug}.md", tool_page(t, cat, panels, shots, vals))
        if t.icon_file is not None:
            out.write(f"content/{icon_rel(t)}", t.icon_file.read_bytes())
    out.patch_block("zensical.toml", NAV, nav_lines(cat))
