"""A conservative, deterministic router for final user transcripts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

from parcel_robot.navigation.goals import (
    navigation_directive_from_text,
    navigation_directive_is_blocked,
    semantic_goal_from_directive,
)
from parcel_robot.navigation.spatial import parse_spatial_intent
from parcel_robot.voice.closed_intents import (
    ClosedIntent,
    closed_intent_phrases,
    parse_closed_intent,
)

from .contracts import SCHEMA_VERSION, AffectEvidence, IntentFrame

ROUTER_VERSION = "deterministic-v1"

#: One stop grammar, shared with the closed-intent parser and the agent's fast
#: path. This used to be a third literal copy that omitted "halt" (U33).
_EMERGENCY_STOP = closed_intent_phrases(ClosedIntent.STOP)

#: Closed intents whose effect is an executive/CommandArbiter *cap* — no plan,
#: no admission, but a real change to what the robot is doing. Routing them
#: ``conversation_only`` (which is what "pause", "faster", and "slow down" got
#: until 2026-08-07) labels an executive command as chat: every consumer of
#: ``IntentFrame.route`` — metrics, the frozen router cases, any future
#: barge-in policy — then reads a pause as small talk. The agent has always
#: handled them correctly *before* consulting the route, so this changes the
#: frame's honesty, not the behaviour. Phrase membership is read from
#: ``parse_closed_intent``, so there is no second copy of the grammar.
_CAP_INTENTS = frozenset(
    {
        ClosedIntent.PAUSE,
        ClosedIntent.RESUME,
        ClosedIntent.FASTER,
        ClosedIntent.SLOWER,
    }
)
_FOLLOW = frozenset({"follow", "follow me", "come with me", "heel"})
_HOLD = frozenset({"stay", "wait", "wait here", "hold position"})
_STATUS = frozenset({"status", "get status", "how are your systems"})
_WALK = re.compile(r"^(?:(?:walk|go|move)\s+(?:forward|backward|back)|turn\s+(?:left|right)|walk)$")
_BACKEND = re.compile(r"^use\s+(?:vendor|sport|rl)(?:\s+backend)?$")
_CORRECTION = re.compile(
    r"^(?:actually|instead|no[, ]|change\s+(?:that|course)|correction\b|rather\b)"
)
# Route multi-action language before the semantic navigation parser can absorb
# a second action into one target label (for example ``store and wait
# outside``). The transcript stays authoritative; this expression only selects
# the deliberative route and never performs decomposition itself.
_COMPOUND = re.compile(r"\b(?:and(?:\s+then)?|then|after\s+(?:that|you)|before\s+you|while)\b")


def split_compound_clauses(text: str) -> list[str]:
    """Split a compound physical request into its ordered clauses.

    Cuts the transcript at the SAME ``_COMPOUND`` conjunctions the router
    matches to route a compound to the deliberative lane, so "detect" and
    "split" cannot disagree about what a compound is. It grounds nothing and
    compiles no plan — it exists so the no-planner fallback can NAME the parts
    ("go to the sidewalk", "sit") in a clarification instead of compiling the
    whole string as one literal destination label. Empty and
    pure-conjunction fragments are dropped; a string with no conjunction
    returns ``[itself]``.
    """

    clean = " ".join(str(text).strip().split())
    if not clean:
        return []
    clauses = [fragment.strip(" ,.;") for fragment in _COMPOUND.split(clean)]
    return [fragment for fragment in clauses if fragment] or [clean]


_QUESTION = re.compile(
    r"^(?:what|why|how|who|when|where|which|tell\s+me|explain|do\s+you|are\s+you)\b"
)
_GREETING = re.compile(
    r"^(?:hi|hello|hey|good\s+(?:morning|afternoon|evening)|thanks|thank\s+you|good\s+dog)[!. ]*$"
)
_PHYSICAL_CUE = re.compile(
    r"\b(?:walk(?:ed|ing)?|move|go|navigate|follow|heel|stay|wait|stand|sit|bow|pose|gesture|"
    r"circle|orbit|turn|back\s+away|come|run|stop|trot(?:ting|s)?|jog(?:ging|s)?|scoot(?:ing|s)?)\b"
)
_NON_AUTHORITATIVE = re.compile(
    r"(?:\b(?:do\s+not|don't|dont|never|imagine|hypothetical(?:ly)?)\b|"
    r"\bwhat\s+would\s+happen\s+if\b|\bif\s+you\b)"
)
_REQUEST_PREFIX = re.compile(
    r"^(?:please\b|can\s+you\b|could\s+you\b|would\s+you\b|will\s+you\b|"
    r"i\s+(?:want|need)\s+you\s+to\b|i(?:'d|\s+would)\s+like\s+you\s+to\b)"
)
_AFFECT = (
    (
        "sad",
        re.compile(
            r"\b(?:i\s+am|i'm|i\s+feel|i'm\s+feeling|i\s+am\s+feeling)\s+"
            r"(?:really\s+|very\s+)?(?:sad|down|upset|unhappy)\b"
        ),
    ),
    (
        "happy",
        re.compile(
            r"\b(?:i\s+am|i'm|i\s+feel|i'm\s+feeling|i\s+am\s+feeling)\s+"
            r"(?:really\s+|very\s+)?(?:happy|great|excited|joyful)\b"
        ),
    ),
)
_URGENCY_TERMS = ("dangerous", "danger", "urgent", "urgently", "immediately", "now")


class DeterministicIntentRouter:
    """Attach bounded routing metadata without paraphrasing the transcript.

    The router does not assign priority or generate actuator parameters.  It
    recognizes only reviewed, high-confidence grammars; ambiguous physical
    language is sent to plan mode and non-final ASR text is never actionable.
    """

    def __init__(self, skill_ids: Iterable[str] = ()):
        self._skill_ids = frozenset(str(item) for item in skill_ids)

    def route(
        self,
        transcript: str,
        *,
        turn_id: str,
        original_transcript_ref: str | None = None,
        is_final: bool = True,
    ) -> IntentFrame:
        if not isinstance(transcript, str):
            raise TypeError("transcript must be text")
        if not transcript.strip():
            raise ValueError("transcript must not be empty")
        if len(transcript) > 2_000:
            raise ValueError("transcript exceeds 2000 characters")

        clean = _normalize(transcript)
        transcript_ref = original_transcript_ref or f"turn:{turn_id}:final"
        digest = hashlib.sha256(transcript.encode("utf-8")).hexdigest()
        affect = _explicit_affect(clean)
        urgency = tuple(term for term in _URGENCY_TERMS if _word_present(clean, term))

        if not is_final:
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="clarify_or_abstain",
                confidence=1.0,
                speech_act="unknown",
                affect=affect,
                urgency=urgency,
                rule="non_final_transcript",
            )

        if clean in _EMERGENCY_STOP:
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="cancel",
                affect=affect,
                urgency=urgency,
                rule="emergency_stop",
            )

        blocked_motion = bool(
            (_NON_AUTHORITATIVE.search(clean) or navigation_directive_is_blocked(clean))
            and _PHYSICAL_CUE.search(clean)
        )
        if blocked_motion:
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="conversation_only",
                confidence=1.0,
                speech_act="question" if clean.endswith("?") else "statement",
                affect=affect,
                urgency=urgency,
                rule="non_authoritative_motion_mention",
            )

        # One amendment grammar. ``_CORRECTION`` and the closed-intent parser's
        # GOAL_AMEND regex overlapped but were not equal ("not that one", "the
        # other bench"), so the agent paused and replanned as an amendment while
        # the router had labelled the same turn ``conversation_only`` — the U33
        # route/registry mismatch again, one layer up. The union is what the
        # agent actually does.
        correction = bool(
            _CORRECTION.search(clean) or parse_closed_intent(clean) is ClosedIntent.GOAL_AMEND
        )
        compound = bool(_COMPOUND.search(clean) and _PHYSICAL_CUE.search(clean))
        if correction or compound:
            references = _spatial_references(clean)
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="deliberative_plan",
                confidence=0.98 if correction else 0.92,
                speech_act="correction" if correction else "request",
                affect=affect,
                urgency=urgency,
                spatial_references=references,
                requires_fresh_scene=bool(references or _PHYSICAL_CUE.search(clean)),
                rule="task_correction" if correction else "compound_physical_request",
            )

        if clean in _FOLLOW:
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="request",
                affect=affect,
                urgency=urgency,
                spatial_references=("owner",),
                requires_fresh_scene=True,
                rule="follow_owner",
            )
        # "Come here" is a reviewed closed grammar whose cap is a *system*
        # PlanSketch (``sketch_come`` → FollowFormation relation="follow").
        # Only ``direct_skill`` selects the system registry, and the system
        # registry is the only one that admits relation="follow" (arbitration
        # OB-2, validator.py `system_authored` gate). Routing these exact
        # phrases anywhere else validated a system-authored plan against the
        # model-facing registry and dead-ended every "come here" with the
        # generic refusal — the closed intent existed but was unreachable from
        # the product bar. Phrase membership comes from the closed-intent
        # parser, so there is no second copy of the grammar to drift.
        closed = parse_closed_intent(clean)
        if closed is ClosedIntent.COME:
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="request",
                affect=affect,
                urgency=urgency,
                spatial_references=("owner",),
                requires_fresh_scene=True,
                rule="come_to_owner",
            )
        if closed in _CAP_INTENTS:
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="request",
                affect=affect,
                urgency=urgency,
                # A cap needs no scene: it retimes or suspends work already
                # admitted against a snapshot, and demanding a fresh one would
                # make "pause" fail exactly when perception is degraded.
                requires_fresh_scene=False,
                rule=f"closed_intent:{closed.value}",
            )
        if clean in _HOLD:
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="request",
                affect=affect,
                urgency=urgency,
                rule="hold_position",
            )

        spatial = parse_spatial_intent(clean)
        if spatial is not None:
            owner_relative = (
                spatial.direction == "away_from_owner" or spatial.behavior == "orbit_owner"
            )
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="request",
                affect=affect,
                urgency=urgency,
                spatial_references=(("owner",) if owner_relative else ()),
                requires_fresh_scene=owner_relative,
                rule=("orbit_owner" if spatial.behavior == "orbit_owner" else "move_relative"),
            )

        if _WALK.fullmatch(clean):
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="request",
                affect=affect,
                urgency=urgency,
                rule="reviewed_walk_grammar",
            )

        if _BACKEND.fullmatch(clean):
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="request",
                affect=affect,
                urgency=urgency,
                rule="motion_backend_selection",
            )

        directive = navigation_directive_from_text(clean)
        if directive is not None:
            goal = semantic_goal_from_directive(directive)
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="request",
                affect=affect,
                urgency=urgency,
                spatial_references=(goal.query,),
                requires_fresh_scene=True,
                rule="navigation_directive",
            )

        skill = _named_skill(clean, self._skill_ids)
        if skill is not None:
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="request",
                affect=affect,
                urgency=urgency,
                rule=f"catalog_skill:{skill}",
            )
        if clean in _STATUS:
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="direct_skill",
                confidence=1.0,
                speech_act="question",
                affect=affect,
                urgency=urgency,
                rule="status_query",
            )

        if _PHYSICAL_CUE.search(clean):
            return self._frame(
                turn_id,
                transcript_ref,
                digest,
                route="deliberative_plan",
                confidence=0.70,
                speech_act="request" if _REQUEST_PREFIX.search(clean) else "unknown",
                affect=affect,
                urgency=urgency,
                spatial_references=_spatial_references(clean),
                requires_fresh_scene=True,
                rule="ambiguous_physical_request",
            )

        if _GREETING.fullmatch(clean):
            rule = "greeting"
        elif affect is not None:
            rule = "explicit_affect_statement"
        elif _QUESTION.search(clean) or clean.endswith("?"):
            rule = "conversation_question"
        else:
            rule = "conversation_default"
        return self._frame(
            turn_id,
            transcript_ref,
            digest,
            route="conversation_only",
            confidence=0.99,
            speech_act=(
                "question" if _QUESTION.search(clean) or clean.endswith("?") else "statement"
            ),
            affect=affect,
            urgency=urgency,
            rule=rule,
        )

    @staticmethod
    def _frame(
        turn_id: str,
        transcript_ref: str,
        digest: str,
        *,
        route: str,
        confidence: float,
        speech_act: str,
        affect: AffectEvidence | None,
        urgency: tuple[str, ...],
        rule: str,
        spatial_references: tuple[str, ...] = (),
        requires_fresh_scene: bool = False,
    ) -> IntentFrame:
        return IntentFrame(
            schema_version=SCHEMA_VERSION,
            turn_id=turn_id,
            route=route,
            confidence=confidence,
            speech_act=speech_act,
            affect_evidence=affect,
            spatial_references=spatial_references,
            urgency_cues=urgency,
            requires_fresh_scene=requires_fresh_scene,
            original_transcript_ref=transcript_ref,
            transcript_sha256=digest,
            router_version=ROUTER_VERSION,
            matched_rule=rule,
        )


def physical_cue_present(text: str) -> bool:
    """True when the transcript contains a reviewed physical-action verb.

    Exported so the agent's clarify-fallback can ask the *same* question the
    router asks, instead of keeping a second verb list that drifts. A novel
    verb ("befriend the bench") is exactly the case where this is False and a
    clarification is the honest reply.
    """

    return bool(_PHYSICAL_CUE.search(_normalize(text)))


def _normalize(value: str) -> str:
    translated = value.translate(
        str.maketrans(
            {
                "\N{LEFT SINGLE QUOTATION MARK}": "'",
                "\N{RIGHT SINGLE QUOTATION MARK}": "'",
                "\N{MODIFIER LETTER APOSTROPHE}": "'",
                "`": "'",
            }
        )
    )
    return " ".join(translated.strip().lower().split())


def _explicit_affect(text: str) -> AffectEvidence | None:
    for label, pattern in _AFFECT:
        if pattern.search(text):
            return AffectEvidence(label=label, confidence=1.0)
    return None


def _named_skill(text: str, skill_ids: frozenset[str]) -> str | None:
    match = re.fullmatch(
        r"(?:do|pose|show|run|perform)\s+(?:the\s+)?(.+?)(?:\s+pose|\s+skill|\s+action)?",
        text,
    )
    candidate = match.group(1).replace(" ", "_") if match else text.replace(" ", "_")
    return candidate if candidate in skill_ids else None


def _spatial_references(text: str) -> tuple[str, ...]:
    references: list[str] = []
    known = (
        ("sidewalk", r"\b(?:sidewalk|pavement)\b"),
        ("lamppost", r"\b(?:lamppost|lamp\s+post|streetlight|street\s+light)\b"),
        ("owner", r"\b(?:me|owner|the\s+owner)\b"),
        ("road", r"\b(?:road|street)\b"),
        ("store", r"\b(?:store|shop)\b"),
    )
    for label, pattern in known:
        if re.search(pattern, text):
            references.append(label)
    return tuple(references[:8])


def _word_present(text: str, term: str) -> bool:
    return bool(re.search(rf"\b{re.escape(term)}\b", text))
