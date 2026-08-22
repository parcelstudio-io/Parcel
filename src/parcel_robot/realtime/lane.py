"""The Realtime conversational lane (card R1, task_7).

WHAT THIS OWNS
--------------
One hosted voice session and everything that has to be true around it:

* **session lifecycle** — instructions + memory tail up before any audio,
  a watchdog for the silent-stall case, and a 60-minute rollover that takes the
  same reconnect path (the provider was never holding the memory, so a rollover
  is invisible). A reconnect that inherits an unanswered turn also **repays**
  it — once, counted, and never for a response that actually completed;
* **the idle hang-up** (card R16) — a session nobody is talking to is CLOSED
  rather than renewed. Idle is stated in conversation, not in packets: no owner
  turn, no narration, nothing outstanding, for ``idle_close_after_s``. The
  rollover is checked second, so an idle session at its 60-minute cap hangs up
  instead of opening a fresh paid one;
* **one beat per tool turn** — the ``response.create`` that follows a brokered
  tool answer is conditional, because the model's pre-call announcement is a
  beat the owner already heard. It is only skipped when the call SUCCEEDED and
  its result is a receipt for something the robot's own systems will report
  later; every failure, deferral, refusal and answer-shaped result still gets
  its sentence;
* **the playback bridge** — provider PCM16 coalesced to >=240 ms and
  WAV-wrapped at 24 kHz before it reaches ``SpeakerSink``. Both halves are
  load-bearing: the sink infers its rate from the first RIFF header and
  otherwise plays hosted audio at 16 kHz (50% slow), and ``prosody`` returns
  zero accents for chunks under 200 ms;
* **sink ownership** — ``begin_utterance()`` at every hosted response start,
  because the sink latches suppression on ``interrupt()`` and never re-arms on
  ``enqueue``; plus an explicit refusal to enqueue while a DuplexVoiceSession
  output is live, asserted rather than assumed;
* **barge-in** — server VAD ``speech_started`` while a response plays means
  sink interrupt, ``response.cancel``, and ``conversation.item.truncate`` at the
  milliseconds the sink actually PLAYED, so the provider's belief about its own
  reply matches what the owner heard;
* **the ledger** — both sides of every turn, with the provider's item id kept
  as an annotation;
* **the arming gate** — fail-closed, same shape as ``MicArmingDecision``;
* **the tool broker** — which in R1 refuses every call. Tools are R3.

WHAT THIS DELIBERATELY DOES NOT OWN
-----------------------------------
Deciding anything. Hosted transcripts reach the robot only through
``RobotRuntime.submit_realtime_transcript`` — a closed, four-step ingress — and
tool calls are refused outright. The lane relays, plays, ledgers, and reconnects.

A NOTE ON WHAT "STOP" MEANS HERE
--------------------------------
A spoken "stop" during a hosted session is transcribed in the cloud. It is
supplemental. The cloud-independent stop paths — the panel STOP button, the
operator stop, every local watchdog — are untouched by this module and remain
the guarantee.
"""

from __future__ import annotations

import json
import math
import random
import re
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from parcel_robot.voice_audio import pcm16_wav

from .config import RealtimeConfig
from .ingress import RealtimeTranscriptOutcome
from .protocol import (
    PCM16_SAMPLE_RATE_HZ,
    ConversationItemCreate,
    ConversationItemTruncate,
    ErrorEvent,
    FunctionCallArgumentsDone,
    FunctionCallOutput,
    InputAudioBufferAppend,
    InputTranscriptionCompleted,
    OutputAudioDelta,
    OutputAudioDone,
    OutputTranscriptDelta,
    OutputTranscriptDone,
    RealtimeProtocolError,
    ResponseCancel,
    ResponseCreate,
    ResponseDone,
    RetainedEvent,
    ServerEvent,
    SessionCreated,
    SessionUpdate,
    SpeechStarted,
    SpeechStopped,
    parse_server_event,
)
from .tool_broker import RESPONSE_FROM_OWNER, RESPONSE_FROM_SYSTEM
from .transport import Transport, TransportClosed

#: Minimum audible chunk handed to the sink. Below ~200 ms the prosody analyzer
#: returns no accents at all, so a smaller coalesce would silently cost the
#: hosted voice its beat nods.
DEFAULT_COALESCE_MS = 240.0

#: Card R22, work item 1. How many dispatch-failure LINES are kept. The counts
#: (``dispatch_failure_count`` / ``dispatch_failure_types``) stay exact; this
#: only bounds the text, because a lane failing every frame at 20 Hz must not
#: grow an unbounded list inside the process the firewall is protecting.
DISPATCH_FAILURE_LOG_LIMIT = 200

#: Every function call in R1 gets exactly this. Still the answer whenever no
#: ``tool_handler`` is wired — a build with no broker refuses, it never guesses.
TOOL_REFUSAL_OUTPUT = json.dumps({"error": "tools are not enabled in R1"})

#: Card R11, design point 5. The answer when a response the ROBOT started
#: reaches a tool handler that cannot be told the provenance, so cannot enforce
#: the motion gate itself. Shaped like a broker result so the model narrates it
#: the same way it narrates every other refusal.
SYSTEM_INITIATED_UNGATED_OUTPUT = json.dumps(
    {
        "status": "rejected",
        "refusal": "system_initiated_ungated",
        "detail": (
            "this reply was triggered by the robot's own status update rather than by "
            "the owner, and the tool surface cannot confirm that; only what the owner "
            "asks for may start an action"
        ),
    },
    sort_keys=True,
)

#: The one tool status that means "the robot took it". Stated here rather than
#: imported from ``tool_broker``: the lane has never imported the broker — it
#: holds it behind :class:`ToolHandlerLike` — and a build wired to some other
#: handler must not depend on that module existing.
TOOL_STATUS_OK = "ok"

#: Card R6, Defect 2. Tools whose ``status: ok`` answer is a RECEIPT for a thing
#: the robot's own systems will report later — not an ANSWER the owner is
#: waiting to hear. Only for these may the lane stay quiet after the call, and
#: only when the model already spoke in the same response.
#:
#: The distinction is the whole safety of this fix. ``get_status`` and
#: ``recall_memory`` also return ``status: ok``, but their result IS the answer:
#: suppressing their beat would leave "what do you remember about the willow?"
#: answered by a pre-call "let me check" and nothing else — lying by silence,
#: which is a worse defect than the two beats this card removes. Anything not
#: named here (including a tool this lane has never heard of) gets its beat, so
#: the failure direction is always "one beat too many", never silence.
DEFAULT_RECEIPT_TOOLS = frozenset({"navigate_to", "play_gesture", "set_pose"})

#: Card R6, Defect 2. Per-response instructions for the beat that DOES survive.
#: Sent APPENDED to the session instructions, never instead of them: the
#: provider's ``response.instructions`` REPLACES the session prompt for that one
#: response, so sending the rule alone would drop the persona and every
#: guardrail for exactly the beat where "never claim to have arrived" matters
#: most. See ``_beat_instructions``.
#:
#: CARD R15 ADDS THE TENSE SENTENCE, and only that. Owner session 1 caught this
#: beat saying "Done—I made a small circle around you, and it was okay" ONE
#: SECOND after the orbit was admitted. The result it was narrating said the
#: circle had STARTED; the beat reported it as over. The broker now marks every
#: activity result with its tense, and this is the half of the pair that tells
#: the model what to do with the mark. SI is untouched: this is per-response
#: wording about one result, not a standing rule about who the robot is.
RESULT_BEAT_RULE = (
    "The robot's own systems have just reported the result of what you asked "
    "for. Say ONE short spoken sentence about what actually came back. Do not "
    "restate what you were about to do and do not promise a next step. If it "
    "was refused, deferred or dropped, say plainly what stopped it. If the "
    "result says the work has only STARTED, say so in the present progressive "
    "— the robot is doing it right now — and never say it is done, finished or "
    "that you have already made, walked or performed it: the robot reports the "
    "ending itself, when it actually ends. Never open this sentence by saying "
    "you are checking, looking, thinking, seeing or pulling anything up: the "
    "checking already happened and its result is in front of you."
)

#: Card R19, work item 3. Sent IN ADDITION to :data:`RESULT_BEAT_RULE` — never
#: instead of it — on the beat that carries an ANSWER rather than a receipt.
#:
#: live_run_1 (2026-08-20) is why the two rules are separate. ``get_status``
#: fetched ``battery 90.0%`` and ``recall_memory`` fetched the owner's memory;
#: both beats were REQUESTED (the arithmetic in R19_STATUS §0.1 proves the
#: suppression policy never touched them) and both came back as deliberation:
#: *"Let me check what I can safely report and then we'll go from there."* and
#: *" let me take a"*. The general rule tells the model to report a RESULT; it
#: never told it that this particular result is the answer to the question the
#: owner just asked, and the longest concrete clause in it is about activity
#: tense, which an answer tool has none of. So the model narrated the answer
#: beat as if it were one more receipt.
ANSWER_BEAT_RULE = (
    "The owner asked you a QUESTION and this result is the ANSWER to it. Say "
    "the answer itself — the actual figures, names and facts that are in the "
    "result — in your very first words. Do not say you are checking, looking, "
    "thinking about it, pulling it up or getting back to them: the lookup is "
    "already finished and its answer is the thing you are holding. If the "
    "result is empty, say plainly that you have nothing for them."
)

#: Card R19, mechanism C. The provider's own code for "you asked me to start a
#: response while one was already running". Observed live on 2026-08-20 eating
#: the beat that was carrying an e-stop refusal:
#:
#:   Conversation already has an active response in progress:
#:   resp_EEy3T5quJvQDbJRVd2JNe. Wait until the response is finished before
#:   creating a new one.
CODE_RESPONSE_ALREADY_ACTIVE = "conversation_already_has_active_response"

#: Card R19, work item 2. Tools whose result IS the answer the owner is waiting
#: for. THE POINT OF THIS SET is that it outranks ``receipt_tools`` absolutely:
#: no configuration, no injected receipt list and no future tool surface may
#: make one of these suppressible. R6 protected them by leaving them OUT of
#: ``DEFAULT_RECEIPT_TOOLS``, which is a protection by omission — it survives
#: only as long as nobody names them in the other list, and a constructor
#: argument exists that does exactly that.
DEFAULT_ANSWER_TOOLS = frozenset({"get_status", "recall_memory"})

#: The stronger half of the same guarantee, and the one that does not depend on
#: this module knowing the tool surface at all: a handler may mark its own
#: result ``{"answer": true}`` and the lane will never suppress it, whatever the
#: tool is called. Closes R6's Open risk 4 (``DEFAULT_RECEIPT_TOOLS`` is a name
#: list in the lane, coupling two modules that deliberately do not import each
#: other) from the side that fails safe: the classification travels WITH the
#: result instead of being guessed from a name.
ANSWER_RESULT_KEY = "answer"

#: Card R19, work item 2 — the filler gate.
#:
#: A clause that opens with one of these is a DEFERRAL: the robot announcing it
#: is about to check, think or look, which tells the owner nothing about the
#: world and nothing about what the robot did. Every one of these is a phrase
#: ``gpt-realtime-2.1-mini`` actually produced in live_run_1 or in R6's own live
#: sessions; none of them is a sentence anyone would accept as an answer.
#:
#: Matched as a PREFIX of a clause, not anywhere inside it, so "let me check"
#: is filler while "I can tell you're feeling the crowd, so let me check the
#: map" is not — the owner heard something real in the first clause either way.
FILLER_CLAUSE_PREFIXES: tuple[str, ...] = (
    "let me think",
    "let me check",
    "let me see",
    "let me look",
    "let me take",
    "let me pull",
    "let me figure",
    "let me work out",
    "let me find out",
    "let me get back",
    "let me report",
    "let me describe",
    "let me run through",
    "let me go through",
    "let me have a look",
    "let's see",
    "lets see",
    "i'll check",
    "i'll see",
    "i'll think",
    "i'll look",
    "i'll take a look",
    "i'll figure",
    "i'll find out",
    "i'll get back",
    "i'll let you know",
    "i'll tell you what happened",
    "i'm checking",
    "i'm looking",
    "i'm thinking",
    "give me a moment",
    "give me a second",
    "give me a sec",
    "one moment",
    "one second",
    "just a moment",
    "just a second",
    "just a sec",
    "hold on",
    "hang on",
    "bear with me",
    "checking on that",
    "looking into that",
    "working on it",
    "on it",
    "we'll see",
    "we'll go from there",
    "go from there",
    "then we'll go",
)

#: Clauses that are pure acknowledgement. A response made only of these has told
#: the owner nothing, however many of them there are.
FILLER_ACKNOWLEDGEMENTS: frozenset[str] = frozenset(
    {
        "ok",
        "okay",
        "alright",
        "all right",
        "sure",
        "sure thing",
        "got it",
        "gotcha",
        "yeah",
        "yep",
        "yes",
        "mm",
        "mmm",
        "hmm",
        "uh",
        "um",
        "well",
        "so",
        "oh",
        "right",
        "nice question",
        "good question",
        "great question",
        "interesting question",
        "that's a good one",
    }
)

#: How many words of non-filler content a response must carry before the lane
#: will accept it as "the model already spoke" and stay quiet after the tool.
#: Three, because two-word remainders ("of course", "no problem") are
#: acknowledgements wearing a different coat, and because the failure direction
#: of setting it too HIGH is one beat too many while the failure direction of
#: setting it too low is the silence this card exists to end.
MIN_SUBSTANTIVE_WORDS = 3

#: Clause boundaries. Deliberately NOT ``and``/``then``: "Okay, let me check
#: what I can safely report and then we'll go from there" must read as one
#: deferral rather than as a deferral plus a fragment, or the tail of a filler
#: sentence starts counting as content.
_CLAUSE_SPLIT = re.compile(r"[.!?;:,—–]+|\s-\s")

#: Everything that is not a word character, an apostrophe or a space.
_WORD_NOISE = re.compile(r"[^\w' ]+", re.UNICODE)

#: Stripped from the front of a clause before the filler prefixes are matched.
_LEADING_CONJUNCTIONS: frozenset[str] = frozenset({"and", "but", "so", "then", "or", "now"})


def _normalise_clause(text: str) -> str:
    """Lowercase, curly quotes flattened, punctuation and runs of space gone."""

    flattened = str(text).replace("’", "'").replace("‘", "'")
    return " ".join(_WORD_NOISE.sub(" ", flattened.lower()).split())


def clause_is_filler(clause: str) -> bool:
    """Is this clause a deferral or a bare acknowledgement? Card R19.

    Empty is filler. Anything this function is unsure about is NOT filler,
    which is the conservative direction for the caller that matters most
    (:func:`speech_is_substantive`), because a clause wrongly called filler
    costs one extra beat and a clause wrongly called content costs the owner
    an answer.
    """

    clean = _normalise_clause(clause)
    # A clause joined on with "and"/"then" is the same clause for this purpose:
    # "…and then we'll go from there" is not content because it was preceded by
    # a conjunction. Stripped iteratively so "and then we'll see" reduces once.
    while True:
        head, _, tail = clean.partition(" ")
        if head not in _LEADING_CONJUNCTIONS or not tail:
            break
        clean = tail
    if not clean:
        return True
    if clean in FILLER_ACKNOWLEDGEMENTS:
        return True
    return clean.startswith(FILLER_CLAUSE_PREFIXES)


def speech_is_substantive(text: str) -> bool:
    """Did this response actually SAY something, or only announce that it would?

    Card R19, work item 2. R6's suppression condition was "the model already
    spoke in the response that carried the call", implemented as "a non-blank
    transcript delta arrived". live_run_1 showed what the provider does with
    that: it co-emits *"Okay, let me check how to get you there."*, the lane
    reads it as the turn's beat, suppresses the one sentence that carried the
    fact, and the owner hears a robot promising to check and then nothing at
    all — nine consecutive turns of it.

    The rule: strip the deferral and acknowledgement clauses; whatever is left
    is what the owner actually learned. Fewer than
    :data:`MIN_SUBSTANTIVE_WORDS` words left means nothing was learned.

    R6's own live announcement, ``"Okay, let's head over to the sidewalk."``,
    stays SUBSTANTIVE — it names the destination and commits to the act — so
    R6's single-beat navigation turn is preserved rather than reverted. What
    changes is the deliberation form R6 never measured.
    """

    words = 0
    for clause in _CLAUSE_SPLIT.split(str(text)):
        if clause_is_filler(clause):
            continue
        words += len(_normalise_clause(clause).split())
        if words >= MIN_SUBSTANTIVE_WORDS:
            return True
    return False

