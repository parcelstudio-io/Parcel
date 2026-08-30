"""Card C4 (WHISPER-ACCEPT-1): the plan-acceptance class, and the reroute band.

WHAT THIS FILE PINS
-------------------
MB-1 (``research/20260829/model-b-narration-1``) drove the shipped whisperer
over a 40-scenario receipt corpus and reported two product facts, both verified
at HEAD by parcel-6c:

1. the whisperer had **no class for a plan acceptance** — ``_diff`` turns a
   ``nav_state`` change into ``nav_tick`` (never band, 55 suppressions over the
   corpus) and a ``nav_goal`` change produced nothing at all, so the robot could
   not say "Sure, I'll check the sofa" from any receipt;
2. ``KIND_REROUTE`` was **dead code** — declared, banded ALWAYS, listed
   CRITICAL, given a HINT, exported, and never constructed. Its first
   constructor would therefore have spent past the owner's per-minute cap and
   past the month's ceiling, so its band was a DECISION, not a default.

Every test below is a claim about one of those two, and the two headline claims
an auditor should try hardest to break are:

* :func:`test_a_reissue_of_the_same_plan_is_not_news` — the reason this class is
  fed by a typed executive receipt and not by a ``nav_goal`` string diff. A
  string diff is ``nav_tick`` with a longer period.
* :func:`test_the_off_path_output_over_the_mb1_corpus_is_byte_identical` — the
  digest was computed on the tree BEFORE any edit on this card and is written
  down in ``C4_STATUS.md``. With no receipts, nothing about the whisperer moved.

Time is injected everywhere. Nothing here sleeps, opens a socket, builds a lane
or a runtime, or spends a cent.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from parcel_robot.navigation.social_progress_contracts import (
    SocialBlockCauseV1,
    SocialProgressStateV1,
)
from parcel_robot.realtime.config import WhispererConfig
from parcel_robot.realtime.hosted_budget import (
    CLASS_CRITICAL,
    CLASS_ROUTINE,
    CODE_ENVELOPE_REACHED,
    GovernorConfig,
    HostedCallGovernor,
)
from parcel_robot.realtime.whisperer import (
    ALWAYS_BAND,
    BAND_ALWAYS,
    CRITICAL_KINDS,
    HINTS,
    KIND_BATTERY_STATE,
    KIND_MIN_GAP_S,
    KIND_NAV_TICK,
    KIND_PACE_MISMATCH,
    KIND_PLAN_ACCEPTED,
    KIND_REROUTE,
    LINEAGE_NEW,
    LINEAGE_QUEUE,
    LINEAGE_REVISE,
    MIN_GAP_EXEMPT_KINDS,
    PLAN_ACCEPTED_MIN_GAP_S,
    PLAN_ADMISSION_MEMORY,
    PLAN_LINEAGES,
    REROUTE_PER_MISSION_CAP,
    RULE_BUDGET,
    RULE_CRITICAL_BYPASS,
    RULE_DEDUP,
    RULE_MIN_GAP,
    RULE_NARRATION_FLOOR_REFUSED,
    RULE_PLAN_ACCEPTED_NEEDS_RECEIPT,
    RULE_PLAN_ADMITTED,
    RULE_PLAN_NOT_ADMITTED,
    RULE_PLAN_RECEIPT_INVALID,
    RULE_PLAN_REISSUE,
    RULE_REROUTE_DOOR_WRONG_STATE,
    RULE_REROUTE_MISSION_CAP,
    SOCIAL_STATE_REROUTE,
    PlanAcceptedReceipt,
    RerouteReceipt,
    StateDigest,
    StateEvent,
    Whisperer,
    band_of,
    plan_accepted_event,
    reroute_event,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MB1 = REPO_ROOT / "research" / "20260829" / "model-b-narration-1"

#: The band figures MB-1's published decision ledger was computed under
#: (``RESULTS.md``: "the conservative shipped defaults, not the prototype 6/4").
MB1_MAX_PER_MIN = 2
MB1_MIN_GAP_S = 15.0

#: The prototype configuration's figures, carried so the corpus row can be read
#: at both settings rather than only at the one that starves it.
PROTOTYPE_MAX_PER_MIN = 6
PROTOTYPE_MIN_GAP_S = 4.0

#: **Pinned BEFORE the first edit of card C4**, over MB-1's 40 scenarios with no
#: executive receipts at all: every arm-D decision row (minus ``schema_version``)
#: in corpus order, canonical JSON, SHA-256. Its totals reproduce ``RESULTS.md``
#: exactly — 85 forwarded (65 ``critical_bypass``, 10 ``block_debounce_elapsed``,
#: 10 ``clear_after_forwarded_block``), 65 suppressed (55 ``never_band``,
#: 10 ``block_debounce_holding``).
OFF_PATH_DIGEST = "4e5e2e47d43d3f182260ec9e435a4701861cbf2953f226cea8309f2f9fe03663"


class _Clock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += float(seconds)
        return self.now


def _whisperer(clock: _Clock | None = None, **config) -> tuple[Whisperer, _Clock]:
    clock = clock or _Clock()
    config.setdefault("max_updates_per_minute", 10)
    config.setdefault("min_gap_s", 0.0)
    return Whisperer(config=WhispererConfig(**config), clock=clock), clock


def _rows(whisperer: Whisperer, kind: str) -> list[dict[str, object]]:
    return [row for row in whisperer.decision_rows() if row["kind"] == kind]


def _digest_of(plan: str) -> str:
    """A stand-in for ``ValidatedPlan.plan_sha256``: the plan's own content."""

    return hashlib.sha256(plan.encode("utf-8")).hexdigest()


