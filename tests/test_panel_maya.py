# QC Bake for Maya - panel tests
# ------------------------------
# Everything here is about the panel staying honest: reporting what happened,
# staying in step with the scene, and never leaving a second copy of itself on
# screen. Every check corresponds to a failure that actually occurred.
#
# Run the synchronous half from Maya's script editor:
#
#     import importlib.util
#     spec = importlib.util.spec_from_file_location(
#         "qcbake_panel_tests",
#         r"C:\path\to\qc-bake-maya\tests\test_panel_maya.py")
#     m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
#     print(m.run())
#
# The other half - proving a scriptJob really fires - cannot run in one go.
# Maya dispatches those from its event loop, which a script never reaches:
# measured over a commandPort it took thirteen round trips, and no number of
# refresh() or processEvents() calls inside a single execution substitutes for
# it. So that part is split into phases the caller retries:
#
#     m.setup_deferred()
#     while not m.fired(): pass        # from separate calls / idle moments
#     print(m.finish_deferred(True))
#
# Destructive: repeatedly starts a new scene and saves nothing.

import os
import sys

import maya.cmds as cmds

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

RESULTS = []
STATE = {}


def check(label, got, want):
    RESULTS.append((got == want, label, got, want))


def _report():
    failures = [r for r in RESULTS if not r[0]]
    lines = ["%d checks, %d failed" % (len(RESULTS), len(failures))]
    for _, label, got, want in failures:
        lines.append("  FAIL %s\n       got:  %r\n       want: %r"
                     % (label, got, want))
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Synchronous checks
# -----------------------------------------------------------------------------
def run():
    """Everything that can be decided without waiting on Maya's event loop."""
    del RESULTS[:]

    import shiboken6

    import qc_bake_maya
    from qc_bake_maya import commands
    from qc_bake_maya.ui import panel as panel_mod

    # --- reporting ----------------------------------------------------------
    cmds.file(new=True, force=True)
    for index in range(3):
        cmds.polyCube(name="Cube%d" % (index + 1))

    panel = qc_bake_maya.show()
    panel._on_organize('PER_ASSET')
    message = panel.status.text()
    check("a refused action says something", bool(message), True)
    check("and says what to do next", "Create Namepair" in message, True)
    check("not-ready is a warning, not an error",
          "#3d3626" in panel.status.styleSheet(), True)

    # An exception escaping a command must reach the artist. A PySide slot
    # that raises otherwise prints to stdout and returns quietly, leaving the
    # panel looking fine while the action never ran.
    def boom():
        raise ValueError("synthetic failure")

    panel._run(boom)
    check("an exception reaches the status bar",
          "synthetic failure" in panel.status.text(), True)
    check("and is shown as an error",
          "#3d2727" in panel.status.styleSheet(), True)

    # --- show() must not fight its own uiScript -----------------------------
    # show() is what Maya runs to restore the workspaceControl, so it has to
    # be safe while that control exists. It used to delete it and rebuild,
    # which swapped the panel behind the artist and discarded the message
    # they were reading.
    message = panel.status.text()
    same = qc_bake_maya.show()
    check("show() reuses the live panel", same is panel, True)
    check("and keeps the message", same.status.text(), message)
    exec(panel_mod.UI_SCRIPT, {})
    check("the uiScript is safe to re-run", panel_mod._PANEL is panel, True)
    check("the control survived it",
          cmds.workspaceControl(panel_mod.WORKSPACE_CONTROL, exists=True), True)
    check("so did the message", panel.status.text(), message)

    # --- a mesh squatting on a group name -----------------------------------
    cmds.file(new=True, force=True)
    cmds.polyCube(name="thing_low")
    cmds.polySphere(name="thing_high", sx=20, sy=20)
    cmds.polyCube(name="Bake_Group")        # geometry, not a group
    panel._on_organize('FLAT')
    check("a mesh holding a group name is reported",
          "geometry" in panel.status.text(), True)

    # --- subscriptions ------------------------------------------------------
    cmds.file(new=True, force=True)
    low = cmds.polyCube(name="panel_src_a")[0]
    high = cmds.polySphere(name="panel_src_b", sx=20, sy=20)[0]
    cmds.select(clear=True)
    panel = qc_bake_maya.show()

    check("all subscriptions present", panel._script_jobs_healthy(), True)
    registered = {}
    wanted = ["SelectionChanged"] + list(panel_mod.SCENE_EVENTS)
    for entry in cmds.scriptJob(listJobs=True) or []:
        job_id = entry.split(":", 1)[0].strip()
        if not job_id.isdigit() or int(job_id) not in panel._script_jobs:
            continue
        for event in wanted:
            if "'%s'" % event in entry:
                registered[event] = "qcbake_scriptjob" in entry
    check("every event is subscribed", sorted(registered), sorted(wanted))
    # Bound to a module function, never to a panel method: a job holding a
    # panel's bound method keeps that panel addressable after Maya has
    # destroyed it, and a module reload then leaves those jobs running with
    # nothing able to find them. One real session accumulated 132.
    check("bound to the module, not to a panel", all(registered.values()), True)
    check("no orphaned subscriptions", panel_mod.orphan_job_count(), 0)

    # Reloading the package must not strand the previous generation's jobs.
    before = len(panel._script_jobs)
    panel_mod._install_jobs()                   # as a fresh generation would
    check("re-installing does not accumulate",
          len(panel_mod._running_jobs()), before)
    check("still none orphaned", panel_mod.orphan_job_count(), 0)

    # A subscription firing after its panel has gone must not raise into
    # Maya's error line - it must notice and stop itself.
    panel_mod._PANEL = None
    panel_mod.qcbake_scriptjob_selection()
    check("a job with no panel stops itself", panel_mod._running_jobs(), [])
    panel_mod._PANEL = panel
    panel._install_script_jobs()
    check("and can be re-armed", panel._script_jobs_healthy(), True)

    # Losing them must not freeze the panel. A frozen panel is the worst
    # failure this tool has: it looks completely normal but never notices
    # anything, so every button stays greyed out with nothing to explain why.
    panel._kill_script_jobs()
    check("jobs really gone", panel._script_jobs_healthy(), False)
    panel._check_health()                       # what the 2s timer does
    check("the health timer re-arms it", panel._script_jobs_healthy(), True)

    panel._kill_script_jobs()
    panel.setVisible(False)
    panel.setVisible(True)                      # showEvent
    check("showEvent re-arms it too", panel._script_jobs_healthy(), True)

    # --- exactly one panel --------------------------------------------------
    stray = panel_mod.QCBakePanel()             # built the wrong way, on purpose
    stray.show()
    check("stray starts alive", shiboken6.isValid(stray), True)
    qc_bake_maya.show()
    check("stray is hidden at once", stray.isVisible(), False)
    check("stray is dropped from the registry",
          any(ref() is stray for ref in panel_mod.QCBakePanel._instances), False)
    alive = [ref() for ref in panel_mod.QCBakePanel._instances]
    alive = [p for p in alive if p is not None and shiboken6.isValid(p)]
    check("exactly one panel registered", len(alive), 1)

    # --- the hint that explains a greyed-out button -------------------------
    for label, selection, create_enabled, fragment in (
            ("nothing", None, False, "Nothing selected"),
            ("one mesh", [low], False, "needs at least 2"),
            ("two meshes", [low, high], True, "denser one becomes the high"),
    ):
        if selection:
            cmds.select(selection, replace=True)
        else:
            cmds.select(clear=True)
        panel._refresh_selection()
        check("Create button with %s selected" % label,
              panel.btn_create.isEnabled(), create_enabled)
        check("hint with %s selected" % label,
              fragment in panel.selection_hint.text(), True)

    cmds.polyCube(name="panel_src_c")
    cmds.select([low, high, "panel_src_c"], replace=True)
    panel._refresh_selection()
    check("hint in group mode",
          "1 low and 2 highs" in panel.selection_hint.text(), True)

    # A selection of non-geometry must say so rather than read as "nothing".
    cmds.select(["persp"], replace=True)
    panel._refresh_selection()
    check("hint when the selection is not geometry",
          "none is a polygon mesh" in panel.selection_hint.text(), True)

    cmds.select(clear=True)
    panel.refresh()
    check("visibility hint shown while nothing is named",
          panel.visibility_hint.isVisibleTo(panel), True)
    cmds.select([low, high], replace=True)
    commands.create_namepair()
    panel.refresh()
    check("visibility hint hidden once names exist",
          panel.visibility_hint.isVisibleTo(panel), False)

    # --- the update throttle must not silence a fresh install ---------------
    # Settings are optionVars: they belong to the artist and outlive an
    # install. A copy installed minutes ago inherited the previous one's
    # "checked recently" timestamp and stayed quiet about being out of date.
    # Reported from a real install, so it is pinned here.
    import time

    from qc_bake_maya import prefs

    settings = prefs.load()
    saved = (settings.update_auto_check, settings.update_last_check,
             settings.update_last_version)
    try:
        settings.update_auto_check = True
        settings.update_last_check = time.time()       # checked a moment ago

        settings.update_last_version = qc_bake_maya.VERSION_STRING
        panel._update_check = None
        panel.maybe_check_for_updates()
        check("no check when this version checked recently",
              panel._update_check, None)

        settings.update_last_version = "0.0.1"         # a different build
        panel._update_check = None
        panel.maybe_check_for_updates()
        check("but a freshly installed version checks anyway",
              panel._update_check is not None, True)
        panel._update_check = None

        settings.update_auto_check = False
        settings.update_last_version = "0.0.1"
        panel.maybe_check_for_updates()
        check("and never when the artist switched it off",
              panel._update_check, None)
    finally:
        (settings.update_auto_check, settings.update_last_check,
         settings.update_last_version) = saved

    cmds.file(new=True, force=True)
    qc_bake_maya.show()
    return _report()


