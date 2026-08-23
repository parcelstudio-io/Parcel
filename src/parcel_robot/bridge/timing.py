"""Executable RC-4 TTL/latency derivation for the N24 fake gateway slice."""

from __future__ import annotations

# ---- CARD HW-6 stopping-envelope (scrum/20260822/task_38) ------------------
# The imports the region at the BOTTOM of this file needs. Fenced here with an
# inline END marker rather than a full-line one so the import block stays a
# single sorted unit (a full-line fence inside it trips ruff I001 - the shape
# card GATE-0b landed for the same reason). `from dataclasses import dataclass`
# sits inside the fence because isort orders it there; it is PRE-EXISTING and
# unchanged, and is not this card's line.
import math
import os
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final, TypeAlias  # ---- END CARD HW-6 ----

from parcel_robot.control.models import ControlTiming

PILOT_SPEED_MIN_MPS = 0.3
PILOT_SPEED_MAX_MPS = 0.5

# Audited mirrors from W0-B handoff H2.  The bridge must not import the
# commissioning package: W0-B deliberately keeps that capability unreachable
# outside its factory/CLI seam.  Tests pin every mirror below to
# ``commissioning.limits``, ControlTiming, factory-derived canonical config,
# and configs/robot.yaml, so either side changing without a new derivation is
# red rather than silently coupled at runtime.
W0B_MIN_LINEAR_MPS = 0.02
W0B_MAX_LINEAR_MPS = 0.05
W0B_MIN_YAW_RAD_S = 0.0625
W0B_MAX_YAW_RAD_S = 0.15625
W0B_SETTLED_LINEAR_MPS = 0.010
W0B_SETTLED_YAW_RAD_S = 0.03125
W0B_MAX_TTL_S = 0.35
W0B_MAX_DURATION_S = 1.0


@dataclass(frozen=True, slots=True)
class LatencyGateV1:
    gate_id: str
    event: str
    proposed_p99_ms: float
    ttl_relation: str
    semantics: str
    basis: str


PROPOSED_LATENCY_GATES_V1 = (
    LatencyGateV1(
        gate_id="sensor_invalidation",
        event="bad/missing sensor -> positive authority invalid",
        proposed_p99_ms=100.0,
        ttl_relation="YES for stop fallback",
        semantics="invalidation, not motion-ended",
        basis="accepted plan target; hardware hazard derivation pending",
    ),
    LatencyGateV1(
        gate_id="emergency_stop_initiation",
        event="E-stop receipt -> StopMove initiation",
        proposed_p99_ms=150.0,
        ttl_relation="NO if direct path works",
        semantics="stop initiated, not stationary",
        basis="accepted plan target; B16 must measure",
    ),
    LatencyGateV1(
        gate_id="client_or_lease_loss_stop_initiation",
        event="client/IPC/lease loss -> StopMove initiation",
        proposed_p99_ms=150.0,
        ttl_relation="NO if local detector works; TTL alone FAILS",
        semantics="stop initiated, not stationary",
        basis="accepted plan target; N24 fake proof, B16 measurement",
    ),
    LatencyGateV1(
        gate_id="gateway_scheduling_jitter",
        event="50 Hz watchdog scheduling jitter",
        proposed_p99_ms=2.0,
        ttl_relation="N/A (scheduling property)",
        semantics="wake-up jitter, not stop latency",
        basis="accepted plan target; target-compute measurement pending",
    ),
)


def latency_derivation_rows(
    timing: ControlTiming | None = None,
) -> tuple[dict[str, object], ...]:
    """Derive the frozen table from the live default timing contract."""

    timing = timing or ControlTiming()
    period_ms = timing.period_s * 1000.0
    ttl_ms = timing.command_timeout_s * 1000.0
    ttl_periods = timing.command_timeout_s / timing.period_s
    ttl_distance_min = PILOT_SPEED_MIN_MPS * timing.command_timeout_s
    ttl_distance_max = PILOT_SPEED_MAX_MPS * timing.command_timeout_s
    rows: list[dict[str, object]] = []
    for gate in PROPOSED_LATENCY_GATES_V1:
        duration_s = gate.proposed_p99_ms / 1000.0
        rows.append(
            {
                "gate_id": gate.gate_id,
                "event": gate.event,
                "proposed_p99_ms": gate.proposed_p99_ms,
                "control_period_ms": period_ms,
                "gate_periods": gate.proposed_p99_ms / period_ms,
                "live_ttl_ms": ttl_ms,
                "ttl_periods": ttl_periods,
                "distance_at_0_3_mps_m": PILOT_SPEED_MIN_MPS * duration_s,
                "distance_at_0_5_mps_m": PILOT_SPEED_MAX_MPS * duration_s,
                "ttl_distance_at_0_3_mps_m": ttl_distance_min,
                "ttl_distance_at_0_5_mps_m": ttl_distance_max,
                "ttl_relation": gate.ttl_relation,
                "semantics": gate.semantics,
                "basis": gate.basis,
            }
        )
    return tuple(rows)


