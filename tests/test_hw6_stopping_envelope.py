"""Card HW-6 `stopping-envelope` (scrum/20260822/task_38).

The RC-4 pins in the first section were written and run GREEN **before** a
byte of ``bridge/timing.py`` was edited: this card adds a derivation beside
the frozen RC-4 table (``docs/GATEWAY_TTL_LATENCY_DERIVATION.md``, which it
must not touch), so the table's immutability is the first thing proved, not
the last.
"""

from __future__ import annotations

import copy
import hashlib
import math
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from parcel_robot.authority import CLEARANCE_CONVENTION, DEFAULT_ROBOT_PROFILE
from parcel_robot.bridge import timing
from parcel_robot.bridge.client import FakeGatewayClientV1
from parcel_robot.bridge.protocol import GatewayAckDispositionV1
from parcel_robot.bridge.timing import (
    PROPOSED_LATENCY_GATES_V1,
    latency_derivation_rows,
    render_commissioning_h2_markdown,
    render_latency_derivation_markdown,
)
from parcel_robot.commissioning import limits
from parcel_robot.control.models import ControlTiming
from parcel_robot.navigation.reactive_safety import ReactiveSafetyPolicy
from parcel_robot.patrol.mission import PatrolLimits
from scripts import ci_gate

REPO = Path(__file__).resolve().parents[1]

# ===========================================================================
# A1/A2 — the RC-4 derivation is byte-identical before and after this card
# ===========================================================================

#: sha256 of the two tables as rendered on 2026-08-23 at HEAD e15e466, taken
#: BEFORE the `CARD HW-6` region existed. Both strings are embedded verbatim
#: in `docs/GATEWAY_TTL_LATENCY_DERIVATION.md` and pinned a second way by
#: `tests/test_gateway_protocol_v1.py`.
RC4_LATENCY_TABLE_SHA256 = "466cad1f6064781f9a94f3bdb79a4c3b2bb4d09d50175bedb9449cca5559bce6"
RC4_H2_TABLE_SHA256 = "2a2927d5ea9dce9f0e3cfa973f1774a3edb1189bcd5879cceebc2650ac86ed2f"

#: Every numeric field of the four rows, hand-copied from the pre-edit run.
RC4_EXPECTED_ROWS = (
    ("sensor_invalidation", 100.0, 5.0, 0.03, 0.05),
    ("emergency_stop_initiation", 150.0, 7.5, 0.045, 0.075),
    ("client_or_lease_loss_stop_initiation", 150.0, 7.5, 0.045, 0.075),
    ("gateway_scheduling_jitter", 2.0, 0.1, 0.0006, 0.001),
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_the_rc4_rows_and_rendered_tables_are_byte_identical() -> None:
    """Row A1/A2. Seed S3 reddens this by moving one `proposed_p99_ms`."""

    rows = latency_derivation_rows()
    assert len(rows) == len(PROPOSED_LATENCY_GATES_V1) == 4
    for row, (gate_id, p99_ms, periods, d_min, d_max) in zip(rows, RC4_EXPECTED_ROWS, strict=True):
        assert row["gate_id"] == gate_id
        assert row["proposed_p99_ms"] == p99_ms
        assert row["gate_periods"] == periods
        assert row["control_period_ms"] == 20.0
        assert row["live_ttl_ms"] == 350.0
        assert row["ttl_periods"] == 17.5
        assert round(float(row["distance_at_0_3_mps_m"]), 12) == d_min
        assert round(float(row["distance_at_0_5_mps_m"]), 12) == d_max
        assert row["ttl_distance_at_0_3_mps_m"] == 0.105
        assert row["ttl_distance_at_0_5_mps_m"] == 0.175

    assert _sha256(render_latency_derivation_markdown()) == RC4_LATENCY_TABLE_SHA256
    assert _sha256(render_commissioning_h2_markdown()) == RC4_H2_TABLE_SHA256


# ===========================================================================
# D1/D2 — the two terms THIS box can measure, through the real N24 process
#
# `bridge/fake_gateway_process.py` over an AF_UNIX SOCK_SEQPACKET socket,
# driven by `bridge/client.py:FakeGatewayClientV1` — the same path
# `tests/test_gateway_process.py` spawns. Nothing is stubbed and nothing is
# monkeypatched: the numbers recorded in `configs/envelope/<host>.yaml` come
# out of this function.
#
# WHAT THE TWO TERMS MEAN HERE, AND WHAT THEY DO NOT.
#   ipc_delay_s     — submit → ack round trip over the seqpacket socket. On
#                     the dog this is the same shape (local socket to the
#                     native gateway) but a different process, a different
#                     kernel and a different CPU.
#   candidate_age_s — `GatewayStateV1.state_age_ms`: the age of the freshest
#                     robot state the writer can consult when it builds a
#                     command. On the dog it is set by the 50 Hz
#                     `rt/sportmodestate` publisher, NOT by this fake sport
#                     service, so this number is a floor, not a prediction.
# Both are recorded as p99, because the sentence asks for the worst case.
# ===========================================================================

DEFAULT_MEASUREMENT_SAMPLES = 300


def _accepted(ack: object) -> bool:
    return getattr(ack, "disposition", None) is GatewayAckDispositionV1.ACCEPTED


def _p99(values: list[float]) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(0.99 * len(ordered)) - 1)
    return ordered[max(index, 0)]


