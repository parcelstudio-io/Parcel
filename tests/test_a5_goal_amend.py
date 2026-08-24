"""A5 C8-FIX — goal amendment is a transaction, proved on the COMMAND STREAM.

RTP-2 F2 traced the defect to the receiver: ``VOICE_INTERRUPT_POLICY`` had no
``goal_amend`` key, so ``_voice_interrupt_action`` fell through to the
``default`` (``overlap``); ``request_interrupt`` returned
``InterruptDecision("overlap", (), reason)``; and ``_apply_goal_amend`` threw
that decision away and set ``_amendment_pending = True`` regardless. **An
executive-only task kept running — and kept commanding the body — while its own
goal was being revised.**

Addendum 2 **A8** is the binding specification and it is stricter than "add a
policy key", because a policy mapping plus a Python assertion suspends a
*record*, not a robot:

* amendment accepts **suspend only** — ``cancel_now`` destroys the goal being
  amended and can never be the decision taken for this reason;
* multi-task semantics are **atomic or rolled back** — on ANY failure every
  already-suspended task is resumed from a journal whose every step is written
  before it is taken, the amendment is refused, and the system stays in HOLD
  until the rollback completes;
* ``_amendment_pending`` stays **False** until every targeted controller is
  verified quiescent, confirmed at the arbiter.

So every headline row here watches ``ControlManager.set_target`` — the last
boundary before the actuator — and not task state. ``test_seeded_*`` are the
anti-vacuity arms: each one breaks exactly one link and shows the assertion
above it reddening, and :func:`test_seeded_red_c8_defect_reproduced` restores
the original defect end-to-end so "zero commands" cannot be passing for want of
a command stream.

The executive-only task used throughout is ``MoveRelative``: it is dispatched by
the executive, it drives the ``spatial`` arbiter source, and it is absent from
``PAUSABLE_SKILL_CHANNELS`` — so the retired body's channel loop
(navigation/follow/search) never touched it and the ignored ``overlap`` decision
was all that stood between the amendment and a moving robot.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain import executive as executive_module
from parcel_robot.brain.compiler import compile_plan_contracts
from parcel_robot.brain.contracts import (
    FrozenDict,
    GoalSpec,
    GoalTarget,
    PlanIR,
    PlanStep,
    SuccessCondition,
)
from parcel_robot.brain.executive import (
    GOAL_AMEND_FORBIDDEN_ACTIONS,
    GOAL_AMEND_REFUSED_ACTION,
    GOAL_AMEND_SUSPEND_REASON,
    VOICE_INTERRUPT_POLICY,
    InterruptDecision,
    InterruptRequest,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice.amendment import AMEND_SUSPEND_REASON
from parcel_robot.voice.closed_intents import ClosedIntent
from parcel_robot.voice.executive_caps import resolve_cap

REPO = Path(__file__).resolve().parents[1]

REFUSAL = "left the current goal exactly as it was"


class _Backend:
    """Minimal deterministic backend: no threads, no sim, no timing."""

    name = "a5-fake"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(owner_id="owner-a5", x=3.0, y=0.0, visible=True, confidence=1.0),
            nearest_obstacle_m=10.0,
            nearest_obstacle_bearing_rad=0.0,
            backend=self.name,
        )
        self.moves: list[VelocityCommand] = []
        self.stop_count = 0

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        self.moves.append(command)

    def stop(self) -> None:
        self.stop_count += 1

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill


@pytest.fixture()
def config(tmp_path: Path) -> Path:
    path = tmp_path / "robot-a5.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: false
motion:
  backend: rl
  max_vx: 0.6
  max_vy: 0.4
  max_vyaw: 1.0
  rl:
    enabled: true
    policy_path: ""
memory:
  path: ":memory:"
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def audio_status() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


@pytest.fixture()
def runtime(config: Path, audio_status: AudioDeviceStatus) -> Iterator[RobotRuntime]:
    backend = _Backend()
    session = RobotRuntime(config, backend, audio_status=audio_status)
    observation = backend.observe()
    session._observation = observation
    if session._control_state_source is not None:
        session._control_state_source.update_observation(observation)
    session.backend_probe = backend  # type: ignore[attr-defined]
    try:
        yield session
    finally:
        session.close()


# --- product-path helpers ---------------------------------------------------


def _move_plan(task_id: str) -> PlanIR:
    """One bounded owner-relative move: executive-owned, spatial-driven."""

    return PlanIR(
        schema_version=1,
        task_id=task_id,
        plan_revision=1,
        source_turn_id=f"turn-{task_id}",
        goal=GoalSpec("relative", GoalTarget("current_pose"), 0.0),
        invariants=(),
        steps=(
            PlanStep(
                "step-1",
                "MoveRelative",
                FrozenDict({"direction": "away_from_owner", "steps": 5}),
                ("base_available", "owner_visible"),
                SuccessCondition("distance_travelled"),
                20.0,
                1,
                (),
                ("base",),
                "checkpoint",
            ),
        ),
    )


def _seed_tasks(runtime: RobotRuntime, task_ids: tuple[str, ...]) -> None:
    """Submit real validated plans and let the executive dispatch them.

    Deliberately NOT through ``_accept_plan``: a second accepted plan interrupts
    the first, and A8's multi-task case needs two live tasks at once. Everything
    below this seam — validation, submission, dispatch, the spatial controller,
    the arbiter, ``ControlManager`` — is the product.
    """

    for task_id in task_ids:
        plan = compile_plan_contracts(_move_plan(task_id), runtime.system_registry)
        validated = runtime.system_plan_validator.validate(
            plan, runtime._build_brain_snapshot()
        )
        submission = runtime.task_executive.submit(validated, task_class="explicit_action")
        assert submission.accepted, submission.reason
    runtime._step_brain()


def _record_commands(runtime: RobotRuntime) -> list[str]:
    """Every ``ControlManager.set_target`` source, in order."""

    sources: list[str] = []
    original = runtime.control_manager.set_target

    def spy(command, *, source, ttl=None, now=None):  # type: ignore[no-untyped-def]
        sources.append(source)
        return original(command, source=source, ttl=ttl, now=now)

    runtime.control_manager.set_target = spy  # type: ignore[method-assign]
    return sources


def _tick(runtime: RobotRuntime, *, count: int = 3) -> None:
    """One control pass: observe, step the spatial behaviour, dispatch."""

    backend = runtime.backend_probe  # type: ignore[attr-defined]
    for _ in range(count):
        observation = backend.observe()
        runtime._observation = observation
        if runtime._observation_sink is not None:
            runtime._observation_sink.update_observation(observation)
        runtime._step_spatial(observation)
        runtime._dispatch_active()


def _amend(runtime: RobotRuntime) -> str:
    return runtime._apply_closed_intent(
        ClosedIntent.GOAL_AMEND, resolve_cap(ClosedIntent.GOAL_AMEND)
    )


def _states(runtime: RobotRuntime) -> dict[str, str]:
    return {
        str(row["task_id"]): str(row["state"])
        for row in runtime.task_executive.snapshot()["tasks"]
    }


def _details(runtime: RobotRuntime) -> dict[str, str]:
    return {
        str(row["task_id"]): str(row.get("last_detail") or "")
        for row in runtime.task_executive.snapshot()["tasks"]
    }


def _journal(runtime: RobotRuntime) -> list[tuple[str, str, str]]:
    txn = runtime._amendment_txn
    rows = txn["journal"] if txn is not None else runtime._amendment_journal
    assert isinstance(rows, list)
    return [(str(r["step"]), str(r["target"]), str(r["state"])) for r in rows]


def _hold_events(runtime: RobotRuntime) -> list[str]:
    return [
        str(event["text"])
        for event in runtime.snapshot()["events"]
        if "goal amend HOLD" in str(event["text"])
    ]


# --- 1. the executive-only task, watched at the actuator boundary ----------


def test_goal_amend_suspends_an_executive_only_task_and_stops_its_commands(
    runtime: RobotRuntime,
) -> None:
    """F2's exact case: task state AND the command stream, in one row."""

    _seed_tasks(runtime, ("task-a",))
    commands = _record_commands(runtime)
    _tick(runtime, count=3)
    # The premise. Without this the "zero commands" assertion below is vacuous.
    assert commands == ["spatial", "spatial", "spatial"], commands
    assert _states(runtime)["task-a"] == "running"
    commands.clear()

    reply = _amend(runtime)

    assert runtime.agent.last_brain_metrics["goal_amend_ok"] is True, reply
    assert _states(runtime)["task-a"] == "suspended"
    assert _details(runtime)["task-a"] == f"suspended:{AMEND_SUSPEND_REASON}"
    assert runtime._amendment_pending is True
    # An explicit HOLD, emitted for the window and visible to the operator.
    assert runtime._amendment_hold["active"] is True
    assert runtime._amendment_hold["sources"] == ["spatial"]
    assert _hold_events(runtime), runtime.snapshot()["events"]
    assert runtime.snapshot()["dialogue_state"]["amendment_hold"]["active"] is True
    # THE ROW: not one further command from the amended task reaches the
    # actuator boundary, over more ticks than produced three of them above.
    _tick(runtime, count=5)
    assert commands == [], commands
    assert runtime.arbiter.current(now=time.monotonic()) is None


