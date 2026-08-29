"""Shared helpers for HS-1 (humor signal). Paths, seeds, bootstrap CIs."""
from __future__ import annotations

import hashlib
import os
import pathlib

SEED = 20260828
DATA = pathlib.Path(os.path.expanduser("~/.cache/parcel-0e/data"))
HERE = pathlib.Path(__file__).resolve().parent
RESULTS_JSON = HERE / "results.json"

ESC50_ROOT = DATA / "esc50" / "ESC-50-master"
JESTER_DIR = DATA

# ESC-50 human non-speech negatives, exactly as pre-registered in DESIGN.md.
POS_CLASS = "laughing"
NEG_CLASSES = [
    "coughing",
    "sneezing",
    "breathing",
    "crying_baby",
    "clapping",
    "snoring",
    "drinking_sipping",
    "brushing_teeth",
    "footsteps",
]


def sha256_file(path: os.PathLike | str, limit: int | None = None) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            if limit is not None and fh.tell() >= limit:
                break
    return h.hexdigest()


def load_results() -> dict:
    import json

    if RESULTS_JSON.exists():
        return json.loads(RESULTS_JSON.read_text())
    return {}


def save_results(payload: dict) -> None:
    import json

    RESULTS_JSON.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def merge_results(key: str, value: dict) -> dict:
    """Write value under key in results.json under an exclusive lock, and also
    drop a per-key sidecar so a concurrent writer can never lose a section."""
    import fcntl
    import json

    (HERE / f"results_{key}.json").write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    lock = HERE / ".results.lock"
    with open(lock, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            payload = load_results()
            payload[key] = value
            save_results(payload)
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)
    return payload


def bootstrap_ci(x, y, stat_fn, n_boot: int = 2000, seed: int = SEED, alpha: float = 0.05):
    """Percentile bootstrap CI over paired samples (resample the n items)."""
    import numpy as np

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        if len(np.unique(x[idx])) < 2 or len(np.unique(y[idx])) < 2:
            continue
        vals.append(stat_fn(x[idx], y[idx]))
    vals = np.sort(np.asarray(vals, dtype=float))
    lo = float(np.percentile(vals, 100 * alpha / 2))
    hi = float(np.percentile(vals, 100 * (1 - alpha / 2)))
    return lo, hi, len(vals)
