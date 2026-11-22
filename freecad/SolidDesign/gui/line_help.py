# SPDX-License-Identifier: LGPL-2.1-or-later
"""The command line's cheat sheet: ":help" (or ":h", ":h sel") shows it over
the 3D view; Esc closes it.

HELP is plain data, so the documentation site's command line page is made from
it too. Keep each line short: what to type, then what it does.
"""

#: [(topic, title, [(what to type, what it does)])]
HELP = [
    ("tools", "Tools", [
        ("fillet 2", "a tool and its main value(s), in order"),
        ("extrude 10 cut", "a word picks an option"),
        ("lp 20 4", "names match loosely: Linear Pattern, spacing 20, 4 of them"),
        ("chamfer d=1.5 flip", "name=value sets any option; a yes/no option by its name"),
        ("fillet Width/2", "a VarSet variable makes a live expression"),
        ("fillet =Width/2 + 1mm", "= starts any FreeCAD expression; units work anywhere"),
        ("Enter", "makes it (one undo step); if it can't, its panel opens"),
    ]),
    ("sel", "Picking: sel=", [
        ("sel=  then Tab", "labels on what the tool can use; type one to pick it"),
        ("sel=jk,dl", "several picks; the comma is added for you"),
        ("sel=jk]  sel=jk[", "step to the next neighbour clockwise (] ) or back ([ )"),
        ("sel=jk+", "step along tangent edges"),
        ("sel=jk,tangent", "add the edges that run on smoothly (tan)"),
        ("sel=jk,loop", "add the loop round the face facing you (otherloop: the other)"),
        ("sel=jk,chain", "add the edges joined end to end"),
        ("sel=new", "what the last feature made"),
        ("sel=last.top", "the far end of the last feature (last.caps, last.sides, last)"),
        ("sel=edges", "every edge shown (faces, vertices; * for both)"),
        ("sel=jk:edges", "the edges of face jk"),
        ("sel=@a", "register a"),
        ("sel=front", "the origin's Front Plane (top, right)"),
        ("sel=Plane1", "anything in the tree by name; Body.Edge3 an element"),
        ("sel=jk,dl >a", "keep the picks in register a"),
    ]),
    ("filters", "Filters (after a colon)", [
        ("edges:circular", "circles and arcs (linear, curved)"),
        ("edges:concave", "inside corners (convex: outside)"),
        ("faces:planar", "flat faces (cylindrical, conical, spherical)"),
        ("edges:top", "the highest (bottom, front, back, left, right, +x...)"),
        ("faces:largest", "the biggest (smallest; nearest: to the pointer)"),
        ("edges:r<5", "radius under 5 (r d len area x y z with < > = <= >=)"),
        ("faces:par:z", "lying flat: normal along Z (perp:z for walls)"),
        ("edges:par:z", "running along Z"),
    ]),
    ("features", "Features by name", [
        ("Fillet1 r=3", "change a feature without opening it"),
        ("last d=+2", "the last feature; + and - add to what it is"),
        ("edit Fillet1", "open a feature (Tab labels the tree)"),
        ("edit jk", "open the feature that made face jk"),
        ("suppress /Fillet/", "names or /pattern/ (unsuppress)"),
        ("rollto Boss-Extrude2", "move the rollback bar (rollto end)"),
        ("set r=2->3 /Fillet/", "every 2 mm radius to 3 mm (set r=3 /Fillet/: all)"),
    ]),
    ("bodies", "Bodies and views", [
        ("hide Body2", "hide bodies (show)"),
        ("isolate Body1", "show only these (showall)"),
        ("mark a", "save the view as a"),
        ("'a", "back to view a (marks lists them, delmark a)"),
    ]),
    ("copy", "Copying", [
        ("yank sel=jk", "copy a face's area, an edge's length or radius, a point"),
        ("yank Fillet1.Radius", "copy a feature's value"),
        ("registers", "the registers (delreg a)"),
    ]),
    ("yours", "Making it yours", [
        ("alias m6 = holewizard size=m6", "then: m6 sel=jk (unalias m6)"),
        ("bind gf = fillet 1 sel=new", "type gf in the 3D view to run it (unbind gf)"),
        ("set fillet.r=1", "a tool's default: fillet alone uses 1 mm (unset fillet.r)"),
        ("alias · bind · set", "list them"),
    ]),
    ("keys", "Keys", [
        (":", "opens the line (in a panel: labels its controls)"),
        (".", "makes the last feature again on what you point at"),
        ("Tab  Shift+Tab", "complete; the grey rest of a word is what Tab adds"),
        ("→", "take the grey rest"),
        ("↑ ↓", "earlier lines"),
        ("Ctrl+R", "search earlier lines"),
        ("Ctrl+X", "label hidden ones too (behind, facing away), model see-through"),
        ("click", "on the model while picking: adds its label (Ctrl+click: out)"),
        ("toolbar", "labels on the toolbar buttons; a label or a name clicks one (tb)"),
        ("help  ·  h sel", "this sheet; with a topic, that part"),
        ("Esc", "close"),
    ]),
    ("panel", "In a panel", [
        (": then a label", "go to that control (a field, a button, a box)"),
        ("ds=10", "set the control labelled ds"),
        ("depth=10", "or by its name"),
    ]),
]


