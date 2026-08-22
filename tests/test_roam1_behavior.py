"""Card ROAM-1 — "go explore" is a behavior, a tool and a closed intent.

Four guards, each with a seeded-RED proof recorded in ``ROAM1_STATUS.md``:

  S1  a roam that runs past its budget
  S2  a roam that survives an e-stop
  S3  a roam reachable from a system-initiated turn
  S4  ``time_s`` missing from the navigator's extras again

Plus the derivation the prototype profile depends on (P1-E's
``safety.person_stop_m`` commissioning the patrol's own standoff) and the
closed-intent table's two new entries.

Everything here runs the PRODUCT code path: the runtime's own ``_step_roam``,
the runtime's own ``_navigation_extras``, the shipped broker and the shipped
ingress. Nothing re-implements a policy and nothing constructs a parallel
runner — MOVE-1's harness proved the policy moves a body and this card is about
whether the product ever asks it to.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.config import PROFILE_ENV
from parcel_robot.models import AgentDecision
from parcel_robot.patrol import (
    FORWARD_CLEARANCE_MARGIN_M,
    PERSON_CLEARANCE_MARGIN_M,
    PatrolLimits,
    PatrolPolicy,
    PatrolSense,
    limits_from_safety,
)
from parcel_robot.realtime.config import (
    PROACTIVE_MOTION_ALLOWED,
    PROACTIVE_MOTION_REFUSED,
    REALTIME_CONFIG_ENV,
)
from parcel_robot.realtime.ingress import (
    KIND_EMERGENCY,
    KIND_ROAM,
    KIND_ROAM_STOP,
    ROAM_START_PHRASES,
    ROAM_STOP_PHRASES,
    scan,
)
from parcel_robot.realtime.tool_broker import (
    ACTIVITY_TOOLS,
    MOTION_TOOLS,
    PROACTIVE_MOTION_CEILING,
    REFUSAL_SYSTEM_INITIATED_MOTION,
    RESPONSE_FROM_OWNER,
    RESPONSE_FROM_SYSTEM,
    ROAM_MAX_MINUTES,
    STATUS_OK,
    STATUS_REJECTED,
    TENSE_STARTED,
    TOOL_ROAM,
    RealtimeToolBroker,
    ToolDoors,
    build_tool_specs,
)
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "roam1"


# ==========================================================================
# 1. The derivation — P1-E's config reaches the patrol's own thresholds
# ==========================================================================
def test_the_shipped_numbers_reproduce_the_shipped_defaults() -> None:
    """The derivation is not a re-tuning: fed the old numbers it returns them.

    ``PatrolLimits``' defaults (1.35 m person, 1.5 m forward) were written
    against the SHIPPED gate (``person_stop_m`` 1.2, ``obstacle_stop_m`` 0.65).
    If ``limits_from_safety`` did not reproduce them exactly, every MOVE-1
    measurement would silently stop being comparable.
    """

    shipped = PatrolLimits()
    derived = limits_from_safety(person_stop_m=1.2, obstacle_stop_m=0.65)

    assert derived.min_person_clearance_m == pytest.approx(shipped.min_person_clearance_m)
    assert derived.min_forward_clearance_m == pytest.approx(shipped.min_forward_clearance_m)
    # The ONE field that deliberately differs, and it differs in one direction:
    # MOVE-1's measured baseline keeps the shipped default (off) so its numbers
    # stay comparable, and the roam behavior — the only caller of this function
    # — gets the alternation that stopped it circling.
    assert shipped.alternate_turns is False
    assert derived.alternate_turns is True


def test_a_patrol_that_always_turns_the_same_way_closes_into_a_circle() -> None:
    """The measured defect, as a property, at the level it actually lives.

    Three consecutive 120 s product runs measured 21.85 m of path against
    0.14 m of net displacement and 1404 degrees of heading change — 3.90 full
    turns, all one way. This is that, in eight lines: with the flag off every
    avoidance turn has the same sign; with it on they alternate.
    """

    def signs(*, alternate: bool) -> list[int]:
        limits = PatrolLimits(alternate_turns=alternate)
        policy = PatrolPolicy(limits)
        out: list[int] = []
        elapsed = 0.0
        for _ in range(4):
            # Blocked: one turn tick, which is one avoidance episode.
            blocked = policy.step(
                PatrolSense(elapsed_s=elapsed, x=0.0, y=0.0, yaw=0.0, forward_clearance_m=0.5)
            )
            assert blocked.reason == "turn_blocked"
            out.append(1 if blocked.vyaw > 0 else -1)
            elapsed += 0.25
            # Clear again: the turn RELEASES, which is where the sign may flip.
            release = policy.step(
                PatrolSense(elapsed_s=elapsed, x=0.0, y=0.0, yaw=0.0, forward_clearance_m=9.0)
            )
            assert release.reason == "advance"
            elapsed += 0.25
        return out

    assert signs(alternate=False) == [1, 1, 1, 1], "the shipped policy circles"
    assert signs(alternate=True) == [1, -1, 1, -1], "the roam policy alternates"


def test_the_prototype_social_zone_moves_the_patrols_standoff_with_it() -> None:
    """P1-E made the zone a config; the roam behavior must follow it.

    A patrol still keeping 1.35 m on a robot whose gate only refuses inside
    0.7 m is not being careful — it is turning away from lanes the gate would
    have allowed, which is E2-D2's budget-burning failure from the other side.
    """

    derived = limits_from_safety(person_stop_m=0.7, obstacle_stop_m=0.65)

    assert derived.min_person_clearance_m == pytest.approx(0.7 + PERSON_CLEARANCE_MARGIN_M)
    assert derived.min_forward_clearance_m == pytest.approx(0.65 + FORWARD_CLEARANCE_MARGIN_M)
    # And it is still strictly OUTSIDE the gate: a proposer inside the refusal
    # radius is the one thing this function may never produce.
    assert derived.min_person_clearance_m > 0.7
    assert derived.min_forward_clearance_m > 0.65


def test_a_nonsense_safety_number_is_refused_rather_than_defaulted() -> None:
    for kwargs in (
        {"person_stop_m": 0.0, "obstacle_stop_m": 0.65},
        {"person_stop_m": 0.7, "obstacle_stop_m": -1.0},
        {"person_stop_m": math.inf, "obstacle_stop_m": 0.65},
    ):
        with pytest.raises(ValueError):
            limits_from_safety(**kwargs)


# ==========================================================================
# 2. The closed intents — appended, and they do not shadow anything
# ==========================================================================
@pytest.mark.parametrize("phrase", sorted(ROAM_START_PHRASES))
def test_every_start_phrase_reads_as_a_roam(phrase: str) -> None:
    assert scan(phrase).kind == KIND_ROAM
    # Punctuated, because a hosted transcriber writes "Go explore." and every
    # phrase set in this repo is unpunctuated. R1's whole reason for existing.
    assert scan(f"{phrase.capitalize()}.").kind == KIND_ROAM


@pytest.mark.parametrize("phrase", sorted(ROAM_STOP_PHRASES))
def test_every_stop_phrase_reads_as_a_roam_stop(phrase: str) -> None:
    assert scan(phrase).kind == KIND_ROAM_STOP
    assert scan(f"{phrase}!").kind == KIND_ROAM_STOP


def test_the_bare_word_stop_is_still_an_emergency() -> None:
    """The one thing the roam table may never do is widen the mouth of "stop".

    ``stop roaming`` is a roam stop; ``stop`` is the e-stop, and it is matched
    above the roam branches so no ordering exists in which a roam phrase could
    swallow a latch.
    """

    assert scan("stop").kind == KIND_EMERGENCY
    assert scan("Stop.").kind == KIND_EMERGENCY
    assert scan("halt").kind == KIND_EMERGENCY
    assert scan("die stop").kind == KIND_EMERGENCY


def test_the_roam_phrases_do_not_collide_with_the_older_grammars() -> None:
    """Appended means appended: nothing above the roam branches changed."""

    from parcel_robot.realtime.ingress import (
        EMERGENCY_STOP_PHRASES,
        follow_phrases,
        hold_phrases,
    )

    older = set(EMERGENCY_STOP_PHRASES) | set(follow_phrases()) | set(hold_phrases())
    assert not (ROAM_START_PHRASES & older)
    assert not (ROAM_STOP_PHRASES & older)
    assert not (ROAM_START_PHRASES & ROAM_STOP_PHRASES)


# ==========================================================================
# 3. The tool — S3's guard: roam is never proactive
# ==========================================================================
class _Doors:
    def __init__(self, *, approve: bool = True) -> None:
        self.approve = approve
        self.touched: list[tuple[str, tuple]] = []
        self.validated: list[object] = []
        self.dispatches = 0

    def validate(self, call):
        from parcel_robot.models import ToolResult

        self.validated.append(call)
        return ToolResult(call.name, self.approve, "approved" if self.approve else "latched")

    def status(self) -> dict[str, object]:
        return {"emergency_stopped": False}

    def recall(self, query: str) -> str:
        return f"recalled:{query}"

    def gesture(self, name: str, intensity: float) -> str:
        self.touched.append(("gesture", (name, intensity)))
        return "Accepted: queued"

    def pose(self, name: str) -> str:
        self.touched.append(("pose", (name,)))
        return "Accepted: queued"

    def navigate(self, place: str, relation: str = "") -> str:
        self.touched.append(("navigate", (place, relation)))
        return "Okay—I'll head there."

    def roam(self, action: str, budget_s: float) -> str:
        self.touched.append(("roam", (action, budget_s)))
        return "Roaming for the next 120 seconds"

    def on_dispatch(self) -> None:
        self.dispatches += 1

    def as_doors(self) -> ToolDoors:
        return ToolDoors(
            validate=self.validate,
            status=self.status,
            recall=self.recall,
            gesture=self.gesture,
            pose=self.pose,
            navigate=self.navigate,
            roam=self.roam,
            on_dispatch=self.on_dispatch,
        )


def _answer(broker: RealtimeToolBroker, arguments: str = "{}") -> dict:
    return json.loads(broker.handle(name=TOOL_ROAM, call_id="call_roam", arguments=arguments))


def test_roam_is_a_motion_tool_and_can_never_be_proactive() -> None:
    """S3's guard, stated as a property before it is exercised."""

    assert TOOL_ROAM in MOTION_TOOLS
    assert TOOL_ROAM in ACTIVITY_TOOLS
    assert TOOL_ROAM not in PROACTIVE_MOTION_CEILING
    assert TOOL_ROAM in PROACTIVE_MOTION_REFUSED
    assert TOOL_ROAM not in PROACTIVE_MOTION_ALLOWED
    # The tuple that decides what a config MAY name still covers the whole
    # motion surface, so a tenth tool cannot join it without a written verdict.
    assert set(PROACTIVE_MOTION_ALLOWED) | set(PROACTIVE_MOTION_REFUSED) == set(MOTION_TOOLS)


