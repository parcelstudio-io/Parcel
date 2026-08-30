"""The receipt-typed utterance contract: nine acts, one template each, a checker.

WHAT THIS MODULE IS
-------------------
MB-1 (``research/20260829/model-b-narration-1``) refuted free-form narration: a
hosted model given the plan queue and a speech act inferred facts nobody had
filed — grounding 0.61-0.73, 45 invented-action flags, and on the keys turn a
robot with no camera offering to look for the keys.  MB-2
(``research/20260829/model-b-contract-2``) answered it: stop asking a model for
the FACTS and ask it only, if at all, for the WORDING.  Arm T — templates, no
model, no network — scored grounding 1.000 / coverage 0.9688 / 0 invented / 15
of 15 capability refusals, at 0.12 ms a turn.

This module is that contract as product code, in three parts:

1. :class:`SpeechAct` — a typed act with slots, emitted from a receipt.  Nine
   acts, exactly the enum MB-2's ``DESIGN.md`` froze::

       ack(goal) · progress · blocked(class) · completed(goal)
       failed(goal, class) · cancelled · resumed(goal) · resume_offer(goal)
       capability_refusal(keys)

   plus one NON-speech row, :data:`ACT_ASK_CLARIFY`, which is the trigger
   table's ``clarify`` and is declared here rather than smuggled in: it carries
   no slots, licenses no claim, and is only ever a question.

2. :func:`render` — one deterministic template sentence per act.  English,
   short, first person, and never a word beyond the slots.  A few acts have a
   second rendering selected by a BOOLEAN SLOT (``queued`` for an acceptance
   that goes behind a running goal, ``resolved`` for a block the owner asks
   about after it cleared); the rendering is still a pure function of the act
   and its slots, and every one is listed in :data:`TEMPLATE_TABLE`.

3. :func:`check` — the post-condition checker.  Every navigation, arrival,
   perception, motion or action claim a candidate sentence makes must map to
   the triggering receipt's act + slots, or to the capability enum; and the
   sentence must still carry the content its acts promised.  Anything else is
   REJECT, with a reason from a closed enum.

WHY THE CHECKER IS BUILT OUT OF THE MATCHER, AND WHAT THAT COSTS
----------------------------------------------------------------
``extract_claims``, ``find_invented_actions``, ``score_turn``, ``normalise``,
``INABILITY`` and ``OFFER`` come from :mod:`parcel_robot.realtime.narration_matcher`,
which is MB-1's scorer ported character for character.  One consequence a reader
must keep in view, and MB-2's own ``RESULTS.md`` states plainly: **an arm gated
by this checker cannot fail the scorer's grounding or invented-action rows,
because the gate IS the scorer.**  The honest numbers for a gated arm are the
fallback rate, the rejection reasons, and the raw ungated candidates scored as
their own shadow arm.  Templates are a different case — arm T's rows are not
tautological, because the templates were written first and then measured.

The checker is stronger than the matcher in two ways the matcher cannot be:

* **slot fidelity.**  ``extract_claims`` sees the CLASS of a claim, not its
  referent: "I'm at the bench" and "I'm at the door" are the same arrival claim
  to it.  The checker requires every act's goal to survive the wording and
  refuses any OTHER known place name — a swapped destination is a rejection
  here and invisible there.
* **unlicensed numbers.**  A candidate that invents a distance or a duration is
  refused; no receipt in this vocabulary carries one.

WHAT IS NOT HERE
----------------
No paraphrase path and no local model: MB-2 measured an ungated paraphraser
deleting the "I have no camera" refusal 15 times out of 15, and its naturalness
row was UNMEASURED (a position-biased judge).  There is no demonstrated win to
install.  A paraphraser, if one ever lands, goes BEHIND :func:`check`.

Receipts are duck-typed for the reason
:mod:`parcel_robot.realtime.narration_matcher` gives: a receipt is anything with
``t``, ``fact``, ``goal``, ``event_id``, ``detail`` and ``queue``.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.realtime.narration_matcher import (
    CLAIM_ACCEPT,
    CLAIM_ARRIVAL,
    CLAIM_BLOCKED,
    CLAIM_CANCELLED,
    CLAIM_FAILED,
    CLAIM_MOTION,
    CLAIM_QUEUED,
    CLAIM_RESUMED,
    FACT_ACCEPTED,
    FACT_BLOCKED,
    FACT_CANCELLED,
    FACT_COMPLETED,
    FACT_FAILED,
    FACT_RESUMED,
    INABILITY,
    OFFER,
    QUEUE_PENDING_STATUSES,
    QUEUE_QUEUED,
    CapabilityRegistry,
    extract_claims,
    normalise,
    score_turn,
)

CONTRACT_ID = "mb2-utterance-contract-v1"

#: MB-2's ``DESIGN.md`` word cap, applied to every candidate the checker sees —
#: the templates included, so the contract's own floor is measured, not assumed.
#: The longest template in the table renders to 21 words.
MAX_WORDS = 25

# ------------------------------------------------------------------- the acts
ACT_ACK = "ack"
ACT_PROGRESS = "progress"
ACT_BLOCKED = "blocked"
ACT_COMPLETED = "completed"
ACT_FAILED = "failed"
ACT_CANCELLED = "cancelled"
ACT_RESUMED = "resumed"
ACT_RESUME_OFFER = "resume_offer"
ACT_CAPABILITY_REFUSAL = "capability_refusal"
#: Not one of the nine.  The trigger table has a ``clarify`` row and the corpus
#: has five clarification scenarios; this is that row, declared.
ACT_ASK_CLARIFY = "ask_clarify"

SPEECH_ACTS: tuple[str, ...] = (
    ACT_ACK,
    ACT_PROGRESS,
    ACT_BLOCKED,
    ACT_COMPLETED,
    ACT_FAILED,
    ACT_CANCELLED,
    ACT_RESUMED,
    ACT_RESUME_OFFER,
    ACT_CAPABILITY_REFUSAL,
)

#: Slot names each act may carry.  An act with an unknown slot is a wiring bug
#: and raises: the contract is the schema, not a suggestion.
ACT_SLOTS: dict[str, frozenset[str]] = {
    ACT_ACK: frozenset({"goal", "queued"}),
    ACT_PROGRESS: frozenset({"goal"}),
    ACT_BLOCKED: frozenset({"goal", "klass", "resolved"}),
    ACT_COMPLETED: frozenset({"goal"}),
    ACT_FAILED: frozenset({"goal", "klass"}),
    ACT_CANCELLED: frozenset({"goal"}),
    ACT_RESUMED: frozenset({"goal"}),
    ACT_RESUME_OFFER: frozenset({"goal"}),
    ACT_CAPABILITY_REFUSAL: frozenset({"keys"}),
    ACT_ASK_CLARIFY: frozenset({"question"}),
}

# ------------------------------------------------------- the capability enum
#: What this body CAN be asked to do.  The names below are the CLASSES a refusal
#: may cite, and each is a thing no receipt in this fact vocabulary can license.
CAP_VISION = "vision"
CAP_MANIPULATION = "manipulation"
CAP_POSITION_REPORT = "position_report"
CAP_MESSAGING = "messaging"
CAP_WORLD_CHANGE = "world_change"

CAPABILITY_KEYS: tuple[str, ...] = (
    CAP_VISION,
    CAP_MANIPULATION,
    CAP_POSITION_REPORT,
    CAP_MESSAGING,
    CAP_WORLD_CHANGE,
)

#: One refusal sentence per capability key.  Each states the inability in the
#: first person and offers nothing the body cannot do.  ``vision`` is the one
#: MB-1's corpus exercises (the keys turn); the others are declared so the enum
#: is the contract's, not the corpus's.
CAPABILITY_REFUSAL_TEXT: dict[str, str] = {
    CAP_VISION: "I have no camera, so I can't look for things.",
    CAP_MANIPULATION: "I have no way to pick anything up.",
    CAP_POSITION_REPORT: "I don't have a position to report.",
    CAP_MESSAGING: "I have no way to contact anyone.",
    CAP_WORLD_CHANGE: "I have no way to change anything in the room.",
}

#: The post-condition each refusal must still satisfy AFTER a rewording: the
#: inability has to survive it or the sentence is no longer a refusal.
#: ``vision`` uses the matcher's own pre-registered ``INABILITY`` — the same
#: instrument that scores the keys turn — so the contract cannot pass its own
#: bar with wording the matcher would not accept.
CAPABILITY_INABILITY: dict[str, re.Pattern[str]] = {
    CAP_VISION: INABILITY,
    CAP_MANIPULATION: re.compile(
        r"\b(?:no way to (?:pick|carry|hold|lift)|can'?t (?:pick|carry|hold|lift)|"
        r"(?:don'?t|do not) have (?:hands|a way to pick))", re.IGNORECASE
    ),
    CAP_POSITION_REPORT: re.compile(
        r"\b(?:(?:don'?t|do not) have (?:a |any )?position|no position|"
        r"can'?t (?:tell|say) (?:you )?(?:exactly )?where|"
        r"(?:don'?t|do not) know (?:exactly )?where)", re.IGNORECASE
    ),
    CAP_MESSAGING: re.compile(
        r"\b(?:no way to (?:contact|call|message|reach)|can'?t (?:contact|call|message|reach))",
        re.IGNORECASE,
    ),
    CAP_WORLD_CHANGE: re.compile(
        r"\b(?:no way to change|can'?t change|can'?t (?:open|move|turn))", re.IGNORECASE
    ),
}

#: Obstruction classes a ``blocked`` / ``failed`` act may cite.  Nothing else is
#: sayable, because nothing else is in a receipt.
CLASS_PERSON = "person"
CLASS_OBSTACLE = "obstacle"
BLOCK_CLASSES: tuple[str, ...] = (CLASS_PERSON, CLASS_OBSTACLE)


@dataclass(frozen=True, slots=True)
class SpeechAct:
    """One typed speech act with its slots.  The executive emits these."""

    act: str
    slots: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.act not in ACT_SLOTS:
            raise ValueError(f"unknown speech act {self.act!r}")
        unknown = set(self.slots) - ACT_SLOTS[self.act]
        if unknown:
            raise ValueError(f"{self.act} has no slot(s) {sorted(unknown)}")
        if self.act == ACT_CAPABILITY_REFUSAL:
            for key in self.slots.get("keys", ()):
                if key not in CAPABILITY_KEYS:
                    raise ValueError(f"{key!r} is not a capability key")
        if self.act in {ACT_BLOCKED, ACT_FAILED}:
            klass = self.slots.get("klass", CLASS_OBSTACLE)
            if klass not in BLOCK_CLASSES:
                raise ValueError(f"{klass!r} is not a block class")

    @property
    def goal(self) -> str:
        return str(self.slots.get("goal", "") or "")

    def as_dict(self) -> dict[str, object]:
        return {"act": self.act, "slots": dict(self.slots)}


# --------------------------------------------------------------- the templates
def _person_phrase(klass: str) -> str:
    return "Someone" if klass == CLASS_PERSON else "Something"


def render(act: SpeechAct) -> str:
    """The one deterministic sentence this act licenses.  Pure function."""

    slots = act.slots
    if act.act == ACT_ACK:
        if slots.get("queued"):
            return f"Okay, I'll check {act.goal} after that."
        return f"Okay, I'll head to {act.goal}."
    if act.act == ACT_PROGRESS:
        return f"I'm still on my way to {act.goal}."
    if act.act == ACT_BLOCKED:
        who = _person_phrase(str(slots.get("klass", CLASS_OBSTACLE)))
        if slots.get("resolved"):
            return f"{who} standing in the way held me up, so I waited."
        return f"{who} is in the way, so I'm waiting for it to clear."
    if act.act == ACT_COMPLETED:
        return f"I'm at {act.goal}."
    if act.act == ACT_FAILED:
        who = "a person" if slots.get("klass") == CLASS_PERSON else "something"
        return f"I couldn't get to {act.goal}, and {who} stayed in the way."
    if act.act == ACT_CANCELLED:
        return f"I've stopped, so {act.goal} is off the list."
    if act.act == ACT_RESUMED:
        return f"Okay, I'm picking that back up, and I'm on my way to {act.goal}."
    if act.act == ACT_RESUME_OFFER:
        return f"Shall I go to {act.goal} next?"
    if act.act == ACT_CAPABILITY_REFUSAL:
        keys = list(slots.get("keys", ()))
        return " ".join(CAPABILITY_REFUSAL_TEXT[key] for key in keys)
    if act.act == ACT_ASK_CLARIFY:
        return str(slots.get("question") or "Which one do you mean?")
    raise ValueError(f"no template for {act.act!r}")


#: The closing question a turn ends with when no ``resume_offer`` carries one.
#: It is not an act: it names nothing, claims nothing, and exists because the
#: trigger table asks an arrival and a failure to hand the floor back.
CLOSING_QUESTION = "What would you like next?"
CLOSING_QUESTION_FAILED = "What would you like to do instead?"


def compose(acts: Sequence[SpeechAct], *, closing: str = "") -> str:
    """The turn's sentence: its acts' templates in order, plus one closing."""

    parts = [render(act) for act in acts]
    if closing:
        parts.append(closing)
    return " ".join(part for part in parts if part).strip()


#: Every rendering the contract can produce, for the record.
TEMPLATE_TABLE: dict[str, str] = {
    "ack(goal)": "Okay, I'll head to {goal}.",
    "ack(goal, queued)": "Okay, I'll check {goal} after that.",
    "progress": "I'm still on my way to {goal}.",
    "blocked(class)": "{Someone|Something} is in the way, so I'm waiting for it to clear.",
    "blocked(class, resolved)": "{Someone|Something} standing in the way held me up, so I waited.",
    "completed(goal)": "I'm at {goal}.",
    "failed(goal, class)": "I couldn't get to {goal}, and {a person|something} stayed in the way.",
    "cancelled": "I've stopped, so {goal} is off the list.",
    "resumed(goal)": "Okay, I'm picking that back up, and I'm on my way to {goal}.",
    "resume_offer(goal)": "Shall I go to {goal} next?",
    "capability_refusal(vision)": CAPABILITY_REFUSAL_TEXT[CAP_VISION],
    "capability_refusal(position_report)": CAPABILITY_REFUSAL_TEXT[CAP_POSITION_REPORT],
    "capability_refusal(manipulation)": CAPABILITY_REFUSAL_TEXT[CAP_MANIPULATION],
    "capability_refusal(messaging)": CAPABILITY_REFUSAL_TEXT[CAP_MESSAGING],
    "capability_refusal(world_change)": CAPABILITY_REFUSAL_TEXT[CAP_WORLD_CHANGE],
    "ask_clarify": "{question from the steering policy}",
    "closing": CLOSING_QUESTION + " / " + CLOSING_QUESTION_FAILED,
}


@dataclass(frozen=True, slots=True)
class Utterance:
    """One turn's acts and its closing question, and the sentence they render to."""

    acts: tuple[SpeechAct, ...]
    closing: str = ""

    @property
    def text(self) -> str:
        return compose(self.acts, closing=self.closing)

    def as_dict(self) -> dict[str, object]:
        return {"acts": [act.as_dict() for act in self.acts], "closing": self.closing}