# =========================================================== the fake executive
@dataclass
class _Admission:
    revision: int
    digest: str


class FakeExecutive:
    """The admission half of ``brain.executive.TaskExecutive``, mirrored.

    Wave A does not touch ``brain/executive.py`` (it is in the owner's
    uncommitted diff), so the two branches ``runtime._accept_plan`` takes are
    reproduced here from the shipped source and nothing else is:

    * ``submit`` — a task id that is absent or terminal is queued; a task id
      that is already active is REJECTED ("submit a higher revision via
      replace()");
    * ``replace`` — a strictly higher revision is activated; a revision that
      does not increase is REJECTED ("replacement revision must increase").

    Note what it does NOT do, because it is the point of
    :func:`test_a_reissue_of_the_same_plan_is_not_news`: ``replace`` compares
    REVISIONS and never plan content, so an identical plan re-submitted at a
    higher revision is ACCEPTED by the executive. The whisperer's re-issue guard
    is the only thing between that and the robot saying "okay, the sofa" twice.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, _Admission] = {}

    def submit(self, *, task_id: str, goal: str, plan: str, revision: int = 1):
        known = self._tasks.get(task_id)
        if known is not None:
            return self._receipt(
                task_id, goal, revision, _digest_of(plan), LINEAGE_NEW,
                accepted=False, disposition="reject",
            )
        self._tasks[task_id] = _Admission(revision, _digest_of(plan))
        return self._receipt(
            task_id, goal, revision, _digest_of(plan), LINEAGE_NEW, disposition="queued"
        )

    def replace(self, *, task_id: str, goal: str, plan: str, revision: int):
        known = self._tasks.get(task_id)
        if known is None:
            return self.submit(task_id=task_id, goal=goal, plan=plan, revision=revision)
        if revision <= known.revision:
            return self._receipt(
                task_id, goal, revision, _digest_of(plan), LINEAGE_REVISE,
                accepted=False, disposition="reject",
            )
        self._tasks[task_id] = _Admission(revision, _digest_of(plan))
        return self._receipt(
            task_id, goal, revision, _digest_of(plan), LINEAGE_REVISE, disposition="queued"
        )

    @staticmethod
    def _receipt(
        task_id: str,
        goal: str,
        revision: int,
        digest: str,
        lineage: str,
        *,
        accepted: bool = True,
        disposition: str = "queued",
    ) -> PlanAcceptedReceipt:
        return PlanAcceptedReceipt(
            task_id=task_id,
            goal_label=goal,
            plan_revision=revision,
            lineage=lineage,
            accepted=accepted,
            disposition=disposition,
            plan_digest=digest,
        )


# ================================================ the class, and what feeds it
def test_a_new_goal_is_acknowledged_once_from_the_executives_own_receipt() -> None:
    """MB-1's finding, closed: there is now a producer for "okay, the sofa"."""

    whisperer, _clock = _whisperer()
    executive = FakeExecutive()

    decision = whisperer.note_plan_accepted(
        executive.submit(task_id="T1", goal="sofa", plan="navigate:sofa")
    )

    assert decision.forwarded is True
    assert decision.kind == KIND_PLAN_ACCEPTED
    assert decision.rule == RULE_PLAN_ADMITTED
    assert decision.band == BAND_ALWAYS
    assert "will go to the sofa" in decision.text
    # The speech act travels with the fact, as it does for every other class.
    assert HINTS[KIND_PLAN_ACCEPTED] in decision.text
    assert len(_rows(whisperer, KIND_PLAN_ACCEPTED)) == 1


