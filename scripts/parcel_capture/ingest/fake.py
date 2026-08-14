"""A synthetic backend behind the real interface — card PS-G.

Every live adapter in this package is unexecutable on the dev box: ``rclpy``,
``pyrealsense2`` and ``unilidar_sdk2`` are all absent and the board forbids
installing them. Without this module the *interface* would be untested too, and
"the first time this stack runs must not be on the dog" would be a slogan.

:class:`FakeIngest` implements :class:`~scripts.parcel_capture.ingest.base.IngestAdapter`
with no dependencies at all, so the whole path — adapter -> frame -> receipt ->
preflight probe -> plausibility verdict, and adapter -> recorder -> MCAP ->
sidecar — runs end to end here, with faults injected on purpose:

* ``silent`` channels yield nothing, which must read as ABSENT, not as an error;
* ``rate_scale`` below 1.0 must read as a rate DEFICIT;
* ``implausible`` channels emit the ~1e24 m/s^2 pathology two independent field
  reports describe on ``utlidar/imu``, which must FAIL the physical-plausibility
  gate while still being recorded — a suspect channel is evidence.

It is deterministic: same construction, same frames, same bytes, same digest.
And it declares ``EvidenceOrigin`` nowhere — the recorder does that — so a
rehearsal bag can never be mistaken for a session bag.
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, ClassVar

from parcel_robot.capture import CHANNELS, Channel, RateKind, Transport
from parcel_robot.capture.channels import SourceClock

from ..preflight import FootForceSample, ImuSample, PhysicalSample, PointCloudSample, PowerSample
from .base import (
    IngestAdapter,
    IngestFrame,
    IngestRefusedError,
    PayloadKind,
    Requirement,
    summary_payload,
)

#: The magnitude two independent reports describe on ``utlidar/imu``. Far above
#: any real accelerometer's full scale (a BMI055 tops out at 156.9 m/s^2), which
#: is why PS-J's sensor-range rule catches it without needing a rest period.
PATHOLOGICAL_ACCEL_MPS2 = -2.17e24

#: Default rate for channels whose matrix row declares none (CONFIGURED or
#: UNKNOWN). A synthetic rate is not an expectation, and nothing downstream
#: treats it as one.
DEFAULT_SYNTHETIC_RATE_HZ = 10.0


class FakeIngest(IngestAdapter):
    """Deterministic synthetic frames for any channel in the matrix."""

    adapter_name: ClassVar[str] = "fake"
    transports: ClassVar[frozenset[Transport]] = frozenset(Transport)
    payload_kind: ClassVar[PayloadKind] = PayloadKind.DERIVED_SUMMARY
    requirements: ClassVar[tuple[Requirement, ...]] = ()
    notes: ClassVar[tuple[str, ...]] = (
        (
            "Synthetic. Nothing produced by this adapter is evidence about any hardware; "
            "it exists so the interface, recorder and sidecar are exercised off the dog."
        ),
    )

    def __init__(
        self,
        *,
        channel_ids: Sequence[str] | None = None,
        silent: Sequence[str] = (),
        implausible: Sequence[str] = (),
        rate_scale: Mapping[str, float] | None = None,
        epoch_ns: int | None = None,
        realtime_epoch_ns: int | None = None,
    ) -> None:
        known = {entry.channel_id for entry in CHANNELS}
        chosen = tuple(channel_ids) if channel_ids is not None else tuple(sorted(known))
        unknown = sorted(set(chosen) - known)
        if unknown:
            raise IngestRefusedError(f"not channels of the matrix: {unknown}")
        for name, group in (("silent", silent), ("implausible", implausible)):
            stray = sorted(set(group) - set(chosen))
            if stray:
                raise IngestRefusedError(f"{name} names channels this adapter does not serve: {stray}")
        for key, value in (rate_scale or {}).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0.0:
                raise IngestRefusedError(f"rate_scale[{key!r}] must be a non-negative number")
        self._channel_ids = chosen
        self.silent = frozenset(silent)
        self.implausible = frozenset(implausible)
        self.rate_scale = dict(rate_scale or {})
        self.epoch_ns = epoch_ns
        self.realtime_epoch_ns = realtime_epoch_ns

    def channels(self) -> tuple[Channel, ...]:
        selected = set(self._channel_ids)
        return tuple(entry for entry in CHANNELS if entry.channel_id in selected)

    def expected_rate_hz(self, entry: Channel) -> float:
        base = (
            entry.nominal_rate_hz
            if entry.rate_kind is RateKind.PERIODIC and entry.nominal_rate_hz
            else DEFAULT_SYNTHETIC_RATE_HZ
        )
        return float(base) * float(self.rate_scale.get(entry.channel_id, 1.0))

    def read_frames(self, entry: Channel, window_s: float) -> Iterator[IngestFrame]:
        if entry.channel_id in self.silent:
            return
        rate = self.expected_rate_hz(entry)
        if rate <= 0.0:
            return
        count = int(window_s * rate)
        period_ns = int(1e9 / rate)
        # Anchored to the caller's real clock unless an epoch was pinned. A
        # probe measures the gap from ITS window start to the first receipt, so
        # a fixed synthetic epoch would read as a multi-decade stall; a pinned
        # epoch is for byte-for-byte determinism and is opted into explicitly.
        base_monotonic = time.monotonic_ns() if self.epoch_ns is None else self.epoch_ns
        base_realtime = (
            time.time_ns() if self.realtime_epoch_ns is None else self.realtime_epoch_ns
        )
        for index in range(count):
            monotonic_ns = base_monotonic + index * period_ns
            realtime_ns = base_realtime + index * period_ns
            samples, summary = self._synthesise(entry, index)
            stamp = (
                realtime_ns
                if entry.source_clock is SourceClock.DEVICE_TIMESPEC
                else None
            )
            summary["stamp_ns"] = stamp
            yield IngestFrame(
                channel_id=entry.channel_id,
                host_monotonic_ns=monotonic_ns,
                host_realtime_ns=realtime_ns,
                payload=summary_payload(summary),
                payload_kind=PayloadKind.DERIVED_SUMMARY,
                source_timestamp_ns=stamp,
                measurements=samples,
                detail=f"synthetic {entry.channel_id} #{index}",
            )

    def _synthesise(
        self, entry: Channel, index: int
    ) -> tuple[tuple[PhysicalSample, ...], dict[str, Any]]:
        """One message's worth of plausible — or deliberately implausible — physics."""

        broken = entry.channel_id in self.implausible
        kind = entry.message_type
        samples: list[PhysicalSample] = []
        summary: dict[str, Any] = {
            "message": kind,
            "synthetic": True,
            "index": index,
            "missing_fields": [],
            "findings": [],
        }
        if "Imu" in kind or entry.channel_id.endswith(".imu") or "imu" in entry.channel_id:
            accel = (
                (PATHOLOGICAL_ACCEL_MPS2, PATHOLOGICAL_ACCEL_MPS2, PATHOLOGICAL_ACCEL_MPS2)
                if broken
                else (0.01, -0.02, 9.81)
            )
            samples.append(ImuSample(accel_mps2=accel, gyro_rps=(0.001, 0.0, -0.001)))
            summary["linear_acceleration_mps2"] = list(accel)
        elif "PointCloud" in kind:
            samples.append(
                PointCloudSample(
                    point_count=1024,
                    field_names=("x", "y", "z", "intensity", "ring", "time"),
                    ranges_m=tuple(0.5 + 0.01 * step for step in range(16)),
                )
            )
            summary["point_count"] = 1024
        elif "LowState" in kind:
            samples.append(ImuSample(accel_mps2=(0.0, 0.0, 9.81), gyro_rps=(0.0, 0.0, 0.0)))
            samples.append(
                PowerSample(power_v=28.6, cell_volts=tuple([1.906] * 15), power_a=1.2)
            )
            samples.append(
                FootForceSample(counts=(12, 14, 11, 13), counts_est=(10, 15, 9, 12))
            )
            summary["tick_ms"] = index
        elif "SportModeState" in kind:
            samples.append(ImuSample(accel_mps2=(0.0, 0.0, 9.81), gyro_rps=(0.0, 0.0, 0.0)))
            summary["range_obstacle"] = [1.5, 1.6, 1.4, 1.7]
        return tuple(samples), summary
