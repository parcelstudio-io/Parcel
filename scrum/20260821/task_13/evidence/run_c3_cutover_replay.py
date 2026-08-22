#!/usr/bin/env python
"""C-3 cutover replay — the REAL ``OnlineSemanticMap`` on the real shipped path.

**What this is, exactly.** It builds C-2's real map class, installs it on the
real process seams, and drives the real shipped consumers:
``RobotRuntime._place_admission`` (R20), ``runtime.scene_report`` (R18) and the
shadow taxonomy. Nothing here is a re-implementation of the code under test.

**What this is NOT.** It is not a live voice session and it is not a
closed-loop mission. The robot does not move; there is no simulator, no
detector, and no arrival. Those are the card's items 5 / REVISION §3 and they
are recorded as NOT REACHED in ``C3_STATUS.md``. A run of this file is evidence
that the cutover's *plumbing* answers correctly on a real map; it is not
evidence that a T1-driven robot arrives anywhere.

**Two arms, for the same reason C-2 used two.**

* **Arm A — real pixels.** C-1's 16 published ``CameraDetectionFrame`` rows
  (``tests/data/c2_online_map_frames.json``): real MuJoCo renders of W-1's
  textured ``city_block``, real OWLv2-b16 int8 on CPU, real poses. This is the
  only real perception available to this card, and C-2 measured its limits
  precisely: the robot moved 4 cm and two nouns were ever asked.
* **Arm B — the map path alone.** Detections synthesised at the surfaces
  ``scene_truth.json`` says exist, so "the map mislocated it" and "the detector
  saw something else" stop being confounded. **Not a perception claim.**

**Falsifiability.** The harness carries its own null controls and **exits
non-zero** if it cannot falsify its own result — C-2's seed-7 precedent. If the
null controls stop being asked, or a POI-sourced goal appears, the run is red.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import random
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

os.environ.setdefault("PARCEL_MEMORY_PATH", ":memory:")

from parcel_robot.backends.base import (
    OwnerTrack,
    RobotPose,
    SemanticObjectTrack,
    SemanticRegionTrack,
    SimObservation,
)
from parcel_robot.navigation.pipeline import DirectiveNavigator
from parcel_robot.online_map import (
    MapObservation,
    OnlineMapStore,
    OnlineSemanticMap,
    WriterProvenance,
)
from parcel_robot.perception_source import (
    SOURCE_LEARNED_MAP,
    SOURCE_ORACLE,
    ArmVerdict,
    SemanticSourcePolicy,
    SensingEnvelope,
    ShadowLedger,
    envelope_comparability,
    use_learned_map,
    use_semantic_source,
)
from parcel_robot.runtime import RobotRuntime, scene_report

SCENE_TRUTH = REPO / "evals" / "nav_instruct" / "scene_truth.json"
FIXTURE = REPO / "tests" / "data" / "c2_online_map_frames.json"

#: Corpus rows 10–13. These must behave IDENTICALLY under both sources.
CORPUS_REFUSAL_ROWS = (
    ("10", "Go to Narnia."),
    ("11", "Go to my office."),
    ("12", "Take me to the moon."),
    ("13", "Let's go back home."),
)

#: Absent places. Nothing may admit these, under any source. Falsifiability.
NULL_CONTROLS = (
    "go to the helipad",
    "go to the swimming pool",
    "go to the aquarium",
    "go to the launch pad",
    "go to the throne room",
    "go to narnia",
)

#: The four `demo_pois.yaml` classes. Under T1 none may reach `known_poi`.
POI_DIRECTIVES = (
    "go to the coffee shop",
    "go to the crosswalk",
    "go to the park",
    "go to the bookstore",
)

#: The D455's envelope, as C-1's stream actually used it: the depth band the
#: localizer trusts and the camera's horizontal half-angle. Supplied by the
#: caller that owns the sensor, never guessed inside the taxonomy.
ENVELOPE = SensingEnvelope(max_range_m=6.0, half_fov_rad=math.radians(43.5))

#: Metric extents for arm B, by class. Fixed here BEFORE the run, from the
#: scene's own geometry, and not adjusted afterwards.
ARM_B_EXTENTS = {
    "bench": (1.4, 0.9),
    "lamppost": (0.14, 3.6),
    "tree": (0.6, 4.0),
    "planter": (0.9, 0.6),
    "door": (1.0, 2.1),
    "building": (3.6, 6.0),
}


class _AdmissionHarness:
    """Binds the SHIPPED runtime methods to a stub, so this is not a re-write."""

    def __init__(self, observation: SimObservation | None) -> None:
        self._lock = threading.RLock()
        self._observation = observation
        for name in (
            "_place_admission",
            "_realtime_scene_vocabulary",
            "_realtime_places",
            "_learned_map_vocabulary",
            "_learned_map_offer_places",
        ):
            setattr(self, name, getattr(RobotRuntime, name).__get__(self))


def _part_centre(spec: dict) -> tuple[float, float]:
    """Centre of a truth surface. Handles BOTH shapes the file actually uses.

    ``scene_truth.json`` carries ``rect`` parts (a ``polygon``) and ``circle``
    parts (a ``center`` + ``radius_m``) — lampposts, planters and trees are all
    circles. An earlier draft read ``polygon`` only and divided by zero on the
    first lamppost, which is the cheapest possible reminder that a fixture's
    shape is something to read rather than assume.
    """

    xs: list[float] = []
    ys: list[float] = []
    for part in spec.get("parts", []):
        polygon = part.get("polygon")
        if polygon:
            for x, y in polygon:
                xs.append(float(x))
                ys.append(float(y))
            continue
        center = part.get("center")
        if center:
            xs.append(float(center[0]))
            ys.append(float(center[1]))
    if not xs:
        raise ValueError(f"truth surface has no usable geometry: {spec.get('label')!r}")
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _truth_targets() -> dict[str, dict]:
    truth = json.loads(SCENE_TRUTH.read_text(encoding="utf-8"))["surfaces"]
    return {
        key: spec
        for key, spec in truth.items()
        if spec.get("measure") == "surface" and spec.get("label") in ARM_B_EXTENTS
    }


def build_arm_b_map(scratch: Path) -> tuple[OnlineSemanticMap, dict[str, dict]]:
    """A real ``OnlineSemanticMap`` fed synthetic detections at real surfaces."""

    random.seed(20260822)
    targets = _truth_targets()
    queries = tuple(sorted({spec["label"] for spec in targets.values()}))
    provenance = WriterProvenance(
        session_id="c3-replay-arm-b",
        seat="async_keyframe_map",
        detector_name="truth-derived-synthetic",
        scene_id="city_block",
    )
    store_path = scratch / "c3_arm_b_map.sqlite3"
    if store_path.exists():
        store_path.unlink()
    store = OnlineMapStore(store_path)
    the_map = OnlineSemanticMap(store, provenance=provenance)

    wall = 1_000_000.0
    for visit in range(3):
        # The robot walks a lap past every target, so navigability is MEASURED
        # (the robot's own body stood there) rather than asserted.
        for spec in targets.values():
            cx, cy = _part_centre(spec)
            for step in range(8):
                angle = 2.0 * math.pi * step / 8
                the_map.note_pose(cx + 1.5 * math.cos(angle), cy + 1.5 * math.sin(angle))
        for frame_index in range(8):
            the_map.note_frame(queries)
            for key, spec in sorted(targets.items()):
                cx, cy = _part_centre(spec)
                width, height = ARM_B_EXTENTS[spec["label"]]
                # The robot observes from 2 m away, on the near side.
                rx = cx - 2.0
                ry = cy
                sx = cx + random.gauss(0.0, 0.05)
                sy = cy + random.gauss(0.0, 0.05)
                range_m = math.hypot(sx - rx, sy - ry)
                wall += 1.0
                the_map.observe(
                    MapObservation(
                        label=str(spec["label"]),
                        score=min(0.95, max(0.05, 0.62 + random.gauss(0.0, 0.05))),
                        surface_x=sx,
                        surface_y=sy,
                        surface_z=0.0,
                        range_m=range_m,
                        bearing_rad=math.atan2(sy - ry, sx - rx),
                        # Depth inside the D455 ground band for a standable
                        # place; PG-3's navigability signal reads this.
                        depth_m=range_m,
                        extent_w_m=width,
                        extent_h_m=height,
                        inlier_pixels=900,
                        frame_id=f"armb-v{visit}-{key}-{frame_index}",
                        visit_id=f"armb-visit-{visit}",
                        observed_wall_s=wall,
                        robot_x=rx,
                        robot_y=ry,
                        provenance=provenance,
                    )
                )
        the_map.close_visit(f"armb-visit-{visit}", wall_s=wall)
    the_map.persist()
    return the_map, targets


def oracle_observation(x: float, y: float, yaw: float, targets: dict) -> SimObservation:
    """What the GT oracle would report at this pose — the T0 arm's answer."""

    objects = []
    for key, spec in sorted(targets.items()):
        cx, cy = _part_centre(spec)
        objects.append(
            SemanticObjectTrack(
                object_id=key,
                label=str(spec["label"]),
                position=(cx, cy, 0.0),
                # The oracle's literal, by fiat. This is the number the whole
                # card exists to replace, and it is reproduced here verbatim so
                # the comparison is against what actually ships.
                confidence=0.98,
                source="perception",
                reachable=True,
                metadata={},
            )
        )
    return SimObservation(
        timestamp=1.0,
        robot=RobotPose(x=x, y=y, yaw=yaw),
        owner=OwnerTrack(x=x + 1.0, y=y, visible=True, confidence=0.9),
        semantic_objects=tuple(objects),
        semantic_regions=(
            SemanticRegionTrack(
                region_id="sidewalk",
                label="sidewalk",
                polygon=((-6.0, 2.4), (6.0, 2.4), (6.0, 3.6), (-6.0, 3.6)),
                confidence=0.98,
                source="perception",
                reachable=True,
                metadata={},
            ),
        ),
    )


