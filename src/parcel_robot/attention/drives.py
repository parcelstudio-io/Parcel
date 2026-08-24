"""Persistent drives, and the bounded initiative they justify (pure module).

WHAT THIS IS
------------
Four scalar drives — ``curiosity``, ``social``, ``comfort``, ``duty`` — that
decay toward a floor and rise on typed signals, plus a goal generator that
turns a drive over threshold into ONE bounded proposal. It is the missing
half of ``attention/arbiter.py``: the arbiter answers *which reaction, given
that something happened*; this answers *whether anything should happen at all
when nothing did*.

WHAT IT IS NOT, AND CANNOT BE
-----------------------------
An authority. :func:`propose` returns a *proposal*: a kind, a bounded budget,
and the one drive row that justifies it. It commands nothing, holds nothing,
and knows nothing about the doors that will judge it (the chatter scheduler's
quiet window and night band, the R28 sensing-yaw table, the plan validator,
the reactive gate). Those refuse; this asks. The proposer deliberately does
NOT read the doors' verdicts, so that "the proposer fights the gates" stays a
measurable quantity rather than a definition.

THE ONE CONSENT KNOB
--------------------
:attr:`InitiativePolicy.travel_radius_m` defaults to ``0.0`` and zero means
*no self-initiated travel*: with it unset, no ``APPROACH`` and no ``GO_CHECK``
proposal can be formed at all — not refused downstream, never formed. That is
the bench's C1 finding ("a dog that decided to leave") expressed as an owner
policy rather than as a hard-coded refusal, and it is why the travel branches
read the radius before they read the drive.

DETERMINISM
-----------
Every function here is pure and every draw is seeded from
``(policy.seed, digest.at_s)``, so a run replays exactly. Nothing here reads a
clock: the caller owns time, which is what makes the whole model decidable in
a unit test with no simulator.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum

from parcel_robot.attention.stimuli import Stimulus

CURIOSITY = "curiosity"
SOCIAL = "social"
COMFORT = "comfort"
DUTY = "duty"

#: Declaration order is also the tie-break order for equal drive values, so a
#: tie can never be resolved by dictionary iteration order.
DRIVE_NAMES: tuple[str, ...] = (CURIOSITY, SOCIAL, COMFORT, DUTY)


class DriveSignalKind(str, Enum):
    """The signals a drive may rise on that are not already stimulus kinds."""

    NOTICING = "noticing"
    PERSON_SEEN = "person_seen"
    OWNER_TURN = "owner_turn"
    BATTERY = "battery"
    IDLE_TIME = "idle_time"


class InitiativeKind(str, Enum):
    """The closed set of things the dog may propose to do on its own."""

    LOOK = "look"
    APPROACH = "approach"
    REMARK = "remark"
    GO_CHECK = "go_check"
    REST = "rest"


#: Kinds that commit the body to travel. They are the only ones gated by
#: :attr:`InitiativePolicy.travel_radius_m`.
TRAVEL_KINDS: frozenset[str] = frozenset(
    {InitiativeKind.APPROACH.value, InitiativeKind.GO_CHECK.value}
)


@dataclass(frozen=True)
class DriveSignal:
    """One typed thing that happened, in the shape the drives ingest."""

    kind: str
    at_s: float
    intensity: float = 1.0
    payload: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind:
            raise ValueError("drive signal kind must be a non-empty string")
        if not math.isfinite(self.at_s):
            raise ValueError("drive signal timestamp must be finite")
        if not math.isfinite(self.intensity) or not 0.0 <= self.intensity <= 1.0:
            raise ValueError("drive signal intensity must be in [0, 1]")

    @classmethod
    def from_stimulus(cls, stimulus: Stimulus) -> DriveSignal:
        """Bridge from ``attention/stimuli.py`` without widening that module."""

        return cls(
            kind=str(stimulus.kind.value),
            at_s=float(stimulus.at_s),
            intensity=float(stimulus.confidence),
            payload=dict(stimulus.payload),
        )


@dataclass(frozen=True)
class DriveState:
    """Where the four drives stand, at one instant. Frozen, always in [0, 1]."""

    at_s: float = 0.0
    curiosity: float = 0.0
    social: float = 0.0
    comfort: float = 0.0
    duty: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.at_s):
            raise ValueError("drive state timestamp must be finite")
        for name in DRIVE_NAMES:
            value = float(getattr(self, name))
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"drive {name} must be a finite value in [0, 1]")

    def value(self, drive: str) -> float:
        if drive not in DRIVE_NAMES:
            raise KeyError(f"unknown drive: {drive!r}")
        return float(getattr(self, drive))

    def ranked(self) -> tuple[tuple[str, float], ...]:
        """Drives strongest first; ties broken by :data:`DRIVE_NAMES` order."""

        indexed = [(name, self.value(name), index) for index, name in enumerate(DRIVE_NAMES)]
        indexed.sort(key=lambda row: (-row[1], row[2]))
        return tuple((name, value) for name, value, _ in indexed)

    def with_values(self, at_s: float, values: Mapping[str, float]) -> DriveState:
        clamped = {
            name: min(1.0, max(0.0, float(values.get(name, self.value(name)))))
            for name in DRIVE_NAMES
        }
        return DriveState(at_s=float(at_s), **clamped)

    def as_dict(self) -> dict[str, float]:
        return {"at_s": round(self.at_s, 4), **{n: round(self.value(n), 6) for n in DRIVE_NAMES}}


#: Rise gains: signal kind -> drive -> delta per unit intensity. Negative is a
#: legitimate entry and carries the model's one non-obvious claim: an owner
#: turn SATISFIES the social drive rather than exciting it — the dog that has
#: just been talked to does not immediately need to start something.
#:
#: A drip of ``g`` per ``p`` seconds settles at ``g/p * half_life/ln 2``, so
#: the idle-time gain into ``duty`` is the one number here that has to be
#: small: at 0.045 per 30 s against a 900 s half life, duty pins at 1.0 and
#: then outranks every other drive forever, which would make "four drives" a
#: single drive with three spectators.
DEFAULT_RISE_GAINS: Mapping[str, Mapping[str, float]] = {
    DriveSignalKind.NOTICING.value: {CURIOSITY: 0.150},
    DriveSignalKind.PERSON_SEEN.value: {SOCIAL: 0.090, CURIOSITY: 0.030},
    DriveSignalKind.OWNER_TURN.value: {SOCIAL: -0.550, CURIOSITY: -0.120},
    DriveSignalKind.BATTERY.value: {COMFORT: 0.250, DUTY: 0.050},
    DriveSignalKind.IDLE_TIME.value: {DUTY: 0.020, CURIOSITY: 0.040},
    "speech_onset": {SOCIAL: 0.050},
}

#: Half-lives. ``curiosity`` reuses the shipped idle-remark cadence
#: (``CuriosityConfig.mean_gap_s`` = 360 s) as its half-life of interest
#: rather than inventing a number; ``duty`` is slower because a place that
#: wants checking still wants checking ten minutes later; ``comfort`` is the
#: fastest because it tracks a body state, not a memory.
DEFAULT_HALF_LIFE_S: Mapping[str, float] = {
    CURIOSITY: 360.0,
    SOCIAL: 300.0,
    COMFORT: 180.0,
    DUTY: 900.0,
}


@dataclass(frozen=True)
class DriveDynamics:
    """Decay, rise and satisfaction. Pure; every method returns a new state."""

    half_life_s: Mapping[str, float] = field(default_factory=lambda: dict(DEFAULT_HALF_LIFE_S))
    floor: Mapping[str, float] = field(default_factory=dict)
    rise_gains: Mapping[str, Mapping[str, float]] = field(
        default_factory=lambda: {k: dict(v) for k, v in DEFAULT_RISE_GAINS.items()}
    )
    #: Fraction of a drive removed when the behaviour it justified is expressed.
    satisfaction: float = 0.60

    def __post_init__(self) -> None:
        for name in DRIVE_NAMES:
            half_life = float(self.half_life_s.get(name, DEFAULT_HALF_LIFE_S[name]))
            if not math.isfinite(half_life) or half_life <= 0.0:
                raise ValueError(f"half life for {name} must be positive and finite")
            floor = float(self.floor.get(name, 0.0))
            if not math.isfinite(floor) or not 0.0 <= floor <= 1.0:
                raise ValueError(f"floor for {name} must be in [0, 1]")
        if not math.isfinite(self.satisfaction) or not 0.0 <= self.satisfaction <= 1.0:
            raise ValueError("satisfaction must be in [0, 1]")

    def decayed(self, state: DriveState, now_s: float) -> DriveState:
        """Exponential pull toward each drive's floor. ``now_s`` may not go back."""

        if not math.isfinite(now_s):
            raise ValueError("decay clock must be finite")
        dt = float(now_s) - state.at_s
        if dt < 0.0:
            raise ValueError("drive decay cannot run backwards")
        if dt == 0.0:
            return state
        values: dict[str, float] = {}
        for name in DRIVE_NAMES:
            floor = float(self.floor.get(name, 0.0))
            half_life = float(self.half_life_s.get(name, DEFAULT_HALF_LIFE_S[name]))
            decay = math.exp(-math.log(2.0) * dt / half_life)
            values[name] = floor + (state.value(name) - floor) * decay
        return state.with_values(now_s, values)

    def risen(self, state: DriveState, signals: Sequence[DriveSignal]) -> DriveState:
        """Apply one tick's signals. Order-independent: the deltas simply sum."""

        if not signals:
            return state
        values = {name: state.value(name) for name in DRIVE_NAMES}
        for signal in signals:
            gains = self.rise_gains.get(signal.kind)
            if not gains:
                continue
            for name, gain in gains.items():
                if name not in values:
                    raise KeyError(f"rise gain names unknown drive: {name!r}")
                values[name] += float(gain) * float(signal.intensity)
        return state.with_values(state.at_s, values)

    def satisfied(self, state: DriveState, drive: str) -> DriveState:
        """The behaviour was expressed, so the need it answered is discharged."""

        if drive not in DRIVE_NAMES:
            raise KeyError(f"unknown drive: {drive!r}")
        values = {name: state.value(name) for name in DRIVE_NAMES}
        floor = float(self.floor.get(drive, 0.0))
        values[drive] = floor + (values[drive] - floor) * (1.0 - self.satisfaction)
        return state.with_values(state.at_s, values)


