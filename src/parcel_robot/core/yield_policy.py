"""Blocked-by-a-person yield policy: how long to wait, and what happens next.

**Owner directive (2026-08-08), verbatim:** "When the robot determines there is
a person in scene, that should be a personality decision. By default let the
robot ask for help but make sure that this personality is configurable."

The measurement this exists for (scrum/20260807/task_2/NAV_FINISH_STATUS.md,
card F-1, traffic case): the robot reaches the scored sidewalk polygon,
pedestrians occupy the last 0.2 m of the approach, and the mission then holds
``status=planned|person_stop`` for ~200 ticks until the 240 s ``NavigateTo``
budget expires as ``step_timeout``. Both behaviours that keep it there are
correct in isolation — person-stop ticks deliberately do not count as
no-progress, and ``inside`` arrival requires a terminal clearance the robot
does not have. What was missing is the *product* decision layered on top:

    how long may a mission spend yielding, and what does the dog do about it?

This module is that decision and nothing else. It is pure: no clock, no I/O,
no motion authority. It reads one string per tick (the navigation note the
navigator already publishes) and a monotonic timestamp the caller supplies,
and returns what the runtime should do — hold, speak, or end the mission with
an attributable reason.

**What it may never do.** The yield policy is *downstream* of every safety
gate. It never sees a velocity, never proposes one, and never inspects or
alters ``person_stop_m``/``obstacle_stop_m``/TTC/the collision brake. A tick on
which the gate zeroed translation is still a zero-translation tick under every
policy value — the only thing this module changes is how long the runtime is
willing to sit on such ticks and what it says while it does. Pinned in
``tests/test_yield_policy.py``.

**Person-blocked, and nothing else.** ``obstacle_stop`` is a different case
with different machinery (``DirectiveNavigator._gate_blocked_route_recovery``
releases a commitment after 60 gate-blocked ticks; it deliberately excludes
``person_stop``, because yielding to a person is the gate doing its job).
:func:`person_blocked_from_note` matches the ``person_stop`` segment exactly
and nothing else, so no obstacle, shield or slow-band note can ever route here.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

#: The collision-brake note for "a person is inside the hard stop envelope".
#: Produced by ``navigation/collision.py::apply_collision_brake`` and composed
#: into ``MidLevelCommand.note`` by ``navigation/pipeline.py`` as
#: ``f"{cmd.note}|{cnote}"`` — e.g.
#: ``"grid_track err=0.0 goal=0.2 route=2 status=planned|person_stop"``.
#: The literal is duplicated from a tree this lane does not own; a shared home
#: is a hand-off, not an edit (same convention as ``POSE_LOST_HOLD_NOTE``).
PERSON_BLOCK_NOTE = "person_stop"

#: The obstacle sibling, named here only so the tests can prove it never fires
#: this policy. Owned by the navigation executor's release machinery.
OBSTACLE_BLOCK_NOTE = "obstacle_stop"

#: Every ``on_blocked`` value the policy accepts.
#:
#: ``ask_for_help``      speak, rate-limited, then fail honestly (the DEFAULT,
#:                       by explicit owner instruction);
#: ``wait``              hold indefinitely — reproduces the behaviour measured
#:                       on 2026-08-07, where the outer step budget is the only
#:                       thing that ends the mission;
#: ``give_up_honestly``  end the mission at patience expiry with an
#:                       attributable reason and no request for help.
YIELD_ACTIONS: tuple[str, ...] = ("ask_for_help", "wait", "give_up_honestly")

#: What the runtime reports as the navigation failure reason when the policy
#: ends a mission. Both are attributable and neither claims anything unverified:
#: the robot *was* stopped by the person gate, and it *did* stop rather than
#: arrive.
BLOCKED_BY_PERSON_REASON = "blocked_by_person"
#: Used when ``ask_for_help`` exhausted its asks and nothing changed.
BLOCKED_BY_PERSON_UNANSWERED_REASON = "blocked_by_person_unanswered"

#: Decision vocabulary returned to the runtime.
YIELD_ACTION_CLEAR = "clear"
YIELD_ACTION_HOLD = "hold"
YIELD_ACTION_ASK = "ask"
YIELD_ACTION_GIVE_UP = "give_up"

#: The only substitution a personality utterance template may carry. Anything
#: else fails closed at load time rather than raising ``KeyError`` mid-mission.
UTTERANCE_PLACEHOLDERS = frozenset({"place"})

#: Phrases a yield utterance may never contain, because each one asserts an
#: arrival or a finished goal — exactly the claim the robot cannot make while
#: it is standing still in front of a person. This is the DialogueAct
#: truthfulness rule applied to authored text at load time, so a bad string in
#: a config file is a startup error and never an utterance.
FORBIDDEN_ARRIVAL_PHRASES: tuple[str, ...] = (
    "arrived",
    "i have arrived",
    "i'm here",
    "i am here",
    "we're here",
    "we are here",
    "i'm there",
    "i am there",
    "made it",
    "got there",
    "i'm at the",
    "i am at the",
    "i reached",
    "i've reached",
    "i have reached",
    "task complete",
    "goal reached",
)

_PROFILE_ID = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_PLACEHOLDER = re.compile(r"\{([a-z_]*)\}")


def _reject_unknown(raw: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"unknown keys in {name}: {sorted(unknown)}")


def person_blocked_from_note(note: str | None) -> bool:
    """True when *this tick's* navigation note is the person gate.

    The note is a ``|``-joined composition, so membership is tested on exact
    segments. A substring test would also match a hypothetical
    ``no_person_stop`` and — more importantly — the exact-segment rule is what
    keeps ``obstacle_stop`` from ever reaching this policy.
    """

    if not note:
        return False
    return PERSON_BLOCK_NOTE in {segment.strip() for segment in str(note).split("|")}


@dataclass(frozen=True)
class YieldPolicy:
    """How long this personality yields, and what it does when patience ends.

    Defaults are the shipped ``gentle_companion`` values and are documented at
    :data:`DEFAULT_YIELD_POLICY`. They are *choices*, not measurements — see
    the docs record — and every one of them is overridable per personality in
    ``configs/personality.yaml``.
    """

    #: Seconds a person-block EPISODE must persist before the policy acts at
    #: all. Measured from the episode's first blocked tick, not from the last
    #: one — see ``release_grace_s``.
    patience_s: float = 8.0
    #: One of :data:`YIELD_ACTIONS`. Owner-mandated default: ``ask_for_help``.
    on_blocked: str = "ask_for_help"
    #: Minimum seconds between two spoken asks, and between the last ask and
    #: the honest give-up (the person gets one full interval to respond to the
    #: final ask before the mission ends).
    reask_interval_s: float = 12.0
    #: How many times the dog may ask **per mission** before it fails honestly.
    #: ``0`` makes ``ask_for_help`` degenerate to ``give_up_honestly`` at
    #: patience expiry. Per mission, not per episode: see :class:`YieldTracker`.
    max_asks: int = 2
    #: How long the gate must stay continuously OPEN before a block episode is
    #: considered over. Measured, not chosen: in the dynamic city a pedestrian
    #: stream makes ``person_stop`` chatter, and under a strict
    #: continuous-blockage rule (``0.0``) the traffic case took 45 s to reach a
    #: first ask that should have come at 8 s. ``0.0`` reproduces the strict
    #: rule exactly.
    release_grace_s: float = 3.0

    def __post_init__(self) -> None:
        if not isinstance(self.on_blocked, str) or self.on_blocked not in YIELD_ACTIONS:
            raise ValueError(
                f"yield_policy.on_blocked must be one of {list(YIELD_ACTIONS)}; "
                f"got {self.on_blocked!r}"
            )
        for name in ("patience_s", "reask_interval_s", "release_grace_s"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise TypeError(f"yield_policy.{name} must be a number")
            if not math.isfinite(float(value)) or float(value) < 0.0:
                raise ValueError(f"yield_policy.{name} must be finite and >= 0")
        if self.reask_interval_s <= 0.0:
            raise ValueError("yield_policy.reask_interval_s must be > 0")
        if isinstance(self.max_asks, bool) or not isinstance(self.max_asks, int):
            raise TypeError("yield_policy.max_asks must be an integer")
        if self.max_asks < 0:
            raise ValueError("yield_policy.max_asks must be >= 0")

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> YieldPolicy:
        """Build from a config mapping; unknown keys fail closed (repo pattern)."""

        return DEFAULT_YIELD_POLICY.merged(raw)

    def merged(self, raw: Mapping[str, Any] | None) -> YieldPolicy:
        """Return this policy with ``raw``'s keys overridden, fail-closed."""

        if raw is None:
            return self
        if not isinstance(raw, Mapping):
            raise TypeError("yield_policy must be a mapping")
        allowed = {item.name for item in fields(self)}
        _reject_unknown(raw, allowed, "yield_policy")
        values: dict[str, Any] = {name: getattr(self, name) for name in allowed}
        for name, value in raw.items():
            if name == "on_blocked":
                values[name] = value
            elif name == "max_asks":
                if isinstance(value, bool) or not isinstance(value, int):
                    raise TypeError("yield_policy.max_asks must be an integer")
                values[name] = int(value)
            else:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise TypeError(f"yield_policy.{name} must be a number")
                values[name] = float(value)
        return YieldPolicy(**values)

    def as_dict(self) -> dict[str, Any]:
        return {
            "patience_s": float(self.patience_s),
            "on_blocked": str(self.on_blocked),
            "reask_interval_s": float(self.reask_interval_s),
            "max_asks": int(self.max_asks),
            "release_grace_s": float(self.release_grace_s),
        }


