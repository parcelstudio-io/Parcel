"""Jester dataset 1 loader (73,421 users x 100 jokes, ratings -10..10, 99 = unrated).

Reads the three Excel matrices from the cache, memoises a dense numpy copy, and
extracts the 100 joke texts. Records the exact source + checksum of every file
it used so RESULTS.md/README.md can state provenance.
"""
from __future__ import annotations

import html
import json
import re
import zipfile

import numpy as np
from hs_common import JESTER_DIR, sha256_file

MATRIX_ZIPS = ["jester_dataset_1_1.zip", "jester_dataset_1_2.zip", "jester_dataset_1_3.zip"]
TEXTS_ZIP = "jester_dataset_1_joke_texts.zip"
NPZ = JESTER_DIR / "jester1_matrix.npz"
TEXTS_JSON = JESTER_DIR / "jester1_joke_texts.json"
PROV_JSON = JESTER_DIR / "jester1_provenance.json"

UNRATED = 99.0


def _read_one_xls(zpath, tmpdir):
    import pandas as pd

    with zipfile.ZipFile(zpath) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".xls", ".xlsx"))]
        if not names:
            raise RuntimeError(f"no excel member in {zpath}: {zf.namelist()}")
        member = names[0]
        out = zf.extract(member, path=tmpdir)
    df = pd.read_excel(out, header=None)
    arr = df.to_numpy(dtype=float)
    # col 0 = number of jokes rated; cols 1..100 = ratings
    return arr[:, 0].astype(int), arr[:, 1:101]


def build_matrix(force: bool = False) -> tuple[np.ndarray, np.ndarray, dict]:
    """Return (n_rated per user, ratings matrix with NaN for unrated, provenance)."""
    import tempfile

    if NPZ.exists() and not force:
        z = np.load(NPZ)
        prov = json.loads(PROV_JSON.read_text())
        return z["n_rated"], z["ratings"], prov

    counts, blocks, prov_files = [], [], []
    with tempfile.TemporaryDirectory() as td:
        for name in MATRIX_ZIPS:
            p = JESTER_DIR / name
            if not p.exists():
                raise FileNotFoundError(f"missing {p}")
            c, r = _read_one_xls(p, td)
            print(f"[jester] {name}: {r.shape[0]} users x {r.shape[1]} jokes")
            counts.append(c)
            blocks.append(r)
            prov_files.append({"file": name, "sha256": sha256_file(p),
                               "bytes": p.stat().st_size, "users": int(r.shape[0])})
    n_rated = np.concatenate(counts)
    ratings = np.vstack(blocks)
    ratings = np.where(ratings >= UNRATED, np.nan, ratings)
    prov = {"files": prov_files, "source": "https://eigentaste.berkeley.edu/dataset/",
            "shape": list(ratings.shape)}
    np.savez_compressed(NPZ, n_rated=n_rated, ratings=ratings)
    PROV_JSON.write_text(json.dumps(prov, indent=2))
    return n_rated, ratings, prov


_TAG = re.compile(r"<[^>]+>")


def build_texts(force: bool = False) -> list[str]:
    if TEXTS_JSON.exists() and not force:
        return json.loads(TEXTS_JSON.read_text())
    p = JESTER_DIR / TEXTS_ZIP
    if not p.exists():
        raise FileNotFoundError(f"missing {p}")
    texts: dict[int, str] = {}
    with zipfile.ZipFile(p) as zf:
        for name in zf.namelist():
            if name.startswith("__MACOSX") or "/._" in name:
                continue
            m = re.search(r"init(\d+)\.html$", name)
            if not m:
                continue
            raw = zf.read(name).decode("latin-1")
            body = raw.split("<!--begin of joke -->")[-1].split("<!--end of joke -->")[0]
            body = re.sub(r"<br\s*/?>", "\n", body, flags=re.IGNORECASE)
            body = re.sub(r"</?p[^>]*>", "\n", body, flags=re.IGNORECASE)
            body = _TAG.sub("", body)
            body = html.unescape(body)
            body = re.sub(r"[ \t]+", " ", body)
            body = re.sub(r"\n\s*\n+", "\n\n", body).strip()
            texts[int(m.group(1))] = body
    if len(texts) != 100:
        print(f"[jester] WARNING: extracted {len(texts)} joke texts, expected 100")
    ordered = [texts[i] for i in sorted(texts)]
    TEXTS_JSON.write_text(json.dumps(ordered, indent=2))
    return ordered


if __name__ == "__main__":
    n_rated, ratings, prov = build_matrix()
    print("matrix", ratings.shape, "users", ratings.shape[0])
    print("observed ratings", int(np.isfinite(ratings).sum()))
    print("n_rated stats", n_rated.min(), n_rated.max(), n_rated.mean().round(2))
    t = build_texts()
    print("texts", len(t))
    print("joke 1:", t[0][:200].replace("\n", " | "))
