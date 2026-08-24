import json
from pathlib import Path

from parcel_robot import providers
from parcel_robot.brain.observations import build_observation_snapshot
from parcel_robot.brain.plan_sketch import PlanSketch
from parcel_robot.brain.router import DeterministicIntentRouter
from parcel_robot.providers import LlamaCppProvider

REPO = Path(__file__).resolve().parents[1]


class _StreamingResponse:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks

    def __iter__(self):
        return iter(self.chunks)

    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_llama_provider_parses_marked_plansketch_without_changing_planir_mode(
    monkeypatch,
) -> None:
    raw_sketch = {
        "schema_version": 1,
        "goal": {"relation": "hold", "kind": "current_pose", "query": ""},
        "steps": [{"skill": "Hold", "arguments": {}, "navigation": None}],
    }
    encoded = json.dumps(raw_sketch)
    event = json.dumps({"choices": [{"delta": {"content": encoded}}]})
    response = _StreamingResponse([f"data: {event}\n".encode(), b"data: [DONE]\n"])
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return response

    monkeypatch.setattr(providers, "urlopen", fake_urlopen)
    provider = LlamaCppProvider(model="fake-planner", plan_timeout=5.0)
    frame = DeterministicIntentRouter().route(
        "Walk to the sidewalk and then wait.",
        turn_id="turn-plan-sketch-provider",
    )
    snapshot = build_observation_snapshot(
        None,
        snapshot_id="snapshot-plan-sketch-provider",
        now=1.0,
    )
    schema = json.loads(
        (REPO / "prompts/schemas/plan_sketch_v1.schema.json").read_text(encoding="utf-8")
    )

    output = provider.plan(
        "Walk to the sidewalk and then wait.",
        intent_frame=frame,
        observation=snapshot,
        skill_contracts={"schema_version": 1, "skills": [{"name": "Hold"}]},
        response_schema=schema,
        system_prompt="Return PlanSketch only.",
    )

    assert isinstance(output, PlanSketch)
    assert output.as_dict() == raw_sketch
    assert provider.last_metrics["model_output_contract"] == "plan_sketch_v1"
    assert provider.last_metrics["model_output_bytes"] == len(encoded.encode("utf-8"))
    payload = json.loads(requests[0][0].data)
    assert payload["response_format"]["schema"]["x-parcel-output-contract"] == ("plan_sketch_v1")
