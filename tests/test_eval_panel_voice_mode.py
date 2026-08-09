"""SLIM-3: the ``/evals`` voice mode routes a scenario through the product path.

Default (headless) mode drives ``DirectiveNavigator`` directly. Voice mode types
the scenario's instruction into ``RobotRuntime.handle_text`` on the live runtime,
so admission, routing and executive dispatch are inside the measurement — the
layer the navigator-level loop is structurally blind to.

Tested at the API level (no browser): POST ``/api/evals/run`` with
``mode="voice"`` and assert the fake runtime's ``handle_text`` received the
selected scenario's instruction. The runtime-injection seam is the one
``tests/test_web_panel.py`` / ``tests/test_viewer_panel.py`` already use —
``RuntimeHTTPServer(addr, fake_runtime)``.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from parcel_robot import eval_panel as eval_panel_module
from parcel_robot.eval_panel import EvalPanelState
from parcel_robot.web_panel import EVALS_UI_PATH, RuntimeHTTPServer


class FakeRuntime:
    """Records handle_text and serves a scripted /api/state-shaped snapshot."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.voice_texts: list[str] = []
        self.task_state = "succeeded"
        self.x = 0.0
        self.y = 0.0
        self._lock = threading.Lock()

    def handle_text(self, text: str) -> str:
        with self._lock:
            self.texts.append(str(text))
        return "Okay—I'll move onto sidewalk and verify it."

    def submit_voice_text(self, text: str, *, is_final: bool = True) -> int:
        with self._lock:
            self.voice_texts.append(str(text))
        return 1

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "robot": {"x": self.x, "y": self.y, "z": 0.0, "heading": 0.0},
                "brain": {"tasks": [{"state": self.task_state}]},
            }

    def latency_snapshot(self) -> dict[str, object]:
        return {"aggregate": {}, "turns": []}


@pytest.fixture
def panel(monkeypatch: pytest.MonkeyPatch):
    """Fresh panel state per test — EVAL_PANEL is a module singleton."""

    state = EvalPanelState()
    monkeypatch.setattr(eval_panel_module, "EVAL_PANEL", state)
    runtime = FakeRuntime()
    server = RuntimeHTTPServer(("127.0.0.1", 0), runtime)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, runtime, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(1.0)


def _base(server: RuntimeHTTPServer) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}"


def _post(server: RuntimeHTTPServer, path: str, body: dict[str, object]):
    base = _base(server)
    request = urllib.request.Request(
        f"{base}{path}",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Parcel-CSRF": server.csrf_token,
            "Origin": base,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status, json.loads(response.read().decode())


def _get(server: RuntimeHTTPServer, path: str):
    with urllib.request.urlopen(f"{_base(server)}{path}", timeout=5) as response:
        return json.loads(response.read().decode())


def _first_episode(state: EvalPanelState):
    state.ensure_scenarios()
    return state.scenarios[0]


def _await_done(state: EvalPanelState, timeout_s: float = 20.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        snap = state.snapshot()
        if snap["status"] in {"done", "error"}:
            return snap
        time.sleep(0.05)
    raise AssertionError(f"voice run never finished: {state.snapshot()}")


def test_voice_mode_routes_the_instruction_through_handle_text(panel) -> None:
    server, runtime, state = panel
    episode = _first_episode(state)

    status, payload = _post(
        server, "/api/evals/run", {"episode_id": episode.episode_id, "mode": "voice"}
    )

    assert status == 202
    assert payload["accepted"] is True
    assert payload["mode"] == "voice"
    assert payload["instruction"] == episode.instruction
    # The goal region is published BEFORE the run so the viewer overlay marks
    # it pre-run; the verdict at the end is scored against this same region.
    assert payload["goal_region"] == episode.goal.as_dict()

    _await_done(state)
    assert runtime.texts == [episode.instruction]
    # Product path only — the navigator-direct runner must not have been used.
    assert runtime.voice_texts == []


def test_voice_mode_verdict_reports_claim_and_predicate_separately(panel) -> None:
    server, runtime, state = panel
    episode = _first_episode(state)
    # The fake runtime never moves, so the K0 predicate must refuse even though
    # the system claims success: claim-without-predicate is a failure (U32).
    runtime.task_state = "succeeded"

    _post(server, "/api/evals/run", {"episode_id": episode.episode_id, "mode": "voice"})
    _await_done(state)

    result = state.snapshot()["last_result"]
    assert isinstance(result, dict)
    assert result["mode"] == "voice"
    assert result["system_verified"] is True
    assert result["predicate_success"] is False
    assert result["success"] is False
    assert result["distance_to_goal_m"] > 0.0
    assert result["sample_count"] > 0


def test_voice_mode_is_sequential_by_construction(panel) -> None:
    server, runtime, state = panel
    episode = _first_episode(state)
    # Hold the first run open by never letting its task reach a terminal state.
    runtime.task_state = "running"

    status, _ = _post(
        server, "/api/evals/run", {"episode_id": episode.episode_id, "mode": "voice"}
    )
    assert status == 202
    assert state.snapshot()["status"] == "running"

    with pytest.raises(urllib.error.HTTPError) as second:
        _post(server, "/api/evals/run", {"episode_id": episode.episode_id, "mode": "voice"})
    # Refused, not queued: one live runtime, one city.
    assert second.value.code == 409
    assert runtime.texts == [episode.instruction]


def test_voice_mode_flag_is_accepted_as_well_as_the_mode_string(panel) -> None:
    server, runtime, state = panel
    episode = _first_episode(state)

    status, payload = _post(
        server,
        "/api/evals/run",
        {"episode_id": episode.episode_id, "voice_mode": True},
    )

    assert status == 202
    assert payload["mode"] == "voice"
    _await_done(state)
    assert runtime.texts == [episode.instruction]


def test_default_run_mode_is_unchanged_and_never_touches_handle_text(panel) -> None:
    server, runtime, state = panel
    episode = _first_episode(state)

    status, payload = _post(server, "/api/evals/run", {"episode_id": episode.episode_id})

    assert status == 202
    assert payload["mode"] == "headless"
    # The headless runner drives the navigator directly; it must never enter
    # the product path, or the two loops stop being independent.
    assert runtime.texts == []
    _await_done(state, timeout_s=90.0)


def test_live_mode_still_uses_the_voice_session_path(panel) -> None:
    server, runtime, state = panel
    episode = _first_episode(state)

    status, payload = _post(
        server, "/api/evals/run", {"episode_id": episode.episode_id, "mode": "live"}
    )

    assert status == 202
    assert payload["mode"] == "live"
    assert runtime.voice_texts == [episode.instruction]
    assert runtime.texts == []


def test_status_endpoint_reports_the_voice_mode(panel) -> None:
    server, _runtime, state = panel
    episode = _first_episode(state)

    _post(server, "/api/evals/run", {"episode_id": episode.episode_id, "mode": "voice"})
    _await_done(state)

    snap = _get(server, "/api/evals/status")
    assert snap["mode"] == "voice"
    assert snap["goal_region"] == episode.goal.as_dict()
    assert snap["last_result"]["mode"] == "voice"


def test_evals_page_exposes_the_voice_mode_toggle() -> None:
    page = EVALS_UI_PATH.read_text(encoding="utf-8")
    assert 'id="voiceMode"' in page
    assert '"voice"' in page
    # Default must stay headless: the toggle chooses, it is not pre-checked.
    assert 'id="voiceMode" checked' not in page
