"""FL-1 synthetic owners: humor taste, look-back preference, laugh detector.

Amendments applied: F1 (Beta-mixture taste prior, reward +1/-2/0),
F2 (per-category history state), F5 (laugh-detector noise + self-echo),
F6 (look-back preference generator), F8 (explicit verbal feedback).

Nothing here imports product code.  ``worldsim`` (BM-1, READ ONLY) supplies the
joke-category vocabulary only.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

BM1 = str(Path(__file__).resolve().parents[1] / "behavior-model-1")
if BM1 not in sys.path:
    sys.path.insert(0, BM1)

import worldsim as W

CATEGORIES: tuple[str, ...] = W.JOKE_CATEGORIES  # pun slapstick absurd dry wordplay callback
NCAT = len(CATEGORIES)

# --- F1: the pre-registered synthetic taste prior ---------------------------
# p_c ~ w_like * Beta(A_LIKE) + (1 - w_like) * Beta(A_DIS), clipped to [0.05, 0.95],
# i.i.d. across the 6 categories.
TASTE_PRIOR = {
    "kind": "beta-mixture",
    "w_like": 0.45,
    "like": (12.0, 2.0),      # mean 0.857
    "dislike": (1.2, 10.0),   # mean 0.107
    "clip": (0.05, 0.95),
}

# F4: Bayes-optimal decision threshold under the 2:1 cost (chuckle iff p >= 2/3).
THRESH = 2.0 / 3.0
THRESH_SENS = 0.6  # DESIGN.md's original rule, reported as a sensitivity row

# F1: reward for one joke.
R_HIT, R_FALSE, R_NONE = 1.0, -2.0, 0.0


def expected_reward(p: float, chuckle: bool) -> float:
    """Expected reward of a decision when the true laugh probability is p."""
    return (R_HIT * p + R_FALSE * (1.0 - p)) if chuckle else R_NONE


def oracle_reward(p: float) -> float:
    return max(expected_reward(p, True), expected_reward(p, False))


# --- F5: laugh-detector model ----------------------------------------------
DETECTOR = {
    "false_negative": 0.20,
    "false_positive": 0.05,
    "onset_latency_s": 0.5,
    "echo_guard_s": 1.0,  # reward window opens after the dog's own chuckle audio ends
    "source": "AMENDMENTS.md F5 default (no humor-signal-1/results.json at run time)",
}


def load_hs1_operating_point() -> dict | None:
    """F5: replace the detector numbers with HS-1's measured point if it exists."""
    p = Path(__file__).resolve().parents[1] / "humor-signal-1" / "results.json"
    if not p.exists():
        return None
    try:
        blob = json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None
    for key in ("operating_point", "hs1a", "laughter"):
        node = blob.get(key) if isinstance(blob, dict) else None
        if isinstance(node, dict) and "false_negative" in node and "false_positive" in node:
            return {"false_negative": float(node["false_negative"]),
                    "false_positive": float(node["false_positive"]),
                    "source": f"humor-signal-1/results.json:{key}"}
    return None


# --- F6: look-back preference ----------------------------------------------
LATENCIES = (2.0, 4.0, 6.0, 8.0)


@dataclass
class Owner:
    idx: int
    seed: int
    p_laugh: np.ndarray          # (6,) true laugh probability per category
    pref_latency: float          # L* in {2,4,6,8} s
    annoy_scale: float = 0.6     # F6: P(annoy | L < L*) = annoy_scale * (L* - L) / 6
    # F8 explicit feedback rates
    p_scold_after_false: float = 0.3
    p_praise_after_hit: float = 0.2
    resets_table: bool = False   # F8: 20 % of owners reset at joke 30
    source: str = "beta-mixture"

    # ---- humor -----------------------------------------------------------
    def laughs(self, cat: int, rng: np.random.Generator) -> bool:
        return bool(rng.random() < self.p_laugh[cat])

    def likes(self, cat: int) -> bool:
        """Decision-theoretic 'funny': the oracle would chuckle (p >= 2/3)."""
        return bool(self.p_laugh[cat] >= THRESH)

    # ---- look-back (F6) ---------------------------------------------------
    def reacq_prob(self, latency: float) -> float:
        return 0.9 if latency >= self.pref_latency else 0.5

    def annoy_prob(self, latency: float) -> float:
        if latency >= self.pref_latency:
            return 0.0
        return self.annoy_scale * (self.pref_latency - latency) / 6.0

    def lookback_true_reward(self, latency: float) -> float:
        return self.reacq_prob(latency) - 0.5 * self.annoy_prob(latency)

    def lookback_step(self, latency: float, rng: np.random.Generator) -> tuple[float, bool, bool]:
        reacq = bool(rng.random() < self.reacq_prob(latency))
        annoy = bool(rng.random() < self.annoy_prob(latency))
        return (1.0 * reacq - 0.5 * annoy), reacq, annoy


def sample_owner(idx: int, seed: int, prior: dict | None = None) -> Owner:
    prior = prior or TASTE_PRIOR
    rng = np.random.default_rng(seed)
    lo, hi = prior["clip"]
    ps = np.empty(NCAT)
    for c in range(NCAT):
        if rng.random() < prior["w_like"]:
            a, b = prior["like"]
        else:
            a, b = prior["dislike"]
        ps[c] = float(np.clip(rng.beta(a, b), lo, hi))
    return Owner(
        idx=idx,
        seed=seed,
        p_laugh=ps,
        pref_latency=float(rng.choice(LATENCIES)),
        resets_table=bool(rng.random() < 0.20),
        source=prior.get("kind", "beta-mixture"),
    )