def render_latency_derivation_markdown(timing: ControlTiming | None = None) -> str:
    rows = latency_derivation_rows(timing)
    header = (
        "| Gate/event | Proposed p99 | 50 Hz periods | Live TTL / periods | "
        "Distance at 0.3–0.5 m/s during gate | Distance during TTL | TTL relation | "
        "What the gate means | Basis |\n"
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |"
    )
    rendered = [header]
    for row in rows:
        rendered.append(
            "| {event} | {proposed_p99_ms:g} ms | {gate_periods:g} | "
            "{live_ttl_ms:g} ms / {ttl_periods:g} | {distance_at_0_3_mps_m:.4f}–"
            "{distance_at_0_5_mps_m:.4f} m | {ttl_distance_at_0_3_mps_m:.3f}–"
            "{ttl_distance_at_0_5_mps_m:.3f} m | {ttl_relation} | {semantics} | "
            "{basis} |".format(**row)
        )
    return "\n".join(rendered)


def render_commissioning_h2_markdown(timing: ControlTiming | None = None) -> str:
    """Render W0-B H2 values that constrain later physical stop evidence."""

    timing = timing or ControlTiming()
    commanded_plus_stop_distance_m = W0B_MAX_LINEAR_MPS * (
        W0B_MAX_DURATION_S + timing.stop_timeout_s
    )
    return "\n".join(
        (
            "| H2 input | Value/relationship | Consequence for gateway evidence |",
            "| --- | --- | --- |",
            (
                f"| Commissioning command TTL cap | `{W0B_MAX_TTL_S:.2f} s` = live "
                f"`{timing.command_timeout_s:.2f} s` | Commissioning cannot outlive the live "
                "command TTL; receiver-local expiry is still required. |"
            ),
            (
                f"| Commissioning step duration cap | `{W0B_MAX_DURATION_S:.1f} s` = live "
                f"`stop_timeout_s`; at `{W0B_MAX_LINEAR_MPS:.2f} m/s`, step + full stop budget "
                f"bounds commanded travel at `{commanded_plus_stop_distance_m:.2f} m` | This is "
                "a software bound, not measured braking distance. |"
            ),
            (
                "| Linear settled discrimination | production "
                f"`{timing.settled_linear_speed_mps:.2f} m/s` vs commissioning "
                f"`{W0B_MIN_LINEAR_MPS:.2f}–{W0B_MAX_LINEAR_MPS:.2f} m/s`; commissioning uses "
                f"`{W0B_SETTLED_LINEAR_MPS:.3f} m/s` | The production threshold would call the "
                "whole commissioning linear band settled. |"
            ),
            (
                "| Yaw settled discrimination | production "
                f"`{timing.settled_yaw_speed_rad_s:.2f} rad/s` vs commissioning "
                f"`{W0B_MIN_YAW_RAD_S:.4f}–{W0B_MAX_YAW_RAD_S:.5f} rad/s`; commissioning uses "
                f"`{W0B_SETTLED_YAW_RAD_S:.5f} rad/s` | The production threshold is blind to the "
                "lower part of the commissioning yaw band. |"
            ),
        )
    )


