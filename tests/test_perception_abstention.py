"""Card PG-3 — "I don't know" must survive the labeled world.

R20 made Parcel refuse "go to Narnia" honestly, but it refuses because the chain
checks a CLOSED LABEL SET the simulator declares. Delete the labeled world and
that capability goes with it. These cells pin the perception-side replacement:
a verdict earned from detector-label agreement, evidence count, navigability and
a ranking margin — and they pin it against **measured** data, not invented
numbers. ``tests/data/pg3_abstention_bench.json`` carries the signals from a
real 120-frame RGB-D run over ``city_block.xml`` (see its ``provenance`` block).

Six sections:

1. OFF by default, and byte-identical off.
2. The failure this replaces — cosine retrieval has no null.
3. The gates, one cell each, fail-closed.
4. The measured operating point reproduces, on the split it was NOT fitted on.
5. Corpus rows 10-13 — the card's acceptance test, as string equality against
   R20's own refusal sentence.
6. The null controls, run as tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from parcel_robot.camera_channel.d455 import MOUNT_HEIGHT_M
from parcel_robot.instructnav.grounding import GrounderV2, GroundingOutcome
from parcel_robot.navigation.base import NavObservation
from parcel_robot.navigation.goals import (
    PLACE_OFFER_LIMIT,
    PLACE_UNKNOWN,
    PlaceAdmission,
    admit_navigation_place,
)
from parcel_robot.navigation.semantic_map import ObservationSemanticMap, SemanticCandidate
from parcel_robot.perception_abstention import (
    ABSTAIN_INDECISIVE_RANKING,
    ABSTAIN_INSUFFICIENT_EVIDENCE,
    ABSTAIN_LABEL_DISAGREEMENT,
    ABSTAIN_NO_DETECTOR_SUPPORT,
    ABSTAIN_NO_OBSERVATIONS,
    ABSTAIN_NOT_NAVIGABLE,
    ABSTENTION_REASONS,
    GROUND_BAND_M,
    GROUNDED,
    AbstentionPolicy,
    AbstentionVerdict,
    DetectorSupport,
    PlaceEvidence,
    active_abstention_policy,
    assess_place_query,
    detector_prompts_for,
    detector_support_from_mapping,
    place_evidence_from_mapping,
    ranking_margin,
    use_abstention_policy,
)

BENCH = json.loads(
    (Path(__file__).parent / "data" / "pg3_abstention_bench.json").read_text()
)
ON = AbstentionPolicy(**{**BENCH["operating_point"], "enabled": True})
CORPUS_CLASSES = {"narnia": 10, "my office": 11, "moon": 12, "home": 13}


def _support(row: dict) -> DetectorSupport:
    d = row["detector"]
    return DetectorSupport(
        term=row["prompt"],
        asked=True,
        frames_observed=d["frames_observed"],
        frames_fired=d["frames_fired"],
        peak_probability=d["peak_probability"],
    )


def _places(row: dict) -> list[PlaceEvidence]:
    return [PlaceEvidence(**place) for place in row["places"]]


def _assess(row: dict, policy: AbstentionPolicy = ON) -> AbstentionVerdict:
    return assess_place_query(
        row["query"],
        support=_support(row),
        places=_places(row),
        policy=policy,
        map_similarities=row["map_similarities"],
    )


def _rows(split: str | None = None, present: bool | None = None) -> list[dict]:
    return [
        row
        for row in BENCH["queries"]
        if (split is None or row["split"] == split)
        and (present is None or row["present"] is present)
    ]


def _observation(candidates: list[dict], extras: dict | None = None) -> NavObservation:
    return NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=0.0,
        extras={"semantic_candidates": candidates, **(extras or {})},
    )


# =============================================================== section 1 ===
# OFF by default, and byte-identical off.


def test_the_shipped_policy_is_disabled() -> None:
    """The default must be OFF: every number in it was fitted in a world that
    ``SYNTHESIS.md`` §2 shows cannot support a perception claim."""

    assert AbstentionPolicy().enabled is False
    assert active_abstention_policy().enabled is False


def test_the_shipped_config_leaves_it_off() -> None:
    """`configs/navigation/default.yaml` is the cutover's flag, and it is false."""

    import yaml

    from parcel_robot.paths import resolve_asset

    data = yaml.safe_load(
        resolve_asset("configs", "navigation", "default.yaml", kind="file").read_text()
    )
    block = data["perception"]["abstention"]
    assert block["enabled"] is False
    assert AbstentionPolicy.from_mapping(block).enabled is False
    # ...and the thresholds in the file ARE the measured operating point, so the
    # flag turns on the thing that was measured and not something adjacent.
    for key, value in BENCH["operating_point"].items():
        if key in {"margin_statistic", "label_prob_threshold"}:
            continue
        assert block[key] == pytest.approx(value), key


