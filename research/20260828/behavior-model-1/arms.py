"""BM-1 arms A (rule baseline), B (GRU), C (BehaviorFormer), D (LoRA LM).

Arm A mimics the shape of ``parcel_robot.attention.arbiter.ReactionArbiter``
(base_rate x gains, per-spec cooldowns, repetition/signed habituation, dwell,
critical-phase veto) plus the deterministic command router that the product
already has.  It is context-blind: nothing but ``base_busy`` and the ``cmd``
cue reaches it.

Arms B/C/D are behaviour-cloning policies over the same frame stream.
"""

from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from eval import Split
from worldsim import (
    ACT_ID,
    ACT_VOCAB,
    CHANNEL_INDEX,
    CHANNEL_SIZES,
    CUE,
    EMOTE_IDS,
    EMOTES,
    IDLE_ID,
    N_ACTS,
    N_CHANNELS,
    SKILL_IDS,
    SKILLS,
)

_PROBE_STEPS = 40
CKPT_DIR = Path(os.path.expanduser("~/.cache/parcel-0e/bm1/ckpt"))
LOG_DIR = Path(os.path.expanduser("~/.cache/parcel-0e/bm1/logs"))


def log(msg: str, tag: str = "arms") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with (LOG_DIR / f"{tag}.log").open("a") as fh:
        fh.write(line + "\n")


# ===========================================================================
# Arm A — context-blind stochastic arbiter + deterministic command router
# ===========================================================================

ARBITER_TOKENS = (
    tuple(f"<emote:{n}>" for n in EMOTES)
    + ("<gaze_owner>", "<gaze_release>")
    + tuple(f"<gaze_bearing_{i}>" for i in range(8))
    + tuple(f"<filler_gesture_{i}>" for i in range(4))
)


def _hab_key(token: str) -> str:
    if token == "<gaze_owner>":
        return "gaze_mutual"
    if token == "<gaze_release>":
        return "gaze_soft"
    if token.startswith("<gaze_bearing_"):
        return "gaze_bearing"
    if token.startswith("<filler_gesture_"):
        return "filler"
    return token[len("<emote:") : -1]


def _cooldown_s(token: str) -> float:
    if token == "<emote:chuckle>":
        return 5.0
    if token.startswith("<emote:"):
        return 2.0
    if token == "<gaze_owner>":
        return 0.8
    if token == "<gaze_release>":
        return 1.5
    if token.startswith("<gaze_bearing_"):
        return 2.0
    return 2.0


@dataclass
class ArmAConfig:
    base_rate: dict[str, float]
    router_delay: int = 3
    min_dwell_frames: int = 6  # 0.6 s, ReactionArbiter default
    signed_tau_s: float = 5.0
    signed_floor: float = -1.0


def calibrate_arm_a(train: Split, *, seed: int, n_episodes: int = 40) -> ArmAConfig:
    """Set base rates from the teacher's marginal expressive-token rates.

    The arbiter fires with ``mean(base_rate x score)`` over available
    candidates, so the marginals only pin the *relative* weights; a single
    global scale is searched so that arm A's realised expressive-token rate
    matches the teacher's.
    """

    counts = np.bincount(train.acts, minlength=N_ACTS)
    total = float(len(train.acts))
    marg = {tok: float(counts[ACT_ID[tok]]) / total for tok in ARBITER_TOKENS}
    target = sum(marg.values())
    log(f"[A] teacher expressive-token rate = {target:.5f} over {int(total)} frames")

    rng = random.Random(seed)
    sub = sorted(rng.sample(range(train.n_episodes), min(n_episodes, train.n_episodes)))

    def realised(scale: float) -> float:
        cfg = ArmAConfig(base_rate={t: min(1.0, scale * marg[t]) for t in ARBITER_TOKENS})
        hits = 0
        frames = 0
        for ei in sub:
            s, e = train.episode(ei)
            pred = _arm_a_episode(train.channels[s:e], cfg, seed=seed + ei)
            hits += int(np.isin(pred, np.array([ACT_ID[t] for t in ARBITER_TOKENS])).sum())
            frames += e - s
        return hits / frames

    lo, hi = 1.0, 4096.0
    for _ in range(12):
        mid = math.sqrt(lo * hi)
        r = realised(mid)
        if r < target:
            lo = mid
        else:
            hi = mid
    scale = math.sqrt(lo * hi)
    cfg = ArmAConfig(base_rate={t: min(1.0, scale * marg[t]) for t in ARBITER_TOKENS})
    log(f"[A] calibrated scale={scale:.2f} realised={realised(scale):.5f} target={target:.5f}")
    return cfg


