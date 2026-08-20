"""The Realtime companion's prompt plane: SI + DI (card R2-C, task_3).

WHAT THIS OWNS
--------------
The two halves of what a hosted session is *told*, and nothing else:

* **SI — the system instruction.** "You are a conversational companion
  quadruped friend…", the active personality out of ``prompts/personalities``,
  and the companion guardrails. It is *periodic*: it changes when a config
  changes (``si_profile``) or when an owner deliberately edits the text and
  bumps ``SI_VERSION``. It never changes because of where the robot is standing.
* **DI — the developer instruction.** Location, local time, who the owner is,
  and what was last talked about. It is *runtime*: a pure, deterministic render
  of a :class:`DeveloperFlags` snapshot taken from injected providers.

Both are versioned, and both hash. ``si_version`` + ``si_digest`` travel in
every corpus fixture and every ledger-facing provenance dict, so a transcript
can always be traced back to the exact words that produced it.

WHY THE SI DIGEST IS PINNED IN THIS FILE
----------------------------------------
"Changes periodically" is only a useful property if a change is *visible*. The
SI text is assembled from three places — this module's preamble, the personality
YAML, and ``lane.GUARDRAILS`` — so an edit to any one of them silently moves
what the model was told. :data:`SI_DIGESTS` pins the rendered digest per
version, ``tests/test_realtime_prompting.py`` asserts it, and the only way to
land an SI edit is to bump :data:`SI_VERSION` and register the new digests.
An edit without a bump is a red test, not a quiet drift.

WHY THE SI TEXT IS SELECTED BY VERSION (card R5, 2026-08-18)
------------------------------------------------------------
``si_version`` used to be a *label* travelling beside text that was always
whatever the tree said today. From v2 on it *selects* the text:
:func:`si_guardrails` maps a version to its guardrails, so
``render_system_instruction(version="si-companion-v1")`` still re-renders the
exact words the 25-thread corpus was captured under. That is what keeps an old
capture readable evidence rather than a grandfathered number — the v1 pins in
:data:`SI_DIGESTS` remain *reproducible from this tree*, not merely remembered.
An unregistered version is a refusal at render time, not a silent default.

WHY DI IS A PURE FUNCTION OF A SNAPSHOT
---------------------------------------
``render_developer_instruction`` takes :class:`DeveloperFlags` and returns text.
It reads no clock, no filesystem and no environment. Everything ambient is
gathered *once*, by :class:`DeveloperContext`, from callables the caller
injected — including the clock. That is what makes a scraped conversation
replayable: the fixture carries the flags, and re-rendering them offline in 2027
produces the same bytes it produced during the scrape.

WHEN DI ENTERS A SESSION — AND WHEN IT DOES NOT
-----------------------------------------------
At session OPEN, and at every rollover/reconnect. Never mid-session.

``RealtimeLane`` re-*sends* ``self.instructions`` inside ``_connect()``, which
runs on open, on rollover and on every reconnect. It does not re-*derive* them:
``instructions`` is a plain ``str`` attribute captured at construction. So the
mechanism here is :meth:`InstructionSource.refresh`, which assigns that public
attribute from a fresh render. A driver that calls ``refresh(lane)`` before each
``lane.tick()`` guarantees that whatever boundary ``tick()`` takes — rollover or
stall-reconnect — carries current DI, and costs one dictionary render per tick.

Mid-session DI *changes* are deliberately NOT instruction rewrites. Rewriting
``session.update`` mid-conversation invalidates the provider's prompt cache, and
the cached-input discount is the entire cost model for a lane that re-sends its
whole system prompt on every reconnect. A change that cannot wait rides as an
appended system conversation item; a change that can wait rides the next
boundary. This module renders; it never sends.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from parcel_robot.paths import resolve_prompts_root
from parcel_robot.prompting import PromptLibrary

from .lane import GUARDRAILS, build_instructions

#: The SI as the corpus was captured under it: ``lane.GUARDRAILS`` verbatim.
#: Still rendered, still pinned, so a v1 fixture stays verifiable forever.
SI_V1 = "si-companion-v1"

#: v2 (card R5, 2026-08-18). Two guardrail sentences superseded — see
#: :data:`TOOL_TURN_CADENCE` and :data:`ABILITY_WORDING`. Everything else,
#: including the preamble, the personalities and the DI contract, is unchanged.
SI_V2 = "si-companion-v2"

#: Bumped by hand whenever any SI ingredient changes. Registered in
#: :data:`SI_DIGESTS`; an unregistered version is a refusal, not a default.
SI_VERSION = SI_V2

#: Bumped by hand whenever the DI *layout* changes. Flag VALUES change every
#: session and are not a version event; the shape of the note is.
DI_VERSION = "di-companion-v1"

#: The owner's framing, verbatim in intent: a friend that happens to be a robot
#: dog. It leads the SI because everything after it is a qualification of it.
COMPANION_PREAMBLE = (
    "You are a conversational companion quadruped friend. "
    "You live with one owner, you walk beside them, and you talk with them. "
    "The conversation is the point; going somewhere is something you do "
    "together, not a task you complete on their behalf."
)

#: How the model must treat the developer note. This belongs in SI, not DI: it
#: is a standing rule about a channel, not a fact about today.
COMPANION_CONTRACT = (
    "A developer note may tell you where you are, the local time, who you are "
    "with, and what you last talked about. Treat it as true. "
    "Never read it aloud, never quote it back, and never invent a detail it "
    "does not contain. "
    "If it does not say something and you need it, ask."
)

#: ------------------------------------------------------------------ SI v2
#: Card R5. Two sentences of ``lane.GUARDRAILS`` produced two live defects, and
#: both are *wording*, not mechanism — which is why the fix lives here, in the
#: prompt plane, and ``lane.py`` is untouched. The v2 guardrails are the lane's
#: own text with exactly these two sentences replaced, so every OTHER rule
#: ("never narrate your own mechanics", "describe it; never decide it") is still
#: the lane's single copy rather than a fork.
#:
#: Defect 1 — the two-beat tool turn (owner, 2026-08-18 20:45): "Got it, I'll
#: head toward that sidewalk" then, one second later, "Okay, let's walk over
#: there together…". "Acknowledge a request before anything happens" told the
#: model to speak BEFORE the call; the response that follows the tool result
#: then said the same thing again, because nothing told it the announcement had
#: already happened.
SUPERSEDED_ACK_RULE = (
    "Acknowledge a request before anything happens, and never claim to have "
    "arrived anywhere or completed a physical action — the robot reports that "
    "itself. "
)

#: The replacement. Note what SURVIVES verbatim: "never claim to have arrived
#: anywhere or completed a physical action". That half of the old sentence was
#: never the defect and must not be lost in the rewrite.
#:
#: WHY THIS NAMES *WHICH* BEAT TO KEEP, RATHER THAN OFFERING A CHOICE
#: The card's wording — "either just before the call or in the reply that
#: follows the result" — was tried live first, verbatim, and the model took
#: BOTH beats anyway (2026-08-18 live session 1: "Okay, let me head that way
#: now." at 3.5 s, then "Okay, I'm on my way to the sidewalk…" at 5.0 s). A
#: choice is not a constraint when one lane forces a response: the lane sends
#: ``response.create`` after every tool result, so the post-result beat always
#: happens. The only beat the prompt can actually remove is the pre-call one —
#: and it is also the WRONG one to keep, because speaking before the call is
#: exactly "claiming an outcome the tools have not confirmed". So: act, then
#: speak once, about something that actually came back.
#:
#: The anti-examples are verbatim from the live runs ("Alright, let me head
#: toward the sidewalk…", "Let me head over to the sidewalk…"). An abstract
#: "do not announce it first" left the model emitting text in the same response
#: as the ``function_call``; naming the exact opening words it reaches for is
#: what the second live session said was missing. "One TURN, one spoken line"
#: (not "one action") covers the multi-tool turn, where the lane answers each
#: call and would otherwise buy one beat per tool.
TOOL_TURN_CADENCE = (
    "When you use one of your own systems, do not speak first: no \"let me…\", "
    "no \"I'll…\", no \"okay, heading there\". "
    "Use it, wait for what comes back, and then say ONE short thing about what "
    "actually came back. "
    "One turn, one spoken line — even when you used more than one system, and "
    "never a line before it and another after. "
    "When what comes back is not what was asked for, say plainly what actually "
    "happened; that is what the line after the result is for. "
    "Never claim to have arrived anywhere or completed a physical action — the "
    "robot reports that itself. "
)

#: Defect 2 — the inability over-claim (AUDIT_R16_R3_FABLE §Carry-forwards 2):
#: the model narrated "I can't physically move your way" in the same turn its
#: gesture executed. "Admit plainly what you cannot do" sat next to "never claim
#: a physical action" and the pair read as "you cannot act at all".
SUPERSEDED_ABILITY_RULE = "Admit plainly what you cannot do. "

#: The replacement. The rule is about OUTCOMES, not about ability: the robot
#: acts through its tools, and it must not disclaim the body it is standing in.
ABILITY_WORDING = (
    "You have a body and you act through its own systems, so never say you "
    "cannot move, walk, turn, look, or gesture. "
    "What you must not do is claim an outcome those systems have not reported "
    "yet; when something is refused or unavailable, say what stopped it. "
)

#: Fallbacks for a flag whose provider had nothing to say. Stated words, not an
#: empty string: an absent location must read as absent to the model, not as a
#: sentence that trails off.
UNKNOWN_LOCATION = "unknown"
UNKNOWN_OWNER = "the owner"

#: Longest history digest the DI will carry. The tail is a *reminder*, not the
#: transcript — ``RealtimeLane._inject_tail`` already replays real turns as
#: conversation items, and duplicating them here would pay for them twice.
MAX_HISTORY_LINES = 6

#: Longest owner-profile block. Same reasoning.
MAX_OWNER_NOTES = 6

#: Card R18. Longest sensor fact block the DI will carry. Short on purpose: the
#: block exists so the model knows the robot HAS perception and can say one true
#: sentence about its surroundings at a session boundary — it is not a scene
#: dump, and ``get_status`` is the thing that answers "right now".
MAX_SCENE_LINES = 6

#: Card R18, the honesty half, and the reason this header is a constant rather
#: than an f-string at the render site. live_run_1 F3 is a robot with LiDAR,
#: semantic regions and eight person tracks saying nothing at all when asked
#: what is around it; owner_session_1 F3 is the same robot claiming it "can't
#: actually see anything around me without a camera feed". Both directions are
#: wrong, and the block has to close both: it says the perception exists, it
#: says what KIND of perception it is so nothing visual is invented on top of
#: it, and it says the reading is a session-boundary snapshot so a model reading
#: it ten minutes later does not report it as the present.
SCENE_BLOCK_HEADER = (
    "What your sensors reported when this session opened (LiDAR ranges and a "
    "semantic map — you have NO camera, so never describe colours, faces, "
    "text or anything else that would need eyes; call get_status for what is "
    "around you right now):"
)

#: ``si_profile`` for a free-text persona (owner directive, 2026-08-18). It is
#: deliberately NOT a personality id: there is no file to look up and no
#: constant to pin, so attribution is carried by the per-session ``si_digest``
#: in the ledger and in every corpus fixture. :func:`si_pin` refuses it, which
#: is the correct answer — a free-text persona has no registered pin by design.
PERSONA_PROFILE_ID = "persona"

#: ``(first_hour, label)`` in ascending order; each entry runs until the next
#: one starts. Stated rather than computed, and deliberately not locale-aware,
#: so that "evening" means the same thing in a 2026 fixture and a 2027 replay.
TIME_OF_DAY_BOUNDS: tuple[tuple[int, str], ...] = (
    (5, "morning"),
    (12, "afternoon"),
    (17, "evening"),
    (21, "night"),
)

#: Before the first boundary — the small hours wrap back onto the last label.
TIME_OF_DAY_LATE = "night"


class PromptPlaneError(ValueError):
    """The prompt plane refused. Never a silent fallback to stale text."""


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean_lines(values: Sequence[str] | None, limit: int) -> tuple[str, ...]:
    """Whitespace-collapsed, blank-dropped, order-preserving, length-capped."""

    out: list[str] = []
    for value in values or ():
        text = " ".join(str(value).split())
        if text:
            out.append(text)
        if len(out) >= limit:
            break
    return tuple(out)


# ------------------------------------------------------------------------ SI
@dataclass(frozen=True)
class SystemInstruction:
    """One rendered SI, with the provenance a fixture has to carry."""

    profile_id: str
    version: str
    text: str

    @property
    def digest(self) -> str:
        return _digest(self.text)

    def provenance(self) -> dict[str, str]:
        return {
            "si_profile": self.profile_id,
            "si_version": self.version,
            "si_digest": self.digest,
        }


def default_prompt_library() -> PromptLibrary:
    """The repo's own prompt library, resolved the way the runtime resolves it."""

    return PromptLibrary(resolve_prompts_root())


