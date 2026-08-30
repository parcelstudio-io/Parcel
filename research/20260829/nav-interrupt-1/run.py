"""NAV-INT-1 runner — from-rest controls, the 40-episode interrupt tier, the
from-rest sequence controls, and the H-NI1c classifier bench.

    .parcel/bin/python research/20260829/nav-interrupt-1/run.py --all --seed 20260829

Writes ``results.json`` plus per-stage JSONL (one line per run, carrying the
1 Hz track and the full receipt timeline) for the verifier.

Host rules honoured here: ``TMPDIR`` unset for the unix socket; one sim at a
time, on a unique short socket under ``~/.cache/parcel-0e/ni1/``, launched
under ``systemd-run --user --scope -p MemoryMax=12G -p MemorySwapMax=0``;
``PARCEL_MEMORY_PATH`` → scratch and ``PARCEL_MEMORY_PURPOSE`` never set to
owner; the owner's ``:8765`` / ``/tmp/parcel_sim.sock`` never touched.

AMENDMENT N3 (binding): teardown is trapped on every exit path — normal
return, exception, SIGINT/SIGTERM — and the run ends with a ``pgrep`` proof
that no sim of ours survived. The proof is recorded in ``results.json``.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import math
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import harness as H
import queue_policy as QP

WORKDIR = Path.home() / ".cache" / "parcel-0e" / "ni1"
TIER_PATH = HERE / "interrupt_tier_v1.json"
GOLD_PATH = HERE / "gold.json"

#: The e2e's own case budget (270 s) strictly dominates the 240 s NavigateTo
#: contract, so the system's terminal verdict is observed rather than raced.
LEG_DEADLINE_S = H.CASE_DEADLINE_S
#: How long the interruption scheduler will wait for its trigger before it
#: gives up and fires anyway.
TRIGGER_MAX_WAIT_S = 90.0
#: The window DESIGN.md scores "no collision / no false arrival" over: from
#: just before the interrupting utterance to a few seconds past the handover.
SWITCH_WINDOW_LEAD_S = 2.0  # amendment N6: cue - 2 s
#: How long a task must read ``suspended``, unchanging, before the harness
#: calls it PARKED and stops waiting for a terminal state it will never reach.
PARKED_GRACE_S = 20.0
SWITCH_WINDOW_TAIL_S = 10.0

_OPEN_SESSIONS: list[H.LiveSession] = []


# ---------------------------------------------------------------------------
# AMENDMENT N3 — teardown on every exit path
# ---------------------------------------------------------------------------


def _close_all() -> None:
    while _OPEN_SESSIONS:
        session = _OPEN_SESSIONS.pop()
        try:
            session.close()
        except Exception as error:  # noqa: BLE001 - teardown must never raise
            print(f"[teardown] session close failed: {error}", file=sys.stderr)


def _signal_teardown(signum, _frame) -> None:
    print(f"[teardown] signal {signum}; closing sims", file=sys.stderr)
    _close_all()
    raise SystemExit(128 + int(signum))


atexit.register(_close_all)
for _sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(_sig, _signal_teardown)


def orphan_check() -> dict:
    """AMENDMENT N3 — prove no sim OF OURS survived.

    Scoped to the pids this process launched. A concurrent NI1 run belongs to
    another process; it is reported separately and never killed.
    """

    proc = subprocess.run(
        ["pgrep", "-af", r"parcel_robot\.sim --socket .*ni1"],
        capture_output=True,
        text=True,
        check=False,
    )
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    ours: list[str] = []
    others: list[str] = []
    for line in lines:
        head = line.split(None, 1)[0]
        try:
            pid = int(head)
        except ValueError:
            others.append(line)
            continue
        (ours if pid in H.LAUNCHED_SIM_PIDS else others).append(line)
    return {
        "pattern": r"parcel_robot\.sim --socket .*ni1",
        "launched_by_this_process": sorted(H.LAUNCHED_SIM_PIDS),
        "survivors_ours": ours,
        "survivors_other_processes": others,
        "clean": not ours,
    }


class Sessions:
    """One sim at a time, each on its own socket index, always closed."""

    def __init__(self) -> None:
        self._index = 0

    def open(self) -> H.LiveSession:
        _close_all()
        self._index += 1
        session = H.LiveSession(WORKDIR, index=self._index)
        _OPEN_SESSIONS.append(session)
        return session

    @staticmethod
    def close(session: H.LiveSession) -> None:
        if session in _OPEN_SESSIONS:
            _OPEN_SESSIONS.remove(session)
        session.close()


# ---------------------------------------------------------------------------
# one navigation leg
# ---------------------------------------------------------------------------


@dataclass
class Leg:
    label: str
    text: str
    goal_key: str
    t_issued: float
    t_terminal: float | None
    reply: str
    metrics: dict
    states: list[str]
    details: list[str]
    admitted_work: bool
    system_arrival: bool
    scorer_arrival: bool | None
    authority_category: str
    distance_to_goal_m: float | None
    path_m: float
    shortest_m: float
    spl: float
    success: bool
    deadline_hit: bool
    start: list[float]
    end: list[float]
    committed: str | None
    follow: dict
    owner_gate: dict

    def as_dict(self) -> dict:
        payload = dict(self.__dict__)
        for key in ("t_issued", "t_terminal", "path_m", "shortest_m", "spl"):
            value = payload.get(key)
            if isinstance(value, float):
                payload[key] = round(value, 3)
        if isinstance(payload.get("distance_to_goal_m"), float):
            payload["distance_to_goal_m"] = round(payload["distance_to_goal_m"], 3)
        return payload


def _shortest_to_goal(spec: H.GoalSpec, start: tuple[float, float], anchor) -> float:
    """Straight-line distance from the start pose to the goal REGION.

    The obstacle-free lower bound on path length — the SPL denominator. The
    static city has no obstacle between the commissioning pose and any of
    these landmarks, so it is a fair bound here and is labelled as such.
    """

    try:
        if spec.owner_anchored:
            if anchor is None:
                return 0.0
            region = H.owner_anchored_goal_region(anchor)
            return float(region.distance_to(start[0], start[1], anchor_xy=anchor))
        region = spec.region()
        return float(region.distance_to(start[0], start[1]))
    except Exception:  # noqa: BLE001 - an unscorable goal contributes 0, never a crash
        return 0.0


def finish_leg(
    live: H.LiveSession,
    *,
    label: str,
    text: str,
    goal_key: str,
    ids: set[str],
    t_issued: float,
    start: tuple[float, float],
    utterance: H.Utterance | None,
    deadline_s: float = LEG_DEADLINE_S,
) -> Leg:
    """Drive an already-issued command to a terminal receipt and score it."""

    spec = H.GOALS[goal_key]
    admitted_work = bool(ids)
    terminal, states = H.wait_terminal(
        live, ids, deadline_s=deadline_s, parked_grace_s=PARKED_GRACE_S
    )
    details = [
        str(row.get("last_detail"))
        for row in live.tasks()
        if str(row.get("task_id")) in ids
    ]
    t_terminal = live.now()
    follow: dict = {}
    if spec.owner_anchored and admitted_work:
        # Copied from the e2e: a persistent FollowFormation's task record goes
        # terminal about a second after dispatch, so the honest termination
        # condition for an approach is the formation band HELD.
        follow = H.await_follow_hold(live, timeout_s=90.0)
        t_terminal = live.now()
    end = live.pose()
    owner_x, owner_y, _visible = live.owner()
    anchor = (owner_x, owner_y) if spec.owner_anchored else None
    mission = live.mission_metadata()
    committed = str(mission.get("candidate_id")) if mission.get("candidate_id") else None
    system_arrival = (
        admitted_work and bool(states) and all(state == "succeeded" for state in states)
    )
    if spec.owner_anchored:
        system_arrival = system_arrival and str(follow.get("state")) == "holding"
    verdict = H.score_arrival(
        spec=spec,
        end_xy=end,
        system_arrival=system_arrival,
        committed=committed,
        anchor_xy=anchor,
    )
    owner_gate: dict = {}
    if spec.owner_anchored:
        # The e2e's own owner gate is the scorer authority for an approach;
        # the frozen K0 disc verdict stays recorded beside it.
        owner_gate = H.owner_arrival(live, end_xy=end, follow=follow)
        verdict = {
            "k0_disc_verdict": dict(verdict),
            "owner_gate": owner_gate,
            "scorer_arrival": owner_gate["success"],
            "system_arrival": system_arrival,
            "authority_category": (
                "agreement"
                if bool(owner_gate["success"]) == bool(system_arrival)
                else ("false_arrival" if system_arrival else "authority_disagreement")
            ),
            "distance_to_goal_m": verdict.get("distance_to_goal_m"),
        }
    samples = live.snapshot_samples()
    path_m = H.path_length(samples, t_from=t_issued, t_to=t_terminal)
    shortest_m = _shortest_to_goal(spec, start, anchor)
    success = bool(system_arrival) and bool(verdict.get("scorer_arrival"))
    return Leg(
        label=label,
        text=text,
        goal_key=goal_key,
        t_issued=t_issued,
        t_terminal=t_terminal,
        reply="" if utterance is None else utterance.reply,
        metrics={} if utterance is None else utterance.metrics,
        states=list(states),
        details=details,
        admitted_work=admitted_work,
        system_arrival=bool(system_arrival),
        scorer_arrival=verdict.get("scorer_arrival"),
        authority_category=str(verdict.get("authority_category")),
        distance_to_goal_m=verdict.get("distance_to_goal_m"),
        path_m=path_m,
        shortest_m=shortest_m,
        spl=H.spl(success, shortest_m, path_m),
        success=success,
        deadline_hit=not terminal,
        start=[round(start[0], 3), round(start[1], 3)],
        end=[round(end[0], 3), round(end[1], 3)],
        committed=committed,
        follow=dict(follow),
        owner_gate=owner_gate,
    )


def run_leg(
    live: H.LiveSession,
    *,
    label: str,
    text: str,
    goal_key: str,
    deadline_s: float = LEG_DEADLINE_S,
    known: dict | None = None,
) -> Leg:
    """Issue one command and drive it to a terminal executive receipt."""

    known = live.task_states() if known is None else known
    start = live.pose()
    utterance = live.issue(text)
    H.wait_for_tasks(live, timeout_s=5.0)
    ids = H.goal_task_ids(live, known=known)
    deadline = time.monotonic() + 3.0
    while not ids and time.monotonic() < deadline:
        time.sleep(0.1)
        ids = H.goal_task_ids(live, known=known)
    return finish_leg(
        live,
        label=label,
        text=text,
        goal_key=goal_key,
        ids=ids,
        t_issued=utterance.t_issued,
        start=start,
        utterance=utterance,
        deadline_s=deadline_s,
    )


def stage_owner(live: H.LiveSession) -> None:
    """Walk the owner up the block, exactly as the e2e does before approaches.

    Scene setup, not behaviour seeding: from the commissioning pose the robot
    already stands 2.06 m away and the formation distance is 1.6 m, so an
    approach to an unmoved owner is scored vacuously.
    """

    for _ in range(3):
        live.move_owner(1.0, 0.0)
        time.sleep(1.0)
    time.sleep(2.0)


# ---------------------------------------------------------------------------
# stage: from-rest controls
# ---------------------------------------------------------------------------


def stage_controls(
    tier: dict, jsonl: Path, *, limit: int | None = None, only: str | None = None
) -> list[dict]:
    sessions = Sessions()
    rows: list[dict] = []
    jobs = [
        (control, rep)
        for control in tier["controls"]
        if only is None or control["goal_key"] == only
        for rep in range(int(control.get("reps", 1)))
    ]
    if limit is not None:
        jobs = jobs[:limit]
    with jsonl.open("a", encoding="utf-8") as handle:
        for control, rep in jobs:
            key = control["goal_key"]
            started = time.time()
            live = sessions.open()
            try:
                if H.GOALS[key].owner_anchored:
                    stage_owner(live)
                leg = run_leg(live, label="control", text=control["text"], goal_key=key)
                row = {
                    "kind": "control",
                    "control_id": control["control_id"],
                    "rep": rep,
                    "goal_key": key,
                    "wall_s": round(time.time() - started, 1),
                    "leg": leg.as_dict(),
                    "track": H.track_1hz(live.snapshot_samples(), t_from=leg.t_issued),
                    "receipts": [r.as_dict() for r in live.snapshot_receipts()],
                    "collisions": H.collisions_in(
                        live.snapshot_samples(), t_from=leg.t_issued, t_to=live.now()
                    ),
                    "min_clearance_m": H.min_clearance(
                        live.snapshot_samples(), t_from=leg.t_issued, t_to=live.now()
                    ),
                }
            except Exception as error:  # noqa: BLE001 - a bad control is a row, not a crash
                row = {
                    "kind": "control",
                    "control_id": control["control_id"],
                    "rep": rep,
                    "goal_key": key,
                    "wall_s": round(time.time() - started, 1),
                    "error": f"{type(error).__name__}: {error}",
                }
            finally:
                sessions.close(live)
            rows.append(row)
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            if "error" in row:
                print(f"[control] {control['control_id']}#{rep} ERROR {row['error']}", flush=True)
                continue
            print(
                f"[control] {control['control_id']}#{rep} "
                f"sys={row['leg']['system_arrival']} scorer={row['leg']['scorer_arrival']} "
                f"cat={row['leg']['authority_category']} dtg={row['leg']['distance_to_goal_m']} "
                f"{row['wall_s']}s",
                flush=True,
            )
    return rows


# ---------------------------------------------------------------------------
# stage: from-rest sequence controls (the H-NI1b path-length reference)
# ---------------------------------------------------------------------------


def stage_sequence(tier: dict, jsonl: Path, *, limit: int | None = None) -> list[dict]:
    sessions = Sessions()
    rows: list[dict] = []
    jobs = tier["sequence_controls"][: limit if limit is not None else None]
    with jsonl.open("a", encoding="utf-8") as handle:
        for control in jobs:
            started = time.time()
            live = sessions.open()
            try:
                if H.GOALS[control["first"]["key"]].owner_anchored or H.GOALS[
                    control["second"]["key"]
                ].owner_anchored:
                    stage_owner(live)
                first = run_leg(
                    live,
                    label="seq_first",
                    text=control["first"]["text"],
                    goal_key=control["first"]["key"],
                )
                second = run_leg(
                    live,
                    label="seq_second",
                    text=control["second"]["text"],
                    goal_key=control["second"]["key"],
                )
                samples = live.snapshot_samples()
                total = H.path_length(samples, t_from=first.t_issued, t_to=second.t_terminal)
                row = {
                    "kind": "sequence_control",
                    "control_id": control["control_id"],
                    "wall_s": round(time.time() - started, 1),
                    "first": first.as_dict(),
                    "second": second.as_dict(),
                    "total_path_m": round(total, 3),
                    "both_reached": bool(
                        first.system_arrival
                        and first.scorer_arrival
                        and second.system_arrival
                        and second.scorer_arrival
                    ),
                    "track": H.track_1hz(samples, t_from=first.t_issued),
                    "receipts": [r.as_dict() for r in live.snapshot_receipts()],
                }
            except Exception as error:  # noqa: BLE001 - a bad sequence control is a row
                row = {
                    "kind": "sequence_control",
                    "control_id": control["control_id"],
                    "wall_s": round(time.time() - started, 1),
                    "error": f"{type(error).__name__}: {error}",
                }
            finally:
                sessions.close(live)
            rows.append(row)
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            if "error" in row:
                print(f"[sequence] {control['control_id']} ERROR {row['error']}", flush=True)
                continue
            print(
                f"[sequence] {control['control_id']} both={row['both_reached']} "
                f"path={row['total_path_m']}m {row['wall_s']}s",
                flush=True,
            )
    return rows


# ---------------------------------------------------------------------------
# stage: the interrupt tier
# ---------------------------------------------------------------------------


def run_interrupt_episode(live: H.LiveSession, episode: dict) -> dict:
    """One mid-task interruption, with the plan-queue policy running on top.

    Three flows, chosen by the episode's phrasing family (amendment N5):

    * ``amend_cue`` / ``explicit_directive`` — the second utterance is issued
      mid-task through ``handle_text``. These are the H-NI1a admission rows.
    * ``queue`` — AMENDMENT N9: the classifier runs FIRST and the utterance is
      HELD in the harness; it never reaches ``handle_text`` mid-task. Goal 1
      runs to its own terminal receipt, and only then is the held text issued
      as a fresh task (a re-issue, N1). These rows carry no admission latency
      by construction — that is the policy, not a measurement failure.
    * ``hold`` — a bare amend cue ("actually") with no replacement goal: the
      C8 HOLD is engaged and nothing new is named. The row measures whether
      the hold is real (task suspended, body stopped) and bounded.
    """

    g1 = episode["goal_1"]
    g2 = episode["goal_2"]
    family_class = str(g2.get("family_class") or "amend_cue")
    has_goal_2 = bool(g2.get("has_goal", True))
    spec1 = H.GOALS[g1["key"]]
    spec2 = H.GOALS[g2["key"]] if has_goal_2 else None
    if spec1.owner_anchored or (spec2 is not None and spec2.owner_anchored):
        stage_owner(live)

    queue = QP.PlanQueue()
    known0 = live.task_states()
    start = live.pose()
    reference = H.goal_reference_xy(spec1)

    utterance1 = live.issue(g1["text"])
    H.wait_for_tasks(live, timeout_s=5.0)
    ids1 = H.goal_task_ids(live, known=known0)
    queue.start_goal(g1["key"], g1["text"], t=utterance1.t_issued)

    trigger = H.wait_for_trigger(
        live,
        start_xy=start,
        reference_xy=reference,
        fraction=episode["trigger"]["fraction"],
        time_s=episode["trigger"]["time_s"],
        task_ids=ids1,
        max_wait_s=TRIGGER_MAX_WAIT_S,
    )

    known_at_interrupt = live.task_states()
    pose_at_interrupt = live.pose()
    decision = QP.classify(
        g2["text"], current_goal=g1["place"], progress=trigger.progress
    )

    held = family_class == "queue"
    admission: dict = {
        # AMENDMENT N2 — the runtime adapter reports every in-progress poll as
        # a checkpoint, so this is admission-at-any-poll, never admission at a
        # controller-certified safe point.
        "label": "admission-at-any-poll",
        "family_class": family_class,
        "held_pre_runtime": held,
    }
    utterance2: H.Utterance | None = None
    receipt_row = None
    receipt_kind = None
    window_anchor = trigger.t

    if held:
        # AMENDMENT N9 — never reaches handle_text mid-task.
        queue.hold_for_later(
            decision, goal_key=g2["key"], text=g2["text"], t=trigger.t
        )
        admission.update(
            {
                "admitted": None,
                "receipt_kind": None,
                "receipt": None,
                "latency_ms": None,
                "inband_handle_text_ms": None,
                "classifier_label": decision.label,
                "note": "queue family: held in the harness, never issued mid-task",
            }
        )
        primary = finish_leg(
            live,
            label="goal_1_uninterrupted",
            text=g1["text"],
            goal_key=g1["key"],
            ids=ids1,
            t_issued=utterance1.t_issued,
            start=start,
            utterance=utterance1,
        )
        displaced = False
    else:
        utterance2 = live.issue(g2["text"])
        window_anchor = utterance2.t_issued
        receipt = H.first_receipt_after(
            live.snapshot_receipts(),
            t_after=utterance2.t_issued,
            known=known_at_interrupt,
        )
        poll_deadline = time.monotonic() + 1.5
        while receipt is None and time.monotonic() < poll_deadline:
            time.sleep(0.02)
            receipt = H.first_receipt_after(
                live.snapshot_receipts(),
                t_after=utterance2.t_issued,
                known=known_at_interrupt,
            )
        latency_ms = None
        if receipt is not None:
            record, receipt_kind = receipt
            receipt_row = record.as_dict()
            latency_ms = round((record.t - utterance2.t_issued) * 1000.0, 1)
        admission.update(
            {
                "admitted": bool(receipt_row) and not utterance2.metrics.get("refused"),
                "receipt_kind": receipt_kind,
                "receipt": receipt_row,
                "latency_ms": latency_ms,
                "inband_handle_text_ms": round(
                    (utterance2.t_returned - utterance2.t_issued) * 1000.0, 1
                ),
                "classifier_label": decision.label,
                "closed_intent": utterance2.metrics.get("closed_intent"),
                "goal_amend_ok": utterance2.metrics.get("goal_amend_ok"),
                "goal_amend_reason": utterance2.metrics.get("goal_amend_reason"),
                "goal_amend_replan": utterance2.metrics.get("goal_amend_replan"),
                "goal_amend_committed": utterance2.metrics.get("goal_amend_committed"),
                "refused": utterance2.metrics.get("refused"),
                "reasoning_source": utterance2.metrics.get("reasoning_source"),
                "local_plan_skills": utterance2.metrics.get("local_plan_skills"),
            }
        )
        displaced = receipt_kind in {"replace", "suspend", "new_task"}
        queue.on_interrupt(
            decision,
            goal_key=g2["key"] if has_goal_2 else g1["key"],
            text=g2["text"],
            t=trigger.t,
            displaced=bool(displaced) and has_goal_2,
        )
        if has_goal_2:
            ids2 = H.goal_task_ids(live, known=known_at_interrupt)
            poll_deadline = time.monotonic() + 3.0
            while not ids2 and time.monotonic() < poll_deadline:
                time.sleep(0.1)
                ids2 = H.goal_task_ids(live, known=known_at_interrupt)
            # A never-admitted interruption creates no goal-2 task: the ORIGINAL
            # goal is still running, so that is what is driven to terminal and
            # the row is marked not-admitted rather than being scored against a
            # region the robot was never sent to.
            primary = finish_leg(
                live,
                label="amended_goal" if ids2 else "goal_1_continued",
                text=g2["text"],
                goal_key=(g2["key"] if ids2 else g1["key"]),
                ids=ids2 or ids1,
                t_issued=utterance2.t_issued,
                start=pose_at_interrupt,
                utterance=utterance2,
            )
        else:
            # HOLD row: observe the hold for a bounded window, then measure it.
            primary = _observe_hold(live, ids1, t_from=utterance2.t_issued)
            if displaced:
                queue.entries.append(
                    QP.QueueEntry(g1["key"], g1["text"], trigger.t, "displaced")
                )

    # --- the switch window (amendment N6: cue - 2 s .. cue + 10 s) ---------
    samples = live.snapshot_samples()
    window_from = max(0.0, window_anchor - SWITCH_WINDOW_LEAD_S)
    window_to = window_anchor + SWITCH_WINDOW_TAIL_S
    switch_min_clearance = H.min_clearance(samples, t_from=window_from, t_to=window_to)
    switch = {
        "from_s": round(window_from, 3),
        "to_s": round(window_to, 3),
        "sim_collision_flag_events": H.collisions_in(
            samples, t_from=window_from, t_to=window_to
        ),
        "min_clearance_m": switch_min_clearance,
        "collision_by_clearance": bool(
            switch_min_clearance is not None and switch_min_clearance <= 0.0
        ),
        "false_arrival": _false_arrival_in_window(
            live, spec1, samples, ids1, t_from=window_from, t_to=window_to
        ),
        "amended_goal_authority_category": primary.authority_category,
        "samples_in_window": sum(1 for s in samples if window_from <= s.t <= window_to),
    }

    # --- the plan-queue policy: RE-ISSUE (amendment N1), never a resume ----
    reissue = queue.next_reissue(
        t=primary.t_terminal or live.now(),
        terminal_state=",".join(primary.states) or "unknown",
    )
    leg3 = None
    if reissue is not None:
        leg3 = run_leg(
            live,
            label="reissue",
            text=reissue.text,
            goal_key=reissue.goal_key,
            known=live.task_states(),
        )

    samples = live.snapshot_samples()
    total_path = H.path_length(
        samples,
        t_from=utterance1.t_issued,
        t_to=(leg3.t_terminal if leg3 is not None else primary.t_terminal),
    )
    # AMENDMENT N8 — the oracle path reference: start -> interruption pose ->
    # goal 2 -> goal 1, straight-line, from the ACTUAL interruption pose.
    oracle = _oracle_path(
        start=start,
        interrupt_xy=pose_at_interrupt,
        spec_second=spec2 if has_goal_2 else None,
        spec_back=spec1,
        second_end=primary.end if has_goal_2 else None,
    )

    return {
        "kind": "interrupt_episode",
        "episode_id": episode["episode_id"],
        "family_class": family_class,
        "goal_1": g1,
        "goal_2": g2,
        "trigger_spec": episode["trigger"],
        "trigger": {
            "fired": trigger.fired,
            "t": round(trigger.t, 3),
            "progress": round(trigger.progress, 3),
            "travelled_m": round(trigger.travelled_m, 3),
            "reference_m": round(trigger.reference_m, 3),
            "pose": [round(pose_at_interrupt[0], 3), round(pose_at_interrupt[1], 3)],
        },
        "utterance_1": utterance1.as_dict(),
        "utterance_2": None if utterance2 is None else utterance2.as_dict(),
        "steering_decision": decision.as_dict(),
        "admission": admission,
        "amended_goal": primary.as_dict(),
        "switch_window": switch,
        "reissue": None if leg3 is None else leg3.as_dict(),
        "queue": queue.as_dict(),
        "total_path_m": round(total_path, 3),
        "oracle_path_m": round(oracle, 3),
        "path_ratio_oracle": (
            round(total_path / oracle, 4) if oracle > 1e-6 else None
        ),
        "track": H.track_1hz(samples, t_from=utterance1.t_issued),
        "receipts": [r.as_dict() for r in live.snapshot_receipts()],
        "collisions_total": H.collisions_in(samples, t_from=0.0, t_to=live.now()),
        "min_clearance_total_m": H.min_clearance(samples, t_from=0.0, t_to=live.now()),
    }


#: How long a bare-cue HOLD is observed before the queue policy moves on.
HOLD_OBSERVE_S = 20.0


def _observe_hold(live: H.LiveSession, ids1: set[str], *, t_from: float) -> Leg:
    """AMENDMENT N5's HOLD row: is the C8 hold real, and is the body stopped?"""

    deadline = time.monotonic() + HOLD_OBSERVE_S
    while time.monotonic() < deadline:
        time.sleep(0.5)
    states = live.task_states()
    watched = {tid: states[tid][0] for tid in ids1 if tid in states}
    details = [
        str(row.get("last_detail"))
        for row in live.tasks()
        if str(row.get("task_id")) in ids1
    ]
    samples = live.snapshot_samples()
    end = live.pose()
    moved = H.path_length(samples, t_from=t_from, t_to=live.now())
    return Leg(
        label="hold",
        text="(hold: amend cue with no replacement goal)",
        goal_key="hold",
        t_issued=t_from,
        t_terminal=live.now(),
        reply="",
        metrics={"hold_path_m": round(moved, 3), "hold_observe_s": HOLD_OBSERVE_S},
        states=list(watched.values()),
        details=details,
        admitted_work=True,
        system_arrival=False,
        scorer_arrival=None,
        authority_category="unknown",
        distance_to_goal_m=None,
        path_m=moved,
        shortest_m=0.0,
        spl=0.0,
        success=False,
        deadline_hit=False,
        start=[0.0, 0.0],
        end=[round(end[0], 3), round(end[1], 3)],
        committed=None,
        follow={},
        owner_gate={},
    )


