"""Card P1-D — ask, don't refuse: the VLM veto and the ADMIT/ASK/REFUSE roster.

Every guard here has a seed named in its docstring: the exact edit that makes it
red. The two the card names by hand — "MAD-zero margin re-introduced" and
"promotion without k agreements" — are
:func:`test_SEED_the_mad_zero_margin_re_introduced_collapses_admission` and
:func:`test_SEED_a_name_promoted_without_k_agreements_is_caught`.

Measured evidence for every number quoted below is in
``scrum/20260822/task_9/P1D_STATUS.md``. Nothing in this file loads a model:
the seat is injected, which is the whole point of the seam.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path

import pytest
import yaml

from parcel_robot.online_map.entries import (
    NAME_DETECTOR_LABEL,
    NAME_PROMOTED,
    NAME_PROMOTION_VISITS,
    NAME_VLM_PROPOSED,
    ProposedName,
)
from parcel_robot.online_map.naming import (
    demote_disagreed_names,
    normalize_proposal,
)
from parcel_robot.perception_abstention import (
    ABSTAIN_INDECISIVE_RANKING,
    ABSTAIN_NO_OBSERVATIONS,
    ABSTAIN_VETO_UNAVAILABLE,
    ABSTAIN_VLM_VETO,
    ABSTENTION_REASONS,
    ASK_ELIGIBLE_REASONS,
    DEFAULT_SIGNALS,
    GROUNDED,
    OUTCOME_ADMIT,
    OUTCOME_ASK,
    OUTCOME_REFUSE,
    REGISTERED_SIGNALS,
    SIGNAL_VLM_VETO,
    VETO_ABSENT,
    VETO_PRESENT,
    VETO_UNAVAILABLE,
    AbstentionPolicy,
    AbstentionVerdict,
    DetectorSupport,
    PlaceEvidence,
    assess_place_query,
)
from parcel_robot.perception_contention import (
    ContentionPolicy,
    ContentionPolicyError,
    PerceptionContentionGuard,
)
from parcel_robot.vlm_veto.runner import (
    LOOP_FORBIDDEN_CALLS,
    ControlLoopViolation,
    VetoRunner,
    clear_control_thread,
    mark_control_thread,
)
from parcel_robot.vlm_veto.verifier import NullVerifier, VetoAnswer, VetoRequest, parse_yes_no

REPO = Path(__file__).resolve().parents[1]
PROTOTYPE_NAV_CONFIG = REPO / "configs/navigation/prototype.yaml"


# ==========================================================================
# helpers
# ==========================================================================


def _place(place_id: str = "p1", label: str = "bench", **kwargs) -> PlaceEvidence:
    fields = {
        "label_support": 10,
        "detection_count": 10,
        "evidence_frames": 9,
        "ground_evidence_fraction": 0.5,
        "similarity": 0.8,
    }
    fields.update(kwargs)
    return PlaceEvidence(place_id=place_id, label=label, x=1.0, y=2.0, **fields)


def _support(term: str = "bench") -> DetectorSupport:
    return DetectorSupport(
        term=term, asked=True, frames_observed=20, frames_fired=12, peak_probability=0.7
    )


def _policy(**kwargs) -> AbstentionPolicy:
    base = {
        "enabled": True,
        "signals": ("label_support", "evidence_count", "vlm_veto"),
        "ask_below_threshold": True,
        "min_evidence_frames": 3,
    }
    base.update(kwargs)
    return AbstentionPolicy(**base)


def _answers(verdict: str, p_yes: float | None = None):
    return lambda _query, _place: VetoAnswer(verdict, p_yes=p_yes, model="stub")


def _prototype_policy() -> AbstentionPolicy:
    data = yaml.safe_load(PROTOTYPE_NAV_CONFIG.read_text(encoding="utf-8"))
    return AbstentionPolicy.from_mapping(data["perception"]["abstention"])


# ==========================================================================
# 1. The three-way outcome
# ==========================================================================


def test_the_shipped_gate_is_still_two_way_and_byte_identical() -> None:
    """FLAG-OFF. Nothing about the default operating point moved.

    SEED: add ``vlm_veto`` to ``DEFAULT_SIGNALS`` — every shipped verdict for a
    query with no seat installed changes, and this goes red on the first line.
    """

    assert SIGNAL_VLM_VETO not in DEFAULT_SIGNALS
    assert SIGNAL_VLM_VETO in REGISTERED_SIGNALS
    assert AbstentionPolicy().ask_below_threshold is False
    # The shipping roster runs the robust z, which needs a real background:
    # four places with spread, exactly as PG-3 fitted it on a cosine map.
    spread = [
        _place("p1", "bench", similarity=0.90),
        _place("p2", "tree", similarity=0.11),
        _place("p3", "door", similarity=0.10),
        _place("p4", "wall", similarity=0.09),
    ]
    verdict = assess_place_query("bench", support=_support(), places=spread)
    assert verdict.outcome == OUTCOME_ADMIT
    assert verdict.admitted is True
    # A default (disabled) policy refusing still reports REFUSE, never ASK.
    empty = assess_place_query("bench", support=_support(), places=[])
    assert empty.outcome == OUTCOME_REFUSE
    assert empty.reason == ABSTAIN_NO_OBSERVATIONS


def test_an_ask_never_authorizes_motion() -> None:
    """The property everything else rests on.

    ``admitted`` is what every caller reads to decide whether a goal may be
    committed. An ASK that also said ``admitted=True`` would authorize the very
    motion it is asking permission for.

    SEED: allow ``AbstentionVerdict(True, ..., outcome=OUTCOME_ASK)`` by deleting
    the two consistency checks in ``__post_init__``.
    """

    verdict = assess_place_query(
        "bench",
        support=_support(),
        places=[_place(evidence_frames=1)],
        policy=_policy(signals=("evidence_count",), min_evidence_frames=7),
    )
    assert verdict.outcome == OUTCOME_ASK
    assert verdict.admitted is False
    assert verdict.asks is True
    assert verdict.question()
    with pytest.raises(ValueError, match="ADMIT"):
        AbstentionVerdict(True, "bench", GROUNDED, outcome=OUTCOME_ASK)
    with pytest.raises(ValueError, match="admitted"):
        AbstentionVerdict(
            False, "bench", ABSTAIN_INDECISIVE_RANKING, outcome=OUTCOME_ADMIT
        )


@pytest.mark.parametrize("reason", sorted(ABSTENTION_REASONS))
def test_only_shortfalls_soften_into_a_question(reason: str) -> None:
    """REFUSE stays REFUSE for the four reasons that are not thresholds.

    ``not_navigable`` is the one worth staring at: it is what refuses corpus row
    12 ("take me to the moon"), and turning it into "want me to go?" would hand
    that row straight back.

    SEED: put ``ABSTAIN_NOT_NAVIGABLE`` into ``ASK_ELIGIBLE_REASONS``.
    """

    softens = reason in ASK_ELIGIBLE_REASONS
    assert softens == (
        reason
        in {
            "label_disagreement",
            "insufficient_evidence",
            "indecisive_ranking",
            # The veto could not be consulted — no seat, no crop, cold seat, or
            # a declined GPU moment. A question, never a refusal, and it has its
            # own reason so the log does not blame the ranking margin.
            "vlm_veto_unavailable",
        }
    ), reason
    assert ABSTAIN_VLM_VETO not in ASK_ELIGIBLE_REASONS
    assert ABSTAIN_NO_OBSERVATIONS not in ASK_ELIGIBLE_REASONS


def test_an_absent_query_refuses_and_is_never_softened() -> None:
    """Row 2's property, in one cell: nothing to ask about is not a question."""

    verdict = assess_place_query(
        "Narnia", support=_support("Narnia"), places=[], policy=_policy()
    )
    assert verdict.outcome == OUTCOME_REFUSE
    assert verdict.reason == ABSTAIN_NO_OBSERVATIONS
    assert verdict.question() == ""
    assert verdict.as_ask() == {}


