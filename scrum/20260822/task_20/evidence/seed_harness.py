"""Seed a product file, run a targeted selection, restore byte-identically."""
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path("/home/jaewoo-jang/Desktop/Projects/Parcel")


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def purge():
    for d in REPO.rglob("__pycache__"):
        if ".parcel" in d.parts or "third_party" in d.parts:
            continue
        shutil.rmtree(d, ignore_errors=True)


def run(sel):
    env = dict(os.environ)
    env.pop("TMPDIR", None)
    proc = subprocess.run(
        [str(REPO / ".parcel/bin/python"), "-m", "pytest", *sel, "-q", "-p", "no:randomly"],
        cwd=str(REPO), capture_output=True, text=True, env=env, check=False,
    )
    tail = [ln for ln in proc.stdout.strip().splitlines() if ln.strip()][-1]
    return proc.returncode, tail


def seeded(rel, old, new, sel, label):
    path = REPO / rel
    before = sha(path)
    original = path.read_bytes()
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"anchor not unique in {rel}"
    path.write_text(text.replace(old, new), encoding="utf-8")
    purge()
    try:
        rc, tail = run(sel)
    finally:
        path.write_bytes(original)
        purge()
    after = sha(path)
    assert after == before, f"RESTORE FAILED for {rel}"
    rc2, tail2 = run(sel)
    print(f"SEED [{label}] {rel}")
    print(f"  seeded : rc={rc} {tail}")
    print(f"  restore: sha256 identical ({before[:12]})")
    print(f"  rerun  : rc={rc2} {tail2}")
    return rc, rc2
