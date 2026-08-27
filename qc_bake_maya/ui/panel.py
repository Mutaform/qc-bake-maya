# QC Bake for Maya - the panel
# ----------------------------
# A dockable PySide6 widget laid out to match the Blender add-on's N-panel:
# the two primary actions up top, then Visibility, Utilities, Naming and
# Options as collapsible sections in that order.
#
# The one thing that could not be carried across is how the panel stays
# current. Blender re-runs a panel's draw() constantly, so its buttons always
# reflected the scene for free. Qt draws once and then waits, so the state has
# to be pushed in - which is what the scriptJobs at the bottom of this module
# are for. They are also why the panel is careful about its own lifetime: a
# scriptJob that outlives the widget it calls into will bring Maya down.

import traceback
import weakref

import maya.cmds as cmds
import shiboken6
from maya.app.general.mayaMixin import MayaQWidgetDockableMixin
from PySide6 import QtCore, QtWidgets

from .. import VERSION_STRING, commands, core, icons, prefs, scene, updater
from ..commands import reduce as reduce_cmd
from .widgets import (
    ICON_SIZE, IconCheckBox, Section, StatusBar, blank_icon, make_icon,
)

OBJECT_NAME = "QCBakeMayaPanel"
WORKSPACE_CONTROL = OBJECT_NAME + "WorkspaceControl"
TITLE = "QC Bake"

# Events that can change which objects hold which role, and so require the
# panel to re-read the scene. SelectionChanged is deliberately not among them:
# selecting something changes nothing about naming, and a full rescan on every
# click would be felt in a heavy scene.
# The Blender panel drew the active Show/Hide button depressed, which is how
# an artist reads a role's state at a glance. Maya's default style renders a
# checked QPushButton almost identically to an unchecked one, so the state has
# to be painted in explicitly.
CHECKED_BUTTON_STYLE = """
QPushButton:checked {
    background-color: #4c7a99;
    color: #ffffff;
    border: 1px solid #6ea3c4;
}
QPushButton:checked:hover { background-color: #588aad; }
"""

SCENE_EVENTS = (
    "NameChanged",
    "DagObjectCreated",
    "deleteAll",
    "SceneOpened",
    "NewSceneOpened",
    "SceneImported",
    "Undo",
    "Redo",
    "displayLayerChange",
    "displayLayerVisibilityChanged",
)


class UpdateCheck(QtCore.QObject):
    """Fetches the update manifest off the main thread.

    The check must never be able to stall Maya. A studio proxy that black-holes
    the request would otherwise freeze the whole application for the length of
    the timeout, every time the panel opened - so the request runs on a plain
    worker thread that touches nothing but urllib, and the answer comes back
    through a Qt signal, which Qt delivers on the main thread. No maya.cmds is
    called from the thread, because none of it is thread-safe.
    """

    finished = QtCore.Signal(object, object)   # manifest, error

    def __init__(self, url, parent=None):
        super(UpdateCheck, self).__init__(parent)
        self._url = url
        self._thread = None

    def start(self):
        import threading

        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            manifest, error = updater.check(self._url)
        except Exception as exc:                 # never kill the worker
            manifest, error = None, "Update check failed: %s" % exc
        self.finished.emit(manifest, error)


