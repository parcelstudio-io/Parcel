"""HS1a — is human laughter separable from other sound the dog will actually
hear, by an off-the-shelf local AudioSet classifier, fast enough to run live?

Pre-registered (DESIGN.md): per-clip max laughter logit -> AUROC, AUPRC,
accuracy at the Youden threshold; per-window latency p50/p99 GPU and 1-thread
CPU; model params. Bar: AUROC >= 0.95, <= 100 ms/window GPU, <= 500 ms CPU.

AMENDMENTS.md (binding, POST-START) applied here:
  H1  laughter score = MAX over the six AudioSet laughter-family labels
      (ids recorded); the single `Laughter` label is also reported.
  H2  negative slices added: LibriSpeech read SPEECH (100) and the product's
      OWN Piper TTS (50). Amended verdict rides on ESC-50 AUROC >= 0.95 AND
      the speech-slice bootstrap lower bound >= 0.90. ESC-50-only = upper bound.
  H3  operating threshold chosen on ESC-50 folds 1-4, reported on fold 5;
      written to results.json under `operating_point` for FL-1.
  H4  streaming onset latency: 1-s window, 250 ms hop, energy-annotated laugh
      onset, time-to-first-detection p50/p95, false triggers per minute on the
      concatenated negative stream.
  H7  evidence tier = `replay`.
"""
from __future__ import annotations

import csv
import json
import time

import negatives
import numpy as np
from hs_common import ESC50_ROOT, NEG_CLASSES, POS_CLASS, SEED, merge_results

MODEL_ID = "MIT/ast-finetuned-audioset-10-10-0.4593"
TARGET_SR = 16000
WINDOW_S = 1.0
HOP_S = 0.25  # H4: 250 ms hop, used for scoring and streaming alike
CACHE = None  # set in run()

LAUGH_PRIMARY = "Laughter"
# H1 — the fixed label set.
LAUGH_FAMILY = ["Laughter", "Giggle", "Snicker", "Belly laugh",
                "Chuckle, chortle", "Baby laughter"]

SLICE_ESC50 = "esc50_human_nonspeech"
SLICE_SPEECH = "speech_librispeech"
SLICE_TTS = "own_piper_tts"


# ---------------------------------------------------------------- inventory
def _esc50_rows():
    rows = list(csv.DictReader(open(ESC50_ROOT / "meta" / "esc50.csv")))  # noqa: SIM115
    keep = [r for r in rows if r["category"] == POS_CLASS or r["category"] in NEG_CLASSES]
    keep.sort(key=lambda r: r["filename"])
    return keep


def build_inventory() -> list[dict]:
    """Every clip scored in this experiment, with its slice and fold."""
    inv = []
    for r in _esc50_rows():
        inv.append({
            "id": f"esc50/{r['filename']}",
            "kind": "file",
            "path": str(ESC50_ROOT / "audio" / r["filename"]),
            "label": 1 if r["category"] == POS_CLASS else 0,
            "category": r["category"],
            "slice": "esc50_laughing" if r["category"] == POS_CLASS else SLICE_ESC50,
            "fold": int(r["fold"]),
        })
    for p in negatives.speech_clips():
        inv.append({"id": f"librispeech/{p.name}", "kind": "file", "path": str(p),
                    "label": 0, "category": "read_speech", "slice": SLICE_SPEECH,
                    "fold": 0})
    for i, e in enumerate(negatives.build_tts()):
        inv.append({"id": f"piper_tts/{i:03d}", "kind": "tts", "path": e["path"],
                    "label": 0, "category": "own_tts", "slice": SLICE_TTS, "fold": 0,
                    "tts": e})
    return inv


def _load(entry: dict) -> np.ndarray:
    import librosa

    if entry["kind"] == "tts":
        return negatives.load_tts_wave(entry["tts"], TARGET_SR)
    y, _ = librosa.load(entry["path"], sr=TARGET_SR, mono=True)
    return y.astype(np.float32)


def _windows(wave: np.ndarray, sr: int = TARGET_SR):
    win, hop = int(WINDOW_S * sr), int(HOP_S * sr)
    if len(wave) < win:
        wave = np.pad(wave, (0, win - len(wave)))
    starts = list(range(0, len(wave) - win + 1, hop))
    return np.stack([wave[s : s + win] for s in starts]), np.array(starts) / sr


