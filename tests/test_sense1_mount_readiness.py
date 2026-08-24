"""Card SENSE-1 — the sensing stack, made honest before a robot is bolted on.

One test per behavior the card buys, and nothing else (owner's testing
directive, 2026-08-23: capability and hardware-integral error checks, not
suites of combinations). Every row here is a defect the ARCH-1 verdict or its
addendum REPRODUCED, so each test names the defect it closes:

* **X04 / two clocks.** ``go2.py`` stamped pose and scan with one
  ``received_at`` taken at ``observe()``. Both channels are buffered, so a DDS
  stream that had stopped and a socket that had gone quiet both looked
  permanently fresh to the one branch of the health join that exists to notice
  it.
* **Blocking finding 4 / the pose seam.** Pose rode ``evidence_origin``'s
  unconditional SIMULATION stamp, so under ``require_physical_inputs`` — which
  is the whole point of ``go2_edu_plus`` — a live dog's pose latched
  ``sim_fixture_forbidden``.
* **A23 / the drain bound.** ``drain_budget_s`` was checked only BETWEEN
  yielded frames, so neither an all-corrupt flood (which never yields) nor a
  socket that went blocking (which never returns) was bounded at all.
* **X06 / resolved-profile inheritance.** The physical profile silently
  inherited a fabricated battery reading, the simulator controller and a
  desktop NIC, twice.
* **Mount-day readiness.** Nothing in the tree could answer "can this host take
  data from the three things about to be bolted on?".

Nothing here opens a simulator, spends on a model, touches the owner's stack or
store, or binds a real port: every socket, camera and card list is injected.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from parcel_robot.backends.go2 import Go2Backend, LiveGo2Sources, RecordedStage0Source
from parcel_robot.config import (
    PHYSICAL_PREMISE_KEYS,
    PHYSICAL_RESOLUTION_ABSENT,
    PHYSICAL_RESOLUTION_KEPT,
    PHYSICAL_RESOLUTION_SET,
    ConfigStore,
    PhysicalProfileError,
)
from parcel_robot.control.models import RobotMotionState
from parcel_robot.core.input_health import (
    CommissionedPoseSource,
    HealthAction,
    PoseDatum,
    RequiredInput,
    evaluate_input_health,
    requirements_requiring_physical_inputs,
)
from parcel_robot.evidence_origin import EvidenceOrigin
from parcel_robot.lidar.livox_udp import build_point_frame
from scripts.parcel_capture.preflight import (
    AbsenceReason,
    MountReadiness,
    format_report,
    probe_d455_mount,
    probe_mid360_udp,
    probe_xvf3800_mount,
    run_preflight,
)

BASE_CONFIG = REPO / "configs" / "robot.yaml"
PROFILE_NAME = "go2_edu_plus"
PROFILE = REPO / "configs" / f"robot.{PROFILE_NAME}.yaml"
FIXTURE = REPO / "tests" / "data" / "hw2_stage0_replay.jsonl"

#: The three the ARCH-1 addendum reproduced, with the value each inherits.
INHERITED_PREMISES = (
    ("battery.simulated_percent", 90.0),
    ("control.controller", "simulator"),
    ("control.unitree_sport.interface", "enp3s0"),
)

POSE_REQUIREMENT = requirements_requiring_physical_inputs()[RequiredInput.POSE]


class Clock:
    """A host monotonic clock the test moves by hand."""

    def __init__(self, start: float = 500.0) -> None:
        self.t = float(start)

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += float(seconds)


class DdsStateSource:
    """A vendor state source that stamps its receipt when the sample ARRIVES.

    This is the one behavior of ``UnitreeSportStateSource`` that matters here
    (``control/unitree_sport.py:150``): ``received_at`` is read at delivery, and
    ``latest()`` is a POLL that re-serves the same buffered sample until the
    next one lands.
    """

    origin = EvidenceOrigin.PHYSICAL
    name = "fake_sportmodestate"

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._state: RobotMotionState | None = None
        self._sequence = 0

    def deliver(self) -> RobotMotionState:
        self._sequence += 1
        self._state = RobotMotionState(
            received_at=float(self._clock()),
            sequence=self._sequence,
            position=(1.0, 2.0, 0.3),
            yaw=0.1,
        )
        return self._state

    def latest(self) -> RobotMotionState | None:
        return self._state


class FakeLivoxSocket:
    """A non-blocking ``recv`` over a queue, and nothing else. No network."""

    def __init__(self, clock: Clock | None = None, per_read_s: float = 0.0) -> None:
        self.queue: list[bytes] = []
        self.reads = 0
        self._clock = clock
        self._per_read_s = per_read_s

    def push(self, *datagrams: bytes) -> None:
        self.queue.extend(datagrams)

    def gettimeout(self) -> float:
        return 0.0

    def recv(self, _max_bytes: int) -> bytes:
        self.reads += 1
        if self._clock is not None and self._per_read_s:
            self._clock.advance(self._per_read_s)
        if not self.queue:
            raise BlockingIOError
        return self.queue.pop(0)


class EndlessCorruptSocket(FakeLivoxSocket):
    """A sender that never stops and never sends a decodable datagram."""

    def recv(self, _max_bytes: int) -> bytes:
        self.reads += 1
        if self._clock is not None and self._per_read_s:
            self._clock.advance(self._per_read_s)
        return b"\x00" * 40


def _datagram(udp_cnt: int = 1) -> bytes:
    """One real Livox SDK2 datagram, built by the product's own frame builder."""

    points = [(1000 * index + 400, 0, 100, 12, 0) for index in range(1, 40)]
    return build_point_frame(points, udp_cnt=udp_cnt, base_timestamp_ns=udp_cnt * 1_000_000)


