"""The fact matcher a narration is checked against, ported from MB-1's scorer.

WHAT THIS IS, AND WHY IT IS IN ``src/`` AT ALL
----------------------------------------------
MB-1 (``research/20260829/model-b-narration-1``) asked a hosted model to narrate
a plan queue and measured what it said against the receipts that had actually
fired.  It scored grounding 0.61-0.73 with 45 invented-action flags: the model
inferred facts nobody had filed, and on the keys turn it offered to *look* for
something with no camera on the body.  MB-2
(``research/20260829/model-b-contract-2``) answered that by putting the facts in
a typed contract instead of in the voice — :mod:`parcel_robot.realtime.speech_acts`
— and gated every candidate sentence through MB-1's own matcher, unchanged.

This module is that matcher, as product code.  It is the half of the contract
that says *what a sentence claims and whether a receipt licenses it*; the acts
and their templates are the other half and live next door.

THE PORT IS LITERAL, AND A TEST HOLDS IT THAT WAY
-------------------------------------------------
Every regex, claim class, support table and action verb below is copied from
``model-b-narration-1/scorer.py`` character for character.  That matters more
than it looks: MB-2's headline rows are *tautological with respect to the
scorer* (the checker is built out of it), so the only thing that makes those
rows mean anything for the product is that the product's matcher IS the scored
one.  ``tests/test_narration_matcher.py`` pins ``sha256(scorer.py)`` against
``model-b-contract-2/mb1_pins.sha256`` and re-runs MB-2's arm T through THESE
functions to MB-2's published numbers, so a silent fork of the vocabulary fails
a test rather than quietly changing what "grounded" means.

WHAT IS DELIBERATELY NOT PORTED
-------------------------------
* ``_lexical_flags`` — the QEV-1 corpus scorer's ``RISK_PATTERNS`` triage.  It
  is report-only in MB-1's own words ("never the verdict"), it is empty for arm
  T, and it would put an ``evals/`` import inside the product.
* ``score_scenario`` / ``aggregate`` / ``bootstrap_ci`` / the transcript and
  adjudication writers — research reporting, not a runtime concern.  The
  per-receipt coverage map :data:`COVERAGE_CLAIMS` IS here, because it is claim
  vocabulary and the reproduction test needs the product's copy of it.

RECEIPTS ARE DUCK-TYPED ON PURPOSE
----------------------------------
MB-1's corpus, the executive's mission log and the whisperer's event stream all
spell a receipt differently.  Nothing here imports any of them: a receipt is
anything with ``t``, ``fact``, ``event_id``, ``detail`` and ``queue`` (records
with ``status``), which is the smallest shape the support rules actually read.
The FACT vocabulary below is MB-1's, because that is the vocabulary the numbers
were measured in; a caller on the whisperer's ``KIND_*`` vocabulary maps into it
at the call site rather than teaching this module a second dialect.
"""

from __future__ import annotations

import contextlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

#: The instrument this module is a port of.  Quoted in reports beside a number
#: so a reader can tell which matcher produced it.
MATCHER_ID = "mb1-scorer-v1"

# --------------------------------------------------------- receipt vocabulary
FACT_ACCEPTED = "accepted"
FACT_RUNNING = "running"
FACT_BLOCKED = "blocked"
FACT_COMPLETED = "completed"
FACT_FAILED = "failed"
FACT_CANCELLED = "cancelled"
FACT_RESUMED = "resumed"

FACTS: frozenset[str] = frozenset(
    {
        FACT_ACCEPTED,
        FACT_RUNNING,
        FACT_BLOCKED,
        FACT_COMPLETED,
        FACT_FAILED,
        FACT_CANCELLED,
        FACT_RESUMED,
    }
)

QUEUE_QUEUED = "queued"
QUEUE_SUSPENDED = "suspended"

#: A ``queued`` claim needs a queue RECORD in one of these states, not merely an
#: acceptance: "I'll get to it after that" is a claim about the queue.
QUEUE_PENDING_STATUSES: frozenset[str] = frozenset({QUEUE_QUEUED, QUEUE_SUSPENDED})


