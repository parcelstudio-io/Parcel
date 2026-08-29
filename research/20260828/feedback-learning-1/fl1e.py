"""H-FL1e — explicit verbal feedback as a second reward channel (AMENDMENTS F8).

After a false chuckle the owner scolds with p=0.3 (3 negative pseudo-counts +
anticipatory chuckles suppressed for the rest of that session); after a hit the
owner praises with p=0.2 (2 positive pseudo-counts).  20 % of owners reset the
table at joke 30; recovery is measured.
"""

from __future__ import annotations

import json
import time

import engine as E
import fl1b
import metrics as M
import numpy as np
import owners as O

N_OWNERS = 100
N_JOKES = 60
SESSION = 20          # "the rest of the episode" = a 20-joke session
FEEDBACK = {"p_scold": 0.3, "p_praise": 0.2, "scold_counts": 3, "praise_counts": 2,
            "session": SESSION}
RESET_AT = 30


def recovery(dec, tab, resets, reset_at=RESET_AT, w=fl1b.SLIDE):
    """Jokes after the reset until the pooled F1 of reset owners is back at the bar."""
    idx = np.nonzero(resets)[0]
    if idx.size == 0:
        return None
    sub = {k: (v[idx] if isinstance(v, np.ndarray) and v.ndim == 2 else v)
           for k, v in tab.items()}
    sub["n_owners"] = int(idx.size)
    f1s, fcs = fl1b.sliding_pooled(dec[idx], sub, w=w)
    for n in range(reset_at, tab["n_jokes"]):
        if np.isfinite(f1s[n]) and f1s[n] >= fl1b.BAR_F1 and fcs[n] <= fl1b.BAR_FC:
            return n - reset_at + 1
    return None


def run(seed: int, out: dict, log=print, quick: bool = False) -> dict:
    t0 = time.time()
    n_own = 20 if quick else N_OWNERS
    book = O.owner_book(n_own, O.EVAL_SEED_OFFSET, seed=seed)
    a0, b0 = E.beta_prior_moments()
    a0 / (a0 + b0)
    tab = E.analytic_table(book, N_JOKES, seed + 3, evaluable_rate=0.91)
    resets = np.array([o.resets_table for o in book])
    res = {"config": {"n_owners": n_own, "n_jokes": N_JOKES, "feedback": FEEDBACK,
                      "reset_at_joke": RESET_AT,
                      "reset_owner_frac": float(resets.mean()),
                      "note": "'the rest of the episode' = the rest of a 20-joke session"},
           "arms": {}}
    regimes = ["clean", E.HEADLINE_REGIME] if quick else ["clean", E.HEADLINE_REGIME]  # noqa: RUF034
    for reg in regimes:
        for fb_name, fb in (("laughter_only", None), ("laughter_plus_verbal", FEEDBACK)):
            for rname, mk in (("beta_mean_2of3", lambda: E.rule_beta(tab, a0, b0)),
                              ("beta_mean_2of3_detector_debiased",
                               lambda: E.rule_beta_debias(tab, a0, b0))):
                r = E.run_rule(tab, mk(), reg, seed=seed + 31, feedback=fb,
                               reset_at=RESET_AT, resets=resets)
                key = f"{reg}|{fb_name}|{rname}"
                s = fl1b.summarize(rname, tab, r["dec"], seed=seed)
                s["scolds_per_owner"] = M.boot_median(r["scolds"], seed=seed)
                s["praises_per_owner"] = M.boot_median(r["praises"], seed=seed)
                s["recovery_jokes_after_reset"] = recovery(r["dec"], tab, resets)
                res["arms"][key] = s
                log(f"[FL1e] {key:62s} F1={s['f1_all60']['median']:.3f} "
                    f"to_bar={s['jokes_to_bar_pooled']} "
                    f"wrong={s['wrong_chuckles_all60']['median']:.0f} "
                    f"recov={s['recovery_jokes_after_reset']}")
    res["wall_s"] = round(time.time() - t0, 1)
    out["fl1e"] = res
    return res


if __name__ == "__main__":
    import sys
    out = {}
    run(O.SEED_BASE, out, quick="--quick" in sys.argv)
    open("fl1e.json", "w").write(json.dumps(out["fl1e"], indent=1))  # noqa: SIM115
    print("wrote fl1e.json")
