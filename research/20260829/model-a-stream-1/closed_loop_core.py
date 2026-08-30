"""THE one episode runner.  The teacher and every closed-loop policy go
through this function, so the script, the frame builder, the truth-oracle gold
and the safety filter cannot drift apart between arms.

Amendments honoured here: A1 (gold from the truth oracle), A3 (5-frame goal
mask after a cue; switch anchored to the cue frame and measured from the truth
pose), A8 (``cmd:stop`` held until a new directive; ``owner_speaking``; raw and
post-filter safety counters), A10 (terminal tokens are predictions).
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from teacher import (
    ACT_ID,
    ACT_VOCAB,
    ANN_INDEX,
    CODEC,
    GAZE_IDS,
    GOAL_MASK_FRAMES,
    HOLD_ID,
    KIND_PLAIN,
    KIND_QUEUE,
    KIND_REVISE,
    MAX_FRAMES_EPISODE,
    MAX_FRAMES_PER_GOAL,
    N_ANN,
    NARR_ID,
    NARR_NONE,
    ORACLE_SETTLE_FRAMES,
    TARGET_ID,
    EpisodeScript,
    HarnessState,
    VelocityCommand,
    _goal_from,
    _Teacher,
    _wrap,
    act_token_for,
    apply_reactive_safety,
    build_frame,
    canon_act,
    derive_event,
    free_sectors,
    inside_goal_band,
    target_geometry,
)

#: Substrings of a ``MidLevelCommand.note`` that mean the NAVIGATOR believes
#: it is blocked or recovering.  Used ONLY to measure agreement with the truth
#: oracle; it never produces a label.
_TEACHER_BLOCK_WORDS = ("blocked", "recover", "no_progress", "person_stop",
                        "unroutable", "gate_blocked", "stop_requested")


def decode_act(token: str) -> VelocityCommand:
    """Product codec decode.  A gaze is a LOOK: the body holds that frame."""

    cmd = CODEC.decode(token)
    if cmd.kind == "twist":
        return VelocityCommand(vx=float(cmd.vx), vy=0.0, vyaw=float(cmd.vyaw))
    return VelocityCommand()


def safety_filter(act_id: int, hs: HarnessState, free: list) -> int:
    """A8's DETERMINISTIC filter.  Post-filter violation rates must be 0."""

    if hs.stop_latched or hs.speaking_hold:
        return HOLD_ID
    tok = ACT_VOCAB[act_id]
    if tok.startswith("<twist:"):
        c = CODEC.decode(tok)
        if c.vx > 0.0 and free[0] == 0:
            return ACT_ID[canon_act(CODEC.encode_twist(0.0, c.vyaw))]
    return act_id


def _violations(act_id: int, hs: HarnessState, free: list) -> dict:
    tok = ACT_VOCAB[act_id]
    is_twist = tok.startswith("<twist:")
    c = CODEC.decode(tok) if is_twist else None
    moving = bool(is_twist and (abs(c.vx) > 1e-9 or abs(c.vyaw) > 1e-9))
    return {
        "nonidle_after_stop": int(hs.stop_latched and act_id != HOLD_ID
                                  and act_id not in GAZE_IDS),
        "twist_into_occupied": int(is_twist and c.vx > 0.0 and free[0] == 0),
        "twist_while_owner_speaking": int(bool(hs.speaking_hold) and moving),
        "stop_frames": int(hs.stop_latched),
        "speaking_frames": int(bool(hs.speaking_hold)),
        "occupied_frames": int(free[0] == 0),
    }


@dataclass
class EpisodeTrace:
    frames: int = 0
    acts: list = field(default_factory=list)         # post-filter tokens
    acts_raw: list = field(default_factory=list)     # the arm's own emission
    narr_pred: list = field(default_factory=list)
    narr_gold: list = field(default_factory=list)
    gold_anchor: list = field(default_factory=list)  # (frame, narr_id)
    switch_anchor: list = field(default_factory=list)  # (cue_frame, target, kind)
    sound_anchor: list = field(default_factory=list)
    resume_anchor: list = field(default_factory=list)  # (frame, target)
    rel_bearing: list = field(default_factory=list)   # truth pose -> ACTIVE goal
    arrivals: list = field(default_factory=list)      # (frame, target, slot)
    arrivals_loose: list = field(default_factory=list)  # band entry, no settle
    safety: dict = field(default_factory=dict)
    channels: np.ndarray | None = None
    acts_id: np.ndarray | None = None
    narr_id_arr: np.ndarray | None = None
    ann: np.ndarray | None = None
    meta: dict = field(default_factory=dict)


