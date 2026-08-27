# QC Bake for Maya - scene adapter
# --------------------------------
# The only module that talks to maya.cmds for data operations. Commands go
# through here rather than calling cmds directly, so that the Maya-specific
# hazards are dealt with once, in one place:
#
#   * every node travels as a full DAG path, because short names stop being
#     unique the moment objects are grouped;
#   * every rename is checked against what Maya actually did, because Maya
#     silently returns "name1" instead of refusing a clash;
#   * every rename carries the original namespace back with it.

import contextlib

import maya.cmds as cmds

from . import core, naming


# -----------------------------------------------------------------------------
# Undo
# -----------------------------------------------------------------------------
@contextlib.contextmanager
def undo_chunk(label):
    """Collapse everything done inside the block into one undo step.

    Blender got this free from an operator's UNDO flag. In Maya each cmds call
    is its own undo entry unless they are chunked, which would leave the user
    pressing Ctrl+Z once per renamed object.
    """
    cmds.undoInfo(openChunk=True, chunkName=label)
    try:
        yield
    finally:
        cmds.undoInfo(closeChunk=True)


# -----------------------------------------------------------------------------
# Queries
# -----------------------------------------------------------------------------
def mesh_shapes(path):
    """Return the non-intermediate mesh shapes under a transform.

    Intermediate shapes are the orig objects deformers leave behind; counting
    or renaming those would be meaningless.
    """
    return cmds.listRelatives(path, shapes=True, type="mesh",
                              fullPath=True, noIntermediate=True) or []


# Internal alias kept short because this module reaches for it constantly.
_mesh_shapes = mesh_shapes


def is_mesh_transform(path):
    """True when `path` is a transform carrying a polygon mesh."""
    return bool(_mesh_shapes(path))


def all_mesh_transforms():
    """Return the full DAG path of every polygon mesh transform in the scene."""
    result = []
    for shape in cmds.ls(type="mesh", long=True, noIntermediate=True) or []:
        parents = cmds.listRelatives(shape, parent=True, fullPath=True) or []
        if parents and parents[0] not in result:
            result.append(parents[0])
    return result


def selected_meshes():
    """Return the selected polygon mesh transforms, as full DAG paths.

    Selecting a shape node (or a component) still counts as selecting its
    transform, which is what an artist means by it.
    """
    selection = cmds.ls(selection=True, long=True, objectsOnly=True) or []
    result = []
    for node in selection:
        path = node
        if cmds.objectType(node, isAType="shape"):
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            if not parents:
                continue
            path = parents[0]
        if path not in result and is_mesh_transform(path):
            result.append(path)
    return result


def selection_order_tracked():
    """True when Maya is recording the order objects were selected in."""
    return bool(cmds.selectPref(query=True, trackSelectionOrder=True))


def set_selection_order_tracked(enabled):
    """Turn Maya's selection-order tracking on or off."""
    cmds.selectPref(trackSelectionOrder=bool(enabled))


def active_mesh():
    """Return the last-selected mesh transform, or None if unknowable.

    Blender always knows which object is active. Maya only records selection
    order when trackSelectionOrder is switched on - off by default, verified
    in Maya 2025 - and without it ls() returns DAG order, which has nothing to
    do with what the artist clicked last. Returning None in that case lets the
    caller fall back to a geometric choice instead of acting on a wrong guess.
    """
    if not selection_order_tracked():
        return None
    ordered = cmds.ls(orderedSelection=True, long=True, objectsOnly=True) or []
    for node in reversed(ordered):
        path = node
        if cmds.objectType(node, isAType="shape"):
            parents = cmds.listRelatives(node, parent=True, fullPath=True) or []
            if not parents:
                continue
            path = parents[0]
        if is_mesh_transform(path):
            return path
    return None


