# QC Bake for Maya - shared command helpers
# -----------------------------------------
# Pieces every command needs: turning settings into validated suffixes, and
# finding the objects in the scene that those suffixes claim.

from .. import core, naming, scene
from . import fail


def resolve_suffixes(settings):
    """Return ((low, high, cage), None) or (None, Result) if unusable.

    Validation happens here rather than at the point of rename because Maya
    does not refuse a bad name - it rewrites it and reports success. By the
    time a rename has "worked", the damage is already in the scene.
    """
    low_suf, high_suf, cage_suf = core.get_suffixes(settings)

    for suffix, label in ((low_suf, "Low"), (high_suf, "High")):
        error = naming.validate_suffix(suffix, label)
        if error:
            return None, fail(error)

    if cage_suf:
        error = naming.validate_suffix(cage_suf, "Cage")
        if error:
            return None, fail(error)

    if low_suf == high_suf:
        return None, fail("Low and high suffixes must differ.")

    return (low_suf, high_suf, cage_suf), None


def collect_participants(low_suf, high_suf, cage_suf):
    """Return {role: [dag paths]} for every mesh the suffixes claim.

    Matching runs against the leaf name only. A full DAG path would also carry
    the names of parent groups, so a namepair sitting inside "Bake_asset_low"
    would have every member classified as a low.
    """
    buckets = {'LOW': [], 'HIGH': [], 'CAGE': []}
    for path in scene.all_mesh_transforms():
        role = core.classify_role(naming.leaf_name(path),
                                  low_suf, high_suf, cage_suf)
        if role:
            buckets[role].append(path)
    return buckets


def assets_by_base(buckets, low_suf, high_suf, cage_suf):
    """Regroup role buckets into one entry per namepair, keyed by base name.

    Each asset is {"base", "LOW", "HIGH", "CAGE", "objects"} with paths in
    every list. Insertion order is preserved so results read predictably.
    """
    assets = {}
    for role in ('LOW', 'HIGH', 'CAGE'):
        for path in buckets[role]:
            base = core.base_name(naming.leaf_name(path),
                                  low_suf, high_suf, cage_suf)
            asset = assets.setdefault(
                base,
                {"base": base, "LOW": [], "HIGH": [], "CAGE": [], "objects": []},
            )
            asset[role].append(path)
            asset["objects"].append(path)
    return assets


def check_collisions(wanted_leaves, allowed_paths):
    """Return a Result describing the first real name clash, or None.

    Maya tolerates two nodes sharing a short name in different groups, so this
    cannot be left to Maya - and must not be, because the names go on to
    exporters and to Substance, where the clash is real.
    """
    for leaf in wanted_leaves:
        conflicts = scene.name_conflicts(leaf, allowed_paths)
        if conflicts:
            return fail(
                "Name '%s' is already used by %s. Enable 'Allow Name "
                "Collisions' or rename that object first."
                % (leaf, conflicts[0]))
    return None