def _supersede(base: str, *, old: str, new: str, what: str) -> str:
    """Replace one guardrail sentence, or refuse. Never a silent no-op.

    A ``str.replace`` that matches nothing would leave the DEFECTIVE sentence in
    the shipped v2 SI and change nothing else — the exact failure this card
    exists to end. So a miss is a :class:`PromptPlaneError`: if ``lane.py``
    rewords its guardrails, the next render says so by name instead of quietly
    shipping v2 text that still contains the v1 rule.
    """

    if old not in base:
        raise PromptPlaneError(
            f"SI {SI_V2} cannot supersede the {what} rule: lane.GUARDRAILS no "
            f"longer contains it verbatim. Re-derive the v2 guardrails against "
            f"the lane's current text (and bump SI_VERSION) rather than "
            f"shipping a supersession that silently matched nothing."
        )
    return base.replace(old, new)


def si_guardrails(version: str = SI_VERSION) -> str:
    """The guardrails block for one SI version. Unregistered ⇒ refusal.

    v1 is ``lane.GUARDRAILS`` verbatim — the corpus's words, re-renderable
    forever. v2 is the same text with :data:`SUPERSEDED_ACK_RULE` and
    :data:`SUPERSEDED_ABILITY_RULE` replaced.
    """

    if version == SI_V1:
        return GUARDRAILS
    if version == SI_V2:
        return _supersede(
            _supersede(
                GUARDRAILS,
                old=SUPERSEDED_ACK_RULE,
                new=TOOL_TURN_CADENCE,
                what="tool-turn cadence",
            ),
            old=SUPERSEDED_ABILITY_RULE,
            new=ABILITY_WORDING,
            what="ability wording",
        )
    raise PromptPlaneError(
        f"si_version {version!r} has no guardrails text. From v2 on the version "
        f"SELECTS the SI wording, so a new version must register its text here "
        f"and its digests in SI_DIGESTS; registered: {SI_V1}, {SI_V2}"
    )


