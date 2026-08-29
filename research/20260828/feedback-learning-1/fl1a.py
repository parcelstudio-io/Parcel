"""H-FL1a — in-context adaptation of policy C from the per-category history channel.

AMENDMENTS applied: F1 (owner prior, reward, ORACLE / POPULATION-PRIOR rows),
F2 (per-category history; FL-1's OWN retrain, no BM-1 checkpoint), F3 (window
= jokes 13..32 after 12 observed, 32 jokes/owner, fresh eval seeds, bare-history
-rule baseline, +0.05 margin), F4 (threshold 2/3), F5 (noisy-reward grid;
q=0.1/m=0.3 is the headline).
"""

from __future__ import annotations

import json
import os
import time

import data as D
import engine as E
import metrics as M
import numpy as np
import owners as O
import torch

N_TRAIN_OWNERS = 1000
N_EVAL_OWNERS = 100
N_TRAIN_JOKES = 50
N_EVAL_JOKES = 32
WINDOW = (12, 32)   # F3: F1 over jokes 13..32 (0-based [12, 32))
STEPS = 8000
DEC_WEIGHT = 30.0  # loss weight on anticipatory-decision frames (0.17 % of frames)


def owner_rows(tab, dec, lo, hi):
    """Per-owner metric dicts over the F3 evaluation window."""
    rows = []
    for i in range(tab["n_owners"]):
        m = tab["evaluable"][i, lo:hi]
        r = M.joke_metrics(dec[i, lo:hi][m], tab["laughed"][i, lo:hi][m], tab["liked"][i, lo:hi][m])
        r["regret"] = M.regret(dec[i, lo:hi][m], tab["p"][i, lo:hi][m])
        r["regret_all"] = M.regret(dec[i][tab["evaluable"][i]], tab["p"][i][tab["evaluable"][i]])
        r["wrong"] = M.wrong_chuckles(dec[i][tab["evaluable"][i]], tab["laughed"][i][tab["evaluable"][i]])
        rows.append(r)
    return rows


def summarize(name, tab, dec, seed=0):
    rows = owner_rows(tab, dec, *WINDOW)
    return {
        "rule": name,
        "f1": M.boot_median([r["f1"] for r in rows], seed=seed),
        "false_chuckle_bm1": M.boot_median([r["false_chuckle_bm1"] for r in rows], seed=seed + 1),
        "false_chuckle_strict": M.boot_median([r["false_chuckle_strict"] for r in rows], seed=seed + 2),
        "precision": M.boot_median([r["precision"] for r in rows], seed=seed + 3),
        "recall": M.boot_median([r["recall"] for r in rows], seed=seed + 4),
        "regret_window": M.boot_median([r["regret"] for r in rows], seed=seed + 5),
        "regret_all32": M.boot_median([r["regret_all"] for r in rows], seed=seed + 6),
        "wrong_chuckles_all32": M.boot_median([r["wrong"] for r in rows], seed=seed + 7),
        "pooled_f1_curve": M.pooled_curve(dec, tab["laughed"], tab["evaluable"]),
    }