# ------------------------------------------------------- receipts to acts
#: Facts a receipt folded into an owner turn may contribute an act for.  A
#: progress tick is not one: "I'm still on my way" is not an answer to a
#: question the owner just asked.
FOLDABLE_FACTS: frozenset[str] = frozenset(
    {FACT_ACCEPTED, FACT_BLOCKED, FACT_COMPLETED, FACT_FAILED, FACT_CANCELLED, FACT_RESUMED}
)


def _block_class(detail: object) -> str:
    text = str(detail).lower()
    if "person" in text or "someone" in text or "somebody" in text:
        return CLASS_PERSON
    return CLASS_OBSTACLE


def _pending(queue: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(record for record in queue if record.status in QUEUE_PENDING_STATUSES)


def _record_for(receipt: Any) -> Any | None:
    for record in receipt.queue:
        if record.task_id == receipt.task_id:
            return record
    return None


def _ack(receipt: Any) -> Utterance:
    record = _record_for(receipt)
    queued = bool(record is not None and record.status == QUEUE_QUEUED)
    return Utterance((SpeechAct(ACT_ACK, {"goal": receipt.goal, "queued": queued}),))


def acts_for_receipt(receipt: Any) -> Utterance:
    """The act a receipt licenses, once something has decided it is spoken.

    WHEN to speak is not this module's business — it belongs to the whisperer's
    trigger table and band ledger.  This is the WHAT: given that a receipt has
    earned a turn, exactly one utterance is licensed by it.
    """

    if receipt.fact == FACT_COMPLETED:
        acts = [SpeechAct(ACT_COMPLETED, {"goal": receipt.goal})]
        pending = _pending(receipt.queue)
        if pending:
            acts.append(SpeechAct(ACT_RESUME_OFFER, {"goal": pending[0].goal}))
            return Utterance(tuple(acts))
        return Utterance(tuple(acts), CLOSING_QUESTION)
    if receipt.fact == FACT_BLOCKED:
        return Utterance(
            (
                SpeechAct(
                    ACT_BLOCKED,
                    {"goal": receipt.goal, "klass": _block_class(receipt.detail)},
                ),
            )
        )
    if receipt.fact == FACT_FAILED:
        return Utterance(
            (
                SpeechAct(
                    ACT_FAILED,
                    {"goal": receipt.goal, "klass": _block_class(receipt.detail)},
                ),
            ),
            CLOSING_QUESTION_FAILED,
        )
    if receipt.fact == FACT_CANCELLED:
        return Utterance((SpeechAct(ACT_CANCELLED, {"goal": receipt.goal}),), CLOSING_QUESTION)
    if receipt.fact == FACT_ACCEPTED:
        return _ack(receipt)
    if receipt.fact == FACT_RESUMED:
        return Utterance((SpeechAct(ACT_RESUMED, {"goal": receipt.goal}),))
    return Utterance((SpeechAct(ACT_PROGRESS, {"goal": receipt.goal}),))


def acts_for_owner_turn(
    *,
    keys_turn: bool,
    clarify_question: str,
    folded: Sequence[Any],
    prior: Sequence[Any],
) -> Utterance:
    """The reply to an owner turn: its own receipts, or an answer from the last.

    Four deterministic branches, in this order:

    1. a KEYS turn — a perception request this body cannot serve.  MB-1
       amendment M8's pre-registered behaviour is arrival + explicit inability +
       an offer, and the contract says it with ``completed(goal)`` +
       ``capability_refusal(vision)`` + the closing question;
    2. an ungrounded referent — the steering policy's clarify question, verbatim
       (a non-empty ``clarify_question`` IS that branch; the policy itself is the
       caller's, not this module's);
    3. the receipts folded into this turn, in order;
    4. and when there are none, an answer composed from the last terminal
       receipt (a cancellation, or a block the owner is asking about after it
       cleared).  When even that is empty the robot hands the floor back and
       claims nothing — which is a real turn with zero claims, not a silence.
    """

    if keys_turn:
        acts: list[SpeechAct] = []
        arrived = [receipt for receipt in prior if receipt.fact == FACT_COMPLETED]
        if arrived:
            acts.append(SpeechAct(ACT_COMPLETED, {"goal": arrived[-1].goal}))
        acts.append(SpeechAct(ACT_CAPABILITY_REFUSAL, {"keys": (CAP_VISION,)}))
        return Utterance(tuple(acts), CLOSING_QUESTION)

    if clarify_question:
        return Utterance((SpeechAct(ACT_ASK_CLARIFY, {"question": clarify_question}),))

    if folded:
        acts = []
        for receipt in folded:
            if receipt.fact not in FOLDABLE_FACTS:
                continue
            acts.extend(acts_for_receipt(receipt).acts)
        if acts:
            closing = CLOSING_QUESTION if any(a.act == ACT_CANCELLED for a in acts) else ""
            return Utterance(tuple(acts), closing)

    terminals = [
        receipt
        for receipt in prior
        if receipt.fact in {FACT_COMPLETED, FACT_FAILED, FACT_CANCELLED}
    ]
    if terminals and terminals[-1].fact == FACT_CANCELLED:
        return Utterance(
            (
                SpeechAct(ACT_CANCELLED, {"goal": terminals[-1].goal}),
                SpeechAct(ACT_CAPABILITY_REFUSAL, {"keys": (CAP_POSITION_REPORT,)}),
            ),
            CLOSING_QUESTION,
        )
    blocks = [receipt for receipt in prior if receipt.fact == FACT_BLOCKED]
    if blocks and terminals:
        block = blocks[-1]
        return Utterance(
            (
                SpeechAct(
                    ACT_BLOCKED,
                    {
                        "goal": block.goal,
                        "klass": _block_class(block.detail),
                        "resolved": True,
                    },
                ),
            )
        )
    return Utterance((), CLOSING_QUESTION)


# ---------------------------------------------------------------- the checker
#: Which claim CLASSES each act licenses.  A claim class outside the union of
#: the turn's acts is a claim the receipt never made.
LICENSED_CLAIMS: dict[str, frozenset[str]] = {
    ACT_ACK: frozenset({CLAIM_ACCEPT, CLAIM_MOTION}),
    ACT_PROGRESS: frozenset({CLAIM_MOTION}),
    ACT_BLOCKED: frozenset({CLAIM_BLOCKED}),
    ACT_COMPLETED: frozenset({CLAIM_ARRIVAL}),
    ACT_FAILED: frozenset({CLAIM_FAILED, CLAIM_BLOCKED}),
    ACT_CANCELLED: frozenset({CLAIM_CANCELLED}),
    ACT_RESUMED: frozenset({CLAIM_RESUMED, CLAIM_MOTION, CLAIM_ACCEPT}),
    ACT_RESUME_OFFER: frozenset(),
    ACT_CAPABILITY_REFUSAL: frozenset(),
    ACT_ASK_CLARIFY: frozenset(),
}

#: The ``queued`` slot licenses the one extra class its template needs.
_QUEUED_EXTRA = frozenset({CLAIM_QUEUED})

#: Acts whose goal must survive the wording.  ``blocked`` is absent on purpose:
#: its template names no place, and a candidate that adds one is caught by the
#: foreign-place rule below.
REQUIRE_GOAL: frozenset[str] = frozenset(
    {ACT_ACK, ACT_COMPLETED, ACT_FAILED, ACT_CANCELLED, ACT_RESUMED, ACT_RESUME_OFFER, ACT_PROGRESS}
)

REASON_EMPTY = "empty"
REASON_TOO_LONG = "too_long"
REASON_UNLICENSED_CLAIM = "claim_not_licensed_by_act"
REASON_UNSUPPORTED = "unsupported_claim"
REASON_INVENTED = "invented_action"
REASON_PREMATURE = "premature_arrival"
REASON_FOREIGN_PLACE = "foreign_place_name"
REASON_MISSING_GOAL = "missing_required_goal"
REASON_MISSING_INABILITY = "missing_inability_statement"
REASON_MISSING_OFFER = "missing_offer"
REASON_MISSING_QUESTION = "missing_question"
REASON_UNLICENSED_NUMBER = "unlicensed_number"

REJECTION_REASONS: tuple[str, ...] = (
    REASON_EMPTY,
    REASON_TOO_LONG,
    REASON_UNLICENSED_CLAIM,
    REASON_UNSUPPORTED,
    REASON_INVENTED,
    REASON_PREMATURE,
    REASON_FOREIGN_PLACE,
    REASON_MISSING_GOAL,
    REASON_MISSING_INABILITY,
    REASON_MISSING_OFFER,
    REASON_MISSING_QUESTION,
    REASON_UNLICENSED_NUMBER,
)

_DIGIT = re.compile(r"\d")


def bare_place(place: object) -> str:
    """A place name without its article, lowercased — "the bench" -> "bench"."""

    return str(place).strip().lower().removeprefix("the ").strip()


@dataclass
class CheckResult:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    claims: list[str] = field(default_factory=list)
    words: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "reasons": list(self.reasons),
            "claims": list(self.claims),
            "words": self.words,
        }


