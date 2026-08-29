"""FL-1 shared engine: joke tables, decision-rule runners, policy-C train/eval."""

from __future__ import annotations

import math
import time

import data as D
import fl_world as F
import numpy as np
import owners as O
import torch
import worldsim as W

import models

DEV = "cuda" if torch.cuda.is_available() else "cpu"
CHUCKLE_ID = F.CHUCKLE_ID
IDLE_ID = F.IDLE_ID


# --------------------------------------------------------------------------
# joke table
# --------------------------------------------------------------------------
def joke_table(corpus: D.Corpus, n_jokes: int) -> dict:
    n_own = len(corpus.owners)
    cat = np.zeros((n_own, n_jokes), np.int64)
    laughed = np.zeros((n_own, n_jokes), bool)
    evalu = np.zeros((n_own, n_jokes), bool)
    dec_f = np.full((n_own, n_jokes), -1, np.int64)
    for j in corpus.jokes:
        if j["n"] < n_jokes:
            cat[j["owner"], j["n"]] = j["cat"]
            laughed[j["owner"], j["n"]] = j["laughed"]
            evalu[j["owner"], j["n"]] = j["evaluable"]
            dec_f[j["owner"], j["n"]] = j["dec"]
    p_true = np.stack([o.p_laugh for o in corpus.owners])          # (n_own, 6)
    p_joke = np.take_along_axis(p_true, cat.reshape(n_own, -1) % O.NCAT, axis=1).reshape(cat.shape) \
        if False else np.array([[corpus.owners[i].p_laugh[cat[i, n]] for n in range(n_jokes)]
                                for i in range(n_own)])
    liked = p_joke >= O.THRESH
    return {"cat": cat, "laughed": laughed, "evaluable": evalu, "dec_f": dec_f,
            "p": p_joke, "liked": liked, "n_owners": n_own, "n_jokes": n_jokes}


# --------------------------------------------------------------------------
# observation regimes (F5)
# --------------------------------------------------------------------------
REGIMES = {
    "clean": None,                       # obs = the true laugh (ceiling)
    "det_q0.0_m0.0": (0.0, 0.0),
    "det_q0.0_m0.3": (0.0, 0.3),
    "det_q0.1_m0.0": (0.1, 0.0),
    "det_q0.1_m0.3": (0.1, 0.3),         # HEADLINE (F5)
    "det_q0.3_m0.0": (0.3, 0.0),
    "det_q0.3_m0.3": (0.3, 0.3),
}
HEADLINE_REGIME = "det_q0.1_m0.3"


def run_rule(tab: dict, decide, regime: str, seed: int, detector: dict | None = None,
             reset_at: int | None = None, resets: np.ndarray | None = None,
             feedback: dict | None = None) -> dict:
    """Sequential closed-loop run of one decision rule over every owner's jokes.

    ``decide(n, hists, cats, extra) -> (n_owners,) bool``.
    """
    n_own, n_jokes = tab["n_owners"], tab["n_jokes"]
    rng = np.random.default_rng(seed)
    hists = [O.HistoryState() for _ in range(n_own)]
    dec = np.zeros((n_own, n_jokes), bool)
    obsv = np.zeros((n_own, n_jokes), bool)
    suppressed = np.zeros(n_own, bool)          # F8: scold suppresses for the session
    scolds = np.zeros(n_own, np.int64)
    praises = np.zeros(n_own, np.int64)
    qm = REGIMES[regime]
    session = feedback.get("session", 20) if feedback else 20
    for n in range(n_jokes):
        if reset_at is not None and n == reset_at and resets is not None:
            for i in np.nonzero(resets)[0]:
                hists[i].reset()
        if feedback and n % session == 0:
            suppressed[:] = False
        d = np.asarray(decide(n, hists, tab["cat"][:, n]), dtype=bool)
        d &= tab["evaluable"][:, n]
        if feedback is not None:
            d &= ~suppressed
        dec[:, n] = d
        for i in range(n_own):
            true_l = bool(tab["laughed"][i, n])
            if qm is None:
                o = true_l
            else:
                o = O.observe_laugh(true_l, bool(d[i]), rng, qm[0], qm[1], detector)
            obsv[i, n] = o
            hists[i].observe(int(tab["cat"][i, n]), o)
            if feedback is not None and d[i]:
                if not true_l and rng.random() < feedback["p_scold"]:
                    scolds[i] += 1
                    suppressed[i] = True
                    for _ in range(feedback["scold_counts"]):
                        hists[i].total[tab["cat"][i, n]] += 1
                elif true_l and rng.random() < feedback["p_praise"]:
                    praises[i] += 1
                    for _ in range(feedback["praise_counts"]):
                        hists[i].total[tab["cat"][i, n]] += 1
                        hists[i].laughed[tab["cat"][i, n]] += 1
    return {"dec": dec, "obs": obsv, "scolds": scolds, "praises": praises}


