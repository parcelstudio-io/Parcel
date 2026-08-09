"""Pinned NavigateTo admission contract: searchable ≠ visible."""

from __future__ import annotations

import pytest

from parcel_robot.brain.navigate_admission import (
    NAVIGATE_TO_FORBIDDEN_ADMISSION_PRECONDITIONS,
    NAVIGATE_TO_REQUIRED_PRECONDITIONS,
    assert_searchable_admission_contract,
)
from parcel_robot.brain.validator import SkillContractRegistry


def test_registry_navigate_to_matches_searchable_pin() -> None:
    contract = SkillContractRegistry.default().get("NavigateTo")
    assert_searchable_admission_contract(contract.required_preconditions)


def test_assert_rejects_visibility_requirement() -> None:
    with pytest.raises(AssertionError, match="searchable"):
        assert_searchable_admission_contract(
            NAVIGATE_TO_REQUIRED_PRECONDITIONS
            | NAVIGATE_TO_FORBIDDEN_ADMISSION_PRECONDITIONS
        )


def test_assert_rejects_missing_sensor_precondition() -> None:
    with pytest.raises(AssertionError, match="missing searchable"):
        assert_searchable_admission_contract({"camera_fresh", "base_available"})
