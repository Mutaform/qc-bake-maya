"""Build the QC Bake shelf icon from qc_bake_source.png.

    python icons_src/make_icon.py

Writes qc_bake_32/64/128.png into qc_bake_maya/resources/ - inside the
package, deliberately, so the icon travels both into the release archive and
through an update, which swaps the package folder and nothing else.

The source art is a rounded badge exported flat: RGB with no alpha, and the
corners filled with the design tool's own canvas grey. Dropped straight onto
Maya's lighter shelf, that grey reads as four dark wedges around the badge.

So the alpha is rebuilt here rather than taken from the file. Not by making
the background colour transparent - that would also punch holes anywhere
inside the badge that happens to share it - but by measuring the badge's
corner radius and drawing a clean anti-aliased rounded rectangle. The edge
comes out better than the flattened original's, too.

Needs Pillow. Nothing else, and not Maya.
"""

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SOURCE = os.path.join(HERE, "qc_bake_source.png")
DEST = os.path.join(REPO, "qc_bake_maya", "resources")

NAME = "qc_bake"
# 32 is the size a Maya shelf button actually draws. The other two are there
# for high-DPI displays.
SIZES = (128, 64, 32)
SUPERSAMPLE = 8


def measure_radius(img, background, tolerance=24):
    """Corner radius of the badge, read off its top row.

    A rounded rectangle's top row starts at x = r, so the run of background
    pixels before the shape begins is the radius.
    """
    width = img.size[0]
    for x in range(width):
        pixel = img.getpixel((x, 0))
        if sum(abs(a - b) for a, b in zip(pixel, background)) > tolerance:
            return x
    return 0


def build():
    source = Image.open(SOURCE).convert("RGB")
    width, height = source.size
    background = source.getpixel((0, 0))
    radius = measure_radius(source, background)

    # Drawn large and shrunk down, so the curve is smooth rather than
    # stair-stepped.
    mask = Image.new("L", (width * SUPERSAMPLE, height * SUPERSAMPLE), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, width * SUPERSAMPLE - 1, height * SUPERSAMPLE - 1),
        radius=radius * SUPERSAMPLE, fill=255)
    mask = mask.resize((width, height), Image.LANCZOS)

    badge = source.copy()
    badge.putalpha(mask)

    os.makedirs(DEST, exist_ok=True)
    written = []
    for size in SIZES:
        path = os.path.join(DEST, "%s_%d.png" % (NAME, size))
        badge.resize((size, size), Image.LANCZOS).save(path)
        written.append(path)
    return radius, background, written


if __name__ == "__main__":
    radius, background, written = build()
    print("source corner radius %d px, background %s" % (radius, background))
    for path in written:
        print("wrote", path)