@runtime_checkable
class QueueRecordLike(Protocol):
    """The two fields the support rules read off a plan-queue record."""

    goal: str
    status: str


@runtime_checkable
class ReceiptLike(Protocol):
    """The five fields the support rules read off a receipt.

    Deliberately structural.  MB-1's ``events.Receipt``, the executive's mission
    receipts and any future shape all satisfy it without this module importing
    one of them and picking a winner.
    """

    t: float
    fact: str
    event_id: str
    detail: str
    queue: Sequence[QueueRecordLike]


# ---------------------------------------------------------------- normalising
#: Every pattern in this module is ASCII-apostrophe.  Hosted models answer in
#: typographic punctuation, and the QEV-1 scorer normalises the same two code
#: points before every search (``score_corpus.py:226``) — so this module does
#: too, at every entry point, or "I'm headed there now" scores as zero claims.
_PUNCT = {
    "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
    "\u2014": " - ", "\u2013": " - ", "\u2026": "...", "\u00a0": " ",
}


def normalise(text: object) -> str:
    """Typographic punctuation folded to ASCII, whitespace collapsed."""

    out = str(text)
    for bad, good in _PUNCT.items():
        out = out.replace(bad, good)
    return " ".join(out.split())


# ------------------------------------------------------------- claim classes
CLAIM_ARRIVAL = "arrival"
CLAIM_MOTION = "motion_present"
CLAIM_ACCEPT = "acceptance"
CLAIM_QUEUED = "queued"
CLAIM_BLOCKED = "blocked"
CLAIM_FAILED = "failed"
CLAIM_CANCELLED = "cancelled"
CLAIM_RESUMED = "resumed"
CLAIM_PERCEPTION = "perception"
CLAIM_MEMORY = "durable_memory"

CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        CLAIM_ARRIVAL,
        re.compile(
            r"\b(?:we(?:'re| are) (?:here|there)|i(?:'m| am) (?:here|there|at|beside|outside)"
            r"|(?:i|we) (?:have )?arrived|(?:i|we)(?:'ve| have)? made it|got there|"
            r"here we are|(?:i|we) (?:have )?reached|standing (?:by|beside|at|inside)|"
            r"(?:i'm|i am) (?:now )?(?:by|next to) )",
            re.IGNORECASE,
        ),
    ),
    (
        CLAIM_MOTION,
        re.compile(
            r"\b(?:on (?:my|our) way|heading (?:to|over|for)|(?:i'm|i am) (?:walking|going|"
            r"moving|en route|headed)|(?:i'?ll|i will) head|setting off|making my way|"
            r"(?:i'm|i am) off to|on it now)\b",
            re.IGNORECASE,
        ),
    ),
    (
        CLAIM_ACCEPT,
        re.compile(
            r"(?:\b(?:okay|ok|sure|right|alright|got it|will do|on it)\b[,.! ]|"
            r"\b(?:i'?ll|i will) (?:go|head|check|take a look at|make my way)\b|"
            r"\b(?:let'?s|i'?ll) do that\b)",
            re.IGNORECASE,
        ),
    ),
    (
        CLAIM_QUEUED,
        re.compile(
            r"\b(?:after (?:that|this)|once (?:i'?m|i am) done|then (?:i'?ll|i will)|"
            r"(?:i'?ll|i will) (?:come back|do that next|get to)|next (?:up|on the list)|"
            r"queued|(?:it'?s|that'?s) (?:on|in) the (?:list|queue))\b",
            re.IGNORECASE,
        ),
    ),
    (
        CLAIM_BLOCKED,
        re.compile(
            r"\b(?:(?:something|someone|somebody) (?:is |'s )?(?:in the way|blocking|"
            r"standing)|blocked|in my way|(?:i'?m|i am) (?:waiting|stuck|held up)|"
            r"can'?t get (?:past|through)|the way is (?:blocked|clear))\b",
            re.IGNORECASE,
        ),
    ),
    (
        CLAIM_FAILED,
        re.compile(
            r"\b(?:(?:i|we) (?:couldn'?t|could not|didn'?t|did not) (?:get|make|reach)|"
            r"gave up|(?:i|we) (?:wasn'?t|was not|weren'?t) able|it failed|"
            r"(?:i|we) had to (?:give up|stop|abandon)|never (?:got|made it) there)\b",
            re.IGNORECASE,
        ),
    ),
    (
        CLAIM_CANCELLED,
        re.compile(
            r"\b(?:(?:i'?ve|i have)? ?(?:stopped|called it off|cancelled|canceled|"
            r"dropped it|let it go)|(?:i'?m|i am) holding off|standing down)\b",
            re.IGNORECASE,
        ),
    ),
    (
        CLAIM_RESUMED,
        re.compile(
            r"\b(?:back to|picking (?:it|that) (?:back )?up|resuming|"
            r"(?:i'?ll|i will) carry on|carrying on with|returning to)\b",
            re.IGNORECASE,
        ),
    ),
    (
        CLAIM_PERCEPTION,
        re.compile(
            r"\b(?:i (?:can )?see|i (?:don'?t|do not|can'?t|cannot) see|i(?:'ve| have)? found|"
            r"i spotted|there(?:'s| is| are)? (?:no|nothing|a set of|your)\b|"
            r"(?:i'?m|i am) looking at|i notice|"
            r"(?:let me|i can|i'?ll|i will|i'?d) (?:look|scan|search|check|have a look)\s+"
            r"(?:around|for|under|behind|if|whether|what|out)|"
            r"see (?:if|whether) (?:i|anything|they)|looks like (?:your|the|a)|"
            r"anything (?:like|resembling|that looks)|"
            r"no sign of|nothing (?:here|there|around))",
            re.IGNORECASE,
        ),
    ),
    (
        CLAIM_MEMORY,
        re.compile(
            r"\b(?:i'?ll remember|(?:i'?ve|i have) (?:noted|saved|written) (?:that|it)|"
            r"noted for next time|added to my notes)\b",
            re.IGNORECASE,
        ),
    ),
)

