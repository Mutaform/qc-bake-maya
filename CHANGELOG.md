# Changelog

## 1.1.2

Licensing and housekeeping. No functional change to the tool.

- **The LICENSE file was a placeholder.** It carried GPL-2.0-or-later, pointed
  at `qc_bake/blender_manifest.toml` - a file that belongs to the Blender
  repository and does not exist here - and contained an instruction to replace
  itself before public release, which had not happened. QC Bake for Maya is now
  explicitly Copyright (c) 2026 Mutaform Studio, all rights reserved. The
  Blender edition is GPL because Blender's Python API requires that of add-ons;
  Maya imposes no equivalent condition, and the same author licenses this
  edition on its own terms.
- Documentation examples no longer hard-code one machine's folder layout. They
  read `C:\path\to\qc-bake-maya`, which is obviously a placeholder rather than
  a path that happens to exist on exactly one computer.
- Removed an empty `tests/__init__.py`. Nothing imported `tests` as a package.

## 1.1.1

**The release archive did not contain the shelf icon.** It sat beside the
package rather than inside it, so the build skipped it: every install from a
published zip would have silently worn a stock Maya icon, and an update - which
swaps the package folder and nothing else - would never have put it right. The
rendered PNGs now live in `qc_bake_maya/resources/`, inside the package, so
they travel with both. The artwork and its generator stay outside, in
`icons_src/`, since only whoever redraws the icon needs them.

Found by a new test, `tests/test_install_maya.py`, which unpacks the published
archive into a folder that has never held the tool and installs from there
through the real drag-and-drop entry point - then checks the module file, the
shelf button, the icon on it, the panel, its subscriptions, and that Create
Namepair actually renames something. Nothing in it reaches back into the
development repository, which is why it caught this at all.

## 1.1.0

**Updates.** Maya has no add-on repository - a `.mod` is a path pointer,
`moduleInfo` knows nothing about versions, and the Autodesk App Store means a
bundle and a review queue. So QC Bake now checks a manifest published on
GitHub Pages and says at the top of the panel when a newer release exists. It
never installs on its own.

- Pressing **Install** downloads the archive, checks it against the digest the
  manifest declared, unpacks it, swaps it into place and reloads the package
  without restarting Maya. The previous version is kept until the new one has
  actually imported, so a broken release restores itself.
- The check runs on a worker thread, at most once every six hours, and stays
  quiet on failure unless it was asked for by hand - a studio proxy that
  swallows the request must never stall Maya or nag every time the panel opens.
- Refusals that matter: manifests served or downloading over plain http, a
  manifest for a different tool, a version string that is not a version, an
  archive that is not a zip, an archive that unpacks outside its own folder,
  and an archive whose contents disagree with the version advertised.
- `tools/build_release.ps1` generates `version.json` beside the zip, and
  `.github/workflows/pages.yml` publishes both. The manifest is built, never
  hand-written, so it cannot drift from the archive it describes.

**A shelf icon of its own.** A flame, drawn as flat vector in three layers,
replacing the borrowed Maya resource. Source and generator in `icons/src/`.
The studio mark was tried in the icon and dropped: at the 32 pixels a shelf
button actually draws, it either crowded the flame or turned into a dark
smudge that read as dirt rather than as a logo.

## 1.0.4

Fixes the blank panel and the `RuntimeError: Internal C++ object already
deleted` behind it. One session had accumulated **132 scriptJobs aimed at
twelve destroyed panels**, each firing on every selection change.

The cause was ownership. Subscriptions were installed by a panel, bound to
that panel's own methods, and tracked in a registry on the class. Maya does
not reliably tell a widget when its workspaceControl is destroyed, so the jobs
outlived their panels - and reloading the package gave the class a fresh
registry while Maya carried on running the old jobs, which nothing could then
find or stop.

- Subscriptions now belong to the module and are bound to module functions
  that look up whichever panel is current, so a job can never hold a dead one.
- Which jobs exist is read back from Maya rather than remembered. Keeping a
  second copy of that list meant two sources of truth that drifted: a panel
  would believe its subscriptions were gone while eleven of them ran happily,
  and reinstall on every tick. It also makes jobs from a previous generation
  findable, which is what makes a reload survivable.
- Nothing escapes a subscription callback any more. Maya *disables* a
  scriptJob whose callback raises - which is how those orphans eventually died,
  one error line each - so a single unhandled exception in a refresh would have
  silently unsubscribed the panel and frozen it for the session.
- `_refresh_selection` is guarded like `refresh`. It was the one callback
  reaching for widgets with no protection, and it was line 506 in the report.