def test_a_reissue_of_the_same_plan_is_not_news() -> None:
    """THE bar this card is named for.

    ``replace`` with an identical plan at a higher revision is ACCEPTED by the
    executive — it compares revisions, not content — so without this guard the
    robot acknowledges the same goal twice. Keyed on the plan's identity and not
    on the goal LABEL, because a label is what a ``nav_goal`` string diff would
    have watched, and that is the ``nav_tick`` mistake with a longer period.
    """

    whisperer, clock = _whisperer()
    executive = FakeExecutive()
    first = whisperer.note_plan_accepted(
        executive.submit(task_id="T1", goal="sofa", plan="navigate:sofa")
    )
    assert first.forwarded is True

    clock.advance(120.0)  # well past the dedup TTL: the guard is not the dedup
    again = executive.replace(
        task_id="T1", goal="sofa", plan="navigate:sofa", revision=2
    )
    assert again.accepted is True, "the executive itself does accept the re-issue"

    decision = whisperer.note_plan_accepted(again)

    assert decision.forwarded is False
    assert decision.rule == RULE_PLAN_REISSUE
    assert decision.text == ""
    assert len([row for row in _rows(whisperer, KIND_PLAN_ACCEPTED) if row["forwarded"]]) == 1


def test_a_replacement_the_executive_rejects_says_nothing() -> None:
    whisperer, _clock = _whisperer()
    executive = FakeExecutive()
    whisperer.note_plan_accepted(
        executive.submit(task_id="T1", goal="sofa", plan="navigate:sofa")
    )

    rejected = executive.replace(
        task_id="T1", goal="sofa", plan="navigate:sofa", revision=1
    )
    assert rejected.accepted is False

    decision = whisperer.note_plan_accepted(rejected)

    assert decision.forwarded is False
    assert decision.rule == RULE_PLAN_NOT_ADMITTED


def test_a_revision_fires_and_carries_its_lineage() -> None:
    """A mid-trip correction is different news, and it says so."""

    whisperer, clock = _whisperer()
    executive = FakeExecutive()
    whisperer.note_plan_accepted(
        executive.submit(task_id="T1", goal="sofa", plan="navigate:sofa")
    )
    clock.advance(5.0)

    decision = whisperer.note_plan_accepted(
        executive.replace(task_id="T1", goal="door", plan="navigate:door", revision=2)
    )

    assert decision.forwarded is True
    assert decision.rule == RULE_PLAN_ADMITTED
    assert "instead of what it was doing" in decision.text
    assert "the door" in decision.text
    row = _rows(whisperer, KIND_PLAN_ACCEPTED)[-1]
    assert row["key"] == f"plan_accepted:T1:{_digest_of('navigate:door')}"


def test_the_lineage_vocabulary_carries_the_queue_value_c6_will_produce() -> None:
    """Declared now, unused now. A vocabulary that grows later is one two
    components can disagree about in the meantime."""

    assert PLAN_LINEAGES == {LINEAGE_NEW, LINEAGE_REVISE, LINEAGE_QUEUE}
    queued = PlanAcceptedReceipt(
        task_id="T2", goal_label="bench", lineage=LINEAGE_QUEUE, plan_digest="abc"
    )
    assert "queued the bench" in plan_accepted_event(queued).fact


def test_a_malformed_receipt_is_logged_and_never_raised() -> None:
    """This door is called from the plan-admission path. Narration is a nicety
    and must never be able to take down a plan the owner asked for."""

    whisperer, _clock = _whisperer()

    no_task = whisperer.note_plan_accepted(
        PlanAcceptedReceipt(task_id="", goal_label="sofa")
    )
    bad_lineage = whisperer.note_plan_accepted(
        PlanAcceptedReceipt(task_id="T1", goal_label="sofa", lineage="whatever")
    )

    assert no_task.forwarded is False
    assert no_task.rule == RULE_PLAN_RECEIPT_INVALID
    assert bad_lineage.forwarded is False
    assert bad_lineage.rule == RULE_PLAN_RECEIPT_INVALID


def test_an_empty_goal_label_never_leaves_a_hole_in_the_sentence() -> None:
    """``curiosity_event``'s lesson: a hole in the sentence is what the model
    fills in."""

    event = plan_accepted_event(PlanAcceptedReceipt(task_id="T1", goal_label="   "))

    assert "the place the owner asked for" in event.fact
    assert "{" not in event.fact


def test_the_admission_memory_is_bounded() -> None:
    whisperer, _clock = _whisperer()
    executive = FakeExecutive()
    for index in range(PLAN_ADMISSION_MEMORY + 8):
        whisperer.note_plan_accepted(
            executive.submit(task_id=f"T{index}", goal=f"place {index}", plan=f"p{index}")
        )

    assert len(whisperer._plan_admitted) == PLAN_ADMISSION_MEMORY


