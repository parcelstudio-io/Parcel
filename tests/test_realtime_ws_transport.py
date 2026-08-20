"""Card R1.5: ``WebSocketTransport`` against a real loopback WebSocket server.

WHY A REAL SERVER AND NOT A MOCK
--------------------------------
Every claim this file makes is about framing, threading and close codes — the
three things a mock of ``websockets`` would define into existence rather than
test. So each test starts an actual ``websockets.sync.server`` on 127.0.0.1 with
an ephemeral port, in this process, with no network, no credential and no
provider. What is exercised is the genuine article: a real opening handshake, a
real reader thread, real RFC 6455 close codes.

WHAT IS *NOT* PROVEN HERE
-------------------------
That the hosted provider behaves like these scripts. It is scripted here
because it cannot be reached — the account has no billing quota. See
``R1_5_STATUS.md``.

ON WAITING
----------
Nothing in this file sleeps to make an assertion true. ``_settle`` blocks on the
transport's own arrival event until a stated condition holds, with a generous
deadline; an assertion either holds or the test fails loudly. The only timing
assertion is an upper bound proving ``receive()`` does not block, and it is 20x
away from the value that would flake.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest
from websockets.sync.server import ServerConnection, serve

from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.lane import RealtimeLane
from parcel_robot.realtime.protocol import SessionUpdate
from parcel_robot.realtime.transport import Transport, TransportClosed
from parcel_robot.realtime.ws_transport import (
    DEFAULT_API_KEY_ENV,
    REDACTED,
    RealtimeAuthError,
    RealtimeConnectError,
    RealtimeQuotaError,
    RealtimeTransportError,
    WebSocketTransport,
    realtime_url,
    redact,
    websocket_transport_factory,
)

#: A credential-shaped string that is not a credential. Deliberately wears the
#: ``sk-`` prefix so the pattern half of :func:`redact` is exercised too.
FAKE_KEY = f"sk-parcel-test-{uuid.uuid4().hex}"

#: How long a test will wait for a real socket on loopback before giving up.
SETTLE_S = 5.0

CLOSE_TRY_AGAIN_LATER = 1013

QUOTA_FRAME = {
    "type": "error",
    "error": {
        "type": "invalid_request_error",
        "code": "insufficient_quota",
        "message": "You exceeded your current quota, please check your plan and billing details.",
    },
}


def test_voice_extra_declares_the_realtime_transport_dependency() -> None:
    """A clean CI/wheel install must not rely on the developer venv's lock."""

    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    voice_block = pyproject.split("voice = [", 1)[1].split("]", 1)[0]
    assert '"websockets>=17,<18"' in voice_block