def _live_backend(clock: Clock, sock: FakeLivoxSocket) -> tuple[Go2Backend, DdsStateSource]:
    state = DdsStateSource(clock)
    source = LiveGo2Sources(state_source=state, socket=sock, clock=clock)
    return Go2Backend(source, clock=clock), state


def _pose_verdict(evidence: Any, *, now: float) -> Any:
    return evaluate_input_health(
        {RequiredInput.POSE: evidence},
        now=now,
        requirements={RequiredInput.POSE: POSE_REQUIREMENT},
    )


def _faults(verdict: Any) -> list[tuple[str, str]]:
    return [(fault.required_input.value, fault.reason) for fault in verdict.faults]


# ======================================================================
# X04 — one received_at became three clocks
# ======================================================================


def test_x04_pose_scan_and_assembly_carry_three_different_receipts() -> None:
    """The defect in one assertion: the two buffered channels keep their own clocks.

    The DDS sample lands at t; the tick runs 200 ms later; the socket hands the
    frame over later still. Before this card all three were the tick's clock,
    which is what made a stopped stream un-noticeable.
    """

    clock = Clock()
    sock = FakeLivoxSocket(clock, per_read_s=0.001)
    backend, state = _live_backend(clock, sock)

    state.deliver()  # the DDS sample arrives at 500.00
    clock.advance(0.2)  # ... and the control loop ticks at 500.20
    sock.push(_datagram(1))
    observation = backend.observe()

    pose = backend.pose_datum_for(observation)
    scan = backend.scan_datum_for(observation)
    assert pose is not None and scan is not None
    assert pose.captured_at == pytest.approx(500.0), "the pose keeps its DDS receipt"
    assert observation.timestamp == pytest.approx(500.2), "the assembly clock is unchanged"
    assert scan.captured_at == pytest.approx(500.201), "the scan keeps its socket receipt"
    assert len({pose.captured_at, observation.timestamp, scan.captured_at}) == 3


def test_x04_a_buffered_pose_goes_stale_instead_of_being_restamped_fresh() -> None:
    """The consequence, and the whole reason the clock matters.

    ``latest()`` re-serves the same sample when the stream goes quiet. Graded at
    its OWN receipt the pose ages and the join HOLDs; graded at the tick's clock
    — the old behavior — it would be permanently fresh.
    """

    clock = Clock()
    sock = FakeLivoxSocket(clock)
    backend, state = _live_backend(clock, sock)
    state.deliver()
    sock.push(_datagram(1))
    backend.observe()

    clock.advance(5.0)  # five seconds of silence from the Sport service
    sock.push(_datagram(2))
    quiet = backend.observe()

    verdict = _pose_verdict(backend.pose_evidence_source.evidence(quiet), now=clock.t)
    assert verdict.action is HealthAction.HOLD
    assert ("pose", "stale") in _faults(verdict)
    assert verdict.translation_allowed is False