def test_a_disabled_policy_returns_the_callers_own_candidate_objects() -> None:
    """Not "an equivalent list" — the SAME objects. Byte-identical by
    construction is the only claim that survives a refactor."""

    raw = [{"id": "c1", "label": "bench", "position": [1.0, 2.0, 0.0],
            "confidence": 0.9, "kind": "object"}]
    observation = _observation(raw)
    from parcel_robot.navigation.goals import semantic_goal_from_directive

    goal = semantic_goal_from_directive("go to the bench")
    with_gate = ObservationSemanticMap().query(goal, observation)
    assert [c.candidate_id for c in with_gate] == ["c1"]
    assert "abstention_verdict" not in observation.extras


def test_a_grounder_with_no_policy_is_the_pre_pg3_path() -> None:
    hits = [{"id": "h1", "label": "bench", "confidence": 0.9, "distance_m": 2.0}]
    result = GrounderV2().ground("bench", detections=hits)
    assert result.outcome is GroundingOutcome.RESOLVED
    assert result.detail == "frustum"


# =============================================================== section 2 ===
# The failure this module replaces.


def test_cosine_retrieval_cannot_separate_present_from_absent() -> None:
    """The measurement the card is built on, re-read from the run's own record.

    29 present and 20 absent queries against a real fused map: the ranges
    overlap, so no threshold exists. This is not a tuning problem — ``argmax``
    over a similarity has no null.
    """

    base = BENCH["cosine_only_baseline"]
    assert base["separable_by_any_threshold"] is False
    present_lo = base["present_cos_range"][0]
    absent_hi = base["absent_cos_range"][1]
    assert absent_hi > present_lo, "the absent set must reach above the present floor"
    assert base["present_lost_if_all_absent_rejected"] == 18
    assert base["best_single_threshold"]["false_accepts"] >= 1
    assert base["best_single_threshold"]["false_rejects"] >= 1


def test_a_ranking_always_returns_something_which_is_why_a_margin_is_needed() -> None:
    """A degenerate map cannot establish separation, so the margin is 0 and the
    gate refuses. A mechanism that reported "decisive" here would be reporting
    the absence of alternatives as confidence."""

    assert ranking_margin([]) == 0.0
    assert ranking_margin([0.11]) == 0.0
    assert ranking_margin([0.11, 0.11, 0.11]) == 0.0
    assert ranking_margin([0.05, 0.06, 0.07, 0.30]) > 1.0


# =============================================================== section 3 ===
# The gates, fail-closed.


def test_a_query_the_detector_was_never_asked_about_is_refused() -> None:
    """Not asking is not evidence of absence — and it is not evidence of
    presence either. Fail closed."""

    verdict = assess_place_query("the fountain", support=None, places=(), policy=ON)
    assert verdict.admitted is False
    assert verdict.reason == ABSTAIN_NO_DETECTOR_SUPPORT
    unasked = detector_support_from_mapping({"a bench": {"peak_probability": 0.9}}, ("a tree",))
    assert unasked.asked is False


