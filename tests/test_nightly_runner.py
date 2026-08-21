"""The nightly runner's contract. Card R26, work items 1 and 2.

The audit's finding was not that the nightly was broken. It was that the nightly
had **never produced a recorded run**, so nobody could tell. Everything here is
therefore about the properties that make a run RECORDED and BELIEVABLE:

* the failure exit code is not swallowed (the card's named RED seed);
* the evidence folder is written even — especially — when the run is red;
* the folder names every red stage rather than publishing only the greens;
* the ledger gains exactly one row per run, so "has the nightly ever run" is a
  question the repository can answer without a human;
* the deselected tier is really in the nightly's stage list, under the same
  marker constant the tier-coverage gate reads.

The stages themselves are monkeypatched: this file tests the RUNNER, and running
the real nightly inside the commit tier would take forty minutes and defeat the
purpose of having tiers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_nightly as runner
from scripts.ci_gate import COMMIT_MARKERS, NIGHTLY_ENV, NIGHTLY_SLOW_MARKERS, GateResult


def _stub_stages(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gate: list[GateResult] | None = None,
    sweep: GateResult | None = None,
) -> None:
    gate_results = gate if gate is not None else [
        GateResult("default-suite", "nightly", True, "pass", "7442 passed"),
        GateResult("slow-suite", "nightly", True, "pass", "42 passed"),
    ]
    monkeypatch.setattr(
        runner, "stage_gate", lambda: (gate_results, "CI GATE — tier=nightly\nstub", 1.0)
    )
    monkeypatch.setattr(
        runner,
        "stage_future_clock",
        lambda days, **kwargs: sweep
        or GateResult("future-clock-sweep", "nightly", True, "pass", f"+{days}d clean"),
    )
    monkeypatch.setattr(
        runner,
        "stage_assertion_nightly",
        lambda **kwargs: GateResult("assertion-nightly", "nightly", False, "report", "stub"),
    )


# --- the exit code -----------------------------------------------------------


def test_a_red_hard_stage_produces_a_non_zero_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE seed the card names: "the nightly's failure exit-code swallowed"."""

    _stub_stages(
        monkeypatch,
        gate=[GateResult("slow-suite", "nightly", True, "fail", "2 failed, 26 passed")],
    )
    assert runner.main(["--out", str(tmp_path)]) == 1


def test_a_green_run_exits_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_stages(monkeypatch)
    assert runner.main(["--out", str(tmp_path)]) == 0


def test_a_red_report_only_stage_does_not_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """EV-1's judge measured 2 false positives a run; it must never gate."""

    _stub_stages(monkeypatch)
    monkeypatch.setattr(
        runner,
        "stage_assertion_nightly",
        lambda **kwargs: GateResult("assertion-nightly", "nightly", False, "fail", "judge 500"),
    )
    assert runner.main(["--out", str(tmp_path)]) == 0
    payload = _latest(tmp_path)
    assert payload["soft_red"] == ["assertion-nightly"]
    assert payload["gating_red"] == []