class QCBakePanel(MayaQWidgetDockableMixin, QtWidgets.QWidget):
    """The QC Bake tool window."""

    # Every panel ever built, weakly. Maya can destroy a widget without Python
    # noticing, and a panel that survives with no scriptJobs is worse than no
    # panel at all - it looks alive but never learns that the selection
    # changed, so its buttons stay greyed out forever. show() uses this to
    # guarantee exactly one live panel.
    _instances = []

    def __init__(self, parent=None):
        super(QCBakePanel, self).__init__(parent=parent)
        self.setObjectName(OBJECT_NAME)
        self.setWindowTitle(TITLE)
        self.setMinimumWidth(268)

        self.settings = prefs.load()
        self._refreshing = False
        # Maya can show a dockable widget before __init__ returns, and
        # showEvent refreshes - which would reach for widgets that do not
        # exist yet. Nothing refreshes until the layout is actually built.
        self._ready = False

        self._build()
        self._ready = True
        self._load_settings()
        self.refresh()
        self._refresh_selection()

        # Subscriptions are deliberately NOT installed here. They are wired to
        # whichever panel the module currently holds, and that reference is
        # only assigned once this constructor returns - so a job installed now
        # would, for the length of that window, see no panel at all and shut
        # itself down. show() installs them once the panel is reachable.

        # Last line of defence. showEvent re-arms a panel that lost its
        # subscriptions, but only when it is shown again - and Maya can kill
        # non-protected scriptJobs while the panel sits there visible. This
        # notices within a couple of seconds. It only asks Maya whether the
        # jobs still exist, so it costs nothing measurable; the scene is never
        # rescanned on a timer.
        self._health_timer = QtCore.QTimer(self)
        self._health_timer.setInterval(2000)
        self._health_timer.timeout.connect(self._check_health)
        self._health_timer.start()

        QCBakePanel._instances.append(weakref.ref(self))

    # -- construction --------------------------------------------------------
    def _build(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        root.addLayout(self._build_header())
        root.addWidget(self._build_update_banner())
        root.addLayout(self._build_primary())

        # Section order matches the Blender panel: Visibility, Utilities,
        # Naming, Options.
        self.sec_visibility = self._add_section(
            root, "visibility", "Visibility", icons.ICON_VISIBILITY, False)
        self._build_visibility(self.sec_visibility)

        self.sec_utilities = self._add_section(
            root, "utilities", "Utilities", icons.ICON_UTILITIES, False)
        self._build_utilities(self.sec_utilities)

        self.sec_naming = self._add_section(
            root, "naming", "Naming", icons.ICON_NAMING, True)
        self._build_naming(self.sec_naming)

        self.sec_options = self._add_section(
            root, "options", "Options", icons.ICON_OPTIONS, False)
        self._build_options(self.sec_options)

        root.addStretch(1)

        self.status = StatusBar(self)
        root.addWidget(self.status)

    def _build_header(self):
        layout = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("QC Bake by Mutaform Studio", self)
        title.setStyleSheet("QLabel { font-weight: bold; }")
        version = QtWidgets.QLabel("ver %s" % VERSION_STRING, self)
        version.setStyleSheet("QLabel { color: #888888; }")
        layout.addWidget(title, 1)
        layout.addWidget(version, 0)
        return layout

    def _build_update_banner(self):
        """A strip that appears only when a newer release has been published.

        Deliberately not a popup. An update is news, not an interruption - it
        waits at the top of the panel until the artist has a moment, and until
        then the tool behaves exactly as it did.
        """
        self.update_banner = QtWidgets.QWidget(self)
        self.update_banner.setStyleSheet(
            "QWidget { background-color: #2b3a4a; border-radius: 3px; }")

        self.update_label = QtWidgets.QLabel(self.update_banner)
        self.update_label.setWordWrap(True)
        self.update_label.setStyleSheet("QLabel { color: #a9cbe8; }")

        self.btn_update = QtWidgets.QPushButton("Install", self.update_banner)
        self.btn_update.setMinimumWidth(96)
        self.btn_update.setMinimumHeight(26)
        self.btn_update.setStyleSheet(
            "QPushButton { background-color: #3d6a8c; color: #f0f6fb;"
            " border: 1px solid #5a89ad; border-radius: 3px; font-weight: bold; }"
            "QPushButton:hover { background-color: #4a7da3; }"
            "QPushButton:disabled { background-color: #3a4650; color: #7f8b95; }")
        self.btn_update.setToolTip(
            "Download the new version, replace this one and reload.\n"
            "The current version is kept until the new one has loaded.")
        self.btn_update.clicked.connect(self._on_install_update)

        self.btn_skip_update = QtWidgets.QPushButton("Skip",
                                                     self.update_banner)
        self.btn_skip_update.setMinimumWidth(72)
        self.btn_skip_update.setMinimumHeight(26)
        self.btn_skip_update.setStyleSheet(
            "QPushButton { background-color: transparent; color: #9fb4c6;"
            " border: 1px solid #4a5f70; border-radius: 3px; }"
            "QPushButton:hover { color: #cfe0ee; border-color: #6d8397; }")
        self.btn_skip_update.setToolTip(
            "Stop offering this particular version. A later one will still "
            "be announced.")
        self.btn_skip_update.clicked.connect(self._on_skip_update)

        # Opposite corners, with the whole width between them. Side by side,
        # the two are one slip apart - and they do very different things: one
        # replaces the running tool, the other silently hides the offer. The
        # weight differs too, so the one that acts looks like the one that
        # acts.
        buttons = QtWidgets.QHBoxLayout()
        buttons.setContentsMargins(0, 2, 0, 0)
        buttons.addWidget(self.btn_skip_update, 0, QtCore.Qt.AlignLeft)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_update, 0, QtCore.Qt.AlignRight)

        layout = QtWidgets.QVBoxLayout(self.update_banner)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        layout.addWidget(self.update_label)
        layout.addLayout(buttons)

        self.update_banner.setVisible(False)
        self._pending_update = None
        self._update_check = None
        return self.update_banner

    def _build_primary(self):
        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(4)

        self.btn_create = QtWidgets.QPushButton(
            make_icon(icons.ICON_CREATE), "  Create Namepair", self)
        self.btn_create.setMinimumHeight(34)
        self.btn_create.setStyleSheet("QPushButton { font-weight: bold; }")
        self.btn_create.setToolTip(
            "Rename the selected meshes into a high/low baking namepair.")
        self.btn_create.clicked.connect(self._on_create)

        self.btn_swap = QtWidgets.QPushButton(
            make_icon(icons.ICON_SWAP), "  Swap High / Low", self)
        self.btn_swap.setMinimumHeight(26)
        self.btn_swap.setToolTip(
            "Swap the low and high roles of the two selected objects.")
        self.btn_swap.clicked.connect(self._on_swap)

        # A greyed-out button is an answer with the reason left out. Blender
        # could get away with it because hovering a dead operator still shows
        # its tooltip; here the artist is left staring at a dead control with
        # nothing to go on. This line always says what the tool can see and
        # what it wants.
        self.selection_hint = QtWidgets.QLabel(self)
        self.selection_hint.setWordWrap(True)
        self.selection_hint.setStyleSheet("QLabel { color: #9a9a9a; }")

        layout.addWidget(self.btn_create)
        layout.addWidget(self.btn_swap)
        layout.addWidget(self.selection_hint)
        return layout

    def _add_section(self, layout, key, title, icon, default_open):
        section = Section(title, icon, prefs.ui_flag(key, default_open), self)
        section.toggled.connect(
            lambda state, name=key: prefs.set_ui_flag(name, state))
        layout.addWidget(section)
        return section

    # -- Visibility ----------------------------------------------------------
    def _build_visibility(self, section):
        self.visibility_rows = {}
        for group, label, icon in (
                ('HIGH', "High", icons.ICON_HIGH),
                ('LOW', "Low", icons.ICON_LOW),
                ('CAGE', "Cage", icons.ICON_CAGE)):
            section.add_layout(self._visibility_row(group, label, icon))

        line = QtWidgets.QFrame(self)
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        section.add_widget(line)
        section.add_layout(self._visibility_row('ALL', "All", icons.ICON_ALL))

        clear = QtWidgets.QPushButton("Clear QC Bake Layers", self)
        clear.setToolTip(
            "Remove the QC Bake display layers and reveal every object.\n"
            "Names and groups are left exactly as they are.")
        clear.clicked.connect(self._on_clear_visibility)
        section.add_widget(clear)

        # Shown only while every row is dead, so the greyed-out state has a
        # stated reason instead of looking broken.
        self.visibility_hint = QtWidgets.QLabel(
            "These rows act on objects that already carry the suffixes. "
            "Run Create Namepair first.", self)
        self.visibility_hint.setWordWrap(True)
        self.visibility_hint.setStyleSheet("QLabel { color: #9a9a9a; }")
        section.add_widget(self.visibility_hint)

    def _visibility_row(self, group, label, icon):
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)

        glyph = QtWidgets.QLabel(self)
        glyph.setPixmap(make_icon(icon).pixmap(ICON_SIZE, ICON_SIZE))

        text = QtWidgets.QLabel(label, self)
        text.setMinimumWidth(42)

        show = QtWidgets.QPushButton("Show", self)
        hide = QtWidgets.QPushButton("Hide", self)
        for button in (show, hide):
            button.setCheckable(True)
            button.setMinimumWidth(62)
            # Maya's default style barely distinguishes a checked QPushButton
            # from an unchecked one, which would leave these rows unable to
            # answer the only question they exist to answer.
            button.setStyleSheet(CHECKED_BUTTON_STYLE)
        show.clicked.connect(lambda _=False, g=group: self._on_visibility(g, True))
        hide.clicked.connect(lambda _=False, g=group: self._on_visibility(g, False))

        row.addWidget(glyph, 0)
        row.addWidget(text, 0)
        row.addStretch(1)
        row.addWidget(show, 0)
        row.addWidget(hide, 0)

        self.visibility_rows[group] = (show, hide)
        return row

    # -- Utilities -----------------------------------------------------------
    def _build_utilities(self, section):
        section.add_widget(self._heading("Group Reduction"))

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(QtCore.Qt.AlignRight)

        self.field_prefix = QtWidgets.QLineEdit(self)
        self.field_prefix.setToolTip(
            "Base name given to each merged bake group.")
        self.field_prefix.editingFinished.connect(self._on_prefix_changed)

        self.field_gap = QtWidgets.QDoubleSpinBox(self)
        self.field_gap.setDecimals(3)
        self.field_gap.setRange(0.0, 10000.0)
        self.field_gap.setSingleStep(0.05)
        self.field_gap.setToolTip(
            "How far apart two assets must be before they may share one bake\n"
            "group. Anything closer risks rays from one asset striking the\n"
            "other's high poly.")
        self.field_gap.valueChanged.connect(self._on_gap_changed)

        form.addRow("Prefix", self.field_prefix)
        form.addRow("Minimum Gap", self.field_gap)
        section.add_layout(form)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(4)
        self.btn_reduce = QtWidgets.QPushButton(
            make_icon(icons.ICON_UTIL_REDUCE), "  Reduce Bake Groups", self)
        self.btn_reduce.setMinimumHeight(28)
        self.btn_reduce.setToolTip(
            "Merge namepairs that are far enough apart into fewer bake groups.")
        self.btn_reduce.clicked.connect(self._on_reduce)

        self.btn_restore = QtWidgets.QPushButton(
            make_icon(icons.ICON_UTIL_RESTORE), "", self)
        self.btn_restore.setMinimumHeight(28)
        self.btn_restore.setFixedWidth(32)
        self.btn_restore.setToolTip(
            "Undo the last reduction, restoring the previous names.\n"
            "The backup is saved with the scene, so this still works\n"
            "after a save and reload.")
        self.btn_restore.clicked.connect(self._on_restore)

        row.addWidget(self.btn_reduce, 1)
        row.addWidget(self.btn_restore, 0)
        section.add_layout(row)

        section.body().addSpacing(6)
        section.add_widget(self._heading("Collection Layout"))

        self.btn_flat = QtWidgets.QPushButton(
            make_icon(icons.ICON_UTIL_FLAT), "  Flat  ( High / Low )", self)
        self.btn_flat.setMinimumHeight(28)
        self.btn_flat.setToolTip(
            "Bake_Group -> High / Low / Cage, grouped by role.")
        self.btn_flat.clicked.connect(lambda: self._on_organize('FLAT'))

        self.btn_per_asset = QtWidgets.QPushButton(
            make_icon(icons.ICON_UTIL_PERASSET), "  Per Asset  ( Bake_name )", self)
        self.btn_per_asset.setMinimumHeight(28)
        self.btn_per_asset.setToolTip(
            "Bake_Group -> one Bake_<name> group per namepair.\n"
            "Each group is tinted green when its pair is complete and red\n"
            "when a member is missing.")
        self.btn_per_asset.clicked.connect(lambda: self._on_organize('PER_ASSET'))

        section.add_widget(self.btn_flat)
        section.add_widget(self.btn_per_asset)

        note = QtWidgets.QLabel(
            "Head group: '%s'\nMembership is decided by name suffix only."
            % core.HEAD_NAME, self)
        note.setStyleSheet("QLabel { color: #888888; }")
        section.add_widget(note)

    # -- Naming --------------------------------------------------------------
    def _build_naming(self, section):
        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setLabelAlignment(QtCore.Qt.AlignRight)

        self.combo_preset = QtWidgets.QComboBox(self)
        for key, label, tooltip in core.PRESET_ITEMS:
            self.combo_preset.addItem(label, key)
            self.combo_preset.setItemData(self.combo_preset.count() - 1,
                                          tooltip, QtCore.Qt.ToolTipRole)
        self.combo_preset.currentIndexChanged.connect(self._on_preset_changed)
        form.addRow("Convention", self.combo_preset)
        section.add_layout(form)

        self.custom_box = QtWidgets.QWidget(self)
        custom_form = QtWidgets.QFormLayout(self.custom_box)
        custom_form.setContentsMargins(0, 0, 0, 0)
        custom_form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.field_low = QtWidgets.QLineEdit(self)
        self.field_high = QtWidgets.QLineEdit(self)
        self.field_cage = QtWidgets.QLineEdit(self)
        for field, name in ((self.field_low, "custom_low_suffix"),
                            (self.field_high, "custom_high_suffix"),
                            (self.field_cage, "custom_cage_suffix")):
            field.editingFinished.connect(
                lambda f=field, n=name: self._on_suffix_changed(f, n))
        custom_form.addRow("Low", self.field_low)
        custom_form.addRow("High", self.field_high)
        custom_form.addRow("Cage", self.field_cage)
        section.add_widget(self.custom_box)

        detect_form = QtWidgets.QFormLayout()
        detect_form.setContentsMargins(0, 6, 0, 0)
        detect_form.setLabelAlignment(QtCore.Qt.AlignRight)
        self.combo_criterion = QtWidgets.QComboBox(self)
        for key, label, tooltip in core.HILO_CRITERION_ITEMS:
            self.combo_criterion.addItem(label, key)
            self.combo_criterion.setItemData(self.combo_criterion.count() - 1,
                                             tooltip, QtCore.Qt.ToolTipRole)
        self.combo_criterion.currentIndexChanged.connect(
            self._on_criterion_changed)
        detect_form.addRow("Detect By", self.combo_criterion)
        section.add_layout(detect_form)

        self.chk_smooth = IconCheckBox(
            "Count Smooth Preview", icons.ICON_SMOOTH,
            "Maya's smooth mesh preview (the '3' key) does not change what\n"
            "polyEvaluate counts, so a high poly viewed smoothed can read as\n"
            "its base cage and lose the comparison to a dense low.\n"
            "Turn this on to fold the preview level into the count.", self)
        self.chk_smooth.toggled.connect(
            lambda v: setattr(self.settings, "count_smooth_preview", v))
        section.add_widget(self.chk_smooth)

    # -- Options -------------------------------------------------------------
    def _build_options(self, section):
        self.option_boxes = {}
        for name, label, icon, tooltip in (
                ("generate_random_name", "Generate Random Name", icons.ICON_RANDOM,
                 "Use a random base name instead of the low poly's name."),
                ("also_rename_shape", "Also Rename Shape Node", icons.ICON_SHAPE,
                 "Rename the mesh shape to match its transform."),
                ("detect_cage", "Detect Cage", icons.ICON_DETECT_CAGE,
                 "Treat a selected object ending in the cage suffix as the cage,\n"
                 "and keep it out of the high/low comparison."),
                ("move_to_group", "Move to Group", icons.ICON_GROUP,
                 "Move the new namepair into a 'Bake_<name>' group."),
                ("hide_after_renaming", "Hide After Renaming", icons.ICON_HIDE_AFTER,
                 "Park the objects out of sight once they have been renamed.\n"
                 "Uses lodVisibility, so their own visibility attribute is\n"
                 "left alone."),
        ):
            box = IconCheckBox(label, icon, tooltip, self)
            box.toggled.connect(
                lambda value, n=name: setattr(self.settings, n, value))
            section.add_widget(box)
            self.option_boxes[name] = box

        section.body().addSpacing(6)

        box = IconCheckBox(
            "Allow Name Collisions", icons.ICON_OVERWRITE,
            "Off, a clash is reported and nothing is renamed.\n"
            "On, Maya is allowed to number its way out of it - which produces\n"
            "'asset_low1', not a second 'asset_low'.", self)
        box.toggled.connect(
            lambda value: setattr(self.settings, "allow_name_collisions", value))
        section.add_widget(box)
        self.option_boxes["allow_name_collisions"] = box

        # Maya-only. Blender always knew which object was active; Maya only
        # records selection order when this preference is on, and without it
        # the low poly in group mode has to be guessed from geometry instead
        # of taken from what the artist clicked last.
        self.chk_track_order = IconCheckBox(
            "Track Selection Order", icons.ICON_SELECT_ORDER,
            "A Maya preference, not a QC Bake setting.\n"
            "With it on, selecting three or more meshes makes the LAST one\n"
            "selected the low poly. With it off, Maya does not record the\n"
            "order and the smallest mesh is used instead.", self)
        self.chk_track_order.toggled.connect(self._on_track_order)
        section.add_widget(self.chk_track_order)

        section.body().addSpacing(6)
        section.add_widget(self._heading("Updates"))

        box = IconCheckBox(
            "Check on Open", icons.ICON_RANDOM,
            "Maya has no add-on repository of its own, so QC Bake asks a\n"
            "manifest we publish whether a newer release exists.\n"
            "It only ever tells you - it never installs on its own.\n"
            "Checked at most once every few hours, in the background.", self)
        box.toggled.connect(
            lambda value: setattr(self.settings, "update_auto_check", value))
        section.add_widget(box)
        self.option_boxes["update_auto_check"] = box

        check_now = QtWidgets.QPushButton("Check for Updates Now", self)
        check_now.clicked.connect(lambda: self.check_for_updates(announce=True))
        section.add_widget(check_now)

    def _heading(self, text):
        label = QtWidgets.QLabel(text, self)
        label.setStyleSheet("QLabel { font-weight: bold; }")
        return label

    # -- settings <-> widgets ------------------------------------------------
    def _load_settings(self):
        """Push stored settings into the widgets, without echoing back."""
        self._refreshing = True
        try:
            settings = self.settings
            index = self.combo_preset.findData(settings.naming_preset)
            self.combo_preset.setCurrentIndex(max(0, index))

            self.field_low.setText(settings.custom_low_suffix)
            self.field_high.setText(settings.custom_high_suffix)
            self.field_cage.setText(settings.custom_cage_suffix)

            index = self.combo_criterion.findData(settings.hilo_criterion)
            self.combo_criterion.setCurrentIndex(max(0, index))
            self.chk_smooth.setChecked(settings.count_smooth_preview)

            for name, box in self.option_boxes.items():
                box.setChecked(getattr(settings, name))

            self.field_prefix.setText(settings.reduce_group_prefix)
            self.field_gap.setValue(settings.reduce_min_gap)

            self.chk_track_order.setChecked(scene.selection_order_tracked())
        finally:
            self._refreshing = False

    # -- refresh -------------------------------------------------------------
    def refresh(self):
        """Re-read the scene and bring every stateful widget up to date."""
        if self._refreshing or not getattr(self, "_ready", False):
            return
        self._refreshing = True
        try:
            self.custom_box.setVisible(
                self.combo_preset.currentData() == 'CUSTOM')

            blank = blank_icon()
            any_named = False
            for group, (show, hide) in self.visibility_rows.items():
                state = commands.group_state(group)
                enabled = state is not None
                any_named = any_named or enabled
                for button in (show, hide):
                    button.setEnabled(enabled)
                show.setChecked(state == 'SHOWN')
                hide.setChecked(state == 'HIDDEN')
                # The eye rides whichever button reflects the current state,
                # exactly as it did in the Blender panel.
                show.setIcon(make_icon(icons.ICON_SHOW)
                             if state == 'SHOWN' else blank)
                hide.setIcon(make_icon(icons.ICON_HIDE)
                             if state == 'HIDDEN' else blank)

            self.visibility_hint.setVisible(not any_named)
            self.btn_restore.setEnabled(reduce_cmd.has_backup())
        except RuntimeError:
            # A scriptJob can fire mid scene-change, when a node the scan is
            # walking has already gone. Skipping that refresh is correct: the
            # event that finishes the change will fire another one.
            pass
        finally:
            self._refreshing = False

    def _refresh_selection(self):
        """Cheap update: only what depends on the current selection.

        Guarded like refresh(): this runs from a subscription, and a widget
        can be destroyed between the event being queued and the callback
        arriving. Reaching for a deleted button then raises out of a callback,
        where the only place it can go is Maya's error line.
        """
        if not getattr(self, "_ready", False):
            return
        try:
            count = len(scene.selected_meshes())
            self.btn_create.setEnabled(count >= 2)
            self.btn_swap.setEnabled(count == 2)
            self.selection_hint.setText(self._selection_hint_text(count))
        except RuntimeError:
            pass

    def _selection_hint_text(self, count):
        """Say what is selected and what each button would do with it."""
        if count == 0:
            selected = cmds.ls(selection=True, objectsOnly=True) or []
            if selected:
                return ("Nothing selected that QC Bake can use - %d object%s "
                        "selected, but none is a polygon mesh."
                        % (len(selected), "" if len(selected) == 1 else "s"))
            return "Nothing selected. Pick the meshes of one asset."
        if count == 1:
            return "1 mesh selected. Create Namepair needs at least 2."
        if count == 2:
            return "2 meshes selected: the denser one becomes the high."
        if self.settings.detect_cage:
            cage = ", minus any object already ending in the cage suffix"
        else:
            cage = ""
        return ("%d meshes selected: 1 low and %d highs%s."
                % (count, count - 1, cage))

    # -- handlers ------------------------------------------------------------
    def _run(self, function, *args):
        """Run a command and report it, whatever happens.

        A Qt slot that raises does not reach the user: PySide prints the
        traceback to stdout and returns as if nothing happened, so the panel
        sits there looking fine while the action silently did not run. Every
        button therefore goes through here, and an escaping exception is
        turned into an error the status strip can show. The traceback is still
        printed, because that is what a bug report needs.
        """
        try:
            result = function(*args)
        except Exception as exc:
            traceback.print_exc()
            result = commands.fail(
                "%s: %s  (full traceback in the Script Editor)"
                % (type(exc).__name__, exc))

        self.status.show_result(result)

        try:
            self.refresh()
        except Exception:
            traceback.print_exc()
        return result

    def _on_create(self):
        self._run(commands.create_namepair)

    def _on_swap(self):
        self._run(commands.swap_high_low)

    def _on_visibility(self, group, visible):
        self._run(commands.set_group_visible, group, visible)

    def _on_clear_visibility(self):
        self._run(commands.clear_all)

    def _on_reduce(self):
        self._run(commands.reduce_groups)

    def _on_restore(self):
        self._run(commands.restore_groups)

    def _on_organize(self, mode):
        self._run(commands.organize, mode)

    def _on_preset_changed(self):
        if self._refreshing:
            return
        self.settings.naming_preset = self.combo_preset.currentData()
        self.refresh()

    def _on_criterion_changed(self):
        if self._refreshing:
            return
        self.settings.hilo_criterion = self.combo_criterion.currentData()

    def _on_suffix_changed(self, field, name):
        if self._refreshing:
            return
        setattr(self.settings, name, field.text())
        self.refresh()

    def _on_prefix_changed(self):
        if self._refreshing:
            return
        self.settings.reduce_group_prefix = self.field_prefix.text()

    def _on_gap_changed(self, value):
        if self._refreshing:
            return
        self.settings.reduce_min_gap = value

    def _on_track_order(self, value):
        if self._refreshing:
            return
        scene.set_selection_order_tracked(value)

    # -- updates -------------------------------------------------------------
    def maybe_check_for_updates(self):
        """Check at most a few times a day, and only if asked to.

        Rate limited because opening the panel is something an artist does
        constantly, and a request per open is both rude to the server and
        pointless - releases do not appear every ten minutes.

        The limit is skipped when the running version is not the one the last
        check was made from. These settings live in Maya optionVars, so they
        belong to the artist and outlive any install: without this, a copy
        installed minutes ago inherits the previous one's timestamp and stays
        quiet about being out of date, which is the one moment it really ought
        not to.
        """
        import time

        if not self.settings.update_auto_check:
            return

        if self.settings.update_last_version != VERSION_STRING:
            self.check_for_updates(announce=False)
            return

        age = time.time() - (self.settings.update_last_check or 0.0)
        if age < prefs.UPDATE_CHECK_INTERVAL:
            return
        self.check_for_updates(announce=False)

    def check_for_updates(self, announce=True):
        """Start a check. `announce` reports "you are up to date" as well.

        Silent when it runs on its own: nobody wants "no update available" in
        the status strip every time they open the tool. A check the artist
        asked for says so either way, because a button that does nothing
        visible reads as broken.
        """
        if self._update_check is not None:
            return
        url = self.settings.update_url
        self._announce_update = announce
        if announce:
            self.status.show_message('INFO', "Checking for updates...")

        self._update_check = UpdateCheck(url, self)
        self._update_check.finished.connect(self._on_update_checked)
        self._update_check.start()

    def _on_update_checked(self, manifest, error):
        """Back on the main thread with the manifest, or a reason there isn't."""
        import time

        self._update_check = None
        if not getattr(self, "_ready", False):
            return

        if error:
            # A failed check is not the artist's problem unless they asked.
            if getattr(self, "_announce_update", False):
                self.status.show_message('WARNING', error)
            return

        self.settings.update_last_check = time.time()
        # Recorded together, so the throttle can tell "checked recently" from
        # "checked recently, by a different version of the tool".
        self.settings.update_last_version = VERSION_STRING
        remote = manifest.get("version", "")

        if not updater.is_newer(remote, VERSION_STRING):
            if getattr(self, "_announce_update", False):
                self.status.show_message(
                    'INFO', "QC Bake %s is the latest version." % VERSION_STRING)
            return

        if remote == self.settings.update_skip_version:
            return

        self._pending_update = manifest
        notes = manifest.get("notes") or ""
        self.update_label.setText(
            "QC Bake %s is available (you have %s).%s"
            % (remote, VERSION_STRING, ("\n" + notes) if notes else ""))
        self.update_banner.setVisible(True)
        # The banner is now carrying the news, so the status strip should stop
        # saying "Checking for updates..." - left there it reads as a check
        # that never finished.
        if getattr(self, "_announce_update", False):
            self.status.clear_message()

    def _on_skip_update(self):
        if self._pending_update:
            self.settings.update_skip_version = self._pending_update.get(
                "version", "")
        self._pending_update = None
        self.update_banner.setVisible(False)

    def _on_install_update(self):
        """Fetch, verify, swap and reload. Never silent about what happened."""
        manifest = self._pending_update
        if not manifest:
            return

        self.btn_update.setEnabled(False)
        self.status.show_message(
            'INFO', "Downloading QC Bake %s..." % manifest.get("version"))
        QtWidgets.QApplication.processEvents()

        install_dir = updater.install_dir_for(updater.__file__)
        try:
            backup, error = updater.perform_update(manifest, install_dir)
        except Exception as exc:
            traceback.print_exc()
            backup, error = None, "Update failed: %s" % exc

        if error:
            self.btn_update.setEnabled(True)
            self.status.show_message('ERROR', error)
            return

        # The swap is done. Reloading has to happen after this handler has
        # returned, because it destroys the very widget the handler is running
        # on - and the backup is kept until the new version has actually
        # imported, so a broken release cannot take the tool out of the studio.
        QtCore.QTimer.singleShot(
            0, lambda: _finish_update(backup, install_dir,
                                      manifest.get("version", "")))

    # -- scriptJobs ----------------------------------------------------------
    @property
    def _script_jobs(self):
        """The subscriptions currently running, straight from Maya.

        They deliberately do not belong to the panel. A scriptJob bound to a
        panel's own method keeps that panel addressable forever, and Maya does
        not reliably tell a widget when its workspaceControl is destroyed - so
        the jobs outlive the widget and fire into deleted C++ objects. Worse,
        reloading the module gives the class a fresh registry while Maya keeps
        running the old jobs, which nothing is then able to find or stop. One
        real session had 132 of them, aimed at twelve dead panels.
        """
        return _running_jobs()

    def _install_script_jobs(self):
        """Subscribe to the scene events that make the panel go stale."""
        _install_jobs()
        self._refresh_selection()

    def _kill_script_jobs(self, stop_timer=False):
        _purge_jobs()
        if stop_timer:
            timer = getattr(self, "_health_timer", None)
            if timer is not None:
                timer.stop()

    def _script_jobs_healthy(self):
        """True when every subscription the panel needs is still running."""
        return _jobs_healthy()

    def _check_health(self):
        """Timer tick: re-arm if the subscriptions have gone missing."""
        if not getattr(self, "_ready", False):
            return
        # Only the panel the module is actually serving owns the
        # subscriptions; a stray still counting down its timer must not
        # reinstall them out from under it.
        if _PANEL is not self:
            return
        try:
            if self._script_jobs_healthy():
                return
            self._install_script_jobs()
            self.refresh()
        except RuntimeError:
            # The widget is being torn down underneath us; the timer dies
            # with it.
            pass

    def showEvent(self, event):
        """Re-arm before becoming visible, and re-read the scene.

        A panel whose scriptJobs have gone is the worst failure this tool has:
        it looks completely normal but never notices anything, so its buttons
        stay greyed out no matter what the artist selects, with nothing on
        screen to explain why. Rather than trust that never to happen, the
        panel checks its own subscriptions every time it is shown and rebuilds
        them if any are missing.
        """
        super(QCBakePanel, self).showEvent(event)
        if not getattr(self, "_ready", False):
            return
        if not self._script_jobs_healthy():
            self._install_script_jobs()
        timer = getattr(self, "_health_timer", None)
        if timer is not None and not timer.isActive():
            timer.start()
        self._refresh_selection()
        self.refresh()
        self.maybe_check_for_updates()

    def _teardown(self):
        """Give up this panel's timer, and the subscriptions if they are ours.

        The guard matters. The subscriptions are shared by the module, and a
        panel being replaced is closed *after* its successor has armed them -
        so an unguarded teardown here tears down the new panel's wiring and
        leaves it deaf. Only the panel the module is currently serving may
        stop them.
        """
        timer = getattr(self, "_health_timer", None)
        if timer is not None:
            timer.stop()
        if _PANEL is self or _PANEL is None:
            _purge_jobs()

    def closeEvent(self, event):
        self._teardown()
        super(QCBakePanel, self).closeEvent(event)

    def dockCloseEventTriggered(self):
        self._teardown()


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------
_PANEL = None