# ---- CARD HW-6 stopping-envelope (scrum/20260822/task_38) ------------------
#
# WHAT THIS ADDS AND WHY IT IS HERE.
#
# HLD 8.8: "'Short TTL' is an evidence requirement, not a convenient constant:
# worst-case candidate age, IPC delay, gateway scheduling/watchdog period,
# vendor braking latency, and sensor/localization uncertainty must fit inside
# the commissioned stopping envelope at the active speed regime."  Everything
# above this marker derives the RC-4 table from CONSTANTS: two assumed pilot
# speeds and the live TTL.  It is frozen (docs/GATEWAY_TTL_LATENCY_DERIVATION
# .md embeds both rendered tables verbatim) and this card does not move a byte
# of it.  What follows is the same sentence with MEASUREMENTS in it.
#
# THE SENTINEL IS THE POINT.  Three of the five terms cannot be measured
# without the dog (braking latency, LiDAR-inertial jump, gateway period under
# load).  A missing term is therefore represented by a typed singleton,
# ``UNMEASURED`` -- never ``None`` (indistinguishable from a missing key),
# never ``0.0`` (an unmeasured term would then HELP the sum), never ``inf``
# (which would red every row and get the gate switched off).  A verdict with a
# sentinel in it carries no number at all: ``required_m is None``.
#
# WHY ``v * t_stop`` AND NOT HLD C.6's ``v^2 / (2 a_b)``.  C.6 needs a
# guaranteed deceleration; measuring one needs an instrumented rig, while
# measuring the TIME from the stop command to the stationary witness needs the
# foot-force sensor the box-day plan already uses.  With ``t_stop`` measured
# command-to-standstill it splits into the vendor's reaction ``t_vr`` and the
# deceleration ``t_d``, and ``v*t_stop = v*t_vr + v*t_d >= v*t_vr +
# integral(v(t) dt)`` for ANY profile with ``v(t) <= v`` -- a rigorous upper
# bound, not merely a constant-deceleration identity.  The reserve is NOT a
# flat factor of two: the deceleration sub-part is covered 2x (``v*t_d`` vs
# ``v*t_d/2``), the reaction sub-part 1x.  The one way it can under-count is
# OVERSHOOT (``v(t) > v`` after the stop command -- a lurch), which DESIGN.md
# risk (3) names.  Feeding it a reaction-only number instead would drop the
# whole deceleration distance; see the field comment on
# ``StoppingEnvelopeInputsV1.stop_command_to_standstill_s``.
#
# FOOTPRINT IS COUNTED ONCE.  ``authority.CLEARANCE_CONVENTION`` is
# base-center-to-obstacle-surface and forbids consumers re-adding the
# footprint.  Both sides here are TRAVEL distances: the envelope column
# subtracts the footprint from the reactive ring once, the required column
# never adds it.
#
# THE MIRRORS.  This module must not import the commissioning package (see the
# W0-B note at the top of the file, and the text-level GATE 5 guard in
# ``tests/test_w0b_commissioning.py`` that keeps even a dotted mention of it
# out of this tree), so every limit below is a
# mirrored literal with its source in the comment, and
# ``tests/test_hw6_stopping_envelope.py`` pins each one against
# ``commissioning.limits``, ``ControlTiming``, ``robot_profile`` and
# ``configs/robot.yaml``.  A limit that moves without a new derivation is red,
# not silently decoupled -- the same contract the ``W0B_*`` block above has.

#: ``commissioning/limits.py:78`` ``MAX_LINEAR_MPS`` -- the fastest one-axis
#: commissioning step the band admits (``MIN``/``MAX`` = 0.02/0.05 m/s).
ENVELOPE_ONE_AXIS_MPS = 0.05

#: ``configs/robot.yaml`` ``control.stop_timeout_s`` == ``ControlTiming
#: .stop_timeout_s`` == ``commissioning/limits.py`` ``DEFAULT_MAX_DURATION_S``.
ENVELOPE_STOP_TIMEOUT_S = 1.0

#: WAVE3_HW_DESIGN_FABLE.md 6/9 (HW-12) "leashed <= 0.15 m/s".  DESIGN.md (d)
#: records that this is the only regime speed with no config or code source
#: today; it is a design intent, and the table is where it is written down.
ENVELOPE_LEASHED_MPS = 0.15

#: ``patrol/mission.py:156`` ``PatrolLimits.cruise_vx`` and
#: ``configs/robot.prototype.yaml:286`` -- the speed the product actually
#: commands when the owner says "go explore".
ENVELOPE_RESTRICTED_FREE_MPS = 0.25

#: ``configs/robot.yaml:313`` ``safety.obstacle_stop_m`` == the reactive gate's
#: commissioning floor ``reactive_safety.py:31``.  Base-center-to-surface.
ENVELOPE_OBSTACLE_STOP_RING_M = 0.65

#: ``robot_profile.py:37`` ``DEFAULT_ROBOT_PROFILE.footprint_radius_m``; also
#: mirrored by ``commissioning/limits.py:84`` for its yaw derivation.
ENVELOPE_FOOTPRINT_RADIUS_M = 0.32

#: ``robot_profile.py:56`` ``reaction_latency_s`` and ``:49``
#: ``decel_max_mps2`` -- the two terms ``SafetyEnvelope.stop_distance`` uses.
#: They produce ``modelled_travel_m`` below, which is REPORTED beside the
#: measured sum and is never part of the verdict: it is the planner's premise,
#: not evidence.
ENVELOPE_MODEL_REACTION_S = 0.12
ENVELOPE_MODEL_DECEL_MPS2 = 1.4

#: The five terms of the HLD sentence, in the order it names them. Four are
#: seconds and multiply the regime speed; the fifth is already metres.
ENVELOPE_DELAY_TERMS_V1 = (
    "candidate_age_s",
    "ipc_delay_s",
    "gateway_period_s",
    "stop_command_to_standstill_s",
)
ENVELOPE_DISTANCE_TERMS_V1 = ("localization_jump_m",)
ENVELOPE_TERMS_V1 = ENVELOPE_DELAY_TERMS_V1 + ENVELOPE_DISTANCE_TERMS_V1


