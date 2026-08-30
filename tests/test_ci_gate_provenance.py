"""Checkout identity for CI reports, including a dirty worktree."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import ci_gate


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
    )


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet")
    _git(root, "config", "user.email", "ci-gate@example.invalid")
    _git(root, "config", "user.name", "CI Gate Test")
    (root / ".gitignore").write_text("ignored.bin\n", encoding="utf-8")
    (root / "tracked.txt").write_text("committed\n", encoding="utf-8")
    _git(root, "add", ".gitignore", "tracked.txt")
    _git(root, "commit", "--quiet", "-m", "fixture")
    return root


def test_checkout_identity_binds_head_index_worktree_and_untracked_bytes(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    clean = ci_gate.capture_checkout_provenance(root)
    repeat = ci_gate.capture_checkout_provenance(root)

    assert clean["available"] is True
    assert clean["dirty"] is False
    assert clean["checkout_identity_sha256"] == repeat["checkout_identity_sha256"]

    (root / "tracked.txt").write_text("staged\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    staged = ci_gate.capture_checkout_provenance(root)
    assert staged["head_sha"] == clean["head_sha"]
    assert staged["staged_path_count"] == 1
    assert staged["unstaged_path_count"] == 0
    assert staged["index_manifest_sha256"] != clean["index_manifest_sha256"]

    (root / "tracked.txt").write_text("staged plus unstaged\n", encoding="utf-8")
    unstaged = ci_gate.capture_checkout_provenance(root)
    assert unstaged["index_manifest_sha256"] == staged["index_manifest_sha256"]
    assert unstaged["worktree_manifest_sha256"] != staged["worktree_manifest_sha256"]
    assert unstaged["unstaged_path_count"] == 1

    (root / "new.txt").write_text("untracked\n", encoding="utf-8")
    untracked = ci_gate.capture_checkout_provenance(root)
    assert untracked["untracked_path_count"] == 1
    assert untracked["worktree_manifest_sha256"] != unstaged["worktree_manifest_sha256"]
    assert (
        len(
            {
                clean["checkout_identity_sha256"],
                staged["checkout_identity_sha256"],
                unstaged["checkout_identity_sha256"],
                untracked["checkout_identity_sha256"],
            }
        )
        == 4
    )


def test_checkout_identity_explicitly_excludes_git_ignored_bytes(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    before = ci_gate.capture_checkout_provenance(root)
    (root / "ignored.bin").write_bytes(b"first")
    after = ci_gate.capture_checkout_provenance(root)

    assert before["checkout_identity_sha256"] == after["checkout_identity_sha256"]
    assert any("Git-ignored files" in item for item in after["limitations"])


def test_checkout_identity_is_typed_unavailable_outside_a_git_checkout(
    tmp_path: Path,
) -> None:
    checkout = ci_gate.capture_checkout_provenance(tmp_path)
    provenance = ci_gate.run_provenance(checkout, checkout)

    assert checkout["available"] is False
    assert checkout["error"]
    assert provenance["checkout_unchanged_during_run"] is None
    assert "unavailable" in ci_gate.format_run_provenance(provenance)


def test_main_emits_the_same_run_provenance_in_text_and_json(
    monkeypatch,
    capsys,
) -> None:
    snapshots = [
        {
            "available": True,
            "head_sha": "a" * 40,
            "checkout_identity_sha256": "b" * 64,
            "dirty": True,
            "staged_path_count": 1,
            "unstaged_path_count": 2,
            "untracked_path_count": 3,
        },
        {
            "available": True,
            "head_sha": "a" * 40,
            "checkout_identity_sha256": "c" * 64,
            "dirty": True,
            "staged_path_count": 1,
            "unstaged_path_count": 2,
            "untracked_path_count": 3,
        },
    ]
    monkeypatch.setattr(ci_gate, "capture_checkout_provenance", lambda: snapshots.pop(0))
    monkeypatch.setattr(
        ci_gate,
        "run_commit_tier",
        lambda: [ci_gate.GateResult("proof", "commit", True, "pass", "ok")],
    )

    assert ci_gate.main(["--tier", "commit", "--json"]) == 0
    output = capsys.readouterr().out
    assert "RUN PROVENANCE" in output
    assert "checkout=bbbbbbbbbbbb->cccccccccccc" in output
    payload = json.loads(output[output.index("{") :])
    provenance = payload["provenance"]
    assert provenance["schema"] == ci_gate.RUN_PROVENANCE_SCHEMA
    assert provenance["checkout_unchanged_during_run"] is False
    assert provenance["start"]["checkout_identity_sha256"] == "b" * 64
    assert provenance["finish"]["checkout_identity_sha256"] == "c" * 64
    assert "not execution" in provenance["claim"]