# ------------------------------------------------------------------ scoring
def score_all(inv, model, fe, dev, batch: int = 16):
    """Per-window laughter-family logits for every clip. Cached to npz."""
    import torch

    fam_scores, single_scores, starts_all = [], [], []
    with torch.inference_mode():
        for i, e in enumerate(inv):
            wave = _load(e)
            wins, starts = _windows(wave)
            fam_w, sing_w = [], []
            for b in range(0, len(wins), batch):
                feats = fe(list(wins[b : b + batch]), sampling_rate=TARGET_SR,
                           return_tensors="pt")
                lg = model(input_values=feats["input_values"].to(dev)).logits.float().cpu().numpy()
                fam_w.append(lg[:, CACHE["family_idx"]].max(axis=1))
                sing_w.append(lg[:, CACHE["primary_idx"]])
            fam_scores.append(np.concatenate(fam_w))
            single_scores.append(np.concatenate(sing_w))
            starts_all.append(starts)
            if (i + 1) % 100 == 0:
                print(f"[hs1a]   scored {i+1}/{len(inv)} clips", flush=True)
    return fam_scores, single_scores, starts_all


# ------------------------------------------------------------------ metrics
def _auroc(scores, labels):
    from sklearn.metrics import roc_auc_score

    return float(roc_auc_score(labels, scores))


def _boot_auroc_ci(scores, labels, n_boot=2000, seed=SEED):
    """Stratified bootstrap over CLIPS (resample positives and negatives)."""
    from sklearn.metrics import roc_auc_score

    scores, labels = np.asarray(scores, float), np.asarray(labels, int)
    pos, neg = np.where(labels == 1)[0], np.where(labels == 0)[0]
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        idx = np.concatenate([rng.choice(pos, len(pos), replace=True),
                              rng.choice(neg, len(neg), replace=True)])
        vals.append(roc_auc_score(labels[idx], scores[idx]))
    v = np.sort(np.asarray(vals))
    return float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5)), float(np.mean(v))


def _full_metrics(scores, labels):
    from sklearn.metrics import average_precision_score, roc_curve

    scores, labels = np.asarray(scores, float), np.asarray(labels, int)
    fpr, tpr, thr = roc_curve(labels, scores)
    k = int(np.argmax(tpr - fpr))
    t = float(thr[k])
    pred = (scores >= t).astype(int)
    lo, hi, mean = _boot_auroc_ci(scores, labels)
    return {
        "auroc": _auroc(scores, labels),
        "auroc_ci95": [lo, hi],
        "auroc_bootstrap_mean": mean,
        "auprc": float(average_precision_score(labels, scores)),
        "youden_threshold": t,
        "accuracy_at_youden": float((pred == labels).mean()),
        "tpr_at_youden": float(tpr[k]),
        "fpr_at_youden": float(fpr[k]),
        "n_pos": int((labels == 1).sum()),
        "n_neg": int((labels == 0).sum()),
    }


def _slice_metrics(clip_scores, inv, neg_slice):
    """Positives (ESC-50 laughing) vs one negative slice."""
    idx = [i for i, e in enumerate(inv) if e["label"] == 1 or e["slice"] == neg_slice]
    s = np.array([clip_scores[i] for i in idx])
    y = np.array([inv[i]["label"] for i in idx])
    m = _full_metrics(s, y)
    m["negative_slice"] = neg_slice
    return m


# --------------------------------------------------- H3 operating point
def operating_point(clip_scores, inv):
    """Threshold from ESC-50 folds 1-4 (Youden), reported on held-out fold 5."""
    from sklearn.metrics import roc_curve

    esc = [i for i, e in enumerate(inv) if e["slice"] in (SLICE_ESC50, "esc50_laughing")]
    tr = [i for i in esc if inv[i]["fold"] != 5]
    te = [i for i in esc if inv[i]["fold"] == 5]
    s_tr = np.array([clip_scores[i] for i in tr]); y_tr = np.array([inv[i]["label"] for i in tr])
    fpr, tpr, thr = roc_curve(y_tr, s_tr)
    t = float(thr[int(np.argmax(tpr - fpr))])

    def at(idxs):
        s = np.array([clip_scores[i] for i in idxs]); y = np.array([inv[i]["label"] for i in idxs])
        p = (s >= t).astype(int)
        pos, neg = y == 1, y == 0
        return {
            "n": len(idxs), "n_pos": int(pos.sum()), "n_neg": int(neg.sum()),
            "tpr": float(p[pos].mean()) if pos.any() else None,
            "fpr": float(p[neg].mean()) if neg.any() else None,
            "accuracy": float((p == y).mean()),
        }

    out = {
        "threshold": t,
        "threshold_selected_on": "ESC-50 folds 1-4 (Youden J), laughter-family max logit",
        "fold5_heldout": at(te),
        "folds1_4_insample": at(tr),
    }
    for sl in (SLICE_SPEECH, SLICE_TTS):
        idxs = [i for i, e in enumerate(inv) if e["slice"] == sl]
        s = np.array([clip_scores[i] for i in idxs])
        out[f"{sl}_fpr_at_threshold"] = float((s >= t).mean())
        out[f"{sl}_n"] = len(idxs)
    return out