def _oracle_path(
    *,
    start: tuple[float, float],
    interrupt_xy: tuple[float, float],
    spec_second: H.GoalSpec | None,
    spec_back: H.GoalSpec,
    second_end: list[float] | None,
) -> float:
    """AMENDMENT N8 — start -> interruption pose -> goal 2 -> goal 1, straight-line.

    Obstacle-free lower bound on the two-goal detour, measured from the pose
    the robot was ACTUALLY at when the interruption landed, so the reference
    is stratified by trigger fraction for free.
    """

    # ``_shortest_to_goal`` already answers 0.0 for a goal it cannot score, so
    # an unscorable leg shortens the reference rather than raising here.
    total = math.dist(start, interrupt_xy)
    here = interrupt_xy
    if spec_second is not None:
        total += _shortest_to_goal(spec_second, here, None)
        if second_end is not None:
            here = (float(second_end[0]), float(second_end[1]))
    total += _shortest_to_goal(spec_back, here, None)
    return total


def _false_arrival_in_window(
    live: H.LiveSession,
    spec1: H.GoalSpec,
    samples: list[H.Sample],
    ids1: set[str],
    *,
    t_from: float,
    t_to: float,
) -> dict:
    """Did the system claim GOAL 1 succeeded inside the switch window, while
    the independent K0 predicate on the pose at that moment said no?"""

    claim = None
    for receipt in live.snapshot_receipts():
        if receipt.t < t_from or receipt.t > t_to:
            continue
        if receipt.task_id in ids1 and receipt.state == "succeeded":
            claim = receipt
            break
    if claim is None:
        return {"claimed": False, "false_arrival": False}
    pose = next(
        ((s.x, s.y) for s in samples if s.t >= claim.t),
        (samples[-1].x, samples[-1].y) if samples else (math.nan, math.nan),
    )
    try:
        region = spec1.region()
        inside = bool(region.contains(pose[0], pose[1]))
        distance = float(region.distance_to(pose[0], pose[1]))
    except Exception:  # noqa: BLE001 - a goal we cannot score cannot convict
        # Fail toward "inside": a false-arrival accusation needs a predicate
        # that actually ran. Not being able to score goal 1 is not evidence
        # against the system.
        inside, distance = True, 0.0
    return {
        "claimed": True,
        "false_arrival": not inside,
        "pose": [round(pose[0], 3), round(pose[1], 3)],
        "distance_to_goal_1_m": round(distance, 3),
        "receipt": claim.as_dict(),
    }