def render_system_instruction(
    *,
    profile_id: str,
    library: PromptLibrary | None = None,
    version: str = SI_VERSION,
    persona_text: str | None = None,
) -> SystemInstruction:
    """Preamble + personality + reply style + guardrails + the DI contract.

    ``GUARDRAILS`` is imported from ``lane.py`` rather than restated. Two copies
    of "never claim to have arrived anywhere" is one copy too many: the lane's
    rule and the corpus's rule have to be the same sentence or the corpus stops
    being evidence about the lane. From v2 the block is
    :func:`si_guardrails`, which is still the lane's text — with exactly two
    named sentences superseded, and a refusal if either one stops matching.

    PERSONA AS PLAIN PROSE (owner directive, 2026-08-18)
    ----------------------------------------------------
    ``persona_text`` replaces the personality-profile block VERBATIM and skips
    the library lookup entirely, so a config can say

        persona: "You are a lively conversational agent that likes to go
                  around New York."

    and never author a YAML profile. What it replaces is exactly the personality
    — :data:`COMPANION_PREAMBLE`, :data:`GUARDRAILS` and
    :data:`COMPANION_CONTRACT` are not personality (they are what keeps a hosted
    voice honest about a physical robot) and ride along regardless of where the
    persona came from. A persona that could delete them would be a way to
    prompt the guardrails out of the session.

    ``persona_text=None`` is the profile path, byte-for-byte: same call, same
    ingredients, same digest, which is why the :data:`SI_DIGESTS` pins still
    hold. An empty or whitespace-only persona is a REFUSAL rather than a silent
    fall-back to the profile — "the persona key is present but says nothing" is
    a config the operator has to see.
    """

    if persona_text is not None:
        persona = str(persona_text).strip()
        if not persona:
            raise PromptPlaneError(
                "persona text is empty. A persona is prose the model is told "
                "verbatim; blank is not a personality, and silently falling "
                "back to a preset profile would hide the mistake."
            )
        body = build_instructions(personality=persona, guardrails=si_guardrails(version))
        text = f"{COMPANION_PREAMBLE}\n\n{body}\n\n{COMPANION_CONTRACT}"
        return SystemInstruction(profile_id=PERSONA_PROFILE_ID, version=version, text=text)

    resolved = library if library is not None else default_prompt_library()
    personality = resolved.personality(profile_id)
    body = build_instructions(
        personality=personality.instruction,
        reply_style=personality.reply_style,
        guardrails=si_guardrails(version),
    )
    text = f"{COMPANION_PREAMBLE}\n\n{body}\n\n{COMPANION_CONTRACT}"
    return SystemInstruction(profile_id=personality.id, version=version, text=text)