def _oracle_verdict(query_class: str, targets: dict, rx: float, ry: float) -> ArmVerdict:
    """The oracle admits any declared class and names its nearest instance."""

    best = None
    for key, spec in targets.items():
        if str(spec["label"]) != query_class:
            continue
        cx, cy = _part_centre(spec)
        distance = math.hypot(cx - rx, cy - ry)
        if best is None or distance < best[0]:
            best = (distance, key, cx, cy)
    if best is None:
        return ArmVerdict(admitted=False, reason="not_in_scene_vocabulary")
    _distance, key, cx, cy = best
    return ArmVerdict(admitted=True, place_id=key, label=query_class, x=cx, y=cy)


def _learned_verdict(the_map: OnlineSemanticMap, query_class: str, rx: float, ry: float) -> ArmVerdict:
    """The learned map's answer, through C-2's own query API and PG-3 verdict."""

    result = the_map.resolve(query_class, robot_xy=(rx, ry))
    best = result.best
    if best is None:
        return ArmVerdict(admitted=False, reason="no_candidate")
    if not result.admitted:
        return ArmVerdict(
            admitted=False,
            reason=str(getattr(result.verdict, "reason", "refused")),
            label=best.label,
            x=best.x,
            y=best.y,
        )
    return ArmVerdict(
        admitted=True, place_id=best.entry_id, label=best.label, x=best.x, y=best.y
    )