def _arm_a_episode(channels: np.ndarray, cfg: ArmAConfig, *, seed: int) -> np.ndarray:
    ci = CHANNEL_INDEX
    T = channels.shape[0]
    out = np.full(T, IDLE_ID, dtype=np.int64)
    rng = random.Random(seed)

    cooldown: dict[str, float] = {}
    reps: dict[str, int] = {}
    signed: dict[str, float] = {}
    last_decay: dict[str, float] = {}
    last_reaction: str | None = None
    last_reaction_at = -10_000

    pending_skill: tuple[int, str] | None = None  # (due_frame, token)
    busy_until = -1

    cue_col = channels[:, ci["cue"]]
    busy_col = channels[:, ci["base_busy"]]

    for f in range(T):
        now = f / 10.0
        critical = int(busy_col[f]) == 2

        # --- deterministic command router (today's product path) ----------
        cue = int(cue_col[f])
        name = CUE[cue]
        if name.startswith("cmd:"):
            cmd = name[4:]
            if cmd == "stop":
                pending_skill = None
                out[f] = IDLE_ID
                last_reaction, last_reaction_at = None, -10_000
                busy_until = f + 2
                continue
            elif cmd in SKILLS:
                pending_skill = (f + cfg.router_delay, f"<skill:{cmd}>")
        if pending_skill is not None and f >= pending_skill[0]:
            if critical:
                pending_skill = (f + 1, pending_skill[1])  # defer past critical
            else:
                out[f] = ACT_ID[pending_skill[1]]
                pending_skill = None
                last_reaction, last_reaction_at = None, -10_000
                busy_until = f + 25  # executive holds the skill
                continue

        # --- context-blind arbiter tick -----------------------------------
        if critical:  # t0 veto (critical_phase)
            continue
        if f <= busy_until:
            continue
        if last_reaction is not None and (f - last_reaction_at) < cfg.min_dwell_frames:
            continue  # dwelling: the executive is still playing the last reaction

        # signed-weight decay toward the floor
        for key, base in list(last_decay.items()):
            dt = max(0.0, now - base)
            if dt > 0:
                tgt = cfg.signed_floor
                signed[key] = tgt + (signed.get(key, 0.0) - tgt) * math.exp(-dt / cfg.signed_tau_s)
                last_decay[key] = now

        weights: list[tuple[str, float]] = []
        for tok in ARBITER_TOKENS:
            if now < cooldown.get(tok, -1e9):
                continue
            key = _hab_key(tok)
            score = 1.0  # unit temperament factors: base_rate dominates
            score *= max(0.05, 1.0 - 0.15 * reps.get(key, 0))
            if "gaze" in key:
                score *= max(0.0, 1.0 + signed.get(key, 0.0))
            w = score * cfg.base_rate[tok]
            if w > 0.0:
                weights.append((tok, w))
        if not weights:
            continue
        mean_rate = sum(w for _, w in weights) / len(weights)
        if rng.random() > min(1.0, mean_rate):
            continue
        pick = rng.choices([t for t, _ in weights], weights=[w for _, w in weights], k=1)[0]
        out[f] = ACT_ID[pick]
        last_reaction, last_reaction_at = pick, f
        key = _hab_key(pick)
        cooldown[pick] = now + _cooldown_s(pick)
        reps[key] = reps.get(key, 0) + 1
        if "gaze" in key:
            signed[key] = max(cfg.signed_floor, signed.get(key, 0.0) - 0.35)
        last_decay[key] = now
    return out


def _arm_a_worker(args):
    ei, chan, cfg, seed = args
    return ei, _arm_a_episode(chan, cfg, seed=seed)