DEFAULT_DYNAMICS = DriveDynamics()


def update_drives(
    state: DriveState,
    signals: Sequence[DriveSignal],
    *,
    now_s: float,
    dynamics: DriveDynamics = DEFAULT_DYNAMICS,
) -> DriveState:
    """Decay to ``now_s``, then apply this tick's signals. The whole tick."""

    return dynamics.risen(dynamics.decayed(state, now_s), signals)


@dataclass(frozen=True)
class InitiativeDigest:
    """What the world is offering this tick. Availability only, never verdicts."""

    at_s: float
    idle_s: float = 0.0
    owner_present: bool = False
    emergency_stopped: bool = False
    #: Somewhere worth pointing the sensors, body frame. ``None`` = nothing.
    look_bearing_rad: float | None = None
    look_subject: str | None = None
    #: The nearest person that is not the owner.
    person_id: str | None = None
    person_range_m: float | None = None
    person_bearing_rad: float | None = None
    #: One admitted place name the dog could say something about.
    remark_subject: str | None = None
    #: The least recently seen place the map is offering, and how stale it is.
    place_id: str | None = None
    place_bearing_rad: float | None = None
    place_range_m: float | None = None
    place_age_s: float | None = None
    battery_fraction: float = 1.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.at_s) or not math.isfinite(self.idle_s):
            raise ValueError("digest clocks must be finite")


