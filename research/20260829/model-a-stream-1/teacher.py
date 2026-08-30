"""MA-1 teacher: drive the REAL navigation stack in generated headless-city
layouts and record a state-of-the-world / act / narration stream.

Pre-registration: ``DESIGN.md`` (FROZEN) + ``AMENDMENTS.md`` (POST-START,
binding).  Amendments applied here: **A1** (gold from the truth oracle;
label-copy channels dropped or replaced by A's own state), **A2** (real MJCF
geometry variants from ``evals.nav_instruct.scene_gen.build_scene`` on MA-1's
own seed range, split by geometry seed), **A3** (5-frame goal-channel mask
after a cue), **A5** (last-60-s age/count channels), **A8** (``cmd:stop`` and
``owner_speaking`` cues), **A9** (this is a CUE-duplex model), **A10**
(terminal tokens are predictions, never receipts).

WHAT IS PRODUCT AND WHAT IS HARNESS
-----------------------------------
Product: ``DirectiveNavigator`` (grid planner, semantic resolution ladder,
search/recovery), ``apply_reactive_safety``, ``HeadlessCityWorld`` (geometry,
LiDAR, semantics, truth oracle), ``ActTokenCodec``, ``scene_gen.build_scene``.
Nothing under ``src/`` or ``evals/`` is modified; scenes are written to MA-1's
own scratch tree.

Harness: the scripted owner, the episode/queue script, the frame builder and
the event deriver.

THE FRAME IS AN OBSERVATION, NOT A LABEL (A1).  Every channel is either
(i) a pure function of the ``SimObservation`` and the active goal's geometry,
(ii) a cue the scripted owner emitted, or (iii) **A's own state** — computed
from A's own past emissions.  ``plan_step`` and ``blocked``, which the first
draft carried, are GONE: they were one-step copies of the labels.
:data:`EVAL_CHANNELS` is the exact published list.

Evidence tier: ``desktop-sim``.  No sim subprocess (the headless city is
in-process); no sockets; no hosted or VLM calls; no ``/dev/bus/usb``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np

REPO = Path(__file__).resolve().parents[3]
for p in (str(REPO / "src"), str(REPO)):
    if p not in sys.path:
        sys.path.insert(0, p)

from parcel_robot.duplex.act_codec import ActTokenCodec, default_twist_bins
from parcel_robot.models import VelocityCommand
from parcel_robot.navigation.goals import navigation_directive_from_text
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.navigation.reactive_safety import apply_reactive_safety
from parcel_robot.simulation.headless_city import (
    HeadlessCityQualityHarness,
    HeadlessCityWorld,
    _nav_observation,
)

SCRATCH = Path(os.environ.get("MA1_SCRATCH", Path.home() / ".cache/parcel-0e/ma1"))
DATA_DIR = SCRATCH / "data"
#: A2: the scene tree mirrors the repo depth so the generated MJCF's
#: ``../../../third_party`` include resolves; ``third_party`` is a symlink.
SCENE_ROOT = SCRATCH / "scenegen"
SCENE_DIR = SCENE_ROOT / "configs" / "scenes" / "generated"

FRAME_HZ = 10.0
CONTROL_DT = 0.1

# ===========================================================================
# A2 — geometry seeds.  Disjoint from the val_unseen manifests (91011-91015)
# and from the NAV evals' held-out scene, which is never loaded or named.
# ===========================================================================

SEED_TRAIN = (770_000, 770_600)     # [lo, hi)
SEED_DEV = (780_000, 780_060)
SEED_HELD = (790_000, 790_120)
RESERVED_FOREIGN_SEEDS = frozenset(range(91_000, 91_100))


def ensure_scene_tree() -> None:
    SCENE_DIR.mkdir(parents=True, exist_ok=True)
    link = SCENE_ROOT / "third_party"
    if not link.exists():
        link.symlink_to(REPO / "third_party")


def build_scene_path(seed: int) -> Path:
    """One accepted MJCF variant for ``seed``; cached on disk, byte-stable."""

    if seed in RESERVED_FOREIGN_SEEDS:
        raise ValueError(f"seed {seed} is reserved by another split")
    ensure_scene_tree()
    out = SCENE_DIR / f"ma1_{seed}.xml"
    if out.is_file():
        return out
    from evals.nav_instruct.scene_gen import build_scene

    _params, xml, _derived, _rec = build_scene(seed, scratch_dir=SCENE_DIR)
    tmp = SCENE_DIR / f".ma1_{seed}.tmp"
    tmp.write_text(xml, encoding="utf-8")
    tmp.replace(out)
    return out


def scene_manifest(seeds) -> dict:
    rows = []
    for s in sorted(seeds):
        p = build_scene_path(s)
        rows.append({"seed": s, "file": p.name,
                     "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    blob = json.dumps(rows, sort_keys=True).encode()
    return {"scenes": rows, "n": len(rows),
            "manifest_sha256": hashlib.sha256(blob).hexdigest()}


# ===========================================================================
# Act vocabulary — the PRODUCT codec.  ``<idle>`` is the codec's hold token
# (DESIGN.md writes ``<hold>``; the shipped vocabulary spells it ``<idle>``).
# ===========================================================================

CODEC = ActTokenCodec(twist=default_twist_bins(), gaze_bins=8, skills=(), emotes=(),
                      filler_gestures=0)
ACT_VOCAB = CODEC.vocabulary()
ACT_ID = {t: i for i, t in enumerate(ACT_VOCAB)}
N_ACTS = len(ACT_VOCAB)
HOLD_TOKEN = "<idle>"
HOLD_ID = ACT_ID[HOLD_TOKEN]
VX_BINS = default_twist_bins().vx_bins
VYAW_BINS = default_twist_bins().vyaw_bins
GAZE_IDS = frozenset(ACT_ID[f"<gaze_bearing_{i}>"] for i in range(8)) | {
    ACT_ID["<gaze_owner>"], ACT_ID["<gaze_release>"]}

# ===========================================================================
# Target vocabulary — the generated scenes' own semantic LABELS.  Generic
# class words; nothing from the learned map (which `_curiosity_admitted_names`
# governs) and nothing that names a NAV-eval scene.
#
# ``tree`` and ``door`` are OUT, measured: on 16 plain episodes each the
# shipped teacher reached the tree 0/16 and the door 0/16 (the door does not
# exist in generated variants at all).  A vocabulary the teacher cannot
# demonstrate teaches the student to wander; the measurement is in RESULTS.md.
# ===========================================================================

TARGETS = ("bench", "lamppost", "planter", "sidewalk", "crosswalk")
OBJECT_TARGET_ID = {"bench": "bench_1", "lamppost": "lamp_post_1",
                    "planter": "planter_1"}
TARGET_ID = {t: i + 1 for i, t in enumerate(TARGETS)}

BLOCK_CLASSES = ("obstacle", "stalled", "unroutable")
FAIL_CLASSES = ("timeout", "unroutable", "not_found")


def _build_narration_vocab() -> tuple[str, ...]:
    v = ["none"]
    v += [f"nav.start:{t}" for t in TARGETS]
    v += ["nav.progress"]
    v += [f"nav.blocked:{c}" for c in BLOCK_CLASSES]
    v += ["nav.replan"]
    v += [f"nav.arrived:{t}" for t in TARGETS]
    v += [f"nav.failed:{c}" for c in FAIL_CLASSES]
    v += [f"plan.revised:{t}" for t in TARGETS]
    v += [f"plan.queued:{t}" for t in TARGETS]
    v += [f"plan.resumed:{t}" for t in TARGETS]
    v += [f"attend.sound:{b}" for b in range(8)]
    v += ["attend.owner"]
    return tuple(v)


NARR_VOCAB = _build_narration_vocab()
NARR_ID = {t: i for i, t in enumerate(NARR_VOCAB)}
N_NARR = len(NARR_VOCAB)
NARR_NONE = NARR_ID["none"]
NARR_FAMILY = tuple(t.split(":")[0] for t in NARR_VOCAB)

#: H-MA1c's bar applies to these.  A7 partitions them.
SCORED_NARR_FAMILIES = ("nav.start", "nav.arrived", "nav.blocked",
                        "plan.revised", "plan.queued", "plan.resumed")
#: A7: product-backed (a live-runtime receipt exists) vs research-only.
PRODUCT_BACKED_FAMILIES = ("nav.arrived", "nav.blocked")
RESEARCH_ONLY_FAMILIES = ("nav.start", "plan.revised", "plan.queued",
                          "plan.resumed")
#: A7: INTERNAL-ONLY — never a narration claim (the whisperer's NEVER band).
INTERNAL_ONLY_FAMILIES = ("nav.progress",)

# ===========================================================================
# Frame schema (A1: the EXACT published list).
# ===========================================================================

HIST_K = 6

DLG = ("idle", "listening", "thinking", "speaking")
CUE = ("none", "owner_speaking", "call_name")
CUE_CONF = ("none", "lo", "mid", "hi")
VAL = ("-2", "-1", "0", "1", "2")
ARO = ("0", "1", "2")
OWN_VIS = ("visible", "occluded", "unknown")
OWN_DIST = ("near", "mid", "far", "unknown")
OWN_BEAR = tuple(f"b{i}" for i in range(8)) + ("unknown",)
OWN_GAZE = ("at_dog", "away", "unknown")
OWN_MOTION = ("still", "walking", "approaching", "leaving")
T_SINCE_SEEN = ("lt1s", "1_3s", "3_8s", "8_20s", "gt20s")
SELF_ACT = ("idle", "navigating", "hold", "looking")
BASE_BUSY = ("free", "busy", "critical")
LOC_HEALTH = ("ok", "degraded", "lost")
ENV = ("kitchen", "living", "hall", "outdoor")
PEOPLE = ("0", "1", "2+")

GOAL_KIND = ("none", "object", "region", "relative", "unknown")
GOAL_TARGET = ("none",) + TARGETS
BEAR8 = tuple(f"b{i}" for i in range(8)) + ("unknown",)
DIST5 = ("d0", "d1", "d2", "d3", "d4", "unknown")
FREE3 = ("blocked", "near", "free")
PROGRESS = ("p0", "p1", "p2", "p3", "p4", "unknown")
REPLAN = ("0", "1", "2", "3+")
CMD = ("none", "cmd:go_to", "cmd:revise", "cmd:queue", "cmd:stop", "steer:resume")
SOUND = ("none",) + tuple(f"b{i}" for i in range(8))
STOP_STATE = ("running", "stopped")
#: A5 — the last minute, explicitly.
AGE = ("never", "lt1s", "1_3s", "3_8s", "8_20s", "20_60s", "gt60s")
COUNT60 = ("0", "1", "2", "3_5", "6+")

CHANNELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # (a) BM-1 social block — constant/idle in this venue except the owner
    #     channels and the cue, which are real.
    ("dlg", DLG), ("cue", CUE), ("cue_conf", CUE_CONF), ("val", VAL),
    ("aro", ARO), ("own_vis", OWN_VIS), ("own_dist", OWN_DIST),
    ("own_bear", OWN_BEAR), ("own_gaze", OWN_GAZE), ("own_motion", OWN_MOTION),
    ("t_since_seen", T_SINCE_SEEN), ("base_busy", BASE_BUSY),
    ("loc_health", LOC_HEALTH), ("env", ENV), ("people", PEOPLE),
    # (b) navigation OBSERVATION — goal geometry + the LiDAR free-space ring.
    ("goal_kind", GOAL_KIND), ("goal_target", GOAL_TARGET),
    ("goal_bear", BEAR8), ("goal_dist", DIST5), ("progress", PROGRESS),
) + tuple((f"free{i}", FREE3) for i in range(8)) + (
    # (c) A's OWN state — computed from A's own past emissions, never a label.
    ("self_act", SELF_ACT), ("stop_state", STOP_STATE), ("replan_own", REPLAN),
    ("since_blocked", AGE), ("since_replan", AGE), ("since_cue", AGE),
    ("since_sound", AGE), ("since_owner", AGE),
    ("n_blocks_60", COUNT60), ("n_replans_60", COUNT60),
    # (d) cues the scripted owner / the world emitted.
    ("cmd", CMD), ("cmd_target", GOAL_TARGET), ("sound", SOUND),
) + tuple((f"hist{i}", NARR_VOCAB) for i in range(HIST_K))

CHANNEL_NAMES = tuple(n for n, _ in CHANNELS)
CHANNEL_SIZES = tuple(len(v) for _, v in CHANNELS)
CHANNEL_INDEX = {n: i for i, n in enumerate(CHANNEL_NAMES)}
N_CHANNELS = len(CHANNELS)
_VAL_ID = {n: {v: i for i, v in enumerate(vals)} for n, vals in CHANNELS}

#: A1 — the EXACT channel list available at closed-loop eval, by provenance.
EVAL_CHANNELS = {
    "observation": [
        "own_vis", "own_dist", "own_bear", "goal_kind", "goal_target",
        "goal_bear", "goal_dist", "progress", *[f"free{i}" for i in range(8)],
    ],
    "owner_cue": ["dlg", "cue", "cue_conf", "cmd", "cmd_target", "sound"],
    "A_own_state": [
        "self_act", "stop_state", "replan_own", "since_blocked", "since_replan",
        "since_cue", "since_sound", "since_owner", "n_blocks_60",
        "n_replans_60", *[f"hist{i}" for i in range(HIST_K)],
    ],
    "constant_in_this_venue": ["val", "aro", "own_gaze", "own_motion",
                              "t_since_seen", "base_busy", "loc_health",
                              "env", "people"],
    "dropped_by_A1": ["plan_step (encoded the arrival label)",
                      "blocked (encoded the nav.blocked label)",
                      "replan (teacher-side count; replaced by replan_own)"],
}

ANN_COLS = ("gold_narr", "gold_event", "goal_slot", "target_id",
            "switch_anchor", "switch_target", "sound_anchor", "sound_bin",
            "dist_m_x100", "inside_band", "stopped", "clearance_cm",
            "owner_speaking", "stop_latched")
ANN_INDEX = {n: i for i, n in enumerate(ANN_COLS)}
N_ANN = len(ANN_COLS)

SWITCH_WINDOW_FRAMES = 10     # H-MA1b: 1.0 s
NARR_WINDOW_FRAMES = 10       # H-MA1c: 1.0 s, CAUSAL (A4)
SOUND_WINDOW_FRAMES = 5       # H-MA1d: 0.5 s
GOAL_MASK_FRAMES = 5          # A3
ORACLE_SETTLE_FRAMES = 5      # A1: "stopped >= 5 frames" / "blocked >= 5"
PROGRESS_EVERY_FRAMES = 50
STALL_WINDOW_S = 3.0
STALL_MIN_M = 0.25

JITTER_M = 0.0                # A2: geometry varies by SCENE, not by jitter
START_MIN_M = 2.5
START_MAX_M = 9.5
START_YAW_NOISE = 0.7
MAX_FRAMES_PER_GOAL = 420
MAX_FRAMES_EPISODE = 1000
P_STOP_CUE = 0.12             # A8
P_OWNER_SPEAKING = 0.15       # A8


def _wrap(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def bearing_bin(rel: float) -> int:
    return round((_wrap(rel) % (2.0 * math.pi)) / (2.0 * math.pi) * 8) % 8


def dist_bin(d: float) -> int:
    for i, edge in enumerate((1.0, 2.5, 5.0, 9.0)):
        if d < edge:
            return i
    return 4


def age_bin(frames: int | None) -> str:
    if frames is None:
        return "never"
    s = frames * CONTROL_DT
    for edge, name in ((1.0, "lt1s"), (3.0, "1_3s"), (8.0, "3_8s"),
                       (20.0, "8_20s"), (60.0, "20_60s")):
        if s < edge:
            return name
    return "gt60s"


def count_bin(n: int) -> str:
    if n <= 2:
        return str(n)
    return "3_5" if n <= 5 else "6+"


def free_sectors(obs) -> list[int]:
    """8 x 45 deg minimum-range sectors from the venue's planar LiDAR."""

    ranges = obs.lidar_ranges
    if not ranges:
        return [2] * 8
    n = len(ranges)
    a0 = float(obs.lidar_angle_min_rad or -math.pi)
    inc = float(obs.lidar_angle_increment_rad or (2.0 * math.pi / n))
    rmax = float(obs.lidar_range_max_m or 30.0)
    mins = [rmax] * 8
    for i in range(n):
        r = float(ranges[i])
        if not math.isfinite(r) or r <= 0.0:
            continue
        s = bearing_bin(a0 + i * inc)
        mins[s] = min(mins[s], r)
    return [0 if m < 1.0 else (1 if m < 2.5 else 2) for m in mins]


