"""HS1b — does a local instruct LM carry a funniness prior without hearing a laugh?

Pre-registered (DESIGN.md): 100 LLM ratings of the Jester jokes, temperature 0,
fixed prompt, one call per joke, repeated with 2 prompt paraphrases; Spearman and
Pearson vs the Jester mean rating, bootstrap 95 % CI over the 100 jokes.
Bar: rho >= 0.40; refuted below 0.25.

AMENDMENTS.md (binding, POST-START) applied here:
  H6  verbatim-completion memorisation probe (first 40 % of each joke, exact
      continuation of >= 8 consecutive words) reported beside rho; verdict bands
      recorded; named consumer = FL-1's per-category Beta prior initialisation
      and dog-told joke selection.
  H7  evidence tier = `replay` (public corpus through a local model).

Also tags the 100 jokes into 6 coarse categories with the same local model, for
`owner_taste_prior.json` (a DERIVED artifact, clearly labelled).
"""
from __future__ import annotations

import json
import re
import string
import time

import numpy as np
from hs_common import HERE, SEED, merge_results

MODEL_7B = "Qwen/Qwen2.5-7B-Instruct"
MODEL_3B = "Qwen/Qwen2.5-3B-Instruct"
GPU_BUDGET_FULL_GB = 20.0   # >= this free -> may use up to 18 GB (7B)
MAX_NEW_RATING = 8

PROMPT_A = (
    "You are rating jokes for how funny an average adult reader would find them.\n\n"
    "Joke:\n\"\"\"\n{joke}\n\"\"\"\n\n"
    "Rate this joke on a scale from -10 to +10, where -10 means \"not funny at all\" "
    "and +10 means \"extremely funny\". Reply with only the number."
)
PROMPT_B = (
    "Below is a joke. Estimate the average funniness rating that a large group of "
    "ordinary people would give it.\n\n{joke}\n\n"
    "The scale runs from -10 (they disliked it strongly) to +10 (they found it "
    "hilarious). Output just the numeric rating and nothing else."
)
PROMPT_COMPLETE = (
    "Continue this joke exactly as it is usually told. Output only the continuation.\n\n"
    "{stub}"
)
CATEGORIES = [
    "wordplay_or_pun",
    "sex_or_relationships",
    "religion_or_clergy",
    "politics_or_current_affairs",
    "professions_or_workplace",
    "absurd_dark_or_other",
]
PROMPT_CATEGORY = (
    "Classify the joke below into exactly one of these categories:\n"
    + "\n".join(f"- {c}" for c in CATEGORIES)
    + "\n\nJoke:\n\"\"\"\n{joke}\n\"\"\"\n\n"
    "Reply with only the category name."
)


def pick_model() -> tuple[str, str]:
    import torch

    free_gb = torch.cuda.mem_get_info()[0] / 1e9 if torch.cuda.is_available() else 0.0
    if free_gb >= GPU_BUDGET_FULL_GB:
        return MODEL_7B, (f"{free_gb:.1f} GB free >= {GPU_BUDGET_FULL_GB} GB, so the "
                          f"7-8B step was allowed up to 18 GB")
    return MODEL_3B, (f"only {free_gb:.1f} GB free (< {GPU_BUDGET_FULL_GB} GB) at model "
                      f"selection time, so the 3B fallback was used per the GPU cap")


def _disable_triton_native_ops() -> str | None:
    """This host has no Python 3.14 dev headers, so Triton cannot build its CUDA
    utils module and torch 2.13's native-op router explodes inside Qwen's RoPE.
    Deregister the Triton-backed overrides through torch's own supported hook so
    every op falls back to the stock CUDA kernel. Numerics are the reference
    kernels; only the fused fast path is given up."""
    try:
        from torch._native import registry, triton_utils

        registry.deregister_op_overrides(disable_dsl_names=triton_utils._TRITON_DSL_NAME)
        return ("torch._native Triton overrides deregistered (no python3.14 dev "
                "headers on this host, so Triton cannot JIT); stock CUDA kernels used")
    except Exception as e:  # pragma: no cover - best effort  # noqa: BLE001
        return f"could not deregister Triton overrides: {e!r}"


