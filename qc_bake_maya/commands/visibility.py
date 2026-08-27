# QC Bake for Maya - visibility
# -----------------------------
# Show/hide whole roles at once: all the highs, all the lows, all the cages.
#
# This runs through display layers rather than each object's visibility
# attribute, which is the one place the Maya port is better than the Blender
# original by construction. A layer override is non-destructive - switching
# the layer off leaves every member's own .visibility exactly as the artist
# left it, and switching it back on restores that state rather than a state
# QC Bake guessed at.
#
# Membership is rebuilt from the scene on every call, so objects renamed into
# (or out of) a role since the last run are always picked up.

from .. import core, prefs, scene
from . import fail, ok, warn
from ._common import collect_participants, resolve_suffixes

GROUPS = ('HIGH', 'LOW', 'CAGE', 'ALL')


def _roles_for(group):
    if group == 'ALL':
        return ('HIGH', 'LOW', 'CAGE')
    return (group,)


def sync_layers():
    """Rebuild role layer membership from what is currently in the scene.

    Returns {role: [paths]}. Layers are created only for roles that actually
    have members, so an asset set with no cages never grows an empty Cage
    layer to clutter the layer editor.
    """
    settings = prefs.load()
    suffixes, error = resolve_suffixes(settings)
    if error:
        return {}
    low_suf, high_suf, cage_suf = suffixes

    buckets = collect_participants(low_suf, high_suf, cage_suf)
    for role, layer_name in scene.ROLE_LAYERS.items():
        paths = buckets.get(role) or []
        if paths:
            scene.set_layer_members(layer_name, paths)
        else:
            scene.delete_layer(layer_name)
    return buckets


def group_state(group):
    """Return 'SHOWN', 'HIDDEN', 'MIXED' or None for a role.

    None means the role has no members at all, which the panel shows as a
    disabled row rather than a lie about the state of nothing.
    """
    settings = prefs.load()
    suffixes, error = resolve_suffixes(settings)
    if error:
        return None
    low_suf, high_suf, cage_suf = suffixes

    buckets = collect_participants(low_suf, high_suf, cage_suf)
    roles = [r for r in _roles_for(group) if buckets.get(r)]
    if not roles:
        return None

    states = set()
    for role in roles:
        layer = scene.ROLE_LAYERS[role]
        visible = scene.layer_visible(layer)
        # No layer yet means nothing has hidden this role, so it is shown.
        if visible is None:
            visible = True
        # A member parked individually by "Hide After Renaming" counts as
        # hidden too, or the panel would claim a row is shown while half of
        # it is invisible.
        if visible and any(scene.object_parked(p) for p in buckets[role]):
            states.add('MIXED')
            continue
        states.add('SHOWN' if visible else 'HIDDEN')

    if len(states) == 1:
        return states.pop()
    return 'MIXED'


def set_group_visible(group, visible):
    """Show or hide every object in a role."""
    if group not in GROUPS:
        return fail("Unknown visibility group '%s'." % group)

    settings = prefs.load()
    suffixes, error = resolve_suffixes(settings)
    if error:
        return error
    low_suf, high_suf, cage_suf = suffixes

    buckets = collect_participants(low_suf, high_suf, cage_suf)
    roles = [r for r in _roles_for(group) if buckets.get(r)]
    if not roles:
        # Nothing carries that role yet, which is a state of the scene rather
        # than a failure of the tool.
        return warn("Nothing to show or hide: no object ends in %s or %s yet."
                    % (low_suf, high_suf))

    touched = 0
    with scene.undo_chunk("QC Bake: %s %s" % ("Show" if visible else "Hide", group)):
        for role in roles:
            paths = buckets[role]
            scene.set_layer_members(scene.ROLE_LAYERS[role], paths)
            scene.set_layer_visible(scene.ROLE_LAYERS[role], visible)
            if visible:
                # Showing a role has to clear individual parking as well, or
                # objects hidden by "Hide After Renaming" would stay invisible
                # while the panel insisted the role was shown.
                for path in paths:
                    scene.set_object_parked(path, False)
            touched += len(paths)

    return ok("%s %d object%s." % ("Showed" if visible else "Hid",
                                   touched, "" if touched == 1 else "s"))


def clear_all():
    """Remove every QC Bake display layer and un-park every object.

    The way out of the tool: the scene keeps its names and its groups, but
    nothing QC Bake did to visibility is left behind.
    """
    settings = prefs.load()
    suffixes, error = resolve_suffixes(settings)
    if error:
        return error
    low_suf, high_suf, cage_suf = suffixes

    buckets = collect_participants(low_suf, high_suf, cage_suf)
    with scene.undo_chunk("QC Bake: Clear Visibility"):
        for layer_name in scene.ROLE_LAYERS.values():
            scene.delete_layer(layer_name)
        for paths in buckets.values():
            for path in paths:
                scene.set_object_parked(path, False)

    return ok("Cleared QC Bake visibility layers.")


# Referenced by the panel so it can label rows without duplicating the map.
ROLE_LABELS = {'HIGH': "High", 'LOW': "Low", 'CAGE': "Cage", 'ALL': "All"}
assert set(ROLE_LABELS) == set(GROUPS)
assert set(scene.ROLE_LAYERS) == set(core.FLAT_SUBS)