# ------------------------------------------------- H4 streaming onset
def onset_latency(fam_scores, starts_all, inv, threshold):
    """Time from annotated laugh onset to first window crossing `threshold`."""
    import librosa

    lat, missed = [], 0
    for i, e in enumerate(inv):
        if e["label"] != 1:
            continue
        y, _ = librosa.load(e["path"], sr=TARGET_SR, mono=True)
        # energy-threshold onset: first frame whose short-time RMS exceeds
        # 20 % of the clip's peak RMS (annotation, not a detector)
        rms = librosa.feature.rms(y=y, frame_length=1024, hop_length=256)[0]
        above = np.where(rms > 0.20 * rms.max())[0]
        onset_s = float(above[0] * 256 / TARGET_SR) if len(above) else 0.0
        s, st = fam_scores[i], starts_all[i]
        fired = np.where(s >= threshold)[0]
        if not len(fired):
            missed += 1
            continue
        # a window is "detected at" its END (all its audio has arrived)
        det_s = float(st[fired[0]] + WINDOW_S)
        lat.append(max(0.0, det_s - onset_s))
    lat = np.asarray(lat)
    return {
        "n_positive_clips": int(sum(1 for e in inv if e["label"] == 1)),
        "n_detected": len(lat),
        "n_missed_at_threshold": missed,
        "time_to_first_detection_p50_s": float(np.percentile(lat, 50)) if len(lat) else None,
        "time_to_first_detection_p95_s": float(np.percentile(lat, 95)) if len(lat) else None,
        "time_to_first_detection_min_s": float(lat.min()) if len(lat) else None,
        "onset_annotation": "first RMS frame above 20 % of clip peak RMS "
                            "(1024-sample frame, 256 hop)",
        "note": "detection time is the END of the first window over threshold, so "
                f"{WINDOW_S:.2f} s of window fill is included by construction",
    }


def false_triggers(fam_scores, inv, threshold):
    """False triggers per minute on the concatenated negative stream, per slice."""
    out = {}
    for sl in (SLICE_ESC50, SLICE_SPEECH, SLICE_TTS):
        idxs = [i for i, e in enumerate(inv) if e["slice"] == sl]
        n_win = sum(len(fam_scores[i]) for i in idxs)
        n_fire = sum(int((fam_scores[i] >= threshold).sum()) for i in idxs)
        # each hop advances HOP_S of stream; stream duration ~ n_win * HOP_S
        minutes = n_win * HOP_S / 60.0
        out[sl] = {
            "n_windows": int(n_win),
            "stream_minutes": round(minutes, 3),
            "n_windows_over_threshold": n_fire,
            "false_triggers_per_minute": round(n_fire / minutes, 3) if minutes else None,
            "n_clips_with_any_trigger": sum(
                1 for i in idxs if (fam_scores[i] >= threshold).any()),
            "n_clips": len(idxs),
        }
    return out


# ------------------------------------------------------------------ latency
def _latency(model, fe, device, n_threads, n_windows=200):
    import torch

    prev = torch.get_num_threads()
    if n_threads is not None:
        torch.set_num_threads(n_threads)
    dev = torch.device(device)
    model.to(dev)
    rng = np.random.default_rng(SEED)
    wave = (rng.standard_normal(int(WINDOW_S * TARGET_SR)) * 0.05).astype(np.float32)

    def one():
        feats = fe(wave, sampling_rate=TARGET_SR, return_tensors="pt")
        with torch.inference_mode():
            model(input_values=feats["input_values"].to(dev))
        if device == "cuda":
            torch.cuda.synchronize()

    for _ in range(10):
        one()
    ts = []
    for _ in range(n_windows):
        t0 = time.perf_counter(); one(); ts.append((time.perf_counter() - t0) * 1000)
    torch.set_num_threads(prev)
    ts = np.asarray(ts)
    r = {"n": n_windows, "p50_ms": float(np.percentile(ts, 50)),
         "p99_ms": float(np.percentile(ts, 99)), "mean_ms": float(ts.mean()),
         "threads": n_threads if n_threads is not None else prev,
         "note": "batch=1, one 1-s window, includes log-mel feature extraction"}
    print(f"[hs1a] latency {device} threads={r['threads']}: "
          f"p50={r['p50_ms']:.1f} ms p99={r['p99_ms']:.1f} ms", flush=True)
    return r


