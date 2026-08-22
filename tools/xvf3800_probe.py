#!/usr/bin/env python
"""Card AIR-1 — is the reSpeaker XVF3800 wired up the way the voice stack thinks?

    tools/xvf3800_probe.py                     # the four read-only sections
    tools/xvf3800_probe.py --json probe.json   # ... and write the evidence
    tools/xvf3800_probe.py --doa 100           # poll DOA_VALUE 100 times
    tools/xvf3800_probe.py --rms 5             # 5 s of ch0/ch1 level while you talk

WHAT THIS IS FOR
----------------
Three facts about this array decide whether full duplex through air can work at
all, and every one of them is invisible from inside Python until somebody looks:

1. **It is 16 kHz-only, both directions.** ``/proc/asound/card2/stream0`` lists
   exactly one rate. The hosted realtime lane produces 24 kHz and Piper produces
   22.05 kHz, so *something* must resample; when that something is missing,
   PortAudio refuses with ``PaErrorCode -9997`` (Invalid sample rate) and the
   failure looks like a broken microphone rather than a rate mismatch.
   :func:`rate_matrix` measures it and :func:`check_producer_rates` says which
   producer needs a resampler.
2. **The two capture channels are different beams.** The 2-channel firmware is
   ch0 = Conference, ch1 = ASR (``scrum/20260820/research/res_speech_identity.md``).
   An ear that asks for one channel gets PipeWire's *average* of the two, which
   is not the ASR beam and not the conference beam — it is a third signal nobody
   tuned. :func:`downmix_hazard` puts a number on the damage.
3. **DoA needs a udev rule.** The vendor control interface is a separate USB
   interface from the two UAC ones, so reading it cannot disturb capture — but
   the device node is ``root:root 0664`` until the rule lands, and every read
   fails with ``Errno 13``. :func:`usb_section` reports the node's mode so the
   answer is "the rule is not in" and not "the array is broken".

WHAT IT DOES NOT DO
-------------------
It never changes the PipeWire profile, never moves a default device, never
writes to the array, and never issues a USB control *write*. ``--doa`` and
``--rms`` are opt-in precisely because they touch the device: the default run
reads sysfs, ``/proc/asound``, ``wpctl status`` and PortAudio's format query,
all of which leave the array in the state they found it.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import struct
import subprocess
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:  # pragma: no cover - script entry
    sys.path.insert(0, str(REPO_ROOT / "src"))

# ============================================================== the rate pin
#: USB identity of the reSpeaker XVF3800 (``lsusb``: 2886:001a). Duplicated from
#: ``realtime.voice_identity`` on purpose: this tool must be runnable on a host
#: where the package does not import, which is exactly the host you are
#: debugging when the array is the suspect.
XVF3800_VENDOR_ID = 0x2886
XVF3800_PRODUCT_ID = 0x001A

#: The ONE rate this array accepts, in either direction. Not a preference and
#: not a default — ``/proc/asound/card<n>/stream0`` lists ``Rates: 16000`` for
#: both the playback and the capture altsetting, and PortAudio refuses
#: everything else outright.
ARRAY_RATE_HZ = 16_000
ARRAY_SUPPORTED_RATES_HZ: tuple[int, ...] = (16_000,)

#: ``paInvalidSampleRate``. The number you will actually see in the traceback.
PA_INVALID_SAMPLE_RATE = -9997

#: Rates the rate matrix sweeps. Every entry that is not 16 kHz is expected to
#: be refused; the sweep exists so the refusal is *evidence* and not folklore.
PROBE_RATES_HZ: tuple[int, ...] = (8_000, 16_000, 22_050, 24_000, 44_100, 48_000)

#: Who produces audio in this stack, and at what rate. Cross-checked against the
#: real constants by ``tests/test_air1_rate_pin.py`` so that moving one of them
#: without teaching the array path to resample reddens a test instead of
#: producing a silent robot.
PRODUCER_RATES_HZ: dict[str, int] = {
    "hosted_realtime": 24_000,  # realtime.protocol.PCM16_SAMPLE_RATE_HZ
    "piper_tts": 22_050,  # the local synthesiser
    "legacy_loop": 16_000,  # voice_audio.SAMPLE_RATE_HZ
}

#: The two capture beams of the 2-channel firmware, in channel order.
CAPTURE_BEAMS: tuple[str, ...] = ("conference", "asr")
#: Which one the ear must take. MARK-1 pins this on the browser side; AIR-1
#: measures what taking the other one (or the average) costs.
ASR_CHANNEL_INDEX = 1


class ProbeError(RuntimeError):
    """The probe refused. Always with the measurement that caused it."""


def resample_plan(source_rate_hz: int) -> dict[str, Any]:
    """What must happen to play ``source_rate_hz`` audio through this array.

    Returns the plan rather than raising, because "resample" is a perfectly good
    answer and the caller is entitled to make it. What is *not* a good answer is
    handing 24 kHz PCM to a 16 kHz endpoint and hoping, which is why
    :func:`assert_array_rate` exists beside this.
    """

    rate = int(source_rate_hz)
    direct = rate == ARRAY_RATE_HZ
    return {
        "source_rate_hz": rate,
        "array_rate_hz": ARRAY_RATE_HZ,
        "direct": direct,
        "action": "direct" if direct else "resample",
        "ratio": ARRAY_RATE_HZ / rate if rate else math.inf,
    }


def assert_array_rate(rate_hz: int, *, where: str) -> None:
    """Refuse a rate this array cannot open. ``where`` names the caller."""

    if int(rate_hz) not in ARRAY_SUPPORTED_RATES_HZ:
        raise ProbeError(
            f"{where}: the XVF3800 opens only {ARRAY_RATE_HZ} Hz, not {int(rate_hz)} Hz "
            f"(PortAudio answers PaErrorCode {PA_INVALID_SAMPLE_RATE}); resample first"
        )


def check_producer_rates(
    producers: Mapping[str, int] | None = None,
) -> dict[str, dict[str, Any]]:
    """Per producer: does it reach this array directly, or does it need a resampler?"""

    source = PRODUCER_RATES_HZ if producers is None else producers
    return {name: resample_plan(rate) for name, rate in sorted(source.items())}


# ================================================================= USB / udev
@dataclass(frozen=True)
class UsbNode:
    """Where the array sits on the bus, and whether its control node is readable."""

    sysfs_path: str
    bus: int
    device: int
    dev_node: str
    mode: str
    owner: str
    writable: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "sysfs_path": self.sysfs_path,
            "bus": self.bus,
            "device": self.device,
            "dev_node": self.dev_node,
            "mode": self.mode,
            "owner": self.owner,
            # The vendor control transfer needs O_RDWR on the node. Without it
            # every DOA_VALUE read is Errno 13 and the sector prefilter is inert.
            "control_writable": self.writable,
            "udev_rule_needed": not self.writable,
        }


def find_usb_node(
    *,
    vendor_id: int = XVF3800_VENDOR_ID,
    product_id: int = XVF3800_PRODUCT_ID,
    sysfs_root: Path = Path("/sys/bus/usb/devices"),
    dev_root: Path = Path("/dev/bus/usb"),
) -> UsbNode | None:
    """Walk sysfs for the array. ``None`` when it is not attached.

    Deliberately does not use pyusb: this must answer "is the udev rule in?" on a
    host where pyusb is not installed, which is the host that needs the answer.
    """

    want_vendor = f"{vendor_id:04x}"
    want_product = f"{product_id:04x}"
    if not sysfs_root.is_dir():
        return None
    for entry in sorted(sysfs_root.iterdir()):
        vendor_file = entry / "idVendor"
        product_file = entry / "idProduct"
        if not vendor_file.is_file() or not product_file.is_file():
            continue
        if vendor_file.read_text().strip() != want_vendor:
            continue
        if product_file.read_text().strip() != want_product:
            continue
        bus = int((entry / "busnum").read_text().strip())
        device = int((entry / "devnum").read_text().strip())
        node = dev_root / f"{bus:03d}" / f"{device:03d}"
        mode = ""
        owner = ""
        writable = False
        try:
            info = node.stat()
            mode = oct(info.st_mode & 0o7777)
            owner = f"{info.st_uid}:{info.st_gid}"
            import os

            writable = os.access(node, os.R_OK | os.W_OK)
        except OSError:
            mode = "absent"
        return UsbNode(
            sysfs_path=str(entry),
            bus=bus,
            device=device,
            dev_node=str(node),
            mode=mode,
            owner=owner,
            writable=writable,
        )
    return None


def udev_commands(node: UsbNode) -> list[str]:
    """The exact two lines that grant DoA, with this host's own sysfs path in them."""

    rule = (
        'SUBSYSTEM=="usb", ATTRS{idVendor}=="2886", ATTRS{idProduct}=="001a", '
        'MODE="0660", GROUP="plugdev", TAG+="uaccess"'
    )
    return [
        f"sudo tee /etc/udev/rules.d/99-respeaker-xvf3800.rules <<< '{rule}'",
        (
            "sudo udevadm control --reload && sudo udevadm trigger --action=change "
            f"{node.sysfs_path}"
        ),
    ]