# ===========================================================================
# Goal geometry / the truth-oracle predicates (A1)
# ===========================================================================


def target_geometry(world, target: str):
    if target in OBJECT_TARGET_ID:
        oid = OBJECT_TARGET_ID[target]
        for item in world._object_specs:
            if str(item["id"]) == oid:
                meta = dict(item.get("metadata") or {})
                region = dict(meta.get("goal_region") or {})
                band = region.get("band_m") or (
                    0.0, float(meta.get("vicinity_radius_m", 1.2)))
                return ((float(item["position"][0]), float(item["position"][1])),
                        (float(band[0]), float(band[1])), "object")
        return None
    for item in world._region_specs:
        if str(item["label"]) == target:
            poly = [(float(x), float(y)) for x, y in item["polygon"]]
            return ((sum(p[0] for p in poly) / len(poly),
                     sum(p[1] for p in poly) / len(poly)), (0.0, 0.0), "region")
    return None


def inside_goal_band(world, target: str, x: float, y: float) -> bool:
    """The harness's OWN region predicate — the truth oracle (A1)."""

    if target in OBJECT_TARGET_ID:
        geo = target_geometry(world, target)
        if geo is None:
            return False
        (cx, cy), (lo, hi), _ = geo
        return lo <= math.hypot(x - cx, y - cy) <= hi
    for item in world._region_specs:
        if str(item["label"]) == target:
            try:
                if world.truth_inside_region((x, y), str(item["id"])):
                    return True
            except KeyError:
                continue
    return False


