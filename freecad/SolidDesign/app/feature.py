# SPDX-License-Identifier: LGPL-2.1-or-later
"""Base class for every Solid Design feature (spec section 5.3).

A feature is a Part::FeaturePython. It reads the body set of the feature before
it (``BaseFeature``) and writes a new body set:
- ``Shape`` is the compound of the bodies after it;
- ``BodyIds`` / ``BodyKinds`` / ``BodyFeatures`` give each child's ID, kind and
  the last feature that changed it.

A feature that fails keeps its error (``ErrorMessage``) and passes the bodies
before it through unchanged, so the features after it still compute
(SolidWorks behaviour). Rolled-back and suppressed features pass through too.

Proxies are stateless: everything is in properties.
"""

import json
import traceback

import FreeCAD as App
import Part

from ..core import topo
from ..core.bodies import BodySet
from . import perf, refs, util

# Features being edited in a panel that shows the model before them (Fillet,
# Chamfer): they still compute their result for the preview while the rollback
# bar sits just above them. Session state only, never saved.
EDITING = set()


class FeatureProxy(object):
    SD_ROLE = "feature"
    TYPE = "Feature"          # overridden: "Extrude", "Revolve"...
    LABELS = ("Feature",)     # default label prefix per mode

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    # -------------------------------------------------- properties
    def setup(self, obj):
        g = "Base"
        util.add_prop(obj, "App::PropertyLink", "BaseFeature", g,
                      "The feature before this one in the history")
        util.add_prop(obj, "App::PropertyBool", "Suppressed", g,
                      "Suppress the feature: it passes the bodies through unchanged", False)
        util.add_prop(obj, "App::PropertyStringList", "BodyIds", "Result",
                      "Body ID of each child of Shape")
        util.add_prop(obj, "App::PropertyStringList", "BodyKinds", "Result",
                      "solid or surface, per body")
        util.add_prop(obj, "App::PropertyStringList", "BodyFeatures", "Result",
                      "The last feature that changed each body")
        util.add_prop(obj, "Part::PropertyPartShape", "AddSubShape", "Result",
                      "Material added or removed, for the preview")
        util.add_prop(obj, "App::PropertyString", "ErrorMessage", "Result",
                      "Why the feature failed (empty when it worked)", "")
        util.add_prop(obj, "App::PropertyString", "WarningMessage", "Result",
                      "Warnings from the last recompute", "")
        util.add_prop(obj, "App::PropertyString", "IdMemory", "Result",
                      "Bodies this feature made last time, to keep their IDs stable", "")
        util.add_prop(obj, "App::PropertyString", "Pieces", "Result",
                      "Pieces made by a split, for Bodies to Keep (JSON)", "[]")
        util.add_prop(obj, "App::PropertyMap", "RefFingerprints", "Result",
                      "Fingerprints of picked faces/edges, to repair lost references")
        util.add_prop(obj, "App::PropertyString", "RefRepairs", "Result",
                      "References repaired from their fingerprints, not yet checked (JSON)",
                      "[]")
        util.add_prop(obj, "App::PropertyString", "RefLost", "Result",
                      "References that couldn't be found at the last recompute (JSON)", "[]")
        util.add_prop(obj, "App::PropertyBool", "RolledBack", "Result",
                      "True when the feature is below the rollback bar", False)
        util.add_prop(obj, "App::PropertyString", "AutoLabel", "Base",
                      "The label the feature was given automatically", "")
        util.add_prop(obj, "App::PropertyInteger", "SchemaVersion", "Base",
                      "File format version of this feature", util.SCHEMA_VERSION)
        for p in ("BaseFeature", "BodyIds", "BodyKinds", "BodyFeatures", "AddSubShape",
                  "IdMemory", "Pieces", "RefFingerprints", "AutoLabel", "SchemaVersion",
                  "RolledBack", "RefRepairs", "RefLost"):
            util.hide_prop(obj, p)
        for p in ("ErrorMessage", "WarningMessage"):
            util.readonly_prop(obj, p)

    def onDocumentRestored(self, obj):
        self.setup(obj)
        self.migrate(obj)

    def migrate(self, obj):
        """Bring an older file up to the current schema. Never break a file."""
        if obj.SchemaVersion < util.SCHEMA_VERSION:
            obj.SchemaVersion = util.SCHEMA_VERSION

    def dumps(self):
        return None

    def loads(self, state):
        return None

    # -------------------------------------------------- history
    def base_bodies(self, obj):
        base = obj.BaseFeature
        if base is None:
            return BodySet()
        return BodySet.from_columns(base.Shape, list(base.BodyIds), list(base.BodyKinds),
                                    list(base.BodyFeatures))

    def is_rolled_back(self, obj):
        if obj.Name in EDITING:
            return False
        part = util.part_of(obj)
        if part is None:
            return False
        feats = util.features(part)
        tip = part.Tip
        if tip is None:
            return True
        if obj not in feats or tip not in feats:
            return False
        return feats.index(obj) > feats.index(tip)

    # -------------------------------------------------- recompute
    def execute(self, obj):
        if not perf.enabled():
            return self._execute(obj)
        label = obj.Label.rstrip(u"\u200b")
        perf.count("features recomputed", u"{} [{}]".format(label, obj.Name))
        with perf.span("feature", u"{} ({})".format(label, self.TYPE)):
            return self._execute(obj)

    def _execute(self, obj):
        try:
            base = self.base_bodies(obj)
        except topo.GeometryError as e:
            base = BodySet()
            obj.ErrorMessage = str(e)
            self.write(obj, base, None)
            return
        rolled = self.is_rolled_back(obj)
        if obj.RolledBack != rolled:
            obj.RolledBack = rolled
        if rolled and not obj.Shape.isNull():
            # Below the rollback bar a feature is frozen, as in SolidWorks: it keeps
            # its last result. Sketches attached to its faces stay attached (a
            # pass-through result would lose those faces, and FreeCAD would break
            # or re-attach the sketches); rolling forward recomputes it.
            return
        if rolled or obj.Suppressed or util.part_of(obj) is None:
            self.write(obj, base, None)
            return
        warnings = []
        refs.start_recompute(obj)
        try:
            res, preview = self.compute(obj, base)
            out = res.bodies
            warnings.extend(res.warnings)
            error = ""
        except topo.GeometryError as e:
            out, preview, error = base, None, str(e)
        except Exception as e:
            out, preview = base, None
            error = "Internal error: {} (see the Report view)".format(e)
            util.console_error("{} failed:\n{}".format(obj.Label, traceback.format_exc()))
        # Lost element maps are a developer diagnostic: the Report view, not the user.
        for m in topo.map_warnings:
            App.Console.PrintLog("Solid Design: {}: {}\n".format(obj.Label, m))
        del topo.map_warnings[:]
        if obj.ErrorMessage != error:
            obj.ErrorMessage = error
        # A repaired reference stays a warning until it has been checked.
        for m in refs.pending_warnings(obj):
            if m not in warnings:
                warnings.append(m)
        w = "; ".join(warnings)
        if obj.WarningMessage != w:
            obj.WarningMessage = w
        self.write(obj, out, preview)

    @perf.traced("feature.write")
    def write(self, obj, bodies, preview):
        try:
            comp = bodies.to_compound(obj.ID)
        except topo.GeometryError:
            comp = Part.makeCompound([b.shape for b in bodies])
        obj.Shape = comp
        ids, kinds, feats = bodies.columns()
        if list(obj.BodyIds) != ids:
            obj.BodyIds = ids
        if list(obj.BodyKinds) != kinds:
            obj.BodyKinds = kinds
        if list(obj.BodyFeatures) != feats:
            obj.BodyFeatures = feats
        obj.AddSubShape = preview if preview is not None else Part.Shape()

    def compute(self, obj, base):
        """Return (core.features.common.Result, preview shape). Raise GeometryError."""
        raise NotImplementedError

    # -------------------------------------------------- helpers for subclasses
    @staticmethod
    def store_pieces(obj, res):
        data = []
        for pid, s, parent in res.pieces:
            c = topo.centroid(s)
            data.append({"id": pid, "parent": parent, "size": topo.size_of(s),
                         "c": [c.x, c.y, c.z]})
        text = json.dumps(data)
        if obj.Pieces != text:
            obj.Pieces = text

    def default_label(self, obj):
        return self.LABELS[0]

    def rename_for_mode(self, obj):
        """Follow the mode in the label, unless the user renamed the feature."""
        prefix = self.default_label(obj)
        if obj.AutoLabel and obj.Label != obj.AutoLabel:
            return
        if obj.AutoLabel and obj.AutoLabel.startswith(prefix):
            return
        obj.AutoLabel = util.set_label(obj, prefix)