def test_the_hold_is_engaged_before_the_first_suspension_is_even_requested(
    runtime: RobotRuntime,
) -> None:
    """Order matters: suspending first would leave a gap with no HOLD in it."""

    _seed_tasks(runtime, ("task-a",))
    _tick(runtime, count=2)
    _amend(runtime)

    steps = [row[0] for row in _journal(runtime)]
    assert "hold_engage" in steps and "suspend" in steps
    assert steps.index("hold_engage") < steps.index("suspend"), steps
    # And the journal is written BEFORE each step is taken, never after it.
    assert _journal(runtime)[0] == ("hold_engage", "spatial", "planned")


# --- 2. the multi-task forced-partial-failure case (A8) --------------------


def test_a_forced_second_suspension_failure_rolls_the_whole_amendment_back(
    runtime: RobotRuntime,
) -> None:
    """Two tasks, the second suspension refused: atomic, or nothing happened.

    The window is observed from INSIDE it — the monkeypatched receiver runs
    while ``_apply_goal_amend`` holds ``_command_lock`` — so "``_amendment_pending``
    False throughout", "in HOLD" and "zero commands" are read at the only moment
    they can be falsified, not reconstructed afterwards.
    """

    _seed_tasks(runtime, ("task-a", "task-b"))
    commands = _record_commands(runtime)
    _tick(runtime, count=3)
    assert commands == ["spatial", "spatial", "spatial"], commands
    assert _states(runtime) == {"task-a": "running", "task-b": "queued"}
    commands.clear()

    inside: list[dict[str, object]] = []
    real = runtime.task_executive.request_interrupt

    def refusing(request: InterruptRequest) -> InterruptDecision:
        # A real control-loop dispatch cannot interleave here (it takes the same
        # ``_command_lock`` this transaction holds), so the dispatch half is
        # driven directly: it must find nothing to forward.
        before = len(commands)
        runtime._dispatch_active()
        inside.append(
            {
                "task": request.target_task_id,
                "pending": runtime._amendment_pending,
                "hold": runtime._amendment_hold.get("active"),
                "commands": len(commands) - before,
                "intent": runtime.arbiter.current(now=time.monotonic()),
            }
        )
        if request.target_task_id == "task-b":
            return InterruptDecision("overlap", (), request.reason)
        return real(request)

    runtime.task_executive.request_interrupt = refusing  # type: ignore[method-assign]
    reply = _amend(runtime)

    # Refused, and said so honestly.
    assert REFUSAL in reply, reply
    assert runtime.agent.last_brain_metrics["goal_amend_ok"] is False
    assert runtime.agent.last_brain_metrics["goal_amend_reason"] == "refused:task-b:overlap"
    # Never half-amended: the first task is RESUMED, the second never suspended.
    assert _states(runtime) == {"task-a": "running", "task-b": "queued"}
    assert _details(runtime)["task-a"].startswith("resumed")
    # The flag was False at every point inside the window, and stays False.
    assert [row["pending"] for row in inside] == [False, False], inside
    assert runtime._amendment_pending is False
    assert runtime._amendment_txn is None
    # In HOLD throughout the window, with zero commands emitted from inside it.
    assert [row["hold"] for row in inside] == [True, True], inside
    assert [row["commands"] for row in inside] == [0, 0], inside
    assert [row["intent"] for row in inside] == [None, None], inside
    # HOLD released only after the rollback finished.
    assert runtime._amendment_hold == {
        "active": False,
        "reason": "rollback_complete",
        "released_at_s": runtime._amendment_hold["released_at_s"],
    }


