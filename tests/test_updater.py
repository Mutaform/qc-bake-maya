# QC Bake for Maya - updater tests
# --------------------------------
# The updater downloads an archive and then imports what is inside it, so its
# rules about what to accept are the only thing standing between a published
# mistake and a broken tool in the field - or worse. None of this needs Maya:
#
#     python tests/test_updater.py

import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from qc_bake_maya import updater  # noqa: E402

FAILURES = []


def check(label, got, want):
    if got != want:
        FAILURES.append("%s\n     got:  %r\n     want: %r" % (label, got, want))


def check_rejected(label, result):
    manifest, error = result
    if manifest is not None or not error:
        FAILURES.append("%s\n     was accepted, should have been refused" % label)


# -- version parsing ---------------------------------------------------------
check("plain version", updater.parse_version("1.2.3"), (1, 2, 3))
check("leading v tolerated", updater.parse_version("v1.2.3"), (1, 2, 3))
check("two parts", updater.parse_version("1.2"), (1, 2))
check("not a version", updater.parse_version("latest"), None)
check("partly a version", updater.parse_version("1.2.x"), None)
check("empty", updater.parse_version(""), None)
check("not a string", updater.parse_version(None), None)

check("newer patch", updater.is_newer("1.0.5", "1.0.4"), True)
check("newer minor", updater.is_newer("1.1.0", "1.0.9"), True)
check("same is not newer", updater.is_newer("1.0.4", "1.0.4"), False)
check("older is not newer", updater.is_newer("1.0.3", "1.0.4"), False)
# Shorter versions pad with zeros, so 1.1 and 1.1.0 are the same release.
check("short form equals long", updater.is_newer("1.1", "1.1.0"), False)
check("short form still compares", updater.is_newer("1.1", "1.0.9"), True)
# Numeric, not lexical: "10" beats "9", which a string compare gets backwards.
check("double digits compare numerically",
      updater.is_newer("1.10.0", "1.9.0"), True)
# An unparsable version must never trigger an update.
check("garbage never triggers", updater.is_newer("latest", "1.0.4"), False)
check("garbage local never triggers", updater.is_newer("2.0.0", "dev"), False)

# -- url safety --------------------------------------------------------------
check("https accepted", updater.is_safe_url("https://example.com/x.json"), True)
check("http refused", updater.is_safe_url("http://example.com/x.json"), False)
check("file refused", updater.is_safe_url("file:///c:/x.json"), False)
check("nonsense refused", updater.is_safe_url("example.com"), False)
check("None refused", updater.is_safe_url(None), False)

# -- manifest validation -----------------------------------------------------
GOOD = {
    "id": "qc_bake_maya",
    "version": "1.1.0",
    "download": "https://mutaform.github.io/qc-bake-maya/qc_bake_maya.zip",
    "sha256": "a" * 64,
    "notes": "Something changed.",
}
manifest, error = updater.validate_manifest(dict(GOOD))
check("a good manifest is accepted", error, None)
check("and comes back whole", manifest["version"], "1.1.0")

check_rejected("not an object", updater.validate_manifest([1, 2, 3]))
for key in ("id", "version", "download"):
    broken = dict(GOOD)
    del broken[key]
    check_rejected("missing %s" % key, updater.validate_manifest(broken))

wrong_id = dict(GOOD, id="something_else")
check_rejected("a manifest for another tool",
               updater.validate_manifest(wrong_id))

# The important one: an http download link would let anyone on the network
# swap the code this tool is about to execute.
insecure = dict(GOOD, download="http://mutaform.github.io/x.zip")
check_rejected("plain http download", updater.validate_manifest(insecure))

check_rejected("unparsable version",
               updater.validate_manifest(dict(GOOD, version="latest")))
check_rejected("malformed digest",
               updater.validate_manifest(dict(GOOD, sha256="nope")))

# A manifest with no digest at all is allowed - it just cannot be verified.
no_digest = dict(GOOD)
del no_digest["sha256"]
manifest, error = updater.validate_manifest(no_digest)
check("digest is optional", error, None)


# -- archive handling --------------------------------------------------------
def make_package(root, version="1.1.0", package=updater.PACKAGE_NAME):
    """Write a minimal package tree and return its folder."""
    package_dir = os.path.join(root, "release", package)
    os.makedirs(package_dir)
    with open(os.path.join(package_dir, "__init__.py"), "w",
              encoding="utf-8") as handle:
        handle.write("VERSION = (%s)\n" % ", ".join(version.split(".")))
        handle.write('VERSION_STRING = "%s"\n' % version)
    return package_dir


def zip_dir(folder, archive_path):
    with zipfile.ZipFile(archive_path, "w") as archive:
        base = os.path.dirname(folder)
        for current, _dirs, files in os.walk(folder):
            for name in files:
                full = os.path.join(current, name)
                archive.write(full, os.path.relpath(full, base))
    return archive_path


