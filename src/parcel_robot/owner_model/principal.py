"""WHO may write a durable owner fact — card OT-2, the DW-3 memory slice.

P2-A built the table, the policy and the door. It answered *what* the robot may
keep about its owner. It never asked the other half of the question, and the
half it never asked is the one an attacker (or a house guest, or a television)
walks through: **who is asking**.

Today's write path takes the model's word for it. ``remember_fact`` arrives
from the hosted lane, the deterministic privacy policy rules on the TEXT, and a
row lands with ``consent='granted'`` — whether the sentence came from the
enrolled owner, from somebody else in the room, from a voice the verifier ran on
and could not identify, or from a build where nobody has enrolled a voice at
all. P2-B made that distinction visible (``SpeakerLabel``: ``owner`` /
``not_owner`` / ``unverified`` / ``unenrolled`` / ``ungated``) and was careful to
give it no authority — "identity is a LABEL, not a gate" is that card's central
absolute, and it is right about **arming**: a robot that will not stop for a
stranger is a worse robot.

This module is where that label acquires exactly one power, and only one:

    an unverified voice may talk to the robot, may interrupt it, may STOP it —
    and may not silently create a durable, consented belief about its owner.

Nothing here refuses anything. A principal that may not GRANT may still
propose: the fact lands ``pending``, the model is told it landed pending and
why, and the owner can confirm it later through the confirmation door. That is
ask-over-refuse applied to memory rather than to motion, and it is the shape
this wave's rule 1 asks for.

WHAT IS NOT HERE, on purpose: this module reads nothing, writes nothing, opens
no store and imports no store. It is a pure decision over a typed value, so the
rule can be read in one screen and tested without a database.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Consent states, spelled here rather than imported from
#: :mod:`parcel_robot.owner_model.policy` so this module stays a leaf that the
#: policy, the broker and the runtime can all depend on without a cycle. A test
#: pins them equal to the policy's.
CONSENT_GRANTED = "granted"
CONSENT_PENDING = "pending"
CONSENT_DENIED = "denied"

#: The channel the request arrived on. Not a security claim by itself — it is
#: the context that makes a label readable ("unverified" means something
#: different on a keyboard than on a microphone).
CHANNEL_VOICE = "voice"
CHANNEL_TEXT = "text"
CHANNEL_DISTILLER = "distiller"
CHANNEL_API = "api"

#: P2-B's speaker labels, as this module's vocabulary. Duplicated for the same
#: leaf-module reason as the consent states, and pinned equal by a test.
LABEL_OWNER = "owner"
LABEL_NOT_OWNER = "not_owner"
LABEL_UNVERIFIED = "unverified"
LABEL_UNENROLLED = "unenrolled"
LABEL_UNGATED = "ungated"

#: THE RULE, as data. Read the table, not the code.
#:
#: * ``owner`` — the enrolled voice, verified on this turn. Grants.
#: * ``unenrolled`` — there is no check to run: nobody has enrolled a voice
#:   yet (``tools/enroll_owner_voice.py`` is still a pending owner action) and
#:   the voice gate arms everything in that state anyway. Grants, and that is a
#:   DECISION rather than an oversight: demoting every memory on a stock
#:   install would be a new fail-closed default, which this wave forbids, and
#:   it would make the feature useless on the only configuration that exists
#:   today. The honest reading is "single-user, unauthenticated" — the same
#:   trust a laptop with no password extends to whoever is sitting at it.
#: * ``unverified`` — the check RAN and abstained. This is the card's row. The
#:   robot heard a voice it could not attribute; a durable consented belief
#:   about the owner may not come from it.
#: * ``not_owner`` — verified, and it was somebody else. The strongest case.
#: * ``ungated`` — the emergency class, where identity was never consulted.
#:   Emergency traffic stops the dog; it does not teach it things.
GRANTING_LABELS: frozenset[str] = frozenset({LABEL_OWNER, LABEL_UNENROLLED})

#: Principal kinds, for the record and for the tool result the model reads.
KIND_OWNER_VERIFIED = "owner_verified"
KIND_OWNER_UNAUTHENTICATED = "owner_unauthenticated"
KIND_UNVERIFIED_AUDIO = "unverified_audio"
KIND_OTHER_SPEAKER = "other_speaker"
KIND_EMERGENCY = "emergency"
KIND_DISTILLER = "distiller"

_KIND_BY_LABEL: dict[str, str] = {
    LABEL_OWNER: KIND_OWNER_VERIFIED,
    LABEL_UNENROLLED: KIND_OWNER_UNAUTHENTICATED,
    LABEL_UNVERIFIED: KIND_UNVERIFIED_AUDIO,
    LABEL_NOT_OWNER: KIND_OTHER_SPEAKER,
    LABEL_UNGATED: KIND_EMERGENCY,
}

#: Why a downgrade happened, in the words the model should say back. One
#: sentence each, and each one names the thing the owner can do about it.
_DOWNGRADE_REASON: dict[str, str] = {
    KIND_UNVERIFIED_AUDIO: (
        "I could not verify whose voice that was, so I have written it down as "
        "unconfirmed rather than remembered it"
    ),
    KIND_OTHER_SPEAKER: (
        "that did not sound like my owner, so I have written it down as "
        "unconfirmed rather than remembered it"
    ),
    KIND_EMERGENCY: (
        "that came in on the emergency path, which I never learn from; it is "
        "written down as unconfirmed"
    ),
    KIND_DISTILLER: (
        "I worked that out myself rather than being told it, so it is written "
        "down as unconfirmed until my owner says otherwise"
    ),
}


@dataclass(frozen=True, slots=True)
class MemoryPrincipal:
    """WHO is asking for a durable owner fact to be written.

    Typed rather than a string because three separate facts decide the answer
    and folding them into one would be the same mistake ``OwnerTrack``'s bare
    ``confidence`` was: ``label`` (what the voice verifier concluded),
    ``channel`` (where the request came from) and ``verified`` (whether a check
    actually ran) are different questions with different failure modes.

    Frozen, slotted, and it carries no store handle, no session and no text —
    a principal is an identity, not a request.
    """

    kind: str
    label: str
    channel: str
    verified: bool
    enrolled: bool
    confidence: float = 0.0

    def __post_init__(self) -> None:
        for name in ("kind", "label", "channel"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"memory principal {name} must be a non-empty string")
        for name in ("verified", "enrolled"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"memory principal {name} must be a bool")
        confidence = self.confidence
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise TypeError("memory principal confidence must be numeric")
        object.__setattr__(self, "confidence", max(0.0, min(1.0, float(confidence))))

    @property
    def may_grant_consent(self) -> bool:
        """May a fact from this principal land ``granted`` without confirmation?

        The whole rule, in one expression, keyed on P2-B's label. The distiller
        is excluded structurally: it is built with a label of its own that is
        not in :data:`GRANTING_LABELS`, so "the model inferred it" can never
        become "the owner said it" by any route through this module.
        """

        return self.label in GRANTING_LABELS

    @property
    def may_confirm_consent(self) -> bool:
        """May this principal answer "yes, remember that" for a pending row?

        Deliberately the SAME set and not a wider one. Confirmation is the act
        that turns a parked belief into a kept one, so a voice that could not
        create a granted fact directly must not be able to create one in two
        steps either — that is the whole point of having a confirmation door at
        all rather than letting a repeat count as a yes.
        """

        return self.may_grant_consent

    def as_dict(self) -> dict[str, object]:
        """The record the tool result and the ledger carry. No text, ever."""

        return {
            "kind": self.kind,
            "label": self.label,
            "channel": self.channel,
            "verified": self.verified,
            "enrolled": self.enrolled,
            "confidence": round(float(self.confidence), 4),
        }


def principal_from_speaker_label(
    label: str,
    *,
    channel: str = CHANNEL_VOICE,
    confidence: float = 0.0,
) -> MemoryPrincipal:
    """Adapt one of P2-B's :data:`SPEAKER_LABELS` into a principal.

    An unknown label is treated as :data:`LABEL_UNVERIFIED` — not as an error
    and not as the owner. A label this module has not been taught about is
    exactly the state "the check ran and I cannot read the answer", and reading
    it as anything more generous would make adding a sixth label a silent
    privilege escalation.
    """

    clean = str(label).strip() or LABEL_UNVERIFIED
    if clean not in _KIND_BY_LABEL:
        clean = LABEL_UNVERIFIED
    return MemoryPrincipal(
        kind=_KIND_BY_LABEL[clean],
        label=clean,
        channel=str(channel).strip() or CHANNEL_VOICE,
        verified=clean in (LABEL_OWNER, LABEL_NOT_OWNER),
        enrolled=clean != LABEL_UNENROLLED,
        confidence=confidence,
    )


#: The distiller's principal. It proposes; it never states. Its label is not in
#: :data:`GRANTING_LABELS`, so every fact it writes is ``pending`` regardless of
#: what the policy said about the text — which is the shape HLD §8.4 asks for
#: ("a model may PROPOSE a memory fact") expressed as a type rather than as a
#: convention somebody has to remember.
DISTILLER_PRINCIPAL = MemoryPrincipal(
    kind=KIND_DISTILLER,
    label="distiller",
    channel=CHANNEL_DISTILLER,
    verified=False,
    enrolled=False,
    confidence=0.0,
)


@dataclass(frozen=True, slots=True)
class ConsentAdmission:
    """What the write path is allowed to store, and whether that was a downgrade."""

    consent: str
    downgraded: bool
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "consent": self.consent,
            "consent_downgraded": self.downgraded,
            "consent_downgrade_reason": self.reason,
        }


def admit_consent(principal: MemoryPrincipal, consent: str) -> ConsentAdmission:
    """The one function on the write path. Never raises, never refuses.

    ``granted`` from a principal that may not grant becomes ``pending``, with a
    reason that says so out loud. Everything else passes through untouched:
    this function can only ever move a fact toward "not yet", which is why it is
    safe to put it at the last point before the store rather than having to
    trust every caller to have already applied it.

    ``denied`` and ``pending`` are left alone deliberately — a principal that
    may not grant also may not *promote*, and it has nothing to gain by
    demoting a row that is already parked.
    """

    if not isinstance(principal, MemoryPrincipal):
        raise TypeError("admit_consent needs a MemoryPrincipal")
    verdict = str(consent)
    if verdict != CONSENT_GRANTED or principal.may_grant_consent:
        return ConsentAdmission(consent=verdict, downgraded=False, reason="")
    return ConsentAdmission(
        consent=CONSENT_PENDING,
        downgraded=True,
        reason=_DOWNGRADE_REASON.get(
            principal.kind,
            "I could not tell that it was my owner speaking, so it is written "
            "down as unconfirmed",
        ),
    )


#: What this module does NOT establish, kept beside the code that could be
#: mistaken for establishing it (the house convention, cf. ``uwb.fusion``).
DOES_NOT_PROVE = (
    (
        "This is an authorization rule over a voice LABEL, not authentication. "
        "P2-B's label is as good as the enrolled speaker profile behind it, and "
        "on this host no voice has been enrolled at all."
    ),
    (
        "A recording of the owner's voice would produce the `owner` label. "
        "Nothing here is anti-spoofing, and nothing here should be read as it."
    ),
    (
        "The `unenrolled` grant means a stock install trusts whoever is talking "
        "to it. That is a deliberate prototype decision (see GRANTING_LABELS), "
        "and it is the reason enrolling a voice is a real security act and not "
        "a convenience."
    ),
    (
        "Typed panel turns and the local (non-hosted) agent carry no voice "
        "verdict; they resolve to the `unenrolled` principal on the text "
        "channel, so the keyboard is trusted exactly as far as the room is."
    ),
)