# ==========================================================================
# 2. The veto
# ==========================================================================


def test_the_veto_is_subtractive_and_never_promotes() -> None:
    """A ``present`` answer cannot rescue a place the evidence gates refused.

    This is the whole safety argument for a 2B model on this path.

    SEED: move the veto call above the evidence loop and admit on ``present``.
    """

    starved = _place(evidence_frames=1)
    verdict = assess_place_query(
        "bench",
        support=_support(),
        places=[starved],
        policy=_policy(min_evidence_frames=7),
        veto=_answers(VETO_PRESENT, 0.99),
    )
    assert verdict.admitted is False
    assert verdict.reason == "insufficient_evidence"


def test_an_absent_veto_refuses_a_place_every_other_gate_admitted() -> None:
    """Evidence of absence. The only subtractive reason in the module.

    SEED: treat ``VETO_ABSENT`` as ``VETO_UNAVAILABLE``.
    """

    admitted = assess_place_query(
        "bench",
        support=_support(),
        places=[_place()],
        policy=_policy(),
        veto=_answers(VETO_PRESENT, 0.98),
    )
    assert admitted.outcome == OUTCOME_ADMIT

    vetoed = assess_place_query(
        "bench",
        support=_support(),
        places=[_place()],
        policy=_policy(),
        veto=_answers(VETO_ABSENT, 0.02),
    )
    assert vetoed.outcome == OUTCOME_REFUSE
    assert vetoed.reason == ABSTAIN_VLM_VETO
    assert vetoed.signals["veto"] == 0.0
    assert vetoed.signals["veto_p_yes"] == pytest.approx(0.02)


