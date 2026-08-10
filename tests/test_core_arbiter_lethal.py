"""S-B: fail-closed mixed-lethal waypoint predicate (core helper)."""

from __future__ import annotations

from parcel_robot.core.arbiter import waypoints_trigger_lethal_veto


def _lethal_x_gt_9(x: float, y: float) -> bool:
    del y
    return x > 9.0


def test_empty_waypoints_do_not_veto() -> None:
    assert waypoints_trigger_lethal_veto(_lethal_x_gt_9, None) is False
    assert waypoints_trigger_lethal_veto(_lethal_x_gt_9, ()) is False


def test_all_lethal_waypoints_veto() -> None:
    assert (
        waypoints_trigger_lethal_veto(
            _lethal_x_gt_9,
            ((10.0, 0.0), (11.0, 0.0)),
        )
        is True
    )


def test_mixed_lethal_waypoints_veto_fail_closed() -> None:
    """Old all() rule let this through; harden requires any() veto."""

    assert (
        waypoints_trigger_lethal_veto(
            _lethal_x_gt_9,
            ((10.0, 0.0), (1.0, 0.0)),
        )
        is True
    )


def test_all_safe_waypoints_do_not_veto() -> None:
    assert (
        waypoints_trigger_lethal_veto(
            _lethal_x_gt_9,
            ((1.0, 0.0), (2.0, 0.0)),
        )
        is False
    )
