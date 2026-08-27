# QC Bake for Maya - name handling
# --------------------------------
# Maya node names carry two pieces of structure that Blender object names do
# not, and both bite silently rather than raising:
#
#   |group|child   DAG path. Names are unique only within a parent, so once
#                  objects are organised into bake groups the same short name
#                  can legitimately exist several times. Every lookup in this
#                  add-on therefore travels as a full path, and only the leaf
#                  is ever compared against a suffix.
#
#   REF:child      Namespace, put there by referencing. Renaming such a node
#                  with a bare name does not just rename it - it also yanks it
#                  out of its namespace. Any new name we hand to cmds.rename
#                  has to carry the original namespace back with it.
#
# On top of that Maya quietly mangles illegal names instead of refusing them:
# renaming a node to "1bad" produces "bad". Verified in Maya 2025. Validation
# up front is the only way to give the user an honest error message.

import re

DAG_SEP = "|"
NS_SEP = ":"

# Maya node names: a leading letter or underscore, then letters/digits/
# underscores. Everything else is stripped or rejected.
_VALID_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ILLEGAL_CHARS = re.compile(r"[^A-Za-z0-9_]")


def short_name(path):
    """Return the last DAG component of a path (namespace still attached)."""
    return path.rsplit(DAG_SEP, 1)[-1]


def split_namespace(path):
    """Return (namespace, leaf) for a node path.

    The namespace is returned without its trailing colon, and is "" for nodes
    in the root namespace. Nested namespaces (``a:b:node``) come back whole.
    """
    name = short_name(path)
    if NS_SEP not in name:
        return "", name
    namespace, _, leaf = name.rpartition(NS_SEP)
    return namespace, leaf


def leaf_name(path):
    """Return the bare node name: no DAG parents, no namespace.

    This is what suffix matching and base-name recovery must run against -
    matching "_low" against a full path would also fire on a parent group
    called "something_low".
    """
    return split_namespace(path)[1]


def with_namespace(path, new_leaf):
    """Re-apply `path`'s namespace to a new leaf name.

    Renaming ``REF:asset_low`` to ``asset_high`` would move the node into the
    root namespace; renaming it to ``REF:asset_high`` keeps it where it
    belongs. Callers build the new name from the leaf and pass it through
    here before touching cmds.rename.
    """
    namespace, _ = split_namespace(path)
    if not namespace:
        return new_leaf
    return "%s%s%s" % (namespace, NS_SEP, new_leaf)


def parent_path(path):
    """Return the DAG path of a node's parent, or "" when it sits at the root."""
    if DAG_SEP not in path.lstrip(DAG_SEP):
        return ""
    return path.rsplit(DAG_SEP, 1)[0]


def is_valid(name):
    """True when Maya will accept `name` as a node name unchanged."""
    return bool(_VALID_NAME.match(name or ""))


def sanitize(name, fallback="object"):
    """Coerce `name` into something Maya will accept verbatim.

    Illegal characters become underscores and a leading digit gains an
    underscore prefix, rather than being dropped the way Maya would drop it.
    Losing the leading character of an asset id silently is far worse than
    an obviously prefixed name.
    """
    cleaned = _ILLEGAL_CHARS.sub("_", (name or "").strip())
    if not cleaned:
        return fallback
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


def validate_suffix(suffix, label):
    """Return an error string for an unusable suffix, or None when it is fine.

    Suffixes end up glued onto a base name, so they may contain digits
    anywhere but must not introduce characters Maya would rewrite.
    """
    if not suffix:
        return "%s suffix must not be empty." % label
    if _ILLEGAL_CHARS.search(suffix):
        return ("%s suffix '%s' contains characters Maya does not allow in "
                "node names (letters, digits and underscore only)."
                % (label, suffix))
    return None