# ===========================================================================
# Harness state (all of it A's own, or a cue, or the world)
# ===========================================================================


@dataclass
class GoalState:
    target: str = ""
    kind: str = "none"
    centre: tuple[float, float] = (0.0, 0.0)
    band: tuple[float, float] = (0.0, 0.0)
    dist0_m: float = 1.0
    slot: int = 0
    started_frame: int = 0


@dataclass
class HarnessState:
    hist: list = field(default_factory=lambda: [NARR_NONE] * HIST_K)
    # --- cues ---------------------------------------------------------------
    cmd_hold: int = 0
    cmd_kind: str = "none"
    cmd_target: str = ""
    sound_hold: int = 0
    sound_bin: int = -1
    speaking_hold: int = 0
    stop_latched: bool = False
    # --- A's own state ------------------------------------------------------
    last_act_id: int = HOLD_ID
    gaze_hold: int = 0
    gaze_token: str = ""
    own_blocks: int = 0
    own_replans: int = 0
    block_frames: list = field(default_factory=list)
    replan_frames: list = field(default_factory=list)
    f_blocked: int | None = None
    f_replan: int | None = None
    f_cue: int | None = None
    f_sound: int | None = None
    f_owner: int | None = None
    # --- the truth-oracle latches (GOLD ONLY, never a channel) --------------
    oracle_clear_run: int = 0
    oracle_stop_run: int = 0
    oracle_blocked_latched: bool = False
    oracle_stall_run: int = 0
    last_progress_frame: int = 0
    masked_goal: GoalState = field(default_factory=GoalState)
    mask_until: int = -1
    prev_goal: GoalState = field(default_factory=GoalState)

    def push_event(self, narr_id: int) -> None:
        if narr_id != NARR_NONE:
            self.hist = ([int(narr_id)] + self.hist)[:HIST_K]