# --------------------------------------------------------------------- run
def run(device: str = "cuda") -> dict:
    global CACHE
    import torch
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    t0 = time.time()
    inv = build_inventory()
    from collections import Counter
    print(f"[hs1a] inventory {len(inv)} clips: {Counter(e['slice'] for e in inv)}", flush=True)

    fe = AutoFeatureExtractor.from_pretrained(MODEL_ID)
    model = AutoModelForAudioClassification.from_pretrained(MODEL_ID).eval()
    n_params = int(sum(p.numel() for p in model.parameters()))
    label2id = {v: int(k) for k, v in model.config.id2label.items()}
    missing = [n for n in LAUGH_FAMILY if n not in label2id]
    if missing:
        raise RuntimeError(f"laughter-family labels absent from the model: {missing}")
    CACHE = {"primary_idx": label2id[LAUGH_PRIMARY],
             "family_idx": [label2id[n] for n in LAUGH_FAMILY]}
    print(f"[hs1a] {MODEL_ID} params={n_params/1e6:.1f}M family ids={CACHE['family_idx']}",
          flush=True)

    use_cuda = device == "cuda" and torch.cuda.is_available()
    dev = torch.device("cuda" if use_cuda else "cpu")
    model.to(dev)

    fam_scores, single_scores, starts_all = score_all(inv, model, fe, dev)
    clip_fam = np.array([s.max() for s in fam_scores])
    clip_single = np.array([s.max() for s in single_scores])

    esc_idx = [i for i, e in enumerate(inv)
               if e["slice"] in (SLICE_ESC50, "esc50_laughing")]
    y_esc = np.array([inv[i]["label"] for i in esc_idx])
    m_esc_fam = _full_metrics(clip_fam[esc_idx], y_esc)
    m_esc_single = _full_metrics(clip_single[esc_idx], y_esc)
    print(f"[hs1a] ESC-50 AUROC family={m_esc_fam['auroc']:.4f} "
          f"CI={m_esc_fam['auroc_ci95']} | single Laughter={m_esc_single['auroc']:.4f}",
          flush=True)

    slices = {sl: _slice_metrics(clip_fam, inv, sl)
              for sl in (SLICE_ESC50, SLICE_SPEECH, SLICE_TTS)}
    for sl, m in slices.items():
        print(f"[hs1a] slice {sl}: AUROC={m['auroc']:.4f} CI={m['auroc_ci95']}", flush=True)

    # all negatives pooled
    m_all = _full_metrics(clip_fam, np.array([e["label"] for e in inv]))

    op = operating_point(clip_fam, inv)
    print(f"[hs1a] operating point t={op['threshold']:.3f} fold5 "
          f"TPR={op['fold5_heldout']['tpr']} FPR={op['fold5_heldout']['fpr']}", flush=True)

    onset = onset_latency(fam_scores, starts_all, inv, op["threshold"])
    ft = false_triggers(fam_scores, inv, op["threshold"])
    op["onset_latency"] = onset
    op["false_triggers"] = ft
    print(f"[hs1a] onset p50={onset['time_to_first_detection_p50_s']} "
          f"p95={onset['time_to_first_detection_p95_s']}", flush=True)

    lat = {}
    if use_cuda:
        lat["gpu"] = _latency(model, fe, "cuda", None)
    else:
        lat["gpu"] = {"error": "cuda unavailable"}
    lat["cpu_1thread"] = _latency(model, fe, "cpu", 1)
    model.to(dev)

    out = {
        "evidence_tier": "replay",
        "amendments_applied": ["H1", "H2", "H3", "H4", "H7"],
        "model": MODEL_ID,
        "model_params": n_params,
        "gpu_name": torch.cuda.get_device_name(0) if use_cuda else None,
        "torch_version": torch.__version__,
        "window_seconds": WINDOW_S,
        "hop_seconds": HOP_S,
        "sample_rate": TARGET_SR,
        "laughter_family_labels": LAUGH_FAMILY,
        "laughter_family_ids": CACHE["family_idx"],
        "laughter_primary_label": LAUGH_PRIMARY,
        "laughter_primary_id": CACHE["primary_idx"],
        "n_clips_total": len(inv),
        "slice_counts": dict(Counter(e["slice"] for e in inv)),
        "headline_esc50_family_max": m_esc_fam,
        "esc50_single_laughter_label": m_esc_single,
        "per_slice": slices,
        "all_negatives_pooled": m_all,
        "operating_point": op,
        "latency_ms": lat,
        "data_provenance": negatives.provenance(),
        "seed": SEED,
        "wall_seconds": round(time.time() - t0, 1),
    }
    merge_results("hs1a", out)
    return out


if __name__ == "__main__":
    r = run()
    print(json.dumps({k: v for k, v in r.items() if k != "data_provenance"}, indent=2)[:6000])