def mesh_metrics(path, count_smooth_preview=False):
    """Return (verts, faces, tris) for a mesh transform.

    polyEvaluate reads the end of the construction history, so modelling
    operations and deformers are already accounted for - the equivalent of
    Blender's evaluated depsgraph.

    Smooth mesh preview is the one thing it does not see: a cube pressed to
    "3" still evaluates as 12 triangles (verified in Maya 2025), whereas the
    same shape under a Blender subdivision modifier counted as its subdivided
    self. When `count_smooth_preview` is on, the preview level is folded in so
    a hi-poly the artist is viewing smoothed is still recognised as the hi.
    The estimate is exact for quad meshes (Catmull-Clark quadruples the face
    count per level) and close enough on mixed topology, which is all a
    bigger-than comparison needs.
    """
    try:
        counts = cmds.polyEvaluate(path, vertex=True, face=True, triangle=True)
    except RuntimeError:
        return (0, 0, 0)
    # polyEvaluate answers with a string complaint rather than raising when
    # handed something that is not a polygon.
    if not isinstance(counts, dict):
        return (0, 0, 0)

    verts = counts.get("vertex", 0)
    faces = counts.get("face", 0)
    tris = counts.get("triangle", 0)

    if count_smooth_preview:
        level = smooth_preview_level(path)
        if level > 0:
            factor = 4 ** level
            verts *= factor
            faces *= factor
            tris *= factor

    return (verts, faces, tris)


def smooth_preview_level(path):
    """Return the active smooth-mesh-preview level, or 0 when it is off."""
    for shape in _mesh_shapes(path):
        try:
            if cmds.getAttr(shape + ".displaySmoothMesh") == 0:
                continue
            return max(0, int(cmds.getAttr(shape + ".smoothLevel")))
        except (RuntimeError, ValueError):
            continue
    return 0


def world_bounds(paths):
    """Return the combined world bounding box of several nodes, or None.

    Shaped as (minx, miny, minz, maxx, maxy, maxz), matching core.bounds_gap.
    """
    existing = [p for p in paths if cmds.objExists(p)]
    if not existing:
        return None
    try:
        return tuple(cmds.exactWorldBoundingBox(existing))
    except RuntimeError:
        return None


# -----------------------------------------------------------------------------
# Renaming
# -----------------------------------------------------------------------------
def name_conflicts(leaf, allowed_paths):
    """Return the paths of nodes already holding `leaf` that we may not rename.

    Maya only requires names to be unique within a parent, so this deliberately
    checks the whole scene: a bake pipeline hands names to exporters and to
    Substance, where two "asset_low" nodes in different groups are a genuine
    collision even though Maya tolerates them.
    """
    allowed = set(allowed_paths)
    hits = []
    for node in cmds.ls(leaf, long=True, recursive=True) or []:
        if node in allowed:
            continue
        if cmds.objectType(node, isAType="shape"):
            continue
        hits.append(node)
    return hits


def rename_node(path, new_leaf, rename_shape=True, strict=True):
    """Rename a transform (and optionally its shape), returning the new path.

    Two things Maya does quietly are handled here. The namespace of the
    original node is re-applied, so renaming a referenced ``REF:asset_low``
    cannot fling it into the root namespace. And the name Maya actually
    assigned is compared with the one that was asked for: on a clash Maya
    appends a digit and reports success, so reading back what came out is the
    only way to know it happened.

    `strict` decides what to do about that mismatch. On (the default) it is an
    error, because a namepair whose halves ended up as "asset_low" and
    "asset_low1" is not a namepair. Off - which is what the "Allow Name
    Collisions" setting means - Maya's numbered name is accepted and the shape
    is named after what the node actually became, not after what was asked
    for, so the two can never disagree.
    """
    result = cmds.rename(path, naming.with_namespace(path, new_leaf))
    new_path = cmds.ls(result, long=True)[0]

    assigned = naming.leaf_name(new_path)
    if strict and assigned != new_leaf:
        raise RuntimeError(
            "Maya named the node '%s' instead of '%s' - that name was either "
            "already taken or contains characters Maya rewrites."
            % (assigned, new_leaf))

    if rename_shape:
        rename_shape_node(new_path, assigned + "Shape")

    return cmds.ls(result, long=True)[0]


def rename_shape_node(path, shape_leaf):
    """Rename a transform's mesh shapes, keeping their namespace.

    Several shapes under one transform is rare but legal; the extras are
    numbered so the rename cannot fail on its own siblings.
    """
    shapes = mesh_shapes(path)
    for index, shape in enumerate(shapes):
        leaf = shape_leaf if index == 0 else "%s%d" % (shape_leaf, index)
        cmds.rename(shape, naming.with_namespace(shape, leaf))