def test_allow_red_is_the_only_way_to_swallow_and_it_announces_itself(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _stub_stages(
        monkeypatch, gate=[GateResult("slow-suite", "nightly", True, "fail", "2 failed")]
    )
    assert runner.main(["--out", str(tmp_path), "--allow-red"]) == 0
    printed = capsys.readouterr().out
    assert "--allow-red" in printed and "RETURNING 0" in printed
    # The artifact still records the truth, whatever the exit code says.
    assert _latest(tmp_path)["verdict"] == "FAIL"
    assert _latest(tmp_path)["exit_code"] == 1


# --- the evidence ------------------------------------------------------------


def _latest(root: Path) -> dict:
    folders = [p for p in root.iterdir() if p.is_dir()]
    assert folders, f"no run folder was written under {root}"
    newest = max(folders, key=lambda path: path.name)
    return json.loads((newest / "results.json").read_text(encoding="utf-8"))


def test_a_red_run_still_leaves_its_evidence_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nightly that only writes a folder when it is green is a press release."""

    _stub_stages(
        monkeypatch,
        gate=[GateResult("slow-suite", "nightly", True, "fail", "2 failed, 26 passed")],
    )
    runner.main(["--out", str(tmp_path)])
    folder = max((p for p in tmp_path.iterdir() if p.is_dir()), key=lambda path: path.name)
    assert (folder / "results.json").is_file()
    assert (folder / "README.md").is_file()
    assert (folder / "gate.txt").is_file()
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert "2 failed, 26 passed" in readme, "the README must name what went red"
    assert "## What went red" in readme


def test_the_folder_is_dated_and_the_ledger_gains_one_row_per_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_stages(monkeypatch)
    runner.main(["--out", str(tmp_path)])
    runner.main(["--out", str(tmp_path)])
    ledger = tmp_path / runner.LEDGER_NAME
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 2
    for row in rows:
        assert row["run"].endswith("Z") and len(row["run"]) == 16, row["run"]
        assert row["verdict"] in {"PASS", "FAIL"}
        assert "git_head" in row and "git_dirty" in row
        assert (tmp_path / row["run"]).is_dir()


def test_the_run_records_the_tree_it_ran_on_including_dirt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wave is largely uncommitted; a bare HEAD sha would misattribute."""

    _stub_stages(monkeypatch)
    runner.main(["--out", str(tmp_path)])
    env = _latest(tmp_path)["environment"]
    assert set(env) >= {"git_head", "git_dirty", "git_dirty_paths", "python", "load_at_start"}
    assert isinstance(env["git_dirty"], bool)
    assert env["git_dirty"] is (len(env["git_dirty_paths"]) > 0)


# --- the deselected tier is really in there ---------------------------------


def test_disabling_the_sweep_records_an_error_rather_than_omitting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing stage must not read as a green stage."""

    _stub_stages(monkeypatch)
    assert runner.main(["--out", str(tmp_path), "--no-future-clock"]) == 1
    payload = _latest(tmp_path)
    sweep = [row for row in payload["stages"] if row["name"] == "future-clock-sweep"]
    assert len(sweep) == 1
    assert sweep[0]["status"] == "error" and sweep[0]["hard"] is True


def test_the_nightly_tier_runs_the_deselected_tier_under_the_shared_constant() -> None:
    """The seed: "a deselected test silently dropped from the nightly"."""

    import inspect

    from scripts import ci_gate

    source = inspect.getsource(ci_gate.run_nightly_tier)
    assert "NIGHTLY_SLOW_MARKERS" in source, (
        "the nightly must select the deselected tier through the same constant the "
        "tier-coverage gate reads, or the two can disagree in silence"
    )
    assert '"slow-suite"' in source
    assert NIGHTLY_SLOW_MARKERS == "slow"
    assert COMMIT_MARKERS == "not slow"
    assert NIGHTLY_ENV["PARCEL_NIGHTLY"] == "1"


def test_the_sweep_stage_is_hard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A report-only time-bomb sweep is a sweep nobody acts on."""

    _stub_stages(
        monkeypatch,
        sweep=GateResult("future-clock-sweep", "nightly", True, "fail", "+400d: 1 failed"),
    )
    assert runner.main(["--out", str(tmp_path)]) == 1
    assert "future-clock-sweep" in _latest(tmp_path)["gating_red"]


def test_the_scheduled_workflow_invokes_the_recording_runner() -> None:
    """The cron must call the runner that WRITES evidence, not the bare gate.

    Card R26's finding in one assertion. ``ci.yml`` declared an 08:00 UTC nightly
    from 2026-08-09 and ran ``ci_gate.py --tier nightly``, whose only output is
    terminal scrollback — which is why "the nightly has never produced a recorded
    run" was true and undetectable at the same time. Reverting this line would
    restore that state silently, so it is pinned.
    """

    import yaml

    repo = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((repo / ".github" / "workflows" / "ci.yml").read_text("utf-8"))
    steps = workflow["jobs"]["nightly-gate"]["steps"]

    runs = " ".join(str(step.get("run", "")) for step in steps)
    assert "scripts/run_nightly.py" in runs, (
        "the scheduled nightly must invoke scripts/run_nightly.py; ci_gate.py alone "
        "leaves no dated folder and no ledger row"
    )
    assert "--allow-red" not in runs, "CI must never swallow a red nightly"

    upload = [step for step in steps if "upload-artifact" in str(step.get("uses", ""))]
    assert upload, "the run folder must leave the runner as a workflow artifact"
    assert "evals/nightly" in str(upload[0]["with"]["path"])
    assert str(upload[0].get("if", "")).strip() == "always()", (
        "a RED nightly is exactly the run whose evidence matters; upload it anyway"
    )


def test_the_dirty_path_list_keeps_whole_paths() -> None:
    """Regression: ``git status --porcelain``'s first column is significant.

    ``_git`` used ``.strip()``, which ate the leading space of the first porcelain
    line (an unstaged modification is ``" M path"``), so the first entry of
    ``git_dirty_paths`` lost its first character — ``onfigs/realtime.yaml.example``
    in the first recorded nightly. Provenance that is wrong by one character is
    provenance a future reader cannot grep for.
    """

    env = runner.environment()
    repo = Path(__file__).resolve().parents[1]
    for relpath in env["git_dirty_paths"]:
        assert not relpath.startswith(" "), relpath
        assert (repo / relpath).exists(), (
            f"{relpath!r} is not a path in this tree — the porcelain column offset is wrong"
        )