def measure_n24_envelope_inputs(samples: int, tmp_path: Path) -> dict[str, float]:
    """Round-trip and state-age percentiles from the real fake-gateway process."""

    socket_path = tmp_path / "hw6.sock"
    event_log = tmp_path / "hw6_events.jsonl"
    gateway = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "parcel_robot.bridge.fake_gateway_process",
            "--socket",
            str(socket_path),
            "--event-log",
            str(event_log),
        ],
        cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    round_trips: list[float] = []
    ages_s: list[float] = []
    try:
        deadline = time.monotonic() + 10.0
        client = None
        while client is None and time.monotonic() < deadline:
            try:
                client = FakeGatewayClientV1.connect(socket_path, timeout_s=0.2)
            except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError):
                time.sleep(0.01)
        if client is None:  # pragma: no cover - the process failed to start
            raise AssertionError("the fake gateway never opened its socket")
        with client:
            ack = client.acquire(writer_id="hw6-envelope", sequence=1)
            assert _accepted(ack), f"lease refused: {ack}"
            for index in range(samples):
                start = time.perf_counter()
                reply = client.command(
                    writer_id="hw6-envelope", sequence=index + 2, vx_mps=0.02
                )
                round_trips.append(time.perf_counter() - start)
                assert _accepted(reply), f"command refused: {reply}"
                ages_s.append(client.state(sequence=index + 2).state_age_ms / 1000.0)
    finally:
        if gateway.poll() is None:
            gateway.terminate()
            try:
                gateway.wait(timeout=5.0)
            except subprocess.TimeoutExpired:  # pragma: no cover - defensive
                gateway.kill()
                gateway.wait(timeout=5.0)
    return {
        "samples": float(len(round_trips)),
        "ipc_delay_s_p99": _p99(round_trips),
        "ipc_delay_s_median": sorted(round_trips)[len(round_trips) // 2],
        "candidate_age_s_p99": _p99(ages_s),
        "candidate_age_s_median": sorted(ages_s)[len(ages_s) // 2],
    }


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(socket, "SOCK_SEQPACKET"),
    reason="the N24 path needs Unix SOCK_SEQPACKET",
)
def test_the_two_dev_box_terms_are_measurable_on_the_n24_path(tmp_path, capsys) -> None:
    """Rows D1/D2. Bounds are sanity bounds, not the recorded numbers.

    The record's values were taken from this same function with
    ``PARCEL_HW6_SAMPLES=2000``; the assertion here is only that the path is
    alive and two orders of magnitude away from anything that would matter,
    so the test cannot flake on a loaded box.
    """

    samples = int(os.environ.get("PARCEL_HW6_SAMPLES", DEFAULT_MEASUREMENT_SAMPLES))
    measured = measure_n24_envelope_inputs(samples, tmp_path)
    with capsys.disabled():
        print(f"\nHW-6 N24 measurement ({samples} samples): {measured}")
    assert measured["samples"] == samples
    assert 0.0 < measured["ipc_delay_s_p99"] < 0.5
    assert 0.0 <= measured["candidate_age_s_p99"] < 0.5


# ===========================================================================
# B3 — the mirrors. `bridge/timing.py` may not import the commissioning
# package (its own rule, `timing.py:26-31`), so every limit it uses is a
# mirrored literal. These are what make "mirrored" mean something.
# ===========================================================================

ROBOT_YAML = yaml.safe_load((REPO / "configs" / "robot.yaml").read_text(encoding="utf-8"))


def test_the_envelope_mirrors_equal_their_sources() -> None:
    """Row B3. A limit that moves without a new derivation reddens here."""

    assert timing.ENVELOPE_ONE_AXIS_MPS == limits.MAX_LINEAR_MPS == 0.05
    assert (
        timing.ENVELOPE_STOP_TIMEOUT_S
        == ControlTiming().stop_timeout_s
        == float(ROBOT_YAML["control"]["stop_timeout_s"])
        == limits.DEFAULT_MAX_DURATION_S
        == 1.0
    )
    assert (
        timing.ENVELOPE_OBSTACLE_STOP_RING_M
        == float(ROBOT_YAML["safety"]["obstacle_stop_m"])
        == ReactiveSafetyPolicy().obstacle_stop_m
        == 0.65
    )
    assert (
        timing.ENVELOPE_FOOTPRINT_RADIUS_M
        == DEFAULT_ROBOT_PROFILE.footprint_radius_m
        == limits.FOOTPRINT_RADIUS_M
        == 0.32
    )
    assert timing.ENVELOPE_MODEL_REACTION_S == DEFAULT_ROBOT_PROFILE.reaction_latency_s == 0.12
    assert timing.ENVELOPE_MODEL_DECEL_MPS2 == DEFAULT_ROBOT_PROFILE.decel_max_mps2 == 1.4
    assert timing.ENVELOPE_RESTRICTED_FREE_MPS == PatrolLimits().cruise_vx == 0.25


def test_the_clearance_convention_is_the_one_the_authority_declares() -> None:
    """The envelope column subtracts the footprint from a base-center-to-
    surface ring exactly once; if that convention ever changes, the derivation
    below it is wrong and this is where it is caught."""

    assert CLEARANCE_CONVENTION == "base_center_to_obstacle_surface"
    assert timing.ENVELOPE_REACTIVE_ROOM_M == pytest.approx(0.33, abs=1e-9)


# ===========================================================================
# B2 — the three regimes
# ===========================================================================

EXPECTED_REGIMES = (
    ("one_axis", 0.05, 0.050),
    ("leashed", 0.15, 0.330),
    ("restricted_free", 0.25, 0.330),
)


def test_the_three_regimes_carry_the_designed_speeds_and_envelopes() -> None:
    """Row B2."""

    assert tuple(r.name for r in timing.ENVELOPE_REGIMES_V1) == tuple(
        name for name, _speed, _envelope in EXPECTED_REGIMES
    )
    for regime, (name, speed, envelope) in zip(
        timing.ENVELOPE_REGIMES_V1, EXPECTED_REGIMES, strict=True
    ):
        assert regime.name == name
        assert regime.speed_mps == pytest.approx(speed, abs=1e-12)
        assert regime.envelope_m == pytest.approx(envelope, abs=1e-9)
        assert regime.speed_source and regime.envelope_source
    # The default active regime is the slowest one: design §6 says the
    # commissioned speed stays the one-axis step until this row is green.
    assert timing.DEFAULT_ACTIVE_REGIME == "one_axis"
    assert timing.envelope_regime("one_axis") is timing.ENVELOPE_REGIMES_V1[0]
    with pytest.raises(ValueError, match="unknown stopping regime"):
        timing.envelope_regime("sprint")


def test_the_modelled_travel_is_reported_but_is_not_the_verdict() -> None:
    """`v*tau + v^2/(2a)` — what SafetyEnvelope.stop_distance assumes. It is
    printed beside the measured sum so a reader can see the gap; nothing in
    `derive_envelope` compares against it."""

    leashed = timing.envelope_regime("leashed")
    assert leashed.modelled_travel_m == pytest.approx(
        0.15 * 0.12 + 0.15**2 / (2 * 1.4), abs=1e-12
    )
    assert leashed.modelled_travel_m < leashed.envelope_m


# ===========================================================================
# B1 — the arithmetic. Seed S2 (drop `+ d_localization`) reddens this.
# ===========================================================================

TERMS = ("candidate_age_s", "ipc_delay_s", "gateway_period_s", "stop_command_to_standstill_s")
PROVENANCE = tuple((term, f"seeded by {__name__}") for term in timing.ENVELOPE_TERMS_V1)


def _inputs(**overrides: object) -> timing.StoppingEnvelopeInputsV1:
    values: dict[str, object] = {
        "candidate_age_s": 0.020,
        "ipc_delay_s": 0.005,
        "gateway_period_s": 0.020,
        "stop_command_to_standstill_s": 0.450,
        "localization_jump_m": 0.200,
        "provenance": PROVENANCE,
    }
    values.update(overrides)
    return timing.StoppingEnvelopeInputsV1(**values)  # type: ignore[arg-type]


def test_the_envelope_arithmetic_is_pinned_term_by_term() -> None:
    """Row B1: required = v*(cand + ipc + period + braking) + jump."""

    verdict = timing.derive_envelope(_inputs(), "restricted_free")
    speed = 0.25
    expected = {
        "candidate_age_s": speed * 0.020,
        "ipc_delay_s": speed * 0.005,
        "gateway_period_s": speed * 0.020,
        "stop_command_to_standstill_s": speed * 0.450,
        "localization_jump_m": 0.200,
    }
    assert dict(verdict.contributions) == pytest.approx(expected, abs=1e-12)
    assert tuple(term for term, _ in verdict.contributions) == timing.ENVELOPE_TERMS_V1
    assert verdict.required_m == pytest.approx(sum(expected.values()), abs=1e-12)
    assert verdict.required_m == pytest.approx(0.25 * 0.495 + 0.200, abs=1e-12)
    assert verdict.headroom_m == pytest.approx(verdict.envelope_m - verdict.required_m, abs=1e-12)
    assert verdict.state == "FITS"
    # The distance term is metres and is NOT multiplied by the speed: at half
    # the speed the four delay terms halve and the jump does not.
    slower = timing.derive_envelope(_inputs(), "leashed")
    assert dict(slower.contributions)["localization_jump_m"] == pytest.approx(0.200, abs=1e-12)
    assert dict(slower.contributions)["stop_command_to_standstill_s"] == pytest.approx(
        0.15 * 0.450, abs=1e-12
    )


def test_a_sum_exactly_on_the_envelope_fits_and_one_ulp_over_does_not() -> None:
    """No epsilon: an epsilon on a safety envelope is a silent loosening, and
    the last value that fits is the one that lands exactly on it."""

    regime = timing.envelope_regime("one_axis")
    exact = _inputs(
        candidate_age_s=0.0,
        ipc_delay_s=0.0,
        gateway_period_s=0.0,
        stop_command_to_standstill_s=0.0,
        localization_jump_m=regime.envelope_m,
    )
    assert timing.derive_envelope(exact, regime).state == "FITS"
    over = _inputs(
        candidate_age_s=0.0,
        ipc_delay_s=0.0,
        gateway_period_s=0.0,
        stop_command_to_standstill_s=0.0,
        localization_jump_m=math.nextafter(regime.envelope_m, math.inf),
    )
    assert timing.derive_envelope(over, regime).state == "OVER"


# ===========================================================================
# B4 — the sentinel
# ===========================================================================


def test_an_unmeasured_term_poisons_the_verdict_and_names_itself() -> None:
    """Row B4. UNMEASURED is not 0.0 and not None: it produces NO number."""

    for term in timing.ENVELOPE_TERMS_V1:
        verdict = timing.derive_envelope(_inputs(**{term: timing.UNMEASURED}), "leashed")
        assert verdict.state == "UNMEASURED"
        assert verdict.missing == (term,)
        assert verdict.required_m is None
        assert verdict.headroom_m is None
        assert verdict.contributions == ()
        assert verdict.line().endswith(f"UNMEASURED - {term}")

    empty = timing.StoppingEnvelopeInputsV1(provenance=PROVENANCE)
    assert empty.missing() == timing.ENVELOPE_TERMS_V1
    assert not empty.fully_measured()
    assert empty.value("stop_command_to_standstill_s") is timing.UNMEASURED
    # The sentinel is typed and is never confused with a number or with None.
    assert timing.UNMEASURED is timing.Unmeasured.TOKEN
    assert timing.UNMEASURED is not None
    assert timing.UNMEASURED != 0.0
    assert str(timing.UNMEASURED) == "UNMEASURED"


def test_measured_terms_are_validated_at_construction() -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        _inputs(stop_command_to_standstill_s=-0.1)
    with pytest.raises(ValueError, match="finite and non-negative"):
        _inputs(stop_command_to_standstill_s=float("inf"))
    with pytest.raises(TypeError, match="must be a number"):
        _inputs(stop_command_to_standstill_s="fast")
    with pytest.raises(ValueError, match="unknown stopping regime"):
        _inputs(active_regime="sprint")
    with pytest.raises(ValueError, match="no provenance"):
        timing.StoppingEnvelopeInputsV1(provenance=PROVENANCE[:-1])


# ===========================================================================
# B5 — the record file shape (fail-closed: this file is evidence)
# ===========================================================================

VALID_RECORD = {
    "schema": "parcel.stopping_envelope.v1",
    "host": "rig",
    "active_regime": "restricted_free",
    "measurements": {
        "candidate_age_s": {"value": 0.020, "provenance": "rig"},
        "ipc_delay_s": {"value": 0.005, "provenance": "rig"},
        "gateway_period_s": {"value": 0.020, "provenance": "rig"},
        "stop_command_to_standstill_s": {"value": 0.450, "provenance": "rig"},
        "localization_jump_m": {"value": 0.200, "provenance": "rig"},
    },
}


def _write_record(path: Path, document: object) -> Path:
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_a_record_round_trips_and_the_literal_becomes_the_sentinel(tmp_path) -> None:
    """Row B5."""

    document = copy.deepcopy(VALID_RECORD)
    document["measurements"]["stop_command_to_standstill_s"]["value"] = "UNMEASURED"
    loaded = timing.load_stopping_envelope_record(
        _write_record(tmp_path / "rig.yaml", document)
    )
    assert loaded.host == "rig"
    assert loaded.active_regime == "restricted_free"
    assert loaded.stop_command_to_standstill_s is timing.UNMEASURED
    assert loaded.ipc_delay_s == 0.005
    assert loaded.missing() == ("stop_command_to_standstill_s",)
    assert loaded.provenance_of("ipc_delay_s") == "rig"
    assert loaded.source.endswith("rig.yaml")


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.__setitem__("schema", "parcel.stopping_envelope.v2"), "schema is"),
        (lambda d: d["measurements"].pop("ipc_delay_s"), "missing measurement"),
        (
            lambda d: d["measurements"].__setitem__("brake_time", {"value": 1, "provenance": "x"}),
            "unknown measurement",
        ),
        (
            lambda d: d["measurements"].__setitem__("ipc_delay_s", {"value": 0.1}),
            "exactly",
        ),
        (lambda d: d["measurements"]["ipc_delay_s"].__setitem__("value", -1.0), "non-negative"),
        (lambda d: d.__setitem__("active_regime", "sprint"), "unknown stopping regime"),
        (lambda d: d.__setitem__("measurements", []), "must be a mapping"),
    ],
)
def test_a_broken_record_is_refused_rather_than_half_read(tmp_path, mutate, match) -> None:
    """Row B5. Evidence that does not parse is not evidence."""

    document = copy.deepcopy(VALID_RECORD)
    mutate(document)
    with pytest.raises((ValueError, TypeError), match=match):
        timing.load_stopping_envelope_record(_write_record(tmp_path / "bad.yaml", document))