def test_a_system_initiated_turn_cannot_send_the_dog_off() -> None:
    """S3. The robot talked to itself; the body does not leave."""

    doors = _Doors()
    broker = RealtimeToolBroker(doors.as_doors())
    broker.note_response_provenance(RESPONSE_FROM_SYSTEM)

    result = _answer(broker, '{"action": "start", "minutes": 2}')

    assert result["status"] == STATUS_REJECTED
    assert result["refusal"] == REFUSAL_SYSTEM_INITIATED_MOTION
    assert doors.touched == [], "a proactive roam reached the runtime door"
    assert doors.validated == [], "the gate must sit AHEAD of the supervisor"


def test_a_config_that_names_roam_proactive_is_still_refused_at_the_broker() -> None:
    """The ceiling, enforced in the broker as well as at config load."""

    doors = _Doors()
    broker = RealtimeToolBroker(doors.as_doors(), proactive_motion_tools=[TOOL_ROAM])
    broker.note_response_provenance(RESPONSE_FROM_SYSTEM)

    result = _answer(broker, "{}")

    assert result["status"] == STATUS_REJECTED
    assert result["refusal"] == REFUSAL_SYSTEM_INITIATED_MOTION
    assert doors.touched == []
    assert broker.snapshot()["proactive_motion_tools"] == []


