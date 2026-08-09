"""Metamorphic relations for NAV_INSTRUCT (eval instrument 3).

A metamorphic relation is a label-free oracle: it does not need to know what the
right answer is, only that two runs must relate to each other in a stated way.
That is exactly what this stack lacks — a 25-episode minival with 1–4 successes
gives almost no signal, but *every* episode can carry an MR.

Two relations live here.

**Rigid-transform equivariance.** Mirror the scene and the episode in ``y``, or
rotate both 90°, and the trajectory must be the same trajectory transformed.
The transform is applied to the MJCF itself (every ``pos``, and box ``size``
under a rotation) and to the episode's start pose and goal region — a rigid
transform preserves every distance a band or radius encodes, so bands and radii
are carried through unchanged. This is the strongest single fault detector in
the robot metamorphic-testing literature because almost every frame, sign and
axis bug breaks it.

**Detector-dropout monotonicity.** Raise the detector's miss probability and
performance must not improve. Directional, not exact: it catches the class of
bug where more noise accidentally helps (a threshold with the wrong sign, an
oracle leak that a dropout mask reveals).

Tolerance, and why it is not exact equality
-------------------------------------------
The plan specifies a Wasserstein/z-test against N≈8 repeat variability, because
exact equality would false-alarm on the reactive gate's nondeterminism. That
test is implemented here as :func:`equivariance_verdict`, and **measured** on
this harness (2026-08-07, N=8, ``go to the sidewalk``): the repeat spread has
mean **2.9e-5 m** and sd **1.9e-5 m**. So the runner is effectively but not
exactly deterministic, the z-test does have a scale, and a real violation lands
5 orders of magnitude outside it (the measured one scores z ≈ 1.6e5).

A floor is still applied on top of the z-test — :data:`EQUIVARIANCE_FLOOR_M`,
the robot's own footprint radius — because a z-test against a 2e-5 m sd would
otherwise call a centimetre of float noise in a 90° rotation a defect. A
discrepancy smaller than the robot is not a behavioural difference this
instrument can resolve. When the spread is exactly zero the z-test has no scale
at all and the floor decides alone; :func:`equivariance_verdict` says so in its
``detail`` rather than reporting a silent ``inf``. Both numbers are always
reported.
"""

from __future__ import annotations

import dataclasses
import math
import statistics
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.nav_instruct.generator import EpisodeSpec
from parcel_robot.instructnav.scoring import GoalRegion
from parcel_robot.robot_profile import DEFAULT_ROBOT_PROFILE

#: Named rigid transforms. ``identity`` is included so the harness can prove the
#: machinery is a no-op before it is trusted to detect anything.
TRANSFORMS: tuple[str, ...] = ("identity", "mirror_y", "rotate_90")

#: Below this, a discrepancy is not a behavioural difference this instrument can
#: resolve. It is the robot's own footprint radius, derived rather than typed.
EQUIVARIANCE_FLOOR_M = DEFAULT_ROBOT_PROFILE.footprint_radius_m

#: Repeats used to measure this harness's own run-to-run variability.
REPEAT_N = 8

#: z above which a discrepancy is a violation rather than variability.
Z_CRITICAL = 3.0


def transform_xy(name: str, x: float, y: float) -> tuple[float, float]:
    if name == "identity":
        return (float(x), float(y))
    if name == "mirror_y":
        return (float(x), -float(y))
    if name == "rotate_90":
        return (-float(y), float(x))
    raise ValueError(f"unknown transform: {name!r}")


def transform_yaw(name: str, yaw: float) -> float:
    if name == "identity":
        return float(yaw)
    if name == "mirror_y":
        return -float(yaw)
    if name == "rotate_90":
        return float(yaw) + math.pi / 2.0
    raise ValueError(f"unknown transform: {name!r}")


def swaps_box_axes(name: str) -> bool:
    """A 90° rotation exchanges a box's x and y half-extents."""

    return name == "rotate_90"


def transform_scene_xml(
    xml_text: str,
    name: str,
    *,
    source_dir: Path | None = None,
) -> str:
    """Apply a rigid transform to every element of a scene MJCF.

    Geom **names are preserved**, which is the point: ``sidewalk`` mirrored to
    the south side is still ``sidewalk``, so entity identity — the thing the
    semantic layer joins on — is invariant while every coordinate moves.

    ``source_dir`` re-roots the scene's relative ``include``/``meshdir`` paths
    to absolute ones, so a transformed copy can be written anywhere (a pytest
    ``tmp_path``) and still find the Go2 model.
    """

    root = ET.fromstring(xml_text)
    if source_dir is not None:
        for element in root.iter("include"):
            target = element.get("file")
            if target and not Path(target).is_absolute():
                element.set("file", str((source_dir / target).resolve()))
        for element in root.iter("compiler"):
            meshdir = element.get("meshdir")
            if meshdir and not Path(meshdir).is_absolute():
                element.set("meshdir", str((source_dir / meshdir).resolve()))
    for element in root.iter():
        pos = element.get("pos")
        if pos is not None:
            parts = pos.split()
            if len(parts) >= 2:
                x, y = transform_xy(name, float(parts[0]), float(parts[1]))
                rest = parts[2:]
                element.set("pos", " ".join([_fmt(x), _fmt(y), *rest]))
        size = element.get("size")
        if (
            size is not None
            and swaps_box_axes(name)
            and element.get("type") in {"box", "plane"}
        ):
            parts = size.split()
            if len(parts) >= 2:
                element.set("size", " ".join([parts[1], parts[0], *parts[2:]]))
    return ET.tostring(root, encoding="unicode")


