"""O3: DirectiveNavigator pause freezes tick budgets; Mission.status PAUSED."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from parcel_robot.navigation.base import MissionStatus, NavObservation
from parcel_robot.navigation.pipeline import DirectiveNavigator

REPO = Path(__file__).resolve().parents[1]


def _obs(x: float = 0.0, y: float = 0.0) -> NavObservation:
    return NavObservation(
        position=(x, y, 0.0),
        heading_deg=0.0,
        lidar=np.full(72, 5.0, dtype=np.float32),
        nearest_obstacle_m=5.0,
        nearest_person_m=None,
    )


def test_pause_freezes_watchdog_and_retains_mission() -> None:
    nav = DirectiveNavigator.from_config(REPO / "configs/navigation/default.yaml")
    mission = nav.start("go to the kitchen")
    assert mission.status_value() in {"running", "searching"}
    for _ in range(5):
        nav.step(_obs())
    before = nav._steps_without_progress
    nav.pause()
    assert nav.paused
    assert mission.status_value() == "paused"
    assert mission.status_value() == MissionStatus.PAUSED.value
    assert nav.snapshot()["paused"] is True
    for _ in range(50):
        cmd = nav.step(_obs())
        assert cmd.note == "mission_paused"
    assert nav._steps_without_progress == before
    nav.resume()
    assert not nav.paused
    assert mission.status_value() != "paused"
    assert nav.mission is mission


def test_stop_destroys_mission_unlike_pause() -> None:
    nav = DirectiveNavigator.from_config(REPO / "configs/navigation/default.yaml")
    nav.start("go to the kitchen")
    nav.pause()
    nav.stop()
    assert nav.mission is None
    assert not nav.paused
