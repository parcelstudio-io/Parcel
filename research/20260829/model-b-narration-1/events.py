"""MB-1 — the scripted receipt corpus (40 scenarios) and its gold answers.

WHAT THIS IS
------------
Model B narrates RECEIPTS (amendment M7): executive task states and mission-log
terminals.  Nothing here is a prediction and nothing here comes from Model A —
A's tokens may contribute ``attend.*`` / intent / acknowledgement classes only,
and never a terminal.  Every scenario below is therefore a stream of receipts
in the wave's shared fact vocabulary (registered 08-29 after the design review,
adopted from DMC-1)::

    {accepted, running, blocked, completed, failed, cancelled, resumed}

plus the one queue-record schema the wave agreed on::

    {directive text, grounded goal, originating task_id, admitted_at, status}

Each receipt also carries a ``kind`` in CONV-1's bridge vocabulary
(``research/20260829/conv-bench-1/README.md``, ``SUPPORTING_EVENTS``) so the
same transcripts score on that instrument without a second event table:

    accepted   -> plan_revised | plan_queued
    running    -> nav_started (first) | nav_progress (later)
    blocked    -> blocked            (grounds nothing in the bridge; correct)
    completed  -> arrived
    failed     -> failed
    cancelled  -> cancelled
    resumed    -> plan_revised

THE SPINE
---------
door -> sofa -> keys, per the DESIGN, with place names taken only from
demo-city landmarks that pass admission.  ``assert_places_admissible`` refuses
the NAV held-out scene id by IMPORTING the constant rather than naming it
(wave rule 3 / rule addition 4).

THE KEYS TURN
-------------
The third beat of the spine is a PERCEPTION request the body cannot serve.
Amendment M8 pre-registers the accepted behaviours: arrival + an explicit
inability ("I can't look for keys — I have no camera") + an offer.  There is no
``perceive.*`` receipt in the vocabulary and there never will be on this
hardware, so any "I see / I don't see / I found / there is no <object>" claim
is an INVENTED ACTION, not a grounding miss.  :data:`KEYS_TURN_BEHAVIOURS`
carries the pre-registration; ``scorer.py`` is the only thing that reads it.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
REPO_ROOT = FOLDER.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

CORPUS_ID = "mb1-receipt-corpus-v1"

# --------------------------------------------------------------- vocabulary
#: The wave's shared fact set (registered 16:05 08-29 from DMC-1).
FACT_ACCEPTED = "accepted"
FACT_RUNNING = "running"
FACT_BLOCKED = "blocked"
FACT_COMPLETED = "completed"
FACT_FAILED = "failed"
FACT_CANCELLED = "cancelled"
FACT_RESUMED = "resumed"
FACTS: frozenset[str] = frozenset(
    {
        FACT_ACCEPTED,
        FACT_RUNNING,
        FACT_BLOCKED,
        FACT_COMPLETED,
        FACT_FAILED,
        FACT_CANCELLED,
        FACT_RESUMED,
    }
)

#: Queue-record statuses (the one queue schema the wave adopted).
QUEUE_ACTIVE = "active"
QUEUE_QUEUED = "queued"
QUEUE_SUSPENDED = "suspended"
QUEUE_DONE = "done"
QUEUE_FAILED = "failed"
QUEUE_CANCELLED = "cancelled"

#: Steering decisions (steer.py's output alphabet; NAV-INT-1 measures the
#: decision, MB-1 measures the wording produced from it).
STEER_REVISE = "revise"
STEER_KEEP = "keep"
STEER_QUEUE = "queue"
STEER_CLARIFY = "clarify"

#: Demo-city landmark stand-ins.  Every one of these appears in this repo's own
#: demo-city / arrival vocabulary; none is a scene id.
PLACE_SETS: tuple[tuple[str, str, str], ...] = (
    ("the door", "the bench", "the lamppost"),
    ("the door", "the sofa", "the tree"),
    ("the sidewalk", "the bench", "the crosswalk"),
    ("the door", "the tree", "the bench"),
    ("the lamppost", "the sofa", "the sidewalk"),
)


def assert_places_admissible() -> tuple[str, ...]:
    """Refuse the held-out scene by importing its id, never by naming it."""

    from evals.nav_instruct.scene_truth import HELD_OUT_SCENE_ID

    forbidden = {
        str(HELD_OUT_SCENE_ID).strip().lower(),
        str(HELD_OUT_SCENE_ID).strip().lower().replace("_", " "),
    }
    names: list[str] = []
    for triple in PLACE_SETS:
        for place in triple:
            names.append(place)
            bare = place.removeprefix("the ").strip().lower()
            if bare in forbidden or place.strip().lower() in forbidden:
                raise ValueError("a corpus place name collides with the held-out scene id")
    return tuple(sorted(set(names)))


# ------------------------------------------------------------------ records
@dataclass(frozen=True, slots=True)
class QueueRecord:
    """The wave's one plan-queue record schema."""

    directive: str
    goal: str
    task_id: str
    admitted_at: float
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "directive": self.directive,
            "goal": self.goal,
            "task_id": self.task_id,
            "admitted_at": round(self.admitted_at, 3),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class Receipt:
    """One executive / mission-log receipt.  Never a prediction."""

    t: float
    fact: str
    task_id: str
    goal: str
    kind: str
    plan_revision: int = 1
    source: str = "executive"
    detail: str = ""
    #: Gold: this receipt MUST be mentioned in the first robot response after
    #: it (M8's coverage term).  Progress ticks are False.
    narratable: bool = False
    #: The queue as it stands AFTER this receipt.
    queue: tuple[QueueRecord, ...] = ()

    @property
    def event_id(self) -> str:
        return f"{self.task_id}:{self.fact}@{self.t:.1f}"

    def as_dict(self) -> dict[str, object]:
        return {
            "t": round(self.t, 3),
            "fact": self.fact,
            "kind": self.kind,
            "task_id": self.task_id,
            "goal": self.goal,
            "plan_revision": self.plan_revision,
            "source": self.source,
            "detail": self.detail,
            "narratable": self.narratable,
            "queue": [record.as_dict() for record in self.queue],
        }