def test_the_record_is_resolved_by_env_then_host_then_default(tmp_path) -> None:
    directory = tmp_path / "configs" / "envelope"
    directory.mkdir(parents=True)
    (directory / "default.yaml").write_text("x", encoding="utf-8")
    resolved = timing.resolve_stopping_envelope_record(tmp_path, hostname="nowhere", env={})
    assert resolved == directory / "default.yaml"
    (directory / "somehost.yaml").write_text("x", encoding="utf-8")
    assert timing.resolve_stopping_envelope_record(
        tmp_path, hostname="somehost", env={}
    ) == directory / "somehost.yaml"
    override = tmp_path / "elsewhere.yaml"
    assert timing.resolve_stopping_envelope_record(
        tmp_path, hostname="somehost", env={timing.ENVELOPE_RECORD_ENV: str(override)}
    ) == override


# ===========================================================================
# C1-C7 — the gate row, proved IN-PROCESS.
#
# Card rule: this card runs NO gate tier (`ci_gate.py --tier` is the
# integrator's, once, at close — anti-crash rule 3). Every row below calls
# `evaluate_stopping_envelope` directly with a temp record and reads the
# returned `GateResult`, exactly as XD-1's verifier did. Nothing here starts
# a pytest, a subprocess or a simulator.
# ===========================================================================


