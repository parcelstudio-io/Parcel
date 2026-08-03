from __future__ import annotations

from datetime import UTC, datetime

from parcel_robot.context import ContextBuildConfig, ContextBuilder, ContextField


class CountingProvider:
    def __init__(self, kind: str, value: dict):
        self.kind = kind
        self.value = value
        self.calls = 0

    def collect(self, now: datetime) -> ContextField:
        self.calls += 1
        return ContextField(self.kind, "test", now, self.value)


def test_disabled_context_never_invokes_or_serializes_provider():
    location = CountingProvider("location", {"x": 1.0, "area": "test"})
    builder = ContextBuilder(
        ContextBuildConfig(enabled=False, enable_location_context=True),
        {"location": location},
    )

    snapshot = builder.build(datetime(2026, 8, 2, tzinfo=UTC))

    assert location.calls == 0
    assert snapshot.fields == {}
    assert "location" not in snapshot.prompt_data()


def test_flags_are_independent_and_precise_location_is_prompt_private():
    now = datetime(2026, 8, 2, 14, 30, tzinfo=UTC)
    location = CountingProvider(
        "location",
        {"x": 12.5, "y": -3.0, "area": "demo block", "heading_deg": 90.0},
    )
    scene = CountingProvider("scene", {"visible_semantic_labels": ["sidewalk"]})
    builder = ContextBuilder(
        ContextBuildConfig(enabled=True, enable_location_context=True),
        {"location": location, "scene": scene},
    )

    snapshot = builder.build(now)
    prompt = snapshot.prompt_data(include_precise_coordinates=False)

    assert location.calls == 1
    assert scene.calls == 0
    assert prompt["location"]["data"] == {"area": "demo block", "heading_deg": 90.0}
    assert snapshot.navigation_data()["location"]["x"] == 12.5


def test_missing_enabled_provider_is_explicitly_unavailable():
    builder = ContextBuilder(
        ContextBuildConfig(enabled=True, enable_map_context=True),
        {},
    )

    snapshot = builder.build(datetime(2026, 8, 2, tzinfo=UTC))

    assert snapshot.fields == {}
    assert snapshot.errors == {"map": "provider unavailable"}
    assert snapshot.prompt_data()["unavailable"] == ["map"]
