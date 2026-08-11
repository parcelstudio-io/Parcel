"""Additive T-cam cell: pixel candidates carry arrival-capable near-envelope metadata.

Card V-A closes B4 arrival on the pixel path by stamping the same near-envelope
field set city objects already carry (``radius_m`` from box angular width ×
depth / 2, plus ``stand_off_m`` / vicinity fields from
``object_near_envelope_m``). This standalone report proves that contract on a
deterministic fake backend — no frozen pack, no runtime wiring, no edit to
``cam_foundation.py`` / ``cam_detector.py``.

The live product-path arrival flip (``arrival=succeeded`` via
``candidate_source=pixel_detector``) is measured by
``scrum/20260809/task_12/b4_gate.py`` Mission A; this cell pins the metadata
geometry that makes that flip possible.

Usage::

    .parcel/bin/python -m evals.nav_instruct.cam_arrival
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from parcel_robot.camera_channel.channel import CameraChannelSpec
from parcel_robot.camera_channel.ingress import (
    PIXEL_SOURCE,
    CameraIngress,
    radius_m_from_box_depth,
)
from parcel_robot.detection_adapter.pixel_detections import PixelDetection
from parcel_robot.instructnav.scoring import object_near_envelope_m

TIER_ID = "T-cam-proxy-arrival"
DOES_NOT_PROVE = (
    (
        "Offline envelope stamping proves pixel candidates carry the city-object "
        "near-envelope field set; it does not prove open-vocab recognition or "
        "hardware D455 arrival."
    ),
    (
        "Live Mission-A arrival (b4_gate) is measured separately with real OWLv2 "
        "+ EGL; this cell is the additive metadata contract, not that live run."
    ),
)


class _FakeCaptureBackend:
    def __init__(self, rgb: np.ndarray, depth: np.ndarray) -> None:
        from types import SimpleNamespace

        self._buffers = SimpleNamespace(
            color_rgb8=rgb, depth_m_f32=depth, seg_u16=None
        )

    def capture(self, *, source_timestamp_ns, sequence, robot_x, robot_y, robot_yaw_rad):
        del source_timestamp_ns, sequence, robot_x, robot_y, robot_yaw_rad

    @property
    def last_buffers(self):
        return self._buffers

    def close(self) -> None:
        return None


class _FakeDetector:
    name = "fake_owlv2"

    def __init__(self, box: tuple[int, int, int, int], label: str = "red ball") -> None:
        self._box = box
        self._label = label

    def detect(self, *, rgb, depth, seg, query):
        del rgb, depth, seg, query
        return [PixelDetection(label=self._label, score=0.86, box=self._box, seg_id=None)]


def _fake_frame() -> tuple[np.ndarray, np.ndarray, tuple[int, int, int, int]]:
    spec = CameraChannelSpec.d455_go2_nominal()
    h, w = spec.intrinsics.height_px, spec.intrinsics.width_px
    rgb = np.zeros((h, w, 3), dtype=np.uint8)
    depth = np.full((h, w), np.inf, dtype=np.float32)
    # ~0.4 m sphere half-width at 3 m with fx≈644 → ~86 px half-side.
    u0, v0, u1, v1 = (554, 274, 726, 446)
    depth[v0:v1, u0:u1] = 3.0
    rgb[v0:v1, u0:u1] = (220, 30, 30)
    return rgb, depth, (u0, v0, u1, v1)


def evaluate_cells() -> dict[str, Any]:
    """Return deterministic JSON evidence that pixel candidates are arrival-ready."""

    spec = CameraChannelSpec.d455_go2_nominal()
    rgb, depth, box = _fake_frame()
    ingress = CameraIngress(
        backend=_FakeCaptureBackend(rgb, depth),
        detector=_FakeDetector(box),
        intrinsics=spec.intrinsics,
        mount=spec.mount,
        depth_min_m=spec.depth_min_m,
        depth_max_m=spec.depth_max_m - 1e-2,
    )
    ingress.set_query("red ball")
    ingress.set_pose(0.0, 0.0, 0.0)
    candidates = ingress.poll_once() or []
    assert len(candidates) == 1, "fake detector must emit one localized candidate"
    cand = candidates[0]
    meta = cand["metadata"]
    expected_r = radius_m_from_box_depth(box, 3.0, spec.intrinsics.fx)
    stand_off, minimum, vicinity = object_near_envelope_m(
        expected_r, label=str(cand["label"])
    )
    # Planning inset (approach.py): stand_off must land inside the verified band.
    arrival_r = float(meta["arrival_radius_m"])
    margin = 0.04  # StandOffEnvelope.stand_off_margin_m at Go2
    plan_lo = minimum + arrival_r + margin
    plan_hi = vicinity - (arrival_r + margin)
    stand_off_in_band = plan_lo - 1e-9 <= stand_off <= plan_hi + 1e-9
    return {
        "tier_id": TIER_ID,
        "candidate_source": cand["source"],
        "label": cand["label"],
        "confidence": cand["confidence"],
        "radius_m": meta["radius_m"],
        "expected_radius_m": round(expected_r, 4),
        "stand_off_m": meta["stand_off_m"],
        "minimum_vicinity_radius_m": meta["minimum_vicinity_radius_m"],
        "vicinity_radius_m": meta["vicinity_radius_m"],
        "stand_off_inside_planning_band": stand_off_in_band,
        "planning_band_m": [plan_lo, plan_hi],
        "envelope_matches_object_near_envelope_m": (
            math.isclose(meta["stand_off_m"], stand_off, abs_tol=1e-9)
            and math.isclose(meta["minimum_vicinity_radius_m"], minimum, abs_tol=1e-9)
            and math.isclose(meta["vicinity_radius_m"], vicinity, abs_tol=1e-9)
        ),
        "pixel_source_tag": cand["source"] == PIXEL_SOURCE,
        "does_not_prove": list(DOES_NOT_PROVE),
    }


def main() -> int:
    report = evaluate_cells()
    print(json.dumps(report, indent=2, sort_keys=True))
    ok = (
        report["pixel_source_tag"]
        and report["envelope_matches_object_near_envelope_m"]
        and report["stand_off_inside_planning_band"]
        and abs(report["radius_m"] - report["expected_radius_m"]) < 1e-3
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