def test_the_rollback_journal_records_every_step_before_it_is_taken(
    runtime: RobotRuntime,
) -> None:
    """HOLD + refusal + rollback, in that order, each planned then applied."""

    _seed_tasks(runtime, ("task-a", "task-b"))
    _tick(runtime, count=2)
    real = runtime.task_executive.request_interrupt

    def refusing(request: InterruptRequest) -> InterruptDecision:
        if request.target_task_id == "task-b":
            return InterruptDecision("overlap", (), request.reason)
        return real(request)

    runtime.task_executive.request_interrupt = refusing  # type: ignore[method-assign]
    _amend(runtime)

    assert _journal(runtime) == [
        ("hold_engage", "spatial", "planned"),
        ("hold_engage", "spatial", "applied"),
        ("suspend", "task-a", "planned"),
        ("suspend", "task-a", "applied"),
        ("suspend", "task-b", "planned"),
        ("suspend", "task-b", "failed:overlap"),
        ("refuse", "task-b:overlap", "applied"),
        ("rollback_task", "task-a", "planned"),
        ("rollback_task", "task-a", "applied:running"),
        ("hold_release", "rollback_complete", "planned"),
        ("hold_release", "rollback_complete", "applied"),
    ]
    # The journal is also carried on the metrics the panel/agent already read.
    assert runtime.agent.last_brain_metrics["goal_amend_journal"]