# -----------------------------------------------------------------------------
# Scene subscriptions
# -----------------------------------------------------------------------------
# The scriptJobs live here rather than on the panel, and they call these two
# functions rather than any panel's bound method. That indirection is the whole
# point: a job can then always find whichever panel is current, and can never
# hold a dead one addressable.
#
# The names below are load-bearing. Maya reports a job's callback in
# scriptJob(listJobs=True), so a distinctive name is the only way to find jobs
# installed by an earlier generation of this module - which a reload orphans,
# leaving Maya running callbacks that nothing in the new generation has a
# reference to. Do not rename them without updating JOB_MARKERS.
# There is deliberately no list of job ids kept here. Maya already knows what
# it is running, and keeping a second copy meant two sources of truth that
# drifted apart - a panel would believe its subscriptions were missing while
# eleven of them were running perfectly well, and reinstall on every tick.
# Everything below asks Maya instead.
JOB_MARKERS = ("qcbake_scriptjob", "QCBakePanel")


def _dispatch(method_name):
    """Route one scene event to the current panel, whatever the state of it.

    Nothing may escape from here. Maya disables a scriptJob whose callback
    raises - which is how the orphaned jobs of a previous session eventually
    died, each one printing to the error line on its way out - so a single
    unhandled exception in a refresh would silently unsubscribe the panel and
    freeze it for the rest of the session. The traceback is still printed,
    because a bug in refresh is worth seeing; the subscription just survives it.
    """
    panel = _live_panel()
    if panel is None:
        _purge_jobs()
        return
    try:
        getattr(panel, method_name)()
    except RuntimeError:
        # The widget went away between the event and this callback.
        _purge_jobs()
    except Exception:
        traceback.print_exc()


