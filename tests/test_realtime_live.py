"""Card R1.5: the ONE test that talks to the real provider. Never in the gate.

DOUBLE-GATED, ON PURPOSE
------------------------
``pytest.mark.slow`` keeps it out of the commit tier (which runs
``-m "not slow"``), and two ``skipif``s keep it out of the nightly slow tier
unless an operator has *both* opted in with ``PARCEL_REALTIME_LIVE=1`` and put a
credential in the environment. CI therefore never needs a key, and a machine
without one never goes red.

WHAT IT ASSERTS
---------------
The whole product path, unfaked: R1's ``RealtimeLane`` over R1.5's
``WebSocketTransport`` against ``gpt-realtime-2.1-mini``, one user item up, one
reply down, and the conversation ledger holding both sides afterwards.

STATUS AS OF 2026-08-17: THIS HAS NEVER PASSED
----------------------------------------------
The account has no billing quota. The socket opens and authenticates, the
provider immediately sends ``error{code: insufficient_quota}`` and closes 1013,
and the transport turns that into ``RealtimeQuotaError``. The test catches that
one case and fails with an actionable message rather than an opaque traceback,
because "add credit" is an owner action and should read like one. Every other
failure is left to raise on its own terms.

The credential is read BY NAME from the environment. It is never written into
this repository, never printed, and never asserted against.
"""

from __future__ import annotations

import os
import time

import pytest

from parcel_robot.memory import ConversationMemory
from parcel_robot.realtime.config import RealtimeConfig
from parcel_robot.realtime.lane import SPEAKER_OWNER, SPEAKER_ROBOT, RealtimeLane
from parcel_robot.realtime.protocol import ConversationItemCreate, ResponseCreate

#: The operator's explicit opt-in. Nothing else turns this file on.
LIVE_ENV = "PARCEL_REALTIME_LIVE"

#: Which environment variable holds the key — a NAME, resolved at import.
KEY_ENV = os.environ.get("PARCEL_REALTIME_KEY_ENV", "").strip() or "OPENAI_API_KEY"

#: Cheapest realtime model, verified present in ``GET /v1/models`` on 2026-08-17.
LIVE_MODEL = os.environ.get("PARCEL_REALTIME_MODEL", "").strip() or "gpt-realtime-2.1-mini"

#: Wall-clock ceiling for one hosted turn. Generous: this is a real network.
TURN_TIMEOUT_S = 45.0

LIVE = os.environ.get(LIVE_ENV, "").strip() == "1"
HAVE_KEY = bool(os.environ.get(KEY_ENV, "").strip())

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not LIVE, reason=f"live realtime lane is opt-in: set {LIVE_ENV}=1"),
    pytest.mark.skipif(not HAVE_KEY, reason=f"no credential in ${KEY_ENV}"),
]

PROMPT = "Say the single word: acknowledged."


class _NullSink:
    """A speaker that discards audio. The card's subject is the wire, not PortAudio."""

    def __init__(self) -> None:
        self.chunks: list[bytes] = []
        self.first_chunk_started_monotonic: float | None = None

    def begin_utterance(self) -> None:
        self.first_chunk_started_monotonic = None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token
        self.chunks.append(chunk)
        if self.first_chunk_started_monotonic is None:
            self.first_chunk_started_monotonic = time.monotonic()

    def interrupt(self) -> None:
        return


def test_one_live_turn_reaches_the_provider_and_lands_in_the_ledger(tmp_path) -> None:
    """Open, ask, hear back, and prove both sides are in the conversation ledger."""

    from parcel_robot.realtime.ws_transport import (
        RealtimeQuotaError,
        websocket_transport_factory,
    )

    ledger = ConversationMemory(tmp_path / "live_realtime.sqlite3")
    lane = RealtimeLane(
        config=RealtimeConfig(enabled=True, model=LIVE_MODEL, source="live-test"),
        instructions="Answer in one short word. You are a robot dog.",
        transport_factory=websocket_transport_factory(model=LIVE_MODEL, api_key_env=KEY_ENV),
        ledger=ledger,
        sink=_NullSink(),
    )

    try:
        session_id = lane.open_session(handshake_token="live-test", mic_gesture=True)
        # The runtime owns the owner side of the ledger (R1_STATUS: "who writes
        # the owner row"); with no ingress wired, this test plays that part.
        ledger.write_realtime_turn(
            session_id=session_id,
            speaker=SPEAKER_OWNER,
            text=PROMPT,
            origin="realtime",
            provider_item_id=None,
        )
        transport = lane.transport
        assert transport is not None
        transport.send(ConversationItemCreate(role="user", text=PROMPT))
        transport.send(ResponseCreate())

        deadline = time.monotonic() + TURN_TIMEOUT_S
        while time.monotonic() < deadline and not lane.usage_rows:
            lane.pump()
            time.sleep(0.05)
    except RealtimeQuotaError as error:
        pytest.fail(
            "The live Realtime session was refused for QUOTA, not for a code fault.\n"
            f"  provider: {error}\n"
            f"  model:    {LIVE_MODEL}\n"
            f"  credential: ${KEY_ENV} (present, accepted at the handshake)\n"
            "This is an owner billing action: add credit to the account. As of "
            "2026-08-17 this test has never passed, and R1_5_STATUS.md says so."
        )
    finally:
        lane.close()

    assert lane.usage_rows, f"no response.done arrived within {TURN_TIMEOUT_S:.0f}s"
    assert lane.protocol_errors == [], f"the codec refused live frames: {lane.protocol_errors}"

    speakers = {str(row["speaker"]) for row in ledger.realtime_turns(session_id=session_id)}
    assert SPEAKER_OWNER in speakers
    assert SPEAKER_ROBOT in speakers, "the provider replied but the lane ledgered no robot row"
