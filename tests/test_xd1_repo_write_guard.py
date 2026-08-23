"""The repo-write guard, proved. Card XD-1 (``scrum/20260822/task_14``).

``tests/_repo_write_guard.py`` is the check for the defect CLASS that stopped
the commit tier being flipped to ``-n auto``: a test that writes under the
repository root is correct alone and reddens its NEIGHBOURS at
one-worker-per-test (GATE-0's recorded instance, ``AUDIT_WEEK1_FABLE.md``).

The guard is only worth having if it goes red for the right reason and stays
quiet for every wrong one, so this file drives the classifier over the four
cases that decide a verdict — tracked, ignored, untracked-not-ignored, outside
the repo — and over the hot-path filter, whose first implementation exempted
``.github/`` by accident.

The hook is exercised as a function rather than installed: ``sys.addaudithook``
is irreversible by CPython's design, so a test that installed one would leave
it running for every later test in the worker. The WIRING (conftest fixture ->
recorder -> failure naming the test) is proved separately, on the product, by
the card's S1 seed: a real test that writes a real file, run under the real
conftest, whose failure names it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import _repo_write_guard as guard
import pytest

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# mode resolution — fail-closed, the way scripts/load_guard.py is
# ---------------------------------------------------------------------------


def test_the_default_mode_is_named_and_not_inferred() -> None:
    # The default is CENSUS, and it is a pre-registered decision, not a taste:
    # the D7 census named 10 offending tests in three files that belong to other
    # cards, and the rule written before the census said "ON iff empty".
    assert guard.read_mode({}) == guard.MODE_CENSUS
    assert guard.read_mode({guard.MODE_ENV: ""}) == guard.MODE_CENSUS
    assert guard.read_mode({guard.MODE_ENV: "on"}) == guard.MODE_ON
    assert guard.read_mode({guard.MODE_ENV: "  CENSUS "}) == guard.MODE_CENSUS
    assert guard.read_mode({guard.MODE_ENV: "off"}) == guard.MODE_OFF


def test_a_typo_refuses_to_choose_a_mode() -> None:
    """An unrecognised value silently meaning ``off`` is how a guard dies."""

    for typo in ("no", "true", "1", "ON=1", "cencus"):
        with pytest.raises(guard.RepoWriteGuardMisconfigured):
            guard.read_mode({guard.MODE_ENV: typo})


def test_the_refusal_names_the_value_and_the_valid_set() -> None:
    with pytest.raises(guard.RepoWriteGuardMisconfigured) as excinfo:
        guard.read_mode({guard.MODE_ENV: "yes"})
    message = str(excinfo.value)
    assert "'yes'" in message
    for mode in guard.VALID_MODES:
        assert mode in message


# ---------------------------------------------------------------------------
# the recorder's hot path
# ---------------------------------------------------------------------------


def _record(*calls: tuple[str, tuple]) -> dict[str, str]:
    recorder = guard.Recorder()
    recorder.start()
    for event, args in calls:
        recorder.hook(event, args)
    return recorder.stop()


def test_a_write_under_the_repo_is_recorded_with_its_mode() -> None:
    found = _record(("open", (str(REPO / "evals" / "scratch.json"), "w", None)))
    assert found == {"evals/scratch.json": "w"}


def test_a_read_is_not_a_write() -> None:
    assert _record(("open", (str(REPO / "README.md"), "r", None))) == {}
    assert _record(("open", (str(REPO / "README.md"), "rb", None))) == {}


def test_an_os_open_is_classified_by_its_flags_not_its_mode_string() -> None:
    path = str(REPO / "evals" / "scratch.json")
    assert _record(("open", (path, None, os.O_RDONLY))) == {}
    written = _record(("open", (path, None, os.O_WRONLY | os.O_CREAT)))
    assert list(written) == ["evals/scratch.json"]
    assert "os.open" in written["evals/scratch.json"]


#: The REAL argument tuples CPython emits, verified against the interpreter by
#: probe (see ``_PATH_ARGS`` in the guard). Feeding the recorder a plausible-
#: looking short tuple instead is how the src/dst and ``dir_fd`` defects below
#: survived the first draft of this file: the test agreed with the code because
#: both had made up the same shape.
def _target(name: str) -> str:
    return str(REPO / "evals" / name)


def test_the_path_events_that_create_or_move_are_recorded() -> None:
    cases = {
        "os.mkdir": ((_target("scratch"), 0o777, -1), "evals/scratch"),
        "os.rmdir": ((_target("scratch"), -1), "evals/scratch"),
        "os.remove": ((_target("scratch"), -1), "evals/scratch"),
        "os.truncate": ((_target("scratch"), 0), "evals/scratch"),
    }
    for event, (args, expected) in cases.items():
        assert _record((event, args)) == {expected: event}, event


def test_symlink_and_link_record_the_path_they_CREATE_not_the_one_they_read() -> None:
    """The created path is the SECOND argument. Recording the first named a
    path the test only read — and missed the write entirely when the source was
    outside the repo, which is the usual shape (``os.symlink("/usr/lib/x", …)``).
    """

    assert _record(("os.symlink", ("/usr/lib/libEGL.so", _target("libEGL.so"), -1))) == {
        "evals/libEGL.so": "os.symlink"
    }
    assert _record(
        ("os.link", ("/elsewhere/src", _target("hard"), -1, -1))
    ) == {"evals/hard": "os.link"}


def test_a_rename_changes_both_ends_and_both_are_recorded() -> None:
    found = _record(("os.rename", (_target("a"), _target("b"), -1, -1)))
    assert found == {"evals/a": "os.rename", "evals/b": "os.rename"}
    # ...and a rename OUT of the repo still names the end that is inside it.
    assert _record(("os.rename", (_target("a"), "/tmp/b", -1, -1))) == {
        "evals/a": "os.rename"
    }


def test_a_path_relative_to_a_dir_fd_is_not_charged_to_the_cwd() -> None:
    """THE REGRESSION (found by HY-1's executor, 2026-08-23).

    ``shutil.rmtree`` walks with ``dir_fd`` for safety, so the audit events
    carry BARE ENTRY NAMES. Resolving those against the process cwd charged
    every file of an ``rmtree`` of a ``tmp_path`` tree to the repository —
    because under pytest the cwd IS the repository. A dir_fd-relative path is
    not cwd-relative, and this module cannot resolve it, so it records nothing.
    """

    assert _record(("os.remove", ("a.txt", 7))) == {}
    assert _record(("os.mkdir", ("sub", 0o777, 7))) == {}
    assert _record(("os.symlink", ("src", "link2", 7))) == {}
    # ...while dir_fd == -1 (nobody passed one) is genuinely cwd-relative and
    # IS an offence: `robot.yaml` really was deleted from the repo root by a
    # test in the D7 census.
    assert _record(("os.remove", ("robot.yaml", -1))) == {"robot.yaml": "os.remove"}


def test_an_rmtree_of_a_tmp_path_tree_charges_the_repo_with_nothing(tmp_path) -> None:
    """The same regression END TO END, through the real audit hook, with the
    cwd set to the repository exactly as pytest leaves it."""

    import shutil

    (tmp_path / "scratch" / "sub").mkdir(parents=True)
    (tmp_path / "scratch" / "a.txt").write_text("x", encoding="utf-8")
    (tmp_path / "scratch" / "sub" / "b.txt").write_text("y", encoding="utf-8")

    recorder = guard.Recorder()
    calls: list[tuple[str, tuple]] = []
    original_cwd = os.getcwd()
    os.chdir(REPO)
    try:
        recorder.start()
        # Drive the recorder with the events the interpreter really emits.
        def spy(event: str, args: tuple) -> None:
            calls.append((event, args))

        sys.addaudithook(spy)
        shutil.rmtree(tmp_path / "scratch")
    finally:
        os.chdir(original_cwd)
    for event, args in calls:
        recorder.hook(event, args)
    charged = recorder.stop()

    assert charged == {}, f"an rmtree of a tmp tree was charged to the repo: {charged}"
    assert any(e == "os.remove" for e, _ in calls), "the probe saw no removals at all"


def test_a_write_outside_the_repo_is_not_our_business() -> None:
    assert _record(("open", ("/tmp/whatever.json", "w", None))) == {}
    assert _record(("open", (str(REPO.parent / "sibling.json"), "w", None))) == {}


def test_a_relative_path_is_resolved_against_the_cwd(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(REPO / "evals")
    assert _record(("open", ("scratch.json", "w", None))) == {"evals/scratch.json": "w"}
    monkeypatch.chdir(tmp_path)
    assert _record(("open", ("scratch.json", "w", None))) == {}


def test_an_fd_or_bytes_path_is_ignored_rather_than_crashing() -> None:
    assert _record(("open", (7, "w", None))) == {}
    assert _record(("open", (b"/repo/x", "w", None))) == {}
    assert _record(("os.mkdir", (7, 0o777, -1))) == {}
    assert _record(("os.symlink", ("/x", b"/repo/y", -1))) == {}


def test_an_inactive_recorder_records_nothing() -> None:
    recorder = guard.Recorder()
    recorder.hook("open", (str(REPO / "evals" / "scratch.json"), "w", None))
    recorder.start()
    assert recorder.stop() == {}


def test_the_hot_path_filter_matches_whole_directory_components_only() -> None:
    """The regression: ``".git" in ".github/…"`` exempted a TRACKED directory.

    ``.github/workflows/ci.yml`` is the hosted cadence this repo's gate
    declares; a test that rewrote it had to be nameable.
    """

    assert _record(("open", (str(REPO / "src" / "__pycache__" / "x.pyc"), "wb", None))) == {}
    assert _record(
        ("open", (str(REPO / ".github" / "workflows" / "ci.yml"), "w", None))
    ) == {".github/workflows/ci.yml": "w"}


# ---------------------------------------------------------------------------
# classification — git is the oracle, this module owns no allowlist
# ---------------------------------------------------------------------------


def test_a_tracked_file_is_an_offence() -> None:
    assert guard.offences({"README.md": "w"}) == {"README.md": "w"}


def test_an_ignored_path_is_not_an_offence() -> None:
    """``.gitignore`` is the authority — `/recordings/` is ignored there."""

    assert guard.offences({"recordings/session.wav": "w"}) == {}


def test_an_untracked_path_git_would_notice_is_an_offence() -> None:
    """The GATE-0 shape: a NEW file in a tracked directory, no rule covering it."""

    assert guard.offences({"evals/xd1-not-a-real-file.json": "w"}) == {
        "evals/xd1-not-a-real-file.json": "w"
    }


def test_the_empty_batch_never_calls_git() -> None:
    """On a clean tree the classifier must cost nothing at all."""

    calls: list[list[str]] = []

    original = guard._git
    guard._git = lambda args, stdin=None: calls.append(args)  # type: ignore[assignment]
    try:
        assert guard.offences({}) == {}
    finally:
        guard._git = original  # type: ignore[assignment]
    assert calls == []


def test_the_hot_path_filter_is_a_speed_trick_and_not_an_exemption_table() -> None:
    """Standing rule 1: no new allowlist. The exemptions live in ``.gitignore``.

    Proved behaviourally, not by reading the source: every ``_HOT_SKIP`` entry
    is ALREADY ignored by ``.gitignore``, so deleting the filter would change
    no verdict — only speed. The day one of them stops being ignored, this test
    reddens and the filter has to be re-argued.
    """

    for name in ("__pycache__", ".pytest_cache", ".hypothesis", ".ruff_cache"):
        assert guard.offences({f"{name}/probe": "w"}) == {}, name
    # And the one that was NOT covered, and so was removed from the filter
    # rather than kept as a private exemption: git does not report its own
    # metadata directory as ignored, so the guard must be able to name it.
    assert guard.offences({".git/probe": "w"}) == {".git/probe": "w"}


# ---------------------------------------------------------------------------
# the second net, and the report
# ---------------------------------------------------------------------------


def test_session_residue_is_the_lines_a_run_added() -> None:
    before = " M src/a.py\n M src/b.py\n"
    after = " M src/a.py\n M src/b.py\n?? scratch.json\n"
    assert guard.session_residue(before, after) == ["?? scratch.json"]
    assert guard.session_residue(after, before) == []


def test_the_report_names_the_test_the_path_and_the_mode() -> None:
    report = guard.format_report(
        "tests/test_x.py::test_y", {"evals/scratch.json": "w"}
    )
    assert "tests/test_x.py::test_y" in report
    assert "evals/scratch.json" in report
    assert "(opened w)" in report
    assert guard.OWNER in report
    assert guard.MODE_ENV in report, "a failure must say how to downgrade it"
    assert "tmp_path" in report, "and what to do instead"