def stage_tier(
    tier: dict, jsonl: Path, *, limit: int | None = None, offset: int = 0
) -> list[dict]:
    sessions = Sessions()
    rows: list[dict] = []
    episodes = tier["episodes"][offset:]
    if limit is not None:
        episodes = episodes[:limit]
    with jsonl.open("a", encoding="utf-8") as handle:
        for episode in episodes:
            started = time.time()
            live = sessions.open()
            try:
                row = run_interrupt_episode(live, episode)
            except Exception as error:  # noqa: BLE001 - a bad episode is a row, not a crash
                row = {
                    "kind": "interrupt_episode",
                    "episode_id": episode["episode_id"],
                    "error": f"{type(error).__name__}: {error}",
                }
            finally:
                sessions.close(live)
            row["wall_s"] = round(time.time() - started, 1)
            rows.append(row)
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            if "error" in row:
                print(f"[tier] {row['episode_id']} ERROR {row['error']}", flush=True)
                continue
            print(
                f"[tier] {row['episode_id']} fam={row['family_class']} "
                f"trig={row['trigger']['fired']}@{row['trigger']['progress']} "
                f"admit={row['admission']['admitted']}/{row['admission']['receipt_kind']} "
                f"lat={row['admission']['latency_ms']}ms "
                f"primary={row['amended_goal']['label']}:{row['amended_goal']['success']} "
                f"reissue={'-' if row['reissue'] is None else row['reissue']['system_arrival']}"
                f"/{'-' if row['reissue'] is None else row['reissue']['scorer_arrival']} "
                f"coll={row['switch_window']['sim_collision_flag_events']} "
                f"clr={row['switch_window']['min_clearance_m']} {row['wall_s']}s",
                flush=True,
            )
    return rows