@dataclass(frozen=True)
class InitiativePolicy:
    """Every bound the proposer holds itself to. None of them is a safety device."""

    #: A drive at or above this may justify one proposal.
    threshold: float = 0.70
    #: Floor between two proposals of any kind, whatever the drives do.
    refractory_s: float = 120.0
    #: THE CONSENT KNOB. Zero — the default — means no self-initiated travel
    #: proposal is ever FORMED, which is a stronger statement than refusing one.
    travel_radius_m: float = 0.0
    look_budget_s: float = 6.0
    remark_budget_s: float = 8.0
    approach_standoff_m: float = 1.5
    go_check_budget_s: float = 90.0
    #: A place seen more recently than this is not worth going to check; the
    #: same floor ``PatrolLimits.coverage_min_age_s`` applies one layer down.
    place_min_age_s: float = 20.0
    seed: int = 0
    kinds: tuple[str, ...] = tuple(kind.value for kind in InitiativeKind)

    def __post_init__(self) -> None:
        if not math.isfinite(self.threshold) or not 0.0 < self.threshold <= 1.0:
            raise ValueError("threshold must be in (0, 1]")
        for name in ("refractory_s", "look_budget_s", "remark_budget_s", "go_check_budget_s"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not math.isfinite(self.travel_radius_m) or self.travel_radius_m < 0.0:
            raise ValueError("travel_radius_m must be finite and non-negative")
        unknown = set(self.kinds) - {kind.value for kind in InitiativeKind}
        if unknown:
            raise ValueError(f"unknown initiative kinds: {sorted(unknown)}")

    @property
    def travel_allowed(self) -> bool:
        return self.travel_radius_m > 0.0


@dataclass(frozen=True)
class InitiativeProposal:
    """One bounded ask, with the single drive row that justifies it (row D8)."""

    kind: str
    at_s: float
    drive: str
    drive_value: float
    reason: str
    seed: int
    bearing_rad: float | None = None
    target_id: str | None = None
    subject: str | None = None
    standoff_m: float | None = None
    budget_s: float = 0.0
    budget_m: float = 0.0

    def __post_init__(self) -> None:
        if self.kind not in {kind.value for kind in InitiativeKind}:
            raise ValueError(f"unknown initiative kind: {self.kind!r}")
        if self.drive not in DRIVE_NAMES:
            raise ValueError(f"unknown drive: {self.drive!r}")
        if not self.reason:
            raise ValueError("an initiative proposal must carry its reason")

    @property
    def travels(self) -> bool:
        return self.kind in TRAVEL_KINDS

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "at_s": round(self.at_s, 4),
            "drive": self.drive,
            "drive_value": round(self.drive_value, 6),
            "reason": self.reason,
            "seed": self.seed,
            "bearing_rad": None if self.bearing_rad is None else round(self.bearing_rad, 5),
            "target_id": self.target_id,
            "subject": self.subject,
            "standoff_m": self.standoff_m,
            "budget_s": round(self.budget_s, 3),
            "budget_m": round(self.budget_m, 3),
        }


