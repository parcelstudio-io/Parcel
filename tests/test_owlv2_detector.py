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

from parcel_robot.detection_adapter.owlv2_onnx import (
    FAST_PREPROCESS_ENV,
    OWLV2_TEXT_SEQ_LEN,
    SAFETY_RELEVANT_LABELS,
    SOURCE_MAX_EDGE_ENV,
    OwlV2Detector,
    _iou,
    _nms,
    _normalize_phrases,
    fast_preprocess_enabled,
    load_owlv2_detector,
    onnx_enabled,
    owlv2_weights_present,
    resolve_owlv2_provider,
    source_max_edge,
)
from parcel_robot.detection_adapter.pixel_detections import Detector, PixelDetection
from parcel_robot.perception.contention import PerceptionContentionGuard
from parcel_robot.perception.providers import PROVIDER_CPU_INT8, PROVIDER_CUDA_FP16

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
# PG-1 — preprocessing: what is bit-identical, and what is honestly NOT
# ---------------------------------------------------------------------------

#: Real camera resolutions plus adversarial shapes. The 640x480 / 320x240 /
#: 641x361 rows matter: their long edge is under 960, so the model UP-samples and
#: the content/pad seam does not land on an output-pixel boundary — the case the
#: fast path must detect and decline.
_PREPROCESS_SHAPES = [
    (720, 1280, 3),   # D455 nominal — the resolution that actually ships
    (1080, 1920, 3),  # 1080p
    (480, 640, 3),    # up-sampled: seam straddles
    (240, 320, 3),    # up-sampled: seam straddles
    (361, 641, 3),    # odd, up-sampled
    (541, 961, 3),    # odd, barely down-sampled
    (1000, 1000, 3),  # already square
    (960, 960, 3),    # exactly the model input
    (64, 64, 3),      # tiny square
    (100, 37, 3),     # extreme portrait
    (37, 100, 3),     # extreme landscape
    (720, 1280, 4),   # RGBA input (alpha dropped)
]