def test_the_owner_asking_reaches_the_door_and_reads_as_started() -> None:
    doors = _Doors()
    broker = RealtimeToolBroker(doors.as_doors())
    broker.note_response_provenance(RESPONSE_FROM_OWNER)

    result = _answer(broker, '{"action": "start", "minutes": 2}')

    assert result["status"] == STATUS_OK, result
    assert result["tense"] == TENSE_STARTED
    assert result["finished"] is False
    assert doors.touched == [("roam", ("start", 120.0))]
    # The promise stays on the record; the model reads the fact.
    assert result["admitted"] == "Roaming for the next 120 seconds"
    assert result["admitted"] not in result["detail"]


def test_an_absurd_budget_is_clamped_and_the_clamp_is_reported() -> None:
    """A model guessing at a unit is not a safety error; a silent fix would be."""

    doors = _Doors()
    broker = RealtimeToolBroker(doors.as_doors())
    result = _answer(broker, '{"action": "start", "minutes": 600}')

    assert result["status"] == STATUS_OK
    assert result["minutes"] == pytest.approx(ROAM_MAX_MINUTES)
    assert result["minutes_clamped"] is True
    assert doors.touched == [("roam", ("start", ROAM_MAX_MINUTES * 60.0))]


def test_the_declared_tool_forbids_a_destination_and_an_ending() -> None:
    spec = next(row for row in build_tool_specs() if row["name"] == TOOL_ROAM)
    description = str(spec["description"]).lower()

    assert "never" in description
    assert "started" in description
    # The patrol prompt's lineage, carried rather than re-worded.
    assert "idle checkpoint" in description
    assert "report" in description or "blocker" in description


# ==========================================================================
# 4. The runtime behavior — S1 (budget) and S2 (e-stop)
# ==========================================================================
class _Backend:
    """A backend whose clock and clearance the test drives directly."""

    name = BACKEND_NAME

    def __init__(self) -> None:
        self.timestamp = 1.0
        self.obstacle_m = 10.0
        self.commands: list[object] = []

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=self.timestamp,
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=self.obstacle_m,
            backend=BACKEND_NAME,
        )

    def move(self, command: object) -> None:
        self.commands.append(command)

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context
        return AgentDecision("Understood.")


def _runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, overlay: str | None = None
) -> RobotRuntime:
    """``overlay`` is written as a ``demo`` PROFILE beside the base config.

    A profile rather than extra lines in the base file, because the roam knobs
    only ever arrive through an overlay in real use and the overlay is the half
    that was broken: ``config.check_overlay_keys`` refuses any key path the
    SHA-locked base does not define, so a ``roam:`` block needed an explicit
    exemption before it could reach anything.
    """

    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.delenv(REALTIME_CONFIG_ENV, raising=False)
    path = tmp_path / "roam1-robot.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    if overlay is None:
        monkeypatch.delenv(PROFILE_ENV, raising=False)
    else:
        # The profile reaches RobotRuntime the way the launcher delivers it —
        # through the environment. `RobotRuntime.__init__` builds its own
        # ConfigStore and takes no profile argument, so setting the env var IS
        # the product path.
        (tmp_path / "roam1-robot.demo.yaml").write_text(overlay, encoding="utf-8")
        monkeypatch.setenv(PROFILE_ENV, "demo")
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="roam1 fixture",
        ),
    )


