# QC Bake for Maya - reusable widgets
# -----------------------------------
# Blender gives an add-on collapsible sub-panels, property rows and a report
# line for free. Qt gives none of that, so the pieces the panel leans on are
# built once here and the panel module stays about layout rather than plumbing.

from PySide6 import QtCore, QtGui, QtWidgets

from .. import icons

ICON_SIZE = 16


def make_icon(name):
    """Return a QIcon for one of Maya's built-in resources, scaled to fit.

    Maya's resource set mixes 11x11 and 32x32 art, so leaving them at their
    native size produces a visibly ragged column of buttons.
    """
    pixmap = QtGui.QPixmap(icons.path(name))
    if pixmap.isNull():
        return QtGui.QIcon()
    if pixmap.width() != ICON_SIZE or pixmap.height() != ICON_SIZE:
        pixmap = pixmap.scaled(ICON_SIZE, ICON_SIZE,
                               QtCore.Qt.KeepAspectRatio,
                               QtCore.Qt.SmoothTransformation)
    return QtGui.QIcon(pixmap)


def blank_icon():
    """Return a transparent icon of the standard size.

    Swapping a button between an icon and no icon changes its width, so a row
    of them visibly twitches every time the state changes. A blank of the same
    size holds the layout still - the same reason Blender has a BLANK1 icon.
    """
    pixmap = QtGui.QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(QtCore.Qt.transparent)
    return QtGui.QIcon(pixmap)


class Section(QtWidgets.QWidget):
    """A collapsible section with a disclosure arrow, icon and title.

    Stands in for a Blender sub-panel: click the header to fold it away. The
    open/closed state is reported through `toggled` so the panel can remember
    it in an optionVar and give the artist the same layout next time.
    """

    toggled = QtCore.Signal(bool)

    def __init__(self, title, icon_name=None, expanded=True, parent=None):
        super(Section, self).__init__(parent)

        self._button = QtWidgets.QToolButton(self)
        self._button.setStyleSheet("QToolButton { border: none; }")
        self._button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self._button.setArrowType(QtCore.Qt.DownArrow)
        self._button.setText(" " + title)
        self._button.setCheckable(True)
        self._button.setChecked(expanded)
        self._button.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                                   QtWidgets.QSizePolicy.Fixed)
        self._button.clicked.connect(self._on_clicked)

        self._header_icon = QtWidgets.QLabel(self)
        if icon_name:
            self._header_icon.setPixmap(
                make_icon(icon_name).pixmap(ICON_SIZE, ICON_SIZE))

        header = QtWidgets.QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        header.addWidget(self._button, 1)
        header.addWidget(self._header_icon, 0)

        self._body = QtWidgets.QWidget(self)
        self._body_layout = QtWidgets.QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(14, 4, 2, 6)
        self._body_layout.setSpacing(4)
        self._body.setVisible(expanded)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addLayout(header)
        outer.addWidget(self._body)

        self._separator = QtWidgets.QFrame(self)
        self._separator.setFrameShape(QtWidgets.QFrame.HLine)
        self._separator.setFrameShadow(QtWidgets.QFrame.Sunken)
        outer.addWidget(self._separator)

    def body(self):
        """Return the layout section contents should be added to."""
        return self._body_layout

    def add_widget(self, widget):
        self._body_layout.addWidget(widget)
        return widget

    def add_layout(self, layout):
        self._body_layout.addLayout(layout)
        return layout

    def is_expanded(self):
        return self._button.isChecked()

    def set_expanded(self, expanded):
        self._button.setChecked(expanded)
        self._apply()

    def _on_clicked(self):
        self._apply()
        self.toggled.emit(self._button.isChecked())

    def _apply(self):
        expanded = self._button.isChecked()
        self._button.setArrowType(
            QtCore.Qt.DownArrow if expanded else QtCore.Qt.RightArrow)
        self._body.setVisible(expanded)


class IconCheckBox(QtWidgets.QWidget):
    """A checkbox with an icon between the box and its label.

    Mirrors the Blender panel's option rows, which put a small icon beside
    every toggle so the list can be scanned by shape rather than by reading
    every label.
    """

    toggled = QtCore.Signal(bool)

    def __init__(self, label, icon_name=None, tooltip="", parent=None):
        super(IconCheckBox, self).__init__(parent)

        self._box = QtWidgets.QCheckBox(self)
        self._box.toggled.connect(self.toggled.emit)

        icon_label = QtWidgets.QLabel(self)
        if icon_name:
            icon_label.setPixmap(make_icon(icon_name).pixmap(ICON_SIZE, ICON_SIZE))

        text = QtWidgets.QLabel(label, self)

        # Clicking anywhere on the row should toggle it, not just the 13-pixel
        # box, which is the behaviour a Blender row has.
        for widget in (icon_label, text):
            widget.setCursor(QtCore.Qt.PointingHandCursor)
            widget.mousePressEvent = self._forward_click

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self._box, 0)
        layout.addWidget(icon_label, 0)
        layout.addWidget(text, 0)
        layout.addStretch(1)

        if tooltip:
            self.setToolTip(tooltip)

    def _forward_click(self, event):
        self._box.toggle()

    def isChecked(self):
        return self._box.isChecked()

    def setChecked(self, value):
        was = self._box.blockSignals(True)
        self._box.setChecked(bool(value))
        self._box.blockSignals(was)


class StatusBar(QtWidgets.QLabel):
    """The panel's report line.

    Blender showed a command's outcome in the status bar and the info log.
    Here it lands in a coloured strip at the bottom of the panel, which is
    both more visible and does not disappear the moment the mouse moves.
    """

    COLORS = {
        'INFO': ("#2c3b2c", "#9fd39f"),
        'WARNING': ("#3d3626", "#e0c274"),
        'ERROR': ("#3d2727", "#e59191"),
    }

    def __init__(self, parent=None):
        super(StatusBar, self).__init__(parent)
        self.setWordWrap(True)
        self.setMargin(6)
        self.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.clear_message()

    def clear_message(self):
        self.setText("")
        self.setStyleSheet("")
        self.setVisible(False)

    def show_result(self, result):
        """Display a commands.Result."""
        self.show_message(result.level, result.message)

    def show_message(self, level, message):
        background, foreground = self.COLORS.get(level, self.COLORS['INFO'])
        self.setStyleSheet(
            "QLabel { background-color: %s; color: %s; border-radius: 3px; }"
            % (background, foreground))
        self.setText(message)
        self.setVisible(True)