# ============================================= the band: caps, ceiling, spacing
def test_the_acceptance_is_not_critical_and_is_dropped_unbilled_at_a_spent_cap() -> None:
    """The card's governor row, at the whisperer's own gate.

    An acknowledgement is not worth spending past the owner's cost knob: if the
    cap is gone the owner has already heard this robot twice inside the minute
    and the plan runs either way. Dropped means ``forwarded=False`` and
    ``text=""`` — the runtime never calls ``_narrate_mission``, so nothing is
    sent and nothing is billed.
    """

    assert KIND_PLAN_ACCEPTED in ALWAYS_BAND
    assert KIND_PLAN_ACCEPTED not in CRITICAL_KINDS
    assert KIND_PLAN_ACCEPTED not in MIN_GAP_EXEMPT_KINDS

    whisperer, clock = _whisperer(max_updates_per_minute=0)
    executive = FakeExecutive()

    decision = whisperer.note_plan_accepted(
        executive.submit(task_id="T1", goal="sofa", plan="navigate:sofa")
    )

    assert decision.forwarded is False
    assert decision.rule == RULE_BUDGET
    assert decision.text == ""
    assert whisperer.forwarded == 0
    del clock


def test_the_hosted_governor_at_zero_refuses_an_acceptance_and_never_a_reroute() -> None:
    """The month's ceiling, at the gate the runtime reads the same set from.

    ``runtime._narrate_mission`` carries ``critical=event.kind in CRITICAL_KINDS``
    into the lane, and ``hosted_budget`` answers a critical call before it reads
    a ledger at all. So this is the same decision as the assertion above, one
    layer out: an acceptance is a ROUTINE call and a $0 envelope refuses it; a
    reroute is CRITICAL and is never governed.
    """

    governor = HostedCallGovernor(
        config=GovernorConfig(envelope_usd=0.0),
        month_to_date=lambda: 0.0,
        day_to_date=lambda: 0.0,
    )

    acceptance = governor.admit(
        "a plan acknowledgement",
        call_class=CLASS_CRITICAL if KIND_PLAN_ACCEPTED in CRITICAL_KINDS else CLASS_ROUTINE,
    )
    reroute = governor.admit(
        "a reroute",
        call_class=CLASS_CRITICAL if KIND_REROUTE in CRITICAL_KINDS else CLASS_ROUTINE,
    )

    assert acceptance.admitted is False
    assert acceptance.code == CODE_ENVELOPE_REACHED
    assert reroute.admitted is True


def test_the_acceptance_has_its_own_min_gap_and_no_other_class_moved() -> None:
    """MB-1's corpus prices the shared number: an acknowledgement lands 2.8-3.1 s
    after the completion before it, and the owner's 15 s spacing would swallow
    every second one in a two-goal trip."""

    assert KIND_MIN_GAP_S == {KIND_PLAN_ACCEPTED: PLAN_ACCEPTED_MIN_GAP_S}
    assert PLAN_ACCEPTED_MIN_GAP_S < 3.0

    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=15.0)
    executive = FakeExecutive()
    whisperer.note_plan_accepted(
        executive.submit(task_id="T1", goal="sofa", plan="navigate:sofa")
    )
    clock.advance(3.0)

    decision = whisperer.note_plan_accepted(
        executive.submit(task_id="T2", goal="bench", plan="navigate:bench")
    )

    assert decision.forwarded is True, "the owner's spacing swallowed an answer"


def test_the_acceptance_is_still_spaced_inside_its_own_gap() -> None:
    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=15.0)
    executive = FakeExecutive()
    whisperer.note_plan_accepted(
        executive.submit(task_id="T1", goal="sofa", plan="navigate:sofa")
    )
    clock.advance(PLAN_ACCEPTED_MIN_GAP_S / 2.0)

    decision = whisperer.note_plan_accepted(
        executive.submit(task_id="T2", goal="bench", plan="navigate:bench")
    )

    assert decision.forwarded is False
    assert decision.rule == RULE_MIN_GAP


# ================================================= the KIND_REROUTE decision
def test_the_reroute_stays_critical_which_is_what_keeps_g3_fixed() -> None:
    """The band decision, recorded as an assertion.

    The bench's disqualifying counterexample IS a reroute ("reroute at t=96 was
    silently dropped because a mission_clear forwarded at t=90 held the 15 s
    min-gap"). In this module the min-gap exemption is the critical set, and
    ``runtime._narrate_mission`` reads the same set for the monthly ceiling, so
    moving reroute out of it would re-open G3 and split "which facts outrank the
    owner's cost knob" into two lists.
    """

    assert KIND_REROUTE in CRITICAL_KINDS
    assert KIND_REROUTE in MIN_GAP_EXEMPT_KINDS
    assert band_of(KIND_REROUTE) == BAND_ALWAYS


def test_a_reroute_is_constructed_from_the_navigators_own_state() -> None:
    """Fed from ``SocialProgressStateV1.REROUTE``, not from a new detector."""

    assert SOCIAL_STATE_REROUTE == SocialProgressStateV1.REROUTE.value

    event = reroute_event(
        RerouteReceipt(
            mission="sofa",
            state=SocialProgressStateV1.REROUTE.value,
            cause=SocialBlockCauseV1.TRUE_DYNAMIC_BLOCK.value,
            blocker_id="track-7",
        )
    )

    assert event.kind == KIND_REROUTE
    assert "taking a different way to the sofa" in event.fact
    assert "because something is blocking" in event.fact
    # A track id is not something to say out loud.
    assert "track-7" not in event.fact
    assert event.detail["blocker_id"] == "track-7"


