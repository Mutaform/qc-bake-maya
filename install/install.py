"""QC Bake for Maya - installer.

Drag this file into a Maya viewport to install. That writes a module file
pointing back at wherever this repository sits, adds a QC Bake button to a
Mutaform shelf, and opens the panel.

It can also be run from the script editor:

    import sys
    sys.path.insert(0, r"D:\\Mutaform\\Mutaform Addons\\qc_bake-maya\\install")
    import install
    install.install()

Nothing is copied anywhere. The module file is a pointer, so pulling a new
version of the repository is all an update takes - no reinstall, no stale
second copy to get confused with.
"""

import os
import sys

import maya.cmds as cmds
import maya.mel as mel

MODULE_NAME = "qc_bake_maya"
SHELF_NAME = "Mutaform"
BUTTON_LABEL = "QC Bake"

# The shelf icon: the flame, in qc_bake_maya/resources/, drawn by
# icons_src/make_icon.py.
#
# It lives inside the package rather than beside it so that it travels - both
# into the release zip and, more importantly, through an update, which swaps
# the package folder and nothing else.
#
# A shelf button is 32x32, and that is the entire design constraint - the 32px
# file is the one Maya draws, the 64 and 128 are there for high-DPI displays.
# The studio mark was tried in the icon and dropped: at 32 pixels it either
# crowded the flame or turned into a dark smudge that read as dirt rather than
# as a logo.
SHELF_ICON_NAME = "qc_bake"
RESOURCE_DIR = os.path.join("qc_bake_maya", "resources")

# Used when the bundled icon cannot be found, so a broken path never leaves
# the button blank.
FALLBACK_ICON = ":/polyBakeSetEdit.png"

COMMAND = """import sys

QCBAKE_ROOT = r"{root}"
if QCBAKE_ROOT not in sys.path:
    sys.path.insert(0, QCBAKE_ROOT)

import qc_bake_maya
qc_bake_maya.show()
"""


def repo_root():
    """Return the repository root - the folder holding qc_bake_maya/."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def shelf_icon(size=32, root=None):
    """Return the icon path for the shelf button.

    Falls back to a Maya resource rather than an empty button if the bundled
    file is missing - a shelf button with no image is not obviously broken,
    it just quietly becomes impossible to find among thirty others.
    """
    root = root or repo_root()
    path = os.path.join(root, RESOURCE_DIR,
                        "%s_%d.png" % (SHELF_ICON_NAME, size))
    return path if os.path.isfile(path) else FALLBACK_ICON


def modules_dir():
    """Return this Maya version's user modules folder, creating it if needed.

    On a machine whose Documents folder is redirected to OneDrive - and with a
    localised folder name at that - this path is neither ASCII nor where the
    documentation says it is, so it is always asked of Maya rather than
    assembled by hand.
    """
    path = os.path.join(cmds.internalVar(userAppDir=True),
                        cmds.about(version=True), "modules")
    if not os.path.isdir(path):
        os.makedirs(path)
    return path


def module_file():
    return os.path.join(modules_dir(), MODULE_NAME + ".mod")


def write_module(root=None):
    """Write the .mod file that puts this repository on Maya's script path."""
    root = root or repo_root()
    from qc_bake_maya import VERSION_STRING  # noqa: E402 - needs the path first

    # "scripts: ." adds the module root itself, which is where the package
    # lives - verified against Maya 2025 rather than assumed.
    body = "+ {name} {version} {root}\nscripts: .\n".format(
        name=MODULE_NAME, version=VERSION_STRING, root=root.replace("\\", "/"))

    path = module_file()
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return path


def ensure_shelf():
    """Return the Mutaform shelf, creating it if this is the first tool on it."""
    top = mel.eval("$tmp = $gShelfTopLevel")
    if cmds.shelfLayout(SHELF_NAME, exists=True):
        return SHELF_NAME
    mel.eval('addNewShelfTab "%s";' % SHELF_NAME)
    cmds.tabLayout(top, edit=True, selectTab=SHELF_NAME)
    return SHELF_NAME


def add_shelf_button(root=None):
    """Put a QC Bake button on the Mutaform shelf, replacing any older one."""
    root = root or repo_root()
    shelf = ensure_shelf()

    for child in cmds.shelfLayout(shelf, query=True, childArray=True) or []:
        if cmds.control(child, query=True, exists=True) \
                and cmds.shelfButton(child, query=True, label=True) == BUTTON_LABEL:
            cmds.deleteUI(child)

    icon = shelf_icon(32, root)

    # No imageOverlayLabel: a word stamped across a 32-pixel icon obscures the
    # very thing that makes it findable. The tooltip carries the name.
    return cmds.shelfButton(
        parent=shelf,
        label=BUTTON_LABEL,
        annotation="QC Bake - high/low namepairs for texture baking",
        image=icon,
        image1=icon,
        sourceType="python",
        command=COMMAND.format(root=root),
    )


def refresh_shelf_icon():
    """Re-apply the icon after regenerating it, without a full reinstall."""
    add_shelf_button()
    mel.eval('saveAllShelves $gShelfTopLevel;')
    return shelf_icon()


def install():
    """Write the module, add the shelf button and open the panel."""
    root = repo_root()
    if root not in sys.path:
        sys.path.insert(0, root)

    path = write_module(root)
    add_shelf_button(root)

    # Save the shelf now, or the button is lost if Maya exits uncleanly.
    mel.eval('saveAllShelves $gShelfTopLevel;')

    import qc_bake_maya
    qc_bake_maya.show()

    print("QC Bake %s installed.\n  module: %s\n  shelf:  %s"
          % (qc_bake_maya.VERSION_STRING, path, SHELF_NAME))
    return path


def uninstall():
    """Remove the module file and the shelf button. The repository is left."""
    removed = []

    path = module_file()
    if os.path.isfile(path):
        os.remove(path)
        removed.append(path)

    if cmds.shelfLayout(SHELF_NAME, exists=True):
        for child in cmds.shelfLayout(SHELF_NAME, query=True, childArray=True) or []:
            if cmds.control(child, query=True, exists=True) \
                    and cmds.shelfButton(child, query=True,
                                         label=True) == BUTTON_LABEL:
                cmds.deleteUI(child)
                removed.append("shelf button")
        mel.eval('saveAllShelves $gShelfTopLevel;')

    control = "QCBakeMayaPanelWorkspaceControl"
    if cmds.workspaceControl(control, exists=True):
        cmds.deleteUI(control, control=True)
        removed.append(control)

    print("QC Bake uninstalled: %s" % (", ".join(removed) or "nothing to remove"))
    return removed


def onMayaDroppedPythonFile(*args):
    """Maya calls this when the file is dragged into a viewport."""
    install()
