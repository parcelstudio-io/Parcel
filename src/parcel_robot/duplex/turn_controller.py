"""Who has the floor, and what to do about it (card DUPLEX-1, task_26).

WHY THIS EXISTS
---------------
Until this card the hosted lane had exactly one rule for an interruption: any
``speech_started`` while the robot is talking cancels the reply on the frame
(``lane._on_speech_started`` at floor 0 — R16's behaviour). That is not how
people talk. "mm-hmm" and "yeah" are how a listener says *keep going*, and a
companion that stops mid-sentence every time you agree with it is not fluid,
it is skittish. MARK-1 built the one knob that can soften it — a
``backchannel_floor_ms`` deadline — and measured that a deadline alone gets
**0.38** survival over its matrix, because a time-only floor cannot beat the
VAD tail. The floor is a threshold. What was missing is a state machine.

This module is that state machine, and nothing else. It is pure: no sockets, no
audio, no clock of its own beyond the ``at_s`` its callers pass in. It answers
three questions and holds no other authority:

1. **who has the floor right now** — LISTEN / THINK / SPEAK / OVERLAP / YIELD;
2. **what should happen to the robot's voice** — DUCK it (provisionally, while
   we find out whether this was a backchannel), RESUME it (it was), or COMMIT
   the barge-in (it was not);
3. **may the robot start talking on its own** — ``initiative_allowed``, which
   is false in every state but idle LISTEN, so a proactive remark can never
   collide with a turn that is already in progress.

THE TRADE, NAMED
----------------
A held barge-in costs a real interruption the whole floor: the dog goes on
talking while the controller decides. That is why DUCK exists and why it is
the FIRST thing that happens, not the last — the reply drops to
``duck_gain`` within one control frame of the onset, so the floor is spent
with the robot quiet under the owner rather than shouting over them. The
number that describes the owner's experience of a 700 ms floor is therefore
the *time to quiet*, not the time to cancel, and DUPLEX-1 measures both.

WHAT IS NOT HERE, AND WHERE IT WOULD GO
---------------------------------------
The card's design wants the offset signal to come from a LOCAL endpointer on
ch1 (Silero, ``parcel_robot.endpointing``) rather than from the provider's
server VAD, because the local one sees the owner's last syllable and the
provider's trails it by the whole silence tail. **No such producer exists in
this tree**: ``TurnEndpointer`` is wired to the local voice pipeline, not to
the hosted lane's gateway. The seam is real and one call wide —
``RealtimeLane.note_owner_speech_stopped()`` — and this controller consumes
whichever of the two reaches it first. Until a local producer is built, every
offset here is server VAD's, tail included, and the floor has to cover it.
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass

#: The owner has the floor (or nobody does). The only state in which the robot
#: is allowed to start talking on its own.
STATE_LISTEN = "listen"
#: The owner's turn ended and a reply has been asked for but no audio is out
#: yet. Initiative is refused here too: the answer is already coming.
STATE_THINK = "think"
#: The robot's reply is playing and nobody is talking over it.
STATE_SPEAK = "speak"
#: Both at once. A provisional barge-in is open, the reply is ducked, and the
#: controller is deciding whether this was a backchannel or a turn.
STATE_OVERLAP = "overlap"
#: The controller decided it was a turn. The reply has been committed away and
#: the floor belongs to the owner until they stop.
STATE_YIELD = "yield"

STATES: tuple[str, ...] = (STATE_LISTEN, STATE_THINK, STATE_SPEAK, STATE_OVERLAP, STATE_YIELD)

#: Nothing to do.
ACTION_NONE = "none"
#: Attenuate playback to ``duck_gain``. Reversible; tells the provider nothing.
ACTION_DUCK = "duck"
#: Put playback back to unity. The overlap was a backchannel.
ACTION_RESUME = "resume"
#: Interrupt, cancel, truncate. The overlap was a turn.
ACTION_COMMIT = "commit"

#: THE FLOOR UNDER EVERY DUCK, and the reason it is a constant rather than a
#: comment. Correction pass, finding 1: "not zero on purpose" was stated in
#: three places and enforced in none — the panel's ``Number(body.gain)`` read
#: ``null`` / ``[]`` / ``""`` / ``false`` as ``+0`` and muted the reply, and the
#: gateway's own clamp bottomed out at 0.0. A duck to silence is
#: indistinguishable from a dropped connection, which is the one thing a
#: provisional barge-in must never sound like: the owner said "mm-hmm", the dog
#: went silent, and nothing on the wire says whether it is coming back.
#:
#: So this is the quietest level anything in this card will produce. A real
#: mute is ``sink.interrupt()`` — it stops the schedule and tells the provider
#: — and it is a different act with a different name.
MIN_DUCK_GAIN = 0.05

#: How far playback drops while a provisional barge-in is open. AIR-1's
#: ``signal_to_echo_db`` from the double-talk leg is what should eventually set
#: this (its handoff, verbatim: "not the attenuation figure") — until that
#: session runs this is a taste value and is declared as one.
DEFAULT_DUCK_GAIN = 0.18

#: Words that end the argument. A backchannel is a noise; a turn has content.
#: Used only when a partial owner transcript reaches the controller — nothing
#: in this tree produces one yet (the hosted lane delivers the owner transcript
#: after the turn), so this is a seam with a test and no product caller, and
#: DUPLEX1_STATUS.md says so rather than counting it as wiring.
STOP_WORDS: frozenset[str] = frozenset(
    {"stop", "wait", "no", "hold", "quiet", "shush", "hang", "enough", "actually"}
)


class TurnControllerError(ValueError):
    """A turn controller was built with a number that cannot mean anything."""


@dataclass(frozen=True)
class TurnAction:
    """One instruction for the voice. Returned; never executed here."""

    kind: str
    at_s: float
    reason: str
    #: Playback gain the action asks for. Meaningful for DUCK and RESUME.
    gain: float = 1.0

    @property
    def is_noop(self) -> bool:
        return self.kind == ACTION_NONE


def _noop(at_s: float, reason: str = "") -> TurnAction:
    return TurnAction(kind=ACTION_NONE, at_s=float(at_s), reason=reason)


class TurnController:
    """The local turn state machine. Pure, bounded, and never raises on input.

    Thread-safety is the same shape as :class:`~parcel_robot.duplex.filler_policy.FillerPolicy`:
    one lock, held only across bookkeeping, never across a caller's I/O. The
    lane drives it from the pump thread and the panel reads its snapshot from
    the HTTP thread, so "one lock" is not decoration.
    """

    def __init__(
        self,
        *,
        floor_ms: float = 0.0,
        duck_gain: float = DEFAULT_DUCK_GAIN,
        stop_words: frozenset[str] = STOP_WORDS,
    ) -> None:
        floor = float(floor_ms)
        if not math.isfinite(floor) or floor < 0.0:
            raise TurnControllerError(f"floor_ms must be finite and >= 0, got {floor_ms!r}")
        gain = float(duck_gain)
        if not math.isfinite(gain) or not MIN_DUCK_GAIN <= gain <= 1.0:
            raise TurnControllerError(
                f"duck_gain must be within [{MIN_DUCK_GAIN}, 1] — a duck to silence is a "
                f"dropped connection, not a quieter dog; got {duck_gain!r}"
            )
        self._lock = threading.RLock()
        self._floor_s = floor / 1000.0
        self._duck_gain = gain
        self._stop_words = frozenset(str(word).lower() for word in stop_words)

        self._state = STATE_LISTEN
        self._owner_started_at: float | None = None
        self._deadline: float | None = None
        self._ducked = False
        #: An owed turn survives EVERY transition. Only ``note_turn_answered``
        #: clears it, which is what makes "no owed turn is dropped on a state
        #: change" a measurable property rather than a hope.
        self._owed = False
        self._owed_since: float | None = None

        self.ducks = 0
        self.resumes = 0
        self.commits = 0
        self.backchannels = 0
        self.overlaps = 0
        self.initiative_grants = 0
        self.initiative_refusals = 0
        self.owed_turns_opened = 0
        self.owed_turns_answered = 0
        self.owed_turns_abandoned = 0
        self.transitions = 0
        self.last_reason = ""

    # ------------------------------------------------------------- read-only
    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def floor_ms(self) -> float:
        with self._lock:
            return self._floor_s * 1000.0

    @property
    def duck_gain(self) -> float:
        return self._duck_gain

    @property
    def ducked(self) -> bool:
        """Is playback attenuated right now?"""

        with self._lock:
            return self._ducked

    @property
    def owner_turn_owed(self) -> bool:
        with self._lock:
            return self._owed

    @property
    def initiative_allowed(self) -> bool:
        """May the robot start talking on its own RIGHT NOW? A PURE read.

        Only from idle LISTEN, and only with no turn owed. Every other state
        means somebody is mid-turn — the robot, the owner, or both — and a
        proactive remark dropped into one is the collision the card
        pre-registers at zero.

        **Correction pass:** reading this used to MOVE the counters D-4 is
        scored from, so a test that sampled it in a loop inflated its own
        evidence and a panel that rendered it changed the number it was
        rendering. Sampling is free now; :meth:`consult_initiative` is the
        thing that counts, and only a real caller asking permission calls it.
        """

        with self._lock:
            return self._state == STATE_LISTEN and not self._owed

    def consult_initiative(self) -> bool:
        """Ask permission to speak unprompted, and be counted asking.

        The counting is the point: "the gate was never consulted" and "the gate
        always said yes" are different failures and must not look the same in a
        snapshot.
        """

        with self._lock:
            allowed = self._state == STATE_LISTEN and not self._owed
            if allowed:
                self.initiative_grants += 1
            else:
                self.initiative_refusals += 1
            return allowed

    # -------------------------------------------------------------- the robot
    def note_response_requested(self, at_s: float) -> TurnAction:
        """A reply has been asked for. THINK until audio actually starts."""

        with self._lock:
            if self._state in (STATE_LISTEN, STATE_YIELD):
                self._enter(STATE_THINK, "a reply was asked for")
            return _noop(at_s)

    def note_robot_started(self, at_s: float) -> TurnAction:
        """The robot's reply began playing."""

        with self._lock:
            self._owner_started_at = None
            self._deadline = None
            # A new reply always starts at unity: the sink re-arms per
            # utterance and the panel resets its gain on the utterance frame,
            # so a controller that stayed "ducked" across replies would be
            # describing a gain nobody is applying.
            self._ducked = False
            self._enter(STATE_SPEAK, "the robot took the floor")
            return _noop(at_s)

    def note_robot_ended(self, at_s: float, *, cancelled: bool = False) -> TurnAction:
        """The reply finished, or was cancelled out from under the controller.

        ``cancelled=True`` is the provider's own ``interrupt_response`` cancel
        (MARK-1, correction pass §2): the reply is dead whatever this
        controller believed, the owner is mid-sentence, and the floor is
        theirs. It is a COMMIT and not a survived backchannel.
        """

        with self._lock:
            was_overlap = self._state == STATE_OVERLAP
            self._owner_started_at = None
            self._deadline = None
            resume = self._ducked
            self._ducked = False
            if cancelled and was_overlap:
                self.commits += 1
                self._enter(STATE_YIELD, "the provider cancelled the reply during an overlap")
                return TurnAction(
                    kind=ACTION_COMMIT,
                    at_s=float(at_s),
                    reason="provider cancelled during overlap",
                )
            self._enter(STATE_LISTEN, "the reply ended")
            if resume:
                self.resumes += 1
                return TurnAction(
                    kind=ACTION_RESUME,
                    at_s=float(at_s),
                    reason="the reply ended while ducked",
                    gain=1.0,
                )
            return _noop(at_s)

    # -------------------------------------------------------------- the owner
    def note_owner_started(self, at_s: float) -> TurnAction:
        """The owner started making noise. DUCK first, decide second."""

        now = float(at_s)
        with self._lock:
            if self._state not in (STATE_SPEAK, STATE_OVERLAP):
                # Nobody is being talked over: the owner simply has the floor.
                self._owner_started_at = now
                self._enter(STATE_LISTEN, "the owner started speaking")
                return _noop(now)
            if self._state == STATE_OVERLAP:
                # One overlap per reply. A second VAD start inside the same
                # burst is the same turn and must not re-arm the deadline.
                return _noop(now, "already overlapping")
            self.overlaps += 1
            self._owner_started_at = now
            self._deadline = None if self._floor_s <= 0.0 else now + self._floor_s
            self._enter(STATE_OVERLAP, "the owner spoke over the reply")
            if self._floor_s <= 0.0:
                # Floor off: R16 to the frame. No duck, no hold, commit now —
                # the duck would be a control frame the browser applies after
                # the reply has already been stopped.
                self.commits += 1
                self._enter(STATE_YIELD, "no floor: the barge-in commits on the frame")
                return TurnAction(
                    kind=ACTION_COMMIT, at_s=now, reason="floor is off; commit on the frame"
                )
            self.ducks += 1
            self._ducked = True
            return TurnAction(
                kind=ACTION_DUCK,
                at_s=now,
                reason="provisional barge-in; the reply is quiet while the floor runs",
                gain=self._duck_gain,
            )

    def note_owner_stopped(self, at_s: float) -> TurnAction:
        """The owner stopped. Inside the floor it was a backchannel.

        Whichever producer reaches this first wins — server VAD through
        ``lane._on_speech_stopped``, or the local endpointer that does not
        exist yet through ``lane.note_owner_speech_stopped()``. The controller
        does not care which, and that is the point of the seam.
        """

        now = float(at_s)
        with self._lock:
            if self._state != STATE_OVERLAP or self._owner_started_at is None:
                return _noop(now)
            burst_s = max(0.0, now - self._owner_started_at)
            deadline = self._deadline
            if deadline is not None and now <= deadline:
                self.backchannels += 1
                self._owner_started_at = None
                self._deadline = None
                resume = self._ducked
                self._ducked = False
                self._enter(
                    STATE_SPEAK,
                    f"backchannel: {burst_s * 1000.0:.0f} ms of noise inside the floor",
                )
                if resume:
                    self.resumes += 1
                    return TurnAction(
                        kind=ACTION_RESUME,
                        at_s=now,
                        reason="backchannel survived; the reply comes back up",
                        gain=1.0,
                    )
                return _noop(now)
            return self._commit(now, "the owner spoke past the floor")

    def note_owner_words(self, at_s: float, text: str) -> TurnAction:
        """A partial owner transcript. A content word ends the argument early.

        **No product caller.** The hosted lane delivers the owner's transcript
        after the turn, not during it, so nothing in this tree can call this
        yet. It is here because the card's design names it and because the
        state machine has to have a defined answer when a producer arrives —
        not because it is wired. Tested, counted, and declared unwired.
        """

        now = float(at_s)
        with self._lock:
            if self._state != STATE_OVERLAP:
                return _noop(now)
            words = {part.strip(".,!?;:").lower() for part in str(text).split()}
            if not (words & self._stop_words):
                return _noop(now, "no content word yet")
            return self._commit(now, f"content word in {text!r}")

    def tick(self, at_s: float) -> TurnAction:
        """The deadline is only a deadline if something checks it."""

        now = float(at_s)
        with self._lock:
            if self._state != STATE_OVERLAP or self._deadline is None:
                return _noop(now)
            if now < self._deadline:
                return _noop(now)
            return self._commit(now, "the backchannel floor expired")

    # -------------------------------------------------------- the owed turn
    def note_turn_owed(self, at_s: float) -> None:
        """The owner said something the robot has not answered yet."""

        with self._lock:
            if not self._owed:
                self.owed_turns_opened += 1
                self._owed_since = float(at_s)
            self._owed = True

    def note_turn_answered(self, at_s: float) -> None:
        """...and it was answered. The ONLY way an owed turn is cleared."""

        del at_s
        with self._lock:
            if self._owed:
                self.owed_turns_answered += 1
            self._owed = False
            self._owed_since = None

    def note_turn_abandoned(self, at_s: float, reason: str = "") -> None:
        """An owed turn was given up on deliberately (a session died, say).

        Counted apart from ``answered`` so a soak can tell "every owed turn was
        answered" from "every owed turn stopped being owed".
        """

        del at_s
        with self._lock:
            if self._owed:
                self.owed_turns_abandoned += 1
                self.last_reason = reason or "owed turn abandoned"
            self._owed = False
            self._owed_since = None

    def owed_for_s(self, at_s: float) -> float | None:
        with self._lock:
            if not self._owed or self._owed_since is None:
                return None
            return max(0.0, float(at_s) - self._owed_since)

    # ------------------------------------------------------------- internals
    def _commit(self, at_s: float, reason: str) -> TurnAction:
        """Caller holds the lock."""

        self.commits += 1
        self._owner_started_at = None
        self._deadline = None
        self._ducked = False
        self._enter(STATE_YIELD, reason)
        return TurnAction(kind=ACTION_COMMIT, at_s=float(at_s), reason=reason)

    def _enter(self, state: str, reason: str) -> None:
        """Caller holds the lock."""

        if state not in STATES:  # pragma: no cover - defensive
            raise TurnControllerError(f"unknown turn state {state!r}")
        if state != self._state:
            self.transitions += 1
        self._state = state
        self.last_reason = reason

    def reset(self, *, keep_owed: bool = True) -> None:
        """A new session. The owed turn survives unless the caller says not to.

        ``keep_owed=True`` by default because a reconnect is not an answer: the
        owner asked something and a dropped socket does not make it answered.
        MARK-1's hold, by contrast, is reset at ``_connect()``/``close()`` — a
        provisional barge-in belongs to one socket. Two different lifetimes, on
        purpose.
        """

        with self._lock:
            self._state = STATE_LISTEN
            self._owner_started_at = None
            self._deadline = None
            self._ducked = False
            if not keep_owed:
                if self._owed:
                    self.owed_turns_abandoned += 1
                self._owed = False
                self._owed_since = None
            self.last_reason = "reset"

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "state": self._state,
                "floor_ms": round(self._floor_s * 1000.0, 3),
                "duck_gain": self._duck_gain,
                "ducked": self._ducked,
                "owner_turn_owed": self._owed,
                "overlaps": self.overlaps,
                "ducks": self.ducks,
                "resumes": self.resumes,
                "commits": self.commits,
                "backchannels": self.backchannels,
                "initiative_grants": self.initiative_grants,
                "initiative_refusals": self.initiative_refusals,
                "owed_turns_opened": self.owed_turns_opened,
                "owed_turns_answered": self.owed_turns_answered,
                "owed_turns_abandoned": self.owed_turns_abandoned,
                "transitions": self.transitions,
                "last_reason": self.last_reason,
            }


__all__ = [
    "ACTION_COMMIT",
    "ACTION_DUCK",
    "ACTION_NONE",
    "ACTION_RESUME",
    "DEFAULT_DUCK_GAIN",
    "MIN_DUCK_GAIN",
    "STATES",
    "STATE_LISTEN",
    "STATE_OVERLAP",
    "STATE_SPEAK",
    "STATE_THINK",
    "STATE_YIELD",
    "STOP_WORDS",
    "TurnAction",
    "TurnController",
    "TurnControllerError",
]