def qcbake_scriptjob_selection():
    """SelectionChanged: update only what depends on the selection."""
    _dispatch("_refresh_selection")


def qcbake_scriptjob_scene():
    """Any event that can change which objects hold which role."""
    _dispatch("refresh")


JOB_COUNT = len(SCENE_EVENTS) + 1


def _running_jobs():
    """Ids of every QC Bake subscription Maya is actually running.

    Read back from Maya rather than remembered, which is what makes this
    survive a module reload: jobs installed by a previous generation are
    otherwise unreachable - nothing in the new generation holds their ids -
    and they go on firing at panels that no longer exist. Matching on the
    callback Maya reports is the only way to find them again.
    """
    found = []
    for entry in cmds.scriptJob(listJobs=True) or []:
        if not any(marker in entry for marker in JOB_MARKERS):
            continue
        job_id = entry.split(":", 1)[0].strip()
        if job_id.isdigit():
            found.append(int(job_id))
    return found


def _purge_jobs():
    """Stop every QC Bake subscription in this Maya, whoever installed it."""
    for job in _running_jobs():
        if cmds.scriptJob(exists=job):
            cmds.scriptJob(kill=job, force=True)


def _install_jobs():
    """Replace every subscription with a fresh set."""
    _purge_jobs()
    jobs = [cmds.scriptJob(event=["SelectionChanged",
                                  qcbake_scriptjob_selection])]
    for name in SCENE_EVENTS:
        jobs.append(cmds.scriptJob(event=[name, qcbake_scriptjob_scene]))
    return jobs