# ======================================================================
# Blocking finding 4 — the pose provenance seam
# ======================================================================


def test_a_live_pose_passes_the_physical_requirements_table() -> None:
    """The seam's whole purpose: a real dog's pose is believed.

    Under ``requirements_requiring_physical_inputs`` — the table
    ``safety.require_physical_inputs: true`` selects — this pose ALLOWs, where
    the observation's own ``evidence_origin`` stamp latches it SIMULATION.
    """

    clock = Clock()
    sock = FakeLivoxSocket(clock)
    backend, state = _live_backend(clock, sock)
    state.deliver()
    sock.push(_datagram(1))
    observation = backend.observe()

    evidence = backend.pose_evidence_source.evidence(observation)
    assert evidence is not None
    assert evidence.origin is EvidenceOrigin.PHYSICAL
    assert evidence.fixture_label is None
    verdict = _pose_verdict(evidence, now=clock.t + 0.01)
    assert verdict.action is HealthAction.ALLOW
    assert verdict.faults == ()


def test_a_replayed_pose_still_latches_under_the_physical_table() -> None:
    """The fail-closed direction, unmoved: a file is not a robot.

    The origin is declared BY CONSTRUCTION — ``RecordedStage0Source`` reads a
    file, so it is REPLAY — and no configuration key can move it.
    """

    clock = Clock()
    backend = Go2Backend(RecordedStage0Source(FIXTURE, clock=clock), clock=clock)
    backend.start()
    clock.advance(0.05)
    observation = backend.observe()

    evidence = backend.pose_evidence_source.evidence(observation)
    assert evidence is not None
    assert evidence.origin is EvidenceOrigin.REPLAY
    verdict = _pose_verdict(evidence, now=clock.t)
    assert verdict.action is HealthAction.LATCHED_STOP
    assert ("pose", "sim_fixture_forbidden") in _faults(verdict)


def test_a_pose_the_source_has_no_datum_for_holds_and_never_stubs() -> None:
    """Absence is a recoverable HOLD, through both halves of the seam.

    ``evidence()`` answers about ONE observation (the H2 keying), so an
    observation this backend never graded — another backend's, or one older
    than the bounded window — reads as *missing*, never as a fabricated sample.
    """

    clock = Clock()
    sock = FakeLivoxSocket(clock)
    backend, state = _live_backend(clock, sock)
    state.deliver()
    sock.push(_datagram(1))
    backend.observe()

    assert backend.pose_datum_for(object()) is None
    assert backend.pose_evidence_source.evidence(object()) is None
    verdict = _pose_verdict(None, now=clock.t)
    assert verdict.action is HealthAction.HOLD
    assert ("pose", "missing") in _faults(verdict)


@pytest.mark.parametrize("rebuild", [False, True])
def test_the_pose_source_latches_on_an_ordering_fault_but_not_on_a_re_read(
    rebuild: bool,
) -> None:
    """HW-2's identity exemption, extended to pose and not re-cut.

    Re-reading the SAME datum is normal — the join does it after an
    ``observe()`` exception and again when the operator clears the latch — so
    identity (and full field equality, for a producer that rebuilds equal
    values) is exempt. A DIFFERENT datum carrying a repeated sequence is a
    producer defect and latches EVERY later read, including clean ones.
    """

    class Producer:
        def __init__(self) -> None:
            self.next: PoseDatum | None = None

        def pose_datum_for(self, key: object) -> PoseDatum | None:
            del key
            return self.next

    producer = Producer()
    source = CommissionedPoseSource(producer, origin=EvidenceOrigin.PHYSICAL, name="go2_live")

    first = PoseDatum(captured_at=100.0, sequence=1)
    producer.next = first
    assert source.evidence("tick").payload_valid is True

    producer.next = PoseDatum(captured_at=100.0, sequence=1) if rebuild else first
    assert source.evidence("tick").payload_valid is True, "a re-read is not a fault"
    assert source.latched_reason is None

    producer.next = PoseDatum(captured_at=100.0, sequence=1, source_time_s=9.0)
    assert source.evidence("tick").payload_valid is False
    assert source.latched_reason == "sequence_duplicate"

    producer.next = PoseDatum(captured_at=101.0, sequence=2)
    clean = source.evidence("tick")
    assert clean.payload_valid is False, "a latch a good tick can clear is not a latch"
    verdict = _pose_verdict(clean, now=101.0)
    assert verdict.action is HealthAction.LATCHED_STOP
    assert ("pose", "payload_malformed") in _faults(verdict)