# ---------------------------------------------------------------------------
# stage: sample episode (one, printed)
# ---------------------------------------------------------------------------


def render_sample(row: dict, receipts: list[dict], out: Path) -> str:
    """Render one episode as the human-readable receipt timeline."""

    lines = [
        "NAV-INT-1 — sample episode (desktop-sim, MuJoCo static city, live runtime)",
        f"episode      : {row['episode_id']}",
        f"goal 1       : {row['goal_1']['text']!r}",
        (
            f"goal 2       : {row['goal_2']['text']!r}  "
            f"(family {row['goal_2']['family']}, class {row['family_class']})"
        ),
        (
            f"trigger      : {row['trigger_spec']} -> fired {row['trigger']['fired']} "
            f"at progress {row['trigger']['progress']} "
            f"({row['trigger']['travelled_m']} m of {row['trigger']['reference_m']} m), "
            f"t={row['trigger']['t']} s, pose {row['trigger']['pose']}"
        ),
        (
            f"steering     : {row['steering_decision']['label']} "
            f"({row['steering_decision']['reason']})"
        ),
        "",
        "admission (label: admission-at-any-poll — amendment N2)",
        f"  admitted            : {row['admission']['admitted']}",
        f"  receipt kind        : {row['admission']['receipt_kind']}",
        (
            f"  latency             : {row['admission']['latency_ms']} ms "
            f"(in-band handle_text {row['admission']['inband_handle_text_ms']} ms)"
        ),
        f"  closed_intent       : {row['admission'].get('closed_intent')!r}",
        f"  goal_amend_ok       : {row['admission'].get('goal_amend_ok')}",
        f"  goal_amend_replan   : {row['admission'].get('goal_amend_replan')}",
        f"  goal_amend_committed: {row['admission'].get('goal_amend_committed')}",
        f"  held pre-runtime    : {row['admission'].get('held_pre_runtime')}",
        f"  reply               : {(row['utterance_2'] or {}).get('reply')!r}",
        "",
        (
            f"leg after the interruption -- {row['amended_goal']['label']} "
            f"(goal {row['amended_goal']['goal_key']}; differential arrival "
            f"authority, copied from the e2e)"
        ),
        f"  states              : {row['amended_goal']['states']}",
        f"  system_arrival      : {row['amended_goal']['system_arrival']}",
        f"  scorer_arrival      : {row['amended_goal']['scorer_arrival']}",
        f"  authority_category  : {row['amended_goal']['authority_category']}",
        f"  DTG                 : {row['amended_goal']['distance_to_goal_m']} m",
        f"  SPL                 : {row['amended_goal']['spl']}",
        f"  final pose          : {row['amended_goal']['end']}",
        "",
        "switch window",
        (
            f"  span                : {row['switch_window']['from_s']} .. "
            f"{row['switch_window']['to_s']} s"
        ),
        f"  sim collision flags : {row['switch_window']['sim_collision_flag_events']}",
        f"  collision (clearance<=0): {row['switch_window']['collision_by_clearance']}",
        f"  false arrival       : {row['switch_window']['false_arrival']}",
        (
            f"  min clearance       : {row['switch_window']['min_clearance_m']} m "
            f"({row['switch_window']['samples_in_window']} samples in window)"
        ),
        "",
        "plan-queue policy (amendment N1: RE-ISSUE, never a resume)",
    ]
    for entry in row["queue"]["log"]:
        lines.append(f"  {entry}")
    if row.get("reissue") is not None:
        lines += [
            f"  re-issued           : {row['reissue']['text']!r}",
            f"  states              : {row['reissue']['states']}",
            (
                f"  system/scorer       : {row['reissue']['system_arrival']}/"
                f"{row['reissue']['scorer_arrival']}"
            ),
            f"  DTG                 : {row['reissue']['distance_to_goal_m']} m",
            f"  final pose          : {row['reissue']['end']}",
        ]
    lines += [
        "",
        (
            f"total path (all legs) : {row['total_path_m']} m "
            f"(oracle {row['oracle_path_m']} m, ratio {row['path_ratio_oracle']})"
        ),
        (
            f"collisions (whole ep) : {row['collisions_total']} "
            f"(min clearance {row['min_clearance_total_m']} m)"
        ),
        f"wall clock            : {row.get('wall_s')} s",
        "",
        "RECEIPT TIMELINE (sampler-observed executive transitions, 50 Hz poll)",
        f"{'t (s)':>8}  {'task':<28} {'rev':>3}  {'from':>10} -> {'to':<10} skill / detail",
    ]
    for receipt in receipts:
        lines.append(
            f"{float(receipt['t']):8.2f}  {str(receipt['task_id'])[:28]:<28} "
            f"{receipt['plan_revision']:>3}  "
            f"{receipt['previous']!s:>10} -> {receipt['state']!s:<10} "
            f"{receipt['skill']} :: {receipt['detail']}"
        )
    text = "\n".join(lines) + "\n"
    out.write_text(text, encoding="utf-8")
    return text


