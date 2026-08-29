"""HS1c — is owner taste real variance rather than noise?

Pre-registered (DESIGN.md): between-user SD of the per-joke rating > 3.0 for the
median joke; a 6-cluster k-means over users' rating vectors beats the global mean
on held-out users by >= 10 % RMSE. Dense core = >= 36 ratings, 80/20 user split,
seed 20260828.

AMENDMENTS.md (binding, POST-START) applied here:
  H5  the baseline is BIASES-ONLY (user mean + joke mean), not the global mean;
      clustering is on bias-centred residuals; each held-out user is assigned
      from a random half of their ratings and scored on the other half; the
      amended bar is >= 10 % RMSE improvement over biases-only. Split-half
      reliability is reported as the noise ceiling. The SD statement is kept
      as a reported number.
  H7  evidence tier = `replay`.

The global-mean comparison the design pre-registered is ALSO reported, so the
original bar and the amended bar can both be adjudicated.
"""
from __future__ import annotations

import json
import time

import numpy as np
from hs_common import HERE, SEED, merge_results

MIN_RATINGS = 36
K = 6
TEST_FRAC = 0.20


def _fit_biases(R, O, n_iter=12):
    """mu + b_user + b_joke by alternating means over observed entries."""
    mu = float(R[O].mean())
    b_u = np.zeros(R.shape[0])
    b_j = np.zeros(R.shape[1])
    for _ in range(n_iter):
        resid = np.where(O, R - mu - b_j[None, :], 0.0)
        cnt = O.sum(axis=1)
        b_u = np.where(cnt > 0, resid.sum(axis=1) / np.maximum(cnt, 1), 0.0)
        resid = np.where(O, R - mu - b_u[:, None], 0.0)
        cnt = O.sum(axis=0)
        b_j = np.where(cnt > 0, resid.sum(axis=0) / np.maximum(cnt, 1), 0.0)
    return mu, b_u, b_j


