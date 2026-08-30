"""Card C5: the product matcher IS MB-1's scorer, and MB-2's arm T proves it.

WHAT THIS FILE HOLDS THE PRODUCT TO
-----------------------------------
:mod:`parcel_robot.realtime.narration_matcher` is a hand port of
``research/20260829/model-b-narration-1/scorer.py``.  A port can drift, and this
one drifting would be worse than useless: MB-2's fact gates are *tautological
with respect to the scorer* (``model-b-contract-2/VERDICT.md`` §2 — "the gate is
the scorer"), so a product matcher that is only approximately the scored one
would carry MB-2's numbers on a vocabulary nobody measured.

So there are three rows, in ascending strength:

1. **the file pin** — ``sha256`` of MB-1's four modules against
   ``model-b-contract-2/mb1_pins.sha256``, the pin parcel-6c's lens asked for
   because the whole ``research/20260829`` tree is untracked and
   ``results.json`` records only ``scorer_id = "mb1-scorer-v1"``;
2. **the vocabulary pin** — every regex, support table, action verb and
   coverage row in the product module compared against the research scorer's,
   pattern string by pattern string.  The file pin says MB-1 did not change;
   this says the PORT did not;
3. **the reproduction** — MB-2's arm T re-run over MB-1's 40-scenario corpus
   with the PRODUCT modules doing the rendering, the checking and the scoring,
   to ``results.json``'s ``arm_T`` row: grounding 1.0, coverage 0.9688, 0
   invented actions, 180 robot turns.

WHAT THE RESEARCH TREE IS STILL USED FOR, AND WHY THAT IS NOT A PRODUCT IMPORT
------------------------------------------------------------------------------
The corpus (``events.py``), the trigger table (``narrate.py``) and the steering
policy (``steer.py``) are imported HERE, in the test, by path.  They decide
WHEN a turn happens and which scenario it happens in — the instrument, not the
subject.  Nothing under ``src/`` imports ``research/`` at runtime, and
``test_speech_acts.py`` asserts that in so many words.  A clone without the
research tree skips these rows with a named reason rather than failing.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from parcel_robot.realtime import narration_matcher as nm
from parcel_robot.realtime import speech_acts as sa

REPO = Path(__file__).resolve().parents[1]
MB1 = REPO / "research/20260829/model-b-narration-1"
MB2 = REPO / "research/20260829/model-b-contract-2"
PINS = MB2 / "mb1_pins.sha256"
RESULTS = MB2 / "results.json"

#: The four MB-1 modules this card's evidence rests on. ``scorer.py`` is the one
#: the card names; the other three decide the corpus and the turn ordering, so a
#: silent change to any of them would move the reproduction just as far.
PINNED_MB1_FILES = ("scorer.py", "narrate.py", "events.py", "steer.py")

#: MB-1's published bands, quoted at ``model-b-contract-2/mb1.py:34``. Hard-coded
#: here for the same reason MB-2 hard-codes them: this is a REPLAY of a frozen
#: run, and a replay that reads today's ``realtime.yaml`` is not a replay.
BANDS = {"max_updates_per_minute": 2, "min_gap_s": 15.0}

#: "A receipt filed this close behind an owner turn belongs to that turn"
#: (``mb1.py:37``, mirrored from MB-1's own ``run.py:run_scenario``).
IMMEDIATE_RECEIPT_S = 0.6


# ------------------------------------------------------------------ fixtures
def skip_unless_research_present() -> None:
    for path in (MB1, MB2, PINS, RESULTS):
        if not path.exists():
            pytest.skip(
                f"MB-1/MB-2 research tree absent ({path.relative_to(REPO)}); the "
                "narration-matcher pin and the arm-T reproduction need the frozen "
                "instrument, which is not part of the shipped package"
            )


def _pins() -> dict[str, str]:
    """``mb1_pins.sha256`` as ``{name: digest}``. The pin file is the authority."""

    rows: dict[str, str] = {}
    for line in PINS.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            rows[parts[1]] = parts[0]
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class _MB1:
    """The three frozen research modules the replay is driven by."""

    events: Any
    narrate: Any
    steer: Any


def _import_mb1() -> _MB1:
    """Put MB-1 on ``sys.path`` and import its corpus, trigger table and steer.

    Exactly what ``model-b-contract-2/mb1.py`` does, spelled out here so this
    file does not import MB-2's shim as well as MB-1's modules.
    """

    for extra in (str(MB1), str(REPO), str(REPO / "src")):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    import events
    import narrate
    import steer

    return _MB1(events=events, narrate=narrate, steer=steer)


def _import_scorer() -> Any:
    _import_mb1()
    import scorer

    return scorer


# ------------------------------------------------------------- the replay
@dataclass
class _Turn:
    role: str
    text: str
    at_s: float
    turn_index: int


@dataclass
class _ScenarioRun:
    scenario_id: str
    turns: list[_Turn]
    verdicts: list[nm.TurnVerdict]
    checks: list[sa.CheckResult]

    @property
    def robot(self) -> list[_Turn]:
        return [turn for turn in self.turns if turn.role == "robot"]


def _clarify_question(mb1: _MB1, decision: Any) -> str:
    """The steering policy's clarify question, or "" when it did not clarify."""

    if decision.decision != mb1.events.STEER_CLARIFY:
        return ""
    return str(decision.question)


