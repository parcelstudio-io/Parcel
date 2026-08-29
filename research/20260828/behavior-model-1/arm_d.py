"""Arm D — LoRA on a pretrained instruct LM over the same frame stream as text.

Input  : the last 32 frames as text lines, including the raw transcript words.
Target : the next act token, written out (``<emote:chuckle>``), decoded greedily
         (= the A4 argmax rule).
LoRA   : r=16 on attention + MLP projections, bf16, <= 12 GB.

Arm D is evaluated on a *subset* of episodes because a 0.5 B forward per frame
is three orders of magnitude more expensive than arm C's; the exact episode and
event counts are recorded in the result so the reduced N is visible.
"""

from __future__ import annotations

import json
import time

import arms
import eval as ev
import numpy as np
import torch
from worldsim import ACT_ID, ACT_VOCAB, CHANNEL_INDEX, CUE, IDLE_ID, PHRASES

MODELS = ("Qwen/Qwen2.5-0.5B-Instruct", "HuggingFaceTB/SmolLM2-360M-Instruct")
CTX = 32
MAX_TOK = 400


_ACT_SHORT = {"<idle>": "."}


def _fields(split: ev.Split, t: int) -> list[str]:
    """The frame as a list of ``key=value`` fields (order is stable)."""

    from worldsim import (
        _BUSY_S,
        _DIST_S,
        _DLG_S,
        _MOT_S,
        _TASK_S,
        _TSS_S,
        _TSTATE_S,
        _VIS_S,
        CUE_CONF,
        OBSTACLE,
        SELF_ACT,
    )

    ci = CHANNEL_INDEX
    r = split.channels[t]
    out = [f"d={_DLG_S[int(r[ci['dlg']])]}"]
    cue = int(r[ci["cue"]])
    if cue:
        out.append(f"cue={CUE[cue]}/{CUE_CONF[int(r[ci['cue_conf']])]}")
        out.append(f"va={int(r[ci['val']]) - 2}{int(r[ci['aro']])}")
    vis = int(r[ci["own_vis"]])
    if vis == 0:
        out.append(
            f"own={_DIST_S[int(r[ci['own_dist']])]},b{int(r[ci['own_bear']])},"
            f"{'eye' if int(r[ci['own_gaze']]) == 0 else 'away'},"
            f"{_MOT_S[int(r[ci['own_motion']])]}"
        )
    else:
        out.append(f"own={_VIS_S[vis]},{_TSS_S[int(r[ci['t_since_seen']])]}")
    out.append(f"s={SELF_ACT[int(r[ci['self_act']])]}")
    out.append(f"b={_BUSY_S[int(r[ci['base_busy']])]}")
    out.append(f"k={_TASK_S[int(r[ci['task']])]}/{_TSTATE_S[int(r[ci['task_state']])]}")
    ob = int(r[ci["obstacle"]])
    if ob:
        out.append(f"o={OBSTACLE[ob]}")
    w = int(split.words[t])
    if w >= 0:
        out.append(f'w="{PHRASES.strings[w]}"')
    return out