#: Rendered SI digests, per version, per personality. THE pin.
#:
#: Regenerate with ``python -m evals.companion.realtime_convo_v1.build_manifest
#: --print-si-digests`` after deliberately bumping :data:`SI_VERSION`.
#:
#: v1 STAYS registered after the v2 bump, and its digests are still the ones
#: this tree renders for ``version=SI_V1``. The 25-thread corpus was captured
#: under v1: dropping the row would make every fixture's ``si_digest`` an
#: unverifiable number, and re-scraping the corpus to chase a prompt edit would
#: throw away the only real transcripts this project has.
SI_DIGESTS: Mapping[str, Mapping[str, str]] = {
    SI_V1: {
        "calm_guardian": "008dd8ea80140d81869d293495a277cf4384b885727322102f78cbf9cac432ef",
        "gentle_companion": "418e6662efd60d0e35f3c4bd1715d902d03c4c2b3899b5da4d6257e8910e253d",
        "playful_companion": "ee40a44a45a4046e9ce72c8f40fac3b98854350df3a0cd65c0931667788774d5",
    },
    SI_V2: {
        "calm_guardian": "0268e2086f130bca0a29330454828e6b52883ec92779c0f6dbf782f76bbe6b17",
        "gentle_companion": "da7bcb0d0c7cd142d49e903692cbf94050478eadc69d312feb736128c251ca00",
        "playful_companion": "d0505f07a47ec41cfcffae6d019d5ee62079e8cf9992d1e0745d9f55ab543008",
    },
}


