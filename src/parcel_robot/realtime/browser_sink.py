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

    # ---- CARD DUPLEX-1 (task_26) — the two seams a turn controller needs ----
    # Correction pass: ``duck`` and ``accepts_interrupt_onset`` are deliberately
    # NOT members of this Protocol. Every member of a Protocol is mandatory for
    # structural typing, so declaring one and calling it optional in a comment
    # was a contradiction — a gateway that predates DUPLEX-1, or a test double
    # standing in for one, would stop satisfying the contract. :class:`BrowserSink`
    # feature-detects both (``getattr(..., "duck", None)`` /
    # ``accepts_interrupt_onset``) and counts the gateways that lack them.
    # ---- END CARD DUPLEX-1 ----


class BrowserSink:
    """The lane's ``SinkLike``, wired to a browser instead of a speaker."""

    def __init__(self, gateway: PlaybackGateway) -> None:
        self._gateway = gateway
        self.chunks_sent = 0
        self.bytes_sent = 0
        self.interrupts = 0
        self.utterances = 0
        # ---- CARD DUPLEX-1 (task_26) — provisional ducking, counted ----
        self.ducks = 0
        self.ducks_unsupported = 0
        self.last_duck_gain: float | None = None
        # ---- END CARD DUPLEX-1 ----

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

    # ---- CARD DUPLEX-1 (task_26) — the interrupt says WHEN the owner started
    # MARK-1 handoff H-7, and AIR-1's second missing half. ``interrupted_at`` in
    # the capture index is the moment ``interrupt()`` RAN. With MARK-1's floor
    # at 0 those are the same instant, so the field was the onset by accident.
    # The moment a floor > 0 ships they are a whole floor apart, and AIR-1's
    # latency row — owner's voice hits the array → this WAV stops — needs the
    # onset, not the commit.
    #
    # It travels as ``onset_ago_s``, a DURATION, and not as a timestamp. The
    # lane runs on ``time.monotonic``; the capture index is stamped from the
    # wall clock the tee's relay thread reads. Handing over "how long before
    # now" is the one shape that cannot be read on the wrong clock, and it
    # survives a test that drives both from a fake clock starting at 1000.0.
    #: Advertised so :meth:`RealtimeLane._commit_barge_in` can pass the onset to
    #: sinks that understand it and call the old one-argument ``interrupt()``
    #: everywhere else (``DiscardSink``, ``voice_audio.SpeakerSink``). A
    #: ``TypeError`` swallowed around a barge-in would be the same bug with a
    #: longer stack trace.
    accepts_interrupt_onset = True

    #: Correction pass, finding 3. ``duck`` on THIS sink takes a LINEAR GAIN in
    #: [MIN_DUCK_GAIN, 1]. ``voice_audio.SpeakerSink.duck`` takes an
    #: ATTENUATION IN DECIBELS and its unity call is ``restore()``, so a lane
    #: that feature-detected the method name would have handed 0.18 to a dB
    #: scale and produced an inaudible 0.18 dB duck instead of a real one. This
    #: flag names the scale; the lane gates on it and on nothing else.
    accepts_gain_duck = True

    def interrupt(self, *, onset_ago_s: float | None = None) -> None:
        self.interrupts += 1
        gateway = self._gateway
        if onset_ago_s is None or not getattr(gateway, "accepts_interrupt_onset", False):
            gateway.interrupt()
            return
        gateway.interrupt(onset_ago_s=float(onset_ago_s))  # type: ignore[call-arg]

    def duck(self, gain: float) -> None:
        """Attenuate playback WITHOUT stopping it. Card DUPLEX-1.

        A provisional barge-in is not an interruption: nothing is told to the
        provider, nothing is truncated, and the schedule in the browser is left
        exactly where it is. All that changes is a gain, so a "mm-hmm" that
        resolves inside the floor costs the owner a moment of quieter dog and
        no lost words at all. A gateway that does not know the word is a
        counted no-op here rather than an exception on the pump thread.
        """

        level = max(0.0, min(1.0, float(gain)))
        hook = getattr(self._gateway, "duck", None)
        if hook is None:
            self.ducks_unsupported += 1
            return
        hook(level)
        self.ducks += 1
        self.last_duck_gain = level

    # ---- END CARD DUPLEX-1 ----

    def snapshot(self) -> dict[str, object]:
        return {
            "kind": "browser",
            "utterances": self.utterances,
            "chunks_sent": self.chunks_sent,
            "bytes_sent": self.bytes_sent,
            "interrupts": self.interrupts,
            # ---- CARD DUPLEX-1 (task_26) ----
            "ducks": self.ducks,
            "ducks_unsupported": self.ducks_unsupported,
            "last_duck_gain": self.last_duck_gain,
            # ---- END CARD DUPLEX-1 ----
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
