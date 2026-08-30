"""NAV-INT-1 harness — one sim + one runtime + a mid-task interruption scheduler.

Evidence tier: ``desktop-sim`` (MuJoCo static city, driven through the live
``RobotRuntime.handle_text`` product path).

The ``LiveSession`` below is a COPY of the ``_LiveRuntime`` pattern in
``tests/test_voice_nav_e2e.py`` (sim subprocess on a unique unix socket,
``PARCEL_MEMORY_PATH`` → scratch, commissioned runtime config written to a
scratch file, ``build_runtime`` + ``runtime.start()``, poll ``tasks()`` /
``pose()``).  The test module is never imported — only the *pattern* is
reused, plus the two shared helper modules the test itself imports
(``evals.nav_instruct.*`` and ``parcel_robot.instructnav.scoring``, which are
product/eval code, not test code) and ``tests/commissioned_sim.py``, the
explicit commissioning-fixture helper (a helper module, not a test module:
duplicating its authenticator material here would be worse than importing it).

Differences from the e2e fixture, all forced by this experiment's rules:

* the sim is launched under ``systemd-run --user --scope -p MemoryMax=12G
  -p MemorySwapMax=0`` so a runaway sim cannot take the host down, still with
  ``start_new_session=True`` so teardown can signal the whole process group
  (the 2026-08-22 orphaned-sim incident);
* sockets live under a SHORT owned path (``~/.cache/parcel-0e/ni1/sN.sock``)
  because ``AF_UNIX`` paths are capped at 108 bytes;
* a background SAMPLER thread runs at ~20 Hz for the whole episode.  The
  executive's ``snapshot()`` rows carry no timestamps, so the only way to
  timestamp a suspend/replace receipt is to observe the transition.  The
  sampler is also where the pose track, the pace track, the collision flag
  and the receipt timeline come from.
"""

from __future__ import annotations

