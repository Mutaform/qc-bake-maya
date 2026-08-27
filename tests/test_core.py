# QC Bake for Maya - logic tests
# ------------------------------
# core and naming import nothing from Maya, so the decision layer can be
# exercised in a plain interpreter. Run with:
#
#     python tests/test_core.py
#
# Deliberately dependency-free (no pytest) so it also runs inside mayapy.

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qc_bake_maya import core, naming  # noqa: E402

FAILURES = []


def check(label, got, want):
    if got != want:
        FAILURES.append("%s\n     got:  %r\n     want: %r" % (label, got, want))


# -- suffix handling ---------------------------------------------------------
class FakeSettings(object):
    naming_preset = 'CUSTOM'
    custom_low_suffix = "_L"
    custom_high_suffix = "_H"
    custom_cage_suffix = "_C"


check("custom suffixes", core.get_suffixes(FakeSettings()), ("_L", "_H", "_C"))

FakeSettings.naming_preset = 'XNORMAL'
check("preset suffixes", core.get_suffixes(FakeSettings()), ("_lo", "_hi", "_cage"))

check("strip suffix", core.strip_known_suffixes("asset_low", ["_low", "_high"]), "asset")
check("strip nothing", core.strip_known_suffixes("asset", ["_low"]), "asset")

# -- role classification -----------------------------------------------------
check("role low", core.classify_role("a_low", "_low", "_high", "_cage"), 'LOW')
check("role high", core.classify_role("a_high", "_low", "_high", "_cage"), 'HIGH')
check("role cage", core.classify_role("a_cage", "_low", "_high", "_cage"), 'CAGE')
check("role indexed high",
      core.classify_role("a_high_01", "_low", "_high", "_cage"), 'HIGH')
check("role none", core.classify_role("prop_wall", "_low", "_high", "_cage"), None)
# A prop whose own name merely contains "low" must not be swept in.
check("role not fooled",
      core.classify_role("yellow", "_low", "_high", "_cage"), None)

check("base plain", core.base_name("a_high", "_low", "_high", "_cage"), "a")
check("base indexed", core.base_name("a_high_01", "_low", "_high", "_cage"), "a")
check("base of low", core.base_name("FMN204_low", "_low", "_high", "_cage"), "FMN204")

# -- Maya's auto-numbering ---------------------------------------------------
# Duplicating geometry is how a Maya artist makes a variant, and Maya names the
# copy by appending a digit. A plain endswith goes blind to the result, and the
# object then disappears from every list the tool builds while still sitting
# inside whatever group it was in - reported as a bug on a real scene.
check("duplicate of a low is still a low",
      core.classify_role("Cub_low2", "_low", "_high", "_cage"), 'LOW')
check("and keeps its own base",
      core.base_name("Cub_low2", "_low", "_high", "_cage"), "Cub")
check("duplicate of a high is still a high",
      core.classify_role("crate_high3", "_low", "_high", "_cage"), 'HIGH')
check("multi-digit duplicate",
      core.base_name("crate_low12", "_low", "_high", "_cage"), "crate")
check("duplicate of a cage",
      core.classify_role("crate_cage2", "_low", "_high", "_cage"), 'CAGE')
check("xNormal suffix duplicates too",
      core.classify_role("crate_lo2", "_lo", "_hi", "_cage"), 'LOW')

# The leading underscore is what keeps this from over-reaching.
check("a prop is not swept in by digit trimming",
      core.classify_role("pillow2", "_low", "_high", "_cage"), None)
check("nor is a numbered prop",
      core.classify_role("Cube1", "_low", "_high", "_cage"), None)
check("a digit inside the base is untouched",
      core.base_name("wall2_low", "_low", "_high", "_cage"), "wall2")
# An indexed member must still beat the digit rule: "_high_02" is a member of
# a multi-high asset, not a duplicate called "_high_0" plus a "2".
check("indexed member still wins",
      core.base_name("Cube1_high_02", "_low", "_high", "_cage"), "Cube1")
check("a name that is only a suffix keeps itself",
      core.base_name("_low", "_low", "_high", "_cage"), "_low")

check("suffix_index plain", core.suffix_index("a_low", "_low"), 1)
check("suffix_index numbered", core.suffix_index("a_low7", "_low"), 1)
check("suffix_index absent", core.suffix_index("a_lowx", "_low"), None)
check("suffix_index empty suffix", core.suffix_index("a_low", ""), None)

# -- health colour -----------------------------------------------------------
check("group ok",
      core.bakegroup_color(["a_low", "a_high"], "_low", "_high", "_cage"),
      core.BAKEGROUP_COLOR_OK)
check("group missing high",
      core.bakegroup_color(["a_low"], "_low", "_high", "_cage"),
      core.BAKEGROUP_COLOR_WARN)
check("cage alone is not a pair",
      core.bakegroup_color(["a_low", "a_cage"], "_low", "_high", "_cage"),
      core.BAKEGROUP_COLOR_WARN)
