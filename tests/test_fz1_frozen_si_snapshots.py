"""FZ-1 — a historical SI version renders from its snapshot, not the live files.

Card ``scrum/20260822/task_13``. On 2026-08-22 the owner added a one-line
identity prelude to each ``prompts/personalities/*.yaml``. Ten pins reddened;
eight were the current version and were answered by the intended mechanism (bump
``SI_VERSION``, register the new digests — ``SI_V3``). Two could not be answered
that way at all: ``test_the_v1_si_still_renders_to_its_v1_pins`` and
``test_the_corpus_capture_version_is_still_rendered_by_this_tree`` assert that a
HISTORICAL version is still reproducible from source, and re-pinning them to the
new text would have falsified the provenance of a 25-thread, 52-query voice
corpus. They were carried as ``xfail(strict=True)`` naming this card; this file
is the guard that lets them come back.

HOW EVERY ROW HERE IS MEASURED
------------------------------
Through ``render_system_instruction`` — the product's own renderer — comparing
**digests of rendered text**. Nothing here greps source, asserts that a path
equals itself, or re-implements the composition. The wave's lesson (see the
verifier's note on seeds proving guards rather than integration) is that a guard
which does not run the product's resolution path is not a guard.

The seed is applied to a SANDBOX prompts tree rather than to the repository's
own ``prompts/``: several agent sessions share this working tree, and a test
that mutates a tracked persona file — even with a ``finally`` restore — is a
live hazard to every other session and to the owner's running stack.
``PARCEL_ROOT`` is exactly the seam the product already uses to relocate its
assets (``parcel_robot.paths.parcel_roots``), so pointing it at a copy exercises
the same resolution a wheel would take.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from parcel_robot.paths import packaged_assets_root, parcel_roots
from parcel_robot.prompting.loader import PromptLibrary
from parcel_robot.realtime.prompting import (
    FROZEN_PERSONAS_DIRNAME,
    SI_DIGESTS,
    SI_V1,
    SI_V2,
    SI_VERSION,
    PromptPlaneError,
    frozen_personas_dir,
    prompts_root,
    render_system_instruction,
    si_pin,
)

REPO = Path(__file__).resolve().parents[1]
LIVE_PERSONAS = REPO / "prompts" / "personalities"
FREEZE_TOOL = REPO / "tools" / "freeze_si_version.py"

#: Every version in the registry that is NOT the one the live files render.
HISTORICAL = tuple(version for version in sorted(SI_DIGESTS) if version != SI_VERSION)

#: The seed: one line appended to a live persona YAML, in the shape of the edit
#: that actually happened (a prose line inside ``instruction``). It is a real
#: persona edit, not a corrupting byte, so a renderer that reads it still
#: produces valid text — which is what makes the "did the digest move" question
#: meaningful rather than an exception.
SEED_LINE = "  You also always mention the weather when you greet someone.\n"


def _remove_dir(path: Path) -> None:
    """Delete a directory tree with ABSOLUTE unlinks, never ``shutil.rmtree``.

    ``shutil.rmtree`` deletes through directory file descriptors, so the path it
    hands Python's audit hook is a bare filename. The repository write guard
    (``tests/_repo_write_guard.py``, card XD-1) resolves that with
    ``os.path.abspath`` against the process cwd — the repo root — and reports a
    write under the repository that never happened, for a delete inside
    ``tmp_path``. Absolute unlinks keep that report truthful.
    """

    for child in sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if child.is_file() or child.is_symlink():
            child.unlink()
        else:
            child.rmdir()
    path.rmdir()


def _sandbox(tmp_path: Path) -> Path:
    """A byte-for-byte copy of ``prompts/`` — snapshots included."""

    root = tmp_path / "tree"
    root.mkdir()
    shutil.copytree(REPO / "prompts", root / "prompts")
    return root


@pytest.fixture
def prompts_sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the whole product at a copy of ``prompts/`` and yield that copy."""

    root = _sandbox(tmp_path)
    monkeypatch.setenv("PARCEL_ROOT", str(root))
    parcel_roots.cache_clear()
    try:
        yield root / "prompts"
    finally:
        parcel_roots.cache_clear()


