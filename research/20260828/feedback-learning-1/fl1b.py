"""H-FL1b — contextual Thompson-sampling bandit (the auditable, safety-preferred arm).

AMENDMENTS: F1 (reward/regret, ORACLE + POPULATION-PRIOR rows), F2 (same
per-category state as policy C), F4 (threshold 2/3; 0.6 as a sensitivity row),
F5 (noisy-reward grid, q=0.1/m=0.3 headline).
"""

from __future__ import annotations

import json
import time

import engine as E
import metrics as M
import numpy as np
import owners as O

N_OWNERS = 100
N_JOKES = 60
BAR_F1, BAR_FC = 0.80, 0.10
SLIDE = 10


def sliding_pooled(dec, tab, w=SLIDE):
    """Pooled F1 and false-chuckle over a trailing window of ``w`` joke indices."""
    n_jokes = tab["n_jokes"]
    f1s, fcs = [], []
    for n in range(n_jokes):
        lo = max(0, n - w + 1)
        m = tab["evaluable"][:, lo:n + 1]
        d, l = dec[:, lo:n + 1][m], tab["laughed"][:, lo:n + 1][m]
        li = tab["liked"][:, lo:n + 1][m]
        f1s.append(M.f1(float(np.sum(d & l)), float(np.sum(d & ~l)), float(np.sum(~d & l))))
        nf = ~l & ~li
        fcs.append(float(np.sum(d & nf)) / max(1, int(nf.sum())))
    return f1s, fcs


def jokes_to_bar(f1s, fcs):
    for n, (a, b) in enumerate(zip(f1s, fcs)):
        if np.isfinite(a) and a >= BAR_F1 and b <= BAR_FC:
            return n + 1
    return None


def oracle_agreement_n(dec, tab):
    """Per owner: first joke index after which every decision matches the oracle."""
    orc = tab["p"] >= O.THRESH
    out = []
    for i in range(tab["n_owners"]):
        m = tab["evaluable"][i]
        agree = (dec[i] == orc[i]) | ~m
        n = tab["n_jokes"]
        while n > 0 and agree[n - 1]:
            n -= 1
        out.append(n + 1)
    return out


def summarize(name, tab, dec, seed=0):
    f1s, fcs = sliding_pooled(dec, tab)
    rows = []
    for i in range(tab["n_owners"]):
        m = tab["evaluable"][i]
        r = M.joke_metrics(dec[i][m], tab["laughed"][i][m], tab["liked"][i][m])
        r["regret"] = M.regret(dec[i][m], tab["p"][i][m])
        r["wrong"] = M.wrong_chuckles(dec[i][m], tab["laughed"][i][m])
        rows.append(r)
    return {
        "rule": name,
        "f1_all60": M.boot_median([r["f1"] for r in rows], seed=seed),
        "false_chuckle_bm1_all60": M.boot_median([r["false_chuckle_bm1"] for r in rows], seed=seed + 1),
        "false_chuckle_strict_all60": M.boot_median([r["false_chuckle_strict"] for r in rows], seed=seed + 2),
        "wrong_chuckles_all60": M.boot_median([r["wrong"] for r in rows], seed=seed + 3),
        "expected_reward_regret_all60": M.boot_median([r["regret"] for r in rows], seed=seed + 4),
        "jokes_to_bar_pooled": jokes_to_bar(f1s, fcs),
        "jokes_to_oracle_agreement": M.boot_median(oracle_agreement_n(dec, tab), seed=seed + 5),
        "sliding_f1_curve": f1s,
        "sliding_false_chuckle_curve": fcs,
    }


def rules(tab, a0, b0, prior_mean, seed):
    return [
        ("oracle", E.rule_oracle(tab)),
        ("population_prior", E.rule_population_prior(tab, prior_mean)),
        ("history_rule_2of3", E.rule_history(tab)),
        ("beta_mean_2of3", E.rule_beta(tab, a0, b0, thompson=False)),
        ("beta_thompson_2of3", E.rule_beta(tab, a0, b0, thompson=True, seed=seed)),
        ("beta_mean_0.6", E.rule_beta(tab, a0, b0, thompson=False, thresh=O.THRESH_SENS)),
        ("beta_mixture_mean_2of3", E.rule_beta_mixture(tab)),
        ("beta_mean_2of3_detector_debiased", E.rule_beta_debias(tab, a0, b0)),
    ]


def run(seed: int, out: dict, log=print, quick: bool = False) -> dict:
    t0 = time.time()
    n_own = 20 if quick else N_OWNERS
    book = O.owner_book(n_own, O.EVAL_SEED_OFFSET, seed=seed)
    a0, b0 = E.beta_prior_moments()
    prior_mean = a0 / (a0 + b0)
    tab = E.analytic_table(book, N_JOKES, seed + 3, evaluable_rate=0.91)
    res = {"config": {"n_owners": n_own, "n_jokes": N_JOKES, "threshold": O.THRESH,
                      "beta_prior": {"a0": a0, "b0": b0, "mean": prior_mean},
                      "bar_f1": BAR_F1, "bar_false_chuckle": BAR_FC,
                      "sliding_window_jokes": SLIDE,
                      "joke_stream": "analytic (uniform category, Bernoulli(p_c)); "
                                     "evaluable rate 0.91 matches the rendered corpus"},
           "regimes": {}}
    regimes = ["clean", E.HEADLINE_REGIME] if quick else list(E.REGIMES)
    for reg in regimes:
        rows = {}
        for name, fn in rules(tab, a0, b0, prior_mean, seed):
            r = E.run_rule(tab, fn, reg, seed=seed + 29)
            rows[name] = summarize(name, tab, r["dec"], seed=seed)
            if name.startswith("beta_mean_2"):
                rows[name]["posterior_bias"] = posterior_bias(tab, r, a0, b0)
        res["regimes"][reg] = rows
        log(f"[FL1b] {reg:14s} "
            + " ".join(f"{k.split('_')[0][:5]}:{v['f1_all60']['median']:.3f}/"
                       f"{v['jokes_to_bar_pooled']}" for k, v in rows.items())
            + f" [{time.time()-t0:.0f}s]")
    res["wall_s"] = round(time.time() - t0, 1)
    out["fl1b"] = res
    return res


def posterior_bias(tab, r, a0, b0):
    """F5: mean posterior minus true p, per owner x category, after all jokes."""
    obs = r["obs"]
    bias = []
    for i in range(tab["n_owners"]):
        for c in range(O.NCAT):
            m = tab["cat"][i] == c
            if m.sum() == 0:
                continue
            k, n = int(obs[i][m].sum()), int(m.sum())
            bias.append((a0 + k) / (a0 + b0 + n) - tab["p"][i][m][0])
    return M.boot_mean(bias)


if __name__ == "__main__":
    import sys
    out = {}
    run(O.SEED_BASE, out, quick="--quick" in sys.argv)
    open("fl1b.json", "w").write(json.dumps(out["fl1b"], indent=1))  # noqa: SIM115
    print("wrote fl1b.json")