#: Card R6, Defect 1. Consecutive turn repays with no completed response in
#: between. The card's rule is "one repay per reconnect, and a repay that itself
#: stalls is the next watchdog cycle's problem" — this is the bound on *that*
#: sentence: a turn the provider dies on every single time is abandoned out
#: loud (a ledger row and a counter) rather than re-asked forever on a socket
#: that keeps billing.
DEFAULT_REPAY_LIMIT = 3

#: Card R8. How many conversation items the lane keeps a descriptor for while it
#: waits to learn whether the provider kept them. An item that is ACCEPTED never
#: produces an error frame, so its descriptor is never claimed and the map would
#: otherwise grow for the life of the session. Oldest is evicted first: a
#: refusal arrives within a frame or two of the item that caused it, so anything
#: this far back was accepted.
DEFAULT_ITEM_TRACE_LIMIT = 64

#: Card R8. How many server refusals the snapshot carries alongside the count.
#: The count answers "is something wrong"; the window answers "what". Five is
#: enough to show a whole memory tail being refused without turning
#: ``/api/state`` into a log file.
DEFAULT_SERVER_ERROR_WINDOW = 5

#: Card R8, work item 3. What the lane calls the item it just sent, so a refusal
#: can be reported as the thing it cost rather than as an opaque frame. Purposes
#: the snapshot and the counters key on, stated once.
ITEM_PURPOSE_TAIL = "memory tail"
ITEM_PURPOSE_OWNER_TURN = "owner turn"
ITEM_PURPOSE_ACTION_REPORT = "action report"
ITEM_PURPOSE_NARRATION = "narration"

#: Reconnect backoff (card R1.6+R3, from the R1.5 audit's first standing risk:
#: "Reconnect still has no backoff … a flapping provider would hot-loop").
#: The first FAILURE retry waits ~0.25-0.5 s, then doubles, capped. A *rollover*
#: is a scheduled, healthy reconnect and deliberately waits nothing.
DEFAULT_RECONNECT_BACKOFF_S = 0.5
DEFAULT_RECONNECT_BACKOFF_MAX_S = 30.0

#: Reasons that mean the session died on us. Only these back off.
FAILURE_RECONNECT_REASONS = frozenset({"stall", "disconnect"})

#: Card R16. What ``tick()`` returns when it HUNG UP rather than reconnected.
#: Deliberately not in :data:`FAILURE_RECONNECT_REASONS` and deliberately not a
#: reconnect reason at all: nothing is being recovered, there is no new session,
#: and the driver reads this exact string as its cue to stop pumping a lane that
#: has no socket to pump. See :data:`~parcel_robot.realtime.driver.DEFAULT_STOP_REASONS`.
REASON_IDLE_HANG_UP = "idle"

#: Card R16. The ledger row an idle hang-up leaves behind, shaped like the
#: ``[session rollover]`` and ``[turn repaid]`` markers beside it so a reader of
#: the transcript can see WHY the conversation stops here rather than inferring
#: it from a gap. The rows this replaces are the seven the owner woke up to.
IDLE_LEDGER_PREFIX = "[idle hang-up after"

#: How long a caller that needs a session waits for an in-flight reconnect
#: (card R4-lite, task_1). The lane is genuinely multi-threaded in the product —
#: the driver pumps on its own thread while the panel's HTTP thread submits
#: turns — and a reconnect is not instantaneous: it closes the socket, waits out
#: the backoff, and only then opens a new one. A turn that arrives inside that
#: window has to WAIT for the new session, because the alternative (concluding
#: "no session, I'll open my own") is what silently orphaned a socket and lost
#: the owner's turn. Ten seconds is well past the first few rungs of the backoff
#: ladder and well short of "the panel is hung": past it the lane refuses out
#: loud rather than accepting a turn nobody will answer.
DEFAULT_ENTRY_TIMEOUT_S = 10.0

#: Ear-oriented instructions layered under the personality. Not persona: these
#: are the rules that keep a hosted voice honest about a physical robot.
GUARDRAILS = (
    "You are speaking aloud through a robot dog's speaker. "
    "Use short spoken sentences. "
    "Never narrate your own mechanics or mention tools, sessions, or transcripts. "
    "Acknowledge a request before anything happens, and never claim to have "
    "arrived anywhere or completed a physical action — the robot reports that "
    "itself. "
    "Admit plainly what you cannot do. "
    "If the robot's own systems report an action, describe it; never decide it."
)

CODE_ARMED = "armed"
CODE_DISABLED = "realtime_disabled"
CODE_NO_HANDSHAKE = "no_handshake_token"
CODE_NO_MIC_GESTURE = "no_mic_gesture"
CODE_NO_TRANSPORT = "no_transport"
CODE_BUDGET_EXHAUSTED = "monthly_budget_exhausted"

SPEAKER_OWNER = "owner"
SPEAKER_ROBOT = "robot"
SPEAKER_SYSTEM = "system"


class RealtimeLaneError(RuntimeError):
    """The lane refused to do something. Never a silent no-op."""


class SinkOwnershipError(RealtimeLaneError):
    """Two speakers tried to own one mouth."""


@dataclass(frozen=True)
class RealtimeArmingDecision:
    """May the hosted lane open a session? Mirrors ``MicArmingDecision``.

    Deliberately NOT ``decide_microphone_arming``: that gate requires a local
    recognizer, and passing "the cloud is reachable" as recognizer availability
    is precisely the service-reachability arming FIX-A exists to ban.
    """

    armed: bool
    code: str
    reason: str
    #: Card R25. Facts the owner must see even when the answer is "armed".
    #: Today there is exactly one producer: an unreadable spend ledger, which
    #: fails OPEN (see :func:`decide_realtime_arming`) and therefore has no
    #: other way to be heard. A refusal carries its reason; a *degraded yes*
    #: had nowhere to put one until this field existed.
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "armed": self.armed,
            "code": self.code,
            "reason": self.reason,
            "warnings": list(self.warnings),
        }


def decide_realtime_arming(
    *,
    config: RealtimeConfig,
    handshake_token: str | None,
    mic_gesture: bool,
    transport_available: bool = True,
    spend_usd: float = 0.0,
    spend_readable: bool = True,
    spend_month: str = "",
    spend_note: str = "",
) -> RealtimeArmingDecision:
    """Fail closed. Three independent yeses are required, plus a budget.

    An enabled flag is consent to the FEATURE; an authenticated handshake is
    proof the caller is the local panel; the mic gesture is the owner's
    per-connection act. None of the three substitutes for another, and none of
    them is "the service answered".

    THE BUDGET, AND WHY IT USED TO DO NOTHING (card R25, audit §Ops-2)
    ------------------------------------------------------------------
    The ``spend_usd >= config.monthly_budget_usd`` comparison below is
    unchanged since R1. What changed is that somebody now passes a number.
    ``RealtimeLane.arm`` defaulted it to ``0.0`` for the whole of R1-R24, so
    the owner's documented ceiling — "the arming gate refuses to open a session
    once this month's estimated spend reaches this number", in the owner's own
    ``realtime.yaml`` — compared zero against twenty-five, every time, forever.
    A documented safety control that does not exist is worse than an absent one.

    ``spend_readable`` is the fail-**open** half, and it is the one deliberate
    inversion of this file's fail-closed doctrine. A ledger that cannot be read
    yields ``readable=False`` and this gate does NOT refuse: it arms, and
    attaches a warning naming the ledger and the fact that the ceiling is not
    being enforced. The doctrine is about the CONFIG (a typo'd budget must
    refuse to load, and still does); a *measurement* that fails closed is a
    robot grounded by a read-only disk. See
    :mod:`parcel_robot.realtime.spend_ledger`.

    THERE IS DELIBERATELY NO SAFETY EXEMPTION *HERE* (card R25 work item 4)
    -----------------------------------------------------------------------
    The asymmetry the card asks for — SAFETY-class facts outrank the cost
    ceiling — is real, and it lives in :meth:`RealtimeLane.narrate_event`, not
    in this function. The reason is card R16's older and stronger rule: a
    robot-initiated fact may never OPEN a paid session. A latch announced into
    a session the owner walked away from an hour ago is spend with no listener,
    so a closed lane stays closed for every class of fact, at every budget.
    Nothing safety-related therefore ever reaches this gate, and giving it an
    exemption would have been a parameter no caller could pass.

    What the ceiling gates here is exactly one thing: the owner pressing the
    microphone button to start a new billed conversation.
    """

    warnings: list[str] = []
    if not spend_readable and spend_note:
        warnings.append(spend_note)

    if not config.enabled:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_DISABLED,
            reason=(
                "Realtime lane not armed: realtime.enabled is false "
                f"(config source: {config.source})."
            ),
            warnings=tuple(warnings),
        )
    if not handshake_token:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_NO_HANDSHAKE,
            reason=(
                "Realtime lane not armed: no authenticated handshake token. The audio "
                "listener requires the panel's per-process CSRF token, exactly as "
                "_authorize_post does."
            ),
            warnings=tuple(warnings),
        )
    if not mic_gesture:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_NO_MIC_GESTURE,
            reason=(
                "Realtime lane not armed: the owner has not pressed the microphone "
                "button for this connection. A reachable service is not consent."
            ),
            warnings=tuple(warnings),
        )
    if spend_readable and spend_usd >= config.monthly_budget_usd:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_BUDGET_EXHAUSTED,
            reason=(
                "Realtime lane not armed: "
                + _budget_sentence(spend_usd=spend_usd, config=config, month=spend_month)
                + " Raise realtime.monthly_budget_usd in your realtime.yaml (or wait "
                "for the 1st of next month, UTC) to open a session. Safety-class "
                "narrations on a session that is already open are never gated by "
                "this ceiling."
            ),
            warnings=tuple(warnings),
        )
    if not transport_available:
        return RealtimeArmingDecision(
            armed=False,
            code=CODE_NO_TRANSPORT,
            reason=(
                "Realtime lane not armed: no transport is configured. R1 ships the "
                "in-process fake transport only; the live WebSocket transport is R1.5 "
                "and needs `websockets` plus a key."
            ),
            warnings=tuple(warnings),
        )
    return RealtimeArmingDecision(
        armed=True,
        code=CODE_ARMED,
        reason=(
            f"Realtime lane armed on {config.model} (voice={config.voice}); "
            "handshake token supplied and microphone gesture given."
        ),
        warnings=tuple(warnings),
    )


def _budget_sentence(*, spend_usd: float, config: RealtimeConfig, month: str) -> str:
    """The figure, the period, and the config source — in one sentence.

    Card R25 asks the refusal to name "the figure, the period, and how to raise
    it". Split out of the refusal so the same sentence can be asserted by test
    without matching on the surrounding advice, and so the panel and the log
    can never quote a different number from the one the gate refused on.
    """

    period = f" in {month}" if month else " this month"
    budget = float(config.monthly_budget_usd)
    # ONE precision for BOTH figures, chosen off the smaller of them. Two
    # decimals is right for a $25 ceiling and useless for a $0.001 one: the
    # live proof's first refusal read "an estimated $0.00 has reached the $0.00
    # ceiling", which names a figure the owner cannot act on and is the
    # "refusal reason silent" failure this card exists to prevent. Formatting
    # the two numbers independently would be worse still — "$0.01 has reached
    # the $0.0052 ceiling" reads like a bug.
    places = 2 if min(abs(spend_usd), abs(budget)) >= 0.10 else 4
    return (
        f"an estimated ${spend_usd:.{places}f}{period} has reached the "
        f"${budget:.{places}f} realtime.monthly_budget_usd ceiling "
        f"(config source: {config.source}; rates are ASSUMED, not billed)."
    )


def build_instructions(
    *,
    personality: str,
    reply_style: Sequence[str] = (),
    guardrails: str = GUARDRAILS,
) -> str:
    """Persona from the repo's own prompt library, plus ear-oriented rules."""

    parts = [personality.strip()]
    for line in reply_style:
        text = str(line).strip()
        if text:
            parts.append(f"- {text}")
    parts.append(guardrails)
    return "\n".join(part for part in parts if part)


class SinkLike(Protocol):
    """The part of ``SpeakerSink`` the playback bridge uses."""

    first_chunk_started_monotonic: float | None

    def begin_utterance(self) -> None: ...

    def enqueue(self, chunk: bytes, token: object = None) -> None: ...

    def interrupt(self) -> None: ...


class ToolHandlerLike(Protocol):
    """The tool broker, as the lane sees it (card R3, task_6).

    Three methods and no state the lane may read. ``session_events`` is sent
    immediately after ``session.update`` at every session open, rollover and
    reconnect, so the tool surface is re-declared exactly where the instructions
    are. ``handle`` must answer EVERY call and must never raise: an unanswered
    ``function_call`` wedges the provider's turn.

    ``note_response_provenance`` (card R11, design point 5) is told who asked
    for the response the call arrived in — ``"owner"`` or ``"system"`` — before
    every dispatch. A handler that does not implement it is treated as unable to
    enforce the system-initiated motion gate, and the lane refuses its calls
    itself for the duration of a system-initiated response; see
    :meth:`RealtimeLane._on_function_call`.
    """

    def session_events(self) -> Sequence[Any]: ...

    def handle(self, *, name: str, call_id: str, arguments: str) -> str: ...

    def note_response_provenance(self, provenance: str) -> None: ...


class LedgerLike(Protocol):
    """The part of ``ConversationMemory`` the lane writes through."""

    def write_realtime_turn(
        self,
        *,
        session_id: str | None,
        speaker: str,
        text: str,
        origin: str,
        provider_item_id: str | None = None,
    ) -> int: ...


class MonthToDateSpendLike(Protocol):
    """The four fields the lane reads off a month-to-date total (card R25).

    Structural rather than an import of
    :class:`parcel_robot.realtime.spend_ledger.MonthToDateSpend` so the lane
    keeps knowing nothing about money beyond "a number, and whether it is real".
    ``readable`` is the fail-open contract: False means the number is a floor of
    zero produced by a broken file, and the gate must let the session open.
    """

    month: str
    usd: float
    readable: bool
    note: str


class SpendLedgerLike(Protocol):
    """The part of ``SpendLedger`` the lane uses. Both methods must never raise.

    ``record`` is called from the pump thread (card R22's entire subject was an
    exception on that thread killing the crank) and ``month_to_date`` from the
    arming path and the narration gate.
    """

    def record(
        self, row: Mapping[str, object], *, session_id: str | None = None
    ) -> bool: ...

    def month_to_date(self) -> MonthToDateSpendLike: ...


def _never() -> bool:
    return False


@dataclass
class _ResponseState:
    """Bookkeeping for the one hosted response currently in flight."""

    response_id: str = ""
    item_id: str = ""
    playing: bool = False
    enqueued_ms: float = 0.0
    transcript_parts: list[str] = field(default_factory=list)

    @property
    def transcript(self) -> str:
        return "".join(self.transcript_parts)


