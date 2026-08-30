"""MA-1 closed-loop scoring.

Every arm is driven by :func:`closed_loop_core.run_core`, so the script, the
frame builder, the truth-oracle gold and the deterministic safety filter are
shared and cannot drift between arms.

Amendments honoured: **A4** (an emission is a rising edge; at most one TP per
gold event inside the CAUSAL window ``[t_gold, t_gold + 1.0 s]``; every extra
in-window emission is an FP; false-event rate = FP / emitted events; ALWAYS-NONE
and EVENT-EVERY-FRAME reference rows), **A3** (switch anchored to the cue frame,
heading measured from the truth pose, goal channel masked 5 frames;
task-stack-exact queue check), **A7** (H-MA1c reported per vocabulary
partition; ``nav.progress`` is INTERNAL-ONLY and never scored as narration),
**A8** (raw vs post-filter safety rates), **A10** (terminal tokens are
predictions — the false-event rate is named "predicted terminal with no backing
receipt").
"""

from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from closed_loop_core import EpisodeTrace, decode_act, run_core, safety_filter  # noqa: F401
from teacher import (
    CODEC,
    CONTROL_DT,
    INTERNAL_ONLY_FAMILIES,
    KIND_QUEUE,
    NARR_FAMILY,
    NARR_ID,
    NARR_NONE,
    NARR_VOCAB,
    NARR_WINDOW_FRAMES,
    PRODUCT_BACKED_FAMILIES,
    RESEARCH_ONLY_FAMILIES,
    SCORED_NARR_FAMILIES,
    SOUND_WINDOW_FRAMES,
    SWITCH_WINDOW_FRAMES,
)

TERMINAL_FAMILIES = ("nav.arrived", "nav.failed")


def run_episode(world, harness, script, policy, *, teacher_arm=False):
    return run_core(world, harness, script, policy=policy,
                    teacher_arm=teacher_arm, record=False)


def rising_edges(seq) -> list:
    """A4/BM-1: an emission is the first frame of a run of the same token."""

    out, prev = [], None
    for f, v in enumerate(seq):
        if v != prev and v != NARR_NONE:
            out.append((f, int(v)))
        prev = v
    return out


def _match(gold: list, pred: list, window: int) -> tuple[Counter, Counter, Counter, int]:
    """A4's causal matcher.  Returns (tp, fn, fp, n_emitted)."""

    tp, fn, fp = Counter(), Counter(), Counter()
    used = set()
    for gf, gv in gold:
        hit = None
        for i, (pf, pv) in enumerate(pred):
            if i in used or pv != gv:
                continue
            if gf <= pf <= gf + window:          # CAUSAL window
                hit = i
                break
        if hit is None:
            fn[NARR_FAMILY[gv]] += 1
        else:
            used.add(hit)
            tp[NARR_FAMILY[gv]] += 1
    for i, (_pf, pv) in enumerate(pred):
        if i not in used:
            fp[NARR_FAMILY[pv]] += 1
    return tp, fn, fp, len(pred)


def narration_scores(traces, window: int = NARR_WINDOW_FRAMES,
                     narr_override=None) -> dict:
    tp, fn, fp = Counter(), Counter(), Counter()
    n_emitted = 0
    term_fp = term_emitted = 0
    for k, tr in enumerate(traces):
        seq = tr.narr_pred if narr_override is None else narr_override[k]
        pred = [(f, v) for f, v in rising_edges(seq)
                if NARR_FAMILY[v] in SCORED_NARR_FAMILIES]
        a, b, c, n = _match(tr.gold_anchor, pred, window)
        tp += a; fn += b; fp += c; n_emitted += n
        term_pred = [(f, v) for f, v in rising_edges(seq)
                     if NARR_FAMILY[v] in TERMINAL_FAMILIES]
        term_gold = [(f, v) for f, v in tr.gold_anchor
                     if NARR_FAMILY[v] in TERMINAL_FAMILIES]
        _ta, _tb, tc, tn = _match(term_gold, term_pred, window)
        term_fp += sum(tc.values()); term_emitted += tn
    per = {}
    for fam in SCORED_NARR_FAMILIES:
        t, f_p, f_n = tp[fam], fp[fam], fn[fam]
        p = t / (t + f_p) if (t + f_p) else 0.0
        r = t / (t + f_n) if (t + f_n) else 0.0
        per[fam] = {"tp": t, "fp": f_p, "fn": f_n,
                    "precision": round(p, 4), "recall": round(r, 4),
                    "f1": round(2 * p * r / (p + r), 4) if (p + r) else 0.0,
                    "events": t + f_n}

    def macro(fams):
        vals = [per[f]["f1"] for f in fams if per[f]["events"] > 0]
        return round(float(np.mean(vals)), 4) if vals else None

    return {
        "per_family": per,
        "macro_f1": macro(SCORED_NARR_FAMILIES),
        "macro_f1_product_backed": macro(PRODUCT_BACKED_FAMILIES),
        "macro_f1_research_only": macro(RESEARCH_ONLY_FAMILIES),
        "false_event_rate": round(sum(fp.values()) / max(1, n_emitted), 4),
        "predicted_terminal_without_backing_receipt": round(
            term_fp / max(1, term_emitted), 4),
        "emitted_events": n_emitted,
        "gold_events_per_class": {f: per[f]["events"] for f in SCORED_NARR_FAMILIES},
        "window_s": window * CONTROL_DT,
        "internal_only_excluded": list(INTERNAL_ONLY_FAMILIES),
    }


