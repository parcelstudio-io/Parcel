#!/usr/bin/env python
"""Does the XVF3800 -> JST amp -> CQRobot speaker path make a sound? Measured.

``scrum/20260822/task_44/HWMIC_STATUS.md`` recorded ``frames_out 0``: nothing had
ever been played through this board. This is the first attempt, and it answers
what it can.

WHAT IS ACTUALLY MEASURABLE HERE
--------------------------------
The array cancels its OWN DAC on-chip (the AEC's reference is that DAC), and its
USB capture exposes only the two processed beams. So a probe played through the
board and recorded on the board's own microphones is the ONE case where "no
speaker attached" and "an AEC doing its job" look identical. This tool therefore
reports:

1. the OUTPUT INVENTORY — every ALSA card and whether its profiles are
   ``available``, plus paired Bluetooth sinks. If the array's DAC is the only
   output on the host, no independent listener exists and no through-air row can
   be run at all; that alone is a finding;
2. the RESIDUAL — short high-level bursts with long gaps (an adaptive canceller
   has to re-converge at every onset, so the leak is largest there), reported as
   the rise over the room floor in the same window;
3. a REAL ROBOT UTTERANCE through the same path, reported the same way.

It does NOT claim audibility either way. It writes the numbers and says which
owner action would settle it: listen to the board while it plays, or put any
independent microphone in the room.
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import wave
from pathlib import Path

import numpy as np

RATE_HZ = 16_000
BURSTS = 5
BURST_S = 0.15
BURST_GAP_S = 2.0


def output_inventory() -> dict:
    """Every audio output this host could possibly present a stimulus through."""

    dump = subprocess.run(["pw-dump"], capture_output=True, text=True, check=False)
    devices: list[dict] = []
    try:
        objects = json.loads(dump.stdout or "[]")
    except json.JSONDecodeError:  # pragma: no cover - a missing pipewire is a finding
        objects = []
    for entry in objects:
        if entry.get("type") != "PipeWire:Interface:Device":
            continue
        params = entry.get("info", {}).get("params", {})
        props = entry.get("info", {}).get("props", {})
        if "EnumProfile" not in params:
            continue
        devices.append(
            {
                "id": entry.get("id"),
                "name": props.get("device.name"),
                "description": props.get("device.description"),
                "active_profile": [
                    profile.get("name") for profile in params.get("Profile", [])
                ],
                "profiles": [
                    {
                        "name": profile.get("name"),
                        "description": profile.get("description"),
                        "available": profile.get("available"),
                    }
                    for profile in params.get("EnumProfile", [])
                ],
            }
        )
    bluetooth = subprocess.run(
        ["bluetoothctl", "devices"], capture_output=True, text=True, check=False, timeout=15
    ).stdout.strip()
    return {"pipewire_devices": devices, "bluetooth_devices": bluetooth}


def frame_db(samples: np.ndarray, window: int = 160) -> np.ndarray:
    usable = samples.size - samples.size % window
    blocks = samples[:usable].reshape(-1, window)
    return 20 * np.log10(np.sqrt(np.maximum(1e-12, (blocks**2).mean(axis=1))))


def play_and_capture(probe: np.ndarray, device: int) -> np.ndarray:
    import sounddevice as sd

    total = probe.size
    out = np.column_stack([probe, probe]).astype(np.float32)
    rec = np.zeros((total, 2), dtype=np.float32)
    cursor = {"in": 0, "out": 0}

    def callback(indata, outdata, frames, _time, _status) -> None:
        taken = min(frames, total - cursor["in"])
        rec[cursor["in"] : cursor["in"] + taken] = indata[:taken]
        cursor["in"] += taken
        given = min(frames, total - cursor["out"])
        outdata[:given] = out[cursor["out"] : cursor["out"] + given]
        if given < frames:
            outdata[given:] = 0
        cursor["out"] += given

    with sd.Stream(
        device=(device, device),
        samplerate=RATE_HZ,
        channels=(2, 2),
        dtype="float32",
        blocksize=256,
        callback=callback,
    ):
        sd.sleep(int(total / RATE_HZ * 1000) + 400)
    return rec


def burst_probe(seed: int = 11) -> tuple[np.ndarray, list[tuple[int, int]]]:
    total = int((BURST_GAP_S * (BURSTS + 1)) * RATE_HZ)
    probe = np.zeros(total, dtype=np.float32)
    rng = np.random.default_rng(seed)
    spans: list[tuple[int, int]] = []
    for index in range(BURSTS):
        start = int(RATE_HZ * BURST_GAP_S * (index + 1))
        end = start + int(RATE_HZ * BURST_S)
        segment = rng.standard_normal(end - start)
        spectrum = np.fft.rfft(segment)
        frequencies = np.fft.rfftfreq(segment.size, 1.0 / RATE_HZ)
        spectrum[(frequencies < 200) | (frequencies > 6000)] = 0.0
        segment = np.fft.irfft(spectrum, segment.size)
        probe[start:end] = (0.95 * segment / (np.abs(segment).max() + 1e-9)).astype(np.float32)
        spans.append((start, end))
    return probe, spans


def load_wav_16k(path: Path) -> np.ndarray:
    with wave.open(str(path)) as handle:
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float64) / 32768.0
    if rate != RATE_HZ:
        index = np.linspace(0.0, samples.size - 1.0, round(samples.size * RATE_HZ / rate))
        samples = np.interp(index, np.arange(samples.size), samples)
    return samples.astype(np.float32)


def analyse(rec: np.ndarray, spans: list[tuple[int, int]]) -> dict:
    out: dict[str, list[dict]] = {}
    for channel in (0, 1):
        levels = frame_db(rec[:, channel].astype(np.float64))
        rows = []
        for start, end in spans:
            window = 160
            first = start // window
            last = end // window + 2
            before = levels[max(0, first - 100) : first]
            during = levels[first:last]
            rows.append(
                {
                    "burst_at_s": start / RATE_HZ,
                    "floor_dbfs": float(before.mean()) if before.size else float("nan"),
                    "peak_dbfs": float(during.max()) if during.size else float("nan"),
                    "rise_db": float(during.max() - before.mean()) if before.size else float("nan"),
                }
            )
        out[f"ch{channel}"] = rows
    return out


def transcribe_capture(channel: np.ndarray) -> dict:
    """What the local ear made of the array's own capture during playback."""

    from .asr import WhisperClient
    from .gate import GateConfig, Tape, run_gate, vad_only_arm

    pcm = np.clip(np.rint(channel.astype(np.float64) * 32768.0), -32768, 32767).astype(np.int16)
    admissions, transport = run_gate(Tape(samples=pcm, placements=[]), vad_only_arm,
                                     config=GateConfig())
    client = WhisperClient()
    transcript = client.transcribe(channel.astype(np.float64))
    return {
        "vad_spans": len(admissions),
        "vad_uploaded_seconds": transport.uploaded_seconds,
        "transcript": transcript.text.strip(),
        "capture_rms_dbfs": float(
            20 * np.log10(np.sqrt(np.mean(channel.astype(np.float64) ** 2)) + 1e-12)
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", type=int, default=4)
    parser.add_argument("--tts-wav", type=Path, default=None, nargs="*")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--transcribe",
        action="store_true",
        help="run the local ASR and the VAD gate over what the array captured while its "
        "own DAC played the robot's voice — the self-speech row, on the real device",
    )
    args = parser.parse_args()

    inventory = output_inventory()
    probe, spans = burst_probe()
    rec = play_and_capture(probe, args.device)
    payload = {
        "tier": "desktop-real-sensor",
        "host": platform.node(),
        "device_index": args.device,
        "question": "does the XVF3800 DAC -> JST amp -> CQRobot speaker path emit sound?",
        "verdict": "UNDETERMINED_ON_THIS_HOST",
        "why": (
            "the array's AEC references its own DAC and its USB capture exposes only "
            "processed beams, so 'no speaker attached' and 'a working canceller' produce "
            "the same recording; this host has no independent microphone and no other "
            "loudspeaker to cross-check with"
        ),
        "frames_out_nonzero": True,
        "frames_out_note": (
            "HWMIC_STATUS.md recorded frames_out 0 to date; this run is the first audio "
            "ever pushed to this board's playback endpoint"
        ),
        "output_inventory": inventory,
        "burst_probe": {
            "bursts": BURSTS,
            "burst_s": BURST_S,
            "amplitude": 0.95,
            "levels": analyse(rec, spans),
        },
    }
    if args.tts_wav:
        utterances = []
        for wav in args.tts_wav:
            speech = load_wav_16k(wav)
            padded = np.concatenate(
                [np.zeros(int(RATE_HZ * 2.0), dtype=np.float32), speech,
                 np.zeros(int(RATE_HZ * 2.0), dtype=np.float32)]
            )
            padded = (0.9 * padded / (np.abs(padded).max() + 1e-9)).astype(np.float32)
            tts_rec = play_and_capture(padded, args.device)
            tts_span = [(int(RATE_HZ * 2.0), int(RATE_HZ * 2.0) + speech.size)]
            row = {
                "wav": str(wav),
                "seconds": float(speech.size / RATE_HZ),
                "levels": analyse(tts_rec, tts_span),
            }
            if args.transcribe:
                row.update(transcribe_capture(tts_rec[:, 1]))
            utterances.append(row)
        payload["robot_utterances"] = utterances
        payload["self_speech_row"] = {
            "question": "while the array's own DAC played the robot's voice at -0.9 dBFS, "
            "did the ASR beam carry enough of it to open a VAD gate or be transcribed?",
            "vad_spans_total": sum(row.get("vad_spans", 0) for row in utterances),
            "transcribed_words_total": sum(
                len(row.get("transcript", "").split()) for row in utterances
            ),
            "reading": (
                "zero of both is consistent with an unwired speaker AND with an on-chip AEC "
                "that suppresses self-speech below the ASR floor; it does not distinguish "
                "them, and it is not an AEC attenuation figure"
            ),
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    for channel, rows in payload["burst_probe"]["levels"].items():
        rises = ", ".join(f"{row['rise_db']:.1f}" for row in rows)
        print(f"{channel}: burst rise over floor (dB) = {rises}")
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
