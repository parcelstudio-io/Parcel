"""Card R7 §A: the browser audio gateway — ears, mouth, and the gates between.

WHAT THIS FILE PINS
-------------------
* **Fail-closed twice over.** A socket without the panel's token never reaches
  the lane, and a socket WITH it gets a mouth and no ear until the owner's own
  per-connection gesture arrives as its own control frame. "Connected" is not
  "listening", and the gate is asserted from a real websocket client.
* **Bounded in both directions.** Outbound playback has a hard frame bound and
  a hard byte bound and drops the OLDEST frame with a counter; inbound has a
  hard per-frame cap and no queue at all. Neither can grow.
* **The played clock is clamped by whoever owns bytes-sent.** A browser can
  claim anything; three clamps (current utterance only, never more than was
  transmitted, never earlier than the first byte left) decide what the lane is
  allowed to tell the provider the owner heard.
* **Barge-in reaches the browser.** The lane cancels the response; the gateway
  additionally tells the tab to stop playing what it already buffered, and mic
  frames keep flowing the whole time.
* **``mode: audio`` constructs.** It used to raise at construction. It now
  builds a gateway that is armed but idle, and text mode is byte-identically
  what it was.
* **R4L open risk 6.** The lane's sink-ownership assertion no longer fires when
  there is nothing to contend for.

Every socket here is a REAL websocket to a REAL ``RuntimeHTTPServer``; the only
fake is the provider (``FakeRealtimeServer``) and the robot backend.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from parcel_robot.audio.devices import AudioDeviceStatus
from parcel_robot.audio.voice_loop import pcm16_wav
from parcel_robot.backends.base import OwnerTrack, RobotPose, SimObservation
from parcel_robot.models import AgentDecision, VelocityCommand
from parcel_robot.realtime.audio_gateway import (
    CSRF_SUBPROTOCOL_PREFIX,
    DEFAULT_MAX_INBOUND_FRAME_BYTES,
    GATEWAY_PATH,
    SUBPROTOCOL_AUDIO,
    BrowserAudioGateway,
    GatewayAuthError,
    GatewayNotRunningError,
    select_csrf_subprotocol,
    verify_capture_index,
)
from parcel_robot.realtime.browser_sink import BrowserSink, DiscardSink
from parcel_robot.realtime.config import REALTIME_CONFIG_ENV, RealtimeConfigError
from parcel_robot.realtime.fake_server import (
    FakeRealtimeServer,
    Step,
    audio_delta,
    audio_done,
    handshake,
    input_transcript,
    pcm_tone,
    response_done,
    transcript_done,
)
from parcel_robot.realtime.protocol import PCM16_SAMPLE_RATE_HZ
from parcel_robot.realtime.transport import TransportClosed, transport_pair
from parcel_robot.runtime import RobotRuntime
from parcel_robot.web_panel import RuntimeHTTPServer

REPO = Path(__file__).resolve().parents[1]
BACKEND_NAME = "r7-audio"
TOKEN = "panel-token-r7"


# ============================================================ tiny scaffolding
class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def _gateway(**kwargs) -> tuple[BrowserAudioGateway, list[bytes]]:
    """A started, token-bound gateway plus the list its ear writes into."""

    heard: list[bytes] = []
    gateway = BrowserAudioGateway(on_audio=heard.append, **kwargs)
    gateway.bind_token(TOKEN)
    gateway.start()
    return gateway, heard


def _wav(ms: int) -> bytes:
    return pcm16_wav(pcm_tone(ms), sample_rate_hz=PCM16_SAMPLE_RATE_HZ)


# =================================================== A. the handshake is closed
def test_a_gateway_with_no_bound_token_refuses_every_connection() -> None:
    """Fail-closed: nothing is the panel until the panel says what it is."""

    gateway = BrowserAudioGateway(on_audio=lambda _pcm: None)
    gateway.start()
    with pytest.raises(GatewayAuthError) as caught:
        gateway.attach("anything at all")
    assert "no panel token bound" in str(caught.value)
    assert gateway.snapshot()["connections"] == 0
    assert gateway.snapshot()["connections_refused"] == 1


def test_a_wrong_token_is_refused_and_counted() -> None:
    gateway, _heard = _gateway()
    with pytest.raises(GatewayAuthError):
        gateway.attach(TOKEN + "x")
    with pytest.raises(GatewayAuthError):
        gateway.attach(None)
    assert gateway.snapshot()["connections_refused"] == 2
    assert gateway.snapshot()["connected"] is False


def test_a_stopped_gateway_refuses_before_it_even_looks_at_the_token() -> None:
    gateway, _heard = _gateway()
    gateway.stop()
    with pytest.raises(GatewayNotRunningError):
        gateway.attach(TOKEN)


def test_the_token_rides_as_a_subprotocol_not_a_query_parameter() -> None:
    chosen, token = select_csrf_subprotocol([SUBPROTOCOL_AUDIO, f"{CSRF_SUBPROTOCOL_PREFIX}abc"])
    assert (chosen, token) == (SUBPROTOCOL_AUDIO, "abc")
    assert select_csrf_subprotocol(["something-else"]) == (None, None)


# ============================================ B. connected is not yet listening
def test_attaching_gets_a_mouth_and_no_ear_until_the_owner_gestures() -> None:
    """Constraint 6: the gateway is ARMED BUT IDLE. This is that word, tested."""

    gateway, heard = _gateway()
    conn = gateway.attach(TOKEN)
    assert gateway.connected is True
    assert gateway.mic_open is False

    assert gateway.accept_audio(conn, b"\x01\x02" * 100) is False
    assert heard == []
    assert gateway.snapshot()["frames_refused_unarmed"] == 1
    assert gateway.snapshot()["frames_in"] == 0
    # And the browser is told once, rather than silently ignored.
    refusals = [json.loads(f) for f in conn.outbox if isinstance(f, str)]
    assert any(body["type"] == "refused" for body in refusals)

    assert gateway.set_mic(conn, True) is True
    assert gateway.accept_audio(conn, b"\x01\x02" * 100) is True
    assert heard == [b"\x01\x02" * 100]
    assert gateway.snapshot()["mic_open"] is True


def test_a_runtime_that_refuses_to_arm_leaves_the_microphone_shut() -> None:
    """No session, no budget, no credential ⇒ shut, and the browser hears why."""

    def _refuse(open_: bool) -> None:
        if open_:
            raise RuntimeError("the realtime lane has no panel handshake token")

    gateway, heard = _gateway(on_mic=_refuse)
    conn = gateway.attach(TOKEN)
    assert gateway.set_mic(conn, True) is False
    assert gateway.mic_open is False
    assert gateway.snapshot()["mic_refusals"] == 1
    assert gateway.accept_audio(conn, b"\x00" * 64) is False
    assert heard == []
    replies = [json.loads(f) for f in conn.outbox if isinstance(f, str)]
    denial = [body for body in replies if body["type"] == "mic" and body["on"] is False]
    assert denial and "no panel handshake token" in denial[-1]["reason"]


def test_the_mic_gesture_is_reported_to_the_runtime_exactly_once_per_edge() -> None:
    seen: list[bool] = []
    gateway, _heard = _gateway(on_mic=seen.append)
    conn = gateway.attach(TOKEN)
    gateway.set_mic(conn, True)
    gateway.set_mic(conn, True)
    gateway.set_mic(conn, False)
    gateway.set_mic(conn, False)
    assert seen == [True, False]


def test_a_control_frame_from_a_displaced_connection_is_refused() -> None:
    gateway, _heard = _gateway()
    first = gateway.attach(TOKEN)
    second = gateway.attach(TOKEN)
    assert gateway.snapshot()["connections_displaced"] == 1
    assert first.closed.is_set()
    assert gateway.set_mic(first, True) is False
    assert gateway.set_mic(second, True) is True


# ============================================ C. bounded buffers, drop-and-count
def test_the_outbound_queue_is_bounded_and_drops_the_oldest_with_a_counter() -> None:
    gateway, _heard = _gateway(max_outbound_frames=3)
    conn = gateway.attach(TOKEN)
    conn.drain()  # the hello frame
    gateway.begin_utterance()
    for index in range(6):
        gateway.send_audio(bytes([index]) * 10)
    frames = [f for f in conn.drain() if isinstance(f, bytes)]
    assert len(conn.outbox) == 0
    # Three survivors, and they are the NEWEST three.
    assert frames[-1] == bytes([5]) * 10
    assert len(frames) <= 3
    assert gateway.snapshot()["frames_dropped_backpressure"] >= 3
    assert gateway.snapshot()["frames_out"] == 6


def test_the_outbound_queue_is_also_bounded_in_bytes() -> None:
    gateway, _heard = _gateway(max_outbound_frames=10_000, max_outbound_bytes=2_048)
    conn = gateway.attach(TOKEN)
    conn.drain()
    for _ in range(50):
        gateway.send_audio(b"\x00" * 512)
    assert conn.queued_bytes <= 2_048
    assert gateway.snapshot()["frames_dropped_backpressure"] > 0


def test_an_oversized_microphone_frame_is_refused_rather_than_allocated() -> None:
    gateway, heard = _gateway()
    conn = gateway.attach(TOKEN)
    gateway.set_mic(conn, True)
    assert gateway.accept_audio(conn, b"\x00" * (DEFAULT_MAX_INBOUND_FRAME_BYTES + 1)) is False
    assert heard == []
    assert gateway.snapshot()["frames_oversize"] == 1
    assert gateway.accept_audio(conn, b"\x00" * DEFAULT_MAX_INBOUND_FRAME_BYTES) is True


def test_playback_with_nobody_listening_is_counted_and_never_raises() -> None:
    """``send_audio`` runs inside ``lane.pump``. An exception here kills the turn."""

    gateway, _heard = _gateway()
    gateway.begin_utterance()
    gateway.send_audio(b"RIFF" + b"\x00" * 40)
    gateway.interrupt()
    assert gateway.snapshot()["frames_dropped_no_client"] == 1
    assert gateway.snapshot()["frames_out"] == 0


# ================================================== D. the played clock, clamped
def test_a_played_ack_is_clamped_to_what_was_actually_transmitted() -> None:
    clock = _Clock()
    gateway, _heard = _gateway(clock=clock)
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    assert gateway.played_started_monotonic is None, "nothing heard yet ⇒ truncate at zero"

    # 48 bytes/ms at 24 kHz: 4 800 bytes is exactly 100 ms of audio.
    gateway.send_audio(b"\x00" * 4_800)
    first_send_at = clock.now
    clock.advance(10.0)
    assert gateway.ack_played(1, 999_999.0) is True
    anchor = gateway.played_started_monotonic
    assert anchor is not None
    # Clamped to 100 ms of elapsed playback, not the ten seconds it claimed.
    assert clock.now - anchor == pytest.approx(0.100, abs=1e-6)
    assert anchor > first_send_at


def test_a_played_ack_can_never_predate_the_first_byte_of_its_utterance() -> None:
    clock = _Clock()
    gateway, _heard = _gateway(clock=clock)
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 48_000)  # 1 000 ms transmitted
    first_send_at = clock.now
    clock.advance(0.010)  # only 10 ms of wall time has passed
    assert gateway.ack_played(1, 900.0) is True
    assert gateway.played_started_monotonic == pytest.approx(first_send_at)


def test_an_ack_for_a_previous_utterance_is_dropped_and_counted() -> None:
    gateway, _heard = _gateway()
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 4_800)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 4_800)
    assert gateway.ack_played(1, 50.0) is False
    assert gateway.snapshot()["stale_acks"] == 1
    assert gateway.played_started_monotonic is None


def test_a_new_utterance_and_a_barge_in_both_clear_the_anchor() -> None:
    gateway, _heard = _gateway()
    gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 4_800)
    assert gateway.ack_played(1, 10.0) is True
    assert gateway.played_started_monotonic is not None
    gateway.interrupt()
    assert gateway.played_started_monotonic is None


def test_a_nonsense_ack_is_a_counted_protocol_error_not_a_crash() -> None:
    gateway, _heard = _gateway()
    conn = gateway.attach(TOKEN)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 480)
    gateway.handle_control(conn, json.dumps({"type": "played", "utterance": "x", "ms": 1}))
    gateway.handle_control(conn, json.dumps({"type": "played", "utterance": 1, "ms": "soon"}))
    gateway.handle_control(conn, "not json at all")
    gateway.handle_control(conn, json.dumps({"type": "teleport"}))
    assert gateway.snapshot()["control_errors"] == 4
    assert gateway.played_started_monotonic is None


# ========================================================== E. barge-in, browser
def test_barge_in_clears_the_queue_and_tells_the_browser_to_stop() -> None:
    gateway, _heard = _gateway()
    conn = gateway.attach(TOKEN)
    conn.drain()
    gateway.begin_utterance()
    for _ in range(4):
        gateway.send_audio(b"\x00" * 128)
    gateway.interrupt()
    frames = conn.drain()
    assert not any(isinstance(f, bytes) for f in frames), "queued audio was discarded"
    controls = [json.loads(f) for f in frames if isinstance(f, str)]
    assert {"type": "stop", "utterance": 1} in controls
    assert gateway.snapshot()["interrupts"] == 1
    # An interrupted queue is the product working; backpressure is a defect.
    # Folding both into one number would make a panel with a stalled socket look
    # exactly like a chatty owner.
    assert gateway.snapshot()["frames_discarded_interrupt"] == 4
    assert gateway.snapshot()["frames_dropped_backpressure"] == 0


def test_microphone_frames_keep_flowing_while_hosted_audio_plays() -> None:
    """Without this there is no barge-in at all: the ear closes when the mouth opens."""

    gateway, heard = _gateway()
    conn = gateway.attach(TOKEN)
    gateway.set_mic(conn, True)
    gateway.begin_utterance()
    gateway.send_audio(b"\x00" * 4_800)
    assert gateway.accept_audio(conn, b"\x11" * 480) is True
    gateway.interrupt()
    assert gateway.accept_audio(conn, b"\x22" * 480) is True
    assert heard == [b"\x11" * 480, b"\x22" * 480]


def test_the_sink_contract_the_lane_expects_is_satisfied_by_this_gateway() -> None:
    """``BrowserSink`` over the gateway is a ``SinkLike``. Both halves counted."""

    gateway, _heard = _gateway()
    conn = gateway.attach(TOKEN)
    conn.drain()
    sink = BrowserSink(gateway)
    assert sink.first_chunk_started_monotonic is None
    sink.begin_utterance()
    sink.enqueue(_wav(20))
    sink.enqueue(b"")  # empty chunks never reach the wire
    sink.interrupt()
    assert sink.snapshot()["utterances"] == 1
    assert sink.snapshot()["chunks_sent"] == 1
    assert gateway.snapshot()["utterances"] == 1
    assert gateway.snapshot()["interrupts"] == 1


# ================================================ F. the real socket, real panel
class _PanelRuntime:
    """The two members ``web_panel`` actually uses for this route."""

    def __init__(self, gateway: object | None) -> None:
        self.realtime_gateway = gateway
        self.bound: list[str] = []

    def snapshot(self) -> dict[str, object]:
        return {"status": "test"}

    def bind_panel_token(self, token: str) -> None:
        self.bound.append(token)
        binder = getattr(self.realtime_gateway, "bind_token", None)
        if callable(binder):
            binder(token)


@pytest.fixture()
def panel():
    """A real loopback panel whose gateway is a real gateway. Torn down properly."""

    heard: list[bytes] = []
    gateway = BrowserAudioGateway(on_audio=heard.append)
    gateway.start()
    runtime = _PanelRuntime(gateway)
    server = RuntimeHTTPServer(("127.0.0.1", 0), runtime)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, gateway, heard
    finally:
        gateway.stop()
        server.shutdown()
        server.server_close()
        thread.join(2.0)


def _url(server: RuntimeHTTPServer) -> str:
    host, port = server.server_address[:2]
    return f"ws://{host}:{port}{GATEWAY_PATH}"


def _subs(token: str) -> list[str]:
    return [SUBPROTOCOL_AUDIO, f"{CSRF_SUBPROTOCOL_PREFIX}{token}"]


def _recv_json(client, timeout: float = 3.0) -> dict:
    while True:
        message = client.recv(timeout=timeout)
        if isinstance(message, str):
            return json.loads(message)


def test_a_real_client_without_the_panel_token_is_closed_on_policy(panel) -> None:
    server, gateway, _heard = panel
    with (
        pytest.raises(ConnectionClosed) as caught,
        connect(_url(server), subprotocols=_subs("not-the-token")) as client,
    ):
        client.recv(timeout=3.0)
    assert "policy" in str(caught.value).lower() or "1008" in str(caught.value)
    assert gateway.snapshot()["connections_refused"] == 1
    assert gateway.snapshot()["frames_in"] == 0


def test_a_real_client_with_the_panel_token_gets_the_negotiated_wire_format(panel) -> None:
    server, _gw, _heard = panel
    with connect(_url(server), subprotocols=_subs(server.csrf_token)) as client:
        hello = _recv_json(client)
    assert hello["type"] == "hello"
    assert hello["input"] == {
        "format": "pcm16",
        "rate": PCM16_SAMPLE_RATE_HZ,
        "channels": 1,
        "max_frame_bytes": DEFAULT_MAX_INBOUND_FRAME_BYTES,
    }
    assert hello["mic_open"] is False


def test_a_real_socket_refuses_audio_until_the_real_gesture_frame_arrives(panel) -> None:
    server, gateway, heard = panel
    with connect(_url(server), subprotocols=_subs(server.csrf_token)) as client:
        _recv_json(client)
        client.send(b"\x01\x02" * 240)
        refusal = _recv_json(client)
        assert refusal["type"] == "refused"
        assert heard == []

        client.send(json.dumps({"type": "mic", "on": True}))
        assert _recv_json(client) == {"type": "mic", "on": True, "reason": "armed"}
        client.send(b"\x03\x04" * 240)
        deadline = time.monotonic() + 3.0
        while not heard and time.monotonic() < deadline:
            time.sleep(0.01)
    assert heard == [b"\x03\x04" * 240]
    assert gateway.snapshot()["frames_refused_unarmed"] == 1


def test_a_real_socket_carries_playback_and_the_barge_in_stop_frame(panel) -> None:
    server, gateway, _heard = panel
    with connect(_url(server), subprotocols=_subs(server.csrf_token)) as client:
        _recv_json(client)
        gateway.begin_utterance()
        assert _recv_json(client) == {"type": "utterance", "utterance": 1}
        gateway.send_audio(_wav(20))
        played = client.recv(timeout=3.0)
        assert isinstance(played, bytes | bytearray)
        assert bytes(played)[:4] == b"RIFF"
        gateway.interrupt()
        assert _recv_json(client) == {"type": "stop", "utterance": 1}


def test_a_text_control_frame_is_never_mistaken_for_microphone_audio(panel) -> None:
    """``Frame.data`` is bytes for TEXT too; only the opcode tells them apart."""

    server, gateway, heard = panel
    with connect(_url(server), subprotocols=_subs(server.csrf_token)) as client:
        _recv_json(client)
        client.send(json.dumps({"type": "mic", "on": True}))
        _recv_json(client)
        client.send(json.dumps({"type": "played", "utterance": 7, "ms": 1}))
        time.sleep(0.2)
    assert heard == [], "a JSON control frame must never be appended to the input buffer"
    assert gateway.snapshot()["stale_acks"] == 1


def test_a_second_panel_displaces_the_first_and_the_first_is_closed(panel) -> None:
    server, gateway, _heard = panel
    first = connect(_url(server), subprotocols=_subs(server.csrf_token))
    _recv_json(first)
    with connect(_url(server), subprotocols=_subs(server.csrf_token)) as second:
        _recv_json(second)
        with pytest.raises(ConnectionClosed):
            while True:
                first.recv(timeout=3.0)
    first.close()
    assert gateway.snapshot()["connections_displaced"] == 1


def test_the_route_is_a_404_when_no_gateway_was_constructed() -> None:
    """``mode: text`` ⇒ the endpoint does not exist, rather than existing and idling."""

    import urllib.error
    import urllib.request

    runtime = _PanelRuntime(None)
    server = RuntimeHTTPServer(("127.0.0.1", 0), runtime)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"http://{host}:{port}{GATEWAY_PATH}", timeout=3)
        assert caught.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2.0)


def test_a_plain_get_on_the_gateway_route_is_426_not_a_body(panel) -> None:
    import urllib.error
    import urllib.request

    server, _gateway, _heard = panel
    host, port = server.server_address[:2]
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"http://{host}:{port}{GATEWAY_PATH}", timeout=3)
    assert caught.value.code == 426


def test_a_cross_origin_audio_socket_is_forbidden(panel) -> None:
    import urllib.error
    import urllib.request

    server, _gateway, _heard = panel
    host, port = server.server_address[:2]
    request = urllib.request.Request(
        f"http://{host}:{port}{GATEWAY_PATH}",
        headers={
            "Upgrade": "websocket",
            "Connection": "Upgrade",
            "Origin": "http://evil.example",
            "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
            "Sec-WebSocket-Version": "13",
        },
    )
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=3)
    assert caught.value.code == 403


# ============================================= G. the browser half, as source
PANEL = REPO / "src" / "parcel_robot" / "ui" / "index.html"


def test_the_mic_affordance_is_actually_wired_to_the_gateway() -> None:
    """The button existed before this card and did nothing. Pin that it does now."""

    source = PANEL.read_text(encoding="utf-8")
    # The WHOLE wiring block, guard included. A substring check on the
    # addEventListener line alone survives `if (false) {` around it, which is a
    # button that is present, visible, and dead.
    assert (
        '    if (el("mic-button")) {\n'
        '      el("mic-button").addEventListener("click", () => {\n'
        "        if (state.mic) {\n"
        '          stopMic("Microphone closed");\n'
        "          return;\n"
        "        }\n"
        "        startMic();\n"
        "      });\n"
        "    }"
    ) in source
    assert 'el("mic-button").hidden = realtime.mode !== "audio";' in source


def test_the_panel_token_never_reaches_the_gateway_url() -> None:
    """A token in the URL is a token in the terminal: the panel logs request lines."""

    source = PANEL.read_text(encoding="utf-8")
    assert '`parcel-csrf.${CSRF_TOKEN}`' in source
    assert "audio?token=" not in source
    assert f'"{GATEWAY_PATH}?' not in source


def test_the_browser_arms_the_microphone_only_after_the_gateway_says_hello() -> None:
    """R7's rule, through MARK-1's arming path.

    Card MARK-1 moved the arming frame into ``armEar``, which first applies the
    capture beam the hello names and then says which ear it actually opened. The
    rule R7 pinned is unchanged and is still what is asserted: the frame that
    opens the ear is sent from the hello branch and from nowhere else.
    """

    source = PANEL.read_text(encoding="utf-8")
    assert 'type: "mic", on: true, channels: mic.captureChannels, beam: mic.beam,' in source
    assert source.count('type: "mic", on: true') == 1, "one arming frame, one place"
    # And it is reached from the hello branch, not on socket open.
    hello_at = source.index('if (body.type === "hello")')
    call_at = source.index("armEar(mic, body.capture);")
    mic_at = source.index('if (body.type === "mic")')
    assert hello_at < call_at < mic_at


def test_the_browser_stops_local_playback_on_the_barge_in_frame() -> None:
    """Constraint 4: the lane cancels the response; the tab must stop its buffer."""

    source = PANEL.read_text(encoding="utf-8")
    assert 'if (body.type === "stop") {\n          stopPlayback(mic);' in source
    assert "function stopPlayback(mic) {" in source
    assert "mic.sources.splice(0).forEach((source) => { try { source.stop(); } catch (_) {} });" in source


def test_microphone_capture_is_never_gated_on_playback_state() -> None:
    """Mic frames keep flowing while the robot speaks, or barge-in cannot happen."""

    source = PANEL.read_text(encoding="utf-8")
    start = source.index("mic.processor.onaudioprocess")
    body = source[start : source.index("mic.source.connect(mic.processor);")]
    assert "playAt" not in body and "sources" not in body
    assert "if (payload.byteLength <= mic.maxFrameBytes) mic.socket.send(payload);" in body


def test_the_browser_resamples_to_the_rate_the_gateway_named() -> None:
    source = PANEL.read_text(encoding="utf-8")
    assert "function encodeMicFrame(samples, fromRate, toRate)" in source
    assert "mic.rate = Number(body.input && body.input.rate) || 24000;" in source
    # Card MARK-1: the ear is the pinned beam (``ear``), not channel 0 — the
    # XVF3800's channel 0 is the conference beam and 1 is the ASR beam. The
    # resample this test is about is unchanged.
    assert (
        "encodeMicFrame(event.inputBuffer.getChannelData(ear), mic.capture.sampleRate, mic.rate)"
        in source
    )


# ================================================ H. the whole pipe, end to end
class _Backend:
    name = BACKEND_NAME

    def observe(self) -> SimObservation:
        return SimObservation(
            timestamp=time.monotonic(),
            robot=RobotPose(),
            owner=OwnerTrack(),
            nearest_obstacle_m=10.0,
            backend=BACKEND_NAME,
        )

    def move(self, command: VelocityCommand) -> None:
        del command

    def stop(self) -> None:
        return None

    def emergency_stop(self) -> None:
        return None

    def pose(self, pose: object) -> None:
        del pose

    def trajectory(self, skill: object) -> None:
        del skill

    def move_owner(self, dx: float, dy: float) -> None:
        del dx, dy


class _SilentModel:
    def decide(self, transcript, tools, context) -> AgentDecision:
        del tools, context, transcript
        return AgentDecision("Understood.")


def _runtime(tmp_path: Path) -> RobotRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / "r7-audio.yaml"
    path.write_text(
        f"""