def _row(tmp_path: Path, **overrides: object):
    document = copy.deepcopy(VALID_RECORD)
    for key, value in overrides.items():
        if key in document["measurements"]:
            document["measurements"][key]["value"] = value
        else:
            document[key] = value
    record = _write_record(tmp_path / "row.yaml", document)
    return ci_gate.evaluate_stopping_envelope(record=record)


def test_the_row_state_unmeasured_is_soft_and_names_every_missing_term(tmp_path) -> None:
    """Row C1. The state this box is in, and will be until the dog arrives."""

    result = _row(tmp_path, stop_command_to_standstill_s="UNMEASURED", gateway_period_s="UNMEASURED")
    assert result.name == "stopping-envelope"
    assert result.hard is False
    assert result.status == "pass"
    assert result.gating_red is False
    assert result.detail.startswith("UNMEASURED — gateway_period_s, stop_command_to_standstill_s")
    assert result.extra["state"] == "UNMEASURED"
    assert result.extra["missing"] == ["gateway_period_s", "stop_command_to_standstill_s"]
    assert result.extra["required_m"] is None
    # Every regime is printed, not only the active one.
    for regime in ("one_axis", "leashed", "restricted_free"):
        assert regime in result.detail


def test_the_row_state_fits_is_soft_and_shows_the_arithmetic(tmp_path) -> None:
    """Row C2."""

    result = _row(tmp_path)
    assert result.hard is False
    assert result.status == "pass"
    assert result.extra["state"] == "FITS"
    assert result.extra["active_regime"] == "restricted_free"
    assert result.extra["required_m"] == pytest.approx(0.25 * 0.495 + 0.2, abs=1e-12)
    assert result.extra["envelope_m"] == pytest.approx(0.33, abs=1e-9)
    assert result.extra["headroom_m"] == pytest.approx(0.006, abs=1e-3)
    assert "fits at the active regime" in result.detail


