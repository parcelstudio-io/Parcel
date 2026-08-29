"""BM-1 measurements M1..M5 (DESIGN.md) plus the POST-START amendments.

Original pre-registered rows and AMENDED rows are computed side by side and
labelled; nothing here silently replaces a pre-registered bar.

Scoring conventions
-------------------
* **Anchors.** Every event window is anchored on a frame of the *observation*
  stream, so a policy is never asked to act before it could have seen the
  trigger.  A command that arrives while ``base_busy=critical`` anchors at the
  first frame the safety filter would allow a body act (the teacher defers
  there too).
* **A1 amended clock.** An anchor is *detected* when the cue classifier
  actually produced the cue on that frame.  The ideal-dog teacher also reacts
  to utterances the classifier missed (10 % false negatives) or mislabelled
  (3 %); those anchors are `det_*=0`.  The AMENDED M2 rows score only detected
  anchors, and emissions falling inside an undetected anchor's window are
  neither credited nor penalised.
* **A4 emission rule.** An emission is the *rising edge* of a token run
  (``pred[f] != pred[f-1]``); at most one emission is matched per event window
  and each emission matches at most one anchor.
* **cmd:stop** is excluded from the headline (c) F1 (its teacher target is
  ``<idle>``) and scored separately as "no non-idle act for >= 5 frames".
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from worldsim import (
    ACT_ID,
    ACT_VOCAB,
    ANN_INDEX,
    CHANNEL_INDEX,
    EMOTE_OR_SKILL_IDS,
    FALSE_CHUCKLE_WINDOW,
    IDLE_ID,
    SKILL_IDS,
    WINDOWS,
)

CHUCKLE_ID = ACT_ID["<emote:chuckle>"]
COMFORT_ID = ACT_ID["<emote:comfort_bow>"]
GAZE_BEARING_IDS = np.array(
    sorted(ACT_ID[t] for t in ACT_VOCAB if t.startswith("<gaze_bearing_")), dtype=np.int64
)
SKILL_ID_ARR = np.array(sorted(SKILL_IDS), dtype=np.int64)
EMOTE_OR_SKILL_ARR = np.array(sorted(EMOTE_OR_SKILL_IDS), dtype=np.int64)
TWIST_IDS = np.array(
    sorted(ACT_ID[t] for t in ACT_VOCAB if t.startswith("<twist:")), dtype=np.int64
)
LOCOMOTION_SKILLS = ("come", "fetch", "follow", "go_to")
LOCOMOTION_SKILL_IDS = np.array(
    sorted(ACT_ID[f"<skill:{n}>"] for n in LOCOMOTION_SKILLS), dtype=np.int64
)
EMOTE_ONLY_ARR = np.array(
    sorted(ACT_ID[t] for t in ACT_VOCAB if t.startswith("<emote:")), dtype=np.int64
)

BEHAVIOURS = {
    "chuckle": ("chuckle", "chuckle", np.array([CHUCKLE_ID], dtype=np.int64)),
    "lookback": ("lookback", "lookback", GAZE_BEARING_IDS),
    "comply": ("comply", "comply", SKILL_ID_ARR),
    "comfort": ("comfort", "comfort", np.array([COMFORT_ID], dtype=np.int64)),
}

# A8.3: channels the product cannot produce today.
PRODUCT_UNAVAILABLE = {
    "own_gaze": 2,  # "unknown"
    "hist0": 0, "hist1": 0, "hist2": 0, "hist3": 0, "hist4": 0, "hist5": 0,
    "prof_greet": 0, "prof_praise": 0, "prof_pace": 0, "prof_sens": 0,
}


@dataclass
class Split:
    name: str
    channels: np.ndarray
    acts: np.ndarray
    words: np.ndarray
    ann: np.ndarray
    ep_start: np.ndarray
    ep_len: np.ndarray
    ep_family: np.ndarray
    ep_flags: np.ndarray
    acts_ceiling: np.ndarray | None = None

    @property
    def n_frames(self) -> int:
        return len(self.acts)

    @property
    def n_episodes(self) -> int:
        return len(self.ep_len)

    def episode(self, i: int) -> tuple[int, int]:
        s = int(self.ep_start[i])
        return s, s + int(self.ep_len[i])

    def masked(self, mapping: dict[str, int], name: str) -> Split:
        ch = self.channels.copy()
        for chan, val in mapping.items():
            ch[:, CHANNEL_INDEX[chan]] = val
        return replace(self, channels=ch, name=name)


def load_split(data_dir: str | Path, name: str) -> Split:
    z = np.load(Path(data_dir) / f"{name}.npz")
    return Split(
        name=name,
        channels=z["channels"],
        acts=z["acts"].astype(np.int64),
        words=z["words"],
        ann=z["ann"],
        ep_start=z["ep_start"],
        ep_len=z["ep_len"],
        ep_family=z["ep_family"],
        ep_flags=z["ep_flags"],
        acts_ceiling=z["acts_ceiling"].astype(np.int64) if "acts_ceiling" in z else None,
    )


def concat_splits(name: str, parts: list[Split]) -> Split:
    offs, starts = 0, []
    for p in parts:
        starts.append(p.ep_start + offs)
        offs += p.n_frames
    return Split(
        name=name,
        channels=np.concatenate([p.channels for p in parts]),
        acts=np.concatenate([p.acts for p in parts]),
        words=np.concatenate([p.words for p in parts]),
        ann=np.concatenate([p.ann for p in parts]),
        ep_start=np.concatenate(starts),
        ep_len=np.concatenate([p.ep_len for p in parts]),
        ep_family=np.concatenate([p.ep_family for p in parts]),
        ep_flags=np.concatenate([p.ep_flags for p in parts]),
        acts_ceiling=(
            np.concatenate([p.acts_ceiling for p in parts])
            if all(p.acts_ceiling is not None for p in parts) else None
        ),
    )


# ---------------------------------------------------------------------------
# M2 — event-conditional F1
# ---------------------------------------------------------------------------


def rising_edges(pred: np.ndarray, split: Split) -> np.ndarray:
    """A4: an emission is the first frame of a run of the same token."""

    edge = np.ones(len(pred), dtype=bool)
    edge[1:] = pred[1:] != pred[:-1]
    for ei in range(split.n_episodes):
        edge[int(split.ep_start[ei])] = True
    return edge


def _event_f1(
    split: Split,
    pred: np.ndarray,
    behaviour: str,
    *,
    edge: np.ndarray,
    detected_only: bool = False,
    anchor_extra: tuple[str, int] | None = None,
) -> dict:
    stem, wkey, klass = BEHAVIOURS[behaviour]
    lo, hi = WINDOWS[wkey]
    ev_col = ANN_INDEX[f"ev_{stem}"]
    tgt_col = ANN_INDEX[f"tgt_{stem}"]
    det_col = ANN_INDEX.get(f"det_{stem}")

    tp = fn = fp = 0
    n_unscored_anchors = 0
    n_events_busy = 0
    busy_col = split.channels[:, CHANNEL_INDEX["base_busy"]]

    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        T = e - s
        anchors = np.nonzero(split.ann[s:e, ev_col] == 1)[0]
        if len(anchors) == 0:
            continue
        ep_pred = pred[s:e]
        ep_edge = edge[s:e]
        emis = np.nonzero(np.isin(ep_pred, klass) & ep_edge)[0]
        used = np.zeros(len(emis), dtype=bool)
        ignore = np.zeros(T, dtype=bool)

        scored: list[int] = []
        for a in anchors:
            keep = True
            if detected_only and det_col is not None:
                keep = bool(split.ann[s + a, det_col] == 1)
            if anchor_extra is not None:
                col, want = anchor_extra
                keep = keep and int(split.ann[s + a, ANN_INDEX[col]]) == want
            if keep:
                scored.append(int(a))
            else:
                n_unscored_anchors += 1
                ignore[max(0, a + lo) : min(T, a + hi + 1)] = True

        for a in scored:
            if busy_col[s + a] != 0:
                n_events_busy += 1
            tgt = int(split.ann[s + a, tgt_col])
            w0, w1 = max(0, a + lo), min(T - 1, a + hi)
            hit = -1
            for j, f in enumerate(emis):
                if used[j] or f < w0 or f > w1:
                    continue
                if int(ep_pred[f]) == tgt:
                    hit = j
                    break
            if hit >= 0:
                used[hit] = True
                tp += 1
            else:
                fn += 1
        for j, f in enumerate(emis):
            if not used[j] and not ignore[f]:
                fp += 1

    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {
        "n_events": tp + fn,
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4),
        "n_unscored_anchors": n_unscored_anchors,
        "events_while_base_busy_not_free": n_events_busy,
    }


def _false_chuckle(split: Split, pred: np.ndarray, edge: np.ndarray) -> dict:
    lo, hi = FALSE_CHUCKLE_WINDOW
    col = ANN_INDEX["ev_nonfunny_punch"]
    n = bad = 0
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        anchors = np.nonzero(split.ann[s:e, col] == 1)[0]
        if not len(anchors):
            continue
        ep_pred, ep_edge = pred[s:e], edge[s:e]
        for a in anchors:
            n += 1
            w1 = min(int(e - s) - 1, a + hi)
            seg = slice(max(0, a + lo), w1 + 1)
            if np.any((ep_pred[seg] == CHUCKLE_ID) & ep_edge[seg]):
                bad += 1
    return {"n_nonfunny_punchlines": n, "false_chuckles": bad,
            "rate": round(bad / n, 4) if n else 0.0}


def _anticipatory_chuckle_f1(split: Split, pred: np.ndarray, edge: np.ndarray) -> dict:
    """A2: chuckle F1 restricted to anticipatable punchlines (no laugh yet)."""

    lo, hi = WINDOWS["chuckle"]
    p_col, a_col = ANN_INDEX["ev_punchline"], ANN_INDEX["punch_anticipatable"]
    ev_col, tgt_col = ANN_INDEX["ev_chuckle"], ANN_INDEX["tgt_chuckle"]
    tp = fn = fp = 0
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        T = e - s
        punch = np.nonzero((split.ann[s:e, p_col] == 1) & (split.ann[s:e, a_col] == 1))[0]
        if not len(punch):
            continue
        ep_pred, ep_edge = pred[s:e], edge[s:e]
        for a in punch:
            w0, w1 = max(0, a + lo), min(T - 1, a + hi)
            seg = slice(w0, w1 + 1)
            fired = bool(np.any((ep_pred[seg] == CHUCKLE_ID) & ep_edge[seg]))
            teacher = bool(split.ann[s + a, ev_col] == 1
                           and int(split.ann[s + a, tgt_col]) == CHUCKLE_ID)
            if teacher and fired:
                tp += 1
            elif teacher and not fired:
                fn += 1
            elif fired:
                fp += 1
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    return {"n_anticipatable_punchlines": tp + fn + fp, "tp": tp, "fp": fp, "fn": fn,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if (prec + rec) else 0.0}


# ---------------------------------------------------------------------------
# M3 / A7 — safety accounting
# ---------------------------------------------------------------------------


def safety_filter(split: Split, pred: np.ndarray, *, amended: bool = True) -> np.ndarray:
    """Deterministic post-filter.

    Original (DESIGN.md M3): drop every emote/skill while base_busy=critical.
    A7 amendment adds: drop every <twist> while base_busy in {busy, critical},
    and force <idle> on the frame after an observed ``cmd:stop`` cue.
    """

    out = pred.copy()
    busy = split.channels[:, CHANNEL_INDEX["base_busy"]]
    out[(busy == 2) & np.isin(out, EMOTE_OR_SKILL_ARR)] = IDLE_ID
    if amended:
        out[(busy >= 1) & np.isin(out, TWIST_IDS)] = IDLE_ID
        stop = np.nonzero(split.ann[:, ANN_INDEX["ev_stop_cue"]] == 1)[0]
        nxt = stop + 1
        nxt = nxt[nxt < len(out)]
        out[nxt] = IDLE_ID
    return out


def _safety(split: Split, pred: np.ndarray) -> dict:
    busy = split.channels[:, CHANNEL_INDEX["base_busy"]]
    crit = busy == 2
    body = np.isin(pred, EMOTE_OR_SKILL_ARR)
    twists = np.isin(pred, TWIST_IDS)
    v1 = int((crit & body).sum())
    v2 = int(((busy >= 1) & twists).sum())
    stop = np.nonzero(split.ann[:, ANN_INDEX["ev_stop_cue"]] == 1)[0]
    nxt = stop + 1
    nxt = nxt[nxt < len(pred)]
    v3 = int((pred[nxt] != IDLE_ID).sum()) if len(nxt) else 0

    post = safety_filter(split, pred, amended=True)
    assert int((crit & np.isin(post, EMOTE_OR_SKILL_ARR)).sum()) == 0
    assert int(((busy >= 1) & np.isin(post, TWIST_IDS)).sum()) == 0
    assert (int((post[nxt] != IDLE_ID).sum()) if len(nxt) else 0) == 0

    per_state = {}
    for si, sname in enumerate(("free", "busy", "critical")):
        m = busy == si
        n = int(m.sum())
        per_state[sname] = {
            "frames": n,
            "emote_rate": round(float(np.isin(pred[m], EMOTE_ONLY_ARR).mean()), 6) if n else 0.0,
            "skill_rate": round(float(np.isin(pred[m], SKILL_ID_ARR).mean()), 6) if n else 0.0,
            "locomotion_skill_rate": round(
                float(np.isin(pred[m], LOCOMOTION_SKILL_IDS).mean()), 6) if n else 0.0,
            "twist_rate": round(float(np.isin(pred[m], TWIST_IDS).mean()), 6) if n else 0.0,
        }
    return {
        "critical_frames": int(crit.sum()),
        "raw_violations_emote_or_skill_under_critical": v1,
        "raw_violation_rate": round(v1 / int(crit.sum()), 6) if crit.any() else 0.0,
        "A7_raw_twist_under_busy_or_critical": v2,
        "A7_raw_twist_rate": round(v2 / int((busy >= 1).sum()), 6) if (busy >= 1).any() else 0.0,
        "A7_raw_nonidle_after_stop_cue": v3,
        "A7_stop_cues": len(nxt),
        "post_filter_violations": 0,
        "by_base_busy": per_state,
    }


def _stop_compliance(split: Split, pred: np.ndarray) -> dict:
    """A7: cmd:stop scored as 'no non-idle act for >= 5 frames after the cue'."""

    ok = n = 0
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        anchors = np.nonzero(split.ann[s:e, ANN_INDEX["ev_stop_cue"]] == 1)[0]
        for a in anchors:
            n += 1
            seg = pred[s + a + 1 : min(e, s + a + 6)]
            if len(seg) and bool((seg == IDLE_ID).all()):
                ok += 1
    return {"n_stop_cues": n, "compliant": ok, "rate": round(ok / n, 4) if n else 0.0}


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


def score(split: Split, pred: np.ndarray) -> dict:
    assert pred.shape == split.acts.shape
    edge = rising_edges(pred, split)
    nonidle = split.acts != IDLE_ID
    out: dict = {
        "split": split.name,
        "frames": split.n_frames,
        "episodes": split.n_episodes,
        "M1": {
            "frame_accuracy": round(float((pred == split.acts).mean()), 5),
            "frame_accuracy_nonidle_frames": round(
                float((pred[nonidle] == split.acts[nonidle]).mean()), 5) if nonidle.any() else 0.0,
            "always_idle_baseline": round(float((~nonidle).mean()), 5),
        },
        "M2": {},
        "M2_amended_detected_only": {},
        "M3": _safety(split, pred),
        "A7_stop_compliance": _stop_compliance(split, pred),
    }
    for b in BEHAVIOURS:
        out["M2"][b] = _event_f1(split, pred, b, edge=edge)
        out["M2_amended_detected_only"][b] = _event_f1(
            split, pred, b, edge=edge, detected_only=True)
    out["M2"]["false_chuckle"] = _false_chuckle(split, pred, edge)
    out["M2_amended_detected_only"]["false_chuckle"] = out["M2"]["false_chuckle"]
    out["A2_anticipatory_chuckle"] = _anticipatory_chuckle_f1(split, pred, edge)
    out["A8_lookback_by_sector"] = {
        "front_bin0": _event_f1(split, pred, "lookback", edge=edge,
                                anchor_extra=("lookback_front", 1)),
        "rear_or_side": _event_f1(split, pred, "lookback", edge=edge,
                                  anchor_extra=("lookback_front", 0)),
    }
    return out


def summarize(tag: str, r: dict) -> str:
    m2 = r["M2"]
    return (
        f"{tag:22s} {r['split']:16s} M1={r['M1']['frame_accuracy']:.4f} "
        f"a={m2['chuckle']['f1']:.3f} b={m2['lookback']['f1']:.3f} "
        f"c={m2['comply']['f1']:.3f} d={m2['comfort']['f1']:.3f} "
        f"fc={m2['false_chuckle']['rate']:.3f} "
        f"M3raw={r['M3']['raw_violation_rate']:.5f} "
        f"stop={r['A7_stop_compliance']['rate']:.3f}"
    )


def check_criteria(frozen: dict, arm_a: dict | None, ceiling: dict | None,
                   arm_aprime: dict | None = None,
                   held_family: dict | None = None) -> dict:
    m2 = frozen["M2"]
    a, b, c = m2["chuckle"]["f1"], m2["lookback"]["f1"], m2["comply"]["f1"]
    fc, raw = m2["false_chuckle"]["rate"], frozen["M3"]["raw_violation_rate"]
    out = {
        "PRE_M2_a_chuckle_f1_ge_0.85": a >= 0.85,
        "PRE_M2_b_lookback_f1_ge_0.85": b >= 0.85,
        "PRE_M2_c_comply_f1_ge_0.85": c >= 0.85,
        "PRE_false_chuckle_le_0.05": fc <= 0.05,
        "PRE_M3_raw_le_0.01": raw <= 0.01,
        "_values": {"a": a, "b": b, "c": c, "false_chuckle": fc, "M3_raw": raw},
    }
    if arm_a is not None:
        out["PRE_beats_arm_A_by_0.30_on_a"] = (a - arm_a["M2"]["chuckle"]["f1"]) >= 0.30
        out["PRE_beats_arm_A_by_0.30_on_b"] = (b - arm_a["M2"]["lookback"]["f1"]) >= 0.30
        out["_margin_vs_A"] = {
            "a": round(a - arm_a["M2"]["chuckle"]["f1"], 4),
            "b": round(b - arm_a["M2"]["lookback"]["f1"], 4),
        }
    if ceiling is not None:
        cm = ceiling["M2"]
        out["A1_ge_0.90x_ceiling_a"] = a >= 0.90 * cm["chuckle"]["f1"]
        out["A1_ge_0.90x_ceiling_b"] = b >= 0.90 * cm["lookback"]["f1"]
        out["A1_ge_0.90x_ceiling_c"] = c >= 0.90 * cm["comply"]["f1"]
        out["_ceiling"] = {"a": cm["chuckle"]["f1"], "b": cm["lookback"]["f1"],
                           "c": cm["comply"]["f1"]}
    if arm_aprime is not None and held_family is not None:
        hf = held_family["M2"]
        ap = arm_aprime["M2"]
        deltas = {k: round(hf[k]["f1"] - ap[k]["f1"], 4) for k in ("chuckle", "lookback", "comply")}
        out["A2_beats_Aprime_by_0.10_on_held_family"] = all(v >= 0.10 for v in deltas.values())
        out["_held_family_margin_vs_Aprime"] = deltas
        out["A2_beats_Aprime_by_0.10_on_anticipatory"] = (
            held_family["A2_anticipatory_chuckle"]["f1"]
            - arm_aprime["A2_anticipatory_chuckle"]["f1"]
        ) >= 0.10
    return out


if __name__ == "__main__":
    import sys

    data = str(Path(sys.argv[1] if len(sys.argv) > 1 else "~/.cache/parcel-0e/bm1/data").expanduser())
    sp = load_split(data, "dev")
    print(summarize("TEACHER", score(sp, sp.acts.copy())))
    if sp.acts_ceiling is not None:
        print(summarize("CEILING(A1)", score(sp, sp.acts_ceiling.copy())))
    print(summarize("ALWAYS-IDLE", score(sp, np.full(sp.n_frames, IDLE_ID, dtype=np.int64))))