def test_a_reroute_with_an_unknown_cause_says_nothing_about_the_cause() -> None:
    """R21's discipline: a receipt that cannot name the reason does not guess."""

    event = reroute_event(
        RerouteReceipt(mission="sofa", state=SOCIAL_STATE_REROUTE, cause="not_a_cause")
    )

    assert event.fact.endswith("taking a different way to the sofa.")


def test_the_reroute_door_refuses_a_state_that_is_not_a_reroute() -> None:
    whisperer, _clock = _whisperer()

    decision = whisperer.note_reroute(
        RerouteReceipt(mission="sofa", state=SocialProgressStateV1.SLOW_YIELD.value)
    )

    assert decision.forwarded is False
    assert decision.rule == RULE_REROUTE_DOOR_WRONG_STATE


def test_a_mission_may_announce_three_reroutes_and_no_more() -> None:
    """The cap, and the arithmetic behind it.

    A reroute is fed from a policy STATE the navigator can re-enter whenever an
    alternate route appears, and the only thing under it is the 20 s critical
    dedup: unbounded, a 10-minute trip could announce ~30 of them PAST the
    month's ceiling. Three admits a real re-plan sequence and bounds the bypass.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=1, min_gap_s=15.0)
    forwarded = 0
    for _ in range(REROUTE_PER_MISSION_CAP + 4):
        clock.advance(30.0)  # past the 20 s critical dedup every time
        decision = whisperer.note_reroute(
            RerouteReceipt(mission="sofa", state=SOCIAL_STATE_REROUTE),
            now=clock.now,
        )
        forwarded += int(decision.forwarded)

    assert forwarded == REROUTE_PER_MISSION_CAP
    over = [
        row
        for row in _rows(whisperer, KIND_REROUTE)
        if row["rule"] == RULE_REROUTE_MISSION_CAP
    ]
    assert len(over) == 4
    assert all(row["text"] == "" for row in over), "a capped reroute was still composed"
    # Under the cap it really is the bypass, spent by a spent-cap whisperer.
    assert whisperer.forwarded_by_rule[RULE_CRITICAL_BYPASS] == REROUTE_PER_MISSION_CAP


def test_a_second_reroute_inside_the_critical_dedup_is_one_piece_of_news() -> None:
    whisperer, clock = _whisperer()
    first = whisperer.note_reroute(
        RerouteReceipt(mission="sofa", state=SOCIAL_STATE_REROUTE), now=clock.now
    )
    clock.advance(5.0)
    second = whisperer.note_reroute(
        RerouteReceipt(mission="sofa", state=SOCIAL_STATE_REROUTE), now=clock.now
    )

    assert first.forwarded is True
    assert second.forwarded is False
    assert second.rule == RULE_DEDUP


def test_a_new_mission_gets_a_fresh_reroute_allowance() -> None:
    whisperer, clock = _whisperer()
    for _ in range(REROUTE_PER_MISSION_CAP + 2):
        clock.advance(30.0)
        whisperer.note_reroute(
            RerouteReceipt(mission="sofa", state=SOCIAL_STATE_REROUTE), now=clock.now
        )

    clock.advance(30.0)
    decision = whisperer.note_reroute(
        RerouteReceipt(mission="bench", state=SOCIAL_STATE_REROUTE), now=clock.now
    )

    assert decision.forwarded is True


def test_a_reroute_the_lane_refused_gives_its_allowance_back() -> None:
    """``undeliver``'s own doctrine, applied to the cap: the allowance is spent
    by a sentence the owner HEARS."""

    whisperer, clock = _whisperer()
    decision = whisperer.note_reroute(
        RerouteReceipt(mission="sofa", state=SOCIAL_STATE_REROUTE), now=clock.now
    )
    assert decision.forwarded is True
    refusal = whisperer.undeliver(decision)
    assert refusal is not None and refusal.rule == RULE_NARRATION_FLOOR_REFUSED

    forwarded = 0
    for _ in range(REROUTE_PER_MISSION_CAP):
        clock.advance(30.0)
        forwarded += int(
            whisperer.note_reroute(
                RerouteReceipt(mission="sofa", state=SOCIAL_STATE_REROUTE), now=clock.now
            ).forwarded
        )

    assert forwarded == REROUTE_PER_MISSION_CAP


# ================================== the differ did not learn a new string trick
def test_the_differ_still_has_no_nav_goal_branch() -> None:
    """The class is fed by a receipt, and by nothing else. A ``nav_goal`` string
    diff fires on re-issues, re-groundings and restatements — which is exactly
    what ``nav_tick`` does, one order of magnitude slower."""

    whisperer, clock = _whisperer()
    whisperer.observe(StateDigest(at_s=clock.now, navigating=True, nav_goal="sofa"))
    clock.advance(1.0)

    decisions = whisperer.observe(
        StateDigest(at_s=clock.now, navigating=True, nav_goal="the bench")
    )

    assert [d.kind for d in decisions if d.kind == KIND_PLAN_ACCEPTED] == []
    assert all(d.forwarded is False for d in decisions)
    assert {d.kind for d in decisions} <= {KIND_NAV_TICK}


# =========================================================== the MB-1 corpus
def _mb1():
    """Import MB-1's corpus and arm-D driver. Read-only; nothing is written."""

    if not MB1.is_dir():
        pytest.skip("MB-1's research folder is not present in this tree")
    for extra in (str(REPO_ROOT), str(REPO_ROOT / "src"), str(MB1)):
        if extra not in sys.path:
            sys.path.insert(0, extra)
    try:
        import events as mb1_events
        import narrate as mb1_narrate
    except ImportError as error:  # pragma: no cover - environment, not logic
        pytest.skip(f"MB-1's harness will not import here: {error}")
    return mb1_events, mb1_narrate


