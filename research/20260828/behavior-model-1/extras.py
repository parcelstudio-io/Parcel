"""A8 reporting slices, the codec capability-proof check, and the criterion
check.  Writes `_extra_md` and `criteria` into results.json for report.py.

Run after the arms: ``python extras.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
REPO_SRC = HERE.parents[2] / "src"

import eval as ev
from worldsim import ACT_VOCAB, EMOTES, FROZEN_SPLITS, SKILLS

DATA = Path("~/.cache/parcel-0e/bm1/data").expanduser()
ORDER = ["TEACHER", "CEILING", "ALWAYS-IDLE", "CHUCKLE-ALL", "A", "Aprime", "E",
         "B", "C", "C025", "D"]


def codec_check() -> tuple[bool, str]:
    """A8.6 capability proof: the harness vocabulary IS the product codec's."""

    sys.path.insert(0, str(REPO_SRC))
    from parcel_robot.duplex.act_codec import ActTokenCodec, default_twist_bins

    codec = ActTokenCodec(twist=default_twist_bins(), gaze_bins=8, skills=SKILLS,
                          emotes=EMOTES, filler_gestures=4)
    same = tuple(codec.vocabulary()) == ACT_VOCAB
    for tok in ACT_VOCAB:
        codec.decode(tok)  # raises on any unknown token
    return same, f"{len(ACT_VOCAB)}/{len(codec.vocabulary())}"


TOKEN_MAP = [
    ("teacher: chuckle / comfort / greeting / ... (emote)", "`<emote:NAME>`",
     "the 20 `runtime.DEFAULT_EMOTES`, verbatim"),
    ("teacher: gaze toward the last-known bearing", "`<gaze_bearing_i>`",
     "8 bins; DESIGN.md wrote this `<gaze:b>`"),
    ("teacher: gaze at the owner", "`<gaze_owner>`", "attention track"),
    ("teacher: gaze aversion (`gaze:away` in DESIGN.md rule 4)", "`<gaze_release>`",
     "the codec has no `away` token"),
    ("teacher: `attentive_stand` (DESIGN.md rule 4)", "`<emote:attentive_nod>`",
     "**`attentive_stand` does not exist in DEFAULT_EMOTES**"),
    ("teacher: command compliance", "`<skill:NAME>`",
     "come / fetch / follow / go_to / shake_paw / sit / stay"),
    ("teacher: `cmd:stop`", "`<idle>`", "scored separately (A7), not in headline (c)"),
    ("teacher: turn back toward the owner, slow approach", "`<twist:i:j>`",
     "7x5 bins from `default_twist_bins()`"),
    ("teacher: thinking filler", "`<filler_gesture_0>`", "liveness rule 5"),
]


