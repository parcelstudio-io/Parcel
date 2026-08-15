"""Fail-closed microphone arming gate (card FIX-A, fix F1).

WHY THIS MODULE EXISTS
----------------------
On 2026-08-11 the runtime armed its microphone loop on a desktop that had no
physical audio endpoints at all. PipeWire offered a single ``Dummy Output``
sink and ZERO sources, so the default capture stream was wired to the MONITOR
of the robot's own speaker sink — a unity-gain digital loopback. Every TTS
filler came back into the recognizer at full amplitude, defeated the acoustic
RMS echo guard, triggered barge-in, closed ~0.5 s utterances, and each junk
transcript was answered as a command. That self-talk oscillator ran 669 turns.

Arming was gated on exactly one condition: "is the STT service reachable".
The runtime's own audio probe was simultaneously and correctly reporting
``connected_input: false`` — and nothing read it.

This module is the missing gate. It answers one question with one line of
justification: *may the microphone loop open a capture stream?* It fails
CLOSED — an unknown or unprobeable audio world does not arm anything — and it
never silently degrades: every refusal carries a reason string the panel and
the log both show.

WHAT THIS IS NOT
----------------
This is an ARMING gate. It does not touch, tune, or second-guess the echo
guard, the barge-in policy, or the endpointer (N16/N17/B2 territory). A real
microphone in a real room still bleeds the robot's own voice into capture, and
nothing here improves that; it only stops the degenerate case where capture IS
the output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

#: ``speech:`` key that lets a deliberate loopback rig opt back in. Default is
#: False: fail closed, and never silently.
OVERRIDE_KEY = "allow_monitor_capture"

#: Machine-readable outcome codes. Anything other than ``armed`` /
#: ``override`` means the microphone loop was NOT constructed.
CODE_ARMED = "armed"
CODE_OVERRIDE = "armed_by_override"
CODE_NO_RECOGNIZER = "no_recognizer"
CODE_MONITOR = "monitor_capture"
CODE_NO_INPUT_ENDPOINT = "no_input_endpoint"


class _AudioProbe(Protocol):
    """The part of ``AudioDeviceStatus`` this gate reads."""

    connected_input: bool
    detail: str
    input_is_monitor: bool
    input_identity: str


@dataclass(frozen=True)
class CaptureIdentity:
    """What the resolved capture endpoint actually IS, and how we know.

    ``signal`` names the concrete metadata key that decided monitor-ness (e.g.
    ``device.class=monitor``), so a refusal is falsifiable. ``confidence``
    separates the two very different qualities of evidence:

    ``metadata``   PipeWire object properties — device.class / media.class /
                   stream.monitor. Authoritative.
    ``name_only``  A configured PortAudio device whose NAME contains
                   "monitor". Weak: a name is operator-chosen text, and this
                   is only ever used for an explicitly configured device that
                   PipeWire metadata could not classify.
    ``none``       No monitor evidence either way.
    """

    name: str = "system default"
    index: int | None = None
    is_monitor: bool = False
    signal: str = ""
    source: str = "unknown"
    confidence: str = "none"

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "index": self.index,
            "is_monitor": self.is_monitor,
            "signal": self.signal,
            "source": self.source,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class MicArmingDecision:
    """Whether the mic loop may arm, plus one line saying why not."""

    armed: bool
    code: str
    reason: str
    override: bool = False
    identity: CaptureIdentity = field(default_factory=CaptureIdentity)

    def as_dict(self) -> dict[str, object]:
        return {
            "armed": self.armed,
            "code": self.code,
            "reason": self.reason,
            "override": self.override,
            "capture_device": self.identity.as_dict(),
        }


def _monitor_by_name(name: str) -> bool:
    """Last-resort, explicitly weak: does a device NAME read as a monitor?

    PulseAudio/PipeWire name monitor sources ``Monitor of <sink>`` and
    ``<sink>.monitor``; PortAudio surfaces those names verbatim. Nothing else
    about a PortAudio entry distinguishes a monitor from a microphone.
    """

    folded = str(name).casefold()
    return "monitor of " in folded or folded.endswith(".monitor") or ".monitor " in folded


def capture_identity(
    *,
    audio_status: _AudioProbe,
    device_detail: str = "system default",
    device_index: int | None = None,
) -> CaptureIdentity:
    """Merge the PipeWire probe with the resolved PortAudio device.

    The probe classifies the SYSTEM DEFAULT capture endpoint from object
    metadata. When ``speech.input_device`` explicitly names a device, that
    device — not the default — is what will be opened, so the probe's verdict
    no longer describes it and the (weak) name signal is all that is left.
    """

    explicit = device_index is not None or device_detail not in {"", "system default"}
    if explicit:
        if _monitor_by_name(device_detail):
            return CaptureIdentity(
                name=device_detail,
                index=device_index,
                is_monitor=True,
                signal=f"portaudio device name {device_detail!r}",
                source="portaudio",
                confidence="name_only",
            )
        return CaptureIdentity(
            name=device_detail,
            index=device_index,
            is_monitor=False,
            signal="portaudio name carries no monitor marker",
            source="portaudio",
            confidence="name_only",
        )
    return CaptureIdentity(
        name="system default",
        index=None,
        is_monitor=bool(getattr(audio_status, "input_is_monitor", False)),
        signal=str(getattr(audio_status, "input_identity", "unknown")),
        source="pipewire",
        confidence="metadata"
        if getattr(audio_status, "input_identity", "unknown")
        not in {"unknown", "no default node", "node not inspectable"}
        else "none",
    )


def decide_microphone_arming(
    *,
    recognizer_available: bool,
    audio_status: _AudioProbe,
    identity: CaptureIdentity,
    allow_monitor_capture: bool = False,
) -> MicArmingDecision:
    """Decide whether to construct the microphone capture loop. Fails closed.

    Order matters only for which reason the operator reads first; both refusal
    conditions are checked. The monitor verdict is reported ahead of the
    missing-endpoint verdict because it is the more specific and more
    dangerous fact: the robot would be listening to its own mouth.
    """

    connected_input = bool(getattr(audio_status, "connected_input", False))
    probe_detail = str(getattr(audio_status, "detail", "")).strip()

    if not recognizer_available:
        # Unchanged historical behaviour, stated explicitly so the status line
        # is never blank.
        return MicArmingDecision(
            armed=False,
            code=CODE_NO_RECOGNIZER,
            reason="Microphone not armed: no speech recognizer (STT unreachable or disabled).",
            identity=identity,
        )

    if identity.is_monitor:
        if not allow_monitor_capture:
            return MicArmingDecision(
                armed=False,
                code=CODE_MONITOR,
                reason=(
                    "Microphone not armed: the capture endpoint is a monitor of a playback "
                    f"sink ({identity.signal}; confidence={identity.confidence}) — the robot "
                    "would transcribe its own speech. Set speech.allow_monitor_capture: true "
                    "to override for a deliberate loopback rig."
                ),
                identity=identity,
            )
        return MicArmingDecision(
            armed=True,
            code=CODE_OVERRIDE,
            reason=(
                "Microphone ARMED onto a sink monitor because speech.allow_monitor_capture "
                f"is true ({identity.signal}). The robot will hear its own speech; this is a "
                "loopback test configuration, not a usable listening configuration."
            ),
            override=True,
            identity=identity,
        )

    if not connected_input:
        if not allow_monitor_capture:
            return MicArmingDecision(
                armed=False,
                code=CODE_NO_INPUT_ENDPOINT,
                reason=(
                    "Microphone not armed: the audio probe reports no connected input "
                    f"endpoint ({probe_detail or 'no detail'}). A capture stream opened now "
                    "would be routed to whatever the host substitutes — on a sink-only host "
                    "that is the speaker's own monitor. Using streaming text."
                ),
                identity=identity,
            )
        return MicArmingDecision(
            armed=True,
            code=CODE_OVERRIDE,
            reason=(
                "Microphone ARMED with no connected input endpoint because "
                "speech.allow_monitor_capture is true. The host may substitute a sink "
                "monitor for the missing source; the robot may hear its own speech."
            ),
            override=True,
            identity=identity,
        )

    return MicArmingDecision(
        armed=True,
        code=CODE_ARMED,
        reason=f"Microphone armed on {identity.name} ({identity.signal or 'no identity signal'}).",
        identity=identity,
    )


def resolve_allow_monitor_capture(speech_config: dict[str, Any]) -> bool:
    """Read ``speech.allow_monitor_capture``; anything non-boolean fails loud."""

    value = speech_config.get(OVERRIDE_KEY, False)
    if isinstance(value, bool):
        return value
    raise ValueError(f"speech.{OVERRIDE_KEY} must be a boolean")


__all__ = [
    "CODE_ARMED",
    "CODE_MONITOR",
    "CODE_NO_INPUT_ENDPOINT",
    "CODE_NO_RECOGNIZER",
    "CODE_OVERRIDE",
    "OVERRIDE_KEY",
    "CaptureIdentity",
    "MicArmingDecision",
    "capture_identity",
    "decide_microphone_arming",
    "resolve_allow_monitor_capture",
]