def arm_a_predict(split: Split, cfg: ArmAConfig, *, seed: int, workers: int = 24) -> np.ndarray:
    import multiprocessing as mp

    tasks = []
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        tasks.append((ei, split.channels[s:e], cfg, seed * 1000003 + ei))
    out = np.full(split.n_frames, IDLE_ID, dtype=np.int64)
    if workers > 1:
        with mp.get_context("fork").Pool(workers) as pool:
            rows = pool.map(_arm_a_worker, tasks, chunksize=4)
    else:
        rows = [_arm_a_worker(t) for t in tasks]
    for ei, pred in rows:
        s, e = split.episode(ei)
        out[s:e] = pred
    return out


# ===========================================================================
# Arms B / C — from-scratch behaviour cloning
# ===========================================================================

import torch
import torch.nn.functional as F
from torch import nn


def set_determinism(seed: int) -> None:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(seed)
    np.random.seed(seed % (2**32))
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    try:
        torch.use_deterministic_algorithms(True, warn_only=True)
    except Exception:  # pragma: no cover  # noqa: BLE001,S110
        pass


class ChannelEncoder(nn.Module):
    def __init__(self, d_model: int, emb: int = 16) -> None:
        super().__init__()
        self.embs = nn.ModuleList([nn.Embedding(size, emb) for size in CHANNEL_SIZES])
        self.proj = nn.Linear(emb * N_CHANNELS, d_model)

    def forward(self, x: torch.Tensor) -> torch.Tensor:  # x: (B, T, C) long
        parts = [e(x[:, :, i]) for i, e in enumerate(self.embs)]
        return self.proj(torch.cat(parts, dim=-1))


class GRUPolicy(nn.Module):
    """Arm B — 2 x 256 GRU over per-channel embeddings."""

    name = "B"

    def __init__(self, d_model: int = 256, layers: int = 2) -> None:
        super().__init__()
        self.enc = ChannelEncoder(d_model)
        self.rnn = nn.GRU(d_model, d_model, num_layers=layers, batch_first=True)
        self.head = nn.Linear(d_model, N_ACTS)

    def forward(self, x: torch.Tensor, h: torch.Tensor | None = None):
        z = self.enc(x)
        z, h = self.rnn(z, h)
        return self.head(z), h


class BehaviorFormer(nn.Module):
    """Arm C — causal transformer, 6 layers, d=256, 4 heads, context 128."""

    name = "C"

    def __init__(self, d_model: int = 256, layers: int = 6, heads: int = 4, ctx: int = 128):
        super().__init__()
        self.ctx = ctx
        self.enc = ChannelEncoder(d_model)
        self.pos = nn.Embedding(ctx, d_model)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=heads,
            dim_feedforward=4 * d_model,
            dropout=0.1,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.body = nn.TransformerEncoder(layer, num_layers=layers)
        self.norm = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, N_ACTS)
        mask = torch.triu(torch.ones(ctx, ctx, dtype=torch.bool), diagonal=1)
        self.register_buffer("causal", mask, persistent=False)

    def forward(self, x: torch.Tensor):
        T = x.shape[1]
        z = self.enc(x) + self.pos(torch.arange(T, device=x.device))[None]
        z = self.body(z, mask=self.causal[:T, :T])
        return self.head(self.norm(z))


def _window_starts(split: Split, window: int) -> np.ndarray:
    out = []
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        if e - s >= window:
            out.append(np.arange(s, e - window + 1))
    return np.concatenate(out)