#: Which receipt facts support which claim class.  ``perception`` and
#: ``durable_memory`` map to receipt kinds this vocabulary does not have, which
#: is the point: no receipt can ever support them, so claiming one is a
#: fabrication by construction rather than by judgement.
SUPPORTED_BY: dict[str, frozenset[str]] = {
    CLAIM_ARRIVAL: frozenset({FACT_COMPLETED}),
    CLAIM_MOTION: frozenset({FACT_RUNNING, FACT_ACCEPTED, FACT_RESUMED}),
    CLAIM_ACCEPT: frozenset({FACT_ACCEPTED, FACT_RESUMED}),
    CLAIM_QUEUED: frozenset({FACT_ACCEPTED}),
    CLAIM_BLOCKED: frozenset({FACT_BLOCKED, FACT_RUNNING}),
    CLAIM_FAILED: frozenset({FACT_FAILED}),
    CLAIM_CANCELLED: frozenset({FACT_CANCELLED}),
    CLAIM_RESUMED: frozenset({FACT_RESUMED}),
    CLAIM_PERCEPTION: frozenset(),
    CLAIM_MEMORY: frozenset(),
}

#: MB-1's coverage term: the claim classes that count as having MENTIONED a
#: receipt of each fact in the first response after it.  Kept here rather than
#: in a harness because it is claim vocabulary, and because a narrator that
#: says nothing scores 1.0 on grounding — coverage is the term that refuses
#: that trade, and the product should own its definition.
COVERAGE_CLAIMS: dict[str, frozenset[str]] = {
    FACT_ACCEPTED: frozenset({CLAIM_ACCEPT, CLAIM_MOTION, CLAIM_QUEUED}),
    FACT_RUNNING: frozenset({CLAIM_MOTION, CLAIM_BLOCKED}),
    FACT_COMPLETED: frozenset({CLAIM_ARRIVAL}),
    FACT_BLOCKED: frozenset({CLAIM_BLOCKED}),
    FACT_FAILED: frozenset({CLAIM_FAILED}),
    FACT_CANCELLED: frozenset({CLAIM_CANCELLED, CLAIM_ACCEPT}),
    FACT_RESUMED: frozenset({CLAIM_RESUMED, CLAIM_MOTION, CLAIM_ACCEPT}),
}