# --------------------------------------------------------------------- rigs
class LoopbackServer:
    """A real WebSocket server on an ephemeral loopback port, in this process."""

    def __init__(
        self,
        handler: Callable[[ServerConnection], None],
        *,
        process_request: Callable[..., Any] | None = None,
    ) -> None:
        self.received: list[str] = []
        self.headers: dict[str, str] = {}
        self.done = threading.Event()
        self._server = serve(
            self._wrap(handler),
            "127.0.0.1",
            0,
            process_request=process_request,
            compression=None,
            ping_interval=None,
        )
        self.port = int(self._server.socket.getsockname()[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def _wrap(self, handler: Callable[[ServerConnection], None]):
        def _run(connection: ServerConnection) -> None:
            self.headers = {
                str(key): str(value) for key, value in connection.request.headers.raw_items()
            }
            try:
                handler(connection)
            finally:
                self.done.set()

        return _run

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=SETTLE_S)


@pytest.fixture
def key_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """The credential lives in the environment under a name, as in production."""

    monkeypatch.setenv(DEFAULT_API_KEY_ENV, FAKE_KEY)
    return DEFAULT_API_KEY_ENV


@pytest.fixture
def loopback():
    """Start/stop one scripted server per test."""

    servers: list[LoopbackServer] = []

    def _start(handler, *, process_request=None) -> LoopbackServer:
        server = LoopbackServer(handler, process_request=process_request)
        servers.append(server)
        return server

    yield _start
    for server in servers:
        server.stop()


@pytest.fixture
def transports():
    """Every transport a test opens gets closed, pass or fail."""

    built: list[WebSocketTransport] = []

    def _open(server: LoopbackServer, **kwargs: Any) -> WebSocketTransport:
        transport = WebSocketTransport(url=server.url, allow_insecure=True, **kwargs)
        built.append(transport)
        return transport.open()

    yield _open
    for transport in built:
        transport.close()


def _settle(
    transport: WebSocketTransport,
    *,
    frames: int = 0,
    down: bool = False,
    timeout: float = SETTLE_S,
) -> None:
    """Block on the transport's arrival event until the condition holds."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if transport.pending >= frames and (transport.closed or not down):
            return
        transport.wait(timeout=0.02)
    raise AssertionError(
        f"transport never settled: pending={transport.pending} closed={transport.closed} "
        f"wanted frames>={frames} down={down}"
    )


def _until(predicate: Callable[[], bool], *, what: str, timeout: float = SETTLE_S) -> None:
    """Block until a server-side fact is true. Never asserts on how long it took."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError(f"never became true within {timeout:.1f}s: {what}")


def _emit(connection: ServerConnection, payload: Mapping[str, Any]) -> None:
    connection.send(json.dumps(dict(payload)))


def _collect(connection: ServerConnection, server: LoopbackServer, count: int) -> None:
    for _ in range(count):
        server.received.append(str(connection.recv()))


# ----------------------------------------------------------------- the seam
def test_it_is_the_transport_the_lane_already_knows(key_env: str) -> None:
    """R1's Protocol is runtime-checkable; this class satisfies it unopened."""

    transport = WebSocketTransport(model="gpt-realtime-2.1-mini", api_key_env=key_env)
    assert isinstance(transport, Transport)
    assert "unopened" in repr(transport)
    assert realtime_url("gpt-realtime-2.1-mini").endswith("?model=gpt-realtime-2.1-mini")


def test_a_frame_goes_up_and_the_answer_comes_back(key_env, loopback, transports) -> None:
    """Round trip over real framing: a typed ClientEvent up, a mapping down."""

    def handler(connection: ServerConnection) -> None:
        raw = str(connection.recv())
        _emit(connection, {"type": "session.created", "session": {"id": "sess_live_1"}})
        _emit(connection, {"type": "echo", "saw": json.loads(raw)["type"]})

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)
    transport.send(SessionUpdate(instructions="be a good dog", model="m", voice="cedar"))

    _settle(transport, frames=2)
    created = transport.receive()
    echoed = transport.receive()
    assert created is not None and created["session"]["id"] == "sess_live_1"
    assert echoed is not None and echoed["saw"] == "session.update"
    assert transport.sent_frames == 1
    assert transport.received_frames == 2
    assert transport.receive() is None


def test_receive_returns_none_when_idle_and_never_blocks(key_env, loopback, transports) -> None:
    """The lane pumps in a tight loop; a blocking receive would stall the robot."""

    def handler(connection: ServerConnection) -> None:
        connection.recv()

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)

    started = time.monotonic()
    for _ in range(500):
        assert transport.receive() is None
    elapsed = time.monotonic() - started
    # One socket poll interval is 50 ms; 500 blocking reads would be ~25 s.
    assert elapsed < 1.0, f"500 idle receives took {elapsed:.3f}s — receive() blocked"


def test_the_backlog_drains_before_the_hang_up_is_reported(key_env, loopback, transports) -> None:
    """``InProcessTransport``'s documented ordering, reproduced on a real socket."""

    def handler(connection: ServerConnection) -> None:
        for index in range(3):
            _emit(connection, {"type": "response.output_audio.delta", "n": index})
        connection.close(1000, "done")

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)

    _settle(transport, frames=3, down=True)
    assert transport.closed is True
    seen = [transport.receive(), transport.receive(), transport.receive()]
    assert [frame["n"] for frame in seen if frame is not None] == [0, 1, 2]
    with pytest.raises(TransportClosed) as caught:
        transport.receive()
    assert "hung up" in str(caught.value)