def _walk(scenario: Any, *, mb1: _MB1, registry: nm.CapabilityRegistry, places: tuple[str, ...]):
    """MB-2 arm T over one scenario, with the PRODUCT modules doing the work.

    Mirrors ``model-b-contract-2/arms.py:run_scenario`` with ``paraphraser=None``:
    MB-1's ``PlanQueueWhisperer`` decides when a receipt earns a turn, the
    product's :mod:`speech_acts` decides what the turn says, and the product's
    :mod:`narration_matcher` scores it.
    """

    ev = mb1.events
    turns: list[_Turn] = []
    verdicts: list[nm.TurnVerdict] = []
    checks: list[sa.CheckResult] = []
    index = 0
    pq = mb1.narrate.PlanQueueWhisperer(
        max_updates_per_minute=BANDS["max_updates_per_minute"],
        min_gap_s=BANDS["min_gap_s"],
    )
    queue: tuple[Any, ...] = ()

    def _emit_robot(utterance: sa.Utterance, at_s: float) -> None:
        nonlocal index
        text = utterance.text
        turns.append(_Turn("robot", text, at_s, index))
        checks.append(
            sa.check(
                text,
                acts=utterance.acts,
                receipts=scenario.receipts,
                at_s=at_s,
                registry=registry,
                places=places,
                turn_index=index,
            )
        )
        verdicts.append(
            nm.score_turn(
                text,
                receipts=scenario.receipts,
                at_s=at_s,
                registry=registry,
                turn_index=index,
            )
        )
        index += 1

    steps = list(scenario.steps)
    cursor = 0
    while cursor < len(steps):
        step = steps[cursor]
        if isinstance(step, ev.Receipt):
            queue = step.queue
            if pq.decide(step).speak:
                _emit_robot(sa.acts_for_receipt(step), step.t)
            cursor += 1
            continue

        decision = mb1.steer.steer(step.text, queue)
        turns.append(_Turn("owner", step.text, step.t, index))
        index += 1

        reply_at = step.t + 0.01
        folded: list[Any] = []
        ahead = cursor + 1
        while (
            ahead < len(steps)
            and isinstance(steps[ahead], ev.Receipt)
            and steps[ahead].t <= step.t + IMMEDIATE_RECEIPT_S
        ):
            receipt = steps[ahead]
            queue = receipt.queue
            # The ledger must SEE every folded receipt even when the reply
            # swallows it, or the band budget drifts from MB-1's.
            pq.decide(receipt)
            folded.append(receipt)
            reply_at = receipt.t + 0.01
            ahead += 1

        prior = tuple(r for r in scenario.receipts if r.t <= reply_at + 1e-9)
        _emit_robot(
            sa.acts_for_owner_turn(
                keys_turn=bool(step.keys_turn),
                clarify_question=_clarify_question(mb1, decision),
                folded=tuple(folded),
                prior=prior,
            ),
            reply_at,
        )
        cursor = ahead

    return _ScenarioRun(scenario.scenario_id, turns, verdicts, checks)