def test_fifty_milliseconds_of_extra_braking_latency_reddens_the_row(tmp_path) -> None:
    """Row C3 — the card's seed, in one test.

    The record fits with 0.450 s of vendor braking latency and 6 mm to spare;
    at 0.500 s the same record does not fit, and the row is the only thing in
    the commit tier that says so.
    """

    fits = _row(tmp_path, stop_command_to_standstill_s=0.450)
    assert fits.status == "pass" and fits.hard is False
    assert fits.extra["headroom_m"] == pytest.approx(0.00625, abs=1e-9)

    over = _row(tmp_path, stop_command_to_standstill_s=0.500)
    assert over.hard is True
    assert over.status == "fail"
    assert over.gating_red is True
    assert over.extra["state"] == "OVER"
    assert over.extra["headroom_m"] == pytest.approx(-0.00625, abs=1e-9)
    assert "does NOT fit" in over.detail
    assert "restricted_free" in over.detail
    # The overrun is 50 ms of braking at 0.25 m/s = 12.5 mm of travel, which
    # is exactly the swing from +6.25 mm of headroom to -6.25 mm.
    assert fits.extra["headroom_m"] - over.extra["headroom_m"] == pytest.approx(
        0.25 * 0.050, abs=1e-12
    )


def test_only_the_active_regime_can_redden_the_row(tmp_path) -> None:
    """Row C4. HLD 8.8 says "at the ACTIVE speed regime"; a regime nobody has
    commissioned must not block a commit — but it is still printed."""

    # 0.500 s of braking fits the leash (0.15 m/s x 0.545 s + 0.2 m = 0.282 m
    # of 0.330 m) and does NOT fit the roam speed (0.336 m of 0.330 m).
    result = _row(tmp_path, stop_command_to_standstill_s=0.500, active_regime="leashed")
    assert result.hard is False
    assert result.status == "pass"
    assert result.extra["state"] == "FITS"
    assert result.extra["regimes"]["leashed"]["state"] == "FITS"
    assert result.extra["regimes"]["restricted_free"]["state"] == "OVER"
    # ... and the over-budget regime is still on the page, marked OVER.
    assert "restricted_free" in result.detail
    assert "EXCEEDS" in result.detail