def _observation(runtime: RobotRuntime) -> SimObservation:
    """One fresh observation, stamped on the runtime's own freshness clock."""

    import time as _time

    backend = runtime.backend
    backend.timestamp = _time.monotonic()
    return backend.observe()


def test_go_explore_through_the_hosted_ingress_starts_the_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The product path, end to end, without the model saying anything."""

    runtime = _runtime(tmp_path / "start", monkeypatch)
    try:
        assert runtime.roam_snapshot()["active"] is False
        outcome = runtime.submit_realtime_transcript("Go explore.")

        assert outcome.kind == KIND_ROAM
        assert outcome.executed is True
        snapshot = runtime.roam_snapshot()
        assert snapshot["active"] is True
        assert snapshot["budget_s"] == pytest.approx(RobotRuntime.DEFAULT_ROAM_BUDGET_S)
        # And the panel can see it without opening a log.
        assert runtime.snapshot()["roam"]["active"] is True
    finally:
        runtime.close()


def test_stop_roaming_latches_to_idle_in_one_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path / "stop", monkeypatch)
    try:
        runtime.submit_realtime_transcript("go explore")
        assert runtime.roam_snapshot()["active"] is True

        outcome = runtime.submit_realtime_transcript("stop roaming")

        assert outcome.kind == KIND_ROAM_STOP
        assert outcome.executed is True
        assert runtime.roam_snapshot()["active"] is False
        # Idempotent: said twice it is a calm confirmation, not an error.
        again = runtime.submit_realtime_transcript("stop roaming")
        assert again.executed is True
        assert again.error == ""
    finally:
        runtime.close()


def test_a_roam_ends_when_its_budget_runs_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S1. Remove the budget branch from ``_step_roam`` and this reddens."""

    runtime = _runtime(tmp_path / "budget", monkeypatch)
    try:
        runtime.start_roam(RobotRuntime.MIN_ROAM_BUDGET_S)
        assert runtime.roam_snapshot()["active"] is True

        # Wind the start stamp back past the budget rather than sleeping for it.
        with runtime._lock:
            runtime._roam_started_at -= RobotRuntime.MIN_ROAM_BUDGET_S + 1.0
        runtime._step_roam(_observation(runtime))

        assert runtime.roam_snapshot()["active"] is False
        assert runtime.roam_snapshot()["reason"] == "budget_exhausted"
    finally:
        runtime.close()


def test_a_roam_ends_at_its_budget_even_with_no_observation_at_all(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S1, isolated. Remove the runtime's budget branch and this reddens.

    The FIRST version of this test could not tell the two budget guards apart:
    the policy carries the same ``budget_s`` and returns ``budget_exhausted``
    from its own ladder, so seeding the runtime's branch alone still ended the
    roam and the seed came back green. Measured, not assumed.

    The case that separates them is a roam whose eye has gone quiet. The policy
    is never asked anything without a pose, so only the runtime's own check can
    end this one — and a roam that outlives its budget because the camera
    stopped talking is a dog that never comes back.
    """

    runtime = _runtime(tmp_path / "budget-blind", monkeypatch)
    try:
        runtime.start_roam(RobotRuntime.MIN_ROAM_BUDGET_S)
        with runtime._lock:
            runtime._roam_started_at -= RobotRuntime.MIN_ROAM_BUDGET_S + 1.0

        runtime._step_roam(None)  # no observation this tick, and none coming

        assert runtime.roam_snapshot()["active"] is False
        assert runtime.roam_snapshot()["reason"] == "budget_exhausted"
    finally:
        runtime.close()


def test_a_latched_estop_ends_a_roam_on_the_next_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S2. Remove the latch branch from ``_step_roam`` and this reddens.

    The point is not that the commands would be refused — they would — but that
    a roam whose commands were merely refused RESUMES the instant the latch
    clears, which is a dog that remembers an errand nobody re-issued.
    """

    runtime = _runtime(tmp_path / "estop", monkeypatch)
    try:
        runtime.start_roam()
        assert runtime.roam_snapshot()["active"] is True

        runtime.emergency_stop()
        runtime._step_roam(_observation(runtime))

        assert runtime.roam_snapshot()["active"] is False
        assert runtime.roam_snapshot()["reason"] == "emergency_stop"
    finally:
        runtime.close()


def test_a_roam_cannot_be_started_under_a_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path / "latched", monkeypatch)
    try:
        runtime.emergency_stop()
        with pytest.raises(RuntimeError):
            runtime.start_roam()
        assert runtime.roam_snapshot()["active"] is False
    finally:
        runtime.close()


def test_an_owner_command_ends_the_roam_rather_than_outbidding_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """"Yields to any owner command" — by STOPPING, which is the honest way.

    A roam that merely lost an arbitration bid would resume underneath the
    owner's own behavior the moment that behavior paused.
    """

    runtime = _runtime(tmp_path / "yield", monkeypatch)
    try:
        runtime.start_roam()
        runtime.set_behavior("follow")
        runtime._step_roam(_observation(runtime))

        assert runtime.roam_snapshot()["active"] is False
        assert runtime.roam_snapshot()["reason"] == "owner_command"
    finally:
        runtime.close()