#: The shipped default. ``on_blocked = ask_for_help`` is the owner's explicit
#: instruction and is asserted by a test so it cannot drift silently.
DEFAULT_YIELD_POLICY = YieldPolicy()


def assert_truthful_yield_text(text: str, *, where: str = "yield utterance") -> str:
    """Fail closed on any authored line that claims arrival or completion.

    The DialogueAct contract permits a ``verified`` claim only with an
    ``evidence_ref``. A yield utterance's evidence is the person gate, which
    proves exactly one thing: the robot is stopped because a person is inside
    the stop envelope. It proves nothing about arrival, so an arrival sentence
    can never be backed and must not be authorable.
    """

    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{where} must be a non-empty string")
    lowered = " ".join(text.lower().split())
    for phrase in FORBIDDEN_ARRIVAL_PHRASES:
        if phrase in lowered:
            raise ValueError(
                f"{where} claims arrival or completion ({phrase!r}); a yielding "
                "robot has verified only that it is blocked, never that it got there"
            )
    unknown = {name for name in _PLACEHOLDER.findall(text)} - UTTERANCE_PLACEHOLDERS
    if unknown:
        raise ValueError(
            f"{where} uses unsupported placeholders {sorted(unknown)}; "
            f"only {sorted(UTTERANCE_PLACEHOLDERS)} are substituted"
        )
    return text.strip()