def test_the_one_axis_regime_is_the_strictest_and_reddens_first(tmp_path) -> None:
    """The slowest regime has the smallest envelope (0.05 m), so a chain that
    fits the leash does not necessarily fit the commissioning step. This is
    the whole reason the row is per-regime."""

    result = _row(tmp_path, active_regime="one_axis")
    assert result.hard is True
    assert result.extra["regimes"]["one_axis"]["state"] == "OVER"
    assert result.extra["regimes"]["leashed"]["state"] == "FITS"


def test_a_broken_record_is_a_visible_but_non_gating_error(tmp_path) -> None:
    """Row C5. GATE-0b's trade: a broken evidence file is an ERROR row, not a
    red build. `test_the_shipped_records_...` below is what makes a broken
    SHIPPED record red somewhere."""

    absent = ci_gate.evaluate_stopping_envelope(record=tmp_path / "nope.yaml")
    assert absent.status == "error"
    assert absent.hard is False
    assert absent.gating_red is False
    assert "FileNotFoundError" in absent.detail

    (tmp_path / "junk.yaml").write_text("schema: nope\n", encoding="utf-8")
    broken = ci_gate.evaluate_stopping_envelope(record=tmp_path / "junk.yaml")
    assert broken.status == "error"
    assert broken.hard is False
    assert "schema is" in broken.detail


