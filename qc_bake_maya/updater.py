# QC Bake for Maya - updates
# --------------------------
# Maya has nothing like Blender's extension repositories: no index, no add-on
# manager, no version awareness. A .mod file is a path pointer and nothing
# more. So the update mechanism is ours to write, and this is it - the same
# shape Blender's is, aimed at a manifest published on GitHub Pages beside the
# release zip.
#
# The module is split so the decisions can be tested without a network, a
# filesystem or Maya:
#
#   parse_version / is_newer / validate_manifest / is_safe_url
#       pure, and where every rule about what is acceptable lives
#   check / download
#       network
#   stage / apply_update / rollback
#       filesystem
#
# Three rules the implementation holds to, because an updater that gets them
# wrong is worse than no updater at all:
#
#   * Nothing is ever applied without the artist asking for it. A tool that
#     replaces itself mid-shot is a tool nobody trusts again.
#   * HTTPS only, and the download is checked against the digest the manifest
#     declares. This code runs whatever it unpacks.
#   * The old version is kept until the new one is proven to import. Anything
#     that goes wrong puts the previous version back.

import hashlib
import json
import os
import re
import shutil
import tempfile
import zipfile

PACKAGE_NAME = "qc_bake_maya"
MANIFEST_NAME = "version.json"

# What a published manifest must look like:
#
#   {
#     "id": "qc_bake_maya",
#     "version": "1.1.0",
#     "download": "https://mutaform.github.io/qc-bake-maya/qc_bake_maya.zip",
#     "sha256": "<hex digest of the zip>",
#     "notes": "One line about what changed.",
#     "maya": ["2025"]
#   }
REQUIRED_KEYS = ("id", "version", "download")

_VERSION_PART = re.compile(r"^\d+$")


# -----------------------------------------------------------------------------
# Pure logic
# -----------------------------------------------------------------------------
def parse_version(text):
    """Return a version string as a tuple of ints, or None if it is not one.

    Deliberately strict. A manifest that says "latest" or "v1.2" is a mistake
    on the publishing side, and guessing what it meant is how an updater ends
    up downgrading someone.
    """
    if not isinstance(text, str):
        return None
    parts = text.strip().lstrip("vV").split(".")
    if not 1 <= len(parts) <= 4:
        return None
    if not all(_VERSION_PART.match(part) for part in parts):
        return None
    return tuple(int(part) for part in parts)


def is_newer(remote, local):
    """True when `remote` is a strictly newer version than `local`.

    Shorter versions compare as if padded with zeros, so 1.1 is newer than
    1.0.4 and the same as 1.1.0. Anything unparsable answers False: refusing
    to act on a version we do not understand is the safe direction.
    """
    remote_parts = parse_version(remote)
    local_parts = parse_version(local)
    if remote_parts is None or local_parts is None:
        return False
    length = max(len(remote_parts), len(local_parts))
    remote_parts += (0,) * (length - len(remote_parts))
    local_parts += (0,) * (length - len(local_parts))
    return remote_parts > local_parts


def is_safe_url(url):
    """True for an https URL we are willing to fetch code from.

    The scheme check is not a formality: this downloads an archive that will
    then be imported and executed, so a plain-http manifest is something an
    attacker on the network could rewrite.
    """
    return isinstance(url, str) and url.lower().startswith("https://")


def validate_manifest(data, expect_id=PACKAGE_NAME):
    """Return (manifest, None) or (None, reason) for a decoded manifest."""
    if not isinstance(data, dict):
        return None, "The manifest is not a JSON object."

    missing = [key for key in REQUIRED_KEYS if not data.get(key)]
    if missing:
        return None, "The manifest is missing: %s." % ", ".join(missing)

    if data["id"] != expect_id:
        return None, ("The manifest is for '%s', not '%s'."
                      % (data["id"], expect_id))

    if parse_version(data["version"]) is None:
        return None, ("'%s' is not a version number the updater understands."
                      % data["version"])

    if not is_safe_url(data["download"]):
        return None, "The download link is not an https URL."

    digest = data.get("sha256")
    if digest is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", str(digest)):
        return None, "The sha256 in the manifest is not a valid digest."

    return data, None


def find_package(root):
    """Return the package folder inside an extracted archive, or None.

    The release zip carries the package plus the installer and the docs, so
    the package is one level down. Searching for it rather than assuming a
    layout means the archive can be restructured without breaking updates in
    the field - which would be unfixable, since the broken updater is the one
    that has to fetch its own fix.
    """
    for current, dirs, files in os.walk(root):
        if os.path.basename(current) == PACKAGE_NAME and "__init__.py" in files:
            return current
    return None


