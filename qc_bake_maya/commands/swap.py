# QC Bake for Maya - swap high/low
# --------------------------------
# When the automatic hi/lo choice picks wrong - a dense low poly against a
# sparse blocked-out high, say - this flips the two roles over.

from .. import naming, prefs, scene
from . import fail, ok
from ._common import resolve_suffixes


def swap_high_low():
    """Swap the low and high roles of the two selected objects."""
    settings = prefs.load()

    selected = scene.selected_meshes()
    if len(selected) != 2:
        return fail("Select exactly two objects: one low and one high.")

    suffixes, error = resolve_suffixes(settings)
    if error:
        return error
    low_suf, high_suf, _cage = suffixes

    lows = [p for p in selected if naming.leaf_name(p).endswith(low_suf)]
    highs = [p for p in selected if naming.leaf_name(p).endswith(high_suf)]

    if len(lows) != 1 or len(highs) != 1:
        return fail("Select exactly one '%s' and one '%s' object."
                    % (low_suf, high_suf))

    low_path, high_path = lows[0], highs[0]
    low_base = naming.leaf_name(low_path)[: -len(low_suf)]
    high_base = naming.leaf_name(high_path)[: -len(high_suf)]

    # The object currently named <base>_low becomes <base>_high and the other
    # way round. rename_batch parks both on temporary names first, which
    # matters here more than anywhere: a namepair shares its base name, so the
    # second rename would otherwise land on a name the first still holds and
    # Maya would quietly number its way out of the clash.
    plan = [(low_path, low_base + high_suf),
            (high_path, high_base + low_suf)]

    with scene.undo_chunk("QC Bake: Swap High / Low"):
        try:
            scene.rename_batch(plan, settings.also_rename_shape,
                               strict=not settings.allow_name_collisions)
        except RuntimeError as exc:
            return fail(str(exc))

    return ok("Swapped high/low roles.")
