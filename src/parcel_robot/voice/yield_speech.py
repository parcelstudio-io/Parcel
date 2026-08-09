"""DialogueAct binding for the blocked-by-a-person yield policy.

The policy itself (timings, personality profiles, the authored templates and
their arrival-claim guard) lives in :mod:`parcel_robot.core.yield_policy`. This
module is the one place that turns a rendered line into a
:class:`~parcel_robot.contracts.v1.DialogueActV1`, so the truthfulness rules
are applied at exactly one seam.

**What a yielding dog may honestly claim.** The evidence available on a
person-gate tick is the gate itself: ``apply_collision_brake`` returned
``person_stop``, which means a person is inside the hard stop envelope and
translation was zeroed. That supports precisely two verified claims —

1. "a person is in my way", and
2. "I have stopped",

each carried with an ``evidence_ref`` naming the gate, as
:class:`DialogueClaimV1` requires for ``veracity="verified"``. It supports **no**
claim about arrival, about the person's intent, about whether help is coming,
or about what happens next — so the act carries nothing else, and
:func:`~parcel_robot.core.yield_policy.assert_truthful_yield_text` has already
refused any authored line that asserts one.
"""

from __future__ import annotations

from parcel_robot.contracts.v1 import DialogueActV1, DialogueClaimV1
from parcel_robot.core.yield_policy import assert_truthful_yield_text

from .dialogue_lane import dialogue_act_from_text

#: Evidence handle for every claim a yield utterance makes. Names the authority
#: (the collision gate) rather than a free-text justification.
YIELD_EVIDENCE_REF = "navigation:person_stop"

#: The two facts the person gate proves, and the only claims a yield act
#: carries. Both are stated in the first person and neither mentions the goal.
YIELD_BLOCKED_CLAIM = "A person is inside my stop distance."
YIELD_STOPPED_CLAIM = "I stopped and did not move past them."

#: ``ask`` / ``reask`` request an action from a human, so they set
#: ``asks_clarification``; ``give_up`` reports and asks for nothing.
YIELD_UTTERANCE_KINDS = ("ask", "reask", "give_up")


def yield_claims() -> tuple[DialogueClaimV1, ...]:
    """The verified claims a person-gate tick supports, and no others."""

    return (
        DialogueClaimV1(
            text=YIELD_BLOCKED_CLAIM,
            veracity="verified",
            evidence_ref=YIELD_EVIDENCE_REF,
        ),
        DialogueClaimV1(
            text=YIELD_STOPPED_CLAIM,
            veracity="verified",
            evidence_ref=YIELD_EVIDENCE_REF,
        ),
    )


def yield_dialogue_act(
    *,
    turn_id: str,
    text: str,
    kind: str,
    speech_style: str = "neutral",
) -> DialogueActV1:
    """Build the DialogueAct for one yield utterance, fail-closed.

    Raises ``ValueError`` when ``kind`` is unknown or when ``text`` claims an
    arrival or completion. Both are startup/authoring errors: no reachable
    runtime path can produce them once the config has loaded.
    """

    if kind not in YIELD_UTTERANCE_KINDS:
        raise ValueError(
            f"unknown yield utterance kind: {kind!r}; expected one of "
            f"{list(YIELD_UTTERANCE_KINDS)}"
        )
    clean = assert_truthful_yield_text(text, where=f"yield utterance ({kind})")
    return dialogue_act_from_text(
        turn_id=turn_id,
        text=clean,
        speech_style=speech_style,
        acknowledgement_kind="report" if kind == "give_up" else "request",
        asks_clarification=kind != "give_up",
        claims=yield_claims(),
        social_cues=("yield_to_person",),
    )


__all__ = [
    "YIELD_BLOCKED_CLAIM",
    "YIELD_EVIDENCE_REF",
    "YIELD_STOPPED_CLAIM",
    "YIELD_UTTERANCE_KINDS",
    "yield_claims",
    "yield_dialogue_act",
]