def render_prompt(split: ev.Split, s: int, f: int) -> str:
    """Frames [f-31 .. f] as text lines.

    History lines are *delta encoded* (only fields that changed since the
    previous frame are printed; ``~`` means nothing changed) so that 32 frames
    of context fit in ~200 LM tokens.  The frame to predict is always printed
    in full.  The raw transcript words are always printed when present.
    """

    from worldsim import ENV, HIST, PROF_GREET, PROF_PACE, PROF_PRAISE, PROF_SENS

    ci = CHANNEL_INDEX
    lo = max(s, f - CTX + 1)
    r0 = split.channels[lo]
    hist = ",".join(HIST[int(r0[ci[f"hist{k}"]])] for k in range(6))
    lines = [
        (f"# {ENV[int(r0[ci['env']])]} "
        f"{PROF_GREET[int(r0[ci['prof_greet']])]}/"
        f"{PROF_PRAISE[int(r0[ci['prof_praise']])]}/"
        f"{PROF_PACE[int(r0[ci['prof_pace']])]}/"
        f"{PROF_SENS[int(r0[ci['prof_sens']])]} h={hist}")
    ]
    prev: list[str] = []
    for t in range(lo, f):
        cur = _fields(split, t)
        if t == lo:
            body = " ".join(cur)
        else:
            pk = {x.split("=", 1)[0]: x for x in prev}
            changed = [x for x in cur if pk.get(x.split("=", 1)[0]) != x]
            gone = [k for k in pk if k not in {x.split("=", 1)[0] for x in cur}]
            body = " ".join(changed + [f"-{k}" for k in gone]) or "~"
        act = ACT_VOCAB[int(split.acts[t])]
        lines.append(f"{body} > {_ACT_SHORT.get(act, act)}")
        prev = cur
    lines.append(" ".join(_fields(split, f)) + " >")
    return "\n".join(lines)


def load_model(seed: int):
    from transformers import AutoModelForCausalLM, AutoTokenizer

    last = None
    for name in MODELS:
        try:
            tok = AutoTokenizer.from_pretrained(name)
            model = AutoModelForCausalLM.from_pretrained(name, dtype=torch.bfloat16)
            arms.log(f"[D] loaded {name}", tag="arm_D")
            return name, tok, model
        except Exception as exc:  # pragma: no cover  # noqa: BLE001
            arms.log(f"[D] load failed for {name}: {exc!r}", tag="arm_D")
            last = exc
    raise RuntimeError(f"no LM available: {last!r}")


def build_examples(train: ev.Split, n: int, seed: int) -> list[tuple[int, int]]:
    """Frames sampled with probability ~ n_c^-0.5 (the A4 class reweighting)."""

    w = arms.class_weights(train).numpy()
    p = w[train.acts]
    # never start a window before its episode
    ok = np.zeros(train.n_frames, dtype=bool)
    for ei in range(train.n_episodes):
        s, e = train.episode(ei)
        ok[s + CTX : e] = True
    p = p * ok
    p = p / p.sum()
    rng = np.random.default_rng(seed)
    idx = rng.choice(train.n_frames, size=n, replace=False, p=p)
    starts = np.zeros(train.n_frames, dtype=np.int64)
    for ei in range(train.n_episodes):
        s, e = train.episode(ei)
        starts[s:e] = s
    return [(int(starts[i]), int(i)) for i in sorted(idx.tolist())]


