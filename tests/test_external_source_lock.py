from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.external.fetch_sources import load_lock


def test_committed_source_lock_pins_adopted_contest_repositories() -> None:
    sources = load_lock()

    assert sources["barn_challenge"]["commit"] == ("bf5a226f6088ec96bf0d2dbee3253a8ea6119b83")
    assert sources["barn_challenge_ros2_2026"]["commit"] == (
        "d6c575b51e477bd524d634e12cffeb34036fcd1e"
    )
    assert sources["habitat_challenge_2020"]["commit"] == (
        "ddf1575532aecc4df2f4cd4c5db173b8eada3e1e"
    )
    assert sources["threewe_robot_platform"] == {
        "kind": "git",
        "url": "https://github.com/telleroutlook/3we-robot-platform.git",
        "commit": "6073a1bd0a30b6ca1348027ac35b05832b97bfe9",
        "license": "Apache-2.0",
        "purpose": (
            "Adopted 3WE portfolio source; pins the alpha SDK, benchmark "
            "implementation, scene declarations, documentation, and public "
            "leaderboard snapshot for compatibility auditing"
        ),
    }
    assert sources["jackal_melodic"]["commit"] == ("0d8d76f96bd52102b69a3b9cb735fd5f9e15f695")
    assert sources["jackal_simulator_melodic"]["commit"] == (
        "f72ffe1c160db5595dc033b323eb924abec539c4"
    )


def test_source_lock_rejects_mutable_revision(tmp_path: Path) -> None:
    lock = tmp_path / "sources.json"
    lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": {
                    "unsafe": {
                        "kind": "git",
                        "url": "https://example.com/repo.git",
                        "commit": "main",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="immutable"):
        load_lock(lock)