def _split_half_reliability(R, O, users, seed=SEED, n_rep=20):
    """Users split in half; correlate the two per-joke mean profiles.
    Spearman-Brown corrected -> the reliability ceiling of any joke-level model."""
    from scipy.stats import pearsonr, spearmanr

    rng = np.random.default_rng(seed)
    pear, spear = [], []
    for _ in range(n_rep):
        p = rng.permutation(len(users))
        a, b = users[p[: len(p) // 2]], users[p[len(p) // 2 :]]
        ma = np.array([R[a][O[a][:, j], j].mean() for j in range(R.shape[1])])
        mb = np.array([R[b][O[b][:, j], j].mean() for j in range(R.shape[1])])
        pear.append(pearsonr(ma, mb)[0])
        spear.append(spearmanr(ma, mb)[0])
    def sb(r):  # Spearman-Brown for doubling the sample
        r = float(np.mean(r))
        return 2 * r / (1 + r)
    return {
        "per_joke_mean_profile_pearson_halves": float(np.mean(pear)),
        "per_joke_mean_profile_spearman_halves": float(np.mean(spear)),
        "spearman_brown_corrected_pearson": sb(pear),
        "spearman_brown_corrected_spearman": sb(spear),
        "n_repeats": n_rep,
        "interpretation": "ceiling on how much per-joke signal is reliably estimable; "
                          "a model cannot beat this on the joke-level profile",
    }


def run() -> dict:
    import jester_data
    from sklearn.cluster import KMeans

    t0 = time.time()
    n_rated, R, prov = jester_data.build_matrix()
    O = np.isfinite(R)
    np.where(O, R, 0.0)
    print(f"[hs1c] Jester-1 {R.shape}, {int(O.sum())} ratings, {O.mean():.1%} dense", flush=True)

    # --- reported number (original DESIGN statement) ------------------------
    sd = np.array([R[O[:, j], j].std(ddof=1) for j in range(R.shape[1])])
    print(f"[hs1c] between-user SD per joke: median={np.median(sd):.3f} "
          f"min={sd.min():.3f} max={sd.max():.3f}", flush=True)

    core = np.where(n_rated >= MIN_RATINGS)[0]
    rng = np.random.default_rng(SEED)
    perm = rng.permutation(len(core))
    n_test = round(TEST_FRAC * len(core))
    test_u, train_u = core[perm[:n_test]], core[perm[n_test:]]
    print(f"[hs1c] dense core {len(core)} users; {len(train_u)} train / {len(test_u)} held out",
          flush=True)

    Rtr, Otr = R[train_u], O[train_u]
    mu, b_u_tr, b_j = _fit_biases(Rtr, Otr)
    global_mean = np.array([Rtr[Otr[:, j], j].mean() for j in range(R.shape[1])])
    print(f"[hs1c] biases: mu={mu:.3f} b_joke range [{b_j.min():.2f}, {b_j.max():.2f}]",
          flush=True)

    # --- H5: cluster on bias-centred residuals ------------------------------
    Resid = np.where(Otr, Rtr - (mu + b_u_tr[:, None] + b_j[None, :]), 0.0)
    km = KMeans(n_clusters=K, random_state=SEED, n_init=10)
    labels = km.fit_predict(Resid)
    counts = np.bincount(labels, minlength=K)
    print(f"[hs1c] k={K} residual-cluster sizes: {counts.tolist()}", flush=True)

    # cluster residual profile from OBSERVED train entries
    c_resid = np.zeros((K, R.shape[1]))
    for c in range(K):
        m = labels == c
        Rc, Oc = Resid[m], Otr[m]
        cnt = Oc.sum(axis=0)
        c_resid[c] = np.where(cnt > 0, Rc.sum(axis=0) / np.maximum(cnt, 1), 0.0)
    # cluster ABSOLUTE per-joke mean (for the FL-1 prior)
    c_abs = np.zeros((K, R.shape[1]))
    for c in range(K):
        m = labels == c
        Rc, Oc = Rtr[m], Otr[m]
        for j in range(R.shape[1]):
            s = Oc[:, j]
            c_abs[c, j] = Rc[s, j].mean() if s.any() else global_mean[j]

    # --- held-out scoring: assign on a random half, score the other half ----
    rng2 = np.random.default_rng(SEED + 1)
    se_cluster = se_bias = se_global = 0.0
    n_eval = 0
    assigned = np.zeros(K, dtype=int)
    se_oracle = 0.0
    for u in test_u:
        jj = np.where(O[u])[0]
        if len(jj) < 4:
            continue
        rng2.shuffle(jj)
        h = len(jj) // 2
        a_idx, e_idx = jj[:h], jj[h:]
        # the held-out user's own bias, from the ASSIGN half only
        b_u = float((R[u, a_idx] - mu - b_j[a_idx]).mean())
        res_a = R[u, a_idx] - (mu + b_u + b_j[a_idx])
        d = ((c_resid[:, a_idx] - res_a[None, :]) ** 2).mean(axis=1)
        c = int(np.argmin(d))
        assigned[c] += 1
        y = R[u, e_idx]
        base = mu + b_u + b_j[e_idx]
        se_bias += float(((base - y) ** 2).sum())
        se_cluster += float(((base + c_resid[c, e_idx] - y) ** 2).sum())
        se_global += float(((global_mean[e_idx] - y) ** 2).sum())
        # oracle: best of the 6 clusters for THIS user's eval half (ceiling on
        # what perfect assignment could buy the 6-cluster family)
        se_oracle += float(min(((base + c_resid[k, e_idx] - y) ** 2).sum() for k in range(K)))
        n_eval += len(e_idx)

    rmse = {k: float(np.sqrt(v / n_eval)) for k, v in
            (("cluster", se_cluster), ("biases_only", se_bias),
             ("global_mean", se_global), ("oracle_cluster", se_oracle))}
    imp_bias = (rmse["biases_only"] - rmse["cluster"]) / rmse["biases_only"]
    imp_glob = (rmse["global_mean"] - rmse["cluster"]) / rmse["global_mean"]
    imp_oracle = (rmse["biases_only"] - rmse["oracle_cluster"]) / rmse["biases_only"]
    print(f"[hs1c] held-out RMSE cluster={rmse['cluster']:.4f} "
          f"biases={rmse['biases_only']:.4f} global={rmse['global_mean']:.4f} "
          f"oracle={rmse['oracle_cluster']:.4f}", flush=True)
    print(f"[hs1c] improvement over biases-only = {imp_bias:.2%} "
          f"(amended bar >= 10 %); over global mean = {imp_glob:.2%}", flush=True)

    rel = _split_half_reliability(R, O, core)
    print(f"[hs1c] split-half reliability (Spearman-Brown Pearson) = "
          f"{rel['spearman_brown_corrected_pearson']:.4f}", flush=True)

    # --- FL-1 derived artifact ---------------------------------------------
    prior = {
        "_derived_artifact": (
            "DERIVED ARTIFACT, not a measurement of the Parcel owner. Six k-means "
            "taste clusters over bias-centred residuals of real Jester dataset-1 "
            "users, exported so FL-1 can build synthetic owners whose preference "
            "spread is real human variance rather than invented noise."
        ),
        "source_dataset": "Jester dataset 1 (73,421 users x 100 jokes, ratings -10..10)",
        "produced_by": "research/20260828/humor-signal-1/hs1c_taste.py",
        "seed": SEED, "k": K, "dense_core_min_ratings": MIN_RATINGS,
        "n_train_users": len(train_u), "scale": [-10.0, 10.0],
        "global_mean_rating_per_joke": [round(float(v), 4) for v in global_mean],
        "joke_bias_b_j": [round(float(v), 4) for v in b_j],
        "mu": mu,
        "clusters": [
            {
                "cluster_id": c,
                "weight": float(counts[c] / counts.sum()),
                "n_train_users": int(counts[c]),
                "n_heldout_users_assigned": int(assigned[c]),
                "mean_rating_per_joke": [round(float(v), 4) for v in c_abs[c]],
                "taste_residual_per_joke": [round(float(v), 4) for v in c_resid[c]],
                "mean_rating_overall": float(c_abs[c].mean()),
                "residual_sd": float(c_resid[c].std()),
            }
            for c in range(K)
        ],
    }
    (HERE / "owner_taste_prior.json").write_text(json.dumps(prior, indent=2) + "\n")

    out = {
        "evidence_tier": "replay",
        "amendments_applied": ["H5", "H7"],
        "dataset": "Jester dataset 1",
        "provenance": prov,
        "n_users": int(R.shape[0]), "n_jokes": int(R.shape[1]),
        "n_observed_ratings": int(O.sum()),
        "between_user_sd_per_joke": {
            "median": float(np.median(sd)), "mean": float(sd.mean()),
            "min": float(sd.min()), "max": float(sd.max()),
            "n_jokes_above_3": int((sd > 3.0).sum()),
            "per_joke": [round(float(v), 4) for v in sd],
            "status": "reported number (H5 keeps the DESIGN statement as a report)",
        },
        "dense_core": {"min_ratings": MIN_RATINGS, "n_users": len(core),
                       "n_train": len(train_u), "n_test": len(test_u),
                       "test_frac": TEST_FRAC},
        "biases_model": {"mu": mu, "b_joke_min": float(b_j.min()),
                         "b_joke_max": float(b_j.max()),
                         "fit": "alternating means over train observed entries, 12 iters",
                         "heldout_user_bias": "estimated from the ASSIGN half only"},
        "kmeans": {"k": K, "seed": SEED, "cluster_sizes": counts.tolist(),
                   "cluster_weights": (counts / counts.sum()).round(4).tolist(),
                   "inertia": float(km.inertia_),
                   "features": "bias-centred residuals, missing entries = 0"},
        "heldout_rmse": {
            **rmse,
            "improvement_over_biases_only": float(imp_bias),
            "improvement_over_global_mean": float(imp_glob),
            "oracle_improvement_over_biases_only": float(imp_oracle),
            "n_eval_ratings": int(n_eval),
            "protocol": "each held-out user's ratings split 50/50 (seed 20260829): "
                        "assign half -> user bias + nearest residual centroid on those "
                        "jokes only; eval half scored. No eval rating touches assignment.",
        },
        "noise_ceiling_split_half": rel,
        "seed": SEED, "wall_seconds": round(time.time() - t0, 1),
    }
    merge_results("hs1c", out)
    return out


if __name__ == "__main__":
    r = run()
    skip = {"per_joke_mean_rating", "per_joke_n_ratings", "between_user_sd_per_joke",
            "provenance"}
    print(json.dumps({k: v for k, v in r.items() if k not in skip}, indent=2))
