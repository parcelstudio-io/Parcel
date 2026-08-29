"""H-FL1d — online REINFORCE on policy C's output head vs the bandit.

AMENDMENTS F7: (i) product-realistic arm = trainable head MASKED to
{<emote:chuckle>, <idle>}; (ii) second row = the unmasked full head (naive
online RL); (iii) credit assignment over frames in [punchline, laugh + 1.5 s],
baseline-subtracted running mean, one update per joke, lr 1e-4; (iv) the single
regression pair that counts = compliance F1 and raw M3 extended to
twist/locomotion emission by base_busy, plus cmd:stop compliance, >= 3 seeds,
bootstrap CI on the regression must exclude 0; (v) "faster" = jokes-to-0.8-F1
with CIs on both curves.  Online weights stay under ~/.cache/parcel-0e/.
"""

from __future__ import annotations

import json
import os
import time

import data as D
import engine as E
import fl1b
import fl_world as F
import metrics as M
import numpy as np
import owners as O
import torch
import worldsim as W

import models

N_OWNERS = 100
N_JOKES = 60
N_SEEDS = 3
LR = 1e-4
CREDIT_END = 25          # frames past the punchline reference kept in the credit window
FROZEN_OWNERS = 24
STRIDE, SCORE_FROM = 96, 32


# --------------------------------------------------------------------------
def credit_windows(corpus: D.Corpus, tab: dict):
    """Windows ending CREDIT_END frames past each punchline; decision position."""
    n_own, n_jokes = tab["n_owners"], tab["n_jokes"]
    win = np.zeros((n_own, n_jokes, models.CTX, F.FL_N_CHANNELS), np.int8)
    dec_pos = np.zeros((n_own, n_jokes), np.int64)
    cred_lo = np.zeros((n_own, n_jokes), np.int64)
    cred_hi = np.zeros((n_own, n_jokes), np.int64)
    ep_end = corpus.ep_start + corpus.ep_len
    jj = {(j["owner"], j["n"]): j for j in corpus.jokes}
    for i in range(n_own):
        for n in range(n_jokes):
            j = jj.get((i, n))
            if j is None:
                continue
            g = j["dec"]
            e = int(np.searchsorted(ep_end, g, side="right"))
            lo, hi = int(corpus.ep_start[e]), int(ep_end[e])
            end = min(hi - 1, j["punch"] + CREDIT_END)
            a = max(lo, end - models.CTX + 1)
            w = corpus.ch[a:end + 1]
            pad = models.CTX - len(w)
            win[i, n, pad:] = w
            if pad:
                win[i, n, :pad] = corpus.ch[lo]
            dec_pos[i, n] = pad + (g - a)
            cred_lo[i, n] = pad + (j["punch"] - a)
            top = min(end, (j["laugh_ref"] + 15) if j["laugh_ref"] > 0 else j["punch"] + CREDIT_END)
            cred_hi[i, n] = pad + (top - a)
    return win, dec_pos, np.clip(cred_lo, 0, models.CTX - 1), np.clip(cred_hi, 0, models.CTX - 1)