def test_an_unavailable_veto_asks_and_never_admits_or_refuses_outright() -> None:
    """No seat, no crop, or a declined GPU moment — the owner gets a question.

    Measured (P1D_STATUS §row 1): with no seat installed the seven-place map
    produces 0 admits and 7 asks; with the real seat it produces 5 admits.

    SEED: return the ADMIT verdict when the veto answers ``unavailable``.
    """

    for veto in (None, _answers(VETO_UNAVAILABLE)):
        verdict = assess_place_query(
            "bench", support=_support(), places=[_place()], policy=_policy(), veto=veto
        )
        assert verdict.outcome == OUTCOME_ASK, veto
        assert verdict.admitted is False
        # Its OWN reason: the ranking margin was fine, the veto simply did not
        # run, and a gate that blames the wrong signal cannot be debugged.
        assert verdict.reason == ABSTAIN_VETO_UNAVAILABLE
        assert verdict.candidate == "bench"
        assert "look" in verdict.question().lower()


def test_a_raising_or_nonsense_veto_is_unavailable_not_an_admission() -> None:
    """A broken seat must not fail open.

    SEED: let the exception propagate, or accept an unregistered verdict string.
    """

    def boom(_query, _place):
        raise RuntimeError("cuda gone")

    for veto in (boom, lambda _q, _p: "maybe", lambda _q, _p: None):
        verdict = assess_place_query(
            "bench", support=_support(), places=[_place()], policy=_policy(), veto=veto
        )
        assert verdict.outcome == OUTCOME_ASK
        assert verdict.admitted is False


def test_selecting_the_veto_without_the_ask_posture_is_a_construction_error() -> None:
    """The two keys cannot drift apart in a config.

    Without the ask posture an unavailable veto is a refusal, which is the 0/18
    this card exists to end — silently, on a host that merely lacks the weights.

    SEED: delete the invariant from ``AbstentionPolicy.__post_init__``.
    """

    with pytest.raises(ValueError, match="ask_below_threshold"):
        AbstentionPolicy(
            enabled=True,
            signals=("label_support", SIGNAL_VLM_VETO),
            ask_below_threshold=False,
        )
    # ...and it is only checked when the policy is ENABLED, because a disabled
    # policy is never consulted.
    AbstentionPolicy(
        enabled=False, signals=("label_support", SIGNAL_VLM_VETO)
    )


def test_the_veto_is_asked_once_per_query_not_once_per_candidate() -> None:
    """GPU time is the budget. Asking about the losers would be re-ranking.

    SEED: move the veto call into the loop body before the gate checks.
    """

    calls: list[str] = []

    def counting(_query, place):
        calls.append(place.place_id)
        return VetoAnswer(VETO_PRESENT, p_yes=0.9)

    places = [_place(f"p{i}", similarity=0.9 - 0.1 * i) for i in range(4)]
    verdict = assess_place_query(
        "bench", support=_support(), places=places, policy=_policy(), veto=counting
    )
    assert verdict.admitted is True
    assert calls == ["p0"]


def test_parse_yes_no_reads_the_first_word_and_nothing_else() -> None:
    """A model that rambled has not answered. Keyword-scraping a hint is worse
    than treating it as unavailable, because it manufactures confidence.

    SEED: fall back to ``"yes" in text``.
    """

    assert parse_yes_no("yes") == "yes"
    assert parse_yes_no("  No.") == "no"
    assert parse_yes_no("Yes, that is a bench") == "yes"
    assert parse_yes_no("I think it might be a bench, yes") is None
    assert parse_yes_no("") is None