def check(
    text: str,
    *,
    acts: Sequence[SpeechAct],
    receipts: Sequence[Any],
    at_s: float,
    registry: CapabilityRegistry,
    places: Sequence[str],
    turn_index: int = 0,
    max_words: int = MAX_WORDS,
) -> CheckResult:
    """The post-condition checker.  PASS or REJECT, with closed-enum reasons.

    Order is fixed and cheap-first.  Every rule below is a POST-condition on the
    sentence, never a pre-condition on a generator: nothing here asks what a
    writer intended, only whether what it produced is licensed.

    ``places`` is the caller's place vocabulary — every name the body knows how
    to go to.  It is a required argument and not a default because an empty one
    silently disables the foreign-place rule, which is the rule that catches a
    swapped destination; a caller with no vocabulary must say so by passing an
    empty sequence, in writing, at the call site.
    """

    clean = normalise(text)
    reasons: list[str] = []
    if not clean:
        return CheckResult(False, [REASON_EMPTY], [], 0)

    words = len(clean.split())
    if words > max_words:
        reasons.append(f"{REASON_TOO_LONG}:{words}")

    # 1. every claim class must be licensed by one of the turn's acts.
    licensed: set[str] = set()
    for act in acts:
        licensed |= LICENSED_CLAIMS.get(act.act, frozenset())
        if act.act == ACT_ACK and act.slots.get("queued"):
            licensed |= _QUEUED_EXTRA
    claims = extract_claims(clean)
    for claim, _excerpt in claims:
        if claim not in licensed:
            reasons.append(f"{REASON_UNLICENSED_CLAIM}:{claim}")

    # 2. every claim must ALSO be supported by a receipt that had already fired,
    #    and the sentence must name no act this body cannot perform.  Both come
    #    from the matcher, unchanged, on a turn built exactly as it scores.
    scored = score_turn(
        clean, receipts=receipts, at_s=float(at_s), registry=registry, turn_index=turn_index
    )
    for claim, _why in scored.unsupported:
        reasons.append(f"{REASON_UNSUPPORTED}:{claim}")
    for item in scored.invented:
        reasons.append(f"{REASON_INVENTED}:{item.reason}")
    if scored.premature:
        reasons.append(REASON_PREMATURE)

    # 3. slot fidelity — the matcher cannot see referents, so the contract must.
    lowered = clean.lower()
    goals = {bare_place(act.goal) for act in acts if act.goal}
    for act in acts:
        if act.act in REQUIRE_GOAL and act.goal and bare_place(act.goal) not in lowered:
            reasons.append(f"{REASON_MISSING_GOAL}:{bare_place(act.goal)}")
    for name in sorted({bare_place(place) for place in places}):
        if name and name in lowered and name not in goals:
            reasons.append(f"{REASON_FOREIGN_PLACE}:{name}")

    # 4. the acts' own post-conditions must survive the wording.
    for act in acts:
        if act.act == ACT_CAPABILITY_REFUSAL:
            for key in act.slots.get("keys", ()):
                if not CAPABILITY_INABILITY[key].search(clean):
                    reasons.append(f"{REASON_MISSING_INABILITY}:{key}")
        elif act.act == ACT_RESUME_OFFER:
            if not OFFER.search(clean):
                reasons.append(REASON_MISSING_OFFER)
        elif act.act == ACT_ASK_CLARIFY and "?" not in clean:
            reasons.append(REASON_MISSING_QUESTION)

    # 5. no number the slots did not carry.  No receipt in this vocabulary has a
    #    distance or a duration, so any digit at all is invented here.
    if _DIGIT.search(clean) and not any(
        _DIGIT.search(str(value)) for act in acts for value in act.slots.values()
    ):
        reasons.append(REASON_UNLICENSED_NUMBER)

    return CheckResult(
        ok=not reasons,
        reasons=sorted(set(reasons)),
        claims=[claim for claim, _ in claims],
        words=words,
    )