# --------------------------------------------------------------------------
def reinforce(net, corpus, tab, win, dec_pos, cred_lo, cred_hi, *, masked: bool,
              regime: str, seed: int, lr: float = LR):
    """One update per joke, per owner, on the output head only."""
    n_own, n_jokes = tab["n_owners"], tab["n_jokes"]
    dev = E.DEV
    rng = np.random.default_rng(seed)
    tg = torch.Generator(device="cpu").manual_seed(seed)
    acts_idx = [F.CHUCKLE_ID, F.IDLE_ID]
    W0 = net.head.weight.detach().clone()
    b0 = net.head.bias.detach().clone()
    if masked:
        Wp = W0[acts_idx].unsqueeze(0).repeat(n_own, 1, 1).clone().to(dev).requires_grad_(True)
        bp = b0[acts_idx].unsqueeze(0).repeat(n_own, 1).clone().to(dev).requires_grad_(True)
    else:
        Wp = W0.unsqueeze(0).repeat(n_own, 1, 1).clone().to(dev).requires_grad_(True)
        bp = b0.unsqueeze(0).repeat(n_own, 1).clone().to(dev).requires_grad_(True)
    opt = torch.optim.SGD([Wp, bp], lr=lr)
    hists = [O.HistoryState() for _ in range(n_own)]
    baseline = np.zeros(n_own)
    dec = np.zeros((n_own, n_jokes), bool)
    wt = torch.from_numpy(win.astype(np.int64))
    qm = E.REGIMES[regime]
    for n in range(n_jokes):
        x = wt[:, n].clone()
        hc = torch.from_numpy(np.stack([h.channels() for h in hists]).astype(np.int64))
        x[:, :, F.HIST_SLICE] = hc[:, None, :]
        x = x.to(dev)
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16, enabled=(dev == "cuda")):
            feat = net.features(x).float()
        logits = torch.einsum("btd,bad->bta", feat, Wp) + bp[:, None, :]
        dpos = torch.from_numpy(dec_pos[:, n]).to(dev)
        rows = torch.arange(n_own, device=dev)
        dl = logits[rows, dpos]
        two = dl if masked else dl[:, acts_idx]
        p_ch = torch.softmax(two, dim=-1)[:, 0]
        a = (torch.rand(n_own, generator=tg).to(dev) < p_ch.detach())
        a &= torch.from_numpy(tab["evaluable"][:, n]).to(dev)
        dec[:, n] = a.cpu().numpy()
        # reward: the learner sees the DETECTOR's laugh, not the truth
        obs = np.empty(n_own, bool)
        for i in range(n_own):
            t = bool(tab["laughed"][i, n])
            obs[i] = t if qm is None else O.observe_laugh(t, bool(dec[i, n]), rng, qm[0], qm[1])
            hists[i].observe(int(tab["cat"][i, n]), bool(obs[i]))
        r = np.where(dec[:, n], np.where(obs, O.R_HIT, O.R_FALSE), O.R_NONE)
        adv = torch.from_numpy(r - baseline).float().to(dev)
        baseline = 0.9 * baseline + 0.1 * r
        # log-probs over the credit window: the sampled act at the decision frame,
        # <idle> at every other frame the policy passed through.
        logp = torch.log_softmax(logits if not masked else logits, dim=-1)  # noqa: RUF034
        pos = torch.arange(models.CTX, device=dev)[None, :]
        m = (pos >= torch.from_numpy(cred_lo[:, n]).to(dev)[:, None]) & \
            (pos <= torch.from_numpy(cred_hi[:, n]).to(dev)[:, None])
        idle_col = 1 if masked else F.IDLE_ID
        ch_col = 0 if masked else F.CHUCKLE_ID
        tgt = torch.full((n_own, models.CTX), idle_col, device=dev, dtype=torch.long)
        tgt[rows, dpos] = torch.where(a, torch.tensor(ch_col, device=dev),
                                      torch.tensor(idle_col, device=dev))
        lp = logp.gather(-1, tgt[:, :, None]).squeeze(-1) * m.float()
        loss = -(adv[:, None] * lp).sum(dim=1).mean()
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    return dec, Wp.detach(), bp.detach(), (acts_idx if masked else None)


# --------------------------------------------------------------------------
def frozen_windows(corpus: D.Corpus):
    idx, scored = [], []
    for s, L in zip(corpus.ep_start, corpus.ep_len):
        for a in range(int(s), int(s + L) - models.CTX, STRIDE):
            idx.append(np.arange(a, a + models.CTX))
            m = np.zeros(models.CTX, bool)
            m[SCORE_FROM if a > s else 0:] = True
            scored.append(m)
    return np.stack(idx), np.stack(scored)


def frozen_features(net, corpus, idx, batch: int = 256):
    outs = []
    ch = torch.from_numpy(corpus.ch.astype(np.int64))
    for a in range(0, len(idx), batch):
        x = ch[torch.from_numpy(idx[a:a + batch])].to(E.DEV)
        with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16,
                                             enabled=(E.DEV == "cuda")):
            outs.append(net.features(x).float().cpu())
    return torch.cat(outs)


TWIST_IDS = torch.tensor([W.ACT_ID[t] for t in W.ACT_VOCAB if t.startswith("<twist:")])
BODY_IDS = torch.tensor(sorted(set(W.EMOTE_OR_SKILL_IDS) | set(TWIST_IDS.tolist())))