# ==========================================================================
# 3. Never in the 10 Hz loop
# ==========================================================================


def test_the_control_loop_calls_no_veto_method() -> None:
    """The structural half, the C-1 way.

    Every measured VLM breaches the 100 ms detector bound WHILE GENERATING, so a
    veto call reachable from the dispatch path is a safety regression wearing a
    perception costume.

    SEED: call ``VetoRunner.veto_for`` from ``RobotRuntime._dispatch_active``.
    """

    from parcel_robot.runtime import RobotRuntime

    for method in (
        RobotRuntime._dispatch_active,
        RobotRuntime._step_navigation,
    ):
        tree = ast.parse(inspect.getsource(method).strip())
        called = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        overlap = called & set(LOOP_FORBIDDEN_CALLS)
        assert not overlap, f"{method.__qualname__} reaches the VLM: {overlap}"


def test_the_runtime_imports_no_veto_module() -> None:
    """The import-level half: the dispatch module must not even know the seat.

    SEED: ``from parcel_robot.vlm_veto import VetoRunner`` at runtime.py's top.
    """

    source = (REPO / "src/parcel_robot/runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert not any(name.startswith("parcel_robot.vlm_veto") for name in imported)


def test_a_veto_requested_on_the_control_thread_raises() -> None:
    """The runtime tripwire. The AST check sees today's call sites; this one
    sees the call site somebody adds tomorrow.

    SEED: delete the ``in_control_thread()`` guard from ``veto_for``.
    """

    runner = VetoRunner(NullVerifier())
    mark_control_thread()
    try:
        with pytest.raises(ControlLoopViolation):
            runner.veto_for("bench", _place())
    finally:
        clear_control_thread()
    # Off the control thread it answers normally.
    assert runner.veto_for("bench", _place()).verdict == VETO_UNAVAILABLE


def test_importing_the_veto_package_loads_no_tensor_library() -> None:
    """A shipping install without the perception extra must not pay for this.

    SEED: move ``import torch`` to ``verifier.py``'s module scope.
    """

    import subprocess
    import sys

    code = (
        "import sys, parcel_robot.vlm_veto as v;"
        "print(any(m in sys.modules for m in ('torch', 'transformers')))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True,
        cwd=REPO,
    )
    assert out.stdout.strip() == "False", out.stdout


# ==========================================================================
# 4. The contention relaxation
# ==========================================================================


def test_the_veto_budget_is_separate_and_the_generation_budget_did_not_move() -> None:
    """PG-1's llama-server refusal is exactly as strict as it was.

    The relaxation is one named, in-process, stream-prioritised generation —
    not a loosening of the cross-process rule the module's argument is about.

    SEED: raise ``DEFAULT_MAX_GENERATION_MS_WHILE_ACTIVE`` above 0.0.
    """

    guard = PerceptionContentionGuard()
    assert guard.policy.max_generation_ms_while_active == 0.0
    with guard.mission_lease("person-yield"):
        assert not guard.try_admit_generation(estimated_ms=10.0).admitted
        assert guard.try_admit_veto(estimated_ms=45.0).admitted


def test_the_veto_budget_cannot_be_made_infinite_or_exceed_the_ttl() -> None:
    """A budget that admits everything is a guard that only looks installed.

    SEED: drop ``veto_budget_ms_while_active`` from the validation loop.
    """

    for bad in (float("inf"), float("nan"), -1.0, 300.0, 1000.0):
        with pytest.raises(ContentionPolicyError):
            ContentionPolicy(veto_budget_ms_while_active=bad)
    ContentionPolicy(veto_budget_ms_while_active=299.0)


def test_an_undeclared_veto_duration_is_refused_while_a_lease_is_held() -> None:
    """Fail-closed exactly where the generation path is.

    SEED: default ``estimated_ms=None`` to the budget.
    """

    guard = PerceptionContentionGuard()
    with guard.mission_lease("person-yield"):
        assert not guard.try_admit_veto(estimated_ms=None).admitted
        assert not guard.try_admit_veto(estimated_ms=299.0).admitted
    assert guard.try_admit_veto(estimated_ms=None).admitted


def test_SEED_a_cold_seat_is_never_admitted_under_a_held_lease() -> None:
    """The card's third named seed, added post-verification.

    A COLD seat has to load 4.4 GB of weights before it can answer — seconds,
    not milliseconds — so a cold call under a held safety lease would blow the
    detection TTL by three orders of magnitude. The runner declares ``inf``
    until the seat has actually answered once, which no finite budget admits,
    and the warm-up is paid at INSTALL where no lease is held.

    SEED: return ``self._seed_estimate_ms`` instead of ``inf`` while cold, or
    move ``warm_up()`` out of ``runner_for`` and let the first veto load.
    """

    class _ColdSeat:
        name = "cold"
        loaded = False

        def load(self) -> None:
            self.loaded = True

        def verify(self, request):
            return VetoAnswer(VETO_PRESENT, p_yes=0.9, latency_ms=42.0, model="cold")

        def describe(self, crop):
            raise AssertionError("not used")

    guard = PerceptionContentionGuard()
    runner = VetoRunner(_ColdSeat(), guard=guard)
    assert runner.estimated_ms == float("inf"), "a cold seat must declare inf"
    with guard.mission_lease("person-yield"):
        assert not guard.try_admit_veto(estimated_ms=runner.estimated_ms).admitted
        answer = runner.veto_for("bench", _place())
    assert answer.verdict == VETO_UNAVAILABLE
    assert runner.stats()["budget_declined"] == 1

    # Warming is refused while a lease is held — the load is the whole problem.
    with guard.mission_lease("person-yield"):
        assert runner.warm_up() is False
    # Off any lease it warms, and THEN it is admitted.
    assert runner.warm_up() is True
    assert runner.estimated_ms < 300.0
    with guard.mission_lease("person-yield"):
        assert guard.try_admit_veto(estimated_ms=runner.estimated_ms).admitted


def test_the_admitted_estimate_is_measured_not_declared() -> None:
    """The budget decides against what this seat costs, not against a constant.

    The card's original draft declared a flat 90 ms forever. An EMA of observed
    latency means a seat that gets slower (a bigger crop, a busier GPU) closes
    its own gate instead of quietly eating the detector's frame budget.

    SEED: pass ``self._seed_estimate_ms`` to ``try_admit_veto``.
    """

    class _Slow:
        name = "slow"
        ms = 10.0

        def load(self) -> None:
            return None

        def verify(self, request):
            return VetoAnswer(VETO_PRESENT, p_yes=0.9, latency_ms=self.ms, model="slow")

        def describe(self, crop):
            raise AssertionError("not used")

    seat = _Slow()
    runner = VetoRunner(seat)
    runner.warm_up()
    for _ in range(20):
        runner.veto_for("bench", _place())
    fast = runner.estimated_ms
    assert 5.0 < fast < 20.0, fast
    seat.ms = 250.0
    for _ in range(20):
        runner.veto_for("bench", _place())
    assert runner.estimated_ms > fast * 5, runner.estimated_ms


def test_warming_up_costs_one_throwaway_answer_not_just_a_load() -> None:
    """Loading is not the whole cold cost; the first generation pays for CUDA
    kernel selection too. Measured: a load-only warm-up left the seat's early
    answers at ~127 ms against a 120 ms budget, so the EMA opened ABOVE the
    budget and the guard began declining vetoes under a lease.

    SEED: drop the throwaway ``verify`` from ``VetoRunner.warm_up``.
    """

    asked: list[str] = []

    class _Seat:
        name = "counting"

        def load(self) -> None:
            return None

        def verify(self, request):
            asked.append(request.noun)
            return VetoAnswer(VETO_PRESENT, p_yes=0.9, latency_ms=41.0, model="c")

        def describe(self, crop):
            raise AssertionError("not used")

    runner = VetoRunner(_Seat())
    assert runner.warm_up() is True
    assert asked == ["warm-up", "warm-up"], asked
    # The throwaway seeded the EMA, so the seat is admitted from its first real
    # call rather than against a constant nobody measured.
    assert runner.estimated_ms == pytest.approx(41.0)


def test_a_declined_gpu_moment_asks_rather_than_refusing() -> None:
    """Contention must never cost the owner a place; it costs a question.

    SEED: return ``VETO_ABSENT`` when the guard declines.
    """

    guard = PerceptionContentionGuard(ContentionPolicy(veto_budget_ms_while_active=1.0))
    runner = VetoRunner(NullVerifier(), guard=guard, estimate_ms=90.0)
    with guard.mission_lease("person-yield"):
        answer = runner.veto_for("bench", _place())
    assert answer.verdict == VETO_UNAVAILABLE
    assert runner.stats()["budget_declined"] == 1


# ==========================================================================
# 5. SEEDS the card names by hand
# ==========================================================================


def test_SEED_the_mad_zero_margin_re_introduced_collapses_admission() -> None:
    """The card's first named seed: put the robust z back on this background.

    C-3 measured 0/18 because ``(top - median) / (1.4826 * MAD)`` is exactly 0.0
    whenever the map's background is one non-zero score among zeros. If a future
    edit restores ``robust_z`` as the prototype estimator, this cell says so.

    Measured (P1D_STATUS §row 1): the ``SEED_robust_z`` arm produces 0 admits on
    the seven-place map where the shipped prototype produces 5.
    """

    prototype = _prototype_policy()
    assert prototype.ranking_margin_mode == "label_strength"

    background = [2.909294, 0.0, 0.0, 0.0]
    seeded = dataclasses.replace(prototype, ranking_margin_mode="robust_z")
    places = [_place("p1", "lamppost", similarity=2.909294)] + [
        _place(f"p{i}", f"other{i}", similarity=0.0) for i in range(2, 5)
    ]
    good = assess_place_query(
        "lamppost",
        support=_support("lamppost"),
        places=places,
        policy=dataclasses.replace(
            prototype, signals=tuple(s for s in prototype.signals if s != "vlm_veto")
        ),
        map_similarities=background,
    )
    assert good.admitted is True, "the label-strength estimator must admit"

    bad = assess_place_query(
        "lamppost",
        support=_support("lamppost"),
        places=places,
        policy=dataclasses.replace(
            seeded, signals=tuple(s for s in seeded.signals if s != "vlm_veto")
        ),
        map_similarities=background,
    )
    assert bad.admitted is False
    assert bad.reason == ABSTAIN_INDECISIVE_RANKING
    assert bad.signals["ranking_margin"] == 0.0


def test_SEED_a_name_promoted_without_k_agreements_is_caught() -> None:
    """The card's second named seed: promotion must need k DISTINCT visits.

    A VLM names places at roughly 82-87 % accuracy in the literature and at
    45 % on P1-D's own textured dev-scene fixture, so a name that reaches
    ``known_places()`` on fewer than k agreements is a wrong name with
    vocabulary rights.

    SEED: lower ``NAME_PROMOTION_VISITS``, or make ``ProposedName.admissible``
    true for ``vlm_proposed``.
    """

    assert NAME_PROMOTION_VISITS == 3
    name = ProposedName(text="yellow cylinder", provenance=NAME_VLM_PROPOSED)
    for visit in range(NAME_PROMOTION_VISITS - 1):
        name = name.with_visit(f"visit-{visit}")
        assert name.admissible is False, f"promoted after {visit + 1} visits"
    name = name.with_visit("visit-2")
    assert name.admissible is True
    assert name.provenance == NAME_PROMOTED

    # Three frames of ONE stare is one visit and promotes nothing.
    stare = ProposedName(text="yellow cylinder", provenance=NAME_VLM_PROPOSED)
    for _ in range(5):
        stare = stare.with_visit("visit-0")
    assert stare.visits == 1
    assert stare.admissible is False


# ==========================================================================
# 6. Vocabulary growth and demotion
# ==========================================================================


def test_a_promoted_name_that_is_contradicted_leaves_known_places() -> None:
    """Demotion on disagreement. Promotion alone would be a ratchet.

    SEED: make ``demote_disagreed_names`` a no-op, or let it keep the
    ``promoted`` provenance when the visit count drops below k.
    """

    entry = _fake_entry()
    promoted = ProposedName(
        text="yellow cylinder",
        provenance=NAME_PROMOTED,
        supporting_visit_ids=("v0", "v1", "v2"),
    )
    entry.names = (ProposedName("bollard", NAME_DETECTOR_LABEL), promoted)
    assert "yellow cylinder" in entry.admissible_names()

    demoted = demote_disagreed_names(entry, agreed="bollard", wall_s=1.0)
    assert demoted == ("yellow cylinder",)
    assert "yellow cylinder" not in entry.admissible_names()
    assert entry.names[-1].provenance == NAME_VLM_PROPOSED
    assert any(row[1] == "name_demoted" for row in entry.history)


def test_the_detector_label_is_never_demoted() -> None:
    """It is the label channel, not a hypothesis. Demoting it would delete the
    map's own index.

    SEED: drop the ``NAME_DETECTOR_LABEL`` exemption.
    """

    entry = _fake_entry()
    entry.names = (ProposedName("bollard", NAME_DETECTOR_LABEL),)
    assert demote_disagreed_names(entry, agreed="post", wall_s=1.0) == ()
    assert entry.admissible_names() == ("bollard",)


def test_an_unpromoted_hypothesis_is_not_demoted() -> None:
    """Measured decision, not a soft one: penalising every unpromoted guess
    turns k=3 into "three visits IN A ROW". On P1-D's 8-object replay that
    reading promoted NOTHING — a vocabulary gate that cannot grow a vocabulary.

    SEED: demote every non-agreed name regardless of standing.
    """

    entry = _fake_entry()
    hypothesis = ProposedName(
        text="yellow cup", provenance=NAME_VLM_PROPOSED, supporting_visit_ids=("v0",)
    )
    entry.names = (ProposedName("bollard", NAME_DETECTOR_LABEL), hypothesis)
    assert demote_disagreed_names(entry, agreed="yellow cylinder", wall_s=1.0) == ()
    assert entry.names[-1].visits == 1


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("a wooden bench", "wooden bench"),
        ("Wooden Bench.", "wooden bench"),
        ("  the   BENCH ", "bench"),
        ("object", ""),
        ("an unidentified object", ""),
        ("I think this is probably a wooden park bench seat", ""),
        ("", ""),
    ],
)
def test_a_proposal_is_normalized_before_the_k_gate_compares_it(
    raw: str, expected: str
) -> None:
    """Normalization IS the gate's tolerance: three correct visits that spell the
    name differently would never agree and nothing would ever be promoted.

    SEED: compare raw strings; or drop the ``_NON_NAMES`` filter and let three
    "object" answers promote a place called ``object``.
    """

    assert normalize_proposal(raw) == expected