# ============================================== the output mux (host control)
#
# WHAT THIS REFUTES. AIR-1 shipped its first draft asserting that this array
# "exposes only processed beams, so there is no raw microphone to read" and
# built a three-leg differential measurement around that. It is wrong. The
# XVF3800's two USB capture channels are each a MUX, selected at runtime over
# the same vendor control interface DoA already uses, and one of the categories
# is the raw microphone. So the textbook same-instant measurement — the signal
# entering the canceller and the signal leaving it, on the two channels of one
# recording — is available on the firmware already installed, with no second
# loudspeaker, no level matching and no flashing.
#
# THE 6-CHANNEL FIRMWARE IS NOT THE ANSWER AND MUST NOT BE FLASHED. It is a
# separate DFU image (`respeaker_xvf3800_usb_dfu_firmware_6chl_*.bin`), not a
# USB alternate setting — this host's descriptors carry exactly one 2-channel
# altset. Flashing re-enumerates the device with a different channel count,
# breaking every ALSA/PipeWire/PortAudio assumption in the voice stack, resets
# parameters, and is recoverable only via a bundled `4mb_all_ff.bin`. The mux
# below makes it unnecessary.
#
# Sources: Seeed reSpeaker_XVF3800_USB_4MIC_ARRAY host_control README ("Output
# Selection"), its python_control/xvf_host.py command map, and the XMOS XVF
# control-command appendix.

#: ``bmRequestType`` for a vendor IN / OUT control transfer on EP0. The IN value
#: matches ``realtime.voice_identity``'s DoA reader, which uses the same
#: interface — this is the one number both halves have to agree on.
_CTRL_IN = 0xC0
_CTRL_OUT = 0x40

#: The controls this tool knows, as ``(resource_id, command_id, count, kind)``.
#: Deliberately tiny: a control that is not here cannot be touched by accident,
#: and ``SAVE_CONFIGURATION`` is absent on purpose — nothing this tool does may
#: outlive a power cycle.
XVF_CONTROLS: dict[str, tuple[int, int, int, str]] = {
    "AUDIO_MGR_OP_L": (35, 15, 2, "uint8"),
    "AUDIO_MGR_OP_R": (35, 19, 2, "uint8"),
    "PP_AGCONOFF": (17, 10, 1, "int32"),
    "PP_AGCGAIN": (17, 13, 1, "float"),
    "PP_AGCMAXGAIN": (17, 11, 1, "float"),
}