def si_pin(profile_id: str, *, version: str = SI_VERSION) -> str:
    """The pinned digest for one (version, profile). Unregistered ⇒ refusal."""

    pins = SI_DIGESTS.get(version)
    if pins is None:
        raise PromptPlaneError(
            f"si_version {version!r} has no registered digests. Bumping the "
            f"version is half the change; add its rendered digests to "
            f"SI_DIGESTS so the new text is pinned too."
        )
    digest = pins.get(profile_id)
    if digest is None:
        raise PromptPlaneError(
            f"si_version {version!r} has no pinned digest for personality "
            f"{profile_id!r}; registered: {', '.join(sorted(pins))}"
        )
    return digest


# ------------------------------------------------------------------------ DI
def time_of_day(moment: datetime) -> str:
    """Coarse part of day. A stated table, never a locale or a library."""

    hour = int(moment.hour)
    label = TIME_OF_DAY_LATE
    for bound, name in TIME_OF_DAY_BOUNDS:
        if hour >= bound:
            label = name
    return label


@dataclass(frozen=True)
class DeveloperFlags:
    """Everything ambient, captured once, as plain data.

    Frozen and JSON-shaped on purpose: this is the object a corpus fixture
    stores, and a fixture that stored a *callable* would not replay.
    """

    location: str = UNKNOWN_LOCATION
    local_time: str = ""
    part_of_day: str = ""
    owner_name: str = UNKNOWN_OWNER
    owner_notes: tuple[str, ...] = ()
    history_digest: tuple[str, ...] = ()
    #: Card R18. Sensor facts for the session boundary, already rendered as
    #: lines by whoever owns the perception state. Defaults to EMPTY, and an
    #: empty scene renders nothing at all — which is what keeps every
    #: pre-R18 flag set rendering byte-identically and ``DI_VERSION`` honest
    #: (see :func:`render_developer_instruction`).
    scene: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "location": self.location,
            "local_time": self.local_time,
            "part_of_day": self.part_of_day,
            "owner_name": self.owner_name,
            "owner_notes": list(self.owner_notes),
            "history_digest": list(self.history_digest),
            "scene": list(self.scene),
        }

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> DeveloperFlags:
        """Rebuild a snapshot from a fixture. Unknown keys are a refusal."""

        if not isinstance(payload, Mapping):
            raise PromptPlaneError(
                f"developer flags must be a mapping, got {type(payload).__name__}"
            )
        known = {
            "location",
            "local_time",
            "part_of_day",
            "owner_name",
            "owner_notes",
            "history_digest",
            "scene",
        }
        unknown = sorted(str(key) for key in payload if str(key) not in known)
        if unknown:
            raise PromptPlaneError(
                f"unknown developer flag(s): {', '.join(unknown)}; "
                f"allowed: {', '.join(sorted(known))}"
            )
        return cls(
            location=str(payload.get("location", UNKNOWN_LOCATION)),
            local_time=str(payload.get("local_time", "")),
            part_of_day=str(payload.get("part_of_day", "")),
            owner_name=str(payload.get("owner_name", UNKNOWN_OWNER)),
            owner_notes=_clean_lines(payload.get("owner_notes"), MAX_OWNER_NOTES),
            history_digest=_clean_lines(payload.get("history_digest"), MAX_HISTORY_LINES),
            scene=_clean_lines(payload.get("scene"), MAX_SCENE_LINES),
        )


