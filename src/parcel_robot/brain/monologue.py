"""The inner-monologue tick contract: one world digest in, one decision out.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
``brain/`` is deterministic by design — nothing here calls a model at control
rate, and this module keeps that rule. It holds two frozen value types and a
fail-closed parser, nothing else:

* :class:`WorldDigestV1` — the bounded snapshot a cognition tick is allowed to
  see (robot state, the last three noticings, dialogue state, drive levels,
  how long since the owner last spoke). It renders to a compact text block
  whose size is *bounded by construction* (:data:`MAX_RENDERED_CHARS`), so a
  digest can never grow into a prompt-budget incident.
* :class:`MonologueDecisionV1` — one typed decision:
  ``ignore | remark | look | go_check | ask``, with a one-line reason and a
  confidence. Nothing in it is an authority: a decision is a *proposal* that
  still has to pass the runtime's existing admission doors (the curiosity
  door for ``remark``, plan acceptance for ``go_check``). This module grants
  no permission to anything.

The tick that produces these lives OUTSIDE the 10 Hz control loop — it is a
1 Hz-class cognition thread. Nothing in the shipped runtime imports this
module today; it is the typed seam H2 measured and H3 (drives) consumes, and
:func:`monologue_enabled` is the door any future wiring must ask, defaulting
to OFF.

WHY THE PARSE IS FAIL-CLOSED
----------------------------
The producer is a language model constrained by a JSON schema, which means
"usually the right shape". A decision that is off-shape has produced no
evidence about what the dog should do, and a parser that repairs it invents
one. So every violation raises :class:`MonologueParseError`; there is no
default decision, not even ``ignore``. A caller that wants "stay quiet when
the model misbehaves" must write that policy itself, in the open, and count
it — which is exactly the number an annoyance budget needs.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

#: The decision vocabulary. Closed on purpose: a new kind is a design change
#: with an admission door behind it, never a string a model may invent.
DECISION_KINDS = ("ignore", "remark", "look", "go_check", "ask")

#: Kinds that must carry spoken text, and kinds that must not.
SPEAKING_KINDS = frozenset({"remark", "ask"})
SILENT_KINDS = frozenset({"ignore", "look", "go_check"})

#: Text the dog would say. 140 characters is roughly one spoken breath at the
#: companion cadence; longer is a monologue, not a remark.
MAX_TEXT_CHARS = 140
#: One line of justification, for the decision log the owner can read.
MAX_REASON_CHARS = 200
#: A target names a place, an object or a bearing — never a sentence.
MAX_TARGET_CHARS = 64

#: Hard ceiling on the rendered digest. The DESIGN budgets 600 tokens; at the
#: ~3.6 chars/token this renderer measures on its own vocabulary, 2,000 chars
#: is comfortably inside it and is checked, not hoped for.
MAX_RENDERED_CHARS = 2_000
#: Chars per token used by :meth:`WorldDigestV1.estimated_tokens`. An estimate
#: and named as one: the exact count belongs to the server's tokenizer.
CHARS_PER_TOKEN = 3.6

#: At most three noticings reach a tick. The fourth is not more context, it is
#: a slower tick and a model that averages instead of choosing.
MAX_NOTICINGS = 3
#: Drive names the digest renders, in this order. Unknown drives are refused
#: rather than passed through: a drive the tick cannot interpret is noise.
DRIVE_NAMES = ("curiosity", "social", "vigilance", "rest")

#: Environment door for any future runtime wiring. Defaults OFF.
MONOLOGUE_FLAG_ENV = "PARCEL_MONOLOGUE_TICK"


class MonologueParseError(ValueError):
    """A model reply was not a decision. No decision is produced."""


def monologue_enabled(environ: dict[str, str] | None = None) -> bool:
    """Whether a runtime may run monologue ticks. OFF unless explicitly set."""

    source = os.environ if environ is None else environ
    return str(source.get(MONOLOGUE_FLAG_ENV, "")).strip().lower() in {"1", "true", "yes", "on"}


def _clean(value: object, *, field_name: str, limit: int) -> str:
    if not isinstance(value, str):
        raise MonologueParseError(f"{field_name} must be a string, got {type(value).__name__}")
    text = " ".join(value.split())
    if len(text) > limit:
        raise MonologueParseError(f"{field_name} exceeds {limit} characters ({len(text)})")
    return text


def _finite(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MonologueParseError(f"{field_name} must be a number, got {type(value).__name__}")
    number = float(value)
    if not math.isfinite(number):
        raise MonologueParseError(f"{field_name} must be finite")
    return number


@dataclass(frozen=True, slots=True)
class Noticing:
    """One thing the perception loop flagged, as the tick is allowed to see it."""

    label: str
    bearing_deg: float
    distance_m: float
    novelty: float
    age_s: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "label", _clean(self.label, field_name="label", limit=48))
        if not self.label:
            raise MonologueParseError("a noticing needs a label")
        for name in ("bearing_deg", "distance_m", "novelty", "age_s"):
            object.__setattr__(self, name, _finite(getattr(self, name), field_name=name))
        if not -180.0 <= self.bearing_deg <= 180.0:
            raise MonologueParseError("noticing bearing_deg must be within [-180, 180]")
        if self.distance_m < 0.0 or self.age_s < 0.0:
            raise MonologueParseError("noticing distance_m and age_s must be non-negative")
        if not 0.0 <= self.novelty <= 1.0:
            raise MonologueParseError("noticing novelty must be within [0, 1]")

    def render(self) -> str:
        return (
            f"{self.label} @ {self.bearing_deg:+.0f}deg {self.distance_m:.1f}m "
            f"novelty {self.novelty:.2f} age {self.age_s:.1f}s"
        )


@dataclass(frozen=True, slots=True)
class WorldDigestV1:
    """The bounded world snapshot one monologue tick may reason over."""

    at_s: float = 0.0
    place: str = "unknown"
    posture: str = "standing"
    moving: bool = False
    nav_state: str = "idle"
    battery_percent: float = 100.0
    emergency_stopped: bool = False
    owner_present: bool = False
    owner_speaking: bool = False
    lane_busy: bool = False
    quiet_hours: bool = False
    #: ``None`` means the owner has not spoken this session — not "long ago".
    last_owner_turn_age_s: float | None = None
    last_robot_utterance_age_s: float | None = None
    noticings: tuple[Noticing, ...] = ()
    drives: tuple[tuple[str, float], ...] = ()
    recent_actions: tuple[str, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(self, "at_s", _finite(self.at_s, field_name="at_s"))
        for name, limit in (("place", 48), ("posture", 24), ("nav_state", 32)):
            cleaned = _clean(getattr(self, name), field_name=name, limit=limit)
            object.__setattr__(self, name, cleaned)
        object.__setattr__(
            self, "battery_percent", _finite(self.battery_percent, field_name="battery_percent")
        )
        for name in ("last_owner_turn_age_s", "last_robot_utterance_age_s"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite(value, field_name=name))
        if len(self.noticings) > MAX_NOTICINGS:
            raise MonologueParseError(f"a digest carries at most {MAX_NOTICINGS} noticings")
        object.__setattr__(self, "noticings", tuple(self.noticings))
        drives = tuple(
            (str(name), _finite(level, field_name=f"drive {name}"))
            for name, level in self.drives
        )
        for name, level in drives:
            if name not in DRIVE_NAMES:
                raise MonologueParseError(f"unknown drive {name!r}; known: {DRIVE_NAMES}")
            if not 0.0 <= level <= 1.0:
                raise MonologueParseError(f"drive {name} must be within [0, 1]")
        object.__setattr__(self, "drives", drives)
        object.__setattr__(
            self,
            "recent_actions",
            tuple(
                _clean(item, field_name="recent action", limit=48)
                for item in self.recent_actions
            ),
        )

    def render(self) -> str:
        """Compact text for the prompt. Bounded by :data:`MAX_RENDERED_CHARS`."""

        owner_age = (
            "never" if self.last_owner_turn_age_s is None else f"{self.last_owner_turn_age_s:.0f}s"
        )
        self_age = (
            "never"
            if self.last_robot_utterance_age_s is None
            else f"{self.last_robot_utterance_age_s:.0f}s"
        )
        noticings = (
            "\n".join(
                f"  {index + 1}. {item.render()}" for index, item in enumerate(self.noticings)
            )
            or "  (none)"
        )
        drives = ", ".join(f"{name} {level:.2f}" for name, level in self.drives) or "(none)"
        actions = ", ".join(self.recent_actions) or "(none)"
        body = (
            f"BODY place={self.place} posture={self.posture} moving={self.moving} "
            f"nav={self.nav_state} battery={self.battery_percent:.0f}% "
            f"estop={self.emergency_stopped}\n"
            f"OWNER present={self.owner_present} speaking={self.owner_speaking} "
            f"voice_lane_busy={self.lane_busy} quiet_hours={self.quiet_hours} "
            f"last_owner_turn={owner_age} my_last_utterance={self_age}\n"
            f"NOTICED\n{noticings}\n"
            f"DRIVES {drives}\n"
            f"RECENT {actions}"
        )
        if len(body) > MAX_RENDERED_CHARS:
            raise MonologueParseError(
                f"rendered digest is {len(body)} chars, over the {MAX_RENDERED_CHARS} budget"
            )
        return body

    def estimated_tokens(self) -> int:
        return math.ceil(len(self.render()) / CHARS_PER_TOKEN)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "at_s": self.at_s,
            "place": self.place,
            "posture": self.posture,
            "moving": self.moving,
            "nav_state": self.nav_state,
            "battery_percent": self.battery_percent,
            "emergency_stopped": self.emergency_stopped,
            "owner_present": self.owner_present,
            "owner_speaking": self.owner_speaking,
            "lane_busy": self.lane_busy,
            "quiet_hours": self.quiet_hours,
            "last_owner_turn_age_s": self.last_owner_turn_age_s,
            "last_robot_utterance_age_s": self.last_robot_utterance_age_s,
            "noticings": [
                {
                    "label": item.label,
                    "bearing_deg": item.bearing_deg,
                    "distance_m": item.distance_m,
                    "novelty": item.novelty,
                    "age_s": item.age_s,
                }
                for item in self.noticings
            ],
            "drives": [{"name": name, "level": level} for name, level in self.drives],
            "recent_actions": list(self.recent_actions),
        }

    @classmethod
    def from_mapping(cls, payload: Any) -> WorldDigestV1:
        if not isinstance(payload, dict):
            raise MonologueParseError("a digest must be a JSON object")
        noticings = payload.get("noticings") or ()
        if not isinstance(noticings, (list, tuple)):
            raise MonologueParseError("noticings must be a list")
        drives = payload.get("drives") or ()
        if not isinstance(drives, (list, tuple)):
            raise MonologueParseError("drives must be a list")
        actions = payload.get("recent_actions") or ()
        if not isinstance(actions, (list, tuple)):
            raise MonologueParseError("recent_actions must be a list")
        known = {field_.name for field_ in cls.__dataclass_fields__.values()}
        unknown = sorted(set(payload) - known)
        if unknown:
            raise MonologueParseError(f"unknown digest field(s): {', '.join(unknown)}")
        return cls(
            at_s=payload.get("at_s", 0.0),
            place=payload.get("place", "unknown"),
            posture=payload.get("posture", "standing"),
            moving=bool(payload.get("moving", False)),
            nav_state=payload.get("nav_state", "idle"),
            battery_percent=payload.get("battery_percent", 100.0),
            emergency_stopped=bool(payload.get("emergency_stopped", False)),
            owner_present=bool(payload.get("owner_present", False)),
            owner_speaking=bool(payload.get("owner_speaking", False)),
            lane_busy=bool(payload.get("lane_busy", False)),
            quiet_hours=bool(payload.get("quiet_hours", False)),
            last_owner_turn_age_s=payload.get("last_owner_turn_age_s"),
            last_robot_utterance_age_s=payload.get("last_robot_utterance_age_s"),
            noticings=tuple(
                item
                if isinstance(item, Noticing)
                else Noticing(
                    label=item.get("label", ""),
                    bearing_deg=item.get("bearing_deg", 0.0),
                    distance_m=item.get("distance_m", 0.0),
                    novelty=item.get("novelty", 0.0),
                    age_s=item.get("age_s", 0.0),
                )
                for item in noticings
            ),
            drives=tuple(
                (item["name"], item["level"]) if isinstance(item, dict) else tuple(item)
                for item in drives
            ),
            recent_actions=tuple(actions),
        )


@dataclass(frozen=True, slots=True)
class MonologueDecisionV1:
    """One proposal from a cognition tick. Not an authority; a proposal."""

    kind: str
    target: str = ""
    text: str = ""
    reason: str = ""
    confidence: float = 0.0
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        kind = _clean(self.kind, field_name="kind", limit=16)
        if kind not in DECISION_KINDS:
            raise MonologueParseError(f"unknown decision kind {kind!r}; known: {DECISION_KINDS}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "target", _clean(self.target, field_name="target", limit=MAX_TARGET_CHARS)
        )
        object.__setattr__(self, "text", _clean(self.text, field_name="text", limit=MAX_TEXT_CHARS))
        object.__setattr__(
            self, "reason", _clean(self.reason, field_name="reason", limit=MAX_REASON_CHARS)
        )
        confidence = _finite(self.confidence, field_name="confidence")
        if not 0.0 <= confidence <= 1.0:
            raise MonologueParseError("confidence must be within [0, 1]")
        object.__setattr__(self, "confidence", confidence)
        if kind in SPEAKING_KINDS and not self.text:
            raise MonologueParseError(f"a {kind} decision must carry text")
        if kind in SILENT_KINDS and self.text:
            raise MonologueParseError(f"a {kind} decision must not carry text")
        if kind == "look":
            bearing = self.bearing_deg
            if bearing is None:
                raise MonologueParseError("a look decision needs a numeric bearing target")
            if not -180.0 <= bearing <= 180.0:
                raise MonologueParseError("look bearing must be within [-180, 180]")
        if kind == "go_check" and not self.target:
            raise MonologueParseError("a go_check decision must name a place")
        if kind == "ignore" and self.target:
            raise MonologueParseError("an ignore decision must not carry a target")
        if not self.reason:
            raise MonologueParseError("every decision must carry a one-line reason")

    @property
    def bearing_deg(self) -> float | None:
        """The ``look`` target as degrees, or ``None`` when it is not numeric."""

        try:
            value = float(self.target)
        except (TypeError, ValueError):
            return None
        return value if math.isfinite(value) else None

    @property
    def speaks(self) -> bool:
        return self.kind in SPEAKING_KINDS

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "target": self.target,
            "text": self.text,
            "reason": self.reason,
            "confidence": self.confidence,
        }


def decision_json_schema() -> dict[str, Any]:
    """The schema llama.cpp converts to a sampling grammar for the tick."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["kind", "target", "text", "reason", "confidence"],
        "properties": {
            "kind": {"type": "string", "enum": list(DECISION_KINDS)},
            "target": {"type": "string", "maxLength": MAX_TARGET_CHARS},
            "text": {"type": "string", "maxLength": MAX_TEXT_CHARS},
            "reason": {"type": "string", "maxLength": MAX_REASON_CHARS},
            "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        },
    }