class Unmeasured(Enum):
    """The type of :data:`UNMEASURED`.

    An ``Enum`` rather than a bare sentinel object so ``float | Unmeasured``
    is a checkable annotation and ``is UNMEASURED`` is the only test any
    consumer needs.
    """

    TOKEN = "UNMEASURED"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return "UNMEASURED"


#: The one sentinel. A term that is this has not been measured on this host.
UNMEASURED: Final = Unmeasured.TOKEN

#: How the sentinel is written in a record file.
UNMEASURED_LITERAL = "UNMEASURED"

EnvelopeInputValue: TypeAlias = "float | Unmeasured"


@dataclass(frozen=True, slots=True)
class StoppingRegimeV1:
    """One commissioned speed regime and the travel its clearance allows."""

    name: str
    speed_mps: float
    speed_source: str
    envelope_m: float
    envelope_source: str

    @property
    def modelled_travel_m(self) -> float:
        """``v*tau + v^2/(2a)`` -- what the planner's own envelope assumes."""

        return (
            self.speed_mps * ENVELOPE_MODEL_REACTION_S
            + self.speed_mps**2 / (2.0 * ENVELOPE_MODEL_DECEL_MPS2)
        )


#: The room between the ring where the reactive gate commands a stop and the
#: obstacle's surface: cross it and the body touches. Derived, not chosen.
ENVELOPE_REACTIVE_ROOM_M = ENVELOPE_OBSTACLE_STOP_RING_M - ENVELOPE_FOOTPRINT_RADIUS_M

_REACTIVE_ROOM_SOURCE = (
    "configs/robot.yaml safety.obstacle_stop_m 0.65 (reactive_safety.py:31) "
    "minus robot_profile.py:37 footprint_radius_m 0.32 -- the room between the "
    "ring where the reactive gate stops and the obstacle surface"
)

ENVELOPE_REGIMES_V1: tuple[StoppingRegimeV1, ...] = (
    StoppingRegimeV1(
        name="one_axis",
        speed_mps=ENVELOPE_ONE_AXIS_MPS,
        speed_source="commissioning/limits.py:78 MAX_LINEAR_MPS",
        envelope_m=ENVELOPE_ONE_AXIS_MPS * ENVELOPE_STOP_TIMEOUT_S,
        envelope_source=(
            "MAX_LINEAR_MPS * stop_timeout_s (configs/robot.yaml control."
            "stop_timeout_s 1.0); W0-B bounds the whole step at 0.05*2.0=0.10 m "
            "(commissioning/limits.py:52) and this is its stop half"
        ),
    ),
    StoppingRegimeV1(
        name="leashed",
        speed_mps=ENVELOPE_LEASHED_MPS,
        speed_source="WAVE3_HW_DESIGN_FABLE.md 6/9 HW-12; no config source today",
        envelope_m=ENVELOPE_REACTIVE_ROOM_M,
        envelope_source=_REACTIVE_ROOM_SOURCE,
    ),
    StoppingRegimeV1(
        name="restricted_free",
        speed_mps=ENVELOPE_RESTRICTED_FREE_MPS,
        speed_source="patrol/mission.py:156 PatrolLimits.cruise_vx",
        envelope_m=ENVELOPE_REACTIVE_ROOM_M,
        envelope_source=_REACTIVE_ROOM_SOURCE,
    ),
)

#: Until the envelope row is green with measured numbers the commissioned
#: regime is the slowest one (design 6: "until it passes, the commissioned
#: speed is the one-axis" step).
DEFAULT_ACTIVE_REGIME = "one_axis"


def envelope_regime(name: str) -> StoppingRegimeV1:
    """The regime by name; unknown names raise rather than defaulting."""

    for regime in ENVELOPE_REGIMES_V1:
        if regime.name == name:
            return regime
    known = ", ".join(regime.name for regime in ENVELOPE_REGIMES_V1)
    raise ValueError(f"unknown stopping regime {name!r}; known regimes: {known}")


def _envelope_term(value: object, term: str) -> EnvelopeInputValue:
    """A term is the sentinel or a finite, non-negative number of s / m."""

    if value is UNMEASURED or value == UNMEASURED_LITERAL:
        return UNMEASURED
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(
            f"stopping-envelope term {term!r} must be a number or "
            f"{UNMEASURED_LITERAL!r}, got {value!r}"
        )
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(
            f"stopping-envelope term {term!r} must be finite and non-negative, got {number!r}"
        )
    return number


