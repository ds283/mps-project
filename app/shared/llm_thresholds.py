#
# Created by David Seery on 07/04/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

# ---------------------------------------------------------------------------
# Classification thresholds for lexical-diversity AI-indicator metrics.
#
# These are the single authoritative source.  All classification logic and
# display code must import from here rather than defining its own copies.
# ---------------------------------------------------------------------------

MTLD_NOTE_THRESHOLD = 70
MTLD_STRONG_THRESHOLD = 50
MTLD_HIGH_NOTE_THRESHOLD = 100

MATTR_NOTE_THRESHOLD = 0.68
MATTR_STRONG_THRESHOLD = 0.60

BURSTINESS_NOTE_THRESHOLD = 0.20
BURSTINESS_STRONG_THRESHOLD = 0.10


def classify_metric(
    value: float | None, note_threshold: float, strong_threshold: float
) -> str:
    """Return 'ok', 'note', or 'strong' classification for a metric value.

    Metrics are flagged when they fall *below* the note threshold (lower value
    → greater AI-indicator concern).  'unknown' is returned when value is None.
    """
    if value is None:
        return "unknown"
    if value < strong_threshold:
        return "strong"
    if value < note_threshold:
        return "note"
    return "ok"


def classify_mtld(value: float | None) -> str:
    """Classify an MTLD value using the two-sided rule.

    MTLD is flagged 'note' both when it is abnormally *low* (< MTLD_NOTE_THRESHOLD,
    suggesting limited vocabulary range) and abnormally *high*
    (> MTLD_HIGH_NOTE_THRESHOLD, which can indicate inflated diversity from AI
    padding).  'strong' is returned only for very low values.
    """
    if value is None:
        return "unknown"
    if value > MTLD_HIGH_NOTE_THRESHOLD:
        return "note"
    return classify_metric(value, MTLD_NOTE_THRESHOLD, MTLD_STRONG_THRESHOLD)