def _fake_entry():
    from parcel_robot.online_map.entries import MapEntry, WriterProvenance

    return MapEntry(
        entry_id="e1",
        label="bollard",
        surface_x=1.0,
        surface_y=2.0,
        surface_z=0.3,
        provenance=WriterProvenance(
            session_id="s", seat="t", detector_name="d", scene_id="c"
        ),
        first_seen_wall_s=1.0,
        last_seen_wall_s=2.0,
    )


# ==========================================================================
# 7. Refutation D-R3 — a substring match may never ADMIT
# ==========================================================================


def test_SEED_a_coffee_shop_is_not_admitted_against_a_shop() -> None:
    """Refutation D-R3, routed to this card by the P0 verifier.

    ``_matches`` fell back to substring containment whenever SigLIP-2 weights
    are absent — which is the shipping condition — so ``"a coffee shop"``
    matched a map entry labelled ``shop`` and was ADMITTED on the mission path.
    That is the dangerous direction: the dog sets off, confidently, for a place
    it was not asked to go to.

    SEED: return ``MATCH_ALIAS`` (or a bare ``True``) from the substring branch.
    """

    from parcel_robot.navigation.semantic_map import (
        ADMISSIBLE_MATCHES,
        MATCH_EXACT,
        MATCH_NONE,
        MATCH_SUBSTRING,
        _match_strength,
        _matches,
    )

    assert _match_strength("a coffee shop", "shop", None) == MATCH_SUBSTRING
    assert MATCH_SUBSTRING not in ADMISSIBLE_MATCHES
    # It still PRODUCES a candidate, so the dog can ask about it...
    assert _matches("a coffee shop", "shop", None) is True
    # ...and "tree" ⊂ "street" — the cross-class coincidence R14 already found.
    assert _match_strength("street", "tree", None) == MATCH_SUBSTRING
    # The owner's own phrasing is NOT demoted: "the bench" IS the bench.
    assert _match_strength("the bench", "bench", None) == MATCH_EXACT
    assert _match_strength("a bench", "bench", None) == MATCH_EXACT
    assert _match_strength("Narnia", "bench", None) == MATCH_NONE


