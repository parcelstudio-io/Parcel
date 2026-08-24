"""``parcel-unitree-control`` — the commissioning-only CLI (card W0-B).

Rewritten with the CLI it now drives. Before this card the tool called
``build_unitree_sport_control_manager``, which refuses to build until the four
flags a commissioning run exists to establish are already true; the single test
that lived here pinned one shutdown property of that dead path. That property —
**a failed run still tears down and still leaves evidence behind** — is carried
forward as ``test_a_latched_run_still_writes_its_record_and_fails_the_process``.

No test here constructs a vendor object: the session and observer builders are
replaced at the module boundary, which is the only place this CLI could reach
hardware.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from parcel_robot import unitree_control
from parcel_robot.commissioning.limits import (
    SETTLED_LINEAR_MPS,
    SETTLED_YAW_RAD_S,
    CommissioningAxis,
    CommissioningLatchedError,
    LatchReason,
)
from parcel_robot.commissioning.record import (
    AxisSignEvidence,
    CommissioningRecordV1,
    ObservationEvidence,
    ObservedDirection,
    RecordOutcome,
    StopEvidence,
)
from parcel_robot.safety import SafetyLimits


class _FakeStore:
    def section(self, name: str) -> dict:
        assert name == "control"
        return {"unitree_sport": {"state_velocity_frame": "odom"}}

    def safety_limits(self) -> SafetyLimits:
        return SafetyLimits()


class _FakeSession:
    """Stands in for a CommissioningSession without any vendor transport."""

    def __init__(self, *, latch_on_axis: CommissioningAxis | None = None) -> None:
        self.started = 0
        self.closed = 0
        self.steps: list[tuple[CommissioningAxis, float, float, ObservedDirection]] = []
        self.latched = False
        self.observation: ObservationEvidence | None = None
        self._latch_on_axis = latch_on_axis

    def adopt_observation(self, observation: ObservationEvidence) -> None:
        self.observation = observation

    def start(self) -> None:
        self.started += 1

    def run_axis_step(
        self,
        axis: CommissioningAxis,
        speed: float,
        duration_s: float,
        *,
        observed_direction: ObservedDirection = ObservedDirection.UNCERTAIN,
    ) -> AxisSignEvidence:
        self.steps.append((axis, speed, duration_s, observed_direction))
        if axis is self._latch_on_axis:
            self.latched = True
            raise CommissioningLatchedError(
                LatchReason.STOP_NOT_CONFIRMED,
                "seeded: the stop was never confirmed",
            )
        return AxisSignEvidence(
            axis=axis,
            commanded_speed=speed,
            samples=10,
            mean_measured_speed=speed * 0.8,
            mean_cross_axis_speed=0.0,
            mean_yaw_rad=0.6,
            evidence_floor=(
                SETTLED_YAW_RAD_S if axis.is_angular else SETTLED_LINEAR_MPS
            ),
            observed_direction=observed_direction,
            declared_velocity_frame="odom",
        )

    def record(
        self,
        *,
        performed_at: str,
        software_revision: str = "",
        artifact_paths=(),
    ) -> CommissioningRecordV1:
        del artifact_paths
        # Mirrors the real contract: record() finalizes the session first.
        self.close()
        return CommissioningRecordV1(
            record_id="cli-record",
            operator="operator-under-test",
            robot_serial="RIG-0001",
            performed_at=performed_at,
            outcome=RecordOutcome.FAILED if self.latched else RecordOutcome.ABORTED,
            failure_reason="seeded" if self.latched else "",
            declared_velocity_frame="odom",
            observed_modes=(3,),
            observation=self.observation,
            stop=StopEvidence(
                request_latency_s=0.003,
                settle_latency_s=0.05,
                distance_m=0.002,
                distance_method="odom_delta",
                settled_linear_mps=SETTLED_LINEAR_MPS,
                settled_yaw_rad_s=SETTLED_YAW_RAD_S,
                confirmed=not self.latched,
            ),
            software_revision=software_revision,
        )

    def close(self) -> None:
        self.closed += 1


class _FakeObserver:
    def __init__(self, *, refuse: Exception | None = None) -> None:
        self.started = 0
        self.closed = 0
        self._refuse = refuse

    def start(self) -> None:
        self.started += 1

    def observe(self, *, min_samples: int, timeout_s: float) -> ObservationEvidence:
        del min_samples, timeout_s
        if self._refuse is not None:
            raise self._refuse
        return ObservationEvidence(
            samples=20,
            duration_s=1.0,
            modes_seen=(1, 3),
            declared_velocity_frame="odom",
            state_source="fake",
        )

    def close(self) -> None:
        self.closed += 1


def _install(monkeypatch, *, session=None, observer=None):
    monkeypatch.setattr(unitree_control, "ConfigStore", lambda _: _FakeStore())
    if session is not None:
        monkeypatch.setattr(
            unitree_control,
            "build_unitree_sport_commissioning_session",
            lambda *args, **kwargs: session,
        )
    if observer is not None:
        monkeypatch.setattr(
            unitree_control,
            "build_unitree_sport_observer",
            lambda *args, **kwargs: observer,
        )


ALL_ACKS = ("support_rig", "fenced_area", "estop_operator")


def _run_args(
    tmp_path: Path,
    *extra: str,
    acks: tuple[str, ...] = ALL_ACKS,
    modes: tuple[str, ...] = ("3",),
) -> list[str]:
    args = [
        "run",
        "--operator",
        "operator-under-test",
        "--robot-serial",
        "RIG-0001",
    ]
    for ack in acks:
        args += ["--ack", ack]
    for mode in modes:
        args += ["--mode", mode]
    args += [
        "--journal",
        str(tmp_path / "journal.jsonl"),
        "--record-out",
        str(tmp_path / "record.json"),
        *extra,
    ]
    return args


# --------------------------------------------------------------- refusals


def test_run_requires_the_arm_flag(tmp_path, monkeypatch) -> None:
    session = _FakeSession()
    _install(monkeypatch, session=session)
    with pytest.raises(SystemExit) as excinfo:
        unitree_control.main(_run_args(tmp_path))
    assert excinfo.value.code == 2
    assert session.started == 0


@pytest.mark.parametrize("dropped", ALL_ACKS)
def test_run_requires_every_acknowledgement(tmp_path, monkeypatch, dropped) -> None:
    session = _FakeSession()
    _install(monkeypatch, session=session)
    remaining = tuple(ack for ack in ALL_ACKS if ack != dropped)
    with pytest.raises(SystemExit) as excinfo:
        unitree_control.main(_run_args(tmp_path, "--arm", acks=remaining))
    assert excinfo.value.code == 2
    assert session.started == 0


def test_run_requires_observed_modes(tmp_path, monkeypatch) -> None:
    session = _FakeSession()
    _install(monkeypatch, session=session)
    with pytest.raises(SystemExit) as excinfo:
        unitree_control.main(_run_args(tmp_path, "--arm", modes=()))
    assert excinfo.value.code == 2
    assert session.started == 0


def test_run_refuses_a_malformed_observed_direction(tmp_path, monkeypatch) -> None:
    _install(monkeypatch, session=_FakeSession())
    with pytest.raises(SystemExit) as excinfo:
        unitree_control.main(
            _run_args(tmp_path, "--arm", "--observed-direction", "vx=sideways")
        )
    assert excinfo.value.code == 2


# ------------------------------------------------------------------ running


def test_run_commissions_one_axis_at_a_time_inside_the_band(tmp_path, monkeypatch) -> None:
    session = _FakeSession()
    _install(monkeypatch, session=session)
    exit_code = unitree_control.main(
        _run_args(
            tmp_path,
            "--arm",
            "--observed-direction",
            "vx=forward",
            "--observed-direction",
            "vy=left",
            "--observed-direction",
            "vyaw=counterclockwise",
        )
    )
    assert exit_code == 0
    assert session.started == 1
    assert [step[0] for step in session.steps] == list(CommissioningAxis)
    assert [step[3] for step in session.steps] == [
        ObservedDirection.FORWARD,
        ObservedDirection.LEFT,
        ObservedDirection.COUNTERCLOCKWISE,
    ]
    # Defaults sit inside the band the module derives, not at its edges.
    assert 0.02 <= session.steps[0][1] <= 0.05
    record = json.loads((tmp_path / "record.json").read_text())
    assert record["schema"] == "parcel.commissioning.record.v1"


def test_run_prints_the_operator_instructions_before_anything_is_built(
    tmp_path, monkeypatch, capsys
) -> None:
    session = _FakeSession()
    _install(monkeypatch, session=session)
    unitree_control.main(_run_args(tmp_path, "--arm"))
    out = capsys.readouterr().out
    for token in ("support_rig", "fenced_area", "estop_operator", "physical E-stop"):
        assert token in out


def test_a_latched_run_still_writes_its_record_and_fails_the_process(
    tmp_path, monkeypatch, capsys
) -> None:
    """Ported property: a failed run tears down and leaves its evidence behind."""

    session = _FakeSession(latch_on_axis=CommissioningAxis.VY)
    _install(monkeypatch, session=session)
    exit_code = unitree_control.main(_run_args(tmp_path, "--arm"))
    assert exit_code == 1
    assert session.closed == 1
    assert [step[0] for step in session.steps] == [
        CommissioningAxis.VX,
        CommissioningAxis.VY,
    ]
    record = json.loads((tmp_path / "record.json").read_text())
    assert record["outcome"] == RecordOutcome.FAILED.value
    assert record["derived"]["authorizes_configuration"] is False
    assert "commissioning stopped" in capsys.readouterr().out


def test_run_can_commission_a_single_named_axis(tmp_path, monkeypatch) -> None:
    session = _FakeSession()
    _install(monkeypatch, session=session)
    unitree_control.main(_run_args(tmp_path, "--arm", "--axis", "vyaw"))
    assert [step[0] for step in session.steps] == [CommissioningAxis.VYAW]


# ----------------------------------------------------------------- observing


def test_observe_is_read_only_and_reports_modes(tmp_path, monkeypatch, capsys) -> None:
    observer = _FakeObserver()
    _install(monkeypatch, observer=observer)
    out_path = tmp_path / "observation.json"
    exit_code = unitree_control.main(["observe", "--out", str(out_path)])
    assert exit_code == 0
    assert observer.started == 1
    assert observer.closed == 1
    out = capsys.readouterr().out
    assert '"modes_seen"' in out
    assert "--mode 1 --mode 3" in out
    written = json.loads(out_path.read_text())
    assert written["modes_seen"] == [1, 3]


def test_run_carries_the_observation_into_the_record(tmp_path, monkeypatch) -> None:
    """Without this the CLI could never produce an authorizing record."""

    observer = _FakeObserver()
    session = _FakeSession()
    _install(monkeypatch, session=session, observer=observer)
    observation_path = tmp_path / "observation.json"
    unitree_control.main(["observe", "--out", str(observation_path)])

    unitree_control.main(
        _run_args(tmp_path, "--arm", "--observation", str(observation_path))
    )
    assert session.observation is not None
    assert session.observation.samples == 20
    record = json.loads((tmp_path / "record.json").read_text())
    assert record["observation"]["samples"] == 20


def test_run_refuses_modes_the_observation_never_saw(tmp_path, monkeypatch) -> None:
    observer = _FakeObserver()
    session = _FakeSession()
    _install(monkeypatch, session=session, observer=observer)
    observation_path = tmp_path / "observation.json"
    unitree_control.main(["observe", "--out", str(observation_path)])

    with pytest.raises(SystemExit) as excinfo:
        unitree_control.main(
            _run_args(
                tmp_path,
                "--arm",
                "--observation",
                str(observation_path),
                modes=("7",),
            )
        )
    assert excinfo.value.code == 2
    assert session.started == 0


def test_run_refuses_a_missing_observation_file(tmp_path, monkeypatch) -> None:
    session = _FakeSession()
    _install(monkeypatch, session=session)
    with pytest.raises(SystemExit) as excinfo:
        unitree_control.main(
            _run_args(tmp_path, "--arm", "--observation", str(tmp_path / "absent.json"))
        )
    assert excinfo.value.code == 2
    assert session.started == 0


# ------------------------------------------------------------------- review


def _write_record(path: Path, **overrides) -> CommissioningRecordV1:
    payload = {
        "record_id": "cli-review",
        "operator": "operator-under-test",
        "robot_serial": "RIG-0001",
        "performed_at": "2026-08-12T12:00:00Z",
        "outcome": RecordOutcome.ABORTED,
    }
    payload.update(overrides)
    record = CommissioningRecordV1(**payload)
    record.save(path)
    return record


def test_review_refuses_the_operator_reviewing_their_own_record(tmp_path) -> None:
    path = tmp_path / "record.json"
    _write_record(path)
    with pytest.raises(SystemExit) as excinfo:
        unitree_control.main(
            [
                "review",
                "--record",
                str(path),
                "--reviewer",
                "operator-under-test",
                "--accept",
            ]
        )
    assert excinfo.value.code == 2


def test_review_of_an_incomplete_record_still_authorizes_nothing(tmp_path, capsys) -> None:
    path = tmp_path / "record.json"
    _write_record(path)
    exit_code = unitree_control.main(
        ["review", "--record", str(path), "--reviewer", "second-person", "--accept"]
    )
    assert exit_code == 1
    assert "authorizes nothing" in capsys.readouterr().out
    reviewed = CommissioningRecordV1.load(path)
    assert reviewed.review is not None
    assert not reviewed.authorizes_configuration()


def test_apply_refuses_an_unreviewed_record(tmp_path, monkeypatch, capsys) -> None:
    _install(monkeypatch)
    path = tmp_path / "record.json"
    _write_record(path)
    exit_code = unitree_control.main(["apply", "--record", str(path)])
    assert exit_code == 1
    assert "refused" in capsys.readouterr().out