def regression_scores(pred, corpus, idx, scored) -> dict:
    """Compliance F1, cmd:stop compliance and raw M3 by base_busy (F7)."""
    N = len(corpus.acts)
    emitted = np.full(N, -1, np.int64)
    for row, sm in zip(range(len(idx)), scored):
        emitted[idx[row][sm]] = pred[row][sm]
    seen = emitted >= 0
    ann = corpus.ann
    ev = np.nonzero((ann[:, W.ANN_INDEX["ev_comply"]] == 1) & seen)[0]
    lo, hi = W.WINDOWS["comply"]
    tp = 0
    for f in ev:
        tgt = int(ann[f, W.ANN_INDEX["tgt_comply"]])
        seg = emitted[f + lo:f + hi + 1]
        tp += int((seg == tgt).any())
    fn = len(ev) - tp
    # false positives: skill emissions not inside any comply window
    skill_mask = np.isin(emitted, sorted(W.SKILL_IDS)) & seen
    allowed = np.zeros(N, bool)
    for f in ev:
        allowed[f + lo:f + hi + 1] = True
    fp = int((skill_mask & ~allowed).sum())
    comply_f1 = M.f1(float(tp), float(fp), float(fn))
    # cmd:stop compliance: <idle> within 5 frames of an observed cmd:stop cue
    cue = corpus.ch[:, W.CHANNEL_INDEX["cue"]]
    stop_id = W.CUE.index("cmd:stop")
    stops = np.nonzero((cue == stop_id) & seen)[0]
    ok = sum(1 for f in stops if (emitted[f + 1:f + 6] == W.IDLE_ID).any())
    # raw M3 by base_busy: body-token emission rate before any filter
    busy = corpus.ch[:, W.CHANNEL_INDEX["base_busy"]]
    body = np.isin(emitted, BODY_IDS.numpy()) & seen
    m3 = {}
    for bi, bn in enumerate(("free", "busy", "critical")):
        m = seen & (busy == bi)
        m3[bn] = float(body[m].mean()) if m.any() else float("nan")
    return {"compliance_f1": comply_f1, "compliance_events": len(ev),
            "cmd_stop_compliance": float(ok / max(1, len(stops))),
            "cmd_stop_events": len(stops),
            "raw_m3_body_rate_by_busy": m3}


def head_predict(feat, Wp, bp, mask_ids, frozen_head, n_acts):
    """argmax act per frame for one owner's head (masked heads override 2 rows)."""
    if mask_ids is None:
        lg = feat.to(E.DEV) @ Wp.T + bp
    else:
        lg = feat.to(E.DEV) @ frozen_head[0].T.to(E.DEV) + frozen_head[1].to(E.DEV)
        lg[:, :, mask_ids[0]] = feat.to(E.DEV) @ Wp[0] + bp[0]
        lg[:, :, mask_ids[1]] = feat.to(E.DEV) @ Wp[1] + bp[1]
    return lg.argmax(-1).cpu().numpy()