work = tempfile.mkdtemp(prefix="qcbake_test_")
try:
    package_dir = make_package(work)
    check("version read without importing",
          updater.read_package_version(package_dir), "1.1.0")

    archive = zip_dir(package_dir, os.path.join(work, "release.zip"))

    staged, error = updater.stage(archive, os.path.join(work, "w1"), "1.1.0")
    check("a good archive stages", error, None)
    check("and the package is found",
          os.path.basename(staged), updater.PACKAGE_NAME)

    # A manifest promising a version the archive does not contain would
    # install silently and then offer the same update forever.
    staged, error = updater.stage(archive, os.path.join(work, "w2"), "9.9.9")
    check("a version mismatch is caught", staged, None)

    # Not a zip at all.
    junk = os.path.join(work, "junk.zip")
    with open(junk, "wb") as handle:
        handle.write(b"this is not a zip")
    staged, error = updater.stage(junk, os.path.join(work, "w3"))
    check("a non-zip is refused", staged, None)

    # A zip with no package in it.
    empty_dir = os.path.join(work, "empty", "something_else")
    os.makedirs(empty_dir)
    with open(os.path.join(empty_dir, "readme.txt"), "w") as handle:
        handle.write("nothing here")
    other = zip_dir(empty_dir, os.path.join(work, "other.zip"))
    staged, error = updater.stage(other, os.path.join(work, "w4"))
    check("an archive without the package is refused", staged, None)

    # A zip that tries to escape the folder it is extracted into.
    evil = os.path.join(work, "evil.zip")
    with zipfile.ZipFile(evil, "w") as evil_zip:
        evil_zip.writestr("../escaped.txt", "should never be written")
    staged, error = updater.stage(evil, os.path.join(work, "w5"))
    check("a path-traversing archive is refused", staged, None)
    check("and nothing escaped",
          os.path.exists(os.path.join(work, "escaped.txt")), False)

    # -- swap and rollback ---------------------------------------------------
    install_dir = os.path.join(work, "install")
    live = os.path.join(install_dir, updater.PACKAGE_NAME)
    os.makedirs(live)
    with open(os.path.join(live, "__init__.py"), "w", encoding="utf-8") as h:
        h.write("VERSION = (1, 0, 4)\n")
    with open(os.path.join(live, "marker_old.txt"), "w") as handle:
        handle.write("old")

    new_dir = make_package(os.path.join(work, "next"), "1.1.0")
    backup, error = updater.apply_update(new_dir, install_dir)
    check("the swap succeeds", error, None)
    check("the new version is in place",
          updater.read_package_version(live), "1.1.0")
    check("the old version is kept", os.path.isdir(backup), True)
    # A swap, not an overwrite: nothing of the old version may survive inside
    # the new one, or the package would be half of each.
    check("no leftovers from the old version",
          os.path.exists(os.path.join(live, "marker_old.txt")), False)

    check("rollback restores", updater.rollback(backup, install_dir), True)
    check("the old version is back",
          updater.read_package_version(live), "1.0.4")
    check("and its files with it",
          os.path.exists(os.path.join(live, "marker_old.txt")), True)
    check("the backup is consumed", os.path.isdir(backup), False)

    backup, error = updater.apply_update(new_dir, install_dir)
    check("a second swap works", error, None)
    updater.discard_backup(backup)
    check("the backup can be dropped", os.path.isdir(backup), False)

    # -- digest verification -------------------------------------------------
    payload = open(archive, "rb").read()
    digest = hashlib.sha256(payload).hexdigest()
    check("digest of the archive", len(digest), 64)
    check("a tampered payload gives a different digest",
          hashlib.sha256(payload + b"x").hexdigest() == digest, False)
finally:
    shutil.rmtree(work, ignore_errors=True)


# -- against the real build --------------------------------------------------
# The synthetic archives above prove the rules. This proves the rules match
# what the build actually produces: the release zip nests the package one level
# down, beside the installer and the docs, and a stage() that assumed a flat
# layout would pass every test above and then fail on the first real update.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The build writes into the repository on CI and into the Dev folder beside it
# when run by hand, so both are looked at rather than assumed.
built = []
for _base in (ROOT, os.path.join(os.path.dirname(ROOT), "Dev")):
    _dist = os.path.join(_base, "dist")
    if os.path.isdir(_dist):
        built.extend(os.path.join(_dist, n) for n in sorted(os.listdir(_dist))
                     if n.endswith(".zip"))
built.sort(key=os.path.getmtime)

if built:
    archive = built[-1]

    # Everything a first install needs must be in the archive. The shelf icon
    # was not, once: it lived beside the package instead of inside it, so the
    # build skipped it and every fresh install silently wore a stock Maya icon
    # - and an update, which swaps only the package folder, would never have
    # fixed it either.
    with zipfile.ZipFile(archive) as handle:
        entries = handle.namelist()
    for needed in ("qc_bake_maya/__init__.py",
                   "qc_bake_maya/resources/qc_bake_32.png",
                   "install/install.py"):
        check("the release zip ships %s" % needed,
              any(name.endswith(needed) for name in entries), True)

    work = tempfile.mkdtemp(prefix="qcbake_real_")
    try:
        staged, error = updater.stage(archive, work)
        check("the real release zip stages", error, None)
        if staged:
            check("and yields the package",
                  os.path.basename(staged), updater.PACKAGE_NAME)
            check("with a readable version",
                  updater.parse_version(
                      updater.read_package_version(staged)) is not None, True)

            # The version in the archive must match the manifest the same
            # build wrote, or the update installs and re-offers itself.
            manifest_path = os.path.join(os.path.dirname(archive), "..", "pages", "version.json")
            if os.path.isfile(manifest_path):
                raw = open(manifest_path, "rb").read()
                # The published file must be plain UTF-8. A byte-order mark
                # makes json.loads refuse it outright, so a manifest written
                # the obvious way on Windows is unreadable by the very updater
                # it feeds. This check caught exactly that.
                check("the manifest carries no BOM",
                      raw.startswith(b"\xef\xbb\xbf"), False)
                published = json.loads(raw.decode("utf-8-sig"))
                manifest, error = updater.validate_manifest(published)
                check("the published manifest validates", error, None)
                check("and its version matches the archive",
                      published.get("version"),
                      updater.read_package_version(staged))
    finally:
        shutil.rmtree(work, ignore_errors=True)
else:
    print("note: no dist/*.zip yet, skipped the real-archive checks")


if FAILURES:
    print("FAILED (%d)\n" % len(FAILURES))
    for failure in FAILURES:
        print("  - " + failure)
    sys.exit(1)
print("all updater tests passed")