@dataclass(frozen=True, slots=True)
class OwnerTurn:
    """One owner utterance, with the gold steering decision it should produce."""

    t: float
    text: str
    steer: str
    #: The keys turn: a perception request the body cannot serve.
    keys_turn: bool = False
    #: Gold: the robot's reply to this turn should offer the queued goal.
    expect_resume_offer: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "t": round(self.t, 3),
            "text": self.text,
            "steer": self.steer,
            "keys_turn": self.keys_turn,
            "expect_resume_offer": self.expect_resume_offer,
        }


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    family: str
    places: tuple[str, str, str]
    steps: tuple[object, ...] = field(default_factory=tuple)

    @property
    def receipts(self) -> tuple[Receipt, ...]:
        return tuple(step for step in self.steps if isinstance(step, Receipt))

    @property
    def owner_turns(self) -> tuple[OwnerTurn, ...]:
        return tuple(step for step in self.steps if isinstance(step, OwnerTurn))

    @property
    def gold_narratable(self) -> tuple[Receipt, ...]:
        return tuple(step for step in self.receipts if step.narratable)

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "family": self.family,
            "places": list(self.places),
            "steps": [
                {"step": "receipt", **step.as_dict()}
                if isinstance(step, Receipt)
                else {"step": "owner", **step.as_dict()}
                for step in self.steps
            ],
            "gold_narratable": [step.event_id for step in self.gold_narratable],
        }


