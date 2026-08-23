"""Card HW-MIC `array-arm-route` (scrum/20260822/task_44).

The array ear's arming door, driven the way `tests/test_web_panel.py` drives
every other one: a real `RuntimeHTTPServer` on a real loopback socket, real
HTTP, the real `do_POST`. Nothing about the handler is stubbed — the only
stand-ins are the runtime object the panel reads two attributes off, and the
PortAudio module underneath the REAL `ArrayAudioGateway`, which is the
``audio=`` proxy shape card HW-4 built for exactly this (its own fake is not
imported: a test module is not an interface, and this one needs an ordering log
HW-4's does not keep).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.realtime.audio_gateway import (
    AUDIO_GATEWAY_ARRAY,
    ArrayAudioGateway,
    BrowserAudioGateway,
)
from parcel_robot.web_panel import RuntimeHTTPServer

REPO = Path(__file__).resolve().parents[1]
PANEL_HTML = REPO / "src" / "parcel_robot" / "ui" / "index.html"
WEB_PANEL_PY = REPO / "src" / "parcel_robot" / "web_panel.py"

#: The route this card adds. Spelled once, here, so a test cannot pass against
#: a route the product does not serve.
ROUTE = "/api/realtime/mic"

#: The websocket the browser ear uses, which the 409 must name.
SOCKET_ROUTE = "/api/realtime/audio"

#: `do_POST`'s route literals at HEAD (`e15e466`), in order, read off
#: `git show HEAD:src/parcel_robot/web_panel.py` before this card's first edit.
#: The flag-off row is "this list, plus exactly one".
HEAD_POST_ROUTES: tuple[str, ...] = (
    "/api/command",
    "/api/voice/text",
    "/api/realtime/text",
    "/api/voice/barge-in",
    "/api/motion",
    "/api/action",
    "/api/pose-review/run",
    "/api/owner",
    "/api/personality",
    "/api/prompt/fact",
    "/api/evals/run",
    "/api/evals/batch",
    "/api/evals/select",
)

#: `do_GET`'s route-literal count at the same commit.
HEAD_GET_ROUTE_COUNT = 8

#: sha256 of three `ui/index.html` functions at HEAD, taken before the first
#: edit (the file was byte-identical at HEAD, in the index and in the working
#: tree: `aa70ea86…`). With every `CARD HW-MIC` fenced block removed the file
#: must still produce these — that is what "the browser path is untouched"
#: means, and a prose promise would not have caught a one-character edit.
HEAD_UI_FUNCTIONS: dict[str, str] = {
    "async function startMic()": (
        "06bf808620d951a2e0226f79cded2a314f57e1620459df895ddb39fc6cc5d560"
    ),
    "function renderRealtime(realtime)": (
        "3f80f97b82ec3f9e8371c34762857d2b6b810574565976442cb6f236b8d5ca8d"
    ),
    "function stopMic(reason)": (
        "ca299601266160133f66b638c7f4f02654ae22cc70df7aed2dcaba633bdfe410"
    ),
}

#: The host's PortAudio enumeration, trimmed to what device resolution reads.
#: Two entries carry the array's name and two input channels — the raw ALSA
#: node and the PipeWire one — because that ambiguity is real on this desk.
HOST_DEVICES: tuple[dict[str, Any], ...] = (
    {"name": "HDA NVidia: HDMI 0 (hw:0,3)", "max_input_channels": 0, "max_output_channels": 8},
    {
        "name": "reSpeaker XVF3800 4-Mic Array: USB Audio (hw:1,0)",
        "max_input_channels": 2,
        "max_output_channels": 2,
    },
    {"name": "pipewire", "max_input_channels": 128, "max_output_channels": 128},
)

#: The same host with the array unplugged.
NO_ARRAY_DEVICES = tuple(entry for entry in HOST_DEVICES if "XVF3800" not in str(entry["name"]))


# ======================================================= the PortAudio stand-in
class _FakeStream:
    def __init__(self, owner: _FakeAudio, label: str, **kwargs: Any) -> None:
        self.owner = owner
        self.label = label
        self.kwargs = kwargs
        self.callback = kwargs["callback"]
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def abort(self) -> None:
        self.started = False

    def stop(self) -> None:
        self.started = False

    def close(self) -> None:
        self.closed = True


class _FakeAudio:
    """`sounddevice`'s four names, plus one ordering log.

    `events` is what makes HW-4's F5 ordering checkable THROUGH THE ROUTE: the
    gateway is supposed to have a live device before it asks the runtime for
    the gesture that opens a billed hosted session, and the only way to see
    that from outside is to watch both happen.
    """

    class PortAudioError(Exception):
        """`sounddevice.PortAudioError` subclasses `Exception` directly."""

    def __init__(
        self,
        devices: tuple[dict[str, Any], ...] = HOST_DEVICES,
        *,
        input_raises: bool = False,
    ) -> None:
        self.devices = [dict(entry) for entry in devices]
        self.input_raises = input_raises
        self.events: list[str] = []
        self.input_streams: list[_FakeStream] = []
        self.output_streams: list[_FakeStream] = []

    def query_devices(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self.devices]

    def InputStream(self, **kwargs: Any) -> _FakeStream:  # PortAudio's own name
        if self.input_raises:
            raise OSError("PortAudio: device unavailable [PaErrorCode -9985]")
        self.events.append("input")
        stream = _FakeStream(self, "input", **kwargs)
        self.input_streams.append(stream)
        return stream

    def OutputStream(self, **kwargs: Any) -> _FakeStream:  # PortAudio's own name
        self.events.append("output")
        stream = _FakeStream(self, "output", **kwargs)
        self.output_streams.append(stream)
        return stream


# ============================================================ the runtime stand-in
class _PanelRuntime:
    """Everything the panel handler reads, and nothing else.

    The two attributes this card's route touches are `realtime_gateway` (the
    same one `_serve_realtime_audio` reads) and `realtime_config.mode` (only to
    say what a runtime with no ear is). `snapshot`/`latency_snapshot` are what
    the panel's other routes need to exist at all.
    """

    class _Config:
        def __init__(self, mode: str) -> None:
            self.mode = mode

    def __init__(self, gateway: object | None = None, *, mode: str = "audio") -> None:
        self.realtime_gateway = gateway
        self.realtime_config = self._Config(mode)
        self.motions: list[tuple[float, float, float]] = []

    def snapshot(self) -> dict[str, object]:
        return {"status": "hwmic"}

    def latency_snapshot(self) -> dict[str, object]:
        return {"aggregate": {}, "turns": []}

    def manual_motion(self, vx: float, vy: float, vyaw: float) -> str:
        self.motions.append((vx, vy, vyaw))
        return "accepted"


class _NoRealtimeRuntime:
    """A `mode: text` runtime: the attribute is not there at all."""

    def snapshot(self) -> dict[str, object]:
        return {"status": "hwmic-text"}

    def latency_snapshot(self) -> dict[str, object]:
        return {"aggregate": {}, "turns": []}


# ==================================================================== the harness
def _serve(runtime: object) -> Any:
    server = RuntimeHTTPServer(("127.0.0.1", 0), runtime)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server._hwmic_thread = thread  # type: ignore[attr-defined]
    return server


def _shutdown(server: Any) -> None:
    server.shutdown()
    server.server_close()
    server._hwmic_thread.join(2.0)


@pytest.fixture
def panel():
    """A panel server per test, torn down with whatever gateway it was given."""

    made: list[Any] = []

    def _make(runtime: object) -> Any:
        server = _serve(runtime)
        made.append(server)
        return server

    try:
        yield _make
    finally:
        for server in made:
            gateway = getattr(server.runtime, "realtime_gateway", None)
            stop = getattr(gateway, "stop", None)
            if callable(stop):
                stop()
            _shutdown(server)


def _post(
    server: Any,
    payload: object,
    *,
    path: str = ROUTE,
    token: str | None | bool = True,
    origin: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """One real POST. Returns (status, body) for refusals as well as successes."""

    base = f"http://127.0.0.1:{server.server_address[1]}"
    headers = {"Content-Type": "application/json"}
    if token is True:
        headers["X-Parcel-CSRF"] = server.csrf_token
    elif isinstance(token, str):
        headers["X-Parcel-CSRF"] = token
    if origin is not None:
        headers["Origin"] = origin
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=4) as response:
            return int(response.status), json.load(response)
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        return int(error.code), json.loads(raw) if raw else {}


def _array_runtime(
    audio: _FakeAudio,
    *,
    on_mic: Any = None,
    device: object = None,
) -> _PanelRuntime:
    """A runtime holding a REAL, started `ArrayAudioGateway` over a fake device."""

    gateway = ArrayAudioGateway(
        on_audio=lambda _payload: None,
        on_mic=on_mic,
        audio=audio,
        device=device,
    )
    gateway.start()
    return _PanelRuntime(gateway)


# ========================================================================= rows
def test_an_unauthorised_arm_is_refused_before_the_gateway(panel) -> None:
    """Row R1. The route inherits `_authorize_post()` and adds no way around it.

    Three refusals, and the one that matters most is the third: a page on
    another origin must not be able to open the microphone in this room.
    Seed S1: move the route arm above the `_authorize_post()` prologue.
    """

    audio = _FakeAudio()
    server = panel(_array_runtime(audio))
    gateway = server.runtime.realtime_gateway

    assert _post(server, {"open": True}, token=None)[0] == 403
    assert _post(server, {"open": True}, token="not-the-token")[0] == 403
    assert _post(server, {"open": True}, origin="https://attacker.example")[0] == 403

    assert gateway.mic_open is False
    assert gateway.mic_opens == 0
    assert audio.input_streams == []
    assert audio.output_streams == []


def test_a_browser_ear_refuses_this_route_and_names_the_socket(panel) -> None:
    """Row R2. The wrong door, said in words the owner can act on.

    409 rather than 404 on purpose: the route EXISTS, the request is well
    formed, and the fitted ear is simply armed somewhere else. Seed S2: answer
    the browser gateway with `set_mic` instead.
    """

    gateway = BrowserAudioGateway(on_audio=lambda _payload: None)
    server = panel(_PanelRuntime(gateway))

    status, body = _post(server, {"open": True})

    assert status == 409
    assert SOCKET_ROUTE in body["detail"]
    assert body["kind"] == "browser_audio"
    assert gateway.snapshot()["mic_open"] is False


def test_the_array_ear_arms_through_the_route(panel) -> None:
    """Row R3. The whole point of the card, through the real handler.

    `set_mic` is not stubbed: the real one runs, the real duplex pair opens on
    the fake device, and the response is the state that now holds.
    """

    audio = _FakeAudio()
    calls: list[bool] = []
    runtime = _array_runtime(audio, on_mic=calls.append)
    server = panel(runtime)
    gateway = runtime.realtime_gateway

    status, body = _post(server, {"open": True})

    assert status == 200
    assert body == {"open": True, "kind": AUDIO_GATEWAY_ARRAY}
    assert calls == [True], "the runtime gesture fires once, not twice, not never"
    assert gateway.mic_open is True
    assert gateway.mic_opens == 1
    assert len(audio.input_streams) == 1
    assert len(audio.output_streams) == 1, "the playback stream IS the capture clock (HW-4 F1)"
    assert audio.input_streams[0].started is True

    # Arming twice is idempotent, not a second device open: the owner's second
    # click on a live microphone must not cost a second stream.
    assert _post(server, {"open": True}) == (200, {"open": True, "kind": AUDIO_GATEWAY_ARRAY})
    assert len(audio.input_streams) == 1
    assert calls == [True]


def test_the_device_is_open_before_the_session_gesture(panel) -> None:
    """Row R4. HW-4's finding F5, asserted THROUGH this route.

    `on_mic` is `RobotRuntime._realtime_mic_gesture`, and that is what calls
    `lane.ensure_session(...)` — the billed hosted session. If the route (or a
    future edit to it) ever opened the session first, a host with no array
    would leave the owner paying for a lane with no ear. The order is the
    gateway's to keep; this row proves the route did not undo it.
    Seed S3: swap the two halves of `set_mic` in a scratch copy.
    """

    audio = _FakeAudio()
    # ONE log, not two. The first draft of this test kept the gesture in its own
    # list and asserted `audio.events + order` — which is the same three strings
    # in the same order whatever actually happened, and the S3 seed (the two
    # halves of `set_mic` swapped) passed it. The session gesture writes into
    # the device's own event log, so the sequence below is a real sequence.
    runtime = _array_runtime(audio, on_mic=lambda _open: audio.events.append("on_mic"))
    server = panel(runtime)

    assert _post(server, {"open": True})[0] == 200

    assert audio.events == ["output", "input", "on_mic"], (
        "the playback clock, then the ear, then the runtime gesture that opens "
        "the billed hosted session — HW-4 finding F5"
    )
    assert audio.input_streams[0].started is True
    assert audio.output_streams[0].started is True


def test_a_refused_device_answers_503_and_opens_no_session(panel) -> None:
    """Row R5. The right door with no microphone behind it.

    503, not 409: nothing about the request is wrong. The gateway's own text is
    passed through verbatim because it is the text that tells the owner what to
    check, in order.
    """

    audio = _FakeAudio(NO_ARRAY_DEVICES)
    gestures: list[bool] = []
    runtime = _array_runtime(audio, on_mic=gestures.append)
    server = panel(runtime)

    status, body = _post(server, {"open": True})

    assert status == 503
    assert "99-respeaker-xvf3800.rules" in body["detail"]
    assert "lsusb" in body["detail"]
    assert body["kind"] == AUDIO_GATEWAY_ARRAY
    assert gestures == [], "a device refusal must never reach the session opener"
    assert runtime.realtime_gateway.mic_open is False
    assert audio.input_streams == []


def test_a_gateway_that_was_never_started_is_a_409(panel) -> None:
    """The other typed refusal `set_mic` can raise, mapped by the existing ladder.

    `GatewayNotRunningError` is a `RuntimeError`, so `do_POST`'s own
    `except (ConnectionError, FileNotFoundError, OSError, RuntimeError)` arm
    answers 409 — this row pins that the route did not swallow it into a 200.
    """

    audio = _FakeAudio()
    gateway = ArrayAudioGateway(on_audio=lambda _payload: None, audio=audio)
    server = panel(_PanelRuntime(gateway))  # never started

    status, body = _post(server, {"open": True})

    assert status == 409
    assert "not running" in body["detail"]
    assert audio.input_streams == []


def test_the_route_closes_the_ear_again(panel) -> None:
    """Row R6. `{"open": false}` shuts both halves of the duplex pair."""

    audio = _FakeAudio()
    gestures: list[bool] = []
    runtime = _array_runtime(audio, on_mic=gestures.append)
    server = panel(runtime)

    assert _post(server, {"open": True})[0] == 200
    status, body = _post(server, {"open": False})

    assert status == 200
    assert body == {"open": False, "kind": AUDIO_GATEWAY_ARRAY}
    assert runtime.realtime_gateway.mic_open is False
    assert audio.input_streams[0].closed is True
    assert audio.output_streams[0].closed is True
    # Closing the microphone is NOT hanging up: `set_mic(False)` never calls
    # the gesture, so the hosted session survives a released button by design
    # (`RobotRuntime._realtime_mic_gesture`'s own rule).
    assert gestures == [True]


def test_a_runtime_that_refuses_the_gesture_answers_open_false(panel) -> None:
    """The honest 200. A runtime may refuse the mic gesture (no panel token, no
    credential, budget spent); `set_mic` then closes what it opened and returns
    False, and the route reports the state that HOLDS rather than inventing an
    error the owner cannot act on."""

    audio = _FakeAudio()

    def _refuse(_open: bool) -> None:
        raise RuntimeError("the realtime lane has no panel handshake token")

    runtime = _array_runtime(audio, on_mic=_refuse)
    server = panel(runtime)

    status, body = _post(server, {"open": True})

    assert status == 200
    assert body == {"open": False, "kind": AUDIO_GATEWAY_ARRAY}
    assert runtime.realtime_gateway.mic_open is False
    assert audio.input_streams[0].closed is True


def test_a_missing_or_wrong_typed_open_is_a_400(panel) -> None:
    """Row R7. `open` is strictly boolean, because truthiness arms ears.

    `"no"`, `0` and `1` are all perfectly good JSON and all of them would be
    read as an instruction by `bool(...)`. Seed S4: `bool(payload.get("open"))`.
    """

    audio = _FakeAudio()
    runtime = _array_runtime(audio)
    server = panel(runtime)

    for payload in ({}, {"open": "yes"}, {"open": "no"}, {"open": 1}, {"open": 0}, {"open": None}):
        status, body = _post(server, payload)
        assert status == 400, payload
        assert "open must be a boolean" in body["detail"]

    assert runtime.realtime_gateway.mic_opens == 0
    assert audio.input_streams == []


def test_a_runtime_with_no_gateway_answers_404(panel) -> None:
    """Row R8. `mode: text` has no ear to arm, and says so."""

    server = panel(_NoRealtimeRuntime())
    status, body = _post(server, {"open": True})
    assert status == 404
    assert body["kind"] is None

    text_server = panel(_PanelRuntime(None, mode="text"))
    status, body = _post(text_server, {"open": True})
    assert status == 404
    assert "'text'" in body["detail"]


def test_the_socket_gate_now_says_which_ear_is_fitted(panel) -> None:
    """The 404 text at `_serve_realtime_audio`, corrected — not its logic.

    "the realtime audio gateway is not constructed (mode is not audio)" was
    false the day HW-4 landed: in array mode the gateway IS constructed and the
    mode IS audio. The condition is untouched (this socket still serves the
    browser ear only); the sentence now names the fitted ear and the door it
    uses.
    """

    audio = _FakeAudio()
    server = panel(_array_runtime(audio))
    base = f"http://127.0.0.1:{server.server_address[1]}"

    with pytest.raises(urllib.error.HTTPError) as refused:
        urllib.request.urlopen(f"{base}{SOCKET_ROUTE}", timeout=4)

    assert refused.value.code == 404
    body = json.loads(refused.value.read().decode())
    assert body["kind"] == AUDIO_GATEWAY_ARRAY
    assert ROUTE in body["detail"]
    assert "mode is not audio" not in body["detail"]


# ==================================================== flag-off / byte-identity
def _route_literals(source: str, method: str, end: str) -> list[str]:
    body = source[source.index(f"    def {method}(self) -> None:") : source.index(end)]
    return re.findall(r'path == "([^"]+)"', body)


def test_the_route_table_is_heads_plus_exactly_this_one_route() -> None:
    """Row R9, first half. FLAG-OFF: nothing else about the panel moved.

    The handler has no route table to compare — the routes ARE the `path ==`
    literals in `do_POST`, so those are what gets pinned. Seed S6: add a second
    new route literal.
    """

    source = WEB_PANEL_PY.read_text(encoding="utf-8")
    post_routes = _route_literals(
        source, "do_POST", "    # ------------------------------------------------- card R7"
    )
    get_routes = _route_literals(source, "do_GET", "    def do_POST(self) -> None:")

    assert post_routes.count(ROUTE) == 1
    assert tuple(route for route in post_routes if route != ROUTE) == HEAD_POST_ROUTES
    assert len(post_routes) == len(HEAD_POST_ROUTES) + 1
    assert len(get_routes) == HEAD_GET_ROUTE_COUNT, "this card adds no GET route"


def test_with_no_audio_key_the_panel_still_builds_the_browser_ear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row R9, second half, through the real `web_panel.build_runtime`.

    HW-4's `audio.gateway` is still absent from the SHA-locked base, so a panel
    started with no profile must still get the browser ear — and then this
    card's route is the only thing in the panel that answers differently, with
    a 409 that names the socket.
    """

    import yaml

    from parcel_robot import web_panel
    from parcel_robot.paths import resolve_config_yaml

    base = tmp_path / "robot.yaml"
    base.write_text(resolve_config_yaml().read_text(encoding="utf-8"), encoding="utf-8")
    realtime = tmp_path / "realtime.yaml"
    realtime.write_text(
        yaml.safe_dump({"enabled": True, "mode": "audio", "model": "gpt-realtime-2.1"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PARCEL_REALTIME_CONFIG", str(realtime))
    monkeypatch.setenv("PARCEL_MEMORY_PATH", str(tmp_path / "memory.sqlite3"))
    monkeypatch.setenv("PARCEL_REALTIME_SPEND_LEDGER", str(tmp_path / "spend.jsonl"))
    monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV", raising=False)
    monkeypatch.delenv("PARCEL_PROFILE", raising=False)

    runtime = web_panel.build_runtime(base, tmp_path / "sim.sock", use_llm=False)
    try:
        assert type(runtime.realtime_gateway) is BrowserAudioGateway
        assert runtime.realtime_gateway.snapshot()["kind"] == "browser_audio"
        assert runtime.store.section("audio") == {}
    finally:
        runtime.realtime_gateway.stop()


def _strip_card_regions(text: str) -> str:
    """Every `CARD HW-MIC` fenced block, marker lines included, removed."""

    out: list[str] = []
    inside = False
    for line in text.splitlines(keepends=True):
        if "---- CARD HW-MIC" in line:
            inside = True
            continue
        if "---- END CARD HW-MIC" in line:
            inside = False
            continue
        if not inside:
            out.append(line)
    return "".join(out)


def _js_function(text: str, header: str) -> str:
    start = text.index(header)
    index = text.index("{", start)
    depth = 0
    while True:
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    return text[start : index + 1]


def test_the_browser_half_of_the_panel_is_byte_identical() -> None:
    """Row R10. The browser ear's code is not touched, and that is checkable.

    Take this card's fenced blocks out of `index.html` and the three functions
    it sits in must hash to what HEAD had. Anything else — a reflow, a renamed
    local, a "harmless" tidy — reddens this.
    """

    stripped = _strip_card_regions(PANEL_HTML.read_text(encoding="utf-8"))
    for header, digest in HEAD_UI_FUNCTIONS.items():
        body = _js_function(stripped, header)
        assert hashlib.sha256(body.encode()).hexdigest() == digest, header


def test_the_panel_arms_the_array_over_the_route_not_the_socket() -> None:
    """Row R11. The UI branch exists, is array-only, and opens nothing locally.

    A text row, deliberately named as one: it pins what the fenced block says,
    not what a browser does with it (no JS engine runs here — MARK-1's `gjs`
    row is available and is NOT claimed by this card). Seed S5: delete the
    branch from `startMic()`.
    """

    html = PANEL_HTML.read_text(encoding="utf-8")
    regions = re.findall(r"---- CARD HW-MIC.*?---- END CARD HW-MIC[^\n]*\n", html, flags=re.DOTALL)
    assert len(regions) == 4, (
        "the label constant, the startMic branch, the N1 poll correction, the status line"
    )
    joined = "".join(regions)

    assert ROUTE in joined
    assert '=== "array"' in joined
    assert "state.arrayMic" in joined
    assert "ear: array" in joined
    # Verifier finding F1, the browser half: one arm in flight at a time, and
    # the guard is released on every path (the `finally`), not only on success.
    assert "state.arrayMicBusy" in joined
    assert "micButton.disabled = true" in joined
    assert "micButton.disabled = false" in joined
    # Verifier note N1: the poll that already carries `mic_open` corrects a
    # button still reading "Listening" over an ear the runtime shut.
    assert "realtime.gateway.mic_open === false" in joined
    # The array ear is not a browser microphone: nothing this branch RUNS may
    # open one, and nothing in it may open the browser ear's socket. Comment
    # lines are dropped first — the prose above says why those calls are absent,
    # and a test that read the prose as code would be testing the comment.
    code = "".join(
        line for line in joined.splitlines(keepends=True) if not line.strip().startswith("//")
    )
    for forbidden in ("getUserMedia", "openAudioSocket", "AudioContext"):
        assert forbidden not in code, forbidden
    # ...and the branch reads the kind the page already has from /api/state,
    # rather than asking the server a second question.
    assert "state.realtime.gateway.kind" in joined


def test_two_simultaneous_arms_open_one_device_and_both_get_the_state(panel) -> None:
    """Row R16 — verifier finding F1, reproduced on the real array and closed here.

    `ThreadingHTTPServer` hands every request its own thread and
    `ArrayAudioGateway.set_mic` is not re-entrant: it reads `_mic_open` under
    its lock, then opens the duplex pair and calls the runtime's gesture
    OUTSIDE it, and writes `_mic_open = True` only at the end. Two POSTs inside
    that window — one double-click — either leak a second stream and a second
    reader thread (a device that accepts two opens, which is this fake and is
    also what a PipeWire node does) or, on the real array's exclusive `hw:`
    node, get refused and write "shut" over the first click's LIVE ear: session
    open and billing, button reading "Listening", every frame dropped unarmed.

    The route now holds one process-wide lock around `set_mic`, so the second
    caller waits and is answered with the state that holds. The gesture is slow
    here on purpose: it is the window the race lives in.
    Seed S8: drop the `with _ARRAY_MIC_ROUTE_LOCK:` line.
    """

    audio = _FakeAudio()
    gestures: list[bool] = []

    def _slow_gesture(open_: bool) -> None:
        gestures.append(open_)
        time.sleep(0.3)

    runtime = _array_runtime(audio, on_mic=_slow_gesture)
    server = panel(runtime)
    gateway = runtime.realtime_gateway

    barrier = threading.Barrier(2)
    answers: dict[int, tuple[int, dict[str, Any]]] = {}

    def _fire(index: int) -> None:
        barrier.wait(timeout=5.0)
        answers[index] = _post(server, {"open": True})

    threads = [threading.Thread(target=_fire, args=(index,)) for index in (0, 1)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10.0)
        assert not thread.is_alive()

    assert answers[0] == (200, {"open": True, "kind": AUDIO_GATEWAY_ARRAY})
    assert answers[1] == (200, {"open": True, "kind": AUDIO_GATEWAY_ARRAY})
    assert len(audio.input_streams) == 1, "one ear, one device open"
    assert len(audio.output_streams) == 1, "one clock, not two"
    assert gateway.mic_opens == 1
    assert gestures == [True], "one billed session gesture, not two"
    assert gateway.mic_open is True, "the second call must not write 'shut' over the first"
    # (the open-before-gesture ORDER is R4's row; this gesture writes to its own
    # list so the two concurrent callers can be counted separately)

    # And the ear still closes cleanly afterwards: nothing was leaked that a
    # single `{"open": false}` cannot shut.
    assert _post(server, {"open": False}) == (200, {"open": False, "kind": AUDIO_GATEWAY_ARRAY})
    assert audio.input_streams[0].closed is True
    assert audio.output_streams[0].closed is True
    assert gateway.mic_open is False
