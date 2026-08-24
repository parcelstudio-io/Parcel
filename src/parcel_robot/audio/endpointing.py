"""Local neural voice activity and semantic turn endpointing.

The optional ONNX models are deliberately not bundled with Parcel:

* Smart Turn v3.2 CPU/int8 (8.7 MB):
  https://huggingface.co/pipecat-ai/smart-turn-v3/resolve/main/smart-turn-v3.2-cpu.onnx
* Silero VAD v6 (2 MB):
  https://github.com/snakers4/silero-vad/raw/v6.2/src/silero_vad/data/silero_vad.onnx

Smart Turn preprocessing follows the official ``pipecat-ai/smart-turn``
inference path: retain the last eight seconds of mono 16 kHz audio, pad on
the *left*, normalize the padded waveform, and compute Whisper-Tiny-style
80-bin log-mel features.  The numpy feature implementation mirrors Pipecat's
BSD-2/Apache-2 licensed ``_whisper_features.py`` implementation:
https://github.com/pipecat-ai/pipecat/blob/main/src/pipecat/audio/turn/smart_turn/_whisper_features.py

``onnxruntime`` is imported only when a real model is first used.  Missing or
broken optional dependencies never prevent this module from importing.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

_SAMPLE_RATE_HZ = 16_000
_SILERO_FRAME_SAMPLES = 512
_SILERO_CONTEXT_SAMPLES = 64
_SMART_TURN_SECONDS = 8
_SMART_TURN_SAMPLES = _SAMPLE_RATE_HZ * _SMART_TURN_SECONDS
_SMART_TURN_THRESHOLD = 0.5

_N_FFT = 400
_HOP_LENGTH = 160
_N_MELS = 80
_MEL_FLOOR = 1e-10
_NORM_VARIANCE_EPS = 1e-7


def _optional_module_present(name: str) -> bool:
    """Return whether an optional module can be imported without importing it."""

    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class SileroVad:
    """Stateful Silero VAD v6 ONNX inference for 32 ms, 16 kHz frames.

    ``process`` returns the raw probability; callers apply ``threshold`` when
    converting that probability into a speech/non-speech decision.
    """

    def __init__(self, model_path: str, *, threshold: float = 0.5):
        if not isinstance(model_path, str):
            raise TypeError("Silero model_path must be a string")
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError("Silero threshold must be in [0, 1]")

        self.model_path = model_path
        self.threshold = float(threshold)
        self._session: Any | None = None
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, _SILERO_CONTEXT_SAMPLES), dtype=np.float32)
        self._warned_unavailable = False

    @property
    def available(self) -> bool:
        """Whether both the configured model file and ONNX Runtime exist."""

        return Path(self.model_path).is_file() and _optional_module_present("onnxruntime")

    def process(self, frame: np.ndarray) -> float:
        """Return speech probability for one int16 mono 512-sample frame."""

        if not isinstance(frame, np.ndarray):
            raise TypeError("Silero VAD frames must be numpy arrays")
        if frame.dtype != np.int16:
            raise TypeError("Silero VAD frames must be int16 PCM")
        if frame.ndim != 1:
            raise ValueError(f"Silero VAD frames must be mono (1-D), got shape {frame.shape}")
        if frame.size != _SILERO_FRAME_SAMPLES:
            raise ValueError(
                "Silero VAD requires exactly 512 samples at 16 kHz "
                f"(received {frame.size})"
            )

        self._ensure_session()

        samples = frame.astype(np.float32)[None, :] / 32768.0
        model_input = np.concatenate((self._context, samples), axis=1)
        outputs = self._session.run(
            None,
            {
                "input": model_input,
                "state": self._state,
                "sr": np.asarray(_SAMPLE_RATE_HZ, dtype=np.int64),
            },
        )
        if len(outputs) < 2:
            raise RuntimeError("Silero VAD model returned no recurrent state")

        probabilities = np.asarray(outputs[0]).reshape(-1)
        if probabilities.size == 0:
            raise RuntimeError("Silero VAD model returned an empty probability output")
        probability = float(probabilities[0])
        state = np.asarray(outputs[1], dtype=np.float32)
        if state.shape != self._state.shape:
            raise RuntimeError(
                "Silero VAD model returned an invalid state shape: "
                f"expected {self._state.shape}, got {state.shape}"
            )
        if not math.isfinite(probability):
            raise RuntimeError("Silero VAD model returned a non-finite probability")

        self._state = state
        self._context = model_input[:, -_SILERO_CONTEXT_SAMPLES:].copy()
        return float(np.clip(probability, 0.0, 1.0))

    def _ensure_session(self) -> None:
        if self._session is not None:
            return
        if not self.available:
            reason = (
                f"model file not found: {self.model_path}"
                if not Path(self.model_path).is_file()
                else "onnxruntime is not installed"
            )
            if not self._warned_unavailable:
                warnings.warn(
                    f"Silero VAD unavailable ({reason}); neural VAD cannot run",
                    RuntimeWarning,
                    stacklevel=3,
                )
                self._warned_unavailable = True
            raise RuntimeError(f"Silero VAD unavailable: {reason}")

        try:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.inter_op_num_threads = 1
            options.intra_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(self.model_path, sess_options=options)
        except Exception as exc:
            if not self._warned_unavailable:
                warnings.warn(
                    f"Silero VAD model failed to load ({exc}); neural VAD cannot run",
                    RuntimeWarning,
                    stacklevel=3,
                )
                self._warned_unavailable = True
            raise RuntimeError(f"Silero VAD model failed to load: {exc}") from exc


class TurnEndpointer:
    """Dual-timeout semantic endpointing (Smart Turn v3 pattern).

    ``_infer`` is a test seam.  It receives exactly eight seconds of float32
    16 kHz audio, with older audio removed and short tails zero-padded on the
    left, and returns the probability that the user's turn is complete.
    """

    def __init__(
        self,
        model_path: str | None,
        *,
        complete_silence_s: float = 0.20,
        incomplete_silence_s: float = 2.5,
        _infer: Callable[[np.ndarray], float] | None = None,
    ):
        if model_path is not None and not isinstance(model_path, str):
            raise TypeError("Smart Turn model_path must be a string or None")
        if not math.isfinite(complete_silence_s) or complete_silence_s < 0.0:
            raise ValueError("complete_silence_s must be finite and non-negative")
        if not math.isfinite(incomplete_silence_s) or incomplete_silence_s <= 0.0:
            raise ValueError("incomplete_silence_s must be finite and positive")
        if incomplete_silence_s < complete_silence_s:
            raise ValueError("incomplete_silence_s must not be shorter than complete_silence_s")

        self.model_path = model_path
        self.complete_silence_s = float(complete_silence_s)
        self.incomplete_silence_s = float(incomplete_silence_s)
        self._session: Any | None = None
        self._silence_started_at: float | None = None
        self._completion_probability: float | None = None

        if _infer is not None:
            if not callable(_infer):
                raise TypeError("_infer must be callable")
            self._infer: Callable[[np.ndarray], float] | None = _infer
            self._detail = "smart-turn-v3"
        elif model_path and Path(model_path).is_file() and _optional_module_present("onnxruntime"):
            self._infer = self._infer_onnx
            self._detail = "smart-turn-v3"
        else:
            self._infer = None
            self._detail = "fixed-timeout-fallback"
            if not model_path:
                reason = "no Smart Turn model path was configured"
            elif not Path(model_path).is_file():
                reason = f"Smart Turn model file not found: {model_path}"
            else:
                reason = "onnxruntime is not installed"
            self._warn_fallback(reason)

    @property
    def detail(self) -> str:
        """Active endpointing implementation name."""

        return self._detail

    def observe(
        self,
        *,
        is_speech: bool,
        audio_tail: np.ndarray | None,
        now_s: float,
    ) -> str:
        """Observe speech state and return ``speaking``, ``hold``, or ``commit``."""

        if not isinstance(is_speech, (bool, np.bool_)):
            raise TypeError("is_speech must be a boolean")
        if not math.isfinite(now_s):
            raise ValueError("now_s must be finite")

        now = float(now_s)
        if is_speech:
            self._silence_started_at = None
            self._completion_probability = None
            return "speaking"

        if self._silence_started_at is None or now < self._silence_started_at:
            self._silence_started_at = now
            self._completion_probability = None

        elapsed = max(0.0, now - self._silence_started_at)

        if self._detail == "fixed-timeout-fallback":
            return "commit" if self._elapsed(elapsed, self.incomplete_silence_s) else "hold"

        if self._completion_probability is None and audio_tail is not None:
            prepared_audio = _prepare_smart_turn_audio(audio_tail)
            try:
                assert self._infer is not None
                probability = float(self._infer(prepared_audio))
                if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                    raise ValueError(
                        "Smart Turn inference must return a finite probability in [0, 1]"
                    )
                self._completion_probability = probability
            # An injected/model callable can surface backend-specific exception
            # types. Any inference failure must enter the documented fallback.
            except Exception as exc:  # noqa: BLE001
                self._degrade_to_fallback(f"Smart Turn inference failed: {exc}")
                return (
                    "commit"
                    if self._elapsed(elapsed, self.incomplete_silence_s)
                    else "hold"
                )

        complete = (
            self._completion_probability is not None
            and self._completion_probability >= _SMART_TURN_THRESHOLD
        )
        timeout = self.complete_silence_s if complete else self.incomplete_silence_s
        return "commit" if self._elapsed(elapsed, timeout) else "hold"

    @staticmethod
    def _elapsed(elapsed: float, timeout: float) -> bool:
        # Decimal test timestamps such as 10.2 - 10.0 land a few ulps below
        # 0.2; this tolerance does not move a real 16 kHz frame boundary.
        return elapsed + 1e-9 >= timeout

    def _infer_onnx(self, audio: np.ndarray) -> float:
        self._ensure_session()
        features = _whisper_log_mel_features(audio)
        outputs = self._session.run(
            None,
            {"input_features": np.expand_dims(features, axis=0)},
        )
        if not outputs:
            raise RuntimeError("Smart Turn model returned no outputs")
        probabilities = np.asarray(outputs[0]).reshape(-1)
        if probabilities.size == 0:
            raise RuntimeError("Smart Turn model returned an empty probability output")
        return float(probabilities[0])

    def _ensure_session(self) -> None:
        if self._session is not None:
            return
        if not self.model_path:
            raise RuntimeError("no Smart Turn model path was configured")

        import onnxruntime as ort

        options = ort.SessionOptions()
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self._session = ort.InferenceSession(self.model_path, sess_options=options)

    def _degrade_to_fallback(self, reason: str) -> None:
        self._infer = None
        self._session = None
        self._completion_probability = None
        self._detail = "fixed-timeout-fallback"
        self._warn_fallback(reason)

    def _warn_fallback(self, reason: str) -> None:
        warnings.warn(
            f"{reason}; using fixed {self.incomplete_silence_s:.3g} s turn timeout",
            RuntimeWarning,
            stacklevel=3,
        )


def _prepare_smart_turn_audio(audio: np.ndarray) -> np.ndarray:
    """Return Smart Turn's last-eight-seconds, left-padded float32 waveform."""

    if not isinstance(audio, np.ndarray):
        raise TypeError("Smart Turn audio_tail must be a numpy array or None")
    if audio.ndim != 1:
        raise ValueError(f"Smart Turn audio_tail must be mono (1-D), got shape {audio.shape}")
    if not np.issubdtype(audio.dtype, np.number) or np.issubdtype(
        audio.dtype, np.complexfloating
    ):
        raise TypeError("Smart Turn audio_tail must contain numeric PCM samples")

    if np.issubdtype(audio.dtype, np.integer):
        if audio.dtype != np.int16:
            raise TypeError("Integer Smart Turn audio_tail must be int16 PCM")
        waveform = audio.astype(np.float32) / 32768.0
    else:
        waveform = audio.astype(np.float32)
        if not np.all(np.isfinite(waveform)):
            raise ValueError("Smart Turn audio_tail contains non-finite samples")
        peak = float(np.max(np.abs(waveform))) if waveform.size else 0.0
        if peak > 1.0:
            waveform = waveform / peak

    if waveform.size > _SMART_TURN_SAMPLES:
        waveform = waveform[-_SMART_TURN_SAMPLES:]
    elif waveform.size < _SMART_TURN_SAMPLES:
        waveform = np.pad(
            waveform,
            (_SMART_TURN_SAMPLES - waveform.size, 0),
            mode="constant",
        )
    return np.ascontiguousarray(waveform, dtype=np.float32)