import contextlib
import math
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
for _extra in (str(REPO), str(REPO / "tests")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

from commissioned_sim import commissioned_runtime_kwargs

from evals.nav_instruct.generator import _object_goal, _region_goal
from evals.nav_instruct.scene_truth import derived_landmark_table
from parcel_robot.instructnav.scoring import (
    ARRIVAL_BOUNDARY_EPSILON_M,
    AuthorityCategory,
    GoalRegion,
    differential_arrival_verdict,
    evaluate_owner_arrival,
    object_near_goal_region,
    owner_anchored_goal_region,
)
from parcel_robot.web_panel import build_runtime

GENERIC_REFUSAL = "couldn't admit"
TERMINAL_STATES = {"succeeded", "failed", "cancelled"}
#: Same budget the e2e uses: strictly dominates the 240 s NavigateTo contract.
CASE_DEADLINE_S = 270.0
#: A second (amended) goal gets the same contract budget.
AMEND_DEADLINE_S = 270.0
SETTLE_HOLD_S = 3.0
SETTLE_TOLERANCE_M = 0.08
SAMPLE_PERIOD_S = 0.02

#: AMENDMENT N11 — the runtime otherwise resolves the realtime spend ledger to
#: the OWNER's ``recordings/spend.jsonl``. This experiment makes no hosted
#: call (``use_llm=False``), but the ledger path is pointed at our own scratch
#: file anyway so a future edit cannot write into the owner's ledger by
#: accident.
SPEND_LEDGER = Path.home() / ".cache" / "parcel-0e" / "wave20260829" / "spend.jsonl"
SPEND_LEDGER.parent.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PARCEL_REALTIME_SPEND_LEDGER", str(SPEND_LEDGER))

#: Every sim pid this PROCESS launched. The N3 orphan proof is scoped to
#: these: another NI1 run happening concurrently on this host is somebody
#: else's process and must never be reported as our leak (nor killed).
LAUNCHED_SIM_PIDS: set[int] = set()

DERIVED_LANDMARKS = derived_landmark_table()


# ---------------------------------------------------------------------------
# goal catalogue — only landmarks the e2e already reaches on the static city
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoalSpec:
    """One scorable goal: its phrasings and its K0 arrival region."""

    key: str
    kind: str  # "region" | "object_near" | "object_towards" | "owner"
    plain: str  # the from-rest phrasing
    entity_id: str | None = None

    def region(self, *, committed: str | None = None) -> GoalRegion:
        if self.kind == "region":
            return _region_goal(self.plain, tier="A", absent=False)[1]
        if self.kind == "object_towards":
            return _object_goal("walk towards the lamppost", tier="A", absent=False)[1]
        if self.kind == "object_near":
            entity = committed if committed in DERIVED_LANDMARKS else self.entity_id
            landmark = DERIVED_LANDMARKS[str(entity)]
            return object_near_goal_region(
                landmark["position"],
                float(landmark["radius_m"]),
                label=str(landmark["label"]),
                entity_id=str(entity),
            )
        raise ValueError(f"{self.key} has no static region (kind={self.kind})")

    @property
    def owner_anchored(self) -> bool:
        return self.kind == "owner"


GOALS: dict[str, GoalSpec] = {
    "sidewalk": GoalSpec("sidewalk", "region", "go to the sidewalk", "sidewalk"),
    "lamppost": GoalSpec("lamppost", "object_near", "go to the lamppost", "lamp_post_1"),
    "bench": GoalSpec("bench", "object_near", "go to the bench", "bench_1"),
    "towards_lamppost": GoalSpec(
        "towards_lamppost", "object_towards", "walk towards the lamppost", "lamp_post_1"
    ),
    "owner": GoalSpec("owner", "owner", "go to the owner", None),
    "come_here": GoalSpec("come_here", "owner", "come here", None),
}


def goal_reference_xy(
    spec: GoalSpec, *, anchor_xy: tuple[float, float] | None = None
) -> tuple[float, float]:
    """A single (x, y) to measure straight-line progress against.

    Only ever used for the interruption TRIGGER (what fraction of the way to
    goal 1 are we?), never for scoring — scoring is the K0 region.
    """

    if spec.owner_anchored:
        if anchor_xy is None:
            raise ValueError("owner-anchored goals need the observed owner pose")
        return (float(anchor_xy[0]), float(anchor_xy[1]))
    region = spec.region()
    if region.kind == "disc" and region.center is not None:
        return (float(region.center[0]), float(region.center[1]))
    if region.kind == "polygon" and region.polygon:
        xs = [float(p[0]) for p in region.polygon]
        ys = [float(p[1]) for p in region.polygon]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    landmark = DERIVED_LANDMARKS[str(spec.entity_id)]
    return (float(landmark["position"][0]), float(landmark["position"][1]))


# ---------------------------------------------------------------------------
# sampler records
# ---------------------------------------------------------------------------


@dataclass
class Sample:
    t: float
    x: float
    y: float
    yaw: float
    pace: float
    collision: bool
    nearest_obstacle_m: float | None
    owner_x: float
    owner_y: float
    tasks: tuple[tuple[str, str, int, str, str], ...]  # id, state, revision, skill, detail

    def as_dict(self) -> dict:
        return {
            "t": round(self.t, 3),
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "yaw": round(self.yaw, 4),
            "pace": round(self.pace, 3),
            "collision": self.collision,
            "nearest_obstacle_m": (
                None if self.nearest_obstacle_m is None else round(self.nearest_obstacle_m, 3)
            ),
            "tasks": [list(row) for row in self.tasks],
        }


@dataclass
class Receipt:
    """One observed executive state transition, timestamped by the sampler."""

    t: float
    task_id: str
    previous: str | None
    state: str
    plan_revision: int
    skill: str
    detail: str

    def as_dict(self) -> dict:
        return {
            "t": round(self.t, 3),
            "task_id": self.task_id,
            "previous": self.previous,
            "state": self.state,
            "plan_revision": self.plan_revision,
            "skill": self.skill,
            "detail": self.detail,
        }


@dataclass
class Utterance:
    t_issued: float
    t_returned: float
    text: str
    reply: str
    metrics: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "t_issued": round(self.t_issued, 3),
            "t_returned": round(self.t_returned, 3),
            "text": self.text,
            "reply": self.reply,
            "metrics": self.metrics,
        }


# ---------------------------------------------------------------------------
# LiveSession
# ---------------------------------------------------------------------------