def stage_sample(tier: dict, out: Path, *, from_jsonl: Path | None = None) -> dict:
    """One episode, printed with its receipt timeline.

    Reads the episode from ``episodes.jsonl`` when the tier has already been
    run (no extra sim), otherwise runs one live.
    """

    if from_jsonl is not None and from_jsonl.exists():
        rows = [
            row
            for row in _read_jsonl(from_jsonl)
            if "error" not in row and row.get("reissue") is not None
        ]
        if rows:
            row = rows[0]
            print(render_sample(row, row.get("receipts") or [], out), flush=True)
            return row
    sessions = Sessions()
    episode = tier["episodes"][5]
    live = sessions.open()
    try:
        row = run_interrupt_episode(live, episode)
        receipts = [item.as_dict() for item in live.snapshot_receipts()]
    finally:
        sessions.close(live)
    print(render_sample(row, receipts, out), flush=True)
    return row


# ---------------------------------------------------------------------------
# stage: the H-NI1c classifier bench
# ---------------------------------------------------------------------------


BLIND_PATH = HERE / "gold_blind.json"
BLIND_SHA_PATH = HERE / "gold_blind.sha256"


def _bench(
    cases: list[dict],
    *,
    use_progress: bool = True,
    label_key: str = "label",
    classifier=None,
) -> dict:
    classify = classifier or QP.classify
    labels = list(QP.LABELS)
    confusion = {name: {out: 0 for out in labels} for name in labels}
    misses: list[dict] = []
    for case in cases:
        decision = classify(
            case["utterance"],
            current_goal=case.get("current_goal"),
            progress=float(case.get("progress", 0.0)) if use_progress else 0.0,
        )
        gold = str(case[label_key])
        confusion.setdefault(gold, {out: 0 for out in labels})
        confusion[gold][decision.label] += 1
        if decision.label != gold:
            misses.append(
                {
                    "id": case.get("id"),
                    "utterance": case["utterance"],
                    "gold": gold,
                    "predicted": decision.label,
                    "reason": decision.reason,
                    "adversarial": bool(case.get("adversarial")),
                }
            )
    per_class = {}
    for gold, row in confusion.items():
        total = sum(row.values())
        if not total:
            continue
        per_class[gold] = {
            "n": total,
            "correct": row.get(gold, 0),
            "accuracy": round(row.get(gold, 0) / total, 4),
            "wilson95": wilson(row.get(gold, 0), total),
        }
    correct = sum(row.get(name, 0) for name, row in confusion.items())
    n = sum(sum(row.values()) for row in confusion.values())
    return {
        "n": n,
        "overall_accuracy": round(correct / n, 4) if n else None,
        "overall_wilson95": wilson(correct, n),
        "per_class": per_class,
        "confusion": {k: v for k, v in confusion.items() if sum(v.values())},
        "misses": misses,
    }


