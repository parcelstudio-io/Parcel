from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

import pytest
import yaml

from parcel_robot.bridge.gateway_client import MotionGatewayClientV1, MotionStateV2
from parcel_robot.bridge.invariants import (
    load_gateway_fault_seeds_v1,
    load_gateway_invariants_v1,
)
from parcel_robot.bridge.protocol import (
    GATEWAY_PROTOCOL_VERSION,
    GATEWAY_STATE_PROTOCOL_VERSION_V2,
    MAX_GATEWAY_PACKET_BYTES,
    MAX_LOCAL_TTL_MS,
    GatewayAckDispositionV1,
    GatewayAckV1,
    GatewayAcquireV1,
    GatewayBodyKindV1,
    GatewayCommandV1,
    GatewayHashesV1,
    GatewayHelloV1,
    GatewayPhaseV1,
    GatewayStateQueryV1,
    GatewayStateQueryV2,
    GatewayStateV1,
    GatewayStateV2,
    GatewayStopReportV1,
    GatewayStopV1,
    decode_gateway_message,
    encode_gateway_message,
)
from parcel_robot.bridge.timing import (
    PROPOSED_LATENCY_GATES_V1,
    W0B_MAX_DURATION_S,
    W0B_MAX_LINEAR_MPS,
    W0B_MAX_TTL_S,
    W0B_MAX_YAW_RAD_S,
    W0B_MIN_LINEAR_MPS,
    W0B_MIN_YAW_RAD_S,
    W0B_SETTLED_LINEAR_MPS,
    W0B_SETTLED_YAW_RAD_S,
    latency_derivation_rows,
    render_commissioning_h2_markdown,
    render_latency_derivation_markdown,
)
from parcel_robot.commissioning.limits import (
    DEFAULT_MAX_DURATION_S,
    MAX_LINEAR_MPS,
    MAX_TTL_S,
    MAX_YAW_RAD_S,
    MIN_LINEAR_MPS,
    MIN_YAW_RAD_S,
    SETTLED_LINEAR_MPS,
    SETTLED_YAW_RAD_S,
)
from parcel_robot.control.factory import _timing
from parcel_robot.control.models import ControlTiming

ROOT = Path(__file__).resolve().parents[1]
HASHES = GatewayHashesV1(
    config_sha256="a" * 64,
    capability_sha256="b" * 64,
    calibration_sha256="c" * 64,
    firmware_sha256="d" * 64,
)


def _messages() -> tuple[object, ...]:
    return (
        GatewayHelloV1("epoch-1", 1, GatewayPhaseV1.DISARMED, HASHES),
        GatewayAcquireV1("writer", "epoch-1", 1, 350, HASHES),
        GatewayCommandV1(
            "writer",
            "epoch-1",
            2,
            300,
            "base_link",
            0.2,
            0.0,
            -0.1,
            "task-1",
            "trace-1",
            HASHES,
        ),
        GatewayStopV1("writer", "epoch-1", 3, "test", False),
        GatewayStateQueryV1(4),
        GatewayAckV1(
            "epoch-1",
            2,
            "command",
            2,
            GatewayAckDispositionV1.ACCEPTED,
            "",
        ),
        GatewayStateV1(
            "epoch-1",
            3,
            GatewayPhaseV1.ARMED,
            7,
            10.0,
            True,
            "writer",
            0.2,
            0.0,
            0.0,
            False,
            0,
            "gateway_boot",
        ),
        GatewayStopReportV1("epoch-1", 4, 1, "client_lost", True, True, 8),
    )


def _state_v2() -> GatewayStateV2:
    return GatewayStateV2(
        boot_epoch="epoch-1",
        gateway_sequence=5,
        phase=GatewayPhaseV1.DISARMED,
        state_sequence=9,
        state_age_ms=4.5,
        lease_active=False,
        writer_id="",
        vx_mps=0.0,
        vy_mps=0.0,
        vyaw_rad_s=0.0,
        stationary=True,
        last_stop_sequence=2,
        last_stop_reason="client_stop",
        body_kind=GatewayBodyKindV1.UNITREE_SDK2,
        telemetry_valid=True,
        vendor_position_m=(1.0, 2.0, 0.3),
        vendor_rpy_rad=(0.01, -0.02, 0.3),
        mode=1,
        error_code=0,
        source_time_s=123.25,
        sport_foot_force_raw=(-3, 4, 5, 6),
        feedback_integrity_ok=True,
        feedback_integrity_reason="ok",
        commissioned_soc_ok=True,
        commissioned_soc_reason="soc_above_commissioned_minimum",
        low_state_valid=True,
        low_state_sequence=11,
        low_state_age_ms=2.0,
        low_state_tick=2**32 - 1,
        battery_soc_percent=82,
        power_v=31.7,
        power_a=-2.5,
        max_motor_temperature_raw=48,
        motor_lost_max_raw=0,
        foot_force_est_raw=(-10, 20, 30, 40),
        imu_temperature_raw=43,
        temperature_ntc_raw=(44, 45),
        bms_status=0,
    )


