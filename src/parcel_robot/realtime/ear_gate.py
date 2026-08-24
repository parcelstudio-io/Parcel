"""The gate in front of the wire — card A7 (``scrum/20260824/task_2``).

THE DEFECT THIS CLOSES
----------------------
``realtime/audio_gateway.py``'s ``accept_audio`` says it in its own comment: the
speaker-identity hook "never decides whether the frame goes up: it cannot".
Every microphone frame the browser sends is relayed into ``lane.send_audio``
before anything local has an opinion about whose voice it is. Codex's freeze
review named that finding 3 — *post-upload identity is too late for cost and for
privacy* — and H1 measured what it costs: a plain VAD in a room with a
television opens **960.6 sessions/hour** (H1 C5), 809.4/hour through air on a
real room floor (VOICE-GATE F4), which is the difference between $30.72/month
and $572.36/month (EVENT-BUDGET). Admission dominates cost. This module is the
admission.

THE CHAIN, AND WHY IT IS PUSH-TO-TALK FOR M1
--------------------------------------------
``research/20260824/voice-gate/VERDICT.md`` decided it: **push-to-talk ships for
M1** — owner recall 1.000, zero non-owner hosted bytes, zero false openings/day,
$0.15/day, 0 % replay. So the chain is::

    PTT press -> hosted-call governor -> local identity/engagement -> pre-roll -> upload

and ambient admission is OFF (``ambient: false``), because no ambient arm on
this host has evidence behind it and shipping a flag-off ambient gate with no
result behind it would be debt. The governor is first because it guards
*whatever* opens a session, and a session that may not be paid for should not
cost a verification either.

THE OPERATING POINT, AND WHY IT IS NOT 0.55
-------------------------------------------
VOICE-GATE's F1: ``voice_identity.DEFAULT_THRESHOLD`` is 0.55, and through this
room the owner scores p50 **0.47** — admitted **16.7 %** of the time. The model
is fine: **EER 0.000** at >= 2 s of speech, and **0.352** buys 0.95 owner recall
at **0.000** impostor acceptance (n = 36 owner, 31 impostor, channel-matched
gallery). So :data:`MEASURED_IDENTITY_THRESHOLD` is 0.352 and
:data:`MEASURED_MIN_SPEECH_S` is 2.0 s, both configurable, both carrying the run
they came from.

``realtime.voice_identity.threshold`` (0.55) is deliberately NOT changed. It is
a different question with a different asymmetry: that gate decides whether a
voice may MOVE THE ROBOT, and a wrong yes there is a stranger driving; this gate
decides whether bytes may LEAVE THE HOUSE, and a wrong no there is an unheard
sentence. The stricter number belongs on the safety side. Recalibrating the
arming gate needs the owner's real voice enrolled through the deployment
channel, which does not exist on this host (VOICE-GATE caveat 2) — it is
box-day work and is recorded as such.

CHANNEL-MATCHED ENROLLMENT IS A PRECONDITION, NOT ADVICE
--------------------------------------------------------
"a gallery enrolled through the same microphone and room is measurably better
than a clean one" (F1). ``enrollment_channel`` is how an operator states which
channel the profile was enrolled through; when it is set and the profile's own
``source`` does not name it, this gate does NOT verify — it falls back to
push-to-talk admission and says so once, rather than scoring a room against a
studio gallery and calling the result identity.

REPLAY IS AN ACCEPTED INDOOR RISK, IN WRITING
---------------------------------------------
At the usable threshold, **52.8 %** of simulated loudspeaker replays of the
owner are accepted (VOICE-GATE F2), and addendum A9 is explicit that no arm may
claim replay immunity — a recording contains the wake phrase too. Push-to-talk
refuses replay only under the assumption that the spoofer does not also hold the
owner's button. M1 accepts that risk indoors; a liveness mechanism is post-M1.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from parcel_robot.realtime.hosted_budget import (
    CLASS_ROUTINE,
    GovernorConfig,
    HostedCallGovernor,
    HostedCallRefused,
)
from parcel_robot.voice.engagement import (
    EXCHANGE_WINDOW_S,
    TIER_ANSWER,
    EngagementVerdict,
    triage_in_exchange,
)

#: PCM16 mono, the shape both gateways hand over.
PCM_SAMPLE_WIDTH_BYTES = 2
DEFAULT_SAMPLE_RATE_HZ = 24_000

#: VOICE-GATE F1: 0.95 owner recall at 0.000 impostor acceptance, channel-matched
#: gallery, >= 2 s of speech. NOT the arming gate's 0.55 — see the docstring.
MEASURED_IDENTITY_THRESHOLD = 0.352

#: VOICE-GATE F1: EER is 0.000 at >= 2 s and not below it. Less audio than this
#: is not a cheaper verdict, it is a different and worse one.
MEASURED_MIN_SPEECH_S = 2.0

#: H1 C3: truncation is 0 % at >= 500 ms of pre-roll and non-zero below it.
MEASURED_PRE_ROLL_MS = 500.0

#: Bound on one un-admitted turn's buffer. A gate that never decides must not
#: also never stop allocating; past this the turn is refused and erased.
DEFAULT_MAX_TURN_S = 20.0

EAR_CONFIG_KEYS = frozenset(
    {
        "ambient",
        "identity_threshold",
        "min_speech_s",
        "pre_roll_ms",
        "max_turn_s",
        "enrollment_channel",
        "exchange_window_s",
        "governor",
    }
)

#: Admission codes. Exactly two of them put bytes on the wire.
CODE_ADMITTED_IDENTITY = "admitted_owner_voice"
CODE_ADMITTED_PTT = "admitted_push_to_talk"
CODE_PENDING = "pending"
CODE_NOT_OWNER = "not_owner"
CODE_NO_PRESS = "no_push_to_talk"
CODE_BUDGET_REFUSED = "hosted_budget_refused"
CODE_TURN_TOO_LONG = "turn_exceeded_max"

ADMITTING_CODES: frozenset[str] = frozenset({CODE_ADMITTED_IDENTITY, CODE_ADMITTED_PTT})


@dataclass(frozen=True)
class EarGateConfig:
    """How the dog listens, and what listening is allowed to cost."""

    #: M1 = push-to-talk. True would let a local VAD open turns, and no ambient
    #: arm on this host has evidence behind it (VOICE-GATE, caveat 6).
    ambient: bool = False
    identity_threshold: float = MEASURED_IDENTITY_THRESHOLD
    min_speech_s: float = MEASURED_MIN_SPEECH_S
    pre_roll_ms: float = MEASURED_PRE_ROLL_MS
    max_turn_s: float = DEFAULT_MAX_TURN_S
    #: Free text naming the channel the owner's profile was enrolled through.
    #: Empty = unstated, and then the gate does not claim a channel match.
    enrollment_channel: str = ""
    exchange_window_s: float = EXCHANGE_WINDOW_S
    governor: GovernorConfig = field(default_factory=GovernorConfig)

    @property
    def pre_roll_s(self) -> float:
        return self.pre_roll_ms / 1000.0

    @classmethod
    def from_mapping(cls, section: object) -> EarGateConfig:
        """Validate the ``audio.ear:`` block. Unknown key ⇒ refusal by name.

        The read-site guard, for ``resolve_audio_gateway_selection``'s reason
        exactly: ``config.OVERLAY_INTRODUCIBLE_KEYS`` exempts the whole ``audio``
        subtree and cannot be narrower, so the spelling check has to live where
        the section is read. ``config.py`` sits ON the DEC-0 1,000-line ceiling
        and may not grow, which is the second reason this block is nested under
        an already-exempt parent rather than given a top-level key of its own.
        """

        if section is None:
            return cls()
        if not isinstance(section, Mapping):
            raise TypeError(
                f"the audio.ear config section must be a mapping, got {type(section).__name__}"
            )
        unknown = sorted(str(key) for key in section if str(key) not in EAR_CONFIG_KEYS)
        if unknown:
            raise ValueError(
                f"unknown audio.ear config key(s): {', '.join(unknown)}; "
                f"allowed: {', '.join(sorted(EAR_CONFIG_KEYS))}"
            )
        ambient = section.get("ambient", False)
        if not isinstance(ambient, bool):
            raise TypeError(f"audio.ear.ambient must be true or false, got {ambient!r}")
        channel = section.get("enrollment_channel", "")
        if not isinstance(channel, str):
            raise TypeError(
                f"audio.ear.enrollment_channel must be text, got {type(channel).__name__}"
            )
        return cls(
            ambient=ambient,
            identity_threshold=_number(section, "identity_threshold", MEASURED_IDENTITY_THRESHOLD),
            min_speech_s=_number(section, "min_speech_s", MEASURED_MIN_SPEECH_S),
            pre_roll_ms=_number(section, "pre_roll_ms", MEASURED_PRE_ROLL_MS),
            max_turn_s=_number(section, "max_turn_s", DEFAULT_MAX_TURN_S),
            enrollment_channel=channel.strip(),
            exchange_window_s=_number(section, "exchange_window_s", EXCHANGE_WINDOW_S),
            governor=GovernorConfig.from_mapping(section.get("governor")),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "ambient": self.ambient,
            "identity_threshold": self.identity_threshold,
            "min_speech_s": self.min_speech_s,
            "pre_roll_ms": self.pre_roll_ms,
            "max_turn_s": self.max_turn_s,
            "enrollment_channel": self.enrollment_channel,
            "exchange_window_s": self.exchange_window_s,
            "governor": self.governor.as_dict(),
        }


@dataclass(frozen=True)
class EarAdmission:
    """One turn's admission answer, with the audio it stands on."""

    admitted: bool
    code: str
    reason: str
    score: float | None = None
    threshold: float = MEASURED_IDENTITY_THRESHOLD
    speech_s: float = 0.0
    #: Seconds of audio flushed at the admitting instant — everything buffered
    #: BEFORE the decision, which is what the pre-roll bar is measured on.
    pre_roll_s: float = 0.0
    uploaded_bytes: int = 0
    erased_bytes: int = 0

    @property
    def budget_refused(self) -> bool:
        """Did the ENVELOPE say no, as opposed to "not yet"?

        The distinction is the whole reason this is a property and not a bare
        ``not admitted``: a press that has not been admitted yet is the normal
        state of every turn for its first second, and treating that as a refusal
        would refuse every turn ever spoken.
        """

        return not self.admitted and self.code == CODE_BUDGET_REFUSED

    def as_dict(self) -> dict[str, object]:
        return {
            "admitted": self.admitted,
            "code": self.code,
            "reason": self.reason,
            "budget_refused": self.budget_refused,
            "score": None if self.score is None else round(self.score, 6),
            "threshold": self.threshold,
            "speech_s": round(self.speech_s, 4),
            "pre_roll_s": round(self.pre_roll_s, 4),
            "uploaded_bytes": self.uploaded_bytes,
            "erased_bytes": self.erased_bytes,
        }