def _first_robot_after(run: _ScenarioRun, at_s: float) -> _Turn | None:
    for turn in run.turns:
        if turn.role == "robot" and turn.at_s >= at_s - 1e-9:
            return turn
    return None


def _verdict_for(run: _ScenarioRun, turn: _Turn) -> nm.TurnVerdict:
    return run.verdicts[run.robot.index(turn)]


def run_arm_t() -> dict[str, Any]:
    """Arm T over MB-1's whole corpus, aggregated MB-1's way.

    Rates are the mean of the per-scenario rates rounded to four places, which
    is ``scorer.bootstrap_ci``'s point estimate exactly (``scorer.py:757, 766``).
    """

    mb1 = _import_mb1()
    registry = nm.default_registry()
    places = tuple(mb1.events.assert_places_admissible())
    runs = [
        _walk(scenario, mb1=mb1, registry=registry, places=places)
        for scenario in mb1.events.build_corpus()
    ]

    grounded_rates: list[float] = []
    coverage_rates: list[float] = []
    robot_turns = 0
    invented = 0
    claims = 0
    zero_claim = 0
    hedged = 0
    keys_hit = keys_total = 0
    template_pass = 0
    words_max = 0
    texts: list[str] = []

    for run, scenario in zip(runs, mb1.events.build_corpus(), strict=True):
        robot = run.robot
        robot_turns += len(robot)
        texts.extend(turn.text for turn in robot)
        verdicts = run.verdicts
        invented += sum(len(v.invented) for v in verdicts)
        claims += sum(len(v.claims) for v in verdicts)
        zero_claim += sum(1 for v in verdicts if not v.claims)
        hedged += sum(1 for v in verdicts if v.hedged)
        template_pass += sum(1 for c in run.checks if c.ok)
        words_max = max([words_max, *[c.words for c in run.checks]])
        if robot:
            grounded_rates.append(sum(1 for v in verdicts if v.grounded) / len(robot))

        hit = total = 0
        for receipt in scenario.gold_narratable:
            total += 1
            first = _first_robot_after(run, receipt.t)
            if first is None:
                continue
            wanted = nm.COVERAGE_CLAIMS.get(receipt.fact, frozenset())
            if _verdict_for(run, first).claim_classes & wanted:
                hit += 1
        if total:
            coverage_rates.append(hit / total)

        for owner in scenario.owner_turns:
            if not owner.keys_turn:
                continue
            first = _first_robot_after(run, owner.t)
            if first is None:
                continue
            keys_total += 1
            verdict = _verdict_for(run, first)
            stated = nm.INABILITY.search(nm.normalise(first.text)) is not None
            keys_hit += int(nm.CLAIM_PERCEPTION not in verdict.claim_classes and stated)

    return {
        "robot_turns": robot_turns,
        "grounding_turn_rate": round(sum(grounded_rates) / len(grounded_rates), 4),
        "coverage_rate": round(sum(coverage_rates) / len(coverage_rates), 4),
        "invented_actions": invented,
        "claims_per_turn": round(claims / robot_turns, 3),
        "zero_claim_turns": zero_claim,
        "hedge_rate": round(hedged / robot_turns, 4),
        "keys_bar": (keys_hit, keys_total),
        "template_self_check_pass": template_pass,
        "template_words_max": words_max,
        "texts": texts,
    }


# ================================================================ row 1: pins
def test_the_matcher_is_pinned_to_mb1s_frozen_scorer() -> None:
    """``sha256(scorer.py)`` is the value ``mb1_pins.sha256`` records.

    The card's own words: "its test asserts sha256 of
    research/20260829/model-b-narration-1/scorer.py equals the value in
    mb1_pins.sha256".  The three modules that decide the corpus and the turn
    ordering are pinned with it — a changed corpus moves the reproduction just
    as far as a changed matcher, and the pin file already carries them.
    """

    skip_unless_research_present()
    pins = _pins()
    for name in PINNED_MB1_FILES:
        assert name in pins, f"{name} is not pinned in mb1_pins.sha256"
        assert _sha256(MB1 / name) == pins[name], (
            f"{name} no longer matches its pin. Either the frozen instrument "
            "moved (it must not) or this product port is being measured against "
            "a different scorer than the one MB-2 published."
        )
    assert pins["scorer.py"].startswith("e5044a90"), (
        "the scorer pin is not the digest the card names (e5044a90...9bab5)"
    )