def rename_batch(plan, rename_shape=True, strict=True):
    """Apply a [(path, new_leaf), ...] plan, returning the new paths in order.

    Every node is parked on a unique temporary name first. Without that pass,
    a namepair that merely swaps two names would collide with itself halfway
    through - and Maya would not complain, it would just number its way out
    and leave a broken pair behind.
    """
    staged = []
    for path, new_leaf in plan:
        temp = "qcbakeTmp_" + core.id_generator()
        renamed = cmds.rename(path, naming.with_namespace(path, temp))
        staged.append((cmds.ls(renamed, long=True)[0], new_leaf))

    return [rename_node(path, new_leaf, rename_shape, strict)
            for path, new_leaf in staged]


# -----------------------------------------------------------------------------
# Dynamic attributes - the reversible-rename backup
# -----------------------------------------------------------------------------
def set_string_attr(path, attr, value):
    """Store a string on a node, adding the attribute if it is not there yet."""
    if not cmds.attributeQuery(attr, node=path, exists=True):
        cmds.addAttr(path, longName=attr, dataType="string")
    cmds.setAttr("%s.%s" % (path, attr), value, type="string")


def get_string_attr(path, attr):
    """Read a string attribute, or None when the node does not carry it."""
    if not cmds.attributeQuery(attr, node=path, exists=True):
        return None
    return cmds.getAttr("%s.%s" % (path, attr))


def remove_attr(path, attr):
    """Delete a dynamic attribute if present, ignoring locks."""
    if cmds.attributeQuery(attr, node=path, exists=True):
        full = "%s.%s" % (path, attr)
        if cmds.getAttr(full, lock=True):
            cmds.setAttr(full, lock=False)
        cmds.deleteAttr(path, attribute=attr)


def nodes_with_attr(attr):
    """Return every transform carrying a given dynamic attribute."""
    return [path for path in cmds.ls(type="transform", long=True) or []
            if cmds.attributeQuery(attr, node=path, exists=True)]


# -----------------------------------------------------------------------------
# Outliner organisation - groups
# -----------------------------------------------------------------------------
def ensure_group(name, parent=None):
    """Return the DAG path of a group, creating or re-parenting as needed.

    Grouping never moves geometry: Maya compensates a child's local transform
    when the DAG changes, so world positions survive (verified against a group
    offset ten units off the origin). The group itself is created at the
    origin with an identity transform so nothing is polluted either way.

    Two things have to be got right when looking for an existing group. A
    short name can match several nodes, so one already sitting under the
    wanted parent is preferred over an unrelated namesake elsewhere. And a
    transform carrying geometry is never treated as a group: an asset called
    "Low" or "Bake_Group" would otherwise be adopted as the container and have
    the rest of the scene parented inside it.
    """
    matches = [p for p in cmds.ls(name, long=True, type="transform") or []
               if naming.leaf_name(p) == name]

    groups = [p for p in matches if not mesh_shapes(p)]
    if not groups and matches:
        raise RuntimeError(
            "'%s' is already the name of an object with geometry (%s). QC Bake "
            "needs that name for a group - rename the object, or pick a "
            "different naming convention." % (name, matches[0]))

    if groups:
        # A namesake already under the right parent is the one we mean.
        path = next((p for p in groups if naming.parent_path(p) == (parent or "")),
                    groups[0])
    else:
        path = cmds.ls(cmds.group(empty=True, name=name), long=True)[0]

    if parent is None:
        if naming.parent_path(path):
            path = cmds.ls(cmds.parent(path, world=True), long=True)[0]
    elif naming.parent_path(path) != parent:
        path = cmds.ls(cmds.parent(path, parent), long=True)[0]

    return path


def parent_to(paths, group):
    """Re-parent nodes under a group, returning their new paths.

    Nodes already sitting directly under the group are left alone: re-parenting
    a node to where it already is makes Maya raise rather than shrug.
    """
    result = []
    for path in paths:
        if not cmds.objExists(path):
            continue
        if naming.parent_path(path) == group:
            result.append(path)
            continue
        moved = cmds.parent(path, group)
        result.append(cmds.ls(moved, long=True)[0])
    return result


def mesh_children(group):
    """Return the mesh transforms parented directly under a group."""
    children = cmds.listRelatives(group, children=True, type="transform",
                                  fullPath=True) or []
    return [path for path in children if mesh_shapes(path)]


def delete_if_empty(paths):
    """Delete each group that has no children left. Returns how many went."""
    removed = 0
    for path in paths:
        if not cmds.objExists(path):
            continue
        if cmds.listRelatives(path, children=True, fullPath=True):
            continue
        cmds.delete(path)
        removed += 1
    return removed