#: The only controls :meth:`XvfControl.write` will ever accept, and only then
#: with ``allow_writes=True``. The AGC pair is writable because freezing
#: adaptation is part of a valid measurement; the mux because that IS the
#: measurement. Nothing else.
XVF_WRITABLE: frozenset[str] = frozenset(
    {"AUDIO_MGR_OP_L", "AUDIO_MGR_OP_R", "PP_AGCONOFF"}
)

#: Output-mux categories, from the vendor's "Output Selection" table.
MUX_RAW_MIC = 1  # raw microphone, before amplification, no system delay
MUX_AMPLIFIED_MIC = 3  # the mic signal as the canceller receives it
MUX_FAR_END = 4  # far-end reference, no system delay
MUX_FAR_END_DELAYED = 5  # far-end reference with system delay
MUX_PROCESSED = 6  # processed output; source 3 = auto-selected beam
MUX_AEC_RESIDUAL = 7  # per-microphone AEC residual

#: The pairing this tool uses: what went INTO the canceller on the left channel,
#: and the processed beam that came out on the right. Same instant, same
#: acoustic event, one recording. It measures the whole pipeline's echo
#: attenuation — the same quantity the three-leg fallback estimates — and needs
#: no second loudspeaker and no level match.
MUX_PAIR_PIPELINE: dict[str, tuple[int, int]] = {
    "AUDIO_MGR_OP_L": (MUX_AMPLIFIED_MIC, 0),
    "AUDIO_MGR_OP_R": (MUX_PROCESSED, 3),
}


class XvfControl:
    """The XVF3800 vendor control interface. EP0 only; writes are opt-in.

    Reads are always allowed and cannot change the device. Writes require
    ``allow_writes=True`` AND a control on :data:`XVF_WRITABLE`, because writing
    the output mux changes what the LIVE capture stream carries — a stack on
    :8765 would start receiving a raw microphone instead of the beam. Use
    :meth:`mux_session`, which reads the current routing, restores it in a
    ``finally``, and verifies the restore actually took.

    ``SAVE_CONFIGURATION`` is not in the command table and there is no code path
    that could issue it, so nothing here survives a power cycle.

    NEVER EXERCISED AGAINST HARDWARE. Every read on this host fails with
    ``Errno 13``: ``/dev/bus/usb/003/008`` is ``root:root 0664`` and the udev
    rule is an owner action. The encoding, the allow-list and the restore
    discipline are covered by ``tests/test_air1_mux.py`` against a fake device;
    the wire behaviour is not covered by anything and is owner-gated.
    """

    def __init__(self, *, vendor_id: int = XVF3800_VENDOR_ID,
                 product_id: int = XVF3800_PRODUCT_ID, timeout_ms: int = 200,
                 allow_writes: bool = False) -> None:
        self.vendor_id = int(vendor_id)
        self.product_id = int(product_id)
        self.timeout_ms = max(1, int(timeout_ms))
        self.allow_writes = bool(allow_writes)
        self.reads_ok = 0
        self.writes_ok = 0
        self.last_error = ""
        self._device: Any = None

    # ------------------------------------------------------------- plumbing
    def _ensure_device(self) -> Any:
        if self._device is not None:
            return self._device
        try:
            import usb.core
        except ImportError as error:
            raise ProbeError(f"pyusb is not available in this build ({error})") from None
        device = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
        if device is None:
            raise ProbeError(
                f"no USB device {self.vendor_id:04x}:{self.product_id:04x} is attached"
            )
        self._device = device
        return device

    @staticmethod
    def _decode(payload: bytes, count: int, kind: str) -> list[Any]:
        width = 1 if kind == "uint8" else 4
        values: list[Any] = []
        for index in range(count):
            chunk = payload[index * width:(index + 1) * width]
            if len(chunk) < width:
                break
            if kind == "uint8":
                values.append(int(chunk[0]))
            elif kind == "int32":
                values.append(int.from_bytes(chunk, "little", signed=True))
            else:
                values.append(struct.unpack("<f", chunk)[0])
        return values

    @staticmethod
    def _encode(values: Sequence[Any], kind: str) -> bytes:
        if kind == "uint8":
            return bytes(int(value) & 0xFF for value in values)
        if kind == "int32":
            return b"".join(int(value).to_bytes(4, "little", signed=True) for value in values)
        return b"".join(struct.pack("<f", float(value)) for value in values)

    # ------------------------------------------------------------------ API
    def read(self, name: str) -> list[Any]:
        """One control's current value. Read-only; safe beside a live session."""

        if name not in XVF_CONTROLS:
            raise ProbeError(f"unknown control {name!r}; this tool knows {sorted(XVF_CONTROLS)}")
        resource, command, count, kind = XVF_CONTROLS[name]
        width = 1 if kind == "uint8" else 4
        device = self._ensure_device()
        try:
            raw = bytes(
                device.ctrl_transfer(
                    _CTRL_IN, 0, 0x80 | command, resource, count * width + 1,
                    timeout=self.timeout_ms,
                )
            )
        except Exception as error:  # noqa: BLE001 - the refusal is the result
            self.last_error = f"{type(error).__name__}: {error}"
            raise ProbeError(f"reading {name} failed: {self.last_error}") from None
        payload = raw[1:] if len(raw) == count * width + 1 else raw
        self.reads_ok += 1
        return self._decode(payload, count, kind)

    def write(self, name: str, values: Sequence[Any]) -> None:
        """Set one control. Refused unless explicitly unlocked AND allow-listed."""

        if not self.allow_writes:
            raise ProbeError(
                f"refusing to write {name}: this XvfControl was opened read-only. "
                "Writing the output mux changes what the LIVE capture stream carries; "
                "pass allow_writes=True only when you own the audio path"
            )
        if name not in XVF_WRITABLE:
            raise ProbeError(
                f"refusing to write {name}: not on the allow-list {sorted(XVF_WRITABLE)}"
            )
        resource, command, count, kind = XVF_CONTROLS[name]
        if len(values) != count:
            raise ProbeError(f"{name} takes {count} value(s), got {len(values)}")
        device = self._ensure_device()
        try:
            device.ctrl_transfer(
                _CTRL_OUT, 0, command, resource, self._encode(values, kind),
                timeout=self.timeout_ms,
            )
        except Exception as error:  # noqa: BLE001
            self.last_error = f"{type(error).__name__}: {error}"
            raise ProbeError(f"writing {name} failed: {self.last_error}") from None
        self.writes_ok += 1

    # ------------------------------------------------------------- sessions
    @contextmanager
    def mux_session(self, routing: Mapping[str, tuple[int, int]]) -> Iterator[dict[str, Any]]:
        """Re-point the capture mux, then put it back. Restores on any exception.

        Yields the routing that was in place before, so a caller can record it.
        The restore is READ BACK and verified: a silent failure to restore would
        leave the owner's voice stack listening to a raw microphone with no sign
        that anything had happened, which is far worse than a loud error here.
        """

        previous = {name: list(self.read(name)) for name in routing}
        try:
            for name, value in routing.items():
                self.write(name, value)
            yield {"previous": previous, "applied": {k: list(v) for k, v in routing.items()}}
        finally:
            problems: list[str] = []
            for name, value in previous.items():
                try:
                    self.write(name, value)
                    if list(self.read(name)) != list(value):
                        problems.append(f"{name} did not read back as {value}")
                except ProbeError as error:
                    problems.append(str(error))
            if problems:
                raise ProbeError(
                    "THE CAPTURE MUX WAS NOT RESTORED — the array may still be sending a "
                    "raw microphone to every listener. Power-cycle the array (nothing was "
                    "saved to flash). Details: " + "; ".join(problems)
                )