def topics():
    return [t for t, _title, _rows in HELP]


def find(topic):
    """The topic a typed word means ("sel", "filter", "key"...), or None."""
    t = (topic or "").lower().strip()
    for name, title, _rows in HELP:
        if name.startswith(t) or title.lower().startswith(t):
            return name
    return None


def html(focus=None):
    """The cheat sheet as rich text, in two columns."""
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    cells = []
    for name, title, rows in HELP:
        lines = "".join(
            u"<tr><td style='padding:1px 10px 1px 0; white-space:pre'><code>{}</code></td>"
            u"<td style='padding:1px 0'>{}</td></tr>".format(esc(a), esc(b)) for a, b in rows)
        here = u" \u2190" if name == focus else ""
        cells.append(u"<a name='{}'></a><h4>{}{}</h4><table cellspacing=0>{}</table>"
                     .format(name, esc(title), here, lines))
    half = (len(cells) + 1) // 2
    return (u"<table width='100%'><tr><td valign='top' width='50%' style='padding-right:14px'>"
            u"{}</td><td valign='top' width='50%'>{}</td></tr></table>"
            u"<p style='color:gray'>Esc closes this. :h sel, :h filters... jump to a part.</p>"
            .format("".join(cells[:half]), "".join(cells[half:])))


def show(parent, focus=None):
    """The cheat sheet over the 3D view whose widget (or top layer) is ``parent``,
    in front of any overlaid docks. Esc closes it."""
    from PySide import QtCore, QtWidgets
    from . import top_layer
    view = top_layer.view_of(parent)
    parent = top_layer.for_view(view)

    class Sheet(QtWidgets.QFrame):
        def __init__(self, parent):
            super(Sheet, self).__init__(parent)
            self.setObjectName("SD_LineHelp")
            self.setAutoFillBackground(True)
            self.setFrameShape(QtWidgets.QFrame.StyledPanel)
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(10, 8, 10, 8)
            head = QtWidgets.QHBoxLayout()
            title = QtWidgets.QLabel("Command line")
            f = title.font()
            f.setBold(True)
            title.setFont(f)
            head.addWidget(title)
            head.addStretch(1)
            close = QtWidgets.QToolButton()
            close.setText(u"×")
            close.setAutoRaise(True)
            close.setToolTip("Close (Esc)")
            close.clicked.connect(self.close)
            head.addWidget(close)
            lay.addLayout(head)
            self.text = QtWidgets.QTextBrowser()
            self.text.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.text.setOpenLinks(False)
            self.text.installEventFilter(self)
            lay.addWidget(self.text, 1)
            parent.installEventFilter(self)

        def fill(self, focus):
            self.text.setHtml(html(focus))
            if focus:
                self.text.scrollToAnchor(focus)

        def place(self):
            p = self.parentWidget()
            m = 24
            self.setGeometry(m, m, max(300, p.width() - 2 * m), max(200, p.height() - 2 * m))

        def eventFilter(self, obj, ev):
            if obj is self.parentWidget() and ev.type() == QtCore.QEvent.Resize:
                self.place()
                return False
            if ev.type() == QtCore.QEvent.KeyPress and ev.key() == QtCore.Qt.Key_Escape:
                self.close()
                return True
            return super(Sheet, self).eventFilter(obj, ev)

        def keyPressEvent(self, ev):
            if ev.key() == QtCore.Qt.Key_Escape:
                self.close()
                return
            super(Sheet, self).keyPressEvent(ev)

        def closeEvent(self, ev):
            try:
                self.parentWidget().removeEventFilter(self)
                view.setFocus()
            except Exception:
                pass
            super(Sheet, self).closeEvent(ev)

    old = parent.findChild(QtWidgets.QFrame, "SD_LineHelp")
    if old is not None:
        old.close()
        old.deleteLater()
    s = Sheet(parent)
    s.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
    s.fill(focus)
    s.place()
    s.show()
    s.raise_()
    s.text.setFocus()
    return s