def _jobs_healthy():
    """True when exactly the expected subscriptions are running."""
    return len(_running_jobs()) == JOB_COUNT


def orphan_job_count():
    """Subscriptions beyond the one set that should exist.

    Only useful for diagnosis and tests - a healthy session answers zero. A
    session that has reloaded the package without closing the panel first used
    to answer in the hundreds.
    """
    return max(0, len(_running_jobs()) - JOB_COUNT)


# Maya stores this with the workspaceControl and runs it whenever it rebuilds
# the control - restoring a saved layout, or starting up with the panel docked
# where it was left. It therefore has to be safe to call while the control
# already exists, which is exactly what show() below guarantees.
UI_SCRIPT = "import qc_bake_maya; qc_bake_maya.show()"


def _live_panel():
    """Return the existing panel if it is still a real widget, else None.

    A Python reference can easily outlive the C++ widget it wraps - Maya
    deletes the workspaceControl and everything inside it without telling
    Python - and touching one of those raises. shiboken is the only way to
    ask whether the object underneath is still there.
    """
    global _PANEL
    if _PANEL is None:
        return None
    if not shiboken6.isValid(_PANEL):
        _PANEL = None
        return None
    return _PANEL


def _sweep_orphans(keep=None):
    """Destroy every live panel except `keep`. Returns how many went.

    Anything that builds a QCBakePanel without going through show() - a
    screenshot helper, a half-finished reload, a script an artist pasted into
    the Script Editor - can leave a second panel on screen. That copy is not
    merely redundant: whichever one loses the race for the module global keeps
    no scriptJobs, so it never sees a selection change and sits there with
    every button greyed out. One panel, always.
    """
    removed = 0
    survivors = []
    for ref in QCBakePanel._instances:
        panel = ref()
        if panel is None:
            continue
        try:
            if not shiboken6.isValid(panel):
                continue
        except Exception:
            continue
        if panel is keep:
            survivors.append(ref)
            continue
        try:
            # Deliberately not touching the subscriptions: they belong to the
            # module and already aim at whichever panel is current, so tearing
            # down a stray must not take them with it.
            timer = getattr(panel, "_health_timer", None)
            if timer is not None:
                timer.stop()
            # Hide before unparenting: a widget whose parent is dropped
            # becomes a top-level window, and would flash on screen on its way
            # out. deleteLater only takes effect when the event loop next
            # spins, so hiding is what actually gets it off screen now.
            panel.hide()
            panel.setParent(None)
            panel.deleteLater()
            removed += 1
        except RuntimeError:
            pass
    QCBakePanel._instances = survivors
    return removed