def mux_snapshot(control: XvfControl | None = None) -> dict[str, Any]:
    """Read the mux and AGC state. READ-ONLY, and never raises.

    This is the section of the probe that answers "can the same-instant
    measurement run here?" — and, on a host without the udev rule, answers it
    with the permission error rather than with silence.
    """

    reader = control if control is not None else XvfControl()
    out: dict[str, Any] = {"readable": True, "controls": {}}
    for name in ("AUDIO_MGR_OP_L", "AUDIO_MGR_OP_R", "PP_AGCONOFF", "PP_AGCGAIN"):
        try:
            out["controls"][name] = reader.read(name)
        except ProbeError as error:
            out["readable"] = False
            out.setdefault("errors", {})[name] = str(error)
    out["same_instant_available"] = bool(out["readable"])
    if not out["readable"]:
        out["note"] = (
            "the vendor control interface could not be read, so the same-instant "
            "measurement is unavailable and the three-leg fallback is the only option. "
            "The usual cause is the missing udev rule (Errno 13)."
        )
    return out


# ============================================================== ALSA / stream0
_RATE_LINE = re.compile(r"^\s*Rates:\s*(?P<rates>[0-9,\s]+)$")
_CHANNEL_LINE = re.compile(r"^\s*Channels:\s*(?P<channels>\d+)\s*$")
_FORMAT_LINE = re.compile(r"^\s*Format:\s*(?P<format>\S+)\s*$")
_STATUS_LINE = re.compile(r"^\s*Status:\s*(?P<status>\S+)\s*$")


def parse_stream0(text: str) -> dict[str, Any]:
    """Parse ``/proc/asound/card<n>/stream0`` into playback/capture facts.

    Pure text in, dict out — so the 16 kHz claim can be tested against a captured
    copy of this host's own ``stream0`` on a machine with no array attached.
    """

    sections: dict[str, dict[str, Any]] = {}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in {"Playback:", "Capture:"}:
            current = stripped[:-1].lower()
            sections[current] = {"rates_hz": [], "channels": None, "format": "", "status": ""}
            continue
        if current is None:
            continue
        section = sections[current]
        match = _RATE_LINE.match(line)
        if match:
            rates = [int(part) for part in match.group("rates").replace(" ", "").split(",") if part]
            for rate in rates:
                if rate not in section["rates_hz"]:
                    section["rates_hz"].append(rate)
            continue
        match = _CHANNEL_LINE.match(line)
        if match and section["channels"] is None:
            section["channels"] = int(match.group("channels"))
            continue
        match = _FORMAT_LINE.match(line)
        if match and not section["format"]:
            section["format"] = match.group("format")
            continue
        match = _STATUS_LINE.match(line)
        if match and not section["status"]:
            section["status"] = match.group("status")
    for section in sections.values():
        section["rates_hz"].sort()
    return sections


def find_alsa_card(
    *, proc_root: Path = Path("/proc/asound"), name_fragment: str = "XVF3800"
) -> tuple[int, str] | None:
    """``(card index, stream0 text)`` for the array, or ``None``."""

    if not proc_root.is_dir():
        return None
    for entry in sorted(proc_root.glob("card*")):
        stream = entry / "stream0"
        if not stream.is_file():
            continue
        try:
            text = stream.read_text()
        except OSError:
            continue
        if name_fragment.lower() not in text.lower():
            continue
        digits = "".join(ch for ch in entry.name if ch.isdigit())
        if not digits:
            continue
        return int(digits), text
    return None