def run(seed: int, out: dict, log=print, quick: bool = False) -> dict:
    t0 = time.time()
    n_tr = 40 if quick else N_TRAIN_OWNERS
    n_ev = 20 if quick else N_EVAL_OWNERS
    steps = 200 if quick else STEPS

    log(f"[FL1a] building corpora (train {n_tr} owners x {N_TRAIN_JOKES} jokes, "
        f"eval {n_ev} owners x {N_EVAL_JOKES} jokes)")
    train_book = O.owner_book(n_tr, O.TRAIN_SEED_OFFSET, seed=seed)
    eval_book = O.owner_book(n_ev, O.EVAL_SEED_OFFSET, seed=seed)
    tr = D.build_corpus(train_book, N_TRAIN_JOKES, seed)
    ev = D.build_corpus(eval_book, N_EVAL_JOKES, seed + 1)
    tab = E.joke_table(ev, N_EVAL_JOKES)
    log(f"[FL1a] train frames {tr.ch.shape[0]:,} ({len(tr.ep_len)} episodes, "
        f"{len(tr.jokes)} jokes) | eval frames {ev.ch.shape[0]:,} ({len(ev.jokes)} jokes) "
        f"[{time.time()-t0:.0f}s]")

    nets = {}
    for name, use_hist in (("policyC_hist", True), ("policyC_nohist", False)):
        log(f"[FL1a] training {name} ({steps} steps)")
        nets[name] = E.train_policy(tr, use_hist=use_hist, steps=steps, seed=seed,
                                    dec_weight=DEC_WEIGHT, log=log)
    log(f"[FL1a] trained [{time.time()-t0:.0f}s]; params {nets['policyC_hist'].n_params():,}")

    windows = E.eval_windows(ev, tab)
    a0, b0 = E.beta_prior_moments()
    prior_mean = a0 / (a0 + b0)
    log(f"[FL1a] moment-matched population Beta prior: a0={a0:.4f} b0={b0:.4f} mean={prior_mean:.4f}")

    regimes = ["clean", E.HEADLINE_REGIME] if quick else list(E.REGIMES)
    res = {"config": {"n_train_owners": n_tr, "n_eval_owners": n_ev,
                      "n_train_jokes": N_TRAIN_JOKES, "n_eval_jokes": N_EVAL_JOKES,
                      "eval_window_jokes": [WINDOW[0] + 1, WINDOW[1]], "steps": steps,
                      "threshold": O.THRESH, "params": nets["policyC_hist"].n_params(),
                      "train_frames": int(tr.ch.shape[0]), "eval_frames": int(ev.ch.shape[0]),
                      "evaluable_frac": float(np.mean(tab["evaluable"])),
                      "beta_prior": {"a0": a0, "b0": b0, "mean": prior_mean},
                      "history_observed_in_training": "clean (true laugh); noise applied at eval",
                      "decision_frame_loss_weight": DEC_WEIGHT},
           "regimes": {}}

    for reg in regimes:
        rows = {}
        specs = [
            ("oracle", E.rule_oracle(tab)),
            ("population_prior", E.rule_population_prior(tab, prior_mean)),
            ("history_rule_2of3", E.rule_history(tab)),
            ("policyC_hist", E.rule_policy(nets["policyC_hist"], windows, tab, True)),
            ("policyC_nohist", E.rule_policy(nets["policyC_nohist"], windows, tab, False)),
        ]
        for name, fn in specs:
            r = E.run_rule(tab, fn, reg, seed=seed + 17)
            rows[name] = summarize(name, tab, r["dec"], seed=seed)
        res["regimes"][reg] = rows
        h = rows["policyC_hist"]["f1"]["median"]
        log(f"[FL1a] {reg:14s} oracle F1={rows['oracle']['f1']['median']:.3f} "
            f"rule={rows['history_rule_2of3']['f1']['median']:.3f} "
            f"policyC_hist={h:.3f} policyC_nohist={rows['policyC_nohist']['f1']['median']:.3f} "
            f"[{time.time()-t0:.0f}s]")

    # diagnostics: is the signal there at all, independent of calibration?
    diag = {}
    for name, uh in (("policyC_hist", True), ("policyC_nohist", False)):
        pr = E.policy_probs(nets[name], windows, tab, uh)
        m = tab["evaluable"]
        sweep = {}
        for th in (0.4, 0.5, 0.6, 2 / 3, 0.75, 0.8):
            d = pr >= th
            rows = owner_rows(tab, d, *WINDOW)
            sweep[f"{th:.3f}"] = {"f1_median": M.boot_median([r["f1"] for r in rows])["median"],
                                  "false_chuckle_bm1_median":
                                      M.boot_median([r["false_chuckle_bm1"] for r in rows])["median"]}
        diag[name] = {"auroc_vs_laughed": E.auroc(pr[m], tab["laughed"][m]),
                      "auroc_vs_liked": E.auroc(pr[m], tab["liked"][m]),
                      "p_mean": float(pr[m].mean()), "p_max": float(pr[m].max()),
                      "frac_ge_threshold": float((pr[m] >= O.THRESH).mean()),
                      "threshold_sweep": sweep}
        if uh:
            diag[name]["counterfactual_history_probe"] = E.history_probe(nets[name], windows, tab)
    res["diagnostics"] = diag
    log(f"[FL1a] AUROC hist={diag['policyC_hist']['auroc_vs_laughed']:.3f} "
        f"nohist={diag['policyC_nohist']['auroc_vs_laughed']:.3f}")
    log(f"[FL1a] probe {diag['policyC_hist']['counterfactual_history_probe']}")
    res["wall_s"] = round(time.time() - t0, 1)
    out["fl1a"] = res
    torch.save({"hist": nets["policyC_hist"].state_dict(),
                "nohist": nets["policyC_nohist"].state_dict()},
               os.path.expanduser(f"~/.cache/parcel-0e/fl1/policyC_{seed}.pt"))
    return res


if __name__ == "__main__":
    import sys
    out = {}
    run(O.SEED_BASE, out, quick="--quick" in sys.argv)
    p = "fl1a_quick.json" if "--quick" in sys.argv else "fl1a.json"
    open(p, "w").write(json.dumps(out["fl1a"], indent=1))  # noqa: SIM115
    print("wrote", p)
