# QC Bake for Maya - settings
# ---------------------------
# The Blender version hung its settings off the Scene, so they travelled
# inside the .blend. Maya optionVars are used instead, which makes them
# per-artist rather than per-file.
#
# That is a deliberate upgrade, not a compromise. A naming convention is a
# property of the person and the studio pipeline, not of one scene: opening a
# colleague's file should not silently switch you to xNormal suffixes, and
# having to re-pick your convention every time you open a fresh scene is the
# behaviour the Blender version was stuck with.
#
# Settings are read and written through plain attribute access, so call sites
# read the same as they did before the port:
#
#     settings = prefs.load()
#     low, high, cage = core.get_suffixes(settings)

import maya.cmds as cmds

OPTIONVAR_PREFIX = "qcBake_"


class _Field(object):
    """One setting: its default, and how it survives a round trip to Maya."""

    def __init__(self, name, default, kind):
        self.name = name
        self.default = default
        self.kind = kind
        self.var = OPTIONVAR_PREFIX + name

    def read(self):
        if not cmds.optionVar(exists=self.var):
            return self.default
        raw = cmds.optionVar(query=self.var)
        try:
            if self.kind is bool:
                return bool(int(raw))
            return self.kind(raw)
        except (TypeError, ValueError):
            return self.default

    def write(self, value):
        if self.kind is bool:
            cmds.optionVar(intValue=(self.var, int(bool(value))))
        elif self.kind is float:
            cmds.optionVar(floatValue=(self.var, float(value)))
        elif self.kind is int:
            cmds.optionVar(intValue=(self.var, int(value)))
        else:
            cmds.optionVar(stringValue=(self.var, str(value)))


# Declared in the order the UI presents them, which is also the order the
# Blender add-on used, so the two versions stay recognisably the same tool.
FIELDS = [
    _Field("naming_preset", "SUBSTANCE", str),
    _Field("custom_low_suffix", "_low", str),
    _Field("custom_high_suffix", "_high", str),
    _Field("custom_cage_suffix", "_cage", str),

    _Field("hilo_criterion", "TRIS", str),
    # Maya-only. Smooth mesh preview does not change what polyEvaluate counts,
    # so a hi-poly being viewed on "3" would otherwise read as its base cage
    # and lose the hi/lo comparison to a denser low.
    _Field("count_smooth_preview", False, bool),

    _Field("generate_random_name", False, bool),
    _Field("also_rename_shape", True, bool),
    _Field("detect_cage", True, bool),
    _Field("move_to_group", False, bool),
    _Field("hide_after_renaming", False, bool),
    _Field("allow_name_collisions", False, bool),

    _Field("reduce_group_prefix", "BakeGroup", str),
    _Field("reduce_min_gap", 0.05, float),

    # Updates. Maya has no add-on repository of its own, so the tool checks a
    # manifest we publish and tells the artist - it never installs on its own.
    _Field("update_url",
           "https://mutaform.github.io/qc-bake-maya/version.json", str),
    _Field("update_auto_check", True, bool),
    # Epoch seconds of the last successful check, so opening the panel twenty
    # times in an afternoon does not mean twenty requests.
    _Field("update_last_check", 0.0, float),
    # A version the artist chose to pass over; they are not asked about it
    # again, but a later one still surfaces.
    _Field("update_skip_version", "", str),
]

# How long a check is considered fresh.
UPDATE_CHECK_INTERVAL = 6 * 60 * 60  # six hours

_BY_NAME = {f.name: f for f in FIELDS}


class Settings(object):
    """Live view onto the optionVars: every read and write hits Maya."""

    __slots__ = ()

    def __getattr__(self, name):
        field = _BY_NAME.get(name)
        if field is None:
            raise AttributeError(name)
        return field.read()

    def __setattr__(self, name, value):
        field = _BY_NAME.get(name)
        if field is None:
            raise AttributeError(name)
        field.write(value)

    def as_dict(self):
        return {f.name: f.read() for f in FIELDS}

    def reset(self):
        """Drop every stored value, returning the tool to its defaults."""
        for field in FIELDS:
            if cmds.optionVar(exists=field.var):
                cmds.optionVar(remove=field.var)


_INSTANCE = Settings()


def load():
    """Return the shared settings object."""
    return _INSTANCE


# -----------------------------------------------------------------------------
# UI state
# -----------------------------------------------------------------------------
# Which panel sections are folded open is not a setting the tool acts on, so it
# stays out of FIELDS - but it is still worth remembering, because re-folding
# the same three sections at the start of every session is exactly the kind of
# small friction that makes a tool feel unfinished.
_UI_PREFIX = OPTIONVAR_PREFIX + "ui_"


def ui_flag(name, default=True):
    var = _UI_PREFIX + name
    if not cmds.optionVar(exists=var):
        return default
    return bool(cmds.optionVar(query=var))


def set_ui_flag(name, value):
    cmds.optionVar(intValue=(_UI_PREFIX + name, int(bool(value))))