def run_core(world, harness, script: EpisodeScript, *, policy=None,
             teacher_arm: bool = False, record: bool = False) -> EpisodeTrace:
    world.reset(robot=script.start)
    if policy is not None and hasattr(policy, "reset"):
        policy.reset()
    hs = HarnessState()
    tr = EpisodeTrace()
    # A1 says "truth minimum clearance below the reactive-safety stop band".
    # MEASURED on 600 held-out teacher episodes, the STOP band (0.65 m) fires
    # 2 times in 600 episodes — A4 needs >= 200 events per class and no
    # achievable number of seeds gets there (rate 0.003/episode).  The SLOW
    # band (obstacle_slow_m = 1.2 m, the radius at which the same product gate
    # begins to brake) fires 637 times over 467/600 episodes.  The gold uses
    # the SLOW band; the stop-band edges are counted alongside so the
    # deviation from A1's letter is visible rather than silent.
    stop_band = float(harness.reactive_safety.obstacle_stop_m)
    block_band = float(harness.reactive_safety.obstacle_slow_m)

    teacher = _Teacher(harness) if teacher_arm else None
    goal = _goal_from(world, script.target_a, script.start[0], script.start[1], 1, 0)
    if teacher_arm:
        teacher.start(script.directive_a)
    pending = [f"nav.start:{script.target_a}"]
    hs.cmd_hold, hs.cmd_kind, hs.cmd_target = 3, "cmd:go_to", script.target_a
    hs.f_cue = 0

    chans, act_ids, narr_ids, anns = [], [], [], []
    sums = {"nonidle_after_stop": 0, "twist_into_occupied": 0,
            "twist_while_owner_speaking": 0, "stop_frames": 0,
            "speaking_frames": 0, "occupied_frames": 0}
    post = {"nonidle_after_stop": 0, "twist_into_occupied": 0,
            "twist_while_owner_speaking": 0}

    interrupted = False
    interrupt_frame = int(30 + script.interrupt_at * 110)
    stop_release = -1
    force_interrupt = False
    frame = goal_frame = 0
    path_len = 0.0
    prev = (script.start[0], script.start[1])
    n_goals = 0
    resumed = False
    teacher_blocks: list = []
    oracle_blocks: list = []
    teacher_block_latched = False
    teacher_arrived_frame = -1
    oracle_arrived_frame = -1
    stopband_run = 0
    stopband_edges: list = []
    loose_hits: set = set()

    try:
        while frame < MAX_FRAMES_EPISODE:
            obs = world.observe()
            free = free_sectors(obs)
            x, y, yaw = float(obs.robot.x), float(obs.robot.y), float(obs.robot.yaw)

            # ---------- scripted owner ----------------------------------
            if frame == script.stop_frame and not hs.stop_latched:      # A8
                hs.stop_latched = True
                hs.cmd_hold, hs.cmd_kind, hs.cmd_target = 3, "cmd:stop", "none"
                hs.f_cue = frame
                stop_release = frame + script.stop_len
                if teacher_arm and teacher.nav is not None:
                    teacher.nav.pause()
            elif hs.stop_latched and frame == stop_release:
                hs.stop_latched = False
                hs.cmd_hold, hs.cmd_kind = 3, "cmd:go_to"
                hs.cmd_target = goal.target or script.target_a
                hs.f_cue = frame
                pending.append(f"nav.start:{goal.target or script.target_a}")
                if teacher_arm and teacher.nav is not None:
                    teacher.nav.resume()

            for i, sp in enumerate(script.speak_frames):                # A8
                if frame == sp:
                    hs.speaking_hold = script.speak_lens[i]

            if (not interrupted and script.kind in (KIND_REVISE, KIND_QUEUE)
                    and (goal_frame >= interrupt_frame or force_interrupt)
                    and goal.slot == 1 and not hs.stop_latched):
                force_interrupt = False
                interrupted = True
                hs.cmd_hold = 3
                hs.cmd_kind = ("cmd:revise" if script.kind == KIND_REVISE
                               else "cmd:queue")
                hs.cmd_target = script.target_b
                hs.f_cue = frame
                pending.append(
                    f"{'plan.revised' if script.kind == KIND_REVISE else 'plan.queued'}"
                    f":{script.target_b}")
                tr.switch_anchor.append((frame, script.target_b, script.kind))
                hs.prev_goal = goal
                hs.masked_goal = goal                       # A3: lag the channel
                hs.mask_until = frame + GOAL_MASK_FRAMES
                goal = _goal_from(world, script.target_b, x, y, 2, frame)
                if teacher_arm:
                    teacher.start(script.directive_b)
                goal_frame = 0
                hs.oracle_stop_run = 0

            for i, sf in enumerate(script.sound_frames):
                if frame == sf:
                    hs.sound_hold = 2
                    hs.sound_bin = script.sound_bins[i]
                    hs.f_sound = frame
                    pending.append(f"attend.sound:{hs.sound_bin}")
                    tr.sound_anchor.append((frame, hs.sound_bin))
                    if teacher_arm:
                        hs.gaze_hold = 2
                        hs.gaze_token = f"<gaze_bearing_{hs.sound_bin}>"

            # ---------- the frame ---------------------------------------
            row = build_frame(obs, goal, hs, frame, free)

            # ---------- the arm ------------------------------------------
            if teacher_arm:
                if hs.stop_latched or hs.speaking_hold:
                    vel = VelocityCommand()
                    raw_id = (ACT_ID[hs.gaze_token] if (hs.gaze_hold and hs.gaze_token)
                              else HOLD_ID)
                else:
                    _cmd, vel = teacher.step(world, obs)
                    raw_id = ACT_ID[act_token_for(vel, hs)]
                    _note = str(getattr(_cmd, "note", ""))
                    _st = teacher.mission.status_value() if teacher.mission else ""
                    _tb = any(w in _note for w in _TEACHER_BLOCK_WORDS)
                    if _tb and not teacher_block_latched:
                        teacher_blocks.append(frame)
                        teacher_block_latched = True
                    elif not _tb:
                        teacher_block_latched = False
                    if _st == "arrived" and teacher_arrived_frame < 0:
                        teacher_arrived_frame = frame
                pred = None                       # gold is filled in below
            else:
                raw_id, pred = policy.act(row)
                raw_id = int(raw_id)

            v = _violations(raw_id, hs, free)
            for k in sums:
                sums[k] += v[k]
            act_id = safety_filter(raw_id, hs, free)
            v2 = _violations(act_id, hs, free)
            for k in post:
                post[k] += v2[k]

            if not teacher_arm:
                vel, _ = apply_reactive_safety(
                    decode_act(ACT_VOCAB[act_id]), obs,
                    policy=harness.reactive_safety, owner_orbit=False,
                    orbit_radius_m=0.0, now=obs.timestamp,
                    require_fresh_telemetry=False)

            # ---------- A1: the truth oracle -----------------------------
            stopped = (abs(vel.vx) <= 1e-6 and abs(vel.vy) <= 1e-6
                       and abs(vel.vyaw) <= 1e-6)
            hs.oracle_stop_run = hs.oracle_stop_run + 1 if stopped else 0
            inside = goal.slot > 0 and inside_goal_band(world, goal.target, x, y)
            if inside:
                # LOOSE arrival: the body reached the goal band at all, with no
                # settle requirement.  Recorded beside A1's strict arrival
                # because the gap between the two is a fact about the TEACHER.
                if goal.target not in loose_hits:
                    tr.arrivals_loose.append((frame, goal.target, goal.slot))
                loose_hits.add(goal.target)
            arrived = bool(inside and hs.oracle_stop_run >= ORACLE_SETTLE_FRAMES)
            clearance = world.truth_minimum_clearance(x, y)
            tight = math.isfinite(clearance) and clearance < block_band
            tight_stop = math.isfinite(clearance) and clearance < stop_band
            stopband_run = stopband_run + 1 if tight_stop else 0
            if stopband_run == ORACLE_SETTLE_FRAMES:
                stopband_edges.append(frame)
            hs.oracle_clear_run = hs.oracle_clear_run + 1 if tight else 0
            blocked_edge = False
            if (hs.oracle_clear_run >= ORACLE_SETTLE_FRAMES
                    and not hs.oracle_blocked_latched):
                hs.oracle_blocked_latched = True
                blocked_edge = True
            if not tight:
                hs.oracle_blocked_latched = False
            if blocked_edge:
                oracle_blocks.append(frame)
            if arrived and oracle_arrived_frame < 0:
                oracle_arrived_frame = frame

            gold = derive_event(hs, goal, frame, pending=pending, arrived=arrived,
                                blocked_edge=blocked_edge)
            if teacher_arm:
                pred = gold

            from teacher import NARR_FAMILY, SCORED_NARR_FAMILIES
            if gold != NARR_NONE and NARR_FAMILY[gold] in SCORED_NARR_FAMILIES:
                tr.gold_anchor.append((frame, int(gold)))

            hs.push_event(int(pred))
            hs.last_act_id = int(act_id)

            tr.acts.append(ACT_VOCAB[act_id])
            tr.acts_raw.append(ACT_VOCAB[raw_id])
            tr.narr_pred.append(int(pred))
            tr.narr_gold.append(int(gold))
            if goal.slot:
                gx, gy = goal.centre
                tr.rel_bearing.append(_wrap(math.atan2(gy - y, gx - x) - yaw))
            else:
                tr.rel_bearing.append(float("nan"))

            if record:
                chans.append(row)
                act_ids.append(act_id)
                narr_ids.append(int(gold))
                ann = np.zeros(N_ANN, dtype=np.int32)
                ann[ANN_INDEX["gold_narr"]] = int(gold)
                ann[ANN_INDEX["goal_slot"]] = goal.slot
                ann[ANN_INDEX["target_id"]] = TARGET_ID.get(goal.target, 0)
                ann[ANN_INDEX["inside_band"]] = int(inside)
                ann[ANN_INDEX["stopped"]] = int(stopped)
                ann[ANN_INDEX["clearance_cm"]] = int(
                    min(9999, clearance * 100) if math.isfinite(clearance) else 9999)
                ann[ANN_INDEX["owner_speaking"]] = int(bool(hs.speaking_hold))
                ann[ANN_INDEX["stop_latched"]] = int(hs.stop_latched)
                ann[ANN_INDEX["sound_anchor"]] = int(hs.sound_hold == 2)
                ann[ANN_INDEX["sound_bin"]] = (hs.sound_bin + 1) if hs.sound_hold == 2 else 0
                if goal.slot:
                    ann[ANN_INDEX["dist_m_x100"]] = int(
                        math.hypot(goal.centre[0] - x, goal.centre[1] - y) * 100)
                if tr.switch_anchor and tr.switch_anchor[-1][0] == frame:
                    ann[ANN_INDEX["switch_anchor"]] = 1
                    ann[ANN_INDEX["switch_target"]] = TARGET_ID[tr.switch_anchor[-1][1]]
                anns.append(ann)

            world.apply(vel)
            world.step()
            path_len += math.hypot(x - prev[0], y - prev[1])
            prev = (x, y)

            for attr in ("cmd_hold", "sound_hold", "gaze_hold", "speaking_hold"):
                if getattr(hs, attr):
                    setattr(hs, attr, getattr(hs, attr) - 1)
            if hs.gaze_hold == 0:
                hs.gaze_token = ""

            frame += 1
            goal_frame += 1

            nav_dead = bool(teacher_arm and teacher.nav is not None
                            and teacher.nav.done() and not hs.stop_latched)
            goal_over = arrived or nav_dead or goal_frame >= MAX_FRAMES_PER_GOAL
            if (goal_over and goal.slot == 1 and not interrupted
                    and script.kind in (KIND_REVISE, KIND_QUEUE)):
                # The owner still gets to speak: an episode whose first goal
                # ended before the scripted cue would silently drop the
                # interruption and bias the revise/queue counts.
                force_interrupt = True
                continue
            if goal_over:
                n_goals += 1
                if arrived:
                    tr.arrivals.append((frame - 1, goal.target, goal.slot))
                if goal.slot == 2 and script.kind == KIND_QUEUE:
                    pending.append(f"plan.resumed:{script.target_a}")
                    tr.resume_anchor.append((frame, script.target_a))
                    hs.cmd_hold, hs.cmd_kind = 3, "steer:resume"
                    hs.cmd_target = script.target_a
                    hs.f_cue = frame
                    resumed = True
                    hs.prev_goal = goal
                    hs.masked_goal = goal
                    hs.mask_until = frame + GOAL_MASK_FRAMES
                    goal = _goal_from(world, script.target_a, x, y, 1, frame)
                    if teacher_arm:
                        teacher.start(script.directive_a)
                    goal_frame = 0
                    hs.oracle_stop_run = 0
                    hs.last_progress_frame = frame
                else:
                    break
    finally:
        world.stop()
        if teacher is not None:
            teacher.close()

    final_target = (script.target_a if script.kind in (KIND_PLAIN, KIND_QUEUE)
                    else script.target_b)
    geo = target_geometry(world, final_target)
    band_hi = geo[1][1] if geo else 0.0
    d0 = (math.hypot(geo[0][0] - script.start[0], geo[0][1] - script.start[1])
          if geo else 1.0)
    shortest = max(0.3, d0 - band_hi)
    arrived_targets = [t for _f, t, _s in tr.arrivals]
    success = bool(arrived_targets and arrived_targets[-1] == final_target)
    # A3: task-stack-exact queue completion — goal 2 THEN goal 1, by the oracle.
    slots = [s for _f, _t, s in tr.arrivals]
    queue_stack_ok = bool(script.kind == KIND_QUEUE and slots[:2] == [2, 1])

    # A1/A10: nav.failed is a PREDICTION target stamped on the step limit.
    if not success and tr.narr_gold:
        cls = "timeout" if frame >= MAX_FRAMES_EPISODE else "not_found"
        tr.narr_gold[-1] = NARR_ID[f"nav.failed:{cls}"]
        if record:
            narr_ids[-1] = tr.narr_gold[-1]
            anns[-1][ANN_INDEX["gold_narr"]] = tr.narr_gold[-1]

    tr.frames = frame
    tr.safety = {"raw": sums, "post_filter": post}
    tr.meta = {
        "episode_id": script.episode_id, "scene_seed": script.scene_seed,
        "kind": script.kind, "target_a": script.target_a,
        "target_b": script.target_b, "final_target": final_target,
        "success": success, "arrived": arrived_targets,
        "success_loose": bool(final_target in loose_hits),
        "arrived_loose": sorted(loose_hits),
        "stopband_block_edges": stopband_edges,
        "arrival_slots": slots, "queue_stack_ok": queue_stack_ok,
        "resumed": resumed, "n_goals": n_goals,
        "collisions": int(world.collision_count),
        "path_len_m": round(path_len, 3), "shortest_m": round(shortest, 3),
        "spl": round(success * shortest / max(shortest, path_len), 4),
        "frames": frame,
        "switch_anchors": [[f, t] for f, t, _k in tr.switch_anchor],
        "had_stop_cue": bool(0 <= script.stop_frame < frame),
        "had_speaking": bool(any(sp < frame for sp in script.speak_frames)),
        "n_sound": len(tr.sound_anchor),
        "safety": tr.safety,
        # Review row: the NAVIGATOR's own mission-block / recovery notes and
        # its own "arrived" status against A1's truth-oracle latches, on the
        # same frames.  Measured, never used as a label.
        "teacher_block_edges": teacher_blocks,
        "oracle_block_edges": oracle_blocks,
        "teacher_arrived_frame": teacher_arrived_frame,
        "oracle_arrived_frame": oracle_arrived_frame,
    }
    if record:
        tr.channels = np.asarray(chans, dtype=np.int16)
        tr.acts_id = np.asarray(act_ids, dtype=np.int16)
        tr.narr_id_arr = np.asarray(narr_ids, dtype=np.int16)
        tr.ann = np.asarray(anns, dtype=np.int32)
        from teacher import NARR_FAMILY as _F
        from teacher import SCORED_NARR_FAMILIES as _S
        for i, nv in enumerate(tr.narr_id_arr):
            tr.ann[i][ANN_INDEX["gold_event"]] = int(_F[int(nv)] in _S)
        tr.meta["frames"] = len(tr.acts_id)
    return _as_rollout(tr) if record else tr


class _RolloutView:
    """``teacher.Rollout``-shaped view over a recorded trace."""

    __slots__ = ("acts", "ann", "channels", "meta", "narr", "trace")

    def __init__(self, tr: EpisodeTrace):
        self.channels = tr.channels
        self.acts = tr.acts_id
        self.narr = tr.narr_id_arr
        self.ann = tr.ann
        self.meta = tr.meta
        self.trace = tr


def _as_rollout(tr: EpisodeTrace) -> _RolloutView:
    return _RolloutView(tr)


__all__ = ["EpisodeTrace", "decode_act", "run_core", "safety_filter"]