def test_the_rolled_back_work_really_drives_again(runtime: RobotRuntime) -> None:
    """Rollback restores the mission, not just the record."""

    _seed_tasks(runtime, ("task-a", "task-b"))
    commands = _record_commands(runtime)
    _tick(runtime, count=2)
    real = runtime.task_executive.request_interrupt

    def refusing(request: InterruptRequest) -> InterruptDecision:
        if request.target_task_id == "task-b":
            return InterruptDecision("overlap", (), request.reason)
        return real(request)

    runtime.task_executive.request_interrupt = refusing  # type: ignore[method-assign]
    _amend(runtime)
    commands.clear()

    _tick(runtime, count=3)
    assert commands == ["spatial", "spatial", "spatial"], commands


# --- 3. commit and abandon --------------------------------------------------


def test_amendment_commit_replaces_the_parked_work_and_drops_the_hold(
    runtime: RobotRuntime,
) -> None:
    """The existing commit semantics, kept: the replacement plan wins."""

    _seed_tasks(runtime, ("task-a",))
    _tick(runtime, count=2)
    _amend(runtime)
    assert runtime._amendment_pending is True

    reply = runtime.handle_text("Can you walk away from the owner 5 steps?")

    assert "bounded move" in reply.lower(), reply
    assert runtime.agent.last_brain_metrics["goal_amend_committed"] is True
    assert runtime._amendment_pending is False
    assert runtime._amendment_txn is None
    assert runtime._amendment_hold["active"] is False
    assert ("close", "committed", "applied") in _journal(runtime)
    states = _states(runtime)
    assert states.pop("task-a") == "cancelled"
    # …and exactly one replacement task took its place.
    assert list(states.values()) == ["queued"], states


def test_amendment_abandon_restores_the_parked_work_and_drops_the_hold(
    runtime: RobotRuntime,
) -> None:
    """"actually…" then "resume": the old goal comes back, not a dead window."""

    _seed_tasks(runtime, ("task-a",))
    commands = _record_commands(runtime)
    _tick(runtime, count=2)
    _amend(runtime)
    commands.clear()

    reply = runtime.handle_text("resume")

    assert "picked up where I left off" in reply, reply
    assert runtime._amendment_pending is False
    assert runtime._amendment_txn is None
    assert runtime._amendment_hold["active"] is False
    assert ("rollback_task", "task-a", "applied:queued") in _journal(runtime)
    # The controller was STOPPED (spatial carries no ResumeIntent), so the task
    # is re-queued for a fresh dispatch — and it really dispatches and drives.
    assert _states(runtime)["task-a"] == "queued"
    runtime._step_brain()
    assert _states(runtime)["task-a"] == "running"
    _tick(runtime, count=3)
    assert commands == ["spatial", "spatial", "spatial"], commands


def test_abandoning_with_no_window_open_is_honest(runtime: RobotRuntime) -> None:
    assert "no goal revision in progress" in runtime._abandon_goal_amend("test")


# --- 4. cancel_now can never be the goal-amend decision --------------------


def test_the_policy_maps_goal_amend_to_suspend_and_the_words_agree() -> None:
    """The three parties must agree on one string, or the pair stops matching."""

    assert GOAL_AMEND_SUSPEND_REASON == AMEND_SUSPEND_REASON
    assert VOICE_INTERRUPT_POLICY[GOAL_AMEND_SUSPEND_REASON] == "suspend"
    assert "cancel_now" in GOAL_AMEND_FORBIDDEN_ACTIONS