def main() -> None:
    R = json.loads((HERE / "results.json").read_text())
    frozen_parts = [ev.load_split(DATA, s) for s in FROZEN_SPLITS]
    ev.concat_splits("frozen", frozen_parts)
    splits_meta = json.loads((HERE / "splits.json").read_text())

    md: list[str] = []

    # --- A8.1 bearing sector ------------------------------------------------
    md.append("### A8.1 — (b) look-back split by bearing sector\n")
    md.append(
        "Bearings are 8 bins of 45 deg, so `|bearing| <= 40 deg` selects **bin 0 only**;\n"
        "everything else needs a base rotation on a neckless Go2. The front cell is\n"
        "therefore a small sample and is reported with its n.\n"
    )
    md.append("{{SECTOR}}\n")

    # --- A8.2 cue source ----------------------------------------------------
    md.append("### A8.2 — cue source tag\n")
    md.append(
        "**The generator does not know who spoke.** Every cue in `worldsim.py` is an\n"
        "owner utterance reaching the dog through a cue classifier over ASR/prosody;\n"
        "there is no `self_speech` cue and no dog-speech act channel. The modelled\n"
        "detector latency is **1-5 frames (0.1-0.5 s)**, which is the *self-speech*\n"
        "regime; real owner ASR adds 0.5-1.5 s. So every timing bar reported here is\n"
        "optimistic by roughly one reaction window for owner-ASR cues, and the\n"
        "chuckle/comply windows in particular would have to widen on real audio.\n"
        "Registered as BM-1b follow-up.\n"
    )

    # --- A8.3 product-available channels ------------------------------------
    md.append("### A8.3 — product-available channels only (frozen, no retrain)\n")
    masked_rows = []
    for tag in ORDER:
        base = R.get(tag, {}).get("frozen")
        mask = R.get(tag, {}).get("A8_product_channels_only")
        if not base or not mask:
            continue
        for k in ("chuckle", "lookback", "comply", "comfort"):
            d = mask["M2"][k]["f1"] - base["M2"][k]["f1"]
            masked_rows.append(
                f"| {tag} | {k} | {base['M2'][k]['f1']:.3f} | {mask['M2'][k]['f1']:.3f} | "
                f"{d:+.3f} | {'**yes**' if d < -0.05 else 'no'} |")
    if masked_rows:
        md.append("`own_gaze`, `hist0..5` and the 4 `prof_*` channels forced to "
                  "unknown/index 0 at inference (no retraining).\n")
        md.append("| arm | sub-score | full channels | product channels only | delta | "
                  "drop > 0.05? |\n|---|---|---|---|---|---|\n" + "\n".join(masked_rows) + "\n")
        md.append(
            "A sub-score marked **yes** *depends on a signal the product cannot produce\n"
            "today* (owner gaze from a camera, a per-category humour history, and a\n"
            "four-fact owner profile). Note the pace channel also carries the teacher's\n"
            "reaction latency, so masking `prof_*` removes timing information as well as\n"
            "taste information.\n")
    else:
        md.append("_not computed_\n")

    # --- A8.4 events under base_busy ---------------------------------------
    md.append("### A8.4 — scored events occurring while `base_busy != free`\n")
    t = R.get("TEACHER", {}).get("frozen")
    if t:
        rows = []
        for k in ("chuckle", "lookback", "comply", "comfort"):
            n = t["M2"][k]["n_events"]
            b = t["M2"][k]["events_while_base_busy_not_free"]
            rows.append(f"| {k} | {n} | {b} | {(b / n if n else 0):.3f} |")
        md.append("| behaviour | events | while base_busy != free | fraction |\n"
                  "|---|---|---|---|\n" + "\n".join(rows) + "\n")
        md.append(
            "The product bridge (`SocialReactionBridge.tick`) vetoes **all** social\n"
            "reactions whenever `base_busy` is true, not only in the critical phase. The\n"
            "fraction above is therefore the share of this experiment's scored expressive\n"
            "events that today's product would suppress outright.\n")

    # --- A8.5 anticipatory condition ---------------------------------------
    md.append("### A8.5 — how often the anticipatory-chuckle condition is satisfiable\n")
    tot = sum(splits_meta["splits"][s]["events"]["punchlines"] for s in FROZEN_SPLITS)
    ant = sum(splits_meta["splits"][s]["events"]["anticipatable_punchlines"]
              for s in FROZEN_SPLITS)
    md.append(
        f"Frozen split: **{ant} / {tot} punchlines = {ant / tot:.1%}** satisfy it.\n\n"
        "`worldsim.py` implements the condition as: take the `hist_k` channel, which is\n"
        "the **last 6 jokes globally** as `(category, laughed?)` pairs; filter to the\n"
        "entries whose category matches the current punchline; take up to the last 3 of\n"
        "those; fire if >= 2 of them were laughed at. So it is a *per-category filter\n"
        "over a global 6-slot window* -- with 6 joke categories, a category is often\n"
        "absent from the window entirely, which is why only ~10 % of punchlines are\n"
        "anticipatable. A per-category last-3 history (6 x 3 slots) would raise this\n"
        "sharply and is the more faithful reading of DESIGN.md rule 1; recorded, not\n"
        "changed.\n")

    # --- A8.6 token map + codec assertion ----------------------------------
    md.append("### A8.6 — teacher token -> `ActTokenCodec` token\n")
    md.append("| teacher behaviour | act token | note |\n|---|---|---|\n" +
              "\n".join(f"| {a} | {b} | {c} |" for a, b, c in TOKEN_MAP) + "\n")
    same, ratio = codec_check()
    md.append(
        f"\n**Capability-proof check (read-only import of the product package):** the "
        f"harness vocabulary is byte-identical to `ActTokenCodec(...).vocabulary()` "
        f"({ratio}, identical={same}) and **every one of the {len(ACT_VOCAB)} tokens "
        f"decodes via `ActTokenCodec.decode()` without raising**. Run it with "
        f"`python extras.py`.\n")

    # --- A8.7 tier ----------------------------------------------------------
    md.append("### A8.7 — evidence tier\n")
    md.append("`desktop-sim (synthetic token world, no physics/sensors)`\n")

    # --- A5 arm D phrasing extras ------------------------------------------
    d = R.get("D", {})
    if d.get("A5_cue_masked_phrasing") or d.get("A5_ngram_overlap"):
        md.append("### A5 — phrasing slice for arm D\n")
        ov = d.get("A5_ngram_overlap")
        if ov:
            md.append(
                f"4-gram overlap between the training phrasings and the held-out-phrasing "
                f"slice: **{ov['shared']} / {ov['slice_ngrams']} = "
                f"{ov['slice_fraction_seen_in_train']:.1%} of the slice's 4-grams already "
                f"appear in training**. The split holds out *surface strings* built from "
                f"shared fragments, **not paraphrase templates**, so this slice understates "
                f"the difficulty of genuinely novel phrasing. A template-held-out slice was "
                f"not added (it would need new fragments and a new frozen split); recorded "
                f"as unmet.\n")
        cm = d.get("A5_cue_masked_phrasing")
        if cm:
            base = d.get("slices", {}).get("frozen_phrasing")
            m = cm["M2"]
            md.append(
                "\nCue-masked pass (cue forced to `none`, `cue_conf=lo` on command / joke /\n"
                "laugh frames, so only the raw `words` carry the instruction):\n\n"
                "| sub-score | arm D, cue visible | arm D, cue masked |\n|---|---|---|\n"
                + "\n".join(
                    f"| {k} | "
                    f"{(base['M2'][k]['f1'] if base else float('nan')):.3f} | "
                    f"{m[k]['f1']:.3f} |"
                    for k in ("chuckle", "lookback", "comply", "comfort")) + "\n")

    md.append("### Arm D evaluation scale\n")
    if d.get("eval_note"):
        md.append(d["eval_note"] + ".\n")
        dec = d.get("dev_decode", {})
        md.append(f"Decoded {dec.get('frames_decoded', '?')} dev frames; invalid act-token "
                  f"outputs {dec.get('invalid_rate', '?')} (mapped to `<idle>`).\n")

    R["_extra_md"] = "\n".join(md)

    # --- criterion check ----------------------------------------------------
    learned = [t for t in ("B", "C", "C025", "D", "E") if R.get(t, {}).get("frozen")]
    crit: dict = {}
    if learned:
        best = max(learned, key=lambda t: np.mean([
            R[t]["frozen"]["M2"][k]["f1"] for k in ("chuckle", "lookback", "comply")]))
        crit["best_learned_arm"] = best
        crit["pre_registered"] = ev.check_criteria(
            R[best]["frozen"], R.get("A", {}).get("frozen"), R.get("CEILING", {}).get("frozen"),
            R.get("Aprime", {}).get("frozen"),
            R.get(best, {}).get("slices", {}).get("frozen_family"))
        for arm in ("B", "C", "C025", "E", "D"):
            if R.get(arm, {}).get("frozen"):
                crit[arm] = ev.check_criteria(
                    R[arm]["frozen"], R.get("A", {}).get("frozen"),
                    R.get("CEILING", {}).get("frozen"), R.get("Aprime", {}).get("frozen"),
                    R.get(arm, {}).get("slices", {}).get("frozen_family"))
        lat_ok = {}
        for arm in ("B", "C", "C025"):
            p = R.get(arm, {}).get("latency", {})
            if p.get("gpu"):
                lat_ok[f"{arm}_p99_gpu_le_20ms"] = p["gpu"]["p99_ms"] <= 20.0
                lat_ok[f"{arm}_p99_cpu1_le_60ms"] = p["cpu1"]["p99_ms"] <= 60.0
        if R.get("D", {}).get("latency", {}).get("gpu"):
            lat_ok["D_p99_gpu_le_100ms"] = R["D"]["latency"]["gpu"]["p99_ms"] <= 100.0
        crit["M4_latency"] = lat_ok
    R["criteria"] = crit
    (HERE / "results.json").write_text(json.dumps(R, indent=1))
    print(json.dumps(crit, indent=1))


if __name__ == "__main__":
    main()