class RealtimeLane:
    """One hosted session, its mouth, its ledger, and its failure handling."""

    def __init__(
        self,
        *,
        config: RealtimeConfig,
        instructions: str,
        transport_factory: Callable[[], Transport] | None = None,
        sink: SinkLike | None = None,
        sink_factory: Callable[[], SinkLike] | None = None,
        ingress: Callable[..., RealtimeTranscriptOutcome] | None = None,
        ledger: LedgerLike | None = None,
        memory_tail: Callable[[], Sequence[Mapping[str, str]]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        cost_log_path: Path | None = None,
        spend_ledger: SpendLedgerLike | None = None,
        duplex_output_active: Callable[[], bool] = _never,
        coalesce_ms: float = DEFAULT_COALESCE_MS,
        sample_rate_hz: int = PCM16_SAMPLE_RATE_HZ,
        session_id_factory: Callable[[], str] | None = None,
        summarize_hook: Callable[[str], str | None] | None = None,
        transcript_origin: str = "realtime",
        tool_handler: ToolHandlerLike | None = None,
        reconnect_backoff_s: float = DEFAULT_RECONNECT_BACKOFF_S,
        reconnect_backoff_max_s: float = DEFAULT_RECONNECT_BACKOFF_MAX_S,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        entry_timeout_s: float = DEFAULT_ENTRY_TIMEOUT_S,
        receipt_tools: Sequence[str] | None = None,
        answer_tools: Sequence[str] | None = None,
        result_beat_instruction: str | None = RESULT_BEAT_RULE,
        answer_beat_instruction: str | None = ANSWER_BEAT_RULE,
        repay_limit: int = DEFAULT_REPAY_LIMIT,
        item_trace_limit: int = DEFAULT_ITEM_TRACE_LIMIT,
        server_error_window: int = DEFAULT_SERVER_ERROR_WINDOW,
        on_idle_close: Callable[[float], None] | None = None,
        retention_sink: Callable[[str, Mapping[str, Any]], None] | None = None,
    ) -> None:
        self.config = config
        self.instructions = instructions
        self._transport_factory = transport_factory
        self._sink = sink
        # The sink is constructed here when the local synthesizer never loaded:
        # runtime.py only builds one under `if speech_stack.synthesizer is not
        # None`, and hosted playback must work with zero local speech models.
        self._sink_factory = sink_factory
        self._ingress = ingress
        self._ledger = ledger
        self._memory_tail = memory_tail
        self._clock = clock
        self._cost_log_path = cost_log_path
        #: Card R25. The DURABLE month-to-date spend, on disk, beside the
        #: recordings. ``None`` keeps every pre-R25 behaviour byte-for-byte —
        #: no ceiling is consulted and no narration is budget-gated — which is
        #: what every test that does not care about money gets by default. The
        #: lane still knows nothing about prices: it hands rows to this object
        #: and reads one number back.
        self._spend_ledger = spend_ledger
        self._duplex_output_active = duplex_output_active
        self._sample_rate_hz = int(sample_rate_hz)
        self._bytes_per_ms = (self._sample_rate_hz * 2) / 1000.0
        self._coalesce_bytes = max(1, int(coalesce_ms * self._bytes_per_ms))
        self._session_id_factory = session_id_factory or (lambda: f"rt_{uuid.uuid4().hex[:12]}")
        self._summarize_hook = summarize_hook
        self._transcript_origin = transcript_origin
        #: Card R3. ``None`` keeps R1's refuse-every-call stub byte-for-byte.
        self._tool_handler = tool_handler
        self._backoff_s = max(0.0, float(reconnect_backoff_s))
        self._backoff_max_s = max(self._backoff_s, float(reconnect_backoff_max_s))
        self._sleep = sleep
        self._jitter = jitter
        self._entry_timeout_s = max(0.0, float(entry_timeout_s))
        #: Card R6, Defect 2. Injectable so a build with a different tool surface
        #: states its own receipts rather than inheriting this module's guess.
        self._receipt_tools = frozenset(
            DEFAULT_RECEIPT_TOOLS if receipt_tools is None else (str(n) for n in receipt_tools)
        )
        #: Card R19, work item 2. Injectable for the same reason the receipts
        #: are, and applied with the opposite force: this set OUTRANKS the
        #: receipt set, so naming a tool here can only ever add speech.
        self._answer_tools = frozenset(
            DEFAULT_ANSWER_TOOLS if answer_tools is None else (str(n) for n in answer_tools)
        )
        self._result_beat_instruction = result_beat_instruction
        self._answer_beat_instruction = answer_beat_instruction
        self._repay_limit = max(0, int(repay_limit))
        #: Card R8. Bounds on the refused-item machinery; injectable so a test
        #: can prove the eviction without sending sixty-five items.
        self._item_trace_limit = max(1, int(item_trace_limit))
        self._server_error_window = max(1, int(server_error_window))
        #: Card R16. Told, after the fact, that the lane hung itself up and how
        #: long it had been quiet. The lane must not know what a microphone is —
        #: this is how the runtime learns to put the browser's mic button back to
        #: "Enable microphone" so the owner's next click re-opens rather than
        #: streaming into a session that is gone. A hook that raises is noted and
        #: swallowed: the hang-up has already happened.
        self._on_idle_close = on_idle_close
        #: Card R22, work item 5 — EV-1's open risk §10.3, closed. Where a
        #: :class:`RetainedEvent` goes. Called ``(type_name, fields)`` and
        #: wired by the runtime to the SESSION EVIDENCE LOG's sink, which is an
        #: unbounded on-disk JSONL stream. EV-1 named the alternative and
        #: refused it in writing: routing 44 ASR deltas per session through
        #: ``_note`` would put 44 more rows per session into the 100-slot panel
        #: ring, which is the exact resource that card exists to stop
        #: overflowing. ``None`` keeps the pre-R22 behaviour byte-for-byte — the
        #: frames are parsed, counted and dropped.
        self._retention_sink = retention_sink
        #: One lane, one socket, one thread at a time. Re-entrant because the
        #: watchdog reaches ``_reconnect`` from inside ``tick``/``pump``.
        self._lock = threading.RLock()

        self.transport: Transport | None = None
        self.session_id: str | None = None
        self.provider_session_id: str | None = None
        self.arming: RealtimeArmingDecision | None = None
        self.usage_rows: list[dict[str, object]] = []
        self.refused_tool_calls: list[str] = []
        #: Calls answered by a broker rather than the refusal stub, newest last.
        self.brokered_tool_calls: list[str] = []
        #: Owner turns typed into the panel in ``mode: text``.
        self.text_turns = 0
        #: Seconds actually waited before each reconnect, in order.
        self.backoff_waits: list[float] = []
        self.truncations: list[dict[str, object]] = []
        self.protocol_errors: list[str] = []
        #: Card R22, work item 1. Frames the lane UNDERSTOOD and then failed to
        #: handle, kept apart from ``protocol_errors`` on purpose: a protocol
        #: refusal is the provider saying something new, a dispatch failure is
        #: this process breaking. Counted by exception TYPE because §Safety-1 is
        #: a story about a type that was not on a list.
        self.dispatch_failures: list[str] = []
        self.dispatch_failure_count = 0
        self.dispatch_failure_types: dict[str, int] = {}
        #: Card R22, work item 4. Ledger writes that failed and were degraded to
        #: a note rather than being allowed to take the turn — and now the pump
        #: thread — down with them.
        self.ledger_failures = 0
        self.ledger_failure_types: dict[str, int] = {}
        self.last_ledger_failure: str | None = None
        #: Card R22, work item 5 (EV-1 §10.3). Retained ASR/boundary frames
        #: handed to the evidence log's own sink, by type, plus the handoffs
        #: that failed. Never routed through ``_note``: 44 deltas a session
        #: through the panel ring is the exact flood EV-1 exists to relieve.
        self.retained_events = 0
        self.retained_event_types: dict[str, int] = {}
        self.retention_failures = 0
        self.server_errors: list[ErrorEvent] = []
        self.events: list[str] = []
        self.reconnects = 0
        self.rollovers = 0
        self.stalls = 0
        self.disconnects = 0
        self.tail_items_injected = 0
        #: Facts the runtime asked the model to narrate, and the ones the floor
        #: gate refused. Counted so "narration spams the session" is a NUMBER a
        #: test can assert on rather than a judgement call.
        self.narrations = 0
        self.narrations_skipped = 0
        #: Card R16. Narrations offered to a lane that had already HUNG UP. A
        #: subset of ``narrations_skipped``, kept separately because it answers a
        #: different question: not "was the floor busy" but "is the robot talking
        #: to a session that no longer exists". The whisperer must never be the
        #: thing that re-opens a paid session, so this number is the cost of that
        #: rule, stated out loud. The always-band facts these carried still latch
        #: locally — the mission log, the event ring and every local watchdog are
        #: upstream of the lane and are untouched by a hang-up.
        self.narrations_skipped_closed = 0
        #: Card R25. The two halves of the cost-ceiling asymmetry, counted so it
        #: is a NUMBER on ``/api/state`` rather than a claim in a doc.
        #: ``narrations_skipped_budget`` is non-safety chatter this month's
        #: ceiling silenced on an already-open session (a subset of
        #: ``narrations_skipped``); ``narrations_over_budget`` is SAFETY-class
        #: facts that were spoken anyway. The second number rising while the
        #: first one does is the asymmetry working; the second one being
        #: permanently zero while the first climbs is the over-correction.
        self.narrations_skipped_budget = 0
        self.narrations_over_budget = 0
        #: Card R25. Spend-ledger appends this lane degraded to a note rather
        #: than letting them end a turn, beside ``ledger_failures`` for the
        #: conversation ledger. Kept apart because the two answer different
        #: questions: one loses a transcript, the other loses the ceiling.
        self.spend_ledger_failures = 0
        #: Card R8. Narrations the PROVIDER refused after the lane counted them.
        #: ``narrations`` has always meant "a narration frame left this process";
        #: until R8 nothing could tell you whether the provider kept it, and for
        #: the whole of R1-R7 the answer was no. This is the number that makes a
        #: counted-but-dropped narration diagnosable from ``/api/state``.
        self.narrations_refused = 0
        #: Card R8. Every conversation item the provider refused, newest last,
        #: attributed to the item that caused it (role, purpose, text). The
        #: aggregate the card asks for, with per-item detail where the provider
        #: echoed our ``event_id`` — which, live, it always does.
        self.refused_items: list[dict[str, object]] = []
        #: Card R8. Server refusals as records rather than typed events, appended
        #: in the same place as ``server_errors`` so the two cannot drift.
        self.server_error_records: list[dict[str, object]] = []
        #: Card R6, Defect 1. Turns the lane re-asked for after a reconnect that
        #: inherited an unanswered question, and the ones it refused to re-ask
        #: because the repay limit was reached. Both counted: an answer that
        #: arrives after a reconnect must be explainable from the snapshot.
        self.turn_repays = 0
        self.turn_repays_abandoned = 0
        #: Card R8, work item 3. Spoken turns the lane has started waiting on,
        #: and the repays that were fired for one. ``turn_repays`` stays the
        #: superset (every repay counts there, whatever armed it) so R6's
        #: counters keep meaning exactly what R6 said they mean.
        self.voice_turns_owed = 0
        self.voice_turn_repays = 0
        #: Card R6, Defect 2. Post-tool beats requested vs. deliberately left
        #: unrequested. "One beat per tool turn" is a NUMBER, not a judgement.
        self.tool_beats_requested = 0
        self.tool_beats_suppressed = 0
        #: Card R19, mechanism C. Beats held until the response that carried the
        #: call closed (which is all of them) and beats that died with a session
        #: before that happened. ``tool_beats_lost`` is the number an operator
        #: reads as "a refusal the owner was never told about".
        self.tool_beats_deferred = 0
        self.tool_beats_lost = 0
        self.tool_beats_refused = 0
        #: Frames the transport refused because it had already hung up. Counted
        #: rather than swallowed: a dropped frame is a turn that will never be
        #: answered, and it used to leave nothing behind but a note.
        self.dropped_sends = 0
        self.outcomes: list[RealtimeTranscriptOutcome] = []

        #: Items already ledgered by a barge-in truncation. A late
        #: ``transcript.done`` for one of these must not write a SECOND, longer
        #: robot row — the ledger records what was heard, not what was drafted.
        self._truncated_items: set[str] = set()
        self._response = _ResponseState()
        self._pcm = bytearray()
        self._expecting_server = False
        #: ``response.create`` frames sent whose ``response.done`` has not come
        #: back yet. A tool turn legitimately has two outstanding at once.
        self._responses_pending = 0
        #: True once the response currently open has emitted transcript text.
        #: Card R6, Defect 2: the pre-call announcement the provider co-emits
        #: with a ``function_call`` is the ONLY thing that can stand in for the
        #: post-result beat, so "did the model already speak in this response?"
        #: has to be a fact the lane knows rather than an assumption.
        self._spoke_this_response = False
        #: Card R19, mechanism B. WHAT it said, not merely that it said
        #: something. ``_spoke_this_response`` cannot tell "Okay, let me check
        #: how to get you there." from "It's at 90 percent" and live_run_1 is
        #: four minutes of what that costs. Kept beside the boolean rather than
        #: replacing it: the boolean is what R6's seeds S9/S10 pin and it still
        #: answers its own question ("did anything at all come out?") correctly.
        self._response_speech: list[str] = []
        #: Card R19, mechanism C. The beat whose ``response.create`` is up but
        #: unanswered, and the beat the provider refused and this lane still
        #: owes the owner. A refused beat is a refusal the owner never hears,
        #: and before R19 nothing in this lane could tell the two apart.
        self._beat_in_flight: dict[str, object] | None = None
        self._pending_beat: dict[str, object] | None = None
        #: Card R6, Defect 1. Repays since the last ``response.done``.
        self._repays_since_answer = 0
        #: Card R8, work item 3. True when the owner has SPOKEN a turn the
        #: provider has not answered yet. A server-VAD turn has no ``send_text``
        #: to arm the owed-turn accounting: the provider creates the response
        #: itself, so ``_responses_pending`` — which counts only the
        #: ``response.create`` frames this lane sent — stays at zero for the
        #: whole turn and a spoken sentence that died with the socket was never
        #: repaid (R6 does_not_prove, "No voice turn was repaid").
        #:
        #: Kept SEPARATE from ``_responses_pending`` rather than folded into it,
        #: which is the point R6's carry-forward called a design question. That
        #: counter has one invariant — it moves only for frames the transport
        #: accepted (``_send``) — and the watchdog, the repay, the beat
        #: accounting and four of R6's sixteen seeds all read it through that
        #: invariant. Incrementing it for a response nobody asked for would make
        #: it a count of two different things and would silently break every one
        #: of them. The repay reads BOTH and fires once.
        self._voice_turn_owed = False
        #: Card R8. ``event_id`` -> what that item was, for the frames still
        #: waiting to find out whether the provider kept them. Bounded by
        #: ``_item_trace_limit``, oldest evicted first.
        self._item_trace: dict[str, dict[str, str]] = {}
        self._item_seq = 0
        self._last_event_at = clock()
        self._session_started_at: float | None = None
        #: Card R16. When this session last did anything CONVERSATIONAL. Set at
        #: every session open and moved by exactly five events — an owner turn
        #: typed, the provider's VAD hearing the owner start or finish speaking,
        #: a narration the model actually took, and a response completing. It is
        #: deliberately NOT moved by ``send_audio``: an armed microphone in an
        #: empty room streams frames forever and is the single most expensive
        #: idle state there is, so "the mic is on" must not read as "someone is
        #: talking to me". Same shape of rule as R7's "connected is not
        #: listening" and FIX-A's "a reachable service is not consent".
        self._last_activity_at = clock()
        #: Card R16. Sessions this lane hung up for idleness, and how long the
        #: last one had been quiet. Counted so "the lane keeps hanging up on me"
        #: and "the lane never hangs up" are both numbers in ``/api/state``.
        self.idle_hang_ups = 0
        self.last_idle_seconds: float | None = None
        self._handshake_token: str | None = None
        self._mic_gesture = False
        self._audio_sent_this_session = 0
        #: Consecutive FAILURE reconnects. Reset by ``session.created`` — the
        #: provider's own acknowledgement that a session exists again.
        self._failed_reconnects = 0
        #: True between ``open_session`` and ``close``. The difference between
        #: "this lane has no session because nobody armed it" (leave it alone)
        #: and "this lane has no session because its socket died" (recover it).
        self._opened = False
        #: True for the whole of ``_reconnect``, backoff included.
        self._reconnecting = False
        #: Card R11, design point 5 — WHO ASKED FOR THE RESPONSE IN FLIGHT.
        #:
        #: The bench found a state injection firing a spurious
        #: ``navigate_to("picnic spot by the big oak")`` in 2/3 forced-response
        #: trials (``bench_navmodel.md`` §4, C1): motion initiated by a system
        #: item rather than by anything the owner said. The broker's
        #: utterance-scoped dedupe cannot see that — there IS no utterance — so
        #: the lane has to say where the response came from and the broker has
        #: to refuse motion when the answer is "from the robot itself".
        #:
        #: One field rather than a per-response map because the lane already
        #: serialises this: ``narrate_event`` refuses to fire unless the session
        #: is idle (nothing playing, nothing pending, no spoken turn owed), so a
        #: system-initiated response is the only response in flight for its whole
        #: life. It is reset to OWNER the moment the owner is heard from, and
        #: when the last outstanding response completes.
        self._response_provenance = RESPONSE_FROM_OWNER
        #: How many responses this lane started off a ``system`` item, and how
        #: many of them tried to move the body anyway.
        self.system_initiated_responses = 0
        self.system_initiated_tool_calls = 0

    # ------------------------------------------------------------ properties
    @property
    def active(self) -> bool:
        return self.transport is not None and not self.transport.closed

    @property
    def recovering(self) -> bool:
        """True while a reconnect is in flight, backoff wait included.

        ``active`` is False for that whole window — truthfully, there is no
        usable socket — and before R4-lite that was indistinguishable from
        "this lane has no session", which is what made a caller open a second,
        competing one. ``recovering`` is the difference.
        """

        return self._reconnecting

    @contextmanager
    def _entered(self, what: str) -> Iterator[None]:
        """Take the lane for one owner-facing operation, or refuse out loud.

        A bounded wait, never an unbounded one: the caller is usually an HTTP
        handler, and a panel that hangs forever is its own defect.
        """

        if not self._lock.acquire(timeout=self._entry_timeout_s):
            raise RealtimeLaneError(
                f"realtime lane is busy (recovering={self._reconnecting}); {what} "
                f"waited {self._entry_timeout_s:.1f}s and refused rather than open a "
                "competing session or accept a turn nobody would answer"
            )
        try:
            yield
        finally:
            self._lock.release()

    @property
    def playback_owned(self) -> bool:
        """True while the lane is the exclusive owner of the speaker."""

        return self._response.playing

    @property
    def enqueued_ms(self) -> float:
        return self._response.enqueued_ms

    # ------------------------------------------------------------- lifecycle
    def month_to_date_spend(self) -> MonthToDateSpendLike | None:
        """This month's durable estimated spend, or ``None`` with no ledger.

        Card R25. Never raises: a ledger whose read blows up is the same
        situation as a ledger that cannot be read, and both fail OPEN. The
        exception is counted so "the ceiling quietly stopped working" is a
        number rather than a silence.
        """

        ledger = self._spend_ledger
        if ledger is None:
            return None
        try:
            return ledger.month_to_date()
        except Exception as error:  # noqa: BLE001 - the ceiling may never brick the lane
            self.spend_ledger_failures += 1
            self._note(f"month-to-date spend unreadable ({type(error).__name__}: {error})")
            return None

    def _over_monthly_budget(self) -> bool:
        """True only when a READABLE ledger says the ceiling has been reached.

        The narration gate's half of card R25's asymmetry. Unreadable, absent
        or unwired ⇒ False: the same fail-open direction the arming gate takes,
        written once so the two cannot drift into disagreeing about what "over
        budget" means.
        """

        total = self.month_to_date_spend()
        if total is None or not total.readable:
            return False
        return float(total.usd) >= float(self.config.monthly_budget_usd)

    def arm(self, *, handshake_token: str | None, mic_gesture: bool) -> RealtimeArmingDecision:
        """Card R25: this is where the owner's monthly ceiling became real.

        For R1-R24 this method called the gate WITHOUT a spend figure, so the
        gate compared its ``0.0`` default against the configured budget and the
        documented ceiling never once fired. The number now comes from the
        durable on-disk ledger rather than from ``self.usage_rows``: that list
        is emptied by every process restart, and a ceiling that resets on reboot
        is not a ceiling.
        """

        total = self.month_to_date_spend()
        decision = decide_realtime_arming(
            config=self.config,
            handshake_token=handshake_token,
            mic_gesture=mic_gesture,
            transport_available=self._transport_factory is not None,
            spend_usd=0.0 if total is None else float(total.usd),
            # No ledger wired at all is NOT "unreadable": it is a lane nobody
            # asked to meter, and it arms exactly as it did before this card.
            spend_readable=True if total is None else bool(total.readable),
            spend_month="" if total is None else str(total.month),
            spend_note="" if total is None else str(total.note),
        )
        for warning in decision.warnings:
            self._note(warning)
        self.arming = decision
        return decision

    def open_session(
        self,
        *,
        handshake_token: str | None = None,
        mic_gesture: bool = False,
    ) -> str:
        """Arm, connect, send instructions, then inject the tail. In that order.

        The tail goes up BEFORE any audio append, and the ordering is asserted
        by test rather than assumed: mid-session history edits bust the prompt
        cache, and the cached-audio discount is the entire cost model.
        """

        with self._entered("open_session"):
            return self._open_locked(handshake_token=handshake_token, mic_gesture=mic_gesture)

    def ensure_session(
        self,
        *,
        handshake_token: str | None = None,
        mic_gesture: bool = False,
    ) -> str:
        """The session the next turn will land on. Never a SECOND, competing one.

        Card R4-lite, task_1 — Defect A. The caller that wants to submit a turn
        cannot ask ``active`` and then act on the answer: a reconnect makes
        ``active`` False for as long as its backoff lasts, and a caller that
        reads that flag from another thread concludes "no session" and opens
        its own. The lane then finishes its reconnect, replaces the transport,
        and the socket carrying the owner's turn is orphaned — open, unread,
        and about to be answered to nobody. The decision has to be taken while
        holding the lane, which is what this does.
        """

        with self._entered("ensure_session"):
            if self.active and self.session_id:
                return self.session_id
            return self._open_locked(handshake_token=handshake_token, mic_gesture=mic_gesture)

    def _open_locked(self, *, handshake_token: str | None, mic_gesture: bool) -> str:
        decision = self.arm(handshake_token=handshake_token, mic_gesture=mic_gesture)
        if not decision.armed:
            raise RealtimeLaneError(decision.reason)
        self._handshake_token = handshake_token
        self._mic_gesture = mic_gesture
        self.session_id = self._session_id_factory()
        self._opened = True
        self._connect()
        return self.session_id or ""

    def _connect(self) -> None:
        factory = self._transport_factory
        if factory is None:  # pragma: no cover - the arming gate refuses first
            raise RealtimeLaneError("realtime lane has no transport factory")
        previous = self.transport
        self.transport = factory()
        # One lane, one socket. The reconnect path used to leave the transport
        # it replaced open whenever anything else had already swapped one in,
        # and an orphaned socket is worse than a closed one: it is still billing
        # and it may be holding a turn whose answer nobody will ever read.
        if previous is not None and previous is not self.transport:
            try:
                previous.close()
            except OSError:  # pragma: no cover - defensive
                pass
        self._response = _ResponseState()
        self._pcm.clear()
        self._expecting_server = False
        self._responses_pending = 0
        self._spoke_this_response = False
        self._response_speech = []
        # Card R19, mechanism C. A beat still waiting for a ``response.done``
        # that will now never arrive dies HERE, out loud. It cannot be carried
        # onto the new socket: it names a ``function_call`` from a conversation
        # that no longer exists. Counted, and noted with the tool and the status
        # it was going to report, because the ones that get lost are exactly the
        # refusals — a beat is only ever pending because the call did not
        # simply succeed in silence.
        self._drop_pending_beat("the session it belonged to ended")
        # Card R8: the spoken turn owed on the socket that just died is not owed
        # by the NEW one — ``_reconnect`` reads it before this runs and repays it
        # explicitly, exactly as it does for ``_responses_pending``. Leaving it
        # set here would make every later reconnect repay the same sentence.
        self._voice_turn_owed = False
        # Card R11: a new socket has no response in flight, so nothing is
        # system-initiated on it. Left set, a narration that died with the old
        # session would refuse the owner's first request on the new one.
        self._response_provenance = RESPONSE_FROM_OWNER
        # Descriptors for items sent on the dead session. Their event ids can
        # never be echoed by the new one, so keeping them would only let a
        # coincidence attribute a fresh refusal to a stale item.
        self._item_trace.clear()
        self._audio_sent_this_session = 0
        now = self._clock()
        self._last_event_at = now
        self._session_started_at = now
        # Card R16. A brand-new socket gets the whole idle window, whether it was
        # opened by an owner gesture or by a reconnect: a session that has just
        # been rebuilt has had no chance to be talked to yet, and hanging it up
        # on the strength of the DEAD session's silence would make a stall
        # recovery indistinguishable from a hang-up.
        self._last_activity_at = now
        self._send(
            SessionUpdate(
                instructions=self.instructions,
                model=self.config.model,
                voice=self.config.voice,
            )
        )
        self._declare_tools()
        self._inject_tail()

    def _declare_tools(self) -> None:
        """Re-declare the broker's tool surface at every session boundary.

        Nothing is sent when no handler is wired, which is what makes the
        flag-off wire trace byte-identical to R1's.
        """

        handler = self._tool_handler
        if handler is None:
            return
        for event in handler.session_events():
            self._send(event)

    def _inject_tail(self) -> None:
        """Replay BOTH halves of the conversation into the new session.

        "Both halves" is new as of card R8 and was the whole point of it. The
        ``assistant`` rows were always selected here and always sent — and,
        since R1, always refused on the wire, because every non-``user`` item
        carried a content type the provider accepts for no role at all. Nothing
        in the lane noticed: the refusal came back as a generic ``error`` frame
        with no way to tell which item it was about, ``tail_items_injected``
        counted the attempt, and every session the product ever opened inherited
        the owner's sentences with the robot's answers missing from between them.

        See :data:`~parcel_robot.realtime.protocol.CONTENT_TYPE_BY_ROLE`.
        """

        self.tail_items_injected = 0
        if self._memory_tail is None:
            return
        for row in self._memory_tail():
            role = str(row.get("role", "")).strip()
            content = str(row.get("content", "")).strip()
            if role not in {"user", "assistant"} or not content:
                continue
            self._send_item(role=role, text=content, purpose=ITEM_PURPOSE_TAIL)
            self.tail_items_injected += 1

    def close(self) -> None:
        # Deliberately NOT under ``_entered``: teardown must never block on a
        # reconnect's backoff, and ``runtime.close`` calls this from a thread
        # that a stuck lane would otherwise hang. Clearing ``_opened`` FIRST is
        # what makes an in-flight reconnect abandon itself instead of opening a
        # fresh socket after the owner hung up — a resurrected socket bills.
        self._opened = False
        if self.transport is not None:
            try:
                self.transport.close()
            except OSError:  # pragma: no cover - defensive
                pass
        self.transport = None
        self._response = _ResponseState()
        self._pcm.clear()
        self._expecting_server = False
        self._responses_pending = 0
        self._spoke_this_response = False
        self._response_speech = []
        self._drop_pending_beat("the lane hung up")
        self._repays_since_answer = 0
        self._voice_turn_owed = False
        self._response_provenance = RESPONSE_FROM_OWNER
        self._item_trace.clear()
        self._session_started_at = None

    # ------------------------------------------------------------------ relay
    def send_audio(self, pcm: bytes) -> None:
        """Owner microphone frames going up. Requires an open session."""

        with self._entered("send_audio"):
            if not self.active:
                raise RealtimeLaneError("realtime lane has no open session")
            if not pcm:
                return
            self._send(InputAudioBufferAppend(audio=bytes(pcm)))
            self._audio_sent_this_session += 1
            # From here the provider owes us something. Silence past
            # stall_timeout_s is the watchdog's trigger; without this flag a
            # dead session looks exactly like an idle one.
            self._arm_watchdog()

    def send_text(self, text: str) -> str:
        """Owner TEXT going up (``mode: text``), through the same ingress.

        The manual-testing path: no microphone, no gateway, no speaker. The
        typed sentence takes exactly the route a hosted transcript takes —
        restricted ingress first (so a typed "stop" latches the local emergency
        stop before the cloud is even asked), then the conversation item, then
        an explicit ``response.create`` because nothing else will trigger one
        without server VAD.

        Ordering is deliberate: the owner's line is created BEFORE the ingress
        runs, so the robot's own factual report ("[robot] executed …") lands
        after the sentence it is about rather than before it.

        Every frame here is ``required``: a turn whose frames were quietly
        dropped by a closed socket is the exact shape of the live incident —
        202 to the panel, a row in the ledger, an advanced utterance sequence,
        and silence forever. A dropped owner turn now raises.
        """

        with self._entered("send_text"):
            if not self.active:
                raise RealtimeLaneError("realtime lane has no open session")
            clean = " ".join(str(text).split())
            if not clean:
                raise RealtimeLaneError("realtime lane refuses empty owner text")
            self._send_item(
                role="user", text=clean, purpose=ITEM_PURPOSE_OWNER_TURN, required=True
            )
            self.text_turns += 1
            # Card R16. The owner typed: this session is being used.
            self._mark_activity("the owner typed a turn")
            if self._ingress is None:
                self._write_ledger(SPEAKER_OWNER, clean, item_id=None)
            else:
                try:
                    outcome = self._ingress(clean, item_id=None, session_id=self.session_id)
                except (RuntimeError, TypeError, ValueError) as error:
                    self._note(f"ingress refused {clean!r}: {error}")
                    self._write_ledger(SPEAKER_OWNER, clean, item_id=None)
                else:
                    self.outcomes.append(outcome)
                    narration = outcome.narration()
                    if narration:
                        self._send_item(
                            role="system",
                            text=narration,
                            purpose=ITEM_PURPOSE_ACTION_REPORT,
                        )
            # A NEW question gets its own repay budget (card R6, Defect 1): the
            # limit exists to stop ONE poisoned turn being re-asked forever, and
            # inheriting a spent budget would make the next turn unrepayable for
            # a reason that has nothing to do with it.
            self._repays_since_answer = 0
            # Card R11. The owner typed this, so the response it produces MAY
            # move the body. Stated positively rather than relying on the field
            # already being ``owner``: a narration that raced this turn would
            # otherwise leave the owner's own request refused.
            self._response_provenance = RESPONSE_FROM_OWNER
            # ``_send`` arms the watchdog for every response.create, so a turn
            # that goes up is a turn the watchdog is already watching.
            self._send(ResponseCreate(), required=True)
            return clean

    def narrate_event(self, text: str, *, critical: bool = False) -> bool:
        """Tell the model one FACT the robot's own systems reported.

        Card R4-lite, task_1 — Defect B.3. The design's §4 defer/rejoin applied
        to R4-lite: a mission that ends while the owner is standing there should
        be SAID, not left to a log nobody is reading. It takes the same door a
        post-hoc action report takes — a ``system`` conversation item plus a
        ``response.create`` — so the model narrates a fact rather than deciding
        anything, exactly as ``GUARDRAILS`` requires.

        Floor-gated, and returns False rather than raising when the floor is
        taken. FOUR noes: no session; a hosted response is playing (the model
        has the mouth); a response is already outstanding (the owner asked
        something and has not been answered yet — the robot does not talk over
        its own pending answer); or — card R8 — the owner has SPOKEN a turn the
        provider has not answered yet, which is the same rule applied to the
        half of the conversation ``_responses_pending`` could not see.
        ``narrations`` counts what got through, so a seed that tries to narrate
        per tick is visible as a number.

        WHAT ``True`` MEANS, EXACTLY (card R8, work item 2)
        --------------------------------------------------
        It means the frame left this process, and no more than that. It has
        never meant the provider kept the item, and until R8 the provider kept
        NONE of them: the ``system`` item carried a content type the API
        refuses, so the fact was dropped, the follow-up response was about
        nothing, and ``narrations`` counted it anyway (R6 probe 3, decisive).
        A refusal is asynchronous — it arrives on a later frame, long after this
        method has returned — so no boolean returned here can carry it.

        What CAN carry it, and now does: the item goes up tagged with an
        ``event_id``, the provider echoes that id on any refusal, and
        ``_on_server_error`` turns the echo back into "the narration you counted
        was dropped". Read ``narrations_refused`` beside ``narrations`` in the
        snapshot; the two agreeing is what "the narration was heard" looks like
        from ``/api/state``.

        ``critical`` — THE COST-CEILING ASYMMETRY (card R25, work item 4)
        ----------------------------------------------------------------
        A FIFTH no, and the only one a caller can be exempt from: once this
        month's durable estimated spend has reached ``monthly_budget_usd``, a
        non-critical robot-initiated fact is no longer worth a billed
        ``response.create``. Battery state, a pace mismatch, a rejected voice —
        those wait for next month or for a raised ceiling.

        SAFETY-class facts do not wait. ``critical=True`` — the caller passes
        it for exactly ``whisperer.CRITICAL_KINDS``: the emergency latch and its
        clear, a refusal of the owner's own command, a mission terminal — spends
        past the ceiling and is counted in ``narrations_over_budget``. This is
        the same asymmetry those classes already have against the whisperer's
        ``max_updates_per_minute``, for the same reason C's bench measured
        disqualifyingly: a robot that will not say "I have stopped" because of a
        money knob is the failure the knob was supposed to prevent. Tenths of a
        cent per fact is not a budget question.

        Note the direction of the two gates. The ceiling REFUSES TO OPEN a new
        session (``decide_realtime_arming``) but never hangs up an open one: the
        owner is mid-conversation and being cut off mid-sentence over a
        rounding error is worse than the overshoot, which is bounded by
        ``session_max_s`` anyway. What it does to an open session is exactly
        this — it stops the ROBOT from starting billed exchanges the owner did
        not ask for, while leaving every turn the owner does ask for alone.

        With no spend ledger wired (``spend_ledger=None``) this gate never
        fires, and the method behaves exactly as it did before card R25.
        """

        clean = " ".join(str(text).split())
        if not clean:
            return False
        if not self._lock.acquire(blocking=False):
            # The lane is busy with a turn or a reconnect. A narration is never
            # worth waiting for; the mission log has the fact either way.
            self.narrations_skipped += 1
            return False
        try:
            if not self.active:
                # Card R16, work item 3. The lane has hung up (or never opened).
                # A narration is a SKIP here and can never be anything else: the
                # whisperer must not be able to re-open a paid session the owner
                # is not part of, or the hang-up would only ever last until the
                # robot next noticed something about itself. Counted twice — in
                # the general skip counter and in its own — so an operator can
                # see how much the robot wanted to say while nobody was there.
                self.narrations_skipped += 1
                self.narrations_skipped_closed += 1
                self._note(
                    f"narration dropped into a closed lane (the session hung up after "
                    f"{'?' if self.last_idle_seconds is None else f'{self.last_idle_seconds:.0f}s'} "
                    f"idle): {clean}"
                )
                return False
            if self._response.playing or self._responses_pending > 0 or self._voice_turn_owed:
                self.narrations_skipped += 1
                return False
            # Card R25. The ceiling, and the one class of fact that outranks it.
            # Checked LAST of the noes so the cheaper, session-shaped refusals
            # above still take precedence: a narration the floor gate would have
            # dropped anyway must not be attributed to the owner's budget.
            if self._over_monthly_budget():
                if not critical:
                    self.narrations_skipped += 1
                    self.narrations_skipped_budget += 1
                    self._note(
                        "narration held back by this month's realtime.monthly_budget_usd "
                        f"ceiling (${self.config.monthly_budget_usd:.2f}); safety facts "
                        f"are not held back: {clean}"
                    )
                    return False
                self.narrations_over_budget += 1
                self._note(
                    "safety narration spent PAST this month's "
                    f"${self.config.monthly_budget_usd:.2f} ceiling, as designed: {clean}"
                )
            self._send_item(role="system", text=clean, purpose=ITEM_PURPOSE_NARRATION)
            # Card R11, design point 5. THE TAG, set BEFORE the frame goes up:
            # the provider can answer faster than this method returns, and a
            # ``function_call`` belonging to this response must never find the
            # lane still claiming the owner asked for it.
            self._response_provenance = RESPONSE_FROM_SYSTEM
            self.system_initiated_responses += 1
            self._send(ResponseCreate())
            self.narrations += 1
            # Card R16. A narration the model TOOK is traffic on this session and
            # holds the idle clock open — the card's own definition of idle is
            # "no owner turn, no narration, no pending response". A narration the
            # floor gate refused above does not, because nothing went up.
            self._mark_activity("the robot narrated a fact to the model")
            self._note(f"narrated to the model: {clean}")
            return True
        finally:
            self._lock.release()

    def pump(self) -> int:
        """Drain and dispatch every pending server frame. Returns the count.

        A non-blocking acquire: the driver runs this 20 times a second, and if
        the panel's thread is mid-turn the right answer is "nothing this pass",
        not a queue of pump calls waiting on each other.
        """

        if not self._lock.acquire(blocking=False):
            return 0
        try:
            return self._pump_locked()
        finally:
            self._lock.release()

    def _pump_locked(self) -> int:
        """Drain the socket, dispatching each frame behind its own firewall.

        **Card R22, work item 1.** ``_dispatch`` used to run bare. Everything
        downstream of it rides this one call — the ledger write (raw sqlite),
        the sink, the broker, the ingress, the barge-in arithmetic — and any
        exception from any of them left this method, left ``pump()``, and (until
        R22's driver firewall) killed the pump thread outright. The refuter's
        MRO walk on ``sqlite3.Error`` is the reason this is a broad catch and
        not one more type list: the next blindspot would be the next type
        nobody thought to name.

        The frame is COUNTED as handled either way. A frame that was received,
        parsed and then blew up in dispatch is not a frame that failed to
        arrive, and pretending otherwise would make ``handled`` lie to the
        driver about whether the socket had traffic on it.
        """

        if self.transport is None:
            return 0
        handled = 0
        while True:
            try:
                frame = self.transport.receive()
            except TransportClosed:
                self._on_disconnect()
                return handled
            if frame is None:
                return handled
            self._last_event_at = self._clock()
            handled += 1
            try:
                event = parse_server_event(frame)
            except RealtimeProtocolError as error:
                # Fail closed and LOUD-in-the-record: an unrecognized frame is
                # never treated as "nothing happened". The session survives —
                # dropping the conversation because the provider shipped a new
                # event type would be a worse failure than ignoring one frame.
                self.protocol_errors.append(str(error))
                self._note(f"protocol refusal: {error}")
                continue
            try:
                self._dispatch(event)
            except Exception as error:  # noqa: BLE001 - see the docstring above
                self._record_dispatch_failure(event, error)

    def tick(self) -> str | None:
        """Idle hang-up + rollover + watchdog. Returns what the lane DID.

        Three of the four answers name a reconnect (``rollover``, ``stall``,
        ``disconnect``); :data:`REASON_IDLE_HANG_UP` names the one that is not a
        reconnect at all — the session was closed and no new one was opened.
        """

        if not self._lock.acquire(blocking=False):
            return None
        try:
            return self._tick_locked()
        finally:
            self._lock.release()

    def _tick_locked(self) -> str | None:
        if not self.active:
            # An ARMED lane with no usable socket is not idle, it is deaf. The
            # watchdog is the only thing in the product that reconnects, so
            # returning None here is how such a lane stayed deaf forever — the
            # transport was gone, nothing was pumping it, and no counter moved.
            # An unarmed lane is genuinely idle and is left alone.
            if self._opened and not self._reconnecting and self._transport_factory is not None:
                self._on_disconnect()
                return "disconnect"
            return None
        now = self._clock()
        # Card R16, work items 1 and 2, AND THE ORDER IS THE WHOLE OF ITEM 2.
        # A rollover RENEWS a session: it closes the socket and immediately opens
        # a paid one, re-sends the instructions and replays the tail. Asking "is
        # anyone here?" first is what makes an idle session at its 60-minute cap
        # hang up instead — which is precisely the seven rows the owner woke up
        # to (06:23 → 12:23, one renewal an hour, nobody talking). Swap these two
        # blocks and F5 comes straight back; there is a seed for exactly that.
        idle_for = self._idle_due(now)
        if idle_for is not None:
            return self._idle_hang_up(idle_for)
        started = self._session_started_at
        if started is not None and (now - started) >= self.config.session_max_s:
            return self._rollover(now)
        if self._expecting_server and (now - self._last_event_at) > self.config.stall_timeout_s:
            self.stalls += 1
            self._note(
                f"watchdog: no server event for {now - self._last_event_at:.1f}s "
                f"while a response was expected (limit {self.config.stall_timeout_s:.1f}s)"
            )
            self._reconnect("stall")
            return "stall"
        return None

    # ------------------------------------------------------- the idle hang-up
    def _mark_activity(self, why: str) -> None:
        """This session was just USED. Card R16.

        Five callers and no more, each of them a thing a person would recognise
        as the conversation continuing: the owner typed, the provider's VAD heard
        the owner start speaking, it heard them finish (or the words came back
        transcribed), the model took a narration, or a response completed.
        ``_connect`` is the sixth place the clock moves and sets the field
        directly, because it stamps all three of this session's clocks at once.

        Every other frame on the wire — a session.created, an error, a protocol
        event, and above all a microphone frame — leaves the clock exactly where
        it was.
        """

        self._last_activity_at = self._clock()
        del why  # named at every call site so the reason survives review

    def _idle_seconds(self, now: float) -> float | None:
        """How long this session has been unused, or ``None`` if it is BUSY.

        ``None`` is the fail-safe answer and it is returned for four states, any
        one of which means hanging up would destroy work in flight:

        * there is no live socket — there is nothing to hang up, and the "deaf
          lane" arm of ``_tick_locked`` above already owns that case;
        * a hosted response is PLAYING — the owner is listening to the robot
          right now;
        * a ``response.create`` this lane sent is outstanding (R6's
          ``_responses_pending``) — the provider owes an answer, and the stall
          watchdog, not this, is what bounds that wait;
        * a SPOKEN turn is owed (R8's ``_voice_turn_owed``) — the same rule for
          the half of the conversation ``_responses_pending`` cannot see.

        The last two are load-bearing beyond politeness: closing a session with
        an unanswered turn on it would throw the turn away silently, and the
        repay path that exists to rescue it (``_repay_turn``) only ever runs on a
        RECONNECT. An idle hang-up must therefore never be able to race one.
        """

        if not self.active:
            return None
        if self._response.playing or self._responses_pending > 0 or self._voice_turn_owed:
            return None
        return max(0.0, now - self._last_activity_at)

    def _idle_due(self, now: float) -> float | None:
        """Seconds of silence when the lane should hang up, else ``None``.

        Card P0-B, deliverable 3. ``idle_close_after_s: 0`` means NEVER, and it
        has to be answered here rather than in the comparison below: ``idle_for
        < 0.0`` is false for every idle duration there is, so a zero that fell
        through to the arithmetic would hang the session up on its first idle
        tick — the exact opposite of what the operator wrote. The sentinel's
        meaning lives on the config object (``idle_close_enabled``) so this file
        and the loader cannot drift apart about what zero is.
        """

        if not self.config.idle_close_enabled:
            return None
        idle_for = self._idle_seconds(now)
        if idle_for is None or idle_for < self.config.idle_close_after_s:
            return None
        return idle_for

    def _idle_hang_up(self, idle_for: float) -> str:
        """Close cleanly, say so in the ledger, and open nothing. Card R16.

        The order matters. The ledger row goes first, because ``_write_ledger``
        stamps ``self.session_id`` and the row belongs to the session that is
        ending. ``close()`` then does exactly what the owner hanging up does —
        including clearing ``_opened``, which is what stops ``_tick_locked``'s
        deaf-lane arm from resurrecting the socket on the very next tick. Only
        then is the runtime told, so a hook that raises cannot leave the lane
        half-closed.

        Nothing here reconnects, repays or summarizes. The next owner gesture
        opens a session the ordinary way — ``ensure_session`` → ``_open_locked``
        → a new id, the instructions, the memory tail — which is why the
        conversation survives a hang-up even though the socket does not.
        """

        self.idle_hang_ups += 1
        self.last_idle_seconds = round(float(idle_for), 3)
        self._write_ledger(
            SPEAKER_SYSTEM,
            f"{IDLE_LEDGER_PREFIX} {idle_for:.0f}s] no owner turn, no narration and "
            "nothing outstanding; the session was closed rather than renewed. The next "
            "thing you say opens a fresh one with the same memory.",
            item_id=None,
        )
        self._note(
            f"idle hang-up: nothing conversational for {idle_for:.1f}s "
            f"(limit {self.config.idle_close_after_s:.1f}s); closing session "
            f"{self.session_id} rather than keeping it open"
        )
        self.close()
        self._notify_idle_close(idle_for)
        return REASON_IDLE_HANG_UP

    def _notify_idle_close(self, idle_for: float) -> None:
        """Tell whoever wired us that the lane hung up. Never raises."""

        hook = self._on_idle_close
        if hook is None:
            return
        try:
            hook(float(idle_for))
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._note(f"idle-close hook failed: {error}")

    # -------------------------------------------------------------- dispatch
    def _dispatch(self, event: ServerEvent) -> None:
        if isinstance(event, SessionCreated):
            self.provider_session_id = event.session_id
            # The provider says a session exists: the backoff ladder has done
            # its job and starts again from the bottom. Resetting on anything
            # weaker (a local connect() returning) would defeat the ladder,
            # because a flapping provider always lets the socket open.
            self._failed_reconnects = 0
            self._note(f"session created: {event.session_id}")
            return
        if isinstance(event, SpeechStarted):
            # Card R16. Server VAD heard the owner START talking. This is the
            # first moment in a spoken turn at which anything distinguishes a
            # person from an open microphone, and it is therefore the first
            # moment the idle clock may be reset — long before ``speech_stopped``
            # closes the utterance, so a sentence that runs past the threshold is
            # never hung up on midway.
            self._mark_activity("the provider's VAD heard the owner start speaking")
            self._on_speech_started()
            return
        if isinstance(event, SpeechStopped):
            # Card R8. Server VAD has closed the owner's utterance, which is the
            # moment the provider takes on the obligation to answer it. Until
            # this line the frame was a documented no-op and a spoken turn was
            # owed by nobody the lane could name.
            self._arm_voice_turn("server VAD closed the owner's utterance")
            return
        if isinstance(event, InputTranscriptionCompleted):
            # Belt and braces on the same turn: transcription can complete on a
            # session where the ``speech_stopped`` frame was dropped by a full
            # inbound buffer. ``_arm_voice_turn`` de-duplicates, so the pair
            # arms ONE owed turn rather than two.
            self._arm_voice_turn("the owner's words were transcribed")
            self._on_owner_transcript(event)
            return
        if isinstance(event, OutputTranscriptDelta):
            self._response.transcript_parts.append(event.delta)
            if event.delta.strip():
                self._spoke_this_response = True
                # Card R19. Deltas are the only speech record in text mode and
                # they arrive before ``transcript.done``, which for a barged-in
                # reply may never arrive at all. Whatever the owner heard is in
                # here by the time the ``function_call`` lands.
                self._response_speech.append(event.delta)
            return
        if isinstance(event, OutputTranscriptDone):
            self._on_robot_transcript(event)
            return
        if isinstance(event, OutputAudioDelta):
            self._on_audio(event)
            return
        if isinstance(event, OutputAudioDone):
            self._flush_audio(final=True)
            return
        if isinstance(event, FunctionCallArgumentsDone):
            self._on_function_call(event)
            return
        if isinstance(event, ResponseDone):
            self._on_response_done(event)
            return
        if isinstance(event, ErrorEvent):
            self._on_server_error(event)
            return
        if isinstance(event, RetainedEvent):
            # Card R22, work item 5 — EV-1 §10.3, the last hole between the
            # typed codec and the evidence stream. EV-1 taught the codec to KEEP
            # these payloads (the 88 ASR frames of live_run_1, the only surviving
            # trace of how the owner's words were transcribed) and then had
            # nowhere to put them: its card scoped it to ``protocol.py`` and
            # listed this file under MUST NOT TOUCH, so they were parsed and
            # dropped. This is the three lines that closes it.
            #
            # Still a no-op for the CONVERSATION: nothing here marks activity,
            # arms a turn, touches the sink or writes the ledger. The lane's
            # behaviour is byte-identical; only the record survives.
            self._retain(event)
            return

    def _retain(self, event: RetainedEvent) -> None:
        """Hand one retained frame to the evidence log. Card R22, work item 5.

        Never raises and never notes. A retention sink that breaks costs a
        counter, because these frames are evidence about the session and the
        session must not be able to die of its own bookkeeping.
        """

        name = str(event.type_name)
        self.retained_events += 1
        self.retained_event_types[name] = self.retained_event_types.get(name, 0) + 1
        sink = self._retention_sink
        if sink is None:
            return
        try:
            sink(name, dict(event.fields))
        except Exception:  # noqa: BLE001 - evidence never kills a conversation
            self.retention_failures += 1

    def _record_dispatch_failure(self, event: ServerEvent, error: Exception) -> None:
        """One understood frame that blew up while being handled. Card R22.

        Bounded like every other list on this object, counted exactly, and
        broken out by exception type so the next §Safety-1 is a number somebody
        can read off ``/api/state`` instead of a thread that is simply gone.
        """

        name = type(error).__name__
        label = type(event).__name__
        message = f"dispatch failed for {label}: {name}: {error}"
        self.dispatch_failure_count += 1
        self.dispatch_failure_types[name] = self.dispatch_failure_types.get(name, 0) + 1
        self.dispatch_failures.append(message)
        if len(self.dispatch_failures) > DISPATCH_FAILURE_LOG_LIMIT:
            del self.dispatch_failures[:-DISPATCH_FAILURE_LOG_LIMIT]
        self._note(message)

    # ------------------------------------------------------- refused by the provider
    def _on_server_error(self, event: ErrorEvent) -> None:
        """Record a refusal, and say WHAT it cost when the provider tells us.

        Card R8, work item 2. Before this the lane appended the typed event to a
        list nothing rendered and wrote a note nothing read, so "the provider
        refused an item" and "nothing happened" looked identical from
        ``/api/state`` — which is how a narration channel stayed broken from R1
        to R7 while ``narrations`` climbed.

        Per-item attribution turned out to need no protocol surgery at all: the
        item goes up carrying an ``event_id``, and the provider echoes it inside
        the error (``error.event_id``, verified live on all six refusals of the
        R8 content-type probe). So a refusal names its own item, and a refusal
        this lane cannot attribute — an error about a session frame, a rate
        limit, anything whose id we never sent — still lands in the aggregate
        rather than being dropped for want of a match.
        """

        self.server_errors.append(event)
        item = self._item_trace.pop(event.event_id, None) if event.event_id else None
        record: dict[str, object] = {"code": event.code, "message": event.message}
        if str(event.code).strip() == CODE_RESPONSE_ALREADY_ACTIVE:
            # Card R19, mechanism C. A ``response.create`` the provider would not
            # open. It is not an ITEM refusal, so R8's event-id trace has nothing
            # for it and before R19 it fell into the aggregate below and was
            # forgotten — with the beat it was carrying.
            self._beat_refused_by_provider(event.message)
        if item is None:
            self.server_error_records.append(record)
            self._note(f"server error {event.code}: {event.message}")
            return
        purpose = item["purpose"]
        record["item"] = {
            "role": item["role"],
            "purpose": purpose,
            "text": item["text"],
        }
        self.server_error_records.append(record)
        self.refused_items.append(dict(record))
        if purpose == ITEM_PURPOSE_NARRATION:
            # The counter that makes R6's live finding impossible to repeat
            # silently: ``narrations`` says a fact went up, this says the
            # provider threw it away, and a gap between them is the defect.
            self.narrations_refused += 1
        self._note(
            f"server error {event.code}: {event.message} — the provider REFUSED our "
            f"{item['role']} {purpose}: {item['text']!r}"
        )

    def _arm_voice_turn(self, why: str) -> None:
        """A SPOKEN turn is owed an answer. Card R8, work item 3.

        ``send_text`` arms the owed-turn accounting by sending a
        ``response.create`` of its own; a server-VAD turn never does, because the
        provider creates that response itself. So for the whole of ``mode:
        audio`` the lane's bookkeeping said nothing was outstanding while the
        owner stood there waiting, and a socket that died mid-answer took the
        spoken sentence with it, unrepaid and uncounted (R6 does_not_prove, "No
        voice turn was repaid"; R6 open risk 3).

        Three things happen here and each is deliberate:

        * **the repay budget resets, every time.** Exactly what ``send_text``
          does for a typed turn (card R6 seed S14): one sentence the provider
          chokes on must not spend the budget for everything the owner says
          afterwards. It is outside the de-duplication guard on purpose — the
          guard is about not counting one turn twice, not about withholding a
          fresh turn's budget;
        * **the flag and the counter move once per turn.** ``speech_stopped``
          and the transcription that follows describe ONE utterance. Counting
          both would make ``voice_turns_owed`` claim the owner said twice as
          much as they did, and would make one unanswered sentence look like two;
        * **the watchdog's patience clock starts here** — at the end of the
          owner's speech, which is when the provider actually became late. Same
          rule as ``_arm_watchdog`` states for every other request (card R6,
          Defect 3): the clock measures OUR wait, never the provider's last
          frame.
        """

        self._repays_since_answer = 0
        # Card R11. The owner SPOKE, so whatever the provider answers next is
        # the owner's response and may move the body. Set outside the
        # de-duplication guard for the same reason the repay budget is: this is
        # about who is talking, not about counting the turn twice.
        self._response_provenance = RESPONSE_FROM_OWNER
        # Card R16, and outside the guard for the same reason again: the idle
        # clock is about WHEN the owner last spoke, not about how many events
        # described the one utterance.
        self._mark_activity(why)
        if self._voice_turn_owed:
            return
        self._voice_turn_owed = True
        self.voice_turns_owed += 1
        self._arm_watchdog()
        self._note(f"a spoken turn is owed an answer: {why}")

    # -------------------------------------------------------- playback bridge
    def assert_sink_free(self, claimant: str = "realtime lane") -> None:
        """Refuse to share the mouth. Called before every claim, both ways.

        ``SpeakerSink`` is an ordered queue with no notion of who filled it: two
        concurrent enqueuers interleave sentences. ``speak_system``'s busy check
        cannot see hosted playback, so the rule is stated here and asserted.
        """

        if self._duplex_output_active():
            raise SinkOwnershipError(
                f"{claimant} may not enqueue while a DuplexVoiceSession output is live; "
                "the sink is an ordered queue and the two would interleave"
            )

    def assert_lane_not_speaking(self, claimant: str = "duplex voice session") -> None:
        """The other direction of the same rule, for the local output lane."""

        if self._response.playing:
            raise SinkOwnershipError(
                f"{claimant} may not enqueue while the realtime lane owns the sink"
            )

    def _begin_response(self, response_id: str, item_id: str) -> None:
        self.assert_sink_free()
        sink = self._require_sink()
        # The sink NEVER re-arms on enqueue: after any interrupt() every later
        # chunk is dropped until begin_utterance() clears the latch. A hosted
        # reply that followed a barge-in would otherwise be silent.
        sink.begin_utterance()
        self._response = _ResponseState(response_id=response_id, item_id=item_id, playing=True)
        self._pcm.clear()

    def _on_audio(self, event: OutputAudioDelta) -> None:
        if not self._response.playing or self._response.response_id != event.response_id:
            self._begin_response(event.response_id, event.item_id)
        if not self._response.item_id:
            self._response.item_id = event.item_id
        self._pcm.extend(event.audio)
        while len(self._pcm) >= self._coalesce_bytes:
            self._emit_audio(self._coalesce_bytes)

    def _flush_audio(self, *, final: bool = False) -> None:
        if not self._pcm:
            return
        if final or len(self._pcm) >= self._coalesce_bytes:
            self._emit_audio(len(self._pcm))

    def _emit_audio(self, size: int) -> None:
        chunk = bytes(self._pcm[:size])
        del self._pcm[:size]
        if not chunk:
            return
        self.assert_sink_free()
        sink = self._require_sink()
        # WAV-wrapped, with the rate stated. SpeakerSink._decode reads the rate
        # from the first RIFF header and otherwise keeps the last one it saw
        # (default 16 kHz), so raw 24 kHz PCM would play ~50% slow.
        sink.enqueue(pcm16_wav(chunk, sample_rate_hz=self._sample_rate_hz))
        self._response.enqueued_ms += len(chunk) / self._bytes_per_ms

    def _require_sink(self) -> SinkLike:
        if self._sink is None:
            if self._sink_factory is None:
                raise RealtimeLaneError(
                    "realtime lane has no speaker sink and no factory to build one"
                )
            self._sink = self._sink_factory()
        return self._sink

    def played_ms(self) -> float:
        """Milliseconds the SINK actually started playing, not what we queued.

        Anchored to ``first_chunk_started_monotonic`` — the speaker worker's own
        clock — and clamped by what was enqueued, because a truncate that
        overstates what the owner heard makes the provider's transcript lie in
        the ledger's favour.
        """

        if self._sink is None:
            return 0.0
        started = getattr(self._sink, "first_chunk_started_monotonic", None)
        if started is None:
            return 0.0
        elapsed_ms = max(0.0, (self._clock() - float(started)) * 1000.0)
        return min(self._response.enqueued_ms, elapsed_ms)

    # -------------------------------------------------------------- barge-in
    def _on_speech_started(self) -> None:
        if not self._response.playing:
            return
        played = self.played_ms()
        sink = self._sink
        if sink is not None:
            sink.interrupt()
        self._send(ResponseCancel(response_id=self._response.response_id or None))
        if self._response.item_id:
            self._send(
                ConversationItemTruncate(
                    item_id=self._response.item_id,
                    audio_end_ms=int(played),
                )
            )
        self.truncations.append(
            {
                "item_id": self._response.item_id,
                "audio_end_ms": int(played),
                "enqueued_ms": round(self._response.enqueued_ms, 3),
            }
        )
        heard = self._response.transcript
        if self._response.item_id:
            self._truncated_items.add(self._response.item_id)
        if heard:
            self._write_ledger(
                SPEAKER_ROBOT,
                f"{heard} [interrupted after {int(played)} ms]",
                item_id=self._response.item_id,
            )
        self._response.playing = False
        self._pcm.clear()
        self._note(f"barge-in: cancelled {self._response.response_id!r} at {int(played)} ms")

    # --------------------------------------------------------------- content
    def _on_owner_transcript(self, event: InputTranscriptionCompleted) -> None:
        """The owner's words: approximate (a separate ASR pass), and restricted.

        This is the ONLY place a hosted transcript can reach the robot, and it
        reaches it through ``submit_realtime_transcript`` — never
        ``submit_voice_text``, which is the front door to the whole local agent.
        """

        if self._ingress is None:
            # Lane-only wiring (unit tests, or a runtime with no ingress): the
            # lane is then the ledger writer for both sides.
            self._write_ledger(SPEAKER_OWNER, event.transcript, item_id=event.item_id)
            return
        try:
            outcome = self._ingress(
                event.transcript,
                item_id=event.item_id,
                session_id=self.session_id,
            )
        except (RuntimeError, TypeError, ValueError) as error:
            self._note(f"ingress refused {event.transcript!r}: {error}")
            self._write_ledger(SPEAKER_OWNER, event.transcript, item_id=event.item_id)
            return
        self.outcomes.append(outcome)
        narration = outcome.narration()
        if narration:
            # The agent NARRATES what the robot did; it never decides it.
            self._send_item(
                role="system", text=narration, purpose=ITEM_PURPOSE_ACTION_REPORT
            )

    def _on_robot_transcript(self, event: OutputTranscriptDone) -> None:
        if event.transcript.strip():
            # Set even for a truncated item: the owner HEARD part of it, so the
            # model has spoken in this response whatever the ledger records.
            self._spoke_this_response = True
            # Card R19. The done frame carries the WHOLE utterance for its item,
            # so it is appended only when the deltas did not already deliver it
            # — a provider that sends both would otherwise count every sentence
            # twice, and a two-word acknowledgement would cross the substantive
            # floor by arithmetic rather than by content. A response with two
            # spoken items keeps both.
            spoken = "".join(self._response_speech)
            if not spoken.rstrip().endswith(event.transcript.rstrip()):
                self._response_speech.append(event.transcript)
        if event.item_id in self._truncated_items:
            self._note(f"suppressed post-truncation transcript for {event.item_id}")
            return
        self._write_ledger(SPEAKER_ROBOT, event.transcript, item_id=event.item_id)

    def _on_function_call(self, event: FunctionCallArgumentsDone) -> None:
        """Answer one call — through the broker if one is wired, else refuse.

        With ``tool_handler=None`` these four statements are R1's, unchanged and
        proven byte-identical by test: same counter, same output string, same
        note, and no ``response.create``. With a broker wired the answer is the
        broker's, and it is followed by a ``response.create`` so the model speaks
        what ACTUALLY happened rather than what it hoped would — *unless* the
        turn has already had its one beat.

        Card R6, Defect 2 — that follow-up used to be unconditional, and that is
        what made the two-beat tool turn structural. The provider co-emits an
        announcement with the ``function_call`` ("Okay, let's head to the
        sidewalk") and ``gpt-realtime-2.1-mini`` will not be talked out of it:
        R5 proved that live under three SI wordings, including the card's own.
        So the beat that can be removed is this one, and it may only be removed
        when removing it costs the owner nothing:

        * the model already SPOKE in the response that carried the call — an
          announcement the owner has heard is a beat;
        * the call actually succeeded (``status: ok``) — a refusal, a deferral,
          a drop or a broker explosion contradicts that announcement, and the
          owner is entitled to hear the contradiction;
        * and the result is a RECEIPT rather than an ANSWER
          (:data:`DEFAULT_RECEIPT_TOOLS`) — what the robot does next is reported
          by its own systems through ``narrate_event`` and the mission log,
          while ``get_status``/``recall_memory`` have no later reporter at all
          and going quiet on those would be lying by silence.

        Every other path asks for the response, so the truthful-narration
        channel — the reason this beat exists — always survives.

        THE CAVEAT R6 LEFT HERE IS DISCHARGED (card R8, 2026-08-19). R6 wrote
        that the "reported by its own systems" half of the third bullet was not
        true on the wire: ``narrate_event`` builds a ``system`` conversation
        item through ``ConversationItemCreate``, which sent ``{"type": "text"}``
        for every non-``user`` role, and the provider refused it — so the fact
        never reached the model and the follow-up response was about nothing.
        R6 asked whoever fixed the content types to come back and confirm this
        bullet. Confirmed: the role-correct content types are live-verified
        (:data:`~parcel_robot.realtime.protocol.CONTENT_TYPE_BY_ROLE`), a
        narration now lands and the model's next reply reflects it, and the
        suppression this method performs rests on a channel that works. If it
        ever stops working the lane says so out loud — ``narrations_refused``
        in the snapshot, and a note naming the narration that was dropped.
        """

        handler = self._tool_handler
        if handler is None:
            self.refused_tool_calls.append(event.name)
            self._send(FunctionCallOutput(call_id=event.call_id, output=TOOL_REFUSAL_OUTPUT))
            self._note(f"tool call refused: {event.name}")
            return
        provenance = self._response_provenance
        if provenance == RESPONSE_FROM_SYSTEM:
            self.system_initiated_tool_calls += 1
        if not self._tag_handler(handler, provenance):
            # Card R11, design point 5, fail-closed arm. A handler that cannot be
            # told where the response came from cannot enforce the gate, and a
            # response the ROBOT started must not be able to move the body just
            # because the seam between these two objects is missing. Owner
            # responses are unaffected — this arm is only reachable for a system
            # -initiated one.
            self.refused_tool_calls.append(event.name)
            self._send(
                FunctionCallOutput(
                    call_id=event.call_id, output=SYSTEM_INITIATED_UNGATED_OUTPUT
                )
            )
            self._note(
                f"tool call refused: {event.name} (this reply was started by the robot's "
                "own status update and the tool handler cannot be told so)"
            )
            return
        try:
            output = handler.handle(
                name=event.name,
                call_id=event.call_id,
                arguments=event.arguments,
            )
        except (RuntimeError, TypeError, ValueError) as error:
            # A broker that raised still owes the provider an answer; an
            # unanswered function_call wedges the turn forever.
            output = json.dumps({"status": "rejected", "detail": f"tool broker failed: {error}"})
            self._note(f"tool broker raised on {event.name}: {error}")
        self.brokered_tool_calls.append(event.name)
        self._send(FunctionCallOutput(call_id=event.call_id, output=output))
        why = self._beat_reason(name=event.name, output=output)
        if why is None:
            self.tool_beats_suppressed += 1
            self._note(
                f"tool call answered: {event.name} (no second beat: the model already "
                "said something substantive in the response that carried the call, and "
                "the robot's own systems report what happens next)"
            )
            return
        beat = {
            "tool": event.name,
            "why": why,
            "answer": self._is_answer_result(name=event.name, output=output),
        }
        self._note(f"tool call answered: {event.name} (narrating: {why})")
        self._request_beat(beat)

    def _request_beat(self, beat: Mapping[str, object]) -> None:
        """Send one beat, and REMEMBER it in case the provider refuses the frame.

        Card R19, mechanism C. Sent immediately, exactly as R6 and R11 pinned it
        (a tool turn legitimately has two responses in flight, and R6's seed S2
        and R11's provenance seed both read that). What is new is that the lane
        now knows which frame it is, so the provider's answer to it can be acted
        on instead of landing in a counter nobody reconciles.
        """

        instructions = self._beat_instructions(answer=bool(beat.get("answer")))
        if self._send(ResponseCreate(instructions=instructions)):
            self.tool_beats_requested += 1
            self._beat_in_flight = dict(beat)
            return
        self.tool_beats_lost += 1
        self._note(
            f"tool beat NOT delivered for {beat['tool']}: the frame was dropped, so the "
            f"owner was never told — {beat['why']}"
        )

    def _beat_refused_by_provider(self, message: str) -> None:
        """The provider would not open the beat's response. Try again after this one.

        THE DEFECT THIS REPAIRS, from live_run_1
        (``state.realtime.lane.recent_server_errors``, verbatim):

            conversation_already_has_active_response: Conversation already has
            an active response in progress: resp_EEy3T5quJvQDbJRVd2JNe. Wait
            until the response is finished before creating a new one.

        A ``function_call`` arrives INSIDE an open response. The beat that
        answers it is a ``response.create``, and the provider refuses one while
        a response is in progress. In ``mode: text`` the carrying response
        closes within a millisecond of the call and the frame almost always
        wins the race; in ``mode: audio`` the response stays open for the length
        of the spoken sentence, so it almost always loses — which is why this
        defect waited for the first live voice run to appear, and why three of
        that run's four e-stop refusals were never spoken.

        Before this method the refused frame was counted as a beat, left
        ``_responses_pending`` incremented for a response that would never come
        (the leak the stall watchdog eventually fired on, 48 s later), and was
        never re-sent. Now it is un-counted, un-owed, and re-offered by
        :meth:`_on_response_done` the moment the conversation is free.

        ATTRIBUTION, stated honestly: the provider names the ACTIVE response in
        the message, not the refused one, so this cannot be matched by id. The
        rule is "a beat is in flight and the provider says a response is already
        active" — and the beat is sent within microseconds of the frame that
        opened the window, which is why it is the overwhelmingly likely
        candidate. If it is ever wrong the cost is one extra beat, never a
        silence.
        """

        beat = self._beat_in_flight
        if beat is None:
            return
        self._beat_in_flight = None
        self._responses_pending = max(0, self._responses_pending - 1)
        self._expecting_server = self._responses_pending > 0
        self.tool_beats_requested = max(0, self.tool_beats_requested - 1)
        self.tool_beats_refused += 1
        self._pending_beat = dict(beat)
        self._note(
            f"the provider refused the beat for {beat['tool']} ({message}); it will be "
            "asked for again as soon as the response that made the call finishes"
        )

    def _flush_pending_beat(self) -> None:
        """Ask again for a beat the provider refused. Card R19, mechanism C."""

        beat = self._pending_beat
        if beat is None:
            return
        self._pending_beat = None
        self.tool_beats_deferred += 1
        self._request_beat(beat)

    def _drop_pending_beat(self, reason: str) -> None:
        """A re-offer whose session died first. Counted, and said out loud."""

        self._beat_in_flight = None
        beat = self._pending_beat
        if beat is None:
            return
        self._pending_beat = None
        self.tool_beats_lost += 1
        self._note(
            f"tool beat LOST for {beat['tool']} ({reason}): the owner was never told — "
            f"{beat['why']}"
        )

    def _tag_handler(self, handler: ToolHandlerLike, provenance: str) -> bool:
        """Tell the handler who asked for this response. False ⇒ refuse the call.

        Returns True whenever the handler was successfully told, and also
        whenever the response is the OWNER's and the handler has no such method
        — a legacy handler answering an owner's request is exactly what it has
        always been, and this card does not narrow it. The only False is the one
        case the gate exists for: a system-initiated response reaching a handler
        that cannot be told so.
        """

        tell = getattr(handler, "note_response_provenance", None)
        if tell is None:
            return provenance != RESPONSE_FROM_SYSTEM
        try:
            tell(provenance)
        except (RuntimeError, TypeError, ValueError) as error:
            self._note(f"tool handler refused the response provenance tag: {error}")
            return provenance != RESPONSE_FROM_SYSTEM
        return True

    def _parsed_result(self, output: str) -> Mapping[str, object] | None:
        """The tool answer as an object, or ``None`` when it is not one."""

        try:
            parsed = json.loads(output)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, Mapping) else None

    def _is_answer_result(self, *, name: str, output: str) -> bool:
        """Is this result the ANSWER to a question the owner asked?

        Card R19, work item 2. Two independent ways to be one, because the
        weaker of them is the one R6 shipped and live_run_1 is the record of
        how little a protection-by-omission is worth once a card is allowed to
        pass ``receipt_tools=``:

        * the handler said so IN THE RESULT (``{"answer": true}``) — the lane
          does not need to know the tool surface at all, which is the tidy seam
          R6's Open risk 4 asked for;
        * or the tool is named in ``answer_tools``.

        Whichever fires, :meth:`_beat_reason` returns a reason to speak BEFORE
        it ever consults the receipt set, so an answer tool is unsuppressible
        by construction rather than by not being mentioned somewhere else.
        """

        if name in self._answer_tools:
            return True
        parsed = self._parsed_result(output)
        return bool(parsed is not None and parsed.get(ANSWER_RESULT_KEY) is True)

    def _beat_reason(self, *, name: str, output: str) -> str | None:
        """Why this tool answer still owes the owner a spoken beat, or ``None``.

        Fail-toward-speech at every branch: an output that will not parse, a
        status this lane has never heard of, a tool it does not recognise, a
        response whose only speech was "let me check" — all answer "speak". The
        only silence is one this method can positively justify, which is why the
        checks are stated as reasons rather than as a boolean.

        CARD R19 ADDS TWO BRANCHES to R6's four, and reorders nothing else.

        1. **An ANSWER is never suppressible**, checked ahead of the status and
           the receipt set so that no receipt configuration can reach it.
        2. **Filler is not speech.** R6's condition was "the model already spoke
           in the response that carried the call"; live_run_1 spent nine
           consecutive owner turns proving that the provider will happily
           satisfy that with "Let me think through what I can safely check and
           describe." A beat may only be dropped when the owner was told
           something (:func:`speech_is_substantive`).
        """

        if not self._spoke_this_response:
            return "the model made the call without saying anything"
        if self._is_answer_result(name=name, output=output):
            return "the result IS the answer the owner asked for, and nothing else says it"
        try:
            raw = json.loads(output)
        except (TypeError, ValueError):
            return "the tool answer is not JSON this lane can read"
        if not isinstance(raw, Mapping):
            return "the tool answer is not an object"
        parsed: Mapping[str, object] = raw
        status = str(parsed.get("status", "")).strip()
        if status != TOOL_STATUS_OK:
            return f"the call did not succeed (status={status or 'missing'})"
        if name not in self._receipt_tools:
            return "the result is an answer the owner is waiting for, not a receipt"
        if not speech_is_substantive("".join(self._response_speech)):
            return "the only thing said in this response was filler, so nothing has been said"
        return None

    def _beat_instructions(self, *, answer: bool = False) -> str | None:
        """Session instructions PLUS the beat rules, or ``None``.

        Never the rules on their own: ``response.instructions`` REPLACES the
        session prompt for that one response, so sending the bare rule would
        strip the persona and every guardrail from the single beat that reports
        what the robot actually did.

        Card R19 appends :data:`ANSWER_BEAT_RULE` — never substitutes it — when
        the result is the answer to a question. ``RESULT_BEAT_RULE`` still
        carries R6's four claims and R15's tense sentence, none of which is
        wrong for an answer beat; what it never carried is "say the figure".
        """

        rule = self._result_beat_instruction
        answer_rule = self._answer_beat_instruction if answer else None
        if not rule and not answer_rule:
            return None
        parts = [self.instructions]
        if rule:
            parts.append(rule)
        if answer_rule:
            parts.append(answer_rule)
        return "\n".join(parts)

    def _on_response_done(self, event: ResponseDone) -> None:
        self._flush_audio(final=True)
        self._response.playing = False
        # One ``response.done`` clears ONE outstanding request, not the whole
        # expectation. A tool turn has two in flight — the owner's, and the
        # follow-up the lane sends with the tool's answer — and clearing the
        # flag outright on the first one disarmed the watchdog for the second.
        # The provider could then go silent after a tool call forever and the
        # lane, by its own bookkeeping, was not waiting for anything.
        self._responses_pending = max(0, self._responses_pending - 1)
        # Card R8. A response came back, so whatever the owner SPOKE has been
        # answered too — the provider does not run two turns at once. This is
        # the line that stops the voice signal double-counting: without it an
        # answered spoken turn stays "owed" forever and every later reconnect
        # re-asks a question the owner already heard the answer to.
        self._voice_turn_owed = False
        self._expecting_server = self._responses_pending > 0
        # This response is over: the next ``function_call`` belongs to a new one
        # and inherits none of this one's speech (card R6, Defect 2).
        self._spoke_this_response = False
        self._response_speech = []
        # Card R19, mechanism C. BEFORE the provenance decision below, because a
        # re-offered beat is another outstanding response and inherits the tag
        # of the response that made the call exactly as the first attempt did.
        # Nothing is in progress at this instant, which is the one condition the
        # provider gave us for accepting it.
        if self._responses_pending == 0:
            self._beat_in_flight = None
        self._flush_pending_beat()
        # Card R11. The provenance tag lives until the LAST outstanding response
        # completes, not until the first: a tool turn has two in flight (the
        # original and the beat the lane sends with the tool's answer), and the
        # beat inherits the provenance of the response that made the call. Only
        # when nothing is outstanding does the lane go back to "the next thing
        # that happens is the owner's".
        if self._responses_pending == 0:
            self._response_provenance = RESPONSE_FROM_OWNER
        # A response that came back is the provider answering, which is what a
        # repay was for. The ladder that bounds repeated repays starts again
        # (card R6, Defect 1).
        self._repays_since_answer = 0
        # Card R16. The robot just finished saying something, so the idle window
        # is measured from the END of the exchange rather than from the question.
        # Without this a long answer would spend the owner's silence budget.
        self._mark_activity("a hosted response completed")
        row = {
            "session_id": self.session_id,
            "response_id": event.response_id,
            "status": event.status,
            "monotonic_s": round(self._clock(), 6),
            **event.usage.as_dict(),
        }
        self.usage_rows.append(row)
        self._append_cost_row(row)

    def _append_cost_row(self, row: Mapping[str, object]) -> None:
        """Usage lands in a JSONL beside the ledger, not in the sqlite ledger.

        Chosen over a sqlite table so that "invoice / committed turns" stays a
        one-file query and a cost-log write can never take a lock the
        conversation ledger needs mid-turn.

        Card R25 adds the second destination: the DURABLE month-to-date spend
        ledger the arming gate reads. ``cost_log_path`` is a per-run debugging
        dump nobody wires in production and it holds raw token counts; the spend
        ledger is priced, month-keyed and the thing the owner's ceiling stands
        on. Both are fed from here because this is the one place a response's
        usage is known, and neither may take the pump thread down with it — this
        runs inside ``pump()`` (card R22, §Safety-1).
        """

        if self._cost_log_path is not None:
            try:
                self._cost_log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._cost_log_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(dict(row), sort_keys=True) + "\n")
            except OSError as error:  # pragma: no cover - disk boundary
                self._note(f"cost row not written: {error}")
        ledger = self._spend_ledger
        if ledger is None:
            return
        try:
            ledger.record(row, session_id=self.session_id)
        except Exception as error:  # noqa: BLE001 - a cost row may never end a turn
            self.spend_ledger_failures += 1
            self._note(f"spend ledger row not written ({type(error).__name__}: {error})")

    # ------------------------------------------------------- session recovery
    def _on_disconnect(self) -> None:
        self.disconnects += 1
        self._note("transport disconnected mid-session")
        self._reconnect("disconnect")

    def _rollover(self, now: float) -> str:
        """The 60-minute cap. Same reconnect path, plus a summarize marker.

        The summarizer itself is R2 (the Voice Spine's idle-time distiller on
        the local reasoner). R1 ledgers the marker so a rollover is visible in
        the record rather than inferred from a gap.
        """

        del now
        self.rollovers += 1
        summary = None
        if self._summarize_hook is not None:
            try:
                summary = self._summarize_hook(self.session_id or "")
            except (RuntimeError, TypeError, ValueError) as error:  # pragma: no cover
                self._note(f"summarize hook failed: {error}")
        marker = summary or "[session rollover] summarization is not implemented in R1"
        self._write_ledger(SPEAKER_SYSTEM, marker, item_id=None)
        self._reconnect("rollover")
        return "rollover"

    def _backoff_wait(self, reason: str) -> float:
        """Bounded, jittered wait before a FAILURE reconnect. Returns seconds.

        The R1.5 audit's first standing risk: reconnect had no delay at all, so
        a provider that accepts a socket and immediately drops it turned
        ``pump()`` into a hot loop. The ladder is exponential from
        ``DEFAULT_RECONNECT_BACKOFF_S``, capped at ``_backoff_max_s``, and
        jittered across [0.5, 1.0] of the step so two lanes recovering from the
        same outage do not synchronize. A rollover is not a failure and waits
        nothing; a healthy session resets the ladder on ``session.created``.
        """

        if reason not in FAILURE_RECONNECT_REASONS or self._backoff_s <= 0.0:
            return 0.0
        step = min(self._backoff_max_s, self._backoff_s * (2.0**self._failed_reconnects))
        self._failed_reconnects += 1
        raw = self._jitter()
        # A jitter source that returns nonsense must lengthen the wait, never
        # shorten it: the failure mode this exists to prevent is a hot loop.
        jitter = float(raw) if isinstance(raw, (int, float)) and math.isfinite(raw) else 1.0
        delay = step * (0.5 + 0.5 * min(1.0, max(0.0, jitter)))
        self.backoff_waits.append(round(delay, 6))
        self._note(
            f"reconnect backoff after {reason}: waiting {delay:.3f}s "
            f"(attempt {self._failed_reconnects}, cap {self._backoff_max_s:.1f}s)"
        )
        self._sleep(delay)
        return delay

    def _reconnect(self, reason: str) -> None:
        """New session, same memory. The provider was never holding anything.

        Always reached with the lane held, so no other caller can observe the
        window between "the old socket is closed" and "the new one is up" and
        conclude the lane needs a session of its own.

        Card R6, Defect 1 — and same memory is not the same as same turn. The
        new session inherits the owner's question (the ledger wrote it and
        ``_inject_tail`` replays it) but nobody was asking it to ANSWER, so a
        provider that went quiet mid-turn cost the owner the whole sentence:
        no reply, no refusal, no billing. Twice observed live (R4L session 3,
        R5 session 3). ``_responses_pending`` is what was owed on the socket
        that just died, and it has to be read BEFORE ``_connect`` resets it.
        """

        if self._transport_factory is None:
            self._note(f"cannot reconnect after {reason}: no transport factory")
            return
        if self._reconnecting:  # pragma: no cover - defensive against re-entry
            self._note(f"reconnect after {reason} skipped: already recovering")
            return
        owed = self._responses_pending
        # Card R8, work item 3. Both signals are read here, before ``_connect``
        # clears them, and the repay below fires ONCE whichever of them is set.
        # A spoken turn and a typed one that were both outstanding are still one
        # conversation with one question at the end of it; two repays would buy
        # the owner a duplicate answer and a duplicate bill.
        voice_owed = self._voice_turn_owed
        self._reconnecting = True
        try:
            if self.transport is not None:
                try:
                    self.transport.close()
                except OSError:  # pragma: no cover - defensive
                    pass
            self._backoff_wait(reason)
            if not self._opened:
                # close() landed while we were waiting out the backoff. Opening
                # a socket now would resurrect a session the owner hung up on,
                # and a live hosted socket keeps billing.
                self._note(f"reconnect after {reason} abandoned: the lane was closed")
                return
            previous = self.session_id
            self.session_id = self._session_id_factory()
            self.reconnects += 1
            self._write_ledger(
                SPEAKER_SYSTEM,
                f"[session {reason}] reconnected {previous} -> {self.session_id}",
                item_id=None,
            )
            self._connect()
            self._note(
                f"reconnected after {reason}: re-sent instructions and "
                f"{self.tail_items_injected} tail item(s)"
            )
            if owed > 0 or voice_owed:
                self._repay_turn(owed=owed, reason=reason, voice=voice_owed)
        finally:
            self._reconnecting = False

    def _repay_turn(self, *, owed: int, reason: str, voice: bool = False) -> None:
        """Ask the NEW session to answer the turn the dead one never did.

        Card R6, Defect 1. Bounded three ways, because an unbounded version of
        this is worse than the defect it fixes:

        * **once per reconnect**, whatever was owed. A tool turn legitimately
          has two responses outstanding; re-asking twice would buy the owner a
          duplicate answer and a duplicate bill for one question.
        * **only what was actually owed.** ``_on_response_done`` decrements
          ``_responses_pending``, so a response that genuinely completed leaves
          nothing to repay and this is never reached — which is the rule that
          keeps a reconnect from double-answering.
        * **only while the provider is still worth asking.** A repay that itself
          stalls is the next watchdog cycle's problem (its backoff already
          climbs), but a turn that kills every session it touches is abandoned
          after :data:`DEFAULT_REPAY_LIMIT` tries, out loud in the ledger.

        The system row matters as much as the frame: without it the transcript
        shows an answer arriving minutes after the question with nothing in
        between to explain the gap.

        ``voice`` (card R8) says the turn was SPOKEN — ``owed`` is then usually
        zero, because the provider was going to create that response itself and
        this lane never sent a ``response.create`` to count. The frame and all
        three bounds are identical; only the sentence in the ledger changes, and
        it changes because "the previous session owed 0 answer(s)" is a lie
        about a question the owner definitely asked.
        """

        if self._repays_since_answer >= self._repay_limit:
            self.turn_repays_abandoned += 1
            self._note(
                f"turn NOT repaid after {reason}: {self._repays_since_answer} repay(s) "
                "since the last completed response; the provider is not answering this "
                "turn and re-asking it forever would only keep billing"
            )
            self._write_ledger(
                SPEAKER_SYSTEM,
                f"[turn abandoned] the owner's last turn was re-asked "
                f"{self._repays_since_answer} time(s) after a {reason} and was never "
                "answered; it will not be re-asked again",
                item_id=None,
            )
            return
        if not self._send(ResponseCreate()):
            # The brand-new socket died between opening and this frame. The
            # drop is already counted; the next watchdog cycle owns it.
            return
        self.turn_repays += 1
        if voice:
            self.voice_turn_repays += 1
        self._repays_since_answer += 1
        what = (
            f"owed {owed} answer(s)"
            if owed > 0
            else "was answering a turn the owner had SPOKEN"
        )
        self._write_ledger(
            SPEAKER_SYSTEM,
            f"[turn repaid] the previous session {what} when it died "
            f"({reason}); asked the new session to answer the turn it inherited",
            item_id=None,
        )
        self._note(
            f"repaid the owner's {'spoken' if voice and owed == 0 else 'typed'} turn after "
            f"{reason}: {owed} response(s) were owed on the dead session, voice_owed={voice} "
            f"(repay {self._repays_since_answer} of {self._repay_limit})"
        )

    # ----------------------------------------------------------------- plumbing
    def _send_item(self, *, role: str, text: str, purpose: str, required: bool = False) -> bool:
        """One conversation item up, TAGGED so a refusal can name it.

        Card R8, work item 2. Every ``conversation.item.create`` this lane sends
        goes through here and carries an ``event_id`` the provider echoes back
        on refusal, plus a descriptor kept locally saying what that item was for.
        The descriptor is the whole difference between the note the lane used to
        write ("server error invalid_value: Invalid value: 'text'…") and the one
        it writes now, which names the narration that was thrown away.

        The trace is bounded and evicts oldest-first. An item the provider
        ACCEPTS produces no error frame at all, so its descriptor is never
        claimed; without a bound a long session would accumulate one per item
        forever. A refusal arrives within a frame or two of the item that caused
        it — six for six in the R8 live probe — so anything evicted this far
        back was accepted.
        """

        self._item_seq += 1
        event_id = f"itm{self._item_seq}"
        self._item_trace[event_id] = {"role": role, "purpose": purpose, "text": text}
        while len(self._item_trace) > self._item_trace_limit:
            self._item_trace.pop(next(iter(self._item_trace)))
        delivered = self._send(
            ConversationItemCreate(role=role, text=text, event_id=event_id),
            required=required,
        )
        if not delivered:
            # The frame never left, so no refusal can ever be about it. Keeping
            # the descriptor would let an unrelated error claim it.
            self._item_trace.pop(event_id, None)
        return delivered

    def _send(self, event: Any, *, required: bool = False) -> bool:
        """One frame up. ``required`` means a drop is a failure, not a note.

        Returns whether the frame actually left the process — card R6, so a
        counter can be incremented for what was SENT rather than for what was
        attempted. ``_responses_pending`` has always had that property (it moves
        after the transport accepts the frame, never before) and the repay and
        beat counters must agree with it or the watchdog and the snapshot start
        telling different stories.

        Two behaviours the lane did not have before R4-lite:

        * a dropped frame is COUNTED (``dropped_sends``), so "the socket was
          closed under us" is visible in the snapshot instead of living only in
          an in-memory note list nothing renders;
        * whoever asks for a response arms the watchdog. Only ``send_text`` used
          to, which left the ``response.create`` that follows a tool answer
          unwatched: if the provider never came back from a tool call,
          ``_expecting_server`` was False and ``tick`` had nothing to notice.
        """

        if self.transport is None:
            raise RealtimeLaneError("realtime lane has no transport")
        try:
            self.transport.send(event)
        except TransportClosed as error:
            self.dropped_sends += 1
            self._note("send dropped: transport closed")
            if required:
                raise RealtimeLaneError(
                    "realtime lane dropped the owner's turn: the session's transport "
                    f"closed mid-send ({error}). The turn was NOT delivered."
                ) from None
            return False
        if isinstance(event, ResponseCreate):
            self._responses_pending += 1
            self._arm_watchdog()
        return True

    def _arm_watchdog(self) -> None:
        """Start the provider's patience clock NOW, not from its last frame.

        Found live, 2026-08-19 (card R6, session 1) and fixed here because it
        MANUFACTURES the incident this card exists to repair.
        ``_expecting_server`` was armed by whoever asked for a response, but
        ``_last_event_at`` moved only when a frame ARRIVED. So a session that
        had been quiet for longer than ``stall_timeout_s`` — which is any
        conversation with a pause in it — was already "stalled" the instant the
        owner's next turn went up: the watchdog hung up a healthy socket about
        two seconds after the question, before the provider had any chance to
        answer, and the turn was lost. In the R6 live session that is exactly
        what happened to "Wave at me please" (last frame 10.0 s earlier,
        timeout 8.0 s), and it is the most likely explanation for R4L's
        ``stalls: 2`` in two minutes and R5's four stalls across four short
        sessions.

        The watchdog's own note has always claimed to measure "no server event
        for Ns *while a response was expected*". This is the line that makes
        that sentence true.
        """

        self._expecting_server = True
        self._last_event_at = self._clock()

    def _write_ledger(self, speaker: str, text: str, *, item_id: str | None) -> None:
        """Both sides of every hosted turn. A failure here is a NOTE. Card R22.

        This is the call site the full audit named (AUDIT_FULL_FABLE §Safety-1,
        ``lane.py:1389`` at the time). It sits on the pump thread, it reaches
        raw sqlite two frames later, and until R22 it caught exactly
        ``RuntimeError``/``TypeError``/``ValueError``. ``sqlite3.Error``
        subclasses ``Exception`` and none of those three, so a disk-full or a
        locked database on the owner's store raised straight through here, out
        of ``_dispatch``, out of ``pump()`` and out of the pump thread — taking
        the spoken e-stop relay with it for the rest of the session.

        The rule was never wrong, only unenforced: **a ledger write must never
        take down a turn.** Now it cannot take down anything at all.
        """

        if self._ledger is None or not text.strip():
            return
        try:
            self._ledger.write_realtime_turn(
                session_id=self.session_id,
                speaker=speaker,
                text=text,
                origin=self._transcript_origin,
                provider_item_id=item_id,
            )
        except Exception as error:  # noqa: BLE001 - see the docstring above
            name = type(error).__name__
            self.ledger_failures += 1
            self.ledger_failure_types[name] = self.ledger_failure_types.get(name, 0) + 1
            self.last_ledger_failure = f"{name}: {error}"
            self._note(f"ledger write failed: {name}: {error}")

    def _note(self, message: str) -> None:
        self.events.append(message)

    def _month_to_date_snapshot(self) -> dict[str, object] | None:
        """The ledger's own dict, or ``None`` when no ledger is wired.

        ``None`` is a meaningful answer and not a missing one: it says "this
        lane is not metered", which is what every non-runtime construction of
        :class:`RealtimeLane` is. The panel renders that as "no ledger" rather
        than as "$0.00 spent", because the two are not the same claim.
        """

        total = self.month_to_date_spend()
        if total is None:
            return None
        fallback: dict[str, object] = {
            "month": str(total.month),
            "usd": round(float(total.usd), 6),
            "readable": bool(total.readable),
            "note": str(total.note),
        }
        as_dict = getattr(total, "as_dict", None)
        if not callable(as_dict):
            return fallback
        try:
            return dict(as_dict())
        except Exception as error:  # noqa: BLE001 - a snapshot may never raise
            fallback["note"] = f"{total.note} (snapshot degraded: {type(error).__name__})".strip()
            return fallback

    def snapshot(self) -> dict[str, object]:
        """What ``/api/state`` would show about the lane."""

        idle_now = self._idle_seconds(self._clock())
        return {
            "enabled": self.config.enabled,
            "active": self.active,
            "recovering": self._reconnecting,
            "dropped_sends": self.dropped_sends,
            # Card R16. The hang-up, from outside: how many sessions this lane
            # has closed for idleness, how long the last one had been quiet, how
            # long the current one has been quiet RIGHT NOW (``None`` while it is
            # busy or closed), and the window it is measured against.
            "idle_hang_ups": self.idle_hang_ups,
            "last_idle_seconds": self.last_idle_seconds,
            "idle_seconds": None if idle_now is None else round(float(idle_now), 3),
            "idle_close_after_s": self.config.idle_close_after_s,
            "narrations": self.narrations,
            "narrations_skipped": self.narrations_skipped,
            "narrations_skipped_closed": self.narrations_skipped_closed,
            # Card R25. The cost-ceiling asymmetry as two numbers: chatter this
            # month's ceiling silenced, and safety facts that outranked it.
            "narrations_skipped_budget": self.narrations_skipped_budget,
            "narrations_over_budget": self.narrations_over_budget,
            # Card R8, work item 2. ``narrations`` counts what left this process;
            # this counts what the provider threw away. A gap between them is
            # the R6 defect happening again, and it is now visible from
            # ``/api/state`` instead of only from a wire trace.
            "narrations_refused": self.narrations_refused,
            # The aggregate the card asks for, shaped like ``dropped_sends``:
            # a count, plus the most recent few with the item each refusal was
            # about wherever the provider echoed our event id.
            "server_errors": len(self.server_errors),
            "recent_server_errors": [
                dict(record) for record in self.server_error_records[-self._server_error_window :]
            ],
            "items_refused": len(self.refused_items),
            # Card R8, work item 3. Spoken turns the lane is waiting on, and the
            # repays that were fired for one. ``turn_repays`` still counts every
            # repay, so these two are a breakdown of it and never a second total.
            "voice_turn_owed": self._voice_turn_owed,
            "voice_turns_owed": self.voice_turns_owed,
            "voice_turn_repays": self.voice_turn_repays,
            "session_id": self.session_id,
            "provider_session_id": self.provider_session_id,
            "arming": None if self.arming is None else self.arming.as_dict(),
            "reconnects": self.reconnects,
            "turn_repays": self.turn_repays,
            "turn_repays_abandoned": self.turn_repays_abandoned,
            "tool_beats_requested": self.tool_beats_requested,
            "tool_beats_suppressed": self.tool_beats_suppressed,
            # Card R19, mechanism C. ``refused`` is beats the PROVIDER would not
            # open a response for (``conversation_already_has_active_response``
            # — the thing that ate three of live_run_1's four e-stop refusals);
            # ``deferred`` is how many of those were successfully asked for
            # again once the conversation was free. ``refused`` climbing with
            # ``deferred`` flat, or any ``lost`` at all, is an operator's alarm:
            # it is the count of refusals and answers the owner never heard.
            "tool_beats_refused": self.tool_beats_refused,
            "tool_beats_deferred": self.tool_beats_deferred,
            "tool_beats_lost": self.tool_beats_lost,
            "stalls": self.stalls,
            "rollovers": self.rollovers,
            "disconnects": self.disconnects,
            "refused_tool_calls": list(self.refused_tool_calls),
            "protocol_errors": list(self.protocol_errors),
            # Card R22, work item 1. Frames the lane understood and could not
            # handle. Beside ``protocol_errors`` and never folded into it: one
            # is the provider changing, the other is this process breaking, and
            # an operator reading a rising number needs to know which.
            "dispatch_failures": self.dispatch_failure_count,
            "dispatch_failure_types": dict(self.dispatch_failure_types),
            "recent_dispatch_failures": list(self.dispatch_failures[-3:]),
            # Card R22, work item 4. Ledger writes degraded to a note.
            "ledger_failures": self.ledger_failures,
            "ledger_failure_types": dict(self.ledger_failure_types),
            "last_ledger_failure": self.last_ledger_failure,
            # Card R22, work item 5 / EV-1 §10.3. Retained ASR + boundary frames
            # handed to the evidence log, by type.
            "retained_events": self.retained_events,
            "retained_event_types": dict(self.retained_event_types),
            "retention_failures": self.retention_failures,
            "retention_wired": self._retention_sink is not None,
            "usage_rows": len(self.usage_rows),
            # Card R25. The durable ceiling, from the lane's own point of view:
            # what this month has cost, whether that number came from a file we
            # could actually read, and the ceiling it is measured against. The
            # panel answers "how close am I?" off this without reading files.
            "month_to_date": self._month_to_date_snapshot(),
            "monthly_budget_usd": self.config.monthly_budget_usd,
            "spend_ledger_failures": self.spend_ledger_failures,
            "audio_frames_sent": self._audio_sent_this_session,
            "tail_items_injected": self.tail_items_injected,
            "tools_enabled": self._tool_handler is not None,
            # Card R11, design point 5. The tag, from outside: how many responses
            # the robot started off its own state, how many of those tried to
            # call a tool anyway, and what the lane currently believes about the
            # response in flight.
            "response_provenance": self._response_provenance,
            "system_initiated_responses": self.system_initiated_responses,
            "system_initiated_tool_calls": self.system_initiated_tool_calls,
            "brokered_tool_calls": list(self.brokered_tool_calls),
            "text_turns": self.text_turns,
            "backoff_waits_s": list(self.backoff_waits),
        }