def _seed_live_persona(prompts: Path, profile_id: str) -> None:
    """Edit a live persona file the way the owner did, in the sandbox only."""

    path = prompts / "personalities" / f"{profile_id}.yaml"
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for index, line in enumerate(lines):
        if line.startswith("reply_style:"):
            lines.insert(index, SEED_LINE)
            break
    else:  # pragma: no cover - the shipped personas all have reply_style
        raise AssertionError(f"{path} has no reply_style block to seed above")
    path.write_text("".join(lines), encoding="utf-8")


def _digest(profile_id: str, version: str) -> str:
    return render_system_instruction(profile_id=profile_id, version=version).digest


def _personality_ids() -> tuple[str, ...]:
    return tuple(sorted(SI_DIGESTS[SI_VERSION]))


# ------------------------------------------------------- the resolution rule
def test_the_sandbox_really_is_the_tree_under_test(prompts_sandbox: Path) -> None:
    """Guard on the guard: if PARCEL_ROOT did not take, every row below is vacuous."""

    assert prompts_root() == prompts_sandbox.resolve()
    assert prompts_sandbox.resolve() != (REPO / "prompts").resolve()


def test_the_current_version_still_renders_from_the_live_persona_files(
    prompts_sandbox: Path,
) -> None:
    """Row 1. The live files are the source for exactly one version: today's.

    Unseeded, the current version renders byte-identically to what this tree
    pins. Seeded, it MOVES — which is the property the existing ``SI_DIGESTS``
    pin test depends on and the reason the current version must NOT be served
    from a snapshot.
    """

    for profile_id in _personality_ids():
        assert _digest(profile_id, SI_VERSION) == si_pin(profile_id, version=SI_VERSION), profile_id

    _seed_live_persona(prompts_sandbox, "gentle_companion")

    moved = _digest("gentle_companion", SI_VERSION)
    assert moved != si_pin("gentle_companion", version=SI_VERSION), (
        "an edit to a live persona file did not move the CURRENT version's render; "
        "the current version is being served from something other than the live files"
    )
    for profile_id in _personality_ids():
        if profile_id != "gentle_companion":
            assert _digest(profile_id, SI_VERSION) == si_pin(profile_id, version=SI_VERSION)


@pytest.mark.parametrize("version", HISTORICAL)
def test_a_historical_version_ignores_an_edit_to_the_live_persona_file(
    version: str, prompts_sandbox: Path
) -> None:
    """THE row. A persona edit must not move what a historical version renders.

    This is the 2026-08-22 defect stated as an executable claim: before FZ-1 the
    seed below moved v1's digest and broke the corpus's provenance. The digest
    is compared to the registry value that has been pinned since the capture —
    not to a value re-derived in this test, which would move with the bug.
    """

    before = {profile_id: _digest(profile_id, version) for profile_id in _personality_ids()}
    assert before == dict(SI_DIGESTS[version]), f"{version} did not start reproducible"

    _seed_live_persona(prompts_sandbox, "gentle_companion")
    _seed_live_persona(prompts_sandbox, "calm_guardian")
    _seed_live_persona(prompts_sandbox, "playful_companion")

    after = {profile_id: _digest(profile_id, version) for profile_id in _personality_ids()}
    assert after == dict(SI_DIGESTS[version]), (
        f"editing the LIVE persona files moved what {version} renders. A historical "
        f"version must come from prompts/personalities/{FROZEN_PERSONAS_DIRNAME}/{version}/."
    )
    # And the seed genuinely took: the current version did move.
    assert _digest("gentle_companion", SI_VERSION) != si_pin("gentle_companion")


def test_every_registered_version_is_reproducible_from_its_snapshot_alone(
    prompts_sandbox: Path,
) -> None:
    """Row 3. Delete every live persona file; the history still renders.

    "From the snapshots alone" is only demonstrated when the live files are not
    there to be read. Deleting them also proves the control: the CURRENT version
    then cannot render at all, so the previous row's pass was not an artefact of
    the live and frozen bytes happening to agree.
    """

    for path in sorted((prompts_sandbox / "personalities").glob("*.yaml")):
        path.unlink()

    for version in HISTORICAL:
        for profile_id in sorted(SI_DIGESTS[version]):
            assert _digest(profile_id, version) == SI_DIGESTS[version][profile_id], (
                f"{version}/{profile_id} is not reproducible from its snapshot alone"
            )

    with pytest.raises(FileNotFoundError):
        _digest("gentle_companion", SI_VERSION)