@dataclass(frozen=True)
class YieldSpeech:
    """The three personality-flavoured lines the yield policy may speak.

    Templates, not sentences assembled in ``runtime.py``: the runtime holds no
    yield vocabulary at all, which is what makes "calm vs playful" a config
    change. ``{place}`` is the mission's goal label and is the only slot.
    """

    ask: str = (
        "Someone is standing right where I need to go, so I've stopped. "
        "Could you help me get through to {place}?"
    )
    reask: str = (
        "I'm still waiting — there's someone in my way and I won't push past. "
        "Could someone help me reach {place}?"
    )
    give_up: str = (
        "I couldn't get to {place}. Someone stayed in my way and I stopped "
        "rather than push past, so I've stopped trying for now."
    )

    def __post_init__(self) -> None:
        for item in fields(self):
            assert_truthful_yield_text(
                getattr(self, item.name), where=f"yield_speech.{item.name}"
            )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> YieldSpeech:
        return DEFAULT_YIELD_SPEECH.merged(raw)

    def merged(self, raw: Mapping[str, Any] | None) -> YieldSpeech:
        if raw is None:
            return self
        if not isinstance(raw, Mapping):
            raise TypeError("yield_speech must be a mapping")
        allowed = {item.name for item in fields(self)}
        _reject_unknown(raw, allowed, "yield_speech")
        values = {name: getattr(self, name) for name in allowed}
        for name, value in raw.items():
            if not isinstance(value, str):
                raise TypeError(f"yield_speech.{name} must be a string")
            values[name] = value
        return YieldSpeech(**values)

    def render(self, kind: str, *, place: str) -> str:
        """Render one line. ``kind`` is ``ask`` / ``reask`` / ``give_up``."""

        allowed = {item.name for item in fields(self)}
        if kind not in allowed:
            raise ValueError(f"unknown yield utterance kind: {kind!r}")
        label = " ".join(str(place).split()) or "where I was going"
        rendered = " ".join(getattr(self, kind).format(place=label).split())
        # Re-checked after substitution: a goal *label* could smuggle in a
        # forbidden phrase, and the label is scene data, not authored text.
        return assert_truthful_yield_text(rendered, where=f"yield_speech.{kind}")

    def as_dict(self) -> dict[str, str]:
        return {item.name: str(getattr(self, item.name)) for item in fields(self)}