def read_package_version(package_dir):
    """Read VERSION out of a package folder without importing it.

    Importing would mean executing the very code we are still deciding whether
    to trust, and would collide with the copy already loaded in this session.
    """
    init = os.path.join(package_dir, "__init__.py")
    try:
        with open(init, encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith("VERSION"):
                    continue
                digits = re.findall(r"\d+", line.split("=", 1)[1])
                if digits:
                    return ".".join(digits)
    except OSError:
        return None
    return None


# -----------------------------------------------------------------------------
# Network
# -----------------------------------------------------------------------------
def check(url, timeout=15):
    """Fetch and validate the published manifest.

    Returns (manifest, None) or (None, reason). Never raises: this runs on a
    timer in the background, and a studio proxy or an offline laptop must
    produce a quiet message rather than an error every time the panel opens.
    """
    import urllib.error
    import urllib.request

    if not is_safe_url(url):
        return None, "The update URL must be https."

    request = urllib.request.Request(
        url, headers={"User-Agent": "QCBakeMaya-Updater"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            # utf-8-sig, not utf-8: a manifest written by almost any Windows
            # tool carries a byte-order mark, and json.loads refuses one
            # outright. Tolerating it here costs nothing and stops a perfectly
            # good release from being unreachable.
            raw = response.read().decode("utf-8-sig", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None, ("No manifest published at that address yet (404): %s"
                          % url)
        return None, "The update server answered HTTP %s." % exc.code
    except Exception as exc:
        return None, "Could not reach the update server: %s" % exc

    try:
        data = json.loads(raw)
    except ValueError as exc:
        return None, "The manifest is not valid JSON: %s" % exc

    return validate_manifest(data)


def download(url, destination, expected_sha=None, timeout=120):
    """Fetch the release archive. Returns (path, None) or (None, reason)."""
    import urllib.request

    if not is_safe_url(url):
        return None, "The download URL must be https."

    request = urllib.request.Request(
        url, headers={"User-Agent": "QCBakeMaya-Updater"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except Exception as exc:
        return None, "Download failed: %s" % exc

    if expected_sha:
        actual = hashlib.sha256(payload).hexdigest()
        if actual.lower() != str(expected_sha).lower():
            return None, ("The download does not match the digest the manifest "
                          "declared, so it is not the file that was published. "
                          "Nothing was installed.")

    try:
        with open(destination, "wb") as handle:
            handle.write(payload)
    except OSError as exc:
        return None, "Could not write the download: %s" % exc

    return destination, None


# -----------------------------------------------------------------------------
# Filesystem
# -----------------------------------------------------------------------------
def stage(archive_path, work_dir, expect_version=None):
    """Unpack an archive and return (package_dir, None) or (None, reason).

    The archive is checked before anything on disk is touched: it must be a
    real zip, must contain the package, and - when the manifest promised a
    version - must actually contain that version. A manifest advertising 1.1.0
    over a zip still holding 1.0.4 would otherwise install silently and offer
    the same update forever.
    """
    if not zipfile.is_zipfile(archive_path):
        return None, "The downloaded file is not a zip archive."

    extract_dir = os.path.join(work_dir, "extracted")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            for name in archive.namelist():
                # A zip may not write outside the folder it is extracted into.
                target = os.path.normpath(os.path.join(extract_dir, name))
                if not target.startswith(os.path.normpath(extract_dir)):
                    return None, ("The archive tries to write outside its own "
                                  "folder (%s) and was rejected." % name)
            archive.extractall(extract_dir)
    except Exception as exc:
        return None, "Could not unpack the download: %s" % exc

    package_dir = find_package(extract_dir)
    if package_dir is None:
        return None, ("The archive does not contain a '%s' package."
                      % PACKAGE_NAME)

    found = read_package_version(package_dir)
    if expect_version and found != expect_version:
        return None, ("The manifest advertised %s but the archive contains %s."
                      % (expect_version, found or "no readable version"))

    return package_dir, None


def apply_update(new_package_dir, install_dir):
    """Swap a staged package into place. Returns (backup_path, None) or error.

    Done as two renames rather than a copy over the top, so the package is
    never half old and half new - a partially overwritten package would import
    and misbehave in ways far harder to diagnose than a clean failure. The
    displaced version is kept so rollback() can put it back.
    """
    target = os.path.join(install_dir, PACKAGE_NAME)
    backup = target + ".backup"
    incoming = target + ".incoming"

    for path in (backup, incoming):
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)

    try:
        shutil.copytree(new_package_dir, incoming)
    except OSError as exc:
        shutil.rmtree(incoming, ignore_errors=True)
        return None, "Could not stage the new version: %s" % exc

    try:
        if os.path.isdir(target):
            os.rename(target, backup)
    except OSError as exc:
        shutil.rmtree(incoming, ignore_errors=True)
        return None, ("Could not move the current version aside - something "
                      "still has a file open in it. Close Maya and update "
                      "again, or unpack the zip by hand. (%s)" % exc)

    try:
        os.rename(incoming, target)
    except OSError as exc:
        # Put the old one back before reporting: leaving no package at all
        # would take the tool out of the session entirely.
        if os.path.isdir(backup):
            os.rename(backup, target)
        shutil.rmtree(incoming, ignore_errors=True)
        return None, "Could not move the new version into place: %s" % exc

    return backup, None


def rollback(backup_path, install_dir):
    """Undo apply_update, putting the previous version back."""
    target = os.path.join(install_dir, PACKAGE_NAME)
    if not backup_path or not os.path.isdir(backup_path):
        return False
    shutil.rmtree(target, ignore_errors=True)
    try:
        os.rename(backup_path, target)
    except OSError:
        return False
    return True


def discard_backup(backup_path):
    """Remove a backup once the new version has proven itself."""
    if backup_path and os.path.isdir(backup_path):
        shutil.rmtree(backup_path, ignore_errors=True)


def work_directory():
    """A temporary folder for one update attempt."""
    return tempfile.mkdtemp(prefix="qcbake_update_")


def install_dir_for(package_file):
    """The folder holding the package, given the package's __file__.

    The .mod points Maya at this folder, so replacing what is inside it is the
    whole of an update - there is no second installed copy anywhere.
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(package_file)))


def perform_update(manifest, install_dir):
    """Download, verify, stage and swap in one release.

    Returns (backup_path, None) on success, or (None, reason). Nothing is
    touched inside install_dir until the download has been verified and
    unpacked successfully, so a failure at any earlier step leaves the
    installed version exactly as it was.
    """
    work_dir = work_directory()
    try:
        archive = os.path.join(work_dir, "release.zip")
        archive, error = download(manifest["download"], archive,
                                  manifest.get("sha256"))
        if error:
            return None, error

        package_dir, error = stage(archive, work_dir, manifest.get("version"))
        if error:
            return None, error

        return apply_update(package_dir, install_dir)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
