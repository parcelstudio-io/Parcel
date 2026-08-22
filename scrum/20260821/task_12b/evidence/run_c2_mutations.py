"""C-2 seeded-defect harness — 13 seeds, each must turn a real test RED.

Protocol, per the register and C-1's hardening of it:

* a **fresh-interpreter canary** before any seeding, so a run that starts from a
  dirty tree is caught rather than averaged in;
* ``__pycache__`` purged before **every** cell — a stale ``.pyc`` is how a seed
  silently does not apply and reports GREEN as if the property were checked;
* the restore lives in a ``finally`` and is **SHA-verified** against the
  pre-seed bytes; C-1's seed 8 crashed its harness before the restore line and
  left mutated bytes in the tree, so restoring on the exception path is the
  whole lesson;
* a hang counts as RED-by-timeout rather than crashing the run;
* a **final sweep** run after the last source write, plus a repo-root stray
  sweep.

Run:
    .parcel/bin/python scrum/20260821/task_12b/evidence/run_c2_mutations.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PKG = REPO / "src" / "parcel_robot" / "online_map"
TESTS = REPO / "tests" / "test_c2_online_map.py"
REPLAY = Path(__file__).parent / "run_c2_replay.py"
PYTHON = REPO / ".parcel" / "bin" / "python"


@dataclass(frozen=True)
class Seed:
    number: int
    name: str
    breaks: str
    path: Path
    anchor: str
    replacement: str
    #: pytest node ids that must go RED. Empty means "run the replay harness
    #: and require a non-zero exit" instead.
    nodes: tuple[str, ...] = ()
    replay: bool = False


def T(name: str) -> str:
    return f"{TESTS}::{name}"


SEEDS: tuple[Seed, ...] = (
    Seed(
        1,
        "decay deletes instead of marking",
        "history is destroyed; the map can no longer say what it stopped believing",
        PKG / "online_map.py",
        """                was = entry.status
                entry.mark_decayed(""",
        """                was = entry.status
                self._entries.pop(entry.entry_id, None)  # SEED-1
                entry.mark_decayed(""",
        (T("test_absence_marks_and_never_deletes"),),
    ),
    Seed(
        2,
        "decay-marked entries stay retrievable",
        "quarantine degrades to annotation; a place the robot stopped believing "
        "is still offered as a goal",
        PKG / "entries.py",
        "RETRIEVABLE_STATUSES: frozenset[str] = frozenset({STATUS_ACTIVE})",
        "RETRIEVABLE_STATUSES: frozenset[str] = frozenset({STATUS_ACTIVE, STATUS_DECAYED})",
        (
            T("test_a_decayed_entry_is_excluded_from_retrieval_not_merely_annotated"),
        ),
    ),
    Seed(
        3,
        "writer provenance dropped on persist",
        "R27 discipline: a stored place stops naming the session and eye that "
        "wrote it",
        PKG / "entries.py",
        '            "provenance": self.provenance.as_dict(),',
        '            "provenance": WriterProvenance("unknown", "unknown", "unknown", "unknown").as_dict(),  # SEED-3',
        (T("test_a_map_reloads_entry_for_entry_with_its_provenance"),),
    ),
    Seed(
        4,
        "the owner's conversation store is accepted as a map store",
        "the R27 catastrophe, re-armed",
        PKG / "store.py",
        "    if resolved.name == OWNER_STORE_NAME:",
        "    if False:  # SEED-4",
        (T("test_the_owner_conversation_store_is_refused_by_name"),),
    ),
    Seed(
        5,
        "reload skipped; every session starts empty",
        "the dog that walked yesterday forgets the lamppost",
        PKG / "online_map.py",
        "        loaded = self._store.load_all()",
        "        loaded = ()  # SEED-5",
        (
            T("test_a_map_reloads_entry_for_entry_with_its_provenance"),
            T("test_reload_survives_a_fresh_interpreter"),
        ),
    ),
    Seed(
        6,
        "abstention bypassed in the query API",
        "PG-3 becomes decoration; every query is grounded",
        PKG / "online_map.py",
        "        return verdict, diagnostics",
        """        from parcel_robot.perception_abstention import GROUNDED as _G  # SEED-6
        return AbstentionVerdict(True, query, _G), diagnostics""",
        (
            T("test_a_query_with_no_label_match_produces_no_candidates_and_a_verdict"),
            T("test_an_unasked_term_is_refused_because_nobody_asked"),
        ),
    ),
    Seed(
        7,
        "null controls removed from the live-proof scoring",
        "the live proof stops being falsifiable",
        REPLAY,
        'NULL_CONTROLS = (\n    "fire hydrant",',
        'NULL_CONTROLS = (  # SEED-7\n)\n_UNUSED = (\n    "fire hydrant",',
        (),
        replay=True,
    ),
    Seed(
        8,
        "volatile-class exclusion disabled (poster enters the map as a person)",
        "REVISION 3(a): a photorealistic person poster becomes a persistent place",
        PKG / "hygiene.py",
        "    if is_volatile_label(label):",
        "    if False:  # SEED-8",
        (
            T("test_a_person_is_observed_counted_and_never_persisted"),
            T("test_the_poster_decoy_cannot_enter_the_map_as_a_person"),
        ),
    ),
    Seed(
        9,
        "metric-size gate disabled (decal forges label agreement)",
        "REVISION 3(b): a 0.45 m painted sign becomes a coffee shop",
        PKG / "hygiene.py",
        "    if w < prior.min_w_m or h < prior.min_h_m:",
        "    if False:  # SEED-9",
        (
            T("test_the_decal_decoy_cannot_forge_a_storefront"),
            T("test_the_decal_decoy_is_refused_by_the_map_itself"),
        ),
    ),
    Seed(
        10,
        "embeddings averaged across views instead of best-view",
        "REVISION 2: the stored vector describes no view that ever existed",
        PKG / "online_map.py",
        "        entry.embedding = obs.embedding",
        """        entry.embedding = (  # SEED-10
            obs.embedding
            if entry.embedding is None
            else tuple(0.5 * (a + b) for a, b in zip(entry.embedding, obs.embedding))
        )""",
        (T("test_the_stored_embedding_is_the_best_view_and_never_a_blend"),),
    ),
    Seed(
        11,
        "version mismatch silently cross-space cosines",
        "REVISION 2: two coordinate systems compared as if they were one",
        PKG / "online_map.py",
        "            or not entry.embedding_stamp.compatible_with(query_stamp)\n",
        "            or False  # SEED-11\n",
        (
            T(
                "test_a_version_mismatch_reports_unavailable_and_never_cross_space_cosines"
            ),
        ),
    ),
    Seed(
        12,
        "cosine promoted to an absolute presence threshold",
        "REVISION 1: the modality-gap band becomes a presence verdict",
        PKG / "online_map.py",
        "        ordered = ordered[: max(0, int(limit))]",
        """        ordered = tuple(  # SEED-12
            c for c in ordered if c.similarity is None or c.similarity >= 0.1
        )[: max(0, int(limit))]""",
        (
            T("test_the_embedding_channel_returns_a_permutation_of_the_same_candidates"),
        ),
    ),
    Seed(
        13,
        "VLM-proposed name admitted without the k-visit gate",
        "REVISION 5: one-in-seven wrong names becomes vocabulary",
        PKG / "entries.py",
        "        if self.provenance == NAME_DETECTOR_LABEL:\n            return True",
        "        if True:  # SEED-13\n            return True",
        (
            T("test_an_unpromoted_vlm_name_is_not_retrievable_and_is_not_vocabulary"),
            T("test_the_same_visit_repeated_does_not_promote_a_name"),
        ),
    ),
)


def purge_pycache() -> None:
    for cache in REPO.rglob("__pycache__"):
        if ".parcel" in cache.parts or ".git" in cache.parts:
            continue
        shutil.rmtree(cache, ignore_errors=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_pytest(nodes: tuple[str, ...], timeout: int = 300) -> tuple[bool, str]:
    """Returns (all_passed, tail)."""

    proc = subprocess.run(
        [str(PYTHON), "-m", "pytest", "-q", "-p", "no:cacheprovider", *nodes],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, "\n".join(tail[-3:])


def run_replay(timeout: int = 300) -> tuple[bool, str]:
    proc = subprocess.run(
        [str(PYTHON), str(REPLAY)],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    tail = (proc.stdout + proc.stderr).strip().splitlines()
    return proc.returncode == 0, "\n".join(tail[-3:])


def main() -> int:
    started = time.time()
    results: list[dict] = []

    # ---- canary: a fresh interpreter on a clean tree must be green --------
    purge_pycache()
    canary_ok, canary_tail = run_pytest((str(TESTS),))
    if not canary_ok:
        print("CANARY FAILED — the tree is not green before seeding:")
        print(canary_tail)
        return 2
    print(f"canary: GREEN ({canary_tail.splitlines()[-1] if canary_tail else 'ok'})")

    replay_ok, replay_tail = run_replay()
    if not replay_ok:
        print("CANARY FAILED — the replay harness self-check is not green:")
        print(replay_tail)
        return 2
    print("canary: replay harness self-check GREEN")

    for seed in SEEDS:
        purge_pycache()
        original = seed.path.read_bytes()
        before = hashlib.sha256(original).hexdigest()
        text = original.decode()
        occurrences = text.count(seed.anchor)
        cell: dict = {
            "seed": seed.number,
            "name": seed.name,
            "breaks": seed.breaks,
            "file": str(seed.path.relative_to(REPO)),
            "anchor_occurrences": occurrences,
        }
        if occurrences != 1:
            cell.update(
                {"red": False, "how": "ANCHOR_NOT_UNIQUE",
                 "detail": f"anchor appears {occurrences} times"}
            )
            results.append(cell)
            print(f"seed {seed.number:2d}: ANCHOR ERROR ({occurrences} matches)")
            continue

        try:
            seed.path.write_text(text.replace(seed.anchor, seed.replacement))
            purge_pycache()
            if seed.replay:
                passed, tail = run_replay()
            else:
                passed, tail = run_pytest(seed.nodes)
            cell.update(
                {"red": not passed,
                 "how": "assertion" if not passed else "STAYED GREEN",
                 "detail": tail}
            )
        except subprocess.TimeoutExpired:
            cell.update({"red": True, "how": "timeout/hang", "detail": "cell hung"})
        finally:
            # The restore is here, not after the check. C-1's seed 8 hung and
            # its harness died before its restore line, leaving mutated bytes.
            seed.path.write_bytes(original)
            purge_pycache()
            after = sha(seed.path)
            cell["restored_byte_identical"] = after == before
            if after != before:
                raise SystemExit(
                    f"FATAL: seed {seed.number} did not restore {seed.path}"
                )
        results.append(cell)
        print(f"seed {seed.number:2d}: {'RED' if cell['red'] else 'GREEN (BAD)':10s}"
              f" [{cell['how']}] {seed.name}")

    # ---- final sweep, AFTER the last source write ------------------------
    purge_pycache()
    sweep_ok, sweep_tail = run_pytest((str(TESTS),))
    sweep_line = sweep_tail.splitlines()[-1] if sweep_tail else ""

    # ---- anchors all present exactly once = no seed left applied ---------
    anchors_clean = all(
        seed.path.read_text().count(seed.anchor) == 1 for seed in SEEDS
    )

    # ---- repo-root stray sweep -------------------------------------------
    tracked = subprocess.run(
        ["git", "-C", str(REPO), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()
    strays = [
        line for line in tracked
        if line.startswith("??") and "/" not in line[3:].strip().rstrip("/")
    ]

    red = sum(1 for cell in results if cell.get("red"))
    restored = sum(1 for cell in results if cell.get("restored_byte_identical"))
    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seeds": len(SEEDS),
        "red": red,
        "byte_restored": restored,
        "final_sweep": sweep_line,
        "final_sweep_green": sweep_ok,
        "no_seed_remains_applied": anchors_clean,
        "repo_root_strays": strays,
        "elapsed_s": round(time.time() - started, 1),
        "cells": results,
    }
    out = Path(__file__).parent / "c2_mutation_results.json"
    out.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    print(f"\n{red}/{len(SEEDS)} RED · {restored}/{len(SEEDS)} byte-restored")
    print(f"final sweep: {sweep_line} (green={sweep_ok})")
    print(f"no seed remains applied: {anchors_clean} · repo-root strays: {strays}")
    print(f"wrote {out}")
    return 0 if red >= 10 and sweep_ok and anchors_clean and not strays else 1


if __name__ == "__main__":
    raise SystemExit(main())