# ============================================================ the capture gain
_MIXER_CONTROL = re.compile(r"^Simple mixer control '(?P<name>[^']+)',(?P<index>\d+)\s*$")
_MIXER_VALUE = re.compile(
    r"^\s*(?P<channel>[A-Za-z ]+):\s+(?P<direction>Playback|Capture)\s+(?P<raw>-?\d+)"
    r"(?:\s+\[(?P<percent>-?\d+)%\])?(?:\s+\[(?P<db>-?[\d.]+)dB\])?"
)


def parse_amixer(text: str) -> dict[str, Any]:
    """Parse ``amixer -c N scontents`` into per-control gain values.

    WHY A LEVEL MEASUREMENT CARES. Two recordings compared in dB are only
    comparable if the gain between the microphone and the samples did not move
    between them. On this array that gain is a USB mixer control, it is readable,
    and it is the single most likely thing to have been nudged between two legs
    of an ERLE measurement recorded ten minutes apart. Reading it costs one
    subprocess and turns "I did not touch anything" into a recorded fact.
    """

    controls: dict[str, Any] = {}
    current: str | None = None
    for line in text.splitlines():
        match = _MIXER_CONTROL.match(line.strip())
        if match:
            current = f"{match.group('name')},{match.group('index')}"
            controls[current] = {}
            continue
        if current is None:
            continue
        match = _MIXER_VALUE.match(line)
        if not match:
            continue
        channel = match.group("channel").strip()
        if channel == "Limits":
            # `Limits: Playback 0 - 60` has the same shape as a value line and is
            # a range, not a setting. Recording it as a channel would make every
            # control look like it moved to zero.
            continue
        entry = controls[current].setdefault(match.group("direction").lower(), {})
        entry[channel] = {
            "raw": int(match.group("raw")),
            "db": None if match.group("db") is None else float(match.group("db")),
        }
    return controls


def alsa_gain_state(card: int, *, timeout_s: float = 10.0) -> dict[str, Any]:
    """The array's readable gain state right now. READ-ONLY: ``scontents`` only.

    This is as close to "the AGC state" as this device lets a host get without
    the vendor control interface. It is not the chip's internal adaptive gain —
    it is the USB-side capture and playback gain that scales what the host
    actually records, which is the part a dB subtraction depends on.
    """

    try:
        proc = subprocess.run(
            ["amixer", "-c", str(int(card)), "scontents"],
            capture_output=True, text=True, timeout=timeout_s, check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"available": False, "reason": f"{type(error).__name__}: {error}"}
    if proc.returncode != 0:
        return {"available": False, "reason": (proc.stderr or "amixer failed").strip()[:200]}
    return {"available": True, "card": int(card), "controls": parse_amixer(proc.stdout)}


# ================================================================== PipeWire
_WPCTL_ROW = re.compile(
    r"^\s*[│|├└─\s]*(?P<default>\*?)\s*(?P<id>\d+)\.\s+(?P<name>.+?)\s*"
    r"(?:\[vol:\s*(?P<vol>[0-9.]+)[^\]]*\])?\s*$"
)


def parse_wpctl_status(text: str) -> dict[str, list[dict[str, Any]]]:
    """Parse ``wpctl status`` into ``{"sinks": [...], "sources": [...]}``.

    Only the two sections AIR-1 cares about, and only the fields it uses: id,
    name, default flag, volume. A parser that read more would break more often.
    """

    wanted = {"Sinks:": "sinks", "Sources:": "sources"}
    out: dict[str, list[dict[str, Any]]] = {"sinks": [], "sources": []}
    current: str | None = None
    for line in text.splitlines():
        stripped = line.strip(" │├└─|")
        if stripped.endswith(":"):
            current = wanted.get(stripped)
            continue
        if current is None or not stripped:
            continue
        match = _WPCTL_ROW.match(line)
        if not match:
            continue
        volume = match.group("vol")
        out[current].append(
            {
                "id": int(match.group("id")),
                "name": match.group("name").strip(),
                "default": match.group("default") == "*",
                "volume": None if volume is None else float(volume),
            }
        )
    return out