DEFAULT_YIELD_SPEECH = YieldSpeech()


@dataclass(frozen=True)
class PersonalityYieldProfile:
    """One personality's complete yield behaviour."""

    personality_id: str
    policy: YieldPolicy = DEFAULT_YIELD_POLICY
    speech: YieldSpeech = DEFAULT_YIELD_SPEECH
    #: ``"config"`` when a ``profiles:`` entry supplied it, ``"defaults"`` when
    #: the personality inherited the file's defaults, ``"builtin"`` when no
    #: config file was found at all. Reported, never guessed.
    source: str = "builtin"

    def as_dict(self) -> dict[str, Any]:
        return {
            "personality_id": self.personality_id,
            "source": self.source,
            "yield_policy": self.policy.as_dict(),
            "yield_speech": self.speech.as_dict(),
        }


@dataclass(frozen=True)
class PersonalityPolicyConfig:
    """Parsed ``configs/personality.yaml``. Unknown keys fail closed."""

    schema_version: int = 1
    defaults_policy: YieldPolicy = DEFAULT_YIELD_POLICY
    defaults_speech: YieldSpeech = DEFAULT_YIELD_SPEECH
    profiles: Mapping[str, tuple[YieldPolicy, YieldSpeech]] = field(default_factory=dict)
    path: str = ""

    def for_personality(self, personality_id: str) -> PersonalityYieldProfile:
        entry = self.profiles.get(personality_id)
        if entry is None:
            return PersonalityYieldProfile(
                personality_id=personality_id,
                policy=self.defaults_policy,
                speech=self.defaults_speech,
                source="defaults" if self.path else "builtin",
            )
        policy, speech = entry
        return PersonalityYieldProfile(
            personality_id=personality_id,
            policy=policy,
            speech=speech,
            source="config",
        )

    @classmethod
    def builtin(cls) -> PersonalityPolicyConfig:
        """The no-file config: every personality gets the documented defaults."""

        return cls()

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], *, path: str = ""
    ) -> PersonalityPolicyConfig:
        if not isinstance(raw, Mapping):
            raise TypeError("personality policy config must be a mapping")
        _reject_unknown(raw, {"schema_version", "defaults", "profiles"}, "personality config")
        version = raw.get("schema_version", 1)
        if isinstance(version, bool) or not isinstance(version, int) or version != 1:
            raise ValueError("personality config schema_version must be 1")
        defaults_raw = raw.get("defaults") or {}
        if not isinstance(defaults_raw, Mapping):
            raise TypeError("personality config defaults must be a mapping")
        _reject_unknown(defaults_raw, {"yield_policy", "yield_speech"}, "personality defaults")
        defaults_policy = DEFAULT_YIELD_POLICY.merged(defaults_raw.get("yield_policy"))
        defaults_speech = DEFAULT_YIELD_SPEECH.merged(defaults_raw.get("yield_speech"))

        profiles_raw = raw.get("profiles") or {}
        if not isinstance(profiles_raw, Mapping):
            raise TypeError("personality config profiles must be a mapping")
        profiles: dict[str, tuple[YieldPolicy, YieldSpeech]] = {}
        for profile_id, entry in profiles_raw.items():
            if not isinstance(profile_id, str) or not _PROFILE_ID.fullmatch(profile_id):
                raise ValueError(f"invalid personality id in config: {profile_id!r}")
            entry = entry or {}
            if not isinstance(entry, Mapping):
                raise TypeError(f"personality profile {profile_id!r} must be a mapping")
            _reject_unknown(
                entry, {"yield_policy", "yield_speech"}, f"personality profile {profile_id!r}"
            )
            profiles[profile_id] = (
                defaults_policy.merged(entry.get("yield_policy")),
                defaults_speech.merged(entry.get("yield_speech")),
            )
        return cls(
            schema_version=1,
            defaults_policy=defaults_policy,
            defaults_speech=defaults_speech,
            profiles=profiles,
            path=str(path),
        )


