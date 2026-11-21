# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the Solid Design addon.

"""The workbench's tools, read from its code: ``_data/catalog.json``.

Made on every build by running catalog_runner.py in ``freecadcmd`` (under a
second), so the reference pages follow the code. Without FreeCAD the committed
file is used as it is, with a note.

Shape of the file::

    version          the workbench's __version__
    workbench        name, tooltip, icon, toolbars [{name, commands}], menus [{path, commands}]
    commands         [{name, label, tooltip, pixmap, shortcut, checkable, class, doc, group?}]
    features         {command: {class, module, type, kind, doc, properties: [...]}}
                     each property: name, type, group, doc, hidden, readonly, default?, choices?
    command_line     main (the values a tool takes in order), keywords, search_shortcut
    health           the geometry check's limits

The objects below wrap it for the page writers.
"""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import env

FILE = "_data/catalog.json"     # relative to docs/

#: Commands that are part of the workbench's machinery, not tools to document.
NOT_TOOLS = set()


def refresh(out) -> list[str]:
    """Remake catalog.json from the code with freecadcmd. Returns notes."""
    exe = env.freecad(gui=False)
    if exe is None:
        out.keep(FILE)
        return ["catalog.json not remade: freecadcmd wasn't found (run through `pixi run docs`)."]
    with tempfile.TemporaryDirectory(prefix="sd-catalog-") as tmp:
        target = Path(tmp) / "catalog.json"
        home = Path(tmp) / "home"
        home.mkdir()
        e = env.sealed_env(SD_REPO=str(env.REPO), SD_CATALOG_OUT=str(target),
                           FREECAD_USER_HOME=str(home), QT_QPA_PLATFORM="offscreen")
        runner = Path(__file__).with_name("catalog_runner.py")
        proc = subprocess.run([exe, str(runner)], env=e, capture_output=True, text=True, timeout=300)
        if not target.exists():
            raise SystemExit("Reading the workbench in freecadcmd failed:\n"
                             + (proc.stdout + proc.stderr)[-3000:])
        data = json.loads(target.read_text(encoding="utf-8"))
    if "error" in data:
        raise SystemExit("Reading the workbench in freecadcmd failed:\n" + data["error"])
    out.write(FILE, json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return []


# -- the objects the pages use ------------------------------------------------------


def slug(text: str) -> str:
    """"What's Wrong" -> "whats-wrong", "Delete/Keep Body" -> "delete-keep-body"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower().replace("'", "")).strip("-")


@dataclass
class Prop:
    name: str
    type: str
    group: str
    doc: str
    hidden: bool
    readonly: bool
    default: object = None
    choices: list | None = None

    @property
    def user(self) -> bool:
        """Shown in the Property editor and meant to be set."""
        return not self.hidden and self.group not in ("Base", "Result")


@dataclass
class Tool:
    name: str               # SD_Fillet
    label: str              # Fillet
    tooltip: str
    pixmap: str
    shortcut: str
    checkable: bool
    group: list[str] | None
    props: list[Prop] = field(default_factory=list)
    feature_type: str = ""
    section: str = ""       # the Solid Design menu it is in first
    menus: list[list[str]] = field(default_factory=list)
    toolbars: list[tuple[str, str | None]] = field(default_factory=list)  # (toolbar, drop-down)

    @property
    def slug(self) -> str:
        return slug(self.label)

    @property
    def icon_file(self) -> Path | None:
        p = env.REPO / self.pixmap if self.pixmap and not self.pixmap.startswith(":") else None
        return p if p is not None and p.is_file() else None


@dataclass
class Catalog:
    data: dict
    tools: dict[str, Tool]          # every command, by name
    sections: list[tuple[str, list[str]]]  # [(section, [command])], in menu order

    @property
    def documented(self) -> list[Tool]:
        """Every tool that gets a page, in section order."""
        seen, out = set(), []
        for _s, names in self.sections:
            for n in names:
                if n not in seen:
                    seen.add(n)
                    out.append(self.tools[n])
        return out


#: The workbench's own menu; its submenus are the sections.
MENU = "&Solid Design"
#: The top of the menu (Part, Sketch) and its last block (the keyboard and
#: view tools) get these section names.
TOP, LAST = "Part and sketch", "Working faster"


def _clean(text: str) -> str:
    return text.replace("&", "")


def load() -> Catalog:
    data = json.loads((env.DOCS / FILE).read_text(encoding="utf-8"))
    tools: dict[str, Tool] = {}
    for c in data["commands"]:
        tools[c["name"]] = Tool(name=c["name"], label=c["label"], tooltip=c["tooltip"],
                                pixmap=c["pixmap"], shortcut=c["shortcut"],
                                checkable=c["checkable"], group=c.get("group"))
    for name, f in data["features"].items():
        if name in tools:
            tools[name].props = [Prop(**{k: p.get(k) for k in Prop.__dataclass_fields__})
                                 for p in f["properties"]]
            tools[name].feature_type = f.get("type") or f.get("kind") or ""
    wb = data["workbench"]
    sections: list[tuple[str, list[str]]] = []
    for m in wb["menus"]:
        path = [_clean(p) for p in m["path"]]
        for c in m["commands"]:
            if c in tools:
                tools[c].menus.append(path)
        if path[0] != _clean(MENU):
            continue
        name = path[1] if len(path) > 1 else (TOP if not sections else LAST)
        cmds = [c for c in m["commands"] if c in tools and not tools[c].group]
        if cmds:
            sections.append((name, cmds))
    for tb in wb["toolbars"]:
        for c in tb["commands"]:
            t = tools.get(c)
            if t is None:
                continue
            t.toolbars.append((tb["name"], None))
            for child in t.group or []:
                if child in tools:
                    tools[child].toolbars.append((tb["name"], t.label))
    for sec, names in sections:
        for n in names:
            if not tools[n].section:
                tools[n].section = sec
    return Catalog(data=data, tools=tools, sections=sections)