def test_a_substring_only_winner_is_downgraded_on_the_mission_path() -> None:
    """The gate half of D-R3: even when every evidence signal passes, a place
    that only matched by spelling does not authorize motion.

    SEED: delete the ``ADMISSIBLE_MATCHES`` check in ``_abstention_filtered``.
    """

    from parcel_robot.navigation.base import NavObservation
    from parcel_robot.navigation.goals import SemanticGoal
    from parcel_robot.navigation.semantic_map import ObservationSemanticMap

    candidate = {
        "id": "shop-1",
        "label": "shop",
        "position": (3.0, 0.0, 0.0),
        "confidence": 0.9,
        "kind": "object",
        "metadata": {
            "label_support": 12,
            "detection_count": 12,
            "evidence_frames": 9,
            "ground_evidence_fraction": 0.5,
        },
    }
    observation = NavObservation(
        position=(0.0, 0.0, 0.0),
        heading_deg=0.0,
        extras={
            "semantic_candidates": [candidate],
            "detector_support": {
                "a coffee shop": {
                    "frames_observed": 20,
                    "frames_fired": 12,
                    "peak_probability": 0.7,
                }
            },
        },
    )
    policy = _policy(
        signals=("label_support", "evidence_count"), ranking_margin_mode="label_strength"
    )
    smap = ObservationSemanticMap(abstention=policy)
    found = smap.query(SemanticGoal(query="a coffee shop", kind="object"), observation)
    assert found == [], "a substring match must not become a goal"
    verdict = observation.extras["abstention_verdict"]
    assert verdict["admitted"] is False
    assert verdict["outcome"] == OUTCOME_ASK
    assert verdict["signals"]["substring_match_only"] == 1.0

    # The control: an EXACT match on the same evidence still admits.
    observation.extras["abstention_verdict"] = None
    exact = smap.query(SemanticGoal(query="shop", kind="object"), observation)
    assert [c.candidate_id for c in exact] == ["shop-1"]