def train_lora(train: ev.Split, *, seed: int, budget_s: float, n_examples: int = 200_000):
    from peft import LoraConfig, get_peft_model

    arms.set_determinism(seed)
    name, tok, model = load_model(seed)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    cfg = LoraConfig(
        r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, cfg).to("cuda")
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    arms.log(f"[D] LoRA trainable={trainable/1e6:.2f}M / {total/1e6:.1f}M", tag="arm_D")

    ex = build_examples(train, n_examples, seed)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4)
    batch = 32
    t0 = time.time()
    model.train()
    step = 0
    losses: list[float] = []
    sched = None
    while time.time() - t0 < budget_s and step * batch < len(ex):
        chunk = ex[step * batch : (step + 1) * batch]
        if not chunk:
            break
        prompts = [render_prompt(train, s, f) + " " for s, f in chunk]
        targets = [_ACT_SHORT.get(ACT_VOCAB[int(train.acts[f])],
                                   ACT_VOCAB[int(train.acts[f])]) + tok.eos_token
                   for _, f in chunk]
        enc_p = [tok(p, add_special_tokens=False)["input_ids"][-MAX_TOK:] for p in prompts]
        enc_t = [tok(t, add_special_tokens=False)["input_ids"] for t in targets]
        maxlen = max(len(a) + len(b) for a, b in zip(enc_p, enc_t))
        ids = torch.full((len(chunk), maxlen), tok.pad_token_id, dtype=torch.long)
        lab = torch.full((len(chunk), maxlen), -100, dtype=torch.long)
        att = torch.zeros((len(chunk), maxlen), dtype=torch.long)
        for i, (a, b) in enumerate(zip(enc_p, enc_t)):
            seq = a + b
            ids[i, : len(seq)] = torch.tensor(seq)
            att[i, : len(seq)] = 1
            lab[i, len(a) : len(seq)] = torch.tensor(b)
        out = model(input_ids=ids.to("cuda"), attention_mask=att.to("cuda"),
                    labels=lab.to("cuda"))
        out.loss.backward()
        torch.nn.utils.clip_grad_norm_(
            [p for p in model.parameters() if p.requires_grad], 1.0)
        opt.zero_grad(set_to_none=True) if False else None
        opt.step()
        opt.zero_grad(set_to_none=True)
        if sched is None and step == 20:
            rate = 20 / max(1e-6, time.time() - t0)
            total_steps = int(budget_s * rate * 0.92)
            sched = torch.optim.lr_scheduler.CosineAnnealingLR(
                opt, T_max=max(1, total_steps - 20))
            arms.log(f"[D] {rate:.2f} step/s -> planning {total_steps} steps "
                     f"({total_steps * batch} examples)", tag="arm_D")
        elif sched is not None:
            sched.step()
        losses.append(float(out.loss.item()))
        step += 1
        if step % 50 == 0:
            arms.log(f"[D] step {step} loss={np.mean(losses[-50:]):.4f} "
                     f"elapsed={time.time() - t0:.0f}s tok/ex={maxlen}", tag="arm_D")
    stats = {
        "model": name,
        "steps_run": step,
        "batch": batch,
        "examples_seen": step * batch,
        "train_frames_seen": step * batch,
        "wall_s": round(time.time() - t0, 1),
        "final_loss": round(float(np.mean(losses[-50:])) if losses else float("nan"), 4),
        "lora_trainable_params": trainable,
        "gpu_peak_mb": round(torch.cuda.max_memory_allocated() / 1e6, 1),
        "context_frames": CTX,
        "max_prompt_tokens": MAX_TOK,
    }
    model.save_pretrained(str(arms.CKPT_DIR / "arm_D"))
    return model, tok, stats