#: Hostnames the shipped records must all answer honestly. `fv-az…` is the
#: `ubuntu-latest` shape (`.github/workflows/ci.yml` runs `--tier commit`
#: there); the second stands in for a host that has not written a record yet,
#: and the third is this box.
#:
#: The placeholder is deliberately FICTIONAL rather than `orin-nx`: on box day
#: the Orin gets its own `configs/envelope/<its-hostname>.yaml`, and a test
#: whose `else` branch asserts `default.yaml` would then fail for a reason
#: that has nothing to do with what it is testing (verifier N12). No host may
#: ever be named `fictional-orin-host`, so the branch stays true forever.
#: Only this box has a record here; the other two fall back, which is exactly
#: why this test may not pin one host's term list.
HOSTNAMES_THE_ROW_MUST_SURVIVE = (
    "jaewoo-jang-parcel",
    "fv-az1234-567",
    "fictional-orin-host",
)

#: The dev box is the only host in the tree with its own record.
DEV_BOX_HOSTNAME = "jaewoo-jang-parcel"


@pytest.mark.parametrize("hostname", HOSTNAMES_THE_ROW_MUST_SURVIVE)
def test_the_shipped_records_are_valid_and_the_row_follows_the_resolved_one(
    hostname: str,
) -> None:
    """Row C6, and the target of seed S1 — asserted STRUCTURALLY.

    An earlier form of this test pinned `missing` to THIS box's three terms.
    That is a property of one file on one machine: on `ubuntu-latest` (whose
    hostnames are `fv-az…`) and on the Orin the resolver falls to
    `configs/envelope/default.yaml`, where all five terms are UNMEASURED, and
    the pinned assertion would have reddened the hosted commit tier on the
    first push — `default-suite` is a hard row and does not deselect this
    file. Verifier finding F1.

    What is invariant, and what this asserts instead: whatever record the
    resolver picks, the row reports THAT record's missing terms, points at
    THAT file, and never gates. The dev box's three terms are asserted only
    where they are true — against the dev-box record itself.
    """

    resolved = timing.resolve_stopping_envelope_record(REPO, hostname=hostname, env={})
    assert resolved.is_file(), f"no shipped record resolves for {hostname!r}"
    record = timing.load_stopping_envelope_record(resolved)
    result = ci_gate.evaluate_stopping_envelope(record=resolved)

    # Invariant 1: a shipped record never gates. This is what seed S1 targets.
    assert result.hard is False, f"the shipped record must not gate: {result.detail}"
    assert result.status == "pass"
    assert result.gating_red is False
    # Invariant 2: the row reports the resolved record's own terms, whichever
    # file that is — no host's term list is written into this test.
    assert result.extra["record"] == str(resolved)
    assert set(result.extra["missing"]) == set(record.missing())
    assert result.extra["state"] == ("UNMEASURED" if record.missing() else result.extra["state"])
    # Invariant 3: every term carries a provenance line, measured or not.
    for term in timing.ENVELOPE_TERMS_V1:
        assert len(record.provenance_of(term).strip()) > 40
    # Invariant 4: the fallback is complete-and-empty; a host with no record
    # of its own must not inherit another host's numbers.
    if hostname == DEV_BOX_HOSTNAME:
        assert resolved.name == f"{DEV_BOX_HOSTNAME}.yaml"
        assert set(record.missing()) == {
            "gateway_period_s",
            "stop_command_to_standstill_s",
            "localization_jump_m",
        }
    else:
        assert resolved.name == "default.yaml"
        assert record.missing() == timing.ENVELOPE_TERMS_V1
    assert record.active_regime == "one_axis"