def train_bc(
    model: nn.Module,
    train: Split,
    *,
    window: int,
    warmup: int,
    batch: int,
    steps: int,
    lr: float,
    seed: int,
    budget_s: float,
    device: str = "cuda",
    eval_fn=None,
    eval_every: int = 400,
    tag: str = "B",
    weights: torch.Tensor | None = None,
) -> dict:
    set_determinism(seed)
    model = model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01, betas=(0.9, 0.95))
    sched = None  # built after the throughput probe so the cosine tail lands
    starts = _window_starts(train, window)
    gen = np.random.default_rng(seed)
    ch = torch.from_numpy(train.channels.astype(np.int64))
    ac = torch.from_numpy(train.acts.astype(np.int64))
    idx_off = torch.arange(window)

    w_dev = None if weights is None else weights.to(device)
    t0 = time.time()
    hist: list[dict] = []
    best = {"score": -1.0, "step": -1}
    stopped = "steps"
    planned_steps = steps
    step = 0
    while step < steps:
        step += 1
        pick = gen.integers(0, len(starts), size=batch)
        base = torch.from_numpy(starts[pick].astype(np.int64))[:, None] + idx_off[None]
        xb = ch[base].to(device, non_blocking=True)
        yb = ac[base].to(device, non_blocking=True)
        if isinstance(model, GRUPolicy):
            logits, _ = model(xb)
        else:
            logits = model(xb)
        loss = F.cross_entropy(
            logits[:, warmup:].reshape(-1, N_ACTS), yb[:, warmup:].reshape(-1),
            weight=w_dev,
        )
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if sched is not None:
            sched.step()
        elif step == _PROBE_STEPS:
            rate = _PROBE_STEPS / max(1e-6, time.time() - t0)
            total = int(min(steps, max(_PROBE_STEPS + 10, budget_s * rate * 0.90)))
            sched = torch.optim.lr_scheduler.OneCycleLR(
                opt, max_lr=lr, total_steps=total - _PROBE_STEPS,
                pct_start=0.10, anneal_strategy="cos")
            planned_steps = total
            log(f"[{tag}] throughput {rate:.2f} step/s -> planning {total} steps",
                tag=f"arm_{tag}")
            steps = total

        if step % 100 == 0 or step == 1:
            log(f"[{tag}] step {step}/{steps} loss={loss.item():.4f} "
                f"elapsed={time.time() - t0:.0f}s", tag=f"arm_{tag}")
        if eval_fn is not None and (step % eval_every == 0 or step == steps):
            m = eval_fn(model, step)
            hist.append(m)
            log(f"[{tag}] step {step} dev {m}", tag=f"arm_{tag}")
            if m["score"] > best["score"]:
                best = {"score": m["score"], "step": step, "metrics": m}
                CKPT_DIR.mkdir(parents=True, exist_ok=True)
                torch.save(model.state_dict(), CKPT_DIR / f"arm_{tag}.pt")
        if time.time() - t0 > budget_s:
            stopped = "budget"
            log(f"[{tag}] wall budget reached at step {step}", tag=f"arm_{tag}")
            break
    if best["step"] < 0:
        CKPT_DIR.mkdir(parents=True, exist_ok=True)
        torch.save(model.state_dict(), CKPT_DIR / f"arm_{tag}.pt")
    epochs = step * batch * max(1, window - warmup) / max(1, train.n_frames)
    return {
        "steps_run": step,
        "planned_steps": planned_steps,
        "batch": batch,
        "window": window,
        "frames_per_step": batch * (window - warmup if window > warmup else window),
        "epochs_equivalent": round(float(epochs), 2),
        "wall_s": round(time.time() - t0, 1),
        "stopped": stopped,
        "final_loss": float(loss.item()),
        "best": best,
        "history": hist,
        "gpu_peak_mb": round(torch.cuda.max_memory_allocated() / 1e6, 1) if device == "cuda" else 0.0,
    }


# --- inference -------------------------------------------------------------


def _decode(logits: torch.Tensor, mode: str, gen: torch.Generator) -> torch.Tensor:
    if mode == "argmax":
        return logits.argmax(-1)
    probs = torch.softmax(logits.float(), dim=-1)
    flat = probs.reshape(-1, probs.shape[-1])
    idx = torch.multinomial(flat, 1, generator=gen).squeeze(-1)
    return idx.reshape(probs.shape[:-1])


@torch.no_grad()
def predict_gru(
    model: GRUPolicy, split: Split, *, mode: str, seed: int, device: str = "cuda",
    batch_eps: int = 32,
) -> np.ndarray:
    model.eval().to(device)
    gen = torch.Generator(device=device); gen.manual_seed(seed)
    out = np.full(split.n_frames, IDLE_ID, dtype=np.int64)
    order = np.argsort(-split.ep_len)
    for i in range(0, len(order), batch_eps):
        eps = order[i : i + batch_eps]
        L = int(split.ep_len[eps].max())
        xb = torch.zeros(len(eps), L, N_CHANNELS, dtype=torch.long)
        for j, ei in enumerate(eps):
            s, e = split.episode(int(ei))
            xb[j, : e - s] = torch.from_numpy(split.channels[s:e].astype(np.int64))
        logits, _ = model(xb.to(device))
        dec = _decode(logits, mode, gen).cpu().numpy()
        for j, ei in enumerate(eps):
            s, e = split.episode(int(ei))
            out[s:e] = dec[j, : e - s]
    return out


