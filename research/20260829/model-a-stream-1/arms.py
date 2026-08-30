"""MA-1 arms: T (teacher replay), A'n (reflex table), C (two-head BehaviorFormer),
ALWAYS-IDLE and straight-to-goal references.

BM-1 reuse: ``research/20260828/behavior-model-1/arms.py`` is imported BY PATH
and never modified.  Its :func:`set_determinism` and its class-weight rule
(counts ** -alpha, mean-normalised) are reused verbatim; its ``BehaviorFormer``
is single-headed over BM-1's own channel table, so MA-1's model mirrors the
same architecture (6 layers, d=256, 4 heads, ctx 128, pre-norm, GELU, dropout
0.1) over MA-1's channel table with TWO heads (act + narration), which is what
DESIGN.md specifies.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "32")

import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

sys.path.insert(0, str(Path(__file__).parent))
from teacher import (
    ACT_ID,
    CHANNEL_INDEX,
    CHANNEL_SIZES,
    CMD,
    GOAL_TARGET,
    HOLD_ID,
    N_ACTS,
    N_CHANNELS,
    N_NARR,
    NARR_ID,
    NARR_NONE,
    VX_BINS,
    VYAW_BINS,
)

# --- BM-1, imported by path, never modified --------------------------------
_BM1 = Path(__file__).resolve().parents[2] / "20260828" / "behavior-model-1" / "arms.py"


def _load_bm1():
    """Import BM-1's arms module by path (it needs its own dir on sys.path)."""

    d = str(_BM1.parent)
    if d not in sys.path:
        sys.path.append(d)
    spec = importlib.util.spec_from_file_location("bm1_arms", _BM1)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    BM1 = _load_bm1()
    set_determinism = BM1.set_determinism
    BM1_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    BM1 = None
    BM1_AVAILABLE = False
    _BM1_ERR = f"{type(exc).__name__}: {exc}"

    def set_determinism(seed: int) -> None:  # BM-1's body, reproduced
        import random as _r
        os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
        _r.seed(seed)
        np.random.seed(seed % (2 ** 32))
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        try:
            torch.use_deterministic_algorithms(True, warn_only=True)
        except Exception:  # noqa: BLE001,S110
            pass


# ===========================================================================
# Split
# ===========================================================================


@dataclass
class Split:
    name: str
    channels: np.ndarray
    acts: np.ndarray
    narr: np.ndarray
    ann: np.ndarray
    ep_start: np.ndarray
    ep_len: np.ndarray
    ep_scene: np.ndarray
    ep_kind: np.ndarray

    @property
    def n_frames(self) -> int:
        return len(self.acts)

    @property
    def n_episodes(self) -> int:
        return len(self.ep_len)

    def episode(self, i: int) -> tuple[int, int]:
        s = int(self.ep_start[i])
        return s, s + int(self.ep_len[i])


def load_split(data_dir, name: str) -> Split:
    z = np.load(Path(data_dir) / f"{name}.npz")
    return Split(
        name=name,
        channels=z["channels"].astype(np.int64),
        acts=z["acts"].astype(np.int64),
        narr=z["narr"].astype(np.int64),
        ann=z["ann"],
        ep_start=z["ep_start"],
        ep_len=z["ep_len"],
        ep_scene=z["ep_scene"],
        ep_kind=z["ep_kind"],
    )


# ===========================================================================
# The policy interface every arm implements (closed_loop.py drives this).
# ===========================================================================


class Policy:
    name = "policy"

    def reset(self) -> None:
        pass

    def act(self, row: np.ndarray) -> tuple[int, int]:
        """One frame in, (act_id, narration_id) out."""

        raise NotImplementedError


# ===========================================================================
# A'n — the frozen reflex table over the CURRENT frame.
# ===========================================================================

_VX = {v: i for i, v in enumerate(VX_BINS)}
_VYAW = {v: i for i, v in enumerate(VYAW_BINS)}
VX_STOP, VYAW_STOP = 1, 2      # vx = 0.0, vyaw = 0.0


def _twist(vx_i: int, vyaw_i: int) -> int:
    return ACT_ID[f"<twist:{vx_i}:{vyaw_i}>"]