@torch.inference_mode()
def predict(model, tok, split: ev.Split, ep_ids: list[int], *, batch: int = 96,
            budget_s: float = 900.0) -> tuple[np.ndarray, dict]:
    """Greedy decode for every frame of the selected episodes (A4 argmax)."""

    model.eval()
    pred = np.full(split.n_frames, IDLE_ID, dtype=np.int64)
    frames: list[tuple[int, int]] = []
    for ei in ep_ids:
        s, e = split.episode(ei)
        frames.extend((s, f) for f in range(s, e))
    tok.padding_side = "left"
    invalid = 0
    t0 = time.time()
    done = 0
    for i in range(0, len(frames), batch):
        if time.time() - t0 > budget_s:
            arms.log(f"[D] predict budget hit at {done}/{len(frames)} frames", tag="arm_D")
            break
        chunk = frames[i : i + batch]
        prompts = [render_prompt(split, s, f) + " " for s, f in chunk]
        enc = tok(prompts, return_tensors="pt", padding=True, truncation=True,
                  max_length=MAX_TOK, add_special_tokens=False).to("cuda")
        gen = model.generate(**enc, max_new_tokens=14, do_sample=False,
                             num_beams=1, pad_token_id=tok.pad_token_id)
        new = gen[:, enc["input_ids"].shape[1] :]
        texts = tok.batch_decode(new, skip_special_tokens=True)
        for (s, f), txt in zip(chunk, texts):
            t = txt.strip().split("\n")[0].strip()
            if t == ".":
                t = "<idle>"
            if t in ACT_ID:
                pred[f] = ACT_ID[t]
            else:
                invalid += 1
                pred[f] = IDLE_ID
        done += len(chunk)
        if (i // batch) % 25 == 0:
            arms.log(f"[D] predict {done}/{len(frames)} ({time.time() - t0:.0f}s) "
                     f"invalid={invalid}", tag="arm_D")
    return pred, {"frames_decoded": done, "frames_requested": len(frames),
                  "invalid_token_outputs": invalid,
                  "invalid_rate": round(invalid / max(1, done), 5),
                  "wall_s": round(time.time() - t0, 1)}


def sub_split(split: ev.Split, ep_ids: list[int], name: str) -> tuple[ev.Split, np.ndarray]:
    """A view containing only the selected episodes (so FP counting is honest)."""

    idx = []
    starts, lens = [], []
    off = 0
    for ei in ep_ids:
        s, e = split.episode(ei)
        idx.append(np.arange(s, e))
        starts.append(off)
        lens.append(e - s)
        off += e - s
    sel = np.concatenate(idx)
    out = ev.Split(
        name=name, channels=split.channels[sel], acts=split.acts[sel],
        words=split.words[sel], ann=split.ann[sel],
        ep_start=np.asarray(starts, dtype=np.int64), ep_len=np.asarray(lens, dtype=np.int64),
        ep_family=split.ep_family[ep_ids], ep_flags=split.ep_flags[ep_ids],
        acts_ceiling=None if split.acts_ceiling is None else split.acts_ceiling[sel],
    )
    return out, sel


@torch.inference_mode()
def latency(model, tok, split: ev.Split, *, device: str, n: int) -> dict:
    model.eval()
    rng = np.random.default_rng(11)
    s0, e0 = split.episode(0)
    frames = [(s0, int(x)) for x in rng.integers(s0 + CTX, e0, size=n)]
    if device == "cpu":
        torch.set_num_threads(1)
        model = model.to("cpu")
    times = []
    for k, (s, f) in enumerate(frames):
        p = render_prompt(split, s, f) + " "
        enc = tok(p, return_tensors="pt", add_special_tokens=False,
                  truncation=True, max_length=MAX_TOK).to(device)
        if device == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        model.generate(**enc, max_new_tokens=14, do_sample=False, num_beams=1,
                       pad_token_id=tok.pad_token_id)
        if device == "cuda":
            torch.cuda.synchronize()
        if k >= 5:
            times.append((time.perf_counter() - t0) * 1000.0)
    if device == "cpu":
        model.to("cuda")
        torch.set_num_threads(32)
    a = np.asarray(times)
    return {"device": device, "threads": 1 if device == "cpu" else None, "n": len(a),
            "p50_ms": round(float(np.percentile(a, 50)), 2),
            "p99_ms": round(float(np.percentile(a, 99)), 2),
            "mean_ms": round(float(a.mean()), 2)}


def mask_cues(split: ev.Split, name: str) -> ev.Split:
    """A5: hide the cue label on command / joke frames; only `words` remains."""

    ch = split.channels.copy()
    cue = ch[:, CHANNEL_INDEX["cue"]]
    hide = np.zeros(len(cue), dtype=bool)
    for k, kind in enumerate(CUE):
        if kind.startswith("cmd:") or kind in ("joke_setup", "joke_punchline", "laugh"):
            hide |= cue == k
    ch[hide, CHANNEL_INDEX["cue"]] = 0
    ch[hide, CHANNEL_INDEX["cue_conf"]] = 1  # "lo"
    from dataclasses import replace as _replace

    return _replace(split, channels=ch, name=name)


def ngram_overlap(train: ev.Split, held: ev.Split, n: int = 4) -> dict:
    def grams(split):
        out = set()
        ids = np.unique(split.words[split.words >= 0])
        for i in ids:
            w = PHRASES.strings[int(i)].split()
            for j in range(len(w) - n + 1):
                out.add(" ".join(w[j : j + n]))
        return out

    a, b = grams(train), grams(held)
    inter = a & b
    return {"n": n, "train_ngrams": len(a), "slice_ngrams": len(b),
            "shared": len(inter),
            "slice_fraction_seen_in_train": round(len(inter) / max(1, len(b)), 4)}


def run(train, dev, frozen, frozen_parts, *, seed, budget_s, results, res_path, out,
        host_state):
    from worldsim import FROZEN_SPLITS

    h0 = host_state()
    model, tok, stats = train_lora(train, seed=seed, budget_s=budget_s)
    entry = {"train": stats, "latency": {"host_before": h0}}

    lat_gpu = latency(model, tok, dev, device="cuda", n=205)
    entry["latency"]["gpu"] = lat_gpu
    entry["latency"]["cpu1"] = latency(model, tok, dev, device="cpu", n=8)
    entry["latency"]["cpu1"]["note"] = "reduced N: a 0.5B batch-1 CPU forward is ~seconds"
    entry["latency"]["gpu"]["note"] = "reduced N (205 frames, not 2000): compute budget"
    entry["latency"]["host_after"] = host_state()
    results["D"] = entry
    res_path.write_text(json.dumps(results, indent=1))

    rng = np.random.default_rng(seed)
    n_dev, n_slice = 26, 24
    dev_eps = sorted(rng.choice(dev.n_episodes, n_dev, replace=False).tolist())
    dsub, _ = sub_split(dev, dev_eps, "dev[D-subset]")
    pred, meta = predict(model, tok, dsub, list(range(dsub.n_episodes)), budget_s=420)
    entry["dev"] = ev.score(dsub, pred)
    entry["dev_decode"] = meta
    arms.log(ev.summarize("D", entry["dev"]), tag="run")
    results["D"] = entry
    res_path.write_text(json.dumps(results, indent=1))

    entry["slices"] = {}
    frz_preds, frz_subs = [], []
    for name, part in zip(FROZEN_SPLITS, frozen_parts):
        eps = sorted(rng.choice(part.n_episodes, n_slice, replace=False).tolist())
        sub, _ = sub_split(part, eps, f"{name}[D-subset]")
        p, m = predict(model, tok, sub, list(range(sub.n_episodes)), budget_s=330)
        entry["slices"][name] = ev.score(sub, p)
        entry["slices"][name]["decode"] = m
        arms.log(ev.summarize("D", entry["slices"][name]), tag="run")
        frz_preds.append(p)
        frz_subs.append(sub)
        results["D"] = entry
        res_path.write_text(json.dumps(results, indent=1))
    pooled = ev.concat_splits("frozen[D-subset]", frz_subs)
    entry["frozen"] = ev.score(pooled, np.concatenate(frz_preds))
    arms.log(ev.summarize("D", entry["frozen"]), tag="run")

    # A5 — cue-masked phrasing slice: only `words` carries the command
    ph = frozen_parts[list(FROZEN_SPLITS).index("frozen_phrasing")]
    eps = sorted(rng.choice(ph.n_episodes, 10, replace=False).tolist())
    sub, _ = sub_split(ph, eps, "frozen_phrasing[cue-masked]")
    masked = mask_cues(sub, "frozen_phrasing[cue-masked]")
    p, m = predict(model, tok, masked, list(range(masked.n_episodes)), budget_s=300)
    entry["A5_cue_masked_phrasing"] = ev.score(sub, p)
    entry["A5_cue_masked_phrasing"]["decode"] = m
    arms.log(ev.summarize("D[A5]", entry["A5_cue_masked_phrasing"]), tag="run")
    entry["A5_ngram_overlap"] = ngram_overlap(train, ph)
    entry["eval_note"] = (
        f"arm D is scored on {n_dev} dev and {n_slice} episodes per frozen slice; "
        "a 0.5B forward per frame is ~3 orders of magnitude costlier than arm C"
    )
    results["D"] = entry
    res_path.write_text(json.dumps(results, indent=1))
    (out / "results-D.json").write_text(json.dumps(entry, indent=1))