# ==========================================================================
# 8. The overlay
# ==========================================================================


def test_the_prototype_overlay_selects_the_veto_and_the_ask_posture() -> None:
    """The roster is a config change, not a code change — the card's whole
    shape. And it loads: an overlay that names an unknown signal is a hard
    error, so this cell also proves the two spellings agree.

    SEED: remove ``ask_below_threshold`` from the overlay — the policy refuses to
    construct and this goes red at ``from_mapping``.
    """

    policy = _prototype_policy()
    assert policy.enabled is True
    assert SIGNAL_VLM_VETO in policy.signals
    assert policy.ask_below_threshold is True
    assert policy.ranking_margin_mode == "label_strength"
    # The shipped file must NOT have moved.
    default = yaml.safe_load(
        (REPO / "configs/navigation/default.yaml").read_text(encoding="utf-8")
    )
    shipped = AbstentionPolicy.from_mapping(default["perception"]["abstention"])
    assert shipped.enabled is False
    assert SIGNAL_VLM_VETO not in shipped.signals
    assert shipped.ask_below_threshold is False


def test_an_ask_is_carried_in_the_shape_the_hosted_lane_already_speaks() -> None:
    """P0-B's broker answers an unknown place with a structured ask. A verdict
    that is uncertain rather than ignorant travels the same envelope, so the
    model reads one shape and not two.

    SEED: change ``as_ask()``'s keys and the broker's consumer stops finding the
    place name.
    """

    from parcel_robot.realtime.tool_broker import STATUS_UNKNOWN_PLACE

    verdict = assess_place_query(
        "the coffee place",
        support=_support("the coffee place"),
        places=[_place(label="shop")],
        policy=_policy(),
        veto=_answers(VETO_UNAVAILABLE),
    )
    payload = verdict.as_ask()
    assert payload["status"] != STATUS_UNKNOWN_PLACE, "a seen place is not unknown"
    assert set(payload) >= {"status", "tool", "detail", "place", "valid_places", "reason"}
    assert payload["place"] == "the coffee place"
    assert payload["candidate"] == "shop"
    assert payload["detail"] == verdict.question()


def test_a_veto_request_refuses_an_empty_noun_and_bad_bytes() -> None:
    """Validation at the seam, so a malformed request never reaches the GPU.

    SEED: drop the ``__post_init__`` checks.
    """

    with pytest.raises(ValueError, match="noun"):
        VetoRequest(noun="   ")
    with pytest.raises(TypeError, match="crop_png"):
        VetoRequest(noun="bench", crop_png="not bytes")
    with pytest.raises(ValueError, match="probability"):
        VetoAnswer(VETO_PRESENT, p_yes=1.4)
    with pytest.raises(ValueError, match="verdict"):
        VetoAnswer("probably")