# --- seed books (F3): fresh seeds never used by BM-1 ------------------------
SEED_BASE = 20260828
EVAL_SEED_OFFSET = 1_000_000   # F3: evaluation owners
TUNE_SEED_OFFSET = 2_000_000   # F3: tuning owners
TRAIN_SEED_OFFSET = 3_000_000  # training owners for policy C


def owner_book(n: int, offset: int, prior: dict | None = None, seed: int = SEED_BASE) -> list[Owner]:
    return [sample_owner(i, seed + offset + i, prior) for i in range(n)]


# --- F2: per-category history state ----------------------------------------
CAP = 7  # counts capped at 7
REC_NONE, REC_LAUGH, REC_SILENT = 0, 1, 2


@dataclass
class HistoryState:
    """F2: per category, (laughed, total) capped at 7 plus a recency bin."""

    laughed: np.ndarray = field(default_factory=lambda: np.zeros(NCAT, dtype=np.int64))
    total: np.ndarray = field(default_factory=lambda: np.zeros(NCAT, dtype=np.int64))
    recent: np.ndarray = field(default_factory=lambda: np.zeros(NCAT, dtype=np.int64))
    last3: list[list[int]] = field(default_factory=lambda: [[] for _ in range(NCAT)])

    def observe(self, cat: int, laughed: bool) -> None:
        self.total[cat] += 1
        if laughed:
            self.laughed[cat] += 1
        self.recent[cat] = REC_LAUGH if laughed else REC_SILENT
        self.last3[cat].append(int(laughed))
        if len(self.last3[cat]) > 3:
            self.last3[cat].pop(0)

    def reset(self) -> None:
        self.laughed[:] = 0
        self.total[:] = 0
        self.recent[:] = 0
        self.last3 = [[] for _ in range(NCAT)]

    def channels(self) -> np.ndarray:
        """(18,) int16: [laughed_c capped, total_c capped, recency_c] for c in 0..5."""
        out = np.empty(3 * NCAT, dtype=np.int16)
        for c in range(NCAT):
            out[3 * c + 0] = min(int(self.laughed[c]), CAP)
            out[3 * c + 1] = min(int(self.total[c]), CAP)
            out[3 * c + 2] = int(self.recent[c])
        return out

    def rule_decision(self, cat: int) -> bool:
        """F3 baseline: chuckle iff laughed >= 2 of the last 3 in this category."""
        return sum(self.last3[cat]) >= 2

    def copy(self) -> HistoryState:
        h = HistoryState()
        h.laughed = self.laughed.copy()
        h.total = self.total.copy()
        h.recent = self.recent.copy()
        h.last3 = [list(x) for x in self.last3]
        return h


HIST_CHANNEL_SIZES = tuple([CAP + 1, CAP + 1, 3] * NCAT)
HIST_CHANNEL_NAMES = tuple(
    f"h{part}_{CATEGORIES[c]}" for c in range(NCAT) for part in ("laugh", "tot", "rec")
)


# --- F5: the observation channel the learner actually sees ------------------
def observe_laugh(
    true_laugh: bool,
    dog_chuckled: bool,
    rng: np.random.Generator,
    q_echo: float,
    m_mask: float,
    det: dict | None = None,
) -> bool:
    """Detector output for one joke window (F5).

    ``q_echo``  P(detector fires on the dog's own chuckle) -- but the default
                decision rule discards events overlapping the dog's own audio,
                so only the leak that survives the guard is modelled.
    ``m_mask``  P(a true laugh in the 1 s after the dog's chuckle is masked).
    """
    det = det or DETECTOR
    obs = bool(true_laugh)
    if obs and dog_chuckled and rng.random() < m_mask:
        obs = False                      # masked by the dog's own chuckle audio
    if obs and rng.random() < det["false_negative"]:
        obs = False                      # detector miss
    if not obs:
        if dog_chuckled and rng.random() < q_echo:
            obs = True                   # self-echo leaked past the 1.0 s guard
        elif rng.random() < det["false_positive"]:
            obs = True                   # ordinary false positive
    return obs


def main() -> None:  # pragma: no cover - sample dump
    rows = []
    book = owner_book(6, EVAL_SEED_OFFSET)
    for o in book:
        rows.append(
            f"owner {o.idx} seed={o.seed} L*={o.pref_latency:.0f}s resets={o.resets_table}\n"
            + "  p_laugh: "
            + "  ".join(f"{CATEGORIES[c]}={o.p_laugh[c]:.2f}{'*' if o.likes(c) else ' '}"
                        for c in range(NCAT))
            + f"\n  oracle chuckle categories: {[CATEGORIES[c] for c in range(NCAT) if o.likes(c)]}"
            + "\n  look-back true reward per arm: "
            + "  ".join(f"{L:.0f}s={o.lookback_true_reward(L):.3f}" for L in LATENCIES)
        )
    print("\n".join(rows))


if __name__ == "__main__":
    main()