def update_own_state(hs: HarnessState, obs, frame: int, act_id: int) -> None:
    """A's own state: everything here is a function of A's own emissions."""

    hs.last_act_id = int(act_id)
    hs.block_frames = [f for f in hs.block_frames if frame - f <= 600]
    hs.replan_frames = [f for f in hs.replan_frames if frame - f <= 600]


def update_oracle(hs: HarnessState, world, obs, goal: GoalState, frame: int,
                  vel, stop_band_m: float) -> tuple[bool, bool]:
    """A1's truth-oracle latches.  Returns (arrived_now, blocked_edge).

    * arrived — truth pose inside the goal region AND stopped >= 5 frames.
    * blocked — truth minimum clearance below the reactive-safety stop band
      for >= 5 frames (rising edge only).
    """

    x, y = float(obs.robot.x), float(obs.robot.y)
    stopped = (abs(vel.vx) <= 1e-6 and abs(vel.vy) <= 1e-6
               and abs(vel.vyaw) <= 1e-6)
    hs.oracle_stop_run = hs.oracle_stop_run + 1 if stopped else 0
    inside = goal.slot > 0 and inside_goal_band(world, goal.target, x, y)
    arrived = bool(inside and hs.oracle_stop_run >= ORACLE_SETTLE_FRAMES)

    clearance = world.truth_minimum_clearance(x, y)
    tight = math.isfinite(clearance) and clearance < stop_band_m
    hs.oracle_clear_run = hs.oracle_clear_run + 1 if tight else 0
    edge = False
    if hs.oracle_clear_run >= ORACLE_SETTLE_FRAMES and not hs.oracle_blocked_latched:
        hs.oracle_blocked_latched = True
        edge = True
    if not tight:
        hs.oracle_blocked_latched = False
    return arrived, edge