def test_the_pose_source_refuses_an_undeclared_or_mislabelled_origin() -> None:
    """Construction errors with names, rather than a stop three layers away."""

    class Producer:
        def pose_datum_for(self, key: object) -> PoseDatum | None:
            del key
            return None

    with pytest.raises(ValueError, match="UNKNOWN is not one"):
        CommissionedPoseSource(Producer(), origin=EvidenceOrigin.UNKNOWN)
    with pytest.raises(TypeError, match="must be an EvidenceOrigin"):
        CommissionedPoseSource(Producer(), origin="physical")
    with pytest.raises(TypeError, match="pose_datum_for"):
        CommissionedPoseSource(object(), origin=EvidenceOrigin.PHYSICAL)
    with pytest.raises(ValueError, match="must name its fixture"):
        CommissionedPoseSource(Producer(), origin=EvidenceOrigin.REPLAY)
    with pytest.raises(ValueError, match="must not carry a fixture label"):
        CommissionedPoseSource(
            Producer(), origin=EvidenceOrigin.PHYSICAL, fixture_label="a-recording"
        )


def test_an_empty_sweep_is_still_no_scan_and_still_has_a_pose() -> None:
    """HW-3's branch preserved, and the one place the two channels differ.

    A sweep with no returns is a real answer from a LiDAR: ``ranges_m == ()``,
    no scan datum, SCAN missing -> HOLD. The tick still HAS a pose, so the pose
    datum is recorded for it — the asymmetry the seam is built around.
    """

    clock = Clock()
    sock = FakeLivoxSocket(clock)
    backend, state = _live_backend(clock, sock)
    state.deliver()
    scanless = backend.observe()  # the socket was never fed

    assert scanless.lidar_ranges == ()
    assert backend.scan_datum_for(scanless) is None
    assert backend.scan_evidence_source.evidence(scanless) is None
    pose = backend.pose_evidence_source.evidence(scanless)
    assert pose is not None and pose.payload_valid is True
    assert _pose_verdict(pose, now=clock.t + 0.01).action is HealthAction.ALLOW


# ======================================================================
# A23 — the drain is bounded, whatever the socket does
# ======================================================================


def test_a23_an_all_corrupt_flood_is_bounded_by_the_datagram_budget() -> None:
    """The clock cannot help here, so the datagram budget must.

    A refused datagram deliberately does not consume a frame slot (that is what
    makes one corrupt datagram cost one datagram), so ``max_frames`` alone never
    ends this loop and the old drain span for as long as the sender sent.
    """

    clock = Clock()
    sock = EndlessCorruptSocket(clock)  # the clock never advances on a read
    source = LiveGo2Sources(
        state_source=DdsStateSource(clock), socket=sock, clock=clock, max_frames_per_drain=8
    )

    assert source.drain() == ()
    assert sock.reads == source.max_datagrams_per_drain == 32
    assert source.refused_datagrams == 32, "every datagram was refused, one at a time"
    assert source.bounded_drains == 1
    assert clock.t == 500.0, "no wall clock was spent; the budget still held"


def test_a23_a_flood_that_costs_time_is_bounded_by_the_wall_budget() -> None:
    """The other belt: whatever the transport does, the tick is bounded."""

    clock = Clock()
    sock = EndlessCorruptSocket(clock, per_read_s=0.01)
    source = LiveGo2Sources(
        state_source=DdsStateSource(clock),
        socket=sock,
        clock=clock,
        max_frames_per_drain=32,
        drain_budget_s=0.02,
    )

    assert source.drain() == ()
    assert clock.t - 500.0 == pytest.approx(0.02), "the drain stopped on the budget"
    assert sock.reads == 2 and sock.reads < source.max_datagrams_per_drain
    assert source.bounded_drains == 1