# -----------------------------------------------------------------------------
# The part that needs Maya's event loop
# -----------------------------------------------------------------------------
def setup_deferred():
    """Arm the end-to-end check: select two meshes and hand back to Maya."""
    del RESULTS[:]

    import qc_bake_maya

    cmds.file(new=True, force=True)
    STATE["low"] = cmds.polyCube(name="deferred_src_a")[0]
    STATE["high"] = cmds.polySphere(name="deferred_src_b", sx=20, sy=20)[0]
    cmds.select(clear=True)

    panel = qc_bake_maya.show()
    STATE["panel"] = panel
    panel._refresh_selection()
    check("baseline: Create is disabled", panel.btn_create.isEnabled(), False)

    # Nobody calls _refresh_selection from here on. Only the subscription can
    # turn the button on, which is the whole point.
    cmds.select([STATE["low"], STATE["high"]])
    return "armed"


def fired():
    """True once the SelectionChanged subscription has run. Poll me."""
    panel = STATE.get("panel")
    return bool(panel is not None and panel.btn_create.isEnabled())


def finish_deferred(did_fire):
    """Record the end-to-end result and report."""
    check("SelectionChanged reached the panel", bool(did_fire), True)

    import qc_bake_maya
    cmds.file(new=True, force=True)
    qc_bake_maya.show()
    return _report()
