from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from parcel_robot import web_panel
from parcel_robot.web_panel import RuntimeHTTPServer


class FakeRuntime:
    def __init__(self):
        self.motions: list[tuple[float, float, float]] = []

    def snapshot(self):
        return {"status": "test"}

    def latency_snapshot(self):
        return {"aggregate": {}, "turns": []}

    def manual_motion(self, vx, vy, vyaw):
        self.motions.append((vx, vy, vyaw))
        return "accepted"


@pytest.fixture
def panel_server():
    runtime = FakeRuntime()
    server = RuntimeHTTPServer(("127.0.0.1", 0), runtime)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, runtime
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1.0)


def _post(url: str, token: str | None, *, origin: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-Parcel-CSRF"] = token
    if origin is not None:
        headers["Origin"] = origin
    request = urllib.request.Request(
        url,
        data=json.dumps({"vx": 0.1, "vy": 0.0, "vyaw": 0.0}).encode(),
        headers=headers,
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=2)


def test_control_api_requires_embedded_token_and_same_origin(panel_server):
    server, runtime = panel_server
    base = f"http://127.0.0.1:{server.server_address[1]}"
    with urllib.request.urlopen(base, timeout=2) as response:
        page = response.read().decode()
    token_match = re.search(r'const CSRF_TOKEN = "([^"]+)"', page)
    assert token_match is not None
    token = token_match.group(1)
    assert token != "__PARCEL_CSRF_TOKEN__"

    with pytest.raises(urllib.error.HTTPError) as missing:
        _post(f"{base}/api/motion", None)
    assert missing.value.code == 403

    with pytest.raises(urllib.error.HTTPError) as hostile:
        _post(f"{base}/api/motion", token, origin="https://attacker.example")
    assert hostile.value.code == 403

    with _post(f"{base}/api/motion", token, origin=base) as response:
        assert response.status == 200
    assert runtime.motions == [(0.1, 0.0, 0.0)]


def test_latency_dashboard_and_api_are_separate_read_only_views(panel_server):
    server, _ = panel_server
    base = f"http://127.0.0.1:{server.server_address[1]}"

    with urllib.request.urlopen(f"{base}/latency", timeout=2) as response:
        page = response.read().decode()
    assert "Parcel latency traces" in page
    assert "textContent" in page
    assert 'aria-label="Per-turn latency traces"' in page
    assert "UserQueryEndToFirstPlanOutput" in page
    assert "UserQueryEndToAcceptedPlan" in page
    assert 'colspan="15"' in page
    assert "row.firstChild.colSpan = 15" in page

    with urllib.request.urlopen(f"{base}/api/latency", timeout=2) as response:
        payload = json.load(response)
    assert payload == {"aggregate": {}, "turns": []}


def test_build_runtime_can_configure_an_independent_planner_provider(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = tmp_path / "robot.yaml"
    config.write_text(
        """
language_model:
  enabled: true
  base_url: http://127.0.0.1:8080
  model: conversation
planner_model:
  enabled: true
  base_url: http://127.0.0.1:8082
  model: planner
""",
        encoding="utf-8",
    )
    providers = []
    captured = {}

    def provider_from_config(model_config):
        provider = {"model": model_config["model"], "base_url": model_config["base_url"]}
        providers.append(provider)
        return provider

    def runtime_from_models(config_path, backend, **kwargs):
        captured.update(kwargs)
        return {"config_path": config_path, "backend": backend, **kwargs}

    monkeypatch.setattr(
        web_panel.LlamaCppProvider,
        "from_config",
        staticmethod(provider_from_config),
    )
    monkeypatch.setattr(web_panel, "MujocoSocketBackend", lambda path: ("backend", path))
    monkeypatch.setattr(web_panel, "RobotRuntime", runtime_from_models)

    result = web_panel.build_runtime(config, tmp_path / "sim.sock")

    assert result["language_model"] is providers[0]
    assert result["planner_model"] is providers[1]
    assert providers == [
        {"model": "conversation", "base_url": "http://127.0.0.1:8080"},
        {"model": "planner", "base_url": "http://127.0.0.1:8082"},
    ]


def test_no_llm_override_disables_both_configured_model_lanes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = tmp_path / "robot.yaml"
    config.write_text(
        """
language_model:
  enabled: true
planner_model:
  enabled: true
""",
        encoding="utf-8",
    )
    captured = {}

    monkeypatch.setattr(
        web_panel.LlamaCppProvider,
        "from_config",
        staticmethod(lambda config: pytest.fail("disabled providers must not be constructed")),
    )
    monkeypatch.setattr(web_panel, "MujocoSocketBackend", lambda path: ("backend", path))

    def runtime_from_models(config_path, backend, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(web_panel, "RobotRuntime", runtime_from_models)

    web_panel.build_runtime(config, tmp_path / "sim.sock", use_llm=False)

    assert captured["language_model"] is None
    assert captured["planner_model"] is None