def test_close_is_idempotent_and_a_closed_transport_still_drains(
    key_env, loopback, transports
) -> None:
    """``close()`` twice is fine, and it does not throw away what already arrived."""

    def handler(connection: ServerConnection) -> None:
        for index in range(2):
            _emit(connection, {"type": "response.output_audio.delta", "n": index})
        connection.recv()

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)
    _settle(transport, frames=2)

    transport.close()
    transport.close()
    assert transport.closed is True
    assert transport.receive() is not None
    assert transport.receive() is not None
    with pytest.raises(TransportClosed):
        transport.receive()
    with pytest.raises(TransportClosed):
        transport.send({"type": "response.cancel"})


def test_overflow_drops_the_oldest_frames_and_counts_them(key_env, loopback, transports) -> None:
    """A bounded buffer keeps the newest state instead of growing without limit."""

    def handler(connection: ServerConnection) -> None:
        for index in range(12):
            _emit(connection, {"type": "response.output_audio.delta", "n": index})
        connection.close(1000, "done")

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env, max_inbound=4)

    _settle(transport, frames=4, down=True)
    survivors = []
    while True:
        try:
            frame = transport.receive()
        except TransportClosed:
            break
        if frame is None:  # pragma: no cover - the socket is already down
            break
        survivors.append(frame["n"])

    assert survivors == [8, 9, 10, 11]
    assert transport.dropped_frames == 8
    assert transport.received_frames == 12
    assert transport.diagnostics()["dropped_frames"] == 8


def test_a_frame_that_is_not_a_json_object_is_counted_and_never_delivered(
    key_env, loopback, transports
) -> None:
    """Garbage in the stream is recorded, not silently forgotten and not invented."""

    def handler(connection: ServerConnection) -> None:
        connection.send("this is not json")
        connection.send(json.dumps([1, 2, 3]))
        _emit(connection, {"type": "session.created", "session": {"id": "sess_ok"}})
        connection.close(1000, "done")

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)

    _settle(transport, frames=1, down=True)
    frame = transport.receive()
    assert frame is not None and frame["type"] == "session.created"
    assert transport.decode_errors == 2
    assert transport.received_frames == 1


# ------------------------------------------------------------ typed refusals
def test_insufficient_quota_then_1013_raises_a_typed_quota_error(
    key_env, loopback, transports
) -> None:
    """Today's live shape, scripted: the error frame lands, then the typed raise."""

    def handler(connection: ServerConnection) -> None:
        _emit(connection, QUOTA_FRAME)
        connection.close(CLOSE_TRY_AGAIN_LATER, "insufficient_quota")

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)

    _settle(transport, frames=1, down=True)
    delivered = transport.receive()
    assert delivered is not None and delivered["error"]["code"] == "insufficient_quota"

    with pytest.raises(RealtimeQuotaError) as caught:
        transport.receive()
    message = str(caught.value)
    assert "quota" in message and "1013" in message
    assert "billing" in message
    # The whole point of the type: the lane's reconnect path must not catch it.
    assert not isinstance(caught.value, TransportClosed)
    assert transport.down_kind == "quota"


def test_a_bare_1013_without_an_error_frame_is_still_a_quota_refusal(
    key_env, loopback, transports
) -> None:
    """Close code alone is enough; the provider does not always narrate."""

    def handler(connection: ServerConnection) -> None:
        connection.close(CLOSE_TRY_AGAIN_LATER, "try again later")

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)

    _settle(transport, down=True)
    with pytest.raises(RealtimeQuotaError):
        transport.receive()


def test_the_quota_diagnosis_survives_an_overflow_that_drops_the_error_frame(
    key_env, loopback, transports
) -> None:
    """Classification happens before enqueueing, so a full buffer cannot hide it."""

    def handler(connection: ServerConnection) -> None:
        _emit(connection, QUOTA_FRAME)
        for index in range(6):
            _emit(connection, {"type": "response.output_audio.delta", "n": index})
        connection.close(CLOSE_TRY_AGAIN_LATER, "insufficient_quota")

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env, max_inbound=2)

    _settle(transport, frames=2, down=True)
    assert transport.dropped_frames >= 1
    with pytest.raises(RealtimeQuotaError) as caught:
        for _ in range(4):
            transport.receive()
    assert "exceeded your current quota" in str(caught.value)