- A panel being replaced no longer tears down its successor's wiring, and a
  panel is no longer wired up before it is reachable - a race that left the
  new subscriptions dead on arrival.
- `close()` stops the subscriptions; call it before reloading the package.

## 1.0.3

- **Maya's auto-numbering no longer hides an object from the tool.**
  Duplicating geometry is how a Maya artist makes a variant, and Maya names the
  copy by appending a digit - so `Cub_low` becomes `Cub_low2`, which a plain
  suffix test does not recognise. Such an object dropped out of every list QC
  Bake builds: not organised, not counted, not shown or hidden, and left
  sitting inside whatever bake group it happened to be in. Suffix matching now
  accepts a trailing number, so `Cub_low2` is a low with the base `Cub`, gets
  its own `Bake_Cub` group and is tagged red for having no high. The leading
  underscore keeps this from over-reaching: `pillow2` is still not a low.
- **A bake group holding an unnamed object no longer reports itself healthy.**
  An object with no bake suffix is not ours to move, so it stays where it is -
  but the group is now tagged red and the run says which objects they are.
  Previously such a group stayed green while carrying geometry that would end
  up in the bake.

## 1.0.2

Fixes the "buttons are dead" report: a second panel was left on screen holding
no scriptJobs, so it never saw a selection change and its buttons stayed greyed
out no matter what was picked. It is now impossible to end up with two.

- **Exactly one panel, always.** Panels are tracked in a weak registry, and
  `show()` destroys any copy that did not come through it - a screenshot
  helper, a pasted snippet, a half-finished reload. Strays are hidden at once
  rather than on the next event-loop trip.
- **A panel that loses its subscriptions re-arms itself**, rather than sitting
  there looking normal and noticing nothing. Checked when the panel is shown,
  and every two seconds by a timer that only asks whether the jobs still exist
  - the scene is never rescanned on a timer.
- **A greyed-out button now says why.** A live hint under the primary buttons
  reports what QC Bake can see and what each button would do with it: nothing
  selected, one mesh when two are needed, which of two becomes the high, or a
  selection that holds no polygon meshes at all. The Visibility section says
  the same when nothing has been named yet.

Also added `tests/test_panel_maya.py`, covering all of the above plus the
1.0.1 fixes.

## 1.0.1

Fixes for four defects found the first time the tool met a real scene.

- **The panel could show one instance while the code held another.** `show()`
  was also the uiScript Maya runs when it rebuilds the workspaceControl, and
  it began by deleting that very control - so restoring the dock replaced the
  panel behind the artist's back, and any message on screen belonged to a
  discarded widget. `show()` now surfaces a live panel instead of rebuilding
  it, and only clears a control when nothing is alive inside it.
- **An exception in a command never reached the artist.** A PySide slot that
  raises prints to stdout and returns quietly, so the panel looked fine while
  the action had not run - and with no Script Editor open there was nothing to
  see at all. Commands now report failures in the status strip either way.
- **"Nothing to organize" was dressed up as an error.** Pressing a Collection
  Layout button before anything is renamed is a normal thing to do. It is now
  a warning that says to run Create Namepair first, and counts the meshes it
  looked at.
- **A mesh named `Low`, `High` or `Bake_Group` was adopted as that group**, and
  the rest of the scene parented inside the geometry. Transforms carrying a
  mesh are no longer treated as groups, and the clash is reported by name.

## 1.0.0

First release. A port of the QC Bake Blender extension 2.0.0 to Maya 2025,
with feature parity: namepair creation, high/low swapping, role visibility,
bake-group reduction with a reversible backup, and both collection layouts.

Behaviour that differs from the Blender original, by design:

- Settings are stored in optionVars rather than in the scene, so a naming
  convention follows the artist instead of the file.
- Show/hide runs through display layers, which leaves each object's own
  visibility attribute untouched.
- "Hide After Renaming" parks objects with `lodVisibility`, the viewport-only
  switch, matching what Blender's `hide_set` did.
- Collections became groups, under a single `Bake_Group` head.
- Group health is shown as a real outliner colour rather than one of Blender's
  eight fixed collection tags.

New, because Maya needed it:

- **Count Smooth Preview** - `polyEvaluate` does not see smooth mesh preview,
  so a high poly being viewed on "3" would otherwise read as its base cage and
  lose the high/low comparison.
- **Track Selection Order** - Maya does not record selection order unless asked
  to, so without it there is no "active object" to use as the low poly in group
  mode.
- Renames keep referenced objects inside their namespace, and every lookup uses
  full DAG paths so two same-named nodes in different groups are still reported
  as a clash.
- Node names are validated before use. Maya silently rewrites an illegal name
  rather than refusing it, so a rename that "worked" can still be wrong.
