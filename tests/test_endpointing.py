from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import numpy as np
import pytest

from parcel_robot.endpointing import SileroVad, TurnEndpointer


def _audio_tail(samples: int = 16_000) -> np.ndarray:
    return np.arange(samples, dtype=np.int16)


def test_complete_turn_commits_after_short_semantic_timeout():
    endpointer = TurnEndpointer(None, _infer=lambda _audio: 0.9)

    assert endpointer.detail == "smart-turn-v3"
    assert endpointer.observe(is_speech=True, audio_tail=None, now_s=4.0) == "speaking"
    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=5.0) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=5.199) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=5.2) == "commit"


def test_incomplete_turn_holds_until_long_timeout():
    calls = 0

    def incomplete(_audio: np.ndarray) -> float:
        nonlocal calls
        calls += 1
        return 0.49

    endpointer = TurnEndpointer(None, _infer=incomplete)

    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=10.0) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=10.2) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=12.499) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=12.5) == "commit"
    assert calls == 1


def test_new_speech_resets_the_silence_clock_and_cached_prediction():
    probabilities = iter((0.9, 0.1))
    endpointer = TurnEndpointer(None, _infer=lambda _audio: next(probabilities))

    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=1.0) == "hold"
    assert endpointer.observe(is_speech=True, audio_tail=None, now_s=1.15) == "speaking"
    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=2.0) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=2.2) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=4.5) == "commit"


def test_injected_inference_receives_last_eight_seconds_with_leading_padding():
    observed: list[np.ndarray] = []
    endpointer = TurnEndpointer(None, _infer=lambda audio: observed.append(audio.copy()) or 0.0)
    short = np.array([-32768, 0, 16384, 32767], dtype=np.int16)

    assert endpointer.observe(is_speech=False, audio_tail=short, now_s=0.0) == "hold"

    assert len(observed) == 1
    prepared = observed[0]
    assert prepared.dtype == np.float32
    assert prepared.shape == (8 * 16_000,)
    assert np.count_nonzero(prepared[:-4]) == 0
    assert prepared[-4:] == pytest.approx((-1.0, 0.0, 0.5, 32767 / 32768))


def test_injected_inference_truncates_oldest_audio():
    observed: list[np.ndarray] = []
    endpointer = TurnEndpointer(None, _infer=lambda audio: observed.append(audio.copy()) or 0.0)
    long_tail = np.arange(8 * 16_000 + 13, dtype=np.int16)

    endpointer.observe(is_speech=False, audio_tail=long_tail, now_s=0.0)

    expected = long_tail[-8 * 16_000 :].astype(np.float32) / 32768.0
    assert observed[0] == pytest.approx(expected)


def test_smart_turn_onnx_seam_receives_whisper_tiny_feature_shape():
    class FakeSession:
        def __init__(self):
            self.features: np.ndarray | None = None

        def run(self, _outputs, inputs):
            self.features = inputs["input_features"].copy()
            return [np.array([[0.75]], dtype=np.float32)]

    session = FakeSession()
    endpointer = TurnEndpointer(None, _infer=lambda _audio: 0.0)
    endpointer._session = session
    endpointer._infer = endpointer._infer_onnx

    decision = endpointer.observe(
        is_speech=False,
        audio_tail=np.zeros(16_000, dtype=np.int16),
        now_s=0.0,
    )

    assert decision == "hold"
    assert session.features is not None
    assert session.features.shape == (1, 80, 800)
    assert session.features.dtype == np.float32


def test_smart_turn_rejects_complex_audio_tail():
    endpointer = TurnEndpointer(None, _infer=lambda _audio: 0.0)

    with pytest.raises(TypeError, match="numeric PCM"):
        endpointer.observe(
            is_speech=False,
            audio_tail=np.zeros(512, dtype=np.complex64),
            now_s=0.0,
        )


def test_missing_model_degrades_loudly_to_fixed_timeout(tmp_path: Path):
    missing = tmp_path / "smart-turn-v3.2-cpu.onnx"
    with pytest.warns(RuntimeWarning, match="model file not found"):
        endpointer = TurnEndpointer(str(missing))

    assert endpointer.detail == "fixed-timeout-fallback"
    assert endpointer.observe(is_speech=True, audio_tail=None, now_s=1.0) == "speaking"
    assert endpointer.observe(is_speech=False, audio_tail=None, now_s=2.0) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=None, now_s=4.499) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=None, now_s=4.5) == "commit"


