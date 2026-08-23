"""Card HW-2 `go2-backend` (`scrum/20260822/task_40`) — the physical eye.

Rows are `scrum/20260822/task_40/PREREGISTRATION.md`'s, by name. What every
group is for, in one line each:

* **A** — the backend itself, against the recorded Stage-0 fixture, through the
  REAL `navigation/reactive_safety.py` functions. A local copy of
  `scan_present` would make this file pass while the product read something
  else, which is the defect this suite exists to catch.
* **B** — physical scan authority at the health join, through
  `runtime._evaluate_dispatch_input_health` on a REAL `RobotRuntime`. Nothing
  patches `evidence_origin`, `scan_evidence_from_observation`, the requirements
  tables, or the sources' declared origins.
* **C** — the one branch at `web_panel.build_runtime`, including the flag-off
  identity the whole card rests on.
* **D** — `unitree_control observe --duration` (handoff HO-6 from HW-8).
* **E** — the sixth stopping-envelope term, and the pin that HW-6's five-term
  shape did not move.

No simulator is started anywhere in this file and no network socket is opened:
the fixture is a recording and the live adapter's transports are injected.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from parcel_robot.backends import MujocoSocketBackend
from parcel_robot.backends.base import (
    OwnerTrack,
    RobotPose,
    SimObservation,
    SimulatorBackend,
)
from parcel_robot.backends.go2 import (
    Go2Backend,
    Go2BackendError,
    Go2MotionRefused,
    Go2ReplayError,
    Go2SdkUnavailable,
    Go2StateUnavailable,
    LiveGo2Sources,
    RecordedStage0Source,
    state_from_sport_mode_state,
)
from parcel_robot.bridge import timing
from parcel_robot.control.adapters import BackendVelocityController
from parcel_robot.core.input_health import (
    CommissionedScanSource,
    EvidenceOrigin,
    HealthAction,
    RequiredInput,
    ScanDatum,
)
from parcel_robot.models import Pose, VelocityCommand
from parcel_robot.navigation.reactive_safety import (
    ReactiveSafetyPolicy,
    apply_reactive_safety,
    scan_present,
)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "data" / "hw2_stage0_replay.jsonl"

#: The fixture's scene, from its generator
#: (`scrum/20260822/task_40/evidence/make_stage0_fixture.py`): six 10 Hz frames
#: of a wall closing from 2.00 m to 0.85 m while the dog stands still. The
#: footprint radius 0.32 m comes off each one
#: (`lidar/band.py:nearest_obstacle_from_scan`), and `configs/robot.yaml:312`
#: puts the thresholds at slow 1.2 m and stop 0.65 m.
WALL_DISTANCES_M = (2.00, 2.00, 1.60, 1.20, 0.95, 0.85)
EXPECTED_CLEARANCES_M = (1.68, 1.68, 1.28, 0.88, 0.63, 0.53)
EXPECTED_PROXIMITY = ("clear", "clear", "clear", "slowing", "stopped", "stopped")


class FakeClock:
    """A monotonic clock the test moves by hand. Not a product seam: both
    `RecordedStage0Source` and `Go2Backend` already take `clock=` because a
    replay's cursor is defined against one."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> float:
        self.t += float(seconds)
        return self.t


def _replay_backend(clock: FakeClock | None = None) -> tuple[Go2Backend, FakeClock]:
    clock = clock or FakeClock()
    source = RecordedStage0Source(FIXTURE, clock=clock)
    backend = Go2Backend(source, clock=clock)
    backend.start()
    return backend, clock


def _fixture_records() -> tuple[list[dict[str, Any]], list[bytes]]:
    lines = FIXTURE.read_text(encoding="utf-8").splitlines()
    records = [json.loads(line) for line in lines[1:] if line.strip()]
    states = [r["sport_mode_state"] for r in records if r["channel"] == "rt/sportmodestate"]
    frames = [bytes.fromhex(r["frame_hex"]) for r in records if r["channel"].endswith("points")]
    return states, frames


class FakeSportModeSubscriber:
    """Stands in for the vendor DDS subscriber — and ONLY for it.

    `UnitreeSportStateSource` already exposes `subscriber_factory`/
    `message_type` for exactly this reason: the vendor boundary is the one
    thing a desktop can honestly stand in for. It replays the same recorded
    samples the fixture holds, so the two paths see identical numbers.
    """

    name = "fake_rt_sportmodestate"

    def __init__(self, states: list[dict[str, Any]], clock: FakeClock) -> None:
        self._states = states
        self._clock = clock
        self._index = 0

    def start(self) -> None:
        return None

    def close(self) -> None:
        return None

    def latest(self):
        self._index += 1
        payload = self._states[min(self._index, len(self._states)) - 1]
        return state_from_sport_mode_state(
            payload, received_at=self._clock(), sequence=self._index
        ).state


class FakeLivoxSocket:
    """A bound NON-BLOCKING UDP socket's `recv`, and nothing else.

    `receive_frames` owns no socket by design (HW-3), so this needs no network.
    It answers `gettimeout()` because the real contract is answerable: F3 makes
    `LiveGo2Sources` refuse a blocking socket, and a double that could not be
    asked would be a double that dodges the check.
    """

    def __init__(self, payloads: list[bytes]) -> None:
        self._queue = list(payloads)
        self.remaining_after_error = 0

    def gettimeout(self) -> float:
        return 0.0

    def recv(self, _max_bytes: int) -> bytes:
        if not self._queue:
            raise BlockingIOError("no datagram ready")
        return self._queue.pop(0)

    def push(self, *payloads: bytes) -> None:
        self._queue.extend(payloads)

    def __len__(self) -> int:
        return len(self._queue)


def _live_sources(frames: int = 1, **kwargs: Any) -> tuple[LiveGo2Sources, FakeClock, Any]:
    clock = FakeClock()
    states, payloads = _fixture_records()
    sock = FakeLivoxSocket(payloads[:frames])
    source = LiveGo2Sources(
        state_source=FakeSportModeSubscriber(states, clock),
        socket=sock,
        clock=clock,
        **kwargs,
    )
    return source, clock, sock


def _live_backend(frames: int = 1) -> tuple[Go2Backend, FakeClock]:
    source, clock, _sock = _live_sources(frames)
    backend = Go2Backend(source, clock=clock)
    backend.start()
    return backend, clock


def _config_tree(
    tmp_path: Path,
    *,
    backend: dict[str, Any] | None = None,
    require_physical: bool = True,
    overlay_backend: dict[str, Any] | None = None,
    profile: str | None = None,
) -> Path:
    """A real base config (a copy of the shipped one) plus an optional overlay.

    The `backend:` block is written into the BASE here rather than introduced
    by an overlay: this helper was written before HW-5's
    `OVERLAY_INTRODUCIBLE_KEYS` entry landed, and writing it into the base is
    what let C1–C4 exercise the read site without depending on another card.
    **Row C5 proves the OVERLAY path itself** (and the verifier re-proved it
    through `build_runtime` with HW-5's key in place), so both routes are
    covered: this one keeps the read-site rows independent of HW-5's timing.
    """

    document = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    if backend is not None:
        document["backend"] = backend
    document["safety"]["require_physical_inputs"] = bool(require_physical)
    tmp_path.mkdir(parents=True, exist_ok=True)
    base = tmp_path / "robot.yaml"
    base.write_text(yaml.safe_dump(document), encoding="utf-8")
    if profile is not None and overlay_backend is not None:
        overlay = tmp_path / f"robot.{profile}.yaml"
        overlay.write_text(yaml.safe_dump({"backend": overlay_backend}), encoding="utf-8")
    return base


def _build_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: str | None = None,
    **tree: Any,
):
    """`web_panel.build_runtime` — the product launcher, not a stand-in.

    The only environment touched is `PARCEL_MEMORY_PATH` (so the owner's
    `parcel_memory.sqlite3` is never opened, card R27) and `PARCEL_PROFILE`,
    which is how a profile is selected.
    """

    base = _config_tree(tmp_path, profile=profile, **tree)
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    if profile is None:
        monkeypatch.delenv("PARCEL_PROFILE", raising=False)
    else:
        monkeypatch.setenv("PARCEL_PROFILE", profile)

    from parcel_robot import web_panel

    return web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)


class _Producer:
    """A scan producer whose next datum the test sets by hand."""

    name = "test_producer"

    def __init__(self) -> None:
        self.next: ScanDatum | None = None

    def scan_datum_for(self, key: object) -> ScanDatum | None:
        del key
        return self.next


def _faults(verdict) -> set[tuple[str, str]]:
    return {(fault.required_input.value, fault.reason) for fault in verdict.faults}


def _scan_fault_reasons(verdict) -> set[str]:
    return {fault.reason for fault in verdict.faults if fault.required_input is RequiredInput.SCAN}