_CH = CHANNEL_INDEX
_CMD_V = {v: i for i, v in enumerate(CMD)}
_TGT_NAME = dict(enumerate(GOAL_TARGET))
_D0 = 0          # goal_dist "d0" == within 1 m
_STOPPED = 1     # stop_state "stopped"
_SPEAKING = 1    # cue "owner_speaking"
_HOLD_SELF = 2   # self_act "hold"


class ReflexTable(Policy):
    """A'n: BM-1's A' shape, extended with the NAVIGATION channels.

    Frozen — no calibration, no memory beyond the frame it is handed.  Under
    amendment A1 it no longer has a ``plan_step`` or ``blocked`` channel to
    read the label off: arrival has to be inferred from ``goal_dist`` plus its
    own ``self_act``, and a block from the free-space ring.
    """

    name = "Aprime_n"

    def act(self, row: np.ndarray) -> tuple[int, int]:
        cmd = int(row[_CH["cmd"]])
        cmd_t = _TGT_NAME[int(row[_CH["cmd_target"]])]
        sound = int(row[_CH["sound"]])
        gtgt = _TGT_NAME[int(row[_CH["goal_target"]])]
        gbear = int(row[_CH["goal_bear"]])
        gdist = int(row[_CH["goal_dist"]])
        stopped = int(row[_CH["stop_state"]]) == _STOPPED
        speaking = int(row[_CH["cue"]]) == _SPEAKING
        self_act = int(row[_CH["self_act"]])
        free = [int(row[_CH[f"free{i}"]]) for i in range(8)]

        # --- narration, straight off the frame ------------------------------
        narr = NARR_NONE
        if cmd == _CMD_V["cmd:go_to"] and cmd_t != "none":
            narr = NARR_ID[f"nav.start:{cmd_t}"]
        elif cmd == _CMD_V["cmd:revise"] and cmd_t != "none":
            narr = NARR_ID[f"plan.revised:{cmd_t}"]
        elif cmd == _CMD_V["cmd:queue"] and cmd_t != "none":
            narr = NARR_ID[f"plan.queued:{cmd_t}"]
        elif cmd == _CMD_V["steer:resume"] and cmd_t != "none":
            narr = NARR_ID[f"plan.resumed:{cmd_t}"]
        elif sound > 0:
            narr = NARR_ID[f"attend.sound:{sound - 1}"]
        elif gtgt != "none" and gdist == _D0 and self_act == _HOLD_SELF:
            narr = NARR_ID[f"nav.arrived:{gtgt}"]
        elif free[0] == 0 and gtgt != "none":
            narr = NARR_ID["nav.blocked:obstacle"]

        # --- act -------------------------------------------------------------
        if stopped or speaking:
            return HOLD_ID, narr
        if sound > 0:
            return ACT_ID[f"<gaze_bearing_{sound - 1}>"], narr
        if gtgt == "none" or gbear >= 8:
            return HOLD_ID, narr
        if gdist == _D0:
            return HOLD_ID, narr
        if free[0] == 0:
            return _twist(VX_STOP, 4 if free[1] >= free[7] else 0), narr
        if gbear == 0:
            return _twist(4 if free[0] == 2 else 2, VYAW_STOP), narr
        if gbear == 1:
            return _twist(2, 3), narr
        if gbear == 7:
            return _twist(2, 1), narr
        if gbear == 2:
            return _twist(VX_STOP, 3), narr
        if gbear == 6:
            return _twist(VX_STOP, 1), narr
        return _twist(VX_STOP, 4 if gbear in (3, 4) else 0), narr


class AlwaysIdle(Policy):
    name = "ALWAYS-IDLE"

    def act(self, row):
        return HOLD_ID, NARR_NONE


class StraightToGoal(Policy):
    """A2's reference: drive the goal bearing to zero, ignore everything else.

    The criterion A2 adds is read against this arm: on held-out layouts where
    STRAIGHT-TO-GOAL fails, C must beat it by >= 0.10 success, and if it
    succeeds on > 0.7 of the held-out layouts the split is uninformative.
    """

    name = "STRAIGHT-TO-GOAL"

    def act(self, row):
        gtgt = int(row[_CH["goal_target"]])
        gbear = int(row[_CH["goal_bear"]])
        gdist = int(row[_CH["goal_dist"]])
        if gtgt == 0 or gbear >= 8 or gdist == _D0:
            return HOLD_ID, NARR_NONE
        if gbear == 0:
            return _twist(4, VYAW_STOP), NARR_NONE
        if gbear in (1, 2, 3, 4):
            return _twist(2 if gbear == 1 else VX_STOP, 3 if gbear == 1 else 4), NARR_NONE
        return _twist(2 if gbear == 7 else VX_STOP, 1 if gbear == 7 else 0), NARR_NONE