@pytest.mark.parametrize("message", _messages())
def test_gateway_v1_dtos_round_trip_strictly(message: object) -> None:
    encoded = encode_gateway_message(message)  # type: ignore[arg-type]
    assert len(encoded) <= MAX_GATEWAY_PACKET_BYTES
    assert decode_gateway_message(encoded) == message


def test_gateway_state_v2_round_trips_without_changing_v1_kinds() -> None:
    query = GatewayStateQueryV2(sequence=8)
    state = _state_v2()

    assert query.schema_version == state.schema_version == GATEWAY_STATE_PROTOCOL_VERSION_V2
    assert query.kind == "state_query_v2"
    assert state.kind == "state_v2"
    assert GatewayStateQueryV1(8).kind == "state_query"
    assert (
        GatewayStateV1(
            "epoch-1",
            1,
            GatewayPhaseV1.DISARMED,
            1,
            0.0,
            False,
            "",
            0.0,
            0.0,
            0.0,
            True,
            0,
            "",
        ).kind
        == "state"
    )
    assert decode_gateway_message(encode_gateway_message(query)) == query
    assert decode_gateway_message(encode_gateway_message(state)) == state


def test_gateway_state_v2_exact_fields_and_schema_are_strict() -> None:
    wire = _state_v2().as_dict()
    missing = dict(wire)
    missing.pop("power_v")
    with pytest.raises(ValueError, match="fields mismatch"):
        decode_gateway_message(json.dumps(missing).encode())
    extra = dict(wire, calibrated_foot_force_n=[1.0, 1.0, 1.0, 1.0])
    with pytest.raises(ValueError, match="fields mismatch"):
        decode_gateway_message(json.dumps(extra).encode())
    wrong_version = dict(wire, schema_version=GATEWAY_PROTOCOL_VERSION)
    with pytest.raises(ValueError, match="unsupported"):
        decode_gateway_message(json.dumps(wrong_version).encode())
    invalid_body = dict(wire, body_kind="unitree-ish")
    with pytest.raises(ValueError):
        decode_gateway_message(json.dumps(invalid_body).encode())
    with pytest.raises(TypeError, match="body_kind"):
        dataclasses.replace(_state_v2(), body_kind="unitree_sdk2")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("vendor_position_m", (0.0, 0.0)),
        ("vendor_rpy_rad", (0.0, math.inf, 0.0)),
        ("mode", 256),
        ("error_code", -1),
        ("error_code", 2**32),
        ("source_time_s", math.nan),
        ("sport_foot_force_raw", (-32769, 0, 0, 0)),
        ("low_state_age_ms", -0.1),
        ("low_state_tick", 2**32),
        ("battery_soc_percent", 101),
        ("power_v", math.inf),
        ("max_motor_temperature_raw", 256),
        ("motor_lost_max_raw", -1),
        ("foot_force_est_raw", (0, 0, 0, 32768)),
        ("imu_temperature_raw", True),
        ("temperature_ntc_raw", (0, 1, 2)),
        ("bms_status", -1),
    ),
)
def test_gateway_state_v2_rejects_invalid_raw_telemetry(field: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        dataclasses.replace(_state_v2(), **{field: value})


def test_gateway_state_v2_nullable_raw_low_state_values_round_trip() -> None:
    state = dataclasses.replace(
        _state_v2(),
        low_state_valid=False,
        low_state_sequence=0,
        commissioned_soc_ok=None,
        commissioned_soc_reason="commissioned_soc_unavailable",
        low_state_age_ms=None,
        low_state_tick=None,
        battery_soc_percent=None,
        power_v=None,
        power_a=None,
        max_motor_temperature_raw=None,
        motor_lost_max_raw=None,
        foot_force_est_raw=None,
        imu_temperature_raw=None,
        temperature_ntc_raw=None,
        bms_status=None,
    )
    assert decode_gateway_message(encode_gateway_message(state)) == state


def test_gateway_state_v2_uses_nullable_integrity_for_unavailable_sport_telemetry() -> None:
    state = dataclasses.replace(
        _state_v2(),
        telemetry_valid=False,
        vendor_position_m=(0.0, 0.0, 0.0),
        vendor_rpy_rad=(0.0, 0.0, 0.0),
        mode=0,
        error_code=0,
        source_time_s=None,
        sport_foot_force_raw=(0, 0, 0, 0),
        feedback_integrity_ok=None,
        feedback_integrity_reason="feedback_integrity_unavailable",
    )
    assert decode_gateway_message(encode_gateway_message(state)) == state


def test_gateway_state_v2_refuses_contradictory_validity_flags() -> None:
    with pytest.raises(ValueError, match="invalid LowState"):
        dataclasses.replace(_state_v2(), low_state_valid=False)
    with pytest.raises(ValueError, match="valid LowState"):
        dataclasses.replace(_state_v2(), low_state_tick=None)
    with pytest.raises(ValueError, match="neutral placeholders"):
        dataclasses.replace(_state_v2(), telemetry_valid=False)
    with pytest.raises(ValueError, match="requires a feedback integrity verdict"):
        dataclasses.replace(
            _state_v2(),
            feedback_integrity_ok=None,
            feedback_integrity_reason="feedback_integrity_unavailable",
        )
    with pytest.raises(ValueError, match="unavailable feedback integrity"):
        dataclasses.replace(
            _state_v2(),
            feedback_integrity_ok=None,
            feedback_integrity_reason="unknown",
        )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    (
        (
            {"feedback_integrity_ok": True, "feedback_integrity_reason": "bad_mode"},
            "integrity verdict",
        ),
        (
            {"feedback_integrity_ok": False, "feedback_integrity_reason": "ok"},
            "integrity verdict",
        ),
        (
            {
                "feedback_integrity_ok": False,
                "feedback_integrity_reason": "feedback_integrity_unavailable",
            },
            "unavailable reason",
        ),
        (
            {"commissioned_soc_ok": True, "commissioned_soc_reason": "low_battery"},
            "SOC verdict",
        ),
        (
            {"commissioned_soc_ok": False, "commissioned_soc_reason": "ok"},
            "SOC verdict",
        ),
        (
            {"commissioned_soc_ok": None, "commissioned_soc_reason": "unknown"},
            "SOC verdict",
        ),
        (
            {
                "commissioned_soc_ok": False,
                "commissioned_soc_reason": "commissioned_soc_unavailable",
            },
            "SOC verdict",
        ),
    ),
)
def test_gateway_state_v2_refuses_inconsistent_verdicts(
    overrides: dict[str, object],
    reason: str,
) -> None:
    with pytest.raises(ValueError, match=reason):
        dataclasses.replace(_state_v2(), **overrides)