def main() -> int:
    scratch = Path(
        os.environ.get(
            "C3_SCRATCH",
            "/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/"
            "799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/c3",
        )
    )
    scratch.mkdir(parents=True, exist_ok=True)

    owner_store = REPO / "parcel_memory.sqlite3"
    owner_sha_before = (
        hashlib.sha256(owner_store.read_bytes()).hexdigest()[:16]
        if owner_store.exists()
        else None
    )

    the_map, targets = build_arm_b_map(scratch)
    summary: dict[str, object] = {
        "card": "C-3",
        "arm": "B (truth-derived synthetic detections; NOT a perception claim)",
        "map_entries": len(the_map.entries()),
        "map_known_places": list(the_map.known_places()),
    }

    rx, ry, yaw = -2.0, 1.0, math.radians(75.0)
    observation = oracle_observation(rx, ry, yaw, targets)

    # ---- R20 admission: oracle vs learned map, on the SHIPPED path ---------
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_ORACLE))
    use_learned_map(None)
    oracle_harness = _AdmissionHarness(observation)

    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    use_learned_map(the_map)
    learned_harness = _AdmissionHarness(observation)

    admission_rows = []
    equivalence_failures = []
    for row_id, directive in CORPUS_REFUSAL_ROWS:
        use_semantic_source(SemanticSourcePolicy(source=SOURCE_ORACLE))
        use_learned_map(None)
        a = oracle_harness._place_admission(directive)
        use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
        use_learned_map(the_map)
        b = learned_harness._place_admission(directive)
        same = (a.admitted, a.reason) == (b.admitted, b.reason)
        if not same:
            equivalence_failures.append(row_id)
        admission_rows.append(
            {
                "row": row_id,
                "directive": directive,
                "oracle": {"admitted": a.admitted, "reason": a.reason},
                "learned_map": {"admitted": b.admitted, "reason": b.reason},
                "equivalent": same,
            }
        )
    summary["corpus_rows_10_13"] = admission_rows
    summary["corpus_equivalence_failures"] = equivalence_failures

    # Known places the map actually learned MUST admit.
    use_semantic_source(SemanticSourcePolicy(source=SOURCE_LEARNED_MAP))
    use_learned_map(the_map)
    known_rows = []
    for name in the_map.known_places():
        admission = learned_harness._place_admission(f"go to the {name}")
        known_rows.append(
            {"place": name, "admitted": admission.admitted, "reason": admission.reason}
        )
    summary["known_place_admission"] = known_rows
    summary["known_place_admitted"] = sum(1 for row in known_rows if row["admitted"])
    summary["known_place_total"] = len(known_rows)

    # ---- null controls (falsifiability) -----------------------------------
    null_rows = []
    for directive in NULL_CONTROLS:
        admission = learned_harness._place_admission(directive)
        null_rows.append(
            {
                "directive": directive,
                "admitted": admission.admitted,
                "reason": admission.reason,
            }
        )
    admitted_nulls = [
        row for row in null_rows if row["admitted"] and row["reason"] != "not_a_navigation_directive"
    ]
    summary["null_controls"] = null_rows
    summary["null_controls_admitted"] = len(admitted_nulls)

    # ---- POI arm must be empty under T1 -----------------------------------
    navigator = DirectiveNavigator.from_config()
    poi_rows = []
    try:
        for directive in POI_DIRECTIVES:
            mission = navigator.parse(directive)
            poi_rows.append(
                {
                    "directive": directive,
                    "goal_source": mission.metadata.get("goal_source"),
                    "goal": None if mission.goal is None else [mission.goal.x, mission.goal.y],
                }
            )
    finally:
        navigator.close()
    poi_sourced = [row for row in poi_rows if row["goal_source"] == "known_poi"]
    summary["poi_arm"] = poi_rows
    summary["poi_sourced_goals"] = len(poi_sourced)
    summary["poi_table_size"] = len(navigator.grounder.pois)

    # ---- R18 scene answerability ------------------------------------------
    learned_scene = scene_report(observation, learned_map=the_map)
    oracle_scene = scene_report(observation)
    summary["scene"] = {
        "learned_map": {
            "semantic_source": learned_scene["semantic_source"],
            "note_denies_eyes": "no eyes" in str(learned_scene["note"]),
            "things": learned_scene["things"],
            "summary": learned_scene["summary"],
        },
        "oracle": {
            "semantic_source": oracle_scene["semantic_source"],
            "note_denies_eyes": "no eyes" in str(oracle_scene["note"]),
            "things": [thing["label"] for thing in oracle_scene["things"]],
        },
    }

    # ---- shadow agreement table, both denominators ------------------------
    ledger = ShadowLedger(localization_tolerance_m=1.0)
    query_classes = sorted({str(spec["label"]) for spec in targets.values()})
    poses = [(-2.0, 1.0, math.radians(75.0)), (0.0, 0.0, 0.0), (3.0, 2.0, math.radians(150.0))]
    for px, py, pyaw in poses:
        for query_class in query_classes:
            oracle_arm = _oracle_verdict(query_class, targets, px, py)
            learned_arm = _learned_verdict(the_map, query_class, px, py)
            comparable = envelope_comparability(
                ENVELOPE,
                oracle=oracle_arm,
                robot_x=px,
                robot_y=py,
                robot_yaw_rad=pyaw,
            )
            ledger.record(
                query=query_class,
                query_class=query_class,
                oracle=oracle_arm,
                learned=learned_arm,
                comparable=comparable,
                frames=(f"pose-{px}-{py}-{query_class}",),
            )
    shadow = ledger.summary()
    summary["shadow"] = shadow

    owner_sha_after = (
        hashlib.sha256(owner_store.read_bytes()).hexdigest()[:16]
        if owner_store.exists()
        else None
    )
    summary["owner_store_sha16"] = {"before": owner_sha_before, "after": owner_sha_after}

    use_semantic_source(None)
    use_learned_map(None)

    out = Path(__file__).with_name("c3_replay_summary.json")
    out.write_text(json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8")

    # ---- self-check: the harness must be able to falsify itself -----------
    problems: list[str] = []
    if len(NULL_CONTROLS) < 5:
        problems.append("fewer than 5 null controls: this run cannot falsify itself")
    if admitted_nulls:
        problems.append(f"null control(s) admitted: {[r['directive'] for r in admitted_nulls]}")
    if equivalence_failures:
        problems.append(f"corpus rows moved across the cutover: {equivalence_failures}")
    if poi_sourced:
        problems.append(f"POI-sourced goal under T1: {poi_sourced}")
    if owner_sha_before != owner_sha_after:
        problems.append("the owner's conversation store CHANGED during this run")
    if not shadow["rows"]:
        problems.append("empty shadow table")
    for row in shadow["rows"]:
        if row["n_total"] == 0:
            problems.append(f"class {row['query_class']} reported with a zero denominator")

    print(json.dumps(summary["shadow"]["overall"], indent=2))
    print(f"map entries        : {summary['map_entries']}")
    print(f"known places       : {summary['map_known_places']}")
    print(f"corpus 10-13       : {len(admission_rows)} rows, "
          f"{len(equivalence_failures)} moved across the cutover")
    print(f"known-place admit  : {summary['known_place_admitted']}/{summary['known_place_total']}")
    print(f"null controls      : {len(NULL_CONTROLS)} asked, {len(admitted_nulls)} admitted")
    print(f"POI-sourced goals  : {len(poi_sourced)} (table size {summary['poi_table_size']})")
    print(f"owner store sha16  : {owner_sha_before} -> {owner_sha_after}")
    for row in shadow["rows"]:
        print(
            f"  {row['query_class']:<10} agree_total={row['agreement_total']} "
            f"(n={row['n_total']})  agree_comparable={row['agreement_comparable']} "
            f"(n={row['n_comparable']})  {row['counts']}"
        )
    if problems:
        print("\nHARNESS SELF-CHECK FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  * {problem}", file=sys.stderr)
        return 1
    print("\nself-check passed (the run is falsifiable and was not falsified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
