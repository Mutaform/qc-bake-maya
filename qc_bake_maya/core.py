# QC Bake for Maya - core
# -----------------------
# Pure logic with no Maya dependency at all: naming conventions, role
# classification, the hi/lo decision and the bake-group packing maths.
#
# Keeping this import-clean means the whole decision layer can be exercised
# from a plain python interpreter, which is the only practical way to test a
# DCC tool's logic. Everything that touches the scene lives in scene.py.

import math
import random
import re
import string

# -----------------------------------------------------------------------------
# Naming convention presets
# -----------------------------------------------------------------------------
# Each preset maps to (low_suffix, high_suffix, cage_suffix).
NAMING_PRESETS = {
    'SUBSTANCE': ("_low", "_high", "_cage"),
    'MARMOSET': ("_low", "_high", "_cage"),
    'XNORMAL': ("_lo", "_hi", "_cage"),
    'CUSTOM': (None, None, None),  # resolved from user-provided strings
}

PRESET_ITEMS = [
    ('SUBSTANCE', "Substance ( _low / _high )",
     "Suffixes used by Substance Painter / Designer"),
    ('MARMOSET', "Marmoset ( _low / _high )",
     "Suffixes used by Marmoset Toolbag"),
    ('XNORMAL', "xNormal ( _lo / _hi )",
     "Short suffixes used by xNormal"),
    ('CUSTOM', "Custom",
     "Define your own suffixes below"),
]

HILO_CRITERION_ITEMS = [
    ('TRIS', "Triangles", "Compare triangle counts (most reliable)"),
    ('FACES', "Faces", "Compare face (polygon) counts"),
    ('VERTS', "Vertices", "Compare vertex counts"),
]

LAYOUT_ITEMS = [
    ('FLAT', "Flat ( High / Low )",
     "Bake Group with High, Low and Cage sub-groups"),
    ('PER_ASSET', "Per Asset ( Bake_name )",
     "Bake Group with one Bake_<name> group per namepair"),
]

# Outliner hierarchy names.
HEAD_NAME = "Bake_Group"
FLAT_SUBS = {'HIGH': "High", 'LOW': "Low", 'CAGE': "Cage"}
PER_ASSET_PREFIX = "Bake_"

# -----------------------------------------------------------------------------
# Reduce Bake Groups - reversible rename backup
# -----------------------------------------------------------------------------
# "Reduce Bake Groups" merges small namepairs into fewer groups by renaming
# objects (and optionally their shape nodes). That is destructive unless the
# pre-rename names are kept somewhere. We stash them in dynamic attributes on
# the nodes themselves rather than in a side list, because:
#   - they are saved into the .ma/.mb and outlast Maya's undo queue;
#   - they need no name-keyed bookkeeping that renaming would instantly break;
#   - they stay consistent even if objects are later deleted.
# A "Restore Bake Groups" command reads these back and removes them.
#
# Both are valid Maya attribute names (leading letter, no separators), which
# matters: Maya silently mangles anything else.
REDUCE_PREV_NAME_ATTR = "qcbakePrevName"
REDUCE_PREV_SHAPE_ATTR = "qcbakePrevShapeName"

# -----------------------------------------------------------------------------
# Bake-group quality tags (Outliner colours)
# -----------------------------------------------------------------------------
# A per-asset "Bake_<name>" group is only bakeable when it holds both a low and
# a high member. That health check is surfaced as an outliner colour so
# problems are visible at a glance, exactly as the Blender version used
# collection colour tags. Maya takes a real RGB rather than a fixed palette,
# so these are picked to read clearly against the dark outliner background.
BAKEGROUP_COLOR_OK = (0.30, 0.72, 0.35)    # green - complete pair, ready
BAKEGROUP_COLOR_WARN = (0.83, 0.31, 0.31)  # red   - a member is missing


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def id_generator(size=6, chars=string.ascii_uppercase + string.digits):
    """Return a random uppercase/digit identifier of the given length."""
    return ''.join(random.choice(chars) for _ in range(size))


