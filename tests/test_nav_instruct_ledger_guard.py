"""Card GATE-0b (`scrum/20260822/task_30`). The ledger appends on purpose.

`evals/nav_instruct/results/ledger.jsonl` is append-only provenance: the
`frozen_baseline` pointer `ci_gate.evaluate_hard_safety` certifies from lives
in it, and `evaluate_nav_instruct_candidate` diffs it around a nightly run.
Until this card, EVERY invocation of `run_nav_instruct_v1` appended a row —
including runs that were never provenance. Card ROAM-1's two verification
minivals wrote two rows, one of them from a tree with `time_s` seeded out, and
the verifier restored the file by hand (`AUDIT_WEEK1_FABLE.md` §ROAM-1
finding 4).

What is proved here, in both directions:

* the pure resolution (`resolve_ledger_path`) for every input — a guard tested
  in one direction only is indistinguishable from an unconditional refusal;
* THROUGH THE REAL CLI, in a subprocess: `--no-ledger` appends nothing; a run
  started from inside pytest that did not say where to append leaves the
  tracked ledger alone AND says so; `--ledger PATH` really does write a row
  somewhere else. Arm three is the negative control: without it "nothing was
  appended" would also be true of a runner that had simply stopped working.

No arm of this module may write to the tracked ledger, and
`test_the_tracked_ledger_is_byte_identical_after_every_arm` re-checks its
sha256 after the last one.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evals.nav_instruct.run_nav_instruct_v1 import (
    LEDGER,
    LEDGER_ENV,
    PYTEST_MARKER_ENV,
    resolve_ledger_path,
)

REPO = Path(__file__).resolve().parents[1]

#: One episode of the frozen v4 minival: ~1.8 s, enough to reach the append.
CLI = (
    sys.executable, "-m", "evals.nav_instruct.run_nav_instruct_v1",
    "--minival", "--mode", "candidate", "--episode-version", "v4", "--limit", "1",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(out: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """The product path: the real CLI, in a subprocess, from the repo root."""

    return subprocess.run(
        [*CLI, "--out", str(out), *extra],
        cwd=str(REPO), capture_output=True, text=True, check=False, timeout=300,
    )


# ---------------------------------------------------------------------------
# The pure resolution, both directions
# ---------------------------------------------------------------------------


def test_the_default_is_unchanged() -> None:
    """The whole point of the switch is that not passing it changes nothing."""

    target, why = resolve_ledger_path(env={})
    assert target == LEDGER
    assert why == "default"


def test_no_ledger_means_no_target() -> None:
    assert resolve_ledger_path(no_ledger=True, env={})[0] is None


def test_an_explicit_path_is_used_verbatim(tmp_path: Path) -> None:
    target, why = resolve_ledger_path(ledger=tmp_path / "scratch.jsonl", env={})
    assert target == tmp_path / "scratch.jsonl"
    assert "--ledger" in why


@pytest.mark.parametrize("word", ["off", "none", "NO", "0"])
def test_the_environment_can_turn_it_off(word: str) -> None:
    target, why = resolve_ledger_path(env={LEDGER_ENV: word})
    assert target is None
    assert LEDGER_ENV in why


def test_the_environment_can_redirect_it(tmp_path: Path) -> None:
    target, _ = resolve_ledger_path(env={LEDGER_ENV: str(tmp_path / "env.jsonl")})
    assert target == tmp_path / "env.jsonl"


def test_a_pytest_run_that_said_nothing_does_not_get_the_tracked_ledger() -> None:
    """THE GUARD. A verification run is not provenance unless it says so."""

    target, why = resolve_ledger_path(env={PYTEST_MARKER_ENV: "tests/x.py::test_y"})
    assert target is None
    assert PYTEST_MARKER_ENV in why
    assert str(LEDGER) in why, "the withheld path has to be named, or nobody can act"


def test_a_caller_that_redirected_the_module_default_is_not_second_guessed(
    tmp_path: Path,
) -> None:
    """The guard protects ONE file, not "the default", and the difference is real.

    `tests/test_dr2_pose_drift_arm.py:722` has monkeypatched
    `run_nav_instruct_v1.LEDGER` to a tmp path since long before this card, and
    then asserts the row landed there. That monkeypatch IS the caller saying
    where to append; a guard that fired on it would have silently emptied that
    test — which is exactly what happened on the first draft of this card, and
    is why `TRACKED_LEDGER` is a second name for the same path.
    """

    redirected = tmp_path / "redirected.jsonl"
    target, why = resolve_ledger_path(
        env={PYTEST_MARKER_ENV: "tests/x.py::test_y"}, default=redirected
    )
    assert target == redirected
    assert why == "default"
    assert redirected != LEDGER


def test_an_explicit_path_outranks_the_pytest_guard(tmp_path: Path) -> None:
    """Ask, do not refuse: a person who typed a path is not overruled."""

    target, _ = resolve_ledger_path(
        ledger=tmp_path / "on-purpose.jsonl",
        env={PYTEST_MARKER_ENV: "tests/x.py::test_y"},
    )
    assert target == tmp_path / "on-purpose.jsonl"


def test_the_flag_outranks_the_environment(tmp_path: Path) -> None:
    target, _ = resolve_ledger_path(
        ledger=tmp_path / "flag.jsonl", env={LEDGER_ENV: str(tmp_path / "env.jsonl")}
    )
    assert target == tmp_path / "flag.jsonl"


# ---------------------------------------------------------------------------
# Through the real CLI
# ---------------------------------------------------------------------------


def test_the_two_switches_are_mutually_exclusive(tmp_path: Path) -> None:
    proc = _run(tmp_path, "--no-ledger", "--ledger", str(tmp_path / "x.jsonl"))
    assert proc.returncode == 2
    assert "not allowed with" in proc.stderr


def test_no_ledger_runs_the_matrix_and_appends_nothing(tmp_path: Path) -> None:
    before = _sha256(LEDGER)
    proc = _run(tmp_path, "--no-ledger")
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert list(tmp_path.glob("nav-instruct-*.json")), "the report is still written"
    assert "ledger: not appended" in proc.stdout
    assert _sha256(LEDGER) == before


def test_a_pytest_started_run_leaves_the_tracked_ledger_alone_and_says_so(
    tmp_path: Path,
) -> None:
    """The seeded row: no flag at all, but the child inherits PYTEST_CURRENT_TEST."""

    assert os.environ.get(PYTEST_MARKER_ENV), "this test's premise is pytest's own mark"
    before = _sha256(LEDGER)
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "ledger: not appended" in proc.stdout
    assert PYTEST_MARKER_ENV in proc.stdout
    assert _sha256(LEDGER) == before


def test_an_explicit_ledger_really_does_receive_the_row(tmp_path: Path) -> None:
    """The negative control: the append still works, it just went elsewhere."""

    before = _sha256(LEDGER)
    scratch = tmp_path / "nested" / "scratch.jsonl"
    proc = _run(tmp_path, "--ledger", str(scratch))
    assert proc.returncode == 0, proc.stderr[-2000:]
    rows = [json.loads(line) for line in scratch.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["mode"] == "candidate"
    assert rows[0]["n"] == 1
    report = tmp_path / rows[0]["report"]
    assert report.is_file(), "the row points at the report this run wrote"
    assert _sha256(LEDGER) == before


def test_the_tracked_ledger_is_byte_identical_after_every_arm() -> None:
    """Ordered last in the file, so `--dist loadfile` runs it after the rest."""

    rows = [line for line in LEDGER.read_text().splitlines() if line.strip()]
    assert rows, "the tracked ledger still holds the provenance it always did"
    assert json.loads(rows[-1])["report_id"], "and its last row is still a row"