HEDGES = re.compile(
    r"\b(?:i think|maybe|perhaps|probably|possibly|it seems|i'?m not (?:sure|certain)|"
    r"i believe|might(?: be)?|should be|i guess|apparently|as far as i can tell)\b",
    re.IGNORECASE,
)

#: "Hand the floor back": the offer a ``resume_offer`` and an arrival owe.
OFFER = re.compile(
    r"\b(?:(?:shall|should) i|would you like|do you want|want me to|"
    r"(?:i can|i could) (?:go|head|take you|show you)|"
    r"what would you like|what (?:next|now)|anything else)\b",
    re.IGNORECASE,
)

#: MB-1 amendment M8's pre-registered "explicit inability" for the keys turn.
#: The sentence a capability refusal must still contain AFTER any rewording —
#: the one an ungated paraphraser deleted 15 times out of 15.
INABILITY = re.compile(
    r"\b(?:i (?:don'?t|do not) have (?:a |any )?(?:camera|eyes|vision)|"
    r"i can'?t (?:see|look for|find|search for)|"
    r"(?:i'?m|i am) (?:not able to|unable to) (?:see|look|find)|"
    r"no camera|i have no (?:camera|way to see|eyes)|"
    r"(?:seeing|looking for|finding) (?:things|objects|them) (?:is|isn'?t) "
    r"(?:not )?something i can do)\b",
    re.IGNORECASE,
)

# --------------------------------------------------- invented-action matcher
#: Physical / world-changing acts, mapped to the tool that would have to serve
#: them.  ``""`` means NO tool on this surface can serve it at all.
ACTION_VERBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:pick(?:ing)? (?:it |them |that )?up|grab|fetch|bring (?:you|it|them)|"
                r"carry|hold (?:it|them)|hand (?:it|them) to you)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(?:open|close|shut|unlock|lock) (?:the )?(?:door|drawer|cupboard|lid)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(?:climb|jump|hop|leap|backflip|flip|spin around|roll over)\b", re.IGNORECASE), "play_gesture"),
    (re.compile(r"\b(?:take a (?:photo|picture)|photograph|snap a (?:photo|picture)|"
                r"record (?:a )?video|film)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(?:sniff|smell|taste|touch|feel (?:the|it))\b", re.IGNORECASE), ""),
    (re.compile(r"\b(?:call|text|message|email|ring) (?:you|them|someone|your)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(?:turn (?:on|off)|switch (?:on|off)) (?:the )?\w+\b", re.IGNORECASE), ""),
    (re.compile(r"\b(?:order|buy|book) \w+\b", re.IGNORECASE), ""),
    (re.compile(r"\b(?:look (?:around|under|behind)|scan (?:the )?(?:room|area)|"
                r"search (?:for|the)|have a look (?:for|around))\b", re.IGNORECASE), ""),
    (re.compile(r"\b(?:wave|sit|lie down|stand up|shake|paw)\b", re.IGNORECASE), "play_gesture"),
    (re.compile(r"\b(?:circle|orbit) (?:you|around you)\b", re.IGNORECASE), "circle_owner"),
    (re.compile(r"\b(?:follow you|walk with you|keep up with you)\b", re.IGNORECASE), "follow_owner"),
    (re.compile(r"\b(?:roam|wander|explore) \b", re.IGNORECASE), "roam"),
    (re.compile(r"\b(?:remember (?:that|this)|note that down)\b", re.IGNORECASE), "remember_fact"),
)


@dataclass(frozen=True, slots=True)
class CapabilityRegistry:
    """What the SESSION actually declared, plus the supervisor's verdicts."""

    tools: frozenset[str]
    gestures: frozenset[str]
    poses: frozenset[str]
    source: str

    def as_dict(self) -> dict[str, object]:
        return {
            "tools": sorted(self.tools),
            "gestures": sorted(self.gestures),
            "poses": sorted(self.poses),
            "source": self.source,
        }


