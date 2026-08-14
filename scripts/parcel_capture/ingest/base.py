"""The one interface every live sensor reader implements — card PS-G.

Why this package exists
-----------------------
``record.py`` shipped a recorder with nothing to record: ``resolve_live_source``
refused for **every** transport ("There is no live backend on this card") and
``preflight.py`` defaulted to ``unavailable_reader_factory``. No PS-1 card owned
the DDS subscriber, the RealSense loop or the L2 reader, so the morning of the
physical session would have begun with somebody writing subscriber code against
a live, battery-limited robot. That is the single most likely way the day yields
no usable data, and it is a *missing-component* failure, not a driver failure.

What an adapter is, and is not
------------------------------
An adapter turns one transport into :class:`IngestFrame` records. It is:

* **subscribe-only, as far as a pin can make it.** No adapter names a publisher
  surface — ``tests/test_no_arm_pin.py`` is the tranche-wide pin that asserts it
  over **every** file under ``src/parcel_robot/capture/`` and
  ``scripts/parcel_capture/``, recursively, statically *and* by importing each
  module in a subprocess against a fake vendor SDK whose publisher-creating
  entry points raise. Every vendor object an adapter holds is wrapped in a
  :class:`ReadOnlyHandle`, whose ``__getattribute__`` refuses any attribute
  outside a fixed allowlist — so ``getattr(handle, "create_" + "publisher")``
  raises rather than resolving. Read :class:`ReadOnlyHandle`'s own docstring for
  what that does and does **not** close: an in-process caller with closure or
  ``gc`` introspection is not stopped by any of this, and PS-O's status doc
  names those routes rather than pretending they are shut.
* **refusing rather than failing.** None of ``rclpy``, ``pyrealsense2`` or
  ``unilidar_sdk2`` exists on the dev box. Every adapter answers
  :meth:`IngestAdapter.dependency_report` without importing anything and raises
  :class:`IngestUnavailableError` — module named, remedy attached — instead of a
  traceback.
* **not the primary recorder.** ``ros2 bag record -s mcap``
  (:mod:`scripts.parcel_capture.rosbag2`) is the recorder of record for the
  session, because every downstream tool — GLIM, FAST-LIO2, Point-LIO-ROS2,
  KISS-ICP, Multi-LiCa, ros2_calib, direct_visual_lidar_calibration — reads
  ``rosbag2`` and none of them can open a ``parcel-capture`` MCAP. These
  adapters serve preflight probing (PS-D), the physical-plausibility gate
  (PS-J), and the low-rate Parcel attestation/clock stream, which is the
  **secondary** copy and never the sole copy of anything.

Payloads: derived summaries, not wire bytes, and the frame says which
---------------------------------------------------------------------
Because rosbag2 holds the wire bytes, an adapter here does **not** duplicate a
2.6 MiB colour frame into the Parcel bag. It records a canonical-JSON summary of
what it decoded, and :class:`PayloadKind` on every frame says so out loud. An
adapter that declares :attr:`PayloadKind.DERIVED_SUMMARY` and emits a frame
claiming :attr:`PayloadKind.WIRE_BYTES` is refused: "the bag holds the real
bytes" is exactly the belief that must never be acquired by accident.

The fail-closed rule that catches a fabricated clock
----------------------------------------------------
:class:`IngestFrame` refuses a non-null ``source_timestamp_ns`` on any channel
whose declared :class:`~parcel_robot.capture.SourceClock` is not
``DEVICE_TIMESPEC``. ``LowState`` — the 500 Hz body IMU, the most valuable
stream on the dog — carries no timestamp at all, only a wrapping ``uint32``
``tick``; a decoder that quietly turned that counter into nanoseconds would
produce a dataset whose cross-device alignment is wrong and *looks* right. The
constructor makes that unrepresentable.
"""

from __future__ import annotations

import importlib.util
import json
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar
from weakref import WeakKeyDictionary

from parcel_robot.capture import (
    Channel,
    SourceDevice,
    Transport,
    channel,
)
from parcel_robot.capture.channels import SourceClock

from ..preflight import (
    AbsenceReason,
    PhysicalSample,
    SampleReceipt,
    TransportUnavailableError,
)

