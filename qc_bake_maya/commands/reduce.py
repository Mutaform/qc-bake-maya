# QC Bake for Maya - reduce / restore bake groups
# -----------------------------------------------
# Baking every asset into its own texture set is wasteful when the assets are
# small and far apart. Reduce merges namepairs into as few bake groups as the
# geometry allows: two assets may share a group only when their world bounding
# boxes stay at least "Minimum Gap" apart, so a ray cast from one asset can
# never strike another one's high poly.
#
# The merge is a rename, which is destructive - so every participant carries
# its previous name in a dynamic attribute, and Restore puts them all back.
# Those attributes are saved into the scene file, which means Restore still
# works tomorrow, after a save and reload, long past the end of Maya's undo
# queue.

from .. import core, naming, prefs, scene
from . import fail, ok, warn
from ._common import (
    assets_by_base, check_collisions, collect_participants, resolve_suffixes,
)


def reduce_groups():
    """Merge distant bake namepairs into fewer baking groups."""
    settings = prefs.load()
    suffixes, error = resolve_suffixes(settings)
    if error:
        return error
    low_suf, high_suf, cage_suf = suffixes

    buckets = collect_participants(low_suf, high_suf, cage_suf)
    assets, skipped = _complete_assets(
        assets_by_base(buckets, low_suf, high_suf, cage_suf))

    if len(assets) < 2:
        return fail("Need at least two complete namepairs to reduce "
                    "(found %d complete, %d incomplete)."
                    % (len(assets), skipped))

    groups = core.pack_groups(assets, settings.reduce_min_gap)
    if len(groups) >= len(assets):
        # Nothing was changed, so this is not a success even though nothing
        # went wrong - reporting it green would tell the artist the scene had
        # been reorganised when it had not.
        return warn("No safe reduction found: every pair of assets sits closer "
                    "than the %g minimum gap, so none of them can share a "
                    "bake group." % settings.reduce_min_gap)

    prefix = core.clean_prefix(settings.reduce_group_prefix)
    plan = _rename_plan(groups, prefix, low_suf, high_suf, cage_suf)

    participants = [path for path, _ in plan]
    if not settings.allow_name_collisions:
        collision = check_collisions([leaf for _, leaf in plan], participants)
        if collision:
            return collision

    with scene.undo_chunk("QC Bake: Reduce Bake Groups"):
        # The backup is written before anything is renamed, so it records the
        # names as the artist knows them.
        for path, _ in plan:
            scene.set_string_attr(path, core.REDUCE_PREV_NAME_ATTR,
                                  naming.leaf_name(path))
            shape_leaf = _shape_leaf(path) if settings.also_rename_shape else None
            if shape_leaf:
                scene.set_string_attr(path, core.REDUCE_PREV_SHAPE_ATTR,
                                      shape_leaf)
            else:
                # Clear any shape backup left by an earlier pass, so Restore
                # cannot resurrect a name from two reductions ago.
                scene.remove_attr(path, core.REDUCE_PREV_SHAPE_ATTR)

        try:
            scene.rename_batch(plan, settings.also_rename_shape,
                               strict=not settings.allow_name_collisions)
        except RuntimeError as exc:
            return fail(str(exc))

    merged = sum(len(g) for g in groups if len(g) > 1)
    return ok("Reduced %d assets into %d bake group%s%s."
              % (merged, len(groups), "" if len(groups) == 1 else "s",
                 " (%d incomplete skipped)" % skipped if skipped else ""))


def restore_groups():
    """Undo the most recent Reduce pass, restoring the previous names."""
    settings = prefs.load()

    candidates = scene.nodes_with_attr(core.REDUCE_PREV_NAME_ATTR)
    if not candidates:
        return fail("No reduce backup found in this scene.")

    plan = []
    for path in candidates:
        previous = scene.get_string_attr(path, core.REDUCE_PREV_NAME_ATTR)
        if previous:
            plan.append((path, previous))

    if not plan:
        return fail("The reduce backup in this scene is empty.")

    if not settings.allow_name_collisions:
        collision = check_collisions([leaf for _, leaf in plan],
                                     [path for path, _ in plan])
        if collision:
            return collision

    with scene.undo_chunk("QC Bake: Restore Bake Groups"):
        # Shape names are restored from the backup rather than being derived
        # from the transform, because the pre-reduce scene may well not have
        # followed the "<name>Shape" convention at all.
        shape_names = {path: scene.get_string_attr(path,
                                                   core.REDUCE_PREV_SHAPE_ATTR)
                       for path, _ in plan}

        try:
            restored = scene.rename_batch(
                plan, rename_shape=False,
                strict=not settings.allow_name_collisions)
        except RuntimeError as exc:
            return fail(str(exc))

        for old_path, new_path in zip([p for p, _ in plan], restored):
            wanted_shape = shape_names.get(old_path)
            if wanted_shape:
                scene.rename_shape_node(new_path, wanted_shape)
            scene.remove_attr(new_path, core.REDUCE_PREV_NAME_ATTR)
            scene.remove_attr(new_path, core.REDUCE_PREV_SHAPE_ATTR)

    return ok("Restored %d objects to their pre-reduce names. Re-run a "
              "Collection Layout if you rely on the Bake_<name> groups."
              % len(restored))


def has_backup():
    """True when this scene holds a reduce backup that Restore could use."""
    return bool(scene.nodes_with_attr(core.REDUCE_PREV_NAME_ATTR))


# -----------------------------------------------------------------------------
# Internals
# -----------------------------------------------------------------------------
def _shape_leaf(path):
    """Return the leaf name of a transform's first mesh shape, or None."""
    shapes = scene.mesh_shapes(path)
    return naming.leaf_name(shapes[0]) if shapes else None


def _complete_assets(assets):
    """Keep only assets with a low, a high and a measurable bounding box."""
    complete = []
    skipped = 0
    for asset in assets.values():
        if not asset["LOW"] or not asset["HIGH"]:
            skipped += 1
            continue
        bounds = scene.world_bounds(asset["objects"])
        if bounds is None:
            skipped += 1
            continue
        asset["bounds"] = bounds
        complete.append(asset)
    return complete, skipped


def _rename_plan(groups, prefix, low_suf, high_suf, cage_suf):
    """Turn packed groups into a [(path, new_leaf), ...] rename plan.

    Members are sorted by name within each role so a rerun on an unchanged
    scene produces the same numbering, rather than shuffling indices around
    because the DAG happened to be walked in a different order.
    """
    plan = []
    for index, group in enumerate(groups, start=1):
        base = "%s_%02d" % (prefix, index)
        by_role = {'LOW': [], 'HIGH': [], 'CAGE': []}
        for asset in sorted(group, key=lambda a: a["base"]):
            for role in by_role:
                by_role[role].extend(sorted(asset[role], key=naming.leaf_name))

        for role, suffix in (('LOW', low_suf), ('HIGH', high_suf),
                             ('CAGE', cage_suf)):
            paths = by_role[role]
            if not paths or not suffix:
                continue
            names = core.role_names(base, suffix, len(paths))
            plan.extend(zip(paths, names))

    return plan