def stage_classifier() -> dict:
    """AMENDMENT N7 — the 0.9 bar reads on the VERIFIER's blind set only."""

    out: dict = {
        "primary_set": "gold_blind.json (verifier-authored, frozen by sha256 "
        "before the classifier ran — amendment N7)",
    }
    if BLIND_PATH.exists():
        raw = BLIND_PATH.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        expected = ""
        if BLIND_SHA_PATH.exists():
            expected = BLIND_SHA_PATH.read_text(encoding="utf-8").split()[0].strip()
        blind = json.loads(raw.decode("utf-8"))
        cases = blind["cases"]
        out["blind_sha256"] = digest
        out["blind_sha256_expected"] = expected
        out["blind_sha256_matches"] = bool(expected) and digest == expected
        out["blind"] = _bench(cases, label_key="gold")
        out["blind_adversarial"] = _bench(
            [case for case in cases if case.get("adversarial")], label_key="gold"
        )
        out["blind_non_adversarial"] = _bench(
            [case for case in cases if not case.get("adversarial")], label_key="gold"
        )
        # POST-HOC, and labelled so everywhere: written after the blind run's
        # error analysis. No pre-registered bar reads on it.
        out["blind_v2_post_hoc"] = _bench(
            cases, label_key="gold", classifier=QP.classify_v2
        )
        out["blind_v2_post_hoc"]["caveat"] = (
            "POST-HOC: classify_v2 was written AFTER this set was opened. It is "
            "not a blind measurement and the H-NI1c criterion is not read on it."
        )
        out["blind_v2_post_hoc_adversarial"] = _bench(
            [case for case in cases if case.get("adversarial")],
            label_key="gold",
            classifier=QP.classify_v2,
        )
    if GOLD_PATH.exists():
        gold = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
        out["dev_set_note"] = (
            "gold.json is the executor's own DEV set, authored before the blind "
            "set existed; it is reported for transparency and no bar reads on it"
        )
        out["dev_pre_registered"] = _bench(gold["pre_registered"])
        out["dev_pre_registered_progress_ablation"] = _bench(
            gold["pre_registered"], use_progress=False
        )
        out["dev_supplementary_clarify"] = _bench(gold.get("supplementary_clarify", []))
        out["dev_supplementary_context"] = _bench(gold.get("supplementary_context", []))
        out["dev_supplementary_context_progress_ablation"] = _bench(
            gold.get("supplementary_context", []), use_progress=False
        )
    return out


# ---------------------------------------------------------------------------
# aggregation
# ---------------------------------------------------------------------------


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[index], 3)


def wilson(successes: int, n: int, z: float = 1.959963985) -> dict:
    """AMENDMENT N8 — a Wilson 95 % interval for a proportion.

    Criteria are read on the point estimate; the interval is shown beside it
    so a rate measured on 14 episodes is never mistaken for a rate measured
    on 140.
    """

    if n <= 0:
        return {"k": successes, "n": n, "p": None, "lo": None, "hi": None}
    p = successes / n
    denominator = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = (z / denominator) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return {
        "k": successes,
        "n": n,
        "p": round(p, 4),
        "lo": round(max(0.0, centre - half), 4),
        "hi": round(min(1.0, centre + half), 4),
    }


def _counter(values: list) -> dict:
    out: dict[str, int] = {}
    for value in values:
        out[str(value)] = out.get(str(value), 0) + 1
    return dict(sorted(out.items()))


def _rate(rows: list[dict], predicate) -> dict:
    return wilson(sum(1 for row in rows if predicate(row)), len(rows))


def _authority_tally(controls: list[dict], tier_rows: list[dict]) -> dict:
    """The NAV-QUALITY authority-disagreement class, as its OWN row per goal.

    Fable, 2026-08-29: "system-failed-but-arrived" and
    "system-succeeded-but-not-arrived" are the frozen matrix's authority
    disagreement class (22 rows there), NOT an interruption or queue-policy
    effect. They are tallied here separately for every goal, over every scored
    leg this experiment ran — from-rest controls, the leg that followed the
    interruption, and the re-issue leg — so a product terminal-verification bug
    is never read as a failure of the thing under test.
    """

    per_goal: dict[str, dict] = {}

    def note(goal_key: str, leg: dict) -> None:
        if not goal_key or goal_key == "hold":
            return
        entry = per_goal.setdefault(
            goal_key,
            {
                "n_scored_legs": 0,
                "agreement": 0,
                "tolerated_boundary": 0,
                "system_failed_but_arrived": 0,
                "system_succeeded_but_not_arrived": 0,
                "unknown": 0,
                "legs": {},
            },
        )
        entry["n_scored_legs"] += 1
        entry["legs"][leg.get("label", "?")] = entry["legs"].get(leg.get("label", "?"), 0) + 1
        system = bool(leg.get("system_arrival"))
        scorer = leg.get("scorer_arrival")
        category = str(leg.get("authority_category"))
        if scorer is None or category == "unknown":
            entry["unknown"] += 1
        elif category == "tolerated_boundary":
            entry["tolerated_boundary"] += 1
        elif bool(scorer) == system:
            entry["agreement"] += 1
        elif scorer and not system:
            entry["system_failed_but_arrived"] += 1
        else:
            entry["system_succeeded_but_not_arrived"] += 1

    for row in controls:
        if "error" in row:
            continue
        note(row["goal_key"], row["leg"])
    for row in tier_rows:
        if "error" in row:
            continue
        if row["family_class"] != "hold":
            note(row["amended_goal"].get("goal_key", ""), row["amended_goal"])
        if row.get("reissue"):
            note(row["reissue"]["goal_key"], row["reissue"])

    for entry in per_goal.values():
        n = entry["n_scored_legs"]
        entry["rate_system_failed_but_arrived"] = (
            round(entry["system_failed_but_arrived"] / n, 4) if n else None
        )
        entry["rate_system_succeeded_but_not_arrived"] = (
            round(entry["system_succeeded_but_not_arrived"] / n, 4) if n else None
        )
    totals = {
        key: sum(entry[key] for entry in per_goal.values())
        for key in (
            "n_scored_legs",
            "agreement",
            "tolerated_boundary",
            "system_failed_but_arrived",
            "system_succeeded_but_not_arrived",
            "unknown",
        )
    }
    return {
        "note": (
            "NAV-QUALITY authority-disagreement class, per goal, over every "
            "scored leg (controls + post-interruption leg + re-issue leg). Not "
            "an interruption effect: it reproduces from rest."
        ),
        "totals": totals,
        "by_goal": per_goal,
    }