@torch.no_grad()
def predict_former(
    model: BehaviorFormer, split: Split, *, mode: str, seed: int, device: str = "cuda",
    stride: int = 32, batch: int = 384,
) -> np.ndarray:
    """Sliding window: every position keeps >= ctx-stride frames of context."""

    model.eval().to(device)
    gen = torch.Generator(device=device); gen.manual_seed(seed)
    ctx = model.ctx
    out = np.full(split.n_frames, IDLE_ID, dtype=np.int64)
    jobs: list[tuple[int, int, int]] = []  # (win_start, take_from, take_to) global
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        T = e - s
        pos = 0
        while pos < T:
            win_end = min(T, pos + (ctx if pos == 0 else stride))
            win_start = max(0, win_end - ctx)
            jobs.append((s + win_start, s + pos, s + win_end))
            pos = win_end
    ch = split.channels
    for i in range(0, len(jobs), batch):
        chunk = jobs[i : i + batch]
        xb = torch.zeros(len(chunk), ctx, N_CHANNELS, dtype=torch.long)
        lens = []
        for j, (ws, _, we) in enumerate(chunk):
            n = we - ws
            xb[j, :n] = torch.from_numpy(ch[ws:we].astype(np.int64))
            lens.append(n)
        logits = model(xb.to(device))
        dec = _decode(logits, mode, gen).cpu().numpy()
        for j, (ws, ts, te) in enumerate(chunk):
            out[ts:te] = dec[j, ts - ws : te - ws]
    return out


# --- M4 latency ------------------------------------------------------------


@torch.no_grad()
def latency_ms(model: nn.Module, split: Split, *, device: str, n: int = 2000,
               threads: int = 1) -> dict:
    """Batch-1 per-frame inference latency, p50 / p99."""

    if device == "cpu":
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            pass  # verifier 03:05 08-29: already started in this process (B ran after E); latency row uses set_num_threads(1) only
    model = model.to(device).eval()
    rng = np.random.default_rng(7)
    ctx = getattr(model, "ctx", 1)
    is_gru = isinstance(model, GRUPolicy)
    starts = rng.integers(0, split.n_frames - max(ctx, 2) - 1, size=n)
    samples: list[torch.Tensor] = []
    for s in starts[: min(n, 2000)]:
        if is_gru:
            samples.append(
                torch.from_numpy(split.channels[s : s + 1].astype(np.int64))[None].to(device)
            )
        else:
            samples.append(
                torch.from_numpy(split.channels[s : s + ctx].astype(np.int64))[None].to(device)
            )
    h = None
    for x in samples[:20]:  # warm-up
        if is_gru:
            _, h = model(x, h)
        else:
            model(x)
    if device == "cuda":
        torch.cuda.synchronize()
    times = []
    h = None
    for x in samples:
        t0 = time.perf_counter()
        if is_gru:
            _, h = model(x, h)
        else:
            model(x)
        if device == "cuda":
            torch.cuda.synchronize()
        times.append((time.perf_counter() - t0) * 1000.0)
    arr = np.asarray(times)
    if device == "cpu":
        torch.set_num_threads(min(32, os.cpu_count() or 8))
    return {
        "device": device,
        "threads": threads if device == "cpu" else None,
        "n": len(arr),
        "p50_ms": round(float(np.percentile(arr, 50)), 3),
        "p99_ms": round(float(np.percentile(arr, 99)), 3),
        "mean_ms": round(float(arr.mean()), 3),
    }


def arm_a_latency(split: Split, cfg: ArmAConfig, n: int = 2000) -> dict:
    """Arm A has no GPU path; time the Python arbiter tick per frame."""

    chan = split.channels[:n]
    times = []
    for _ in range(3):
        t0 = time.perf_counter()
        _arm_a_episode(chan, cfg, seed=1)
        times.append((time.perf_counter() - t0) * 1000.0 / n)
    return {"device": "cpu", "threads": 1, "n": n,
            "p50_ms": round(float(np.median(times)), 4),
            "p99_ms": round(float(np.max(times)), 4),
            "mean_ms": round(float(np.mean(times)), 4),
            "note": "per-frame mean over a 2000-frame sweep (pure-Python arbiter)"}


