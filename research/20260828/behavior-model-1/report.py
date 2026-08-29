"""Regenerate RESULTS.md from results.json.  Idempotent; run after every arm."""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDER = ["TEACHER", "CEILING", "ALWAYS-IDLE", "CHUCKLE-ALL", "A", "Aprime", "E",
         "B", "C", "C025", "D"]
LABEL = {
    "TEACHER": "TEACHER (upper bound)",
    "CEILING": "CEILING A1 (teacher on the observed cue stream)",
    "ALWAYS-IDLE": "ref ALWAYS-IDLE",
    "CHUCKLE-ALL": "ref CHUCKLE-AT-EVERY-PUNCHLINE",
    "A": "A rule baseline (arbiter)",
    "Aprime": "A' reflex table (A2)",
    "E": "E frame MLP (A2)",
    "B": "B GRU 2x256",
    "C": "C BehaviorFormer (CE alpha=0.5)",
    "C025": "C BehaviorFormer (CE alpha=0.25, dev-chosen)",
    "D": "D LoRA Qwen2.5-0.5B",
}
SLICES = ["frozen_core", "frozen_family", "frozen_profile", "frozen_phrasing"]


def g(d, *path, default=None):
    for p in path:
        if not isinstance(d, dict) or p not in d:
            return default
        d = d[p]
    return d