def managed_groups():
    """Return every group this add-on is responsible for.

    Identified by name: the head group, the three flat role groups and any
    per-asset "Bake_" group. Nothing else in the scene is ever touched.
    """
    names = {core.HEAD_NAME}
    names.update(core.FLAT_SUBS.values())
    found = []
    for path in cmds.ls(type="transform", long=True) or []:
        if _mesh_shapes(path):
            continue
        leaf = naming.leaf_name(path)
        if leaf in names or leaf.startswith(core.PER_ASSET_PREFIX):
            found.append(path)
    # Deepest first, so emptying a child before testing its parent works in
    # a single pass.
    return sorted(found, key=lambda p: p.count(naming.DAG_SEP), reverse=True)


def set_outliner_color(path, rgb):
    """Tint a node's outliner row, or clear the tint when rgb is None."""
    if rgb is None:
        cmds.setAttr(path + ".useOutlinerColor", 0)
        return
    cmds.setAttr(path + ".useOutlinerColor", 1)
    cmds.setAttr(path + ".outlinerColor", rgb[0], rgb[1], rgb[2], type="double3")


# -----------------------------------------------------------------------------
# Visibility - display layers
# -----------------------------------------------------------------------------
# Show/hide runs through display layers rather than each object's own
# visibility attribute. A layer override is non-destructive: switching a layer
# off leaves every member's .visibility untouched (verified), so the add-on can
# never trample a visibility state the artist set by hand, and turning the
# layer back on restores exactly what was there.
LAYER_PREFIX = "QCBake_"
ROLE_LAYERS = {'HIGH': LAYER_PREFIX + "High",
               'LOW': LAYER_PREFIX + "Low",
               'CAGE': LAYER_PREFIX + "Cage"}


def ensure_layer(name):
    """Return a display layer by name, creating it if it does not exist."""
    if cmds.objExists(name) and cmds.objectType(name) == "displayLayer":
        return name
    return cmds.createDisplayLayer(name=name, empty=True, noRecurse=True)


def set_layer_members(name, paths):
    """Make a display layer hold exactly `paths` and nothing else."""
    layer = ensure_layer(name)
    current = cmds.editDisplayLayerMembers(layer, query=True, fullNames=True) or []
    wanted = set(paths)
    stale = [p for p in current
             if p not in wanted and not cmds.objectType(p, isAType="shape")]
    if stale:
        # The default layer is Maya's "no layer" bucket.
        cmds.editDisplayLayerMembers("defaultLayer", stale, noRecurse=True)
    if paths:
        cmds.editDisplayLayerMembers(layer, list(paths), noRecurse=True)
    return layer


def layer_visible(name):
    """Return a layer's visibility, or None when the layer does not exist."""
    if not (cmds.objExists(name) and cmds.objectType(name) == "displayLayer"):
        return None
    return bool(cmds.getAttr(name + ".visibility"))


def set_layer_visible(name, visible):
    """Switch a display layer on or off."""
    layer = ensure_layer(name)
    cmds.setAttr(layer + ".visibility", bool(visible))
    return layer


def delete_layer(name):
    """Remove a display layer if it exists, returning its members to no layer."""
    if cmds.objExists(name) and cmds.objectType(name) == "displayLayer":
        cmds.delete(name)


def object_visible(path):
    """True when a node is visible in its own right, ignoring layer overrides."""
    try:
        return bool(cmds.getAttr(path + ".visibility"))
    except (RuntimeError, ValueError):
        return True


# Parking a single object - "Hide After Renaming" - is a different job from
# role-wide show/hide, and uses a different switch. lodVisibility hides a node
# in the viewport only, leaving .visibility (the flag that decides whether it
# renders, and the one an artist may have set deliberately) alone. It is the
# closest match to Blender's hide_set, which was likewise viewport-only.
def set_object_parked(path, parked):
    """Hide or reveal one node in the viewport without touching .visibility."""
    try:
        cmds.setAttr(path + ".lodVisibility", not bool(parked))
    except (RuntimeError, ValueError):
        pass


def object_parked(path):
    """True when a node is viewport-hidden by the parking switch."""
    try:
        return not bool(cmds.getAttr(path + ".lodVisibility"))
    except (RuntimeError, ValueError):
        return False