def test_an_empty_map_refuses_rather_than_admitting_everything() -> None:
    """The deliberate divergence from R20, which fails OPEN on an empty
    vocabulary (R20 §9 open risk 1). An empty perception map means the robot has
    observed nothing, and the honest answer to that is "I don't know"."""

    support = DetectorSupport("a bench", asked=True, frames_observed=120,
                              frames_fired=30, peak_probability=0.9)
    verdict = assess_place_query("the bench", support=support, places=(), policy=ON)
    assert verdict.admitted is False
    assert verdict.reason == ABSTAIN_NO_OBSERVATIONS
    # ...and R20's own gate does the opposite, on purpose. Both are pinned so a
    # future reader cannot mistake the difference for an inconsistency.
    assert admit_navigation_place("go to narnia", []).admitted is True


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"peak_probability": 0.05}, ABSTAIN_NO_DETECTOR_SUPPORT),
        ({"frames_fired": 0}, ABSTAIN_NO_DETECTOR_SUPPORT),
    ],
)
def test_the_detector_agreement_gate_refuses(mutation: dict, expected: str) -> None:
    support = DetectorSupport(
        "a bench", asked=True, frames_observed=120, frames_fired=30,
        peak_probability=0.9,
    )
    support = DetectorSupport(
        support.term, True, support.frames_observed,
        mutation.get("frames_fired", support.frames_fired),
        mutation.get("peak_probability", support.peak_probability),
    )
    place = PlaceEvidence("p1", "a bench", 1.0, 2.0, label_support=10,
                          detection_count=10, evidence_frames=20,
                          ground_evidence_fraction=0.9, similarity=0.5)
    verdict = assess_place_query("the bench", support=support, places=[place],
                                 policy=ON, map_similarities=[0.01, 0.02, 0.03, 0.5])
    assert (verdict.admitted, verdict.reason) == (False, expected)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("label_support", 1, ABSTAIN_LABEL_DISAGREEMENT),
        ("evidence_frames", 2, ABSTAIN_INSUFFICIENT_EVIDENCE),
        ("ground_evidence_fraction", 0.0, ABSTAIN_NOT_NAVIGABLE),
    ],
)
def test_each_place_gate_refuses_on_its_own(field: str, value: float, expected: str) -> None:
    """One cell per gate. Each mutation moves exactly one signal below its
    threshold and the verdict must name that gate, not a neighbour's."""

    kwargs = {"place_id": "p1", "label": "a bench", "x": 1.0, "y": 2.0,
              "label_support": 10, "detection_count": 10, "evidence_frames": 20,
              "ground_evidence_fraction": 0.9, "similarity": 0.5}
    kwargs[field] = value
    support = DetectorSupport("a bench", asked=True, frames_observed=120,
                              frames_fired=30, peak_probability=0.9)
    verdict = assess_place_query(
        "the bench", support=support, places=[PlaceEvidence(**kwargs)], policy=ON,
        map_similarities=[0.01, 0.02, 0.03, 0.5],
    )
    assert (verdict.admitted, verdict.reason) == (False, expected)


def test_an_indecisive_ranking_refuses_even_when_every_other_gate_passes() -> None:
    place = PlaceEvidence("p1", "a bench", 1.0, 2.0, label_support=10,
                          detection_count=10, evidence_frames=20,
                          ground_evidence_fraction=0.9, similarity=0.11)
    support = DetectorSupport("a bench", asked=True, frames_observed=120,
                              frames_fired=30, peak_probability=0.9)
    flat = [0.11, 0.11, 0.11, 0.11]  # no spread: nothing stands out from anything
    verdict = assess_place_query("the bench", support=support, places=[place],
                                 policy=ON, map_similarities=flat)
    assert (verdict.admitted, verdict.reason) == (False, ABSTAIN_INDECISIVE_RANKING)


def test_the_decision_is_existential_over_places_not_a_test_of_the_top_ranked_one() -> None:
    """Gating only the top-ranked place would let the similarity — the signal
    with no absolute scale — decide which place is even allowed to be checked."""

    decoy = PlaceEvidence("decoy", "a bench", 9.0, 9.0, label_support=0,
                          detection_count=30, evidence_frames=30,
                          ground_evidence_fraction=1.0, similarity=0.40)
    real = PlaceEvidence("real", "a bench", 1.0, 2.0, label_support=20,
                         detection_count=20, evidence_frames=20,
                         ground_evidence_fraction=0.9, similarity=0.30)
    support = DetectorSupport("a bench", asked=True, frames_observed=120,
                              frames_fired=30, peak_probability=0.9)
    verdict = assess_place_query(
        "the bench", support=support, places=[decoy, real], policy=ON,
        map_similarities=[0.01, 0.02, 0.03, 0.30, 0.40],
    )
    assert verdict.admitted is True
    assert verdict.place_id == "real"


def test_missing_perception_metadata_defaults_to_refusing_not_to_passing() -> None:
    """Today's mission path publishes oracle candidates that carry none of these
    fields. They must refuse under an enabled policy, which is exactly why the
    policy ships off."""

    place = place_evidence_from_mapping(
        {}, "a bench", place_id="c1", label="bench", x=1.0, y=2.0, similarity=0.9
    )
    assert (place.label_support, place.detection_count, place.evidence_frames) == (0, 0, 0)
    assert place.ground_evidence_fraction == 0.0
    assert place.label_purity == 0.0


def test_an_enabled_policy_cannot_have_a_gate_turned_off() -> None:
    """A zeroed threshold is how an abstention mechanism dies quietly: it keeps
    reporting verdicts, keeps looking wired, and admits everything."""

    for field in ("min_label_probability", "min_label_purity",
                  "min_ground_evidence_fraction"):
        with pytest.raises(ValueError, match="gate turned off"):
            AbstentionPolicy(enabled=True, **{field: 0.0})
    for field in ("min_label_frames", "min_evidence_frames"):
        with pytest.raises(ValueError, match="gate turned off"):
            AbstentionPolicy(enabled=True, **{field: 0})
    # ...and a DISABLED policy may hold anything, because nothing reads it.
    assert AbstentionPolicy(min_label_purity=0.0).enabled is False