def table_predict(split: Split, policy: Policy) -> tuple[np.ndarray, np.ndarray]:
    a = np.empty(split.n_frames, dtype=np.int64)
    n = np.empty(split.n_frames, dtype=np.int64)
    for i in range(split.n_frames):
        a[i], n[i] = policy.act(split.channels[i])
    return a, n


# ===========================================================================
# C — the two-head BehaviorFormer (BM-1's architecture, MA-1's channel table)
# ===========================================================================


class ChannelEncoder(nn.Module):
    def __init__(self, d_model: int, emb: int = 16) -> None:
        super().__init__()
        self.embs = nn.ModuleList([nn.Embedding(s, emb) for s in CHANNEL_SIZES])
        self.proj = nn.Linear(emb * N_CHANNELS, d_model)

    def forward(self, x):
        return self.proj(torch.cat([e(x[:, :, i]) for i, e in enumerate(self.embs)], dim=-1))


class BehaviorFormerMA(nn.Module):
    """Arm C — causal transformer, 6 layers, d=256, 4 heads, ctx 128, 2 heads."""

    name = "C"

    def __init__(self, d_model: int = 256, layers: int = 6, heads: int = 4,
                 ctx: int = 128) -> None:
        super().__init__()
        self.ctx = ctx
        self.enc = ChannelEncoder(d_model)
        self.pos = nn.Embedding(ctx, d_model)
        layer = nn.TransformerEncoderLayer(
            d_model=d_model, nhead=heads, dim_feedforward=4 * d_model, dropout=0.1,
            activation="gelu", batch_first=True, norm_first=True,
        )
        self.body = nn.TransformerEncoder(layer, num_layers=layers)
        self.norm = nn.LayerNorm(d_model)
        self.head_act = nn.Linear(d_model, N_ACTS)
        self.head_narr = nn.Linear(d_model, N_NARR)
        self.register_buffer(
            "causal", torch.triu(torch.ones(ctx, ctx, dtype=torch.bool), diagonal=1),
            persistent=False,
        )

    def forward(self, x):
        t = x.shape[1]
        z = self.enc(x) + self.pos(torch.arange(t, device=x.device))[None]
        z = self.norm(self.body(z, mask=self.causal[:t, :t]))
        return self.head_act(z), self.head_narr(z)


def class_weights(counts: np.ndarray, n: int, alpha: float = 0.5) -> torch.Tensor:
    """BM-1's A4 rule: counts ** -alpha, mean-normalised."""

    c = np.maximum(np.bincount(counts, minlength=n).astype(np.float64), 1.0)
    w = c ** (-alpha)
    return torch.tensor(w / w.mean(), dtype=torch.float32)


def _window_starts(split: Split, window: int) -> np.ndarray:
    out = []
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        if e - s >= window:
            out.append(np.arange(s, e - window + 1))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int64)