def test_a_second_roam_is_refused_while_one_is_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path / "double", monkeypatch)
    try:
        runtime.start_roam()
        with pytest.raises(ValueError):
            runtime.start_roam()
    finally:
        runtime.close()


def test_the_idle_checkpoint_is_published_for_curio1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The patrol prompt's rule, as a predicate another card can read.

    ``prompts/functions/patrol.yaml``: "social actions can wait until an idle
    checkpoint". A robot that is not roaming is nothing but a checkpoint.
    """

    runtime = _runtime(tmp_path / "checkpoint", monkeypatch)
    try:
        assert runtime.roam_idle_checkpoint() is True
        runtime.start_roam()
        runtime._step_roam(_observation(runtime))
        # A clear lane cruises, and cruising between legs is a checkpoint.
        assert runtime.roam_idle_checkpoint() is True
        assert runtime.roam_snapshot()["reason"] == "advance"
    finally:
        runtime.close()


def test_a_blocked_lane_is_a_turn_and_a_turn_is_not_a_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path / "turning", monkeypatch)
    try:
        runtime.start_roam()
        runtime.backend.obstacle_m = 0.4  # inside the derived forward threshold
        runtime._step_roam(_observation(runtime))

        assert runtime.roam_snapshot()["reason"] == "turn_blocked"
        assert runtime.roam_idle_checkpoint() is False
    finally:
        runtime.close()


# ==========================================================================
# 5. The navigator's clock — S4
# ==========================================================================
def test_the_navigation_extras_carry_the_observation_clock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S4. Delete the ``time_s`` line and this reddens.

    Without it ``pipeline.py``'s tracker falls to its ``dt = 0.1`` literal on
    every tick regardless of ``loop_hz``, and every
    ``float(extras.get("time_s") or 0.0)`` reads zero, so no memory or goal TTL
    ever advances.
    """

    runtime = _runtime(tmp_path / "clock", monkeypatch)
    try:
        runtime.backend.timestamp = 1234.5
        extras = runtime._navigation_extras(runtime.backend.observe())

        assert "time_s" in extras, "the navigator is back on a frozen clock"
        assert extras["time_s"] == pytest.approx(1234.5)

        runtime.backend.timestamp = 1234.6
        later = runtime._navigation_extras(runtime.backend.observe())
        assert later["time_s"] > extras["time_s"], "the clock must advance"
    finally:
        runtime.close()


def test_the_headless_eval_builder_carries_the_same_clock() -> None:
    """The evals ran on the frozen clock too, which is why they never saw it."""

    from parcel_robot.headless_city import _nav_observation
    from parcel_robot.models import VelocityCommand

    observation = SimObservation(
        timestamp=42.5,
        robot=RobotPose(),
        owner=OwnerTrack(),
        nearest_obstacle_m=5.0,
        backend=BACKEND_NAME,
    )
    built = _nav_observation(
        observation,
        measured_velocity=VelocityCommand(),
        stop_confirmed=True,
        settled_linear_speed_mps=0.05,
        settled_yaw_speed_rad_s=0.05,
    )

    assert built.extras["time_s"] == pytest.approx(42.5)


# ==========================================================================
# 6. CORRECTION PASS — the guards the verifier's findings earned
# ==========================================================================
def _product_broker(runtime: RobotRuntime) -> RealtimeToolBroker:
    """A broker wired to the runtime's REAL doors, not a stub.

    THE DEFECT THIS EXISTS FOR. ROAM-1's first pass tested `TOOL_ROAM` against
    a `_Doors` fixture whose `validate` approved everything, so it proved the
    broker's routing and nothing about the authority the broker routes into.
    The verifier built one of these instead and found the tool dead on the
    product path: `SafetySupervisor._validate_behavior`'s allowlist did not
    contain `roam`, so an owner asking got `Unknown behavior: roam` while
    `follow_owner` sailed through the same door. A guard that mocks the
    authority it is guarding is not a guard.
    """

    return RealtimeToolBroker(
        ToolDoors(
            validate=runtime._realtime_validate,
            status=lambda: {"emergency_stopped": False},
            recall=lambda query: f"recalled:{query}",
            gesture=lambda name, intensity: "Accepted: queued",
            pose=lambda name: "Accepted: queued",
            navigate=lambda place, relation="": "Accepted: going",
            roam=runtime._realtime_roam,
        )
    )