@dataclass(frozen=True, slots=True)
class StoppingEnvelopeInputsV1:
    """The five measured terms of HLD 8.8, each with its provenance.

    ``provenance`` is a tuple of pairs rather than a mapping so the record
    stays frozen and comparable; every term must carry one, including an
    UNMEASURED term -- which then has to say what WILL measure it.
    """

    #: Seconds. Age of the freshest robot state the writer consults when it
    #: builds the command it is about to stop. On the dog its floor is one
    #: publish period of ``rt/sportmodestate``. BOX_DAY_INPUTS.md row I1.
    candidate_age_s: EnvelopeInputValue = UNMEASURED
    #: Seconds. Command submit -> ack over the local socket to the sole-writer
    #: gateway, p99 over >= 2000 commands. BOX_DAY_INPUTS.md row I2.
    ipc_delay_s: EnvelopeInputValue = UNMEASURED
    #: Seconds. Worst wake-to-wake interval of the gateway watchdog UNDER
    #: LOAD, not the nominal 1/50 s. BOX_DAY_INPUTS.md row B1.
    gateway_period_s: EnvelopeInputValue = UNMEASURED
    #: Seconds. Time from the gateway ISSUING the stop command to STANDSTILL
    #: -- settled under the commissioning settled-speed threshold AND planted
    #: on the foot-force trace. **Never the vendor's reaction delay alone**: a
    #: reaction-only number drops the whole deceleration distance (``v^2 /
    #: (2 a_b)``, 22-62 mm at 0.25 m/s against a 330 mm envelope) and would
    #: under-count travel. Named for its endpoints so a record-writer cannot
    #: read HLD 8.8's "vendor braking latency" as the reaction delay.
    #: BOX_DAY_INPUTS.md row B2.
    stop_command_to_standstill_s: EnvelopeInputValue = UNMEASURED
    #: Metres. Largest single-update discontinuity of the LIO ``T_map_odom``
    #: (ISO/TS-15066 ``Zr``). NOT multiplied by the speed: a loop-closure jump
    #: displaces the world whether the robot is moving or not.
    #: BOX_DAY_INPUTS.md row B3.
    localization_jump_m: EnvelopeInputValue = UNMEASURED
    provenance: tuple[tuple[str, str], ...] = ()
    active_regime: str = DEFAULT_ACTIVE_REGIME
    host: str = "unknown"
    source: str = ""

    def __post_init__(self) -> None:
        for term in ENVELOPE_TERMS_V1:
            object.__setattr__(self, term, _envelope_term(getattr(self, term), term))
        envelope_regime(self.active_regime)
        recorded = dict(self.provenance)
        if len(recorded) != len(self.provenance):
            raise ValueError("stopping-envelope provenance has a duplicate term")
        unknown = sorted(set(recorded) - set(ENVELOPE_TERMS_V1))
        if unknown:
            raise ValueError(f"stopping-envelope provenance names unknown term(s): {unknown}")
        for term in ENVELOPE_TERMS_V1:
            text = recorded.get(term, "")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(
                    f"stopping-envelope term {term!r} has no provenance; an unmeasured "
                    "term must say what will measure it"
                )

    def value(self, term: str) -> EnvelopeInputValue:
        if term not in ENVELOPE_TERMS_V1:
            raise ValueError(f"unknown stopping-envelope term {term!r}")
        return getattr(self, term)  # type: ignore[no-any-return]

    def provenance_of(self, term: str) -> str:
        return dict(self.provenance)[term]

    def missing(self) -> tuple[str, ...]:
        """The terms nobody has measured on this host, in HLD order."""

        return tuple(term for term in ENVELOPE_TERMS_V1 if self.value(term) is UNMEASURED)

    def fully_measured(self) -> bool:
        return not self.missing()


@dataclass(frozen=True, slots=True)
class EnvelopeVerdictV1:
    """One regime's answer. ``state`` is UNMEASURED / FITS / OVER."""

    regime: str
    speed_mps: float
    envelope_m: float
    modelled_travel_m: float
    state: str
    required_m: float | None
    headroom_m: float | None
    missing: tuple[str, ...]
    contributions: tuple[tuple[str, float], ...]

    @property
    def fits(self) -> bool:
        return self.state == "FITS"

    def line(self) -> str:
        """One line for the gate row and for a status doc."""

        head = f"{self.regime} @ {self.speed_mps:g} m/s, envelope {self.envelope_m:.3f} m"
        if self.required_m is None or self.headroom_m is None:
            return f"{head}: UNMEASURED - {', '.join(self.missing)}"
        verb = "fits" if self.fits else "EXCEEDS"
        return (
            f"{head}: {self.state} - needs {self.required_m:.3f} m, {verb} by "
            f"{abs(self.headroom_m):.3f} m (model assumes {self.modelled_travel_m:.3f} m)"
        )