def get_suffixes(settings):
    """Return (low_suffix, high_suffix, cage_suffix) for the given settings."""
    if settings.naming_preset == 'CUSTOM':
        return (
            settings.custom_low_suffix,
            settings.custom_high_suffix,
            settings.custom_cage_suffix,
        )
    return NAMING_PRESETS[settings.naming_preset]


def metric_for(criterion, metrics):
    """Pick the requested metric out of a (verts, faces, tris) tuple."""
    verts, faces, tris = metrics
    if criterion == 'VERTS':
        return verts
    if criterion == 'FACES':
        return faces
    return tris


def strip_known_suffixes(name, suffixes):
    """Remove any one trailing suffix from the list, if present."""
    for suf in suffixes:
        if suf and name.endswith(suf):
            return name[: -len(suf)]
    return name


_TRAILING_DIGITS = re.compile(r"\d+$")


def suffix_index(name, suffix):
    """Return where `suffix` begins in `name`, or None when it is absent.

    Three shapes count as carrying a suffix:

        asset_low       plain
        asset_low_01    an indexed member of a multi-part role
        asset_low2      Maya's own auto-numbering

    That last one is the reason this is a function rather than an endswith.
    Duplicating geometry is how a Maya artist makes a variant, and Maya names
    the copy by appending a digit - so ``asset_low`` becomes ``asset_low2``
    and a plain suffix test goes blind to it. The object then vanishes from
    every list the tool builds: it is not organised, not counted, not shown or
    hidden, and worst of all it keeps sitting wherever it already was, inside
    a bake group that still reports itself as healthy.

    The leading underscore in a suffix is what keeps this safe: "pillow2"
    trims to "pillow", which does not end in "_low".
    """
    if not suffix:
        return None
    marker = suffix + "_"
    if marker in name:
        return name.index(marker)
    if name.endswith(suffix):
        return len(name) - len(suffix)
    trimmed = _TRAILING_DIGITS.sub("", name)
    if trimmed != name and trimmed.endswith(suffix):
        return len(trimmed) - len(suffix)
    return None


def classify_role(name, low_suf, high_suf, cage_suf):
    """Return 'LOW', 'HIGH', 'CAGE' or None for a name, by suffix.

    Cage is tested first so it still wins when a user picks overlapping
    suffixes.
    """
    if suffix_index(name, cage_suf) is not None:
        return 'CAGE'
    if suffix_index(name, high_suf) is not None:
        return 'HIGH'
    if suffix_index(name, low_suf) is not None:
        return 'LOW'
    return None


def base_name(name, low_suf, high_suf, cage_suf):
    """Recover the shared base name of a namepair member.

    ``asset_high``, ``asset_high_01`` and ``asset_high2`` all return ``asset``.
    A name that is nothing but a suffix keeps itself, since an empty base
    would produce a group called "Bake_".
    """
    for suf in (high_suf, low_suf, cage_suf):
        index = suffix_index(name, suf)
        if index is not None:
            return name[:index] or name
    return name


def bakegroup_color(object_names, low_suf, high_suf, cage_suf, has_stray=False):
    """Return the outliner colour a per-asset bake group should carry.

    Green when both a low and a high member are present (a complete namepair,
    ready to bake); red otherwise. Cage-only members do not by themselves make
    a group complete.

    `has_stray` covers the other way a group can be unfit to bake: something
    is parented inside it that carries no bake naming at all. Such an object
    is invisible to every list this tool builds, so without this the group
    would report itself green while holding geometry that will end up in the
    bake.
    """
    if has_stray:
        return BAKEGROUP_COLOR_WARN

    has_low = has_high = False
    for name in object_names:
        role = classify_role(name, low_suf, high_suf, cage_suf)
        if role == 'LOW':
            has_low = True
        elif role == 'HIGH':
            has_high = True
    return BAKEGROUP_COLOR_OK if (has_low and has_high) else BAKEGROUP_COLOR_WARN