#: Attribute names no :class:`ReadOnlyHandle` will ever resolve, whatever its
#: allowlist says. Belt and braces: the allowlist is the mechanism, this is the
#: assertion that the mechanism was not mis-configured by a later editor.
NEVER_ALLOWED: frozenset[str] = frozenset(
    {
        "create_publisher",
        "advertise",
        "ChannelFactoryInitialize",
        "SportClient",
        "MotionSwitcherClient",
        "ObstaclesAvoidClient",
        "RobotStateClient",
        "VuiClient",
        "AudioClient",
        "send_goal",
        "send_request",
        "call_async",
        "hardware_reset",
        "set_option",
        "startLidar",
        "stopLidar",
        "setLidarWorkMode",
    }
)


class IngestError(RuntimeError):
    """Base for every refusal raised by this package."""


class IngestRefusedError(IngestError):
    """A caller asked an adapter to do something it must not do."""


class IngestContractError(IngestError):
    """An adapter produced something the interface forbids. Our own defect."""


class IngestUnavailableError(IngestError):
    """This transport cannot be read here, with the reason and the remedy.

    Mirrors :class:`~scripts.parcel_capture.preflight.TransportUnavailableError`
    deliberately: :func:`channel_reader_factory` translates one into the other
    so preflight classifies an unreachable transport as ABSENT for a named
    reason rather than as an unexplained probe crash.
    """

    def __init__(self, reason: AbsenceReason, detail: str, remedy: str) -> None:
        super().__init__(f"{reason.value}: {detail}")
        self.reason = reason
        self.detail = detail
        self.remedy = remedy

    def as_transport_error(self) -> TransportUnavailableError:
        return TransportUnavailableError(self.reason, self.detail, self.remedy)


class PayloadKind(str, Enum):
    """What the bytes on a frame actually are. Never inferred, always declared."""

    #: The device's own serialised message, unmodified.
    WIRE_BYTES = "wire_bytes"
    #: A canonical-JSON summary this adapter derived. The wire bytes live in the
    #: rosbag2 primary recording, not here.
    DERIVED_SUMMARY = "derived_summary"


@dataclass(frozen=True, slots=True)
class Requirement:
    """One thing a live reader needs, and what to do when it is absent.

    ``module`` is checked with :func:`importlib.util.find_spec` and **never**
    imported by this call: a probe that imports a vendor SDK to find out whether
    it exists has already done the thing the board forbids.
    """

    module: str
    remedy: str
    #: True when this module alone is enough. A requirement set with several
    #: optional members is satisfied by any one of them.
    optional: bool = False

    def present(self) -> bool:
        try:
            return importlib.util.find_spec(self.module) is not None
        except Exception:  # noqa: BLE001 - a probe that raises is ABSENT
            return False


@dataclass(frozen=True, slots=True)
class DependencyReport:
    """Whether an adapter could run here, computed without importing anything."""

    adapter: str
    satisfied: bool
    present: tuple[str, ...]
    missing: tuple[str, ...]
    remedy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "satisfied": self.satisfied,
            "present": list(self.present),
            "missing": list(self.missing),
            "remedy": self.remedy,
        }