# --------------------------------------------------------------------------
def run(seed: int, out: dict, log=print, quick: bool = False) -> dict:
    t0 = time.time()
    n_own = 16 if quick else N_OWNERS
    n_jokes = 20 if quick else N_JOKES
    n_seeds = 1 if quick else N_SEEDS
    ck = os.path.expanduser(f"~/.cache/parcel-0e/fl1/policyC_{seed}.pt")
    net = models.BehaviorFormer(F.FL_CHANNEL_SIZES, W.N_ACTS).to(E.DEV)
    net.load_state_dict(torch.load(ck, map_location=E.DEV)["hist"])
    net.eval()
    for p in net.parameters():
        p.requires_grad_(False)

    book = O.owner_book(n_own, O.EVAL_SEED_OFFSET, seed=seed)
    corpus = D.build_corpus(book, n_jokes, seed + 5)
    tab = E.joke_table(corpus, n_jokes)
    win, dec_pos, clo, chi = credit_windows(corpus, tab)
    log(f"[FL1d] corpus {corpus.ch.shape[0]:,} frames, {len(corpus.jokes)} jokes "
        f"[{time.time()-t0:.0f}s]")

    # frozen split: held-out owners, ALL families incl. BM-1's two held-out ones
    fbook = O.owner_book(FROZEN_OWNERS, O.TUNE_SEED_OFFSET, seed=seed)
    fcorp = D.build_corpus(fbook, 8, seed + 9, families=W.FAMILIES)
    fidx, fscored = frozen_windows(fcorp)
    feat = frozen_features(net, fcorp, fidx)
    frozen_head = (net.head.weight.detach().cpu(), net.head.bias.detach().cpu())
    before = regression_scores(
        head_predict(feat, frozen_head[0].to(E.DEV), frozen_head[1].to(E.DEV), None,
                     frozen_head, W.N_ACTS), fcorp, fidx, fscored)
    log(f"[FL1d] frozen split {fcorp.ch.shape[0]:,} frames, {len(fidx)} windows; "
        f"BEFORE {before} [{time.time()-t0:.0f}s]")

    a0, b0 = E.beta_prior_moments()
    res = {"config": {"n_owners": n_own, "n_jokes": n_jokes, "n_seeds": n_seeds, "lr": LR,
                      "credit_window": "[punchline, min(laugh+1.5 s, punchline+2.5 s)]",
                      "frozen_split": {"owners": FROZEN_OWNERS, "episodes": len(fcorp.ep_len),
                                       "frames": int(fcorp.ch.shape[0]),
                                       "families": "all 9 incl. BM-1's two held-out",
                                       "note": "FL-1's own frozen split (BM-1 metric definitions, "
                                               "FL-1 owners + FL-1 chuckle relabel)"},
                      "checkpoint": ck},
           "before": before, "arms": {}}

    for regime in (["clean", E.HEADLINE_REGIME] if not quick else [E.HEADLINE_REGIME]):
        # bandit reference on the SAME joke stream
        bdec = E.run_rule(tab, E.rule_beta(tab, a0, b0), regime, seed=seed + 41)["dec"]
        res["arms"][f"{regime}|bandit_beta_mean_2of3"] = arm_summary(tab, bdec, [], before)
        for masked in (True, False):
            name = "reinforce_head_masked" if masked else "reinforce_head_full"
            decs, afters = [], []
            for s in range(n_seeds):
                dec, Wp, bp, mids = reinforce(net, corpus, tab, win, dec_pos, clo, chi,
                                              masked=masked, regime=regime, seed=seed + 1000 * s)
                decs.append(dec)
                for i in range(min(n_own, 24)):
                    pred = head_predict(feat, Wp[i], bp[i], mids, frozen_head, W.N_ACTS)
                    afters.append(regression_scores(pred, fcorp, fidx, fscored))
                torch.save({"W": Wp.cpu(), "b": bp.cpu(), "mask": mids},
                           os.path.expanduser(
                               f"~/.cache/parcel-0e/fl1/reinforce_{name}_{regime}_s{s}.pt"))
            res["arms"][f"{regime}|{name}"] = arm_summary(tab, np.mean(decs, axis=0) > 0.5,
                                                          afters, before, decs=decs)
            log(f"[FL1d] {regime:14s} {name:22s} "
                f"F1={res['arms'][f'{regime}|{name}']['f1_all']['median']:.3f} "
                f"to_bar={res['arms'][f'{regime}|{name}']['jokes_to_bar_pooled']} "
                f"dComply={res['arms'][f'{regime}|{name}']['delta_compliance_f1']['mean']:+.4f} "
                f"[{time.time()-t0:.0f}s]")
    res["wall_s"] = round(time.time() - t0, 1)
    out["fl1d"] = res
    return res


def arm_summary(tab, dec, afters, before, decs=None):
    s = fl1b.summarize("", tab, dec)
    s["f1_all"] = s.pop("f1_all60")
    if decs:
        bars = [fl1b.jokes_to_bar(*fl1b.sliding_pooled(d, tab)) for d in decs]
        s["jokes_to_bar_per_seed"] = bars
    if afters:
        s["delta_compliance_f1"] = M.boot_mean([a["compliance_f1"] - before["compliance_f1"]
                                                for a in afters])
        s["delta_cmd_stop"] = M.boot_mean([a["cmd_stop_compliance"] - before["cmd_stop_compliance"]
                                           for a in afters])
        for bn in ("free", "busy", "critical"):
            s[f"delta_raw_m3_{bn}"] = M.boot_mean(
                [a["raw_m3_body_rate_by_busy"][bn] - before["raw_m3_body_rate_by_busy"][bn]
                 for a in afters])
        s["after_example"] = afters[0]
    else:
        s["delta_compliance_f1"] = {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n": 0}
    return s


if __name__ == "__main__":
    import sys
    out = {}
    run(O.SEED_BASE, out, quick="--quick" in sys.argv)
    open("fl1d.json", "w").write(json.dumps(out["fl1d"], indent=1))  # noqa: SIM115
    print("wrote fl1d.json")
