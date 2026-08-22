"""Card W-1: the held-out scene stays held out, mechanically.

`src/parcel_robot/scenes/city_block_b.xml` exists for exactly one purpose — so
that a future card (E-2) can make a **generalization** claim about pixels no
perception component was ever tuned against. That purpose survives exactly as
long as nobody looks at it. Conventions did not hold for store isolation
(R27's register entry: "convention was tried four times and failed four times"),
so it is not a convention here either.

The rule this file enforces:

* **No module under `src/parcel_robot/` may name the held-out scene at all.**
  That is where every perception component lives — detectors, the camera
  channel, the grounding stack, the navigator. A reference from there is a
  reference from the thing being evaluated.
* **Every other file that names it must be on the allowlist below**, and the
  allowlist is exhaustive: a new mention is a red build until somebody adds it
  here on purpose and says why.
* **No test other than this one may load it**, apart from the asset-integrity
  test, which reads its geometry and never its pixels.

What is deliberately allowed: the scene itself, its generated scene-truth
artifact, the regeneration tooling that produced that artifact, this test, the
asset-integrity test, and the card's own paperwork. Geometry is not the held-out
quantity — appearance is.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HELD_OUT_TOKEN = "city_block_b"
HELD_OUT_SCENE = REPO / "src" / "parcel_robot" / "scenes" / "city_block_b.xml"

#: Every file allowed to name the held-out scene, and the reason.
ALLOWED: dict[str, str] = {
    "src/parcel_robot/scenes/city_block_b.xml": "the scene itself",
    "evals/nav_instruct/scene_truth_city_block_b.json": (
        "the held-out scene's own generated geometry artifact"
    ),
    "evals/nav_instruct/scene_truth.py": "the documented regeneration tooling",
    "tests/test_held_out_scene.py": "this test",
    "tests/test_scene_assets.py": (
        "asset integrity: reads the scene's GEOMETRY and its texture references, "
        "never renders it and never runs a model on it"
    ),
    "tests/test_unitree_asset_pack.py": (
        "card GATE-0 (scrum/20260822/task_20). The vendored Unitree Go2 MJCF is "
        "the payload BOTH product scenes <include>, so proving the pack is "
        "self-contained means compiling both — a gate that certified only the "
        "development city would leave the held-out scene's compilability "
        "uncertified and the clean clone still broken. GEOMETRY ONLY, by the "
        "same rule test_scene_assets.py already runs under: MjModel.from_xml_path "
        "and nothing else. No renderer is constructed, no data is stepped, and no "
        "model is run over its pixels. It names the scene deliberately rather "
        "than reaching it through a glob, so this scan can see the exposure — a "
        "silent load is exactly what the load-pair below exists to prevent. "
        "SEAT GRANTED by the card, which also required the pair to grow "
        "deliberately rather than by accident. scripts/ci_gate.py runs the same "
        "compile at gate time and derives its scene list, so it does not need a "
        "seat of its own."
    ),
    "scrum/20260821/task_10/README.md": "the card that created it",
    "scrum/20260821/task_10/W1_STATUS.md": "the card's status document",
    "scrum/20260821/task_14/README.md": (
        "E-2, the ONE declared held-out evaluation this scene exists for. Its own "
        "dispatch gate says the dog enters cold, with no sidecar vocabulary."
    ),
    "scrum/20260821/task_14/E2_STATUS.md": (
        "E-2's status/halt record: it documents the survey that left the "
        "exposure UNSPENT and cannot do so without naming its subject. Written "
        "after E-2's entry gate, so no executor could see this scan redden — "
        "seat added by the chain auditor (AUDIT_CHAIN_FABLE.md)"
    ),
    "scrum/20260821/task_14/evidence/E2_PREREGISTRATION.md": (
        "E-2's pre-registered protocol, fixed before the dependency survey; "
        "its fixity is the eval's integrity mechanism and it must name the "
        "scene it governs. Same auditor-granted seat as E2_STATUS.md"
    ),
    "scrum/20260822/INTEGRITY_GATES_TODO.md": (
        "a Sol-session corrective TODO (author not a live session at seat time) "
        "whose IG-1 checklist lists the two tracked product scenes for a planned "
        "compile-only asset-pack gate. Prose under scrum/, written after its "
        "author's gate — the doc catch-22 again. Seat granted by the chain "
        "auditor (AUDIT_WAVE_P1P2_FABLE.md); the asset-pack TEST it plans needs "
        "its own seat and the load-pair must grow deliberately"
    ),
    "scrum/20260822/task_20/README.md": (
        "card GATE-0's own dispatch text. It names the two scenes whose "
        "<include> lines the vendored Unitree pack has to satisfy, and it is "
        "the reason the seat above exists. Tracked at HEAD 8862220, i.e. this "
        "scan was ALREADY red on the card's own paperwork before its executor "
        "opened a file — the doc catch-22 AUDIT_CHAIN_FABLE.md describes, for "
        "the fourth time. Seat taken by the GATE-0 executor with the card's "
        "authority over task_20/ docs"
    ),
    "scrum/20260822/task_20/PREREGISTRATION.md": (
        "GATE-0's pre-registered acceptance rows, fixed before any measurement. "
        "Row R3 has to say which scenes the asset gate compiles or it is not a "
        "pre-registration. Same catch-22 seat as the README above"
    ),
    "scrum/20260822/task_20/GATE0_STATUS.md": (
        "GATE-0's status record. It reports the seat granted above and cannot "
        "do so without naming its subject. Same catch-22 seat"
    ),
    "CODEBASE_INDEX.md": (
        "generated file index; lists paths only, never scene content; regenerated "
        "per commit by tools/codebase_index.py. Its single mention is one line of "
        "a directory census — `src/parcel_robot/scenes/ — 2 .xml (city_block.xml; "
        "city_block_b.xml)` — which is the scene's NAME and not one pixel, one "
        "geometry row or one label of it. Seat granted by card FINISH-1 "
        "(scrum/20260822/task_29 §C6) on GATE-0's behalf, which owns this seat "
        "file this wave: the nightly prose scan was red on it from the moment the "
        "index was generated, which is the doc catch-22 for the fifth time — a "
        "file that enumerates every tracked path cannot enumerate them minus one. "
        "ONE seat, grown deliberately: tools/codebase_index.py itself does NOT "
        "name the scene (it globs), so it gets no seat, and this entry does not "
        "join LOAD_ALLOWED — an index never opens what it lists."
    ),
    "scrum/20260821/task_20/MOVE1_STATUS.md": (
        "MOVE-1's status record names the scene only to say its exposure stays "
        "UNSPENT while E2-D2 is diagnosed. Prose under scrum/, written after its "
        "own entry gate — the doc catch-22 AUDIT_CHAIN_FABLE.md describes. Seat "
        "granted by card P0-E (scrum/20260822/task_5)"
    ),
}

#: Directories that are not source and are never scanned.
SKIP_DIRS = {
    ".git", ".parcel", ".cache", ".tmp", ".tmp_ci", "build", "node_modules",
    "__pycache__", "third_party", "recordings", "logs", ".pytest_cache",
    ".ruff_cache", ".venv", "dist",
}

SCANNED_SUFFIXES = {".py", ".json", ".yaml", ".yml", ".xml", ".md", ".toml", ".sh",
                    ".txt", ".tsv", ".html", ".cfg", ".ini"}


def _tracked_files() -> list[Path]:
    """Prefer git's index: it is the set that actually ships and it skips the
    scratch directories a plain walk would trip over."""

    try:
        names: set[str] = set()
        for args in (
            ["git", "ls-files", "-z"],
            # Untracked-but-not-ignored too: a leak that has not been committed
            # yet is still a leak, and this test exists to catch it BEFORE the
            # commit rather than after.
            ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        ):
            out = subprocess.run(args, cwd=REPO, capture_output=True, check=True).stdout
            names.update(name for name in out.decode().split("\0") if name)
        if names:
            return [REPO / name for name in sorted(names)]
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover - no git
        pass
    return [p for p in REPO.rglob("*") if p.is_file()]


def _mentions() -> set[str]:
    found: set[str] = set()
    for path in _tracked_files():
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SCANNED_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if HELD_OUT_TOKEN in text:
            found.add(path.relative_to(REPO).as_posix())
    return found


def test_the_held_out_scene_exists_and_is_marked() -> None:
    assert HELD_OUT_SCENE.is_file()
    header = HELD_OUT_SCENE.read_text(encoding="utf-8")[:2000]
    assert "HELD OUT" in header, "the scene must announce itself in its own first lines"


@pytest.mark.slow
def test_only_the_allowlist_names_the_held_out_scene() -> None:
    # Card P0-E: the repo-wide prose scan is an evidence guard, not a product
    # guard — it reddens on status docs (the catch-22 the chain audit named). It
    # runs nightly; the sharp halves below (src/ and tests/) stay in the commit
    # tier because they are the generalization claim's actual mechanism.
    found = _mentions()
    unexpected = sorted(found - set(ALLOWED))
    assert not unexpected, (
        "these files reference the held-out scene and are not on the allowlist: "
        f"{unexpected}. If a perception component reads it, the generalization "
        "claim E-2 exists to make is already spent. If the reference is "
        "legitimate, add it to ALLOWED with a reason."
    )
    # The allowlist may not rot the other way either: an entry that no longer
    # mentions the scene is a stale exemption. Paperwork under `scrum/` is
    # exempt from the staleness half on purpose — a status document is prose,
    # and making a test outcome depend on whether a sentence has been written
    # yet turns the writing of evidence into a source edit.
    # ... and a file that is not in this checkout at all cannot be hiding a
    # leak, so it is not a stale exemption either. Card FINISH-1 (task_29 §C6)
    # added the seat for the GENERATED CODEBASE_INDEX.md, which a tree that has
    # not run `tools/codebase_index.py` yet simply does not have; without this
    # clause the seat would turn "the index has not been generated" into a red
    # build about the held-out scene, which is a sentence about nothing.
    stale = sorted(
        name
        for name in set(ALLOWED) - found
        if not name.startswith("scrum/") and (REPO / name).is_file()
    )
    assert not stale, f"allowlist entries that no longer mention the scene: {stale}"


def test_no_product_module_names_the_held_out_scene() -> None:
    """The sharp half of the rule: `src/` is where perception lives."""

    offenders = sorted(
        name
        for name in _mentions()
        if name.startswith("src/parcel_robot/") and not name.endswith("city_block_b.xml")
    )
    assert not offenders, (
        f"product modules must not know the held-out scene exists: {offenders}"
    )


#: The tests allowed to LOAD the held-out scene, not merely name it. It was a
#: pair (this file + the asset-integrity scan); card GATE-0 grew it to three,
#: deliberately, because the vendored-simulator gate must compile both product
#: scenes or the clean-clone claim covers only half of them. Every member reads
#: geometry and never appearance. Growing this set is a decision, not a diff.
LOAD_ALLOWED = frozenset({
    "tests/test_held_out_scene.py",
    "tests/test_scene_assets.py",
    "tests/test_unitree_asset_pack.py",
})


def test_no_test_outside_this_pair_loads_the_held_out_scene() -> None:
    offenders = sorted(
        name
        for name in _mentions()
        if name.startswith("tests/")
        and name not in LOAD_ALLOWED
    )
    assert not offenders, (
        f"tests outside the declared load set read the held-out scene: {offenders}"
    )


def test_the_held_out_scene_is_not_the_default_scene_anywhere() -> None:
    """A default is the easiest way to leak a held-out set by accident."""

    pattern = re.compile(r"(DEFAULT|default)[A-Za-z_]*\s*[:=].*city_block_b")
    leaks = []
    for name in _mentions():
        text = (REPO / name).read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text):
            leaks.append(name)
    assert not leaks, f"the held-out scene is wired as a default in: {leaks}"


def test_the_held_out_truth_artifact_carries_its_warning() -> None:
    import json

    payload = json.loads(
        (REPO / "evals/nav_instruct/scene_truth_city_block_b.json").read_text(encoding="utf-8")
    )
    assert "held_out" in payload, "the artifact must say what it is"
    assert "transcribed" not in payload, (
        "the held-out scene has no episode-generator transcription; an empty one "
        "would read as agreement"
    )
    assert payload["scene"]["path"].endswith("city_block_b.xml")


def test_the_held_out_truth_artifact_equals_a_fresh_derivation() -> None:
    """The same golden-file rule PG-2 put on the development scene.

    Without this the held-out answer key could be hand-nudged and E-2 would
    grade against a number nobody derived — which is the exact defect the Wave-0
    audit named and PG-2 closed for `city_block`.
    """

    from evals.nav_instruct.scene_truth import (
        REPO_ROOT,
        SCENE_TARGETS,
        build_artifact,
        load_artifact,
    )

    relpath, artifact_path, transcription = SCENE_TARGETS["city_block_b"]
    fresh = build_artifact(
        REPO_ROOT / relpath, relpath=relpath, transcription=transcription
    )
    assert load_artifact(artifact_path) == fresh, (
        "regenerate with: .parcel/bin/python -m evals.nav_instruct.scene_truth "
        "--scene city_block_b --regenerate"
    )
