"""O3: SearchOwner wall-clock budget freezes while paused."""

from __future__ import annotations

from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.navigation.search_owner import SearchOwnerConfig, SearchOwnerController


def _obs(t: float) -> SimObservation:
    return SimObservation(
        timestamp=t,
        robot=RobotPose(0.0, 0.0, 0.0, 0.0),
        owner=OwnerTrack("none", 0.0, 0.0, False, 0.0),
        nearest_obstacle_m=5.0,
        nearest_person_m=None,
        emergency_stopped=False,
        backend="test",
    )


def test_pause_freezes_wall_clock_budget() -> None:
    ctrl = SearchOwnerController(
        SearchOwnerConfig(max_search_s=5.0, goto_timeout_s=2.0, sweep_timeout_s=2.0)
    )
    ctrl.start(last_x=1.0, last_y=0.0, lost_at_s=0.0, now=0.0)
    ctrl.step(_obs(0.5), now=0.5)
    ctrl.pause(now=1.0)
    assert ctrl.paused
    assert ctrl.snapshot()["paused"] is True
    decision = ctrl.step(_obs(20.0), now=20.0)
    assert decision.reason == "search_paused"
    assert not decision.done
    ctrl.resume(now=20.0)
    decision = ctrl.step(_obs(20.5), now=20.5)
    assert decision.elapsed_s < 5.0
    assert decision.outcome != "gave_up"
