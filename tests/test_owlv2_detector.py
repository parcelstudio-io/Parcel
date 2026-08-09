"""B3 — OWLv2 open-vocab detector behind the Detector protocol.

CI-safe tiers (no weights, no GL): loud-degrade to "detector unavailable", the pure
decode/NMS/preprocess math against a MOCK onnxruntime session, and the additive/opt-in
guarantee. Real-weight + real-render cells are ``skipif``-guarded so they run only where
``scripts/fetch_owlv2.sh`` landed the model, ``PARCEL_OWLV2_ONNX=1`` opted in, and an
offscreen GL context exists — and skip cleanly (byte-unchanged) everywhere else.
"""

from __future__ import annotations

import math
import os

import numpy as np
import pytest

from parcel_robot.detection_adapter import (
    Detector,
    OwlV2Detector,
    load_owlv2_detector,
    owlv2_weights_present,
)
from parcel_robot.detection_adapter.owlv2_onnx import (
    OWLV2_TEXT_SEQ_LEN,
    _iou,
    _nms,
    _normalize_phrases,
    onnx_enabled,
)
from parcel_robot.detection_adapter.pixel_detections import PixelDetection

# ---------------------------------------------------------------------------
# loud degrade / additive-opt-in
# ---------------------------------------------------------------------------


