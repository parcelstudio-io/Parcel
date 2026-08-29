"""BM-1 runner.  ``run.py --arm all --seed 20260828`` -> results.json.

Arms: reference rows (TEACHER, CEILING, ALWAYS-IDLE, CHUCKLE-ALL), A (rule
baseline), A' (reflex table, amendment A2), E (frame MLP, A2), B (GRU),
C (BehaviorFormer), D (LoRA LM).

A4 decoding rule, fixed before any frozen pass: **argmax decoding of
class-weighted cross-entropy models** (w_c proportional to n_c^-0.5).  No
per-class threshold is tuned on dev.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import time
from pathlib import Path

import arms
import eval as ev
import numpy as np
from worldsim import FROZEN_SPLITS

HERE = Path(__file__).resolve().parent
DATA = Path(os.path.expanduser("~/.cache/parcel-0e/bm1/data"))
OUT = HERE
CKPT = arms.CKPT_DIR


def host_state() -> dict:
    def sh(cmd: str) -> str:
        try:
            return subprocess.run(cmd, shell=True, capture_output=True, text=True,  # noqa: PLW1510
                                  timeout=20).stdout.strip()
        except Exception as exc:  # pragma: no cover  # noqa: BLE001
            return f"<{exc}>"

    return {
        "load_1min": float(open("/proc/loadavg").read().split()[0]),
        "nvidia_smi_util_mem": sh(
            "nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total "
            "--format=csv,noheader"),
        "gpu_processes": sh(
            "nvidia-smi --query-compute-apps=pid,process_name,used_memory "
            "--format=csv,noheader") or "<none>",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def subset(split: ev.Split, n_eps: int, name: str) -> ev.Split:
    n_eps = min(n_eps, split.n_episodes)
    end = int(split.ep_start[n_eps - 1] + split.ep_len[n_eps - 1])
    return ev.Split(
        name=name,
        channels=split.channels[:end], acts=split.acts[:end], words=split.words[:end],
        ann=split.ann[:end], ep_start=split.ep_start[:n_eps], ep_len=split.ep_len[:n_eps],
        ep_family=split.ep_family[:n_eps], ep_flags=split.ep_flags[:n_eps],
        acts_ceiling=None if split.acts_ceiling is None else split.acts_ceiling[:end],
    )


def composite(r: dict) -> float:
    m = r["M2"]
    return float(
        np.mean([m["chuckle"]["f1"], m["lookback"]["f1"], m["comply"]["f1"]])
        - m["false_chuckle"]["rate"]
    )


def append_results_md(section: str) -> None:
    with (OUT / "RESULTS.md").open("a") as fh:
        fh.write(section.rstrip() + "\n\n")


def md_table(rows: list[tuple[str, dict]], key: str = "M2") -> str:
    head = ("| arm | split | M1 | (a) chuckle | (b) look-back | (c) comply | "
            "(d) comfort | false-chuckle | M3 raw | A7 twist raw | stop |\n"
            "|---|---|---|---|---|---|---|---|---|---|---|\n")
    out = []
    for tag, r in rows:
        m = r[key]
        out.append(
            f"| {tag} | {r['split']} | {r['M1']['frame_accuracy']:.4f} | "
            f"{m['chuckle']['f1']:.3f} | {m['lookback']['f1']:.3f} | "
            f"{m['comply']['f1']:.3f} | {m['comfort']['f1']:.3f} | "
            f"{m['false_chuckle']['rate']:.3f} | "
            f"{r['M3']['raw_violation_rate']:.5f} | "
            f"{r['M3']['A7_raw_twist_rate']:.5f} | "
            f"{r['A7_stop_compliance']['rate']:.3f} |"
        )
    return head + "\n".join(out)


# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="all")
    ap.add_argument("--seed", type=int, default=20260828)
    ap.add_argument("--budget-min", type=float, default=22.0)
    ap.add_argument("--d-budget-min", type=float, default=35.0)
    ap.add_argument("--skip-existing", action="store_true")
    ap.add_argument("--ce-alpha", type=float, default=0.5,
                    help="A4 class-weight exponent w_c ~ n_c^-alpha")
    ap.add_argument("--suffix", default="", help="tag suffix for a variant run")
    args = ap.parse_args()

    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:256")
    import torch

    torch.set_num_threads(32)
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(12.0 / 32.0)

    t_all = time.time()
    arms.log(f"host at start: {json.dumps(host_state())}", tag="run")

    train = ev.load_split(DATA, "train")
    dev = ev.load_split(DATA, "dev")
    frozen_parts = [ev.load_split(DATA, s) for s in FROZEN_SPLITS]
    frozen = ev.concat_splits("frozen", frozen_parts)
    dev_sel = subset(dev, 120, "dev_sel")

    want = {a.strip() for a in args.arm.split(",")} if args.arm != "all" else {
        "ref", "A", "Aprime", "E", "B", "C", "D"
    }

    results: dict = {}
    res_path = OUT / "results.json"
    if res_path.exists():
        results = json.loads(res_path.read_text())
    results.setdefault("meta", {})
    results["meta"].update({
        "seed": args.seed,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "decoding_rule": "A4: argmax over class-weighted CE (w_c ~ n_c^-0.5); "
                         "no dev-tuned per-class thresholds",
        "evidence_tier": "desktop-sim (synthetic token world, no physics/sensors)",
        "splits": {s: {"episodes": int(x.n_episodes), "frames": int(x.n_frames)}
                   for s, x in [("train", train), ("dev", dev), ("frozen", frozen)]},
    })

    def record(tag: str, pred_dev: np.ndarray | None, pred_frozen: np.ndarray | None,
               extra: dict | None = None) -> dict:
        entry = results.get(tag, {})
        if pred_dev is not None:
            entry["dev"] = ev.score(dev, pred_dev)
            arms.log(ev.summarize(tag, entry["dev"]), tag="run")
        if pred_frozen is not None:
            entry["frozen"] = ev.score(frozen, pred_frozen)
            arms.log(ev.summarize(tag, entry["frozen"]), tag="run")
            offs = 0
            entry["slices"] = {}
            for name, part in zip(FROZEN_SPLITS, frozen_parts):
                n = part.n_frames
                entry["slices"][name] = ev.score(part, pred_frozen[offs : offs + n])
                arms.log(ev.summarize(tag, entry["slices"][name]), tag="run")
                offs += n
        if extra:
            entry.update(extra)
        results[tag] = entry
        (OUT / f"results-{tag}.json").write_text(json.dumps(entry, indent=1))
        res_path.write_text(json.dumps(results, indent=1))
        return entry

    # ---- reference rows --------------------------------------------------
    if "ref" in want:
        record("TEACHER", dev.acts.copy(), frozen.acts.copy())
        if dev.acts_ceiling is not None:
            record("CEILING", dev.acts_ceiling.copy(), frozen.acts_ceiling.copy())
        record("ALWAYS-IDLE", arms.always_idle(dev), arms.always_idle(frozen))
        record("CHUCKLE-ALL", arms.chuckle_every_punchline(dev),
               arms.chuckle_every_punchline(frozen))

    # ---- arm A -----------------------------------------------------------
    if "A" in want:
        t0 = time.time()
        cfg = arms.calibrate_arm_a(train, seed=args.seed)
        record("A", arms.arm_a_predict(dev, cfg, seed=args.seed),
               arms.arm_a_predict(frozen, cfg, seed=args.seed),
               extra={"train_wall_s": round(time.time() - t0, 1),
                      "latency": {"cpu1": arms.arm_a_latency(dev, cfg),
                                  "host_before": host_state()},
                      "base_rates": {k: round(v, 6) for k, v in cfg.base_rate.items()}})

    # ---- arm A' (A2) -----------------------------------------------------
    if "Aprime" in want:
        mb = arms.modal_lookback_bearing(train)
        record("Aprime", arms.arm_aprime_predict(dev, modal_bin=mb),
               arms.arm_aprime_predict(frozen, modal_bin=mb),
               extra={"modal_lookback_bearing_bin": mb})

    # ---- learned arms ----------------------------------------------------
    weights = arms.class_weights(train, alpha=args.ce_alpha)
    sfx = args.suffix
    results["meta"]["ce_alpha" + (sfx or "")] = args.ce_alpha

    def make_eval_fn(kind: str):
        def fn(model, step):
            if kind == "B":
                p = arms.predict_gru(model, dev_sel, mode="argmax", seed=args.seed)
            elif kind == "C":
                p = arms.predict_former(model, dev_sel, mode="argmax", seed=args.seed)
            else:
                p = arms.predict_mlp(model, dev_sel)
            r = ev.score(dev_sel, p)
            model.train()
            return {"step": step, "score": round(composite(r), 4),
                    "a": r["M2"]["chuckle"]["f1"], "b": r["M2"]["lookback"]["f1"],
                    "c": r["M2"]["comply"]["f1"], "d": r["M2"]["comfort"]["f1"],
                    "fc": r["M2"]["false_chuckle"]["rate"]}
        return fn

    if "E" in want:
        h0 = host_state()
        model = arms.FrameMLP()
        stats = arms.train_bc(model, train, window=1, warmup=0, batch=8192, steps=4000,
                              lr=2e-3, seed=args.seed, budget_s=6 * 60,
                              eval_fn=make_eval_fn("E"), eval_every=500, tag="E" + sfx,
                              weights=weights)
        model.load_state_dict(torch.load(CKPT / f"arm_E{sfx}.pt"))
        lat = {"gpu": arms.latency_ms(model, dev, device="cuda"),
               "cpu1": arms.latency_ms(model, dev, device="cpu", threads=1),
               "host_before": h0, "host_after": host_state()}
        model.to("cuda")
        record("E" + sfx, arms.predict_mlp(model, dev), arms.predict_mlp(model, frozen),
               extra={"train": stats, "latency": lat,
                      "params": sum(p.numel() for p in model.parameters())})

    if "B" in want:
        h0 = host_state()
        model = arms.GRUPolicy()
        stats = arms.train_bc(model, train, window=288, warmup=32, batch=96, steps=100_000,
                              lr=1.5e-3, seed=args.seed, budget_s=args.budget_min * 60,
                              eval_fn=make_eval_fn("B"), eval_every=300, tag="B" + sfx,
                              weights=weights)
        model.load_state_dict(torch.load(CKPT / f"arm_B{sfx}.pt"))
        lat = {"gpu": arms.latency_ms(model, dev, device="cuda"),
               "cpu1": arms.latency_ms(model, dev, device="cpu", threads=1),
               "host_before": h0, "host_after": host_state()}
        model.to("cuda")
        record("B" + sfx, arms.predict_gru(model, dev, mode="argmax", seed=args.seed),
               arms.predict_gru(model, frozen, mode="argmax", seed=args.seed),
               extra={"train": stats, "latency": lat,
                      "params": sum(p.numel() for p in model.parameters())})
        masked = frozen.masked(ev.PRODUCT_UNAVAILABLE, "frozen_product_channels_only")
        results["B" + sfx]["A8_product_channels_only"] = ev.score(
            masked, arms.predict_gru(model, masked, mode="argmax", seed=args.seed))
        arms.log(ev.summarize("B[masked]", results["B" + sfx]["A8_product_channels_only"]), tag="run")
        res_path.write_text(json.dumps(results, indent=1))
        (OUT / f"results-B{sfx}.json").write_text(json.dumps(results["B" + sfx], indent=1))

    if "C" in want:
        h0 = host_state()
        model = arms.BehaviorFormer()
        stats = arms.train_bc(model, train, window=128, warmup=0, batch=256, steps=100_000,
                              lr=1e-3, seed=args.seed, budget_s=args.budget_min * 60,
                              eval_fn=make_eval_fn("C"), eval_every=400, tag="C" + sfx,
                              weights=weights)
        model.load_state_dict(torch.load(CKPT / f"arm_C{sfx}.pt"))
        lat = {"gpu": arms.latency_ms(model, dev, device="cuda"),
               "cpu1": arms.latency_ms(model, dev, device="cpu", threads=1),
               "host_before": h0, "host_after": host_state()}
        model.to("cuda")
        pf_dev = arms.predict_former(model, dev, mode="argmax", seed=args.seed)
        pf_frz = arms.predict_former(model, frozen, mode="argmax", seed=args.seed)
        record("C" + sfx, pf_dev, pf_frz,
               extra={"train": stats, "latency": lat,
                      "params": sum(p.numel() for p in model.parameters())})
        # A8.3 product-available-channels-only rescore (no retrain)
        masked = frozen.masked(ev.PRODUCT_UNAVAILABLE, "frozen_product_channels_only")
        pm = arms.predict_former(model, masked, mode="argmax", seed=args.seed)
        results["C" + sfx]["A8_product_channels_only"] = ev.score(masked, pm)
        arms.log(ev.summarize("C[masked]", results["C" + sfx]["A8_product_channels_only"]), tag="run")
        res_path.write_text(json.dumps(results, indent=1))
        (OUT / f"results-C{sfx}.json").write_text(json.dumps(results["C" + sfx], indent=1))

    if "D" in want:
        import arm_d

        arm_d.run(train, dev, frozen, frozen_parts, seed=args.seed,
                  budget_s=args.d_budget_min * 60, results=results,
                  res_path=res_path, out=OUT, host_state=host_state)

    results["meta"]["total_wall_s"] = round(time.time() - t_all, 1)
    results["meta"]["host_at_end"] = host_state()
    res_path.write_text(json.dumps(results, indent=1))
    arms.log(f"done in {results['meta']['total_wall_s']}s", tag="run")


if __name__ == "__main__":
    main()
