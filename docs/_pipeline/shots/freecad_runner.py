# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileCopyrightText: 2026 Ryan Kembrey <ryan.FreeCAD@gmail.com>
# SPDX-FileNotice: Part of the Solid Design addon.

"""Runs inside FreeCAD (``freecad freecad_runner.py``) to take screenshots.

Started by engine.py with:

    SD_REPO         the repository
    SD_SHOTS_OUT    folder to write <id>.png, panels/<id>.json and results.json into
    SD_SHOTS_IDS    comma-separated shot ids to take

and a throwaway FreeCAD user folder, so nothing of anyone's own FreeCAD shows.
Writes results.json: {id: "ok" | error}.
"""

import json
import os
import sys
import traceback

REPO = os.environ["SD_REPO"]
OUT = os.environ["SD_SHOTS_OUT"]
IDS = [i for i in os.environ.get("SD_SHOTS_IDS", "").split(",") if i]

sys.path.insert(0, os.path.join(REPO, "docs"))
sys.path.insert(0, REPO)
import freecad  # noqa: E402  FreeCAD's own namespace package: add the workbench to it

if os.path.join(REPO, "freecad") not in list(freecad.__path__):
    freecad.__path__.insert(0, os.path.join(REPO, "freecad"))

import FreeCAD as App  # noqa: E402
import FreeCADGui as Gui  # noqa: E402
from PySide6 import QtCore  # noqa: E402

#: The main window, inside engine.SCREEN.
WINDOW = (1200, 880)
#: The left dock (tree and task panel).
PANEL_WIDTH = 360


def prepare() -> None:
    """The same FreeCAD for every run: window size and position, Solid Design
    active. (Don't close the Start page from here: its timers then crash FreeCAD.)"""
    from PySide6 import QtGui, QtWidgets

    # One font everywhere: the environment's Ubuntu, whatever the machine has.
    QtWidgets.QApplication.setFont(QtGui.QFont("Ubuntu", 10))
    mw = Gui.getMainWindow()
    mw.showNormal()
    mw.resize(*WINDOW)
    mw.move(0, 0)
    import freecad.SolidDesign.init_gui  # noqa: F401  registers the workbench and its commands

    Gui.activateWorkbench("SolidDesignWorkbench")
    _layout(mw)
    _no_message_boxes()


def _layout(mw) -> None:
    """The classic layout: the tree and the task panel as tabs of one dock on
    the left (as FreeCAD's Combo View), nothing else docked, nothing overlaid."""
    from PySide6 import QtCore, QtWidgets

    docks = {d.objectName(): d for d in mw.findChildren(QtWidgets.QDockWidget)}
    for name, d in docks.items():
        if name not in ("Model", "Tasks"):
            d.hide()
    model, tasks = docks.get("Model"), docks.get("Tasks")
    left = QtCore.Qt.DockWidgetArea.LeftDockWidgetArea
    if model is not None and tasks is not None:
        mw.addDockWidget(left, tasks)
        tasks.setFloating(False)
        mw.tabifyDockWidget(model, tasks)
        tasks.show()
        mw.resizeDocks([model], [PANEL_WIDTH], QtCore.Qt.Orientation.Horizontal)
        model.raise_()
    # The property editor under the tree: closed (the pictures are about the tree).
    if model is not None:
        for sp in model.findChildren(QtWidgets.QSplitter):
            if sp.count() == 2:
                sp.setSizes([1, 0])


def _no_message_boxes() -> None:
    """Nobody is there to click OK: a message box would wait until the timeout.
    Print it instead and answer with the box's default."""
    from PySide6 import QtWidgets

    box = QtWidgets.QMessageBox

    def make(kind, answer):
        def show(_parent, title, text, *args, **kwargs):
            print(f"[{kind}] {title}: {text}", file=sys.stderr, flush=True)
            return answer
        return staticmethod(show)

    box.information = make("information", box.StandardButton.Ok)
    box.warning = make("warning", box.StandardButton.Ok)
    box.critical = make("critical", box.StandardButton.Ok)
    box.question = make("question", box.StandardButton.No)


def _write_results(results: dict) -> None:
    """Written after every shot, so a crash keeps what was already taken."""
    path = os.path.join(OUT, "results.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    os.replace(path + ".tmp", path)


def main() -> None:
    import faulthandler

    # If FreeCAD crashes, engine.py reports the shot named in running.txt,
    # with the Python stack from crash.txt.
    crash = open(os.path.join(OUT, "crash.txt"), "w", encoding="utf-8")
    faulthandler.enable(crash, all_threads=False)
    results = {}
    try:
        prepare()
        from _pipeline.shots import REGISTRY, scenes, tools  # noqa: F401  (registers the shots)

        ctx = scenes.Context(Gui.getMainWindow())
        os.makedirs(os.path.join(OUT, "panels"), exist_ok=True)
        for shot_id in IDS:
            shot = REGISTRY.get(shot_id)
            if shot is None:
                results[shot_id] = "no such shot"
                continue
            with open(os.path.join(OUT, "running.txt"), "w", encoding="utf-8") as f:
                f.write(shot_id)
            try:
                ctx.record = None
                image = shot.fn(ctx)
                if image is None or image.isNull():
                    raise RuntimeError("the shot returned no image")
                if not image.save(os.path.join(OUT, f"{shot_id}.png")):
                    raise RuntimeError("could not save the image")
                if ctx.record is not None:
                    with open(os.path.join(OUT, "panels", f"{shot_id}.json"), "w", encoding="utf-8") as f:
                        json.dump(ctx.record, f, indent=1, ensure_ascii=False)
                results[shot_id] = "ok"
            except Exception:
                results[shot_id] = traceback.format_exc()
            finally:
                ctx.reset()
                _write_results(results)
    except Exception:
        results["_runner"] = traceback.format_exc()
    _write_results(results)
    try:
        os.remove(os.path.join(OUT, "running.txt"))
    except OSError:
        pass
    os._exit(0)


QtCore.QTimer.singleShot(1500, main)