def test_motion_gateway_client_state_v2_is_observation_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MotionGatewayClientV1("/unused/gateway.sock", writer_id="observer")
    requests: list[object] = []

    def exchange(request: object) -> GatewayStateV2:
        requests.append(request)
        return _state_v2()

    monkeypatch.setattr(client, "_exchange", exchange)
    observed = client.state_v2()

    assert isinstance(observed, MotionStateV2)
    assert len(requests) == 1
    assert isinstance(requests[0], GatewayStateQueryV2)
    assert requests[0].schema_version == GATEWAY_STATE_PROTOCOL_VERSION_V2
    assert observed.body_kind is GatewayBodyKindV1.UNITREE_SDK2
    assert observed.vendor_position_m == (1.0, 2.0, 0.3)
    assert observed.foot_force_est_raw == (-10, 20, 30, 40)
    assert observed.battery_soc_percent == 82
    assert observed.feedback_integrity_ok is True
    assert observed.feedback_integrity_reason == "ok"
    assert observed.commissioned_soc_ok is True
    assert observed.commissioned_soc_reason == "soc_above_commissioned_minimum"
    assert observed.motor_lost_max_raw == 0
    assert client.armed is False


def test_duration_ttl_has_no_cross_process_absolute_clock() -> None:
    command = _messages()[2]
    assert isinstance(command, GatewayCommandV1)
    wire = command.as_dict()
    assert wire["local_ttl_ms"] == 300
    assert not {"issued_at", "valid_until", "monotonic_deadline"} & set(wire)


