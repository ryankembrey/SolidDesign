# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Solid Design workbench: toolbars and menus laid out like SolidWorks'."""

import FreeCADGui as Gui

from freecad.SolidDesign import icon


class SolidDesignWorkbench(Gui.Workbench):
    MenuText = "Solid Design"
    ToolTip = "Model parts the SolidWorks way, multi-body from the start"
    Icon = icon("SolidDesign")

    PART = ["SD_Part"]
    SKETCH = ["SD_Sketch"]
    REFERENCE = ["SD_Plane", "SD_Axis", "SD_CoordinateSystem", "SD_Point", "SD_BoundingBox",
                 "SD_CenterOfMass"]
    FEATURES = ["SD_Extrude", "SD_Revolve", "SD_Sweep", "SD_Loft", "SD_Boundary", "SD_Fillet",
                "SD_Chamfer", "SD_Rib", "SD_Wrap", "SD_Draft", "SD_Shell", "SD_Dome",
                "SD_Intersect", "SD_HoleWizard", "SD_Threads", "SD_Fastening", "SD_Patterns",
                "SD_Mirror"]
    FEATURES_MENU = ["SD_Extrude", "SD_Revolve", "SD_Sweep", "SD_Loft", "SD_Boundary",
                     "SD_Fillet", "SD_Chamfer", "SD_Rib", "SD_Wrap", "SD_Draft", "SD_Shell",
                     "SD_Dome", "SD_Intersect", "SD_HoleWizard", "SD_Thread",
                     "SD_CosmeticThread", "Separator", "SD_MountingBoss", "SD_SnapHook",
                     "SD_LipGroove", "SD_Vent", "Separator", "SD_Mirror"]
    PATTERNS = ["SD_LinearPattern", "SD_CircularPattern", "SD_CurvePattern",
                "SD_SketchPattern", "SD_TablePattern", "SD_FillPattern",
                "SD_VariablePattern", "SD_Mirror"]
    CURVES = ["SD_SplitLine", "SD_ProjectedCurve", "SD_CompositeCurve", "SD_CurveXYZ",
              "SD_CurvePoints", "SD_Helix"]
    BODIES = ["SD_Combine", "SD_Split", "SD_DeleteBody", "SD_MoveCopy", "SD_DeformBodies",
              "SD_MoveFace", "SD_DeleteFace", "SD_ReplaceFace"]
    BODIES_MENU = ["SD_Combine", "SD_Split", "SD_DeleteBody", "SD_MoveCopy", "SD_Flex",
                   "SD_Deform", "SD_Indent", "SD_Freeform", "SD_Scale", "SD_MoveFace",
                   "SD_DeleteFace", "SD_ReplaceFace"]
    SURFACE_MAKERS = ["SD_ExtrudedSurface", "SD_RevolvedSurface", "SD_SweptSurface",
                      "SD_LoftedSurface", "SD_BoundarySurface"]
    SURFACES = SURFACE_MAKERS + [
        "SD_PlanarSurface", "SD_OffsetSurface", "SD_FilledSurface", "SD_ExtendSurface",
        "SD_TrimSurface", "SD_Knit", "SD_MoreSurfaces", "SD_Thicken", "SD_SurfaceCut"]
    SURFACES_MENU = SURFACE_MAKERS + [
        "Separator", "SD_PlanarSurface", "SD_OffsetSurface", "SD_FilledSurface",
        "SD_ExtendSurface", "SD_TrimSurface", "SD_UntrimSurface", "SD_Knit",
        "SD_RuledSurface", "SD_RadiateSurface", "SD_MidSurface", "SD_SurfaceFlatten",
        "Separator", "SD_Thicken", "SD_SurfaceCut"]
    EVALUATE = ["SD_Rebuild", "SD_WhatsWrong"]

    # Toolbars, left to right. The names are new (FreeCAD remembers where toolbars
    # sat by name), so this order takes over from the old layout.
    TOOLBARS = [
        ("Solid Design Part", PART),
        ("Solid Design Sketch", SKETCH),
        ("Solid Design Features", FEATURES),
        ("Solid Design Bodies", BODIES),
        ("Solid Design Reference Geometry", ["SD_ReferenceGeometry"]),
        ("Solid Design Surfaces", SURFACES),
        ("Solid Design Curves", ["SD_Curves"]),
        ("Solid Design Evaluate", EVALUATE),
    ]

    def Initialize(self):
        import importlib
        importlib.import_module("SketcherGui")     # the sketch tool uses Sketcher's icon
        from freecad.SolidDesign.gui import commands
        from freecad.SolidDesign.app import part
        commands.register()
        from freecad.SolidDesign.gui import evaluate, context_bar, ref_labels
        evaluate.register()
        Gui.addCommand("SD_ContextToolbar", context_bar.ToggleCommand())
        Gui.addCommand("SD_ReferenceLabels", ref_labels.ToggleCommand())
        ref_labels.install()
        from freecad.SolidDesign.gui import health_badge
        health_badge.install()
        part.install_observer()
        from freecad.SolidDesign.gui import instant3d, sketch_edit, temp_axis
        sketch_edit.install()
        temp_axis.install()
        instant3d.install()
        context_bar.install()
        from freecad.SolidDesign.gui import command_line, reveal, view_menus
        command_line.install()
        view_menus.install()
        reveal.install()
        for name, cmds in self.TOOLBARS:
            self.appendToolbar(name, cmds)
        # The workbench's own menu, with every tool.
        m = "&Solid Design"
        self.appendMenu(m, self.PART + self.SKETCH + ["Separator"])
        self.appendMenu([m, "Features"], self.FEATURES_MENU)
        self.appendMenu([m, "Patterns"], self.PATTERNS)
        self.appendMenu([m, "Bodies"], self.BODIES_MENU)
        self.appendMenu([m, "Reference Geometry"], self.REFERENCE)
        self.appendMenu([m, "Surfaces"], self.SURFACES_MENU)
        self.appendMenu([m, "Curves"], self.CURVES)
        self.appendMenu([m, "Evaluate"], self.EVALUATE + ["Separator", "SD_PerfTrace"])
        self.appendMenu(m, ["Separator", "SD_CommandSearch", "SD_CommandLine", "SD_RepeatLast",
                            "SD_ContextToolbar", "SD_ReferenceLabels"])
        # SolidWorks' Insert menu structure, where FreeCAD lets it.
        self.appendMenu("&Insert", self.PART + self.SKETCH + ["Separator"])
        self.appendMenu(["&Insert", "Features"],
                        [c for c in self.FEATURES if c != "SD_Patterns"] + self.BODIES_MENU)
        self.appendMenu(["&Insert", "Pattern/Mirror"], self.PATTERNS)
        self.appendMenu(["&Insert", "Surface"], self.SURFACES_MENU)
        self.appendMenu(["&Insert", "Reference Geometry"], self.REFERENCE)
        self.appendMenu(["&Insert", "Curve"], self.CURVES)
        self.appendMenu(["&Tools", "Evaluate"], self.EVALUATE + ["Separator", "SD_PerfTrace"])

    def Activated(self):
        from freecad.SolidDesign.gui import tooltips
        tooltips.install()

    def Deactivated(self):
        from freecad.SolidDesign.gui import view_menus
        view_menus.restore()            # FreeCAD's own right-click menus back

    def ContextMenu(self, recipient):
        pass

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(SolidDesignWorkbench())