def load_personality_policy_config(path: str | Path) -> PersonalityPolicyConfig:
    """Load and validate one personality policy file. Malformed content raises."""

    resolved = Path(path).expanduser().resolve()
    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    return PersonalityPolicyConfig.from_mapping(raw, path=str(resolved))


@dataclass(frozen=True)
class YieldDecision:
    """What the runtime should do about this tick."""

    action: str
    blocked_s: float = 0.0
    ask_index: int = 0
    reason: str = ""

    @property
    def speaks(self) -> bool:
        return self.action in (YIELD_ACTION_ASK, YIELD_ACTION_GIVE_UP)

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "blocked_s": float(self.blocked_s),
            "ask_index": int(self.ask_index),
            "reason": self.reason,
        }


class YieldTracker:
    """Edge-triggered person-block accounting for one navigation mission.

    One instance per runtime; reset when a mission starts or stops. It is fed
    one ``(person_blocked, now_s)`` pair per navigation tick and answers with a
    :class:`YieldDecision`. ``ask`` is returned on exactly one tick per ask —
    the caller speaks on that edge and nowhere else, so nothing here can spam
    at control rate.

    **Two scopes, and the difference was measured, not designed.** The first
    live run of the traffic case under this policy asked **13 times in 240 s
    and never gave up**, because both scopes were per-episode and the person
    gate *chatters* in a pedestrian stream: every brief release reset patience
    and the ask budget, so the ask re-armed forever and ``max_asks`` was never
    reached. Both halves of that defect are fixed here:

    * **the episode** (``patience_s``) survives gate releases shorter than
      ``release_grace_s``, so patience measures how long the situation has
      persisted rather than how chatty the gate is;
    * **the ask budget** (``max_asks``, ``reask_interval_s``) is per
      **mission**. It is not refunded when the gate flickers, which is what
      makes "after ``max_asks`` it fails honestly" reachable at all.
    """

    def __init__(self, policy: YieldPolicy | None = None) -> None:
        self._policy = policy or DEFAULT_YIELD_POLICY
        #: Episode scope — cleared by a release that outlasts the grace window.
        self._blocked_since: float | None = None
        self._clear_since: float | None = None
        #: Mission scope — cleared only by :meth:`reset`.
        self._asks = 0
        self._last_ask_s: float | None = None
        self._ended = False
        self._episodes = 0

    @property
    def policy(self) -> YieldPolicy:
        return self._policy

    def configure(self, policy: YieldPolicy) -> None:
        """Install a policy and clear all accounting (a personality change)."""

        self._policy = policy
        self.reset()

    def reset(self) -> None:
        self._blocked_since = None
        self._clear_since = None
        self._asks = 0
        self._last_ask_s = None
        self._ended = False
        self._episodes = 0

    def observe(self, *, person_blocked: bool, now_s: float) -> YieldDecision:
        now = float(now_s)
        if person_blocked:
            self._clear_since = None
            if self._blocked_since is None:
                self._blocked_since = now
                self._episodes += 1
        else:
            if self._blocked_since is None:
                return YieldDecision(action=YIELD_ACTION_CLEAR)
            if self._clear_since is None:
                self._clear_since = now
            if now - float(self._clear_since) >= self._policy.release_grace_s:
                # The way has been open long enough to call the episode over.
                # Patience restarts; the mission's ask budget does not refund.
                self._blocked_since = None
                self._clear_since = None
                return YieldDecision(action=YIELD_ACTION_CLEAR)
            # Inside the grace window the gate is open and the body may be
            # driving again. The episode persists, but nothing is decided and
            # nothing is said — you do not ask someone to move out of a gap
            # you are currently driving through.
            return YieldDecision(
                action=YIELD_ACTION_HOLD, blocked_s=max(0.0, now - self._blocked_since)
            )

        blocked_s = max(0.0, now - self._blocked_since)
        if self._ended:
            # The mission was already ended with an attributable reason; the
            # runtime tears down asynchronously, so keep answering "hold" and
            # never speak twice about the same blockage.
            return YieldDecision(action=YIELD_ACTION_HOLD, blocked_s=blocked_s)

        policy = self._policy
        if blocked_s < policy.patience_s:
            return YieldDecision(action=YIELD_ACTION_HOLD, blocked_s=blocked_s)
        if policy.on_blocked == "wait":
            # Exactly today's behaviour: hold until the outer step budget ends
            # the mission. Nothing is spoken and nothing is abandoned.
            return YieldDecision(action=YIELD_ACTION_HOLD, blocked_s=blocked_s)
        if policy.on_blocked == "give_up_honestly":
            self._ended = True
            return YieldDecision(
                action=YIELD_ACTION_GIVE_UP,
                blocked_s=blocked_s,
                reason=BLOCKED_BY_PERSON_REASON,
            )

        # ask_for_help
        since_last_ask = (
            math.inf if self._last_ask_s is None else now - float(self._last_ask_s)
        )
        if self._asks >= policy.max_asks:
            if since_last_ask >= policy.reask_interval_s:
                self._ended = True
                return YieldDecision(
                    action=YIELD_ACTION_GIVE_UP,
                    blocked_s=blocked_s,
                    ask_index=self._asks,
                    reason=BLOCKED_BY_PERSON_UNANSWERED_REASON,
                )
            return YieldDecision(action=YIELD_ACTION_HOLD, blocked_s=blocked_s)
        if since_last_ask < policy.reask_interval_s:
            return YieldDecision(action=YIELD_ACTION_HOLD, blocked_s=blocked_s)
        self._asks += 1
        self._last_ask_s = now
        return YieldDecision(
            action=YIELD_ACTION_ASK, blocked_s=blocked_s, ask_index=self._asks
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "policy": self._policy.as_dict(),
            "blocked": self._blocked_since is not None,
            "episodes": int(self._episodes),
            "asks": int(self._asks),
            "ended": bool(self._ended),
        }


__all__ = [
    "BLOCKED_BY_PERSON_REASON",
    "BLOCKED_BY_PERSON_UNANSWERED_REASON",
    "DEFAULT_YIELD_POLICY",
    "DEFAULT_YIELD_SPEECH",
    "FORBIDDEN_ARRIVAL_PHRASES",
    "OBSTACLE_BLOCK_NOTE",
    "PERSON_BLOCK_NOTE",
    "YIELD_ACTIONS",
    "YIELD_ACTION_ASK",
    "YIELD_ACTION_CLEAR",
    "YIELD_ACTION_GIVE_UP",
    "YIELD_ACTION_HOLD",
    "PersonalityPolicyConfig",
    "PersonalityYieldProfile",
    "YieldDecision",
    "YieldPolicy",
    "YieldSpeech",
    "YieldTracker",
    "assert_truthful_yield_text",
    "load_personality_policy_config",
    "person_blocked_from_note",
]