def test_inference_error_degrades_loudly_without_short_commit():
    def broken(_audio: np.ndarray) -> float:
        raise OSError("bad graph")

    endpointer = TurnEndpointer(None, _infer=broken)
    with pytest.warns(RuntimeWarning, match="inference failed"):
        assert (
            endpointer.observe(is_speech=False, audio_tail=_audio_tail(), now_s=3.0)
            == "hold"
        )

    assert endpointer.detail == "fixed-timeout-fallback"
    assert endpointer.observe(is_speech=False, audio_tail=None, now_s=5.499) == "hold"
    assert endpointer.observe(is_speech=False, audio_tail=None, now_s=5.5) == "commit"


@pytest.mark.parametrize(
    ("frame", "error", "match"),
    [
        (np.zeros(512, dtype=np.float32), TypeError, "int16"),
        (np.zeros((1, 512), dtype=np.int16), ValueError, "mono"),
        (np.zeros(511, dtype=np.int16), ValueError, "exactly 512"),
        (np.zeros(513, dtype=np.int16), ValueError, "exactly 512"),
    ],
)
def test_silero_frame_validation_happens_before_optional_runtime_check(
    frame: np.ndarray,
    error: type[Exception],
    match: str,
):
    vad = SileroVad("/definitely/missing/silero-vad-v6.onnx")
    with pytest.raises(error, match=match):
        vad.process(frame)


def test_silero_missing_model_is_unavailable_and_fails_loudly():
    vad = SileroVad("/definitely/missing/silero-vad-v6.onnx")

    assert not vad.available
    with (
        pytest.warns(RuntimeWarning, match="Silero VAD unavailable"),
        pytest.raises(RuntimeError, match="model file not found"),
    ):
        vad.process(np.zeros(512, dtype=np.int16))


def test_silero_streams_context_and_recurrent_state_between_frames():
    class FakeSession:
        def __init__(self):
            self.inputs: list[dict[str, np.ndarray]] = []

        def run(self, _outputs, inputs):
            self.inputs.append({name: value.copy() for name, value in inputs.items()})
            return [np.array([[0.75]], dtype=np.float32), inputs["state"] + 1.0]

    session = FakeSession()
    vad = SileroVad("unused.onnx")
    vad._session = session
    first = np.arange(512, dtype=np.int16)
    second = np.arange(512, 1024, dtype=np.int16)

    assert vad.process(first) == pytest.approx(0.75)
    assert vad.process(second) == pytest.approx(0.75)

    first_input, second_input = session.inputs
    assert first_input["input"].shape == (1, 576)
    assert np.count_nonzero(first_input["input"][:, :64]) == 0
    assert first_input["state"] == pytest.approx(np.zeros((2, 1, 128)))
    assert first_input["sr"].dtype == np.int64
    assert int(first_input["sr"]) == 16_000
    assert second_input["input"][0, :64] == pytest.approx(first[-64:] / 32768.0)
    assert second_input["state"] == pytest.approx(np.ones((2, 1, 128)))


_REAL_SMART_TURN_PATH = Path(
    os.environ.get(
        "PARCEL_SMART_TURN_MODEL",
        "models/smart-turn/smart-turn-v3.2-cpu.onnx",
    )
)
_REAL_SMART_TURN_AVAILABLE = (
    _REAL_SMART_TURN_PATH.is_file() and importlib.util.find_spec("onnxruntime") is not None
)


@pytest.mark.skipif(
    not _REAL_SMART_TURN_AVAILABLE,
    reason="Smart Turn ONNX model and onnxruntime are optional",
)
def test_real_smart_turn_onnx_path_returns_a_valid_decision():
    endpointer = TurnEndpointer(str(_REAL_SMART_TURN_PATH))

    decision = endpointer.observe(
        is_speech=False,
        audio_tail=np.zeros(16_000, dtype=np.int16),
        now_s=0.0,
    )

    assert endpointer.detail == "smart-turn-v3"
    assert decision == "hold"