@dataclass(frozen=True)
class DeveloperInstruction:
    """One rendered DI, plus the snapshot it was rendered from."""

    version: str
    text: str
    flags: DeveloperFlags

    @property
    def digest(self) -> str:
        return _digest(self.text)

    def provenance(self) -> dict[str, Any]:
        return {
            "di_version": self.version,
            "di_digest": self.digest,
            "di_flags": self.flags.as_dict(),
        }


def render_developer_instruction(
    flags: DeveloperFlags,
    *,
    version: str = DI_VERSION,
) -> DeveloperInstruction:
    """Flags in, text out. No clock, no filesystem, no environment.

    Field order is written out longhand rather than iterated, so that adding a
    flag is a deliberate layout change (and a :data:`DI_VERSION` bump) instead
    of a silent reordering of what the model reads first.

    CARD R18 AND THE VERSION THAT WAS NOT BUMPED. ``scene`` is appended LAST,
    after history, and renders **nothing whatsoever** when it is empty — which
    is every flag set that existed before this card, because there was no
    provider to fill it. So the rendered bytes for every pre-R18 input are
    unchanged, ``PINNED_DI_DIGEST`` still matches, and the 25 sealed
    ``evals/companion/realtime_convo_v1`` fixtures (whose ``di_version`` is
    asserted equal to :data:`DI_VERSION`, and whose DI digests are re-rendered
    from their own stored flags) stay verifiable. A bump would have
    invalidated all of them for a block none of them contains. The layout rule
    above is intact for every field it was written about; what this card adds
    is an appended, absent-by-default block, and the honest statement of that
    is here rather than in a version string that would have made 25 fixtures
    unreadable. (R18 §7 deviation 1.)
    """

    lines = [f"[developer note · {version}]"]
    lines.append(f"Location: {flags.location or UNKNOWN_LOCATION}")
    when = flags.local_time.strip()
    part = flags.part_of_day.strip()
    if when and part:
        lines.append(f"Local time: {when} ({part})")
    elif when:
        lines.append(f"Local time: {when}")
    elif part:
        lines.append(f"Local time: {part}")
    else:
        lines.append("Local time: unknown")
    lines.append(f"Owner: {flags.owner_name or UNKNOWN_OWNER}")
    if flags.owner_notes:
        lines.append("What you know about them:")
        lines.extend(f"- {note}" for note in flags.owner_notes)
    if flags.history_digest:
        lines.append("What you last talked about:")
        lines.extend(f"- {item}" for item in flags.history_digest)
    if flags.scene:
        lines.append(SCENE_BLOCK_HEADER)
        lines.extend(f"- {item}" for item in flags.scene)
    return DeveloperInstruction(version=version, text="\n".join(lines), flags=flags)


