"""FL-1 metrics: F1 / false-chuckle / regret with bootstrap CIs on the median."""

from __future__ import annotations

import numpy as np
import owners as O


def f1(tp: float, fp: float, fn: float) -> float:
    d = 2 * tp + fp + fn
    return float("nan") if d == 0 else 2 * tp / d


def joke_metrics(decisions: np.ndarray, laughed: np.ndarray, liked: np.ndarray) -> dict:
    """decisions/laughed/liked: (n_jokes,) bool for ONE owner over a joke window."""
    tp = float(np.sum(decisions & laughed))
    fp = float(np.sum(decisions & ~laughed))
    fn = float(np.sum(~decisions & laughed))
    nonfunny = ~laughed & ~liked                    # BM-1 M2 denominator
    fc_bm1 = float(np.sum(decisions & nonfunny)) / max(1, int(nonfunny.sum())) if nonfunny.any() else float("nan")
    nolaugh = ~laughed
    fc_strict = float(np.sum(decisions & nolaugh)) / max(1, int(nolaugh.sum())) if nolaugh.any() else float("nan")
    return {"f1": f1(tp, fp, fn), "tp": tp, "fp": fp, "fn": fn,
            "false_chuckle_bm1": fc_bm1, "false_chuckle_strict": fc_strict,
            "precision": float("nan") if tp + fp == 0 else tp / (tp + fp),
            "recall": float("nan") if tp + fn == 0 else tp / (tp + fn)}


def regret(decisions: np.ndarray, p_true: np.ndarray) -> float:
    """F1 amendment: sum over jokes of (oracle expected reward - policy expected reward)."""
    orc = np.maximum(O.R_HIT * p_true + O.R_FALSE * (1 - p_true), 0.0)
    pol = np.where(decisions, O.R_HIT * p_true + O.R_FALSE * (1 - p_true), 0.0)
    return float(np.sum(orc - pol))


def wrong_chuckles(decisions: np.ndarray, laughed: np.ndarray) -> int:
    return int(np.sum(decisions & ~laughed))


def boot_median(x, n: int = 2000, seed: int = 0) -> dict:
    x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
    if x.size == 0:
        return {"median": float("nan"), "lo": float("nan"), "hi": float("nan"),
                "q1": float("nan"), "q3": float("nan"), "n": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.size, size=(n, x.size))
    meds = np.median(x[idx], axis=1)
    return {"median": float(np.median(x)),
            "lo": float(np.percentile(meds, 2.5)), "hi": float(np.percentile(meds, 97.5)),
            "q1": float(np.percentile(x, 25)), "q3": float(np.percentile(x, 75)),
            "n": int(x.size)}


def boot_mean(x, n: int = 2000, seed: int = 0) -> dict:
    x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
    if x.size == 0:
        return {"mean": float("nan"), "lo": float("nan"), "hi": float("nan"), "n": 0}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.size, size=(n, x.size))
    means = x[idx].mean(axis=1)
    return {"mean": float(x.mean()), "lo": float(np.percentile(means, 2.5)),
            "hi": float(np.percentile(means, 97.5)), "n": int(x.size)}


def pooled_curve(dec: np.ndarray, laugh: np.ndarray, mask: np.ndarray) -> list[float]:
    """dec/laugh/mask: (n_owners, n_jokes) -> pooled F1 at each joke index."""
    out = []
    for n in range(dec.shape[1]):
        m = mask[:, n]
        d, l = dec[m, n], laugh[m, n]
        out.append(f1(float(np.sum(d & l)), float(np.sum(d & ~l)), float(np.sum(~d & l))))
    return out