def test_a_cancel_now_decision_can_never_be_taken_for_a_goal_amendment(
    runtime: RobotRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seeded: the table itself says ``cancel_now``. It must still not cancel."""

    _seed_tasks(runtime, ("task-a",))
    monkeypatch.setitem(VOICE_INTERRUPT_POLICY, GOAL_AMEND_SUSPEND_REASON, "cancel_now")

    decision = runtime.task_executive.request_interrupt(
        InterruptRequest(
            source="voice",
            reason=AMEND_SUSPEND_REASON,
            requested="interrupt_now",
            target_task_id="task-a",
        )
    )

    assert decision.action == GOAL_AMEND_REFUSED_ACTION
    assert decision.affected_task_ids == ()
    assert _states(runtime)["task-a"] == "running"


def test_seeded_red_a_cancel_now_table_refuses_the_amendment_end_to_end(
    runtime: RobotRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_tasks(runtime, ("task-a",))
    _tick(runtime, count=2)
    monkeypatch.setitem(VOICE_INTERRUPT_POLICY, GOAL_AMEND_SUSPEND_REASON, "cancel_now")

    reply = _amend(runtime)

    assert REFUSAL in reply, reply
    assert runtime._amendment_pending is False
    assert (
        runtime.agent.last_brain_metrics["goal_amend_reason"]
        == f"refused:task-a:{GOAL_AMEND_REFUSED_ACTION}"
    )
    assert _states(runtime)["task-a"] == "running"


# --- 5. seeded red: one broken link per assertion --------------------------


def test_seeded_red_removing_the_policy_key_refuses_instead_of_overlapping(
    runtime: RobotRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retired state of the world. It must now be a refusal, not silence."""

    _seed_tasks(runtime, ("task-a",))
    _tick(runtime, count=2)
    monkeypatch.delitem(VOICE_INTERRUPT_POLICY, GOAL_AMEND_SUSPEND_REASON)
    assert (
        executive_module._voice_interrupt_action(AMEND_SUSPEND_REASON)
        == VOICE_INTERRUPT_POLICY["default"]
    )

    reply = _amend(runtime)

    assert REFUSAL in reply, reply
    assert runtime.agent.last_brain_metrics["goal_amend_reason"] == "refused:task-a:overlap"
    assert runtime._amendment_pending is False
    assert _states(runtime)["task-a"] == "running"


def test_seeded_red_a_decision_that_does_not_name_the_task_is_a_failure(
    runtime: RobotRuntime,
) -> None:
    """Fail closed on the RETURNED decision, not on how the record happens to look."""

    _seed_tasks(runtime, ("task-a",))
    _tick(runtime, count=2)
    runtime.task_executive.request_interrupt = (  # type: ignore[method-assign]
        lambda request: InterruptDecision("suspend", (), request.reason)
    )

    reply = _amend(runtime)

    assert REFUSAL in reply, reply
    assert runtime.agent.last_brain_metrics["goal_amend_reason"] == "refused:task-a:suspend"
    assert runtime._amendment_pending is False


def test_seeded_red_a_live_controller_refuses_the_amendment(
    runtime: RobotRuntime,
) -> None:
    """Quiescence is verified, not assumed: no teardown ⇒ no amendment."""

    _seed_tasks(runtime, ("task-a",))
    _tick(runtime, count=2)
    runtime._quiesce_amendment_controllers = lambda *a, **k: None  # type: ignore[assignment]

    reply = _amend(runtime)

    assert REFUSAL in reply, reply
    assert (
        runtime.agent.last_brain_metrics["goal_amend_reason"]
        == "refused:controller_active:spatial"
    )
    assert runtime._amendment_pending is False


def test_seeded_red_c8_defect_reproduced(runtime: RobotRuntime) -> None:
    """Break BOTH the teardown and the quiescence gate: C8 comes straight back.

    This is the anti-vacuity proof for every "zero commands" row above — the
    same fixture, the same ticks, a suspended record, and a robot still being
    commanded. If this test ever goes green-with-zero-commands, the headline
    rows are passing for want of a command stream and must be re-derived.
    """

    _seed_tasks(runtime, ("task-a",))
    commands = _record_commands(runtime)
    _tick(runtime, count=2)
    commands.clear()
    runtime._quiesce_amendment_controllers = lambda *a, **k: None  # type: ignore[assignment]
    runtime._amendment_not_quiescent = lambda *a, **k: None  # type: ignore[assignment]

    _amend(runtime)

    assert runtime._amendment_pending is True
    assert _states(runtime)["task-a"] == "suspended"
    _tick(runtime, count=3)
    assert commands == ["spatial", "spatial", "spatial"], (
        "the C8 defect no longer reproduces through this fixture; the headline "
        "zero-command rows above are no longer proving anything"
    )