# --------------------------------------------------------------------------
# decision rules
# --------------------------------------------------------------------------
def rule_oracle(tab):
    return lambda n, hists, cats: tab["p"][:, n] >= O.THRESH


def rule_population_prior(tab, prior_mean: float):
    return lambda n, hists, cats: np.full(tab["n_owners"], prior_mean >= O.THRESH)


def rule_history(tab):
    def f(n, hists, cats):
        return np.array([h.rule_decision(int(c)) for h, c in zip(hists, cats)])
    return f


def beta_prior_moments(prior=None) -> tuple[float, float]:
    """Moment-matched Beta for the population taste prior (F1 mixture)."""
    prior = prior or O.TASTE_PRIOR
    w = prior["w_like"]
    (a1, b1), (a2, b2) = prior["like"], prior["dislike"]
    m1, m2 = a1 / (a1 + b1), a2 / (a2 + b2)
    v1 = a1 * b1 / ((a1 + b1) ** 2 * (a1 + b1 + 1))
    v2 = a2 * b2 / ((a2 + b2) ** 2 * (a2 + b2 + 1))
    mu = w * m1 + (1 - w) * m2
    ex2 = w * (v1 + m1 ** 2) + (1 - w) * (v2 + m2 ** 2)
    var = ex2 - mu ** 2
    nu = mu * (1 - mu) / var - 1.0
    return max(1e-3, mu * nu), max(1e-3, (1 - mu) * nu)


def rule_beta(tab, a0: float, b0: float, thompson: bool = False, seed: int = 0,
              thresh: float = O.THRESH):
    rng = np.random.default_rng(seed)

    def f(n, hists, cats):
        a = np.array([a0 + h.laughed[int(c)] for h, c in zip(hists, cats)], float)
        b = np.array([b0 + (h.total[int(c)] - h.laughed[int(c)]) for h, c in zip(hists, cats)], float)
        if thompson:
            return rng.beta(a, b) >= thresh
        return a / (a + b) >= thresh
    return f


def _mixture_post(h: O.HistoryState, c: int, prior=None):
    prior = prior or O.TASTE_PRIOR
    w = prior["w_like"]
    comps = [(w, *prior["like"]), (1 - w, *prior["dislike"])]
    k, m = int(h.laughed[c]), int(h.total[c] - h.laughed[c])
    post, mean = [], 0.0
    for pw, a, b in comps:
        lw = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
              + math.lgamma(a + k) + math.lgamma(b + m) - math.lgamma(a + b + k + m))
        post.append(math.log(pw) + lw)
    mx = max(post)
    ws = [math.exp(p - mx) for p in post]
    z = sum(ws)
    for wi, (pw, a, b) in zip(ws, comps):
        mean += (wi / z) * (a + k) / (a + b + k + m)
    return mean


def rule_beta_debias(tab, a0: float, b0: float, det: dict | None = None,
                     thresh: float = O.THRESH):
    """Beta posterior corrected for the KNOWN detector operating point (F5).

    p_obs = p_true (1 - fn) + (1 - p_true) fp  ->  p_true = (p_obs - fp)/(1 - fn - fp).
    """
    det = det or O.DETECTOR
    fn, fp = det["false_negative"], det["false_positive"]

    def f(n, hists, cats):
        a = np.array([a0 + h.laughed[int(c)] for h, c in zip(hists, cats)], float)
        b = np.array([b0 + (h.total[int(c)] - h.laughed[int(c)]) for h, c in zip(hists, cats)], float)
        m = np.clip(((a / (a + b)) - fp) / (1.0 - fn - fp), 0.0, 1.0)
        return m >= thresh
    return f


