"""MA-1 stages 3-6: train C, run every arm closed-loop on held-out geometry,
measure latency.  Imported by ``run.py``; not a script.

Amendments honoured: **A4** (dev-selection metric = harmonic mean of dev
closed-loop success and dev narration F1; the checkpoint hash is frozen BEFORE
any held-out run; ALWAYS-NONE / EVENT-EVERY-FRAME reference rows; latency rows
record host load and co-tenants), **A2** (held-out is disjoint GEOMETRY;
STRAIGHT-TO-GOAL informativeness criterion), **A5** (C-h0 / C-h60 history
ablation), **A8** (safety row), **A1/A3/A7/A10** via ``closed_loop``.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

SCRATCH = Path(os.environ.get("MA1_SCRATCH", Path.home() / ".cache/parcel-0e/ma1"))
DATA_DIR = SCRATCH / "data"
CKPT = SCRATCH / "ckpt"

# ===========================================================================
# episode specs, replayed identically by every arm
# ===========================================================================


def load_specs(split: str) -> list:
    metas = json.loads((DATA_DIR / f"{split}_meta.json").read_text())
    return [(int(m["episode_id"]), int(m["scene_seed"]), str(m["kind"]))
            for m in metas]


_W: dict = {}


def _world(seed: int):
    import teacher as T
    if seed not in _W:
        if len(_W) > 24:
            _W.clear()
        w = T.HeadlessCityWorld(scene=T.build_scene_path(seed))
        _W[seed] = (w, T.HeadlessCityQualityHarness(w))
    return _W[seed]


def _script(episode_id: int, scene_seed: int, kind: str, master_seed: int):
    import teacher as T
    w, _h = _world(scene_seed)
    return T.prepare_episode(
        w, T.sample_script(episode_id, scene_seed, master_seed, force_kind=kind))


# --- pool plumbing ---------------------------------------------------------

_ARM = {"kind": None, "policy": None, "seed": 20260829}


def _init_cpu(arm: str, seed: int):
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    import arms
    _ARM["kind"] = arm
    _ARM["seed"] = seed
    _ARM["policy"] = {
        "Aprime_n": arms.ReflexTable, "ALWAYS-IDLE": arms.AlwaysIdle,
        "STRAIGHT-TO-GOAL": arms.StraightToGoal,
    }.get(arm, lambda: None)()


def _init_gpu(ckpt_path: str, seed: int, hist_mask: str):
    os.environ["OPENBLAS_NUM_THREADS"] = "2"
    import arms
    import torch
    m = arms.BehaviorFormerMA()
    m.load_state_dict(torch.load(ckpt_path, map_location="cpu"))
    _ARM["kind"] = "C"
    _ARM["seed"] = seed
    _ARM["policy"] = arms.FormerPolicy(m, device="cuda", ctx=128,
                                       hist_mask=hist_mask)


def _job(spec):
    from closed_loop_core import run_core
    eid, seed, kind = spec
    try:
        w, h = _world(seed)
        s = _script(eid, seed, kind, _ARM["seed"])
        return run_core(w, h, s, policy=_ARM["policy"],
                        teacher_arm=(_ARM["kind"] == "T"), record=False)
    except Exception as exc:  # noqa: BLE001
        import traceback
        return ("ERROR", f"{eid}/{seed}: {type(exc).__name__}: {exc}",
                traceback.format_exc()[-600:])


def run_arm(arm: str, specs: list, *, seed: int, workers: int,
            ckpt_path: str | None = None, hist_mask: str = "none", log=print):
    import multiprocessing as mp
    ctx = mp.get_context("spawn")
    t0 = time.time()
    if arm.startswith("C"):
        pool = ctx.Pool(workers, initializer=_init_gpu,
                        initargs=(ckpt_path, seed, hist_mask))
    else:
        pool = ctx.Pool(workers, initializer=_init_cpu, initargs=(arm, seed))
    traces, errors = [], []
    with pool:
        for i, r in enumerate(pool.imap_unordered(_job, specs, chunksize=1)):
            if isinstance(r, tuple) and r and r[0] == "ERROR":
                errors.append(r[1:])
                continue
            traces.append(r)
            if (i + 1) % 100 == 0:
                log(f"  [{arm}] {i+1}/{len(specs)} {time.time()-t0:.0f}s")
    log(f"  [{arm}] done {len(traces)} traces, {len(errors)} errors, "
        f"{time.time()-t0:.0f}s")
    return traces, errors, round(time.time() - t0, 1)


# ===========================================================================
# host load (A4's latency clause)
# ===========================================================================


def host_state() -> dict:
    try:
        load = os.getloadavg()
    except OSError:
        load = (0.0, 0.0, 0.0)
    gpu = {}
    try:
        out = subprocess.run(
            ["nvidia-smi",
             "--query-compute-apps=pid,process_name,used_memory",
             "--format=csv,noheader"], capture_output=True, text=True,
            timeout=20, check=False).stdout.strip()
        gpu["compute_apps"] = [ln.strip() for ln in out.splitlines() if ln.strip()]
        out2 = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
             "--format=csv,noheader"], capture_output=True, text=True,
            timeout=20, check=False).stdout.strip()
        gpu["gpu"] = out2
    except Exception as exc:  # noqa: BLE001
        gpu["error"] = str(exc)
    return {"loadavg": [round(v, 2) for v in load],
            "cpus": os.cpu_count(), **gpu}


# ===========================================================================
# the stages
# ===========================================================================


def run(a, results, *, md, log, gate_gpu, amendments, want, open_loop_metrics,
        results_json):
    import arms
    import torch
    from closed_loop import narration_scores, reference_narration_rows, score_arm

    res = results["stages"]

    # ---------------------------------------------------------------- train
    ckpt_path = CKPT / "arm_C.pt"
    if "train" in want:
        am = amendments()
        gate = gate_gpu(min_free_mb=14_000)
        md("## 3. Arm C — training")
        md()
        md(f"* AMENDMENTS.md check before this row: "
           f"{'PRESENT' if am['exists'] else 'ABSENT'}")
        md(f"* **GPU gate** (a foreign executor shares this card): needed >= 14000 MB "
           f"free, saw {gate['free_mb']} MB after waiting {gate['waited_s']} s -> "
           f"{'START' if gate['ok'] else 'ABORT'}. Our own cap is 12 GB.")
        md(f"* host at launch: `{json.dumps(host_state())}`")
        md()
        if not gate["ok"]:
            md("**Training was not started: the GPU gate never opened.**")
            res["train"] = {"skipped": "gpu_gate"}
            return

        train = arms.load_split(DATA_DIR, "train")
        dev = arms.load_split(DATA_DIR, "dev")
        log(f"train {train.n_frames} frames / {train.n_episodes} eps; "
            f"dev {dev.n_frames} / {dev.n_episodes}")

        dev_specs = load_specs("dev")[:a.dev_closed]
        model = arms.BehaviorFormerMA()
        n_params = sum(p.numel() for p in model.parameters())

        def eval_fn(m, step):
            """A4's dev-selection metric: harmonic mean of dev CLOSED-LOOP
            success and dev narration F1, on a fixed dev-layout slice."""

            pa, pn = arms.predict_former(m, dev, device="cuda")
            ol = open_loop_metrics(dev, pa, pn)
            pol = arms.FormerPolicy(m, device="cuda", ctx=128)
            from closed_loop_core import run_core
            trs = []
            for eid, seed, kind in dev_specs:
                w, h = _world(seed)
                s = _script(eid, seed, kind, a.seed)
                trs.append(run_core(w, h, s, policy=pol, record=False))
            sr = float(np.mean([t.meta["success"] for t in trs]))
            nf = narration_scores(trs)["macro_f1"] or 0.0
            score = (0.0 if (sr <= 0 or nf <= 0) else 2 * sr * nf / (sr + nf))
            m.train()
            return {"dev_closed_success": round(sr, 4),
                    "dev_narr_macro_f1": round(nf, 4),
                    "score": round(score, 4),
                    "open_loop_act_top1": ol["act_top1"],
                    "open_loop_act_bal_acc": ol["act_balanced_acc"],
                    "open_loop_narr_f1": ol["narr_macro_f1"]}

        hist = arms.train_c(
            model, train, window=a.window, warmup=a.warmup, batch=a.batch,
            max_steps=a.max_steps, lr=a.lr, seed=a.seed,
            budget_s=a.train_budget_s, device="cuda", eval_fn=eval_fn,
            eval_every=a.eval_every, patience=a.patience, log=log)
        sha = hashlib.sha256(ckpt_path.read_bytes()).hexdigest()
        hist["checkpoint_sha256"] = sha
        hist["params"] = n_params
        hist["dev_closed_episodes"] = len(dev_specs)
        res["train"] = hist
        results_json.write_text(json.dumps(results, indent=2, default=str))

        md(f"Arm C: BehaviorFormer, 6 layers x d=256 x 4 heads, ctx {a.window}, "
           f"two heads (act {arms.N_ACTS} / narration {arms.N_NARR}), "
           f"**{n_params/1e6:.2f} M params**. Class-weighted CE on both heads "
           f"(BM-1's A4 rule, counts^-0.5 mean-normalised), AdamW + OneCycle, "
           f"lr {a.lr}, batch {a.batch}, window {a.window} (warm-up "
           f"{a.warmup} frames excluded from the loss).")
        md()
        md(f"**Early stopping (pre-registered).** Dev-selection metric is A4's: "
           f"the harmonic mean of dev **closed-loop** success and dev narration "
           f"macro-F1 on a fixed {len(dev_specs)}-episode dev-geometry slice, "
           f"evaluated every {a.eval_every} steps, patience {a.patience}. "
           f"Stopped by `{hist['stopped']}` at step {hist['steps_run']}; "
           f"**best step {hist['best']['step']}** "
           f"(score {hist['best']['score']}).")
        md()
        md("| step | dev closed-loop SR | dev narration F1 | selection score | "
           "open-loop act top-1 | open-loop act bal-acc | open-loop narr F1 |")
        md("|---|---|---|---|---|---|---|")
        for h in hist["history"]:
            md(f"| {h['step']} | {h['dev_closed_success']} | "
               f"{h['dev_narr_macro_f1']} | {h['score']} | "
               f"{h['open_loop_act_top1']} | {h['open_loop_act_bal_acc']} | "
               f"{h['open_loop_narr_f1']} |")
        md()
        md(f"* wall {hist['wall_s']} s; GPU peak "
           f"**{hist['gpu_peak_mb']} MB** (cap 12000); "
           f"{hist['epochs_equivalent']} epoch-equivalents")
        md(f"* **checkpoint frozen before any held-out run**: "
           f"`arm_C.pt` sha256 `{sha[:32]}...`")
        md()

    # ------------------------------------------------------- closed-loop
    if "closed" in want:
        am = amendments()
        specs = load_specs("held")
        md("## 4. Held-out closed loop")
        md()
        md(f"* AMENDMENTS.md check before this row: "
           f"{'PRESENT' if am['exists'] else 'ABSENT'} — A1/A2/A3/A4/A7/A8/A10 "
           "applied; see §6 for the per-amendment ledger.")
        md(f"* {len(specs)} held-out episodes on **disjoint generated geometry** "
           "(A2). Every arm replays the SAME scripts through the same "
           "`run_core`, so the world, the cues and the gold timeline are "
           "identical across arms; only the policy differs.")
        md("* Each arm's act token is decoded by the product codec and passes "
           "through `apply_reactive_safety` before it reaches the world — the "
           "safety core is never bypassed by any arm.")
        md()
        arm_res = {}
        traces_by_arm = {}
        for arm, workers, ck, hmask in (
                ("T", a.workers, None, "none"),
                ("Aprime_n", a.workers, None, "none"),
                ("ALWAYS-IDLE", a.workers, None, "none"),
                ("STRAIGHT-TO-GOAL", a.workers, None, "none"),
                ("C", a.gpu_workers, str(ckpt_path), "none"),
                ("C-h0", a.gpu_workers, str(ckpt_path), "h0")):
            if arm.startswith("C") and not ckpt_path.is_file():
                log("no checkpoint; skipping " + arm)
                continue
            if arm.startswith("C"):
                g = gate_gpu(min_free_mb=14_000)
                md(f"* GPU gate before arm {arm} closed loop: {g['free_mb']} MB free "
                   f"after {g['waited_s']} s -> {'RUN' if g['ok'] else 'SKIP'}")
                if not g["ok"]:
                    continue
            use = (specs[:a.ablation_subset] if arm == "C-h0"
                   and a.ablation_subset and a.ablation_subset < len(specs)
                   else specs)
            trs, errs, wall = run_arm(arm, use, seed=a.seed, workers=workers,
                                      ckpt_path=ck, hist_mask=hmask, log=log)
            traces_by_arm[arm] = trs
            arm_res[arm] = {"wall_s": wall, "errors": len(errs),
                            "error_sample": errs[:2], "episodes_run": len(use)}
            results_json.write_text(json.dumps(results, indent=2, default=str))

        t_nav = None
        if "T" in traces_by_arm:
            t_nav = score_arm(traces_by_arm["T"])["nav"]
        for arm, trs in traces_by_arm.items():
            arm_res[arm].update(score_arm(trs, teacher_nav=t_nav))
        if "C" in traces_by_arm:
            arm_res["_narration_references"] = reference_narration_rows(
                traces_by_arm["C"])
        elif "Aprime_n" in traces_by_arm:
            arm_res["_narration_references"] = reference_narration_rows(
                traces_by_arm["Aprime_n"])

        # A5: score C on exactly C-h0's prefix so the ablation is comparable.
        if "C" in traces_by_arm and "C-h0" in traces_by_arm:
            n0 = len(traces_by_arm["C-h0"])
            ids = {t.meta["episode_id"] for t in traces_by_arm["C-h0"]}
            c_sub = [t for t in traces_by_arm["C"] if t.meta["episode_id"] in ids]
            arm_res["_A5"] = {
                "episodes": n0,
                "C": score_arm(c_sub),
                "C-h0": score_arm(traces_by_arm["C-h0"]),
            }

        # A2: is the split informative?
        if "STRAIGHT-TO-GOAL" in arm_res:
            s2g = arm_res["STRAIGHT-TO-GOAL"]["nav"]["success_rate"]
            arm_res["_A2_informativeness"] = {
                "straight_to_goal_success_rate": s2g,
                "uninformative_if_above": 0.7,
                "informative": bool(s2g <= 0.7),
            }
        res["closed"] = arm_res
        results_json.write_text(json.dumps(results, indent=2, default=str))
        _write_closed_tables(md, arm_res, specs)

    # ------------------------------------------------------------- latency
    if "latency" in want and ckpt_path.is_file():
        import arms as _arms
        dev = _arms.load_split(DATA_DIR, "dev")
        m = _arms.BehaviorFormerMA()
        m.load_state_dict(torch.load(ckpt_path, map_location="cpu"))
        host_before = host_state()
        g = gate_gpu(min_free_mb=14_000)
        lat = {"host": host_before, "gpu_gate": {"free_mb": g["free_mb"]}}
        lat["C_gpu"] = _arms.latency_ms(m, dev, device="cuda", n=2000)
        lat["C_cpu_1thread"] = _arms.latency_ms(m, dev, device="cpu", n=2000)
        lat["Aprime_n_cpu"] = _arms.table_latency_ms(_arms.ReflexTable(), dev, 2000)
        lat["host_after"] = host_state()
        res["latency"] = lat
        md("## 5. Per-frame latency")
        md()
        md("Streaming cost of one decision: a full forward over the "
           "ctx = 128 frame window, no KV cache — the deployable cost of the "
           "shape as written. 2 000 frames each. The 10 Hz duplex clock gives "
           "a 100 ms budget per frame.")
        md()
        md("| arm | device | ms / frame | within the 100 ms frame budget |")
        md("|---|---|---|---|")
        for k, tag in (("C_gpu", "C (RTX 5000 Ada)"),
                       ("C_cpu_1thread", "C (1 CPU thread)"),
                       ("Aprime_n_cpu", "A'n (1 CPU thread)")):
            r = lat[k]
            md(f"| {tag} | {r['device']} | {r['ms_per_frame']} | "
               f"{'yes' if r['realtime_ok'] else 'NO'} |")
        md()
        md(f"Host at measurement (A4's co-tenant clause): loadavg "
           f"{host_before['loadavg']}, {host_before.get('cpus')} CPUs; GPU "
           f"`{host_before.get('gpu','?')}`; compute apps on the card: "
           f"`{host_before.get('compute_apps')}`. A foreign executor shares "
           "this host, so these are wall-clock figures under real contention, "
           "not an idle-machine best case.")
        md()
        results_json.write_text(json.dumps(results, indent=2, default=str))


def _fmt(v):
    return "n/a" if v is None else v


def _write_closed_tables(md, r: dict, specs: list) -> None:
    order = [k for k in ("T", "C", "C-h0", "Aprime_n", "STRAIGHT-TO-GOAL",
                         "ALWAYS-IDLE") if k in r]
    name = {"T": "T (teacher — the shipped stack)", "C": "C (Model A v0)",
            "C-h0": "C-h0 (history ablated)",
            "Aprime_n": "A'n (frozen reflex table)",
            "STRAIGHT-TO-GOAL": "STRAIGHT-TO-GOAL (reference)",
            "ALWAYS-IDLE": "ALWAYS-IDLE (reference)"}

    md("### 4.1 H-MA1a — closed-loop navigation on held-out geometry")
    md()
    md("> **Bar (DESIGN):** >= 0.85 x teacher success, <= 1.25 x teacher path "
       "length, collision rate <= teacher + 0.02. Refuted below 0.6 x teacher "
       "success.  **A2 adds:** on held-out layouts C must beat STRAIGHT-TO-GOAL "
       "by >= 0.10 success, and the split is uninformative if STRAIGHT-TO-GOAL "
       "succeeds on > 0.7 of them.")
    md()
    md("| arm | success (A1-strict) | band entry | SPL | x teacher SR | "
       "path (m, successes) | x teacher path | collision rate | vs teacher | "
       "mean frames |")
    md("|---|---|---|---|---|---|---|---|---|---|")
    for k in order:
        n = r[k]["nav"]
        vt = r[k].get("vs_teacher", {})
        md(f"| {name[k]} | **{n['success_rate']}** | {n.get('band_entry_rate','n/a')} | "
           f"{n['spl']} | {_fmt(vt.get('success_ratio'))} | "
           f"{_fmt(n['mean_path_m_success'])} | {_fmt(vt.get('path_ratio'))} | "
           f"{n['collision_rate']} | {_fmt(vt.get('collision_delta'))} | "
           f"{n['mean_frames']} |")
    md()
    if "T" in r and "C" in r:
        tb = r["T"]["nav"].get("band_entry_rate") or 1e-9
        cb = r["C"]["nav"].get("band_entry_rate") or 0.0
        md(f"On the looser band-entry predicate the same comparison reads "
           f"C {cb} vs teacher {round(tb,4)} = **{round(cb/tb,4)} x teacher** "
           "(the DESIGN's bar is 0.85 x on success and 0.6 x is the refutation "
           "line; it is pre-registered against the strict predicate, so this "
           "row is a companion, not a substitute).")
        md()
    inf = r.get("_A2_informativeness")
    if inf:
        md(f"**A2 informativeness:** STRAIGHT-TO-GOAL succeeds on "
           f"{inf['straight_to_goal_success_rate']} of held-out episodes "
           f"(uninformative above {inf['uninformative_if_above']}) -> split is "
           f"**{'INFORMATIVE' if inf['informative'] else 'UNINFORMATIVE'}**.")
        if "C" in r:
            d = round(r["C"]["nav"]["success_rate"] - inf["straight_to_goal_success_rate"], 4)
            md(f"**C - STRAIGHT-TO-GOAL = {d}** (A2 bar: >= 0.10) -> "
               f"{'MET' if d >= 0.10 else 'NOT MET'}.")
        md()

    md("### 4.2 H-MA1b — interruptions absorbed in stream")
    md()
    md("> **Bar (DESIGN):** switch toward the new goal within 1.0 s in >= 0.9 "
       "of cases; for queue cues `plan.queued` then `plan.resumed` in the right "
       "order in >= 0.8.  **A3:** the switch is anchored to the DETECTED CUE "
       "frame, the heading is measured from the truth pose, and the goal "
       "channels are masked for 5 frames after the cue so a bearing-follower "
       "cannot score from the input alone. The queue check is task-stack exact "
       "(oracle arrival at goal 2, then at goal 1).")
    md()
    md("| arm | switch rate (all cues) | median latency | revise | queue | "
       "queue narration order | queue task-stack exact |")
    md("|---|---|---|---|---|---|---|")
    for k in order:
        s = r[k]["switch"]
        md(f"| {name[k]} | **{s.get('any',{}).get('rate','n/a')}** | "
           f"{_fmt(s.get('any',{}).get('median_latency_s'))} | "
           f"{s.get('revise',{}).get('rate','n/a')} | "
           f"{s.get('queue',{}).get('rate','n/a')} | "
           f"{s['queue_narration_order']['rate']} | "
           f"{s['queue_task_stack_exact']['rate']} |")
    md()

    md("### 4.3 H-MA1c — narration events, right and on time")
    md()
    md("> **Bar (DESIGN):** event-conditional F1 >= 0.85 for `nav.start`, "
       "`nav.arrived`, `nav.blocked`, `plan.revised/queued/resumed`, each within "
       "a 1.0 s window; false-event rate <= 0.05.  **A4:** an emission is a "
       "rising edge; at most one TP per gold event in the CAUSAL window "
       "`[t_gold, t_gold + 1.0 s]`; every other emission is an FP.  **A10:** the "
       "false-event rate is *predicted terminal with no backing receipt*; these "
       "tokens are PREDICTIONS and carry no authority.  **A7:** reported per "
       "vocabulary partition; `nav.progress` is INTERNAL-ONLY and is not scored "
       "as narration at all.")
    md()
    md("| arm | macro F1 | product-backed | research-only | false-event rate | "
       "predicted terminal w/o receipt | emitted events |")
    md("|---|---|---|---|---|---|---|")
    for k in order:
        n = r[k]["narration"]
        md(f"| {name[k]} | **{_fmt(n['macro_f1'])}** | "
           f"{_fmt(n['macro_f1_product_backed'])} | "
           f"{_fmt(n['macro_f1_research_only'])} | {n['false_event_rate']} | "
           f"{n['predicted_terminal_without_backing_receipt']} | "
           f"{n['emitted_events']} |")
    refs = r.get("_narration_references")
    if refs:
        for k, v in refs.items():
            md(f"| {k} (A4 reference) | {_fmt(v['macro_f1'])} | "
               f"{_fmt(v['macro_f1_product_backed'])} | "
               f"{_fmt(v['macro_f1_research_only'])} | {v['false_event_rate']} | "
               f"{v['predicted_terminal_without_backing_receipt']} | "
               f"{v['emitted_events']} |")
    md()
    head = order[0]
    counts = r[head]["narration"]["gold_events_per_class"]
    md("Held-out gold events per scored class (A4 floor is 200): " +
       ", ".join(f"`{k}` {v}" for k, v in counts.items()))
    md()
    md("Per-class F1:")
    md()
    md("| class | " + " | ".join(name[k] for k in order) + " |")
    md("|---" * (len(order) + 1) + "|")
    fams = list(r[head]["narration"]["per_family"])
    for fam in fams:
        md(f"| `{fam}` | " + " | ".join(
            str(r[k]["narration"]["per_family"][fam]["f1"]) for k in order) + " |")
    md()

    md("### 4.4 H-MA1d — liveness does not cost navigation")
    md()
    md("> **Bar (DESIGN):** `attend.sound` + a gaze toward the bearing within "
       "0.5 s in >= 0.8 of sound events; success within 0.03 and path within "
       "5 % of episodes with no sound event.")
    md()
    md("| arm | sound events | attend rate (narration AND gaze) | narration only | "
       "gaze only | SR with sound | SR without | delta SR | path delta % |")
    md("|---|---|---|---|---|---|---|---|---|")
    for k in order:
        s = r[k]["sound"]
        sp = r[k]["sound_split"]
        md(f"| {name[k]} | {s['events']} | **{s['attend_rate']}** | "
           f"{s['narration_only_rate']} | {s['gaze_only_rate']} | "
           f"{sp['with_sound'].get('success_rate','n/a')} | "
           f"{sp['without_sound'].get('success_rate','n/a')} | "
           f"{_fmt(sp.get('delta_success'))} | {_fmt(sp.get('path_pct_delta'))} |")
    md()

    a5 = r.get("_A5")
    if a5:
        md("### 4.45 A5 — does the last minute earn its place?")
        md()
        md("> **A5:** C-h60 (the full model) must beat C-h0 by >= 0.10 on "
           "time-to-switch success or on blocked-recovery success on the "
           "held-out slice, else the finding is \"window suffices\".  "
           "**Caveat, stated plainly:** C-h0 here is an INPUT ABLATION of the "
           "SAME trained checkpoint (the six history tokens, the five age "
           "channels and the two 60 s counters pinned to their null values at "
           "inference), not a separately trained model. A retrained C-h0 is the "
           "stronger experiment and was not run inside the wall budget.")
        md()
        md(f"Both rows are scored on the SAME {a5['episodes']} held-out "
           "episodes.")
        md()
        md("| arm | success | switch rate | narration macro F1 | "
           "nav.blocked F1 |")
        md("|---|---|---|---|---|")
        for k in ("C", "C-h0"):
            n, s_, nr = a5[k]["nav"], a5[k]["switch"], a5[k]["narration"]
            md(f"| {'C-h60 (full)' if k == 'C' else 'C-h0 (history pinned null)'} "
               f"| {n['success_rate']} | {s_.get('any',{}).get('rate','n/a')} | "
               f"{_fmt(nr['macro_f1'])} | "
               f"{nr['per_family']['nav.blocked']['f1']} |")
        dsw = round((a5["C"]["switch"].get("any", {}).get("rate", 0) or 0)
                    - (a5["C-h0"]["switch"].get("any", {}).get("rate", 0) or 0), 4)
        dbl = round(a5["C"]["narration"]["per_family"]["nav.blocked"]["f1"]
                    - a5["C-h0"]["narration"]["per_family"]["nav.blocked"]["f1"], 4)
        md()
        md(f"delta switch rate = **{dsw}**, delta `nav.blocked` F1 = **{dbl}** "
           f"(A5 bar: >= 0.10 on either) -> "
           f"{'the last minute EARNS its place' if max(dsw, dbl) >= 0.10 else 'WINDOW SUFFICES'}.")
        md()

    _earns_its_place(md, r)

    md("### 4.5 A8 — the safety row")
    md()
    md("> **Bar (A8):** every RAW violation rate <= 0.01, or the finding is "
       "\"A runs only behind the deterministic filter\". Post-filter rates must "
       "be 0. RAW = the arm's own emission; POST = after the filter "
       "(`stop` latched -> hold; owner speaking -> hold; forward twist into an "
       "occupied sector -> zero forward). Every arm additionally passes through "
       "`apply_reactive_safety` before the world sees it.")
    md()
    md("| arm | stop frames | speaking frames | occupied-ahead frames | "
       "RAW non-idle after stop | RAW twist into occupied | "
       "RAW twist while owner speaking | POST (all three) |")
    md("|---|---|---|---|---|---|---|---|")
    for k in order:
        s = r[k]["safety"]
        pf = s["post_filter"]
        post_all = max(pf["nonidle_after_stop_rate"],
                       pf["twist_into_occupied_rate"],
                       pf["twist_while_owner_speaking_rate"])
        md(f"| {name[k]} | {s['stop_frames']} | {s['owner_speaking_frames']} | "
           f"{s['occupied_ahead_frames']} | "
           f"**{s['raw']['nonidle_after_stop_rate']}** | "
           f"**{s['raw']['twist_into_occupied_rate']}** | "
           f"**{s['raw']['twist_while_owner_speaking_rate']}** | {post_all} |")
    md()


def _earns_its_place(md, r: dict) -> None:
    """The DESIGN's clause, read as A1 and A3 amend it."""

    if "C" not in r or "Aprime_n" not in r:
        return
    c, ap = r["C"], r["Aprime_n"]
    d_succ = round(c["nav"]["success_rate"] - ap["nav"]["success_rate"], 4)
    d_sw = round((c["switch"].get("any", {}).get("rate", 0) or 0)
                 - (ap["switch"].get("any", {}).get("rate", 0) or 0), 4)
    d_f1 = round((c["narration"]["macro_f1"] or 0.0)
                 - (ap["narration"]["macro_f1"] or 0.0), 4)
    md("### 4.6 \"Does the sequence model earn its place?\"")
    md()
    md("> **DESIGN:** beating A'n by >= 0.10 on (b)'s time-to-switch success or "
       "on (a)'s success is the clause.  **A3:** it is read on (a) and (c), and "
       "on (b) only under the goal mask (which is what 4.2 measures).  "
       "**A1:** on narration the clause is `C - A'n >= 0.10 on F1`, else the "
       "finding is \"rules suffice for narration\".")
    md()
    md("| axis | C | A'n | C - A'n | bar | met? |")
    md("|---|---|---|---|---|---|")
    md(f"| (a) held-out success | {c['nav']['success_rate']} | "
       f"{ap['nav']['success_rate']} | **{d_succ}** | >= 0.10 | "
       f"{'YES' if d_succ >= 0.10 else 'no'} |")
    md(f"| (b) time-to-switch success (masked goal) | "
       f"{c['switch'].get('any',{}).get('rate','n/a')} | "
       f"{ap['switch'].get('any',{}).get('rate','n/a')} | **{d_sw}** | "
       f">= 0.10 | {'YES' if d_sw >= 0.10 else 'no'} |")
    md(f"| (c) narration macro F1 | {_fmt(c['narration']['macro_f1'])} | "
       f"{_fmt(ap['narration']['macro_f1'])} | **{d_f1}** | >= 0.10 | "
       f"{'YES' if d_f1 >= 0.10 else 'no'} |")
    md()
    if d_f1 < 0.10:
        md("On narration the clause is NOT met, so the finding this row "
           "carries is **\"rules suffice for narration\"** — the frozen "
           "reflex table, reading the cue channel and the free-space ring off "
           "a single frame, is not beaten by the sequence model by the "
           "pre-registered margin. Read it beside A'n's false-event rate in "
           "4.3: a table that emits on every qualifying frame buys recall with "
           "precision, and the DESIGN's bar is on F1.")
    else:
        md("On narration the clause IS met by the pre-registered margin.")
    md()


__all__ = ["host_state", "load_specs", "run", "run_arm"]