__all__ = [
    "ACT_ACK",
    "ACT_ASK_CLARIFY",
    "ACT_BLOCKED",
    "ACT_CANCELLED",
    "ACT_CAPABILITY_REFUSAL",
    "ACT_COMPLETED",
    "ACT_FAILED",
    "ACT_PROGRESS",
    "ACT_RESUMED",
    "ACT_RESUME_OFFER",
    "ACT_SLOTS",
    "BLOCK_CLASSES",
    "CAPABILITY_INABILITY",
    "CAPABILITY_KEYS",
    "CAPABILITY_REFUSAL_TEXT",
    "CAP_MANIPULATION",
    "CAP_MESSAGING",
    "CAP_POSITION_REPORT",
    "CAP_VISION",
    "CAP_WORLD_CHANGE",
    "CLASS_OBSTACLE",
    "CLASS_PERSON",
    "CLOSING_QUESTION",
    "CLOSING_QUESTION_FAILED",
    "CONTRACT_ID",
    "FOLDABLE_FACTS",
    "LICENSED_CLAIMS",
    "MAX_WORDS",
    "REJECTION_REASONS",
    "REQUIRE_GOAL",
    "SPEECH_ACTS",
    "TEMPLATE_TABLE",
    "CheckResult",
    "SpeechAct",
    "Utterance",
    "acts_for_owner_turn",
    "acts_for_receipt",
    "bare_place",
    "check",
    "compose",
    "render",
]