def _load(model_id):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_id, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(
        model_id, dtype=torch.bfloat16, device_map="cuda")
    model.eval()
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    return tok, model


def _generate(tok, model, prompts, max_new_tokens, batch=8):
    """Greedy (temperature 0) chat completion for a list of user prompts."""
    import torch

    outs = []
    for i in range(0, len(prompts), batch):
        chunk = prompts[i : i + batch]
        texts = [tok.apply_chat_template([{"role": "user", "content": p}],
                                         tokenize=False, add_generation_prompt=True)
                 for p in chunk]
        enc = tok(texts, return_tensors="pt", padding=True).to(model.device)
        with torch.inference_mode():
            gen = model.generate(**enc, max_new_tokens=max_new_tokens, do_sample=False,
                                 temperature=None, top_p=None, top_k=None,
                                 pad_token_id=tok.pad_token_id)
        for j in range(len(chunk)):
            outs.append(tok.decode(gen[j][enc["input_ids"].shape[1]:],
                                   skip_special_tokens=True).strip())
    return outs


_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_rating(text: str):
    m = _NUM.search(text.replace("−", "-"))
    if not m:
        return None
    return float(np.clip(float(m.group()), -10.0, 10.0))


def _words(s: str):
    tbl = str.maketrans("", "", string.punctuation + "“”‘’")
    return [w for w in s.lower().translate(tbl).split() if w]


def longest_common_run(a: list[str], b: list[str]) -> int:
    """Longest contiguous shared word run (classic DP, O(len(a)*len(b)))."""
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
        prev = cur
    return best


def bootstrap_corr(x, y, kind, n_boot=2000, seed=SEED):
    from scipy.stats import pearsonr, spearmanr

    f = spearmanr if kind == "spearman" else pearsonr
    x, y = np.asarray(x, float), np.asarray(y, float)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(x), len(x))
        if len(np.unique(x[idx])) < 2 or len(np.unique(y[idx])) < 2:
            continue
        vals.append(f(x[idx], y[idx])[0])
    v = np.sort(np.asarray(vals))
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))


def _corr_block(pred, truth, name):
    from scipy.stats import pearsonr, spearmanr

    ok = np.isfinite(pred)
    p, t = np.asarray(pred)[ok], np.asarray(truth)[ok]
    sr, sp = spearmanr(p, t)
    pr, pp = pearsonr(p, t)
    slo, shi = bootstrap_corr(p, t, "spearman")
    plo, phi = bootstrap_corr(p, t, "pearson")
    blk = {
        "name": name, "n_jokes_used": int(ok.sum()), "n_unparsed": int((~ok).sum()),
        "spearman": float(sr), "spearman_p": float(sp), "spearman_ci95": [slo, shi],
        "pearson": float(pr), "pearson_p": float(pp), "pearson_ci95": [plo, phi],
        "pred_min": float(p.min()), "pred_max": float(p.max()),
        "pred_mean": float(p.mean()), "pred_n_distinct": len(np.unique(p)),
    }
    print(f"[hs1b] {name}: Spearman={sr:.4f} CI=[{slo:.4f},{shi:.4f}]  "
          f"Pearson={pr:.4f} CI=[{plo:.4f},{phi:.4f}]  "
          f"(distinct predictions: {blk['pred_n_distinct']})", flush=True)
    return blk


def verdict_band(rho, lo, hi):
    """H6 bands. Descriptive only — Fable writes VERDICT.md."""
    if rho >= 0.40 and lo >= 0.25:
        return "point rho >= 0.40 AND bootstrap lower bound >= 0.25 (H6 CONFIRMED band)"
    if hi < 0.40:
        return "bootstrap upper bound < 0.40 (H6 REFUTED band)"
    return "neither band satisfied (H6 INCONCLUSIVE band)"