# A complete pair is still unfit to bake if something unnamed is sitting in
# the group with it - that geometry will be in the bake.
check("a stray drags a complete group red",
      core.bakegroup_color(["a_low", "a_high"], "_low", "_high", "_cage",
                           has_stray=True),
      core.BAKEGROUP_COLOR_WARN)

# -- name planning -----------------------------------------------------------
check("single high names",
      core.member_names("a", "_low", "_high", "_cage", 1, False),
      ["a_low", "a_high"])
check("multi high names",
      core.member_names("a", "_low", "_high", "_cage", 3, True),
      ["a_low", "a_high_01", "a_high_02", "a_high_03", "a_cage"])

# -- hi/lo choice ------------------------------------------------------------
entries = [("cube", (8, 6, 12)), ("sphere", (1562, 1600, 3120))]
check("choose low by tris", core.choose_low(entries, 'TRIS'), "cube")
check("choose low by verts", core.choose_low(entries, 'VERTS'), "cube")
check("tie is unknowable",
      core.choose_low([("a", (8, 6, 12)), ("b", (8, 6, 12))], 'TRIS'), None)

# -- spatial packing ---------------------------------------------------------
# Three unit cubes in a row, two units apart.
def box(x):
    return (x - 0.5, -0.5, -0.5, x + 0.5, 0.5, 0.5)


check("gap between neighbours", round(core.bounds_gap(box(0), box(2)), 4), 1.0)
check("gap when overlapping", core.bounds_gap(box(0), box(0.2)), 0.0)
check("volume", core.bounds_volume(box(0)), 1.0)

assets = [{"base": "a", "bounds": box(0)},
          {"base": "b", "bounds": box(2)},
          {"base": "c", "bounds": box(4)}]
# A tiny gap requirement: all three fit in one group.
check("packs into one", [len(g) for g in core.pack_groups(assets, 0.5)], [3])
# Neighbours sit 1.0 apart but the outer pair is 3.0 apart, so a 1.5 gap
# requirement splits the neighbours yet still lets a and c share a group.
# Skipping over an unusable neighbour to reach a usable one is the whole
# point of the packer - it is not allowed to give up at the first conflict.
check("packs around a conflict",
      [[a["base"] for a in g] for g in core.pack_groups(assets, 1.5)],
      [["a", "c"], ["b"]])
# A gap larger than any spacing in the row: nothing may share a group.
check("packs into three", [len(g) for g in core.pack_groups(assets, 3.5)], [1, 1, 1])
# Packing must be deterministic across runs.
check("packing is stable",
      [[a["base"] for a in g] for g in core.pack_groups(assets, 0.5)],
      [[a["base"] for a in g] for g in core.pack_groups(list(reversed(assets)), 0.5)])

check("prefix cleaned", core.clean_prefix("  My Group "), "My_Group")
check("prefix fallback", core.clean_prefix(""), "BakeGroup")

# -- Maya name handling ------------------------------------------------------
check("leaf of dag path", naming.leaf_name("|Bake_Group|Bake_a|a_low"), "a_low")
check("leaf strips namespace", naming.leaf_name("|grp|REF:a_low"), "a_low")
check("namespace split", naming.split_namespace("|grp|REF:a_low"), ("REF", "a_low"))
check("nested namespace",
      naming.split_namespace("SET:REF:a_low"), ("SET:REF", "a_low"))
check("no namespace", naming.split_namespace("|grp|a_low"), ("", "a_low"))

check("namespace reapplied",
      naming.with_namespace("|grp|REF:a_low", "a_high"), "REF:a_high")
check("no namespace to reapply",
      naming.with_namespace("|grp|a_low", "a_high"), "a_high")

check("parent path", naming.parent_path("|Bake_Group|Bake_a|a_low"),
      "|Bake_Group|Bake_a")
check("root has no parent", naming.parent_path("|a_low"), "")

check("valid name", naming.is_valid("asset_low"), True)
check("leading digit invalid", naming.is_valid("1asset"), False)
check("space invalid", naming.is_valid("my asset"), False)
check("sanitize keeps digits", naming.sanitize("asset01_low"), "asset01_low")
check("sanitize leading digit", naming.sanitize("1asset"), "_1asset")
check("sanitize spaces", naming.sanitize("my asset"), "my_asset")
check("sanitize empty", naming.sanitize("   "), "object")

check("suffix ok", naming.validate_suffix("_low", "Low"), None)
check("empty suffix rejected",
      naming.validate_suffix("", "Low") is not None, True)
check("bad suffix rejected",
      naming.validate_suffix("_lo w", "Low") is not None, True)


if FAILURES:
    print("FAILED (%d)\n" % len(FAILURES))
    for failure in FAILURES:
        print("  - " + failure)
    sys.exit(1)
print("all logic tests passed")