def test_a23_a_socket_that_went_blocking_is_never_read_and_never_costs_the_pose() -> None:
    """A blocking ``recv`` cannot be interrupted, so it is not entered.

    ``_checked_socket`` refuses a blocking socket at CONSTRUCTION; this is the
    same question asked again at every drain, because blocking mode is mutable
    state on an object this class does not always own. The cost is exactly a
    quiet sensor's: an empty band, "no scan", HOLD — and the pose, taken before
    the drain, is untouched.
    """

    class WentBlocking(FakeLivoxSocket):
        def gettimeout(self) -> None:
            return None

        def recv(self, _max_bytes: int) -> bytes:
            raise AssertionError("a blocking recv() was entered on the control loop")

    clock = Clock()
    sock = FakeLivoxSocket(clock)
    backend, state = _live_backend(clock, sock)
    state.deliver()
    backend.source._socket = WentBlocking(clock)  # setblocking(True) behind our back

    observation = backend.observe()
    assert backend.source.refused_blocking_drains == 1
    assert observation.lidar_ranges == ()
    assert backend.scan_evidence_source.evidence(observation) is None
    assert backend.pose_evidence_source.evidence(observation) is not None


def test_a23_a_corrupt_datagram_still_costs_exactly_one_datagram() -> None:
    """PRESERVED: F4's semantics survive the two new budgets, unchanged.

    A corrupt datagram between two good ones costs itself and nothing else —
    not the frames already read, not the good datagram queued behind it, and
    not the tick.
    """

    clock = Clock()
    sock = FakeLivoxSocket(clock)
    source = LiveGo2Sources(state_source=DdsStateSource(clock), socket=sock, clock=clock)
    sock.push(_datagram(1), b"\x00" * 40, _datagram(2))

    frames = source.drain()
    assert [frame.udp_cnt for frame in frames] == [1, 2]
    assert source.refused_datagrams == 1
    assert sock.queue == [], "the good datagram behind the corrupt one was read"
    assert source.bounded_drains == 0


# ======================================================================
# X06 — the resolved profile
# ======================================================================