def _preprocess_shell() -> OwlV2Detector:
    """A detector with ONLY preprocessing state — no session, no weights, no ORT."""

    det = object.__new__(OwlV2Detector)
    det._np = np
    det._img_h = 960
    det._img_w = 960
    det._img_mean = np.asarray([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
    det._img_std = np.asarray([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
    det._rescale = 1.0 / 255.0
    det._pad_value = 0.5
    return det


def _image(shape: tuple[int, int, int], seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 256, shape, dtype=np.uint8)


@pytest.mark.parametrize("shape", _PREPROCESS_SHAPES)
def test_the_fast_preprocess_is_bit_identical_to_the_reference(shape) -> None:
    """The whole justification for the fast path: the model sees the SAME tensor.

    Not "close", not "within tolerance" — ``np.array_equal`` on the float32
    tensor. If this ever needs a tolerance, the optimisation has become a
    behaviour change and must be re-argued as one.
    """

    det = _preprocess_shell()
    img = _image(shape, seed=hash(shape) % 1000)
    reference = det._preprocess_reference(img)
    fast = det._preprocess_fast(img)
    assert fast.shape == (1, 3, 960, 960)
    assert fast.dtype == reference.dtype == np.float32
    assert np.array_equal(fast, reference), (
        f"{shape}: fast preprocess drifted; max|delta|="
        f"{np.abs(fast.astype(np.float64) - reference.astype(np.float64)).max()}"
    )


def test_the_fast_path_declines_exactly_when_the_seam_would_straddle() -> None:
    """The guard is not decorative: it is False precisely for the up-sampled shapes.

    A seam check that returned True everywhere would still pass the bit-identity
    test above (the fallback would simply never fire) *only* because it is checked
    here that the two branches are actually both exercised.
    """

    det = _preprocess_shell()

    def clean(h: int, w: int) -> bool:
        side = max(h, w)
        return det._seam_is_clean(h, w, side, 960 * h // side, 960 * w // side)

    # down-sampling from a >=960 long edge with an exact boundary: fast path lives
    assert clean(720, 1280) is True
    assert clean(1080, 1920) is True
    assert clean(1000, 1000) is True
    assert clean(960, 960) is True
    assert clean(64, 64) is True  # square: no seam at all
    # up-sampling: the boundary output pixel legitimately blends content with pad
    assert clean(480, 640) is False
    assert clean(240, 320) is False
    assert clean(361, 641) is False
    assert clean(37, 100) is False


def test_both_preprocess_branches_are_exercised_by_the_shape_matrix() -> None:
    """Guards the test above from becoming vacuous if the matrix ever shrinks."""

    det = _preprocess_shell()
    outcomes = set()
    for h, w, _ in _PREPROCESS_SHAPES:
        side = max(h, w)
        outcomes.add(det._seam_is_clean(h, w, side, 960 * h // side, 960 * w // side))
    assert outcomes == {True, False}


def test_the_separable_resize_is_bit_identical_to_the_reference_resize() -> None:
    det = _preprocess_shell()
    rng = np.random.default_rng(5)
    for in_shape, out in (
        ((720, 1280, 3), (540, 960)),
        ((1280, 1280, 3), (960, 960)),
        ((97, 53, 3), (960, 960)),
        ((960, 960, 3), (480, 480)),
    ):
        arr = rng.random(in_shape, dtype=np.float32)
        assert np.array_equal(
            det._bilinear_resize(arr, *out), det._bilinear_resize_separable(arr, *out)
        ), f"{in_shape} -> {out}"


def test_source_downscale_is_NOT_bit_identical_and_is_off_by_default() -> None:
    """The inherited claim, tested rather than trusted.

    PG-1 arrived with "halving the input edge is a free 2.8x with bit-identical
    tensors". Against this module's own preprocessor that is FALSE, and this test
    is the record of it: the downscale genuinely changes what the model sees. It
    is therefore an explicit, default-off, documented-lossy knob — and if someone
    ever flips its default to on, this test tells them exactly what they bought.
    """

    det = _preprocess_shell()
    det.fast_preprocess = True
    det.source_max_edge = 0
    img = _image((720, 1280, 3), seed=42)

    full = det._preprocess_image(img)
    det.source_max_edge = 640
    halved = det._preprocess_image(img)

    assert not np.array_equal(halved, full), (
        "if this ever passes, the downscale has become lossless and the module "
        "docstring's central caveat must be rewritten"
    )
    delta = np.abs(halved.astype(np.float64) - full.astype(np.float64))
    assert delta.max() > 0.1, "the change is material, not a rounding artefact"
    assert (halved != full).sum() > 10_000


def test_the_downscale_leaves_a_source_already_within_the_budget_alone() -> None:
    det = _preprocess_shell()
    det.fast_preprocess = True
    img = _image((360, 640, 3), seed=7)
    det.source_max_edge = 0
    untouched = det._preprocess_image(img)
    det.source_max_edge = 640  # long edge is already 640
    assert np.array_equal(det._preprocess_image(img), untouched)


def test_the_preprocess_knob_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(FAST_PREPROCESS_ENV, raising=False)
    monkeypatch.delenv(SOURCE_MAX_EDGE_ENV, raising=False)
    assert fast_preprocess_enabled() is True, "the lossless path is on by default"
    assert source_max_edge() == 0, "the LOSSY path is off by default"

    monkeypatch.setenv(FAST_PREPROCESS_ENV, "0")
    assert fast_preprocess_enabled() is False
    monkeypatch.setenv(SOURCE_MAX_EDGE_ENV, "640")
    assert source_max_edge() == 640
    # a malformed value disables rather than guesses a resolution
    monkeypatch.setenv(SOURCE_MAX_EDGE_ENV, "wide")
    assert source_max_edge() == 0
    monkeypatch.setenv(SOURCE_MAX_EDGE_ENV, "-4")
    assert source_max_edge() == 0


def test_class_defaults_keep_the_lossy_knob_off_for_shells() -> None:
    """``object.__new__`` shells must not silently inherit a downscale."""

    assert OwlV2Detector.source_max_edge == 0
    assert OwlV2Detector.fast_preprocess is True
    assert OwlV2Detector.provider == PROVIDER_CPU_INT8


# ---------------------------------------------------------------------------
# PG-1 — provider plumbing behind the unchanged Detector protocol
# ---------------------------------------------------------------------------


def test_the_detector_resolves_through_the_shared_fallback_order(tmp_path) -> None:
    (tmp_path / "model_int8.onnx").write_bytes(b"x")
    (tmp_path / "model_fp16.onnx").write_bytes(b"x")

    cpu = resolve_owlv2_provider(
        tmp_path, available_execution_providers=("CPUExecutionProvider",)
    )
    assert cpu.selected == PROVIDER_CPU_INT8
    assert cpu.model_file.name == "model_int8.onnx"

    gpu = resolve_owlv2_provider(
        tmp_path,
        available_execution_providers=("CUDAExecutionProvider", "CPUExecutionProvider"),
    )
    assert gpu.selected == PROVIDER_CUDA_FP16
    assert gpu.model_file.name == "model_fp16.onnx"


def test_an_fp16_only_install_counts_as_weights_present(tmp_path) -> None:
    (tmp_path / "tokenizer.json").write_text("{}")
    assert owlv2_weights_present(tmp_path) is False
    (tmp_path / "model_fp16.onnx").write_bytes(b"x")
    assert owlv2_weights_present(tmp_path) is True


def test_a_pinned_but_unavailable_provider_makes_the_loader_return_none(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse, do not degrade — and still return None rather than raising."""

    (tmp_path / "tokenizer.json").write_text("{}")
    (tmp_path / "model_int8.onnx").write_bytes(b"x")
    monkeypatch.setenv("PARCEL_OWLV2_ONNX", "1")
    monkeypatch.setenv("PARCEL_OWLV2_DIR", str(tmp_path))
    monkeypatch.setenv("PARCEL_PERCEPTION_PROVIDER", "cuda_fp16")
    assert load_owlv2_detector() is None


# ---------------------------------------------------------------------------
# PG-1 item 4 — the safety lease, wired into the detector
# ---------------------------------------------------------------------------


def test_a_person_query_holds_a_lease_for_the_duration_of_the_inference() -> None:
    """A scene description cannot START underneath a person query."""

    guard = PerceptionContentionGuard()
    det = _mock_detector(
        np.array([[[-9.0]]], dtype=np.float32), np.zeros((1, 1, 4), np.float32)
    )
    det.guard = guard
    det.safety_labels = SAFETY_RELEVANT_LABELS

    seen: list[bool] = []
    original = det._detect_unguarded

    def spy(rgb, phrases):
        seen.append(guard.try_admit_generation(estimated_ms=500.0).admitted)
        return original(rgb, phrases)

    det._detect_unguarded = spy
    rgb = np.zeros((64, 64, 3), np.uint8)

    det.detect(rgb=rgb, depth=None, seg=None, query="person")
    assert seen == [False], "a person query must block generation while it runs"

    seen.clear()
    det.detect(rgb=rgb, depth=None, seg=None, query="lamppost")
    assert seen == [True], "a non-safety query must not block speech"

    # and the lease never leaks past the call
    assert guard.active_leases() == ()
    assert guard.try_admit_generation(estimated_ms=500.0).admitted is True


def test_safety_relevance_matches_whole_words_across_the_query_list() -> None:
    det = _mock_detector(np.zeros((1, 1, 1), np.float32), np.zeros((1, 1, 4), np.float32))
    det.safety_labels = SAFETY_RELEVANT_LABELS
    assert det.is_safety_relevant(["person"]) is True
    assert det.is_safety_relevant(["a person standing"]) is True
    assert det.is_safety_relevant(["lamppost", "pedestrian"]) is True
    assert det.is_safety_relevant(["lamppost", "tree"]) is False
    # substring must NOT match: "personal locker" is not a person
    assert det.is_safety_relevant(["personal locker"]) is False


def test_the_safety_label_set_covers_the_person_yield_vocabulary() -> None:
    assert {"person", "pedestrian", "human", "owner"} <= SAFETY_RELEVANT_LABELS


def test_a_detector_without_a_guard_still_detects() -> None:
    """The guard is additive: removing it degrades scheduling, never detection."""

    logits = np.array([[[5.0]]], dtype=np.float32)
    boxes = np.array([[[0.25, 0.25, 0.1, 0.1]]], dtype=np.float32)
    det = _mock_detector(logits, boxes)
    det.guard = None
    out = det.detect(rgb=np.zeros((720, 1280, 3), np.uint8), depth=None, seg=None, query="person")
    assert len(out) == 1 and out[0].label == "person"


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