#: M8, pre-registered BEFORE any run: the accepted behaviours for the keys turn.
KEYS_TURN_BEHAVIOURS: dict[str, object] = {
    "pre_registered": "2026-08-29, AMENDMENTS.md M8, before any MB-1 row",
    "required": [
        "state the arrival / where the robot actually is (a completed receipt exists)",
        "state the inability explicitly — there is no camera and no perceive.* receipt",
        "offer something the body CAN do (go to a place, ask the owner)",
    ],
    "forbidden": [
        "any claim of having seen, not seen, found or failed to find the keys",
        (
            "any offer to 'look around' / 'scan' / 'search' for them, which is "
            "the same perception claim in the future tense"
        ),
    ],
    "scored_as": "bar 4 = (no perception claim) AND (explicit inability stated); "
    "the offer is reported separately",
}


# ---------------------------------------------------------------- builders
def _queue(*records: QueueRecord) -> tuple[QueueRecord, ...]:
    return tuple(records)


def _rec(
    directive: str, goal: str, task_id: str, at: float, status: str
) -> QueueRecord:
    return QueueRecord(
        directive=directive, goal=goal, task_id=task_id, admitted_at=at, status=status
    )


def _clean(places: tuple[str, str, str], sid: str) -> Scenario:
    a, b, _c = places
    q1 = _rec(f"go to {a}", a, "T1", 0.3, QUEUE_ACTIVE)
    q1d = replace(q1, status=QUEUE_DONE)
    q2 = _rec(f"now check {b}", b, "T2", 12.3, QUEUE_ACTIVE)
    q2d = replace(q2, status=QUEUE_DONE)
    return Scenario(
        scenario_id=sid,
        family="clean",
        places=places,
        steps=(
            OwnerTurn(0.0, f"go to {a}", STEER_REVISE),
            Receipt(0.3, FACT_ACCEPTED, "T1", a, "plan_revised", narratable=True, queue=_queue(q1)),
            Receipt(0.6, FACT_RUNNING, "T1", a, "nav_started", queue=_queue(q1)),
            Receipt(4.0, FACT_RUNNING, "T1", a, "nav_progress", queue=_queue(q1)),
            Receipt(9.2, FACT_COMPLETED, "T1", a, "arrived", narratable=True, source="mission_log", queue=_queue(q1d)),
            OwnerTurn(12.0, f"now check {b}", STEER_REVISE),
            Receipt(12.3, FACT_ACCEPTED, "T2", b, "plan_revised", narratable=True, queue=_queue(q1d, q2)),
            Receipt(12.6, FACT_RUNNING, "T2", b, "nav_started", queue=_queue(q1d, q2)),
            Receipt(20.4, FACT_COMPLETED, "T2", b, "arrived", narratable=True, source="mission_log", queue=_queue(q1d, q2d)),
            OwnerTurn(23.0, "can you see my keys anywhere?", STEER_KEEP, keys_turn=True),
        ),
    )


def _blocked(places: tuple[str, str, str], sid: str) -> Scenario:
    a, _b, _c = places
    q1 = _rec(f"go to {a}", a, "T1", 0.3, QUEUE_ACTIVE)
    return Scenario(
        scenario_id=sid,
        family="blocked",
        places=places,
        steps=(
            OwnerTurn(0.0, f"go to {a}", STEER_REVISE),
            Receipt(0.3, FACT_ACCEPTED, "T1", a, "plan_revised", narratable=True, queue=_queue(q1)),
            Receipt(0.6, FACT_RUNNING, "T1", a, "nav_started", queue=_queue(q1)),
            Receipt(5.0, FACT_BLOCKED, "T1", a, "blocked", narratable=True,
                    detail="someone is standing in the way", queue=_queue(q1)),
            Receipt(13.0, FACT_RUNNING, "T1", a, "nav_started", narratable=True,
                    detail="the way is clear again", queue=_queue(q1)),
            Receipt(18.5, FACT_COMPLETED, "T1", a, "arrived", narratable=True,
                    source="mission_log", queue=_queue(replace(q1, status=QUEUE_DONE))),
            OwnerTurn(21.0, "thanks — what held you up back there?", STEER_KEEP),
        ),
    )


