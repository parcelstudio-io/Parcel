import json
from pathlib import Path

from evals.companion.compare_planner_contract_size import build_comparison

REPO = Path(__file__).resolve().parents[1]
ARTIFACT = REPO / "evals/companion/planner_contract_size/results/plansketch-v1-static-run05.json"


def test_static_plansketch_size_artifact_is_exactly_reproducible() -> None:
    recorded = json.loads(ARTIFACT.read_text(encoding="utf-8"))

    assert build_comparison() == recorded
    assert recorded["aggregate"]["case_count"] == 5
    assert recorded["aggregate"]["byte_reduction_fraction"] == 0.732126
    assert recorded["aggregate"]["model_tokens"] is None
    assert recorded["aggregate"]["model_latency_ms"] is None
    assert recorded["aggregate"]["physical_navigation_episode_count"] == 0