def _replay(*, max_updates_per_minute: int, min_gap_s: float, receipts: bool):
    """Drive MB-1's 40 scenarios exactly as ``run.py --decisions`` does.

    ``receipts=False`` is the OFF-PATH run: the product whisperer as shipped,
    with no executive in the loop at all. ``receipts=True`` adds the fake
    executive, which offers one admission for every ``accepted`` / ``resumed``
    receipt in the corpus — the 75 "new goal" opportunities MB-1's b1 row counts.
    """

    mb1_events, mb1_narrate = _mb1()
    rows: list[dict[str, object]] = []
    totals: dict[str, int] = {}
    opportunities = 0
    for scenario in mb1_events.build_corpus():
        arm = mb1_narrate.ProductWhisperArm.build(
            max_updates_per_minute=max_updates_per_minute, min_gap_s=min_gap_s
        )
        executive = FakeExecutive()
        for receipt in scenario.receipts:
            produced = list(arm.on_receipt(receipt))
            if receipts and receipt.fact in {
                mb1_events.FACT_ACCEPTED,
                mb1_events.FACT_RESUMED,
            }:
                opportunities += 1
                # The runtime's own branch, in MB-1's alphabet: a task the
                # executive has never seen is a ``submit``; one it has is a
                # ``replace``. The plan is identified by what the owner asked
                # for, which is all a scripted corpus can honestly claim.
                plan = f"navigate:{receipt.goal}"
                admission = (
                    executive.replace(
                        task_id=receipt.task_id,
                        goal=receipt.goal,
                        plan=plan,
                        revision=receipt.plan_revision,
                    )
                    if receipt.task_id in executive._tasks
                    else executive.submit(
                        task_id=receipt.task_id,
                        goal=receipt.goal,
                        plan=plan,
                        revision=receipt.plan_revision,
                    )
                )
                produced.append(
                    arm.whisperer.note_plan_accepted(admission, now=receipt.t).as_dict()
                )
            for row in produced:
                key = f"{'forward' if row.get('forwarded') else 'suppress'}:{row.get('rule')}"
                totals[key] = totals.get(key, 0) + 1
                rows.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "receipt": receipt.event_id,
                        **{k: v for k, v in row.items() if k != "schema_version"},
                    }
                )
    return rows, totals, opportunities


def test_the_off_path_output_over_the_mb1_corpus_is_byte_identical() -> None:
    """With no executive receipts, nothing about the whisperer moved.

    The digest was computed on the tree BEFORE the first edit of this card, and
    its totals reproduce ``RESULTS.md``'s published arm-D ledger row for row.
    """

    rows, totals, opportunities = _replay(
        max_updates_per_minute=MB1_MAX_PER_MIN, min_gap_s=MB1_MIN_GAP_S, receipts=False
    )
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)

    assert opportunities == 0
    assert totals == {
        "forward:block_debounce_elapsed": 10,
        "forward:clear_after_forwarded_block": 10,
        "forward:critical_bypass": 65,
        "suppress:block_debounce_holding": 10,
        "suppress:never_band": 55,
    }
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == OFF_PATH_DIGEST


#: The published arm-D ledger, MB-1 ``RESULTS.md`` §0, reproduced row for row by
#: :func:`_replay` before this card touched anything.
MB1_OTHER_KINDS_LEDGER = {
    "forward:block_debounce_elapsed": 10,
    "forward:clear_after_forwarded_block": 10,
    "forward:critical_bypass": 65,
    "suppress:block_debounce_holding": 10,
    "suppress:never_band": 55,
}


def _split(rows):
    """The acceptance ledger and the other kinds' ledger, separately."""

    acceptance: dict[str, int] = {}
    others: dict[str, int] = {}
    for row in rows:
        key = f"{'forward' if row['forwarded'] else 'suppress'}:{row['rule']}"
        into = acceptance if row["kind"] == KIND_PLAN_ACCEPTED else others
        into[key] = into.get(key, 0) + 1
    return acceptance, others