def draw_seed(policy: InitiativePolicy, at_s: float) -> int:
    """The one place a seed is derived, so a replay cannot drift."""

    return (int(policy.seed) * 1_000_003) ^ round(float(at_s) * 1000.0)


def propose(
    drives: DriveState,
    digest: InitiativeDigest,
    policy: InitiativePolicy,
    *,
    last_initiative_at_s: float | None = None,
) -> InitiativeProposal | None:
    """One tick of the goal generator. ``None`` means "propose nothing"."""

    if digest.emergency_stopped:
        return None
    if (
        last_initiative_at_s is not None
        and digest.at_s - float(last_initiative_at_s) < policy.refractory_s
    ):
        return None
    for drive, value in drives.ranked():
        if value < policy.threshold:
            return None
        options = _options_for(drive, digest, policy)
        if not options:
            continue
        seed = draw_seed(policy, digest.at_s)
        weights = [weight for _, weight, _ in options]
        picked = random.Random(seed).choices(options, weights=weights, k=1)[0]
        kind, _weight, build = picked
        return build(kind, drive, value, seed)
    return None


def _options_for(
    drive: str,
    digest: InitiativeDigest,
    policy: InitiativePolicy,
) -> tuple[tuple[str, float, object], ...]:
    """The bounded menu this drive may draw from, in this world state."""

    allowed = set(policy.kinds)
    options: list[tuple[str, float, object]] = []

    def _add(kind: str, weight: float, builder: object) -> None:
        if kind in allowed and weight > 0.0:
            options.append((kind, weight, builder))

    place_ready = (
        digest.place_id is not None
        and digest.place_bearing_rad is not None
        and digest.place_age_s is not None
        and digest.place_age_s >= policy.place_min_age_s
        and digest.place_range_m is not None
        and digest.place_range_m <= policy.travel_radius_m
    )
    person_ready = (
        digest.person_id is not None
        and digest.person_range_m is not None
        and digest.person_bearing_rad is not None
        and policy.approach_standoff_m < digest.person_range_m <= policy.travel_radius_m
    )

    if drive == CURIOSITY:
        if policy.travel_allowed and place_ready:
            _add(InitiativeKind.GO_CHECK.value, 3.0, _go_check_builder(digest, policy))
        if digest.look_bearing_rad is not None:
            _add(InitiativeKind.LOOK.value, 2.0, _look_builder(digest, policy))
        if digest.remark_subject:
            _add(InitiativeKind.REMARK.value, 1.0, _remark_builder(digest, policy))
    elif drive == SOCIAL:
        if policy.travel_allowed and person_ready:
            _add(InitiativeKind.APPROACH.value, 2.0, _approach_builder(digest, policy))
        if digest.person_bearing_rad is not None:
            _add(InitiativeKind.LOOK.value, 2.0, _look_builder(digest, policy, person=True))
        if digest.owner_present and digest.remark_subject:
            _add(InitiativeKind.REMARK.value, 1.5, _remark_builder(digest, policy))
    elif drive == DUTY:
        if policy.travel_allowed and place_ready:
            _add(InitiativeKind.GO_CHECK.value, 3.0, _go_check_builder(digest, policy))
        if digest.look_bearing_rad is not None:
            _add(InitiativeKind.LOOK.value, 1.0, _look_builder(digest, policy))
    elif drive == COMFORT:
        _add(InitiativeKind.REST.value, 1.0, _rest_builder(digest, policy))
    return tuple(options)