def build_frame(obs, goal: GoalState, hs: HarnessState, frame: int,
                free: list) -> np.ndarray:
    """A1: observation + cue + A's own state.  No label copies."""

    row = np.zeros(N_CHANNELS, dtype=np.int16)

    def put(name: str, value: str) -> None:
        row[CHANNEL_INDEX[name]] = _VAL_ID[name][value]

    x, y, yaw = float(obs.robot.x), float(obs.robot.y), float(obs.robot.yaw)

    put("dlg", "listening" if (hs.cmd_hold or hs.speaking_hold) else "idle")
    put("cue", "owner_speaking" if hs.speaking_hold else "none")
    put("cue_conf", "hi" if (hs.cmd_hold or hs.speaking_hold) else "none")
    put("val", "0"); put("aro", "1"); put("own_gaze", "unknown")
    put("own_motion", "still"); put("t_since_seen", "lt1s")
    put("loc_health", "ok"); put("env", "outdoor"); put("people", "0")
    put("base_busy", "busy" if goal.slot else "free")

    ox, oy = float(obs.owner.x), float(obs.owner.y)
    od = math.hypot(ox - x, oy - y)
    orel = _wrap(math.atan2(oy - y, ox - x) - yaw)
    visible = abs(orel) < 1.05 and od < 14.0
    put("own_vis", "visible" if visible else "occluded")
    put("own_dist", "near" if od < 2.0 else ("mid" if od < 5.0 else "far"))
    put("own_bear", f"b{bearing_bin(orel)}")
    if visible:
        hs.f_owner = frame

    for i in range(8):
        row[CHANNEL_INDEX[f"free{i}"]] = free[i]

    # --- A3: the goal channels LAG the cue by GOAL_MASK_FRAMES -------------
    shown = hs.masked_goal if frame < hs.mask_until else goal
    if shown.slot and not hs.stop_latched:
        gx, gy = shown.centre
        d = math.hypot(gx - x, gy - y)
        rel = _wrap(math.atan2(gy - y, gx - x) - yaw)
        put("goal_kind", shown.kind)
        put("goal_target", shown.target)
        put("goal_bear", f"b{bearing_bin(rel)}")
        put("goal_dist", f"d{dist_bin(d)}")
        p = (0.0 if shown.dist0_m <= 1e-6
             else max(0.0, min(1.0, 1.0 - d / shown.dist0_m)))
        put("progress", f"p{min(4, int(p * 5))}")
    else:
        put("goal_kind", "none"); put("goal_target", "none")
        put("goal_bear", "unknown"); put("goal_dist", "unknown")
        put("progress", "unknown")

    # --- A's own state -----------------------------------------------------
    if hs.gaze_hold or hs.last_act_id in GAZE_IDS:
        put("self_act", "looking")
    elif hs.stop_latched or hs.last_act_id == HOLD_ID:
        put("self_act", "hold" if goal.slot else "idle")
    else:
        put("self_act", "navigating")
    put("stop_state", "stopped" if hs.stop_latched else "running")
    put("replan_own", "3+" if hs.own_replans >= 3 else str(hs.own_replans))
    put("since_blocked", age_bin(None if hs.f_blocked is None else frame - hs.f_blocked))
    put("since_replan", age_bin(None if hs.f_replan is None else frame - hs.f_replan))
    put("since_cue", age_bin(None if hs.f_cue is None else frame - hs.f_cue))
    put("since_sound", age_bin(None if hs.f_sound is None else frame - hs.f_sound))
    put("since_owner", age_bin(None if hs.f_owner is None else frame - hs.f_owner))
    put("n_blocks_60", count_bin(sum(1 for f in hs.block_frames if frame - f <= 600)))
    put("n_replans_60", count_bin(sum(1 for f in hs.replan_frames if frame - f <= 600)))

    put("cmd", hs.cmd_kind if hs.cmd_hold else "none")
    put("cmd_target", hs.cmd_target if (hs.cmd_hold and hs.cmd_target) else "none")
    put("sound", f"b{hs.sound_bin}" if hs.sound_hold and hs.sound_bin >= 0 else "none")
    for i in range(HIST_K):
        row[CHANNEL_INDEX[f"hist{i}"]] = hs.hist[i]
    return row