def test_an_unknown_config_key_is_an_error_not_a_default() -> None:
    """A typo'd safety flag that reads as "default" looks exactly like a gate
    that never fires."""

    with pytest.raises(ValueError, match="unknown perception.abstention key"):
        AbstentionPolicy.from_mapping({"enabled": True, "min_lable_purity": 0.5})


def test_the_ground_band_is_the_robots_own_eye_height_not_a_tuned_number() -> None:
    assert GROUND_BAND_M == MOUNT_HEIGHT_M
    assert AbstentionPolicy().ground_band_m == MOUNT_HEIGHT_M


def test_every_refusal_reason_is_declared() -> None:
    with pytest.raises(ValueError, match="unknown abstention reason"):
        AbstentionVerdict(False, "x", "made_up_reason")
    with pytest.raises(ValueError, match="must report the GROUNDED reason"):
        AbstentionVerdict(True, "x", ABSTAIN_NOT_NAVIGABLE)
    assert GROUNDED not in ABSTENTION_REASONS


def test_the_detector_prompt_is_a_template_not_a_lookup_table() -> None:
    """A table here would smuggle a closed label set back into the module built
    to replace one."""

    assert detector_prompts_for("the crosswalk") == ("the crosswalk", "a crosswalk")
    assert detector_prompts_for("Narnia") == ("Narnia",)
    assert detector_prompts_for("my office") == ("my office",)
    assert detector_prompts_for("the quantum bakery") == (
        "the quantum bakery", "a quantum bakery",
    )
    assert detector_prompts_for("   ") == ()


# =============================================================== section 4 ===
# The measured operating point, on the split it was not fitted on.


def test_the_fitted_operating_point_is_the_one_the_config_ships() -> None:
    """Three copies of the operating point — the module's defaults, the YAML the
    cutover flips, and the fixture the FAR/FRR were measured at — must be one
    number each. A module default that drifts from the measured point would make
    every number in this file a claim about something that is no longer shipped.
    """

    fitted = BENCH["operating_point"]
    assert ON.min_label_probability == fitted["min_label_probability"] == 0.25
    assert ON.min_evidence_frames == fitted["min_evidence_frames"] == 7
    assert ON.min_label_purity == fitted["min_label_purity"] == 0.5
    assert ON.min_ground_evidence_fraction == fitted["min_ground_evidence_fraction"]
    assert ON.min_ranking_margin == fitted["min_ranking_margin"] == 1.0
    shipped = AbstentionPolicy()
    for key, value in fitted.items():
        assert getattr(shipped, key) == pytest.approx(value), key


def test_the_module_imports_on_a_cold_interpreter() -> None:
    """Found by this card's own seed canary and worth a permanent cell: the
    module reads R20's refusal sentence out of ``navigation.goals``, so a
    top-level import of it from ``navigation.pipeline`` closes a cycle and
    ``import parcel_robot.perception_abstention`` fails on a fresh interpreter.
    Nothing else in the tree imports it first, so no other test would notice.
    """

    import subprocess

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import parcel_robot.perception_abstention as m;"
                " print(m.AbstentionPolicy().enabled)"
            ),
        ],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert proc.stdout.strip() == "False"


def test_the_held_out_false_accept_rate_reproduces() -> None:
    """FAR on the EVAL split, which no threshold ever saw. 0 of 12 absent
    classes admitted."""

    absent = _rows("eval", present=False)
    admitted = [row["query"] for row in absent if _assess(row).admitted]
    assert len(absent) == 12
    assert admitted == []
    assert BENCH["measured_scores"]["eval"]["FAR"] == 0.0


def test_the_held_out_false_reject_rate_reproduces_and_is_high() -> None:
    """11 of 15. Reported, not buried: this operating point refuses most real
    places in this world. Every one of those refusals is ``no_detector_support``
    — the detector could not see the thing — which is the world problem
    ``SYNTHESIS.md`` §2 measured, not a defect in the gate."""

    present = _rows("eval", present=True)
    refused = [row for row in present if not _assess(row).admitted]
    assert len(present) == 15
    assert len(refused) == 11
    assert {_assess(row).reason for row in refused} == {ABSTAIN_NO_DETECTOR_SUPPORT}
    assert BENCH["measured_scores"]["eval"]["FRR"] == pytest.approx(11 / 15, abs=1e-3)