def test_a_401_handshake_rejection_raises_a_typed_auth_error(key_env, loopback) -> None:
    """No socket ever opens; the refusal is typed and names the variable."""

    def reject(connection: ServerConnection, request) -> Any:
        del request
        return connection.respond(HTTPStatus.UNAUTHORIZED, "invalid api key\n")

    def handler(connection: ServerConnection) -> None:  # pragma: no cover - never reached
        connection.recv()

    server = loopback(handler, process_request=reject)
    transport = WebSocketTransport(url=server.url, allow_insecure=True, api_key_env=key_env)
    with pytest.raises(RealtimeAuthError) as caught:
        transport.open()
    assert "401" in str(caught.value)
    assert key_env in str(caught.value)
    assert not isinstance(caught.value, TransportClosed)


def test_an_unexpected_handshake_status_is_a_connect_error_not_an_auth_error(
    key_env, loopback
) -> None:
    """Typed does not mean over-claimed: a 500 is not evidence about a credential."""

    def reject(connection: ServerConnection, request) -> Any:
        del request
        return connection.respond(HTTPStatus.INTERNAL_SERVER_ERROR, "boom\n")

    def handler(connection: ServerConnection) -> None:  # pragma: no cover - never reached
        connection.recv()

    server = loopback(handler, process_request=reject)
    transport = WebSocketTransport(url=server.url, allow_insecure=True, api_key_env=key_env)
    with pytest.raises(RealtimeConnectError) as caught:
        transport.open()
    assert not isinstance(caught.value, RealtimeAuthError)
    assert "500" in str(caught.value)


def test_a_refused_port_is_a_connect_error(key_env, loopback) -> None:
    """Nothing listening is a connect failure, not a credential verdict."""

    def handler(connection: ServerConnection) -> None:  # pragma: no cover - never reached
        connection.recv()

    server = loopback(handler)
    port = server.port
    server.stop()
    transport = WebSocketTransport(
        url=f"ws://127.0.0.1:{port}",
        allow_insecure=True,
        api_key_env=key_env,
        open_timeout_s=2.0,
    )
    with pytest.raises(RealtimeConnectError):
        transport.open()


def test_send_after_a_quota_refusal_reports_the_quota_not_a_bare_close(
    key_env, loopback, transports
) -> None:
    """The lane's first symptom is usually a send; it must say the real reason."""

    def handler(connection: ServerConnection) -> None:
        _emit(connection, QUOTA_FRAME)
        connection.close(CLOSE_TRY_AGAIN_LATER, "insufficient_quota")

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)
    _settle(transport, down=True)

    with pytest.raises(RealtimeQuotaError):
        transport.send({"type": "response.cancel"})


def test_a_send_that_beats_the_reader_to_the_close_still_names_the_reason(
    key_env, loopback, transports
) -> None:
    """``send`` is the second place a close surfaces, and it maps it identically.

    The reader thread is stopped first — a white-box move on *this* class, not a
    mock of ``websockets`` — so the close is discovered inside ``conn.send``
    rather than inside ``conn.recv``. Without this, the ``except
    ConnectionClosed`` arm of ``send`` is never executed by any test.
    """

    def handler(connection: ServerConnection) -> None:
        connection.recv()
        connection.close(CLOSE_TRY_AGAIN_LATER, "insufficient_quota")

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)
    transport._stop.set()
    reader = transport._thread
    assert reader is not None
    reader.join(timeout=SETTLE_S)
    assert not reader.is_alive()

    transport.send({"type": "response.cancel"})
    _until(server.done.is_set, what="the server closed the socket")
    assert transport.down_kind is None, "the reader is stopped; nothing should have marked it down"

    refused: list[str] = []

    def _refused_yet() -> bool:
        try:
            transport.send({"type": "response.cancel"})
        except RealtimeQuotaError as error:
            refused.append(str(error))
            return True
        return False

    _until(_refused_yet, what="send observed the 1013 close")
    assert "quota" in refused[0]
    assert transport.down_kind == "quota"