skills:
  root: {REPO / "configs" / "skills"}
navigation:
  enabled: true
motion:
  backend: rl
  rl:
    enabled: true
    policy_path: ""
agent:
  prompts_root: {REPO / "prompts"}
memory:
  path: ":memory:"
duplex:
  enabled: true
  logging: false
poses: {{}}
modules: []
""",
        encoding="utf-8",
    )
    return RobotRuntime(
        path,
        _Backend(),
        language_model=_SilentModel(),
        audio_status=AudioDeviceStatus(
            status="no hardware",
            driver="test",
            capture_hardware=False,
            connected_input=False,
            connected_output=False,
            detail="r7 audio fixture",
        ),
    )


@pytest.fixture()
def audio_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: audio\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PARCEL_REALTIME_KEY_ENV", raising=False)
    runtime = _runtime(tmp_path)
    try:
        yield runtime
    finally:
        runtime.close()


def test_mode_audio_constructs_a_gateway_that_is_armed_but_idle(audio_runtime) -> None:
    """It used to raise here. Constraint 6, as a construction fact."""

    runtime = audio_runtime
    assert runtime.realtime_config.mode == "audio"
    assert isinstance(runtime.realtime_gateway, BrowserAudioGateway)
    assert isinstance(runtime.realtime_lane._sink, BrowserSink)
    snapshot = runtime.realtime_snapshot()
    assert snapshot["gateway"]["running"] is True
    assert snapshot["gateway"]["connected"] is False
    assert snapshot["gateway"]["mic_open"] is False
    # Armed but idle means NO paid session and no driver thread at boot.
    assert runtime.realtime_lane.active is False
    assert runtime.realtime_driver.running is False


def test_text_mode_still_builds_a_discard_sink_and_no_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "realtime.yaml"
    config.write_text("enabled: true\nmode: text\n", encoding="utf-8")
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    runtime = _runtime(tmp_path)
    try:
        assert runtime.realtime_gateway is None
        assert isinstance(runtime.realtime_lane._sink, DiscardSink)
        assert runtime.realtime_snapshot()["gateway"] is None
    finally:
        runtime.close()


def test_the_panel_token_reaches_the_gateway_that_guards_the_socket(audio_runtime) -> None:
    runtime = audio_runtime
    assert runtime.realtime_gateway.snapshot()["token_bound"] is False
    server = RuntimeHTTPServer(("127.0.0.1", 0), runtime)
    try:
        assert runtime.realtime_gateway.snapshot()["token_bound"] is True
        runtime.realtime_gateway.attach(server.csrf_token)
    finally:
        server.server_close()


def test_a_non_speaker_sink_is_never_a_sink_ownership_conflict(audio_runtime) -> None:
    """R4L open risk 6, diagnosed: there was nothing to contend for.

    ``assert_sink_free`` exists because two writers to ONE ordered PortAudio
    queue interleave. The lane's sink is a ``BrowserSink`` (or a ``DiscardSink``
    in text mode) and never that queue, so reporting the local duplex session's
    state was a false positive that raised ``SinkOwnershipError`` out of
    ``_on_audio`` into ``pump()`` — the three ``pump failed: … DuplexVoiceSession
    output is live`` lines in R4-lite live session 1.
    """

    runtime = audio_runtime
    lane = runtime.realtime_lane
    busy = SimpleNamespace(cancel_event=threading.Event())
    runtime.voice_session._active_output = busy  # the local mouth is busy
    try:
        assert runtime._realtime_shares_local_speaker() is False
        lane.assert_sink_free()  # would raise before this card

        # And the law itself is unchanged: a sink this method does not recognise
        # as a non-speaker falls back to the duplex flag and the assertion fires.
        lane._sink = SimpleNamespace(first_chunk_started_monotonic=None)
        assert runtime._realtime_shares_local_speaker() is True
        with pytest.raises(RuntimeError, match="DuplexVoiceSession output is live"):
            lane.assert_sink_free()
    finally:
        runtime.voice_session._active_output = None


def test_hosted_audio_reaches_the_browser_through_the_whole_real_pipe(
    audio_runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mic PCM up → fake provider → transcript through ingress → audio down.

    The only fake is the provider. The panel, the websocket, the gateway, the
    sink, the lane, the ingress and the ledger are all the shipped objects.
    """

    runtime = audio_runtime
    script = [
        *handshake(),
        Step(
            "input_audio_buffer.append",
            (
                input_transcript("item_owner", "go to the sidewalk"),
                audio_delta("resp_1", "item_robot", pcm_tone(40)),
                transcript_done("resp_1", "item_robot", "On my way."),
                audio_done("resp_1", "item_robot"),
                response_done("resp_1"),
            ),
            label="spoken_turn",
        ),
    ]
    stop = threading.Event()
    pumps: list[threading.Thread] = []

    def _factory():
        lane_end, server_end = transport_pair()
        fake = FakeRealtimeServer(transport=server_end, script=list(script))

        def _crank() -> None:
            while not stop.is_set():
                try:
                    fake.pump()
                except TransportClosed:
                    return
                time.sleep(0.01)

        thread = threading.Thread(target=_crank, daemon=True)
        thread.start()
        pumps.append(thread)
        return lane_end

    monkeypatch.setattr(runtime.realtime_lane, "_transport_factory", _factory)

    panel_server = RuntimeHTTPServer(("127.0.0.1", 0), runtime)
    thread = threading.Thread(target=panel_server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = panel_server.server_address[:2]
        url = f"ws://{host}:{port}{GATEWAY_PATH}"
        with connect(url, subprotocols=_subs(panel_server.csrf_token)) as client:
            assert _recv_json(client)["type"] == "hello"
            client.send(json.dumps({"type": "mic", "on": True}))
            assert _recv_json(client)["on"] is True
            # Opening the microphone is what opened the paid session.
            assert runtime.realtime_lane.active is True
            client.send(b"\x05\x06" * 480)

            audio_back: list[bytes] = []
            deadline = time.monotonic() + 5.0
            while not audio_back and time.monotonic() < deadline:
                try:
                    message = client.recv(timeout=0.5)
                except TimeoutError:
                    continue
                if isinstance(message, bytes | bytearray):
                    audio_back.append(bytes(message))
    finally:
        panel_server.shutdown()
        panel_server.server_close()
        thread.join(2.0)
        stop.set()
        for pump in pumps:
            pump.join(2.0)

    assert audio_back, "hosted audio never reached the browser"
    assert audio_back[0][:4] == b"RIFF"
    ledger = [
        (row["speaker"], row["content"]) for row in runtime.agent.memory.realtime_turns(limit=10)
    ]
    assert ("owner", "go to the sidewalk") in ledger
    assert any(speaker == "robot" for speaker, _ in ledger)
    gateway_snapshot = runtime.realtime_snapshot()["gateway"]
    assert gateway_snapshot["frames_in"] >= 1
    assert gateway_snapshot["frames_out"] >= 1


# ================================================ card R17: the config-gated tee
def test_capture_is_not_constructed_unless_the_config_asks_for_it(audio_runtime) -> None:
    """Default OFF, end to end: `mode: audio` alone records nothing.

    The whole feature hangs off one wiring line in ``_build_realtime_sink``, so
    the thing worth pinning is that the line is CONDITIONAL. A build that
    constructed a capture whenever the gateway existed would start writing a
    household microphone to disk for every owner who ever set `mode: audio`.
    """

    runtime = audio_runtime
    assert runtime.realtime_config.capture.enabled is False
    assert runtime.realtime_gateway._capture is None
    assert runtime.realtime_snapshot()["gateway"]["capture"] == {"enabled": False}


def test_the_capture_block_wires_the_tee_into_the_live_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`capture.enabled: true` ⇒ the gateway's audio paths tee to WAVs on disk."""

    recordings = tmp_path / "recordings"
    config = tmp_path / "realtime.yaml"
    config.write_text(
        "enabled: true\n"
        "mode: audio\n"
        "capture:\n"
        "  enabled: true\n"
        f"  dir: {recordings}\n"
        "  max_minutes: 2\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runtime = _runtime(tmp_path)
    try:
        capture = runtime.realtime_gateway._capture
        assert capture is not None
        assert capture.running is True
        assert capture.directory.parent == recordings
        snapshot = runtime.realtime_snapshot()["gateway"]["capture"]
        assert snapshot["enabled"] is True
        assert snapshot["max_minutes"] == 2.0

        gateway = runtime.realtime_gateway
        gateway.bind_token(TOKEN)
        conn = gateway.attach(TOKEN)
        conn.mic_open = True
        gateway.accept_audio(conn, b"\x09\x0a" * 480)
        gateway.begin_utterance()
        gateway.send_audio(pcm16_wav(b"\x0b\x0c" * 240, sample_rate_hz=PCM16_SAMPLE_RATE_HZ))
        gateway.stop()

        index = json.loads((capture.directory / "index.json").read_text(encoding="utf-8"))
        assert verify_capture_index(index, session_dir=capture.directory) == []
        assert index["streams"]["owner"]["data_bytes"] == 960
        assert index["streams"]["robot"]["data_bytes"] == 480
    finally:
        runtime.close()


def test_a_capture_dir_inside_the_eval_tree_refuses_the_whole_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An eval fixture is the record a run is scored against. Fail-closed."""

    config = tmp_path / "realtime.yaml"
    config.write_text(
        "enabled: true\nmode: audio\ncapture:\n  enabled: true\n  dir: evals/20260820\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(REALTIME_CONFIG_ENV, str(config))
    with pytest.raises(RealtimeConfigError, match="inside"):
        _runtime(tmp_path)