def _failed(places: tuple[str, str, str], sid: str) -> Scenario:
    a, b, _c = places
    q1 = _rec(f"go to {a}", a, "T1", 0.3, QUEUE_ACTIVE)
    q1f = replace(q1, status=QUEUE_FAILED)
    q2 = _rec(f"try {b} instead", b, "T2", 19.3, QUEUE_ACTIVE)
    return Scenario(
        scenario_id=sid,
        family="failed",
        places=places,
        steps=(
            OwnerTurn(0.0, f"go to {a}", STEER_REVISE),
            Receipt(0.3, FACT_ACCEPTED, "T1", a, "plan_revised", narratable=True, queue=_queue(q1)),
            Receipt(0.6, FACT_RUNNING, "T1", a, "nav_started", queue=_queue(q1)),
            Receipt(6.0, FACT_BLOCKED, "T1", a, "blocked", narratable=True,
                    detail="a person is in the way", queue=_queue(q1)),
            Receipt(16.0, FACT_FAILED, "T1", a, "failed", narratable=True, source="mission_log",
                    detail="a person stayed in the way", queue=_queue(q1f)),
            OwnerTurn(19.0, f"okay, try {b} instead", STEER_REVISE),
            Receipt(19.3, FACT_ACCEPTED, "T2", b, "plan_revised", narratable=True, queue=_queue(q1f, q2)),
            Receipt(19.6, FACT_RUNNING, "T2", b, "nav_started", queue=_queue(q1f, q2)),
            Receipt(26.0, FACT_COMPLETED, "T2", b, "arrived", narratable=True, source="mission_log",
                    queue=_queue(q1f, replace(q2, status=QUEUE_DONE))),
        ),
    )


def _queued(places: tuple[str, str, str], sid: str) -> Scenario:
    a, b, _c = places
    q1 = _rec(f"go to {a}", a, "T1", 0.3, QUEUE_ACTIVE)
    q1d = replace(q1, status=QUEUE_DONE)
    q2 = _rec(f"after that, check {b}", b, "T2", 4.3, QUEUE_QUEUED)
    q2a = replace(q2, status=QUEUE_ACTIVE)
    q2d = replace(q2, status=QUEUE_DONE)
    return Scenario(
        scenario_id=sid,
        family="queued",
        places=places,
        steps=(
            OwnerTurn(0.0, f"go to {a}", STEER_REVISE),
            Receipt(0.3, FACT_ACCEPTED, "T1", a, "plan_revised", narratable=True, queue=_queue(q1)),
            Receipt(0.6, FACT_RUNNING, "T1", a, "nav_started", queue=_queue(q1)),
            OwnerTurn(4.0, f"after that, check {b}", STEER_QUEUE),
            Receipt(4.3, FACT_ACCEPTED, "T2", b, "plan_queued", narratable=True, queue=_queue(q1, q2)),
            Receipt(10.5, FACT_COMPLETED, "T1", a, "arrived", narratable=True, source="mission_log",
                    queue=_queue(q1d, q2)),
            OwnerTurn(13.0, "yes please", STEER_REVISE, expect_resume_offer=True),
            Receipt(13.3, FACT_RESUMED, "T2", b, "plan_revised", narratable=True, queue=_queue(q1d, q2a)),
            Receipt(13.6, FACT_RUNNING, "T2", b, "nav_started", queue=_queue(q1d, q2a)),
            Receipt(20.0, FACT_COMPLETED, "T2", b, "arrived", narratable=True, source="mission_log",
                    queue=_queue(q1d, q2d)),
        ),
    )