# ===========================================================================
# A — the backend against the recording
# ===========================================================================


def test_a1_scan_present_from_the_recorded_fixture() -> None:
    """Row A1. `observe()` -> a `SimObservation` the REAL `scan_present` believes."""

    backend, clock = _replay_backend()
    observation = backend.observe()

    assert isinstance(observation, SimObservation)
    assert observation.backend == "go2_stage0_replay"  # F5: the SOURCE's name
    assert len(observation.lidar_ranges) == 360
    assert scan_present(observation) is True
    datum = backend.latest_scan()
    assert datum is not None
    assert datum.points_seen > 0
    assert datum.populated_bins >= 1
    assert datum.frame_id == "base_link"
    # The ODOM pose really comes from the recorded `rt/sportmodestate`, not from
    # a default: the fixture stands at z = 0.32 (standing height), yaw 0.
    assert observation.robot.z == pytest.approx(0.32)
    assert observation.robot.x == pytest.approx(0.0)
    # And the two clocks stay apart: the health join reads the HOST receipt.
    assert observation.timestamp == pytest.approx(clock.t)
    assert datum.source_time_ns is not None and datum.source_time_ns > 1_600_000_000_000_000_000


def test_a2_reactive_safety_reads_the_band_across_the_whole_recording() -> None:
    """Row A2. The wall closes; the REAL gate says clear -> slowing -> stopped.

    Every number here is derived, not chosen: the clearances are the fixture's
    wall distances minus the 0.32 m footprint radius
    (`lidar/band.py:nearest_obstacle_from_scan`), and the verdicts are what
    `configs/robot.yaml:312`'s 1.2 / 0.65 m thresholds make of them.
    """

    clock = FakeClock()
    backend, _ = _replay_backend(clock)
    policy = ReactiveSafetyPolicy()
    seen: list[tuple[float, str]] = []
    for index in range(len(WALL_DISTANCES_M)):
        clock.t = 1000.0 + index * 0.10001
        observation = backend.observe()
        command, proximity = apply_reactive_safety(
            VelocityCommand(vx=0.25), observation, policy=policy, now=clock.t
        )
        assert observation.nearest_obstacle_m is not None
        seen.append((round(observation.nearest_obstacle_m, 3), proximity))
        if proximity == "stopped":
            assert command.vx == pytest.approx(0.0)

    assert [clearance for clearance, _ in seen] == list(EXPECTED_CLEARANCES_M)
    assert [proximity for _, proximity in seen] == list(EXPECTED_PROXIMITY)


def test_a2_the_travel_bearing_is_the_states_own_velocity() -> None:
    """Row A2, second half: `travel_bearing_rad(vx, vy)` is passed, not invented."""

    from parcel_robot.lidar import travel_bearing_rad

    states, frames = _fixture_records()
    moving = dict(states[0])
    moving["velocity"] = [0.0, 0.4, 0.0]
    clock = FakeClock()

    class OneSample:
        origin = EvidenceOrigin.PHYSICAL
        fixture_label = ""

        def latest(self):
            return state_from_sport_mode_state(moving, received_at=clock(), sequence=1).state

        def drain(self):
            from parcel_robot.lidar import parse_point_frame

            return [parse_point_frame(frames[0])]

    backend = Go2Backend(OneSample(), clock=clock)
    observation = backend.observe()
    # Body-frame vy = +0.4 with yaw 0 -> bearing +pi/2, which is what the
    # corridor filter is handed. The wall is dead ahead, so the corridor
    # (half-angle 1.15 rad) excludes it and the globally nearest wins — the
    # same fallback `sim.py:select_relevant_obstacle` has.
    assert travel_bearing_rad(0.0, 0.4) == pytest.approx(1.5707963, abs=1e-6)
    assert observation.nearest_obstacle_m == pytest.approx(1.68, abs=1e-9)
    assert observation.nearest_obstacle_bearing_rad == pytest.approx(0.0, abs=1e-9)


def test_a3_empty_band_is_published_as_no_scan() -> None:
    """Row A3. HW-3's branch: `ranges_m == ()` is NOT a scan of nothing.

    Seed S1 (copy the empty `BandScan` across unconditionally) reddens this.
    """

    backend, clock = _replay_backend()
    backend.observe()  # consume what has arrived
    clock.advance(0.0)
    observation = backend.observe()  # nothing new drained

    assert observation.lidar_ranges == ()
    assert observation.nearest_obstacle_m is None
    assert observation.nearest_obstacle_bearing_rad is None
    assert scan_present(observation) is False
    assert backend.latest_scan() is None
    assert backend.latest_scan_age_s() is None
    command, proximity = apply_reactive_safety(
        VelocityCommand(vx=0.3), observation, policy=ReactiveSafetyPolicy(), now=clock.t
    )
    assert proximity == "stopped"
    assert command.vx == pytest.approx(0.0)


def test_a4_motion_is_refused_with_the_motion_md_citation() -> None:
    """Row A4. The backend is an eye. Seed S4 (a no-op `move`) reddens this."""

    backend, _ = _replay_backend()
    calls = (
        ("move", lambda: backend.move(VelocityCommand(vx=0.05))),
        ("pose", lambda: backend.pose(Pose(name="sit", joints={}))),
        ("trajectory", lambda: backend.trajectory(object())),
        ("move_owner", lambda: backend.move_owner(0.1, 0.0)),
        ("set_owner_visible", lambda: backend.set_owner_visible(True)),
    )
    for name, call in calls:
        with pytest.raises(Go2MotionRefused) as caught:
            call()
        assert isinstance(caught.value, NotImplementedError), name
        assert "MOTION.md" in str(caught.value), name
        assert "sole-writer gateway" in str(caught.value), name


def test_a5_the_stop_path_never_raises() -> None:
    """Row A5. `control/adapters.py` calls `stop()` on FOUR paths, one of them
    the emergency stop. An eye that threw there would turn a safe no-op into an
    exception on the safety path."""

    backend, _ = _replay_backend()
    assert backend.stop() is None
    assert backend.emergency_stop() is None
    assert backend.clear_emergency_stop() is None
    assert backend.expression({"neck": 0.1}) is None

    controller = BackendVelocityController(backend)
    controller.activate()
    controller.stop("test")
    controller.emergency_stop()
    controller.clear_emergency_stop()
    controller.close()