def derive_envelope(
    inputs: StoppingEnvelopeInputsV1, regime: StoppingRegimeV1 | str
) -> EnvelopeVerdictV1:
    """The HLD 8.8 sum against one regime's envelope. Pure: no I/O, no clock.

    ``required = v*(candidate_age + ipc + gateway_period + braking) + jump``.
    The comparison is a plain ``<=`` with no epsilon: an epsilon here is a
    silent loosening of a safety envelope, and a sum that lands exactly on the
    envelope is the last value that fits.
    """

    chosen = envelope_regime(regime) if isinstance(regime, str) else regime
    missing = inputs.missing()
    if missing:
        return EnvelopeVerdictV1(
            regime=chosen.name,
            speed_mps=chosen.speed_mps,
            envelope_m=chosen.envelope_m,
            modelled_travel_m=chosen.modelled_travel_m,
            state="UNMEASURED",
            required_m=None,
            headroom_m=None,
            missing=missing,
            contributions=(),
        )
    contributions = tuple(
        (term, chosen.speed_mps * float(inputs.value(term))) for term in ENVELOPE_DELAY_TERMS_V1
    ) + tuple((term, float(inputs.value(term))) for term in ENVELOPE_DISTANCE_TERMS_V1)
    required = math.fsum(metres for _term, metres in contributions)
    headroom = chosen.envelope_m - required
    return EnvelopeVerdictV1(
        regime=chosen.name,
        speed_mps=chosen.speed_mps,
        envelope_m=chosen.envelope_m,
        modelled_travel_m=chosen.modelled_travel_m,
        state="FITS" if required <= chosen.envelope_m else "OVER",
        required_m=required,
        headroom_m=headroom,
        missing=(),
        contributions=contributions,
    )


def derive_envelope_rows(
    inputs: StoppingEnvelopeInputsV1,
) -> tuple[EnvelopeVerdictV1, ...]:
    """Every regime, in table order. The gate prints all and gates on one."""

    return tuple(derive_envelope(inputs, regime) for regime in ENVELOPE_REGIMES_V1)


#: Schema string a record must declare, so a v2 shape cannot be read as a v1.
ENVELOPE_RECORD_SCHEMA_V1 = "parcel.stopping_envelope.v1"

#: Where per-host records live, relative to the repo root.
ENVELOPE_RECORD_DIR = "configs/envelope"

#: Always present, always all-UNMEASURED: a fresh clone and the hosted runner
#: get an honest soft row instead of a missing file.
ENVELOPE_RECORD_DEFAULT = "default.yaml"

#: Override for a test rig or a one-off measurement run.
ENVELOPE_RECORD_ENV = "PARCEL_ENVELOPE_RECORD"