def test_the_current_version_is_already_frozen_for_the_next_bump() -> None:
    """Row 4. The snapshot for today's version exists and equals the live bytes.

    Freezing happens at bump time, not at retirement time: when the next version
    lands, this one must already have the text it actually shipped with. A
    snapshot written later — after the personas moved again — would record the
    wrong words under the right label, which is precisely the falsification this
    card refused to commit.
    """

    snapshot = frozen_personas_dir(SI_VERSION, prompts_root=REPO / "prompts")
    assert snapshot.is_dir(), f"{SI_VERSION} has no snapshot at {snapshot}"
    live = sorted(LIVE_PERSONAS.glob("*.yaml"))
    assert {path.name for path in live} == {path.name for path in snapshot.glob("*.yaml")}
    for path in live:
        assert (snapshot / path.name).read_bytes() == path.read_bytes(), path.name


def test_a_wheel_can_still_render_every_historical_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The snapshots must SHIP, not only exist in the checkout.

    ``runtime_assets/`` is what a wheel carries; ``paths.resolve_prompts_root``
    falls through to it when no repo tree is present. If the frozen dirs were
    left out of the ship set, a packaged install would resolve
    ``version="si-companion-v1"`` to a missing snapshot and refuse — the corpus
    would be verifiable from a checkout and unverifiable from the product. This
    renders history against the PACKAGED root, the way an installed wheel does.
    """

    packaged = packaged_assets_root()
    monkeypatch.setenv("PARCEL_ROOT", str(packaged))
    parcel_roots.cache_clear()
    try:
        assert prompts_root() == (packaged / "prompts").resolve()
        for version in HISTORICAL:
            for profile_id in sorted(SI_DIGESTS[version]):
                assert _digest(profile_id, version) == SI_DIGESTS[version][profile_id], (
                    f"{version}/{profile_id} does not render from the packaged tree"
                )
    finally:
        parcel_roots.cache_clear()


# ------------------------------------------------------------- the refusals
def test_a_historical_version_without_a_snapshot_refuses_by_name(
    prompts_sandbox: Path,
) -> None:
    """A missing snapshot must never fall back to the live files.

    The fall-back is the bug. A version with no frozen text has nothing this
    tree can honestly claim to reproduce, so the render says so and names the
    tool that fixes it rather than quietly rendering today's personas under a
    2026-08-17 label.
    """

    _remove_dir(prompts_sandbox / "personalities" / FROZEN_PERSONAS_DIRNAME / SI_V1)

    with pytest.raises(PromptPlaneError) as caught:
        _digest("gentle_companion", SI_V1)
    message = str(caught.value)
    assert SI_V1 in message
    assert "tools/freeze_si_version.py" in message
    # The other historical version is untouched: the refusal is per-version.
    assert _digest("gentle_companion", SI_V2) == si_pin("gentle_companion", version=SI_V2)


def test_an_unregistered_version_still_refuses_at_the_guardrails_first() -> None:
    """The pre-FZ-1 refusal ordering is preserved.

    ``si-companion-v99`` has no text at all. It must keep failing with "no
    guardrails text" — the message that tells an author what to register —
    rather than with a missing-snapshot message for a version that was never
    going to have one.
    """

    with pytest.raises(PromptPlaneError) as caught:
        render_system_instruction(profile_id="gentle_companion", version="si-companion-v99")
    message = str(caught.value)
    assert "no guardrails text" in message
    assert FROZEN_PERSONAS_DIRNAME not in message


def test_an_explicit_library_cannot_resurrect_the_live_files_for_history(
    prompts_sandbox: Path,
) -> None:
    """Passing ``library=`` selects the live source, and history has none.

    Callers hand in a ``PromptLibrary`` (``evals/…/build_manifest.py``, the
    corpus tests). If that library could override the snapshot, the whole
    property would be one keyword argument away from being false.
    """

    _seed_live_persona(prompts_sandbox, "gentle_companion")
    live = PromptLibrary(prompts_sandbox)

    for version in HISTORICAL:
        rendered = render_system_instruction(
            profile_id="gentle_companion", library=live, version=version
        )
        assert rendered.digest == si_pin("gentle_companion", version=version), version


def test_the_frozen_snapshots_are_not_listed_as_shipped_personalities() -> None:
    """``_frozen`` must not leak into the library's own personality list.

    ``test_every_personality_in_the_repo_is_pinned`` walks
    ``list_personalities()`` and demands a pin for each. A snapshot directory
    appearing there would demand pins for nine phantom personalities.
    """

    listed = {profile.id for profile in PromptLibrary(REPO / "prompts").list_personalities()}
    assert listed == set(_personality_ids())


# ---------------------------------------------------------------- the tool
def _run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(FREEZE_TOOL), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO),
        check=False,
    )


def test_freeze_si_version_check_reproduces_every_pin_on_this_tree() -> None:
    """Row 7. The registry is re-derivable from the snapshots, by the tool."""

    result = _run_tool("--check")
    assert result.returncode == 0, result.stderr
    pinned = sum(len(pins) for pins in SI_DIGESTS.values())
    assert f"{pinned} pinned digest(s)" in result.stdout


def test_freeze_si_version_writes_a_snapshot_and_prints_its_digests(
    tmp_path: Path,
) -> None:
    """Row 8. The freezer copies bytes and reports what those bytes render to.

    Run against a sandbox prompts tree so the repository's own snapshots are
    never rewritten by a test.
    """

    root = _sandbox(tmp_path)
    prompts = root / "prompts"
    target = frozen_personas_dir(SI_VERSION, prompts_root=prompts)
    _remove_dir(target)

    result = _run_tool("--version", SI_VERSION, "--prompts-root", str(prompts))
    assert result.returncode == 0, result.stderr

    live = sorted((prompts / "personalities").glob("*.yaml"))
    assert {path.name for path in live} == {path.name for path in target.glob("*.yaml")}
    for path in live:
        assert (target / path.name).read_bytes() == path.read_bytes()
    for profile_id, digest in sorted(SI_DIGESTS[SI_VERSION].items()):
        assert f'"{profile_id}": "{digest}",' in result.stdout


def test_the_freezer_measures_drift_against_the_tree_it_was_pointed_at(
    tmp_path: Path,
) -> None:
    """``--prompts-root`` must govern the tool's own closing check too.

    ``--version <current>`` ends by asking whether the LIVE files still render
    what the snapshot just recorded. Resolving that live library from the
    DEFAULT prompts root instead of the named one compares this tree's snapshot
    against the REPOSITORY's personas — so an operator freezing any tree whose
    personas differ from the checkout's (a release branch, a packaged root, this
    file's sandbox) is told the freeze drifted when it did not, and the tool
    exits 1 on a correct snapshot. The sandbox is seeded first precisely so the
    two trees disagree; only a root-correct check can stay quiet.
    """

    prompts = _sandbox(tmp_path) / "prompts"
    _seed_live_persona(prompts, "gentle_companion")

    result = _run_tool("--version", SI_VERSION, "--prompts-root", str(prompts), "--force")
    assert result.returncode == 0, result.stderr
    assert "no longer render" not in result.stderr

    frozen = frozen_personas_dir(SI_VERSION, prompts_root=prompts) / "gentle_companion.yaml"
    live = prompts / "personalities" / "gentle_companion.yaml"
    assert frozen.read_bytes() == live.read_bytes()
    assert SEED_LINE in frozen.read_text(encoding="utf-8")


def test_freeze_si_version_refuses_to_rewrite_an_existing_snapshot(tmp_path: Path) -> None:
    """A snapshot is a record. Overwriting one re-attributes captured sessions."""

    prompts = _sandbox(tmp_path) / "prompts"
    result = _run_tool("--version", SI_V1, "--prompts-root", str(prompts))
    assert result.returncode == 2
    assert "already frozen" in result.stderr

    forced = _run_tool("--version", SI_V1, "--prompts-root", str(prompts), "--force")
    assert forced.returncode == 0, forced.stderr


def test_freeze_si_version_refuses_a_version_with_no_registered_guardrails(
    tmp_path: Path,
) -> None:
    """Snapshotting personas for a version that cannot render is a no-op record."""

    prompts = _sandbox(tmp_path) / "prompts"
    result = _run_tool("--version", "si-companion-v99", "--prompts-root", str(prompts))
    assert result.returncode == 2
    assert "no guardrails text" in result.stderr
    assert not frozen_personas_dir("si-companion-v99", prompts_root=prompts).exists()
