"""Card P1-D — the CI eval row: rows 1-3, re-runnable, on pinned fixtures.

Work item 2 asks for "pinned fixtures and a CI eval row (the llmdet lesson)".
The lesson is ``SYNTHESIS.md``'s process finding: *any future model-seat swap
requires a pinned-fixture eval in CI before cutover* — paper numbers and even
sibling-model behaviour are not evidence about a specific converted artifact.

So the fixture is in the tree (``tests/data/p1d_crops/``, 40 textured
``city_block`` crops with the scene's own labels and the exact 64-px thumbnails
``MapEntry`` would store), and the rows re-run here rather than only in a
scratch directory nobody else can reach.

Two arms:

* **CPU, always.** ``NullVerifier`` — no seat, no GPU, no weights. This is the
  degradation arm and it is the one that runs on every commit: the gate must
  ASK about everything and admit nothing wrong.
* **GPU, gated.** The real Qwen3-VL-2B, skipped unless ``PARCEL_P1D_GPU_EVAL=1``
  and the weights resolve. This is the arm that would catch a seat swap.

Both go through the PRODUCT path — ``OnlineSemanticMap.resolve`` — with no
monkeypatch anywhere. The first version of this card measured row 1 through a
harness that replaced ``assess_place_query``; the verifier caught it, and the
whole point of this file is that the number cannot be produced that way again.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path

import pytest

from parcel_robot.online_map import (
    EmbeddingStamp,
    MapObservation,
    OnlineSemanticMap,
    WriterProvenance,
)
from parcel_robot.perception_abstention import (
    OUTCOME_ADMIT,
    OUTCOME_ASK,
    OUTCOME_REFUSE,
    AbstentionPolicy,
    clear_veto_cache,
    use_veto,
)

REPO = Path(__file__).resolve().parents[1]
CROPS = REPO / "tests/data/p1d_crops"
MANIFEST = CROPS / "MANIFEST.json"

#: Pre-registered in ``scrum/20260822/task_9/P1D_PREREGISTRATION.md`` §3 row 2.
ABSENT = (
    "Narnia",
    "my office",
    "the moon",
    "a coffee shop",
    "a fire hydrant",
    "a swimming pool",
    "the airport",
    "a shopping trolley",
)

#: Metric extents per class, so C-2's size-prior hygiene gate admits the entry.
#: These are facts about the dev scene, not tuning.
EXTENTS = {
    "bench": (1.6, 0.9),
    "bicycle": (1.6, 1.0),
    "bollard": (0.25, 0.9),
    "building": (8.0, 6.0),
    "crate": (0.8, 0.8),
    "door": (1.0, 2.1),
    "lamppost": (0.3, 3.2),
    "planter": (0.9, 0.8),
    "traffic light": (0.3, 1.0),
    "tree": (1.6, 3.5),
}

STAMP = EmbeddingStamp(
    model_id="p1d-fixture", revision="1", dim=4, preprocessing="none"
)


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _prototype_policy() -> AbstentionPolicy:
    import yaml

    data = yaml.safe_load(
        (REPO / "configs/navigation/prototype.yaml").read_text(encoding="utf-8")
    )
    return AbstentionPolicy.from_mapping(data["perception"]["abstention"])


def _with(policy: AbstentionPolicy, **overrides) -> AbstentionPolicy:
    import dataclasses

    return dataclasses.replace(policy, **overrides)


def _null_seat_policy() -> AbstentionPolicy:
    """The prototype roster with the veto seat explicitly turned off."""

    return _with(_prototype_policy(), veto_model="")


def _build_map(policy: AbstentionPolicy) -> tuple[OnlineSemanticMap, list[str]]:
    """A real map from the pinned crops, plus D-R3's ``shop``.

    Three observations per object with DISTINCT visit ids, because the evidence
    gate counts visits and a single stare is not a place.
    """

    provenance = WriterProvenance(
        session_id="p1d-eval", seat="fixture", detector_name="scene_gt",
        scene_id="city_block",
    )
    smap = OnlineSemanticMap(provenance=provenance, policy=policy)
    by_object: dict[str, list[dict]] = {}
    for row in _manifest()["crops"]:
        by_object.setdefault(row["object_key"], []).append(row)

    def observe(index: int, label: str, thumb: bytes) -> None:
        for visit in range(3):
            smap.observe(
                MapObservation(
                    label=label, score=0.8,
                    surface_x=float(10 * index), surface_y=0.0, surface_z=0.4,
                    range_m=3.0, bearing_rad=0.0, depth_m=3.0,
                    extent_w_m=EXTENTS[label][0], extent_h_m=EXTENTS[label][1],
                    inlier_pixels=5000, frame_id=f"f{index}-{visit}",
                    visit_id=f"visit-{visit}", observed_wall_s=1000.0 + visit,
                    robot_x=0.0, robot_y=0.0, provenance=provenance,
                    thumbnail=thumb, relief_m=0.2, relief_samples=40,
                    embedding=(0.1, 0.2, 0.3, 0.4), embedding_stamp=STAMP,
                )
            )

    index = 0
    for key, views in sorted(by_object.items()):
        if len(views) < 3:
            continue
        observe(index, views[0]["label"], base64.b64decode(views[0]["thumbnail_b64"]))
        index += 1
    # Refutation D-R3's seed: a place the map really calls `shop`, so
    # "a coffee shop" has a token to catch on. Its crop is a building, which is
    # what a shopfront in this scene IS — the veto should say so.
    building = next(r for r in _manifest()["crops"] if r["label"] == "building")
    observe(index, "building", base64.b64decode(building["thumbnail_b64"]))
    for entry in smap.active_entries():
        if abs(entry.surface_x - 10 * index) < 0.5:
            entry.label = "shop"
    present = sorted({e.label for e in smap.active_entries()} - {"shop"})
    return smap, present


def _outcomes(smap: OnlineSemanticMap, queries) -> list[str]:
    return [smap.resolve(q).verdict.outcome for q in queries]


@pytest.fixture(autouse=True)
def _clean_veto_state():
    use_veto(None)
    clear_veto_cache()
    yield
    use_veto(None)
    clear_veto_cache()


# ==========================================================================
# the fixture itself
# ==========================================================================


def test_the_pinned_fixture_matches_its_recorded_digests() -> None:
    """The llmdet lesson: a fixture that can drift is not a pin.

    SEED: re-render one crop, or edit a label in the manifest.
    """

    manifest = _manifest()
    assert manifest["pool_sha256"].startswith("77c86e15")
    assert manifest["f_name_sha256"].startswith("162bd28b")
    crops = manifest["crops"]
    assert len(crops) == 40
    labels = sorted({c["label"] for c in crops})
    assert len(labels) == 10
    assert all(sum(c["label"] == label for c in crops) == 4 for label in labels)
    for crop in crops:
        blob = (CROPS / crop["file"]).read_bytes()
        assert hashlib.sha256(blob).hexdigest() == crop["sha256"], crop["file"]
        thumb = base64.b64decode(crop["thumbnail_b64"])
        assert thumb.startswith(b"\x89PNG"), crop["file"]
        assert len(thumb) <= 16384, "MapEntry caps a thumbnail at 16 KB"


def test_the_map_built_from_the_fixture_carries_a_crop_for_every_place() -> None:
    """Without this, the veto sees nothing and every arm below reads the same.

    Worth its own cell because it is exactly the coupling P1-D found in C-2:
    ``_maybe_take_best_view`` drops the thumbnail when no embedding arrives with
    it, so a map built without embeddings has zero crops and the veto silently
    degrades to ASK for a reason that has nothing to do with the model.
    """

    smap, present = _build_map(_prototype_policy())
    entries = smap.active_entries()
    assert len(entries) >= 7
    assert all(e.thumbnail for e in entries), "no crop => the eval measures nothing"
    assert "shop" in {e.label for e in entries}
    assert present


# ==========================================================================
# rows 1-3, CPU arm — no seat, no weights, every commit
# ==========================================================================


def test_rows_1_to_3_with_no_seat_ask_and_admit_nothing_wrong() -> None:
    """The DEGRADATION arm, and the one the shipping host actually runs.

    ``.parcel`` carries no tensor library, so this is what a real Parcel install
    does today: the roster selects ``vlm_veto``, no seat resolves, every veto
    answers ``unavailable``, and the gate ASKS. Row 2's property must hold
    anyway — asking about a place is not admitting it.

    ``veto_model`` is pinned to the null seat HERE rather than inherited from
    the profile, so the arm is deterministic on a developer box that happens to
    have torch and the weights. The real seat is the GPU arm at the bottom of
    this file; this cell is about the posture when there is no seat at all.

    SEED: make an unavailable veto admit (row 1 goes to 8 admits, row 2 breaks);
    or drop ``ask_below_threshold`` (every ask becomes a refusal and the 0/18
    posture is back).
    """

    policy = _null_seat_policy()
    smap, present = _build_map(policy)
    present_out = _outcomes(smap, present)
    absent_out = _outcomes(smap, ABSENT)

    # Row 1: nothing admits without a seat...
    assert OUTCOME_ADMIT not in present_out
    # ...but nothing is REFUSED for a threshold either: the dog asks.
    assert present_out.count(OUTCOME_ASK) == len(present)
    # Row 2: 0/8 admitted. This is the property that must survive every arm.
    assert OUTCOME_ADMIT not in absent_out
    # Row 3: the ASK rate, and its shape. Seven of the eight absent queries have
    # no candidate at all and REFUSE as `no_observations`; the eighth is
    # "a coffee shop", which finds `shop` by token overlap and therefore ASKS.
    assert absent_out.count(OUTCOME_REFUSE) == 7
    assert absent_out.count(OUTCOME_ASK) == 1
    all_out = present_out + absent_out
    ask_rate = all_out.count(OUTCOME_ASK) / len(all_out)
    assert 0.5 <= ask_rate <= 0.6, ask_rate


def test_an_injected_present_veto_admits_through_the_product_path() -> None:
    """The seam, proven end to end WITHOUT a monkeypatch.

    ``use_veto`` installs a callable that the gate resolves for itself; nothing
    here replaces ``assess_place_query``. If the producer regresses to the
    original "keyword argument with no producer", the veto never runs, every
    place stays an ASK, and this cell goes red.

    SEED: delete the ``resolve_veto`` call in ``assess_place_query``.
    """

    from parcel_robot.vlm_veto import VetoAnswer

    policy = _prototype_policy()
    seen: list[str] = []

    def always_present(query, place):
        seen.append(place.place_id)
        assert place.crop_png, "the evidence must carry the crop to the seat"
        return VetoAnswer("present", p_yes=0.99, latency_ms=42.0, model="stub")

    use_veto(always_present)
    smap, present = _build_map(policy)
    present_out = _outcomes(smap, present)
    assert present_out.count(OUTCOME_ADMIT) == len(present), present_out
    assert seen, "the veto was never consulted on the product path"
    # ...and an absent veto takes every one of them away again.
    use_veto(lambda q, p: VetoAnswer("absent", p_yes=0.01, model="stub"))
    smap2, present2 = _build_map(policy)
    assert OUTCOME_ADMIT not in _outcomes(smap2, present2)
    assert OUTCOME_ADMIT not in _outcomes(smap2, ABSENT)


def test_the_resolved_seat_is_a_CALLABLE_the_gate_can_actually_invoke() -> None:
    """``resolve_veto`` must return something ``veto(query, place)`` works on.

    The first wiring returned the ``VetoRunner`` itself. A VetoRunner is not
    callable, so every invocation raised ``TypeError``, the gate caught it and
    read it as "unavailable", and the product asked about everything while
    looking perfectly wired. It cost a full GPU re-measurement to notice.

    SEED: ``return runner_for(key)`` instead of ``runner_for(key).veto_callable()``.
    """

    from parcel_robot.perception_abstention import PlaceEvidence, resolve_veto

    policy = _null_seat_policy()
    clear_veto_cache()
    seat = resolve_veto(policy)
    assert callable(seat), f"the gate calls veto(query, place); got {seat!r}"
    answer = seat("bench", PlaceEvidence(place_id="p1", label="bench", x=1.0, y=2.0))
    assert answer.verdict == "unavailable"


def test_the_config_names_the_seat_and_an_unknown_name_asks() -> None:
    """``veto_model`` is the producer's input. An unknown id must ASK, not guess.

    The llmdet lesson again: a seat that resolves to "whatever is importable"
    is how a perception model gets swapped without an eval.

    SEED: fall back to a plugin lookup in ``_named_seat``.
    """

    from parcel_robot.vlm_veto import NULL_SEAT_NAMES, clear_seats, runner_for

    clear_seats()
    try:
        assert "" in NULL_SEAT_NAMES
        assert runner_for("").verifier.name == "null"
        assert runner_for("some-model-nobody-shipped").verifier.name == "null"
    finally:
        clear_seats()

    policy = _prototype_policy()
    assert policy.veto_model == "Qwen/Qwen3-VL-2B-Instruct"
    clear_veto_cache()
    smap, present = _build_map(_with(policy, veto_model="not-a-real-model"))
    assert OUTCOME_ADMIT not in _outcomes(smap, present)
    assert OUTCOME_ADMIT not in _outcomes(smap, ABSENT)


# ==========================================================================
# rows 1-3, GPU arm — the real seat, gated
# ==========================================================================


def _gpu_reason() -> str:
    if os.environ.get("PARCEL_P1D_GPU_EVAL") != "1":
        return "set PARCEL_P1D_GPU_EVAL=1 to run the real-seat eval"
    try:
        import torch
    except ImportError:
        return "no torch in this environment"
    if not torch.cuda.is_available():
        return "no CUDA device"
    from parcel_robot.vlm_veto import resolve_weights

    if not resolve_weights():
        return "no local Qwen3-VL-2B snapshot"
    return ""


@pytest.mark.slow
def test_rows_1_to_3_with_the_real_seat() -> None:
    """The arm that would catch a seat swap. Owner-gated on the GPU.

    Recorded on 2026-08-22 (``P1D_STATUS.md`` §11): 5 of 7 present admitted,
    0 of 8 absent admitted, "a coffee shop" REFUSED by the veto at p_yes 0.008.
    The assertions below are the PROPERTIES, not those exact counts — a seat
    swap that changes 5 to 6 is fine and a swap that admits an absent query is
    not.
    """

    reason = _gpu_reason()
    if reason:
        pytest.skip(reason)

    policy = _prototype_policy()
    smap, present = _build_map(policy)
    # ---- CARD NM-1 (task_18) — the board has to be warm before the assertions.
    #
    # DECLARED EDIT to another card's test, made because NM-1 changed the
    # behaviour this test measures and leaving it broken-when-ungated would be
    # worse than touching it. The veto is no longer computed inside the
    # grounding call: ``resolve_veto`` now hands the gate a BOARD READER
    # (``vlm_veto.bureau``), so the first resolve of a place is an ASK that
    # SCHEDULES the judgement and a later resolve consumes it. Navigation never
    # waits on a model — that is the whole point — so a harness that wants the
    # steady state has to say so.
    #
    # The PROPERTIES this test asserts are unchanged and so are its numbers:
    # measured on the product path with the bureau installed, pass 2 gives 5 of
    # 7 present admitted and 0 of 8 absent — P1-D's own figures
    # (``task_18/evidence/product_bureau.json``).
    from parcel_robot.vlm_veto.bureau import bureau_for

    queries = list(present) + list(ABSENT) + ["a coffee shop"]
    for query in queries:
        smap.resolve(query)
    assert bureau_for(policy.veto_model).drain(timeout=120.0), "the veto worker stalled"
    # ---- END CARD NM-1 (task_18) -----------------------------------------
    present_out = _outcomes(smap, present)
    absent_out = _outcomes(smap, ABSENT)

    # Row 1: the state C-3 measured at 0/18 now admits something.
    assert present_out.count(OUTCOME_ADMIT) >= 1, present_out
    # Row 2: and still nothing the robot never saw.
    assert OUTCOME_ADMIT not in absent_out, absent_out
    # D-R3: "a coffee shop" must not become a goal against a `shop` entry.
    coffee = smap.resolve("a coffee shop").verdict
    assert coffee.admitted is False
    assert coffee.outcome in (OUTCOME_ASK, OUTCOME_REFUSE)
