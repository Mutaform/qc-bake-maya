# QC Bake for Maya - icons
# ------------------------
# A single source of truth for every icon the UI uses. Panels reference the
# semantic names here (ICON_CREATE and so on) rather than hard-coding resource
# paths inline, so restyling the whole tool is a one-file change - the same
# arrangement the Blender version used.
#
# These are Maya's own built-in resources, reached through the ":/" prefix.
# Every name below was confirmed to load as a non-null pixmap in Maya 2025;
# a missing resource does not raise, it silently draws an empty square, so
# guessing at names is not an option.
#
# Sizes in the resource set run from 11x11 to 32x32, so the UI scales them to
# one size rather than trusting them to arrive consistent.

RESOURCE_PREFIX = ":/"

# Primary actions
ICON_CREATE = "out_mesh.png"           # main "Create Namepair" button
ICON_SWAP = "doubleHorizArrow.png"     # swap high/low roles

# Section headers
ICON_NAMING = "quickRename.png"        # naming convention section
ICON_DETECT = "polyRemesh.png"         # hi/lo detection criterion
ICON_OPTIONS = "advancedSettings.png"  # options section
ICON_VISIBILITY = "eye.png"            # visibility section
ICON_UTILITIES = "outliner.png"        # utilities section

# Poly roles
ICON_HIGH = "polySmooth.png"           # high poly
ICON_LOW = "polyCube.png"              # low poly
ICON_CAGE = "cube.png"                 # cage
ICON_ALL = "group.png"                 # all renamed

# Toggle buttons
ICON_SHOW = "visible.png"
ICON_HIDE = "hidden.png"

# Option rows
ICON_RANDOM = "polyRandomizeShell.png"  # refresh.png reads as blank when dark
ICON_SHAPE = "out_mesh.png"
ICON_DETECT_CAGE = "cube.png"
ICON_GROUP = "group.png"
ICON_HIDE_AFTER = "hidden.png"
ICON_OVERWRITE = "warningIcon.svg"
ICON_SELECT_ORDER = "search.png"        # distinct from the cage cube
ICON_SMOOTH = "polySmooth.png"          # smooth-preview counting

# Utilities
ICON_UTIL_FLAT = "group.png"           # flat High/Low layout
ICON_UTIL_PERASSET = "polyBakeSetEdit.png"  # per-asset Bake_<name> layout
ICON_UTIL_REDUCE = "polyReduce.png"    # reduce bake groups by distance
ICON_UTIL_RESTORE = "undo.png"         # undo the last reduce pass

# Status line
ICON_INFO = "info.png"
ICON_WARNING = "warningIcon.svg"


def path(name):
    """Return the Qt resource path for an icon name."""
    return RESOURCE_PREFIX + name
