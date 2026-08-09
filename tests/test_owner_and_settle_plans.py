"""N12 (owner bridge), N13 (settle compile half), and the novel-verb clarify fallback.

**N12.** "Go to the owner" used to compile to ``NavigateTo`` with the target
label ``"owner"`` — i.e. it asked the *semantic map* for a landmark that cannot
exist, ran the resolution ladder for ~38 s, and failed with
``semantic_target_not_found`` having travelled 1.4 m away from the owner. The
owner is a tracked entity on the owner channel. There is now exactly one way to
mean "the owner": the approach lane that "come here" already used.

**N13.** "Sit next to the bench" used to compile to a plan with exactly one
step. The "sit" verb survived only inside the directive string, where the
navigator re-read it as the ``next_to`` placement relation, and
``runtime._last_posture`` stayed ``"unknown"`` for the whole run — so the
posture gate of ``evaluate_sit_next_to`` could not pass by construction. The
plan now carries a real second step. The *placement* half of that command is a
separate, still-open defect (N11 family) and is not claimed here.

**Clarify fallback.** A transcript that names something the robot knows, with a
verb it does not, now gets an honest offer instead of the flat
"I did not understand that command".
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest

from parcel_robot.audio_io import AudioDeviceStatus
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.brain.compiler import compile_plan_sketch
from parcel_robot.brain.contracts import FrozenDict, SuccessCondition
from parcel_robot.brain.executive import DispatchRequest
from parcel_robot.brain.observations import build_observation_snapshot
from parcel_robot.brain.router import DeterministicIntentRouter, physical_cue_present
from parcel_robot.brain.runtime_adapter import SemanticRuntimeState, SemanticTaskRuntimeAdapter
from parcel_robot.brain.validator import (
    RUNTIME_AUTHORED_SKILLS,
    PlanValidationError,
    PlanValidator,
    SkillContractRegistry,
)
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.goals import (
    OWNER_REFERENT_TABLE,
    owner_referent_from_directive,
    semantic_goal_from_directive,
)
from parcel_robot.runtime import RobotRuntime
from parcel_robot.voice.local_plans import (
    SETTLE_POSE_NAME,
    sketch_come,
    sketch_navigate,
    sketch_settle_next_to,
)
from parcel_robot.voice.scene_reference import (
    clarification_for,
    dangling_reference,
    resolve_pending_reference,
)

REPO = Path(__file__).resolve().parents[1]
POSE_CATALOG = ("bow", "crouch", "hello_pose", "lie_down", "sit", "stand", "stretch")
#: What ``configs/robot.yaml`` actually admits on the planner surface. ``Pose``
#: is deliberately absent: it is a SYSTEM skill, reachable only through the
#: runtime's own deterministic sketches.
_CONFIGURED_SKILLS = frozenset(
    {
        "NavigateTo",
        "FollowFormation",
        "OrbitOwner",
        "MoveRelative",
        "Hold",
        "Vocalize",
        "AskClarification",
        "ReturnToSafePose",
        "Gesture",
    }
)


def _registry(*, system_authored: bool) -> SkillContractRegistry:
    return SkillContractRegistry.default(
        owner_heading_supported=True,
        pose_names=POSE_CATALOG,
        gesture_names=("bow", "hello_pose"),
        include_system_skills=True,
    ).restricted(
        _CONFIGURED_SKILLS,
        system_authored=system_authored,
    )


def _snapshot(*, owner_visible: bool = True):
    now = 50.0
    observation = SimObservation(
        timestamp=now,
        robot=RobotPose(),
        owner=OwnerTrack(
            owner_id="owner-test",
            x=2.0,
            y=0.0,
            visible=owner_visible,
            confidence=1.0 if owner_visible else 0.0,
        ),
        backend="plan-test",
    )
    return build_observation_snapshot(observation, snapshot_id="snapshot-plan-1", now=now)


# ---------------------------------------------------------------------------
# N12 — the owner is never a semantic-map query
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directive",
    [
        "go to the owner",
        "go to me",
        "walk to me",
        "navigate to the owner",
        "walk over to my side",
        "head to my position",
    ],
)
def test_owner_referring_directives_compile_to_the_approach_lane(directive: str) -> None:
    assert owner_referent_from_directive(directive) is not None
    assert sketch_navigate(directive) == sketch_come()


def test_no_owner_phrasing_can_produce_a_navigate_to_step() -> None:
    """The whole point of N12: one authority, checked over the whole table."""

    for referent in OWNER_REFERENT_TABLE:
        sketch = sketch_navigate(f"go to {referent}")
        assert [step.skill for step in sketch.steps] == ["FollowFormation"]
        assert sketch.goal.kind == "owner"


@pytest.mark.parametrize(
    "directive",
    [
        "go to the bench",
        "walk to the sidewalk",
        "take me to the store",
        "go towards the tree",
        "find the nearest lamppost",
    ],
)
def test_non_owner_directives_are_untouched(directive: str) -> None:
    assert owner_referent_from_directive(directive) is None
    assert [step.skill for step in sketch_navigate(directive).steps] == ["NavigateTo"]


def test_a_negated_owner_directive_is_still_not_motion_authority() -> None:
    assert owner_referent_from_directive("do not come to me") is None
    assert owner_referent_from_directive("what if you walked to me") is None


def test_the_owner_bridge_admits_against_the_system_registry() -> None:
    """The approach relation is system-authored, and the route selects it.

    "Go to the owner" routes ``direct_skill``/``navigation_directive``, and
    ``direct_skill`` is what selects the system registry — the only one that
    admits ``relation="follow"`` (arbitration OB-2). Validating the same sketch
    against the model-facing registry must still be refused, or the bridge
    would have widened what a language model can author.
    """

    frame = DeterministicIntentRouter().route("go to the owner", turn_id="turn-owner")
    assert (frame.route, frame.matched_rule) == ("direct_skill", "navigation_directive")

    snapshot = _snapshot()
    system = _registry(system_authored=True)
    plan = compile_plan_sketch(sketch_navigate("go to the owner"), frame, snapshot, system)
    PlanValidator(system).validate(plan, snapshot)
    assert [step.skill for step in plan.steps] == ["FollowFormation"]
    assert plan.steps[0].arguments["relation"] == "follow"

    model_facing = _registry(system_authored=False)
    unadmitted = compile_plan_sketch(
        sketch_navigate("go to the owner"), frame, snapshot, model_facing
    )
    with pytest.raises(PlanValidationError) as error:
        PlanValidator(model_facing).validate(unadmitted, snapshot)
    assert "behind" in str(error.value)


# ---------------------------------------------------------------------------
# N13 — the settle compile half
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["bench", "lamppost", "tree"])
def test_sit_next_to_compiles_navigate_plus_a_real_posture_step(target: str) -> None:
    sketch = sketch_navigate(f"sit next to the {target}")
    assert [step.skill for step in sketch.steps] == ["NavigateTo", "Pose"]
    assert sketch.steps[0].navigation is not None
    assert sketch.steps[0].navigation.target == target
    assert sketch.steps[1].arguments["name"] == SETTLE_POSE_NAME == "sit"


def test_the_settle_plan_goal_is_the_shape_the_validator_reserves_for_it() -> None:
    """``hold``/``current_pose`` is the only admissible goal for a terminal Pose.

    ``PlanValidator._validate_goal_completion`` admits a final ``Pose`` step
    proving ``skill_completed`` **only** under a ``hold`` goal, and
    ``_validate_plan_level`` allows ``hold`` only with a ``current_pose``
    target. So this is not a stylistic choice: any other goal shape is refused.
    """

    sketch = sketch_navigate("sit next to the bench")
    assert sketch.goal.as_dict() == {"relation": "hold", "kind": "current_pose", "query": ""}


def test_the_settle_plan_admits_through_the_real_validator() -> None:
    frame = DeterministicIntentRouter().route("sit next to the bench", turn_id="turn-sit")
    snapshot = _snapshot()
    registry = _registry(system_authored=True)
    plan = compile_plan_sketch(sketch_navigate("sit next to the bench"), frame, snapshot, registry)
    validated = PlanValidator(registry).validate(plan, snapshot)
    assert [step.skill for step in plan.steps] == ["NavigateTo", "Pose"]
    # The compiler owns preconditions: the posture step waits for a stopped
    # robot, so the sit cannot fire mid-approach.
    assert "robot_stopped" in plan.steps[1].preconditions
    assert plan.steps[1].success.fact == "skill_completed"
    assert validated.steps[1].effective_resources == ("base", "posture")


def test_the_settle_posture_is_not_on_this_deployments_planner_surface() -> None:
    """A system-authored registry admits ``Pose``; the model-facing one does not.

    The alternative — adding ``Pose`` to ``agent.brain.skills`` — would edit
    ``configs/robot.yaml``, which is a **locked input of the frozen
    embodied-plan manifest** (its SHA-256 is pinned in
    ``evals/companion/embodied_plan_v1/manifest.json``), and would put an
    arbitrary posture on this deployment's model-facing schema.
    """

    assert "Pose" in RUNTIME_AUTHORED_SKILLS
    assert "Pose" in SemanticTaskRuntimeAdapter.EXECUTABLE_SKILLS

    frame = DeterministicIntentRouter().route("sit next to the bench", turn_id="turn-sit")
    snapshot = _snapshot()
    model_facing = _registry(system_authored=False)
    assert "Pose" not in model_facing.names()

    # Since H7 the model-facing registry refuses the Pose step at *compile*
    # time — one registry lookup, no fallback. ADMISSION is still the trust
    # boundary and gives the same verdict, so the refusal is not load-bearing
    # on which of the two runs first.
    with pytest.raises(PlanValidationError) as error:
        compile_plan_sketch(
            sketch_navigate("sit next to the bench"), frame, snapshot, model_facing
        )
    assert error.value.code == "unknown_skill"

    system_authored = _registry(system_authored=True)
    compiled = compile_plan_sketch(
        sketch_navigate("sit next to the bench"), frame, snapshot, system_authored
    )
    with pytest.raises(PlanValidationError) as error:
        PlanValidator(model_facing).validate(compiled, snapshot)
    assert error.value.code == "unknown_skill"


def test_the_compiler_has_no_registry_fallback_left(runtime: RobotRuntime) -> None:
    """H7, done 2026-08-07: the workaround is gone, not just unused.

    ``compile_plan_contracts`` briefly fell back to the system contract table
    for ``Pose``, because ``_materialize_brain_planner_output`` compiled
    *every* sketch against the model-facing registry — including a
    ``direct_skill`` one the runtime authored itself. Selecting the registry by
    route there (the way ``_accept_plan`` always did) removed the need, so the
    compiler now resolves contracts one way only.

    Asserted at the seam it protects, not just by reading the source: the
    settle plan must still be admitted through the product path with the
    fallback gone.
    """

    from parcel_robot.brain import compiler

    assert not hasattr(compiler, "_contract_for")
    assert not hasattr(compiler, "_system_contracts")

    reply = runtime.handle_text("sit next to the bench")
    assert "couldn't admit" not in reply, (
        f"{reply!r} (error={runtime.agent.last_reasoning_error!r})"
    )
    assert runtime.agent.last_brain_metrics["local_plan_skills"] == ["NavigateTo", "Pose"]


def test_the_navigation_half_still_carries_the_placement_relation() -> None:
    """The Pose step must not have replaced the placement contract."""

    goal = semantic_goal_from_directive("sit next to the bench")
    assert goal.terminal_relation == "next_to"
    assert goal.terminal_behavior == "hold"
    sketch = sketch_navigate("sit next to the bench")
    assert sketch.steps[0].arguments["directive"] == "sit next to the bench"


def test_sketch_settle_next_to_refuses_an_unnamed_target() -> None:
    with pytest.raises(ValueError, match="placement target"):
        sketch_settle_next_to("sit next to it", target="   ")


# --- Pose skill wiring at the adapter --------------------------------------


def _pose_request(name: str = "sit") -> DispatchRequest:
    return DispatchRequest(
        task_id="task-pose",
        plan_revision=1,
        step_id="step_2",
        attempt=1,
        skill="Pose",
        arguments=FrozenDict({"name": name}),
        success=SuccessCondition("skill_completed"),
        resources=("base", "posture"),
        timeout_s=30.0,
    )


def test_the_pose_skill_dispatches_through_the_one_runtime_posture_door() -> None:
    applied: list[str] = []
    adapter = SemanticTaskRuntimeAdapter(
        navigate=lambda directive: None,
        follow_formation=lambda relation, distance: None,
        spatial_behavior=lambda intent: None,
        hold=lambda: None,
        vocalize=lambda text: None,
        return_to_safe_pose=applied.append,
    )
    assert adapter.dispatch(_pose_request(), now=1.0) is None
    assert applied == ["sit"]


def test_the_pose_skill_is_verified_against_the_applied_posture_not_the_request() -> None:
    adapter = SemanticTaskRuntimeAdapter(
        navigate=lambda directive: None,
        follow_formation=lambda relation, distance: None,
        spatial_behavior=lambda intent: None,
        hold=lambda: None,
        vocalize=lambda text: None,
        return_to_safe_pose=lambda name: None,
    )
    adapter.dispatch(_pose_request(), now=1.0)

    unapplied = SemanticRuntimeState(
        snapshot_id="s1",
        posture="unknown",
        stop_confirmed=True,
        control_feedback_fresh=True,
        robot_moving=False,
    )
    assert adapter.poll(unapplied, now=2.0)[0].status == "in_progress"

    applied = replace(unapplied, posture="sit")
    result = adapter.poll(applied, now=3.0)[0]
    assert result.status == "succeeded"
    assert result.verified_facts[0].target == "sit"


def test_a_pose_that_never_settles_does_not_succeed() -> None:
    adapter = SemanticTaskRuntimeAdapter(
        navigate=lambda directive: None,
        follow_formation=lambda relation, distance: None,
        spatial_behavior=lambda intent: None,
        hold=lambda: None,
        vocalize=lambda text: None,
        return_to_safe_pose=lambda name: None,
    )
    adapter.dispatch(_pose_request(), now=1.0)
    moving = SemanticRuntimeState(
        snapshot_id="s1",
        posture="sit",
        stop_confirmed=True,
        control_feedback_fresh=True,
        robot_moving=True,
    )
    assert adapter.poll(moving, now=2.0)[0].status == "in_progress"


def test_return_to_safe_pose_still_reads_its_own_argument_name() -> None:
    """Adding Pose must not have broken the battery-critical procedure."""

    applied: list[str] = []
    adapter = SemanticTaskRuntimeAdapter(
        navigate=lambda directive: None,
        follow_formation=lambda relation, distance: None,
        spatial_behavior=lambda intent: None,
        hold=lambda: None,
        vocalize=lambda text: None,
        return_to_safe_pose=applied.append,
    )
    request = replace(
        _pose_request(),
        skill="ReturnToSafePose",
        arguments=FrozenDict({"pose": "stand"}),
        success=SuccessCondition("safe_pose"),
        resources=("base", "posture", "attention"),
    )
    adapter.dispatch(request, now=1.0)
    assert applied == ["stand"]


# ---------------------------------------------------------------------------
# product path — one live-free runtime, entered at handle_text
# ---------------------------------------------------------------------------


class _Backend:
    name = "settle-test"

    def __init__(self) -> None:
        self._observation = SimObservation(
            timestamp=0.0,
            robot=RobotPose(),
            owner=OwnerTrack(owner_id="owner-test", x=3.0, y=0.0, visible=True, confidence=1.0),
            backend=self.name,
        )
        self.poses: list[object] = []

    def observe(self) -> SimObservation:
        return replace(self._observation, timestamp=time.monotonic())

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        self.poses.append(pose)

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


@pytest.fixture()
def runtime(tmp_path: Path):
    config = tmp_path / "robot-settle.yaml"
    config.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
  config: {REPO / "configs" / "navigation" / "default.yaml"}
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
    backend = _Backend()
    session = RobotRuntime(
        config,
        backend,
        audio_status=AudioDeviceStatus(
            status="text mode",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="deterministic test status",
        ),
    )
    observation = backend.observe()
    session._observation = observation
    if session._control_state_source is not None:
        session._control_state_source.update_observation(observation)
    try:
        yield session
    finally:
        session.close()


def test_go_to_the_owner_engages_the_follow_lane_on_the_product_path(
    runtime: RobotRuntime,
) -> None:
    reply = runtime.handle_text("go to the owner")
    assert "couldn't admit" not in reply, (
        f"{reply!r} (error={runtime.agent.last_reasoning_error!r})"
    )
    assert runtime.agent.last_reasoning_source == "local_plan_sketch"
    assert runtime.agent.last_brain_metrics["local_plan_skills"] == ["FollowFormation"]
    runtime._step_brain()
    assert runtime.follow.enabled is True
    assert runtime.follow.mode == "direct"
    # And the navigation lane was never armed for a semantic-map "owner".
    assert runtime.snapshot()["navigation"]["enabled"] is False


def test_sit_next_to_the_bench_publishes_a_two_step_plan_on_the_product_path(
    runtime: RobotRuntime,
) -> None:
    reply = runtime.handle_text("sit next to the bench")
    assert "couldn't admit" not in reply, (
        f"{reply!r} (error={runtime.agent.last_reasoning_error!r})"
    )
    assert runtime.agent.last_reasoning_source == "local_plan_sketch"
    assert runtime.agent.last_brain_metrics["local_plan_skills"] == ["NavigateTo", "Pose"]
    plan = runtime._last_brain_plan
    assert plan is not None
    assert plan["steps"] == ["NavigateTo", "Pose"]


def test_the_settle_plan_is_acknowledged_as_travel_plus_posture(
    runtime: RobotRuntime,
) -> None:
    """H2, fixed 2026-08-07: the reply named the plan, not just its goal shape.

    ``_plan_acknowledgement`` keyed on ``goal.relation`` alone, and a settle
    plan wears ``hold``/``current_pose`` because that is the only goal shape
    the validator admits for a terminal ``Pose`` step. So a command that walks
    to a bench and sits down was answered **"Okay—I'll stay here."** — not
    unsafe, not a false arrival claim, just a wrong answer.
    """

    reply = runtime.handle_text("sit next to the bench")
    assert "stay here" not in reply, reply
    assert "bench" in reply, reply
    assert "sit down" in reply, reply
    # It must still describe intent, never arrival or a posture already taken.
    assert runtime._last_posture in {None, "unknown"}


def test_a_plain_hold_plan_still_says_it_will_stay(runtime: RobotRuntime) -> None:
    """The `hold` branch is narrowed, not replaced: no NavigateTo, no travel."""

    reply = runtime.handle_text("stay")
    assert reply == "Okay—I'll stay here."


def test_the_shipped_config_did_not_have_to_change_for_the_settle_step() -> None:
    """``configs/robot.yaml`` is a frozen eval input; it must stay untouched.

    Its SHA-256 is a locked input of ``evals/companion/embodied_plan_v1``.
    Routing the settle posture through SYSTEM_SKILL_NAMES instead of the brain
    skill list is what keeps it byte-identical.
    """

    import yaml

    config = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))
    skills = config["agent"]["brain"]["skills"]
    assert "Pose" not in skills
    assert set(skills) == _CONFIGURED_SKILLS
    assert set(skills) <= set(SemanticTaskRuntimeAdapter.SUPPORTED_SKILLS)


# ---------------------------------------------------------------------------
# novel-verb clarify fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("transcript", "expected_class"),
    [
        ("befriend the bench", "bench"),
        ("photograph the tree", "tree"),
        ("admire the street light", "lamppost"),
        ("decorate the building", "building"),
    ],
)
def test_a_novel_verb_over_a_known_class_gets_an_offer_not_silence(
    transcript: str,
    expected_class: str,
) -> None:
    reply = clarification_for(transcript)
    assert reply is not None
    assert expected_class in reply
    assert "I'm not sure what you want me to do" in reply


def test_the_offer_names_only_relations_the_class_actually_affords() -> None:
    """The offer must name exactly the relations the sidecar advertises.

    The invariant has never changed; its *examples* have moved twice, with the
    measurement, and both moves are worth keeping in view.

    * **2026-08-08 (card B-2).** ``next_to`` was achievable only while
      ``NEXT_TO_BAND_M[1] >= StandOffEnvelope.minimum_vicinity(R)`` — anchor
      radii up to 0.38 m — because the band was measured to the anchor's centre
      and the envelope to its surface. ``bench`` (0.734), ``tree`` (0.58) and
      ``planter`` (0.45) were dropped as impossible; only the 0.06 m lamppost
      kept the offer.
    * **2026-08-09 (card S-1).** The band is measured to the anchor's SURFACE,
      so its width no longer depends on the anchor's size and all three are
      achievable again. They are back on the positive side.

    ``building`` stays on the negative side, and its reason is now different in
    kind: the sidecar excludes it as a **vocabulary** choice, not a
    measurement. That is exactly what this test checks — the offer tracks the
    sidecar, whatever the sidecar's reason.
    """

    building = clarification_for("decorate the building")
    bench = clarification_for("befriend the bench")
    tree = clarification_for("photograph the tree")
    lamppost = clarification_for("admire the street light")
    assert None not in (building, bench, tree, lamppost)
    for offer in (bench, tree, lamppost):
        assert "sit next to it" in offer, offer
    assert "sit next to it" not in building
    # ...and the offer still says something useful about the excluded class.
    assert "go to it" in building and "walk towards it" in building, building


def test_clarification_returns_none_when_nothing_is_recognized() -> None:
    """It must not manufacture a helpful-sounding reply out of nothing."""

    for transcript in ("befriend the neighbour", "tell me a joke", "xyzzy"):
        assert clarification_for(transcript) is None


def test_the_fallback_is_gated_on_the_routers_own_verb_list() -> None:
    assert physical_cue_present("go to the bench") is True
    assert physical_cue_present("befriend the bench") is False


def test_the_clarify_fallback_reaches_handle_text(runtime: RobotRuntime) -> None:
    reply = runtime.handle_text("befriend the bench")
    assert reply != "I did not understand that command"
    assert "bench" in reply
    # Honest: a clarification is conversation, never motion.
    assert runtime.snapshot()["navigation"]["enabled"] is False
    assert runtime.follow.enabled is False


def test_an_unrecognized_utterance_still_gets_the_flat_reply(runtime: RobotRuntime) -> None:
    assert runtime.handle_text("xyzzy plugh") == "I did not understand that command"


# --- clarify-fallback follow-ups (H6 / C-6a) -------------------------------


def test_the_offer_it_makes_can_actually_be_answered(runtime: RobotRuntime) -> None:
    """Measured defect, fixed 2026-08-07: the clarification wrote a cheque it could not cash.

    ``befriend the bench`` offers *"I can go to it, sit next to it, or walk
    towards it"*. Answering ``go to it`` published a plan whose navigation
    target was the literal word ``it`` and replied *"Okay—I'll go wait near it
    safely."* — a landmark that does not and cannot exist.
    """

    runtime.handle_text("befriend the bench")
    reply = runtime.handle_text("go to it")
    assert runtime.agent.last_resolved_reference == ("go to it", "go to the bench")
    assert "bench" in reply, reply
    assert " it " not in f" {reply} ", reply
    assert runtime.agent.last_brain_metrics["resolved_reference"] == [
        "go to it",
        "go to the bench",
    ]


def test_every_offer_the_clarification_makes_is_answerable(runtime: RobotRuntime) -> None:
    """Each offered phrase, verbatim, must reach a plan about the right class."""

    for answer in ("go to it", "sit next to it", "walk towards it"):
        runtime.handle_text("befriend the bench")
        reply = runtime.handle_text(answer)
        assert runtime.agent.last_resolved_reference is not None, answer
        assert runtime.agent.last_resolved_reference[1].endswith("the bench"), answer
        assert "bench" in reply, (answer, reply)


def test_the_referent_lives_exactly_one_turn(runtime: RobotRuntime) -> None:
    """A pronoun must not bind to something said minutes ago."""

    runtime.handle_text("befriend the bench")
    runtime.handle_text("go to it")
    reply = runtime.handle_text("go to it")
    assert runtime.agent.last_resolved_reference is None
    assert "not sure what" in reply, reply


def test_an_unanswered_clarification_is_consumed_by_whatever_comes_next(
    runtime: RobotRuntime,
) -> None:
    """Any next utterance ends the offer, answered or not."""

    runtime.handle_text("befriend the bench")
    assert runtime.handle_text("tell me a joke") == "I did not understand that command"
    assert runtime.agent.last_resolved_reference is None
    assert runtime.agent._pending_scene_referent is None


def test_a_named_target_is_never_overwritten_by_a_pending_referent(
    runtime: RobotRuntime,
) -> None:
    """Resolution binds pronouns; it must not rewrite what the owner did say."""

    runtime.handle_text("befriend the bench")
    reply = runtime.handle_text("go to the sidewalk")
    assert runtime.agent.last_resolved_reference is None
    assert "sidewalk" in reply
    assert "bench" not in reply


def test_a_dangling_pronoun_destination_is_asked_about_not_admitted(
    runtime: RobotRuntime,
) -> None:
    """No referent, no mission: "it" is not a landmark."""

    reply = runtime.handle_text("go to it")
    assert "not sure what" in reply and '"it"' in reply, reply
    assert runtime._last_brain_plan is None
    assert runtime.snapshot()["navigation"]["enabled"] is False


def test_a_real_label_containing_a_pronoun_is_untouched() -> None:
    """Word boundaries, not substrings: "summit" is not "it"."""

    assert dangling_reference("go to the summit") is None
    assert dangling_reference("go to it") == "it"
    assert dangling_reference("go to the bench") is None


def test_resolution_is_pure_and_refuses_without_a_referent() -> None:
    assert resolve_pending_reference("go to it", None) is None
    assert resolve_pending_reference("go to it", "bench") == "go to the bench"
    # Already names a class: nothing ambiguous, so nothing is rewritten.
    assert resolve_pending_reference("go to the sidewalk", "bench") is None
    assert resolve_pending_reference("hello", "bench") is None