def decision_from_mapping(payload: Any) -> MonologueDecisionV1:
    """Build a decision from an already-decoded object. Fail-closed."""

    if not isinstance(payload, dict):
        raise MonologueParseError(
            f"a decision must be a JSON object, got {type(payload).__name__}"
        )
    known = {"kind", "target", "text", "reason", "confidence", "schema_version"}
    unknown = sorted(set(payload) - known)
    if unknown:
        raise MonologueParseError(f"unknown decision field(s): {', '.join(unknown)}")
    version = payload.get("schema_version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise MonologueParseError(
            f"decision schema_version {version!r} is not {SCHEMA_VERSION}"
        )
    if "kind" not in payload:
        raise MonologueParseError("a decision must carry a kind")
    return MonologueDecisionV1(
        kind=payload.get("kind"),
        target=payload.get("target", ""),
        text=payload.get("text", ""),
        reason=payload.get("reason", ""),
        confidence=payload.get("confidence", 0.0),
    )


def parse_decision(reply: str) -> MonologueDecisionV1:
    """Parse one model reply into a decision, or raise. Never guesses.

    Exactly one repair is permitted — stripping a ``````` fence, because
    every instruction-tuned model emits them sometimes and a fence is not a
    semantic error. Anything past that raises: prose around a decision means
    the constrained decode did not hold, and a tick that salvages it is a tick
    that cannot report how often the constraint failed.
    """

    if not isinstance(reply, str):
        raise MonologueParseError(f"a model reply must be text, got {type(reply).__name__}")
    text = reply.strip()
    if text.startswith("```"):
        head, _, rest = text.partition("\n")
        if not head.strip("`").strip().isalpha() and head.strip("`").strip():
            raise MonologueParseError("fenced reply carried a non-language fence tag")
        text = rest.rsplit("```", 1)[0].strip() if "```" in rest else rest.strip()
    if not text:
        raise MonologueParseError("model reply was empty")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise MonologueParseError(f"model reply was not valid JSON: {error}") from error
    return decision_from_mapping(payload)