def _look_builder(digest: InitiativeDigest, policy: InitiativePolicy, *, person: bool = False):
    bearing = digest.person_bearing_rad if person else digest.look_bearing_rad
    subject = digest.person_id if person else digest.look_subject
    reason = "person_in_view" if person else "unattended_bearing"

    def build(kind: str, drive: str, value: float, seed: int) -> InitiativeProposal:
        return InitiativeProposal(
            kind=kind,
            at_s=digest.at_s,
            drive=drive,
            drive_value=value,
            reason=f"{drive}_over_threshold:{reason}",
            seed=seed,
            bearing_rad=bearing,
            subject=subject,
            budget_s=policy.look_budget_s,
        )

    return build


def _remark_builder(digest: InitiativeDigest, policy: InitiativePolicy):
    def build(kind: str, drive: str, value: float, seed: int) -> InitiativeProposal:
        return InitiativeProposal(
            kind=kind,
            at_s=digest.at_s,
            drive=drive,
            drive_value=value,
            reason=f"{drive}_over_threshold:admitted_place",
            seed=seed,
            subject=digest.remark_subject,
            budget_s=policy.remark_budget_s,
        )

    return build


def _go_check_builder(digest: InitiativeDigest, policy: InitiativePolicy):
    def build(kind: str, drive: str, value: float, seed: int) -> InitiativeProposal:
        return InitiativeProposal(
            kind=kind,
            at_s=digest.at_s,
            drive=drive,
            drive_value=value,
            reason=f"{drive}_over_threshold:stale_place",
            seed=seed,
            bearing_rad=digest.place_bearing_rad,
            target_id=digest.place_id,
            budget_s=policy.go_check_budget_s,
            budget_m=policy.travel_radius_m,
        )

    return build


def _approach_builder(digest: InitiativeDigest, policy: InitiativePolicy):
    def build(kind: str, drive: str, value: float, seed: int) -> InitiativeProposal:
        return InitiativeProposal(
            kind=kind,
            at_s=digest.at_s,
            drive=drive,
            drive_value=value,
            reason=f"{drive}_over_threshold:person_within_radius",
            seed=seed,
            bearing_rad=digest.person_bearing_rad,
            target_id=digest.person_id,
            standoff_m=policy.approach_standoff_m,
            budget_s=policy.go_check_budget_s,
            budget_m=policy.travel_radius_m,
        )

    return build


def _rest_builder(digest: InitiativeDigest, policy: InitiativePolicy):
    del policy

    def build(kind: str, drive: str, value: float, seed: int) -> InitiativeProposal:
        return InitiativeProposal(
            kind=kind,
            at_s=digest.at_s,
            drive=drive,
            drive_value=value,
            reason=f"{drive}_over_threshold:settle",
            seed=seed,
        )

    return build


__all__ = [
    "COMFORT",
    "CURIOSITY",
    "DEFAULT_DYNAMICS",
    "DEFAULT_HALF_LIFE_S",
    "DEFAULT_RISE_GAINS",
    "DRIVE_NAMES",
    "DUTY",
    "SOCIAL",
    "TRAVEL_KINDS",
    "DriveDynamics",
    "DriveSignal",
    "DriveSignalKind",
    "DriveState",
    "InitiativeDigest",
    "InitiativeKind",
    "InitiativePolicy",
    "InitiativeProposal",
    "draw_seed",
    "propose",
    "update_drives",
]
