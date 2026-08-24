"""P3 storefront / OCR sim slice — fixtures, synthetic RGB, fake OCR, ingest."""

from __future__ import annotations

import numpy as np
import pytest

from parcel_robot.camera_channel.channel import assert_nominal_d455_contract
from parcel_robot.camera_channel.d455 import D455_HEIGHT_PX, D455_WIDTH_PX
from parcel_robot.contracts.v1 import DetectionMsg
from parcel_robot.instructnav.memory import SemanticMemory2D
from parcel_robot.storefront import DOES_NOT_PROVE
from parcel_robot.storefront.fixtures import load_manifest
from parcel_robot.storefront.ingest import (
    ingest_ocr_hits,
    ocr_hits_to_detections,
    recall_storefront,
)
from parcel_robot.storefront.ocr import (
    UNVERIFIED_PADDLE_OCR,
    FakeOcrEngine,
    PaddleOcrEngine,
    open_ocr_engine,
    paddleocr_available,
    texts_match,
)
from parcel_robot.storefront.placards import normalize_sign_text, render_placard_rgb, write_png_rgb
from parcel_robot.storefront.render import StorefrontSyntheticAdapter, composite_storefront_frame


def test_manifest_loads_and_materializes_placards(tmp_path) -> None:
    # Copy minimal manifest into tmp and ensure PNG generation.
    import shutil

    from parcel_robot.storefront.fixtures import resolve_storefront_root

    src = resolve_storefront_root()
    dest = tmp_path / "storefronts"
    dest.mkdir()
    shutil.copy2(src / "manifest.yaml", dest / "manifest.yaml")
    manifest = load_manifest(root=dest, ensure_placards=True)
    assert manifest.schema_version == 1
    assert len(manifest.storefronts) >= 3
    assert manifest.does_not_prove
    for fixture in manifest.storefronts:
        assert fixture.placard_path.is_file()
        assert fixture.placard_path.stat().st_size > 64
    nike = manifest.by_id("nike_store")
    assert nike.expected_text == "NIKE"
    assert 0.0 <= nike.roi_norm[0] < nike.roi_norm[2] <= 1.0


def test_placard_png_roundtrip_and_readable_glyphs() -> None:
    rgb = render_placard_rgb("NIKE", width=320, height=96)
    assert rgb.shape == (96, 320, 3)
    assert rgb.dtype == np.uint8
    # Foreground pixels exist (not a flat background).
    assert int(rgb.max()) == 255
    assert not np.all(rgb == rgb[0, 0])


def test_composite_frame_is_d455_sized_with_signage() -> None:
    manifest = load_manifest()
    frame, fixtures = composite_storefront_frame(manifest)
    assert frame.shape == (D455_HEIGHT_PX, D455_WIDTH_PX, 3)
    assert len(fixtures) == len(manifest.storefronts)
    # ROI centers should differ from sky blue backdrop.
    for fixture in fixtures:
        x0, y0, x1, y1 = fixture.roi_norm
        cx = int(0.5 * (x0 + x1) * D455_WIDTH_PX)
        cy = int(0.5 * (y0 + y1) * D455_HEIGHT_PX)
        assert not np.allclose(frame[cy, cx], (70, 110, 160))


def test_storefront_adapter_capture_envelope_contract() -> None:
    adapter = StorefrontSyntheticAdapter(storefront_ids=("nike_store",))
    assert_nominal_d455_contract(adapter.spec)
    envelope = adapter.capture(source_timestamp_ns=1_000, sequence=1)
    assert envelope.color.width_px == D455_WIDTH_PX
    assert envelope.color.height_px == D455_HEIGHT_PX
    assert envelope.color.mount_height_m == pytest.approx(0.35)
    color = adapter.get_color()
    assert color.shape == (D455_HEIGHT_PX, D455_WIDTH_PX, 3)
    assert adapter.last_capture is not None
    assert adapter.last_capture.fixtures[0].id == "nike_store"
    assert any("wild storefront" in s.lower() or "synthetic" in s.lower() for s in DOES_NOT_PROVE)