def derive_event(hs: HarnessState, goal: GoalState, frame: int, *,
                 pending: list, arrived: bool, blocked_edge: bool) -> int:
    """THE gold deriver (A1).  Identical in the teacher and in closed loop.

    Priority: scripted cue events > oracle arrival > oracle block > replan >
    progress.  ``nav.failed`` is stamped by the caller on the step limit.

    A1, tightened after review: ``nav.blocked`` fires ONLY from the truth
    oracle (minimum clearance below the reactive-safety stop band for >= 5
    frames).  A harness-side "stalled for 3 s" class was CUT: it fired while
    the robot was accelerating away with a clear forward sector, and it was
    not oracle-derived, so it could not be gold.  ``nav.blocked:stalled`` and
    ``nav.blocked:unroutable`` stay in the vocabulary with ZERO support.
    """

    if pending:
        return NARR_ID[pending.pop(0)]
    if arrived and goal.slot:
        return NARR_ID[f"nav.arrived:{goal.target}"]
    if blocked_edge:
        hs.own_blocks += 1
        hs.block_frames.append(frame)
        hs.f_blocked = frame
        return NARR_ID["nav.blocked:obstacle"]
    if (hs.f_blocked is not None and frame - hs.f_blocked == 30
            and goal.slot and not hs.stop_latched):
        hs.own_replans += 1
        hs.replan_frames.append(frame)
        hs.f_replan = frame
        return NARR_ID["nav.replan"]
    if (goal.slot and not hs.stop_latched
            and frame - hs.last_progress_frame >= PROGRESS_EVERY_FRAMES):
        hs.last_progress_frame = frame
        return NARR_ID["nav.progress"]
    return NARR_NONE


# ===========================================================================
# Episode script
# ===========================================================================

KIND_PLAIN, KIND_REVISE, KIND_QUEUE = "plain", "revise", "queue"


@dataclass
class EpisodeScript:
    episode_id: int
    scene_seed: int
    kind: str
    target_a: str
    target_b: str
    start: tuple = (0.0, 0.0, 0.0)
    interrupt_at: float = 0.4
    sound_frames: tuple = ()
    sound_bins: tuple = ()
    stop_frame: int = -1
    stop_len: int = 0
    speak_frames: tuple = ()
    speak_lens: tuple = ()

    @property
    def directive_a(self) -> str:
        return f"go to the {self.target_a}"

    @property
    def directive_b(self) -> str:
        return f"go to the {self.target_b}"

    @property
    def owner_text_b(self) -> str:
        return (f"go to the {self.target_b}" if self.kind == KIND_REVISE
                else f"after that, go to the {self.target_b}")


def sample_script(episode_id: int, scene_seed: int, master_seed: int,
                  force_kind: str | None = None) -> EpisodeScript:
    rng = random.Random((master_seed * 1_000_003) ^ (episode_id * 7919))
    r = rng.random()
    kind = KIND_PLAIN if r < 0.60 else (KIND_REVISE if r < 0.80 else KIND_QUEUE)
    if force_kind is not None:
        kind = force_kind
    ta = rng.choice(TARGETS)
    tb = rng.choice([t for t in TARGETS if t != ta])
    n_sound = 0 if rng.random() < 0.6 else rng.randint(1, 2)
    sf = tuple(sorted(rng.randint(30, 300) for _ in range(n_sound)))
    sb = tuple(rng.randint(0, 7) for _ in range(n_sound))
    stop_f, stop_l = -1, 0
    if rng.random() < P_STOP_CUE:                      # A8
        stop_f = rng.randint(40, 260)
        stop_l = rng.randint(20, 45)
    n_sp = 1 if rng.random() < P_OWNER_SPEAKING else 0  # A8
    spf = tuple(sorted(rng.randint(25, 300) for _ in range(n_sp)))
    spl = tuple(rng.randint(10, 25) for _ in range(n_sp))
    return EpisodeScript(episode_id=episode_id, scene_seed=scene_seed, kind=kind,
                         target_a=ta, target_b=tb,
                         interrupt_at=rng.uniform(0.25, 0.6),
                         sound_frames=sf, sound_bins=sb, stop_frame=stop_f,
                         stop_len=stop_l, speak_frames=spf, speak_lens=spl)


def prepare_episode(world, script: EpisodeScript) -> EpisodeScript:
    """Sample a start pose ON this scene's geometry."""

    rng = random.Random((script.scene_seed * 2_654_435_761) ^ script.episode_id)
    geo = target_geometry(world, script.target_a)
    cx, cy = geo[0] if geo else (0.0, 0.0)
    start = (0.0, 0.0, 0.0)
    for _ in range(1200):
        x = rng.uniform(-6.6, 6.6)
        y = rng.uniform(-3.0, 1.6)
        if world.truth_minimum_clearance(x, y) <= 0.7:
            continue
        d = math.hypot(cx - x, cy - y)
        if not (START_MIN_M <= d <= START_MAX_M):
            continue
        start = (x, y, _wrap(math.atan2(cy - y, cx - x)
                             + rng.uniform(-START_YAW_NOISE, START_YAW_NOISE)))
        break
    return replace(script, start=start)


# ===========================================================================
# The teacher (product stack)
# ===========================================================================


