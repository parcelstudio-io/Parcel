"""P0-C product-path activation: a correction flushes stale nav proposals live.

The unit gate (``tests/test_p0c_proposal_flush.py``) proves the flush mechanism at
the ``ProposerBus`` / ``GoalArbiter`` / ``TaskExecutive`` boundary. This file proves
the mechanism is ACTIVE on the product path -- i.e. the two runtime wirings that
turn the proven-but-dormant no-op into live behavior:

  Handoff 1 (nav start): ``RobotRuntime._start_or_resume_navigation_locked``
    registers the live navigator's real ``proposer_bus`` / ``goal_arbiter`` as
    executive revision sinks.
  Handoff 2 (plan accept / stamping): ``DirectiveNavigator.set_active_revision``
    stamps every SE2Goal the pipeline publishes with the mission's committed
    ``(task_id, plan_revision)``, fed from the runtime's plan-accept path via
    ``RobotRuntime._apply_active_nav_revision``.

Together: a real correction (``executive.replace`` -> new ``plan_revision``) (a)
flushes the navigator's proposer buffer atomically, (b) makes any straggler
proposal authored under the OLD revision lose arbitration, so the body never
transiently steers toward the corrected-away target, and (c) lets the NEW target
be pursued.

Everything below runs against a REAL ``RobotRuntime`` + real ``Dog`` /
``DirectiveNavigator`` + real ``ProposerBus`` / ``GoalArbiter`` / ``TaskExecutive``,
with real revision stamping (never the ``("", 0)`` default). The only step mimicked
rather than driven through a full voice/brain sim is the brain plan compilation --
``_accept_plan`` internally calls ``executive.submit`` / ``executive.replace`` and
the ``set_active_revision`` stamp, which is exactly what this test drives directly.
The full ``handle_text``-through-sim e2e (grounder scene that reaches the pipeline's
own ``SE2Goal`` publish sites) is a noted handoff.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain import (
    GoalSpec,
    GoalTarget,
    PlanIR,
    PlanStep,
    PlanValidator,
    SkillContractRegistry,
    SuccessCondition,
)
from parcel_robot.instructnav.arbiter import SE2Goal
from parcel_robot.runtime import RobotRuntime

REPO = Path(__file__).resolve().parents[1]

# A world where the two targets sit in opposite directions, so "steering toward
# the OLD target" is unambiguous in the traced command poses.
OLD_TARGET = (10.0, 0.0, 0.0)  # "the lamppost"
NEW_TARGET = (-8.0, 3.0, 0.0)  # "no, the other lamppost"
NAV_TASK_ID = "nav-mission"


# --------------------------------------------------------------------------- #
# Real-runtime harness (mirrors tests/test_preempt_runtime.py).
# --------------------------------------------------------------------------- #
class _Backend:
    name = "fake"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack("owner", 2.0, 0.0, True, 1.0),
            backend="fake",
        )

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: object) -> None:
        del command

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy

    def set_robot_pose(self, pose: RobotPose) -> None:
        self._observation = replace(self._observation, robot=pose)

    def set_emergency_stopped(self, stopped: bool) -> None:
        self._observation = replace(self._observation, emergency_stopped=stopped)

    def close(self) -> None:
        return None


@pytest.fixture
def audio_status() -> AudioDeviceStatus:
    return AudioDeviceStatus(
        status="text mode",
        driver="test",
        capture_hardware=False,
        connected_input=False,
        connected_output=False,
        detail="deterministic test status",
    )


@pytest.fixture
def runtime_config(tmp_path: Path) -> Path:
    base = yaml.safe_load((REPO / "configs/robot.yaml").read_text(encoding="utf-8"))
    base["memory"] = {"path": ":memory:"}
    base["navigation"] = {
        "enabled": True,
        "config": str(REPO / "configs/navigation/default.yaml"),
    }
    path = tmp_path / "robot.yaml"
    path.write_text(yaml.safe_dump(base), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Plan fixtures (a minimal validated plan the executive accepts, as _accept_plan
# hands it via executive.submit / executive.replace).
# --------------------------------------------------------------------------- #
def _nav_plan(*, revision: int) -> PlanIR:
    return PlanIR(
        schema_version=1,
        task_id=NAV_TASK_ID,
        plan_revision=revision,
        source_turn_id=f"turn-{NAV_TASK_ID}-{revision}",
        # Goal content is irrelevant to the executive flush; a plain hold plan
        # keeps validation minimal (mirrors tests/test_p0c_proposal_flush.py).
        goal=GoalSpec("hold", GoalTarget("current_pose"), 0.0),
        invariants=("keep_collision_margin",),
        steps=(
            PlanStep(
                "hold",
                "Hold",
                {},
                ("base_available",),
                SuccessCondition("motion_stopped"),
                5.0,
                1,
                (),
                ("base",),
                "checkpoint",
            ),
        ),
    )


def _validated(plan: PlanIR):
    registry = SkillContractRegistry.default(pose_names=("sit",))
    return PlanValidator(registry).validate(plan)


def _pipeline_style_proposal(
    navigator,
    pose: tuple[float, float, float],
    *,
    now_s: float,
    source: str = "grounder",
    plan_step_id: str = "align_then_translate",
    priority: int = 10,
    ttl_s: float = 5.0,
) -> SE2Goal:
    """Build an SE2Goal the way the pipeline's publish sites do.

    Mirrors ``navigation/pipeline.py``'s grounder ("align_then_translate") and
    search_entity SE2Goal constructions: the ``task_id`` / ``plan_revision`` stamp
    is read from the navigator's stored active revision -- i.e. exactly whatever
    ``set_active_revision`` last stored. Reading it from the navigator (not a
    literal) is what makes this the pipeline's real stamp, not a re-derivation.
    """

    return SE2Goal(
        source=source,
        pose=pose,
        confidence=1.0,
        ttl_s=ttl_s,
        plan_step_id=plan_step_id,
        issued_s=now_s,
        priority=priority,
        task_id=navigator._active_task_id,
        plan_revision=navigator._active_plan_revision,
    )


def _accept_plan_like(rt: RobotRuntime, validated, *, correction: bool) -> None:
    """Drive the executive + stamping side of ``_accept_plan`` for a nav plan.

    This is the exact pair of effects ``RobotRuntime._accept_plan`` produces once a
    plan is compiled/validated: ``executive.replace`` (correction) or
    ``executive.submit`` (first accept) -- which is where the executive fires the
    revision-sink flush -- followed by recording ``_active_nav_revision`` and
    stamping the live navigator (``_apply_active_nav_revision``).
    """

    plan = validated.plan
    if correction:
        submission = rt.task_executive.replace(validated)
    else:
        submission = rt.task_executive.submit(validated)
    assert submission.accepted, submission.reason
    rt._active_nav_revision = (plan.task_id, plan.plan_revision)
    existing_navigator = getattr(rt.dog, "_navigator", None)
    if existing_navigator is not None:
        rt._apply_active_nav_revision(existing_navigator)


def _resolved_pose(navigator, now_s: float):
    """The pose the arbiter would command this tick from the live buffer."""

    goals = tuple(navigator.proposer_bus.poll(now_s=now_s))
    chosen = navigator.goal_arbiter.resolve(goals, now_s=now_s)
    return None if chosen is None else chosen.pose


# --------------------------------------------------------------------------- #
# THE GATE: correction flushes the stale proposal; old target never re-approached.
# --------------------------------------------------------------------------- #
def test_correction_flushes_stale_and_never_reapproaches_old_target(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        # Default key is the backward-compatible no-op the dormant version used.
        assert rt._active_nav_revision == ("", 0)

        # --- "go to the lamppost": first plan accepted at revision 1. ----------
        _accept_plan_like(rt, _validated(_nav_plan(revision=1)), correction=False)

        # Nav start: registers the live navigator's real proposer_bus/goal_arbiter
        # as executive sinks (Handoff 1) and stamps the navigator with the mission
        # revision (Handoff 2), all via the real runtime method.
        with rt._command_lock:
            rt._start_or_resume_navigation_locked("go to the lamppost")
        nav = rt.dog.navigator
        sinks = rt.task_executive._revision_sinks
        assert any(s is nav.proposer_bus for s in sinks)
        assert any(s is nav.goal_arbiter for s in sinks)
        assert (nav._active_task_id, nav._active_plan_revision) == (NAV_TASK_ID, 1)

        # The grounder publishes a proposal toward the OLD target, stamped rev 1.
        old_proposal = _pipeline_style_proposal(nav, OLD_TARGET, now_s=100.0)
        assert old_proposal.plan_revision == 1  # real stamp, not the ("",0) default
        nav.proposer_bus.publish(old_proposal)

        # Pre-correction the old-target proposal legitimately wins (rev 1 is still
        # the committed steering plan): the body would head toward OLD here.
        assert _resolved_pose(nav, now_s=100.0) == OLD_TARGET

        # --- "no, the other lamppost": correction commits revision 2. ----------
        _accept_plan_like(rt, _validated(_nav_plan(revision=2)), correction=True)

        # (a) The proposer buffer holds NO old-revision goal after the flush.
        buffered = nav.proposer_bus.snapshot()["latest"].values()
        assert all(g["plan_revision"] >= 2 for g in buffered)
        assert nav.proposer_bus.committed_revision(NAV_TASK_ID) == 2
        assert nav.goal_arbiter.committed_revision(NAV_TASK_ID) == 2
        assert (nav._active_task_id, nav._active_plan_revision) == (NAV_TASK_ID, 2)

        # (b) Trace every post-correction tick: the OLD target is never commanded.
        commanded_poses = []
        for tick in range(6):
            now_s = 101.0 + tick
            # A straggler grounder authored under the old revision keeps firing for
            # a few ticks (it hasn't seen the correction yet). Fail-closed: the bus
            # refuses to re-buffer it, and the arbiter would reject it anyway.
            straggler = SE2Goal(
                source="grounder",
                pose=OLD_TARGET,
                confidence=1.0,
                ttl_s=5.0,
                plan_step_id="align_then_translate",
                issued_s=now_s,
                priority=10,
                task_id=NAV_TASK_ID,
                plan_revision=1,
            )
            nav.proposer_bus.publish(straggler)
            assert nav.goal_arbiter.resolve((straggler,), now_s=now_s) is None
            commanded_poses.append(_resolved_pose(nav, now_s=now_s))
        assert OLD_TARGET not in commanded_poses

        # (c) The NEW target, published under the committed revision, is pursued.
        new_proposal = _pipeline_style_proposal(nav, NEW_TARGET, now_s=110.0)
        assert new_proposal.plan_revision == 2
        nav.proposer_bus.publish(new_proposal)
        assert _resolved_pose(nav, now_s=110.0) == NEW_TARGET
    finally:
        rt.close()


# --------------------------------------------------------------------------- #
# Backward compatibility: an unstamped channel commits nothing, so the flush is a
# correct no-op -- this is what kept the mechanism dormant-but-safe before wiring.
# --------------------------------------------------------------------------- #
def test_unstamped_navigator_default_key_is_a_safe_no_op(
    runtime_config: Path, audio_status: AudioDeviceStatus
) -> None:
    rt = RobotRuntime(runtime_config, _Backend(), audio_status=audio_status)
    try:
        with rt._command_lock:
            rt._start_or_resume_navigation_locked("go to the lamppost")
        nav = rt.dog.navigator
        # Never stamped: the navigator keeps the backward-compatible default key.
        assert (nav._active_task_id, nav._active_plan_revision) == ("", 0)

        # A proposal under the default key wins normally...
        default_goal = _pipeline_style_proposal(nav, OLD_TARGET, now_s=50.0)
        assert (default_goal.task_id, default_goal.plan_revision) == ("", 0)
        nav.proposer_bus.publish(default_goal)
        assert _resolved_pose(nav, now_s=50.0) == OLD_TARGET

        # ...and committing a real task's revision on the sinks does NOT touch the
        # unstamped channel's default-key proposal (per-task keying, fail-open for
        # the unstamped default): the flush is inert without stamping.
        rt.task_executive.submit(_validated(_nav_plan(revision=1)))
        rt.task_executive.replace(_validated(_nav_plan(revision=2)))
        assert _resolved_pose(nav, now_s=50.0) == OLD_TARGET
    finally:
        rt.close()
