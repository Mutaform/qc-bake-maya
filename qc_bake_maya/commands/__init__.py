# QC Bake for Maya - commands package
# -----------------------------------
# One module per user-facing action. Each command is a plain function that
# returns a Result rather than raising or printing, so the same call works
# from the panel, from a shelf button and from a pipeline script.
#
# This replaces Blender's Operator classes. Their two useful properties are
# kept: everything a command does collapses into a single undo step, and the
# outcome comes back as a level plus a message for the UI to show.

import collections

Result = collections.namedtuple("Result", "ok level message")


def ok(message):
    return Result(True, 'INFO', message)


def warn(message):
    return Result(False, 'WARNING', message)


def fail(message):
    return Result(False, 'ERROR', message)


from .create import create_namepair          # noqa: E402
from .organize import organize               # noqa: E402
from .reduce import has_backup, reduce_groups, restore_groups  # noqa: E402
from .swap import swap_high_low              # noqa: E402
from .visibility import (                    # noqa: E402
    clear_all, group_state, set_group_visible, sync_layers,
)

__all__ = [
    "Result", "ok", "warn", "fail",
    "create_namepair", "swap_high_low", "organize",
    "reduce_groups", "restore_groups", "has_backup",
    "group_state", "set_group_visible", "sync_layers", "clear_all",
]