# -----------------------------------------------------------------------------
# Namepair planning
# -----------------------------------------------------------------------------
def role_names(base, suffix, count):
    """Return `count` names for one role, indexed only when there are several.

    A lone high poly keeps the plain suffix (``asset_high``); two or more get
    a "_NN" index (``asset_high_01``) so they stay grouped and sort in a
    predictable order.
    """
    if count == 1:
        return [base + suffix]
    return ["%s%s_%02d" % (base, suffix, i + 1) for i in range(count)]


def member_names(base, low_suf, high_suf, cage_suf, high_count, has_cage):
    """Return every name a namepair of this shape should end up with."""
    names = role_names(base, low_suf, 1)
    names.extend(role_names(base, high_suf, high_count))
    if has_cage and cage_suf:
        names.extend(role_names(base, cage_suf, 1))
    return names


def choose_low(entries, criterion):
    """Pick the low poly out of `entries`, a list of (key, metrics) pairs.

    Returns the key with the smallest metric, or None when every candidate
    ties - a tie means we genuinely cannot tell them apart, and the caller
    should say so rather than guess.
    """
    if not entries:
        return None
    scored = [(metric_for(criterion, m), k) for k, m in entries]
    if len(set(value for value, _ in scored)) == 1:
        return None
    return min(scored, key=lambda item: item[0])[1]


# -----------------------------------------------------------------------------
# Reduce Bake Groups - spatial packing
# -----------------------------------------------------------------------------
# Baking several assets into one texture set is only safe when their cages do
# not overlap, or rays cast from one asset strike another one's high poly.
# Assets are therefore packed into as few groups as possible, subject to a
# minimum world-space gap between every pair of bounding boxes in a group.
def bounds_gap(bounds_a, bounds_b):
    """Return the world-space distance between two axis-aligned boxes.

    Zero when they touch or overlap. Each box is
    (min_x, min_y, min_z, max_x, max_y, max_z) - the shape Maya's
    exactWorldBoundingBox hands back.
    """
    sq_dist = 0.0
    for axis in range(3):
        min_a, max_a = bounds_a[axis], bounds_a[axis + 3]
        min_b, max_b = bounds_b[axis], bounds_b[axis + 3]
        if max_a < min_b:
            gap = min_b - max_a
        elif max_b < min_a:
            gap = min_a - max_b
        else:
            gap = 0.0
        sq_dist += gap * gap
    return math.sqrt(sq_dist)


def bounds_volume(bounds):
    """Return the volume of a (minx, miny, minz, maxx, maxy, maxz) box."""
    return ((bounds[3] - bounds[0])
            * (bounds[4] - bounds[1])
            * (bounds[5] - bounds[2]))


def pack_groups(assets, min_gap):
    """Greedily pack assets into the fewest groups that respect `min_gap`.

    `assets` is a list of dicts carrying at least "base" and "bounds". The
    largest assets are placed first (first-fit-decreasing): they are the
    hardest to seat, so placing them early yields fewer groups than the
    reverse order. Sorting by base name breaks ties, so re-running on an
    unchanged scene always reproduces the same grouping.
    """
    groups = []
    ordered = sorted(assets,
                     key=lambda a: (-bounds_volume(a["bounds"]), a["base"]))

    for asset in ordered:
        for group in groups:
            if all(bounds_gap(asset["bounds"], other["bounds"]) >= min_gap
                   for other in group):
                group.append(asset)
                break
        else:
            groups.append([asset])

    return groups


def clean_prefix(prefix, fallback="BakeGroup"):
    """Normalise a user-typed group prefix into something Maya will accept."""
    prefix = (prefix or "").strip().replace(" ", "_")
    return prefix or fallback