def train_c(model, train: Split, *, window: int, warmup: int, batch: int,
            max_steps: int, lr: float, seed: int, budget_s: float,
            device: str, eval_fn, eval_every: int, patience: int,
            narr_lambda: float = 1.0, log=print) -> dict:
    """Behaviour cloning with PRE-REGISTERED early stopping on dev.

    Stop rule (fixed before the run): evaluate every ``eval_every`` steps; keep
    the best checkpoint by the dev score; stop when ``patience`` consecutive
    evaluations fail to improve it, or the wall budget runs out.
    """

    set_determinism(seed)
    model = model.to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01,
                            betas=(0.9, 0.95))
    starts = _window_starts(train, window)
    gen = np.random.default_rng(seed)
    ch = torch.from_numpy(train.channels)
    ac = torch.from_numpy(train.acts)
    na = torch.from_numpy(train.narr)
    off = torch.arange(window)
    w_act = class_weights(train.acts, N_ACTS).to(device)
    w_narr = class_weights(train.narr, N_NARR).to(device)

    ckpt = Path(os.environ.get("MA1_SCRATCH", Path.home() / ".cache/parcel-0e/ma1")) / "ckpt"
    ckpt.mkdir(parents=True, exist_ok=True)
    best = {"score": -1.0, "step": -1, "metrics": None}
    hist: list[dict] = []
    since_improve = 0
    sched = torch.optim.lr_scheduler.OneCycleLR(
        opt, max_lr=lr, total_steps=max_steps, pct_start=0.10, anneal_strategy="cos")
    t0 = time.time()
    stopped = "max_steps"
    step = 0
    loss = torch.tensor(0.0)
    while step < max_steps:
        step += 1
        model.train()
        pick = gen.integers(0, len(starts), size=batch)
        base = torch.from_numpy(starts[pick].astype(np.int64))[:, None] + off[None]
        xb = ch[base].to(device, non_blocking=True)
        ya = ac[base].to(device, non_blocking=True)
        yn = na[base].to(device, non_blocking=True)
        la, ln = model(xb)
        loss_a = F.cross_entropy(la[:, warmup:].reshape(-1, N_ACTS),
                                 ya[:, warmup:].reshape(-1), weight=w_act)
        loss_n = F.cross_entropy(ln[:, warmup:].reshape(-1, N_NARR),
                                 yn[:, warmup:].reshape(-1), weight=w_narr)
        loss = loss_a + narr_lambda * loss_n
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        sched.step()
        if step % 100 == 0 or step == 1:
            log(f"[C] step {step}/{max_steps} loss={loss.item():.4f} "
                f"(act {loss_a.item():.4f} narr {loss_n.item():.4f}) "
                f"{time.time()-t0:.0f}s")
        if step % eval_every == 0 or step == max_steps:
            m = eval_fn(model, step)
            m["step"] = step
            hist.append(m)
            log(f"[C] dev@{step}: {m}")
            if m["score"] > best["score"] + 1e-4:
                best = {"score": m["score"], "step": step, "metrics": m}
                torch.save(model.state_dict(), ckpt / "arm_C.pt")
                since_improve = 0
            else:
                since_improve += 1
                if since_improve >= patience:
                    stopped = "early_stop"
                    log(f"[C] EARLY STOP at step {step} "
                        f"(best {best['score']:.4f} @ {best['step']})")
                    break
        if time.time() - t0 > budget_s:
            stopped = "budget"
            log(f"[C] wall budget reached at step {step}")
            break
    if best["step"] < 0:
        torch.save(model.state_dict(), ckpt / "arm_C.pt")
    return {
        "steps_run": step, "max_steps": max_steps, "batch": batch, "window": window,
        "warmup": warmup, "lr": lr, "eval_every": eval_every, "patience": patience,
        "narr_lambda": narr_lambda,
        "epochs_equivalent": round(step * batch * max(1, window - warmup)
                                   / max(1, train.n_frames), 2),
        "wall_s": round(time.time() - t0, 1), "stopped": stopped,
        "final_loss": float(loss.item()), "best": best, "history": hist,
        "gpu_peak_mb": (round(torch.cuda.max_memory_allocated() / 1e6, 1)
                        if device == "cuda" else 0.0),
    }


