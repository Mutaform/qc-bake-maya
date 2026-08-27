"""Build the QC Bake shelf icon.

One icon: the flame, no logo. Run it inside Maya, which is where Qt already
is:

    exec(open(r"...\\icons_src\\make_icon.py").read(), {})

The PNGs are written into qc_bake_maya/resources/ - inside the package,
deliberately. An asset kept beside the package instead of in it does not
travel: it is missed by the release build, and worse, never replaced by an
update, because an update swaps the package folder and nothing else. This
source folder stays outside the package, since only whoever redraws the icon
needs it.

32 is the size a Maya shelf button actually draws; the larger two are there
for high-DPI displays.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ICONS = os.path.join(REPO, "qc_bake_maya", "resources")
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import flame  # noqa: E402

NAME = "qc_bake"
SIZES = (32, 64, 128)


def build_svg():
    """The flame on its own, in a 64x64 box with a little breathing room."""
    body = flame.flame(scale=0.64, dx=0, dy=0)
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
            'width="64" height="64">%s</svg>' % body)


def write_svg():
    path = os.path.join(HERE, NAME + ".svg")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(build_svg())
    return path


def render(svg_path=None):
    """Render the PNGs. Needs Qt, so this is the part that wants Maya."""
    from PySide6 import QtCore, QtGui, QtSvg

    svg_path = svg_path or write_svg()
    written = []
    for size in SIZES:
        image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        QtSvg.QSvgRenderer(svg_path).render(painter)
        painter.end()
        target = os.path.join(ICONS, "%s_%d.png" % (NAME, size))
        image.save(target)
        written.append(target)
    return written


if __name__ == "__main__":
    write_svg()
    try:
        for path in render():
            print("wrote", path)
    except ImportError:
        print("wrote the SVG; run this inside Maya to render the PNGs")
