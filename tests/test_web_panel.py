from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request

import pytest

from parcel_robot.web_panel import RuntimeHTTPServer


class FakeRuntime:
    def __init__(self):
        self.motions: list[tuple[float, float, float]] = []

    def snapshot(self):
        return {"status": "test"}

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