class EarGate:
    """The only route from a microphone frame to the wire.

    THE RELAY-PATH CONTRACT, inherited from the R17 tee and the F1-SI gate that
    already sit on this hop: :meth:`offer_frame` runs on the audio gateway's own
    socket-reader thread while :meth:`press` / :meth:`release` arrive from the
    panel thread, so the turn buffer is shared mutable state and is held under
    one lock. It is a LEAF lock — nothing is called while it is held except the
    caller-supplied ``verify``, which owns no lock of this package's — so it
    cannot enter r24's order graph. ``offer_frame`` also may not raise into its
    caller, ever.

    Owns no socket, no model and no clock it did not receive. ``verify`` is a
    callable that scores a PCM buffer against the enrolled owner and returns
    ``None`` when it cannot — a missing model, an unenrolled host, a gallery
    from the wrong channel. That is the state this repo is actually in today, so
    it is the state with the loudest behaviour: admit on the owner's own button
    press, and say in the code which of the two admissions happened.
    """

    def __init__(
        self,
        *,
        config: EarGateConfig | None = None,
        verify: Callable[[bytes], float | None] | None = None,
        governor: HostedCallGovernor | None = None,
        on_event: Callable[[str], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    ) -> None:
        self.config = config or EarGateConfig()
        self._verify = verify
        self.governor = governor
        self._on_event = on_event
        self._monotonic = monotonic
        self.bytes_per_second = float(max(1, int(sample_rate_hz)) * PCM_SAMPLE_WIDTH_BYTES)

        #: Guards every field below that a frame and a button press both touch.
        #: See the class docstring: leaf lock, no nested acquisition.
        self._lock = threading.RLock()
        self._pre_roll: deque[bytes] = deque()
        self._pre_roll_bytes = 0
        self._turn: list[bytes] = []
        self._turn_bytes = 0
        self._pressed = False
        self._decided = False
        self._admission = EarAdmission(
            admitted=False,
            code=CODE_NO_PRESS,
            reason="no turn has been admitted yet",
            threshold=self.config.identity_threshold,
        )
        self._addressed_at: float | None = None
        #: Messages already announced. A SET and not a flag: a refusal that is
        #: never announced is the silent grounding this gate exists to prevent,
        #: and one shared flag would let the first warning of a process silence
        #: every later one. Same shape as ``SpendLedger``'s own announce cache.
        self._announced: set[str] = set()

        # ------------------------------------------------------------ counters
        self.frames_seen = 0
        self.bytes_seen = 0
        self.bytes_uploaded = 0
        self.bytes_erased = 0
        self.turns_admitted = 0
        self.turns_refused = 0
        self.verify_failures = 0
        #: Warnings whose sink threw. Counted, never swallowed silently.
        self.notes_dropped = 0
        self.tiers: dict[str, int] = {}

    # ------------------------------------------------------------- the button
    @property
    def admission(self) -> EarAdmission:
        return self._admission

    @property
    def identity_available(self) -> bool:
        """Can this gate score a voice at all right now?"""

        return self._verify is not None

    def press(self) -> EarAdmission:
        """The owner's push-to-talk gesture. Asks the governor; never uploads.

        A press is also the engagement signal: it is the owner addressing the
        dog, so it opens the exchange window that :meth:`note_owner_turn` reads.
        """

        governor = self.governor
        refusal: HostedCallRefused | None = None
        if governor is not None:
            # Deliberately OUTSIDE the lock: the governor reads a file, and a
            # disk that is slow may not also stall the frame relay.
            try:
                governor.require("the owner's hosted conversation", call_class=CLASS_ROUTINE)
            except HostedCallRefused as error:
                refusal = error
        with self._lock:
            if refusal is not None:
                self._pressed = False
                self._decided = True
                self.turns_refused += 1
                self._admission = EarAdmission(
                    admitted=False,
                    code=CODE_BUDGET_REFUSED,
                    reason=refusal.reason,
                    threshold=self.config.identity_threshold,
                )
                return self._admission
            self._pressed = True
            self._decided = False
            self._turn = []
            self._turn_bytes = 0
            self._addressed_at = self._monotonic()
            self._admission = EarAdmission(
                admitted=False,
                code=CODE_PENDING,
                reason="the button is down; nothing has been uploaded yet",
                threshold=self.config.identity_threshold,
            )
            return self._admission

    def release(self) -> None:
        """The button came up. The turn ends; the pre-roll ring stays warm."""

        with self._lock:
            self._erase_turn()
            self._pressed = False
            self._decided = False

    # -------------------------------------------------------------- the frames
    def offer_frame(self, pcm: bytes) -> bytes:
        """One microphone frame in; the bytes that may go UP, out.

        Returns ``b""`` for every frame that has not been admitted, which is
        every frame until a local decision says otherwise. Never raises: this
        runs on the gateway's socket-reader thread, which may not die of a
        verification.
        """

        frame = bytes(pcm or b"")
        if not frame:
            return b""
        with self._lock:
            return self._offer_locked(frame)

    def _offer_locked(self, frame: bytes) -> bytes:
        self.frames_seen += 1
        self.bytes_seen += len(frame)
        if not self._pressed:
            if self.config.ambient:
                # There is no measured ambient arm. The knob exists so the
                # decision is visible; turning it on without one is refused.
                self._note_once(
                    "audio.ear.ambient is on, but no ambient admission arm has evidence "
                    "behind it (VOICE-GATE v2 decided push-to-talk for M1); frames are "
                    "still not uploaded without a press"
                )
            self._remember_pre_roll(frame)
            return b""
        if self._decided:
            if self._admission.admitted:
                return self._uploaded(frame)
            # A refused turn stays refused until the button is released. Frames
            # are counted and dropped; nothing is retained.
            self.bytes_erased += len(frame)
            return b""
        self._turn.append(frame)
        self._turn_bytes += len(frame)
        return self._decide()

    # ------------------------------------------------------------- the verdict
    def _decide(self) -> bytes:
        buffered_s = (self._pre_roll_bytes + self._turn_bytes) / self.bytes_per_second
        speech_s = self._turn_bytes / self.bytes_per_second
        if buffered_s > self.config.max_turn_s:
            return self._refuse(
                CODE_TURN_TOO_LONG,
                f"no admission after {buffered_s:.1f} s of audio; the turn is refused "
                "and its buffer erased",
                speech_s=speech_s,
            )
        # THE PRE-ROLL BAR, ENFORCED AS A PRECONDITION OF THE FIRST UPLOAD.
        # H1 C3 measured 0 % first-word truncation at >= 500 ms of pre-roll and
        # non-zero below it, so the first thing that ever goes up carries at
        # least that much audio from before the decision. Waiting is free here:
        # server VAD is still the endpointer on the far side.
        if buffered_s < self.config.pre_roll_s:
            return b""
        if self._verify is None:
            return self._admit(
                CODE_ADMITTED_PTT,
                (
                    "admitted on the owner's push-to-talk press; no channel-matched "
                    "owner voice profile is available to verify against"
                ),
                score=None,
                speech_s=speech_s,
            )
        if speech_s < self.config.min_speech_s:
            # VOICE-GATE F1: EER is 0.000 at >= 2 s. A verdict on less audio is
            # not an early verdict, it is a worse one, so the gate waits.
            return b""
        score = self._score(bytes(b"".join(self._turn)))
        if score is None:
            self.verify_failures += 1
            return self._admit(
                CODE_ADMITTED_PTT,
                (
                    "admitted on the owner's push-to-talk press; speaker verification "
                    "could not produce a score for this turn"
                ),
                score=None,
                speech_s=speech_s,
            )
        if score < self.config.identity_threshold:
            return self._refuse(
                CODE_NOT_OWNER,
                (
                    f"the speaker scored {score:.3f}, below the "
                    f"{self.config.identity_threshold:.3f} owner threshold; not one byte "
                    "of this turn left the host"
                ),
                score=score,
                speech_s=speech_s,
            )
        return self._admit(
            CODE_ADMITTED_IDENTITY,
            f"the enrolled owner, scoring {score:.3f} over {speech_s:.1f} s of speech",
            score=score,
            speech_s=speech_s,
        )

    def _score(self, payload: bytes) -> float | None:
        verify = self._verify
        if verify is None:  # pragma: no cover - guarded by the caller
            return None
        try:
            score = verify(payload)
        except Exception as error:  # noqa: BLE001 - a failed verify is not a crash
            self._note_once(f"speaker verification failed on this turn: {error}")
            return None
        if score is None:
            return None
        value = float(score)
        return None if math.isnan(value) else value

    def _admit(self, code: str, reason: str, *, score: float | None, speech_s: float) -> bytes:
        flush = b"".join(self._pre_roll) + b"".join(self._turn)
        pre_roll_s = len(flush) / self.bytes_per_second
        self._decided = True
        self.turns_admitted += 1
        self._admission = EarAdmission(
            admitted=True,
            code=code,
            reason=reason,
            score=score,
            threshold=self.config.identity_threshold,
            speech_s=speech_s,
            pre_roll_s=pre_roll_s,
            uploaded_bytes=len(flush),
        )
        self._pre_roll.clear()
        self._pre_roll_bytes = 0
        self._turn = []
        self._turn_bytes = 0
        self.bytes_uploaded += len(flush)
        return flush

    def _refuse(
        self, code: str, reason: str, *, speech_s: float, score: float | None = None
    ) -> bytes:
        erased = self._pre_roll_bytes + self._turn_bytes
        self._decided = True
        self.turns_refused += 1
        self._admission = EarAdmission(
            admitted=False,
            code=code,
            reason=reason,
            score=score,
            threshold=self.config.identity_threshold,
            speech_s=speech_s,
            erased_bytes=erased,
        )
        self._erase_turn()
        self._pre_roll.clear()
        self._pre_roll_bytes = 0
        self.bytes_erased += erased
        self._note_once(f"the ear refused a turn: {reason}")
        return b""

    def _uploaded(self, frame: bytes) -> bytes:
        self.bytes_uploaded += len(frame)
        return frame

    def _remember_pre_roll(self, frame: bytes) -> None:
        """Keep the last ``pre_roll_ms`` of audio, and not one frame more."""

        self._pre_roll.append(frame)
        self._pre_roll_bytes += len(frame)
        limit = int(self.config.pre_roll_s * self.bytes_per_second)
        while self._pre_roll and self._pre_roll_bytes - len(self._pre_roll[0]) >= limit:
            self._pre_roll_bytes -= len(self._pre_roll.popleft())

    def _erase_turn(self) -> None:
        self._turn = []
        self._turn_bytes = 0

    # ------------------------------------------------------- engagement triage
    def note_owner_turn(self, text: str, *, addressed: bool = False) -> EngagementVerdict:
        """Read one committed owner turn IN ITS EXCHANGE, not context-free.

        H1's measurement is the whole reason this method exists: ``triage``
        alone calls **84 of the 174** owner turns of ``realtime_convo_v1``
        ``hear_only``, because a mid-conversation reply ("yes that one", "the one
        by the petrol station") carries no second-person marker at all. A dog
        that ignores half of what its owner says is worse than one that answers
        the television. ``triage_in_exchange`` promotes those back inside an open
        exchange, and the exchange clock is this object's — the ear is what knows
        when it was last spoken to.

        ``addressed=True`` marks the turn as an unambiguous address (a closed
        intent, an emergency, a push-to-talk press) and opens the window without
        consulting the grammar.
        """

        now = self._monotonic()
        with self._lock:
            elapsed = None if self._addressed_at is None else max(0.0, now - self._addressed_at)
        verdict = triage_in_exchange(
            text,
            seconds_since_addressed=elapsed,
            window_s=self.config.exchange_window_s,
        )
        with self._lock:
            self.tiers[verdict.tier] = self.tiers.get(verdict.tier, 0) + 1
            if addressed or verdict.tier == TIER_ANSWER or verdict.addressed:
                self._addressed_at = now
        return verdict

    def note_addressed(self) -> None:
        """The dog was spoken to by some route other than a triaged turn."""

        with self._lock:
            self._addressed_at = self._monotonic()

    # ---------------------------------------------------------------- plumbing
    def _note_once(self, message: str) -> None:
        """Announce a message the first time it is seen, and never again.

        Deduplicated by TEXT, so a television talking to a refused gate for ten
        minutes does not become ten minutes of warnings, while a genuinely new
        refusal still gets through.
        """

        with self._lock:
            if self._on_event is None or message in self._announced:
                return
            self._announced.add(message)
        # The dedup set is updated under the lock; the sink itself is called
        # after it. A refusal announced from inside `_refuse` still holds the
        # outer (re-entrant) lock, so the sink must be cheap and may not raise —
        # it is `_emit`, a ring append, and a throw is counted rather than
        # propagated.
        try:
            self._on_event(message)
        except Exception:  # noqa: BLE001 - a warning may never break a turn
            self.notes_dropped += 1

    def snapshot(self) -> dict[str, object]:
        """What ``/api/state`` says about the ear.

        The governor's own snapshot is taken FIRST and outside the lock: it
        reads the ledger file, and a panel refresh may not hold the frame
        relay's lock across a disk read.
        """

        governed = None if self.governor is None else self.governor.snapshot()
        with self._lock:
            return self._snapshot_locked(governed)

    def _snapshot_locked(self, governed: dict[str, object] | None) -> dict[str, object]:
        return {
            "config": self.config.as_dict(),
            "identity_available": self.identity_available,
            "pressed": self._pressed,
            "frames_seen": self.frames_seen,
            "bytes_seen": self.bytes_seen,
            "bytes_uploaded": self.bytes_uploaded,
            "bytes_erased": self.bytes_erased,
            "turns_admitted": self.turns_admitted,
            "turns_refused": self.turns_refused,
            "verify_failures": self.verify_failures,
            "notes_dropped": self.notes_dropped,
            "tiers": dict(self.tiers),
            "admission": self._admission.as_dict(),
            "governor": governed,
        }


def enrollment_channel_matches(profile_source: object, wanted: str) -> bool:
    """Was this profile enrolled through the channel the ear is listening on?

    Unstated (``wanted`` empty) is not a match and not a failure: it is an
    operator who has not said, and the caller treats it as "do not claim a
    channel-matched verification". The comparison is a containment test on the
    profile's own free-text ``source`` because that is the only field the v1
    profile schema records about where its audio came from.
    """

    if not wanted:
        return False
    return wanted.strip().lower() in str(profile_source or "").strip().lower()


def _number(section: Mapping[str, object], key: str, default: float) -> float:
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"audio.ear.{key} must be a number, got {value!r}")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"audio.ear.{key} must be finite and non-negative, got {value!r}")
    return number


__all__ = [
    "ADMITTING_CODES",
    "CODE_ADMITTED_IDENTITY",
    "CODE_ADMITTED_PTT",
    "CODE_BUDGET_REFUSED",
    "CODE_NOT_OWNER",
    "CODE_NO_PRESS",
    "CODE_PENDING",
    "CODE_TURN_TOO_LONG",
    "EAR_CONFIG_KEYS",
    "MEASURED_IDENTITY_THRESHOLD",
    "MEASURED_MIN_SPEECH_S",
    "MEASURED_PRE_ROLL_MS",
    "EarAdmission",
    "EarGate",
    "EarGateConfig",
    "enrollment_channel_matches",
]