# ------------------------------------------------------------- the credential
def test_a_missing_environment_variable_refuses_before_any_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed at the credential, and say which NAME is empty."""

    monkeypatch.delenv(DEFAULT_API_KEY_ENV, raising=False)
    transport = WebSocketTransport(model="gpt-realtime-2.1-mini")
    with pytest.raises(RealtimeAuthError) as caught:
        transport.open()
    assert DEFAULT_API_KEY_ENV in str(caught.value)
    assert "outside the repo" in str(caught.value)


def test_a_plaintext_url_will_not_carry_the_credential_without_an_opt_in(key_env) -> None:
    """A key on a ws:// socket is a key on the wire. Loopback tests opt in."""

    transport = WebSocketTransport(url="ws://127.0.0.1:1/realtime", api_key_env=key_env)
    with pytest.raises(RealtimeAuthError) as caught:
        transport.open()
    assert "not TLS" in str(caught.value)


def test_the_credential_really_does_travel_as_a_bearer_header(
    key_env, loopback, transports
) -> None:
    """Credential-by-reference still has to authenticate: the header is sent."""

    def handler(connection: ServerConnection) -> None:
        connection.recv()

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)
    transport.send({"type": "response.cancel"})
    _until(lambda: "Authorization" in server.headers, what="the server read the handshake headers")
    assert server.headers["Authorization"] == f"Bearer {FAKE_KEY}"


def test_the_key_never_appears_in_anything_the_transport_produces(
    key_env, loopback, transports, caplog: pytest.LogCaptureFixture
) -> None:
    """The load-bearing credential test: exceptions, repr, diagnostics, logs.

    Both hostile shapes are exercised — a rejecting server whose HTTP body
    echoes the Authorization header back, and an accepted session whose ``error``
    frame embeds the key in its message, which the transport then quotes when it
    raises ``RealtimeQuotaError``. If redaction were decorative, the second one
    would leak.
    """

    caplog.set_level(logging.DEBUG, logger="parcel_robot.realtime.ws_transport")
    produced: list[str] = []

    def reject(connection: ServerConnection, request) -> Any:
        del request
        header = connection.request.headers.get("Authorization", "")
        return connection.respond(HTTPStatus.UNAUTHORIZED, f"rejected {header}\n")

    def never(connection: ServerConnection) -> None:  # pragma: no cover - never reached
        connection.recv()

    rejecting = loopback(never, process_request=reject)
    denied = WebSocketTransport(url=rejecting.url, allow_insecure=True, api_key_env=key_env)
    with pytest.raises(RealtimeAuthError) as auth_error:
        denied.open()
    produced += [str(auth_error.value), repr(auth_error.value), repr(denied)]
    produced.append(json.dumps(denied.diagnostics()))

    def leaky(connection: ServerConnection) -> None:
        _emit(
            connection,
            {
                "type": "error",
                "error": {
                    "code": "insufficient_quota",
                    "message": f"no quota for key {FAKE_KEY} (Bearer {FAKE_KEY})",
                },
            },
        )
        connection.close(CLOSE_TRY_AGAIN_LATER, "insufficient_quota")

    server = loopback(leaky)
    transport = transports(server, api_key_env=key_env)
    _settle(transport, frames=1, down=True)
    transport.receive()  # the provider's own frame is the peer's content, not ours
    with pytest.raises(RealtimeQuotaError) as quota_error:
        transport.receive()
    produced += [
        str(quota_error.value),
        repr(quota_error.value),
        repr(transport),
        str(transport.down_reason),
        json.dumps(transport.diagnostics()),
    ]
    produced += [record.getMessage() for record in caplog.records]

    leaked = [text for text in produced if FAKE_KEY in text]
    assert leaked == [], f"{len(leaked)} string(s) produced by the transport carried the key"
    assert REDACTED in str(quota_error.value)
    # And the redaction did not eat the diagnosis it was protecting.
    assert "no quota for key" in str(quota_error.value)