def wpctl_status_text(*, timeout_s: float = 10.0) -> str:
    """``wpctl status`` output, or ``""`` when wpctl is not on this host."""

    try:
        proc = subprocess.run(
            ["wpctl", "status"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout or ""


def default_device_report(status: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    """Is the array PipeWire's default sink and source, and at what volume?"""

    report: dict[str, Any] = {}
    for kind in ("sinks", "sources"):
        rows = list(status.get(kind, ()))
        default = next((row for row in rows if row.get("default")), None)
        report[kind] = {
            "default_id": None if default is None else default.get("id"),
            "default_name": "" if default is None else str(default.get("name", "")),
            "default_volume": None if default is None else default.get("volume"),
            "is_array": bool(default is not None and "XVF3800" in str(default.get("name", ""))),
            "count": len(rows),
        }
    return report


# =============================================================== PortAudio
def _sounddevice() -> Any:
    try:
        import sounddevice
    except Exception as error:  # noqa: BLE001 - a missing PortAudio is a result
        raise ProbeError(
            f"sounddevice is unavailable ({error}); source scripts/env-audio.sh first"
        ) from None
    return sounddevice


def find_portaudio_device(name_fragment: str = "XVF3800") -> int | None:
    """Index of the array's ALSA hw device in PortAudio's list, or ``None``."""

    sounddevice = _sounddevice()
    for index, device in enumerate(sounddevice.query_devices()):
        name = str(device.get("name", ""))
        if name_fragment.lower() in name.lower() and "hw:" in name:
            return index
    return None


def rate_matrix(
    device_index: int, rates_hz: Iterable[int] = PROBE_RATES_HZ, *, channels: int = 2
) -> dict[str, dict[str, Any]]:
    """Ask PortAudio which rates this device will open, without opening one.

    ``Pa_IsFormatSupported`` is a query, not a stream: it does not take the
    device, so this is safe to run beside a live session. Both directions are
    swept because the array is 16 kHz-only in *both*, and a stack that resamples
    only one way still fails.
    """

    sounddevice = _sounddevice()
    out: dict[str, dict[str, Any]] = {}
    for rate in rates_hz:
        row: dict[str, Any] = {}
        for direction in ("input", "output"):
            check = (
                sounddevice.check_input_settings
                if direction == "input"
                else sounddevice.check_output_settings
            )
            try:
                check(device=device_index, samplerate=rate, channels=channels, dtype="int16")
            except Exception as error:  # noqa: BLE001 - the refusal IS the datum
                row[direction] = {"ok": False, "error": f"{type(error).__name__}: {error}"}
            else:
                row[direction] = {"ok": True, "error": ""}
        out[str(int(rate))] = row
    return out


def evaluate_rate_matrix(matrix: Mapping[str, Mapping[str, Mapping[str, Any]]]) -> list[str]:
    """Problems with a rate matrix. Empty list ⇒ the array is 16 kHz-only as pinned.

    Two ways to fail, and they mean opposite things. A refused 16 kHz says the
    array is gone or busy. An *accepted* 24 kHz says something between Python and
    the hardware is resampling silently — usually because the caller reached the
    PipeWire node instead of ``hw:`` — and every latency number measured through
    it belongs to that resampler, not to the array.
    """

    problems: list[str] = []
    for rate_text, row in sorted(matrix.items(), key=lambda item: int(item[0])):
        rate = int(rate_text)
        for direction in ("input", "output"):
            entry = row.get(direction)
            if not isinstance(entry, Mapping):
                problems.append(f"{rate} Hz {direction}: no result")
                continue
            ok = bool(entry.get("ok"))
            if rate in ARRAY_SUPPORTED_RATES_HZ and not ok:
                problems.append(f"{rate} Hz {direction} was REFUSED: {entry.get('error', '')}")
            if rate not in ARRAY_SUPPORTED_RATES_HZ and ok:
                problems.append(
                    f"{rate} Hz {direction} was ACCEPTED — this is not the array's hw device, "
                    "something is resampling underneath you"
                )
    return problems


# ============================================================ levels / downmix
def dbfs(rms: float, *, full_scale: float = 32768.0) -> float:
    """RMS in int16 counts as dBFS. ``-inf`` for digital silence, honestly."""

    if rms <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(rms / full_scale)


def channel_levels(samples: Any) -> list[dict[str, Any]]:
    """Per-channel RMS/peak of an ``(n, channels)`` int16 array."""

    import numpy as np

    block = np.asarray(samples, dtype=np.float64)
    if block.ndim == 1:
        block = block.reshape(-1, 1)
    rows: list[dict[str, Any]] = []
    for index in range(block.shape[1]):
        column = block[:, index]
        rms = float(np.sqrt(np.mean(np.square(column)))) if column.size else 0.0
        peak = float(np.max(np.abs(column))) if column.size else 0.0
        rows.append(
            {
                "channel": index,
                "beam": CAPTURE_BEAMS[index] if index < len(CAPTURE_BEAMS) else "raw",
                "rms": round(rms, 3),
                "rms_dbfs": round(dbfs(rms), 2),
                "peak": round(peak, 1),
                "peak_dbfs": round(dbfs(peak), 2),
            }
        )
    return rows


def downmix_hazard(samples: Any) -> dict[str, Any]:
    """What an ear that asked for ONE channel actually receives.

    ``getUserMedia({channelCount: 1})`` does not pick a beam — PipeWire averages
    ch0 and ch1. The average of two differently-processed beams of the same room
    is a third signal: correlated where they agree, partially cancelling where
    they do not. This reports the ASR beam's level, the average's level, and the
    difference, so "the downmix is harmless here" is a number and not a hope.
    """

    import numpy as np

    block = np.asarray(samples, dtype=np.float64)
    if block.ndim != 2 or block.shape[1] < 2:
        return {"applicable": False, "reason": "capture is not two-channel"}
    conference = block[:, 0]
    asr = block[:, ASR_CHANNEL_INDEX]
    mixed = (conference + asr) / 2.0

    def _rms(column: Any) -> float:
        return float(np.sqrt(np.mean(np.square(column)))) if column.size else 0.0

    asr_rms = _rms(asr)
    mixed_rms = _rms(mixed)
    denominator = float(np.std(conference) * np.std(asr))
    correlation = (
        float(np.corrcoef(conference, asr)[0, 1]) if denominator > 1e-9 else float("nan")
    )
    return {
        "applicable": True,
        "asr_rms_dbfs": round(dbfs(asr_rms), 2),
        "downmix_rms_dbfs": round(dbfs(mixed_rms), 2),
        "downmix_minus_asr_db": round(dbfs(mixed_rms) - dbfs(asr_rms), 2)
        if asr_rms > 0 and mixed_rms > 0
        else None,
        "ch0_ch1_correlation": None if math.isnan(correlation) else round(correlation, 4),
        "note": (
            "the ear must select channel "
            f"{ASR_CHANNEL_INDEX} ({CAPTURE_BEAMS[ASR_CHANNEL_INDEX]}); a one-channel "
            "request gets the average of both beams"
        ),
    }


def capture_channels(device_index: int, seconds: float, *, channels: int = 2) -> Any:
    """Record ``seconds`` of raw multi-channel int16 from the array. Opens the device."""

    sounddevice = _sounddevice()
    assert_array_rate(ARRAY_RATE_HZ, where="capture_channels")
    frames = round(float(seconds) * ARRAY_RATE_HZ)
    block = sounddevice.rec(
        frames,
        samplerate=ARRAY_RATE_HZ,
        channels=channels,
        dtype="int16",
        device=device_index,
        blocking=True,
    )
    return block


# ====================================================================== DoA
def poll_doa(samples: int, *, timeout_ms: int = 200) -> dict[str, Any]:
    """``samples`` consecutive ``DOA_VALUE`` reads through the product reader.

    Uses ``realtime.voice_identity.UsbDoaReader`` rather than a private copy, so
    a green DoA row here is a claim about the code the runtime actually runs.
    """

    try:
        from parcel_robot.realtime.voice_identity import (
            UsbDoaReader,
        )
    except Exception as error:  # noqa: BLE001 - an unimportable package is a result
        return {"ok": 0, "failed": 0, "reason": f"voice_identity did not import: {error}"}

    reader = UsbDoaReader(timeout_ms=timeout_ms)
    angles: list[int] = []
    read_ms: list[float] = []
    vad_true = 0
    for _ in range(int(samples)):
        sample = reader.read()
        if sample is None:
            continue
        angles.append(sample.angle_deg)
        read_ms.append(sample.read_ms)
        vad_true += int(bool(sample.vad))
    total = int(samples)
    ok = reader.reads_ok
    read_ms.sort()

    def _percentile(values: list[float], fraction: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, max(0, round(fraction * (len(values) - 1))))
        return round(values[index], 3)

    return {
        "requested": total,
        "ok": ok,
        "failed": reader.reads_failed,
        "ok_fraction": round(ok / total, 4) if total else 0.0,
        "last_error": reader.last_error,
        "vad_true": vad_true,
        "angles_deg": angles,
        "distinct_angles": len(set(angles)),
        "read_ms_p50": _percentile(read_ms, 0.5),
        "read_ms_p95": _percentile(read_ms, 0.95),
    }


# =================================================================== sections
@dataclass
class ProbeReport:
    """Everything the probe learned, plus whether any of it is wrong."""

    sections: dict[str, Any] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "parcel.air1.xvf3800_probe.v1",
            "sections": self.sections,
            "problems": self.problems,
            "ok": not self.problems,
        }


def usb_section(report: ProbeReport) -> None:
    node = find_usb_node()
    if node is None:
        report.sections["usb"] = {"attached": False}
        report.problems.append("the XVF3800 (2886:001a) is not attached")
        return
    payload = node.as_dict()
    payload["attached"] = True
    payload["udev_commands"] = udev_commands(node)
    report.sections["usb"] = payload
    if not node.writable:
        # NOT a problem: the array works fine without DoA. It is a finding, and
        # the DoA section is the one entitled to fail over it.
        report.sections["usb"]["note"] = (
            "the vendor control node is not writable by this user, so DOA_VALUE "
            "reads will fail with Errno 13 until the udev rule lands"
        )


def alsa_section(report: ProbeReport) -> None:
    found = find_alsa_card()
    if found is None:
        report.sections["alsa"] = {"found": False}
        report.problems.append("no /proc/asound/card*/stream0 names an XVF3800")
        return
    card, text = found
    parsed = parse_stream0(text)
    report.sections["alsa"] = {"found": True, "card": card, "hw": f"hw:{card},0", **parsed}
    for direction, section in parsed.items():
        rates = section.get("rates_hz") or []
        if list(rates) != list(ARRAY_SUPPORTED_RATES_HZ):
            report.problems.append(
                f"ALSA {direction} advertises {rates} Hz, not {list(ARRAY_SUPPORTED_RATES_HZ)} — "
                "the rate pin was written against a different firmware"
            )


def pipewire_section(report: ProbeReport) -> None:
    text = wpctl_status_text()
    if not text:
        report.sections["pipewire"] = {"available": False}
        return
    status = parse_wpctl_status(text)
    payload = default_device_report(status)
    payload["available"] = True
    report.sections["pipewire"] = payload
    for kind in ("sinks", "sources"):
        if not payload[kind]["is_array"]:
            report.problems.append(
                f"the array is not PipeWire's default {kind[:-1]} "
                f"(that is {payload[kind]['default_name']!r}) — the hardware AEC's "
                "reference is its own DAC, so playback that does not go through the "
                "array is echo the AEC has never heard of"
            )


def rates_section(report: ProbeReport) -> None:
    try:
        device = find_portaudio_device()
    except ProbeError as error:
        report.sections["rates"] = {"available": False, "reason": str(error)}
        return
    if device is None:
        report.sections["rates"] = {"available": False, "reason": "no hw: device named XVF3800"}
        report.problems.append("PortAudio does not list the array's hw device")
        return
    matrix = rate_matrix(device)
    problems = evaluate_rate_matrix(matrix)
    report.sections["rates"] = {
        "available": True,
        "portaudio_device": device,
        "matrix": matrix,
        "producers": check_producer_rates(),
        "problems": problems,
    }
    report.problems.extend(problems)


def mux_section(report: ProbeReport) -> None:
    """Can the same-instant echo measurement run on this host? READ-ONLY."""

    snapshot = mux_snapshot()
    report.sections["mux"] = snapshot
    # NOT a problem: the array works perfectly without it, and the three-leg
    # fallback exists precisely for this case. It is a capability, reported.


def doa_section(report: ProbeReport, samples: int) -> None:
    result = poll_doa(samples)
    report.sections["doa"] = result
    if result.get("ok_fraction", 0.0) < 0.95:
        report.problems.append(
            f"DoA polled {result.get('ok', 0)}/{result.get('requested', samples)} ok "
            f"({result.get('last_error', '')}) — below the 95 % row"
        )


def rms_section(report: ProbeReport, seconds: float) -> None:
    try:
        device = find_portaudio_device()
    except ProbeError as error:
        report.sections["rms"] = {"available": False, "reason": str(error)}
        return
    if device is None:
        report.sections["rms"] = {"available": False, "reason": "no hw: device named XVF3800"}
        return
    block = capture_channels(device, seconds)
    report.sections["rms"] = {
        "available": True,
        "seconds": seconds,
        "channels": channel_levels(block),
        "downmix": downmix_hazard(block),
    }


# ======================================================================== CLI
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--doa",
        type=int,
        default=0,
        metavar="N",
        help="poll DOA_VALUE N times (needs pyusb and the udev rule)",
    )
    parser.add_argument(
        "--rms",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="record SECONDS from the array and report per-channel level (opens the device)",
    )
    parser.add_argument(
        "--mux",
        action="store_true",
        help="read the output-mux and AGC state (needs pyusb + the udev rule); says "
             "whether the same-instant echo measurement can run here",
    )
    parser.add_argument("--json", type=Path, default=None, help="write the full report here")
    parser.add_argument("--quiet", action="store_true", help="report only, no human summary")
    return parser


def _print_summary(report: ProbeReport) -> None:
    sections = report.sections
    usb = sections.get("usb", {})
    if usb.get("attached"):
        print(
            f"usb       2886:001a at {usb['sysfs_path']} "
            f"({usb['dev_node']}, mode {usb['mode']}, "
            f"control {'RW' if usb['control_writable'] else 'read-only — udev rule missing'})"
        )
    else:
        print("usb       NOT ATTACHED")
    alsa = sections.get("alsa", {})
    if alsa.get("found"):
        capture = alsa.get("capture", {})
        playback = alsa.get("playback", {})
        print(
            f"alsa      {alsa['hw']}  capture {capture.get('rates_hz')} Hz "
            f"x{capture.get('channels')} {capture.get('format')} · "
            f"playback {playback.get('rates_hz')} Hz x{playback.get('channels')}"
        )
    pipewire = sections.get("pipewire", {})
    if pipewire.get("available"):
        for kind in ("sinks", "sources"):
            row = pipewire[kind]
            mark = "array" if row["is_array"] else "NOT THE ARRAY"
            print(
                f"pipewire  default {kind[:-1]:<6} {row['default_name']} "
                f"(vol {row['default_volume']}) — {mark}"
            )
    rates = sections.get("rates", {})
    if rates.get("available"):
        accepted = [rate for rate, row in rates["matrix"].items() if row["input"]["ok"]]
        print(f"rates     input accepts {accepted} Hz; every other rate is PaError -9997")
        for name, plan in rates["producers"].items():
            print(f"          {name:<16} {plan['source_rate_hz']:>6} Hz → {plan['action']}")
    elif rates:
        print(f"rates     unavailable: {rates.get('reason', '')}")
    mux = sections.get("mux")
    if mux:
        if mux.get("readable"):
            routing = mux.get("controls", {})
            print(
                f"mux       L={routing.get('AUDIO_MGR_OP_L')} R={routing.get('AUDIO_MGR_OP_R')} "
                f"AGC on={routing.get('PP_AGCONOFF')} gain={routing.get('PP_AGCGAIN')} "
                "— same-instant echo measurement AVAILABLE"
            )
        else:
            first = next(iter(mux.get("errors", {}).values()), "")
            print(f"mux       unreadable ({first}) — same-instant measurement unavailable")
    doa = sections.get("doa")
    if doa:
        print(
            f"doa       {doa.get('ok', 0)}/{doa.get('requested', 0)} ok "
            f"({doa.get('ok_fraction', 0.0):.0%}) {doa.get('last_error', '')}"
        )
    rms = sections.get("rms")
    if rms and rms.get("available"):
        for row in rms["channels"]:
            print(
                f"level     ch{row['channel']} ({row['beam']:<10}) "
                f"rms {row['rms_dbfs']:>7.2f} dBFS  peak {row['peak_dbfs']:>7.2f} dBFS"
            )
        hazard = rms["downmix"]
        if hazard.get("applicable"):
            print(
                f"downmix   one-channel ear would get {hazard['downmix_rms_dbfs']} dBFS vs "
                f"{hazard['asr_rms_dbfs']} dBFS on the ASR beam "
                f"(r={hazard['ch0_ch1_correlation']})"
            )
    if report.problems:
        print()
        for problem in report.problems:
            print(f"PROBLEM   {problem}")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = ProbeReport()
    usb_section(report)
    alsa_section(report)
    pipewire_section(report)
    rates_section(report)
    if args.mux:
        mux_section(report)
    if args.doa > 0:
        doa_section(report, args.doa)
    if args.rms > 0:
        rms_section(report, args.rms)
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    if not args.quiet:
        _print_summary(report)
        if args.json is not None:
            print(f"\nwrote {args.json}")
    # A section that could not run has not confirmed anything, and the config
    # note promises this command exits non-zero "when any of it stops being
    # true". An unavailable PortAudio makes the rate pin unconfirmable, which is
    # not the same as confirmed — so it is a non-zero exit with a named reason,
    # not a quiet success.
    unconfirmed = [
        name for name in ("rates",)
        if isinstance(report.sections.get(name), dict)
        and report.sections[name].get("available") is False
    ]
    if unconfirmed and not args.quiet:
        for name in unconfirmed:
            print(
                f"UNCONFIRMED  the {name} section could not run: "
                f"{report.sections[name].get('reason', '')}"
            )
    return 0 if not (report.problems or unconfirmed) else 1


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