# ===========================================================================
# A2 — arm A' : deterministic reflex table over the CURRENT frame only
# ===========================================================================

from worldsim import (
    _PACE_BASE,
    _PACE_COMFORT,
    _PACE_COMPLY,
    _PACE_SOCIAL,
)
from worldsim import (
    CUE as _CUE,
)
from worldsim import (
    PROF_GREET as _PG,
)
from worldsim import (
    PROF_PACE as _PACE,
)
from worldsim import (
    PROF_PRAISE as _PP,
)


def modal_lookback_bearing(train: Split) -> int:
    """The single bearing bin a history-free reflex would have to guess."""

    from worldsim import ANN_INDEX

    tg = train.ann[:, ANN_INDEX["tgt_lookback"]]
    ev = train.ann[:, ANN_INDEX["ev_lookback"]] == 1
    toks = tg[ev]
    names = [ACT_VOCAB[int(t)] for t in toks]
    bins = [int(n[len("<gaze_bearing_") : -1]) for n in names]
    return int(np.bincount(np.asarray(bins), minlength=8).argmax())


def _arm_aprime_episode(channels: np.ndarray, *, modal_bin: int) -> np.ndarray:
    """Reflex table: current-frame channels + a one-frame edge detector.

    It has the teacher's *timings* (delays are read from the observable
    ``prof_pace`` channel) but no memory: it cannot recall the bearing the
    owner was last seen at, and it cannot tell an anticipatable punchline from
    any other punchline.
    """

    ci = CHANNEL_INDEX
    T = channels.shape[0]
    out = np.full(T, IDLE_ID, dtype=np.int64)
    sched: dict[int, list[tuple[int, str]]] = {}  # frame -> [(prio, token)]
    last_chuckle = -10_000
    busy_until = -1

    cue_c = channels[:, ci["cue"]]
    busy_c = channels[:, ci["base_busy"]]
    tss_c = channels[:, ci["t_since_seen"]]
    vis_c = channels[:, ci["own_vis"]]
    task_c = channels[:, ci["task"]]
    val_c = channels[:, ci["val"]]
    aro_c = channels[:, ci["aro"]]

    def put(f: int, prio: int, tok: str) -> None:
        if 0 <= f < T:
            sched.setdefault(f, []).append((prio, tok))

    for f in range(T):
        pace = _PACE[int(channels[f, ci["prof_pace"]])]
        k = _CUE[int(cue_c[f])]
        if k.startswith("cmd:"):
            cmd = k[4:]
            if cmd == "stop":
                sched = {g: v for g, v in sched.items() if g > f + 5}
                put(f + 1, 0, "<idle>")
            elif cmd in SKILLS:
                put(f + _PACE_COMPLY[pace], 1, f"<skill:{cmd}>")
        elif k == "laugh":
            put(f + _PACE_BASE[pace], 3, "<emote:chuckle>")
        elif k == "sigh" or (int(val_c[f]) - 2 <= -1 and int(aro_c[f]) == 0):
            put(f + _PACE_COMFORT[pace], 4, "<emote:comfort_bow>")
        elif k == "greeting":
            name = {"warm": "hello_pose", "playful": "paw_wave",
                    "brief": "attentive_nod"}[_PG[int(channels[f, ci["prof_greet"]])]]
            put(f + _PACE_SOCIAL[pace], 4, f"<emote:{name}>")
        elif k == "praise":
            name = "attentive_nod" if _PP[int(channels[f, ci["prof_praise"]])] == "frequent" else "happy_wiggle"
            put(f + _PACE_SOCIAL[pace], 4, f"<emote:{name}>")
        elif k == "scold":
            put(f + 1, 4, "<idle>")
            put(f + 3, 4, "<gaze_release>")
        elif k == "call_name":
            put(f + 2, 4, "<gaze_owner>")
            put(f + 2 + _PACE_SOCIAL[pace], 4, "<emote:attentive_nod>")
        elif k == "question":
            put(f + 8, 4, "<emote:observing_head_tilt>")
        # look-back reflex: rising edge of t_since_seen == "3_8s" while the
        # owner is not visible on a follow/go_to task.  The bearing is not in
        # the current frame, so the reflex must guess the modal bin.
        if (
            f > 0
            and int(tss_c[f]) == 2
            and int(tss_c[f - 1]) != 2
            and int(vis_c[f]) != 0
            and int(task_c[f]) in (1, 2)
        ):
            put(f, 2, f"<gaze_bearing_{modal_bin}>")

        cands = sorted(sched.pop(f, []))
        if not cands:
            continue
        prio, tok = cands[0]
        aid = ACT_ID[tok]
        critical = int(busy_c[f]) == 2
        is_body = aid in EMOTE_IDS or aid in SKILL_IDS
        if critical and is_body:
            if prio <= 1:
                put(f + 1, prio, tok)  # defer commands past critical
            continue
        if f <= busy_until and prio > 1 and is_body:
            continue
        if tok == "<emote:chuckle>" and f - last_chuckle < 50:
            continue
        out[f] = aid
        if aid in EMOTE_IDS:
            busy_until = f + 11
            if tok == "<emote:chuckle>":
                last_chuckle = f
        elif aid in SKILL_IDS:
            busy_until = f + 25
    return out