def test_the_roam_tool_is_admitted_by_the_PRODUCT_supervisor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S5. Remove 'roam'/'roam_stop' from safety.BEHAVIOR_MODES -> RED.

    Start and stop, both through the real `SafetySupervisor.validate`.
    """

    runtime = _runtime(tmp_path / "product-broker", monkeypatch)
    try:
        broker = _product_broker(runtime)
        broker.note_response_provenance(RESPONSE_FROM_OWNER)

        started = _answer(broker, '{"action": "start", "minutes": 2}')
        assert started["status"] == STATUS_OK, started
        assert runtime.roam_snapshot()["active"] is True

        stopped = _answer(broker, '{"action": "stop"}')
        assert stopped["status"] == STATUS_OK, stopped
        assert runtime.roam_snapshot()["active"] is False
    finally:
        runtime.close()


def test_the_product_supervisor_still_refuses_roam_under_a_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The allowlist added a NAME, not a permission. Latch parity with follow."""

    runtime = _runtime(tmp_path / "product-latch", monkeypatch)
    try:
        runtime.emergency_stop()
        broker = _product_broker(runtime)
        broker.note_response_provenance(RESPONSE_FROM_OWNER)

        result = _answer(broker, '{"action": "start", "minutes": 2}')

        assert result["status"] != STATUS_OK, result
        assert runtime.roam_snapshot()["active"] is False
    finally:
        runtime.close()


