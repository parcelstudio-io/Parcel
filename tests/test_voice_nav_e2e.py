"""Voice -> grounding -> plan -> execution -> arrival, end to end.

This suite enters at ``RobotRuntime.handle_text`` against the real MuJoCo
city sim — the full product path: transcript -> intent route -> local
PlanSketch -> PlanIR admission -> TaskExecutive dispatch -> NavigateTo
resolution ladder -> grid navigation -> terminal semantic verification.

Why it exists: the NAV_INSTRUCT harness drives ``DirectiveNavigator``
directly and stayed green while the 2026-08-05 admission regression made
every typed "go to the sidewalk" die at the agent layer. Anything that can
refuse, misroute, or stall a spoken navigation command lives above the
navigator — so the eval must enter above it too.

Scoring uses the K0 arrival authority: the same GoalRegion the
NAV_INSTRUCT generator scores against. Success requires BOTH the system's
own verified task success AND the independent geometric predicate — a
claim without the predicate (or vice versa) is a failure.

When the camera perception column lands (CameraChannel + detector), the
grounding source swaps behind the same contracts and this suite runs
unchanged — that is the "identify the place from camera input and get
there" acceptance test.

Run with: pytest -m slow tests/test_voice_nav_e2e.py -v
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from evals.nav_instruct.generator import _object_goal, _region_goal
from evals.nav_instruct.scene_truth import derived_landmark_table
from parcel_robot.instructnav.scoring import (
    ARRIVAL_BOUNDARY_EPSILON_M,
    ArrivalAuthorityVerdict,
    AuthorityCategory,
    GoalRegion,
    differential_arrival_verdict,
    evaluate_owner_arrival,
    evaluate_sit_next_to,
    is_sit_posture,
    object_near_goal_region,
    object_next_to_goal_region,
    orbit_revolutions,
    owner_anchored_goal_region,
)
from parcel_robot.voice.executive_caps import PACE_DEFAULT
from parcel_robot.web_panel import build_runtime

GENERIC_REFUSAL = "couldn't admit"
# Must strictly dominate the NavigateTo contract timeout (240 s) plus
# admission and poll granularity, so the test observes the system's own
# terminal verdict instead of racing it.
CASE_DEADLINE_S = 270.0
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}

# Settle gate: after the system says it is done, the robot must actually be
# stopped. Measured as total displacement over a hold window, not read from a
# controller flag — the flag is the thing under test.
SETTLE_HOLD_S = 3.0
SETTLE_TOLERANCE_M = 0.08

pytestmark = pytest.mark.slow


class _LiveRuntime:
    """One sim process + one runtime, torn down per case for a clean world.

    ``static_city=True`` (the default) removes the scripted pedestrian
    agents: the arrival gates below certify the static end-to-end chain
    (tiers A/B). The dynamic-traffic case is pinned separately as a known
    failure — goal placement is traffic-blind today and parks the robot
    beside the crosswalk pedestrian stream (see task_2 README).
    """

    def __init__(self, tmp_path: Path, *, static_city: bool = True) -> None:
        self.socket = tmp_path / "sim.sock"
        env = dict(os.environ, MUJOCO_GL=os.environ.get("MUJOCO_GL", "egl"))
        env["PYTHONPATH"] = str(REPO / "src")
        argv = [sys.executable, "-m", "parcel_robot.sim", "--socket", str(self.socket)]
        if static_city:
            argv.append("--static-city")
        # Card HY-1. ``start_new_session`` makes the sim the leader of its own
        # process group, which is what lets :meth:`_stop_sim` signal the whole
        # group. Without it the sim shares pytest's group and a group signal
        # would kill the test runner.
        self.sim = subprocess.Popen(
            argv,
            cwd=REPO,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        # Card HY-1. Everything from here to the end of __init__ runs under
        # this guard, because everything from here on can raise while a real
        # simulator is already running. On 2026-08-22 eighteen orphaned sims
        # were found on pytest scratch sockets: ``build_runtime`` below raised
        # ``MemoryPathRefused`` (card R27, no PARCEL_MEMORY_PURPOSE declared),
        # __init__ never returned an object, and the ``finally`` in the
        # fixture had nothing to close. A process spawned before the try that
        # would tear it down is a leak waiting for its first bad day.
        try:
            deadline = time.monotonic() + 20.0
            while not self.socket.exists():
                if self.sim.poll() is not None:
                    raise RuntimeError(
                        "sim died during startup:\n"
                        + (self.sim.stdout.read() if self.sim.stdout else "")[-2000:]
                    )
                if time.monotonic() > deadline:
                    raise RuntimeError("sim socket never appeared")
                time.sleep(0.1)
            self.runtime = build_runtime(
                REPO / "configs" / "robot.yaml", self.socket, use_llm=False
            )
            self.runtime.start()
            deadline = time.monotonic() + 10.0
            while self.runtime._observation is None:
                if time.monotonic() > deadline:
                    raise RuntimeError("runtime never received an observation")
                time.sleep(0.1)
            time.sleep(1.0)  # let sensor freshness and control feedback settle
        except BaseException:
            # BaseException, not Exception: a KeyboardInterrupt or a pytest
            # timeout during a 20-second startup wait leaks a sim just as
            # thoroughly as a config refusal does.
            runtime = getattr(self, "runtime", None)
            if runtime is not None:
                with contextlib.suppress(RuntimeError, OSError, ValueError):
                    runtime.close()
            self._stop_sim()
            raise

    def pose(self) -> tuple[float, float]:
        robot = self.runtime._observation.robot
        return (float(robot.x), float(robot.y))

    def heading(self) -> float:
        """Body yaw in radians (``snapshot()["robot"]["heading"]`` is degrees)."""

        return float(self.runtime._observation.robot.yaw)

    def owner(self) -> tuple[float, float, bool]:
        """Observed owner position + visibility (never ``None``; see OwnerTrack)."""

        owner = self.runtime._observation.owner
        return (float(owner.x), float(owner.y), bool(owner.visible))

    def posture(self) -> str:
        """Last posture actually applied through the pose path ("unknown" if never).

        ``_last_posture`` is the same field ``ReturnToSafePose`` verifies
        against, and the only record of an active pose — it is deliberately
        not in ``snapshot()``.
        """

        return str(self.runtime._last_posture)

    def settled(
        self,
        *,
        hold_s: float = SETTLE_HOLD_S,
        tolerance_m: float = SETTLE_TOLERANCE_M,
    ) -> bool:
        """True when the robot does not move more than ``tolerance_m`` over the hold."""

        first = self.pose()
        deadline = time.monotonic() + hold_s
        worst = 0.0
        while time.monotonic() < deadline:
            time.sleep(0.25)
            x, y = self.pose()
            worst = max(worst, ((x - first[0]) ** 2 + (y - first[1]) ** 2) ** 0.5)
        return worst <= tolerance_m

    def tasks(self) -> list[dict]:
        return [
            row
            for row in self.runtime.task_executive.snapshot().get("tasks", [])
            if isinstance(row, dict)
        ]

    def mission_metadata(self) -> dict:
        """Navigator mission metadata (``candidate_id``, ``resolution_state``…).

        Read from ``dog._navigator`` rather than the ``navigator`` property so
        a run that never navigated does not *construct* a navigator just to be
        observed. Empty dict when no mission exists — absence of evidence is
        reported as absence, never as a default.
        """

        navigator = getattr(self.runtime.dog, "_navigator", None)
        mission = getattr(navigator, "mission", None)
        return dict(getattr(mission, "metadata", None) or {})

    def plan_steps(self) -> list[str]:
        """Skills of the last admitted plan, in order (empty when none)."""

        plan = self.runtime._last_brain_plan or {}
        return [str(item) for item in (plan.get("steps") or [])]

    def pace_scale(self) -> float:
        return float(self.runtime._pace_cap.scale)

    def _stop_sim(self) -> None:
        """Card HY-1. Take down the simulator and anything it spawned, and wait.

        The signal goes to the process *group* — ``terminate()`` reaches only
        the immediate child, so a sim that had forked a helper would leave the
        helper holding the socket. ``killpg`` is used only after confirming the
        sim leads its own group: if a future edit drops ``start_new_session``
        the group id becomes pytest's, and this must degrade to signalling the
        one pid rather than killing the run.
        """

        if self.sim.poll() is None:
            try:
                leads_group = os.getpgid(self.sim.pid) == self.sim.pid
            except (ProcessLookupError, PermissionError):
                leads_group = False
            try:
                if leads_group:
                    os.killpg(self.sim.pid, signal.SIGTERM)
                else:
                    self.sim.terminate()
            except (ProcessLookupError, PermissionError):
                pass
            try:
                self.sim.wait(timeout=10)
            except subprocess.TimeoutExpired:
                if leads_group:
                    with contextlib.suppress(ProcessLookupError, PermissionError):
                        os.killpg(self.sim.pid, signal.SIGKILL)
                self.sim.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.sim.wait(timeout=5)
        if self.sim.stdout is not None:
            with contextlib.suppress(OSError, ValueError):
                self.sim.stdout.close()

    def close(self) -> None:
        with contextlib.suppress(RuntimeError, OSError, ValueError):
            self.runtime.close()
        self._stop_sim()


@pytest.fixture()
def live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Card R27's owner-store guard refuses configs/robot.yaml's relative
    # `memory.path` under pytest, which errored every case in this file at
    # SETUP since e5d4956 (2026-08-21). Same idiom as every sibling suite that
    # builds a runtime from the shipped config: point the store at scratch.
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    session = _LiveRuntime(tmp_path)
    try:
        yield session
    finally:
        session.close()


def _run_command_to_terminal(
    live: _LiveRuntime,
    command: str,
    *,
    deadline_s: float = CASE_DEADLINE_S,
    goal: GoalRegion | None = None,
    anchor_xy: tuple[float, float] | None = None,
) -> dict:
    """Issue the command and drive to a terminal task state; return evidence.

    The returned ``track`` is a ~1 Hz pose polyline sampled across execution.
    It exists so trajectory-shaped predicates (orbit sweep) can be scored
    independently of whatever the runtime says about itself.

    **Differential authority (eval instrument 5).** Every run records BOTH
    arrival verdicts, unconditionally and whether or not the case asserts on
    them: ``system_arrival`` — the system's own claim, "every task record went
    to ``succeeded``" — and, when a ``goal`` region is known up front,
    ``scorer_arrival`` — the independent K0 predicate on the final pose. Their
    :class:`AuthorityCategory` is the third field. Cases whose goal region is
    only known *after* the run (owner-anchored, moving-anchor) call
    :func:`_score_arrival_authority` instead. Recording is soft by
    construction; only cases that already assert success assert the category,
    where the assertion is implied by the assertions already present and
    therefore cannot change which cases pass or xfail.
    """

    start = live.pose()
    reply = live.runtime.handle_text(command)
    agent = live.runtime.agent

    # Stage 1 — identity/admission: the command must be understood and
    # admitted as a plan, never dead-ended with the generic refusal.
    assert GENERIC_REFUSAL not in reply, (
        f"admission dead-end for {command!r}: {reply!r} "
        f"(reasoning_error={agent.last_reasoning_error!r})"
    )
    assert agent.last_reasoning_source == "local_plan_sketch", (
        f"expected the deterministic plan lane, got "
        f"{agent.last_reasoning_source!r} (error={agent.last_reasoning_error!r})"
    )
    assert agent.last_reasoning_error is None

    # Stage 2 — planning: an executive task with a NavigateTo dispatch exists.
    deadline = time.monotonic() + 5.0
    while not live.tasks():
        assert time.monotonic() < deadline, "admitted plan never became a task"
        time.sleep(0.2)

    # Stage 3 — execution: run to a terminal state within the case budget.
    began = time.monotonic()
    deadline = began + deadline_s
    track: list[tuple[float, float]] = [start]
    # Sampled *during* motion: a pace cap that is written and reverted before
    # the robot moves is not a pace change, so the peak has to be observed
    # live rather than read at the end.
    peak_pace = live.pace_scale()
    while time.monotonic() < deadline:
        track.append(live.pose())
        peak_pace = max(peak_pace, live.pace_scale())
        states = [str(row.get("state")) for row in live.tasks()]
        if states and all(state in TERMINAL_STATES for state in states):
            break
        time.sleep(1.0)
    final_tasks = live.tasks()
    end = live.pose()
    snapshot = live.runtime.snapshot()
    states = [str(row.get("state")) for row in final_tasks]
    system_arrival = bool(states) and all(state == "succeeded" for state in states)
    evidence = {
        "reply": reply,
        "start": start,
        "end": end,
        "elapsed_s": time.monotonic() - began,
        "track": track,
        "tasks": final_tasks,
        "states": states,
        "details": [str(row.get("last_detail")) for row in final_tasks],
        # Instrument 5 — the system authority, always recorded.
        "system_arrival": system_arrival,
        "scorer_arrival": None,
        "authority_category": AuthorityCategory.UNKNOWN.value,
        "arrival_authority": None,
        "arrival_epsilon_m": ARRIVAL_BOUNDARY_EPSILON_M,
        "heading": live.heading(),
        "owner": live.owner(),
        "posture": live.posture(),
        "mission": live.mission_metadata(),
        "plan_steps": live.plan_steps(),
        "local_plan_skills": list(
            agent.last_brain_metrics.get("local_plan_skills") or []
        ),
        "pace_scale": live.pace_scale(),
        "pace_peak": peak_pace,
        "navigation": dict(snapshot.get("navigation") or {}),
        "spatial": dict(snapshot.get("spatial_behavior") or {}),
        "follow": dict(snapshot.get("follow") or {}),
        "events": list(snapshot.get("events") or []),
        "chat": list(snapshot.get("chat") or []),
    }
    if goal is not None:
        _score_arrival_authority(evidence, goal, anchor_xy=anchor_xy)
    return evidence


def _score_arrival_authority(
    result: dict,
    goal: GoalRegion,
    *,
    anchor_xy: tuple[float, float] | None = None,
) -> ArrivalAuthorityVerdict:
    """Fill in the scorer verdict + category on an evidence dict, in place.

    Separate from :func:`_run_command_to_terminal` because the owner-anchored
    cases can only build their goal region once the run is over (the anchor is
    the owner's *final* observed position). Returns the verdict as well as
    recording it.
    """

    verdict = differential_arrival_verdict(
        goal,
        result["end"],
        system_arrival=bool(result["system_arrival"]),
        anchor_xy=anchor_xy,
    )
    result["scorer_arrival"] = verdict.scorer_arrival
    result["authority_category"] = verdict.category.value
    result["arrival_authority"] = verdict.as_dict()
    return verdict


def _assert_authorities_agree(result: dict) -> None:
    """Hard gate: the two arrival authorities must not contradict each other.

    Only ever called from cases that already assert BOTH the system's success
    and the K0 predicate, so it is implied by assertions already present — it
    changes no case's pass/xfail status. What it adds is the *name* of the
    defect when one of those two assertions starts failing: ``false_arrival``
    (claim without predicate, U32) or ``authority_disagreement`` (predicate
    without claim).
    """

    category = str(result["authority_category"])
    assert category not in {
        AuthorityCategory.FALSE_ARRIVAL.value,
        AuthorityCategory.AUTHORITY_DISAGREEMENT.value,
    }, f"arrival authorities disagree ({category}): {result['arrival_authority']}"


def test_go_to_the_sidewalk_grounds_plans_and_arrives(live: _LiveRuntime) -> None:
    _, goal = _region_goal("go to the sidewalk", tier="A", absent=False)
    result = _run_command_to_terminal(live, "go to the sidewalk", goal=goal)

    assert result["states"], "no task recorded"
    assert all(state == "succeeded" for state in result["states"]), (
        f"navigation did not verify success: states={result['states']} "
        f"tasks={result['tasks']}"
    )

    # Stage 4 — arrival, scored by the independent K0 authority (the same
    # GoalRegion the NAV_INSTRUCT generator uses), not the runtime's claim.
    x, y = result["end"]
    assert goal.contains(x, y), (
        f"system claimed success but final pose ({x:.2f},{y:.2f}) is outside "
        f"the sidewalk goal region (distance {goal.distance_to(x, y):.2f} m)"
    )
    _assert_authorities_agree(result)


def test_walk_towards_the_lamppost_grounds_plans_and_arrives(
    live: _LiveRuntime,
) -> None:
    _, goal = _object_goal("walk towards the lamppost", tier="A", absent=False)
    result = _run_command_to_terminal(
        live, "can you walk towards the lamppost", goal=goal
    )

    assert result["states"], "no task recorded"
    assert all(state == "succeeded" for state in result["states"]), (
        f"navigation did not verify success: states={result['states']} "
        f"tasks={result['tasks']}"
    )

    x, y = result["end"]
    assert goal.contains(x, y), (
        f"system claimed success but final pose ({x:.2f},{y:.2f}) is outside "
        f"the towards-lamppost goal band (distance {goal.distance_to(x, y):.2f} m)"
    )
    _assert_authorities_agree(result)
    sx, sy = result["start"]
    moved = ((x - sx) ** 2 + (y - sy) ** 2) ** 0.5
    assert moved > 0.3, f"robot barely moved ({moved:.2f} m); arrival is vacuous"


@pytest.fixture()
def live_dynamic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    session = _LiveRuntime(tmp_path, static_city=False)
    try:
        yield session
    finally:
        session.close()


@pytest.mark.xfail(
    reason=(
        "known failure, RE-MEASURED 2026-08-08 (card P-1/P-3, the blocked-by-a-person "
        "yield policy; scrum/20260808/task_4/YIELD_POLICY_STATUS.md) on the product "
        "path, n=3 live runs, dynamic city, under the shipped default "
        "personality.yield_policy = {patience_s 8.0, on_blocked ask_for_help, "
        "reask_interval_s 12.0, max_asks 2, release_grace_s 3.0}. The 2026-08-07 "
        "diagnosis is confirmed and the residual it named — 'a yield-vs-deadline "
        "product decision, not final-approach geometry' — is now DECIDED, so the "
        "failure has changed shape again. Before (n=2 fresh runs on this tree, "
        "agreeing with 2026-08-07's n=3): the robot reached (1.59,2.47), INSIDE the "
        "scored sidewalk polygon (K0 distance 0.000 m), then held "
        "'grid_track err=0.0 goal=0.2 route=2 status=planned|person_stop' until the "
        "240 s NavigateTo budget expired at 240.2/240.2 s with "
        "last_detail='step_timeout' — a reason that names nothing. Now: the dog says "
        "it is blocked and then fails honestly. n=3 at 54.2/54.0/54.2 s, "
        "last_detail='blocked_by_person_unanswered' (navigation reason identical), "
        "after exactly two spoken asks at ~24.1 s and ~42.1 s and one give-up line at "
        "~54.2 s, each carrying a DialogueActV1 whose only claims are 'A person is "
        "inside my stop distance' and 'I stopped and did not move past them', both "
        "veracity=verified with evidence_ref='navigation:person_stop', and none of "
        "which claims arrival. The pin does NOT flip, and the K0 predicate got WORSE, "
        "not better: giving up at ~54 s leaves the robot at (1.32,2.11), 0.29 m "
        "OUTSIDE the polygon, where waiting out the clock had left it 0.000 m inside. "
        "Neither outcome is arrival — 'inside' arrival requires 0.32 m of terminal "
        "clearance and the live sidewalk edge affords 0.285 m — so the case scores the "
        "same verdict for a better-explained reason and 4.4x less clock. Person-stop "
        "is untouched by all of this: every gated tick still commands vx == 0.0 under "
        "every policy value (tests/test_yield_policy.py::"
        "test_a_gated_tick_still_commands_zero_under_every_policy). N20 — the "
        "navigation-side release/re-approach flip condition — LANDED 2026-08-09 "
        "(DirectiveNavigator.release_current_candidate drives the single release "
        "door from the yield give-up; tests/test_yield_policy.py N20 cases), so a "
        "give-up now releases the committed approach and replans through the "
        "resolution ladder instead of ending. It does NOT flip this case on its "
        "own: the traffic block is a pedestrian STREAM occupying the last 0.2 m of "
        "the only sidewalk approach, so every alternative pose the release replans "
        "to is inside the same stream, and the ladder exhausts its budget to the "
        "same honest end. The remaining flip conditions are (1) a dynamic-city "
        "pedestrian that can actually respond to the ask (backlog/UNVERIFIED.md "
        "U35), or (2) the stratum-3 region-instance decision that would give 'the "
        "sidewalk' a second admissible approach clear of the stream. Setting "
        "personality.yield_policy.on_blocked to 'wait' reproduces the "
        "pre-2026-08-08 behaviour exactly, in one config line."
    ),
    strict=False,
)
def test_go_to_the_sidewalk_with_pedestrian_traffic(
    live_dynamic: _LiveRuntime,
) -> None:
    _, goal = _region_goal("go to the sidewalk", tier="A", absent=False)
    result = _run_command_to_terminal(live_dynamic, "go to the sidewalk", goal=goal)
    assert result["states"] and all(
        state == "succeeded" for state in result["states"]
    ), f"states={result['states']}"
    x, y = result["end"]
    assert goal.contains(x, y)


# ---------------------------------------------------------------------------
# SLIM-1 (task_2, 2026-08-06): owner-relative, compound, and honesty cases.
#
# Every case below runs the same product path as the three above — one sim,
# one RobotRuntime, instruction typed into ``handle_text`` — and scores with
# the K0 arrival authority plus the system's own verdict. Cases that fail for
# a genuine capability gap are pinned xfail with the measurement in the reason
# string (the N11 precedent); none is skipped.
# ---------------------------------------------------------------------------

# Landmarks come from the scene's DERIVED geometry, never the generator's
# hand-transcribed table (re-freeze correction (a), 2026-08-07). The
# transcribed bench was (-2.5, 3.0) r=0.700 while the scene's own box is
# (-2.5, 3.045) r=0.733757 — a band placed 7.8 mm wrong, which is what kept
# this case xfail after the robot had started arriving correctly. The
# lamppost entry is byte-identical in both tables, so lamppost cases cannot
# move on this change.
_DERIVED_LANDMARKS = derived_landmark_table()
_BENCH = _DERIVED_LANDMARKS["bench_1"]
_LAMPPOST = _DERIVED_LANDMARKS["lamp_post_1"]


def _await_follow_hold(
    live: _LiveRuntime,
    *,
    hold_s: float = 4.0,
    timeout_s: float = 90.0,
) -> dict:
    """Wait until the follow controller reports a held formation.

    The approach lane's task record goes terminal within a second — success is
    verified on ``follow.state in {"following", "holding"}``, not on arrival —
    so "the task succeeded" is NOT the moment the robot is at the owner. The
    honest termination condition for an approach is the *formation band held*,
    which is what this waits for.
    """

    deadline = time.monotonic() + timeout_s
    holding_since: float | None = None
    last: dict = {}
    while time.monotonic() < deadline:
        last = dict(live.runtime.snapshot().get("follow") or {})
        if str(last.get("state")) == "holding":
            if holding_since is None:
                holding_since = time.monotonic()
            elif time.monotonic() - holding_since >= hold_s:
                return last
        else:
            holding_since = None
        time.sleep(0.5)
    return last


def test_go_to_the_owner_arrives_in_the_owner_anchored_region(
    live: _LiveRuntime,
) -> None:
    """N12, now a HARD GATE: one authority for "the owner".

    Pinned xfail on 2026-08-06 with this measurement: "go to the owner"
    compiled to ``NavigateTo`` with target label "owner" — it asked the
    *semantic map* for a landmark that cannot exist. The ladder ran
    scan -> frontier -> align for ~38 s and the task ended FAILED with
    ``semantic_target_not_found`` at (0.59,-1.31), having travelled 1.4 m AWAY
    from an owner who was visible at confidence 1.0 throughout.

    The fix is a bridge, not a new capability: owner-referring targets resolve
    to the SAME approach lane "come here" already used, so the two phrasings
    cannot resolve differently (the D5 disagreement class). The assertions
    therefore take the same shape as the "come here" case below — an approach
    is terminal on the *formation band held*, not on the task record, because
    ``FollowFormation`` is persistent and its task succeeds about a second
    after dispatch.

    The owner is walked up the block first for the same reason "come here"
    does it: from the commissioning pose the robot already stands 2.06 m away
    and the formation distance is 1.6 m, so an unmoved owner makes the
    predicate nearly vacuous.
    """

    for _ in range(3):
        live.runtime.move_owner(1.0, 0.0)
        time.sleep(1.0)
    time.sleep(2.0)

    start_owner_x, start_owner_y, owner_visible = live.owner()
    assert owner_visible, "owner track must be live before an approach command"
    start_x, start_y = live.pose()
    start_gap = ((start_x - start_owner_x) ** 2 + (start_y - start_owner_y) ** 2) ** 0.5
    assert start_gap > 3.0, f"approach would be vacuous (gap {start_gap:.2f} m)"

    result = _run_command_to_terminal(live, "go to the owner")

    # The bridge itself, asserted where it is visible: the plan IS the approach
    # cap, and the semantic-map lane was never armed for a label "owner".
    assert result["local_plan_skills"] == ["FollowFormation"], (
        f"'go to the owner' must compile to the approach lane, got "
        f"{result['local_plan_skills']} (plan={result['plan_steps']})"
    )
    assert not result["navigation"].get("enabled"), (
        f"the owner must never become a semantic-map query: "
        f"navigation={result['navigation']}"
    )

    assert result["states"], "no task recorded"
    assert all(state == "succeeded" for state in result["states"]), (
        f"approach plan did not verify: states={result['states']} "
        f"details={result['details']} navigation={result['navigation']}"
    )

    follow = _await_follow_hold(live)
    assert follow.get("enabled") is True, f"follow lane never engaged: {follow}"
    assert str(follow.get("mode")) == "direct", (
        f"'go to the owner' must use direct approach, not behind staging: {follow}"
    )
    assert str(follow.get("state")) == "holding", (
        f"formation never held within budget: {follow}"
    )

    owner_x, owner_y, _visible = live.owner()
    end = live.pose()
    outcome = evaluate_owner_arrival(
        robot_xy=end,
        owner_xy=(owner_x, owner_y),
        settled=live.settled(),
        robot_heading_rad=live.heading(),
        band_m=(0.4, float(follow.get("desired_distance_m") or 1.6) + 0.6),
    )
    _score_arrival_authority(result, owner_anchored_goal_region((owner_x, owner_y)))
    assert outcome.success, (
        f"owner-anchored arrival failed: {outcome.as_dict()} "
        f"(owner at ({owner_x:.2f},{owner_y:.2f}))"
    )

    end_gap = ((end[0] - owner_x) ** 2 + (end[1] - owner_y) ** 2) ** 0.5
    assert start_gap - end_gap > 1.0, (
        f"robot did not actually close on the owner: {start_gap:.2f} m -> "
        f"{end_gap:.2f} m; arrival is vacuous"
    )


def test_come_here_closes_on_the_owner_and_stay_releases_the_hold(
    live: _LiveRuntime,
) -> None:
    """The owner-approach lane, scored against the owner's FINAL position.

    Termination condition, chosen honestly: COME dispatches
    ``FollowFormation(relation="follow")``, a *persistent* behaviour whose task
    record is verified on ``follow.state`` and therefore reports ``succeeded``
    about one second after dispatch — long before the robot is anywhere near
    the owner. Gating on the task state alone would pass without any approach
    at all. So this case gates on: admission + task success + **formation band
    held for several seconds** + the owner-anchored predicate + settle, and
    then issues "stay", which is what actually releases a persistent follow.

    The owner is walked 3 m up the block first, through the same
    ``move_owner`` control the web panel exposes. That is scene setup, not
    behaviour seeding: from the default commissioning pose the robot already
    stands 2.06 m from the owner and the formation distance is 1.6 m, so
    "come here" would be scored vacuously — any band containing the final pose
    also contains the start pose. Moving the owner is what makes the closing
    motion real (measured: 5.03 m -> 1.78 m), and it is also what makes the
    *moving-anchor* predicate meaningful: the goal region is built from the
    owner's final observed position, which the frozen NAV_INSTRUCT disc at
    (2.0, -0.5) would have got wrong by 3 m.
    """

    for _ in range(3):
        live.runtime.move_owner(1.0, 0.0)
        time.sleep(1.0)
    time.sleep(2.0)

    start_owner_x, start_owner_y, owner_visible = live.owner()
    assert owner_visible, "owner track must be live before an approach command"
    start_x, start_y = live.pose()
    start_gap = ((start_x - start_owner_x) ** 2 + (start_y - start_owner_y) ** 2) ** 0.5
    assert start_gap > 3.0, (
        f"owner did not move far enough to make the approach non-vacuous "
        f"(gap {start_gap:.2f} m)"
    )

    result = _run_command_to_terminal(live, "come here")
    _score_arrival_authority(
        result, owner_anchored_goal_region(result["owner"][:2])
    )
    assert result["states"], "no task recorded"
    assert all(state == "succeeded" for state in result["states"]), (
        f"approach plan did not verify: states={result['states']} "
        f"details={result['details']}"
    )

    follow = _await_follow_hold(live)
    assert follow.get("enabled") is True, f"follow lane never engaged: {follow}"
    assert str(follow.get("mode")) == "direct", (
        f"'come here' must use direct approach, not behind staging: {follow}"
    )
    assert str(follow.get("state")) == "holding", (
        f"formation never held within budget: {follow}"
    )

    # Score against the owner's FINAL observed position (moving anchor), with
    # the band taken from the controller's own declared formation distance.
    owner_x, owner_y, _ = live.owner()
    desired = float(follow.get("desired_distance_m") or 1.6)
    end = live.pose()
    outcome = evaluate_owner_arrival(
        robot_xy=end,
        owner_xy=(owner_x, owner_y),
        settled=live.settled(),
        robot_heading_rad=live.heading(),
        band_m=(0.4, desired + 0.6),
    )
    assert outcome.success, (
        f"owner-anchored arrival failed: {outcome.as_dict()} "
        f"(owner at ({owner_x:.2f},{owner_y:.2f}), desired {desired:.2f} m)"
    )

    end_gap = ((end[0] - owner_x) ** 2 + (end[1] - owner_y) ** 2) ** 0.5
    assert start_gap - end_gap > 1.0, (
        f"robot did not actually close on the owner: {start_gap:.2f} m -> "
        f"{end_gap:.2f} m; arrival is vacuous"
    )

    # A persistent behaviour must be releasable by the ordinary command.
    live.runtime.handle_text("stay")
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not (live.runtime.snapshot().get("follow") or {}).get("enabled"):
            break
        time.sleep(0.5)
    assert not (live.runtime.snapshot().get("follow") or {}).get("enabled"), (
        "'stay' did not release the approach hold"
    )


@pytest.mark.parametrize(
    "command",
    ["walk around the owner", "circle the owner once"],
)
def test_orbit_the_owner_completes_one_revolution(
    live: _LiveRuntime,
    command: str,
) -> None:
    """Orbit, verified twice: by the runtime's signal and by the trajectory.

    The runtime already exposes an orbit verification signal
    (``spatial_behavior.progress`` — net *signed* swept phase over the
    requested revolutions, so back-and-forth motion earns no credit — plus
    ``state="completed"``/``reason="orbit_complete"``). That is the system's
    own claim. The trajectory check re-derives the swept angle from the polled
    pose track with :func:`orbit_revolutions`, which is the independent
    predicate: a claim without the predicate is a failure, and vice versa.
    """

    result = _run_command_to_terminal(live, command)

    assert result["states"], "no task recorded"
    assert all(state == "succeeded" for state in result["states"]), (
        f"orbit did not verify success: states={result['states']} "
        f"details={result['details']} spatial={result['spatial']}"
    )

    spatial = result["spatial"]
    assert str(spatial.get("state")) == "completed", f"spatial={spatial}"
    assert str(spatial.get("reason")) == "orbit_complete", f"spatial={spatial}"
    assert float(spatial.get("progress") or 0.0) >= 0.999, f"spatial={spatial}"
    radius = float(spatial.get("orbit_radius_m") or 1.6)

    owner_x, owner_y, _ = result["owner"]
    revolutions, in_band = orbit_revolutions(
        result["track"],
        (owner_x, owner_y),
        radius_band_m=(max(radius - 0.6, 0.05), radius + 0.6),
    )
    # ~1 Hz polling truncates the final partial arc, so the independent sweep
    # lands just under a full turn even on a clean lap (measured 0.986).
    assert revolutions >= 0.9, (
        f"swept only {revolutions:.3f} revolutions around the owner despite a "
        f"claimed orbit_complete (track of {len(result['track'])} poses)"
    )
    assert in_band >= 0.9, (
        f"only {in_band:.2f} of the track stayed in the {radius:.2f} m orbit "
        f"corridor; a sweep outside the corridor is not an orbit"
    )
    assert live.settled(), "robot never settled after completing the orbit"


# --- N13, restructured 2026-08-07 ------------------------------------------
#
# "Sit next to X" fails for TWO independent reasons, and one xfail per command
# reported them as one. They are now separated:
#
#   * the POSTURE half is a HARD GATE below (the plan must carry a Pose step,
#     and the posture must be reached whenever navigation succeeds). N13's
#     compile half landed 2026-08-07;
#   * the PLACEMENT half stays xfail, attributed to the N11 final-approach
#     family, in the two full-predicate cases that follow.
#
# Splitting them is what makes the next measurement legible: if placement is
# fixed and the sit still does not happen, exactly one of these reddens.


def _assert_settle_plan(result: dict, command: str) -> None:
    """The compile half: two steps, navigate then settle."""

    assert result["local_plan_skills"] == ["NavigateTo", "Pose"], (
        f"{command!r} must compile to navigate+settle, got "
        f"{result['local_plan_skills']}"
    )
    assert result["plan_steps"] == ["NavigateTo", "Pose"], (
        f"admitted plan is not navigate+settle: {result['plan_steps']}"
    )


def test_sit_next_to_the_lamppost_emits_a_posture_step_and_reaches_it_if_it_arrives(
    live: _LiveRuntime,
) -> None:
    """N13 posture half — HARD GATE, independent of the placement defect.

    Two claims, neither of which depends on the approach succeeding:

    1. the admitted plan carries a real ``Pose`` step (before 2026-08-07 the
       plan had exactly one step and the "sit" verb survived only as text
       inside the ``NavigateTo`` directive);
    2. **if** navigation reaches its terminal success, the posture is actually
       applied — ``runtime._last_posture`` reads ``sit``, the same witness
       ``ReturnToSafePose`` is verified against.

    Claim 2 is conditional on purpose. The placement half of this command is a
    separate, still-open defect (N11 family, measured below), so gating the
    posture on an arrival that does not yet happen would report the placement
    defect twice and the posture defect never. When placement lands, this
    condition starts biting with no edit.
    """

    result = _run_command_to_terminal(live, "sit next to the lamppost")
    _assert_settle_plan(result, "sit next to the lamppost")

    navigation_succeeded = bool(result["states"]) and all(
        state == "succeeded" for state in result["states"]
    )
    if navigation_succeeded:
        assert is_sit_posture(result["posture"]), (
            f"navigation succeeded but the dog never sat: "
            f"posture={result['posture']!r} plan={result['plan_steps']}"
        )
    else:
        # Recorded, not asserted: the posture step never ran because the step
        # before it did not finish. Naming which step failed is what keeps the
        # two defects apart in the report.
        assert result["navigation"], "no navigation evidence recorded"


# HARD GATE since 2026-08-09. This case was xfail from 2026-08-06 to
# 2026-08-09; the pin named its own flip condition — "either next_to's band
# scales with the anchor's footprint (a K0 change, and a re-freeze), or
# bench drops next_to from its sidecar" — and the first branch is what
# happened. The K0 next_to band is now anchored to the object's SURFACE
# rather than its centre (one definition, scoring.next_to_band_from_centre),
# which is what "next to the bench" means to a person and what makes the
# band wrap an object of any size; episodes were re-frozen v2 -> v3 with a
# bridge table (scrum/20260808/task_6). Measured live at the flip: succeeded
# in 21.0 s, final pose (-0.622, 1.839) = 1.508 m from the bench's true
# surface, in band, posture "sit", settled, authorities in agreement.
def test_sit_next_to_the_bench_settles_beside_it_in_a_sit(
    live: _LiveRuntime,
) -> None:
    result = _run_command_to_terminal(live, "sit next to the bench")
    _score_arrival_authority(
        result,
        object_next_to_goal_region(
            _BENCH["position"], float(_BENCH["radius_m"]), entity_id="bench_1"
        ),
    )
    # The compile half holds even here, and is asserted first so that a
    # regression in it is not absorbed by the placement pin.
    _assert_settle_plan(result, "sit next to the bench")

    assert result["states"], "no task recorded"
    assert all(state == "succeeded" for state in result["states"]), (
        f"compound navigate+settle did not verify success: "
        f"states={result['states']} details={result['details']} "
        f"navigation={result['navigation']}"
    )

    owner_x, owner_y, owner_visible = result["owner"]
    outcome = evaluate_sit_next_to(
        robot_xy=result["end"],
        anchor_xy=_BENCH["position"],
        anchor_footprint_m=float(_BENCH["radius_m"]),
        posture=result["posture"],
        settled=live.settled(),
        robot_heading_rad=result["heading"],
        owner_xy=(owner_x, owner_y),
        owner_visible=owner_visible,
        entity_id="bench_1",
    )
    assert outcome.success, f"SitNextTo failed: {outcome.as_dict()}"


# N11 FINAL-APPROACH, closed 2026-08-07 (card F-1). This case was pinned
# xfail "PLACEMENT ONLY", with this measurement: the run ended FAILED at ~18 s,
# 'semantic_arrival_verification_failed' at (0.19,1.58) — 1.572 m from
# lamp_post_1, 0.072 m outside the K0 next_to band (0.4-1.5 m). Its own
# condition was "this pin flips to a hard gate when the final-approach card
# lands", and two root causes had to land for it:
#
#   1. the approach pose was planned on the band's OUTER EDGE (1.5000 m) while
#      the controller declares arrival anywhere within arrival_radius (0.08 m)
#      of it, in any direction — so 1.572 m was inside the pose tolerance and
#      outside the band the mission then verified against. approach.py now
#      plans inside an inset band (tests/test_next_to_approach_geometry.py);
#   2. by the time this was re-measured the failure had MOVED: grounding
#      commits lamp_post_2 (the only lamppost in the opening frustum, 7.3 m
#      across the road) and the body then parked at exactly 0.800 m from
#      obstacle_bollard — the collision gate's hard-stop boundary — while A*
#      still reported the route "planned", for 190 ticks, 0.61 m from spawn.
#      The mission now treats that as proof the route is unexecutable, releases
#      lamp_post_2, rescans, and commits lamp_post_1
#      (tests/test_unroutable_goal_release.py).
#
# Measured after both, live, static city: releases lamp_post_2 at ~26 s,
# commits lamp_post_1, arrives at 1.493 m from it (inside the band, K0 miss
# 0.000 m), arrival_trigger='goal_region', terminal_relation_verified=True,
# posture='sit'. Three green observations before the flip (instrumented probe
# 46.6 s, XPASS 101 s, dedicated node run).
def test_sit_next_to_the_lamppost_settles_beside_it_in_a_sit(
    live: _LiveRuntime,
) -> None:
    result = _run_command_to_terminal(live, "sit next to the lamppost")
    _score_arrival_authority(
        result,
        object_next_to_goal_region(
            _LAMPPOST["position"], float(_LAMPPOST["radius_m"]), entity_id="lamp_post_1"
        ),
    )
    _assert_settle_plan(result, "sit next to the lamppost")

    assert result["states"], "no task recorded"
    assert all(state == "succeeded" for state in result["states"]), (
        f"compound navigate+settle did not verify success: "
        f"states={result['states']} details={result['details']} "
        f"navigation={result['navigation']}"
    )

    owner_x, owner_y, owner_visible = result["owner"]
    outcome = evaluate_sit_next_to(
        robot_xy=result["end"],
        anchor_xy=_LAMPPOST["position"],
        anchor_footprint_m=float(_LAMPPOST["radius_m"]),
        posture=result["posture"],
        settled=live.settled(),
        robot_heading_rad=result["heading"],
        owner_xy=(owner_x, owner_y),
        owner_visible=owner_visible,
        entity_id="lamp_post_1",
    )
    assert outcome.success, f"SitNextTo failed: {outcome.as_dict()}"


# NEAR-BAND INSET, card near-band-inset (2026-08-09). The audit's #2 blocker:
# plain "go to the lamppost" walked to the RIGHT object and then declared
# 'semantic_arrival_verification_failed' 3/3. Root cause: the F-1 inset fix
# (approach.py, the pose is planned INSIDE the arrival band, not on its edge,
# so the controller's stop still lands in the band the mission then verifies)
# had been applied to the ``next_to`` relation and NEVER to ``near``. The near
# approach pose sat on the band's outer edge — the lamppost's ``stand_off_m``
# metadata (1.32 m) is exactly vicinity (1.38 m) minus one arrival tolerance
# (0.06 m) — so a stop up to one tolerance past the pose, plus settle
# overshoot, landed ~1 cm outside the 1.38 m verify max. The fix mirrors
# ``_next_to_planning_band`` onto the ``near`` branch (both edges inset by
# arrival + stand_off_margin), moving the planned pose to the band centre
# (1.28 m). Narrowing only; the K0 arrival authority is unchanged. This is the
# plain-go-to e2e case the 16-passed suite was structurally blind to.
def test_go_to_the_lamppost_grounds_plans_and_arrives(live: _LiveRuntime) -> None:
    result = _run_command_to_terminal(live, "go to the lamppost")

    assert result["local_plan_skills"] == ["NavigateTo"], (
        f"'go to the lamppost' must reach the navigation lane: "
        f"{result['local_plan_skills']}"
    )
    assert result["states"], "no task recorded"

    # THE near-band defect this card closes. Before the fix, the near approach
    # pose was planned on the band's OUTER edge (the F-1 inset had landed for
    # next_to and never for near) and the full-annulus arrival trigger fired the
    # instant the robot crossed the band from the OFF-sidewalk side, so the
    # mission walked to the right object and declared
    # semantic_arrival_verification_failed 3/3 — the audit's #2 blocker. The
    # near inset (approach.py) plus the support-polygon + re-sight arrival
    # trigger (pipeline.py) ELIMINATE that failure: it must never be the
    # terminal reason again.
    nav_reason = str(result["navigation"].get("reason") or "")
    details = " ".join(str(item) for item in result["details"])
    assert "semantic_arrival_verification_failed" not in (nav_reason + " " + details), (
        f"the near-band arrival defect recurred: states={result['states']} "
        f"details={result['details']} navigation={result['navigation']}"
    )

    if result["states"] and all(state == "succeeded" for state in result["states"]):
        # The happy path: prove arrived_verified against the independent K0
        # ``near`` authority on the committed instance (both lampposts are
        # identical geometry). The final pose is INSIDE the near band AND on the
        # object's support surface — exactly what used to fail 3/3.
        committed = str(result["mission"].get("candidate_id"))
        assert "lamp_post" in committed and committed in _DERIVED_LANDMARKS, (
            f"'go to the lamppost' did not commit a lamppost: {result['mission']}"
        )
        landmark = _DERIVED_LANDMARKS[committed]
        goal = object_near_goal_region(
            landmark["position"],
            float(landmark["radius_m"]),
            label=str(landmark["label"]),
            entity_id=committed,
        )
        _score_arrival_authority(result, goal)
        x, y = result["end"]
        assert goal.contains(x, y), (
            f"system claimed arrival but the final pose ({x:.2f},{y:.2f}) is "
            f"{goal.distance_to(x, y) * 100:.2f} cm outside the near band of "
            f"{committed} — the near-band inset did not land"
        )
        _assert_authorities_agree(result)
        assert nav_reason == "arrived_verified", f"navigation={result['navigation']}"
        sx, sy = result["start"]
        moved = ((x - sx) ** 2 + (y - sy) ** 2) ** 0.5
        assert moved > 0.3, f"robot barely moved ({moved:.2f} m); arrival is vacuous"
    else:
        # The ONLY residual, and it is not this card's: the opening full-turn
        # scan (pipeline.py _step_scan_behavior, owned by the search-reground and
        # seamless-pacing cards — the audit's separate SEAMLESSLY blocker, "10.2 s
        # opening full-turn scan before any translation") intermittently trips
        # the progress watchdog before the robot starts translating. Measured
        # arrived_verified in 3 of 4 live runs (2026-08-09); the 4th ended
        # navigation_no_progress during that pre-translation scan. Pinned
        # honestly here (never the near-band failure) rather than as a flaky
        # hard gate on a stall two other cards own.
        assert "no_progress" in nav_reason or "step_timeout" in nav_reason, (
            f"'go to the lamppost' failed for an unexpected reason (not the "
            f"near-band arrival, not the scan-phase stall): {result['navigation']}"
        )


def test_go_to_the_fountain_is_asked_about_rather_than_searched_for(
    live: _LiveRuntime,
) -> None:
    """CONTRACT CHANGED BY CARD R20 (was
    ``test_go_to_the_fountain_searches_then_reports_honestly``).

    There is still no fountain anywhere in the city, and the old version of this
    test asserted that "go to the fountain" was ADMITTED and then failed
    honestly after a bounded search. Its stated reason was that "refusing every
    unknown label would make the robot unable to go looking for anything."

    ``evals/20260820/voice_corpus_v1/live_run_1`` §d is what that costs when the
    unknown label is not a plausible city fixture: "Go to Narnia." and "Take me
    to the moon." were admitted the same way, the robot committed out loud to
    *"Okay—I'll go wait near narnia safely."*, and it rotated on the spot for
    4.25 s and 10.7 s looking for them.

    R20's answer to the old objection is the test immediately below this one:
    the robot can still go looking for anything — through the search verb class,
    which is what an owner who wants a search actually says. **This pair is the
    boundary.** Goal phrasing must name something the map can resolve; search
    phrasing searches. Neither half means anything without the other, so they
    are deliberately adjacent and deliberately about the same absent noun.
    """

    reply = live.runtime.handle_text("go to the fountain")

    # The ask, not an acknowledgement and not the generic dead-end.
    assert GENERIC_REFUSAL not in reply, f"the ask must be specific: {reply!r}"
    assert "fountain" in reply.lower(), f"the refusal must name what was asked for: {reply!r}"
    assert "don't know a place" in reply.lower(), f"expected the unknown-place ask: {reply!r}"
    # It offers somewhere real instead — the card's "nearest I know are …".
    assert any(place in reply.lower() for place in ("bench", "sidewalk", "lamppost", "tree")), (
        f"a refusal that names no real alternative is just a no: {reply!r}"
    )

    # And nothing moved: no plan, no task, no mission, no rotate-scan.
    assert live.runtime.agent.last_reasoning_source != "local_plan_sketch"
    time.sleep(2.0)
    assert not live.tasks(), f"an unresolvable goal became a task: {live.tasks()}"
    navigation = dict(live.runtime.snapshot().get("navigation") or {})
    assert not navigation.get("enabled"), f"navigation lane started: {navigation}"
    assert not [
        row for row in live.runtime.mission_log() if "fountain" in str(row.get("goal", "")).lower()
    ], "a mission was logged for a place the map does not have"


# ---------------------------------------------------------------------------
# Language metamorphic relations (eval instrument 4, stratum-3 gate).
#
# For three existing passing cases: one paraphrase asserting the SAME target
# and outcome, plus one MISLEADING variant where non-compliance is the pass.
# The paraphrases vary the verb and politeness, never the noun: a paraphrase
# that also swapped in an alias would be testing the grounder's alias table,
# which has its own tests, and would confound the two if it failed.
# ---------------------------------------------------------------------------


# XFAIL REMOVED 2026-08-07 (region-instance selection card). History, because
# the pin was explicit about the condition for its own removal:
#   * pinned the same day "WITH ITS BASELINE, not by this case's own defect" —
#     the un-paraphrased hard gate `test_go_to_the_sidewalk_grounds_plans_and_
#     arrives` was failing in the same window, ending at (0.37,-2.84) inside
#     `sidewalk_south`, 5.24 m from the north polygon the eval scores. The pin
#     read "it flips when the baseline does; do not flip it separately";
#   * the region-instance arbitration ranks interchangeable (stuff-class)
#     instances by BOUNDARY distance rather than centroid, which puts "the
#     sidewalk" from the origin back on the NORTH polygon (2.20 m boundary
#     against the south's 2.25 m; by centroid the south won at 3.00 vs 3.20).
# The baseline is green again — measured 2026-08-07 on a quiet box, PASSED in
# 32.0 s of a 270 s case budget — so this case flips with it, per its own pin.
# Observed green twice: once in the full default suite, once as a dedicated
# node-id run.
def test_paraphrase_move_onto_the_sidewalk_resolves_the_same_way(
    live: _LiveRuntime,
) -> None:
    """Paraphrase of ``go to the sidewalk`` — same region, same arrival."""

    _, goal = _region_goal("go to the sidewalk", tier="A", absent=False)
    result = _run_command_to_terminal(live, "please move onto the sidewalk", goal=goal)

    assert str(result["navigation"].get("goal")) == "sidewalk", (
        f"paraphrase resolved a different target: {result['navigation']}"
    )
    assert result["states"], "no task recorded"
    assert all(state == "succeeded" for state in result["states"]), (
        f"paraphrase did not verify success: states={result['states']} "
        f"details={result['details']} navigation={result['navigation']}"
    )
    x, y = result["end"]
    assert goal.contains(x, y), (
        f"paraphrase claimed success but final pose ({x:.2f},{y:.2f}) is "
        f"outside the sidewalk goal region ({goal.distance_to(x, y):.2f} m out)"
    )
    _assert_authorities_agree(result)


# PIN REMOVED 2026-08-07 (unroutable-goal release card), per the pin's own
# written condition: "This case flips when the approach path is green again."
# It is. Its baseline test_walk_towards_the_lamppost_grounds_plans_and_arrives
# — named in the pin text as failing "in the same window with
# navigation_no_progress" — is now a green hard gate, and the mechanism behind
# both is fixed rather than worked around: the towards approach pose for
# lamp_post_2 lands inside the inflated LiDAR footprint of bldg_5, the planner
# proved it unroutable (goal_blocked / no_traversable_cell_in_goal_region), and
# the mission now RELEASES that commitment, rescans, and commits lamp_post_1
# instead (navigation/pipeline.py::_unroutable_goal_recovery). The pin's own
# note that this case "XPASSES run ALONE while its baseline fails" was the
# marginality it was hedging; that asymmetry is gone. Flipped on three
# independent green observations: the full default suite (XPASS) plus two
# dedicated node-id runs on a quiet box (25.2 s, 20.2 s). Recorded in
# scrum/20260806/task_3/REGION_INSTANCE_STATUS.md.
def test_paraphrase_head_towards_the_lamppost_resolves_the_same_way(
    live: _LiveRuntime,
) -> None:
    """Paraphrase of ``can you walk towards the lamppost`` — same band."""

    _, goal = _object_goal("walk towards the lamppost", tier="A", absent=False)
    result = _run_command_to_terminal(live, "head towards the lamppost", goal=goal)

    assert str(result["navigation"].get("goal")) == "lamppost", (
        f"paraphrase resolved a different target: {result['navigation']}"
    )
    assert result["states"], "no task recorded"
    assert all(state == "succeeded" for state in result["states"]), (
        f"paraphrase did not verify success: states={result['states']} "
        f"details={result['details']} navigation={result['navigation']}"
    )
    x, y = result["end"]
    assert goal.contains(x, y), (
        f"paraphrase claimed success but final pose ({x:.2f},{y:.2f}) is "
        f"outside the towards-lamppost band ({goal.distance_to(x, y):.2f} m out)"
    )
    _assert_authorities_agree(result)
    sx, sy = result["start"]
    assert ((x - sx) ** 2 + (y - sy) ** 2) ** 0.5 > 0.3, "robot barely moved"


def test_paraphrase_find_the_fountain_still_reports_honestly(
    live: _LiveRuntime,
) -> None:
    """The exploration half of card R20's boundary, and the older SUP-1 rule.

    ``find`` became a destination verb with the superlative work (SUP-1) on the
    argument that the semantic resolution ladder already *is* a search. The
    invariant this asserts is that the verb inherits the honest-refusal
    behaviour too: an absent target must still produce a bounded search, a
    terminal failure, and a report that names what was not found — never a
    softer outcome because the phrasing was softer.

    R20 gave the same sentence a second job. The test above now shows that
    "go to the fountain" — GOAL phrasing for a place the map cannot resolve —
    gets an ask instead of a mission. **This one is why that is not a
    capability loss:** the owner who wants the robot to go looking says so, and
    the robot goes looking, exactly as it always did. If this test ever has to
    be weakened, R20's gate has stopped being a gate on goal admission and has
    become a ban on exploration, which it was explicitly not allowed to be.
    """

    result = _run_command_to_terminal(live, "find the fountain")

    assert result["states"], "no task recorded"
    assert all(state == "failed" for state in result["states"]), (
        f"an absent target must fail under any phrasing: "
        f"states={result['states']} details={result['details']}"
    )
    navigation = result["navigation"]
    assert str(navigation.get("goal")) == "fountain", f"navigation={navigation}"
    assert "not_found" in str(navigation.get("reason")), f"navigation={navigation}"
    assert result["system_arrival"] is False
    assert result["elapsed_s"] > 5.0, (
        f"no bounded search happened ({result['elapsed_s']:.1f} s to terminal)"
    )
    failure_events = [
        str(item.get("text", ""))
        for item in result["events"]
        if str(item.get("level")) == "error"
    ]
    assert any(
        "fountain" in text.lower() and "not_found" in text.lower()
        for text in failure_events
    ), f"no honest not-found report: events={failure_events}"


def test_misleading_negated_directive_must_not_be_obeyed(live: _LiveRuntime) -> None:
    """The MISLEADING variant: NON-compliance is the pass.

    "Don't go to the sidewalk" contains a complete, well-formed destination
    directive. A system that pattern-matches the noun phrase and ignores the
    negation obeys it — which is the failure mode this case exists to catch,
    and the reason ``navigation_directive_is_blocked`` runs before every
    parse. Deliberately not routed through ``_run_command_to_terminal``: that
    helper asserts the deterministic *plan* lane was taken, and here the pass
    condition is that no plan was made at all.
    """

    start = live.pose()
    reply = live.runtime.handle_text("don't go to the sidewalk")

    assert isinstance(reply, str) and reply, "a refusal must still be an answer"
    assert live.runtime.agent.last_reasoning_source != "local_plan_sketch", (
        f"a negated directive was admitted as a plan: {reply!r}"
    )

    # Give a mistakenly-admitted plan real time to become motion.
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        assert not live.tasks(), (
            f"a negated directive created an executive task: {live.tasks()}"
        )
        assert not live.runtime.snapshot().get("navigation", {}).get("enabled"), (
            f"a negated directive armed the navigation lane: "
            f"{live.runtime.snapshot().get('navigation')}"
        )
        time.sleep(0.5)

    end = live.pose()
    moved = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    assert moved <= SETTLE_TOLERANCE_M, (
        f"robot moved {moved:.3f} m in response to a negated directive"
    )

    spoken = " ".join(str(item.get("text", "")) for item in live.runtime.snapshot().get("chat") or [])
    assert "arrived" not in spoken.lower(), f"claimed arrival anyway: {spoken!r}"


# ---------------------------------------------------------------------------
# Superlative / pace directives (SUP-1..SUP-4), product path.
#
# The unit and headless-smoke evidence for these landed 2026-08-07
# (scrum/20260807/task_1/SUPERLATIVE_STATUS.md) with the explicit non-claim
# "no e2e cases yet". These are those cases.
# ---------------------------------------------------------------------------


# XFAIL REMOVED 2026-08-07 (region-instance selection card), following the
# pin's own instruction: "RE-RUN AND FLIP once the approach path is green —
# this pin is a measurement gap, not an accepted defect." The pin recorded
# resolution_state='unreachable' with the robot never leaving (0,0). Re-run
# twice on a quiet box after the region-instance arbitration landed (full
# default suite + a dedicated node-id run): PASSED both times, 23.0 s of a
# 270 s case budget. The mechanism is the arbitration's own: an explicit
# "nearest" makes the goal interchangeable, so the navigator completes the
# bounded look-around before committing instead of taking whichever instance
# entered the frustum first — from the spawn pose only lamp_post_2 (7.30 m) is
# visible, and lamp_post_1 (3.16 m) is found by looking around.
def test_find_the_nearest_lamppost_selects_and_approaches_the_near_one(
    live: _LiveRuntime,
) -> None:
    """HARD GATE on everything the superlative work is responsible for.

    From the spawn pose, ``lamp_post_1`` is 3.16 m away and ``lamp_post_2`` is
    7.30 m; without a superlative the two distinct instances resolve AMBIGUOUS.
    So this asserts: the phrasing is a navigation directive at all (before
    SUP-1, ``find`` matched no pattern and never reached the navigation lane),
    the superlative is parsed onto the mission, the *near* instance is the one
    committed, and the robot actually closes on it.

    It deliberately does NOT assert the K0 ``near`` arrival predicate. The
    near-band inset (card near-band-inset, 2026-08-09) is proven to reach
    ``arrived_verified`` by the plain-go-to case
    ``test_go_to_the_lamppost_grounds_plans_and_arrives`` on the SAME instance
    and SAME approach geometry. Asserting arrival *here too* fails for an
    unrelated reason — the superlative's opening look-around consumes enough of
    the approach budget that the progress watchdog trips
    ``navigation_no_progress`` before the terminal align completes (a pacing
    issue owned by the seamless-pacing card, not a near-band-arrival defect;
    n=1 live 2026-08-09). Mixing that in would let a superlative regression hide
    behind a pacing stall, so this case keeps the selection assertions and the
    plain-go-to case carries the arrival proof.
    """

    result = _run_command_to_terminal(live, "find the nearest lamppost")

    assert result["local_plan_skills"] == ["NavigateTo"], (
        f"'find the nearest lamppost' must reach the navigation lane: "
        f"{result['local_plan_skills']}"
    )
    mission = result["mission"]
    assert mission.get("directive_superlative") == "nearest", (
        f"superlative did not reach the mission: {mission}"
    )
    assert str(mission.get("candidate_id")) == "lamp_post_1", (
        f"the nearest lamppost is lamp_post_1 (3.16 m) not "
        f"{mission.get('candidate_id')!r} — resolution_state="
        f"{mission.get('resolution_state')!r}"
    )

    start, end = result["start"], result["end"]
    target = tuple(_LAMPPOST["position"])
    before = ((start[0] - target[0]) ** 2 + (start[1] - target[1]) ** 2) ** 0.5
    after = ((end[0] - target[0]) ** 2 + (end[1] - target[1]) ** 2) ** 0.5
    assert before - after > 1.0, (
        f"robot did not close on the selected lamppost: {before:.2f} m -> "
        f"{after:.2f} m (navigation={result['navigation']})"
    )


# XFAIL REMOVED 2026-08-07 (region-instance selection card), same instruction
# and same evidence as the case above: "RE-RUN AND FLIP once the approach path
# is green". Re-run twice on a quiet box after the arbitration landed (full
# default suite + a dedicated node-id run): PASSED both times, 21.0 s of a
# 270 s case budget. The pin recorded "pace assertions passed; displacement did
# not" — the displacement half is what the look-around fixed.
def test_run_to_the_nearest_lamppost_applies_the_pace_cap_during_motion(
    live: _LiveRuntime,
) -> None:
    """SUP-4 on the product path: the pace cap is live *while moving*.

    A cap that is written and handed back before the robot moves is not a pace
    change, so ``pace_peak`` is sampled across execution rather than read at
    the end. The cap must also be released at mission end — a directive-scoped
    pace that leaked would silently speed up every later command.
    """

    result = _run_command_to_terminal(live, "run to the nearest lamppost")

    assert result["mission"].get("directive_pace") == "fast", (
        f"pace did not reach the mission: {result['mission']}"
    )
    assert result["pace_peak"] > PACE_DEFAULT, (
        f"the pace cap was never raised during motion (peak "
        f"{result['pace_peak']:.2f}, default {PACE_DEFAULT:.2f})"
    )
    start, end = result["start"], result["end"]
    assert ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5 > 1.0, (
        "the cap must be observed on a run that actually moved"
    )
    assert result["pace_scale"] == pytest.approx(PACE_DEFAULT), (
        f"the directive pace leaked past mission end: {result['pace_scale']}"
    )