class _Teacher:
    def __init__(self, harness):
        self.h = harness
        self.nav = None
        self.mission = None
        self.pose_provider = None

    def start(self, directive: str):
        if self.nav is not None:
            self.nav.close()
        self.nav = DirectiveNavigator.from_config(self.h.navigation_config)
        self.mission = self.nav.start(
            navigation_directive_from_text(directive) or directive)
        self.pose_provider = self.h.new_pose_provider()
        return self.mission

    def step(self, world, obs):
        cmd = self.nav.step(_nav_observation(
            obs, measured_velocity=world.command, stop_confirmed=world.stopped,
            settled_linear_speed_mps=self.h._settled_linear_speed_mps,
            settled_yaw_speed_rad_s=self.h._settled_yaw_speed_rad_s,
            pose_provider=self.pose_provider))
        requested = (VelocityCommand() if cmd.stop
                     else VelocityCommand(cmd.vx, cmd.vy, cmd.vyaw))
        vel, _ = apply_reactive_safety(
            requested, obs, policy=self.h.reactive_safety, owner_orbit=False,
            orbit_radius_m=0.0, now=obs.timestamp, require_fresh_telemetry=False)
        return cmd, vel

    def close(self):
        if self.nav is not None:
            self.nav.close()
            self.nav = None


def _goal_from(world, target: str, x: float, y: float, slot: int,
               frame: int) -> GoalState:
    geo = target_geometry(world, target)
    if geo is None:
        return GoalState()
    (cx, cy), band, kind = geo
    return GoalState(target=target, kind=kind, centre=(cx, cy), band=band,
                     dist0_m=max(0.5, math.hypot(cx - x, cy - y)), slot=slot,
                     started_frame=frame)


#: ``<twist:1:2>`` is vx = 0, vyaw = 0 — the same body state as ``<idle>``.
#: Two tokens for one behaviour is label noise, so the zero twist is folded
#: into the codec's hold token everywhere.
ZERO_TWIST = "<twist:1:2>"


def canon_act(token: str) -> str:
    return HOLD_TOKEN if token == ZERO_TWIST else token


def act_token_for(vel, hs: HarnessState) -> str:
    if hs.gaze_hold and hs.gaze_token:
        return hs.gaze_token
    if abs(vel.vx) <= 1e-6 and abs(vel.vy) <= 1e-6 and abs(vel.vyaw) <= 1e-6:
        return HOLD_TOKEN
    return canon_act(CODEC.encode_twist(vel.vx, vel.vyaw))


@dataclass
class Rollout:
    channels: np.ndarray
    acts: np.ndarray
    narr: np.ndarray
    ann: np.ndarray
    meta: dict


def rollout_episode(world, harness, script: EpisodeScript) -> Rollout:
    """Drive the product stack and record the stream (open loop, the teacher)."""

    from closed_loop_core import run_core
    return run_core(world, harness, script, policy=None, teacher_arm=True,
                    record=True)


# ===========================================================================
# Generation driver
# ===========================================================================

_W = {}
_H = {}


def _world_for(seed: int):
    if seed not in _W:
        if len(_W) > 3:                     # keep the process small
            _W.clear(); _H.clear()
        path = build_scene_path(seed)
        w = HeadlessCityWorld(scene=path)
        _W[seed] = w
        _H[seed] = HeadlessCityQualityHarness(w)
    return _W[seed], _H[seed]


def _worker(args):
    episode_id, scene_seed, master_seed, force_kind = args
    try:
        w, h = _world_for(scene_seed)
        s = prepare_episode(w, sample_script(episode_id, scene_seed, master_seed,
                                             force_kind))
        r = rollout_episode(w, h, s)
        return (r.channels, r.acts, r.narr, r.ann, r.meta)
    except Exception as exc:  # noqa: BLE001
        import traceback
        return ("ERROR", (f"{type(exc).__name__}: {exc}\n"
                f"{traceback.format_exc()[-900:]}"), episode_id, scene_seed, {})


def generate_split(name: str, episode_ids, scene_seeds, master_seed: int,
                   workers: int = 24, kinds=None) -> dict:
    import multiprocessing as mp

    kinds = kinds or [None] * len(episode_ids)
    args = [(e, s, master_seed, k)
            for e, s, k in zip(episode_ids, scene_seeds, kinds, strict=True)]
    out, errors = [], []
    t0 = time.time()
    with mp.get_context("spawn").Pool(workers) as pool:
        for i, res in enumerate(pool.imap_unordered(_worker, args, chunksize=1)):
            if isinstance(res[0], str) and res[0] == "ERROR":
                errors.append(res[1])
                continue
            out.append(res)
            if (i + 1) % 250 == 0:
                print(f"  [{name}] {i+1}/{len(args)} {time.time()-t0:.0f}s",
                      flush=True)
    out.sort(key=lambda r: r[4]["episode_id"])
    lens = np.array([len(r[1]) for r in out], dtype=np.int64)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        DATA_DIR / f"{name}.npz",
        channels=np.concatenate([r[0] for r in out]),
        acts=np.concatenate([r[1] for r in out]),
        narr=np.concatenate([r[2] for r in out]),
        ann=np.concatenate([r[3] for r in out]),
        ep_start=np.concatenate([[0], np.cumsum(lens)[:-1]]),
        ep_len=lens,
        ep_scene=np.array([m["scene_seed"] for m in (r[4] for r in out)],
                          dtype=np.int64),
        ep_kind=np.array([{"plain": 0, "revise": 1, "queue": 2}[r[4]["kind"]]
                          for r in out], dtype=np.int8),
    )
    (DATA_DIR / f"{name}_meta.json").write_text(json.dumps([r[4] for r in out]))
    return {"split": name, "episodes": len(out), "frames": int(lens.sum()),
            "errors": len(errors), "error_sample": errors[:2],
            "wall_s": round(time.time() - t0, 1)}


