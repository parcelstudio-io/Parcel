from __future__ import annotations

from pathlib import Path

import pytest
from _external_roots import skip_unless

from evals.external.habitat2020_py36_bridge import PROTOCOL_VERSION
from evals.external.run_habitat2020_contract_smoke import (
    DEFAULT_NAVIGATION_CONFIG,
    run_contract_smoke,
    write_immutable_report,
)


class _DeterministicTransport:
    def __init__(self) -> None:
        self.closed = False

    def request(self, message: dict[str, object]) -> dict[str, object]:
        if message["op"] == "start":
            return {
                "schema_version": PROTOCOL_VERSION,
                "op": "started",
                "episode_id": message["episode_id"],
            }
        if message["op"] == "act":
            return {
                "schema_version": PROTOCOL_VERSION,
                "op": "command",
                "episode_id": message["episode_id"],
                "step_id": message["step_id"],
                "vx": 0.2,
                "vy": 0.0,
                "vyaw": 0.0,
                "stop": False,
                "note": "deterministic-test",
            }
        if message["op"] == "close":
            return {"schema_version": PROTOCOL_VERSION, "op": "closed"}
        raise AssertionError(f"unexpected operation: {message['op']}")

    def close(self) -> None:
        self.closed = True


@skip_unless("habitat-challenge-2020-checkout")
def test_full_public_contract_smoke_records_no_fake_navigation_metric() -> None:
    transports: list[_DeterministicTransport] = []

    def factory(_config: Path) -> _DeterministicTransport:
        transport = _DeterministicTransport()
        transports.append(transport)
        return transport

    report = run_contract_smoke(transport_factory=factory)

    assert report["evaluation"] == {
        "id": "habitat20-pointnav-public-validation",
        "scope": "public-val-mini-adapter-contract-smoke",
        "official_rank_eligible": False,
        "leaderboard_comparable": False,
        "official_evaluator_executed": False,
        "habitat_sim_scene_loaded": False,
        "navigation_metrics_emitted": False,
        "allowed_claim": "public-artifact adapter contract smoke",
    }
    assert report["result"]["passed"] is True
    assert report["result"]["scope_complete"] is True
    assert report["result"]["episodes_exercised"] == 30
    assert report["result"]["action_counts"] == {"MOVE_FORWARD": 30}
    assert report["fixture"]["privileged_simulator_state_used"] is False
    assert report["execution"]["gpu_used"] is False
    assert report["provenance"]["active_model"]["active_model"] == "grid_v1"
    assert report["provenance"]["parcel_python_tree"]["file_count"] > 0
    assert transports[0].closed is True
    assert all(
        metric not in report["result"] for metric in ("success", "success_rate", "spl", "soft_spl")
    )


@skip_unless("habitat-challenge-2020-checkout")
def test_real_subprocess_sidecar_smoke_uses_unchanged_config() -> None:
    report = run_contract_smoke(
        navigation_config=DEFAULT_NAVIGATION_CONFIG,
        max_episodes=3,
    )

    assert report["result"]["passed"] is True
    assert report["result"]["scope_complete"] is False
    assert report["result"]["episodes_exercised"] == 3
    assert set(report["result"]["action_counts"]).issubset(
        {"STOP", "MOVE_FORWARD", "TURN_LEFT", "TURN_RIGHT"}
    )
    assert report["provenance"]["navigation_config_path"] == ("configs/navigation/default.yaml")


def test_contract_smoke_report_is_write_once(tmp_path: Path) -> None:
    output = tmp_path / "smoke.json"
    report = {"schema_version": 1, "result": {"passed": True}}

    write_immutable_report(output, report)

    assert output.read_text(encoding="utf-8").endswith("\n")
    with pytest.raises(FileExistsError):
        write_immutable_report(output, report)