def main_table(R: dict, split: str, key: str = "M2") -> str:
    out = [
        ("| arm | M1 acc | (a) chuckle F1 | (b) look-back F1 | (c) comply F1 | "
        "(d) comfort F1 | false-chuckle | M3 raw | stop-comply |"),
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for tag in ORDER:
        r = g(R, tag, split)
        if not r:
            continue
        m = r[key]
        out.append(
            f"| {LABEL[tag]} | {r['M1']['frame_accuracy']:.4f} | {m['chuckle']['f1']:.3f} | "
            f"{m['lookback']['f1']:.3f} | {m['comply']['f1']:.3f} | {m['comfort']['f1']:.3f} | "
            f"{m['false_chuckle']['rate']:.3f} | {r['M3']['raw_violation_rate']:.5f} | "
            f"{r['A7_stop_compliance']['rate']:.3f} |"
        )
    return "\n".join(out)


def counts_table(R: dict, split: str) -> str:
    r = g(R, "TEACHER", split)
    if not r:
        return "_(not run)_"
    m = r["M2"]
    return (
        "| behaviour | events | detected-cue anchors (A1) |\n|---|---|---|\n"
        + "\n".join(
            f"| {b} | {m[b]['n_events']} | "
            f"{g(R, 'TEACHER', split, 'M2_amended_detected_only', b, 'n_events', default='-')} |"
            for b in ("chuckle", "lookback", "comply", "comfort")
        )
        + f"\n| non-funny punchlines | {m['false_chuckle']['n_nonfunny_punchlines']} | - |"
        + f"\n| cmd:stop cues | {r['A7_stop_compliance']['n_stop_cues']} | - |"
    )


def slice_table(R: dict, metric: str) -> str:
    key = {"a": "chuckle", "b": "lookback", "c": "comply", "d": "comfort"}[metric]
    out = ["| arm | " + " | ".join(SLICES) + " | pooled frozen |",
           "|---|" + "---|" * (len(SLICES) + 1)]
    for tag in ORDER:
        if not g(R, tag, "frozen"):
            continue
        cells = []
        for s in SLICES:
            v = g(R, tag, "slices", s, "M2", key, "f1")
            n = g(R, tag, "slices", s, "M2", key, "n_events")
            cells.append("n/a" if v is None else (f"{v:.3f} (n={n})" if n else "n/a (n=0)"))
        pooled = g(R, tag, "frozen", "M2", key, "f1")
        out.append(f"| {LABEL[tag]} | " + " | ".join(cells) +
                   f" | {pooled:.3f} |")
    return "\n".join(out)


def latency_table(R: dict) -> str:
    out = ["| arm | GPU p50 / p99 (ms) | CPU 1-thread p50 / p99 (ms) | n | bar |",
           "|---|---|---|---|---|"]
    bars = {"B": "p99 GPU <= 20 ms, CPU <= 60 ms", "C": "p99 GPU <= 20 ms, CPU <= 60 ms",
            "C025": "p99 GPU <= 20 ms, CPU <= 60 ms",
            "D": "p99 GPU <= 100 ms", "A": "(no bar)", "E": "(no bar)"}
    for tag in ("A", "Aprime", "E", "B", "C", "C025", "D"):
        lat = g(R, tag, "latency")
        if not lat:
            continue
        gpu, cpu = lat.get("gpu"), lat.get("cpu1")
        gs = f"{gpu['p50_ms']:.2f} / {gpu['p99_ms']:.2f}" if gpu else "n/a"
        cs = f"{cpu['p50_ms']:.3f} / {cpu['p99_ms']:.3f}" if cpu else "n/a"
        n = (gpu or cpu or {}).get("n", "-")
        out.append(f"| {LABEL[tag]} | {gs} | {cs} | {n} | {bars.get(tag, '')} |")
    return "\n".join(out)


def safety_table(R: dict) -> str:
    out = [("| arm | crit frames | M3 raw (emote/skill under critical) | "
           "A7 twist under busy/critical | A7 non-idle after cmd:stop | "
           "locomotion-skill rate free / busy / critical |"),
           "|---|---|---|---|---|---|"]
    for tag in ORDER:
        r = g(R, tag, "frozen")
        if not r:
            continue
        m3 = r["M3"]
        bs = m3["by_base_busy"]
        out.append(
            f"| {LABEL[tag]} | {m3['critical_frames']} | "
            f"{m3['raw_violations_emote_or_skill_under_critical']} "
            f"({m3['raw_violation_rate']:.5f}) | "
            f"{m3['A7_raw_twist_under_busy_or_critical']} ({m3['A7_raw_twist_rate']:.5f}) | "
            f"{m3['A7_raw_nonidle_after_stop_cue']}/{m3['A7_stop_cues']} | "
            f"{bs['free']['locomotion_skill_rate']:.5f} / "
            f"{bs['busy']['locomotion_skill_rate']:.5f} / "
            f"{bs['critical']['locomotion_skill_rate']:.5f} |"
        )
    return "\n".join(out)


def antic_table(R: dict) -> str:
    out = ["| arm | anticipatory-chuckle F1 (frozen) | on held-out-family slice |",
           "|---|---|---|"]
    for tag in ORDER:
        v = g(R, tag, "frozen", "A2_anticipatory_chuckle")
        if not v:
            continue
        hf = g(R, tag, "slices", "frozen_family", "A2_anticipatory_chuckle", "f1")
        out.append(f"| {LABEL[tag]} | {v['f1']:.3f} (n={v['n_anticipatable_punchlines']}) | "
                   f"{'n/a' if hf is None else f'{hf:.3f}'} |")
    return "\n".join(out)


def sector_table(R: dict) -> str:
    out = ["| arm | front (bearing bin 0) | rear / side (bins 1-7) |", "|---|---|---|"]
    for tag in ORDER:
        v = g(R, tag, "frozen", "A8_lookback_by_sector")
        if not v:
            continue
        out.append(
            f"| {LABEL[tag]} | {v['front_bin0']['f1']:.3f} (n={v['front_bin0']['n_events']}) | "
            f"{v['rear_or_side']['f1']:.3f} (n={v['rear_or_side']['n_events']}) |")
    return "\n".join(out)


def training_table(R: dict) -> str:
    out = [("| arm | steps | frames/step | epoch-equivalents | wall (s) | stopped by | "
           "final loss | GPU peak (MB) | params |"), "|---|---|---|---|---|---|---|---|---|"]
    for tag in ("E", "B", "C", "C025", "D"):
        t = g(R, tag, "train")
        if not t:
            continue
        out.append(
            f"| {LABEL[tag]} | {t.get('steps_run', '-')} | {t.get('frames_per_step', t.get('batch', '-'))} | "
            f"{t.get('epochs_equivalent', round(t.get('examples_seen', 0) / 3619357, 4))} | "
            f"{t.get('wall_s', '-')} | {t.get('stopped', 'budget')} | "
            f"{t.get('final_loss', '-')} | {t.get('gpu_peak_mb', '-')} | "
            f"{g(R, tag, 'params', default=t.get('lora_trainable_params', '-'))} |")
    return "\n".join(out)


def _trim_meta(m: dict) -> dict:
    m = json.loads(json.dumps(m))
    for k in ("host_at_end",):
        if k in m and isinstance(m[k], dict):
            procs = m[k].get("gpu_processes", "")
            m[k]["gpu_processes"] = "; ".join(
                ln.split(",")[0] + " " + ln.split(",")[-1].strip()
                for ln in str(procs).split("\n") if ln.strip())
    return m


def main() -> None:
    R = json.loads((HERE / "results.json").read_text())
    tpl = (HERE / "_results_template.md").read_text()
    body = tpl
    subs = {
        "{{TABLE_DEV}}": main_table(R, "dev"),
        "{{TABLE_FROZEN}}": main_table(R, "frozen"),
        "{{TABLE_FROZEN_AMENDED}}": main_table(R, "frozen", "M2_amended_detected_only"),
        "{{COUNTS_FROZEN}}": counts_table(R, "frozen"),
        "{{SLICE_A}}": slice_table(R, "a"),
        "{{SLICE_B}}": slice_table(R, "b"),
        "{{SLICE_C}}": slice_table(R, "c"),
        "{{SLICE_D}}": slice_table(R, "d"),
        "{{LATENCY}}": latency_table(R),
        "{{SAFETY}}": safety_table(R),
        "{{ANTIC}}": antic_table(R),
        "{{SECTOR}}": sector_table(R),
        "{{TRAINING}}": training_table(R),
        "{{CRITERIA}}": json.dumps(R.get("criteria", {}), indent=1),
        "{{META}}": json.dumps(_trim_meta(R.get("meta", {})), indent=1),
        "{{EXTRA}}": R.get("_extra_md", ""),
    }
    for _ in range(2):  # EXTRA itself contains placeholders
        for k, v in subs.items():
            body = body.replace(k, v)
    (HERE / "RESULTS.md").write_text(body)
    print("wrote RESULTS.md")


if __name__ == "__main__":
    main()
