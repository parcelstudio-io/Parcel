"""Two sinks that are not a speaker (cards R1.6 §A and §C, task_6).

WHY EITHER OF THESE EXISTS
--------------------------
``RealtimeLane`` writes hosted audio into an object with three methods —
``begin_utterance`` / ``enqueue`` / ``interrupt`` — plus a played-clock anchor
(``first_chunk_started_monotonic``). R1 pointed that at ``SpeakerSink``.
PortAudio does not load on this host, so ``SpeakerSink`` cannot play and there
is no microphone either. Both sinks here satisfy the same contract without
PortAudio:

* :class:`BrowserSink` forwards every WAV chunk to the browser panel through
  the loopback audio gateway, and reads its played-clock back from the marks
  the browser acks. That makes the browser both mouth and (through the
  gateway's inbound half) ear.
* :class:`DiscardSink` drops the bytes and counts them. That is ``mode: text``,
  where the transcript IS the product: the model still speaks, we simply never
  play it, and the discarded-byte counter keeps that honest in the snapshot
  rather than pretending audio was heard.

THE PLAYED CLOCK IS THE WHOLE POINT
-----------------------------------
The lane truncates the provider's belief about its own reply to what the owner
ACTUALLY heard (``conversation.item.truncate`` at ``played_ms``). With a local
speaker that number comes from the worker thread's first-sample stamp. With a
browser it can only come from the browser, over a socket, which means it is
attacker-shaped input: a stale or inflated ack must never be able to move the
truncate point past what was really transmitted. The clamping lives in the
gateway (it owns bytes-sent); this module only reads the clamped result, so
there is exactly one place that decides what "played" means.
"""

from __future__ import annotations

from typing import Protocol


class PlaybackGateway(Protocol):
    """The half of the audio gateway a sink is allowed to touch."""

    def begin_utterance(self) -> None: ...

    def send_audio(self, chunk: bytes) -> None: ...

    def interrupt(self) -> None: ...

    @property
    def played_started_monotonic(self) -> float | None: ...


class BrowserSink:
    """The lane's ``SinkLike``, wired to a browser instead of a speaker."""

    def __init__(self, gateway: PlaybackGateway) -> None:
        self._gateway = gateway
        self.chunks_sent = 0
        self.bytes_sent = 0
        self.interrupts = 0
        self.utterances = 0

    # ------------------------------------------------------- the lane's view
    @property
    def first_chunk_started_monotonic(self) -> float | None:
        """When the BROWSER said playback of this utterance began.

        ``None`` until the browser acks its first mark, which is the honest
        answer: nothing has been heard yet, so ``played_ms`` is zero and a
        barge-in truncates at zero rather than at "however much we sent".
        """

        return self._gateway.played_started_monotonic

    def begin_utterance(self) -> None:
        self.utterances += 1
        self._gateway.begin_utterance()

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token  # beat tokens are a local-playback concept; the browser has none
        payload = bytes(chunk)
        if not payload:
            return
        self.chunks_sent += 1
        self.bytes_sent += len(payload)
        self._gateway.send_audio(payload)

    def interrupt(self) -> None:
        self.interrupts += 1
        self._gateway.interrupt()

    def snapshot(self) -> dict[str, object]:
        return {
            "kind": "browser",
            "utterances": self.utterances,
            "chunks_sent": self.chunks_sent,
            "bytes_sent": self.bytes_sent,
            "interrupts": self.interrupts,
        }


class DiscardSink:
    """``mode: text``: the model speaks, nothing plays, and the count says so.

    Not a silent no-op. A sink that quietly swallowed audio would make "no
    speaker on this host" indistinguishable from "the provider sent no audio",
    and those are very different bugs. Every byte is counted and the counter is
    in the snapshot.
    """

    def __init__(self) -> None:
        self.first_chunk_started_monotonic: float | None = None
        self.chunks_discarded = 0
        self.bytes_discarded = 0
        self.utterances = 0
        self.interrupts = 0

    def begin_utterance(self) -> None:
        self.utterances += 1
        # Mirrors SpeakerSink: a new utterance clears the playback anchor.
        self.first_chunk_started_monotonic = None

    def enqueue(self, chunk: bytes, token: object = None) -> None:
        del token
        payload = bytes(chunk)
        self.chunks_discarded += 1
        self.bytes_discarded += len(payload)

    def interrupt(self) -> None:
        self.interrupts += 1

    def snapshot(self) -> dict[str, object]:
        return {
            "kind": "discard",
            "utterances": self.utterances,
            "chunks_discarded": self.chunks_discarded,
            "bytes_discarded": self.bytes_discarded,
            "interrupts": self.interrupts,
        }


__all__ = ["BrowserSink", "DiscardSink", "PlaybackGateway"]
