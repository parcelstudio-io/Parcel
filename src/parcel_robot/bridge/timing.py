"""Executable RC-4 TTL/latency derivation for the N24 fake gateway slice."""

from __future__ import annotations

from dataclasses import dataclass

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
