# QC Bake for Maya - create namepair
# ----------------------------------
# The main action. Takes the selection, decides which mesh is the low poly and
# which are the highs, and renames the lot into a matching bake namepair.

from .. import core, naming, prefs, scene
from . import fail, ok
from ._common import check_collisions, resolve_suffixes


def create_namepair():
    """Rename the selected meshes into a high/low baking namepair."""
    settings = prefs.load()

    selected = scene.selected_meshes()
    if len(selected) < 2:
        return fail("Select at least two polygon meshes.")

    suffixes, error = resolve_suffixes(settings)
    if error:
        return error
    low_suf, high_suf, cage_suf = suffixes

    all_suffixes = [s for s in (low_suf, high_suf, cage_suf) if s]
    criterion = settings.hilo_criterion
    smooth = settings.count_smooth_preview

    # Pull the cage out before sorting hi from lo, so its poly count never
    # takes part in the comparison.
    cage_path = None
    candidates = list(selected)
    if settings.detect_cage and cage_suf:
        for path in candidates:
            if naming.leaf_name(path).endswith(cage_suf):
                cage_path = path
                candidates.remove(path)
                break

    if len(candidates) < 2:
        return fail("Need at least two non-cage meshes.")

    metrics = {p: scene.mesh_metrics(p, smooth) for p in candidates}
    entries = [(p, metrics[p]) for p in candidates]

    if len(candidates) == 2:
        low_path = core.choose_low(entries, criterion)
        if low_path is None:
            hint = ("" if smooth else
                    " If the high poly is being viewed smoothed, turn on "
                    "'Count Smooth Preview'.")
            return fail("Both meshes have the same %s count, so there is no "
                        "way to tell which is the high poly.%s"
                        % (criterion.lower(), hint))
        high_paths = [p for p in candidates if p != low_path]
    else:
        # Group mode: one low, everything else is a high. The artist's last
        # selection wins when Maya is recording selection order; otherwise the
        # smallest mesh is the only defensible choice.
        active = scene.active_mesh()
        if active in candidates:
            low_path = active
        else:
            low_path = core.choose_low(entries, criterion) or candidates[0]
        high_paths = [p for p in candidates if p != low_path]

    # Base name.
    if settings.generate_random_name:
        base = core.id_generator()
    else:
        base = core.strip_known_suffixes(naming.leaf_name(low_path), all_suffixes)
    base = naming.sanitize(base)

    wanted = core.member_names(base, low_suf, high_suf, cage_suf,
                               len(high_paths), cage_path is not None)

    participants = [low_path] + high_paths + ([cage_path] if cage_path else [])
    if not settings.allow_name_collisions:
        collision = check_collisions(wanted, participants)
        if collision:
            return collision

    # participants and wanted are both built low, highs, cage - in that order
    # and from the same counts - so zipping them cannot misalign.
    plan = list(zip(participants, wanted))

    with scene.undo_chunk("QC Bake: Create Namepair"):
        try:
            renamed = scene.rename_batch(plan, settings.also_rename_shape,
                                         strict=not settings.allow_name_collisions)
        except RuntimeError as exc:
            return fail(str(exc))

        if settings.move_to_group:
            try:
                head = scene.ensure_group(core.HEAD_NAME)
                group = scene.ensure_group(core.PER_ASSET_PREFIX + base,
                                           parent=head)
                renamed = scene.parent_to(renamed, group)
                scene.set_outliner_color(
                    group,
                    core.bakegroup_color([naming.leaf_name(p) for p in renamed],
                                         low_suf, high_suf, cage_suf))
                scene.delete_if_empty(scene.managed_groups())
            except RuntimeError as exc:
                # The rename itself already succeeded and is worth keeping, so
                # say what was and was not done rather than implying nothing
                # happened.
                return fail("Renamed to '%s', but could not group it: %s"
                            % (base, exc))

        if settings.hide_after_renaming:
            for path in renamed:
                scene.set_object_parked(path, True)

    return ok("Namepair '%s' created: 1 low, %d high%s."
              % (base, len(high_paths), ", 1 cage" if cage_path else ""))