def _aprime_worker(args):
    ei, chan, modal_bin = args
    return ei, _arm_aprime_episode(chan, modal_bin=modal_bin)


def arm_aprime_predict(split: Split, *, modal_bin: int, workers: int = 24) -> np.ndarray:
    import multiprocessing as mp

    tasks = []
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        tasks.append((ei, split.channels[s:e], modal_bin))
    out = np.full(split.n_frames, IDLE_ID, dtype=np.int64)
    with mp.get_context("fork").Pool(workers) as pool:
        for ei, pred in pool.map(_aprime_worker, tasks, chunksize=4):
            s, e = split.episode(ei)
            out[s:e] = pred
    return out


# ===========================================================================
# A4 — reference rows
# ===========================================================================


def always_idle(split: Split) -> np.ndarray:
    return np.full(split.n_frames, IDLE_ID, dtype=np.int64)


def chuckle_every_punchline(split: Split, *, delay: int = 5) -> np.ndarray:
    """Reference row: fire <emote:chuckle> after every OBSERVED punchline cue."""

    out = np.full(split.n_frames, IDLE_ID, dtype=np.int64)
    punch = np.nonzero(split.channels[:, CHANNEL_INDEX["cue"]] == _CUE.index("joke_punchline"))[0]
    tgt = punch + delay
    tgt = tgt[tgt < split.n_frames]
    out[tgt] = ACT_ID["<emote:chuckle>"]
    return out


# ===========================================================================
# A2 — arm E : frame-level MLP, no context
# ===========================================================================


class FrameMLP(nn.Module):
    """Arm E — the same per-channel embeddings, one frame, no history."""

    name = "E"

    def __init__(self, d_model: int = 512) -> None:
        super().__init__()
        self.enc = ChannelEncoder(d_model)
        self.net = nn.Sequential(
            nn.GELU(), nn.Linear(d_model, d_model), nn.GELU(),
            nn.Linear(d_model, d_model), nn.GELU(),
        )
        self.head = nn.Linear(d_model, N_ACTS)

    def forward(self, x: torch.Tensor):
        return self.head(self.net(self.enc(x)))


@torch.no_grad()
def predict_mlp(model: FrameMLP, split: Split, *, device: str = "cuda",
                batch: int = 65536) -> np.ndarray:
    model.eval().to(device)
    out = np.empty(split.n_frames, dtype=np.int64)
    for i in range(0, split.n_frames, batch):
        xb = torch.from_numpy(split.channels[i : i + batch].astype(np.int64))[:, None].to(device)
        out[i : i + batch] = model(xb).argmax(-1)[:, 0].cpu().numpy()
    return out


# ===========================================================================
# A4 — class weights (pre-registered decoding rule: argmax + weighted CE)
# ===========================================================================


def class_weights(train: Split, *, alpha: float = 0.5) -> torch.Tensor:
    counts = np.bincount(train.acts, minlength=N_ACTS).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    w = counts ** (-alpha)
    w = w / w.mean()
    return torch.tensor(w, dtype=torch.float32)