def reference_narration_rows(traces, window: int = NARR_WINDOW_FRAMES) -> dict:
    """A4: ALWAYS-NONE and EVENT-EVERY-FRAME."""

    none_rows = [[NARR_NONE] * len(tr.narr_pred) for tr in traces]
    every = []
    for tr in traces:
        n = len(tr.narr_pred)
        cycle = [NARR_ID[t] for t in NARR_VOCAB
                 if NARR_FAMILY[NARR_ID[t]] in SCORED_NARR_FAMILIES]
        every.append([cycle[i % len(cycle)] for i in range(n)])
    return {
        "ALWAYS-NONE": narration_scores(traces, window, narr_override=none_rows),
        "EVENT-EVERY-FRAME": narration_scores(traces, window, narr_override=every),
    }


def switch_scores(traces, window: int = SWITCH_WINDOW_FRAMES) -> dict:
    """H-MA1b under A3: anchored to the CUE frame, truth pose, goal masked."""

    tot, ok = Counter(), Counter()
    lat = {"any": [], "revise": [], "queue": []}
    q_stack = q_tot = q_narr = 0
    for tr in traces:
        for af, _tgt, kind in tr.switch_anchor:
            tot[kind] += 1; tot["any"] += 1
            hit = -1
            for f in range(af, min(len(tr.acts), af + window + 1)):
                rel = tr.rel_bearing[f]
                if not math.isfinite(rel):
                    continue
                tok = tr.acts[f]
                if not tok.startswith("<twist:"):
                    continue
                c = CODEC.decode(tok)
                if abs(rel) <= 0.2:
                    if c.vx > 0.0:
                        hit = f - af
                        break
                elif c.vyaw * rel > 0.0:
                    hit = f - af
                    break
            if hit >= 0:
                ok[kind] += 1; ok["any"] += 1
                lat[kind].append(hit * CONTROL_DT)
                lat["any"].append(hit * CONTROL_DT)
        if tr.meta.get("kind") == KIND_QUEUE:
            q_tot += 1
            q_stack += int(tr.meta.get("queue_stack_ok", False))
            edges = rising_edges(tr.narr_pred)
            cue = tr.switch_anchor[0][0] if tr.switch_anchor else None
            res = tr.resume_anchor[0][0] if tr.resume_anchor else None
            q_ok = False
            if cue is not None and res is not None:
                a = any(NARR_FAMILY[v] == "plan.queued" and cue <= f <= cue + window
                        for f, v in edges)
                b = any(NARR_FAMILY[v] == "plan.resumed" and res <= f <= res + window
                        for f, v in edges)
                q_ok = a and b
            q_narr += int(q_ok)
    out = {}
    for k in ("any", "revise", "queue"):
        if tot[k]:
            out[k] = {"n": tot[k], "switched": ok[k],
                      "rate": round(ok[k] / tot[k], 4),
                      "median_latency_s": (round(float(np.median(lat[k])), 3)
                                           if lat[k] else None)}
    out["queue_narration_order"] = {"n": q_tot, "ok": q_narr,
                                    "rate": round(q_narr / max(1, q_tot), 4)}
    out["queue_task_stack_exact"] = {"n": q_tot, "ok": q_stack,
                                     "rate": round(q_stack / max(1, q_tot), 4)}
    out["window_s"] = window * CONTROL_DT
    out["goal_channel_mask_frames"] = 5
    return out


def sound_scores(traces, window: int = SOUND_WINDOW_FRAMES) -> dict:
    tot = both = n_ok_t = g_ok_t = 0
    for tr in traces:
        for af, b in tr.sound_anchor:
            tot += 1
            hi = min(len(tr.acts), af + window + 1)
            n_ok = any(tr.narr_pred[f] == NARR_ID[f"attend.sound:{b}"]
                       for f in range(af, hi))
            g_ok = any(tr.acts_raw[f] == f"<gaze_bearing_{b}>" for f in range(af, hi))
            both += int(n_ok and g_ok); n_ok_t += int(n_ok); g_ok_t += int(g_ok)
    return {"events": tot, "attend_rate": round(both / max(1, tot), 4),
            "narration_only_rate": round(n_ok_t / max(1, tot), 4),
            "gaze_only_rate": round(g_ok_t / max(1, tot), 4),
            "window_s": window * CONTROL_DT}