def show():
    """Open the QC Bake panel, or bring the one already open to the front.

    This is also the uiScript Maya runs when it restores the panel's
    workspaceControl, so it must never destroy a control that is in the middle
    of being rebuilt - doing that was what left a live panel on screen with the
    module's own reference pointing at a different, discarded one.
    """
    global _PANEL

    panel = _live_panel()
    if panel is not None:
        # Already up. Surface it rather than rebuilding it, so a second click
        # on the shelf button does not wipe the message the artist is reading.
        _sweep_orphans(keep=panel)
        if not panel._script_jobs_healthy():
            panel._install_script_jobs()
        panel.setVisible(True)
        if cmds.workspaceControl(WORKSPACE_CONTROL, exists=True):
            cmds.workspaceControl(WORKSPACE_CONTROL, edit=True,
                                  restore=True, visible=True)
        panel.refresh()
        return panel

    # No live panel of our own, but there may still be a stray one that never
    # made it into the global - it would otherwise stay on screen, frozen.
    _sweep_orphans()

    # Any control still standing is an empty shell - either restored by Maya
    # at startup, or left behind by a reload - so it goes.
    if cmds.workspaceControl(WORKSPACE_CONTROL, exists=True):
        cmds.deleteUI(WORKSPACE_CONTROL, control=True)

    _PANEL = QCBakePanel()
    # Only now is the panel reachable, so only now can subscriptions aimed at
    # it be safely armed.
    _install_jobs()
    _PANEL.show(dockable=True, uiScript=UI_SCRIPT)
    return _PANEL


