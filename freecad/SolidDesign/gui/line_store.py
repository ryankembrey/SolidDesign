# SPDX-License-Identifier: LGPL-2.1-or-later
"""What the command line keeps: aliases, key bindings and tool defaults (yours,
kept between sessions in FreeCAD's parameters), and registers (named selections)
and marks (saved views), kept in the document so they travel with the file.

No Qt here: the headless tests use it.
"""

import json

import FreeCAD as App

PARAMS = "User parameter:BaseApp/Preferences/Mod/SolidDesign"
META_REGISTERS = "SolidDesign.Registers"
META_MARKS = "SolidDesign.Marks"


def _p():
    return App.ParamGet(PARAMS)


def _load(key):
    try:
        v = json.loads(_p().GetString(key, "") or "{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def _save(key, value):
    _p().SetString(key, json.dumps(value, sort_keys=True))


# ------------------------------------------------------------------ aliases

def aliases():
    """{name: the line it stands for}."""
    return _load("LineAliases")


def set_alias(name, line):
    a = aliases()
    a[name.lower()] = line.strip()
    _save("LineAliases", a)


def remove_alias(name):
    a = aliases()
    gone = a.pop(name.lower(), None)
    _save("LineAliases", a)
    return gone is not None


# ------------------------------------------------------------------ bindings

def bindings():
    """{keys typed in the 3D view ("gf"): the line they run}."""
    return _load("LineBindings")


def set_binding(keys, line):
    b = bindings()
    b[keys] = line.strip()
    _save("LineBindings", b)


def remove_binding(keys):
    b = bindings()
    gone = b.pop(keys, None)
    _save("LineBindings", b)
    return gone is not None


# ------------------------------------------------------------------ defaults

def defaults():
    """{command: {property: the value as typed}}: what a tool uses unless the
    line says otherwise."""
    return _load("LineDefaults")


def set_default(cmd, prop, value):
    d = defaults()
    d.setdefault(cmd, {})[prop] = value
    _save("LineDefaults", d)


def remove_default(cmd, prop=None):
    d = defaults()
    if cmd not in d:
        return False
    if prop is None:
        del d[cmd]
    elif d[cmd].pop(prop, None) is None:
        return False
    if cmd in d and not d[cmd]:
        del d[cmd]
    _save("LineDefaults", d)
    return True


# ------------------------------------------------------------------ in the document

def _meta(doc, key):
    try:
        v = json.loads(dict(doc.Meta).get(key, "") or "{}")
        return v if isinstance(v, dict) else {}
    except (ValueError, AttributeError):
        return {}


def _set_meta(doc, key, value):
    m = dict(doc.Meta)
    if value:
        m[key] = json.dumps(value, sort_keys=True)
    else:
        m.pop(key, None)
    doc.Meta = m


def registers(doc):
    """{name: [{"obj", "sub", "fp"}]}: named selections, with each element's
    fingerprint so they are found again after the model changes."""
    return _meta(doc, META_REGISTERS) if doc is not None else {}


def set_register(doc, name, items):
    r = registers(doc)
    r[name] = items
    _set_meta(doc, META_REGISTERS, r)


def remove_register(doc, name):
    r = registers(doc)
    gone = r.pop(name, None)
    _set_meta(doc, META_REGISTERS, r)
    return gone is not None


def marks(doc):
    """{name: the camera, as Inventor text}: saved views."""
    return _meta(doc, META_MARKS) if doc is not None else {}


def set_mark(doc, name, camera):
    m = marks(doc)
    m[name] = camera
    _set_meta(doc, META_MARKS, m)


def remove_mark(doc, name):
    m = marks(doc)
    gone = m.pop(name, None)
    _set_meta(doc, META_MARKS, m)
    return gone is not None