class DeveloperContext:
    """Gathers the ambient flags from injected providers. The only impure part.

    Every source is a callable the caller supplied — including the clock. There
    is no default that reads ``datetime.now()``: a caller who wants wall time
    passes ``clock=datetime.now`` and owns that choice, and a test or a replay
    passes a fixed instant and gets byte-identical text forever.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], datetime],
        location: Callable[[], str] | None = None,
        owner_name: str = UNKNOWN_OWNER,
        owner_notes: Callable[[], Sequence[str]] | None = None,
        history: Callable[[], Sequence[str]] | None = None,
        scene: Callable[[], Sequence[str]] | None = None,
        time_format: str = "%Y-%m-%d %H:%M",
    ) -> None:
        self._clock = clock
        self._location = location
        self._owner_name = owner_name
        self._owner_notes = owner_notes
        self._history = history
        #: Card R18. A perception provider, i.e. a SENSOR — and it obeys the
        #: same rule the location sensor already does: a provider that raises
        #: yields no block at all, never a fabricated one. A robot that says
        #: nothing about its surroundings is honest; a robot that says
        #: something it did not measure is F3 in the other direction.
        self._scene = scene
        self._time_format = time_format

    def flags(self) -> DeveloperFlags:
        """One snapshot. A provider that raises yields the stated unknown."""

        moment = self._clock()
        if not isinstance(moment, datetime):
            raise PromptPlaneError(
                f"developer-context clock must return a datetime, got {type(moment).__name__}"
            )
        return DeveloperFlags(
            location=self._call_text(self._location, UNKNOWN_LOCATION),
            local_time=moment.strftime(self._time_format),
            part_of_day=time_of_day(moment),
            owner_name=self._owner_name or UNKNOWN_OWNER,
            owner_notes=_clean_lines(self._call_lines(self._owner_notes), MAX_OWNER_NOTES),
            history_digest=_clean_lines(self._call_lines(self._history), MAX_HISTORY_LINES),
            scene=_clean_lines(self._call_lines(self._scene), MAX_SCENE_LINES),
        )

    @staticmethod
    def _call_text(provider: Callable[[], str] | None, fallback: str) -> str:
        if provider is None:
            return fallback
        try:
            value = " ".join(str(provider()).split())
        except (RuntimeError, TypeError, ValueError, OSError):
            # A location provider is a sensor. A sensor that fails must make
            # the model say "I am not sure where we are", never crash a turn.
            return fallback
        return value or fallback

    @staticmethod
    def _call_lines(provider: Callable[[], Sequence[str]] | None) -> Sequence[str]:
        if provider is None:
            return ()
        try:
            return list(provider())
        except (RuntimeError, TypeError, ValueError, OSError):
            return ()


def history_digest_from_turns(
    rows: Sequence[Mapping[str, Any]],
    *,
    limit: int = MAX_HISTORY_LINES,
    width: int = 120,
) -> tuple[str, ...]:
    """Ledger tail → short "owner said / you said" reminders, newest last.

    Deliberately lossy. ``RealtimeLane._inject_tail`` already replays the real
    turns as conversation items; this is the one-line-per-turn gist that makes
    the DI readable, and paying full token price for the same text twice is the
    thing it exists to avoid.
    """

    lines: list[str] = []
    for row in rows:
        speaker = str(row.get("speaker") or row.get("role") or "").strip().lower()
        content = " ".join(str(row.get("content") or row.get("text") or "").split())
        if not content:
            continue
        if speaker in {"owner", "user"}:
            who = "they said"
        elif speaker in {"robot", "assistant"}:
            who = "you said"
        else:
            continue
        if len(content) > width:
            content = content[: width - 1].rstrip() + "…"
        lines.append(f"{who}: {content}")
    return tuple(lines[-limit:])


# ------------------------------------------------------------------- session
class InstructionSink(Protocol):
    """The one attribute :meth:`InstructionSource.refresh` writes.

    ``RealtimeLane`` satisfies it. Stated as a Protocol so this module never
    has to import the lane's class or know anything else about it.
    """

    instructions: str


@dataclass(frozen=True)
class SessionInstructions:
    """What one hosted session is told, and how to prove it later."""

    si: SystemInstruction
    di: DeveloperInstruction

    @property
    def text(self) -> str:
        return f"{self.si.text}\n\n{self.di.text}"

    @property
    def digest(self) -> str:
        return _digest(self.text)

    def provenance(self) -> dict[str, Any]:
        return {
            **self.si.provenance(),
            **self.di.provenance(),
            "instructions_digest": self.digest,
        }


def render_session_instructions(
    *,
    profile_id: str,
    flags: DeveloperFlags,
    library: PromptLibrary | None = None,
    si_version: str = SI_VERSION,
    di_version: str = DI_VERSION,
    persona_text: str | None = None,
) -> SessionInstructions:
    """SI over DI, in that order, for one session open."""

    return SessionInstructions(
        si=render_system_instruction(
            profile_id=profile_id,
            library=library,
            version=si_version,
            persona_text=persona_text,
        ),
        di=render_developer_instruction(flags, version=di_version),
    )


class InstructionSource:
    """A re-renderable SI+DI for one lane. Renders; never sends.

    ``current()`` is pure enough to call on every tick: it re-reads the injected
    providers and re-renders text. ``refresh(lane)`` writes the result onto the
    lane's public ``instructions`` attribute, which ``_connect()`` reads at every
    session open, rollover and reconnect — so the value present at the moment of
    a boundary is the value that boundary sends, and nothing changes mid-session.
    """

    def __init__(
        self,
        *,
        profile_id: str,
        context: DeveloperContext,
        library: PromptLibrary | None = None,
        si_version: str = SI_VERSION,
        di_version: str = DI_VERSION,
        persona_text: str | None = None,
    ) -> None:
        self.profile_id = profile_id
        self.context = context
        self.si_version = si_version
        self.di_version = di_version
        #: Free-text persona from config, or ``None`` for the preset profile.
        self.persona_text = persona_text
        self._library = library if library is not None else default_prompt_library()
        self.renders = 0

    def current(self) -> SessionInstructions:
        self.renders += 1
        return render_session_instructions(
            persona_text=self.persona_text,
            profile_id=self.profile_id,
            flags=self.context.flags(),
            library=self._library,
            si_version=self.si_version,
            di_version=self.di_version,
        )

    def refresh(self, lane: InstructionSink) -> bool:
        """Point the lane at fresh text. True when the text actually moved."""

        rendered = self.current().text
        changed = rendered != getattr(lane, "instructions", None)
        lane.instructions = rendered
        return changed


def prompts_root() -> Path:
    """Where :func:`default_prompt_library` reads from. Exposed for status docs."""

    return resolve_prompts_root()


__all__ = [
    "ABILITY_WORDING",
    "COMPANION_CONTRACT",
    "COMPANION_PREAMBLE",
    "DI_VERSION",
    "MAX_HISTORY_LINES",
    "MAX_OWNER_NOTES",
    "MAX_SCENE_LINES",
    "PERSONA_PROFILE_ID",
    "SCENE_BLOCK_HEADER",
    "SI_DIGESTS",
    "SI_V1",
    "SI_V2",
    "SI_VERSION",
    "SUPERSEDED_ABILITY_RULE",
    "SUPERSEDED_ACK_RULE",
    "TIME_OF_DAY_BOUNDS",
    "TOOL_TURN_CADENCE",
    "UNKNOWN_LOCATION",
    "UNKNOWN_OWNER",
    "DeveloperContext",
    "DeveloperFlags",
    "DeveloperInstruction",
    "InstructionSink",
    "InstructionSource",
    "PromptPlaneError",
    "SessionInstructions",
    "SystemInstruction",
    "default_prompt_library",
    "history_digest_from_turns",
    "prompts_root",
    "render_developer_instruction",
    "render_session_instructions",
    "render_system_instruction",
    "si_guardrails",
    "si_pin",
    "time_of_day",
]
