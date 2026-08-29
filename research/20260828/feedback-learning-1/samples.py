"""FL-1 sample dump: a few synthetic owners plus one joke and one loss trace."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fl_world as F
import owners as O
import worldsim as W


def write_samples(path: Path, seed: int = O.SEED_BASE) -> None:
    lines: list[str] = []
    lines.append("FL-1 sample owners and event traces")
    lines.append(f"taste prior (AMENDMENTS F1): {O.TASTE_PRIOR}")
    lines.append(f"detector (F5): {O.DETECTOR}")
    lines.append(f"decision threshold (F4): {O.THRESH:.4f}   reward: +1 hit / -2 false / 0 silent")
    lines.append(f"FL-1 frame schema: {F.FL_N_CHANNELS} channels = "
                 f"{F.BASE_N} worldsim world + 4 profile + joke_cat + {3 * O.NCAT} per-category history")
    lines.append("")

    book = O.owner_book(6, O.EVAL_SEED_OFFSET, seed=seed)
    lines.append("=== six evaluation owners (seeds 20260828 + 1,000,000 + i) ===")
    for o in book:
        taste = "  ".join(f"{O.CATEGORIES[c]}={o.p_laugh[c]:.2f}{'*' if o.likes(c) else ' '}"
                          for c in range(O.NCAT))
        lb = "  ".join(f"{L:.0f}s={o.lookback_true_reward(L):+.2f}" for L in O.LATENCIES)
        lines.append(f"owner {o.idx} seed={o.seed} L*={o.pref_latency:.0f}s resets_table={o.resets_table}")
        lines.append(f"    p_laugh : {taste}      (* = oracle chuckles, p >= 2/3)")
        lines.append(f"    look-back true reward per arm: {lb}   best={max(O.LATENCIES, key=o.lookback_true_reward):.0f}s")
    lines.append("")

    # ---- one joke trace --------------------------------------------------
    rng = np.random.default_rng(seed)
    o = book[0]
    eps, _ = F.owner_stream(o, 40, seed + 11, rng)
    trace = None
    for e in eps:
        for j in e.jokes:
            if j.evaluable and j.laughed and j.laugh_ref > 0:
                trace = (e, j)
                break
        if trace:
            break
    e, j = trace
    lines.append("=== one joke event (frames rendered by worldsim.frame_line) ===")
    lines.append(f"owner {o.idx}  category={O.CATEGORIES[j.cat]} p_laugh={o.p_laugh[j.cat]:.2f}  "
                 f"punch_ref={j.punch_ref} decision={j.decision} laugh_ref={j.laugh_ref} "
                 f"laughed={j.laughed} evaluable={j.evaluable}")
    h = e.ch[j.decision, F.HIST_SLICE]
    lines.append("  per-category history at the decision frame (F2): "
                 + "  ".join(f"{O.CATEGORIES[c]}={int(h[3*c])}/{int(h[3*c+1])}"
                             f"[{('none','laughed','silent')[int(h[3*c+2])]}]" for c in range(O.NCAT)))
    wch = np.zeros(W.N_CHANNELS, dtype=np.int16)
    for f in range(max(0, j.punch_ref - 6), min(len(e.acts), j.laugh_ref + 12)):
        wch[:F.BASE_N] = e.ch[f, :F.BASE_N]
        wch[W.CHANNEL_INDEX["prof_greet"]:W.CHANNEL_INDEX["prof_sens"] + 1] = e.ch[f, F.BASE_N:F.BASE_N + 4]
        mark = ""
        if f == j.punch_ref:
            mark = "   <-- punchline reference"
        elif f == j.decision:
            mark = "   <-- ANTICIPATORY DECISION FRAME (0.3 s)"
        elif f == j.laugh_ref:
            mark = "   <-- owner laughs (the reward)"
        lines.append("  " + W.frame_line(wch, -1, int(e.acts[f])) + mark)
    lines.append("")

    # ---- one loss trace --------------------------------------------------
    lines.append("=== one loss / look-back event stream (H-FL1c, F6) ===")
    o2 = book[2]
    losses = F.owner_loss_stream(o2, 8, seed + 5)
    lines.append(f"owner {o2.idx} L*={o2.pref_latency:.0f}s   loss onsets from worldsim occlusions "
                 f"while following: {losses}")
    rng2 = np.random.default_rng(seed + 77)
    for i, L in enumerate([2.0, 8.0, 4.0, 8.0, 6.0, 8.0, 2.0, 8.0][:len(losses)]):
        r, reacq, annoy = o2.lookback_step(L, rng2)
        lines.append(f"  loss {i}: check-in at {L:.0f}s -> reacquired<=5s={reacq} annoyance={annoy} "
                     f"reward={r:+.1f}  (true E[r] for this arm = {o2.lookback_true_reward(L):+.2f})")
    lines.append("")
    lines.append("The learned quantity for H-FL1c is the follow-skill parameter "
                 "`check_in_latency_s` (a config value the executive owns), never an act token.")
    path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    write_samples(Path(__file__).resolve().parent / "sample_owners.txt")
    print("wrote sample_owners.txt")