def _profile_tree(tmp_path: Path, overlay: dict[str, Any]) -> Path:
    """A byte copy of the shipped base plus a real sibling overlay, on disk."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    base = tmp_path / "robot.yaml"
    base.write_text(BASE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    sibling = tmp_path / f"robot.{PROFILE_NAME}.yaml"
    sibling.write_text(yaml.safe_dump(overlay, sort_keys=False), encoding="utf-8")
    return base


def _shipped_overlay() -> dict[str, Any]:
    return yaml.safe_load(PROFILE.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("path", "inherited"), INHERITED_PREMISES)
def test_x06_an_unresolved_simulator_premise_refuses_at_load_by_name(
    tmp_path: Path, path: str, inherited: object
) -> None:
    """The defect, one key at a time, through the loader an operator uses.

    Reproduced first: each value really is inherited — the profile sets none of
    them. Then the profile's declaration for that one key is removed and the
    load refuses, naming the key, the value it would have inherited, and the
    fix.
    """

    overlay = _shipped_overlay()
    merged = ConfigStore(BASE_CONFIG, profile=PROFILE_NAME).data
    node: Any = merged
    for part in path.split("."):
        node = node[part]
    assert node == inherited, "the resolved profile still carries the base's value"
    assert path not in yaml.safe_dump(overlay).split("physical_resolution")[0]

    section = overlay["physical_resolution"]
    for disposition in (PHYSICAL_RESOLUTION_ABSENT, PHYSICAL_RESOLUTION_KEPT):
        section[disposition] = [key for key in section.get(disposition, []) if key != path]
    base = _profile_tree(tmp_path, overlay)

    with pytest.raises(PhysicalProfileError) as refusal:
        ConfigStore(base, profile=PROFILE_NAME)
    message = str(refusal.value)
    assert path in message
    assert repr(inherited) in message
    assert "Fix:" in message


def test_x06_the_shipped_profile_resolves_every_premise_and_still_merges_transparently(
    tmp_path: Path,
) -> None:
    """The fix, and the two things it deliberately does NOT do.

    It does not delete anything from the merge (HW-5's transparency row still
    holds), and it does not let the profile WRITE the two keys its own header
    forbids — the disposition is the only way to disown them.
    """

    del tmp_path
    store = ConfigStore(BASE_CONFIG, profile=PROFILE_NAME)
    assert set(store.physical_resolution) == set(PHYSICAL_PREMISE_KEYS)
    assert store.physical_resolution["control.controller"] == PHYSICAL_RESOLUTION_KEPT
    assert store.physical_resolution["battery.simulated_percent"] == PHYSICAL_RESOLUTION_ABSENT
    assert store.data["battery"] == yaml.safe_load(BASE_CONFIG.read_text())["battery"]

    overlay = _shipped_overlay()
    assert "battery" not in overlay and "control" not in overlay

    # And a configuration that is not a named physical rig declares nothing.
    assert ConfigStore(BASE_CONFIG, profile="").physical_resolution == {}


def test_x06_a_disowned_key_refuses_at_use_and_a_measured_one_wins(tmp_path: Path) -> None:
    """The USE half: box-day keys refuse by name instead of defaulting.

    And the operator gesture the tree already pins — filling `backend.interface`
    in at step B9 and nothing else — resolves the key by ANSWERING it, so a
    stale declaration cannot refuse the fix.
    """

    store = ConfigStore(BASE_CONFIG, profile=PROFILE_NAME)
    for path in ("battery.simulated_percent", "backend.interface"):
        with pytest.raises(PhysicalProfileError) as refusal:
            store.physical_value(path)
        assert path in str(refusal.value)
    assert store.physical_value("control.controller") == "simulator"

    overlay = _shipped_overlay()
    overlay["backend"]["interface"] = "eth0"
    filled = ConfigStore(_profile_tree(tmp_path, overlay), profile=PROFILE_NAME)
    assert filled.physical_resolution["backend.interface"] == PHYSICAL_RESOLUTION_SET
    assert filled.physical_value("backend.interface") == "eth0"


def test_x06_a_declaration_about_a_key_the_loader_does_not_check_is_refused(
    tmp_path: Path,
) -> None:
    """The section's own spelling guard, at the read site that admits it.

    ``physical_resolution`` is one exempt subtree, so ``check_overlay_keys``
    merges anything inside it. This is the guard that makes that honest.
    """

    overlay = _shipped_overlay()
    overlay["physical_resolution"][PHYSICAL_RESOLUTION_ABSENT].append("battery.simulated_percnt")
    with pytest.raises(PhysicalProfileError, match="battery.simulated_percnt"):
        ConfigStore(_profile_tree(tmp_path, overlay), profile=PROFILE_NAME)


# ======================================================================
# Mount-day readiness
# ======================================================================


def test_the_mid360_row_reports_the_socket_and_the_decoder_separately() -> None:
    """Three answers, and the difference between them is what an operator needs.

    A datagram on the wire is READY; a bound and quiet port is PARTIAL with
    ``no_message``; a port that cannot be bound is ABSENT with the OS's own
    reason. Nothing here binds a real port.
    """

    live = FakeLivoxSocket()
    live.push(_datagram(7))
    ready = probe_mid360_udp(opener=lambda host, port: live, listen_s=0.01)
    assert ready.readiness is MountReadiness.READY
    assert ready.absence is None and "39 points decoded" in ready.evidence

    quiet = probe_mid360_udp(opener=lambda host, port: FakeLivoxSocket(), listen_s=0.01)
    assert quiet.readiness is MountReadiness.PARTIAL
    assert quiet.absence is AbsenceReason.NO_MESSAGE
    assert "56301" in quiet.evidence and quiet.remedy

    def refuse(host: str, port: int) -> Any:
        raise OSError(98, "Address already in use")

    blocked = probe_mid360_udp(opener=refuse, listen_s=0.01)
    assert blocked.readiness is MountReadiness.ABSENT
    assert blocked.absence is AbsenceReason.PROBE_RAISED
    assert "Address already in use" in blocked.absence_detail


def test_the_d455_row_separates_a_missing_wheel_from_a_missing_camera() -> None:
    """The two halves TRUTH-1 split for the identity row, as one readiness row."""

    from scripts.parcel_capture.ingest.base import (
        DependencyReport,
        DevicePresence,
        DeviceReport,
    )

    def reports(*, satisfied: bool, presence: DevicePresence) -> Any:
        return lambda: (
            DependencyReport(
                adapter="realsense",
                satisfied=satisfied,
                present=("pyrealsense2",) if satisfied else (),
                missing=() if satisfied else ("pyrealsense2",),
                remedy="pip install pyrealsense2",
            ),
            DeviceReport(
                adapter="realsense",
                presence=presence,
                detail="nothing matches /dev/video*",
                remedy="plug it in",
                nodes=("video*",),
            ),
        )

    absent = probe_d455_mount(reports(satisfied=False, presence=DevicePresence.ABSENT))
    assert absent.readiness is MountReadiness.ABSENT
    assert absent.absence is AbsenceReason.DEPENDENCY_MISSING

    partial = probe_d455_mount(reports(satisfied=True, presence=DevicePresence.ABSENT))
    assert partial.readiness is MountReadiness.PARTIAL
    assert partial.absence is AbsenceReason.DEVICE_NODE_MISSING
    assert "USB 3 (BLUE)" in partial.remedy

    ready = probe_d455_mount(reports(satisfied=True, presence=DevicePresence.ATTACHED))
    assert ready.readiness is MountReadiness.READY and ready.absence is None


def test_the_xvf3800_row_reads_the_kernels_card_list_and_opens_nothing(
    tmp_path: Path,
) -> None:
    """The array is READY on a host that has one, and typed-absent on one that does not.

    It READS ``/proc/asound/cards``. Opening the device is the audio stack's
    job and it happens on the owner's gesture, never in a preflight.
    """

    cards = tmp_path / "cards"
    cards.write_text(
        " 0 [NVidia         ]: HDA-Intel - HDA NVidia\n"
        " 1 [Array          ]: USB-Audio - reSpeaker XVF3800 4-Mic Array\n",
        encoding="utf-8",
    )
    ready = probe_xvf3800_mount(asound_cards=cards)
    assert ready.readiness is MountReadiness.READY
    assert "XVF3800" in ready.evidence

    bare = tmp_path / "bare"
    bare.write_text(" 0 [NVidia         ]: HDA-Intel - HDA NVidia\n", encoding="utf-8")
    missing = probe_xvf3800_mount(asound_cards=bare)
    assert missing.readiness is MountReadiness.PARTIAL
    assert missing.absence is AbsenceReason.DEVICE_NODE_MISSING

    no_module = probe_xvf3800_mount(asound_cards=cards, modules=("a_module_nobody_ships",))
    assert no_module.readiness is MountReadiness.ABSENT
    assert no_module.absence is AbsenceReason.DEPENDENCY_MISSING


def test_one_preflight_run_reports_all_three_mount_day_channels(tmp_path: Path) -> None:
    """The card's actual deliverable: ONE command, three rows, typed absence.

    The rows are injected so this test binds no port and touches no camera; what
    is measured is that ``run_preflight`` carries them, that they reach the
    operator's report above the matrix, and that the JSON a mount-day session
    keeps has them too.
    """

    rows = (
        probe_mid360_udp(opener=lambda host, port: FakeLivoxSocket(), listen_s=0.0),
        probe_d455_mount(),
        probe_xvf3800_mount(asound_cards=tmp_path / "no-such-cards"),
    )
    report = run_preflight(
        reader_factory=lambda entry: (_ for _ in ()).throw(RuntimeError("no hardware")),
        window_s=0.01,
        storage_path=tmp_path,
        mount_readiness=rows,
    )

    assert [row.channel for row in report.mount_readiness] == [
        "mid360.udp",
        "d455.path",
        "xvf3800.array",
    ]
    for row in report.mount_readiness:
        assert row.readiness is not MountReadiness.READY
        assert row.absence is not None and row.absence_detail and row.remedy

    text = format_report(report)
    assert "MOUNT READINESS" in text
    for row in report.mount_readiness:
        assert row.channel in text
        assert f"why: {row.absence.value}" in text
    assert [row["channel"] for row in report.to_dict()["mount_readiness"]] == [
        "mid360.udp",
        "d455.path",
        "xvf3800.array",
    ]