__all__ = [
    "ANSWER_BEAT_RULE",
    "ANSWER_RESULT_KEY",
    "CODE_ARMED",
    "CODE_BUDGET_EXHAUSTED",
    "CODE_DISABLED",
    "CODE_NO_HANDSHAKE",
    "CODE_NO_MIC_GESTURE",
    "CODE_NO_TRANSPORT",
    "CODE_RESPONSE_ALREADY_ACTIVE",
    "DEFAULT_ANSWER_TOOLS",
    "DEFAULT_COALESCE_MS",
    "DEFAULT_ENTRY_TIMEOUT_S",
    "DEFAULT_ITEM_TRACE_LIMIT",
    "DEFAULT_RECEIPT_TOOLS",
    "DEFAULT_RECONNECT_BACKOFF_MAX_S",
    "DEFAULT_RECONNECT_BACKOFF_S",
    "DEFAULT_REPAY_LIMIT",
    "DEFAULT_SERVER_ERROR_WINDOW",
    "FAILURE_RECONNECT_REASONS",
    "FILLER_ACKNOWLEDGEMENTS",
    "FILLER_CLAUSE_PREFIXES",
    "GUARDRAILS",
    "IDLE_LEDGER_PREFIX",
    "ITEM_PURPOSE_ACTION_REPORT",
    "ITEM_PURPOSE_NARRATION",
    "ITEM_PURPOSE_OWNER_TURN",
    "ITEM_PURPOSE_TAIL",
    "MIN_SUBSTANTIVE_WORDS",
    "REASON_IDLE_HANG_UP",
    "RESPONSE_FROM_OWNER",
    "RESPONSE_FROM_SYSTEM",
    "RESULT_BEAT_RULE",
    "SPEAKER_OWNER",
    "SPEAKER_ROBOT",
    "SPEAKER_SYSTEM",
    "SYSTEM_INITIATED_UNGATED_OUTPUT",
    "TOOL_REFUSAL_OUTPUT",
    "TOOL_STATUS_OK",
    "LedgerLike",
    "MonthToDateSpendLike",
    "RealtimeArmingDecision",
    "RealtimeLane",
    "RealtimeLaneError",
    "SinkLike",
    "SinkOwnershipError",
    "SpendLedgerLike",
    "ToolHandlerLike",
    "build_instructions",
    "clause_is_filler",
    "decide_realtime_arming",
    "speech_is_substantive",
]
