"""MB-1 — Model B's STEER half: owner utterance + plan queue -> one decision.

``steer(utterance, queue)`` returns one of {revise, keep, queue, clarify} and
the EXECUTIVE CALL that would realize it.  It is deterministic and it reuses
the product's own helpers read-only rather than authoring a second grammar:

* ``voice.closed_intents.parse_closed_intent`` — the reviewed closed intent set
  (pause / resume / faster / slower / stop / come / goal-amend);
* ``voice.amendment.strip_amend_prefix`` — the residual goal text after a
  goal-amend cue, so "actually, go to the bench" yields "the bench";
* ``voice.amendment.begin_goal_amend`` — the product's fail-closed gate that
  decides whether there is anything to revise at all;
* ``voice.amendment.clarification_from_grounding`` — the product's clarify /
  offer-scan wording for an ambiguous or unseen referent.

WHAT IS NEW HERE (and is NOT in the product today)
--------------------------------------------------
"queue" and "clarify-with-plan-context".  The product's amendment path can
suspend and replace; there is no policy that says "the owner asked for a SECOND
goal, keep the first and put this behind it".  :func:`steer` is that policy, and
it is a pure function so NAV-INT-1 can measure the DECISION and MB-1 can measure
the WORDING built from it.  Nothing here touches the executive; the
``executive_call`` field says what WOULD be called.

LIT-1 imports this module by path::

    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location(
        "mb1_steer",
        pathlib.Path("research/20260829/model-b-narration-1/steer.py"))
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
REPO_ROOT = FOLDER.parents[2]
for _extra in (str(REPO_ROOT), str(REPO_ROOT / "src")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

if str(FOLDER) not in sys.path:
    sys.path.insert(0, str(FOLDER))

from events import (
    QUEUE_ACTIVE,
    QUEUE_QUEUED,
    QUEUE_SUSPENDED,
    STEER_CLARIFY,
    STEER_KEEP,
    STEER_QUEUE,
    STEER_REVISE,
    QueueRecord,
)

from parcel_robot.voice.amendment import (
    begin_goal_amend,
    strip_amend_prefix,
)
from parcel_robot.voice.closed_intents import ClosedIntent, parse_closed_intent

STEER_ID = "mb1-steer-v1"

#: Executive calls this policy would realize.  Names taken from
#: ``brain/executive.py`` (``TaskExecutive.submit`` / ``replace`` /
#: ``suspend_task`` / ``resume_task`` / ``request_interrupt``) so a reader can
#: follow the decision to a real method.
CALL_SUBMIT = "TaskExecutive.submit"
CALL_REPLACE = "TaskExecutive.replace"
CALL_SUSPEND_AND_SUBMIT = "TaskExecutive.suspend_task + TaskExecutive.submit"
CALL_PUSH_BEHIND = "plan-queue push-behind (no executive call until the head completes)"
CALL_RESUME = "TaskExecutive.resume_task"
CALL_CANCEL = "TaskExecutive.request_interrupt(cancel)"
CALL_NONE = "no-op"
CALL_ASK = "ask (no executive call)"

#: "after that", "when you're done", "then", "next" — the QUEUE cue.  This is
#: the one piece of grammar the product does not have; everything else below
#: delegates.
_QUEUE_CUE = re.compile(
    r"\b(?:after\s+that|after\s+you'?re\s+done|when\s+you'?re\s+done|"
    r"once\s+you'?re\s+done|then\s+(?:go|check|head)|and\s+then|next[, ]|"
    r"afterwards|later\s+on)\b",
    re.IGNORECASE,
)

#: A bare directive that names a destination.
_GOAL_CUE = re.compile(
    r"\b(?:go\s+to|head\s+(?:to|for)|walk\s+to|check|visit|come\s+to|"
    r"back\s+to|over\s+to|try)\b",
    re.IGNORECASE,
)

#: Discourse markers that carry no plan content.  Stripped BEFORE the goal is
#: read, or "okay" makes "okay, try the bench instead" look like an affirmative
#: and "please" leaves "yes" looking like a destination.
_DISCOURSE = re.compile(
    r"^(?:okay|ok|alright|right|well|so|now|yes|yeah|yep|sure|please|and|but|"
    r"thanks|thank\s+you)\b[,: ]*",
    re.IGNORECASE,
)

#: A residual only counts as a destination if it LOOKS like one: a bare place
#: name, or a short determiner-led phrase.  Without this "yes" reads as a goal.
_DESTINATION = re.compile(r"^(?:the|a|an|my|your)\s+\S+(?:\s+\S+){0,2}$", re.IGNORECASE)

#: An affirmative answer to an offer ("yes please", "yeah, go on").
_AFFIRM = re.compile(r"^(?:yes|yeah|yep|sure|please|ok(?:ay)?|go ahead|do it)\b", re.IGNORECASE)

#: Withdrawal of the current goal.
_WITHDRAW = re.compile(
    r"\b(?:never\s*mind|forget\s+(?:it|that)|hold\s+off|don'?t\s+bother|cancel\s+that)\b",
    re.IGNORECASE,
)

#: A referent nothing can ground: "the other one", "that one", "it".
_AMBIGUOUS = re.compile(
    r"\b(?:the\s+other\s+one|that\s+one|the\s+other|the\s+first\s+one|"
    r"the\s+second\s+one)\b",
    re.IGNORECASE,
)

#: Not a plan change at all: a question about state or the past.
_QUESTION = re.compile(
    r"^(?:what|where|why|how|when|who|can\s+you\s+see|do\s+you\s+see|did\s+you|"
    r"are\s+you|thanks|thank\s+you)\b",
    re.IGNORECASE,
)

#: Place vocabulary the corpus uses, so a bare "the bench" reads as a goal.
_BARE_PLACE = re.compile(
    r"^(?:the\s+)?(?:door|sofa|bench|lamppost|tree|sidewalk|crosswalk)$", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class SteerDecision:
    """One steering decision and the executive call that would realize it."""

    decision: str
    executive_call: str
    goal: str = ""
    #: Which queue record the call targets, when it targets one.
    target_task_id: str = ""
    #: The reason, in this module's own closed vocabulary.
    rule: str = ""
    #: The product helper (if any) that produced or gated it.
    product_helper: str = ""
    #: For ``clarify``: the question to ask.
    question: str = ""
    #: For ``keep``: whether the utterance was nonetheless a closed intent.
    closed_intent: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "decision": self.decision,
            "executive_call": self.executive_call,
            "goal": self.goal,
            "target_task_id": self.target_task_id,
            "rule": self.rule,
            "product_helper": self.product_helper,
            "question": self.question,
            "closed_intent": self.closed_intent,
        }


def _active(queue: tuple[QueueRecord, ...]) -> QueueRecord | None:
    for record in queue:
        if record.status == QUEUE_ACTIVE:
            return record
    return None


def _pending(queue: tuple[QueueRecord, ...]) -> tuple[QueueRecord, ...]:
    return tuple(r for r in queue if r.status in {QUEUE_QUEUED, QUEUE_SUSPENDED})


def _goal_text(utterance: str) -> str:
    """The destination phrase, or "" when the utterance names none."""

    clean = " ".join(str(utterance).split())
    previous = None
    while previous != clean:
        previous = clean
        clean = _DISCOURSE.sub("", clean).strip()
    residual = strip_amend_prefix(clean)
    residual = _QUEUE_CUE.sub("", residual).strip(" ,.")
    residual = re.sub(
        r"^(?:go\s+to|head\s+(?:to|for)|walk\s+to|check|visit|come\s+to|"
        r"back\s+to|over\s+to|try)\s+",
        "",
        residual,
        flags=re.IGNORECASE,
    ).strip(" ,.?")
    residual = re.sub(r"\b(?:instead|first|then|please|now)\b", "", residual, flags=re.IGNORECASE)
    residual = " ".join(residual.split()).strip(" ,.?")
    if not residual:
        return ""
    if _BARE_PLACE.match(residual):
        return residual if residual.lower().startswith("the ") else f"the {residual}"
    if _DESTINATION.match(residual):
        return residual
    return ""


def steer(utterance: str, queue: tuple[QueueRecord, ...] = ()) -> SteerDecision:
    """Owner utterance + plan queue -> {revise, keep, queue, clarify}.

    Order matters and is pre-registered:

    1. a closed intent that is not ``goal-amend`` is handled first (the product
       already owns those and none of them changes the GOAL);
    2. a withdrawal cancels;
    3. an ambiguous referent clarifies BEFORE anything is submitted, because a
       plan admitted from an ungrounded phrase is the failure NAV-INT-1 exists
       to find;
    4. a QUEUE cue with something already running queues;
    5. an affirmative with something pending resumes it;
    6. a directive naming a goal revises (submit when the queue is empty,
       suspend+submit when something is running);
    7. everything else keeps.
    """

    clean = " ".join(str(utterance).split())
    queue = tuple(queue)
    active = _active(queue)
    pending = _pending(queue)

    intent = parse_closed_intent(clean)
    if intent is not None and intent is not ClosedIntent.GOAL_AMEND:
        # STOP / PAUSE / RESUME / FASTER / SLOWER / COME.  None of these edits
        # the goal, so the plan queue is unchanged; RESUME is the one that maps
        # to a queue record.
        if intent is ClosedIntent.RESUME and pending:
            head = pending[0]
            return SteerDecision(
                decision=STEER_REVISE,
                executive_call=CALL_RESUME,
                goal=head.goal,
                target_task_id=head.task_id,
                rule="closed_intent_resume",
                product_helper="voice.closed_intents.parse_closed_intent",
                closed_intent=intent.value,
            )
        return SteerDecision(
            decision=STEER_KEEP,
            executive_call=CALL_NONE,
            rule="closed_intent_not_a_goal_change",
            product_helper="voice.closed_intents.parse_closed_intent",
            closed_intent=intent.value,
        )

    if _WITHDRAW.search(clean):
        if active is None:
            return SteerDecision(
                decision=STEER_KEEP,
                executive_call=CALL_NONE,
                rule="withdrawal_with_nothing_running",
            )
        return SteerDecision(
            decision=STEER_REVISE,
            executive_call=CALL_CANCEL,
            goal=active.goal,
            target_task_id=active.task_id,
            rule="owner_withdrew_the_goal",
        )

    goal = _goal_text(clean)

    if _AMBIGUOUS.search(clean) and not _BARE_PLACE.match(goal or ""):
        # The product's own clarify wording, driven by an AMBIGUOUS grounding
        # outcome.  Built here from the queue so the question can name what is
        # already in it — the "clarify-with-plan-context" the DESIGN says does
        # not exist today.
        labels = tuple(record.goal for record in queue if record.goal)
        if labels:
            listed = " or ".join(labels[-2:]) if len(labels) > 1 else labels[0]
            question = f"Do you mean {listed}?"
        else:
            question = "Which one do you mean?"
        return SteerDecision(
            decision=STEER_CLARIFY,
            executive_call=CALL_ASK,
            rule="ungrounded_referent",
            product_helper="voice.amendment.clarification_from_grounding (shape)",
            question=question,
        )

    if goal and _QUEUE_CUE.search(clean) and active is not None:
        return SteerDecision(
            decision=STEER_QUEUE,
            executive_call=CALL_PUSH_BEHIND,
            goal=goal,
            target_task_id=active.task_id,
            rule="queue_cue_with_a_head_running",
        )

    if _AFFIRM.match(clean) and pending and not goal:
        head = pending[0]
        return SteerDecision(
            decision=STEER_REVISE,
            executive_call=CALL_RESUME,
            goal=head.goal,
            target_task_id=head.task_id,
            rule="affirmative_answer_to_a_resume_offer",
        )

    if goal and (_GOAL_CUE.search(clean) or _BARE_PLACE.match(goal)):
        if active is None:
            return SteerDecision(
                decision=STEER_REVISE,
                executive_call=CALL_SUBMIT,
                goal=goal,
                rule="new_goal_with_an_empty_queue",
                product_helper="voice.amendment.begin_goal_amend (consulted)",
            )
        gate = begin_goal_amend(
            active_channels=(active.task_id,),
            paused_channels=tuple(record.task_id for record in pending),
        )
        return SteerDecision(
            decision=STEER_REVISE,
            executive_call=CALL_SUSPEND_AND_SUBMIT if gate.ok else CALL_REPLACE,
            goal=goal,
            target_task_id=active.task_id,
            rule="goal_change_while_running",
            product_helper="voice.amendment.begin_goal_amend",
        )

    if _QUESTION.match(clean):
        return SteerDecision(
            decision=STEER_KEEP,
            executive_call=CALL_NONE,
            rule="question_about_state_not_a_plan_change",
        )

    return SteerDecision(
        decision=STEER_KEEP, executive_call=CALL_NONE, rule="no_plan_change_recognised"
    )


def self_test() -> dict[str, object]:
    """Score :func:`steer` against the corpus's gold steering labels."""

    from events import OwnerTurn, build_corpus

    total = 0
    correct = 0
    rows: list[dict[str, object]] = []
    for scenario in build_corpus():
        queue: tuple[QueueRecord, ...] = ()
        for step in scenario.steps:
            if isinstance(step, OwnerTurn):
                got = steer(step.text, queue)
                total += 1
                ok = got.decision == step.steer
                correct += int(ok)
                if not ok:
                    rows.append(
                        {
                            "scenario_id": scenario.scenario_id,
                            "utterance": step.text,
                            "gold": step.steer,
                            "got": got.decision,
                            "rule": got.rule,
                        }
                    )
            else:
                queue = step.queue
    return {
        "steer_id": STEER_ID,
        "turns": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "mismatches": rows,
    }


__all__ = ["STEER_ID", "SteerDecision", "self_test", "steer"]

if __name__ == "__main__":
    import json

    print(json.dumps(self_test(), indent=2))
