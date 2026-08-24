"""B2 gate: T-cam-foundation tier — localization error + right-object + byte-equal.

Proves the pixels->DetectionMsg pipeline geometry against MuJoCo-style
segmentation-truth (SegTruthDetector) over a frozen synthetic render pack, and
proves the tier is ADDITIVE: the frozen T0/T1 GT-source artifacts are
byte-identical and the process-default perception chain is untouched.

HONESTY (P0): geometry + localization + the DetectionMsg pipeline are proven;
real-texture recognition is NOT (that is B3 + hardware).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest

from evals.nav_instruct.cam_foundation import (
    LOCALIZATION_ERROR_BOUND_M,
    TIER_ID,
    Scene,
    build_pack,
    evaluate_pack,
    load_pack,
    load_scenes,
    pack_digest,
    render_scene,
)
from parcel_robot.camera_channel.d455 import d455_color_intrinsics
from parcel_robot.contracts.v1 import DetectionMsg
from parcel_robot.detection_adapter.pixel_detections import (
    SegTruthDetector,
    localize_frame,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# frozen pack integrity
# ---------------------------------------------------------------------------


def test_checked_in_pack_matches_a_fresh_generation() -> None:
    """The frozen pack is exactly what the seeded generator emits (no drift)."""

    stored = load_pack()
    fresh = build_pack()
    assert stored["digest"] == fresh["digest"]
    assert pack_digest(stored) == stored["digest"]
    assert stored["tier_id"] == TIER_ID
    assert stored["scenes"] == fresh["scenes"]


def test_pack_intrinsics_are_the_advertised_d455_contract() -> None:
    intr = load_pack()["intrinsics"]
    ref = d455_color_intrinsics().as_dict()
    assert intr == ref
    assert intr["fx"] == intr["fy"] == 644.0
    assert intr["cx"] == 640.0 and intr["cy"] == 360.0


# ---------------------------------------------------------------------------
# localization error + right-object (the two foundation metrics)
# ---------------------------------------------------------------------------


def test_localization_error_is_near_zero_by_construction() -> None:
    report = evaluate_pack()
    dist = report["localization_error_m"]
    assert dist["n"] >= 20
    # Pure pixel-quantization residual — sub-cm — not geometry error.
    assert dist["max_m"] < LOCALIZATION_ERROR_BOUND_M
    assert dist["p95_m"] < LOCALIZATION_ERROR_BOUND_M
    assert dist["mean_m"] < LOCALIZATION_ERROR_BOUND_M / 2.0


def test_right_object_and_recall_are_perfect_for_seg_truth() -> None:
    report = evaluate_pack()
    # SegTruthDetector is a perfect detector by construction: it never lands on
    # the wrong object and never misses the queried instance.
    assert report["right_object_rate"] == 1.0
    assert report["recall_mean"] == 1.0
    assert report["detector"] == "seg_truth"
    assert report["frozen_baseline"] is False
    assert report["does_not_prove"]


def test_report_is_deterministic() -> None:
    assert evaluate_pack() == evaluate_pack()


def test_emitted_messages_are_contract_valid_detection_msgs() -> None:
    intr = d455_color_intrinsics()
    scene = load_scenes()[0]
    seg, depth = render_scene(scene, intr)
    detector = SegTruthDetector(scene.id_to_label())
    localized = localize_frame(
        detector,
        rgb=None,
        depth=depth,
        seg=seg,
        query=scene.query,
        intrinsics=intr,
        extrinsics=scene.extrinsics(),
        source_timestamp_ns=1,
        received_monotonic_ns=1,
        depth_max_m=1000.0,
    )
    assert localized
    for loc in localized:
        assert isinstance(loc.message, DetectionMsg)
        # Contract round-trip: the emitted message survives serialize/parse.
        assert DetectionMsg.from_mapping(loc.message.as_dict()) == loc.message
        assert loc.message.class_id == scene.query
        assert loc.message.range_m > 0.0
        # A per-detection covariance rides alongside (D2/D4 fuse it).
        assert loc.sigma_range_m >= 0.0
        assert loc.covariance_xy[0][1] == loc.covariance_xy[1][0]


def test_zscore_reject_holds_localization_under_depth_outliers() -> None:
    """With injected gross depth outliers, the world point stays on the object."""

    intr = d455_color_intrinsics()
    scene = load_scenes()[2]
    seg, depth = render_scene(scene, intr, inject_depth_outliers=True)
    # Confirm the pack actually seeded outliers we are rejecting.
    assert depth.max() > 6.0
    detector = SegTruthDetector(scene.id_to_label())
    localized = localize_frame(
        detector, rgb=None, depth=depth, seg=seg, query=scene.query,
        intrinsics=intr, extrinsics=scene.extrinsics(),
        source_timestamp_ns=1, received_monotonic_ns=1, depth_max_m=1000.0,
    )
    truth = {t.seg_id: t for t in scene.targets}
    assert localized
    for loc in localized:
        tgt = truth[loc.seg_id]
        err = float(
            np.linalg.norm(
                np.array([loc.world_x, loc.world_y, loc.world_z]) - np.array(tgt.position)
            )
        )
        assert err < LOCALIZATION_ERROR_BOUND_M


# ---------------------------------------------------------------------------
# additive / opt-in: frozen baselines byte-equal, mission path untouched
# ---------------------------------------------------------------------------


#: sha256 of the frozen T0/T1 GT-source artifacts captured when the T-cam
#: foundation landed. The tier is additive — it adds only NEW files — so these
#: must never move. Any diff here means the foundation dirtied a frozen pack.
_FROZEN_DIGESTS: dict[str, str] = {
    "evals/nav_instruct/results/nav-instruct-v1-baseline-v3-20260809T161252Z.json":
        "83a226fb06fb8b7394c82720a84f577d79070e07a2945b80d980bb330c7493db",
    "evals/nav_instruct/results/nav-instruct-v1-candidate-v3-20260809T161335Z.json":
        "aa2fa493fd10b7c0ae15bebad612533a306a4b4eec0a149ddca190ca2c656d51",
    "evals/nav_instruct/episodes/v3/manifest.json":
        "eb1289e9723e008336b33bff83f2e4c9a91e07d1e6552866f6ede52da7f57858",
    "evals/nav_instruct/episodes/v2/manifest.json":
        "e45c92a3f2accffd9fd437e14777c78a442c709059874ddbbbeba0fb7444663e",
    "evals/nav_instruct/episodes/v1/manifest.json":
        "b182db4c6bc8ffa1fc4e8c4040b7ab07349ae848949c8a98390ddca3427ab323",
}


@pytest.mark.parametrize("relpath,digest", sorted(_FROZEN_DIGESTS.items()))
def test_frozen_gt_source_artifacts_are_byte_identical(relpath: str, digest: str) -> None:
    actual = hashlib.sha256((REPO_ROOT / relpath).read_bytes()).hexdigest()
    assert actual == digest, f"{relpath} moved — T-cam-foundation must be additive"


def test_tier_does_not_install_a_perception_chain() -> None:
    """Importing/running the foundation tier leaves the mission ingress at T0.

    The additive guarantee at the code level: nothing here touches the
    process-default perception chain, so a live run's T0 pass-through is
    unchanged (the E1 card is what wires a T-cam NoiseTier onto the path).
    """

    import evals.nav_instruct.cam_foundation  # noqa: F401
    from parcel_robot.detection_adapter.perception_chain import active_perception_chain

    evaluate_pack()
    chain = active_perception_chain()
    assert chain.tier.name == "T0"
    assert chain.tier.passthrough is True


def test_pack_scenes_have_clean_non_overlapping_targets() -> None:
    scenes = load_scenes()
    assert len(scenes) >= 20
    for scene in scenes:
        assert isinstance(scene, Scene)
        assert len({t.seg_id for t in scene.targets}) == len(scene.targets)
        assert any(t.is_query for t in scene.targets)
