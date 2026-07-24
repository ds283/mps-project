#
# Created by David Seery on 15/06/2018.
# Copyright (c) 2018 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#


from functools import lru_cache
from typing import List, Optional

from colour import Color


def get_text_colour(bg_colour):
    # assume bg_colour is string instance
    bg = Color(bg_colour)

    # compute perceived luminance
    a = 1 - (0.299 * bg.red + 0.587 * bg.green + 0.114 * bg.blue)

    if a < 0.5:
        return Color(rgb=(0, 0, 0)).hex_l

    return Color(rgb=(1, 1, 1)).hex_l


#: Hue-rotation offsets (degrees) applied, in order, to a base colour's hue to derive an ordered
#: family of distinguishable-but-related tints. Cycles when `count` exceeds this many stops.
_HUE_OFFSETS_DEG = (0, -25, 25, -50, 50)

#: Neutral (Bootstrap secondary-token) fallback used when no class colour is available.
_NEUTRAL_FAMILY_ENTRY = {
    "pill_bg": "var(--bs-secondary-bg-subtle)",
    "pill_fg": "var(--bs-secondary-text-emphasis)",
    "pill_border": "var(--bs-secondary-border-subtle)",
    "band_bg": "var(--bs-secondary-bg)",
    "band_fg": "var(--bs-secondary-text-emphasis)",
    "band_border": "var(--bs-border-color)",
}


def _hsl_hex(hue: float, saturation: float, luminance: float) -> str:
    hue = hue % 1.0
    saturation = min(max(saturation, 0.0), 1.0)
    luminance = min(max(luminance, 0.0), 1.0)
    return Color(hsl=(hue, saturation, luminance)).hex_l


@lru_cache(maxsize=256)
def period_colour_family(base_colour: Optional[str], count: int) -> List[dict]:
    """
    Derive `count` subtle shade triples from `base_colour` (a `ProjectClass.colour` hex string),
    one per submission-period position within that class. Each entry carries a `pill_*` triple
    (chip fill/text/border) and a lighter `band_*` triple (group-band fill/text/border), so
    periods within a class are visually distinguishable while staying anchored on the class hue.

    Positions cycle through a fixed set of hue-rotation offsets from the base colour, cycling
    when `count` exceeds the number of offsets. Pure and deterministic — memoised per
    `(base_colour, count)`.
    """
    count = max(count, 1)

    if base_colour is None:
        return [dict(_NEUTRAL_FAMILY_ENTRY) for _ in range(count)]

    base = Color(base_colour)
    base_hue = base.hue
    # grayish class colours carry ~0 saturation, which would render every stop as flat grey;
    # fall back to a moderate saturation so the tint is still perceptible
    saturation = base.saturation if base.saturation >= 0.15 else 0.45

    family = []
    for i in range(count):
        offset_deg = _HUE_OFFSETS_DEG[i % len(_HUE_OFFSETS_DEG)]
        hue = base_hue + offset_deg / 360.0

        family.append(
            {
                "pill_bg": _hsl_hex(hue, saturation * 0.75, 0.90),
                "pill_fg": _hsl_hex(hue, min(saturation + 0.15, 1.0), 0.24),
                "pill_border": _hsl_hex(hue, saturation * 0.85, 0.80),
                "band_bg": _hsl_hex(hue, saturation * 0.55, 0.96),
                "band_fg": _hsl_hex(hue, min(saturation + 0.10, 1.0), 0.28),
                "band_border": _hsl_hex(hue, saturation * 0.70, 0.85),
            }
        )

    return family