def test_the_corpus_now_has_a_producer_for_every_new_goal() -> None:
    """MB-1's b1 row, at the decision ledger.

    Today's product produces NOTHING for these 75 "new goal" events — they are
    the 55 ``never_band`` suppressions plus 20 receipts the differ does not even
    see, and MB-1's arm D scored 0.67 on b1 only because ARRIVALS' critical
    forwards stood in for an acknowledgement the product had no way to make.
    Every one of the 75 now reaches a class whose whole subject is the
    acknowledgement, and every one of them lands on a NAMED rule.
    """

    rows, _totals, opportunities = _replay(
        max_updates_per_minute=PROTOTYPE_MAX_PER_MIN,
        min_gap_s=PROTOTYPE_MIN_GAP_S,
        receipts=True,
    )
    acceptance, others = _split(rows)

    assert opportunities == 75
    assert sum(acceptance.values()) == 75, "a new-goal opportunity produced no row"
    # 65 of the 75 are the corpus's ``accepted`` receipts and all 65 are said.
    assert acceptance == {
        f"forward:{RULE_PLAN_ADMITTED}": 65,
        # The 10 ``resumed`` receipts. Five are the ``queued`` family resuming
        # task T2 at the SAME revision, which ``replace`` rejects ("replacement
        # revision must increase"); five are the ``resumed`` family resuming T1
        # at revision 3 with the plan it already ran, which the re-issue guard
        # holds. Both are correct for the vocabulary wave A has: a resume is a
        # lifecycle transition of an already-admitted plan, and it becomes its
        # own receipt with its own ``queue`` lineage when C6's plan queue lands.
        f"suppress:{RULE_PLAN_NOT_ADMITTED}": 5,
        f"suppress:{RULE_PLAN_REISSUE}": 5,
    }
    # THE CARD'S BAR: the other kinds' ledger is untouched, row for row.
    assert others == MB1_OTHER_KINDS_LEDGER


def test_at_the_shipped_cap_the_owners_knob_is_what_pays_for_the_courtesy() -> None:
    """The same replay at MB-1's published 2 per minute / 15 s, reported honestly.

    A 40-scenario corpus that already spends 85 forwards cannot absorb 65 more
    at a two-per-minute cap, and this is the class deliberately NOT allowed to
    outrank the owner's cost knob — so 15 acknowledgements are dropped unbilled,
    and the corpus's 10 block CLEARS lose their slot to the ones that got
    through. The displacement is the cap doing its job, it is bounded to the
    budget rule, and it is written down here rather than left for a reader of
    ``RESULTS.md`` to discover:

    * nothing moves between BANDS — the never band still swallows 55, the block
      debounce still holds 10 and elapses 10, the 65 critical terminals are
      untouched;
    * the only row that changes is 10 ``clear_after_forwarded_block`` forwards
      becoming 10 ``budget_exhausted`` suppressions.

    At the prototype bands (the test above) nothing changes at all, which is the
    evidence that the cap and not the class is what does this.
    """

    rows, _totals, _n = _replay(
        max_updates_per_minute=MB1_MAX_PER_MIN, min_gap_s=MB1_MIN_GAP_S, receipts=True
    )
    acceptance, others = _split(rows)

    assert acceptance == {
        f"forward:{RULE_PLAN_ADMITTED}": 50,
        f"suppress:{RULE_BUDGET}": 15,
        f"suppress:{RULE_PLAN_NOT_ADMITTED}": 5,
        f"suppress:{RULE_PLAN_REISSUE}": 5,
    }
    assert others == {
        "forward:block_debounce_elapsed": 10,
        "forward:critical_bypass": 65,
        "suppress:block_debounce_holding": 10,
        "suppress:budget_exhausted": 10,
        "suppress:never_band": 55,
    }
    # Everything the shipped ledger lost, it lost to the BUDGET and to nothing
    # else: no band moved, no mechanism changed its mind.
    lost = {
        key: count
        for key, count in MB1_OTHER_KINDS_LEDGER.items()
        if others.get(key, 0) != count
    }
    assert lost == {"forward:clear_after_forwarded_block": 10}
    assert others["suppress:budget_exhausted"] == 10