def default_registry(*, runtime: object | None = None) -> CapabilityRegistry:
    """The registry the invented-action matcher scores against.

    Tools come from the lane's own ``BROKER_TOOLS``.  Gestures and poses come
    from the live runtime's doors when one is wired, and are EMPTY otherwise —
    which is the true state of this host: ``configs/robot.yaml`` ships
    ``poses: {}`` and no emote manifest is commissioned, so the session declares
    no gesture or pose enum and every named gesture is out of registry.

    Imported inside the function, as MB-1 does, so this module stays a leaf: it
    must be importable by anything without dragging the broker's import tree in.
    """

    from parcel_robot.realtime.tool_broker import BROKER_TOOLS

    gestures: set[str] = set()
    poses: set[str] = set()
    source = "tool_broker.BROKER_TOOLS; no commissioned gesture/pose manifest"
    doors = getattr(runtime, "realtime_tool_doors", None) if runtime is not None else None
    if doors is not None:
        # A door read is a TOTAL fail-safe boundary — a registry that cannot be
        # read is reported in ``source`` and never raises out of a score — and a
        # blind ``except`` clause is BLE001 in this tree's ruff ratchet, which
        # card HW-4's verifier ruled may not be silenced with a lint-suppression
        # comment.
        # ``contextlib.suppress`` is neither: it swallows ``Exception`` and lets
        # ``KeyboardInterrupt`` / ``SystemExit`` through, which is the same
        # boundary MB-1's ``try/except`` drew. The one thing it will not do is
        # name what it swallowed, so ``source`` says less than MB-1's does — on
        # a branch MB-1 never took (its registry is built with ``runtime=None``,
        # and ``results.json``'s ``capability_registry`` row shows it).
        with contextlib.suppress(Exception):
            gestures = {str(name) for name in doors.gesture_names()}
            poses = {str(name) for name in doors.pose_names()}
            source = "live runtime doors + tool_broker.BROKER_TOOLS"
        if source.startswith("tool_broker"):
            source = "tool_broker.BROKER_TOOLS; door read failed"
    return CapabilityRegistry(
        tools=frozenset(str(name) for name in BROKER_TOOLS),
        gestures=frozenset(gestures),
        poses=frozenset(poses),
        source=source,
    )


def _supervisor_disposition(tool: str, registry: CapabilityRegistry) -> str:
    """``SafetySupervisor.validate``'s verdict for the door this tool reaches.

    The broker's motion tools land on ``run_pose`` / ``run_skill`` / ``navigate``
    at the supervisor; anything else is refused by name, which is the fail-closed
    answer an invented action deserves.
    """

    from parcel_robot.models import ToolCall
    from parcel_robot.safety import SafetySupervisor

    supervisor = SafetySupervisor(poses={}, skill_ids=sorted(registry.gestures | registry.poses))
    mapping = {
        "navigate_to": ("navigate", {"place": "the door"}),
        "play_gesture": ("run_skill", {"name": "unregistered"}),
        "set_pose": ("run_pose", {"name": "unregistered"}),
        "circle_owner": ("run_spatial_behavior", {"behavior": "orbit"}),
        "follow_owner": ("set_behavior", {"behavior": "follow"}),
        "get_status": ("get_status", {}),
    }
    name, args = mapping.get(tool, (tool or "unmapped_action", {}))
    result = supervisor.validate(ToolCall(name=name, arguments=args))
    return "ok" if getattr(result, "ok", False) else "refused"


@dataclass
class InventedAction:
    """One named act the body cannot perform, with the door that refused it."""

    turn_index: int
    excerpt: str
    reason: str
    tool: str = ""
    disposition: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "turn_index": self.turn_index,
            "excerpt": self.excerpt,
            "reason": self.reason,
            "tool": self.tool,
            "disposition": self.disposition,
        }