def test_a6_no_vendor_import_at_module_scope() -> None:
    """Row A6. Proven in a FRESH interpreter, because `sys.modules` in this one
    is already full of everything the suite has ever imported.

    THREE THINGS ARE PINNED, and the second and third were found by measurement,
    not foresight:

    1. the VENDOR claim (design §3): `unitree_sdk2py` must never share a process
       with `rclpy`, because CycloneDDS is process-global, so neither may arrive
       merely by importing a backend;
    2. `parcel_robot.core` stays out. `backends/__init__.py` imports `go2` and
       `parcel_robot.commissioning` imports `backends`, so a module-scope
       `from parcel_robot.core.input_health import ...` drags
       `core.motion_shaping` -> `navigation` -> `brain`/`instructnav` into the
       ARMED commissioning tool and reddens W0-B's own guard
       (`tests/test_w0b_commissioning.py`). It did, once, during this card;
    3. `parcel_robot.control` stays out, which is why `RobotMotionState` is
       imported inside the one function that constructs one.

    `socket` DOES arrive, from the sibling `backends.mujoco` -> `sim_ipc`, which
    `backends/__init__.py` has always imported. It is recorded rather than
    asserted away.
    """

    code = (
        "import sys;"
        "import parcel_robot.backends.go2 as go2;"
        "print([m for m in ('unitree_sdk2py','mujoco','rclpy','numpy') if m in sys.modules]);"
        "print([m for m in ('socket',) if m in sys.modules]);"
        "print(sorted(m for m in sys.modules if m.startswith('parcel_robot.core')"
        " or m.startswith('parcel_robot.control')));"
        "print(go2.GRADED_HISTORY)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "[]", f"a vendor SDK or numpy reached module scope: {result.stdout}"
    assert lines[1] == "['socket']", result.stdout
    assert lines[2] == "[]", f"the heavy packages crept back: {result.stdout}"
    assert lines[3] == "8"


def test_a6_importing_commissioning_stays_light() -> None:
    """A6's second half — W0-B's guard, re-run through THIS card's chain.

    `parcel_robot.commissioning` -> `control.factory` -> `backends` -> `go2`.
    That chain is why this card's import discipline is not cosmetic: the armed
    commissioning tool runs in the motion venv and must not carry the runtime.
    `tests/test_w0b_commissioning.py` owns the assertion; this one names the
    edge HW-2 added, so a regression is attributed here instead of appearing as
    a mysterious W0-B failure.
    """

    code = (
        "import sys;"
        "import parcel_robot.commissioning;"
        "import parcel_robot.backends;"
        "print([m for m in sys.modules if m.startswith('parcel_robot.') and"
        " any(k in m for k in ('runtime','navigation','instructnav','brain'))])"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert result.stdout.strip() == "[]", result.stdout


def test_a6_the_lidar_seam_stays_a_leaf() -> None:
    """A6's other half: HW-3's package is still importable with nothing heavy,
    which is what makes the band filter the same code on the Orin."""

    code = (
        "import sys;"
        "import parcel_robot.lidar;"
        "print([m for m in ('unitree_sdk2py','mujoco','rclpy','numpy','socket')"
        " if m in sys.modules])"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=True,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
    )
    assert result.stdout.strip() == "[]", result.stdout


def test_a7_the_live_adapter_names_the_venv() -> None:
    """Row A7. With no injected transport and no SDK, the refusal is typed and
    says which venv has it — not an `ImportError` three frames down."""

    with pytest.raises(Go2SdkUnavailable) as caught:
        LiveGo2Sources(interface="eth0")
    message = str(caught.value)
    assert "unitree_sdk2py" in message
    assert "MOTION venv" in message
    assert "fixture" in message

    with pytest.raises(Go2SdkUnavailable, match="NIC"):
        LiveGo2Sources()


def test_a8_go2_backend_satisfies_the_simulator_backend_protocol() -> None:
    """Row A8. Structural, against the Protocol's own method list."""

    backend, _ = _replay_backend()
    required = [
        name
        for name in dir(SimulatorBackend)
        if not name.startswith("_") and callable(getattr(SimulatorBackend, name, None))
    ]
    assert "observe" in required and "move" in required
    for name in required:
        assert callable(getattr(backend, name, None)), name
    # `SimulatorBackend` is a plain `Protocol` and NOT `runtime_checkable`,
    # which is why the check above is by method list: `isinstance` against it
    # raises. Pinned, so a later `@runtime_checkable` does not leave this test
    # quietly weaker than it could be.
    with pytest.raises(TypeError, match="runtime_checkable"):
        isinstance(backend, SimulatorBackend)


def test_a9_a_broken_recording_is_refused_rather_than_half_read(tmp_path: Path) -> None:
    """Not a headline row: the fixture reader is evidence-handling code, and
    evidence that does not parse is not evidence."""

    header = json.dumps({"schema": "parcel.stage0_replay.v1"})
    cases = {
        "schema": '{"schema": "parcel.stage0_replay.v2"}',
        "not JSON": "{",
        "unknown channel": header + '\n{"t_s": 0.0, "channel": "rt/lowstate"}',
        "t_s": (
            header
            + '\n{"t_s": 1.0, "channel": "rt/sportmodestate", "sport_mode_state": {}}'
            + '\n{"t_s": 0.5, "channel": "rt/sportmodestate", "sport_mode_state": {}}'
        ),
        "frame_hex is not hex": header + '\n{"t_s": 0.0, "channel": "livox/mid360/points",'
        ' "frame_hex": "zz"}',
        "no rt/sportmodestate samples": header,
    }
    for label, text in cases.items():
        path = tmp_path / "broken.jsonl"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(Go2ReplayError):
            RecordedStage0Source(path)
        assert label  # the label is the reason, kept for the failure message


def test_a10_the_shipped_fixture_says_it_is_synthesised() -> None:
    """The fixture is not a recording of a robot and must never be read as one."""

    source = RecordedStage0Source(FIXTURE)
    header = source.header
    assert header["synthesised"] is True
    assert "NOT A RECORDING OF A ROBOT" in header["note"]
    assert header["generator"].endswith("make_stage0_fixture.py")


# ===========================================================================
# B — physical scan authority at the join
# ===========================================================================


def test_b1a_the_join_does_not_believe_a_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row B1a (Amendment 1). Through `web_panel.build_runtime`, zero patches.

    A recorded fixture declares REPLAY *because it reads a file*, and REPLAY is
    a synthetic origin, so under `requirements_requiring_physical_inputs()` it
    latches exactly as before. Passing through the new typed seam does not
    launder a recording into a sensor — that is the whole safety claim.
    """

    runtime = _build_runtime(
        tmp_path,
        monkeypatch,
        backend={"kind": "go2", "fixture": str(FIXTURE)},
    )
    try:
        assert runtime.backend.scan_evidence_source.origin is EvidenceOrigin.REPLAY
        runtime.backend.start()
        observation = runtime.backend.observe()
        assert scan_present(observation) is True
        verdict = runtime._evaluate_dispatch_input_health(
            observation, now=observation.timestamp + 0.01
        )
        assert "sim_fixture_forbidden" in _scan_fault_reasons(verdict)
        assert verdict.action is HealthAction.LATCHED_STOP
    finally:
        runtime.close()


def test_b1b_the_join_no_longer_latches_the_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row B1b (Amendment 1) — THE authority row.

    The runtime is built by `RobotRuntime(config_path, backend)`, which is the
    call `web_panel.build_runtime` makes at `web_panel.py:~728` /
    `runtime.py:1498`. The backend is the LIVE adapter with its vendor DDS
    subscriber and UDP socket injected — the same seam
    `UnitreeSportStateSource(subscriber_factory=…)` already exposes, and the
    only double anywhere in this test. Nothing patches `evidence_origin`,
    `scan_evidence_from_observation`, the requirements table, or any declared
    origin.

    Seed S2 (drop the `declared_origin(...) is PHYSICAL` test) reddens the pair
    B1b + B7.
    """

    from parcel_robot.runtime import RobotRuntime

    base = _config_tree(tmp_path, require_physical=True)
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    backend, clock = _live_backend()
    runtime = RobotRuntime(base, backend)
    try:
        assert backend.scan_evidence_source.origin is EvidenceOrigin.PHYSICAL
        assert backend.scan_evidence_source.fixture_label is None
        observation = backend.observe()
        assert scan_present(observation) is True
        verdict = runtime._evaluate_dispatch_input_health(observation, now=clock.t + 0.01)

        assert "sim_fixture_forbidden" not in _scan_fault_reasons(verdict)
        assert _scan_fault_reasons(verdict) == set(), _faults(verdict)
        # And the evidence really is the typed source's, not the observation's.
        evidence = backend.scan_evidence_source.evidence(observation)
        assert evidence is not None
        assert evidence.origin is EvidenceOrigin.PHYSICAL
        assert evidence.fixture_label is None
    finally:
        runtime.close()


def test_b2_a_sim_scan_still_latches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Row B2 — the control. A simulator observation is unaffected by this card."""

    runtime = _build_runtime(tmp_path, monkeypatch, backend=None)
    try:
        assert type(runtime.backend) is MujocoSocketBackend
        observation = SimObservation(
            timestamp=100.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend="mujoco",
            lidar_ranges=tuple([2.0] * 360),
            lidar_angle_min_rad=-3.141592653589793,
            lidar_angle_increment_rad=0.017453292519943295,
            lidar_range_min_m=0.05,
            lidar_range_max_m=30.0,
        )
        verdict = runtime._evaluate_dispatch_input_health(observation, now=100.01)
        assert "sim_fixture_forbidden" in _scan_fault_reasons(verdict)
        assert verdict.action is HealthAction.LATCHED_STOP
    finally:
        runtime.close()


def test_b3_pose_authority_is_not_in_this_card(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row B3, RE-PINNED by card AWARE-1 (scrum/20260823/task_4) — the pose
    seam this row measured the ABSENCE of is now wired.

    CAUSE OF THE RE-PIN, stated so nobody has to reconstruct it. This row was
    written by HW-2 to assert what HW-2 did not buy: with the scan believed,
    the verdict was still `LATCHED_STOP`, for POSE, which `evidence_origin`
    stamped SIMULATION. Card SENSE-1 (scrum/20260823/task_3) then built
    `CommissionedPoseSource` — the scan seam's twin — and proved its rows AT
    THE SEAM, but could not read it at the join because `runtime.py` was that
    card's MUST-NOT-TOUCH; its STATUS deviation 1 names this row as the one
    that would move when someone landed the wiring. AWARE-1 landed it
    (`runtime.py`, marked region `# ---- CARD AWARE-1 ... SENSE-1 pose seam`).

    So the pose fault is GONE — a live pose is PHYSICAL through the seam and
    passes `requirements_requiring_physical_inputs()` — and what remains is
    `CONTROLLER_FEEDBACK: missing`, because an eye still has no controller.
    That is a recoverable HOLD, not a latch, and translation is still refused.
    The function NAME is kept deliberately: `core/input_health.py:491` and
    `backends/go2.py:880` both cite it by name, and those files are SENSE-1's,
    not this card's, to edit.
    """

    from parcel_robot.runtime import RobotRuntime

    base = _config_tree(tmp_path, require_physical=True)
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    backend, clock = _live_backend()
    runtime = RobotRuntime(base, backend)
    try:
        verdict = runtime._evaluate_dispatch_input_health(backend.observe(), now=clock.t + 0.01)
        # The pose no longer latches, and it no longer faults at all.
        assert not [f for f in verdict.faults if f.required_input is RequiredInput.POSE]
        assert ("pose", "sim_fixture_forbidden") not in _faults(verdict)
        # What the eye still does not have, unchanged.
        assert ("controller_feedback", "missing") in _faults(verdict)
        assert verdict.action is HealthAction.HOLD
        assert verdict.stop_latched is False
        assert verdict.translation_allowed is False
    finally:
        runtime.close()


def test_b4_an_empty_scan_holds_at_the_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row B4. No scan is a recoverable HOLD, never an ALLOW and never a stub."""

    from parcel_robot.runtime import RobotRuntime

    base = _config_tree(tmp_path, require_physical=True)
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    backend, clock = _live_backend()
    runtime = RobotRuntime(base, backend)
    try:
        backend.observe()  # the one frame
        observation = backend.observe()  # the socket is empty now
        assert observation.lidar_ranges == ()
        assert backend.scan_evidence_source.evidence(observation) is None
        verdict = runtime._evaluate_dispatch_input_health(observation, now=clock.t + 0.01)
        scan_faults = [f for f in verdict.faults if f.required_input is RequiredInput.SCAN]
        assert [f.reason for f in scan_faults] == ["missing"]
        assert scan_faults[0].action is HealthAction.HOLD
        assert verdict.translation_allowed is False
    finally:
        runtime.close()


def test_b5_the_scan_source_refuses_an_undeclared_origin() -> None:
    """Row B5. UNKNOWN is not an origin, and a string is not a declaration."""

    class Producer:
        def scan_datum_for(self, key: object) -> ScanDatum | None:
            """Never has a datum: this row is about construction, not reads."""

            del key

    with pytest.raises(ValueError, match="UNKNOWN is not one"):
        CommissionedScanSource(Producer(), origin=EvidenceOrigin.UNKNOWN)
    with pytest.raises(TypeError, match="must be an EvidenceOrigin"):
        CommissionedScanSource(Producer(), origin="physical")
    with pytest.raises(TypeError, match="scan_datum_for"):
        CommissionedScanSource(object(), origin=EvidenceOrigin.PHYSICAL)
    # A synthetic origin must name its fixture (the join latches an unlabeled
    # one); a physical one must NOT carry a label (the join latches that too).
    with pytest.raises(ValueError, match="name its fixture"):
        CommissionedScanSource(Producer(), origin=EvidenceOrigin.REPLAY)
    with pytest.raises(ValueError, match="must not carry a fixture label"):
        CommissionedScanSource(
            Producer(), origin=EvidenceOrigin.PHYSICAL, fixture_label="tape.jsonl"
        )


@pytest.mark.parametrize(
    ("label", "second"),
    [
        ("sequence_duplicate", {"sequence": 1, "captured_at": 101.0}),
        ("sequence_reordered", {"sequence": 0, "captured_at": 101.0}),
        ("receipt_regression", {"sequence": 2, "captured_at": 99.0}),
        ("session_epoch_mismatch", {"sequence": 2, "session_epoch": "other"}),
    ],
)
def test_b6_the_scan_source_latches_on_an_ordering_fault(
    label: str, second: dict[str, Any]
) -> None:
    """Row B6, RE-CUT under PREREGISTRATION Amendment 2.

    A latch a single clean tick can clear is not a latch (RC-1c) — and the
    fault cases below are unchanged. What Amendment 2 changes is the *duplicate*
    case: it is a fault only for a DIFFERENT datum carrying a repeated
    sequence. Re-reading the same one is not (see the test below).

    Seed S3a (remove the ordering latch) reddens this.
    """

    producer = _Producer()
    source = CommissionedScanSource(
        producer, origin=EvidenceOrigin.PHYSICAL, session_epoch="epoch-1"
    )
    producer.next = ScanDatum(captured_at=100.0, sequence=1, session_epoch="epoch-1")
    first = source.evidence("k1")
    assert first is not None and first.payload_valid is True
    assert source.latched_reason is None

    fields = {"captured_at": 101.0, "session_epoch": "epoch-1"}
    fields.update(second)
    producer.next = ScanDatum(**fields)
    assert source.evidence("k2").payload_valid is False
    assert source.latched_reason == label

    # THREE clean data later it is still latched.
    for index in range(3):
        producer.next = ScanDatum(
            captured_at=200.0 + index, sequence=100 + index, session_epoch="epoch-1"
        )
        assert source.evidence(f"k{index}").payload_valid is False
    assert source.latched_reason == label


@pytest.mark.parametrize("rebuild", [False, True])
def test_b6_an_identity_re_read_is_not_a_fault(rebuild: bool) -> None:
    """Row B6's new half (Amendment 2) — and the H1 defect, at its source.

    `control/base.py:CommissionedStateSource` exempts a re-read of the same
    datum "because ``latest()`` is a POLL, not a queue pop: the runtime reads it
    more than once per tick". The scan source is read the same way and an
    earlier draft did not exempt it, so ONE corrupt Livox datagram — which
    makes `observe()` raise, leaving the runtime joining on the PREVIOUS
    observation — latched the join permanently, and the operator's own
    `clear_input_health_latch` re-latched the thing it was clearing.

    Identity first, then full field equality for a producer that rebuilds equal
    values. Seed S3b (remove the exemption) reddens this.
    """

    producer = _Producer()
    source = CommissionedScanSource(
        producer, origin=EvidenceOrigin.PHYSICAL, session_epoch="epoch-1"
    )
    datum = ScanDatum(captured_at=100.0, sequence=1, session_epoch="epoch-1")
    producer.next = datum
    assert source.evidence("obs-1").payload_valid is True

    # The SAME observation graded again — the exact runtime path H1 found.
    if rebuild:
        producer.next = ScanDatum(captured_at=100.0, sequence=1, session_epoch="epoch-1")
        assert producer.next is not datum and producer.next == datum
    for _ in range(3):
        again = source.evidence("obs-1")
        assert again is not None
        assert again.payload_valid is True, "an identity re-read is not an ordering fault"
    assert source.latched_reason is None

    # ...and a genuinely DIFFERENT datum under the same sequence still latches.
    producer.next = ScanDatum(captured_at=101.0, sequence=1, session_epoch="epoch-1")
    assert source.evidence("obs-2").payload_valid is False
    assert source.latched_reason == "sequence_duplicate"


def test_b7_a_string_is_not_a_declaration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Row B7. The runtime read is `declared_origin`, a TYPED lookup (W0-A).

    A backend that hangs `origin = "physical"` on a scan source is NOT believed,
    and the join falls back to the observation stamp.
    """

    from parcel_robot.runtime import RobotRuntime

    base = _config_tree(tmp_path, require_physical=True)
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    backend, clock = _live_backend()

    class Liar:
        origin = "physical"  # a string, not the enum

        def evidence(self):  # pragma: no cover - must never be called
            raise AssertionError("a string declaration must never be read")

    backend.scan_evidence_source = Liar()
    runtime = RobotRuntime(base, backend)
    try:
        verdict = runtime._evaluate_dispatch_input_health(backend.observe(), now=clock.t + 0.01)
        assert "sim_fixture_forbidden" in _scan_fault_reasons(verdict)
    finally:
        runtime.close()


def test_b8_flag_off_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Row B8 / C2. With no `backend:` key nothing about the runtime moved.

    Seed S5 (select the go2 backend whenever the section resolves) reddens this.
    """

    runtime = _build_runtime(tmp_path, monkeypatch, backend=None, require_physical=False)
    try:
        assert type(runtime.backend) is MujocoSocketBackend
        assert getattr(runtime.backend, "scan_evidence_source", None) is None
        assert runtime.backend.socket_path == tmp_path / "sim.sock"

        observation = SimObservation(
            timestamp=500.0,
            robot=RobotPose(),
            owner=OwnerTrack(),
            backend="mujoco",
            nearest_obstacle_m=2.0,
        )
        verdict = runtime._evaluate_dispatch_input_health(observation, now=500.01)
        # The pre-card behaviour, exactly: a labeled sim fixture is allowed for
        # a sim-commissioned deployment, and only the absent controller
        # feedback holds.
        assert _faults(verdict) == {("controller_feedback", "missing")}
        assert verdict.action is HealthAction.HOLD
    finally:
        runtime.close()


# ===========================================================================
# C — selection at web_panel.build_runtime
# ===========================================================================


def test_c1_build_runtime_selects_the_go2_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row C1. Through the product launcher, with a band profile from config."""

    runtime = _build_runtime(
        tmp_path,
        monkeypatch,
        backend={
            "kind": "go2",
            "fixture": str(FIXTURE),
            "band": {"z_lo_m": 0.12, "z_hi_m": 0.55, "min_populated_bins": 3},
            "session_epoch": "c1",
        },
    )
    try:
        assert type(runtime.backend).__name__ == "Go2Backend"
        assert runtime.backend.band_profile.z_lo_m == pytest.approx(0.12)
        assert runtime.backend.band_profile.z_hi_m == pytest.approx(0.55)
        assert runtime.backend.band_profile.min_populated_bins == 3
        assert runtime.backend.scan_evidence_source.session_epoch == "c1"
    finally:
        runtime.close()


def test_c3_an_unknown_backend_key_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row C3. TRUTH-1's rule: the read site refuses a typo BY NAME, because a
    merged key nothing reads leaves the setting at its shipped value."""

    with pytest.raises(ValueError, match="fixtur"):
        _build_runtime(tmp_path, monkeypatch, backend={"kind": "go2", "fixtur": str(FIXTURE)})
    with pytest.raises(ValueError, match="bandd"):
        _build_runtime(tmp_path, monkeypatch, backend={"kind": "go2", "bandd": {}})


def test_c3_an_unknown_band_key_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Row C3, the nested half: `backend.band` has its own read-site guard."""

    with pytest.raises(ValueError, match="z_lo"):
        _build_runtime(
            tmp_path,
            monkeypatch,
            backend={"kind": "go2", "fixture": str(FIXTURE), "band": {"z_lo": 0.1}},
        )


def test_c4_an_unknown_backend_kind_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row C4. The refusal names the vocabulary instead of leaving a guess."""

    with pytest.raises(ValueError) as caught:
        _build_runtime(tmp_path, monkeypatch, backend={"kind": "spot"})
    assert "mujoco" in str(caught.value) and "go2" in str(caught.value)


def test_c5_the_overlay_can_select_the_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row C5. The real overlay path: `$PARCEL_PROFILE` flips mujoco -> go2.

    This is the shape HW-5's `configs/profiles/go2_edu_plus.yaml` will take. It
    works here because the BASE defines `backend:`; on the shipped SHA-locked
    base it needs `"backend"` in `config.OVERLAY_INTRODUCIBLE_KEYS`, which is
    HW-5's one-line entry (DESIGN §c, handoff).
    """

    runtime = _build_runtime(
        tmp_path,
        monkeypatch,
        profile="hw2go2",
        # The base must DEFINE every key the overlay sets — that is
        # `check_overlay_keys`, and it is the guard working, not a workaround.
        # HW-5's real profile introduces the whole subtree with ONE
        # `OVERLAY_INTRODUCIBLE_KEYS` entry, after which the base need not
        # carry the children at all.
        backend={"kind": "mujoco", "fixture": None},
        overlay_backend={"kind": "go2", "fixture": str(FIXTURE)},
    )
    try:
        assert type(runtime.backend).__name__ == "Go2Backend"
    finally:
        runtime.close()


def test_c5_the_overlay_still_refuses_an_unknown_key(tmp_path: Path) -> None:
    """The overlay loader's own guard is untouched by this card: `backend` is
    not introducible yet, so an overlay that INTRODUCES it is refused — which
    is why the base carries it in these tests, and why HW-5 owns the entry."""

    from parcel_robot.config import OVERLAY_INTRODUCIBLE_KEYS, ProfileError, check_overlay_keys

    base = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    assert "backend" not in base, "the SHA-locked base must not have grown a backend section"
    if "backend" in OVERLAY_INTRODUCIBLE_KEYS:  # pragma: no cover - after HW-5 lands
        check_overlay_keys(base, {"backend": {"kind": "go2"}})
    else:
        with pytest.raises(ProfileError, match="backend"):
            check_overlay_keys(base, {"backend": {"kind": "go2"}})


# ===========================================================================
# D — `unitree_control observe --duration` (HO-6)
# ===========================================================================


class _Observer:
    """A `CommissioningObserver` stand-in for the CLI test. The observer itself
    (`commissioning/session.py:293`) is not this card's to edit and is tested by
    `tests/test_w0b_commissioning.py`; what is under test here is the CLI loop."""

    def __init__(self, windows: list[Any], clock: FakeClock, step_s: float = 1.0) -> None:
        self._windows = list(windows)
        self._clock = clock
        self._step_s = step_s
        self.calls = 0
        self.closed = False

    def start(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    def observe(self, *, min_samples: int, timeout_s: float):
        del min_samples, timeout_s
        self.calls += 1
        self._clock.advance(self._step_s)
        window = self._windows[min(self.calls, len(self._windows)) - 1]
        if isinstance(window, Exception):
            raise window
        return window


def _evidence(**overrides: Any):
    from parcel_robot.commissioning import ObservationEvidence

    values: dict[str, Any] = {
        "samples": 20,
        "duration_s": 0.4,
        "modes_seen": (1,),
        "error_codes_seen": (0,),
        "max_interval_s": 0.021,
        "mean_interval_s": 0.020,
        "max_linear_speed_mps": 0.0,
        "max_yaw_speed_rad_s": 0.0,
        "declared_velocity_frame": "odom",
        "state_source": "unitree_sport_state",
    }
    values.update(overrides)
    return ObservationEvidence(**values)


def _json_blocks(text: str) -> list[Any]:
    """Every top-level JSON object printed on stdout, in order."""

    decoder = json.JSONDecoder()
    blocks: list[Any] = []
    index = 0
    while True:
        start = text.find("{", index)
        if start < 0:
            return blocks
        try:
            value, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        blocks.append(value)
        index = end


def _run_observe(monkeypatch: pytest.MonkeyPatch, observer: _Observer, argv: list[str]) -> int:
    from parcel_robot import unitree_control

    monkeypatch.setattr(unitree_control, "build_unitree_sport_observer", lambda _c: observer)
    monkeypatch.setattr(unitree_control.time, "monotonic", observer._clock)
    return unitree_control.main(argv)


def test_d1_observe_without_duration_is_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row D1. One window, one JSON block, no summary — byte-for-byte the old
    behaviour. The default is ABSENT, not a number."""

    from parcel_robot.unitree_control import _build_parser

    assert _build_parser().parse_args(["observe"]).duration is None

    clock = FakeClock()
    observer = _Observer([_evidence()], clock)
    rc = _run_observe(monkeypatch, observer, ["observe"])
    out = capsys.readouterr().out

    assert rc == 0
    assert observer.calls == 1
    assert observer.closed is True
    assert "duration_summary" not in out
    blocks = _json_blocks(out)
    assert len(blocks) == 1
    assert blocks[0] == _evidence().as_dict()


def test_d2_observe_duration_runs_until_the_window_closes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row D2. HO-6: a wall-clock look, made of real windows."""

    clock = FakeClock()
    windows = [
        _evidence(max_interval_s=0.021, modes_seen=(1,)),
        _evidence(max_interval_s=0.044, modes_seen=(1, 3)),
        _evidence(max_interval_s=0.030, modes_seen=(3,), max_linear_speed_mps=0.004),
    ]
    observer = _Observer(windows, clock, step_s=1.0)
    rc = _run_observe(monkeypatch, observer, ["observe", "--duration", "2.5"])
    out = capsys.readouterr().out

    assert rc == 0
    assert observer.calls == 3
    blocks = _json_blocks(out)
    assert len(blocks) == 2, out
    assert blocks[0] == windows[-1].as_dict(), "the JSON block is the LAST window"
    summary = blocks[1]["duration_summary"]
    assert summary["windows"] == 3
    assert summary["requested_duration_s"] == pytest.approx(2.5)
    assert summary["worst_max_interval_s"] == pytest.approx(0.044)
    assert summary["modes_seen"] == [1, 3]
    assert summary["max_linear_speed_mps"] == pytest.approx(0.004)
    assert "not summed" in summary["note"]


def test_d3_observe_duration_propagates_a_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row D3. A refusal in ANY window ends the command rc=1, as one window did.

    This is why the duration mode is a loop over `observe()` and not a new
    observation mode: every refusal the operator needs — not stationary, vendor
    fault, too few samples — keeps working.
    """

    from parcel_robot.commissioning import CommissioningRefusedError, RefusalReason

    clock = FakeClock()
    observer = _Observer(
        [
            _evidence(),
            CommissioningRefusedError(RefusalReason.ROBOT_NOT_STATIONARY, "0.9 m/s"),
        ],
        clock,
        step_s=0.5,
    )
    rc = _run_observe(monkeypatch, observer, ["observe", "--duration", "3"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "observation refused" in out
    assert observer.closed is True


def test_d4_observe_duration_must_be_positive() -> None:
    """Row D4. Refused at parse time, with the reason."""

    from parcel_robot.unitree_control import _build_parser

    for bad in ("0", "-1", "nan", "inf"):
        with pytest.raises(SystemExit):
            _build_parser().parse_args(["observe", "--duration", bad])


# ===========================================================================
# E — the sixth stopping-envelope term
# ===========================================================================

_V2_PROVENANCE = tuple((term, f"seeded by {__name__}") for term in timing.ENVELOPE_TERMS_V1)


def _v2_inputs(**overrides: Any) -> timing.StoppingEnvelopeInputsV2:
    values: dict[str, Any] = {
        "candidate_age_s": 0.020,
        "ipc_delay_s": 0.005,
        "gateway_period_s": 0.020,
        "stop_command_to_standstill_s": 0.450,
        "localization_jump_m": 0.200,
        "provenance": _V2_PROVENANCE,
    }
    scan_age = overrides.pop("scan_age_s", 0.100)
    values.update(overrides)
    return timing.StoppingEnvelopeInputsV2(
        base=timing.StoppingEnvelopeInputsV1(**values),
        scan_age_s=scan_age,
        scan_age_provenance=f"seeded by {__name__}",
    )


def test_e1_the_sixth_term_is_in_the_sum() -> None:
    """Row E1. `required = v*(cand + ipc + period + braking + scan_age) + jump`.

    Seed S6 (drop the scan-age contribution) reddens this.
    """

    verdict = timing.derive_envelope_v2(_v2_inputs(), "restricted_free")
    speed = 0.25
    expected = {
        "candidate_age_s": speed * 0.020,
        "ipc_delay_s": speed * 0.005,
        "gateway_period_s": speed * 0.020,
        "stop_command_to_standstill_s": speed * 0.450,
        "scan_age_s": speed * 0.100,
        "localization_jump_m": 0.200,
    }
    assert dict(verdict.contributions) == pytest.approx(expected, abs=1e-12)
    assert tuple(term for term, _ in verdict.contributions) == timing.ENVELOPE_TERMS_V2
    assert verdict.required_m == pytest.approx(sum(expected.values()), abs=1e-12)
    assert verdict.required_m == pytest.approx(0.25 * 0.595 + 0.200, abs=1e-12)

    # It is a DELAY term: at half the speed it halves, and the jump does not.
    slower = timing.derive_envelope_v2(_v2_inputs(), "leashed")
    assert dict(slower.contributions)["scan_age_s"] == pytest.approx(0.15 * 0.100, abs=1e-12)
    assert dict(slower.contributions)["localization_jump_m"] == pytest.approx(0.200, abs=1e-12)

    # And it costs distance: the five-term sum on the same numbers is smaller by
    # exactly v * scan_age.
    five = timing.derive_envelope(_v2_inputs().base, "restricted_free")
    assert verdict.required_m - five.required_m == pytest.approx(speed * 0.100, abs=1e-12)


def test_e2_an_unmeasured_scan_age_poisons_the_verdict() -> None:
    """Row E2. UNMEASURED is not 0.0: an unmeasured term must not HELP the sum."""

    verdict = timing.derive_envelope_v2(_v2_inputs(scan_age_s=timing.UNMEASURED), "leashed")
    assert verdict.state == "UNMEASURED"
    assert verdict.missing == ("scan_age_s",)
    assert verdict.required_m is None
    assert verdict.headroom_m is None
    assert verdict.contributions == ()
    assert verdict.line().endswith("UNMEASURED - scan_age_s")

    with pytest.raises(ValueError, match="finite and non-negative"):
        _v2_inputs(scan_age_s=-0.001)
    with pytest.raises(ValueError, match="no provenance"):
        timing.StoppingEnvelopeInputsV2(base=_v2_inputs().base, scan_age_s=0.1)


@pytest.mark.parametrize("name", ["default.yaml", "jaewoo-jang-parcel.yaml"])
def test_e3_the_shipped_records_carry_the_sixth_term(name: str) -> None:
    """Row E3. Both shipped records name what will measure the term."""

    path = REPO / "configs" / "envelope" / name
    record = timing.load_stopping_envelope_record_v2(path)
    assert record.value("scan_age_s") is timing.UNMEASURED
    assert "scan_age_s" in record.missing()
    provenance = record.provenance_of("scan_age_s")
    assert len(provenance.strip()) > 40
    assert "Go2Backend" in provenance or "Mid-360" in provenance


@pytest.mark.parametrize("name", ["default.yaml", "jaewoo-jang-parcel.yaml"])
def test_e4_hw6_v1_is_untouched(name: str) -> None:
    """Row E4. The five-term shape did not move — asserted, not assumed.

    The sixth term lives in a TOP-LEVEL `scan_age:` block precisely so that
    `load_stopping_envelope_record` (which reads `schema`, `measurements`,
    `active_regime`, `host` and nothing else) cannot see it. If a later card
    moves it under `measurements:`, HW-6's gate row and five of its tests move
    with it, and this test is where that shows up first.
    """

    assert len(timing.ENVELOPE_TERMS_V1) == 5
    assert "scan_age_s" not in timing.ENVELOPE_TERMS_V1
    path = REPO / "configs" / "envelope" / name
    v1 = timing.load_stopping_envelope_record(path)
    v2 = timing.load_stopping_envelope_record_v2(path)
    assert v2.base == v1
    assert set(v1.missing()) | {"scan_age_s"} == set(v2.missing())
    if name == "jaewoo-jang-parcel.yaml":
        assert set(v1.missing()) == {
            "gateway_period_s",
            "stop_command_to_standstill_s",
            "localization_jump_m",
        }


def test_e5_a_record_without_the_sixth_term_is_refused(tmp_path: Path) -> None:
    """A term nobody wrote down is not a term measured at zero."""

    document = yaml.safe_load(
        (REPO / "configs" / "envelope" / "default.yaml").read_text(encoding="utf-8")
    )
    document.pop("scan_age")
    path = tmp_path / "no_scan_age.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    # V1 still reads it — that is the compatibility this shape buys.
    assert timing.load_stopping_envelope_record(path).missing() == timing.ENVELOPE_TERMS_V1
    with pytest.raises(ValueError, match="scan_age"):
        timing.load_stopping_envelope_record_v2(path)


def test_e6_the_rc4_tables_are_byte_identical() -> None:
    """Row E6. HW-6's frozen half of `bridge/timing.py` did not move.

    The two shas are HW-6's own pins; they are re-read from that test file so
    that this test cannot silently drift away from the pin it is quoting.
    """

    latency_sha = "466cad1f6064781f9a94f3bdb79a4c3b2bb4d09d50175bedb9449cca5559bce6"
    h2_sha = "2a2927d5ea9dce9f0e3cfa973f1774a3edb1189bcd5879cceebc2650ac86ed2f"
    hw6 = (REPO / "tests" / "test_hw6_stopping_envelope.py").read_text(encoding="utf-8")
    assert f'RC4_LATENCY_TABLE_SHA256 = "{latency_sha}"' in hw6
    assert f'RC4_H2_TABLE_SHA256 = "{h2_sha}"' in hw6

    rendered = timing.render_latency_derivation_markdown()
    assert hashlib.sha256(rendered.encode("utf-8")).hexdigest() == latency_sha
    h2 = timing.render_commissioning_h2_markdown()
    assert hashlib.sha256(h2.encode("utf-8")).hexdigest() == h2_sha


# Row E7 was `test_e7_the_gate_row_still_prints_the_five_term_verdict`: a
# DECLARED LIMIT pinning that the gate still read five terms while this card
# derived six. Card GATE-1 (scrum/20260823/task_5) swapped
# `scripts/ci_gate.py:evaluate_stopping_envelope` onto
# `derive_envelope_rows_v2`, which is the event that test's own docstring
# said to delete it on. The limit is gone, so the pin is gone with it; what
# replaces it lives in task_5's tests and in HW-6's updated shipped-record
# assertions.


def test_e8_the_backend_can_measure_the_term_it_registered() -> None:
    """The sixth term is not an orphan: the thing that will measure it exists.

    `Go2Backend.latest_scan_age_s()` is what the record's provenance names. On
    a desktop replay it measures the replay loop and means nothing about a
    robot — which is exactly why the shipped records say UNMEASURED.
    """

    backend, clock = _replay_backend()
    assert backend.latest_scan_age_s() is None
    backend.observe()
    assert backend.latest_scan_age_s() == pytest.approx(0.0)
    clock.advance(0.037)
    assert backend.latest_scan_age_s() == pytest.approx(0.037)
    assert backend.latest_scan_age_s(now=clock.t + 1.0) == pytest.approx(1.037)


# ===========================================================================
# H1 / H2 / F2 / F3 / F5 — the correction pass (PREREGISTRATION Amendment 2)
# ===========================================================================


def _live_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kwargs: Any):
    """A REAL `RobotRuntime` over a live-declaring backend.

    `RobotRuntime(config_path, backend)` is the constructor
    `web_panel.build_runtime` calls (`web_panel.py:~930`, `runtime.py:1498`);
    the vendor DDS subscriber and UDP socket are the only doubles.
    """

    from parcel_robot.runtime import RobotRuntime

    base = _config_tree(tmp_path, **kwargs)
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    source, clock, sock = _live_sources(frames=0)
    backend = Go2Backend(source, clock=clock)
    backend.start()
    return RobotRuntime(base, backend), backend, clock, sock


def test_h1a_a_corrupt_datagram_costs_one_datagram(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row H1a (Amendment 2). One bad datagram is one datagram, not a session.

    The verifier's H1: `receive_frames` without `on_refusal` raises the
    `LivoxDecodeError` out of the generator, so the frames already read that
    tick were abandoned, the GOOD datagram queued behind the corrupt one was
    left unread, `observe()` raised — and the join, re-reading the previous
    observation, latched for ever. `on_refusal` (F4) closes all of it.
    """

    _states, payloads = _fixture_records()
    runtime, backend, clock, sock = _live_runtime(tmp_path, monkeypatch)
    try:
        sock.push(payloads[0])
        first = backend.observe()
        assert scan_present(first) is True

        # A corrupt datagram BETWEEN two good ones.
        sock.push(payloads[1], b"\x00" * 40, payloads[2])
        clock.advance(0.1)
        second = backend.observe()

        assert backend.source.refused_datagrams == 1
        assert len(sock) == 0, "the good datagram behind the corrupt one was abandoned"
        assert scan_present(second) is True

        clock.advance(0.1)
        sock.push(payloads[3])
        third = backend.observe()

        for observation in (first, second, third):
            verdict = runtime._evaluate_dispatch_input_health(
                observation, now=observation.timestamp + 0.01
            )
            assert "payload_malformed" not in _scan_fault_reasons(verdict)
        assert backend.scan_evidence_source.latched_reason is None
    finally:
        runtime.close()


def test_h1b_the_operator_can_clear_the_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row H1b (Amendment 2). The e-stop clear must be able to clear.

    `clear_input_health_latch` (`runtime.py:4786`, reached from the e-stop
    clear at `:4746`) re-joins on `self._observation` — the SAME observation the
    tick before joined on. Before the identity exemption that second read was
    `sequence_duplicate` -> `payload_malformed` -> `LATCHED_STOP`, so the
    operator's clear latched the very thing it was clearing and nothing short
    of a process restart could recover.

    Run on the DEFAULT requirements table, which is what a runtime built from
    any shipped profile actually gets today (`safety.require_physical_inputs`
    is not introducible — verifier finding F6, handed on): the clear can then
    succeed, which is what makes "it clears" observable at all.
    """

    _states, payloads = _fixture_records()
    runtime, backend, _clock, sock = _live_runtime(tmp_path, monkeypatch, require_physical=False)
    try:
        sock.push(payloads[0])
        observation = backend.observe()
        runtime._observation = observation
        runtime._input_health_latched = True
        runtime._input_health_latch_faults = ("scan:seeded",)

        first = runtime.clear_input_health_latch(now=observation.timestamp + 0.01)
        assert runtime._input_health_latched is False, first
        assert backend.scan_evidence_source.latched_reason is None

        # ...and again, the way an operator who clicks twice does.
        runtime._input_health_latched = True
        runtime.clear_input_health_latch(now=observation.timestamp + 0.02)
        verdict = runtime._evaluate_dispatch_input_health(
            observation, now=observation.timestamp + 0.03
        )
        assert "payload_malformed" not in _scan_fault_reasons(verdict)
        assert backend.scan_evidence_source.latched_reason is None
    finally:
        runtime.close()


def test_h2a_the_source_is_never_more_permissive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row H2a (Amendment 2) — the region's claim #3, as a property.

    For every SCAN case, the join's verdict WITH the typed source is compared
    against the same join WITHOUT it (the real `scan_evidence_from_observation`
    through the real `evaluate_input_health` and the runtime's own requirements
    table). Exactly ONE relaxation is permitted, and it is the card's entire
    purpose: clearing `sim_fixture_forbidden` on an observation that ALREADY
    carries a scan. Presence is never invented.

    Seed S8 (drop the `scan is not None` precondition) reddens this.
    """

    from parcel_robot.core.input_health import evaluate_input_health
    from parcel_robot.navigation.reactive_safety import scan_evidence_from_observation

    severity = {None: 0, HealthAction.HOLD: 1, HealthAction.LATCHED_STOP: 2}

    def scan_fault(verdict):
        for fault in verdict.faults:
            if fault.required_input is RequiredInput.SCAN:
                return fault.reason, fault.action
        return None, None

    def without_source(runtime, observation, now):
        return evaluate_input_health(
            {RequiredInput.SCAN: scan_evidence_from_observation(observation)},
            now=now,
            requirements=runtime._input_health_requirements,
        )

    _states, payloads = _fixture_records()
    runtime, backend, clock, sock = _live_runtime(tmp_path, monkeypatch)
    seen: dict[str, tuple[str | None, str | None]] = {}
    try:
        # (1) missing — the observation carries no scan at all.
        empty = backend.observe()
        assert empty.lidar_ranges == ()
        now = empty.timestamp + 0.01
        with_reason, with_action = scan_fault(
            runtime._evaluate_dispatch_input_health(empty, now=now)
        )
        no_reason, no_action = scan_fault(without_source(runtime, empty, now))
        assert (with_reason, with_action) == ("missing", HealthAction.HOLD)
        assert (no_reason, no_action) == ("missing", HealthAction.HOLD)
        seen["missing"] = (with_reason, no_reason)

        # (4) ok — a scan the source can vouch for. The ONE relaxation.
        sock.push(payloads[0])
        clock.advance(0.1)
        good = backend.observe()
        now = good.timestamp + 0.01
        with_reason, with_action = scan_fault(
            runtime._evaluate_dispatch_input_health(good, now=now)
        )
        no_reason, no_action = scan_fault(without_source(runtime, good, now))
        assert with_reason is None
        assert no_reason == "sim_fixture_forbidden"
        seen["ok"] = (with_reason, no_reason)

        # (3) payload_malformed — the source is latched; STRICTER than without.
        backend.scan_evidence_source._latched_reason = "seeded_by_the_test"
        with_reason, with_action = scan_fault(
            runtime._evaluate_dispatch_input_health(good, now=now)
        )
        no_reason, no_action = scan_fault(without_source(runtime, good, now))
        assert with_reason == "payload_malformed"
        assert severity[with_action] >= severity[no_action]
        seen["payload_malformed"] = (with_reason, no_reason)
    finally:
        runtime.close()

    # (2) sim_fixture_forbidden — a REPLAY source: the region does not fire and
    # the two paths are identical.
    replay = _build_runtime(
        tmp_path / "replay", monkeypatch, backend={"kind": "go2", "fixture": str(FIXTURE)}
    )
    try:
        replay.backend.start()
        observation = replay.backend.observe()
        now = observation.timestamp + 0.01
        with_reason, with_action = scan_fault(
            replay._evaluate_dispatch_input_health(observation, now=now)
        )
        no_reason, no_action = scan_fault(without_source(replay, observation, now))
        assert with_reason == no_reason == "sim_fixture_forbidden"
        assert with_action == no_action == HealthAction.LATCHED_STOP
        seen["sim_fixture_forbidden"] = (with_reason, no_reason)
    finally:
        replay.close()

    assert set(seen) == {"missing", "sim_fixture_forbidden", "payload_malformed", "ok"}
    # The invariant in one line: presence is never invented.
    assert seen["missing"] == ("missing", "missing")


def test_h2a_a_source_that_answers_anything_still_cannot_supply_presence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row H2a's second half — the read site's OWN rule, not the backend's.

    `Go2Backend` records no datum for a scan-less observation, so the keying
    alone already produces `missing`. That makes the region's `scan is not
    None` precondition a SECOND guard, and a second guard nothing exercises is
    an inert guard — the anti-pattern this tree's audits keep finding. So it is
    exercised here against the case it exists for: a scan-evidence source that
    answers for EVERY key, which is what a different backend, a buggy one, or a
    hostile one looks like. The rule "the source may re-stamp a scan the
    observation carries, never supply presence it lacks" belongs to the read
    site, and this is where that is true.

    Seed S8 (drop the precondition) reddens this and nothing else.
    """

    runtime, backend, _clock, _sock = _live_runtime(tmp_path, monkeypatch)
    try:
        empty = backend.observe()
        assert empty.lidar_ranges == ()
        assert backend.scan_datum_for(empty) is None

        answers_anything = _Producer()
        answers_anything.next = ScanDatum(
            captured_at=empty.timestamp, sequence=1, populated_bins=360, points_seen=20_000
        )
        backend.scan_evidence_source = CommissionedScanSource(
            answers_anything, origin=EvidenceOrigin.PHYSICAL, name="go2_live"
        )
        assert backend.scan_evidence_source.evidence(empty) is not None, (
            "the double must really answer, or this test proves nothing"
        )

        verdict = runtime._evaluate_dispatch_input_health(empty, now=empty.timestamp + 0.01)
        scan_faults = [f for f in verdict.faults if f.required_input is RequiredInput.SCAN]
        assert [f.reason for f in scan_faults] == ["missing"], (
            "a source supplied a scan the observation did not carry"
        )
        assert scan_faults[0].action is HealthAction.HOLD
    finally:
        runtime.close()


def test_h2b_a_later_sweep_cannot_grade_an_earlier_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row H2b (Amendment 2) — the verifier's exact reproduction.

    `observe()` runs on the control loop AND on HTTP handler threads
    (`runtime.py:6210, 9551, 10295`), each draining the one socket. With a
    LATEST datum, the loop's join on a scan-less observation read the handler's
    sweep and reported NO SCAN FAULT where `scan_evidence_from_observation`
    says `missing`. The datum is now keyed to the observation it graded.

    Seed S9 (`scan_datum_for` returns `latest_scan()`) reddens this.
    """

    _states, payloads = _fixture_records()
    runtime, backend, clock, sock = _live_runtime(tmp_path, monkeypatch)
    try:
        sock.push(payloads[0])
        first = backend.observe()  # a real sweep
        clock.advance(0.1)
        empty = backend.observe()  # the loop's tick: nothing drained
        clock.advance(0.1)
        sock.push(payloads[1])
        later = backend.observe()  # a handler thread's tick: a new sweep

        assert first.lidar_ranges and later.lidar_ranges and empty.lidar_ranges == ()

        verdict = runtime._evaluate_dispatch_input_health(empty, now=later.timestamp + 0.01)
        scan_faults = [f for f in verdict.faults if f.required_input is RequiredInput.SCAN]
        assert [f.reason for f in scan_faults] == ["missing"]
        assert scan_faults[0].action is HealthAction.HOLD

        # Each observation still grades against ITS OWN datum.
        assert backend.scan_datum_for(first) is not None
        assert backend.scan_datum_for(empty) is None
        assert backend.scan_datum_for(later) is not None
        assert backend.scan_datum_for(first) is not backend.scan_datum_for(later)
    finally:
        runtime.close()


def test_f2a_no_pose_is_fabricated_before_the_first_sample() -> None:
    """Row F2a (Amendment 2). `RobotPose()` is a pose, not an absence.

    (0, 0, 0, 0) under a fresh timestamp reads at the join as present and
    fresh. The runtime's own `except (OSError, RuntimeError, TypeError,
    ValueError)` around `backend.observe()` turns this typed refusal into
    `observation=None`, which is a HOLD.
    """

    class Silent:
        origin = EvidenceOrigin.PHYSICAL
        name = "go2_live"
        fixture_label = ""

        def latest(self):
            return None

        def drain(self):
            raise AssertionError("the refused tick must not consume frames")

    backend = Go2Backend(Silent())
    with pytest.raises(Go2StateUnavailable) as caught:
        backend.observe()
    assert "rt/sportmodestate" in str(caught.value)
    assert isinstance(caught.value, Go2BackendError)
    # The runtime catches exactly this shape.
    assert isinstance(caught.value, RuntimeError)
    assert backend.scan_datum_for(None) is None

    # Seed S10 (fall back to RobotPose()) reddens the line above; this pins the
    # positive case so the refusal cannot be "always refuse".
    live, _clock = _live_backend(frames=1)
    assert live.observe().robot.z == pytest.approx(0.32)


def test_f3a_the_live_scan_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Row F3a (Amendment 2). The socket exists, is non-blocking, and is bounded.

    Verifier finding F3: the class docstring declared a "bound UDP socket"
    while `_build_backend` passed none — `drain()` returned `()` for ever and
    box-day would have been asked to prove code that was not there. And
    `_read_until_empty` REQUIRED a non-blocking socket (it catches
    `BlockingIOError`) without saying or checking so: a blocking `recv` inside
    `observe()` stalls the control loop exactly when the sensor goes quiet.
    """

    import socket as socket_module

    # (a) the keys reach the source, and a typo is refused BY NAME.
    with pytest.raises(ValueError, match="hostt"):
        _build_runtime(
            tmp_path,
            monkeypatch,
            backend={"kind": "go2", "interface": "eth0", "livox": {"hostt": "192.168.1.5"}},
        )
    with pytest.raises(ValueError, match="two different sensors"):
        _build_runtime(
            tmp_path,
            monkeypatch,
            backend={"kind": "go2", "fixture": str(FIXTURE), "livox": {"host": "0.0.0.0"}},
        )

    # (b) a real bound socket, non-blocking, from the same call the launcher makes.
    probe = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    free_port = probe.getsockname()[1]
    probe.close()
    sock = LiveGo2Sources.open_livox_socket("127.0.0.1", free_port)
    try:
        assert sock.gettimeout() == 0.0, "a blocking socket would stall the control loop"
        assert sock.getsockname() == ("127.0.0.1", free_port)
    finally:
        sock.close()
    with pytest.raises(ValueError, match="1..65535"):
        LiveGo2Sources.open_livox_socket("127.0.0.1", 70000)

    # (c) an injected BLOCKING socket is refused at construction.
    class Blocking:
        def gettimeout(self):
            return None

        def recv(self, _n):  # pragma: no cover - never reached
            raise AssertionError

    states, payloads = _fixture_records()
    clock = FakeClock()
    with pytest.raises(ValueError, match="non-blocking"):
        LiveGo2Sources(state_source=FakeSportModeSubscriber(states, clock), socket=Blocking())

    # (d) the drain is bounded by wall clock even if the transport keeps giving.
    class Endless:
        def __init__(self, payload: bytes, tick: FakeClock) -> None:
            self._payload = payload
            self._tick = tick
            self.reads = 0

        def gettimeout(self):
            return 0.0

        def recv(self, _n):
            self.reads += 1
            self._tick.advance(0.01)
            return self._payload

    endless = Endless(payloads[0], clock)
    bounded = LiveGo2Sources(
        state_source=FakeSportModeSubscriber(states, clock),
        socket=endless,
        clock=clock,
        drain_budget_s=0.005,
        max_frames_per_drain=1000,
    )
    drained = bounded.drain()
    assert 0 < len(drained) <= 2, f"the drain ignored its budget: {len(drained)} frames"

    # (e) a quiet sensor is not an error: no frames -> () -> no scan -> HOLD.
    quiet, _clock, _sock = _live_sources(frames=0)
    assert quiet.drain() == ()


def test_f5a_the_scan_declaration_is_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row F5a (Amendment 2). What was declared, and by whom, in the latch record.

    No typed check can tell an honest `origin = PHYSICAL` from a lying one —
    `LiveGo2Sources` IS such a declaration, and code that wants to lie can. The
    product's obligation is therefore not a check it cannot write but a RECORD:
    `input_health_latch()` already publishes `state_source_origin` for
    pose/feedback (card W0-A) and published nothing for the scan.
    """

    runtime = _build_runtime(
        tmp_path, monkeypatch, backend={"kind": "go2", "fixture": str(FIXTURE)}
    )
    try:
        record = runtime.input_health_latch()
        assert record["scan_source_origin"] == "replay"
        assert record["scan_source_name"] == "go2_stage0_replay"
        # W0-A's own field, untouched by this card: a config-built runtime
        # synthesises its feedback from the observation, so SIMULATION is the
        # structural fact (`runtime.py:1547-1552`).
        assert record["state_source_origin"] == "simulation"
        assert runtime.backend.observe().backend == "go2_stage0_replay"
    finally:
        runtime.close()

    live_runtime, _backend, _clock, _sock = _live_runtime(tmp_path / "live", monkeypatch)
    try:
        record = live_runtime.input_health_latch()
        assert record["scan_source_origin"] == "physical"
        assert record["scan_source_name"] == "go2_live"
    finally:
        live_runtime.close()

    sim = _build_runtime(tmp_path / "sim", monkeypatch, backend=None)
    try:
        record = sim.input_health_latch()
        assert record["scan_source_origin"] is None
        assert record["scan_source_name"] is None
    finally:
        sim.close()