class LiveSession:
    """One sim process + one runtime + a 20 Hz sampler, torn down per episode."""

    def __init__(
        self,
        workdir: Path,
        *,
        index: int,
        static_city: bool = True,
        sample_period_s: float = SAMPLE_PERIOD_S,
    ) -> None:
        workdir.mkdir(parents=True, exist_ok=True)
        self.workdir = workdir
        self.socket = workdir / f"s{index}.sock"
        with contextlib.suppress(OSError):
            self.socket.unlink()
        env = dict(os.environ, MUJOCO_GL=os.environ.get("MUJOCO_GL", "egl"))
        env["PYTHONPATH"] = str(REPO / "src")
        env.pop("TMPDIR", None)
        env["PARCEL_MEMORY_PATH"] = str(workdir / f"memory{index}.sqlite3")
        env.pop("PARCEL_MEMORY_PURPOSE", None)
        env["PARCEL_REALTIME_SPEND_LEDGER"] = str(SPEND_LEDGER)
        argv = [
            "systemd-run",
            "--user",
            "--scope",
            "--quiet",
            "-p",
            "MemoryMax=12G",
            "-p",
            "MemorySwapMax=0",
            sys.executable,
            "-m",
            "parcel_robot.sim",
            "--socket",
            str(self.socket),
        ]
        if static_city:
            argv.append("--static-city")
        # start_new_session: the sim (and the systemd-run scope wrapper) lead
        # their own process group, so teardown can signal the whole group.
        self.sim = subprocess.Popen(
            argv,
            cwd=REPO,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        # Everything below can raise with a real simulator already running:
        # the guard is what keeps a failure from leaking a sim (2026-08-22).
        LAUNCHED_SIM_PIDS.add(self.sim.pid)
        self._sampler: threading.Thread | None = None
        self._sampling = threading.Event()
        self.samples: list[Sample] = []
        self.receipts: list[Receipt] = []
        self._states: dict[str, str] = {}
        self._sample_period_s = float(sample_period_s)
        self._lock = threading.Lock()
        try:
            deadline = time.monotonic() + 40.0
            while not self.socket.exists():
                if self.sim.poll() is not None:
                    raise RuntimeError(
                        "sim died during startup:\n"
                        + (self.sim.stdout.read() if self.sim.stdout else "")[-2000:]
                    )
                if time.monotonic() > deadline:
                    raise RuntimeError("sim socket never appeared")
                time.sleep(0.1)
            os.environ["PARCEL_MEMORY_PATH"] = str(workdir / f"memory{index}.sqlite3")
            os.environ.pop("PARCEL_MEMORY_PURPOSE", None)
            runtime_config = yaml.safe_load(
                (REPO / "configs" / "robot.yaml").read_text(encoding="utf-8")
            )
            config_path = workdir / f"ni1-commissioned{index}.yaml"
            config_path.write_text(yaml.safe_dump(runtime_config), encoding="utf-8")
            self.runtime = build_runtime(
                config_path,
                self.socket,
                use_llm=False,
                runtime_kwargs=commissioned_runtime_kwargs(config_path),
            )
            self.runtime.start()
            deadline = time.monotonic() + 20.0
            while self.runtime._observation is None:
                if time.monotonic() > deadline:
                    raise RuntimeError("runtime never received an observation")
                time.sleep(0.1)
            time.sleep(1.0)  # sensor freshness + control feedback settle
        except BaseException:
            runtime = getattr(self, "runtime", None)
            if runtime is not None:
                with contextlib.suppress(RuntimeError, OSError, ValueError):
                    runtime.close()
            self._stop_sim()
            raise
        self.t0 = time.monotonic()
        self._start_sampler()

    # -- observation views (copied from the e2e fixture) --------------------

    def _live_observation(self):
        deadline = time.monotonic() + 2.0
        observation = self.runtime._observation
        while observation is None and self.sim.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
            observation = self.runtime._observation
        if observation is None:
            raise RuntimeError(
                "simulator observation disappeared: "
                f"status={self.runtime._sim_status!r} error={self.runtime._sim_error!r} "
                f"process_exit={self.sim.poll()!r}"
            )
        return observation

    def pose(self) -> tuple[float, float]:
        robot = self._live_observation().robot
        return (float(robot.x), float(robot.y))

    def heading(self) -> float:
        return float(self._live_observation().robot.yaw)

    def owner(self) -> tuple[float, float, bool]:
        owner = self._live_observation().owner
        return (float(owner.x), float(owner.y), bool(owner.visible))

    def posture(self) -> str:
        return str(self.runtime._last_posture)

    def pace_scale(self) -> float:
        return float(self.runtime._pace_cap.scale)

    def tasks(self) -> list[dict]:
        return [
            row
            for row in self.runtime.task_executive.snapshot().get("tasks", [])
            if isinstance(row, dict)
        ]

    def mission_metadata(self) -> dict:
        navigator = getattr(self.runtime.dog, "_navigator", None)
        mission = getattr(navigator, "mission", None)
        return dict(getattr(mission, "metadata", None) or {})

    def plan_steps(self) -> list[str]:
        plan = self.runtime._last_brain_plan or {}
        return [str(item) for item in (plan.get("steps") or [])]

    def follow(self) -> dict:
        return dict(self.runtime.snapshot().get("follow") or {})

    def settled(
        self, *, hold_s: float = SETTLE_HOLD_S, tolerance_m: float = SETTLE_TOLERANCE_M
    ) -> bool:
        first = self.pose()
        deadline = time.monotonic() + hold_s
        worst = 0.0
        while time.monotonic() < deadline:
            time.sleep(0.25)
            x, y = self.pose()
            worst = max(worst, math.hypot(x - first[0], y - first[1]))
        return worst <= tolerance_m

    # -- sampler ------------------------------------------------------------

    def now(self) -> float:
        return time.monotonic() - self.t0

    def _start_sampler(self) -> None:
        self._sampling.set()
        self._sampler = threading.Thread(target=self._sample_loop, daemon=True)
        self._sampler.start()

    def _sample_loop(self) -> None:
        while self._sampling.is_set():
            started = time.monotonic()
            try:
                sample = self._take_sample()
            except Exception:  # noqa: BLE001 - a dead sim must not kill the sampler
                sample = None
            if sample is not None:
                with self._lock:
                    self.samples.append(sample)
                    self._record_receipts(sample)
            delay = self._sample_period_s - (time.monotonic() - started)
            if delay > 0:
                time.sleep(delay)

    def _take_sample(self) -> Sample | None:
        observation = self.runtime._observation
        if observation is None:
            return None
        rows = self.runtime.task_executive.snapshot().get("tasks", [])
        tasks = tuple(
            (
                str(row.get("task_id")),
                str(row.get("state")),
                int(row.get("plan_revision") or 0),
                str(row.get("skill")),
                str(row.get("last_detail")),
            )
            for row in rows
            if isinstance(row, dict) and isinstance(row.get("task_id"), str)
        )
        return Sample(
            t=time.monotonic() - self.t0,
            x=float(observation.robot.x),
            y=float(observation.robot.y),
            yaw=float(observation.robot.yaw),
            pace=float(self.runtime._pace_cap.scale),
            collision=bool(getattr(observation, "collision", False)),
            nearest_obstacle_m=(
                None
                if getattr(observation, "nearest_obstacle_m", None) is None
                else float(observation.nearest_obstacle_m)
            ),
            owner_x=float(observation.owner.x),
            owner_y=float(observation.owner.y),
            tasks=tasks,
        )

    def _record_receipts(self, sample: Sample) -> None:
        """Append a Receipt for every (task_id → state) change since last tick."""

        seen: set[str] = set()
        for task_id, state, revision, skill, detail in sample.tasks:
            seen.add(task_id)
            key = f"{task_id}#{revision}"
            previous = self._states.get(key)
            if previous == state:
                continue
            self.receipts.append(
                Receipt(
                    t=sample.t,
                    task_id=task_id,
                    previous=previous,
                    state=state,
                    plan_revision=revision,
                    skill=skill,
                    detail=detail,
                )
            )
            self._states[key] = state

    def snapshot_receipts(self) -> list[Receipt]:
        with self._lock:
            return list(self.receipts)

    def snapshot_samples(self) -> list[Sample]:
        with self._lock:
            return list(self.samples)

    def task_states(self) -> dict[str, tuple[str, int]]:
        """task_id -> (state, plan_revision), read LIVE (not from the sampler).

        The sampler's last frame can be one period stale, which is enough to
        miss a task created microseconds ago -- that race made the first smoke
        episode read an empty task set immediately after ``handle_text``
        returned.  Timestamps still come from the sampler; only the *set
        membership* question is answered live.
        """

        return {
            str(row.get("task_id")): (str(row.get("state")), int(row.get("plan_revision") or 0))
            for row in self.tasks()
            if isinstance(row.get("task_id"), str)
        }

    # -- the product entry point -------------------------------------------

    def issue(self, text: str) -> Utterance:
        """``runtime.handle_text`` — the one product door this experiment uses."""

        t_issued = self.now()
        reply = self.runtime.handle_text(text)
        t_returned = self.now()
        agent = self.runtime.agent
        metrics = {
            "reasoning_source": str(agent.last_reasoning_source),
            "reasoning_error": (
                None if agent.last_reasoning_error is None else str(agent.last_reasoning_error)
            ),
            "closed_intent": str(agent.last_brain_metrics.get("closed_intent") or ""),
            "goal_amend_ok": agent.last_brain_metrics.get("goal_amend_ok"),
            "goal_amend_reason": agent.last_brain_metrics.get("goal_amend_reason"),
            "goal_amend_replan": agent.last_brain_metrics.get("goal_amend_replan"),
            "goal_amend_committed": agent.last_brain_metrics.get("goal_amend_committed"),
            "goal_amend_abandoned": agent.last_brain_metrics.get("goal_amend_abandoned"),
            "local_plan_skills": list(
                agent.last_brain_metrics.get("local_plan_skills") or []
            ),
            "refused": GENERIC_REFUSAL in reply,
            "amendment_pending": bool(getattr(self.runtime, "_amendment_pending", False)),
        }
        return Utterance(
            t_issued=t_issued, t_returned=t_returned, text=text, reply=reply, metrics=metrics
        )

    def move_owner(self, dx: float, dy: float) -> None:
        self.runtime.move_owner(dx, dy)

    # -- teardown -----------------------------------------------------------

    def _stop_sim(self) -> None:
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
        with contextlib.suppress(OSError):
            self.socket.unlink()

    def close(self) -> None:
        self._sampling.clear()
        if self._sampler is not None:
            self._sampler.join(timeout=5.0)
        with contextlib.suppress(RuntimeError, OSError, ValueError):
            self.runtime.close()
        self._stop_sim()


# ---------------------------------------------------------------------------
# waiting / scoring primitives
# ---------------------------------------------------------------------------


def wait_for_tasks(live: LiveSession, *, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if live.tasks():
            return True
        time.sleep(0.1)
    return False


def wait_terminal(
    live: LiveSession,
    task_ids: set[str],
    *,
    deadline_s: float,
    parked_grace_s: float | None = None,
) -> tuple[bool, list[str]]:
    """Drive until every named task reaches a terminal state (or the budget ends).

    An EMPTY watch set returns immediately: an interruption the runtime never
    admitted creates no task to wait on, and spinning the full contract budget
    on nothing would turn one refusal into four minutes of dead clock.
    """

    if not task_ids:
        return False, []
    deadline = time.monotonic() + deadline_s
    parked_since: float | None = None
    while time.monotonic() < deadline:
        states = live.task_states()
        watched = {tid: states[tid][0] for tid in task_ids if tid in states}
        if watched and all(state in TERMINAL_STATES for state in watched.values()):
            return True, list(watched.values())
        # MEASURED 2026-08-29 (episode ni1-01, 316 s): a goal amendment can
        # SUSPEND the running task and then fail to admit its replacement,
        # leaving the task parked in the amendment HOLD. A parked task never
        # reaches a terminal state, so waiting out the full NavigateTo contract
        # budget buys 270 s of dead clock and no extra information -- the state
        # is already stable and already the answer. When every watched task has
        # read ``suspended``, unchanging, for ``parked_grace_s`` seconds, stop
        # and report it parked (terminal=False, states=["suspended", ...]).
        if parked_grace_s is not None and watched and all(
            state == "suspended" for state in watched.values()
        ):
            if parked_since is None:
                parked_since = time.monotonic()
            elif time.monotonic() - parked_since >= parked_grace_s:
                return False, list(watched.values())
        else:
            parked_since = None
        time.sleep(0.25)
    states = live.task_states()
    return False, [states[tid][0] for tid in task_ids if tid in states]


def await_follow_hold(
    live: LiveSession, *, hold_s: float = 4.0, timeout_s: float = 90.0
) -> dict:
    """Copied from the e2e: an approach is terminal on the formation band held."""

    deadline = time.monotonic() + timeout_s
    holding_since: float | None = None
    last: dict = {}
    while time.monotonic() < deadline:
        last = live.follow()
        if str(last.get("state")) == "holding":
            if holding_since is None:
                holding_since = time.monotonic()
            elif time.monotonic() - holding_since >= hold_s:
                return last
        else:
            holding_since = None
        time.sleep(0.5)
    return last


def score_arrival(
    *,
    spec: GoalSpec,
    end_xy: tuple[float, float],
    system_arrival: bool,
    committed: str | None = None,
    anchor_xy: tuple[float, float] | None = None,
) -> dict:
    """The e2e's differential arrival authority, copied.

    Records BOTH verdicts unconditionally: ``system_arrival`` (every task
    record went to ``succeeded``) and ``scorer_arrival`` (the independent K0
    predicate on the final pose), plus their :class:`AuthorityCategory`.
    """

    if spec.owner_anchored:
        if anchor_xy is None:
            return {
                "scorer_arrival": None,
                "system_arrival": system_arrival,
                "authority_category": AuthorityCategory.UNKNOWN.value,
                "distance_to_goal_m": None,
                "epsilon_m": ARRIVAL_BOUNDARY_EPSILON_M,
            }
        region = owner_anchored_goal_region(anchor_xy)
    else:
        region = spec.region(committed=committed)
    verdict = differential_arrival_verdict(
        region, end_xy, system_arrival=system_arrival, anchor_xy=anchor_xy
    )
    return verdict.as_dict()


def owner_arrival(
    live: LiveSession, *, end_xy: tuple[float, float], follow: dict
) -> dict:
    """The e2e's OWN owner-anchored arrival gate, copied.

    ``tests/test_voice_nav_e2e.py`` scores an approach two ways and they are
    not interchangeable: ``evaluate_owner_arrival`` (band taken from the
    controller's declared formation distance, plus settle and bearing) is the
    HARD gate the suite asserts, while the frozen K0
    ``owner_anchored_goal_region`` disc is recorded softly alongside it. The
    disc's band is narrower than the live formation band, so scoring an
    approach on the disc alone reports a false arrival on a correct approach.
    Both are recorded here; the e2e's gate is the scorer authority for
    owner-anchored goals and the disc verdict is kept beside it.
    """

    owner_x, owner_y, _visible = live.owner()
    desired = float(follow.get("desired_distance_m") or 1.6)
    outcome = evaluate_owner_arrival(
        robot_xy=end_xy,
        owner_xy=(owner_x, owner_y),
        settled=live.settled(),
        robot_heading_rad=live.heading(),
        band_m=(0.4, desired + 0.6),
    )
    return {
        "success": bool(outcome.success),
        "detail": outcome.as_dict(),
        "owner_xy": [round(owner_x, 3), round(owner_y, 3)],
        "band_m": [0.4, round(desired + 0.6, 3)],
    }


def path_length(samples: list[Sample], *, t_from: float = 0.0, t_to: float | None = None) -> float:
    total = 0.0
    previous: Sample | None = None
    for sample in samples:
        if sample.t < t_from:
            continue
        if t_to is not None and sample.t > t_to:
            break
        if previous is not None:
            total += math.hypot(sample.x - previous.x, sample.y - previous.y)
        previous = sample
    return total


def track_1hz(samples: list[Sample], *, t_from: float = 0.0, t_to: float | None = None) -> list:
    """The e2e's ~1 Hz pose polyline, decimated from the 20 Hz sampler."""

    out: list[list[float]] = []
    last_t = -1e9
    for sample in samples:
        if sample.t < t_from:
            continue
        if t_to is not None and sample.t > t_to:
            break
        if sample.t - last_t >= 1.0 or not out:
            out.append([round(sample.t, 2), round(sample.x, 3), round(sample.y, 3)])
            last_t = sample.t
    return out


def collisions_in(samples: list[Sample], *, t_from: float, t_to: float) -> int:
    """Rising-edge count of the simulator's own collision flag in a window."""

    count = 0
    previous = False
    for sample in samples:
        if sample.t < t_from or sample.t > t_to:
            continue
        if sample.collision and not previous:
            count += 1
        previous = sample.collision
    return count


def min_clearance(samples: list[Sample], *, t_from: float, t_to: float) -> float | None:
    values = [
        sample.nearest_obstacle_m
        for sample in samples
        if t_from <= sample.t <= t_to and sample.nearest_obstacle_m is not None
    ]
    return min(values) if values else None


def spl(success: bool, shortest_m: float, actual_m: float) -> float:
    if not success:
        return 0.0
    if actual_m <= 0.0 or shortest_m <= 0.0:
        return 0.0
    return float(shortest_m / max(shortest_m, actual_m))


__all__ = [
    "AMEND_DEADLINE_S",
    "CASE_DEADLINE_S",
    "DERIVED_LANDMARKS",
    "GOALS",
    "TERMINAL_STATES",
    "GoalSpec",
    "LiveSession",
    "Receipt",
    "Sample",
    "Utterance",
    "await_follow_hold",
    "collisions_in",
    "evaluate_owner_arrival",
    "goal_reference_xy",
    "min_clearance",
    "owner_arrival",
    "path_length",
    "score_arrival",
    "spl",
    "track_1hz",
    "wait_for_tasks",
    "wait_terminal",
]


# ---------------------------------------------------------------------------
# the mid-task interruption scheduler
# ---------------------------------------------------------------------------


@dataclass
class TriggerOutcome:
    fired: str  # "fraction" | "time" | "terminal" | "deadline"
    t: float
    progress: float
    travelled_m: float
    reference_m: float


def wait_for_trigger(
    live: LiveSession,
    *,
    start_xy: tuple[float, float],
    reference_xy: tuple[float, float],
    fraction: float | None,
    time_s: float | None,
    task_ids: set[str],
    max_wait_s: float,
) -> TriggerOutcome:
    """Hold until the robot has covered ``fraction`` of the goal-1 straight line.

    Progress is ``|p - start| / |reference - start|`` — displacement from the
    start pose over the straight-line distance to the goal's reference point.
    It is deliberately a *displacement* ratio, not a path ratio: the trigger
    must fire at a reproducible place in the world, not after a reproducible
    amount of wandering.  ``time_s`` is either the whole trigger (fraction is
    None) or the fallback deadline when the fraction is never reached.
    """

    reference_m = math.hypot(reference_xy[0] - start_xy[0], reference_xy[1] - start_xy[1])
    began = time.monotonic()
    limit = began + max_wait_s
    while time.monotonic() < limit:
        elapsed = time.monotonic() - began
        x, y = live.pose()
        travelled = math.hypot(x - start_xy[0], y - start_xy[1])
        progress = travelled / reference_m if reference_m > 1e-6 else 0.0
        if fraction is not None and progress >= fraction:
            return TriggerOutcome("fraction", live.now(), progress, travelled, reference_m)
        if time_s is not None and elapsed >= time_s:
            return TriggerOutcome(
                "time" if fraction is None else "time_fallback",
                live.now(),
                progress,
                travelled,
                reference_m,
            )
        states = live.task_states()
        watched = {tid: states[tid][0] for tid in task_ids if tid in states}
        if watched and all(state in TERMINAL_STATES for state in watched.values()):
            return TriggerOutcome("terminal", live.now(), progress, travelled, reference_m)
        time.sleep(0.1)
    x, y = live.pose()
    travelled = math.hypot(x - start_xy[0], y - start_xy[1])
    return TriggerOutcome(
        "deadline",
        live.now(),
        travelled / reference_m if reference_m > 1e-6 else 0.0,
        travelled,
        reference_m,
    )


def first_receipt_after(
    receipts: list[Receipt],
    *,
    t_after: float,
    known: dict[str, tuple[str, int]],
) -> tuple[Receipt, str] | None:
    """The admission receipt for an interruption, with its KIND.

    Measured 2026-08-29 on the first live episode: the shipped stack answers a
    mid-task navigation amendment with ``TaskExecutive.replace()`` -- the task
    id is unchanged and the *plan revision* is bumped (r1 -> r2), the suspended
    state existing only inside the transaction and never observable from
    outside.  So "suspend/replace receipt" has three observable shapes and all
    three are accepted here:

    * ``replace`` -- a known task appears at a HIGHER plan revision;
    * ``suspend`` -- a known task at its known revision goes suspended/cancelled;
    * ``new_task`` -- a task id that did not exist at the utterance appears.

    ``known`` is the live ``task_states()`` map read immediately before the
    interrupting utterance.
    """

    for receipt in receipts:
        if receipt.t < t_after:
            continue
        if receipt.task_id not in known:
            return receipt, "new_task"
        _state, revision = known[receipt.task_id]
        if receipt.plan_revision > revision:
            return receipt, "replace"
        if receipt.plan_revision == revision and receipt.state in {"suspended", "cancelled"}:
            return receipt, "suspend"
    return None


def goal_task_ids(live: LiveSession, *, known: dict[str, tuple[str, int]]) -> set[str]:
    """The task ids carrying work admitted AFTER ``known`` was sampled."""

    out: set[str] = set()
    for task_id, (_state, revision) in live.task_states().items():
        if task_id not in known or revision > known[task_id][1]:
            out.add(task_id)
    return out
