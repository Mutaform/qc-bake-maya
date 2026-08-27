"""Build the QC Bake shelf icon from qc_bake.svg.

    python icons_src/make_icon.py

Writes qc_bake_32/64/128.png into qc_bake_maya/resources/ - inside the
package, deliberately, so the icon travels both into the release archive and
through an update, which swaps the package folder and nothing else.

Two things about how this renders, both learned the hard way:

QtSvg is not usable here. It implements SVG Tiny, which has no <mask>: it
ignores the element and then draws the mask's own contents as if they were
artwork. On this file that flooded a green path across the QC BAKE text and
left a white rectangle behind it. Verified by rendering, not assumed.

So Edge does the drawing - a browser engine implements the whole spec, and
Edge ships with Windows. It is asked for one large render, which is then
resampled down. Asking it for each size directly was unreliable: some sizes
came back correct and others clipped to a band, apparently a race between the
screenshot and layout. One render plus deterministic resampling has no such
lottery, and downsampling from 512 gives a better 32 than rendering 32 would.

Windows only, and must be run from PowerShell or cmd. Launched from a Git Bash
environment, Edge exits 0 and silently writes nothing.

Needs Pillow.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SOURCE = os.path.join(HERE, "qc_bake.svg")
DEST = os.path.join(REPO, "qc_bake_maya", "resources")

NAME = "qc_bake"
# 32 is the size a Maya shelf button actually draws; the other two are for
# high-DPI displays.
SIZES = (128, 64, 32)
# Rendered once at this size, then resampled. Large enough that a 32px
# downsample is clean, and a size Edge returns whole.
MASTER = 512

EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def find_browser():
    for path in EDGE_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def sized_svg(source, size):
    """Return the SVG with its root sized, and its contents untouched.

    Only the first <svg ...> is rewritten. Searching and replacing
    width="32" height="32" would also hit the background rect, which carries
    the same numbers - that collapses the plate and renders a black
    silhouette on transparency.
    """
    match = re.search(r"<svg\b[^>]*>", source)
    if not match:
        raise ValueError("no <svg> element in the source")
    view_box = re.search(r'viewBox="([^"]+)"', match.group(0))
    if not view_box:
        raise ValueError("the <svg> element has no viewBox to scale by")
    root = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s" '
            'width="%d" height="%d">' % (view_box.group(1), size, size))
    return source[:match.start()] + root + source[match.end():]


def render_master(size=MASTER):
    """Render the source once, large. Returns the path to a temporary PNG."""
    browser = find_browser()
    if browser is None:
        raise RuntimeError("no Edge or Chrome found to render the SVG")

    source = open(SOURCE, encoding="utf-8").read()
    work = tempfile.mkdtemp(prefix="qcbake_icon_")
    svg = os.path.join(work, "icon.svg")
    with open(svg, "w", encoding="utf-8") as handle:
        handle.write(sized_svg(source, size))

    shot = os.path.join(work, "shot.png")
    subprocess.run(
        [browser,
         "--headless=new",
         "--disable-gpu",
         "--no-sandbox",
         "--hide-scrollbars",
         "--force-device-scale-factor=1",
         "--default-background-color=00000000",   # transparent
         # Without a time budget the screenshot can be taken before the page
         # paints, and the browser then writes no file at all.
         "--virtual-time-budget=4000",
         "--screenshot=%s" % shot,
         "--window-size=%d,%d" % (size, size),
         "--user-data-dir=%s" % os.path.join(work, "profile"),
         svg],
        capture_output=True, text=True, timeout=180)

    if not os.path.isfile(shot):
        shutil.rmtree(work, ignore_errors=True)
        raise RuntimeError("the browser produced no screenshot")
    return shot, work


def opaque_share(image):
    """How much of the image is drawn. A clipped render is mostly empty."""
    pixels = list(image.getdata())
    drawn = sum(1 for p in pixels if p[3] > 200)
    return 100.0 * drawn / len(pixels)


def build():
    from PIL import Image

    shot, work = render_master()
    try:
        master = Image.open(shot).convert("RGBA")

        # The badge fills its own viewBox, so a correct render is almost all
        # opaque. Anything less means the browser handed back a clipped
        # frame, which has happened - better to fail loudly than to ship it.
        share = opaque_share(master)
        if share < 85.0:
            raise RuntimeError(
                "the render came back %.0f%% drawn, so it is clipped; "
                "try again or use a different MASTER size" % share)

        os.makedirs(DEST, exist_ok=True)
        written = []
        for size in SIZES:
            path = os.path.join(DEST, "%s_%d.png" % (NAME, size))
            master.resize((size, size), Image.LANCZOS).save(path)
            written.append(path)
        return master.size, share, written
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    try:
        size, share, written = build()
        print("rendered %dx%d, %.0f%% drawn" % (size[0], size[1], share))
        for path in written:
            print("wrote", path)
    except Exception as exc:
        print("FAILED: %s" % exc)
        sys.exit(1)