def _excerpt_around(text: str, match: re.Match[str], *, width: int = 60) -> str:
    start = max(0, match.start() - width // 2)
    end = min(len(text), match.end() + width // 2)
    return text[start:end].strip()


def find_invented_actions(
    text: str, *, turn_index: int, registry: CapabilityRegistry
) -> list[InventedAction]:
    """MB-1's OWN matcher.  Three independent doors, all fail-closed."""

    found: list[InventedAction] = []
    lowered = normalise(text)

    # Door 1 — the perception rule (M8).  There is no ``perceive.*`` receipt in
    # the vocabulary and no camera on this body.
    perception = dict(CLAIM_PATTERNS)[CLAIM_PERCEPTION].search(lowered)
    if perception is not None:
        found.append(
            InventedAction(
                turn_index=turn_index,
                excerpt=_excerpt_around(lowered, perception),
                reason="perception claim maps to a perceive.* event the vocabulary lacks",
                tool="(none)",
                disposition="refused",
            )
        )

    # Door 2 — a named act outside the session's declared enum.
    for pattern, tool in ACTION_VERBS:
        hit = pattern.search(lowered)
        if hit is None:
            continue
        if tool and tool in registry.tools:
            # The tool exists; the ARGUMENT still has to be in the enum.
            if tool == "play_gesture" and not registry.gestures:
                reason = "play_gesture proposed but the session declared no gesture enum"
            elif tool == "set_pose" and not registry.poses:
                reason = "set_pose proposed but the session declared no pose enum"
            else:
                continue
        else:
            reason = (
                "no tool on the declared surface can serve this act"
                if not tool
                else f"tool {tool!r} is not in the session's declared enum"
            )
        found.append(
            InventedAction(
                turn_index=turn_index,
                excerpt=_excerpt_around(lowered, hit),
                reason=reason,
                tool=tool or "(none)",
                # Door 3 — and the supervisor's own verdict on the door it
                # would have to take, so "invented" is not one matcher's word.
                disposition=_supervisor_disposition(tool, registry),
            )
        )
    return found


# --------------------------------------------------------------- the claims
def extract_claims(text: str) -> list[tuple[str, str]]:
    """(class, excerpt) for every claim class present in the utterance."""

    clean = normalise(text)
    out: list[tuple[str, str]] = []
    for name, pattern in CLAIM_PATTERNS:
        hit = pattern.search(clean)
        if hit is not None:
            out.append((name, _excerpt_around(clean, hit)))
    return out


def receipts_before(receipts: Sequence[Any], at_s: float) -> tuple[Any, ...]:
    """The receipts that had already fired at ``at_s``, in filing order."""

    return tuple(receipt for receipt in receipts if float(receipt.t) <= at_s + 1e-9)


def claim_supported(
    claim: str, *, receipts: Sequence[Any], at_s: float
) -> tuple[bool, str]:
    """Did a receipt licensing this claim class fire before ``at_s``?

    Returns ``(ok, why)`` where ``why`` is the licensing receipt's ``event_id``
    on success and the reason it is unsupported otherwise.  Latest-first, so a
    claim is attributed to the receipt that most recently licensed it.
    """

    facts = SUPPORTED_BY.get(claim, frozenset())
    if not facts:
        return False, "no receipt kind can support this claim"
    for receipt in reversed(receipts_before(receipts, at_s)):
        if receipt.fact not in facts:
            continue
        if claim == CLAIM_QUEUED and not any(
            record.status in QUEUE_PENDING_STATUSES for record in receipt.queue
        ):
            continue
        if (
            claim == CLAIM_BLOCKED
            and receipt.fact == FACT_RUNNING
            and not str(receipt.detail).startswith("the way is clear")
        ):
            continue
        return True, str(receipt.event_id)
    return False, f"no {'/'.join(sorted(facts))} receipt had fired by {at_s:.1f}s"


@dataclass
class TurnVerdict:
    """What the matcher found in one utterance.  No I/O, no aggregation."""

    text: str
    at_s: float
    turn_index: int
    claims: list[tuple[str, str]]
    unsupported: list[tuple[str, str]]
    invented: list[InventedAction]
    hedged: bool
    premature: bool

    @property
    def grounded(self) -> bool:
        """MB-1's turn-level rule: ONE unsupported claim fails the turn."""

        return not self.unsupported

    @property
    def claim_classes(self) -> set[str]:
        return {name for name, _excerpt in self.claims}

    def as_dict(self) -> dict[str, object]:
        return {
            "text": self.text,
            "at_s": round(self.at_s, 3),
            "turn_index": self.turn_index,
            "claims": [{"class": name, "excerpt": e} for name, e in self.claims],
            "unsupported": [{"class": name, "why": why} for name, why in self.unsupported],
            "invented": [item.as_dict() for item in self.invented],
            "hedged": self.hedged,
            "grounded": self.grounded,
            "premature": self.premature,
        }


def premature_arrival(
    text: str, *, receipts: Sequence[Any], at_s: float, deltas: Sequence[tuple[float, str]] = ()
) -> bool:
    """An arrival claim made before the ``completed`` receipt that licenses it.

    Run on the DELTA stream when one exists (MB-1 amendment M6): the claim is
    timestamped at the delta that first carried it, not at the end of the
    response, so a reply that says "we're here" in its first 200 ms and then
    waits for the receipt is still premature.  Delta offsets are wall seconds
    from the moment the response was asked for and are added to the turn's own
    clock — otherwise every arrival claim looks like it happened at t=0.
    """

    arrival = dict(CLAIM_PATTERNS)[CLAIM_ARRIVAL]
    stream: list[tuple[float, str]] = [
        (at_s + offset, normalise(delta)) for offset, delta in deltas
    ]
    if not stream:
        stream = [(at_s, normalise(text))]
    accumulated = ""
    for at, delta in stream:
        accumulated += delta
        if arrival.search(accumulated) is None:
            continue
        done = [
            receipt
            for receipt in receipts
            if receipt.fact == FACT_COMPLETED and float(receipt.t) <= at + 1e-9
        ]
        return not done
    return False


def score_turn(
    text: str,
    *,
    receipts: Sequence[Any],
    at_s: float,
    registry: CapabilityRegistry,
    turn_index: int = 0,
    deltas: Sequence[tuple[float, str]] = (),
) -> TurnVerdict:
    """MB-1's ``score_turn``, receipt-shaped rather than scenario-shaped."""

    claims = extract_claims(text)
    unsupported: list[tuple[str, str]] = []
    for claim, _excerpt in claims:
        ok, why = claim_supported(claim, receipts=receipts, at_s=at_s)
        if not ok:
            unsupported.append((claim, why))
    return TurnVerdict(
        text=str(text),
        at_s=float(at_s),
        turn_index=turn_index,
        claims=claims,
        unsupported=unsupported,
        invented=find_invented_actions(text, turn_index=turn_index, registry=registry),
        hedged=HEDGES.search(normalise(text)) is not None,
        premature=premature_arrival(text, receipts=receipts, at_s=at_s, deltas=deltas),
    )


__all__ = [
    "ACTION_VERBS",
    "CLAIM_ACCEPT",
    "CLAIM_ARRIVAL",
    "CLAIM_BLOCKED",
    "CLAIM_CANCELLED",
    "CLAIM_FAILED",
    "CLAIM_MEMORY",
    "CLAIM_MOTION",
    "CLAIM_PATTERNS",
    "CLAIM_PERCEPTION",
    "CLAIM_QUEUED",
    "CLAIM_RESUMED",
    "COVERAGE_CLAIMS",
    "FACTS",
    "FACT_ACCEPTED",
    "FACT_BLOCKED",
    "FACT_CANCELLED",
    "FACT_COMPLETED",
    "FACT_FAILED",
    "FACT_RESUMED",
    "FACT_RUNNING",
    "HEDGES",
    "INABILITY",
    "MATCHER_ID",
    "OFFER",
    "QUEUE_PENDING_STATUSES",
    "QUEUE_QUEUED",
    "QUEUE_SUSPENDED",
    "SUPPORTED_BY",
    "CapabilityRegistry",
    "InventedAction",
    "QueueRecordLike",
    "ReceiptLike",
    "TurnVerdict",
    "claim_supported",
    "default_registry",
    "extract_claims",
    "find_invented_actions",
    "normalise",
    "premature_arrival",
    "receipts_before",
    "score_turn",
]