def test_hello_v1_keeps_its_frozen_exact_wire_fields() -> None:
    hello = GatewayHelloV1(
        "epoch-1",
        1,
        GatewayPhaseV1.DISARMED,
        HASHES,
        GATEWAY_PROTOCOL_VERSION,
    )
    assert set(hello.as_dict()) == {
        "schema_version",
        "kind",
        "boot_epoch",
        "gateway_sequence",
        "phase",
        "required_hashes",
    }
    assert decode_gateway_message(encode_gateway_message(hello)) == hello
    extended = dict(hello.as_dict(), body_kind="unitree_sdk2")
    with pytest.raises(ValueError, match="fields mismatch"):
        decode_gateway_message(json.dumps(extended).encode())


@pytest.mark.parametrize(
    ("field", "value", "exception"),
    (
        ("sequence", True, TypeError),
        ("local_ttl_ms", True, TypeError),
        ("local_ttl_ms", 0, ValueError),
        ("local_ttl_ms", 351, ValueError),
    ),
)
def test_acquire_rejects_bool_and_out_of_range_integers(
    field: str,
    value: object,
    exception: type[Exception],
) -> None:
    values = dataclasses.asdict(GatewayAcquireV1("writer", "epoch", 1, 350, HASHES))
    values.pop("kind")
    values[field] = value
    values["hashes"] = HASHES
    with pytest.raises(exception):
        GatewayAcquireV1(**values)


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf, True))
def test_command_rejects_nonfinite_and_bool_velocity(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        GatewayCommandV1(
            "writer",
            "epoch",
            2,
            350,
            "base_link",
            value,
            0.0,
            0.0,
            "task",
            "trace",
            HASHES,  # type: ignore[arg-type]
        )


def test_gateway_command_rejects_wrong_frame_and_bad_hash() -> None:
    with pytest.raises(ValueError, match="base_link"):
        GatewayCommandV1("writer", "epoch", 2, 350, "map", 0.1, 0.0, 0.0, "task", "trace", HASHES)
    with pytest.raises(ValueError, match="task_id"):
        GatewayCommandV1(
            "writer",
            "epoch",
            2,
            350,
            "base_link",
            0.1,
            0.0,
            0.0,
            "t" * 129,
            "trace",
            HASHES,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        dataclasses.replace(HASHES, firmware_sha256="NOT-A-DIGEST")


def test_decoder_rejects_unknown_version_unknown_fields_duplicates_and_oversize() -> None:
    data = GatewayStateQueryV1(1).as_dict()
    data["schema_version"] = GATEWAY_PROTOCOL_VERSION + 1
    with pytest.raises(ValueError, match="unsupported"):
        decode_gateway_message(json.dumps(data).encode())
    data["schema_version"] = GATEWAY_PROTOCOL_VERSION
    data["surprise"] = True
    with pytest.raises(ValueError, match="fields mismatch"):
        decode_gateway_message(json.dumps(data).encode())
    with pytest.raises(ValueError, match="duplicate"):
        decode_gateway_message(
            b'{"schema_version":1,"kind":"state_query","sequence":1,"sequence":2}'
        )
    with pytest.raises(ValueError, match="size"):
        decode_gateway_message(b"x" * (MAX_GATEWAY_PACKET_BYTES + 1))


def test_ack_is_admission_only_and_stop_confirmation_requires_feedback() -> None:
    with pytest.raises(ValueError, match="never acknowledges"):
        GatewayAckV1("epoch", 1, "command", 1, GatewayAckDispositionV1.ACCEPTED, "", "motion_truth")
    with pytest.raises(ValueError, match="feedback state sequence"):
        GatewayStopReportV1("epoch", 1, 1, "stop", True, True, 0)
    with pytest.raises(ValueError, match="failed Stop RPC"):
        GatewayStopReportV1("epoch", 1, 1, "stop", False, True, 2)


def test_rc4_derivation_is_pinned_to_models_factory_and_canonical_config() -> None:
    model = ControlTiming()
    factory = _timing({})
    config = yaml.safe_load((ROOT / "configs/robot.yaml").read_text(encoding="utf-8"))["control"]
    assert model.control_hz == factory.control_hz == float(config["control_hz"]) == 50.0
    assert (
        model.command_timeout_s
        == factory.command_timeout_s
        == float(config["command_timeout_s"])
        == 0.35
    )
    assert MAX_LOCAL_TTL_MS == round(model.command_timeout_s * 1000.0)
    rows = latency_derivation_rows(model)
    assert len(rows) == len(PROPOSED_LATENCY_GATES_V1) == 4
    assert {row["live_ttl_ms"] for row in rows} == {350.0}
    assert {row["ttl_periods"] for row in rows} == {17.5}
    assert rows[0]["gate_periods"] == 5.0
    assert rows[1]["gate_periods"] == rows[2]["gate_periods"] == 7.5
    assert rows[3]["gate_periods"] == 0.1


def test_rc4_document_contains_the_executable_table() -> None:
    document = (ROOT / "docs/GATEWAY_TTL_LATENCY_DERIVATION.md").read_text(encoding="utf-8")
    assert render_latency_derivation_markdown() in document
    assert render_commissioning_h2_markdown() in document


def test_w0b_h2_values_are_pinned_without_choosing_product_stop_thresholds() -> None:
    live = ControlTiming()
    control_config = yaml.safe_load((ROOT / "configs/robot.yaml").read_text(encoding="utf-8"))[
        "control"
    ]
    configured = _timing(control_config)
    assert W0B_MIN_LINEAR_MPS == MIN_LINEAR_MPS
    assert W0B_MAX_LINEAR_MPS == MAX_LINEAR_MPS
    assert W0B_MIN_YAW_RAD_S == MIN_YAW_RAD_S
    assert W0B_MAX_YAW_RAD_S == MAX_YAW_RAD_S
    assert W0B_SETTLED_LINEAR_MPS == SETTLED_LINEAR_MPS
    assert W0B_SETTLED_YAW_RAD_S == SETTLED_YAW_RAD_S
    assert W0B_MAX_TTL_S == MAX_TTL_S
    assert W0B_MAX_DURATION_S == DEFAULT_MAX_DURATION_S
    assert (
        MAX_TTL_S
        == live.command_timeout_s
        == configured.command_timeout_s
        == float(control_config["command_timeout_s"])
        == 0.35
    )
    assert (
        DEFAULT_MAX_DURATION_S
        == live.stop_timeout_s
        == configured.stop_timeout_s
        == float(control_config["stop_timeout_s"])
        == 1.0
    )
    assert (
        SETTLED_LINEAR_MPS
        == 0.01
        < live.settled_linear_speed_mps
        == configured.settled_linear_speed_mps
        == float(control_config["settled_linear_speed_mps"])
        == 0.08
    )
    assert (
        SETTLED_YAW_RAD_S
        == 0.03125
        < live.settled_yaw_speed_rad_s
        == configured.settled_yaw_speed_rad_s
        == float(control_config["settled_yaw_speed_rad_s"])
        == 0.12
    )


def test_gateway_invariant_and_fault_seed_inventories_are_closed_and_owned() -> None:
    seeds = load_gateway_fault_seeds_v1()
    invariants = load_gateway_invariants_v1()
    referenced = {fixture_id for invariant in invariants for fixture_id in invariant.fixture_ids}
    assert len(seeds) == 19
    assert len(invariants) == 12
    assert referenced == {seed.id for seed in seeds}
    assert all(seed.seed == 24000 + int(seed.id.removeprefix("GWF-")) for seed in seeds)
    ttl_invariant = next(invariant for invariant in invariants if invariant.id == "GWI-005")
    ttl_seed = next(seed for seed in seeds if seed.id == "GWF-018")
    assert ttl_seed.id in ttl_invariant.fixture_ids
    assert (
        ttl_seed.fault == "valid_duration_ttl_reaches_receiver_local_expiry_before_refresh_or_query"
    )
    assert ttl_seed.expected == "local_ttl_expired_stop"
    observer_invariant = next(invariant for invariant in invariants if invariant.id == "GWI-012")
    observer_seed = next(seed for seed in seeds if seed.id == "GWF-019")
    assert observer_seed.id in observer_invariant.fixture_ids
    assert observer_seed.fault == "fake_evidence_sink_blocks_raises_or_loses_events"
    assert observer_seed.expected == "identical_stop_and_nonzero_evidence_exit"