def aggregate(controls: list[dict], sequences: list[dict], tier_rows: list[dict]) -> dict:
    good = [row for row in tier_rows if "error" not in row]

    # --- from-rest controls, per goal ------------------------------------
    control_by_goal: dict[str, dict] = {}
    for row in controls:
        if "error" in row:
            continue
        leg = row["leg"]
        entry = control_by_goal.setdefault(
            row["goal_key"],
            {"n": 0, "system": 0, "scorer": 0, "both": 0, "spl": [], "dtg": [], "path": []},
        )
        entry["n"] += 1
        entry["system"] += int(bool(leg["system_arrival"]))
        entry["scorer"] += int(bool(leg["scorer_arrival"]))
        entry["both"] += int(bool(leg["system_arrival"]) and bool(leg["scorer_arrival"]))
        entry["spl"].append(float(leg["spl"]))
        entry["path"].append(float(leg["path_m"]))
        if leg["distance_to_goal_m"] is not None:
            entry["dtg"].append(float(leg["distance_to_goal_m"]))
    for entry in control_by_goal.values():
        entry["success_both"] = wilson(entry["both"], entry["n"])
        entry["success_system"] = wilson(entry["system"], entry["n"])
        entry["mean_spl"] = _mean(entry["spl"])
        entry["mean_dtg_m"] = _mean(entry["dtg"])
        entry["mean_path_m"] = _mean(entry["path"])
        del entry["spl"], entry["dtg"], entry["path"]

    # --- H-NI1a: only the rows the runtime was actually interrupted on ----
    interrupted = [row for row in good if not row["admission"].get("held_pre_runtime")]
    with_goal_2 = [row for row in interrupted if row["family_class"] != "hold"]
    held = [row for row in good if row["admission"].get("held_pre_runtime")]
    hold_rows = [row for row in good if row["family_class"] == "hold"]

    latencies = [
        float(row["admission"]["latency_ms"])
        for row in interrupted
        if row["admission"].get("latency_ms") is not None
    ]
    inband = [
        float(row["admission"]["inband_handle_text_ms"])
        for row in interrupted
        if row["admission"].get("inband_handle_text_ms") is not None
    ]

    def _is_amended(row: dict) -> bool:
        """True only when the leg after the interruption was the AMENDED goal.

        When the runtime refuses the interruption there is no goal-2 task and
        the original goal keeps running; that leg is labelled
        ``goal_1_continued`` and scores goal 1. Counting it as an amended-goal
        success would credit the amendment with an arrival at the goal it
        failed to change.
        """

        return row["amended_goal"].get("label") == "amended_goal"

    def _amended_ok(row: dict) -> bool:
        return _is_amended(row) and bool(row["amended_goal"].get("success"))

    # paired against the goal-2 from-rest control
    paired: dict[str, dict] = {}
    for row in with_goal_2:
        key = row["goal_2"]["key"]
        control = control_by_goal.get(key)
        if control is None or control["n"] == 0:
            continue
        entry = paired.setdefault(
            key,
            {
                "n": 0,
                "amended_success": 0,
                "control_rate": control["success_both"]["p"],
                "control_n": control["n"],
            },
        )
        entry["n"] += 1
        entry["amended_success"] += int(_amended_ok(row))
    deltas = []
    for entry in paired.values():
        entry["amended_rate"] = round(entry["amended_success"] / entry["n"], 4)
        entry["delta"] = round(entry["amended_rate"] - (entry["control_rate"] or 0.0), 4)
        deltas.append((entry["delta"], entry["n"]))
    weighted_control = _mean(
        [
            control_by_goal[row["goal_2"]["key"]]["success_both"]["p"]
            for row in with_goal_2
            if row["goal_2"]["key"] in control_by_goal
            and control_by_goal[row["goal_2"]["key"]]["success_both"]["p"] is not None
        ]
    )
    amended_rate = _rate(with_goal_2, _amended_ok)

    switch_collisions = sum(
        int(row["switch_window"]["sim_collision_flag_events"]) for row in good
    )
    switch_clearance_collisions = sum(
        int(bool(row["switch_window"].get("collision_by_clearance"))) for row in good
    )
    switch_false = sum(
        int(bool(row["switch_window"]["false_arrival"].get("false_arrival")))
        for row in good
    )
    amended_false_arrival = sum(
        int(row["amended_goal"]["authority_category"] == "false_arrival")
        for row in with_goal_2
    )

    def _by_class(rows: list[dict]) -> dict:
        groups: dict[str, list[dict]] = {}
        for row in rows:
            groups.setdefault(row["family_class"], []).append(row)
        out = {}
        for name, items in sorted(groups.items()):
            lat = [
                float(item["admission"]["latency_ms"])
                for item in items
                if item["admission"].get("latency_ms") is not None
            ]
            out[name] = {
                "n": len(items),
                "admission": _rate(items, lambda r: bool(r["admission"].get("admitted"))),
                "median_latency_ms": _quantile(lat, 0.5),
                "max_latency_ms": max(lat) if lat else None,
                "receipt_kinds": _counter(
                    [item["admission"].get("receipt_kind") for item in items]
                ),
                "closed_intent": _counter(
                    [item["admission"].get("closed_intent") for item in items]
                ),
                "goal_amend_ok": _counter(
                    [item["admission"].get("goal_amend_ok") for item in items]
                ),
                "goal_amend_replan": _counter(
                    [item["admission"].get("goal_amend_replan") for item in items]
                ),
                "amended_success": (
                    _rate(
                        [i for i in items if i["family_class"] != "hold"], _amended_ok
                    )
                    if name != "hold"
                    else None
                ),
            }
        return out

    h_ni1a = {
        "note": (
            "measured only on the rows the runtime was actually interrupted on; "
            "the queue family is HELD in the harness by amendment N9 and never "
            "reaches handle_text mid-task, so it carries no admission row"
        ),
        "n_interrupted": len(interrupted),
        "n_with_goal_2": len(with_goal_2),
        "n_held_pre_runtime": len(held),
        "n_hold_rows": len(hold_rows),
        "detectability_bound": (
            "n=40 (rule of three): a zero count bounds the true rate at "
            "<= 3/40 = 7.5 % with 95 % confidence"
        ),
        "admission_rate": _rate(
            interrupted, lambda r: bool(r["admission"].get("admitted"))
        ),
        "admission_latency_label": (
            "admission-at-any-poll (amendment N2): handle_text entry -> first "
            "suspend/replace/submit receipt observed by the 50 Hz sampler"
        ),
        "admission_latency_ms_mean": _mean(latencies),
        "admission_latency_ms_p50": _quantile(latencies, 0.5),
        "admission_latency_ms_p95": _quantile(latencies, 0.95),
        "admission_latency_ms_max": max(latencies) if latencies else None,
        "admission_within_1000ms": wilson(
            sum(1 for value in latencies if value <= 1000.0), len(latencies)
        ),
        "inband_handle_text_ms_mean": _mean(inband),
        "inband_handle_text_ms_max": max(inband) if inband else None,
        "receipt_kinds": _counter(
            [row["admission"].get("receipt_kind") for row in interrupted]
        ),
        "amended_goal_success_both_authorities": amended_rate,
        "amended_goal_success_system_only": _rate(
            with_goal_2, lambda r: _is_amended(r) and bool(r["amended_goal"]["system_arrival"])
        ),
        "amended_goal_success_scorer_only": _rate(
            with_goal_2, lambda r: _is_amended(r) and bool(r["amended_goal"]["scorer_arrival"])
        ),
        "n_interruption_refused_goal_1_continued": sum(
            1 for r in with_goal_2 if not _is_amended(r)
        ),
        "from_rest_control_success_goal2_weighted": weighted_control,
        "delta_success_vs_from_rest": (
            None
            if weighted_control is None or amended_rate["p"] is None
            else round(amended_rate["p"] - weighted_control, 4)
        ),
        "paired_by_goal": paired,
        "mean_spl_amended": _mean(
            [float(r["amended_goal"]["spl"]) for r in with_goal_2 if _is_amended(r)]
        ),
        "mean_dtg_amended_m": _mean(
            [
                float(r["amended_goal"]["distance_to_goal_m"])
                for r in with_goal_2
                if _is_amended(r) and r["amended_goal"]["distance_to_goal_m"] is not None
            ]
        ),
        "collisions_in_switch_window_sim_flag": switch_collisions,
        "collisions_in_switch_window_clearance_le_0": switch_clearance_collisions,
        "min_clearance_in_switch_window_m": min(
            [
                float(row["switch_window"]["min_clearance_m"])
                for row in good
                if row["switch_window"].get("min_clearance_m") is not None
            ]
            or [float("nan")]
        ),
        "false_arrivals_in_switch_window": switch_false,
        "amended_goal_false_arrival_category": amended_false_arrival,
        "authority_categories": _counter(
            [
                row["amended_goal"]["authority_category"]
                for row in with_goal_2
                if _is_amended(row)
            ]
        ),
        "by_family_class": _by_class(interrupted),
        "by_trigger_fraction": {
            name: {
                "n": len(items),
                "admission": _rate(
                    items, lambda r: bool(r["admission"].get("admitted"))
                ),
                "amended_success": _rate(
                    [i for i in items if i["family_class"] != "hold"], _amended_ok
                ),
            }
            for name, items in sorted(
                _group(interrupted, lambda r: str(r["trigger_spec"]["fraction"])).items()
            )
        },
        "hold_rows": [
            {
                "episode_id": row["episode_id"],
                "goal_amend_ok": row["admission"].get("goal_amend_ok"),
                "goal_amend_replan": row["admission"].get("goal_amend_replan"),
                "receipt_kind": row["admission"].get("receipt_kind"),
                "states_after_hold": row["amended_goal"]["states"],
                "details_after_hold": row["amended_goal"]["details"],
                "path_during_hold_m": row["amended_goal"]["metrics"].get("hold_path_m"),
            }
            for row in hold_rows
        ],
    }

    # --- H-NI1b -----------------------------------------------------------
    sequence_by_id = {
        row["control_id"]: row for row in sequences if "error" not in row
    }
    reissued = [row for row in good if row.get("reissue") is not None]
    # "both goals reachable" is read from the from-rest controls: a goal that
    # never verifies from rest cannot be a fair test of the queue policy.
    def _reachable(key: str) -> bool:
        entry = control_by_goal.get(key)
        return bool(entry and entry["both"] > 0)

    both_reachable = [
        row
        for row in reissued
        if _reachable(row["goal_1"]["key"])
        and (row["family_class"] == "hold" or _reachable(row["goal_2"]["key"]))
    ]
    returned = [
        row
        for row in both_reachable
        if row["reissue"]["system_arrival"] and row["reissue"]["scorer_arrival"]
    ]
    oracle_ratios = [
        float(row["path_ratio_oracle"])
        for row in both_reachable
        if row.get("path_ratio_oracle") is not None
    ]
    measured_ratios = []
    for row in both_reachable:
        sequence = sequence_by_id.get(f"seq-{row['goal_2']['key']}-then-{row['goal_1']['key']}")
        if sequence and sequence.get("total_path_m"):
            measured_ratios.append(float(row["total_path_m"]) / float(sequence["total_path_m"]))

    # Which terminal state actually triggered the re-issue, and how often that
    # terminal state was a FALSE failure (the system said failed while the K0
    # predicate said the robot had arrived). Fable, 2026-08-29: the policy
    # should re-issue on either terminal, and the row must say how often the
    # trigger was a false ``failed``.
    trigger_states: list[str] = []
    false_failed_triggers = 0
    for row in good:
        for entry in row["queue"]["log"]:
            if entry.get("action") != "reissue":
                continue
            state = str(entry.get("terminal_state") or "unknown")
            trigger_states.append(state)
            leg = row["amended_goal"]
            if (
                "failed" in state
                and bool(leg.get("scorer_arrival"))
                and not bool(leg.get("system_arrival"))
            ):
                false_failed_triggers += 1

    h_ni1b = {
        "label": (
            "re-issue (amendment N1): the runtime consumes the parked ResumeIntent "
            "on commit, so the harness re-issues the remembered directive text as a "
            "NEW task; queue-family utterances are held PRE-runtime (amendment N9)"
        ),
        "n_reissued": len(reissued),
        "n_both_goals_reachable_from_rest": len(both_reachable),
        "return_rate": wilson(len(returned), len(both_reachable)),
        "return_rate_all_reissued": _rate(
            reissued,
            lambda r: bool(r["reissue"]["system_arrival"] and r["reissue"]["scorer_arrival"]),
        ),
        "return_rate_scorer_only": _rate(
            reissued, lambda r: bool(r["reissue"]["scorer_arrival"])
        ),
        "return_rate_scorer_only_both_reachable": _rate(
            both_reachable, lambda r: bool(r["reissue"]["scorer_arrival"])
        ),
        "return_rate_note": (
            "return_rate is the pre-registered system-AND-scorer rate; "
            "return_rate_scorer_only_both_reachable is the same episodes scored "
            "on the independent K0 predicate alone, so the policy is not "
            "penalised for the product's terminal-verification bug (see "
            "authority_disagreement)"
        ),
        "reissue_trigger_terminal_state": _counter(trigger_states),
        "reissue_trigger_was_a_false_failed": false_failed_triggers,
        "path_ratio_reference": (
            "oracle: start -> interruption pose -> goal 2 -> goal 1, straight line "
            "from the ACTUAL interruption pose (amendment N8)"
        ),
        "path_ratio_oracle_mean": _mean(oracle_ratios),
        "path_ratio_oracle_p50": _quantile(oracle_ratios, 0.5),
        "path_ratio_oracle_p95": _quantile(oracle_ratios, 0.95),
        "n_path_ratio_oracle": len(oracle_ratios),
        "path_ratio_vs_measured_sequence_mean": _mean(measured_ratios),
        "n_path_ratio_measured": len(measured_ratios),
        "path_ratio_by_trigger_fraction": {
            name: {
                "n": len(items),
                "mean": _mean(
                    [
                        float(item["path_ratio_oracle"])
                        for item in items
                        if item.get("path_ratio_oracle") is not None
                    ]
                ),
            }
            for name, items in sorted(
                _group(both_reachable, lambda r: str(r["trigger_spec"]["fraction"])).items()
            )
        },
        "by_family_class": {
            name: {
                "n": len(items),
                "return_rate": _rate(
                    items,
                    lambda r: bool(
                        r["reissue"]["system_arrival"] and r["reissue"]["scorer_arrival"]
                    ),
                ),
            }
            for name, items in sorted(
                _group(both_reachable, lambda r: r["family_class"]).items()
            )
        },
        "queue_actions": _counter(
            [entry["action"] for row in good for entry in row["queue"]["log"]]
        ),
        "sequence_controls_measured": len(sequence_by_id),
        "sequence_controls_both_reached": _mean(
            [float(bool(row.get("both_reached"))) for row in sequence_by_id.values()]
        ),
    }

    return {
        "controls_by_goal": control_by_goal,
        "authority_disagreement": _authority_tally(controls, tier_rows),
        "h_ni1a": h_ni1a,
        "h_ni1b": h_ni1b,
    }