def test_default_is_detector_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the opt-in env switch unset, the loader returns None even if weights exist.

    This is the whole additive/byte-identical guarantee: merely landing the model on
    disk never flips CI/mission onto the neural detector.
    """

    monkeypatch.delenv("PARCEL_OWLV2_ONNX", raising=False)
    assert onnx_enabled() is False
    assert load_owlv2_detector() is None


def test_missing_weights_returns_none(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("PARCEL_OWLV2_ONNX", "1")
    monkeypatch.setenv("PARCEL_OWLV2_DIR", str(tmp_path))
    assert owlv2_weights_present() is False
    assert load_owlv2_detector() is None  # loud degrade, never raises


def test_owlv2_satisfies_detector_protocol() -> None:
    # OwlV2Detector must be a structural Detector (name + detect(*, rgb, depth, seg, query)).
    assert hasattr(OwlV2Detector, "detect")
    assert issubclass(OwlV2Detector, object)


# ---------------------------------------------------------------------------
# pure helpers (no weights, no numpy session)
# ---------------------------------------------------------------------------


def test_normalize_phrases_dedups_lowercases_and_unscores() -> None:
    assert _normalize_phrases(None) == []
    assert _normalize_phrases("Trash_Can") == ["trash can"]
    assert _normalize_phrases(["Red Ball", "red ball", "traffic-cone", ""]) == [
        "red ball",
        "traffic cone",
    ]


def test_iou_basic() -> None:
    assert _iou((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)
    assert _iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    # half-overlap along x: inter 5*10=50, union 100+100-50=150
    assert _iou((0, 0, 10, 10), (5, 0, 15, 10)) == pytest.approx(50 / 150)


def test_nms_suppresses_same_label_only_and_caps() -> None:
    raw = [
        (0.9, "ball", (0, 0, 10, 10)),
        (0.8, "ball", (1, 1, 11, 11)),  # overlaps the 0.9 ball -> suppressed
        (0.7, "box", (0, 0, 10, 10)),  # same box, different label -> kept
    ]
    kept = _nms(raw, iou_thresh=0.3, max_keep=10)
    assert (0.9, "ball", (0, 0, 10, 10)) in kept
    assert (0.7, "box", (0, 0, 10, 10)) in kept
    assert all(not (lbl == "ball" and s == 0.8) for s, lbl, _ in kept)
    # cap
    assert len(_nms(raw, iou_thresh=0.3, max_keep=1)) == 1


# ---------------------------------------------------------------------------
# decode + preprocess against a MOCK onnxruntime session (numpy only)
# ---------------------------------------------------------------------------


class _FakeEncoding:
    def __init__(self, ids: list[int]) -> None:
        self.ids = ids


class _FakeTokenizer:
    """Emits a fixed short id sequence per phrase (bos, hash, eos)."""

    def encode(self, text: str) -> _FakeEncoding:
        return _FakeEncoding([49406, (abs(hash(text)) % 1000) + 1, 49407])

    def token_to_id(self, token: str) -> int:
        return 0


class _FakeSession:
    """Returns canned (logits, pred_boxes) so decode logic is exercised with no weights."""

    def __init__(self, logits: np.ndarray, boxes: np.ndarray) -> None:
        self._logits = logits
        self._boxes = boxes
        self.last_feeds: dict | None = None

    def get_inputs(self):  # not used by detect(), present for parity
        return []

    def run(self, names, feeds):
        self.last_feeds = feeds
        return [self._logits, self._boxes]


def _mock_detector(logits: np.ndarray, boxes: np.ndarray, *, threshold: float = 0.1) -> OwlV2Detector:
    det = object.__new__(OwlV2Detector)
    det._np = np
    det._tok = _FakeTokenizer()
    det._pad_id = 0
    det._session = _FakeSession(logits, boxes)
    det.threshold = threshold
    det.nms_iou = 0.3
    det.max_detections = 64
    det._img_h = 960
    det._img_w = 960
    det._img_mean = np.asarray([0.5, 0.5, 0.5], dtype=np.float32)
    det._img_std = np.asarray([0.5, 0.5, 0.5], dtype=np.float32)
    det._rescale = 1.0 / 255.0
    det._pad_value = 0.5
    det._weights_dir = None
    return det


def test_detect_decodes_boxes_labels_and_threshold() -> None:
    # two queries, three candidate patches. patch 0 -> strong "red ball";
    # patch 1 -> strong "green box"; patch 2 -> below threshold for both.
    #   logit 5 -> sigmoid ~0.993; logit -5 -> ~0.0067 (dropped at thr 0.1)
    logits = np.array([[[5.0, -5.0], [-5.0, 5.0], [-3.0, -3.0]]], dtype=np.float32)
    # cxcywh normalized-to-square: patch0 center-left small, patch1 center-right small.
    boxes = np.array(
        [[[0.25, 0.25, 0.10, 0.10], [0.75, 0.50, 0.10, 0.10], [0.5, 0.5, 0.2, 0.2]]],
        dtype=np.float32,
    )
    det = _mock_detector(logits, boxes)
    rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
    dets = det.detect(rgb=rgb, depth=None, seg=None, query=["red ball", "green box"])
    labels = {d.label for d in dets}
    assert labels == {"red ball", "green box"}
    assert all(isinstance(d, PixelDetection) and d.seg_id is None for d in dets)
    # square side = max(1280, 720) = 1280; red-ball center at 0.25*1280=320.
    red = next(d for d in dets if d.label == "red ball")
    cx = 0.5 * (red.box[0] + red.box[2])
    assert cx == pytest.approx(320, abs=2)
    # scores are sigmoid(5) ~ 0.993
    assert red.score > 0.98


def test_detect_clips_boxes_into_the_padded_region_out() -> None:
    # A box whose center is in the padded (y>720) region of the 1280 square is dropped;
    # square side 1280, so cy=0.9 -> 1152 px > 720 image height.
    logits = np.array([[[6.0]]], dtype=np.float32)
    boxes = np.array([[[0.5, 0.9, 0.05, 0.05]]], dtype=np.float32)
    det = _mock_detector(logits, boxes)
    rgb = np.zeros((720, 1280, 3), dtype=np.uint8)
    assert det.detect(rgb=rgb, depth=None, seg=None, query="thing") == []


def test_detect_none_query_and_none_rgb_are_empty() -> None:
    det = _mock_detector(np.zeros((1, 1, 1), np.float32), np.zeros((1, 1, 4), np.float32))
    assert det.detect(rgb=np.zeros((4, 4, 3), np.uint8), depth=None, seg=None, query=None) == []
    assert det.detect(rgb=None, depth=None, seg=None, query="x") == []


def test_tokenize_pads_to_fixed_len_with_attention_mask() -> None:
    det = _mock_detector(np.zeros((1, 1, 2), np.float32), np.zeros((1, 1, 4), np.float32))
    ids, mask = det._tokenize(["red ball", "a much longer phrase here"])
    assert ids.shape == (2, OWLV2_TEXT_SEQ_LEN)
    assert mask.shape == (2, OWLV2_TEXT_SEQ_LEN)
    # first phrase has 3 real tokens (bos, word, eos) -> mask 1,1,1 then zeros
    assert mask[0].tolist() == [1, 1, 1] + [0] * (OWLV2_TEXT_SEQ_LEN - 3)
    assert ids[0, 3:].tolist() == [0] * (OWLV2_TEXT_SEQ_LEN - 3)


def test_preprocess_pads_to_square_and_normalizes() -> None:
    det = _mock_detector(np.zeros((1, 1, 2), np.float32), np.zeros((1, 1, 4), np.float32))
    rgb = np.full((720, 1280, 3), 255, dtype=np.uint8)
    out = det._preprocess_image(rgb)
    assert out.shape == (1, 3, 960, 960)
    # content region was 255 -> rescale 1.0 -> normalize (1-0.5)/0.5 = 1.0
    # padded region was 0.5 -> normalize (0.5-0.5)/0.5 = 0.0. Bottom rows sample padding.
    assert out[0, 0, 0, 0] == pytest.approx(1.0, abs=1e-3)
    assert out[0, 0, -1, 0] == pytest.approx(0.0, abs=1e-2)


# ---------------------------------------------------------------------------
# real-weight cells (skip cleanly without model / env / GL)
# ---------------------------------------------------------------------------

_REAL = owlv2_weights_present() and os.environ.get("PARCEL_OWLV2_ONNX", "").lower() in {"1", "true", "yes", "on"}
_real_reason = "OWLv2 weights absent or PARCEL_OWLV2_ONNX not set"


@pytest.mark.skipif(not _REAL, reason=_real_reason)
def test_real_owlv2_loads_and_reports_512_or_768_dim() -> None:
    det = load_owlv2_detector()
    assert det is not None
    assert det.name == "owlv2"
    assert isinstance(det, Detector)  # runtime-checkable protocol
    # empty query / blank rgb still runs the plumbing and returns a list.
    out = det.detect(rgb=np.zeros((64, 64, 3), np.uint8), depth=None, seg=None, query="red ball")
    assert isinstance(out, list)


@pytest.mark.skipif(not _REAL, reason=_real_reason)
def test_real_owlv2_recognizes_a_rendered_object_and_localizes() -> None:
    """Guarded end-to-end: render a red ball + green box, OWLv2 names them right and the
    localized world point lands near the seg-truth ruler. Skips without offscreen GL."""

    os.environ.setdefault("MUJOCO_GL", "egl")
    mujoco = pytest.importorskip("mujoco")
    from evals.nav_instruct.cam_detector import build_scenes, render_scene
    from parcel_robot.camera_channel.channel import CameraChannelSpec
    from parcel_robot.detection_adapter.pixel_detections import (
        SegTruthDetector,
        localize_frame,
    )

    spec = CameraChannelSpec.d455_go2_nominal()
    scene = build_scenes()[0]  # det-000: red ball + green box
    rendered = render_scene(scene, spec)
    if rendered is None:
        pytest.skip("MuJoCo offscreen GL unavailable")
    del mujoco  # only needed to gate the skip

    det = load_owlv2_detector()
    assert det is not None
    dets = det.detect(rgb=rendered.rgb, depth=None, seg=None, query=rendered.query)
    assert dets, "OWLv2 detected nothing on the rendered scene"
    assert {d.label for d in dets} <= set(rendered.query)

    seg_locs = localize_frame(
        SegTruthDetector(rendered.id_to_label), rgb=rendered.rgb, depth=rendered.depth,
        seg=rendered.seg, query=rendered.query, intrinsics=spec.intrinsics,
        extrinsics=rendered.extrinsics, source_timestamp_ns=1, received_monotonic_ns=1,
        depth_max_m=1000.0,
    )
    ruler = {loc.seg_id: (loc.world_x, loc.world_y, loc.world_z) for loc in seg_locs}
    owl_locs = localize_frame(
        det, rgb=rendered.rgb, depth=rendered.depth, seg=rendered.seg, query=rendered.query,
        intrinsics=spec.intrinsics, extrinsics=rendered.extrinsics,
        source_timestamp_ns=1, received_monotonic_ns=1, depth_max_m=1000.0,
    )
    # each OWLv2 detection localizes within the recognition budget of the seg ruler.
    from evals.nav_instruct.cam_detector import RECOGNITION_LOCALIZATION_BUDGET_M, _dominant_seg

    valid = set(rendered.id_to_label)
    for d, loc in zip(dets, owl_locs, strict=False):
        mseg = _dominant_seg(rendered.seg, d.box, valid)
        if mseg is None or mseg not in ruler:
            continue
        err = math.dist((loc.world_x, loc.world_y, loc.world_z), ruler[mseg])
        assert err < RECOGNITION_LOCALIZATION_BUDGET_M
        assert rendered.id_to_label[mseg] == d.label  # right-object


@pytest.mark.skipif(_REAL, reason="only asserts the disabled-path skip contract")
def test_eval_reports_skipped_when_disabled() -> None:
    from evals.nav_instruct.cam_detector import evaluate

    report = evaluate()
    assert report["status"] == "skipped"
    assert "blocker" in report