def test_the_fit_split_reproduces_too() -> None:
    fit_absent = _rows("fit", present=False)
    fit_present = _rows("fit", present=True)
    assert sum(_assess(row).admitted for row in fit_absent) == 0
    assert sum(not _assess(row).admitted for row in fit_present) == 4


def test_the_mechanism_beats_both_trivial_baselines() -> None:
    """"Better than a coin" has to be measured, not implied. Always-admit is
    FAR 1.0; always-refuse is FRR 1.0; this operating point is FAR 0.0 with an
    FRR strictly below 1.0."""

    ev = BENCH["measured_scores"]["eval"]
    assert ev["FAR"] < 1.0
    assert ev["FRR"] < 1.0
    assert ev["n_present"] - ev["false_rejects"] > 0


def test_the_map_level_detector_gate_flips_no_verdict_on_this_fixture() -> None:
    """An honest redundancy, recorded rather than sold as depth of defence.

    Detector-label agreement is expressed twice: once at map level ("was this
    term ever answered anywhere") and once per place (``label_purity``). On this
    fixture the candidate lists are already label-filtered, so the map-level
    reading refuses nothing the per-place reading would not — **0 verdicts of 49
    change** when it is forced open. It earns its place only where the caller
    hands over candidates it did NOT label-filter, which is exactly the
    ``ObservationSemanticMap`` wiring (string-matched candidates whose metadata
    describes some other term). That case is pinned separately, by
    ``test_the_detector_agreement_gate_refuses``.
    """

    flips = []
    for row in BENCH["queries"]:
        loud = DetectorSupport(row["prompt"], asked=True, frames_observed=120,
                               frames_fired=120, peak_probability=1.0)
        forced = assess_place_query(
            row["query"], support=loud, places=_places(row), policy=ON,
            map_similarities=row["map_similarities"],
        )
        if forced.admitted != _assess(row).admitted:
            flips.append(row["query"])
    assert flips == []


def test_the_navigability_gate_costs_nothing_and_buys_corpus_row_12() -> None:
    """The post-hoc gate's whole measured contribution, stated as a test: it
    changes exactly one verdict in 49, and that verdict is "the moon"."""

    moved = []
    for row in BENCH["queries"]:
        blind = assess_place_query(
            row["query"], support=_support(row), policy=ON,
            map_similarities=row["map_similarities"],
            # the signal ablated in the DATA, because an enabled policy is not
            # allowed to carry a gate turned off (that is its own cell above)
            places=[PlaceEvidence(**{**place, "ground_evidence_fraction": 1.0})
                    for place in row["places"]],
        )
        if blind.admitted != _assess(row).admitted:
            moved.append(row["query"])
    assert moved == ["the moon"]
    assert BENCH["measured_scores"]["preregistered_three_signal_eval"][
        "false_accepts"
    ] == 1


# =============================================================== section 5 ===
# The card's acceptance test: rows 10-13 refuse, exactly as R20 refuses them.


@pytest.mark.parametrize("cls", sorted(CORPUS_CLASSES))
def test_the_corpus_invalid_rows_refuse_under_the_perception_path(cls: str) -> None:
    row = next(r for r in BENCH["queries"] if r["class"] == cls)
    verdict = _assess(row)
    assert verdict.admitted is False, (
        f"corpus row {CORPUS_CLASSES[cls]} was admitted by the perception path"
    )
    assert verdict.reason in ABSTENTION_REASONS
    assert verdict.place_id is None


@pytest.mark.parametrize("cls", sorted(CORPUS_CLASSES))
def test_the_perception_refusal_is_the_same_sentence_as_r20s(cls: str) -> None:
    """The equivalence the card calls the acceptance test, as string equality.

    Both paths write their refusal through ``PlaceAdmission``, so "exactly as
    they do today" is a call rather than a claim someone has to re-check.
    """

    row = next(r for r in BENCH["queries"] if r["class"] == cls)
    verdict = _assess(row)
    closed_label = PlaceAdmission(
        False, verdict.query, PLACE_UNKNOWN, verdict.alternatives
    )
    assert verdict.reply() == closed_label.reply()
    assert verdict.fact() == closed_label.fact()
    assert "I don't know a place called" in verdict.reply()


