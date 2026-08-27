# QC Bake for Maya
# ================
# A baking-namepair utility by Mutaform Studio, ported from the QC Bake
# Blender extension.
#
# Select the low/high poly meshes for an asset and press "Create Namepair".
# QC Bake works out which object is high and which is low (by triangle, face
# or vertex count) and renames them into a matching pair using the suffixes of
# the chosen naming convention. Multiple high-poly meshes, an optional cage
# and automatic outliner organisation are supported.
#
# This package is layered so the interesting parts stay testable:
#
#   core     pure logic - naming rules, hi/lo choice, grouping maths.
#            Imports nothing from Maya, so it runs under plain python.
#   scene    the only module that talks to maya.cmds for data operations.
#   prefs    settings, persisted in Maya optionVars.
#   commands one module per user-facing action, orchestrating core + scene.
#   ui       the PySide6 dockable panel.

VERSION = (1, 1, 2)
VERSION_STRING = ".".join(str(part) for part in VERSION)

# The Blender extension release this port carries feature parity with.
PORTED_FROM = "2.0.0"


def show():
    """Open (or raise) the QC Bake panel. The single public entry point."""
    from .ui import panel
    return panel.show()
