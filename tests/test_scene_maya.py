# QC Bake for Maya - integration tests
# ------------------------------------
# Exercises the whole non-UI stack against a real Maya session. Run from
# Maya's script editor (or over a commandPort):
#
#     import qc_bake_maya.tests.test_scene_maya as t; t.run()
#
# Every test starts from a brand new scene, so this is destructive to whatever
# is currently open - it asks nothing and saves nothing.

import os
import sys

import maya.cmds as cmds

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

RESULTS = []


def check(label, got, want):
    RESULTS.append((got == want, label, got, want))


def check_true(label, got):
    check(label, bool(got), True)


def _reload():
    """Drop every qc_bake_maya module so edits on disk take effect."""
    for name in [n for n in list(sys.modules) if n.startswith("qc_bake_maya")]:
        del sys.modules[name]


def run():
    _reload()
    from qc_bake_maya import core, naming, prefs, scene
    from qc_bake_maya import commands

    settings = prefs.load()
    settings.reset()
    settings.naming_preset = 'SUBSTANCE'
    settings.hilo_criterion = 'TRIS'
    settings.also_rename_shape = True
    settings.move_to_group = False
    settings.hide_after_renaming = False
    settings.allow_name_collisions = False
    settings.detect_cage = True

    # -- settings round-trip -------------------------------------------------
    settings.reduce_min_gap = 2.5
    check("optionVar float round-trip", settings.reduce_min_gap, 2.5)
    settings.detect_cage = False
    check("optionVar bool round-trip", settings.detect_cage, False)
    settings.detect_cage = True
    settings.reduce_min_gap = 0.05

    # -- metrics -------------------------------------------------------------
    cmds.file(new=True, force=True)
    cube = cmds.ls(cmds.polyCube(name="probe_cube")[0], long=True)[0]
    check("metrics of a cube", scene.mesh_metrics(cube), (8, 6, 12))

    # smooth preview is invisible to polyEvaluate unless we ask for it
    cmds.setAttr(scene.mesh_shapes(cube)[0] + ".displaySmoothMesh", 2)
    cmds.setAttr(scene.mesh_shapes(cube)[0] + ".smoothLevel", 2)
    check("smooth preview ignored by default",
          scene.mesh_metrics(cube)[2], 12)
    check("smooth preview counted on request",
          scene.mesh_metrics(cube, count_smooth_preview=True)[2], 12 * 16)

    # -- create namepair, two objects ---------------------------------------
    cmds.file(new=True, force=True)
    low = cmds.polyCube(name="crate")[0]
    high = cmds.polySphere(name="crate_dense", sx=30, sy=30)[0]
    cmds.select([low, high])
    result = commands.create_namepair()
    check_true("create reports success", result.ok)
    check("low renamed", cmds.objExists("crate_low"), True)
    check("high renamed", cmds.objExists("crate_high"), True)
    check("shape renamed too",
          cmds.listRelatives("crate_low", shapes=True)[0], "crate_lowShape")

    # -- swap ----------------------------------------------------------------
    low_tris_before = scene.mesh_metrics("|crate_low")[2]
    cmds.select(["crate_low", "crate_high"])
    check_true("swap reports success", commands.swap_high_low().ok)
    # The dense mesh should now be the one named _low.
    check("swap moved the geometry over",
          scene.mesh_metrics("|crate_low")[2] != low_tris_before, True)
    cmds.select(["crate_low", "crate_high"])
    commands.swap_high_low()  # put it back

    # -- collision is refused, not silently numbered -------------------------
    cmds.polyCube(name="blocker")[0]
    cmds.rename("blocker", "prop_low")
    a = cmds.polyCube(name="prop")[0]
    b = cmds.polySphere(name="prop_dense", sx=20, sy=20)[0]
    cmds.select([a, b])
    clash = commands.create_namepair()
    check("collision refused", clash.ok, False)
    check("collision names the culprit", "prop_low" in clash.message, True)
    check("nothing was renamed", cmds.objExists("prop"), True)

    settings.allow_name_collisions = True
    cmds.select([a, b])
    check_true("collision allowed when asked for",
               commands.create_namepair().ok)
    settings.allow_name_collisions = False

    # -- multiple highs + cage ----------------------------------------------
    cmds.file(new=True, force=True)
    lo = cmds.polyCube(name="bolt")[0]
    h1 = cmds.polySphere(name="bolt_a", sx=20, sy=20)[0]
    h2 = cmds.polySphere(name="bolt_b", sx=22, sy=22)[0]
    cg = cmds.polyCube(name="bolt_cage")[0]
    cmds.select([lo, h1, h2, cg])
    result = commands.create_namepair()
    check_true("group mode reports success", result.ok)
    check("indexed highs", sorted(cmds.ls("bolt_high_*", type="transform")),
          ["bolt_high_01", "bolt_high_02"])
    check("cage kept its role", cmds.objExists("bolt_cage"), True)
    check("cage did not become a high", cmds.objExists("bolt_high_03"), False)

    # -- namespaces ----------------------------------------------------------
    cmds.file(new=True, force=True)
    cmds.namespace(add="REF")
    cmds.namespace(set="REF")
    nlo = cmds.polyCube(name="ref_asset")[0]
    nhi = cmds.polySphere(name="ref_dense", sx=20, sy=20)[0]
    cmds.namespace(set=":")
    cmds.select([nlo, nhi])
    check_true("namespaced create succeeds", commands.create_namepair().ok)
    check("stayed inside its namespace", cmds.objExists("REF:ref_asset_low"), True)
    check("did not escape to root", cmds.objExists("ref_asset_low"), False)

    # -- organize, both layouts ---------------------------------------------
    cmds.file(new=True, force=True)
    for name in ("alpha", "beta"):
        cmds.polyCube(name=name + "_low")
        cmds.polySphere(name=name + "_high", sx=20, sy=20)
    cmds.polyCube(name="a_prop_that_must_not_move")

    check_true("organize per-asset", commands.organize('PER_ASSET').ok)
    check("head group made", cmds.objExists(core.HEAD_NAME), True)
    check("per-asset groups made",
          sorted(n.rsplit("|", 1)[-1]
                 for n in cmds.ls("Bake_alpha", "Bake_beta", long=True)),
          ["Bake_alpha", "Bake_beta"])
    check("members were moved in",
          sorted(cmds.listRelatives("Bake_alpha", children=True) or []),
          ["alpha_high", "alpha_low"])
    check("unrelated prop untouched",
          cmds.listRelatives("a_prop_that_must_not_move", parent=True), None)
    check("complete pair tagged green",
          [round(v, 2) for v in cmds.getAttr("Bake_alpha.outlinerColor")[0]],
          [round(v, 2) for v in core.BAKEGROUP_COLOR_OK])

    # an incomplete pair must go red
    cmds.polyCube(name="gamma_low")
    commands.organize('PER_ASSET')
    check("incomplete pair tagged red",
          [round(v, 2) for v in cmds.getAttr("Bake_gamma.outlinerColor")[0]],
          [round(v, 2) for v in core.BAKEGROUP_COLOR_WARN])

    # rebuilding into the other layout must clear the old one out
    check_true("organize flat", commands.organize('FLAT').ok)
    check("flat role groups made",
          sorted(cmds.listRelatives(core.HEAD_NAME, children=True) or []),
          ["High", "Low"])
    check("per-asset groups cleaned up", cmds.objExists("Bake_alpha"), False)
    check("flat groups carry no health tag",
          cmds.getAttr(cmds.ls("High", long=True)[0] + ".useOutlinerColor"), 0)

    # -- geometry must not move when grouped --------------------------------
    cmds.file(new=True, force=True)
    moved = cmds.polyCube(name="far_low")[0]
    cmds.setAttr(moved + ".translate", 7, 3, -2)
    cmds.polySphere(name="far_high", sx=20, sy=20)
    before = cmds.xform(moved, query=True, worldSpace=True, translation=True)
    commands.organize('PER_ASSET')
    after = cmds.xform(cmds.ls("far_low", long=True)[0], query=True,
                       worldSpace=True, translation=True)
    check("grouping did not move geometry",
          [round(v, 4) for v in before], [round(v, 4) for v in after])

    # -- organize on a scene that is not ready --------------------------------
    # Pressing a Collection Layout button before anything has been renamed is
    # a normal thing to do, not a failure. It must report a warning that says
    # what to do next, and must not create the head group as a side effect.
    cmds.file(new=True, force=True)
    for index in range(3):
        cmds.polyCube(name="Cube%d" % (index + 1))
    result = commands.organize('PER_ASSET')
    check("unnamed scene warns, not errors", result.level, 'WARNING')
    check("warning points at Create Namepair",
          "Create Namepair" in result.message, True)
    check("warning counts the meshes", "3 meshes" in result.message, True)
    check("no head group left behind", cmds.objExists(core.HEAD_NAME), False)

    result = commands.set_group_visible('HIGH', False)
    check("visibility on unnamed scene warns", result.level, 'WARNING')

    # -- an orphaned duplicate gets its own red group --------------------------
    # The reported case: Cub_low2 (a duplicate Maya renamed) sat inside
    # Bake_Cube1, invisible to the tool, while that group still read green.
    cmds.file(new=True, force=True)
    cmds.polyCube(name="Cube1_low")
    cmds.polySphere(name="Cube1_high", sx=20, sy=20)
    commands.organize('PER_ASSET')
    # Drop the orphan straight into the finished group, the way duplicating
    # inside it would.
    orphan = cmds.polyCube(name="Cub_low")[0]
    orphan = cmds.rename(orphan, "Cub_low2")
    cmds.parent(orphan, cmds.ls("Bake_Cube1", long=True)[0])

    check("the orphan is recognised as a low",
          core.classify_role("Cub_low2", "_low", "_high", "_cage"), 'LOW')

    result = commands.organize('PER_ASSET')
    check("reorganise succeeds", result.ok, True)
    check("orphan moved out of the paired group",
          sorted(cmds.listRelatives("Bake_Cube1", children=True) or []),
          ["Cube1_high", "Cube1_low"])
    check("orphan got its own group", cmds.objExists("Bake_Cub"), True)
    check("which holds exactly it",
          cmds.listRelatives("Bake_Cub", children=True), ["Cub_low2"])
    check("orphan group is red",
          [round(v, 2) for v in cmds.getAttr("Bake_Cub.outlinerColor")[0]],
          [round(v, 2) for v in core.BAKEGROUP_COLOR_WARN])
    check("the complete pair stays green",
          [round(v, 2) for v in cmds.getAttr("Bake_Cube1.outlinerColor")[0]],
          [round(v, 2) for v in core.BAKEGROUP_COLOR_OK])
    # It is a low, so it belongs to the Low role for visibility too.
    check("orphan counts towards the Low role",
          commands.group_state('LOW'), 'SHOWN')

    # -- a genuinely unnamed mesh inside a bake group --------------------------
    # Not ours to move, but it must not let the group claim to be healthy.
    prop = cmds.polyCube(name="just_a_prop")[0]
    cmds.parent(prop, cmds.ls("Bake_Cube1", long=True)[0])
    result = commands.organize('PER_ASSET')
    check("stray is reported", result.level, 'WARNING')
    check("and named", "just_a_prop" in result.message, True)
    check("stray was left where it is",
          cmds.listRelatives("just_a_prop", parent=True), ["Bake_Cube1"])
    check("its group is dragged red",
          [round(v, 2) for v in cmds.getAttr("Bake_Cube1.outlinerColor")[0]],
          [round(v, 2) for v in core.BAKEGROUP_COLOR_WARN])

    cmds.delete(prop)
    result = commands.organize('PER_ASSET')
    check("clean again once the stray is gone", result.level, 'INFO')
    check("and green again",
          [round(v, 2) for v in cmds.getAttr("Bake_Cube1.outlinerColor")[0]],
          [round(v, 2) for v in core.BAKEGROUP_COLOR_OK])

    # -- a mesh squatting on a group name -------------------------------------
    # An asset called "Low" must not be adopted as the Low group and have the
    # rest of the scene parented inside it.
    cmds.file(new=True, force=True)
    cmds.polyCube(name="thing_low")
    cmds.polySphere(name="thing_high", sx=20, sy=20)
    cmds.polyCube(name="Low")        # geometry, not a group
    result = commands.organize('FLAT')
    check("mesh squatting on a group name is refused", result.ok, False)
    check("and the message names it", "geometry" in result.message, True)
    check("the mesh was not turned into a group",
          bool(scene.mesh_shapes(cmds.ls("Low", long=True)[0])), True)

    cmds.delete("Low")
    check_true("organize works once the name is free",
               commands.organize('FLAT').ok)

    # -- visibility ----------------------------------------------------------
    cmds.file(new=True, force=True)
    cmds.polyCube(name="v_low")
    vhigh = cmds.polySphere(name="v_high", sx=20, sy=20)[0]
    # An artist's own visibility choice that the tool must not trample.
    cmds.setAttr(vhigh + ".visibility", 0)

    check("state starts shown", commands.group_state('LOW'), 'SHOWN')
    check_true("hide highs", commands.set_group_visible('HIGH', False).ok)
    check("high layer is off", scene.layer_visible(scene.ROLE_LAYERS['HIGH']), False)
    check("high state reads hidden", commands.group_state('HIGH'), 'HIDDEN')
    check("low state unaffected", commands.group_state('LOW'), 'SHOWN')
    check("artist visibility preserved", cmds.getAttr(vhigh + ".visibility"), False)

    check_true("show highs again", commands.set_group_visible('HIGH', True).ok)
    check("high state reads shown", commands.group_state('HIGH'), 'SHOWN')
    check("cage role reports nothing", commands.group_state('CAGE'), None)

    check_true("clear all", commands.clear_all().ok)
    check("layers removed",
          cmds.objExists(scene.ROLE_LAYERS['HIGH']), False)

    # -- reduce / restore ----------------------------------------------------
    cmds.file(new=True, force=True)
    for index, offset in enumerate((0, 40, 80), start=1):
        lo = cmds.polyCube(name="asset%d_low" % index)[0]
        hi = cmds.polySphere(name="asset%d_high" % index, sx=20, sy=20)[0]
        for node in (lo, hi):
            cmds.setAttr(node + ".translateX", offset)

    settings.reduce_min_gap = 5.0
    settings.reduce_group_prefix = "BakeGroup"
    result = commands.reduce_groups()
    check_true("reduce reports success", result.ok)
    check("three assets became one group",
          sorted(cmds.ls("BakeGroup_01_*", type="transform")),
          ["BakeGroup_01_high_01", "BakeGroup_01_high_02",
           "BakeGroup_01_high_03", "BakeGroup_01_low_01",
           "BakeGroup_01_low_02", "BakeGroup_01_low_03"])
    check("backup recorded", commands.has_backup(), True)
    check("backup holds the old name",
          scene.get_string_attr(cmds.ls("BakeGroup_01_low_01", long=True)[0],
                                core.REDUCE_PREV_NAME_ATTR),
          "asset1_low")

    check_true("restore reports success", commands.restore_groups().ok)
    check("names came back",
          sorted(cmds.ls("asset*_low", "asset*_high", type="transform")),
          ["asset1_high", "asset1_low", "asset2_high", "asset2_low",
           "asset3_high", "asset3_low"])
    check("backup cleared", commands.has_backup(), False)

    # assets too close together must not be merged
    cmds.file(new=True, force=True)
    for index, offset in enumerate((0, 1.2), start=1):
        lo = cmds.polyCube(name="near%d_low" % index)[0]
        hi = cmds.polySphere(name="near%d_high" % index, sx=20, sy=20)[0]
        for node in (lo, hi):
            cmds.setAttr(node + ".translateX", offset)
    settings.reduce_min_gap = 10.0
    result = commands.reduce_groups()
    check("overlapping assets are refused", result.ok, False)
    check("and nothing was renamed", cmds.objExists("near1_low"), True)

    settings.reset()
    cmds.file(new=True, force=True)

    failures = [r for r in RESULTS if not r[0]]
    lines = ["%d checks, %d failed" % (len(RESULTS), len(failures))]
    for _, label, got, want in failures:
        lines.append("  FAIL %s\n       got:  %r\n       want: %r"
                     % (label, got, want))
    report = "\n".join(lines)
    print(report)
    return report
