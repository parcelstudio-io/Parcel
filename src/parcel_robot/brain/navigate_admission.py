"""Pinned NavigateTo admission contract: searchable ≠ visible (task_2).

Admission requires fresh sensors and an available base. It does **not**
require the target to be visible in the frustum — grounding-with-recovery
(frustum → memory → scan → frontier → honest report) is NavigateTo's own
job. Requiring ``target_grounded`` at admission dead-ended
"go to the sidewalk" before the ladder could run (2026-08-05).

This module documents the pin for callers/tests. The skill contract table
in ``validator.py`` remains the runtime source of truth; Opus wires any
shared import later if desired.
"""

from __future__ import annotations

from collections.abc import Iterable

# Must appear on the NavigateTo skill contract at admission.
NAVIGATE_TO_REQUIRED_PRECONDITIONS: frozenset[str] = frozenset(
    {
        "camera_fresh",
        "lidar_fresh",
        "base_available",
    }
)

# Must NOT be a required admission precondition (token stays enforceable
# when a plan declares it explicitly).
NAVIGATE_TO_FORBIDDEN_ADMISSION_PRECONDITIONS: frozenset[str] = frozenset(
    {
        "target_grounded",
    }
)


def assert_searchable_admission_contract(
    required_preconditions: Iterable[str],
) -> None:
    """Raise ``AssertionError`` if the contract requires visibility."""

    required = frozenset(required_preconditions)
    missing = NAVIGATE_TO_REQUIRED_PRECONDITIONS - required
    if missing:
        raise AssertionError(
            "NavigateTo admission missing searchable preconditions: "
            f"{sorted(missing)}"
        )
    forbidden = NAVIGATE_TO_FORBIDDEN_ADMISSION_PRECONDITIONS & required
    if forbidden:
        raise AssertionError(
            "NavigateTo admission must not require visibility tokens "
            f"(searchable ≠ visible): {sorted(forbidden)}"
        )
