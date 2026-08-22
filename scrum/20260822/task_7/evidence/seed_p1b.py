"""Seeded-RED harness for card P1-B.

For each seed: record the target file's sha256, apply ONE exact-match
replacement, purge __pycache__, run the named tests (expect RED), restore the
file byte-identically, verify the sha, purge again, rerun (expect GREEN).
A seed that cannot restore its file exactly is a failure of the harness and is
reported as one.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
PY = REPO / ".parcel" / "bin" / "python"

SEEDS = [
    (
        "S-1  AU-C2-1 returns: as_dict drops the thumbnail again",
        "src/parcel_robot/online_map/entries.py",
        '''            "thumbnail": (
                base64.b64encode(self.thumbnail).decode("ascii")
                if self.thumbnail
                else None
            ),
''',
        "",
        ["tests/test_p1b_map_learns.py::test_the_source_crop_survives_a_store_round_trip"],
    ),
    (
        "S-2  the store stops refusing a mixed-origin map",
        "src/parcel_robot/online_map/store.py",
        "        self._refuse_mixed_origins(out)\n",
        "",
        ["tests/test_p1b_map_learns.py::test_a_store_mixing_physical_and_simulated_entries_is_refused"],
    ),
    (
        "S-3  the seam accepts an embedding with no space",
        "src/parcel_robot/online_map/ingest.py",
        "    if embedding is not None and embedding_stamp is None:\n        raise ValueError(",
        "    if False:\n        raise ValueError(",
        ["tests/test_p1b_map_learns.py::test_an_embedding_with_no_space_is_refused_at_the_seam"],
    ),
    (
        "S-4  D-R2 returns: the query union is uncapped",
        "src/parcel_robot/camera_channel/ingress.py",
        "        if len(ordered) <= MAX_QUERY_PHRASES:\n            return tuple(ordered)\n",
        "        return tuple(ordered)\n",
        [
            "tests/test_p1b_map_learns.py::test_the_query_union_is_capped_and_the_drop_is_counted",
            "tests/test_p1b_map_learns.py::test_the_safety_lease_is_never_the_phrase_that_falls_off_the_end",
        ],
    ),
    (
        "S-5  D-R1 returns: the attach site stops pinning the configured batch",
        "src/parcel_robot/runtime.py",
        "        ingress.pinned_queries = tuple(config.queries)\n",
        "",
        ["tests/test_p1b_map_learns.py::test_the_attach_site_pins_the_configured_batch"],
    ),
    (
        "S-6  the attach site stops arming the SigLIP-2 encoder",
        "src/parcel_robot/runtime.py",
        "        embed_space = load_siglip2_embed_fn()\n",
        "        embed_space = None\n",
        ["tests/test_p1b_map_learns.py::test_the_attach_site_pins_the_configured_batch"],
    ),
    (
        "S-7  the runtime stops persisting the map on close()",
        "src/parcel_robot/runtime.py",
        "                self._p1b_persist_learned_map()\n",
        "                pass\n",
        ["tests/test_p1b_map_learns.py::test_the_runtime_region_wires_all_three_seams"],
    ),
    # ---- added by the 2026-08-22 verification corrections ----------------
    (
        "S-8  the store is never closed, so persisted rows sit in the WAL",
        "src/parcel_robot/online_map/online_map.py",
        "        store = self._store\n        if store is None:\n            return\n        self._store = None\n        store.close()",
        "        return",
        [
            "tests/test_p1b_map_learns.py::test_a_persisted_store_is_one_self_contained_file",
            "tests/test_p1b_map_learns.py::test_closing_the_map_releases_the_store_but_keeps_the_entries",
        ],
    ),
    (
        "S-9  the runtime stops closing the store after persisting",
        "src/parcel_robot/runtime.py",
        "                learned.close()\n            self._p1b_persisted = written\n",
        "                pass\n            self._p1b_persisted = written\n",
        ["tests/test_p1b_map_learns.py::test_the_runtime_closes_the_store_after_persisting"],
    ),
    (
        "S-10 scene_id falls back to the robot-config filename again",
        "src/parcel_robot/runtime.py",
        "            configured = self._camera_scene_path\n            scene = (\n                Path(configured)\n                if configured\n                else resolve_scene(Path(self.store.path), None)\n            )\n            return Path(scene).stem or \"unknown\"",
        "            return Path(self._camera_scene_path or self.store.path).stem or \"unknown\"",
        ["tests/test_p1b_map_learns.py::test_the_map_is_stamped_with_the_scene_not_the_config_filename"],
    ),
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge() -> None:
    for cache in REPO.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def run(tests: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        [str(PY), "-m", "pytest", "-q", "-p", "no:randomly", *tests],
        cwd=str(REPO), capture_output=True, text=True, check=False,
    )
    return proc.returncode, proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""


def main() -> int:
    import datetime

    stamp = datetime.datetime.now(tz=datetime.UTC).isoformat(timespec='seconds')
    head = subprocess.run(
        ['git', '-C', str(REPO), 'rev-parse', 'HEAD'],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    print(f"P1-B seeded-RED harness — {stamp}")
    print(f"interpreter: {PY}")
    print(f"repo HEAD  : {head}")
    print(
        "protocol   : seed one exact replacement -> purge every __pycache__ -> "
        "run the named tests (expect RED) -> restore -> verify sha256 -> purge "
        "-> rerun (expect GREEN)\n"
    )
    failures = 0
    for name, relative, old, new, tests in SEEDS:
        target = REPO / relative
        original = target.read_text(encoding="utf-8")
        before = sha(target)
        count = original.count(old)
        if count != 1:
            print(f"[{name}] HARNESS ERROR: pattern matched {count} times")
            failures += 1
            continue
        target.write_text(original.replace(old, new), encoding="utf-8")
        purge()
        code, line = run(tests)
        red = code != 0
        target.write_text(original, encoding="utf-8")
        after = sha(target)
        purge()
        green_code, green_line = run(tests)
        ok = red and after == before and green_code == 0
        print(f"[{'OK ' if ok else 'BAD'}] {name}")
        print(f"        seeded : {'RED' if red else 'STILL GREEN'}  {line}")
        print(f"        restore: sha {'identical' if after == before else 'DIFFERS'} ({before[:12]})")
        print(f"        rerun  : {'GREEN' if green_code == 0 else 'RED'}  {green_line}")
        if not ok:
            failures += 1
    print(f"\n{len(SEEDS) - failures}/{len(SEEDS)} seeds went RED, restored byte-identically, and came back GREEN.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