def reload_package():
    """Drop the package and bring it back at whatever version is on disk.

    Only possible because close() genuinely lets go - the subscriptions and
    the widgets both. Reloading without that is what leaves a Maya session
    full of orphaned scriptJobs firing at destroyed panels.
    """
    import sys

    close()
    for name in [n for n in list(sys.modules) if n.startswith("qc_bake_maya")]:
        del sys.modules[name]

    import qc_bake_maya
    return qc_bake_maya.show()


def _finish_update(backup, install_dir, version):
    """Reload after a swap, and put the old version back if it will not load.

    An update that installs but cannot import would otherwise leave the artist
    with no tool and no obvious way back, which is the one failure an updater
    absolutely must not have.
    """
    try:
        panel = reload_package()
    except Exception:
        traceback.print_exc()
        restored = updater.rollback(backup, install_dir)
        try:
            panel = reload_package()
        except Exception:
            traceback.print_exc()
            cmds.warning(
                "QC Bake %s failed to load and the previous version could not "
                "be restored automatically. Reinstall from install/install.py."
                % version)
            return None
        if panel is not None and restored:
            panel.status.show_message(
                'ERROR',
                "QC Bake %s failed to load, so the previous version was put "
                "back. The traceback is in the Script Editor." % version)
        return panel

    updater.discard_backup(backup)
    if panel is not None:
        panel.status.show_message('INFO', "Updated to QC Bake %s." % version)
    return panel


def close():
    """Close every QC Bake panel, stop its subscriptions, drop its control.

    Call this before reloading the package. Without it the subscriptions from
    this generation keep running against panels the reload has orphaned.
    """
    global _PANEL

    _purge_jobs()
    _sweep_orphans()
    _PANEL = None

    if cmds.workspaceControl(WORKSPACE_CONTROL, exists=True):
        cmds.deleteUI(WORKSPACE_CONTROL, control=True)