def rule_beta_mixture(tab, thresh: float = O.THRESH):
    def f(n, hists, cats):
        return np.array([_mixture_post(h, int(c)) >= thresh for h, c in zip(hists, cats)])
    return f


# --------------------------------------------------------------------------
# policy C
# --------------------------------------------------------------------------
def train_policy(corpus: D.Corpus, *, use_hist: bool, steps: int, seed: int,
                 batch: int = 64, lr: float = 3e-4, dec_weight: float = 30.0,
                 log=print) -> models.BehaviorFormer:
    torch.manual_seed(seed)
    ch = torch.from_numpy(corpus.ch)          # int8, cast per batch
    acts = torch.from_numpy(corpus.acts.astype(np.int16))
    dmask = torch.from_numpy(corpus.dec_mask)
    starts, lens = corpus.ep_start, corpus.ep_len
    ok = lens > models.CTX + 1
    starts, lens = starts[ok], lens[ok]
    w = lens / lens.sum()
    net = models.BehaviorFormer(F.FL_CHANNEL_SIZES, W.N_ACTS).to(DEV)
    opt = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=0.01, betas=(0.9, 0.95))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / 100) * 0.5 * (1 + math.cos(math.pi * min(1.0, s / steps))))
    rng = np.random.default_rng(seed)
    t0 = time.time()
    net.train()
    for step in range(steps):
        ei = rng.choice(len(starts), size=batch, p=w)
        off = np.array([starts[e] + rng.integers(0, lens[e] - models.CTX) for e in ei])
        idx = torch.from_numpy(off[:, None] + np.arange(models.CTX)[None, :])
        x = ch[idx].to(DEV, non_blocking=True).long()
        if not use_hist:
            x[:, :, F.HIST_SLICE] = 0
        y = acts[idx].to(DEV, non_blocking=True).long()
        wgt = 1.0 + (dec_weight - 1.0) * dmask[idx].to(DEV, non_blocking=True).float()
        with torch.autocast("cuda", dtype=torch.bfloat16, enabled=(DEV == "cuda")):
            logits = net(x)
            ce = torch.nn.functional.cross_entropy(
                logits.reshape(-1, W.N_ACTS), y.reshape(-1), reduction="none")
            loss = (ce * wgt.reshape(-1)).sum() / wgt.sum()
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
        opt.step()
        sched.step()
        if step % 250 == 0 or step == steps - 1:
            log(f"    step {step:5d}/{steps} loss {loss.item():.4f} "
                f"({time.time() - t0:.0f}s)")
    net.eval()
    return net


def eval_windows(corpus: D.Corpus, tab: dict) -> np.ndarray:
    """(n_owners, n_jokes, CTX, C) int8 windows ending at each decision frame."""
    n_own, n_jokes = tab["n_owners"], tab["n_jokes"]
    out = np.zeros((n_own, n_jokes, models.CTX, F.FL_N_CHANNELS), np.int8)
    ep_end = corpus.ep_start + corpus.ep_len
    for i in range(n_own):
        for n in range(n_jokes):
            g = int(tab["dec_f"][i, n])
            if g < 0:
                continue
            e = int(np.searchsorted(ep_end, g, side="right"))
            lo = int(corpus.ep_start[e])
            a = max(lo, g - models.CTX + 1)
            win = corpus.ch[a:g + 1]
            out[i, n, models.CTX - len(win):] = win
            if len(win) < models.CTX:
                out[i, n, :models.CTX - len(win)] = corpus.ch[lo]
    return out


