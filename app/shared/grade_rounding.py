#
# Created by David Seery on 31/05/2026.
# Copyright (c) 2026 University of Sussex. All rights reserved.
#
# This file is part of the MPS-Project platform developed in
# the School of Mathematics & Physical Sciences, University of Sussex.
#
# Contributors: David Seery <D.Seery@sussex.ac.uk>
#

"""
Grade rounding policies for the marking pipeline.

The rounding policy is applied exactly once: when ConflationReport target values are written.
It must NOT be applied to intermediate grades (MarkingReport.grade, SubmitterReport.grade),
which are inputs to conflation expressions and must retain full precision.

To change the active policy, update ACTIVE_ROUNDING_POLICY.  The identifier stored on
historical ConflationReport records is preserved in JSON metadata and looked up via
lookup_rounding_policy() so old records remain self-describing.
"""

from decimal import Decimal


class RoundingPolicy:
    """Abstract base class for a grade rounding policy."""

    #: Short machine-readable identifier stored in ConflationReport JSON metadata.
    identifier: str

    #: Human-readable label shown in the UI.
    label: str

    #: Full policy description, shown as a UI tooltip / info text.
    description: str

    def round(self, value: float) -> int:
        raise NotImplementedError


class SussexStandardRoundingPolicy(RoundingPolicy):
    """
    University of Sussex standard module mark rounding policy.

    The mark for a module is a whole number.  A mark whose fractional part is equal to
    or greater than 0.45 is rounded up to the next integer; a mark whose fractional part
    is equal to or less than 0.44 is rounded down.
    """

    identifier = "sussex-standard-2024"
    label = "University of Sussex Standard"
    description = "Marks are rounded to a whole number. Fractional part ≥ 0.45 rounds up; fractional part ≤ 0.44 rounds down."

    def round(self, value: float) -> int:
        # Use Decimal to avoid IEEE 754 representation errors at the 0.45 threshold.
        d = Decimal(str(value))
        integer_part = int(d)
        fractional_part = d - integer_part
        if fractional_part >= Decimal("0.45"):
            return integer_part + 1
        return integer_part


#: The rounding policy applied to all new conflation runs.
ACTIVE_ROUNDING_POLICY: RoundingPolicy = SussexStandardRoundingPolicy()

_REGISTRY: dict[str, RoundingPolicy] = {
    SussexStandardRoundingPolicy.identifier: SussexStandardRoundingPolicy(),
}


def lookup_rounding_policy(identifier: str | None) -> RoundingPolicy | None:
    """Return the policy instance for a stored identifier, or None if unknown."""
    if identifier is None:
        return None
    return _REGISTRY.get(identifier)