# ==================================================== row 2: the vocabulary
def _patterns(pairs) -> dict[str, tuple[str, int]]:
    return {name: (pattern.pattern, pattern.flags) for name, pattern in pairs}


def test_the_ported_vocabulary_is_the_scorers_vocabulary() -> None:
    """Every regex and table in the product module equals the scorer's.

    The file pin says MB-1 did not move.  This says the PORT did not: a claim
    pattern that lost an alternation, or a support table that gained a fact,
    would leave every number in this file intact while quietly changing what
    "grounded" means.
    """

    skip_unless_research_present()
    scorer = _import_scorer()

    assert _patterns(nm.CLAIM_PATTERNS) == _patterns(scorer.CLAIM_PATTERNS)
    assert [name for name, _ in nm.CLAIM_PATTERNS] == [name for name, _ in scorer.CLAIM_PATTERNS]
    assert nm.SUPPORTED_BY == scorer.SUPPORTED_BY
    assert nm.COVERAGE_CLAIMS == scorer._COVERAGE_CLAIM
    assert nm.QUEUE_PENDING_STATUSES == scorer._QUEUE_STATUSES
    assert nm.MATCHER_ID == scorer.SCORER_ID
    for ours, theirs in (
        (nm.HEDGES, scorer.HEDGES),
        (nm.OFFER, scorer.OFFER),
        (nm.INABILITY, scorer.INABILITY),
    ):
        assert (ours.pattern, ours.flags) == (theirs.pattern, theirs.flags)
    assert [(p.pattern, p.flags, tool) for p, tool in nm.ACTION_VERBS] == [
        (p.pattern, p.flags, tool) for p, tool in scorer.ACTION_VERBS
    ]
    assert nm._PUNCT == scorer._PUNCT
    for fact in (
        nm.FACT_ACCEPTED,
        nm.FACT_RUNNING,
        nm.FACT_BLOCKED,
        nm.FACT_COMPLETED,
        nm.FACT_FAILED,
        nm.FACT_CANCELLED,
        nm.FACT_RESUMED,
    ):
        assert fact in _import_mb1().events.FACTS


def test_the_product_scorer_agrees_with_the_research_one_turn_by_turn() -> None:
    """Same sentences, same receipts, same verdicts — claim for claim.

    The aggregate row below could match while individual turns disagreed in
    compensating ways.  This one cannot: every arm-T sentence is scored by both
    implementations and the claim classes, unsupported claims, invented actions
    and hedge verdict are compared one turn at a time.
    """

    skip_unless_research_present()
    scorer = _import_scorer()
    mb1 = _import_mb1()
    registry = nm.default_registry()
    theirs_registry = scorer.default_registry()
    places = tuple(mb1.events.assert_places_admissible())

    compared = 0
    for scenario in mb1.events.build_corpus():
        run = _walk(scenario, mb1=mb1, registry=registry, places=places)
        for turn, ours in zip(run.robot, run.verdicts, strict=True):
            probe = scorer.Turn(
                scenario_id=scenario.scenario_id,
                arm="product-port",
                turn_index=turn.turn_index,
                role="robot",
                text=turn.text,
                at_s=turn.at_s,
                events_so_far=scorer.events_so_far(scenario, turn.at_s),
            )
            theirs = scorer.score_turn(probe, scenario, theirs_registry)
            assert ours.claims == theirs.claims, turn.text
            assert ours.unsupported == theirs.unsupported, turn.text
            assert [i.reason for i in ours.invented] == [
                i.reason for i in theirs.invented
            ], turn.text
            assert ours.grounded == theirs.grounded, turn.text
            assert ours.hedged == theirs.hedged, turn.text
            assert ours.premature == theirs.premature, turn.text
            compared += 1
    assert compared == 180, f"expected MB-2's 180 robot turns, compared {compared}"