def test_the_acknowledgement_never_silences_a_block_report() -> None:
    """The measured reason :data:`KIND_MIN_GAP_S` carries its own clock.

    Held against the SHARED spacing clock, the acknowledgement at t=0.3 puts the
    8 s block debounce's elapse at t=13.5 inside the owner's 15 s, and MB-1's
    corpus loses 10/10 block reports and 10/10 clears — the owner trades
    "someone is standing in the way" for "okay, I'll go". At the prototype bands,
    where the cap is not binding, both survive intact.
    """

    rows, _totals, _n = _replay(
        max_updates_per_minute=PROTOTYPE_MAX_PER_MIN,
        min_gap_s=PROTOTYPE_MIN_GAP_S,
        receipts=True,
    )
    _acceptance, others = _split(rows)

    assert others["forward:block_debounce_elapsed"] == 10
    assert others["forward:clear_after_forwarded_block"] == 10
    assert "suppress:min_gap" not in others
    assert "suppress:clear_without_forwarded_block" not in others


def test_the_class_cannot_be_spoken_around_its_own_door() -> None:
    """The re-issue guard lives in ``note_plan_accepted``. A class that can be
    forwarded through bare ``offer`` does not have a guard — it has a comment."""

    whisperer, _clock = _whisperer()

    decision = whisperer.offer(
        StateEvent(kind=KIND_PLAN_ACCEPTED, fact="okay, the sofa")
    )

    assert decision.forwarded is False
    assert decision.rule == RULE_PLAN_ACCEPTED_NEEDS_RECEIPT


# ============================ follow-up A1 (parcel-6c): the shared clock's rewind
def test_undelivering_a_shared_class_rewinds_past_an_own_gap_forward() -> None:
    """``[status@t1, plan_accepted@t2, status@t3]`` -> undeliver the last one, and
    the owner's spacing clock goes back to **t1**, not to t2.

    The drift parcel-6c found: an own-gap forward takes a budget slot in the
    shared ``_forwards`` deque but never advances the shared spacing clock, so
    rewinding to ``_forwards[-1]`` handed the clock a moment at which the owner
    had been told nothing that clock is about. Safe in direction (more spacing,
    never less) and still wrong, because the clock has to mean one thing.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=15.0)
    executive = FakeExecutive()

    t1 = clock.now
    assert whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="b1", fact="low")).forwarded
    clock.advance(2.5)
    assert whisperer.note_plan_accepted(
        executive.submit(task_id="T1", goal="sofa", plan="navigate:sofa")
    ).forwarded
    clock.advance(13.5)
    t3 = clock.now
    last = whisperer.offer(StateEvent(kind=KIND_PACE_MISMATCH, key="p1", fact="mismatch"))
    assert last.forwarded and last.at_s == t3

    refusal = whisperer.undeliver(last)

    assert refusal is not None and refusal.rule == RULE_NARRATION_FLOOR_REFUSED
    assert whisperer._last_forward_at == t1, "the shared clock kept an own-gap moment"
    # And the consequence an owner would feel: at t1 + min_gap the next status
    # fact is affordable again. Under the drift it was held for 2.5 s more.
    clock.advance(0.0)
    resumed = whisperer.offer(
        StateEvent(kind=KIND_PACE_MISMATCH, key="p2", fact="mismatch"), now=t1 + 15.0
    )
    assert resumed.forwarded is True, "an own-gap forward was still holding the owner's spacing"


def test_the_budget_slot_is_still_given_back_exactly_once() -> None:
    """A1 changed what the deque carries, not what it counts."""

    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=0.0)
    executive = FakeExecutive()
    whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="b1", fact="low"))
    whisperer.note_plan_accepted(
        executive.submit(task_id="T1", goal="sofa", plan="navigate:sofa")
    )
    clock.advance(3.0)
    last = whisperer.offer(StateEvent(kind=KIND_PACE_MISMATCH, key="p1", fact="mismatch"))
    assert whisperer.snapshot(now=clock.now)["updates_this_minute"] == 3

    whisperer.undeliver(last)

    assert whisperer.snapshot(now=clock.now)["updates_this_minute"] == 2


def test_a_late_undeliver_pops_nothing_and_rewinds_nothing() -> None:
    """Documented, because the rewind above must not be read in isolation.

    Something else forwarded after this decision, so its budget slot is not the
    one on top and there is nothing of its own to give back — the later forward
    has already taken a slot and already advanced the clock. Pre-C4 behaviour,
    unchanged by A1, and the reason ``_last_shared_forward_at`` is only ever
    consulted on the top-of-deque path.
    """

    whisperer, clock = _whisperer(max_updates_per_minute=10, min_gap_s=0.0)
    first = whisperer.offer(StateEvent(kind=KIND_BATTERY_STATE, key="b1", fact="low"))
    clock.advance(20.0)
    later = whisperer.offer(StateEvent(kind=KIND_PACE_MISMATCH, key="p1", fact="mismatch"))
    assert first.forwarded and later.forwarded
    spent_before = whisperer.snapshot(now=clock.now)["updates_this_minute"]

    refusal = whisperer.undeliver(first)

    assert refusal is not None and refusal.rule == RULE_NARRATION_FLOOR_REFUSED
    assert whisperer.snapshot(now=clock.now)["updates_this_minute"] == spent_before
    assert whisperer._last_forward_at == later.at_s