def test_fake_ocr_reads_fixture_metadata_not_pixels() -> None:
    adapter = StorefrontSyntheticAdapter()
    adapter.capture(source_timestamp_ns=2_000, sequence=2)
    engine = FakeOcrEngine()
    hits = engine.recognize(
        adapter.get_color(),
        fixtures=adapter.last_capture.fixtures,  # type: ignore[union-attr]
        sequence=2,
    )
    assert len(hits) == 3
    texts = {h.text for h in hits}
    assert "NIKE" in texts
    assert "BLUE BOTTLE" in texts
    assert "PARCEL CAFE" in texts
    assert all(h.backend == "fake" for h in hits)
    assert all(h.bearing_rad is not None and h.range_m is not None for h in hits)


def test_open_ocr_engine_defaults_to_fake_without_paddle() -> None:
    engine, kind = open_ocr_engine(prefer="fake")
    assert kind == "fake"
    assert isinstance(engine, FakeOcrEngine)
    if not paddleocr_available():
        engine2, kind2 = open_ocr_engine(prefer="auto")
        assert kind2 == "fake"
        assert isinstance(engine2, FakeOcrEngine)


def test_paddle_path_is_unverified_and_optional() -> None:
    assert UNVERIFIED_PADDLE_OCR
    assert any("UNVERIFIED" in s for s in UNVERIFIED_PADDLE_OCR)
    if paddleocr_available():
        engine = PaddleOcrEngine()
        assert engine.kind == "paddleocr"
    else:
        with pytest.raises(ImportError, match="paddleocr"):
            PaddleOcrEngine()


def test_ocr_ingest_to_detection_and_semantic_memory() -> None:
    adapter = StorefrontSyntheticAdapter(storefront_ids=("nike_store", "parcel_cafe"))
    adapter.capture(source_timestamp_ns=5_000, sequence=5)
    hits = FakeOcrEngine().recognize(
        adapter.get_color(),
        fixtures=adapter.last_capture.fixtures,  # type: ignore[union-attr]
        sequence=5,
    )
    detections = ocr_hits_to_detections(hits, received_monotonic_ns=5_000, sequence=5)
    assert len(detections) == 2
    assert all(isinstance(d, DetectionMsg) for d in detections)
    assert all(d.class_id.startswith("storefront:") for d in detections)
    assert all(d.envelope.source.startswith("sim.storefront.ocr.") for d in detections)

    memory = SemanticMemory2D(decay_half_life_s=1e9)
    ingest_ocr_hits(
        memory,
        hits,
        robot_x=0.0,
        robot_y=0.0,
        robot_yaw_rad=0.0,
        now_s=10.0,
        received_monotonic_ns=5_000,
        sequence=5,
    )
    nike = recall_storefront(memory, "nike", now_s=10.0)
    assert nike
    assert nike[0].confidence >= 0.9
    # Map centroid roughly ahead at range_m along bearing 0.
    assert nike[0].x == pytest.approx(4.5, abs=0.05)
    cafe = recall_storefront(memory, "parcel cafe", now_s=10.0)
    assert cafe
    assert cafe[0].y != 0.0  # non-zero bearing


def test_texts_match_normalization() -> None:
    assert texts_match("Nike", "NIKE")
    assert texts_match("BLUE BOTTLE", "blue  bottle")
    assert normalize_sign_text("  parcel cafe ") == "PARCEL CAFE"
    assert texts_match("PARCEL CAFE", "PARCEL CAFE")


def test_write_png_roundtrip(tmp_path) -> None:
    rgb = render_placard_rgb("ABC", width=128, height=48)
    path = write_png_rgb(tmp_path / "abc.png", rgb)
    assert path.is_file()
    from parcel_robot.storefront.render import _read_png_rgb

    decoded = _read_png_rgb(path)
    assert decoded.shape == rgb.shape
    assert np.array_equal(decoded, rgb)


@pytest.mark.skipif(not paddleocr_available(), reason="paddleocr not installed (UNVERIFIED optional)")
def test_optional_paddle_ocr_on_synthetic_placard() -> None:
    """UNVERIFIED: only runs when paddleocr is installed; never required in CI."""

    rgb = render_placard_rgb("NIKE", width=640, height=160)
    # Pad into a larger frame so detectors have context.
    frame = np.full((480, 640, 3), 40, dtype=np.uint8)
    frame[160:320, :] = rgb
    engine = PaddleOcrEngine(min_score=0.3)
    hits = engine.recognize(frame, sequence=0)
    # Soft assertion — synthetic glyphs may or may not decode; never gate CI.
    assert isinstance(hits, tuple)
    if hits:
        assert any(texts_match("NIKE", h.text) or "NIKE" in h.text for h in hits)
