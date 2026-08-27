# QC Bake for Maya - first-install test
# -------------------------------------
# Rehearses what a new artist does: unzip the published archive somewhere it
# has never been, and drop install/install.py into a Maya viewport. Nothing in
# here reaches back into the development repository, which is the point - if
# the release archive is missing a file, this is where it shows.
#
# It found exactly that once: the shelf icon lived beside the package instead
# of inside it, so the build skipped it and every fresh install silently wore
# a stock Maya icon.
#
#     import importlib.util
#     spec = importlib.util.spec_from_file_location(
#         "qcbake_install_test",
#         r"C:\path\to\qc-bake-maya\tests\test_install_maya.py")
#     m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
#     print(m.run())
#
# Destructive: uninstalls QC Bake, installs a copy from the archive, then puts
# the development install back. Starts a new scene and saves nothing.

import glob
import os
import shutil
import sys
import tempfile
import traceback
import zipfile

import maya.cmds as cmds

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

RESULTS = []


def check(label, got, want):
    RESULTS.append((got == want, label, got, want))


def _module_file():
    return os.path.join(cmds.internalVar(userAppDir=True),
                        cmds.about(version=True), "modules",
                        "qc_bake_maya.mod")


def _find_archives():
    """Newest-last list of built archives, wherever the build put them.

    The build writes into the repository on CI, because the workflow publishes
    from the checkout, and into the Dev folder beside it when run by hand, so
    that a working copy holds only the files the repository actually contains.
    Both are looked at rather than assumed.
    """
    found = []
    for base in (REPO, os.path.join(os.path.dirname(REPO), "Dev")):
        found.extend(glob.glob(os.path.join(base, "dist", "*.zip")))
    return sorted(found, key=os.path.getmtime)


def _forget_everything():
    """Leave this Maya with no trace of QC Bake loaded or installed."""
    if "qc_bake_maya.ui.panel" in sys.modules:
        try:
            sys.modules["qc_bake_maya.ui.panel"].close()
        except Exception:
            pass
    for name in [n for n in list(sys.modules)
                 if n.startswith("qc_bake_maya") or n == "install"]:
        del sys.modules[name]
    sys.path[:] = [p for p in sys.path
                   if "qc_bake-maya" not in p and "qcbake_fresh" not in p]

    path = _module_file()
    if os.path.isfile(path):
        os.remove(path)
    if cmds.shelfLayout("Mutaform", exists=True):
        for child in cmds.shelfLayout("Mutaform", query=True,
                                      childArray=True) or []:
            if cmds.control(child, query=True, exists=True):
                cmds.deleteUI(child)


def run():
    """Install from the newest dist/*.zip into a fresh folder, then restore."""
    del RESULTS[:]
    notes = []
    fresh = None

    try:
        _forget_everything()

        archives = _find_archives()
        check("a release archive exists", bool(archives), True)
        if not archives:
            return _report(notes)
        archive = archives[-1]
        notes.append("archive: %s" % os.path.basename(archive))

        fresh = tempfile.mkdtemp(prefix="qcbake_fresh_")
        with zipfile.ZipFile(archive) as handle:
            handle.extractall(fresh)

        tops = [os.path.join(fresh, name) for name in os.listdir(fresh)]
        tool_dir = tops[0] if len(tops) == 1 and os.path.isdir(tops[0]) else fresh
        notes.append("unpacked to: %s" % tool_dir)

        installer_py = os.path.join(tool_dir, "install", "install.py")
        check("install.py is where the README says it is",
              os.path.isfile(installer_py), True)

        sys.path.insert(0, os.path.dirname(installer_py))
        import install as installer

        check("the installer takes its own folder as the root",
              installer.repo_root(), tool_dir)

        # The real drag-into-the-viewport entry point, not install() directly.
        installer.onMayaDroppedPythonFile()
        notes.append("ran onMayaDroppedPythonFile()")

        path = _module_file()
        check("a module file was written", os.path.isfile(path), True)
        if os.path.isfile(path):
            body = open(path, encoding="utf-8").read()
            notes.append("module: %r" % body)
            check("pointing at the unpacked folder",
                  tool_dir.replace("\\", "/") in body, True)

        import qc_bake_maya
        check("the package imports", bool(qc_bake_maya.VERSION_STRING), True)
        check("out of the new folder, not the repository",
              os.path.dirname(os.path.dirname(qc_bake_maya.__file__)), tool_dir)
        notes.append("version: %s" % qc_bake_maya.VERSION_STRING)

        children = cmds.shelfLayout("Mutaform", query=True,
                                    childArray=True) or []
        check("exactly one shelf button",
              [cmds.shelfButton(c, query=True, label=True) for c in children],
              ["QC Bake"])
        icon = (cmds.shelfButton(children[0], query=True, image1=True)
                if children else "")
        notes.append("icon: %s" % icon)
        check("wearing the bundled flame, not a Maya fallback",
              icon.endswith("qc_bake_32.png"), True)
        check("and that file really shipped", os.path.isfile(icon), True)

        check("the panel opened",
              cmds.workspaceControl("QCBakeMayaPanelWorkspaceControl",
                                    exists=True), True)

        from qc_bake_maya.ui import panel as panel_mod
        check("subscriptions armed", panel_mod._jobs_healthy(), True)
        check("no orphaned subscriptions", panel_mod.orphan_job_count(), 0)

        # Loading is not the same as working.
        from qc_bake_maya import commands
        cmds.file(new=True, force=True)
        low = cmds.polyCube(name="fresh_crate")[0]
        high = cmds.polySphere(name="fresh_dense", sx=20, sy=20)[0]
        cmds.select([low, high])
        check("Create Namepair works on a fresh install",
              commands.create_namepair().ok, True)
        check("and the pair was renamed",
              cmds.objExists("fresh_crate_low"), True)
    except Exception:
        notes.append(traceback.format_exc())
    finally:
        try:
            _forget_everything()
            sys.path.insert(0, os.path.join(REPO, "install"))
            import install as dev_installer
            dev_installer.install()
            cmds.file(new=True, force=True)
            import qc_bake_maya as restored
            notes.append("restored the development install: %s from %s"
                         % (restored.VERSION_STRING,
                            os.path.dirname(
                                os.path.dirname(restored.__file__))))
        except Exception:
            notes.append("RESTORE FAILED:\n" + traceback.format_exc())
        if fresh:
            shutil.rmtree(fresh, ignore_errors=True)

    return _report(notes)


def _report(notes):
    failures = [r for r in RESULTS if not r[0]]
    lines = ["%d checks, %d failed" % (len(RESULTS), len(failures))]
    for _, label, got, want in failures:
        lines.append("  FAIL %s\n       got:  %r\n       want: %r"
                     % (label, got, want))
    lines.append("")
    lines.extend(notes)
    return "\n".join(lines)