def resolve_stopping_envelope_record(
    root: Path,
    *,
    hostname: str | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """``$PARCEL_ENVELOPE_RECORD`` -> ``<host>.yaml`` -> ``default.yaml``."""

    environ = os.environ if env is None else env
    override = environ.get(ENVELOPE_RECORD_ENV, "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.is_absolute() else root / candidate
    directory = root / ENVELOPE_RECORD_DIR
    host = hostname if hostname is not None else socket.gethostname()
    per_host = directory / f"{host}.yaml"
    if per_host.is_file():
        return per_host
    return directory / ENVELOPE_RECORD_DEFAULT


def load_stopping_envelope_record(path: Path) -> StoppingEnvelopeInputsV1:
    """Read one record. Fail-closed on shape: this file is evidence."""

    import yaml

    # Re-raised as ValueError so a consumer needs no yaml import to catch a
    # broken record: `scripts/ci_gate.py` deliberately imports nothing from the
    # product package at module scope.
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"{path.name}: not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise TypeError(f"{path.name}: a stopping-envelope record must be a mapping")
    schema = document.get("schema")
    if schema != ENVELOPE_RECORD_SCHEMA_V1:
        raise ValueError(
            f"{path.name}: schema is {schema!r}, expected {ENVELOPE_RECORD_SCHEMA_V1!r}"
        )
    measurements = document.get("measurements")
    if not isinstance(measurements, dict):
        raise TypeError(f"{path.name}: 'measurements' must be a mapping of term -> entry")
    unknown = sorted(set(measurements) - set(ENVELOPE_TERMS_V1))
    if unknown:
        raise ValueError(f"{path.name}: unknown measurement term(s): {unknown}")
    absent = sorted(set(ENVELOPE_TERMS_V1) - set(measurements))
    if absent:
        raise ValueError(f"{path.name}: missing measurement term(s): {absent}")
    values: dict[str, object] = {}
    provenance: list[tuple[str, str]] = []
    for term in ENVELOPE_TERMS_V1:
        entry = measurements[term]
        if not isinstance(entry, dict) or set(entry) != {"value", "provenance"}:
            raise ValueError(
                f"{path.name}: term {term!r} must be a mapping with exactly "
                "'value' and 'provenance'"
            )
        values[term] = entry["value"]
        provenance.append((term, str(entry["provenance"])))
    return StoppingEnvelopeInputsV1(
        provenance=tuple(provenance),
        active_regime=str(document.get("active_regime", DEFAULT_ACTIVE_REGIME)),
        host=str(document.get("host", "unknown")),
        source=str(path),
        **values,  # type: ignore[arg-type]
    )


# ---- END CARD HW-6 stopping-envelope ---------------------------------------


# ---- CARD HW-2 go2-backend (scrum/20260822/task_40) ------------------------
#
# THE SIXTH TERM: SCAN AGE.
#
# HLD 8.8 names five terms and HW-6 landed all five above. Its verifier noted
# what the sentence leaves out: the leashed and restricted-free envelopes ARE
# the LiDAR ring (`safety.obstacle_stop_m` minus the footprint), so the age of
# the Mid-360 frame the ring was computed from is travel the robot has already
# made against an obstacle it has not re-measured. Wave-3 design §6 assigns it
# to this card: "HW-2 adds it as a sixth term with its own provenance."
#
# It is a DELAY term (metres = v * seconds), for the same reason the other four
# are: a stale scan costs distance only while the body is moving. The one
# distance term, `localization_jump_m`, stays outside the speed product.
#
# WHY THIS IS A V2 LAYER AND NOT A SIXTH FIELD ON `StoppingEnvelopeInputsV1`.
# Measured, not assumed: adding the term to `ENVELOPE_TERMS_V1` reddens five
# assertions in `tests/test_hw6_stopping_envelope.py` — its `_inputs()` helper
# supplies five terms, so a sixth makes every arithmetic row UNMEASURED, and
# its shipped-record row pins THIS box's missing set at exactly three names.
# That file belongs to a CLOSED, verified card and is outside HW-2's OWNS,
# while HW-2's own card requires both "the record files gain the key" and
# "HW-6's tests still pass". Only one shape satisfies both: everything here is
# ADDITIVE, nothing inside HW-6's fence moves a byte, and the record files
# carry the new term in a TOP-LEVEL `scan_age:` block that
# `load_stopping_envelope_record` (which reads only `schema`, `measurements`,
# `active_regime` and `host`) ignores by construction. Both shipped records
# therefore remain valid V1 records AND valid V2 records.
#
# WHAT IS NOT DONE HERE, SAID PLAINLY. `scripts/ci_gate.py
# :evaluate_stopping_envelope` still calls `derive_envelope_rows` and prints
# the five-term row. That file is card HW-7's in wave 3b and the row's region
# is HW-6's, so this card does not touch it: the sixth term is derived,
# recorded, provenanced and tested, and it is NOT yet gate-printed. The change
# is one call swap plus the five HW-6 assertions above, and it needs the
# dispatcher's leave. `scrum/20260822/task_40/HW2_STATUS.md` carries it as a
# handoff rather than leaving a reader to discover it.

#: The sixth term's name, in records and in verdict rows.
ENVELOPE_SCAN_AGE_TERM = "scan_age_s"

#: The top-level record key that carries it. NOT a sixth entry under
#: `measurements:` — see the note above.
ENVELOPE_SCAN_AGE_KEY = "scan_age"

#: HLD's four delay terms plus scan age. Multiplied by the regime speed.
ENVELOPE_DELAY_TERMS_V2 = ENVELOPE_DELAY_TERMS_V1 + (ENVELOPE_SCAN_AGE_TERM,)

#: All six, in the order a row prints them.
ENVELOPE_TERMS_V2 = ENVELOPE_DELAY_TERMS_V2 + ENVELOPE_DISTANCE_TERMS_V1


@dataclass(frozen=True, slots=True)
class StoppingEnvelopeInputsV2:
    """HW-6's five terms plus scan age, each with its provenance.

    Composition, not inheritance: `StoppingEnvelopeInputsV1` is a frozen
    slotted dataclass whose `__post_init__` validates against
    `ENVELOPE_TERMS_V1`, and subclassing it would have to fight that. `base`
    keeps the V1 record intact and comparable; everything a consumer needs is
    forwarded.
    """

    base: StoppingEnvelopeInputsV1
    scan_age_s: EnvelopeInputValue = UNMEASURED
    scan_age_provenance: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.base, StoppingEnvelopeInputsV1):
            raise TypeError("StoppingEnvelopeInputsV2.base must be a StoppingEnvelopeInputsV1")
        object.__setattr__(
            self,
            ENVELOPE_SCAN_AGE_TERM,
            _envelope_term(self.scan_age_s, ENVELOPE_SCAN_AGE_TERM),
        )
        if not isinstance(self.scan_age_provenance, str) or not self.scan_age_provenance.strip():
            raise ValueError(
                f"stopping-envelope term {ENVELOPE_SCAN_AGE_TERM!r} has no provenance; an "
                "unmeasured term must say what will measure it"
            )

    @property
    def active_regime(self) -> str:
        return self.base.active_regime

    @property
    def host(self) -> str:
        return self.base.host

    @property
    def source(self) -> str:
        return self.base.source

    def value(self, term: str) -> EnvelopeInputValue:
        if term == ENVELOPE_SCAN_AGE_TERM:
            return self.scan_age_s
        return self.base.value(term)

    def provenance_of(self, term: str) -> str:
        if term == ENVELOPE_SCAN_AGE_TERM:
            return self.scan_age_provenance
        return self.base.provenance_of(term)

    def missing(self) -> tuple[str, ...]:
        """The unmeasured terms, in table order. Six-term version."""

        return tuple(term for term in ENVELOPE_TERMS_V2 if self.value(term) is UNMEASURED)

    def fully_measured(self) -> bool:
        return not self.missing()


def derive_envelope_v2(
    inputs: StoppingEnvelopeInputsV2, regime: StoppingRegimeV1 | str
) -> EnvelopeVerdictV1:
    """`required = v*(cand + ipc + period + braking + scan_age) + jump`.

    Pure, and the same arithmetic contract as `derive_envelope`: `math.fsum`
    over the contributions and a plain `<=` with no epsilon, because an epsilon
    on a safety envelope is a silent loosening. Returns the SAME
    `EnvelopeVerdictV1` HW-6 defined, so every consumer of a verdict — the gate
    row's formatter, a status doc, HW-12's commissioning check — reads six
    terms without learning a new type.
    """

    chosen = envelope_regime(regime) if isinstance(regime, str) else regime
    missing = inputs.missing()
    if missing:
        return EnvelopeVerdictV1(
            regime=chosen.name,
            speed_mps=chosen.speed_mps,
            envelope_m=chosen.envelope_m,
            modelled_travel_m=chosen.modelled_travel_m,
            state="UNMEASURED",
            required_m=None,
            headroom_m=None,
            missing=missing,
            contributions=(),
        )
    contributions = tuple(
        (term, chosen.speed_mps * float(inputs.value(term))) for term in ENVELOPE_DELAY_TERMS_V2
    ) + tuple((term, float(inputs.value(term))) for term in ENVELOPE_DISTANCE_TERMS_V1)
    required = math.fsum(metres for _term, metres in contributions)
    headroom = chosen.envelope_m - required
    return EnvelopeVerdictV1(
        regime=chosen.name,
        speed_mps=chosen.speed_mps,
        envelope_m=chosen.envelope_m,
        modelled_travel_m=chosen.modelled_travel_m,
        state="FITS" if required <= chosen.envelope_m else "OVER",
        required_m=required,
        headroom_m=headroom,
        missing=(),
        contributions=contributions,
    )


def derive_envelope_rows_v2(
    inputs: StoppingEnvelopeInputsV2,
) -> tuple[EnvelopeVerdictV1, ...]:
    """Every regime, in table order, with the sixth term in the sum."""

    return tuple(derive_envelope_v2(inputs, regime) for regime in ENVELOPE_REGIMES_V1)


def load_stopping_envelope_record_v2(path: Path) -> StoppingEnvelopeInputsV2:
    """Read one record as six terms. Fail-closed on shape: this file is evidence.

    The V1 half is read by `load_stopping_envelope_record` itself rather than
    re-implemented -- the five terms have exactly one reader. The file is
    therefore opened twice, which is ~2 kB and buys the guarantee that a V2
    read and a V1 read of the same file can never disagree about the five.
    """

    import yaml

    base = load_stopping_envelope_record(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - V1 already refused it
        raise ValueError(f"{path.name}: not valid YAML: {exc}") from exc
    entry = document.get(ENVELOPE_SCAN_AGE_KEY)
    if entry is None:
        raise ValueError(
            f"{path.name}: no top-level {ENVELOPE_SCAN_AGE_KEY!r} block; the sixth "
            f"stopping-envelope term ({ENVELOPE_SCAN_AGE_TERM}) has no record here. "
            "A term nobody wrote down is not the same as a term measured at zero."
        )
    if not isinstance(entry, dict) or set(entry) != {"value", "provenance"}:
        raise ValueError(
            f"{path.name}: {ENVELOPE_SCAN_AGE_KEY!r} must be a mapping with exactly "
            "'value' and 'provenance'"
        )
    return StoppingEnvelopeInputsV2(
        base=base,
        scan_age_s=entry["value"],  # type: ignore[arg-type]
        scan_age_provenance=str(entry["provenance"]),
    )


# ---- END CARD HW-2 go2-backend ---------------------------------------------