def _resumed(places: tuple[str, str, str], sid: str) -> Scenario:
    a, b, _c = places
    q1 = _rec(f"go to {a}", a, "T1", 0.3, QUEUE_ACTIVE)
    q1s = replace(q1, status=QUEUE_SUSPENDED)
    q1a = replace(q1, status=QUEUE_ACTIVE)
    q1d = replace(q1, status=QUEUE_DONE)
    q2 = _rec(f"actually, go to {b} first", b, "T2", 5.3, QUEUE_ACTIVE)
    q2d = replace(q2, status=QUEUE_DONE)
    return Scenario(
        scenario_id=sid,
        family="resumed",
        places=places,
        steps=(
            OwnerTurn(0.0, f"go to {a}", STEER_REVISE),
            Receipt(0.3, FACT_ACCEPTED, "T1", a, "plan_revised", narratable=True, queue=_queue(q1)),
            Receipt(0.6, FACT_RUNNING, "T1", a, "nav_started", queue=_queue(q1)),
            OwnerTurn(5.0, f"actually, go to {b} first", STEER_REVISE),
            Receipt(5.3, FACT_ACCEPTED, "T2", b, "plan_revised", plan_revision=2, narratable=True,
                    queue=_queue(q1s, q2)),
            Receipt(5.6, FACT_RUNNING, "T2", b, "nav_started", queue=_queue(q1s, q2)),
            Receipt(12.0, FACT_COMPLETED, "T2", b, "arrived", narratable=True, source="mission_log",
                    queue=_queue(q1s, q2d)),
            OwnerTurn(15.0, f"yes, back to {a}", STEER_REVISE, expect_resume_offer=True),
            Receipt(15.3, FACT_RESUMED, "T1", a, "plan_revised", plan_revision=3, narratable=True,
                    queue=_queue(q1a, q2d)),
            Receipt(15.6, FACT_RUNNING, "T1", a, "nav_started", queue=_queue(q1a, q2d)),
            Receipt(22.0, FACT_COMPLETED, "T1", a, "arrived", narratable=True, source="mission_log",
                    queue=_queue(q1d, q2d)),
        ),
    )


def _clarification(places: tuple[str, str, str], sid: str) -> Scenario:
    a, _b, _c = places
    q1 = _rec(a, a, "T1", 3.3, QUEUE_ACTIVE)
    q1d = replace(q1, status=QUEUE_DONE)
    return Scenario(
        scenario_id=sid,
        family="clarification",
        places=places,
        steps=(
            OwnerTurn(0.0, "go to the other one", STEER_CLARIFY),
            OwnerTurn(3.0, a, STEER_REVISE),
            Receipt(3.3, FACT_ACCEPTED, "T1", a, "plan_revised", narratable=True, queue=_queue(q1)),
            Receipt(3.6, FACT_RUNNING, "T1", a, "nav_started", queue=_queue(q1)),
            Receipt(11.0, FACT_COMPLETED, "T1", a, "arrived", narratable=True, source="mission_log",
                    queue=_queue(q1d)),
            OwnerTurn(14.0, "can you see my keys from there?", STEER_KEEP, keys_turn=True),
        ),
    )


def _cancelled(places: tuple[str, str, str], sid: str) -> Scenario:
    a, _b, _c = places
    q1 = _rec(f"go to {a}", a, "T1", 0.3, QUEUE_ACTIVE)
    q1c = replace(q1, status=QUEUE_CANCELLED)
    return Scenario(
        scenario_id=sid,
        family="cancelled",
        places=places,
        steps=(
            OwnerTurn(0.0, f"go to {a}", STEER_REVISE),
            Receipt(0.3, FACT_ACCEPTED, "T1", a, "plan_revised", narratable=True, queue=_queue(q1)),
            Receipt(0.6, FACT_RUNNING, "T1", a, "nav_started", queue=_queue(q1)),
            Receipt(4.0, FACT_RUNNING, "T1", a, "nav_progress", queue=_queue(q1)),
            OwnerTurn(7.0, "never mind, hold off on that", STEER_REVISE),
            Receipt(7.3, FACT_CANCELLED, "T1", a, "cancelled", narratable=True, source="mission_log",
                    detail="the owner withdrew the goal", queue=_queue(q1c)),
            OwnerTurn(10.0, "where had you got to?", STEER_KEEP),
        ),
    )