# Feature routines derived from Pipecat's numpy-only Smart Turn v3 path.
# Copyright (c) 2024-2026, Daily. SPDX-License-Identifier: BSD-2-Clause.
# The implementation in turn mirrors Hugging Face's Apache-2.0 Whisper
# feature extractor; both upstream source links are recorded in this module's
# docstring.
# Keeping them local avoids importing transformers (hundreds of MB of RSS) and
# preserves the card's numpy + stdlib dependency boundary.
def _hertz_to_mel_slaney(frequency: np.ndarray) -> np.ndarray:
    min_log_hertz = 1000.0
    min_log_mel = 15.0
    logstep = 27.0 / np.log(6.4)
    frequency = np.atleast_1d(np.asarray(frequency, dtype=np.float64))
    mels = 3.0 * frequency / 200.0
    log_region = frequency >= min_log_hertz
    mels[log_region] = min_log_mel + np.log(frequency[log_region] / min_log_hertz) * logstep
    return mels


def _mel_to_hertz_slaney(mels: np.ndarray) -> np.ndarray:
    min_log_hertz = 1000.0
    min_log_mel = 15.0
    logstep = np.log(6.4) / 27.0
    mels = np.atleast_1d(np.asarray(mels, dtype=np.float64))
    frequency = 200.0 * mels / 3.0
    log_region = mels >= min_log_mel
    frequency[log_region] = min_log_hertz * np.exp(
        logstep * (mels[log_region] - min_log_mel)
    )
    return frequency


