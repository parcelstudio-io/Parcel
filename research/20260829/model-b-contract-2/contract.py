"""MB-2 — the receipt-typed utterance contract.

WHAT THIS MODULE IS
-------------------
MB-1 refuted free-form narration: a hosted model given the plan queue and a
speech act inferred facts nobody had filed (grounding 0.61-0.73, 45
invented-action flags, 1/25 on the keys turn).  The recommendation both
verdicts reached was to stop asking a model for the FACTS and ask it only for
the WORDING.  This module is that contract, in three parts:

1. :class:`SpeechAct` — a typed act with slots, emitted by the executive from a
   receipt.  Nine acts, exactly the enum ``DESIGN.md`` freezes::

       ack(goal) · progress · blocked(class) · completed(goal)
       failed(goal, class) · cancelled · resumed(goal) · resume_offer(goal)
       capability_refusal(keys)

   plus one NON-speech row, :data:`ACT_ASK_CLARIFY`, which is MB-1's trigger
   table's ``clarify`` and is declared here rather than smuggled in: it carries
   no slots, licenses no claim, and is only ever a question.

2. :func:`render` — one deterministic template sentence per act.  English,
   short, first person, and never a word beyond the slots.  A few acts have a
   second rendering selected by a BOOLEAN SLOT (``queued`` for an acceptance
   that goes behind a running goal, ``resolved`` for a block the owner asks
   about after it cleared); the rendering is still a pure function of the act
   and its slots, and every one of them is listed in :data:`TEMPLATE_TABLE`.

3. :func:`check` — the post-condition checker.  Every navigation, arrival,
   perception, motion or action claim a candidate sentence makes must map to
   the triggering receipt's act + slots, or to the capability enum; and the
   sentence must still carry the content its acts promised.  Anything else is
   REJECT, with a reason from a closed enum.

WHY THE CHECKER REUSES MB-1's MATCHERS
--------------------------------------
``extract_claims``, ``find_invented_actions``, ``score_turn`` and ``normalise``
are imported from MB-1's scorer and used unchanged.  That has one consequence a
reader must keep in view and ``RESULTS.md`` states plainly: an arm gated by this
checker cannot fail the scorer's grounding or invented-action rows, because the
gate is the scorer.  The honest numbers for a checker-gated arm are therefore
(a) the FALLBACK RATE, (b) the rejection reasons, and (c) the RAW, ungated
paraphrases scored as their own shadow arm.  All three are published.

The checker is stronger than the scorer in two ways the scorer cannot be:

* **slot fidelity.**  ``extract_claims`` sees the CLASS of a claim, not its
  referent: "I'm at the bench" and "I'm at the door" are the same arrival claim
  to it.  The checker requires every act's goal to survive the wording and
  refuses any OTHER corpus place name — a swapped destination is a rejection
  here and invisible there.
* **unlicensed numbers.**  A paraphrase that invents a distance or a duration is
  refused; no receipt in the vocabulary carries one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from mb1 import ev, sc

CONTRACT_ID = "mb2-utterance-contract-v1"

#: ``DESIGN.md``'s ≤ 25 words, applied to every candidate the checker sees —
#: the templates included, so the contract's own floor is measured, not assumed.
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
#: Not one of the nine.  MB-1's trigger table has a ``clarify`` row and the
#: corpus has five clarification scenarios; this is that row, declared.
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
#: What this body CAN be asked to do.  Taken from the product's own broker enum
#: through MB-1's ``default_registry`` at call time; the names below are the
#: CLASSES a refusal may cite, and each one is a thing no receipt in the wave's
#: fact vocabulary can ever license.
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
#: the corpus exercises (the keys turn); the others are declared so the enum is
#: the contract's, not the corpus's.
CAPABILITY_REFUSAL_TEXT: dict[str, str] = {
    CAP_VISION: "I have no camera, so I can't look for things.",
    CAP_MANIPULATION: "I have no way to pick anything up.",
    CAP_POSITION_REPORT: "I don't have a position to report.",
    CAP_MESSAGING: "I have no way to contact anyone.",
    CAP_WORLD_CHANGE: "I have no way to change anything in the room.",
}

#: The post-condition each refusal must still satisfy AFTER a paraphrase: the
#: inability has to survive the rewording or the sentence is no longer a
#: refusal.  ``vision`` uses MB-1's own pre-registered ``INABILITY`` matcher —
#: the same instrument that scores the keys turn — so the contract cannot pass
#: its own bar with wording the scorer would not accept.
CAPABILITY_INABILITY: dict[str, object] = {
    CAP_VISION: sc.INABILITY,
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
    raise ValueError(f"no template for {act.act!r}")  # pragma: no cover


#: The closing question a turn ends with when no ``resume_offer`` carries one.
#: It is not an act: it names nothing, claims nothing, and exists because MB-1's
#: trigger table asks an arrival and a failure to hand the floor back.
CLOSING_QUESTION = "What would you like next?"
CLOSING_QUESTION_FAILED = "What would you like to do instead?"


def compose(acts: tuple[SpeechAct, ...], *, closing: str = "") -> str:
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
    "ask_clarify": "{question from steer.py}",
    "closing": CLOSING_QUESTION + " / " + CLOSING_QUESTION_FAILED,
}


# ---------------------------------------------------------------- the checker
#: Which of MB-1's claim CLASSES each act licenses.  A claim class outside the
#: union of the turn's acts is a claim the receipt never made.
LICENSED_CLAIMS: dict[str, frozenset[str]] = {
    ACT_ACK: frozenset({sc.CLAIM_ACCEPT, sc.CLAIM_MOTION}),
    ACT_PROGRESS: frozenset({sc.CLAIM_MOTION}),
    ACT_BLOCKED: frozenset({sc.CLAIM_BLOCKED}),
    ACT_COMPLETED: frozenset({sc.CLAIM_ARRIVAL}),
    ACT_FAILED: frozenset({sc.CLAIM_FAILED, sc.CLAIM_BLOCKED}),
    ACT_CANCELLED: frozenset({sc.CLAIM_CANCELLED}),
    ACT_RESUMED: frozenset({sc.CLAIM_RESUMED, sc.CLAIM_MOTION, sc.CLAIM_ACCEPT}),
    ACT_RESUME_OFFER: frozenset(),
    ACT_CAPABILITY_REFUSAL: frozenset(),
    ACT_ASK_CLARIFY: frozenset(),
}

#: The ``queued`` slot licenses the one extra class its template needs.
_QUEUED_EXTRA = frozenset({sc.CLAIM_QUEUED})

#: Acts whose goal must survive the wording.  ``blocked`` is absent on purpose:
#: its template names no place, and a paraphrase that adds one is caught by the
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


def _bare(place: str) -> str:
    return str(place).strip().lower().removeprefix("the ").strip()


def _all_places() -> tuple[str, ...]:
    return tuple(sorted({_bare(name) for name in ev.assert_places_admissible()}))


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
    acts: tuple[SpeechAct, ...],
    scenario: object,
    at_s: float,
    registry: object,
    turn_index: int = 0,
    max_words: int = MAX_WORDS,
) -> CheckResult:
    """The post-condition checker.  PASS or REJECT, with closed-enum reasons.

    Order is fixed and cheap-first.  Every rule below is a POST-condition on the
    sentence, never a pre-condition on the model: nothing here asks what the
    paraphraser intended, only whether what it produced is licensed.
    """

    clean = sc.normalise(text)
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
    claims = sc.extract_claims(clean)
    for claim, _excerpt in claims:
        if claim not in licensed:
            reasons.append(f"{REASON_UNLICENSED_CLAIM}:{claim}")

    # 2. every claim must ALSO be supported by a receipt that had already fired,
    #    and the sentence must name no act this body cannot perform.  Both come
    #    from MB-1's scorer, unchanged, on a turn built exactly as it scores.
    probe = sc.Turn(
        scenario_id=getattr(scenario, "scenario_id", ""),
        arm="checker",
        turn_index=turn_index,
        role="robot",
        text=clean,
        at_s=float(at_s),
        events_so_far=sc.events_so_far(scenario, float(at_s)),
    )
    scored = sc.score_turn(probe, scenario, registry)
    for claim, why in scored.unsupported:
        reasons.append(f"{REASON_UNSUPPORTED}:{claim}")
    for item in scored.invented:
        reasons.append(f"{REASON_INVENTED}:{item.reason}")
    if scored.premature:
        reasons.append(REASON_PREMATURE)

    # 3. slot fidelity — the scorer cannot see referents, so the contract must.
    lowered = clean.lower()
    goals = {_bare(act.goal) for act in acts if act.goal}
    for act in acts:
        if act.act in REQUIRE_GOAL and act.goal and _bare(act.goal) not in lowered:
            reasons.append(f"{REASON_MISSING_GOAL}:{_bare(act.goal)}")
    for place in _all_places():
        if place and place in lowered and place not in goals:
            reasons.append(f"{REASON_FOREIGN_PLACE}:{place}")

    # 4. the acts' own post-conditions must survive the wording.
    for act in acts:
        if act.act == ACT_CAPABILITY_REFUSAL:
            for key in act.slots.get("keys", ()):
                if not CAPABILITY_INABILITY[key].search(clean):
                    reasons.append(f"{REASON_MISSING_INABILITY}:{key}")
        elif act.act == ACT_RESUME_OFFER:
            if not sc.OFFER.search(clean):
                reasons.append(REASON_MISSING_OFFER)
        elif act.act == ACT_ASK_CLARIFY and "?" not in clean:
            reasons.append(REASON_MISSING_QUESTION)

    # 5. no number the slots did not carry.  No receipt in this vocabulary has
    #    a distance or a duration, so any digit at all is invented here.
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
    "BLOCK_CLASSES",
    "CAPABILITY_INABILITY",
    "CAPABILITY_KEYS",
    "CAPABILITY_REFUSAL_TEXT",
    "CLOSING_QUESTION",
    "CLOSING_QUESTION_FAILED",
    "CONTRACT_ID",
    "LICENSED_CLAIMS",
    "MAX_WORDS",
    "REJECTION_REASONS",
    "SPEECH_ACTS",
    "TEMPLATE_TABLE",
    "CheckResult",
    "SpeechAct",
    "check",
    "compose",
    "render",
]