@dataclass(frozen=True, slots=True)
class IngestFrame:
    """One message an adapter actually received.

    The constructor is where this card's fail-closed rules live, because a rule
    enforced at construction cannot be forgotten by the next decoder:

    * the channel must be a real row of the PS-A/PS-H matrix;
    * ``payload`` must be non-empty — a zero-byte message is not a message;
    * ``source_timestamp_ns`` must be ``None`` unless the channel's declared
      payload clock is a real device time (see the module docstring).
    """

    channel_id: str
    host_monotonic_ns: int
    host_realtime_ns: int
    payload: bytes
    payload_kind: PayloadKind
    source_timestamp_ns: int | None = None
    measurements: tuple[PhysicalSample, ...] = ()
    detail: str = ""

    def __post_init__(self) -> None:
        entry = channel(self.channel_id)  # UnknownChannelError if it is not a row
        # Checked by explicit name rather than through getattr: the read-only
        # pin in tests/test_capture_ingest.py enumerates every dynamic attribute
        # reach in this package, and a convenience loop here would spend one of
        # the two vetted slots on a field validation.
        for name, value in (
            ("host_monotonic_ns", self.host_monotonic_ns),
            ("host_realtime_ns", self.host_realtime_ns),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise IngestContractError(
                    f"{self.channel_id}: {name} must be an int, got {value!r}"
                )
        if not isinstance(self.payload_kind, PayloadKind):
            raise IngestContractError(
                f"{self.channel_id}: payload_kind must be a PayloadKind member, got "
                f"{self.payload_kind!r} — whether a bag holds wire bytes is never inferred"
            )
        if not isinstance(self.payload, (bytes, bytearray)):
            raise IngestContractError(
                f"{self.channel_id}: payload must be raw bytes, got "
                f"{type(self.payload).__name__}"
            )
        object.__setattr__(self, "payload", bytes(self.payload))
        if not self.payload:
            raise IngestContractError(
                f"{self.channel_id}: payload is empty — a zero-byte message is not a "
                f"message, it is a reader reporting its own failure"
            )
        if not isinstance(self.measurements, tuple) or any(
            not isinstance(item, PhysicalSample) for item in self.measurements
        ):
            raise IngestContractError(
                f"{self.channel_id}: measurements must be a tuple of PhysicalSample, got "
                f"{self.measurements!r}"
            )
        stamp = self.source_timestamp_ns
        if stamp is not None:
            if isinstance(stamp, bool) or not isinstance(stamp, int):
                raise IngestContractError(
                    f"{self.channel_id}: source_timestamp_ns must be an int or None, got "
                    f"{stamp!r}"
                )
            if entry.source_clock is not SourceClock.DEVICE_TIMESPEC:
                raise IngestContractError(
                    f"{self.channel_id}: declares source_clock="
                    f"{entry.source_clock.value} and therefore carries no device time, but "
                    f"this frame supplies source_timestamp_ns={stamp}. A wrapping counter "
                    f"promoted to a timestamp is a dataset that is wrong and looks right"
                )

    @property
    def channel(self) -> Channel:
        return channel(self.channel_id)

    def to_receipt(self) -> SampleReceipt:
        """The PS-D view of this frame: arrival, size, and what was measured."""

        return SampleReceipt(
            channel_id=self.channel_id,
            host_monotonic_ns=self.host_monotonic_ns,
            payload_bytes=len(self.payload),
            source_timestamp_ns=self.source_timestamp_ns,
            detail=self.detail,
            measurements=self.measurements,
        )


#: Sentinel distinguishing "the message has no such field" from "the field is
#: there and its value is None". Unknown must never read as a value.
class _Absent:
    __slots__ = ()

    def __repr__(self) -> str:
        return "ABSENT"


ABSENT: Any = _Absent()


def read_field(message: Any, name: str, default: Any = ABSENT) -> Any:
    """Tolerant field read — the ONE dynamic attribute reach decoders may use.

    Every row of the channel matrix is transcribed from vendor documentation
    about *other* Go2 EDUs, so a decoder that assumes a field exists turns a
    documentation error into a crashed probe on session morning. Reading through
    here means a missing field is recorded as missing and the rest of the
    message still decodes.

    Concentrating the reach in one function is also what makes the read-only pin
    checkable: ``tests/test_capture_ingest.py`` enumerates every ``getattr``
    call site in this package, and a new one anywhere else fails the pin.
    """

    return getattr(message, name, default)


def present(value: Any) -> bool:
    """True when :func:`read_field` actually found something."""

    return value is not ABSENT and value is not None


def summary_payload(record: Mapping[str, Any]) -> bytes:
    """Canonical JSON bytes for a :attr:`PayloadKind.DERIVED_SUMMARY` frame.

    Sorted keys and no NaN: the Parcel secondary bag is digest-bound, so two
    runs over the same decode must produce the same bytes, and a non-finite
    number must refuse here rather than become ``NaN`` in a JSON file no
    strict parser will read back.
    """

    text = json.dumps(
        dict(record), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return text.encode("utf-8")


@dataclass(frozen=True, slots=True)
class _HandleState:
    """The three things a handle needs, kept where the handle cannot hand them out.

    Never stored on the handle. See :func:`_build_read_only_handle`.
    """

    target: Any
    allowed: frozenset[str]
    label: str


def _build_read_only_handle() -> Any:
    """Build :class:`ReadOnlyHandle` with its state in a closure, not on the instance.

    Why a factory. The first version of this class kept the wrapped object in
    ``__slots__ = (..., "_target")``. A ``__slots__`` entry is an ordinary
    class-level descriptor, so ``handle._target`` resolved through
    ``object.__getattribute__`` and never reached ``__getattr__`` at all: an
    auditor executed ``handle._target.create_publisher(...)`` and got a
    publisher on ``/cmd_vel``. The allowlist was never consulted. Moving the
    state into a closure-scoped :class:`weakref.WeakKeyDictionary` removes the
    descriptor, so there is no attribute on the instance that yields the target
    under any spelling — computed, mangled, or literal.

    ``__getattribute__`` rather than ``__getattr__``: ``__getattr__`` is only
    consulted after normal lookup *fails*, which is why the slot beat it.
    Overriding ``__getattribute__`` puts the allowlist on the only path there
    is, and lets :data:`NEVER_ALLOWED` be checked at **access** time — the
    construction-time check alone was undone by a single
    ``object.__setattr__(handle, "_allowed", ...)``.
    """

    state: WeakKeyDictionary[Any, _HandleState] = WeakKeyDictionary()

    class ReadOnlyHandle:
        """A vendor object behind a fixed attribute allowlist.

        What this **does** guarantee: no attribute access through this object —
        ``handle.x``, ``getattr(handle, computed)``, ``handle.__getattribute__``,
        ``vars(handle)``, ``handle.__dict__``, a mangled name, an
        ``operator.attrgetter`` — yields the wrapped object or any name outside
        the allowlist, and no name in :data:`NEVER_ALLOWED` resolves even if the
        allowlist is later mutated, because the allowlist is consulted on every
        access rather than only at construction.

        Dunders are refused too, so ``handle.__class__``, ``handle.__dict__``
        and ``handle.__init__`` all raise. ``type(handle)`` and ``isinstance``
        still work, because those go through the type rather than the instance;
        a debugger poking at the object will find it opaque, which is the
        intended trade.

        What this does **not** guarantee, stated plainly because the next reader
        of this comment will be standing next to a robot: it is not a sandbox.
        An in-process caller that reaches for
        ``type(handle).__getattribute__.__closure__`` (or ``__init__``'s, or
        ``gc.get_referents`` on the class) recovers the ``WeakKeyDictionary``
        and through it the wrapped object. The same is true of
        :func:`sealed_call`'s closure. No pure-Python object can close those
        routes, and ``tests/test_no_arm_pin.py`` asserts each residual out loud
        so this paragraph cannot quietly become false. What the class buys is
        that reaching a command surface now takes deliberate introspection —
        which the static half of the pin *can* see and refuses — instead of one
        ordinary attribute access, which it could not.
        """

        # No data slots at all: the only per-instance storage is the weak
        # reference the WeakKeyDictionary needs to key on.
        __slots__ = ("__weakref__",)

        def __init__(self, target: Any, *, allowed: Iterable[str], label: str) -> None:
            names = frozenset(allowed)
            if not isinstance(label, str) or not label.strip():
                raise IngestContractError(
                    "a read-only handle must carry a non-empty label; an unlabelled "
                    "refusal cannot be traced back to the object that refused"
                )
            forbidden = sorted(names & NEVER_ALLOWED)
            if forbidden:
                raise IngestRefusedError(
                    f"{label}: allowlist names {forbidden}, which this package may never "
                    f"reach; a read-only handle cannot be configured into a writable one"
                )
            state[self] = _HandleState(target=target, allowed=names, label=label)

        def __getattribute__(self, name: str) -> Any:
            # Deliberately reads NOTHING off ``self``: every value comes from the
            # closure, so this method cannot recurse and cannot be redirected by
            # anything written onto the instance.
            record = state.get(self)
            if record is None:
                raise IngestRefusedError(
                    "read-only handle has no state — it was not built by "
                    "ReadOnlyHandle.__init__, so nothing about it can be trusted"
                )
            if name in NEVER_ALLOWED:
                raise IngestRefusedError(
                    f"{record.label}: attribute {name!r} is on NEVER_ALLOWED and is "
                    f"refused at access time, whatever this handle's allowlist says"
                )
            if name == "allowed":
                return record.allowed
            if name == "label":
                return record.label
            if name not in record.allowed:
                raise IngestRefusedError(
                    f"{record.label}: attribute {name!r} is not on the read-only allowlist "
                    f"{sorted(record.allowed)} — nothing reached through this object can be "
                    f"a command surface. That is a claim about this object only: see the "
                    f"class docstring for the introspection routes it does not close"
                )
            return getattr(record.target, name)

        def __setattr__(self, name: str, value: Any) -> None:
            record = state.get(self)
            label = "read-only handle" if record is None else record.label
            raise IngestRefusedError(
                f"{label}: this handle is read-only; setting {name!r} is refused"
            )

        def __delattr__(self, name: str) -> None:
            record = state.get(self)
            label = "read-only handle" if record is None else record.label
            raise IngestRefusedError(
                f"{label}: this handle is read-only; deleting {name!r} is refused"
            )

        def __repr__(self) -> str:
            record = state.get(self)
            if record is None:  # pragma: no cover - unconstructed handles cannot exist
                return "<ReadOnlyHandle (no state)>"
            return f"<ReadOnlyHandle {record.label} allowed={sorted(record.allowed)}>"

    return ReadOnlyHandle


ReadOnlyHandle: Any = _build_read_only_handle()


def sealed_call(
    target: Any,
    name: str,
    *,
    label: str,
    bind_args: Sequence[Any] = (),
    bind_kwargs: Mapping[str, Any] | None = None,
) -> Any:
    """Bind ``target.name(*bind_args, **bind_kwargs, ...)`` and return only the call.

    Some vendor entry points take the device object as an *argument* instead of
    offering a method on it — ``rclpy.spin_once(node, timeout_sec=...)`` is the
    one that matters here. The DDS session therefore used to keep the raw node
    and the entire ``rclpy`` module on ``__node`` and ``_rclpy``; an auditor read
    both **from another module, in one line** (``session._SubscribeOnlySession__node``
    is what name mangling actually produces, and ``_rclpy`` is not private at
    all) and created a publisher on ``/cmd_vel`` with the result.

    This binds the call at construction and returns a plain function. The module
    and the device stay in that function's closure; the holder gets a callable
    that can do exactly one thing. Same honest caveat as
    :class:`ReadOnlyHandle`: ``call.__closure__`` still recovers them, and
    ``tests/test_no_arm_pin.py`` pins that residual rather than hiding it.
    """

    if name in NEVER_ALLOWED:
        raise IngestRefusedError(
            f"{label}: sealed_call refuses {name!r}, which is on NEVER_ALLOWED"
        )
    bound = getattr(target, name)
    args = tuple(bind_args)
    kwargs = dict(bind_kwargs or {})

    def call(*extra: Any, **extra_kwargs: Any) -> Any:
        return bound(*args, *extra, **kwargs, **extra_kwargs)

    call.__name__ = f"sealed_{name}"
    call.__qualname__ = f"sealed_call.<locals>.{name}"
    call.__doc__ = f"{label}: sealed {name}. Neither the target nor the bindings are exposed."
    return call


@dataclass(frozen=True, slots=True)
class AdapterCapability:
    """What an adapter claims it can do, before it is asked to do it."""

    adapter: str
    transports: tuple[str, ...]
    devices: tuple[str, ...]
    channel_ids: tuple[str, ...]
    payload_kind: str
    dependency: DependencyReport
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "transports": list(self.transports),
            "devices": list(self.devices),
            "channel_ids": list(self.channel_ids),
            "payload_kind": self.payload_kind,
            "dependency": self.dependency.to_dict(),
            "notes": list(self.notes),
        }


class IngestAdapter(ABC):
    """One transport, read-only, with its dependency stated up front.

    Subclasses declare :attr:`adapter_name`, :attr:`transports`,
    :attr:`requirements` and :attr:`payload_kind`, and implement
    :meth:`read_frames`. Everything else — dependency reporting, refusal
    translation, the preflight bridge, the recorder bridge — is here, so a new
    transport cannot accidentally ship a different refusal contract.
    """

    adapter_name: ClassVar[str] = ""
    transports: ClassVar[frozenset[Transport]] = frozenset()
    requirements: ClassVar[tuple[Requirement, ...]] = ()
    payload_kind: ClassVar[PayloadKind] = PayloadKind.DERIVED_SUMMARY
    #: Free-text caveats printed by the CLI and carried into the sidecar.
    notes: ClassVar[tuple[str, ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # A subclass that implements the read is a concrete adapter and must
        # name itself: an unnamed adapter cannot be reported, refused or audited.
        if "read_frames" in cls.__dict__ and not cls.adapter_name:
            raise IngestContractError(f"{cls.__name__} must declare an adapter_name")

    # ------------------------------------------------------------ dependency

    @classmethod
    def dependency_report(cls) -> DependencyReport:
        """Can this adapter run here? Computed by spec lookup, never by import."""

        found = {req.module: req.present() for req in cls.requirements}
        present = tuple(name for name, ok in found.items() if ok)
        missing = tuple(name for name, ok in found.items() if not ok)
        required = [req for req in cls.requirements if not req.optional]
        optional = [req for req in cls.requirements if req.optional]
        # Every mandatory module, and — when an optional group exists at all —
        # at least one of it. "Any one will do" must not decay into "none will".
        satisfied = all(found[req.module] for req in required) and (
            not optional or any(found[req.module] for req in optional)
        )
        remedy = "; ".join(
            f"{req.module}: {req.remedy}" for req in cls.requirements if req.module in missing
        )
        return DependencyReport(
            adapter=cls.adapter_name,
            satisfied=satisfied,
            present=present,
            missing=missing,
            remedy=remedy,
        )

    @classmethod
    def require_dependencies(cls) -> DependencyReport:
        """The dependency report, or a refusal naming module and remedy."""

        report = cls.dependency_report()
        if not report.satisfied:
            raise IngestUnavailableError(
                AbsenceReason.DEPENDENCY_MISSING,
                f"{cls.adapter_name}: {', '.join(report.missing) or 'no backend'} is not "
                f"importable in this interpreter",
                report.remedy
                or "install the transport's runtime in the Orin's ROS 2 Humble "
                "environment — never into .parcel/",
            )
        return report

    # -------------------------------------------------------------- channels

    def channels(self) -> tuple[Channel, ...]:
        """Matrix rows this adapter serves. Overridden where a subset applies."""

        from parcel_robot.capture import CHANNELS

        return tuple(entry for entry in CHANNELS if entry.transport in self.transports)

    def serves(self, entry: Channel) -> bool:
        return entry.channel_id in {item.channel_id for item in self.channels()}

    def capability(self) -> AdapterCapability:
        entries = self.channels()
        return AdapterCapability(
            adapter=self.adapter_name,
            transports=tuple(sorted(item.value for item in self.transports)),
            devices=tuple(sorted({entry.device.value for entry in entries})),
            channel_ids=tuple(entry.channel_id for entry in entries),
            payload_kind=self.payload_kind.value,
            dependency=self.dependency_report(),
            notes=self.notes,
        )

    # ------------------------------------------------------------- the reads

    @abstractmethod
    def read_frames(self, entry: Channel, window_s: float) -> Iterator[IngestFrame]:
        """Yield one :class:`IngestFrame` per message received, then stop.

        Must stop by itself at the deadline. Must raise
        :class:`IngestUnavailableError` — never a bare vendor exception — when
        the transport cannot be reached.
        """

    def read(self, entry: Channel, window_s: float) -> Iterator[IngestFrame]:
        """:meth:`read_frames` with the interface's invariants enforced."""

        if not isinstance(entry, Channel):
            raise IngestRefusedError(f"expected a Channel, got {entry!r}")
        if not self.serves(entry):
            raise IngestRefusedError(
                f"{self.adapter_name} does not serve {entry.channel_id} "
                f"(transport {entry.transport.value})"
            )
        if isinstance(window_s, bool) or not isinstance(window_s, (int, float)):
            raise IngestRefusedError(f"window_s must be a number, got {window_s!r}")
        if not float(window_s) > 0.0:
            raise IngestRefusedError(f"window_s must be positive, got {window_s!r}")
        for frame in self.read_frames(entry, float(window_s)):
            if not isinstance(frame, IngestFrame):
                raise IngestContractError(
                    f"{self.adapter_name} yielded {frame!r}, which is not an IngestFrame"
                )
            if frame.channel_id != entry.channel_id:
                raise IngestContractError(
                    f"{self.adapter_name} was reading {entry.channel_id} and yielded a "
                    f"frame for {frame.channel_id}"
                )
            if frame.payload_kind is not self.payload_kind:
                raise IngestContractError(
                    f"{self.adapter_name} declares payload_kind "
                    f"{self.payload_kind.value} but yielded a "
                    f"{frame.payload_kind.value} frame on {frame.channel_id}"
                )
            yield frame


def channel_reader_factory(adapter: IngestAdapter) -> Any:
    """Bridge an adapter into PS-D's ``ChannelReaderFactory`` seam.

    An :class:`IngestUnavailableError` becomes preflight's
    :class:`~scripts.parcel_capture.preflight.TransportUnavailableError`, so a
    missing dependency reads as ABSENT with a named reason and a remedy — the
    same outcome ``unavailable_reader_factory`` produces today, but now reached
    by a reader that would have worked had the dependency been there.
    """

    def factory(entry: Channel) -> Any:
        def reader(target: Channel, window_s: float) -> Iterable[SampleReceipt]:
            try:
                for frame in adapter.read(target, window_s):
                    yield frame.to_receipt()
            except IngestUnavailableError as error:
                raise error.as_transport_error() from error

        if not adapter.serves(entry):
            def refusing(target: Channel, window_s: float) -> Iterable[SampleReceipt]:
                raise TransportUnavailableError(
                    AbsenceReason.NOT_ATTEMPTED,
                    f"{target.channel_id}: {adapter.adapter_name} does not serve transport "
                    f"{target.transport.value}",
                    "register an adapter for this transport before claiming the channel "
                    "exists; preflight refuses to guess at presence.",
                )

            return refusing
        return reader

    return factory


@dataclass
class RecorderFeed:
    """Drive a PS-B :class:`CaptureRecorder` from an adapter, one channel at a time.

    This is the **secondary** copy. It exists so the attestation/clock stream
    has a Parcel-native, digest-bound home; it is never where a sensor's bytes
    are kept.

    :attr:`recorded` counts what this feed handed to the recorder. It carries no
    drop tally of its own on purpose: the recorder mints the per-channel sequence
    and owns ``drops``, and a second count kept here would be a second thing that
    can disagree with the bag without either being authoritative.
    """

    adapter: IngestAdapter
    recorded: dict[str, int] = field(default_factory=dict)

    def pump(self, recorder: Any, entry: Channel, window_s: float) -> int:
        """Record every frame from one channel. Returns messages recorded."""

        count = 0
        for frame in self.adapter.read(entry, window_s):
            recorder.record(
                frame.channel_id,
                frame.payload,
                host_monotonic_ns=frame.host_monotonic_ns,
                host_realtime_ns=frame.host_realtime_ns,
                source_timestamp_ns=frame.source_timestamp_ns,
            )
            count += 1
        self.recorded[entry.channel_id] = self.recorded.get(entry.channel_id, 0) + count
        return count


def now_ns() -> tuple[int, int]:
    """``(host_monotonic_ns, host_realtime_ns)`` read as close together as possible.

    Both, always. ``time.monotonic_ns`` has a per-machine arbitrary epoch and is
    the only clock safe for intervals; ``time.time_ns`` is the only one that can
    be compared to a wall-clock note in the run-sheet. Recording one without the
    other is what makes a session unalignable six months later.
    """

    return (time.monotonic_ns(), time.time_ns())


def deadline_ns(window_s: float) -> int:
    return time.monotonic_ns() + int(float(window_s) * 1e9)


def devices_of(entries: Sequence[Channel]) -> tuple[SourceDevice, ...]:
    seen: list[SourceDevice] = []
    for entry in entries:
        if entry.device not in seen:
            seen.append(entry.device)
    return tuple(seen)
