from __future__ import annotations

import json
import math
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evals.external import ledger
from evals.external.ledger import (
    DuplicateRunError,
    GitState,
    LedgerError,
    iter_ledger,
    record_evaluation_run,
    sha256_file,
)


def _report(tmp_path: Path) -> Path:
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps({"aggregate": {"success_rate": 0.42, "spl": 0.31}}) + "\n",
        encoding="utf-8",
    )
    return path


def _record(tmp_path: Path, **overrides: object):
    arguments: dict[str, object] = {
        "benchmark_id": "barn-public-map-nav",
        "benchmark_source": "https://github.com/example/barn",
        "benchmark_source_commit": "benchmark-commit-123",
        "change_description": "Initial Parcel adapter baseline.",
        "aggregate_metrics": {"success_rate": 0.42, "spl": 0.31},
        "report_path": _report(tmp_path),
        "ledger_dir": tmp_path / "ledger",
        "git_state": GitState(commit="parcel-commit-456", dirty=True),
        "run_id": "baseline-001",
        "timestamp_utc": datetime(2026, 8, 3, 15, 4, 5, 6, tzinfo=timezone.utc),
        "agent_id": "ParcelRuntimePolicy",
        "agent_hash": "agent-sha256",
        "adapter_id": "BarnVelocityAdapter-v1",
        "adapter_hash": "adapter-sha256",
        "config_id": "configs/navigation/default.yaml",
        "config_hash": "config-sha256",
        "model_id": "stub-navigator",
        "model_hash": "model-sha256",
    }
    arguments.update(overrides)
    return record_evaluation_run(**arguments)  # type: ignore[arg-type]


def test_record_writes_immutable_run_and_append_only_index(tmp_path: Path) -> None:
    result = _record(tmp_path)

    assert result.record_path == tmp_path / "ledger" / "runs" / "baseline-001.json"
    assert result.index_path == tmp_path / "ledger" / "runs.jsonl"
    stored = json.loads(result.record_path.read_text(encoding="utf-8"))
    assert stored["run_id"] == "baseline-001"
    assert stored["timestamp_utc"] == "2026-08-03T15:04:05.000006Z"
    assert stored["benchmark"]["source_commit"] == "benchmark-commit-123"
    assert stored["parcel"] == {"git_commit": "parcel-commit-456", "git_dirty": True}
    assert stored["components"]["adapter"]["id"] == "BarnVelocityAdapter-v1"
    assert stored["aggregate_metrics"]["success_rate"] == pytest.approx(0.42)
    assert stored["report"]["sha256"] == sha256_file(tmp_path / "report.json")
    assert not (result.record_path.stat().st_mode & stat.S_IWUSR)

    indexed = list(iter_ledger(tmp_path / "ledger"))
    assert len(indexed) == 1
    assert indexed[0]["run_id"] == "baseline-001"
    assert indexed[0]["record_path"] == "runs/baseline-001.json"
    assert indexed[0]["change_description"] == "Initial Parcel adapter baseline."


def test_duplicate_run_id_never_overwrites_or_reindexes(tmp_path: Path) -> None:
    first = _record(tmp_path)
    original = first.record_path.read_bytes()

    with pytest.raises(DuplicateRunError):
        _record(
            tmp_path,
            change_description="This must not replace the first record.",
            aggregate_metrics={"success_rate": 1.0},
        )

    assert first.record_path.read_bytes() == original
    assert len(list(iter_ledger(tmp_path / "ledger"))) == 1


def test_generated_run_ids_are_unique(tmp_path: Path) -> None:
    first = _record(tmp_path, run_id=None)
    second = _record(tmp_path, run_id=None)

    assert first.record["run_id"] != second.record["run_id"]
    assert len(list(iter_ledger(tmp_path / "ledger"))) == 2


def test_nonfinite_metrics_and_unsafe_ids_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(LedgerError, match="finite"):
        _record(tmp_path, aggregate_metrics={"spl": math.nan})
    with pytest.raises(LedgerError, match="run_id"):
        _record(tmp_path, run_id="../escape")
    assert not (tmp_path / "ledger").exists()


def test_cli_reads_aggregate_metrics_from_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = _report(tmp_path)
    monkeypatch.setattr(
        ledger,
        "detect_git_state",
        lambda _repository: GitState(commit="parcel-cli-commit", dirty=False),
    )

    exit_code = ledger.main(
        [
            "record",
            "--benchmark-id",
            "barn",
            "--benchmark-source",
            "https://github.com/example/barn",
            "--benchmark-source-commit",
            "barn-cli-commit",
            "--description",
            "CLI baseline",
            "--report",
            str(report),
            "--ledger-dir",
            str(tmp_path / "cli-ledger"),
            "--run-id",
            "cli-001",
            "--adapter-id",
            "parcel-barn-adapter",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["run_id"] == "cli-001"
    entry = next(iter(iter_ledger(tmp_path / "cli-ledger")))
    assert entry["aggregate_metrics"] == {"success_rate": 0.42, "spl": 0.31}
    assert entry["parcel"] == {"git_commit": "parcel-cli-commit", "git_dirty": False}