def split_plan(a) -> list:
    def take(rng_pair, n):
        lo, hi = rng_pair
        pool = list(range(lo, hi))
        return [pool[i % len(pool)] for i in range(n)]
    # A4: the held-out split forces an EQUAL kind mix so every scored class
    # reaches its >= 200-event floor without inflating the episode count.
    held_kinds = [(KIND_PLAIN, KIND_REVISE, KIND_QUEUE)[i % 3] for i in range(a.held)]
    return [
        ("train", list(range(a.train)), take(SEED_TRAIN, a.train), None),
        ("dev", list(range(a.train, a.train + a.dev)), take(SEED_DEV, a.dev), None),
        ("held", list(range(a.train + a.dev, a.train + a.dev + a.held)),
         take(SEED_HELD, a.held), held_kinds),
    ]


def write_sample_episodes(path: Path, master_seed: int) -> None:
    seed = SEED_TRAIN[0]
    w, h = _world_for(seed)
    lines = ["MA-1 sample episodes — 30-frame excerpts (10 Hz)",
             (f"scene: generated MJCF variant seed {seed} "
             f"({build_scene_path(seed).name}); act vocab {N_ACTS}; "
             f"narration vocab {N_NARR}; {N_CHANNELS} channels"),
             "channels: " + " ".join(CHANNEL_NAMES), ""]
    wanted = {KIND_PLAIN: None, KIND_REVISE: None, KIND_QUEUE: None}
    eid = 0
    while any(v is None for v in wanted.values()) and eid < 400:
        s = sample_script(eid, seed, master_seed)
        if wanted.get(s.kind) is None:
            wanted[s.kind] = s
        eid += 1
    key = ["goal_target", "goal_bear", "goal_dist", "progress", "cmd",
           "cmd_target", "sound", "stop_state", "self_act", "since_blocked",
           "free0", "free1", "free7", "hist0"]
    for kind, s in wanted.items():
        if s is None:
            continue
        s = prepare_episode(w, s)
        r = rollout_episode(w, h, s)
        n = len(r.acts)
        anchor = max(0, (r.meta["switch_anchors"][0][0] - 5)
                     if r.meta["switch_anchors"] else 0)
        lines.append(f"=== kind={kind} ep={s.episode_id} scene={s.scene_seed} "
                     f"A={s.target_a} B={s.target_b} frames={n} "
                     f"success={r.meta['success']} arrived={r.meta['arrived']} "
                     f"coll={r.meta['collisions']} ===")
        lines.append(f"    owner t=0.0s: {s.directive_a!r}   (cue cmd:go_to)")
        if kind != KIND_PLAIN and r.meta["switch_anchors"]:
            fr = r.meta["switch_anchors"][0][0]
            lines.append(f"    owner t={fr*CONTROL_DT:.1f}s: {s.owner_text_b!r}"
                         f"   (cue {'cmd:revise' if kind==KIND_REVISE else 'cmd:queue'};"
                         f" goal channels masked for {GOAL_MASK_FRAMES} frames)")
        for i, sf in enumerate(s.sound_frames):
            if sf < n:
                lines.append(f"    sound  t={sf*CONTROL_DT:.1f}s bearing bin "
                             f"{s.sound_bins[i]}")
        if 0 <= s.stop_frame < n:
            lines.append(f"    owner t={s.stop_frame*CONTROL_DT:.1f}s: 'stop'  "
                         f"(held {s.stop_len} frames, then re-issued)")
        for i, sp in enumerate(s.speak_frames):
            if sp < n:
                lines.append(f"    owner t={sp*CONTROL_DT:.1f}s: speaking for "
                             f"{s.speak_lens[i]} frames")
        lines.append("  frame   t(s)  act                narration           " +
                     " ".join(f"{c:>12s}" for c in key))
        for f in range(anchor, min(n, anchor + 30)):
            row = r.channels[f]
            vals = [f"{CHANNELS[CHANNEL_INDEX[c]][1][row[CHANNEL_INDEX[c]]]:>12s}"
                    for c in key]
            lines.append(f"  {f:5d} {f*CONTROL_DT:6.1f}  "
                         f"{ACT_VOCAB[r.acts[f]]:<18s} "
                         f"{NARR_VOCAB[r.narr[f]]:<19s} " + " ".join(vals))
        lines.append("")
    path.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=20260829)
    ap.add_argument("--train", type=int, default=3000)
    ap.add_argument("--dev", type=int, default=300)
    ap.add_argument("--held", type=int, default=200)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--sample-only", action="store_true")
    a = ap.parse_args()
    if a.sample_only:
        write_sample_episodes(Path(__file__).parent / "sample_episodes.txt", a.seed)
        return
    stats = {}
    for name, eids, seeds, kinds in split_plan(a):
        stats[name] = generate_split(name, eids, seeds, a.seed,
                                     workers=a.workers, kinds=kinds)
        print(json.dumps(stats[name]), flush=True)
    (DATA_DIR / "gen_stats.json").write_text(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