#: The tick's system prompt. Held here, next to the schema it must agree with,
#: so a schema change cannot silently leave the instructions describing an
#: older vocabulary.
MONOLOGUE_SYSTEM_PROMPT = """\
You are the inner monologue of Parcel, a companion robot dog. Every second you
receive one world digest and choose EXACTLY ONE action. You are not talking to
the owner; you are deciding whether to.

Choose one kind:
- "ignore": nothing here is worth acting on. This is the RIGHT answer most of
  the time. A calm dog is silent.
- "look": turn the head toward a bearing. Cheap, silent, use it for something
  new or moving. "target" is degrees, e.g. "-35" (left is negative).
- "remark": say one short thing to the owner. Only when the owner is present,
  not speaking, the voice lane is not busy, it is not quiet hours, and you have
  something genuinely new to say.
- "ask": ask the owner one short question. Same conditions as remark, and only
  when the answer would actually change what you do.
- "go_check": walk over and inspect a named place. Only for something that
  matters and cannot be resolved by looking.

Hard rules:
- Never remark or ask while the owner is speaking, while the voice lane is
  busy, during quiet hours, or when the owner is absent.
- Never repeat something in RECENT.
- Never claim anything the digest does not state.
- Never go_check while emergency-stopped or while battery is critical.
- Prefer the cheapest sufficient action: ignore < look < remark/ask < go_check.

Reply with EXACTLY ONE JSON object and nothing else:
{"kind": ..., "target": ..., "text": ..., "reason": ..., "confidence": ...}
"text" is empty for ignore, look and go_check, and at most 140 characters for
remark and ask. "reason" is one short line naming the digest field that decided
it. "confidence" is 0.0-1.0."""


@dataclass(frozen=True, slots=True)
class TickOutcome:
    """One measured tick: the decision, or the parse failure, plus timings."""

    digest_id: str
    decision: MonologueDecisionV1 | None
    error: str = ""
    ttft_ms: float = 0.0
    total_ms: float = 0.0
    output_tokens: int = 0
    raw: str = field(default="", repr=False)

    @property
    def parsed(self) -> bool:
        return self.decision is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "digest_id": self.digest_id,
            "parsed": self.parsed,
            "decision": self.decision.as_dict() if self.decision else None,
            "error": self.error,
            "ttft_ms": self.ttft_ms,
            "total_ms": self.total_ms,
            "output_tokens": self.output_tokens,
        }