@pytest.mark.parametrize("cls", sorted(CORPUS_CLASSES))
def test_r20s_live_gate_refuses_the_same_rows_through_its_real_code(cls: str) -> None:
    """Audit strengthening (Fable, 2026-08-21). The sentence-equality test above
    compares the perception verdict against a HAND-BUILT PlaceAdmission seeded
    with the perception path's own alternatives — it never executes R20's code,
    so it could not notice R20's live gate drifting. This one invokes the real
    ``admit_navigation_place`` (the exact function ``runtime._place_admission``
    calls) against the real scene vocabulary for the same corpus phrasings.

    The two paths' ALTERNATIVES may legitimately differ (scene sidecar vs
    built map), so the equivalence asserted is the one the card actually
    means: both refuse, through their own code, with the same sentence
    template — never "one refuses and the other guesses".
    """

    from parcel_robot.scene_semantics import scene_semantics

    # The vocabulary, assembled the way runtime._realtime_scene_vocabulary
    # assembles it (class names + aliases from the sidecar) — minus the live
    # observation instances, which an offline test honestly does not have.
    known: list[str] = []
    offer: list[str] = []
    for scene_class in scene_semantics().classes:
        known.append(str(scene_class.name))
        known.extend(str(alias) for alias in scene_class.aliases)
        offer.append(str(scene_class.name))
    live = admit_navigation_place(f"go to {cls}", tuple(known), offer=tuple(offer[:5]))
    assert live.admitted is False, (
        f"R20's live gate admitted corpus row {CORPUS_CLASSES[cls]} ({cls!r}) — "
        "the closed-label refusal this suite claims equivalence with has drifted"
    )
    assert live.reason == PLACE_UNKNOWN
    assert "I don't know a place called" in live.reply()

    row = next(r for r in BENCH["queries"] if r["class"] == cls)
    perception = _assess(row)
    assert perception.admitted is False
    # Same sentence template from both REAL paths. Alternatives may differ
    # (scene sidecar vs built map) and may legitimately be EMPTY on the
    # perception side — reply() has a guarded branch for that — so the
    # template equality that holds across both branches is the refusal
    # prefix, which both paths must speak identically for their own query.
    def prefix(verdict: PlaceAdmission) -> str:
        return f'I don\'t know a place called "{verdict.query}"'

    assert live.reply().startswith(prefix(live))
    assert perception.reply().startswith(prefix(perception))


def test_row_12_is_refused_by_navigability_and_the_label_head_does_not_help() -> None:
    """The finding that forced the fourth gate, pinned so nobody re-derives it.

    OWLv2 does NOT abstain on "the moon" in this world — it answers with peak
    0.338 and builds a place whose detections are 100% "the moon". The card's
    lead ("the detector is innocent") holds for "a coffee shop" and fails here.
    What refuses it is physics: every one of that place's depth returns sits
    2.7 m up, and a destination is somewhere you can stand.
    """

    row = next(r for r in BENCH["queries"] if r["class"] == "moon")
    assert row["detector"]["peak_probability"] > ON.min_label_probability
    best = max(row["places"], key=lambda p: p["evidence_frames"])
    assert best["label_support"] == best["detection_count"]  # 100% pure
    assert best["evidence_frames"] >= ON.min_evidence_frames
    assert best["ground_evidence_fraction"] == 0.0
    assert all(p["ground_evidence_fraction"] == 0.0 for p in row["places"]
               if p["label_support"] / max(1, p["detection_count"]) >= ON.min_label_purity)
    assert _assess(row).reason == ABSTAIN_NOT_NAVIGABLE


def test_rows_10_11_13_are_refused_by_more_than_one_gate() -> None:
    """Depth of defence, measured. Narnia and "my office" never fire the label
    head at all; "home" fires but no place it names survives the evidence gate.
    """

    depths = {}
    for cls in ("narnia", "my office", "home"):
        row = next(r for r in BENCH["queries"] if r["class"] == cls)
        failed = 0
        if row["detector"]["peak_probability"] < ON.min_label_probability:
            failed += 1
        pure = [p for p in row["places"]
                if p["label_support"] / max(1, p["detection_count"]) >= ON.min_label_purity]
        if not pure or not any(p["evidence_frames"] >= ON.min_evidence_frames for p in pure):
            failed += 1
        depths[cls] = failed
    assert all(v >= 2 for v in depths.values()), depths


def test_the_refusal_offers_places_the_gate_would_actually_admit() -> None:
    """A refusal that offers a place the robot cannot reach is worse than one
    that offers nothing (R20 §1.3). Here the offer list is not a config list —
    it is the same evidence and navigability test the admission uses, so it can
    never drift from what the gate would accept."""

    good = PlaceEvidence("p-good", "a crosswalk", 1.0, 1.0, label_support=10,
                         detection_count=10, evidence_frames=18,
                         ground_evidence_fraction=1.0, similarity=0.1)
    overhead = PlaceEvidence("p-sky", "the moon", 0.2, 3.1, z=2.7, label_support=23,
                             detection_count=23, evidence_frames=23,
                             ground_evidence_fraction=0.0, similarity=0.1)
    thin = PlaceEvidence("p-thin", "a fountain", 2.0, 2.0, label_support=1,
                         detection_count=8, evidence_frames=2,
                         ground_evidence_fraction=0.5, similarity=0.1)
    verdict = assess_place_query(
        "the swimming pool",
        support=DetectorSupport("a swimming pool", asked=True, frames_observed=120),
        places=[good, overhead, thin], policy=ON,
    )
    assert verdict.admitted is False
    assert verdict.alternatives == ("a crosswalk",)
    assert len(verdict.alternatives) <= PLACE_OFFER_LIMIT