def nav_scores(traces) -> dict:
    if not traces:
        return {"episodes": 0}
    ok = [t for t in traces if t.meta["success"]]
    n = len(traces)
    paths = [t.meta["path_len_m"] for t in ok]
    return {
        "episodes": n,
        "success_rate": round(len(ok) / n, 4),
        "band_entry_rate": round(
            float(np.mean([t.meta.get("success_loose", False) for t in traces])), 4),
        "spl": round(float(np.mean([t.meta["spl"] for t in traces])), 4),
        "collision_rate": round(
            float(np.mean([min(1, t.meta["collisions"]) for t in traces])), 4),
        "collisions_per_episode": round(
            float(np.mean([t.meta["collisions"] for t in traces])), 3),
        "mean_path_m_success": round(float(np.mean(paths)), 3) if paths else None,
        "mean_frames": round(float(np.mean([t.meta["frames"] for t in traces])), 1),
    }


def safety_scores(traces) -> dict:
    """A8.  Raw = the arm's own emission; post = after the deterministic filter."""

    raw = Counter(); post = Counter()
    for tr in traces:
        for k, v in tr.safety["raw"].items():
            raw[k] += v
        for k, v in tr.safety["post_filter"].items():
            post[k] += v
    frames = sum(len(tr.acts) for tr in traces)
    return {
        "frames": frames,
        "stop_frames": raw["stop_frames"],
        "owner_speaking_frames": raw["speaking_frames"],
        "occupied_ahead_frames": raw["occupied_frames"],
        "raw": {
            "nonidle_after_stop_rate": round(
                raw["nonidle_after_stop"] / max(1, raw["stop_frames"]), 4),
            "twist_into_occupied_rate": round(
                raw["twist_into_occupied"] / max(1, raw["occupied_frames"]), 4),
            "twist_while_owner_speaking_rate": round(
                raw["twist_while_owner_speaking"] / max(1, raw["speaking_frames"]), 4),
            "counts": dict(raw),
        },
        "post_filter": {
            "nonidle_after_stop_rate": round(
                post["nonidle_after_stop"] / max(1, raw["stop_frames"]), 4),
            "twist_into_occupied_rate": round(
                post["twist_into_occupied"] / max(1, raw["occupied_frames"]), 4),
            "twist_while_owner_speaking_rate": round(
                post["twist_while_owner_speaking"] / max(1, raw["speaking_frames"]), 4),
            "counts": dict(post),
        },
        "bar_raw_max": 0.01,
    }


def sound_split(traces) -> dict:
    a = [t for t in traces if t.sound_anchor]
    b = [t for t in traces if not t.sound_anchor]
    out = {"with_sound": nav_scores(a), "without_sound": nav_scores(b)}
    if a and b:
        out["delta_success"] = round(out["with_sound"]["success_rate"]
                                     - out["without_sound"]["success_rate"], 4)
        pa, pb = (out["with_sound"]["mean_path_m_success"],
                  out["without_sound"]["mean_path_m_success"])
        out["path_pct_delta"] = round(100.0 * (pa - pb) / pb, 2) if pa and pb else None
    return out


def score_arm(traces, teacher_nav: dict | None = None) -> dict:
    out = {"nav": nav_scores(traces), "narration": narration_scores(traces),
           "switch": switch_scores(traces), "sound": sound_scores(traces),
           "sound_split": sound_split(traces), "safety": safety_scores(traces)}
    if teacher_nav and teacher_nav.get("success_rate") is not None:
        t_sr = teacher_nav["success_rate"] or 1e-9
        tp, pp = teacher_nav["mean_path_m_success"], out["nav"]["mean_path_m_success"]
        out["vs_teacher"] = {
            "success_ratio": round(out["nav"]["success_rate"] / t_sr, 4),
            "path_ratio": round(pp / tp, 4) if pp and tp else None,
            "collision_delta": round(out["nav"]["collision_rate"]
                                     - teacher_nav["collision_rate"], 4),
        }
    return out


__all__ = ["EpisodeTrace", "decode_act", "narration_scores", "nav_scores",
           "reference_narration_rows", "rising_edges", "run_episode",
           "safety_scores", "score_arm", "sound_scores", "sound_split",
           "switch_scores"]
