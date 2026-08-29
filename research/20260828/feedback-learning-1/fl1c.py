"""H-FL1c — learning the owner's preferred look-back check-in latency.

AMENDMENTS F6: L* ~ U{2,4,6,8} s; P(reacquired <= 5 s | check-in at L) = 0.9 if
L >= L* else 0.5; P(annoyance) = 0.6 (L* - L)/6 when L < L*; reward =
1[reacq] - 0.5*1[annoy]; SUCCESS = simple regret <= 0.1 after N loss events.

The learned quantity is the follow-skill parameter ``check_in_latency_s`` -- a
config value the executive owns -- never an act token, and its verdict is
independent of BM-1's [3, 5] s M2(b) look-back window.
"""

from __future__ import annotations

import json
import time

import fl_world as F
import metrics as M
import numpy as np
import owners as O

N_OWNERS = 100
N_LOSSES = 40
N_GRID = (5, 10, 15, 20, 25, 30, 40)
SIMPLE_REGRET_BAR = 0.10
ARMS = np.array(O.LATENCIES)
R_LO, R_SPAN = -0.5, 1.5  # reward in [-0.5, 1.0] -> normalised to [0, 1] for the Beta


def _learners(seed):
    return {
        "thompson_beta": _thompson,
        "ucb1": _ucb1,
        "epsilon_greedy_0.1": _eps,
    }


def _thompson(rng, a, b, n, mean, t):
    return int(np.argmax(rng.beta(a, b)))


def _ucb1(rng, a, b, n, mean, t):
    unseen = np.nonzero(n == 0)[0]
    if unseen.size:
        return int(unseen[0])
    return int(np.argmax(mean + np.sqrt(2 * np.log(max(2, t)) / n)))


def _eps(rng, a, b, n, mean, t):
    if rng.random() < 0.1 or (n == 0).any():
        return int(rng.integers(0, len(ARMS)))
    return int(np.argmax(mean))


def run_owner(owner, learner, rng, n_losses):
    a = np.ones(len(ARMS))
    b = np.ones(len(ARMS))
    n = np.zeros(len(ARMS))
    s = np.zeros(len(ARMS))
    committed = []
    rewards = []
    for t in range(n_losses):
        mean = np.where(n > 0, s / np.maximum(n, 1), 0.5)
        k = learner(rng, a, b, n, mean, t + 1)
        r, _reacq, _annoy = owner.lookback_step(float(ARMS[k]), rng)
        rn = (r - R_LO) / R_SPAN
        a[k] += rn
        b[k] += 1 - rn
        n[k] += 1
        s[k] += rn
        rewards.append(r)
        post = a / (a + b)
        committed.append(int(np.argmax(post)))
    return np.array(committed), np.array(rewards)


def run(seed: int, out: dict, log=print, quick: bool = False) -> dict:
    t0 = time.time()
    n_own = 20 if quick else N_OWNERS
    book = O.owner_book(n_own, O.EVAL_SEED_OFFSET, seed=seed)
    best = np.array([max(o.lookback_true_reward(L) for L in O.LATENCIES) for o in book])

    # inter-loss structure, for the record: loss onsets from worldsim occlusions
    loss_rate = []
    for o in book[:10]:
        ev = F.owner_loss_stream(o, 40, seed + o.idx)
        loss_rate.append(len(ev))
    res = {"config": {"n_owners": n_own, "n_losses": N_LOSSES, "arms_s": list(O.LATENCIES),
                      "simple_regret_bar": SIMPLE_REGRET_BAR, "n_grid": list(N_GRID),
                      "reward": "1[reacquired<=5s] - 0.5*1[annoyance]",
                      "loss_events_available_per_40_probe": loss_rate,
                      "learned_quantity": "follow-skill config parameter check_in_latency_s"},
           "learners": {}}

    for lname, learner in _learners(seed).items():
        rng = np.random.default_rng(seed + 101)
        commits = np.zeros((n_own, N_LOSSES), np.int64)
        rews = np.zeros((n_own, N_LOSSES))
        for i, o in enumerate(book):
            c, r = run_owner(o, learner, rng, N_LOSSES)
            commits[i] = c
            rews[i] = r
        true_r = np.array([[o.lookback_true_reward(float(ARMS[k])) for k in commits[i]]
                           for i, o in enumerate(book)])
        simple_regret = best[:, None] - true_r
        ok = simple_regret <= SIMPLE_REGRET_BAR + 1e-9
        # first N after which the commitment stays good for the rest of the run
        med_n = []
        for i in range(n_own):
            n = N_LOSSES
            while n > 0 and ok[i, n - 1]:
                n -= 1
            med_n.append(n + 1)
        by_lstar = {}
        for L in O.LATENCIES:
            m = np.array([o.pref_latency == L for o in book])
            if m.any():
                by_lstar[f"L*={L:.0f}s"] = {
                    "n_owners": int(m.sum()),
                    "frac_ok_at_25": float(ok[m, min(24, N_LOSSES - 1)].mean()),
                    "median_n": float(np.median(np.array(med_n)[m])),
                }
        res["learners"][lname] = {
            "frac_simple_regret_ok": {str(N): float(ok[:, N - 1].mean()) for N in N_GRID},
            "frac_best_arm_identified": {
                str(N): float(np.mean([ARMS[commits[i, N - 1]] >= book[i].pref_latency
                                       for i in range(n_own)])) for N in N_GRID},
            "median_n_to_stable_success": M.boot_median(med_n, seed=seed),
            "mean_simple_regret": {str(N): float(simple_regret[:, N - 1].mean()) for N in N_GRID},
            "cum_reward_per_loss": float(rews.mean()),
            "by_preferred_latency": by_lstar,
        }
        log(f"[FL1c] {lname:20s} frac ok @25={res['learners'][lname]['frac_simple_regret_ok']['25']:.2f} "
            f"median N={res['learners'][lname]['median_n_to_stable_success']['median']:.0f} "
            f"[{time.time()-t0:.0f}s]")
    res["wall_s"] = round(time.time() - t0, 1)
    out["fl1c"] = res
    return res


if __name__ == "__main__":
    import sys
    out = {}
    run(O.SEED_BASE, out, quick="--quick" in sys.argv)
    open("fl1c.json", "w").write(json.dumps(out["fl1c"], indent=1))  # noqa: SIM115
    print("wrote fl1c.json")
