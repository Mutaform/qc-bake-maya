"""The flame itself, drawn to match the reference.

A classic flat-vector fire: three stacked silhouettes - orange outer with
several tongues, a vermilion middle that repeats the shape smaller, and a
rounded yellow core sitting low. Built in a 0..100 box so the numbers read
as percentages, and scaled wherever it is used.

Each layer is a union of separate closed paths rather than one clever
outline. Overlapping shapes of the same colour merge visually, and it means a
tongue can be moved without re-deriving the whole silhouette by hand.
"""

ORANGE = "#F26A1B"
RED = "#E23A15"
YELLOW = "#F9C23C"

# -- outer, orange -----------------------------------------------------------
# The body: a wide rounded base that narrows as it rises.
OUTER_BODY = ("M50 97 C29 97 14 83 14 65 C14 52 21 42 30 33 "
              "C40 23 47 14 50 3 C53 14 60 23 70 33 "
              "C79 42 86 52 86 65 C86 83 71 97 50 97 Z")
# The dominant tongue: tall, and leaning off centre at the tip. A flame drawn
# symmetrically reads as a droplet, not as fire - the lean is what sells it.
OUTER_TIP = ("M47 1 C56 12 53 21 57 30 C60 37 59 45 54 50 "
             "C47 45 42 36 43 26 C44 16 45 7 47 1 Z")
# Right-hand tongue. Pushed further out and given a real point, because in the
# first attempt the tongues sank into the body and the silhouette lost its
# teeth.
OUTER_RIGHT = ("M77 15 C77 29 84 37 85 49 C86 60 82 69 75 75 "
               "C75 62 71 54 67 46 C63 36 68 23 77 15 Z")
# Left-hand tongue, shorter and set lower, so the two sides do not mirror.
OUTER_LEFT = ("M24 24 C23 37 16 44 15 55 C14 65 18 72 24 77 "
              "C25 65 28 58 32 51 C36 42 33 32 24 24 Z")
# A small tongue low on the left, purely to break the outline.
OUTER_SPARK = ("M17 52 C14 60 11 65 11 71 C11 77 14 82 18 85 "
               "C18 78 20 73 22 68 C25 62 22 56 17 52 Z")

OUTER = [OUTER_BODY, OUTER_TIP, OUTER_RIGHT, OUTER_LEFT, OUTER_SPARK]

# -- middle, vermilion -------------------------------------------------------
MID_BODY = ("M50 95 C34 95 23 84 23 69 C23 59 28 51 35 44 "
            "C42 36 48 28 50 19 C52 28 58 36 65 44 "
            "C72 51 77 59 77 69 C77 84 66 95 50 95 Z")
MID_TIP = ("M48 14 C54 25 51 33 54 40 C56 45 55 51 51 55 "
           "C46 51 43 44 44 36 C45 27 46 19 48 14 Z")
MID_RIGHT = ("M68 34 C69 45 74 51 74 60 C74 68 71 74 66 78 "
             "C66 68 63 62 60 56 C56 48 61 40 68 34 Z")
MID_LEFT = ("M33 40 C32 50 27 55 26 63 C25 70 27 76 32 79 "
            "C32 70 34 65 37 60 C41 53 39 46 33 40 Z")

MID = [MID_BODY, MID_TIP, MID_RIGHT, MID_LEFT]

# -- core, yellow ------------------------------------------------------------
# Sits low and rounded, the way the hottest part of a flame reads.
CORE_BODY = ("M50 93 C39 93 31 85 31 74 C31 66 35 60 40 54 "
             "C45 48 49 42 50 36 C51 42 55 48 60 54 "
             "C65 60 69 66 69 74 C69 85 61 93 50 93 Z")
CORE_TIP = ("M50 34 C52 42 51 47 52 52 C53 56 52 60 50 62 "
            "C47 59 46 55 46 50 C47 44 49 38 50 34 Z")

CORE = [CORE_BODY, CORE_TIP]


def paths(shapes, fill):
    return "".join('<path d="%s" fill="%s"/>' % (d, fill) for d in shapes)


def flame(scale=1.0, dx=0.0, dy=0.0, layers=("outer", "mid", "core")):
    """Return the flame markup, scaled from its 100x100 box."""
    body = ""
    if "outer" in layers:
        body += paths(OUTER, ORANGE)
    if "mid" in layers:
        body += paths(MID, RED)
    if "core" in layers:
        body += paths(CORE, YELLOW)
    return ('<g transform="translate(%.3f,%.3f) scale(%.5f)">%s</g>'
            % (dx, dy, scale, body))


def silhouette(scale=1.0, dx=0.0, dy=0.0, fill="#000"):
    """Just the outer shape - for knockouts and shadows."""
    return ('<g transform="translate(%.3f,%.3f) scale(%.5f)">%s</g>'
            % (dx, dy, scale, paths(OUTER, fill)))