def run() -> dict:
    import jester_data

    t0 = time.time()
    jokes = jester_data.build_texts()
    _n_rated, R, _ = jester_data.build_matrix()
    O = np.isfinite(R)
    jester_mean = np.array([R[O[:, j], j].mean() for j in range(R.shape[1])])
    print(f"[hs1b] {len(jokes)} jokes; Jester mean rating range "
          f"[{jester_mean.min():.2f}, {jester_mean.max():.2f}]", flush=True)

    model_id, why = pick_model()
    print(f"[hs1b] model: {model_id} -- {why}", flush=True)
    triton_note = _disable_triton_native_ops()
    print(f"[hs1b] {triton_note}", flush=True)
    tok, model = _load(model_id)
    n_params = int(sum(p.numel() for p in model.parameters()))

    # --- ratings, two paraphrases, temperature 0 ---------------------------
    raw_a = _generate(tok, model, [PROMPT_A.format(joke=j) for j in jokes], MAX_NEW_RATING)
    raw_b = _generate(tok, model, [PROMPT_B.format(joke=j) for j in jokes], MAX_NEW_RATING)
    pred_a = np.array([parse_rating(t) if parse_rating(t) is not None else np.nan
                       for t in raw_a])
    pred_b = np.array([parse_rating(t) if parse_rating(t) is not None else np.nan
                       for t in raw_b])
    pred_mean = np.nanmean(np.vstack([pred_a, pred_b]), axis=0)

    blocks = {
        "paraphrase_A": _corr_block(pred_a, jester_mean, "paraphrase_A"),
        "paraphrase_B": _corr_block(pred_b, jester_mean, "paraphrase_B"),
        "mean_of_paraphrases": _corr_block(pred_mean, jester_mean, "mean_of_paraphrases"),
    }
    from scipy.stats import pearsonr, spearmanr
    ok = np.isfinite(pred_a) & np.isfinite(pred_b)
    agree = {
        "spearman_between_paraphrases": float(spearmanr(pred_a[ok], pred_b[ok])[0]),
        "pearson_between_paraphrases": float(pearsonr(pred_a[ok], pred_b[ok])[0]),
        "mean_abs_diff": float(np.abs(pred_a[ok] - pred_b[ok]).mean()),
    }
    print(f"[hs1b] paraphrase agreement: Spearman={agree['spearman_between_paraphrases']:.4f}",
          flush=True)

    # --- H6 verbatim-completion memorisation probe -------------------------
    stubs, tails = [], []
    for j in jokes:
        w = j.split()
        cut = max(1, round(0.40 * len(w)))
        stubs.append(" ".join(w[:cut]))
        tails.append(" ".join(w[cut:]))
    comps = _generate(tok, model, [PROMPT_COMPLETE.format(stub=s) for s in stubs],
                      max_new_tokens=160, batch=8)
    runs = [longest_common_run(_words(c), _words(t)) for c, t in zip(comps, tails)]
    runs = np.asarray(runs)
    mem = {
        "probe": "first 40 % of each joke given; longest contiguous word run shared "
                 "with the true continuation (punctuation/case stripped)",
        "threshold_words": 8,
        "exact_continuation_rate": float((runs >= 8).mean()),
        "n_jokes_at_or_above_8": int((runs >= 8).sum()),
        "longest_run_median": float(np.median(runs)),
        "longest_run_mean": float(runs.mean()),
        "longest_run_max": int(runs.max()),
        "longest_run_p90": float(np.percentile(runs, 90)),
        "per_joke_longest_run": [int(v) for v in runs],
    }
    print(f"[hs1b] H6 memorisation: exact-continuation rate "
          f"{mem['exact_continuation_rate']:.2%} ({mem['n_jokes_at_or_above_8']}/100), "
          f"median run {mem['longest_run_median']:.1f} words, max {mem['longest_run_max']}",
          flush=True)

    # --- 6-category tagging for the FL-1 prior -----------------------------
    cat_raw = _generate(tok, model, [PROMPT_CATEGORY.format(joke=j) for j in jokes],
                        max_new_tokens=12, batch=8)
    cats = []
    for t in cat_raw:
        low = t.strip().lower()
        hit = next((c for c in CATEGORIES if c in low), None)
        if hit is None:
            hit = next((c for c in CATEGORIES
                        if c.split("_")[0] in low), CATEGORIES[-1])
        cats.append(hit)
    from collections import Counter
    cat_counts = dict(Counter(cats))
    print(f"[hs1b] joke categories: {cat_counts}", flush=True)

    mp = blocks["mean_of_paraphrases"]
    out = {
        "evidence_tier": "replay",
        "amendments_applied": ["H6", "H7"],
        "model": model_id,
        "model_params": n_params,
        "model_selection_note": why,
        "host_workaround": triton_note,
        "decoding": "greedy, do_sample=False (temperature 0), one call per joke",
        "prompts": {"paraphrase_A": PROMPT_A, "paraphrase_B": PROMPT_B,
                    "completion_probe": PROMPT_COMPLETE, "category": PROMPT_CATEGORY},
        "n_jokes": len(jokes),
        "jester_mean_rating": [round(float(v), 4) for v in jester_mean],
        "llm_rating_paraphrase_A": [None if not np.isfinite(v) else float(v) for v in pred_a],
        "llm_rating_paraphrase_B": [None if not np.isfinite(v) else float(v) for v in pred_b],
        "llm_rating_mean": [float(v) for v in pred_mean],
        "correlations": blocks,
        "paraphrase_agreement": agree,
        "memorisation_probe": mem,
        "joke_categories": {"categories": CATEGORIES, "counts": cat_counts,
                            "per_joke": cats,
                            "status": "DERIVED artifact, tagged by the local model above"},
        "h6_verdict_band_mean_of_paraphrases": verdict_band(
            mp["spearman"], mp["spearman_ci95"][0], mp["spearman_ci95"][1]),
        "named_consumer": "FL-1 per-category Beta prior initialisation and "
                          "dog-told joke selection",
        "seed": SEED,
        "wall_seconds": round(time.time() - t0, 1),
    }
    merge_results("hs1b", out)

    # fold the categories into the FL-1 prior artifact
    prior_path = HERE / "owner_taste_prior.json"
    if prior_path.exists():
        prior = json.loads(prior_path.read_text())
        prior["joke_categories"] = {
            "_derived": f"tagged by {model_id} (local, greedy); a convenience label, "
                        f"not a validated taxonomy",
            "categories": CATEGORIES, "per_joke": cats, "counts": cat_counts,
        }
        per_cat = {}
        for c in CATEGORIES:
            idx = [i for i, x in enumerate(cats) if x == c]
            if idx:
                per_cat[c] = {
                    "n_jokes": len(idx),
                    "joke_indices_1based": [i + 1 for i in idx],
                    "jester_mean_rating": round(float(jester_mean[idx].mean()), 4),
                    "cluster_mean_rating": {
                        str(cl["cluster_id"]): round(
                            float(np.mean([cl["mean_rating_per_joke"][i] for i in idx])), 4)
                        for cl in prior["clusters"]},
                }
        prior["per_category"] = per_cat
        prior_path.write_text(json.dumps(prior, indent=2) + "\n")
        print("[hs1b] folded categories into owner_taste_prior.json", flush=True)
    return out


if __name__ == "__main__":
    r = run()
    print(json.dumps({k: v for k, v in r.items()
                      if k not in ("jester_mean_rating", "llm_rating_paraphrase_A",
                                   "llm_rating_paraphrase_B", "llm_rating_mean",
                                   "prompts")}, indent=2)[:4000])