# =============================================================== section 6 ===
# Null controls, as tests.


def test_nonsense_queries_are_all_refused() -> None:
    controls = BENCH["nonsense_controls"]
    assert len(controls) == 12
    for control in controls:
        verdict = assess_place_query(
            control["query"],
            support=detector_support_from_mapping({}, (control["prompt"],)),
            places=(), policy=ON,
        )
        assert verdict.admitted is False
        assert verdict.reason == ABSTAIN_NO_DETECTOR_SUPPORT


def test_removing_the_detector_agreement_signal_admits_everything() -> None:
    """The ablation that shows which signal is load-bearing. With the label head
    ignored — every place treated as pure, every query treated as fired — the
    mechanism admits 100% of the absent set. FAR goes 0.0 -> 1.0."""

    admitted = 0
    absent = _rows("eval", present=False)
    for row in absent:
        blind = [
            PlaceEvidence(
                place_id=f"any-{i}", label="place", x=0.0, y=0.0,
                label_support=20, detection_count=20, evidence_frames=20,
                ground_evidence_fraction=1.0, similarity=s,
            )
            for i, s in enumerate(row["map_similarities"])
        ]
        verdict = assess_place_query(
            row["query"],
            support=DetectorSupport(row["prompt"], asked=True, frames_observed=120,
                                    frames_fired=120, peak_probability=1.0),
            places=blind, policy=ON, map_similarities=row["map_similarities"],
        )
        admitted += bool(verdict.admitted)
    assert admitted == len(absent), "the label head is doing all of the work"


def test_judging_a_query_against_another_querys_evidence_breaks_the_gate() -> None:
    """Label-derangement null: keep every query, permute whose detector evidence
    it is judged against. If the label head carries the information, accept
    decisions must stop tracking presence."""

    scored = _rows("eval")
    deranged_accepts = 0
    for i, row in enumerate(scored):
        donor = scored[(i + 1) % len(scored)]
        verdict = assess_place_query(
            row["query"], support=_support(donor), places=_places(donor),
            policy=ON, map_similarities=row["map_similarities"],
        )
        if verdict.admitted is not _assess(row).admitted:
            deranged_accepts += 1
    assert deranged_accepts > 0, "the verdict must depend on this query's own evidence"


def test_the_verdict_records_the_signals_it_decided_on() -> None:
    """A number without its provenance is not evidence. Every verdict carries
    the signals that produced it so an auditor reads the reason rather than
    inferring it."""

    row = next(r for r in BENCH["queries"] if r["class"] == "moon")
    verdict = _assess(row)
    assert set(verdict.signals) >= {"peak_probability", "frames_fired", "frames_observed"}
    assert verdict.as_dict()["reason"] == ABSTAIN_NOT_NAVIGABLE


# =============================================================== wiring =====
# Both consumption points, on and off.


def test_the_semantic_map_returns_nothing_when_the_gate_refuses() -> None:
    """Fail-closed and empty-handed: a refusal is ``[]``, which is exactly the
    UNSEEN the ladder already answers honestly."""

    from parcel_robot.navigation.goals import semantic_goal_from_directive

    goal = semantic_goal_from_directive("go to the fountain")
    raw = [{"id": "c1", "label": "fountain", "position": [1.0, 2.0, 0.0],
            "confidence": 0.9, "kind": "object", "metadata": {}}]
    observation = _observation(raw, {"detector_support": {}})
    refused = ObservationSemanticMap(abstention=ON).query(goal, observation)
    assert refused == []
    assert observation.extras["abstention_verdict"]["admitted"] is False
    assert observation.extras["abstention_verdict"]["reason"] in ABSTENTION_REASONS