def test_the_row_resolves_by_hostname_on_its_own_default_path(monkeypatch) -> None:
    """The test above passes `record=` explicitly; this one proves the DEFAULT
    path — `evaluate_stopping_envelope()` with no argument — reads the same
    two files, and that the choice really is made by the hostname.

    `bridge/timing.py` does `import socket` at module scope and the resolver
    calls `socket.gethostname()`, so `timing.socket` IS the stdlib module:
    patching its attribute is a process-wide patch of `socket.gethostname`,
    undone by `monkeypatch`. There is no narrower hook, and inventing one
    would be a seam that exists only for a test. `PARCEL_ENVELOPE_RECORD` is
    cleared so a developer's shell cannot decide the answer (verifier N9).
    """

    monkeypatch.delenv(timing.ENVELOPE_RECORD_ENV, raising=False)
    for hostname, expected in (
        (DEV_BOX_HOSTNAME, f"{DEV_BOX_HOSTNAME}.yaml"),
        ("fv-az1234-567", "default.yaml"),
        ("fictional-orin-host", "default.yaml"),
    ):
        monkeypatch.setattr(timing.socket, "gethostname", lambda name=hostname: name)
        result = ci_gate.evaluate_stopping_envelope()
        assert Path(result.extra["record"]).name == expected, (
            f"{hostname} resolved to {result.extra['record']}"
        )
        assert result.hard is False
        assert result.status == "pass"
        assert result.extra["state"] == "UNMEASURED"
    # And the env override still wins over the hostname.
    monkeypatch.setattr(timing.socket, "gethostname", lambda: DEV_BOX_HOSTNAME)
    monkeypatch.setenv(
        timing.ENVELOPE_RECORD_ENV, str(REPO / "configs" / "envelope" / "default.yaml")
    )
    override = ci_gate.evaluate_stopping_envelope()
    assert Path(override.extra["record"]).name == "default.yaml"
    assert len(override.extra["missing"]) == len(timing.ENVELOPE_TERMS_V1)


def test_the_stage_is_registered_the_way_gate_0b_registered_its_own() -> None:
    """Row C7. The stage has to appear in BOTH the declared name tuple and
    `run_commit_tier`'s stage tuple, or `tests/test_ci_gate.py` — card XD-1's
    file, which this card does not edit — fails. Asserted by reading the
    source rather than by running a tier (anti-crash rule 3)."""

    assert "stopping-envelope" in ci_gate.COMMIT_TIER_STAGE_NAMES
    names = list(ci_gate.COMMIT_TIER_STAGE_NAMES)
    assert names.index("stopping-envelope") < names.index("default-suite"), (
        "a 2 kB file read that can hard-fail belongs before the 400 s suite"
    )
    source = (REPO / "scripts" / "ci_gate.py").read_text(encoding="utf-8")
    tuple_body = source.split("def run_commit_tier(")[1].split("results: list[GateResult]")[0]
    assert '("stopping-envelope", lambda: evaluate_stopping_envelope(tier=tier)),' in tuple_body
    # ... and it is inside its OWN markers, outside XD-1's and GATE-0b's.
    assert source.count("# ---- CARD HW-6 stopping-envelope") == 3
    assert source.count("# ---- END CARD HW-6 stopping-envelope") == 3
    for region in ("CARD XD-1", "CARD GATE-0b"):
        for chunk in source.split(f"# ---- {region}")[1:]:
            body = chunk.split("# ---- END CARD")[0]
            assert "HW-6" not in body, f"HW-6 text leaked into a {region} region"