def _fmt(value: float) -> str:
    return f"{value:.6g}"


def transform_goal(goal: GoalRegion, name: str) -> GoalRegion:
    """Rigidly transform a goal region. Distances (bands, radii) are invariant."""

    payload = goal.as_dict()
    center = payload.get("center")
    if center is not None:
        payload["center"] = list(transform_xy(name, center[0], center[1]))
    polygon = payload.get("polygon")
    if polygon is not None:
        payload["polygon"] = [list(transform_xy(name, p[0], p[1])) for p in polygon]
    return GoalRegion(
        kind=payload["kind"],
        center=tuple(payload["center"]) if payload.get("center") is not None else None,
        radius_m=payload.get("radius_m"),
        polygon=(
            tuple(tuple(p) for p in payload["polygon"])
            if payload.get("polygon") is not None
            else None
        ),
        anchor_entity=payload.get("anchor_entity"),
        band_m=tuple(payload["band_m"]) if payload.get("band_m") is not None else None,
        anchor_footprint_m=payload.get("anchor_footprint_m", 0.0),
    )


def transform_episode(episode: EpisodeSpec, name: str) -> EpisodeSpec:
    """The same episode, rigidly transformed. Path length is invariant."""

    x, y = transform_xy(name, episode.start_pose[0], episode.start_pose[1])
    placement = dict(episode.placement_overrides or {})
    robot = placement.get("robot")
    if isinstance(robot, dict):
        placement = {
            **placement,
            "robot": {"x": x, "y": y, "yaw": transform_yaw(name, episode.start_pose[2])},
        }
    return dataclasses.replace(
        episode,
        episode_id=f"{name}|{episode.episode_id}",
        start_pose=(x, y, transform_yaw(name, episode.start_pose[2])),
        goal=transform_goal(episode.goal, name),
        placement_overrides=placement,
    )


def write_transformed_scene(scene: Path, name: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{scene.stem}__{name}.xml"
    target.write_text(
        transform_scene_xml(
            scene.read_text(encoding="utf-8"), name, source_dir=scene.parent
        ),
        encoding="utf-8",
    )
    return target


@dataclass(frozen=True)
class EquivarianceVerdict:
    """One MR check, with the tolerance it was judged against."""

    episode_id: str
    transform: str
    discrepancy_m: float
    repeat_mean_m: float
    repeat_sd_m: float
    z: float
    floor_m: float
    violated: bool
    success_matches: bool
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def equivariance_verdict(
    *,
    episode_id: str,
    transform: str,
    discrepancy_m: float,
    repeats_m: Sequence[float],
    success_matches: bool,
    floor_m: float = EQUIVARIANCE_FLOOR_M,
) -> EquivarianceVerdict:
    """The plan's z-test, with the honest degenerate case spelled out.

    ``repeats_m`` are the pairwise final-pose distances between repeat runs of
    the *untransformed* episode: this harness's own variability. When they are
    all zero the runner is deterministic, the z-test has no scale, and the
    verdict falls back to ``floor_m`` — stated in ``detail`` rather than hidden.
    """

    values = [float(item) for item in repeats_m] or [0.0]
    mean = statistics.fmean(values)
    sd = statistics.pstdev(values) if len(values) > 1 else 0.0
    if sd > 0.0:
        z = (discrepancy_m - mean) / sd
        violated = discrepancy_m > floor_m and z > Z_CRITICAL
        detail = f"z-test against repeat sd {sd:.4f} m"
    else:
        z = math.inf if discrepancy_m > mean else 0.0
        violated = discrepancy_m > floor_m
        detail = (
            "repeat spread is exactly zero (deterministic runner): the z-test "
            f"has no scale, so the floor {floor_m:.2f} m decides"
        )
    return EquivarianceVerdict(
        episode_id=episode_id,
        transform=transform,
        discrepancy_m=float(discrepancy_m),
        repeat_mean_m=mean,
        repeat_sd_m=sd,
        z=float(z),
        floor_m=float(floor_m),
        violated=bool(violated or not success_matches),
        success_matches=bool(success_matches),
        detail=detail,
    )


def final_pose(result: Any) -> tuple[float, float]:
    trace = list(result.trace)
    if not trace:
        return (0.0, 0.0)
    return (float(trace[-1].get("x", 0.0)), float(trace[-1].get("y", 0.0)))


def dropout_tier(probability: float, *, name: str | None = None) -> Any:
    """A tier whose *only* noise is detector dropout at a fixed probability.

    Deliberately single-variable: a monotonicity claim over a tier that also
    moves range sigma and false positives is a claim about three things.
    """

    from parcel_robot.detection_adapter.perception_chain import NoiseTier

    value = float(probability)
    if value <= 0.0:
        from parcel_robot.detection_adapter.perception_chain import tier_t0

        return tier_t0()
    return NoiseTier(
        name=name or f"dropout-{value:.2f}",
        passthrough=False,
        dropout_near=value,
        dropout_far=value,
    )