def test_the_product_supervisor_still_refuses_a_system_initiated_roam(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3, re-run against the real doors rather than the stub."""

    runtime = _runtime(tmp_path / "product-system", monkeypatch)
    try:
        broker = _product_broker(runtime)
        broker.note_response_provenance(RESPONSE_FROM_SYSTEM)

        result = _answer(broker, '{"action": "start", "minutes": 2}')

        assert result["status"] == STATUS_REJECTED
        assert result["refusal"] == REFUSAL_SYSTEM_INITIATED_MOTION
        assert runtime.roam_snapshot()["active"] is False
    finally:
        runtime.close()


def test_the_supervisor_allowlist_is_names_only_no_new_permission() -> None:
    """Stated as a property so the ruling cannot drift into a semantics change."""

    from parcel_robot.models import ToolCall
    from parcel_robot.safety import BEHAVIOR_MODES, SafetySupervisor

    assert {"roam", "roam_stop"} <= BEHAVIOR_MODES
    assert {"follow", "follow_behind", "stay"} <= BEHAVIOR_MODES

    supervisor = SafetySupervisor({})
    for mode in sorted(BEHAVIOR_MODES):
        assert supervisor.validate(ToolCall("set_behavior", {"mode": mode})).accepted
    assert not supervisor.validate(ToolCall("set_behavior", {"mode": "nonsense"})).accepted

    # Under a latch every mode is refused by the SAME line, roam included.
    supervisor.emergency_stopped = True
    for mode in sorted(BEHAVIOR_MODES):
        verdict = supervisor.validate(ToolCall("set_behavior", {"mode": mode}))
        assert not verdict.accepted, mode
        assert verdict.message == "Motion is disabled by emergency stop", mode


def test_yielding_to_an_owner_command_does_not_cancel_that_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S6. Restore stop_motion() on the owner_command arm -> RED.

    The roam used to "yield" by calling stop_motion(), which preempts the
    spatial channel — so the owner's just-issued circle died one tick after
    they asked for it. The dog obeyed and then un-obeyed, and the roam looked
    like the polite one.
    """

    from parcel_robot.navigation.spatial import SpatialIntent

    runtime = _runtime(tmp_path / "yield-spatial", monkeypatch)
    try:
        runtime.start_roam()
        assert runtime.roam_snapshot()["active"] is True

        # The spatial controller needs a fresh frame on the runtime, which the
        # control loop would normally have published this tick.
        with runtime._lock:
            runtime._observation = _observation(runtime)
        runtime.start_spatial_behavior(
            SpatialIntent(behavior="move_steps", direction="forward", steps=6)
        )
        assert runtime.spatial.active, "the owner's command did not start"
        # And a navigation directive, the other channel stop_motion's preempt
        # reaches, standing in for "the owner also sent it somewhere".
        with runtime._lock:
            runtime._navigation_directive = "go to the sidewalk"

        runtime._step_roam(_observation(runtime))

        assert runtime.roam_snapshot()["active"] is False
        assert runtime.roam_snapshot()["reason"] == "owner_command"
        assert runtime.spatial.active, "the roam cancelled the owner's command on its way out"
        with runtime._lock:
            assert runtime._navigation_directive == "go to the sidewalk", (
                "the roam cleared the owner's navigation directive"
            )
    finally:
        runtime.close()


def test_a_stop_racing_an_in_flight_tick_leaves_no_stale_roam_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S7. Drop the `_command_lock` around the tick's submit -> RED.

    THE PROPERTY IS MUTUAL EXCLUSION, and it took two attempts to test it.
    The first version fired `stop_roam` from inside the submit on the SAME
    thread, which proves nothing: `stop_roam` cancels the channel itself, so it
    tidied up after the very command the test was trying to strand. Seeding the
    guard left it green.

    The real race needs two threads. `stop_roam` must be able to land BETWEEN
    the roam's decision and its submit — which is only possible if the two are
    not inside one critical section. When they are, the stopping thread blocks
    until the tick is done and there is no window; when they are not, the stop
    cancels, the tick then submits, and the owner's "stop roaming" is followed
    by one more accepted command with up to `loop_period * 3` of TTL to run.
    """

    import threading

    runtime = _runtime(tmp_path / "race", monkeypatch)
    try:
        runtime.start_roam()
        runtime._step_roam(_observation(runtime))
        assert runtime.roam_snapshot()["ticks"] >= 1

        entered = threading.Event()
        release = threading.Event()
        original_submit = runtime.submit_motion

        def _slow_submit(source, command, **kwargs):
            if source == "voice":
                entered.set()
                release.wait(2.0)
            return original_submit(source, command, **kwargs)

        runtime.submit_motion = _slow_submit  # type: ignore[method-assign]
        runtime._roam_last_tick_at = 0.0

        observation = _observation(runtime)
        tick = threading.Thread(target=runtime._step_roam, args=(observation,))
        tick.start()
        assert entered.wait(2.0), "the tick never reached its submit"

        # The owner says stop while that command is in flight.
        stopper = threading.Thread(target=runtime.stop_roam, args=("owner_stopped",))
        stopper.start()
        stopper.join(0.5)
        release.set()
        tick.join(3.0)
        stopper.join(3.0)

        assert runtime.roam_snapshot()["active"] is False
        active = runtime.arbiter.snapshot()["active_source"]
        assert active != "voice", (
            f"a roam command outlived the stop that cancelled it (arbiter owner: {active})"
        )
    finally:
        runtime.submit_motion = original_submit  # type: ignore[method-assign]
        runtime.close()


def test_a_stop_that_wins_the_race_owns_the_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S7b′. Remove the tick's post-check alone -> RED.

    Correction pass 2. The race guard is a redundant PAIR — the command lock and
    the post-check are each independently sufficient to stop a stale command
    reaching the arbiter — so the test above (which asks the ARBITER what it
    holds) is correctly green when either half is seeded out on its own. That
    made "no seed reddens a single half" look like a coverage gap when it was
    really an untested SECOND property.

    This is that second property, and only the post-check provides it: after a
    stop wins the race, the tick that was in flight must not write its own
    reason and tick count over the stop's. Without the post-check the tick
    falls through to ``self._roam_reason = command.reason`` and
    ``self._roam_ticks += 1``, so the owner who said "stop roaming" reads
    ``advance`` in ``/api/state`` and a tick counter that moved after the roam
    ended.
    """

    import threading

    runtime = _runtime(tmp_path / "race_snapshot", monkeypatch)
    try:
        runtime.start_roam()
        runtime._step_roam(_observation(runtime))
        ticks_before = int(runtime.roam_snapshot()["ticks"])
        assert ticks_before >= 1

        entered = threading.Event()
        release = threading.Event()
        original_submit = runtime.submit_motion

        def _slow_submit(source, command, **kwargs):
            if source == "voice":
                entered.set()
                release.wait(2.0)
            return original_submit(source, command, **kwargs)

        runtime.submit_motion = _slow_submit  # type: ignore[method-assign]
        runtime._roam_last_tick_at = 0.0

        tick = threading.Thread(target=runtime._step_roam, args=(_observation(runtime),))
        tick.start()
        assert entered.wait(2.0), "the tick never reached its submit"
        stopper = threading.Thread(target=runtime.stop_roam, args=("owner_stopped",))
        stopper.start()
        stopper.join(0.5)
        release.set()
        tick.join(3.0)
        stopper.join(3.0)

        snapshot = runtime.roam_snapshot()
        assert snapshot["active"] is False
        assert snapshot["reason"] == "owner_stopped", (
            f"the in-flight tick overwrote the stop's reason with {snapshot['reason']!r}"
        )
        assert int(snapshot["ticks"]) == ticks_before, (
            "a roam that has been stopped cannot go on counting ticks"
        )
    finally:
        runtime.submit_motion = original_submit  # type: ignore[method-assign]
        runtime.close()


def test_no_roam_command_is_submitted_after_the_stop_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S7a′. Drop the `_command_lock` around the tick alone -> RED.

    Correction pass 2, the other half of the pair. The arbiter-level test cannot
    see this one because the post-check cancels the channel immediately
    afterwards, so the stale command exists for microseconds and leaves no trace
    in ``arbiter.snapshot()``. What it does leave is an ORDERING: with the lock
    held, ``stop_roam`` cannot return until the tick's submit is finished, so no
    ``voice`` command may be submitted after the stop has returned to its
    caller. Without the lock, the stop returns first and the tick submits into a
    stopped roam — one command, up to ``loop_period * 3`` of TTL, and the
    post-check then races to cancel it.
    """

    import threading
    import time as _time

    runtime = _runtime(tmp_path / "race_order", monkeypatch)
    try:
        runtime.start_roam()
        runtime._step_roam(_observation(runtime))

        entered = threading.Event()
        release = threading.Event()
        submits: list[float] = []
        original_submit = runtime.submit_motion

        def _slow_submit(source, command, **kwargs):
            if source == "voice":
                entered.set()
                release.wait(2.0)
                submits.append(_time.monotonic())
            return original_submit(source, command, **kwargs)

        runtime.submit_motion = _slow_submit  # type: ignore[method-assign]
        runtime._roam_last_tick_at = 0.0

        tick = threading.Thread(target=runtime._step_roam, args=(_observation(runtime),))
        tick.start()
        assert entered.wait(2.0), "the tick never reached its submit"

        stopped_at: list[float] = []

        def _stop() -> None:
            runtime.stop_roam("owner_stopped")
            stopped_at.append(_time.monotonic())

        stopper = threading.Thread(target=_stop)
        stopper.start()
        stopper.join(0.5)
        release.set()
        tick.join(3.0)
        stopper.join(3.0)

        assert stopped_at, "stop_roam never returned"
        late = [when for when in submits if when > stopped_at[0]]
        assert not late, (
            f"{len(late)} roam command(s) were submitted AFTER stop_roam returned; "
            "the tick's submit and the stop are not mutually exclusive"
        )
    finally:
        runtime.submit_motion = original_submit  # type: ignore[method-assign]
        runtime.close()


def test_the_owners_roam_knobs_reach_the_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEED S8. Remove 'roam' from OVERLAY_INTRODUCIBLE_KEYS -> RED.

    The whole point of a knob is that turning it changes something. Before the
    correction pass the overlay loader refused the section outright, so every
    value in it was decorative.
    """

    # THROUGH THE OVERLAY, which is the path that was broken: a base config
    # with no roam section plus a PROFILE that introduces one. Reading the
    # section out of a single flat file would not touch `check_overlay_keys`
    # at all and would prove nothing about the exemption.
    runtime = _runtime(
        tmp_path / "knobs",
        monkeypatch,
        overlay="roam:\n  budget_s: 45.0\n  cruise_vx: 0.3\n  tether_m: 6.0\n",
    )
    try:
        assert runtime.store.profile == "demo", "the overlay never loaded"
        assert runtime.roam_config["budget_s"] == pytest.approx(45.0)
        runtime.start_roam()  # no argument: the OWNER'S default must be used
        snapshot = runtime.roam_snapshot()
        assert snapshot["budget_s"] == pytest.approx(45.0)
        assert runtime._roam_policy is not None
        assert runtime._roam_policy.limits.cruise_vx == pytest.approx(0.3)
        assert runtime._roam_policy.limits.tether_m == pytest.approx(6.0)
    finally:
        runtime.close()


def test_a_misspelled_roam_key_is_refused_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `minimum_confidenc` failure class, closed for this section.

    The overlay loader cannot catch it (an exempt parent stops the descent), so
    the reader must — otherwise `budget_st: 300` merges cleanly, reads as
    nothing, and leaves a 120 s roam while the file says five minutes.
    """

    runtime = _runtime(
        tmp_path / "typo", monkeypatch, overlay="roam:\n  budget_st: 300.0\n"
    )
    try:
        with pytest.raises(ValueError, match="unknown roam config key"):
            _ = runtime.roam_config
    finally:
        runtime.close()


def test_the_tether_turns_a_patrol_back_toward_home() -> None:
    """SEED S9. Set tether_m=None in limits_from_safety -> RED.

    Measured: an untethered roam left the 24x24 m road plane at t=85 s and
    drove straight across the unfenced ground plane, banking 8.66 m of "net
    displacement" off the rendered map.
    """

    limits = PatrolLimits(tether_m=10.0, alternate_turns=True)
    policy = PatrolPolicy(limits)

    # Latch home at the origin, lane clear.
    assert policy.step(
        PatrolSense(elapsed_s=0.0, x=0.0, y=0.0, yaw=0.0, forward_clearance_m=9.0)
    ).reason == "advance"

    # Inside the tether, still cruising.
    assert policy.step(
        PatrolSense(elapsed_s=1.0, x=5.0, y=0.0, yaw=0.0, forward_clearance_m=9.0)
    ).reason == "advance"

    # Outside it and still driving away (home is dead astern): turn.
    outside = policy.step(
        PatrolSense(elapsed_s=2.0, x=11.0, y=0.0, yaw=0.0, forward_clearance_m=9.0)
    )
    assert outside.reason == "turn_tether"
    assert not outside.translating, "the tether must never push, only turn"

    # Nose brought round toward home: releases, even though it is STILL outside
    # the radius. A distance-only tether could never release here — that is the
    # deadlock the person predicate already learned about.
    assert policy.step(
        PatrolSense(
            elapsed_s=3.0, x=11.0, y=0.0, yaw=math.pi, forward_clearance_m=9.0
        )
    ).reason == "advance"


def test_the_tether_is_off_by_default_so_move1s_baseline_is_untouched() -> None:
    assert PatrolLimits().tether_m is None
    assert limits_from_safety(person_stop_m=0.7, obstacle_stop_m=0.65).tether_m == pytest.approx(
        10.0
    )
    far = PatrolSense(elapsed_s=1.0, x=500.0, y=500.0, yaw=0.0, forward_clearance_m=9.0)
    shipped = PatrolPolicy(PatrolLimits())
    shipped.step(PatrolSense(elapsed_s=0.0, x=0.0, y=0.0, yaw=0.0, forward_clearance_m=9.0))
    assert shipped.step(far).reason == "advance", "an untethered patrol keeps going"


def test_a_nonsense_tether_is_refused() -> None:
    for value in (0.0, -1.0, math.inf):
        with pytest.raises((ValueError, TypeError)):
            PatrolLimits(tether_m=value)