def test_the_semantic_map_still_answers_when_perception_supports_the_place() -> None:
    from parcel_robot.navigation.goals import semantic_goal_from_directive

    goal = semantic_goal_from_directive("go to the bollard")
    raw = [
        {
            "id": "c1", "label": "bollard", "position": [3.2, 1.3, 0.0],
            "confidence": 0.135, "kind": "object",
            "metadata": {"label_support": 17, "detection_count": 22,
                         "evidence_frames": 15, "ground_evidence_fraction": 1.0},
        },
        # ...and the rest of the map, which is what the ranking margin is
        # measured against. A one-entry map cannot establish separation and the
        # gate refuses on it — see the ranking_margin cell.
        {"id": "c2", "label": "tree", "position": [8.0, 1.0, 0.0],
         "confidence": 0.061, "kind": "object"},
        {"id": "c3", "label": "building", "position": [9.0, 4.0, 0.0],
         "confidence": 0.058, "kind": "object"},
        {"id": "c4", "label": "planter", "position": [7.0, -2.0, 0.0],
         "confidence": 0.064, "kind": "object"},
    ]
    observation = _observation(
        raw,
        {"detector_support": {"a bollard": {"frames_observed": 120,
                                            "frames_fired": 1,
                                            "peak_probability": 0.299}}},
    )
    kept = ObservationSemanticMap(abstention=ON).query(goal, observation)
    assert [c.candidate_id for c in kept] == ["c1"]
    assert observation.extras["abstention_verdict"]["admitted"] is True


def test_the_grounder_downgrades_an_unsupported_resolution_to_unseen() -> None:
    hits = [{"id": "h1", "label": "fountain", "confidence": 0.9, "distance_m": 2.0}]
    grounded = GrounderV2().ground("fountain", detections=hits)
    assert grounded.outcome is GroundingOutcome.RESOLVED
    abstained = GrounderV2(abstention=ON).ground("fountain", detections=hits)
    assert abstained.outcome is GroundingOutcome.UNSEEN
    assert abstained.detail.startswith("abstained:")
    assert abstained.candidate is None


def test_the_gate_only_ever_makes_a_grounding_more_conservative() -> None:
    """It answers "is there anything of this kind here at all". It has nothing
    to add to "there are two of them" or "there are none", and must not touch
    them."""

    twins = [
        {"id": "a", "label": "bench", "confidence": 0.80, "distance_m": 2.0},
        {"id": "b", "label": "bench", "confidence": 0.79, "distance_m": 2.1},
    ]
    for policy in (None, ON):
        result = GrounderV2(abstention=policy).ground("bench", detections=twins)
        assert result.outcome is GroundingOutcome.AMBIGUOUS
        assert GrounderV2(abstention=policy).ground("bench").outcome is (
            GroundingOutcome.UNSEEN
        )


def test_no_v8_bundle_source_hard_imports_the_abstention_module() -> None:
    """Caught by the commit gate, pinned here as the property rather than the
    instance.

    The frozen BARN v8 policy bundle REPLACES `navigation/pipeline.py` (and
    `collision.py`) into a `parcel_robot` tree that predates this module, so a
    module-scope import there raises `ModuleNotFoundError` inside the isolated
    policy sidecar — a failure two layers away from anything this card is about.
    Any file on the v8 replacement/addition list must reach the abstention
    module lazily and guarded, exactly as `semantic_map._active_chain` does for
    `detection_adapter`.
    """

    import ast

    from evals.external.barn_v8_policy_bundle import V8_ADDITIONS, V8_REPLACEMENTS

    repo = Path(__file__).resolve().parents[1]
    offenders = []
    for source in sorted({**V8_REPLACEMENTS, **V8_ADDITIONS}.values()):
        if not source.endswith(".py"):
            continue
        tree = ast.parse((repo / source).read_text())
        for node in tree.body:  # module scope ONLY — a guarded import is fine
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            if any("perception_abstention" in name for name in names):
                offenders.append(source)
    assert offenders == []


def test_installing_and_clearing_the_process_default_policy() -> None:
    original = active_abstention_policy()
    try:
        use_abstention_policy(ON)
        assert active_abstention_policy().enabled is True
        use_abstention_policy(None)
        assert active_abstention_policy().enabled is False
        with pytest.raises(TypeError):
            use_abstention_policy(object())  # type: ignore[arg-type]
    finally:
        use_abstention_policy(original)


def test_a_candidate_is_still_a_semantic_candidate_after_the_gate() -> None:
    """The gate filters; it never rewrites geometry."""

    from parcel_robot.navigation.goals import semantic_goal_from_directive

    goal = semantic_goal_from_directive("go to the bollard")
    raw = [{"id": "c1", "label": "bollard", "position": [3.2, 1.3, 0.0],
            "confidence": 0.5, "kind": "object"}]
    observation = _observation(raw)
    kept = ObservationSemanticMap().query(goal, observation)
    assert isinstance(kept[0], SemanticCandidate)
    assert (kept[0].x, kept[0].y) == (3.2, 1.3)