def _group(rows: list[dict], key) -> dict:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(str(key(row)), []).append(row)
    return groups


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true")
    parser.add_argument(
        "--stage",
        action="append",
        choices=["sample", "controls", "sequence", "tier", "classifier", "aggregate"],
        default=[],
    )
    parser.add_argument("--seed", type=int, default=20260829)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--only", type=str, default=None, help="controls stage: one goal key")
    args = parser.parse_args()

    stages = args.stage or (
        ["controls", "sequence", "tier", "classifier", "aggregate"] if args.all else []
    )
    if not stages:
        parser.error("give --all or at least one --stage")

    tier = json.loads(TIER_PATH.read_text(encoding="utf-8"))
    if int(tier["seed"]) != int(args.seed):
        raise SystemExit(
            f"tier seed {tier['seed']} != --seed {args.seed}; regenerate with gen_tier.py"
        )
    WORKDIR.mkdir(parents=True, exist_ok=True)

    controls_jsonl = HERE / "controls.jsonl"
    sequence_jsonl = HERE / "sequence_controls.jsonl"
    tier_jsonl = HERE / "episodes.jsonl"
    started = time.time()

    if "sample" in stages:
        stage_sample(tier, HERE / "sample_episode.txt", from_jsonl=HERE / "episodes.jsonl")
    if "controls" in stages:
        stage_controls(tier, controls_jsonl, limit=args.limit, only=args.only)
    if "sequence" in stages:
        stage_sequence(tier, sequence_jsonl, limit=args.limit)
    if "tier" in stages:
        stage_tier(tier, tier_jsonl, limit=args.limit, offset=args.offset)

    results_path = HERE / "results.json"
    if "classifier" in stages or "aggregate" in stages:
        controls = _read_jsonl(controls_jsonl)
        sequences = _read_jsonl(sequence_jsonl)
        tier_rows = _read_jsonl(tier_jsonl)
        payload = {
            "experiment": "NAV-INT-1",
            "evidence_tier": "desktop-sim",
            "seed": args.seed,
            "tier_id": tier["tier_id"],
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "wall_s": round(time.time() - started, 1),
            "amendments_applied": ["N1", "N2", "N3", "N4"],
            "reasoner": "local_plan_sketch (use_llm=False; no LLM planner in this fixture)",
            "counts": {
                "controls": len(controls),
                "sequence_controls": len(sequences),
                "tier_episodes": len(tier_rows),
                "tier_errors": sum(1 for row in tier_rows if "error" in row),
            },
        }
        if "aggregate" in stages or "classifier" in stages:
            payload.update(aggregate(controls, sequences, tier_rows))
        if "classifier" in stages:
            payload["h_ni1c"] = stage_classifier()
        payload["orphan_check"] = orphan_check()
        results_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {results_path}", flush=True)

    check = orphan_check()
    print(
        f"[N3 orphan check] clean={check['clean']} "
        f"ours={check['survivors_ours']} other_processes={check['survivors_other_processes']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
