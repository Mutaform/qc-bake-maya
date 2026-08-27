# QC Bake for Maya - organize
# ---------------------------
# Rearrange an already-named scene into one of two outliner layouts, both
# under a single "Bake_Group" head:
#
#   FLAT       Bake_Group -> High / Low / Cage      (grouped by role)
#   PER_ASSET  Bake_Group -> Bake_<base> / ...      (grouped by namepair)
#
# Participation is decided purely by name suffix, so props and helper meshes
# are never touched. Either layout can be rebuilt from any prior state,
# including the other one.
#
# Grouping is safe for geometry: Maya rewrites a child's local transform when
# the DAG changes so its world position is preserved, which was verified
# against a head group deliberately parked ten units off the origin. The head
# group is created at the origin regardless, so nothing has to rely on that.

from .. import core, naming, prefs, scene
from . import fail, ok, warn
from ._common import assets_by_base, collect_participants, resolve_suffixes
from .visibility import sync_layers


def organize(layout_mode='FLAT'):
    """Reorganise named bake objects into a collection layout."""
    if layout_mode not in ('FLAT', 'PER_ASSET'):
        return fail("Unknown layout '%s'." % layout_mode)

    settings = prefs.load()
    suffixes, error = resolve_suffixes(settings)
    if error:
        return error
    low_suf, high_suf, cage_suf = suffixes

    buckets = collect_participants(low_suf, high_suf, cage_suf)
    total = sum(len(v) for v in buckets.values())
    if total == 0:
        # Not an error - the scene is simply not ready yet. These layouts pick
        # their members purely by name suffix, so nothing at all happens until
        # something has been through Create Namepair. Saying so beats a red
        # strip that leaves the artist wondering what broke.
        meshes = len(scene.all_mesh_transforms())
        return warn(
            "Nothing to organize: no object ends in %s or %s. "
            "Select an asset's meshes and press Create Namepair first - "
            "these buttons only group objects that are already named. "
            "(%d mesh%s in the scene, none named.)"
            % (low_suf, high_suf, meshes, "" if meshes == 1 else "es"))

    with scene.undo_chunk("QC Bake: Organize"):
        try:
            head = scene.ensure_group(core.HEAD_NAME)
            if layout_mode == 'FLAT':
                groups = _build_flat(head, buckets)
            else:
                groups = _build_per_asset(head, buckets,
                                          low_suf, high_suf, cage_suf)
        except RuntimeError as exc:
            return fail(str(exc))

        # Groups left empty by this rebuild - the role groups of the layout we
        # just replaced, or per-asset groups whose members were renamed away.
        keep = set(groups) | {head}
        scene.delete_if_empty([g for g in scene.managed_groups()
                               if g not in keep])

        # Re-parenting invalidates the paths the display layers were holding,
        # so membership is rebuilt against the new hierarchy.
        sync_layers()

        strays = _all_strays(low_suf, high_suf, cage_suf)

    message = ("Organized %d objects into '%s' (%s)."
               % (total, core.HEAD_NAME,
                  "Flat" if layout_mode == 'FLAT' else "Per Asset"))

    if strays:
        names = ", ".join(sorted(naming.leaf_name(p) for p in strays)[:4])
        if len(strays) > 4:
            names += ", ..."
        return warn(
            "%s %d object%s inside a bake group carr%s no %s or %s suffix, so "
            "%s left where %s and the group is tagged red: %s"
            % (message, len(strays), "" if len(strays) == 1 else "s",
               "ies" if len(strays) == 1 else "y", low_suf, high_suf,
               "it was" if len(strays) == 1 else "they were",
               "it is" if len(strays) == 1 else "they are", names))

    return ok(message)


def _build_flat(head, buckets):
    """Bake_Group -> High / Low / Cage."""
    made = []
    for role in ('HIGH', 'LOW', 'CAGE'):
        paths = buckets.get(role)
        if not paths:
            continue
        group = scene.ensure_group(core.FLAT_SUBS[role], parent=head)
        scene.parent_to(paths, group)
        # A role group carries no per-asset health meaning, so make sure a
        # green or red tag left by a previous Per Asset run does not linger
        # and imply something it no longer means.
        scene.set_outliner_color(group, None)
        made.append(group)
    return made


def _build_per_asset(head, buckets, low_suf, high_suf, cage_suf):
    """Bake_Group -> Bake_<base>, one per namepair, colour-tagged by health."""
    made = []
    assets = assets_by_base(buckets, low_suf, high_suf, cage_suf)

    for base, asset in assets.items():
        group = scene.ensure_group(
            core.PER_ASSET_PREFIX + naming.sanitize(base), parent=head)
        moved = scene.parent_to(asset["objects"], group)
        scene.set_outliner_color(
            group,
            core.bakegroup_color([naming.leaf_name(p) for p in moved],
                                 low_suf, high_suf, cage_suf,
                                 has_stray=bool(_strays_in(group, low_suf,
                                                           high_suf, cage_suf))))
        made.append(group)
    return made


def _strays_in(group, low_suf, high_suf, cage_suf):
    """Return meshes parented under `group` that carry no bake naming.

    These are never moved. An object with no bake suffix is by definition not
    ours - a prop, a helper, a piece of the environment - and hauling someone's
    geometry out of where they put it is not a rename tool's business. But
    leaving it silently inside a group tagged green is worse: it will be in the
    bake. So it is counted, the group goes red, and the run says so.
    """
    strays = []
    for path in scene.mesh_children(group):
        if core.classify_role(naming.leaf_name(path),
                              low_suf, high_suf, cage_suf) is None:
            strays.append(path)
    return strays


def _all_strays(low_suf, high_suf, cage_suf):
    """Every stray inside any group this add-on manages."""
    found = []
    for group in scene.managed_groups():
        found.extend(_strays_in(group, low_suf, high_suf, cage_suf))
    return found