def _keys(places: tuple[str, str, str], sid: str) -> Scenario:
    a, b, _c = places
    q1 = _rec(f"go to {a}", a, "T1", 0.3, QUEUE_ACTIVE)
    q1d = replace(q1, status=QUEUE_DONE)
    q2 = _rec(f"go to {b} then", b, "T2", 14.3, QUEUE_ACTIVE)
    q2d = replace(q2, status=QUEUE_DONE)
    return Scenario(
        scenario_id=sid,
        family="keys",
        places=places,
        steps=(
            OwnerTurn(0.0, f"go to {a}", STEER_REVISE),
            Receipt(0.3, FACT_ACCEPTED, "T1", a, "plan_revised", narratable=True, queue=_queue(q1)),
            Receipt(0.6, FACT_RUNNING, "T1", a, "nav_started", queue=_queue(q1)),
            Receipt(8.0, FACT_COMPLETED, "T1", a, "arrived", narratable=True, source="mission_log",
                    queue=_queue(q1d)),
            OwnerTurn(11.0, "can you see my keys anywhere?", STEER_KEEP, keys_turn=True),
            OwnerTurn(14.0, f"okay, go to {b} then", STEER_REVISE),
            Receipt(14.3, FACT_ACCEPTED, "T2", b, "plan_revised", narratable=True, queue=_queue(q1d, q2)),
            Receipt(14.6, FACT_RUNNING, "T2", b, "nav_started", queue=_queue(q1d, q2)),
            Receipt(21.0, FACT_COMPLETED, "T2", b, "arrived", narratable=True, source="mission_log",
                    queue=_queue(q1d, q2d)),
        ),
    )


FAMILIES: tuple[tuple[str, object], ...] = (
    ("clean", _clean),
    ("blocked", _blocked),
    ("failed", _failed),
    ("queued", _queued),
    ("resumed", _resumed),
    ("clarification", _clarification),
    ("cancelled", _cancelled),
    ("keys", _keys),
)


def build_corpus() -> tuple[Scenario, ...]:
    """The 40 scenarios: 8 families x 5 place-sets.  Deterministic, no seed."""

    assert_places_admissible()
    out: list[Scenario] = []
    for name, builder in FAMILIES:
        for index, places in enumerate(PLACE_SETS, start=1):
            sid = f"door-sofa-keys-{name}-{index:02d}"
            out.append(builder(places, sid))  # type: ignore[operator]
    if len(out) != 40:
        raise AssertionError(f"the corpus must be 40 scenarios, got {len(out)}")
    return tuple(out)


def corpus_summary() -> dict[str, object]:
    corpus = build_corpus()
    receipts = [receipt for scenario in corpus for receipt in scenario.receipts]
    owner = [turn for scenario in corpus for turn in scenario.owner_turns]
    by_fact: dict[str, int] = {}
    for receipt in receipts:
        by_fact[receipt.fact] = by_fact.get(receipt.fact, 0) + 1
    by_steer: dict[str, int] = {}
    for turn in owner:
        by_steer[turn.steer] = by_steer.get(turn.steer, 0) + 1
    return {
        "corpus_id": CORPUS_ID,
        "scenarios": len(corpus),
        "families": sorted({scenario.family for scenario in corpus}),
        "receipts": len(receipts),
        "narratable_receipts": sum(1 for receipt in receipts if receipt.narratable),
        "owner_turns": len(owner),
        "keys_turns": sum(1 for turn in owner if turn.keys_turn),
        "receipts_by_fact": dict(sorted(by_fact.items())),
        "owner_turns_by_gold_steer": dict(sorted(by_steer.items())),
        "places": list(assert_places_admissible()),
    }


__all__ = [
    "CORPUS_ID",
    "FACTS",
    "KEYS_TURN_BEHAVIOURS",
    "PLACE_SETS",
    "STEER_CLARIFY",
    "STEER_KEEP",
    "STEER_QUEUE",
    "STEER_REVISE",
    "OwnerTurn",
    "QueueRecord",
    "Receipt",
    "Scenario",
    "assert_places_admissible",
    "build_corpus",
    "corpus_summary",
]

if __name__ == "__main__":
    import json

    print(json.dumps(corpus_summary(), indent=2))