# ============================================== row 3: MB-2's arm T, reproduced
def test_mb2_arm_t_reproduces_through_the_product_modules() -> None:
    """The headline acceptance row, verbatim from the card.

    "the arm-T reproduction row in the test equals MB-2's ``results.json``
    ``arm_T`` (grounding 1.0, coverage 0.9688, invented 0, 180 turns)."

    Every sentence is rendered by :mod:`parcel_robot.realtime.speech_acts`,
    checked by its ``check``, and scored by
    :mod:`parcel_robot.realtime.narration_matcher`.  The research tree supplies
    the corpus, the trigger table and the steering policy — WHEN to speak, which
    MB-2's arm T did not change either.
    """

    skip_unless_research_present()
    import json

    published = json.loads(RESULTS.read_text(encoding="utf-8"))["arm_T"]
    measured = run_arm_t()

    assert measured["robot_turns"] == 180 == published["robot_turns"]
    assert measured["grounding_turn_rate"] == 1.0 == published["grounding_turn_rate"]
    assert measured["coverage_rate"] == 0.9688 == published["coverage_rate"]
    assert measured["invented_actions"] == 0 == published["invented_actions"]
    # Rows MB-2 published beside the four the card names. They are the ones that
    # would move first if the port drifted in a way the headline four survive.
    assert measured["claims_per_turn"] == published["claims_per_turn"] == 1.444
    assert measured["zero_claim_turns"] == published["zero_claim_turns"] == 5
    assert measured["hedge_rate"] == published["hedge_rate"] == 0.0
    assert measured["keys_bar"] == (15, 15)
    assert published["bars"]["b5_keys_turn"]["hit"] == 15


def test_every_template_passes_the_contracts_own_checker() -> None:
    """``checker.template_self_check_rate`` 1.0 and ``template_words_max`` 21.

    MB-2 ran the checker over its own templates so the contract's floor is
    measured rather than assumed; the product's checker must reach the same
    verdict on the same 180 sentences, including the ≤ 25-word cap.
    """

    skip_unless_research_present()
    import json

    published = json.loads(RESULTS.read_text(encoding="utf-8"))["arm_T"]["checker"]
    measured = run_arm_t()
    assert measured["template_self_check_pass"] == 180 == published["template_self_check_pass"]
    assert measured["template_words_max"] == 21 == published["template_words_max"]
    assert measured["template_words_max"] <= sa.MAX_WORDS


# ====================================================== the matcher's own rows
def test_a_perception_claim_is_an_invented_action_with_no_camera_on_the_body() -> None:
    """The keys turn, in one assertion: looking is not a thing this body does."""

    registry = nm.default_registry()
    found = nm.find_invented_actions(
        "Let me have a look around for your keys.", turn_index=0, registry=registry
    )
    assert found, "a perception claim must be flagged; the vocabulary has no perceive.* receipt"
    assert any("perceive" in item.reason for item in found)
    assert all(item.disposition == "refused" for item in found)


def test_the_contracts_refusal_sentence_satisfies_the_pre_registered_inability() -> None:
    """The sentence an ungated paraphraser deleted 15/15 still matches M8."""

    text = sa.CAPABILITY_REFUSAL_TEXT[sa.CAP_VISION]
    assert nm.INABILITY.search(nm.normalise(text)) is not None
    assert not nm.find_invented_actions(text, turn_index=0, registry=nm.default_registry())


def test_typographic_punctuation_is_folded_before_any_match() -> None:
    """"I'm headed there now" with a smart quote is still a motion claim."""

    smart = "I’m headed to the bench…"
    assert nm.normalise(smart) == "I'm headed to the bench..."
    assert nm.CLAIM_MOTION in {name for name, _ in nm.extract_claims(smart)}


def test_a_claim_with_no_receipt_behind_it_is_unsupported() -> None:
    """Grounding is a claim about receipts, not about plausibility."""

    ok, why = nm.claim_supported(nm.CLAIM_ARRIVAL, receipts=(), at_s=10.0)
    assert not ok
    assert "completed" in why
    assert nm.claim_supported(nm.CLAIM_PERCEPTION, receipts=(), at_s=0.0) == (
        False,
        "no receipt kind can support this claim",
    )