def rule_policy(net, windows: np.ndarray, tab: dict, use_hist: bool,
                thresh: float = O.THRESH, store: dict | None = None):
    """Closed-loop decision rule reading the model's P(chuckle | chuckle or idle)."""
    wt = torch.from_numpy(windows.astype(np.int64))

    def f(n, hists, cats):
        x = wt[:, n].clone()
        hc = torch.from_numpy(np.stack([h.channels() for h in hists]).astype(np.int64))
        if use_hist:
            x[:, :, F.HIST_SLICE] = hc[:, None, :]
        else:
            x[:, :, F.HIST_SLICE] = 0
        x = x.to(DEV)
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16, enabled=(DEV == "cuda")):
            lg = net(x)[:, -1].float()
        pair = torch.softmax(lg[:, [CHUCKLE_ID, IDLE_ID]], dim=-1)[:, 0].cpu().numpy()
        if store is not None:
            store.setdefault("p", []).append(pair)
        return pair >= thresh
    return f


# --------------------------------------------------------------------------
# analytic joke table (identical distribution, no frames) -- used by FL1b/FL1e
# --------------------------------------------------------------------------
def analytic_table(book, n_jokes: int, seed: int, evaluable_rate: float = 1.0) -> dict:
    n_own = len(book)
    rng = np.random.default_rng(seed)
    cat = rng.integers(0, O.NCAT, size=(n_own, n_jokes))
    p = np.array([[book[i].p_laugh[cat[i, n]] for n in range(n_jokes)] for i in range(n_own)])
    laughed = rng.random((n_own, n_jokes)) < p
    evalu = rng.random((n_own, n_jokes)) < evaluable_rate
    return {"cat": cat, "laughed": laughed, "evaluable": evalu,
            "dec_f": np.full((n_own, n_jokes), -1, np.int64),
            "p": p, "liked": p >= O.THRESH, "n_owners": n_own, "n_jokes": n_jokes,
            "owners": list(book)}


def auroc(p, y) -> float:
    p, y = np.asarray(p, float), np.asarray(y, bool)
    if y.all() or not y.any():
        return float("nan")
    r = np.argsort(np.argsort(p)) + 1.0
    n1, n0 = int(y.sum()), int((~y).sum())
    return float((r[y].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def policy_probs(net, windows, tab, use_hist: bool, hist_from_corpus: bool = True):
    """P(chuckle | chuckle or idle) at every decision frame, replaying the owner's
    own clean history (open loop) -- used for AUROC / threshold sweeps."""
    n_own, n_jokes = tab["n_owners"], tab["n_jokes"]
    out = np.zeros((n_own, n_jokes))
    hists = [O.HistoryState() for _ in range(n_own)]
    wt = torch.from_numpy(windows)
    for n in range(n_jokes):
        x = wt[:, n].clone().long()
        hc = torch.from_numpy(np.stack([h.channels() for h in hists]).astype(np.int64))
        x[:, :, F.HIST_SLICE] = 0 if not use_hist else hc[:, None, :]
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16, enabled=(DEV == "cuda")):
            lg = net(x.to(DEV))[:, -1].float()
        out[:, n] = torch.softmax(lg[:, [CHUCKLE_ID, IDLE_ID]], -1)[:, 0].cpu().numpy()
        for i in range(n_own):
            hists[i].observe(int(tab["cat"][i, n]), bool(tab["laughed"][i, n]))
    return out


def history_probe(net, windows, tab, n: int = 20):
    """Counterfactual: force the CURRENT category's history and watch P(chuckle)."""
    x0 = torch.from_numpy(windows[:, n]).long()
    cats = tab["cat"][:, n]
    res = {}
    for name, (lg_, tot, rec) in {"7of7_laughed": (7, 7, 1), "0of7_silent": (0, 7, 2),
                                  "4of4_laughed": (4, 4, 1), "0of4_silent": (0, 4, 2),
                                  "unseen_0of0": (0, 0, 0)}.items():
        x = x0.clone()
        for i, c in enumerate(cats):
            b = F.HIST_SLICE.start + 3 * int(c)
            x[i, :, b], x[i, :, b + 1], x[i, :, b + 2] = lg_, tot, rec
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16, enabled=(DEV == "cuda")):
            lgts = net(x.to(DEV))[:, -1].float()
        pv = torch.softmax(lgts[:, [CHUCKLE_ID, IDLE_ID]], -1)[:, 0].cpu().numpy()
        res[name] = {"mean": float(pv.mean()), "max": float(pv.max()),
                     "frac_ge_thresh": float((pv >= O.THRESH).mean())}
    return res
