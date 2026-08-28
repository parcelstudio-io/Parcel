"""The scene-generalization CLI must honor its explicit research output root."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from evals.nav_instruct import unseen_split
from evals.nav_instruct.run_nav_instruct_v1 import _run_scene_split


def test_scene_split_routes_the_report_under_args_out(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    payload = {"mode": "baseline", "sentinel": "split math is not under test"}
    observed: dict[str, object] = {}

    def fake_run_split(**kwargs):
        observed["run_kwargs"] = kwargs
        return payload

    def fake_write_report(value, path=None):
        observed["payload"] = value
        observed["path"] = path
        return path

    monkeypatch.setattr(unseen_split, "run_split", fake_run_split)
    monkeypatch.setattr(unseen_split, "markdown_table", lambda value: "split-table")
    monkeypatch.setattr(unseen_split, "write_report", fake_write_report)

    args = Namespace(
        scenes="all",
        mode="baseline",
        max_steps=200,
        seed=20260804,
        out=tmp_path,
    )
    assert _run_scene_split(args) == 0
    assert observed["run_kwargs"] == {
        "mode": "baseline",
        "max_steps": 200,
        "seed": 20260804,
        "scenes": None,
    }
    assert observed["payload"] is payload
    assert observed["path"] == tmp_path / "scene_split_baseline.json"
    assert "split-table" in capsys.readouterr().out
