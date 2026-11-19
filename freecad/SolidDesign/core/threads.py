# SPDX-License-Identifier: LGPL-2.1-or-later
"""Thread sizes: ISO metric (ISO 261 / ISO 262, coarse and fine) and Unified
inch (ASME B1.1, UNC and UNF), with the 60° basic profile (ISO 68-1).

Diameters are in millimetres. Tap drills follow the usual ~75% thread rule.
"""

import math

ISO_COARSE = "Metric Coarse"
ISO_FINE = "Metric Fine"
UNC = "Unified Coarse (UNC)"
UNF = "Unified Fine (UNF)"
SERIES = [ISO_COARSE, ISO_FINE, UNC, UNF]

INCH = 25.4

# size: (major diameter, pitch, tap drill)
_ISO_COARSE = {
    "M1.6": (1.6, 0.35, 1.25), "M2": (2.0, 0.40, 1.60), "M2.5": (2.5, 0.45, 2.05),
    "M3": (3.0, 0.50, 2.50), "M4": (4.0, 0.70, 3.30), "M5": (5.0, 0.80, 4.20),
    "M6": (6.0, 1.00, 5.00), "M8": (8.0, 1.25, 6.80), "M10": (10.0, 1.50, 8.50),
    "M12": (12.0, 1.75, 10.20), "M14": (14.0, 2.00, 12.00), "M16": (16.0, 2.00, 14.00),
    "M18": (18.0, 2.50, 15.50), "M20": (20.0, 2.50, 17.50), "M22": (22.0, 2.50, 19.50),
    "M24": (24.0, 3.00, 21.00), "M27": (27.0, 3.00, 24.00), "M30": (30.0, 3.50, 26.50),
    "M33": (33.0, 3.50, 29.50), "M36": (36.0, 4.00, 32.00),
}
_ISO_FINE = {
    "M8x1": (8.0, 1.00, 7.00), "M10x1": (10.0, 1.00, 9.00), "M10x1.25": (10.0, 1.25, 8.80),
    "M12x1.25": (12.0, 1.25, 10.80), "M12x1.5": (12.0, 1.50, 10.50),
    "M14x1.5": (14.0, 1.50, 12.50), "M16x1.5": (16.0, 1.50, 14.50),
    "M18x1.5": (18.0, 1.50, 16.50), "M20x1.5": (20.0, 1.50, 18.50),
    "M22x1.5": (22.0, 1.50, 20.50), "M24x2": (24.0, 2.00, 22.00), "M27x2": (27.0, 2.00, 25.00),
    "M30x2": (30.0, 2.00, 28.00), "M36x3": (36.0, 3.00, 33.00),
}
# Unified: size: (major diameter (in), threads per inch, tap drill (in))
_UNC_IN = {
    "#2-56": (0.0860, 56, 0.0700), "#4-40": (0.1120, 40, 0.0890), "#6-32": (0.1380, 32, 0.1065),
    "#8-32": (0.1640, 32, 0.1360), "#10-24": (0.1900, 24, 0.1495),
    "1/4-20": (0.2500, 20, 0.2010), "5/16-18": (0.3125, 18, 0.2570),
    "3/8-16": (0.3750, 16, 0.3125), "7/16-14": (0.4375, 14, 0.3680),
    "1/2-13": (0.5000, 13, 0.4219), "5/8-11": (0.6250, 11, 0.5312),
    "3/4-10": (0.7500, 10, 0.6562), "7/8-9": (0.8750, 9, 0.7656), "1-8": (1.0000, 8, 0.8750),
}
_UNF_IN = {
    "#4-48": (0.1120, 48, 0.0935), "#6-40": (0.1380, 40, 0.1130), "#8-36": (0.1640, 36, 0.1360),
    "#10-32": (0.1900, 32, 0.1590), "1/4-28": (0.2500, 28, 0.2130),
    "5/16-24": (0.3125, 24, 0.2720), "3/8-24": (0.3750, 24, 0.3320),
    "7/16-20": (0.4375, 20, 0.3906), "1/2-20": (0.5000, 20, 0.4531),
    "5/8-18": (0.6250, 18, 0.5781), "3/4-16": (0.7500, 16, 0.6875),
    "7/8-14": (0.8750, 14, 0.8125), "1-12": (1.0000, 12, 0.9219),
}


def _inch(table):
    return {k: (d * INCH, INCH / tpi, t * INCH) for k, (d, tpi, t) in table.items()}


TABLES = {ISO_COARSE: _ISO_COARSE, ISO_FINE: _ISO_FINE, UNC: _inch(_UNC_IN),
          UNF: _inch(_UNF_IN)}


def sizes(series):
    return list(TABLES[series])


def spec(series, size):
    """(major diameter, pitch, tap drill) in mm."""
    try:
        return TABLES[series][size]
    except KeyError:
        raise KeyError("Unknown thread {} {}".format(series, size))


def nearest(series, diameter, internal=False):
    """The size whose major diameter (external) or tap drill (internal) is
    nearest ``diameter``."""
    table = TABLES[series]
    key = 2 if internal else 0
    return min(table, key=lambda k: abs(table[k][key] - diameter))


def depth(pitch, internal=False):
    """Thread depth from the basic profile: external h3 = 0.6134 P, internal
    H1 = 0.5413 P (ISO 68-1; the same 60° form for Unified threads)."""
    return (0.54127 if internal else 0.61343) * pitch


def minor(major, pitch, internal=False):
    return major - 2 * depth(pitch, internal)


H = math.sqrt(3) / 2.0      # fundamental triangle height per unit pitch