def _build_mel_filterbank() -> np.ndarray:
    mel_min = float(_hertz_to_mel_slaney(np.array([0.0]))[0])
    mel_max = float(_hertz_to_mel_slaney(np.array([_SAMPLE_RATE_HZ / 2.0]))[0])
    mel_frequencies = np.linspace(mel_min, mel_max, _N_MELS + 2)
    filter_frequencies = _mel_to_hertz_slaney(mel_frequencies)
    fft_frequencies = np.linspace(0, _SAMPLE_RATE_HZ // 2, _N_FFT // 2 + 1)
    filter_difference = np.diff(filter_frequencies)
    slopes = np.expand_dims(filter_frequencies, 0) - np.expand_dims(fft_frequencies, 1)
    down_slopes = -slopes[:, :-2] / filter_difference[:-1]
    up_slopes = slopes[:, 2:] / filter_difference[1:]
    filters = np.maximum(np.zeros(1), np.minimum(down_slopes, up_slopes))
    area_normalization = 2.0 / (
        filter_frequencies[2 : _N_MELS + 2] - filter_frequencies[:_N_MELS]
    )
    filters *= np.expand_dims(area_normalization, 0)
    return filters


_HANN_WINDOW = np.hanning(_N_FFT + 1)[:-1]
_MEL_FILTERS = _build_mel_filterbank()


def _whisper_log_mel_features(audio: np.ndarray) -> np.ndarray:
    """Compute the exact Smart Turn v3 Whisper feature tensor (80, 800)."""

    if audio.shape != (_SMART_TURN_SAMPLES,):
        raise ValueError(
            f"Smart Turn preprocessing requires {_SMART_TURN_SAMPLES} samples, "
            f"got shape {audio.shape}"
        )

    waveform = np.asarray(audio, dtype=np.float32)
    waveform = (waveform - waveform.mean()) / np.sqrt(
        waveform.var() + _NORM_VARIANCE_EPS
    )
    pad = _N_FFT // 2
    padded = np.pad(waveform.astype(np.float64), (pad, pad), mode="reflect")
    windows = sliding_window_view(padded, _N_FFT)[::_HOP_LENGTH]
    spectrum = np.fft.rfft(windows * _HANN_WINDOW.astype(np.float64), axis=-1)
    magnitudes = (np.abs(spectrum) ** 2).T
    mel_spectrum = np.maximum(_MEL_FLOOR, _MEL_FILTERS.T @ magnitudes)
    log_spectrum = np.log10(mel_spectrum)
    log_spectrum = log_spectrum[:, :-1]
    log_spectrum = np.maximum(log_spectrum, log_spectrum.max() - 8.0)
    log_spectrum = (log_spectrum + 4.0) / 4.0
    return log_spectrum.astype(np.float32)
