"""MA-1 runner.  ``run.py --all --seed 20260829`` -> results.json + RESULTS.md.

RESULTS.md is written INCREMENTALLY, one stage at a time, so a killed process
still leaves the stages that finished.

Host discipline (research/20260829/README.md, 15:41 additions):
  * no sim subprocess is launched — the headless city is in-process.  The only
    child processes are this file's own multiprocessing Pool workers; they are
    joined, and :func:`_reap_process_group` proves the group is empty at exit.
  * every training job is gated on ``nvidia-smi`` reporting >= 14 GB free
    (our own cap stays 12 GB), polled every 60 s, and the reading is recorded.
  * no sockets, no /dev/bus/usb, no hosted calls, no VLM, no git writes.
  * ``PARCEL_MEMORY_PATH`` is pointed at a scratch file before any product
    import, so the owner's memory store is never opened.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRATCH = Path(os.environ.get("MA1_SCRATCH", Path.home() / ".cache/parcel-0e/ma1"))
os.environ.setdefault("MA1_SCRATCH", str(SCRATCH))
os.environ.setdefault("PARCEL_MEMORY_PATH", str(SCRATCH / "scratch_memory.sqlite3"))
os.environ.pop("PARCEL_MEMORY_PURPOSE", None)
os.environ.setdefault("OPENBLAS_NUM_THREADS", "32")
os.environ.setdefault("OMP_NUM_THREADS", "8")

import numpy as np

sys.path.insert(0, str(HERE))

RESULTS_MD = HERE / "RESULTS.md"
RESULTS_JSON = HERE / "results.json"
DATA_DIR = SCRATCH / "data"
LOG = SCRATCH / "logs" / "run.log"

_STATE: dict = {}

# ===========================================================================
# plumbing
# ===========================================================================


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def md(text: str = "") -> None:
    """Append to RESULTS.md immediately."""

    with RESULTS_MD.open("a") as fh:
        fh.write(text + "\n")


def _amendments() -> dict:
    """DESIGN.md said an AMENDMENTS.md may appear; check before EVERY row."""

    p = HERE / "AMENDMENTS.md"
    if p.is_file():
        body = p.read_text()
        return {"exists": True, "bytes": len(body), "sha_head": body[:400]}
    return {"exists": False}


def gpu_free_mb() -> list[int]:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30, check=True).stdout
        return [int(v.strip()) for v in out.splitlines() if v.strip()]
    except Exception as exc:  # noqa: BLE001
        log(f"nvidia-smi unavailable: {exc}")
        return []


def gate_gpu(min_free_mb: int = 14_000, poll_s: int = 60, max_wait_s: int = 3600) -> dict:
    """Wave rule: a foreign executor shares this card.  Wait, never OOM it."""

    t0 = time.time()
    checks = []
    while True:
        free = gpu_free_mb()
        best = max(free) if free else 0
        checks.append({"at_s": round(time.time() - t0, 1), "free_mb": free})
        log(f"GPU gate: free={free} MB (need >= {min_free_mb})")
        if best >= min_free_mb:
            return {"ok": True, "free_mb": best, "waited_s": round(time.time() - t0, 1),
                    "checks": checks}
        if time.time() - t0 > max_wait_s:
            return {"ok": False, "free_mb": best, "waited_s": round(time.time() - t0, 1),
                    "checks": checks}
        log(f"GPU gate: waiting {poll_s}s")
        time.sleep(poll_s)


def _reap_process_group() -> dict:
    """Kill anything left in OUR process group, then prove it is empty."""

    pgid = os.getpgid(0)
    try:
        out = subprocess.run(["ps", "-o", "pid=,pgid=,comm=", "-e"],
                             capture_output=True, text=True, timeout=30, check=False).stdout
    except Exception:  # noqa: BLE001
        return {"pgid": pgid, "checked": False}
    mine = [ln.split(None, 2) for ln in out.splitlines()
            if len(ln.split(None, 2)) == 3 and ln.split(None, 2)[1] == str(pgid)]
    strays = [m for m in mine if int(m[0]) != os.getpid()]
    for pid, _pg, _c in strays:
        try:
            os.kill(int(pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
    time.sleep(0.5)
    out2 = subprocess.run(["ps", "-o", "pid=,pgid=", "-e"],
                          capture_output=True, text=True, timeout=30, check=False).stdout
    left = [ln for ln in out2.splitlines()
            if len(ln.split()) == 2 and ln.split()[1] == str(pgid)
            and int(ln.split()[0]) != os.getpid()]
    return {"pgid": pgid, "checked": True, "strays_signalled": len(strays),
            "remaining_after": len(left), "clean": not left}


# ===========================================================================
# open-loop dev metrics (used for the pre-registered early stop)
# ===========================================================================


def episode_anchors(split, narr: np.ndarray):
    """Gold scored-family anchors per episode, from the recorded stream."""

    from teacher import NARR_FAMILY, SCORED_NARR_FAMILIES
    out = []
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        out.append([(f - s, int(narr[f])) for f in range(s, e)
                    if NARR_FAMILY[int(narr[f])] in SCORED_NARR_FAMILIES])
    return out


def open_loop_metrics(split, pred_act: np.ndarray, pred_narr: np.ndarray,
                      window: int = 10) -> dict:
    from closed_loop import rising_edges
    from teacher import NARR_FAMILY, SCORED_NARR_FAMILIES
    # balanced act accuracy over classes with real support
    acts = split.acts
    classes, counts = np.unique(acts, return_counts=True)
    recalls = []
    for c, n in zip(classes, counts, strict=True):
        if n < 50:
            continue
        m = acts == c
        recalls.append(float((pred_act[m] == c).mean()))
    bal_acc = float(np.mean(recalls)) if recalls else 0.0
    gold = episode_anchors(split, split.narr)
    tp = fp = fn = 0
    per = {}
    from collections import Counter
    ctp, cfp, cfn = Counter(), Counter(), Counter()
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        pe = [(f, v) for f, v in rising_edges(list(pred_narr[s:e]))
              if NARR_FAMILY[v] in SCORED_NARR_FAMILIES]
        used = set()
        for gf, gv in gold[ei]:
            hit = None
            for i, (pf, pv) in enumerate(pe):
                if i not in used and pv == gv and abs(pf - gf) <= window:
                    hit = i
                    break
            if hit is None:
                cfn[NARR_FAMILY[gv]] += 1
                fn += 1
            else:
                used.add(hit)
                ctp[NARR_FAMILY[gv]] += 1
                tp += 1
        for i, (_pf, pv) in enumerate(pe):
            if i not in used:
                cfp[NARR_FAMILY[pv]] += 1
                fp += 1
    f1s = []
    for fam in SCORED_NARR_FAMILIES:
        t, f_p, f_n = ctp[fam], cfp[fam], cfn[fam]
        p = t / (t + f_p) if (t + f_p) else 0.0
        r = t / (t + f_n) if (t + f_n) else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        per[fam] = {"f1": round(f1, 4), "support": t + f_n}
        if t + f_n:
            f1s.append(f1)
    macro = float(np.mean(f1s)) if f1s else 0.0
    return {
        "act_balanced_acc": round(bal_acc, 4),
        "act_top1": round(float((pred_act == acts).mean()), 4),
        "narr_macro_f1": round(macro, 4),
        "narr_per_family": per,
        "score": round(0.5 * bal_acc + 0.5 * macro, 4),
    }


# ===========================================================================
# stages
# ===========================================================================


def stage_header(a) -> None:
    RESULTS_MD.write_text("")
    am = _amendments()
    _STATE["amendments"] = am
    md("# MA-1 — RESULTS")
    md()
    md("Executor: Opus (parcel session), 2026-08-29.  Design: `DESIGN.md` (FROZEN).")
    md("Evidence tier: **`desktop-sim`** (headless city, kinematic, no audio, "
       "no real LiDAR noise beyond the venue's own profile).  Physical motion: "
       "**NO-GO**, unchanged.  No verdict is drawn here — Fable writes "
       "`VERDICT.md`.")
    md()
    md("## 0. Pre-flight")
    md()
    md(f"* **AMENDMENTS.md at start of run: "
       f"{'PRESENT' if am['exists'] else 'ABSENT'}**"
       + (f" ({am['bytes']} bytes)" if am["exists"] else
          " — DESIGN.md as frozen is the operative pre-registration."))
    md(f"* seed `{a.seed}`; venv `~/.cache/parcel-0e/venv` "
       f"(python {sys.version.split()[0]}); scratch `{SCRATCH}`")
    md(f"* `PARCEL_MEMORY_PATH` -> `{os.environ['PARCEL_MEMORY_PATH']}` "
       "(the owner's store is never opened); `PARCEL_MEMORY_PURPOSE` unset")
    md("* **No sim subprocess is launched** — the headless city runs in-process. "
       "The only children are this file's multiprocessing Pool workers; they are "
       "joined and the process group is proved empty at exit (see §7).")
    md("* No sockets are opened, nothing touches `/dev/bus/usb`, no hosted API "
       "call and no VLM call is made, and no git write command is run. The "
       "owner's `:8080` / `:8765` / `/tmp/parcel_sim.sock` are untouched.")
    md("* The NAV evals' held-out scene is never loaded and never named; the "
       "venue is the headless city's own default block, perturbed "
       "procedurally.  No frozen digest is read or moved.")
    md()
    free = gpu_free_mb()
    _STATE["gpu_at_start_mb"] = free
    md(f"* GPU at start: free {free} MB (cap for this job: 12 GB; a foreign "
       "executor shares the card, so every training job is gated at >= 14 GB "
       "free — see §4).")
    md()


def stage_samples(a) -> dict:
    from teacher import write_sample_episodes
    t0 = time.time()
    out = HERE / "sample_episodes.txt"
    write_sample_episodes(out, a.seed)
    txt = out.read_text()
    md("## 1. Sample episodes (timing sanity check)")
    md()
    md(f"`sample_episodes.txt` is written FIRST ({len(txt)} bytes, "
       f"{time.time()-t0:.0f} s): 30-frame excerpts of one **plain**, one "
       "**revise** and one **queue** episode on a generated scene, each "
       "anchored on its interruption, with the scripted owner's utterances, "
       "the `stop` cue and any sound events timestamped above the table.")
    md()
    md("What the excerpt is there to let a reader check, and what it shows:")
    md()
    md("* the `cmd:` cue and the matching narration (`nav.start` / "
       "`plan.revised` / `plan.queued`) land on the SAME frame as the owner's "
       "utterance;")
    md("* **the goal channels do NOT flip on that frame** — A3's 5-frame mask "
       "keeps them on the old goal, so an arm that switches must be reading "
       "`cmd_target`, not `goal_bear`;")
    md("* the act stream turns toward the new bearing over the following "
       "frames;")
    md("* after a `cmd:stop` the `stop_state` channel latches `stopped` and "
       "the act stream holds until the owner re-issues (`cmd:go_to` again) — "
       "stop is a held state, not a one-frame event;")
    md("* `steer:resume` and `plan.resumed` appear only after the amendment "
       "goal's terminal;")
    md("* frame 0 emits `<idle>`, not a zero twist: the two are one token "
       "(see §2.1).")
    md()
    return {"bytes": len(txt), "wall_s": round(time.time() - t0, 1)}


def stage_generate(a) -> dict:
    from teacher import generate_split, split_plan
    t0 = time.time()
    stats = {}
    for name, eids, seeds, kinds in split_plan(a):
        stats[name] = generate_split(name, eids, seeds, a.seed,
                                     workers=a.workers, kinds=kinds)
        log(f"generated {name}: {stats[name]}")
    return _generate_report(a, stats, t0)


def _generate_report(a, stats, t0) -> dict:
    """Read the recorded metadata back and write section 2."""

    import collections

    from teacher import DATA_DIR as TD
    from teacher import N_ACTS, SEED_DEV, SEED_HELD, SEED_TRAIN, scene_manifest
    tq = {}
    for name in ("train", "dev", "held"):
        metas = json.loads((TD / f"{name}_meta.json").read_text())
        kinds = collections.Counter(m["kind"] for m in metas)
        by_t = collections.defaultdict(lambda: [0, 0])
        for m in metas:
            by_t[m["target_a"]][1] += 1
            by_t[m["target_a"]][0] += int(m["success"])
        tq[name] = {
            "episodes": len(metas),
            "frames": int(sum(m["frames"] for m in metas)),
            "kinds": dict(kinds),
            "success_rate": round(float(np.mean([m["success"] for m in metas])), 4),
            "any_arrival_rate": round(
                float(np.mean([len(m["arrived"]) > 0 for m in metas])), 4),
            "collision_rate": round(
                float(np.mean([min(1, m["collisions"]) for m in metas])), 4),
            "mean_frames": round(float(np.mean([m["frames"] for m in metas])), 1),
            "per_target_sr": {k: round(v[0] / max(1, v[1]), 3)
                              for k, v in sorted(by_t.items())},
            "scene_seeds": len({m["scene_seed"] for m in metas}),
            "stop_cue_episodes": int(sum(m["had_stop_cue"] for m in metas)),
            "owner_speaking_episodes": int(sum(m["had_speaking"] for m in metas)),
            "sound_events": int(sum(m["n_sound"] for m in metas)),
        }
    manifests = {
        "train": scene_manifest({m["scene_seed"] for m in
                                 json.loads((TD / "train_meta.json").read_text())}),
        "dev": scene_manifest({m["scene_seed"] for m in
                               json.loads((TD / "dev_meta.json").read_text())}),
        "held": scene_manifest({m["scene_seed"] for m in
                                json.loads((TD / "held_meta.json").read_text())}),
    }
    md("## 2. Teacher corpus and the held-out geometry (A2)")
    md()
    md("The teacher is the shipped stack: `DirectiveNavigator` + grid planner + "
       "semantic resolution ladder + `apply_reactive_safety`, driven in "
       "`HeadlessCityWorld`.")
    md()
    md("**A2 — held-out GEOMETRY, not held-out labels.** The first draft "
       "perturbed the frozen block with `MjSpec` jitter; the amendment is "
       "applied instead: every episode runs on a real MJCF variant built by "
       "`evals.nav_instruct.scene_gen.build_scene(seed, scratch_dir)` — the "
       "same rejection-sampled generator the NAV `val_unseen` split uses, with "
       "its round-trip / overlap / support / **navigability** filters — on "
       "MA-1's own seed ranges "
       f"`train {SEED_TRAIN}`, `dev {SEED_DEV}`, `held {SEED_HELD}`. These are "
       "disjoint from each other and from the `val_unseen` manifests' seeds "
       "(91011-91015); nothing writes into `configs/scenes/generated/` (scenes "
       "land in MA-1's scratch tree) and the NAV evals' held-out scene is never "
       "loaded and never named. Splits are **grouped by geometry seed**.")
    md()
    md("| split | scenes | manifest sha256 |")
    md("|---|---|---|")
    for k in ("train", "dev", "held"):
        md(f"| {k} | {manifests[k]['n']} | `{manifests[k]['manifest_sha256'][:32]}...` |")
    md()
    md("| split | episodes | frames | scene seeds | plain/revise/queue | "
       "teacher SR | any-arrival | collision rate | mean frames | stop cues | "
       "speaking cues | sound events |")
    md("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for name in ("train", "dev", "held"):
        q = tq[name]; k = q["kinds"]
        md(f"| {name} | {q['episodes']} | {q['frames']} | {q['scene_seeds']} | "
           f"{k.get('plain',0)}/{k.get('revise',0)}/{k.get('queue',0)} | "
           f"**{q['success_rate']}** | {q['any_arrival_rate']} | "
           f"{q['collision_rate']} | {q['mean_frames']} | "
           f"{q['stop_cue_episodes']} | {q['owner_speaking_episodes']} | "
           f"{q['sound_events']} |")
    md()
    md("Per-target teacher success (train): " +
       ", ".join(f"`{k}` {v}" for k, v in tq["train"]["per_target_sr"].items()))
    md()
    md("**The target vocabulary is bounded to what the teacher can demonstrate.** "
       "A pre-generation probe of 16 plain episodes per target on the frozen "
       "block measured the shipped stack at `sidewalk` 0.75, `lamppost` 0.44, "
       "`bench` 0.19, `crosswalk` 0.12, `planter` 0.06, **`tree` 0.00, `door` "
       "0.00** (112 episodes, band-entry predicate). `tree` and `door` are "
       "therefore out of the vocabulary: a goal the teacher never reaches "
       "teaches the student to wander, and `door` does not exist in generated "
       "variants at all. This is a bound on the CLAIM, and it is the first "
       "thing §6 says the result does not prove.")
    md()
    # --- teacher-vs-oracle agreement (review row) -------------------------
    metas = json.loads((TD / "held_meta.json").read_text())
    W = 10   # 1.0 s
    ob = tb = ob_hit = tb_hit = 0
    arr_both = arr_only_o = arr_only_t = 0
    lags = []
    for m in metas:
        o, t_ = m["oracle_block_edges"], m["teacher_block_edges"]
        ob += len(o); tb += len(t_)
        ob_hit += sum(1 for f in o if any(abs(f - g) <= W for g in t_))
        tb_hit += sum(1 for f in t_ if any(abs(f - g) <= W for g in o))
        oa, ta = m["oracle_arrived_frame"], m["teacher_arrived_frame"]
        if oa >= 0 and ta >= 0:
            arr_both += 1
            lags.append((oa - ta) * 0.1)
        elif oa >= 0:
            arr_only_o += 1
        elif ta >= 0:
            arr_only_t += 1
    agree = {
        "oracle_block_edges": ob, "teacher_block_edges": tb,
        "oracle_blocks_with_teacher_within_1s": ob_hit,
        "teacher_blocks_with_oracle_within_1s": tb_hit,
        "oracle_recall_of_teacher": round(tb_hit / max(1, tb), 4),
        "teacher_recall_of_oracle": round(ob_hit / max(1, ob), 4),
        "arrived_both": arr_both, "arrived_oracle_only": arr_only_o,
        "arrived_teacher_only": arr_only_t,
        "arrival_lag_s_median": (round(float(np.median(lags)), 2) if lags else None),
    }
    md("### 2.1 Teacher receipts vs the truth oracle (review row)")
    md()
    md("A1 makes the truth oracle the gold. The teacher's OWN opinion — the "
       "navigator's `mission.status` and its `MidLevelCommand.note` block / "
       "recovery words — is recorded on the same frames and compared. It is "
       "never used as a label; it is here so the gap is a number.")
    md()
    md(f"On the {len(metas)} held-out teacher episodes, within a 1.0 s window: "
       f"**{agree['oracle_block_edges']} oracle block edges** vs "
       f"**{agree['teacher_block_edges']} navigator block edges**; the "
       f"navigator covers {agree['teacher_recall_of_oracle']} of the oracle's, "
       f"the oracle covers {agree['oracle_recall_of_teacher']} of the "
       f"navigator's. Arrival: both agree on {agree['arrived_both']} episodes, "
       f"oracle-only on {agree['arrived_oracle_only']}, navigator-only on "
       f"{agree['arrived_teacher_only']}; median lag "
       f"{agree['arrival_lag_s_median']} s (oracle minus navigator).")
    md()
    md("**They are not the same signal**, which is exactly why the amendment "
       "moved gold to the oracle: the navigator calls itself blocked whenever "
       "its recovery ladder is running (a semantic-search rotate counts), while "
       "the oracle only says blocked when the body is actually inside the "
       "reactive-safety stop band. A harness-side \"stalled for 3 s\" class "
       "that the first draft also emitted was CUT for the same reason — it fired "
       "at 2.9 s on an episode where the robot was accelerating away with a "
       "clear forward sector. `nav.blocked:stalled` and `nav.blocked:unroutable` "
       "remain in the vocabulary with ZERO support and are reported as such.")
    md()
    md("**The hold token.** DESIGN.md writes `<hold>`; the shipped "
       "`ActTokenCodec` vocabulary has no such token, so **`<idle>` is the hold "
       "token throughout**, and the zero twist `<twist:1:2>` (vx = 0, vyaw = 0) "
       "is folded into it — one token for one body state, no label noise. The "
       f"act vocabulary is {N_ACTS} tokens.")
    md()
    md(f"Generation wall: {round(time.time()-t0,1)} s on {a.workers} CPU workers "
       "(`OPENBLAS_NUM_THREADS=1` per worker; no sim subprocess).")
    md()
    return {"splits": stats, "teacher_quality": tq,
            "scene_manifests": manifests,
            "teacher_vs_oracle": agree,
            "wall_s": round(time.time() - t0, 1)}


def stage_ledger(a, results) -> None:
    """Section 6 — the amendment ledger, the A7 witness table, and the bounds."""

    from teacher import (
        EVAL_CHANNELS,
        N_ACTS,
        N_CHANNELS,
        N_NARR,
        TARGETS,
    )
    md("## 6. Amendments, the published channel list, and what this does not prove")
    md()
    md("`AMENDMENTS.md` appeared POST-START (15:53) and is binding. Every row "
       "above is the AMENDED row; where an amendment could not be applied "
       "inside the wall budget it is named here rather than quietly skipped.")
    md()
    md("| id | status | how |")
    md("|---|---|---|")
    md("| **A1** gold from the truth oracle; label-copy channels masked | "
       "**APPLIED** | Gold is `nav.arrived` = truth pose inside the harness's "
       "own goal region AND stopped >= 5 frames; `nav.blocked` = truth minimum "
       "clearance below the reactive-safety stop band (0.65 m) for >= 5 frames; "
       "`plan.*` anchored to the cue frame; `nav.failed` on the step limit. "
       "`plan_step` and `blocked` were DROPPED from the frame and the "
       "teacher-side `replan` count was replaced by `replan_own` (A's own "
       "emitted-block count). Channel list below. |")
    md("| **A2** held-out GEOMETRY | **APPLIED** | Real MJCF variants from "
       "`evals.nav_instruct.scene_gen.build_scene` on MA-1's own seed ranges, "
       "split by geometry seed, manifests hashed into `results.json`; "
       "STRAIGHT-TO-GOAL criterion and informativeness test reported in 4.1. "
       "The first draft's `MjSpec` jitter approach is abandoned, not shipped. |")
    md("| **A3** anchored switch, masked goal, task-stack-exact queue | "
       "**APPLIED** | Switch anchored to the detected cue frame, heading "
       "measured from the truth pose, goal channels lag the cue by 5 frames; "
       "queue completion requires oracle arrival at goal 2 then goal 1. |")
    md("| **A4** event counting, reference rows, one dev metric | "
       "**APPLIED** | Rising-edge emissions, at most one TP per gold event in "
       "the CAUSAL 1.0 s window, extras are FP, false-event rate = "
       "FP / emitted; ALWAYS-NONE and EVENT-EVERY-FRAME rows in 4.3; "
       "dev-selection metric is the harmonic mean of dev closed-loop success "
       "and dev narration F1 on a fixed dev-geometry slice; the checkpoint "
       "sha256 is frozen in §3 before any held-out run; latency rows carry host "
       "load and co-tenants. **Per-class held-out event counts are printed in "
       "4.3 — where a class is under 200 the row is under-powered and says so.** |")
    md("| **A5** the last minute, explicitly | **PARTIAL** | The last-60-s "
       "channels were added (five age bins + two 60 s counters beside the K = 6 "
       "event tokens) and a C-h0 arm is reported, but C-h0 is an INPUT "
       "ABLATION of the same checkpoint, not a retrained model. Section 4.45 "
       "says so in the table's own caption. |")
    md("| **A6** proposals vs witnessed narration (`prop.*` head) | "
       "**NOT APPLIED** | A third head with `prop.replan` / "
       "`prop.resume_queued` / `prop.abandon` / `prop.clarify` gold at t + delta, "
       "scored raw and as executive-accepted, did not fit the wall budget. It "
       "is the largest un-run amendment and the natural first item for a "
       "follow-up. No `prop.*` claim is made anywhere. |")
    md("| **A7** witness table and vocabulary partition | **PARTIAL** | The "
       "witness table is below and H-MA1c is reported per partition in 4.3; "
       "`nav.progress` is INTERNAL-ONLY and is excluded from narration scoring "
       "entirely. The >= 20-episode cross-check against NAV-INT-1's live path "
       "was NOT run (that harness did not exist in this folder's tree at run "
       "time), so agreement between the headless teacher and the live runtime "
       "is UNVERIFIED here. No `TaskExecutive` is hosted; the teacher's "
       "receipts are `mission.status` / `command.note`. |")
    md("| **A8** the safety row | **APPLIED** | `cmd:stop` in ~12 % and "
       "`owner_speaking` in ~15 % of episodes; raw and post-filter rates in "
       "4.5; stop is a held state until a new directive re-issues the goal. |")
    md("| **A9** cue-duplex, stated | **PARTIAL** | Stated: **Model A v0 is "
       "CUE-duplex** — router cue tokens at 10 Hz, no audio, no ASR, no "
       "jitter, cues delivered at a single frame with a 3-frame hold. DS-1 "
       "(20260828) is the speech-duplex follow-up. The ASR-timing rows "
       "(end-of-utterance vs partial-cue-at-first-content-word with 10 % "
       "retractions) were NOT run. |")
    md("| **A10** no authority | **APPLIED** | The false-event rate is reported "
       "as *predicted terminal with no backing receipt*; the bound is restated "
       "below. |")
    md()
    md("### 6.1 The exact channel list at closed-loop eval (A1)")
    md()
    md(f"{N_CHANNELS} categorical channels; act vocabulary {N_ACTS} tokens "
       f"(the product codec, no skills/emotes — this venue has no body "
       f"gestures); narration vocabulary {N_NARR} tokens over "
       f"{len(TARGETS)} targets.")
    md()
    for group, cols in EVAL_CHANNELS.items():
        md(f"* **{group}** — " + ", ".join(f"`{c}`" for c in cols))
    md()
    md("Nothing in the first three groups is a one-step copy of a label: the "
       "goal channels are geometry, the free-space ring is the venue's LiDAR, "
       "the cue channels are what the owner said, and every "
       "`A_own_state` channel is computed from A's own past emissions "
       "(`hist*` carries A's own narration tokens in closed loop, not the "
       "teacher's).")
    md()
    md("### 6.2 A7 witness table")
    md()
    md("| token | headless witness (what backs it here) | live-runtime receipt |")
    md("|---|---|---|")
    md("| `nav.arrived:<t>` | truth pose inside the goal region AND stopped "
       ">= 5 frames | `whisperer.KIND_MISSION_ARRIVED` (always band, critical) |")
    md("| `nav.failed:<c>` | episode step limit with no arrival | "
       "`KIND_MISSION_ENDED` |")
    md("| `nav.blocked:<c>` | truth minimum clearance below the "
       "reactive-safety stop band for >= 5 frames | `KIND_MISSION_BLOCKED` "
       "(middle band; the product debounces the block episode) |")
    md("| `nav.replan` | 3.0 s after a latched block with the goal still live | "
       "`KIND_REROUTE` |")
    md("| `nav.start:<t>` | the scripted owner's `cmd:go_to` cue frame | "
       "**research-only** — no receipt class exists |")
    md("| `nav.progress` | 5 s cadence while a goal is live | **INTERNAL-ONLY** "
       "— this is exactly `KIND_NAV_TICK`, the whisperer's NEVER band. It is "
       "never a narration claim and is excluded from every F1 in 4.3. |")
    md("| `plan.revised/queued/resumed:<t>` | the cue frame / the re-issue "
       "frame | **research-only** — `brain/executive.py` has "
       "suspend/resume/`request_interrupt` doors, but no queue POLICY and no "
       "whisperer class |")
    md("| `attend.sound:<b>`, `attend.owner` | authored gold from the scripted "
       "sound event | **research-only** — bounded by the awareness sweep's own "
       "yaw limits |")
    md()
    md("`plan.resumed` means **the original goal was RE-ISSUED after the "
       "amendment's terminal receipt** — the product's plan \"resume\" is a "
       "re-issue (the amendment transaction consumes the parked resume intent "
       "on commit), and the harness models it that way: "
       "`DirectiveNavigator.start(original_directive)`.")
    md()
    md("### 6.3 What this does NOT prove")
    md()
    md("* **The target vocabulary is bounded to five labels the teacher can "
       "reach** (`bench`, `lamppost`, `planter`, `sidewalk`, `crosswalk`). "
       "`tree` and `door` were measured at 0/16 for the shipped teacher and "
       "cut. Any success number here is a number about those five.")
    md("* **A's narration tokens carry no authority.** No consumer may narrate "
       "a terminal from them; they are predictions scored against gold, never "
       "receipts (A10).")
    md("* Kinematic base, no gait, no contact physics, no audio, no ASR, no "
       "real LiDAR noise beyond the venue's profile; the owner is scripted and "
       "the world has no pedestrians.")
    md("* A high score means the policy learned **the product teacher's "
       "behaviour on this generated city-block family** — and the teacher's own "
       "success rate on it is the ceiling, which §2 measures and which is low.")
    md("* The headless teacher's event sequence has NOT been shown to agree "
       "with the live runtime's receipts (A7's cross-check was not run).")
    md("* No `prop.*` proposal head exists (A6), so nothing here says anything "
       "about A proposing plan changes to the executive.")
    md()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--seed", type=int, default=20260829)
    ap.add_argument("--train", type=int, default=3000)
    ap.add_argument("--dev", type=int, default=300)
    ap.add_argument("--held", type=int, default=600)
    ap.add_argument("--gpu-workers", type=int, default=4)
    ap.add_argument("--dev-closed", type=int, default=20)
    ap.add_argument("--ablation-subset", type=int, default=250)
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--max-steps", type=int, default=4000)
    ap.add_argument("--eval-every", type=int, default=400)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--window", type=int, default=128)
    ap.add_argument("--warmup", type=int, default=16)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--train-budget-s", type=float, default=3600.0)
    ap.add_argument("--stages", type=str, default="all")
    a = ap.parse_args()

    t_start = time.time()
    stages = ("header,samples,generate,train,closed,latency,close"
              if a.stages == "all" else a.stages)
    want = set(stages.split(","))
    results: dict = {"seed": a.seed, "stages": {}}
    try:
        if "header" in want:
            stage_header(a)
        if "samples" in want:
            results["stages"]["samples"] = stage_samples(a)
            RESULTS_JSON.write_text(json.dumps(results, indent=2, default=str))
        if "generate" in want:
            results["stages"]["generate"] = stage_generate(a)
        elif "report_generate" in want:
            results["stages"]["generate"] = _generate_report(a, {}, time.time())
            RESULTS_JSON.write_text(json.dumps(results, indent=2, default=str))
        # the training / closed-loop / latency stages live in run_stages.py so
        # this file stays readable; they are imported lazily.
        if want & {"train", "closed", "latency"}:
            import run_stages
            run_stages.run(a, results, md=md, log=log, gate_gpu=gate_gpu,
                           amendments=_amendments, want=want,
                           open_loop_metrics=open_loop_metrics,
                           results_json=RESULTS_JSON)
    finally:
        try:
            stage_ledger(a, results)
        except Exception as exc:  # noqa: BLE001
            log(f"ledger failed: {exc}")
        results["wall_s_total"] = round(time.time() - t_start, 1)
        reap = _reap_process_group()
        results["process_group"] = reap
        if True:
            md("## 7. Housekeeping")
            md()
            md(f"* total wall: **{results['wall_s_total']} s** "
               f"({results['wall_s_total']/3600:.2f} h)")
            md(f"* process group {reap.get('pgid')}: "
               f"{reap.get('strays_signalled', 0)} stray children signalled, "
               f"{reap.get('remaining_after', '?')} remaining -> "
               f"**{'CLEAN' if reap.get('clean') else 'NOT CLEAN'}**. "
               "No sim subprocess was ever started; these are this run's own "
               "rollout Pool workers.")
            am = _amendments()
            md(f"* AMENDMENTS.md at end of run: "
               f"{'PRESENT' if am['exists'] else 'ABSENT'}"
               + (" — see the note beside each headline row." if am["exists"] else "."))
            md()
        RESULTS_JSON.write_text(json.dumps(results, indent=2, default=str))
        log(f"wrote {RESULTS_JSON}")


if __name__ == "__main__":
    main()