def test_the_instance_does_not_hold_the_key_at_all(key_env, loopback, transports) -> None:
    """Read at connect time, never stored: there is nothing on self to leak."""

    def handler(connection: ServerConnection) -> None:
        connection.recv()

    server = loopback(handler)
    transport = transports(server, api_key_env=key_env)
    holders = [name for name, value in vars(transport).items() if FAKE_KEY in repr(value)]
    assert holders == []
    assert transport.diagnostics()["credential_env"] == key_env


def test_redact_scrubs_credential_shapes_it_was_never_told_about() -> None:
    """Pattern redaction is the backstop for text the module did not compose."""

    assert redact("Authorization: Bearer sk-abcd1234") == f"Authorization: {REDACTED}"
    assert redact("token sk-abcd1234 leaked") == f"token {REDACTED} leaked"
    assert redact("hunter2", secret="hunter2") == REDACTED
    assert redact("nothing to see here") == "nothing to see here"


# ------------------------------------------------------------ lane integration
class _CountingLedger:
    """Just enough ``ConversationMemory`` for the lane's system rows."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str]] = []

    def write_realtime_turn(
        self,
        *,
        session_id: str | None,
        speaker: str,
        text: str,
        origin: str,
        provider_item_id: str | None = None,
    ) -> int:
        del session_id, origin, provider_item_id
        self.rows.append((speaker, text))
        return len(self.rows)


def _lane(server: LoopbackServer, key_env: str, ledger: _CountingLedger) -> RealtimeLane:
    return RealtimeLane(
        config=RealtimeConfig(enabled=True, source="test"),
        instructions="be a good dog",
        transport_factory=websocket_transport_factory(
            url=server.url,
            api_key_env=key_env,
            allow_insecure=True,
        ),
        ledger=ledger,
    )


def test_the_unmodified_lane_reconnects_over_a_real_socket_hang_up(key_env, loopback) -> None:
    """R1's lane drives R1.5's transport with zero edits to ``lane.py``."""

    connections: list[int] = []

    def handler(connection: ServerConnection) -> None:
        connections.append(1)
        connection.recv()  # session.update
        connection.close(1000, "bye")

    server = loopback(handler)
    ledger = _CountingLedger()
    lane = _lane(server, key_env, ledger)
    try:
        lane.open_session(handshake_token="tok", mic_gesture=True)
        transport = lane.transport
        assert isinstance(transport, WebSocketTransport)
        _settle(transport, down=True)
        lane.pump()
        assert lane.disconnects == 1
        assert lane.reconnects == 1
        _until(lambda: len(connections) == 2, what="the lane opened a second socket")
        assert any("reconnected" in text for _, text in ledger.rows)
    finally:
        lane.close()


def test_a_quota_refusal_reaches_the_caller_instead_of_starting_a_retry_storm(
    key_env, loopback
) -> None:
    """The typed error is not a ``TransportClosed``, so the lane cannot reconnect it."""

    connections: list[int] = []

    def handler(connection: ServerConnection) -> None:
        connections.append(1)
        connection.recv()  # session.update
        _emit(connection, QUOTA_FRAME)
        connection.close(CLOSE_TRY_AGAIN_LATER, "insufficient_quota")

    server = loopback(handler)
    ledger = _CountingLedger()
    lane = _lane(server, key_env, ledger)
    try:
        lane.open_session(handshake_token="tok", mic_gesture=True)
        transport = lane.transport
        assert isinstance(transport, WebSocketTransport)
        _settle(transport, frames=1, down=True)
        with pytest.raises(RealtimeQuotaError):
            lane.pump()
        # The error frame was still dispatched before the raise.
        assert [event.code for event in lane.server_errors] == ["insufficient_quota"]
        assert lane.reconnects == 0
        assert len(connections) == 1
    finally:
        lane.close()


def test_a_transport_with_neither_url_nor_model_refuses_to_be_built() -> None:
    """Configuration errors are typed too, and never reach a socket."""

    with pytest.raises(RealtimeTransportError):
        WebSocketTransport()
    with pytest.raises(RealtimeTransportError):
        WebSocketTransport(model="m", max_inbound=0)