@torch.no_grad()
def predict_former(model, split: Split, *, device: str, ctx: int = 128,
                   batch: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """Open-loop teacher-forced prediction, episode by episode, causal."""

    model.eval().to(device)
    pa = np.zeros(split.n_frames, dtype=np.int64)
    pn = np.zeros(split.n_frames, dtype=np.int64)
    for ei in range(split.n_episodes):
        s, e = split.episode(ei)
        x = torch.from_numpy(split.channels[s:e]).to(device)[None]
        n = e - s
        for lo in range(0, n, ctx):
            hi = min(n, lo + ctx)
            la, ln = model(x[:, lo:hi])
            pa[s + lo:s + hi] = la[0].argmax(-1).cpu().numpy()
            pn[s + lo:s + hi] = ln[0].argmax(-1).cpu().numpy()
    return pa, pn


#: A5's ablation, as an INPUT MASK on the trained model (not a retrain):
#: every "last minute" channel is pinned to its null value.
from teacher import AGE, COUNT60, HIST_K
from teacher import NARR_NONE as _NN

H0_MASK = {**{f"hist{i}": _NN for i in range(HIST_K)},
           **{c: AGE.index("never") for c in ("since_blocked", "since_replan",
                                              "since_cue", "since_sound",
                                              "since_owner")},
           **{c: COUNT60.index("0") for c in ("n_blocks_60", "n_replans_60")}}


class FormerPolicy(Policy):
    """Streaming wrapper: keeps a rolling ctx-length frame buffer.

    ``hist_mask="h0"`` is A5's C-h0 arm: the last-minute channels are pinned
    to their null values at inference.  It is an INPUT ablation of the trained
    C, not a separately trained model, and RESULTS.md says so.
    """

    name = "C"

    def __init__(self, model, device: str = "cuda", ctx: int = 128,
                 hist_mask: str = "none"):
        self.model = model.eval().to(device)
        self.device = device
        self.ctx = ctx
        self.hist_mask = hist_mask
        self._mask = ([(CHANNEL_INDEX[k], v) for k, v in H0_MASK.items()]
                      if hist_mask == "h0" else [])
        self.buf: list[np.ndarray] = []
        if hist_mask == "h0":
            self.name = "C-h0"

    def reset(self) -> None:
        self.buf = []

    @torch.no_grad()
    def act(self, row: np.ndarray) -> tuple[int, int]:
        row = np.asarray(row, dtype=np.int64)
        if self._mask:
            row = row.copy()
            for i, v in self._mask:
                row[i] = v
        self.buf.append(row)
        if len(self.buf) > self.ctx:
            self.buf = self.buf[-self.ctx:]
        x = torch.from_numpy(np.stack(self.buf)).to(self.device)[None]
        la, ln = self.model(x)
        return int(la[0, -1].argmax()), int(ln[0, -1].argmax())


# ===========================================================================
# Latency (DESIGN: per-frame, GPU and 1 CPU thread, 2000 frames)
# ===========================================================================


@torch.no_grad()
def latency_ms(model, split: Split, *, device: str, n: int = 2000,
               ctx: int = 128) -> dict:
    """Streaming per-frame cost: one forward over the ctx-length window.

    No KV cache — this is the deployable cost of the shape as written.
    """

    if device == "cpu":
        torch.set_num_threads(1)
    m = type(model)().to(device)
    m.load_state_dict(model.state_dict())
    m.eval()
    x = torch.from_numpy(split.channels[:ctx].astype(np.int64)).to(device)[None]
    for _ in range(20):
        m(x)
    if device == "cuda":
        torch.cuda.synchronize()
    t0 = time.perf_counter()
    for i in range(n):
        s = (i * 7) % max(1, split.n_frames - ctx)
        x = torch.from_numpy(split.channels[s:s + ctx].astype(np.int64)).to(device)[None]
        m(x)
    if device == "cuda":
        torch.cuda.synchronize()
    dt = (time.perf_counter() - t0) / n * 1000.0
    if device == "cpu":
        torch.set_num_threads(min(32, os.cpu_count() or 1))
    return {"device": device, "frames": n, "ms_per_frame": round(dt, 3),
            "ctx": ctx, "realtime_budget_ms": 100.0,
            "realtime_ok": bool(dt < 100.0)}


def table_latency_ms(policy: Policy, split: Split, n: int = 2000) -> dict:
    t0 = time.perf_counter()
    for i in range(n):
        policy.act(split.channels[i % split.n_frames])
    dt = (time.perf_counter() - t0) / n * 1000.0
    return {"device": "cpu", "frames": n, "ms_per_frame": round(dt, 4),
            "realtime_budget_ms": 100.0, "realtime_ok": bool(dt < 100.0)}


__all__ = [
    "AlwaysIdle", "BehaviorFormerMA", "FormerPolicy", "Policy", "ReflexTable",
    "Split", "StraightToGoal", "class_weights", "latency_ms", "load_split",
    "predict_former", "set_determinism", "table_latency_ms", "table_predict",
    "train_c",
]
