"""NAV-INT-1 — the harness-side plan-queue policy (H-NI1b) and the
{revise, keep, queue, clarify} steering classifier (H-NI1c).

Both live entirely in the harness. Nothing here is a product seam, nothing
here gains authority, and nothing here is imported by ``src/``.

AMENDMENT N1 (binding, 2026-08-29 15:58) — "resume" is a RE-ISSUE.
``brain/executive.py`` has ``submit`` / ``replace`` / ``request_interrupt``
and no suspend-resume API for this purpose; suspend and resume live inside
``runtime._apply_goal_amend``, which parks the amendable work as a
``ResumeIntent`` and then CONSUMES it in ``_close_amendment_window(
"committed")`` when the replacement plan is accepted. Only a *rollback*
restores it. So a plan queue on top of the shipped stack cannot resume the
displaced goal: it must remember the original directive TEXT itself and
re-issue it through ``handle_text`` once the amended goal reaches a terminal
receipt — a fresh task, a fresh plan revision, navigation from scratch.
Every row this module produces is therefore labelled **re-issue**, never
"resume".

Measured corroboration (first live episode, 2026-08-29): the amendment
"actually, go to the lamppost" during "go to the sidewalk" produced ONE task
record whose plan revision went 1 → 2. No suspended state was ever
observable from outside, and after the amended goal succeeded nothing
returned to the sidewalk.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(__file__).resolve().parents[3]
for _extra in (str(HERE), str(REPO)):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

# The cue vocabulary and the stripper live at the ISSUE DOOR (``harness.py``),
# because that is where a queue-cued re-issue is refused by the product.  One
# definition, imported here, so the classifier and the door cannot disagree.
from harness import QUEUE_CUE_RE as _QUEUE_CUE
from harness import strip_queue_cue as _strip_queue_cue

from evals.nav_instruct.scene_truth import derived_landmark_table
from parcel_robot.brain.router import DeterministicIntentRouter
from parcel_robot.navigation.goals import (
    navigation_directive_from_text,
)
from parcel_robot.voice.amendment import strip_amend_prefix
from parcel_robot.voice.closed_intents import (
    ClosedIntent,
    parse_closed_intent,
)

# ---------------------------------------------------------------------------
# H-NI1c — the steering classifier
# ---------------------------------------------------------------------------

REVISE = "revise"
KEEP = "keep"
QUEUE = "queue"
CLARIFY = "clarify"
LABELS = (REVISE, KEEP, QUEUE, CLARIFY)

#: The queue family, exactly as DESIGN.md names it ("after that / when you're
#: done / then"), plus the small closed set of paraphrases the tier generates.
#: A regex and not the router: the router labels these inconsistently today
#: ("after that, go to the bench" → compound_physical_request; "after that head
#: to the sidewalk" → conversation_only; "when you finish, …" →
#: ambiguous_physical_request), which is itself part of the H-NI1c finding.
#:
#: The pattern itself MOVED to ``harness.QUEUE_CUE_RE`` (card C7) and is
#: imported above, unchanged character for character: the ISSUE DOOR needs the
#: same vocabulary to strip a cue off a re-issue, and two copies would be two
#: opinions.  ``_QUEUE_CUE`` below is that object; the classifier's behaviour is
#: byte-identical to the recorded run (verified against the frozen blind set).

#: Confirmations / acknowledgements: the "keep" half that IS addressed to the
#: robot but asks for no plan change.
_CONFIRMATION = re.compile(
    r"^(?:yes|yep|yeah|ok|okay|sure|right|correct|that(?:'s| is)\s+(?:right|it|great|good)|"
    r"good\s+(?:boy|dog|job|work)|nice\s+(?:work|job)|well\s+done|thanks|thank\s+you|"
    r"perfect|exactly|mm+hmm)\b",
    re.IGNORECASE,
)

#: A replacement that names no resolvable referent — the runtime's own
#: amendment lane refuses these to the planner (``agent._goal_amend_without_
#: planner``: ``anaphoric`` → the honest reply), so the classifier answers
#: ``clarify`` rather than inventing a goal.
_ANAPHORIC = re.compile(r"\b(?:other|another|same|that\s+one|this\s+one|it)\b", re.IGNORECASE)

#: Closed intents that steer the BODY without changing what the plan is.
_NON_GOAL_INTENTS = {
    ClosedIntent.PAUSE,
    ClosedIntent.RESUME,
    ClosedIntent.FASTER,
    ClosedIntent.SLOWER,
    ClosedIntent.STOP,
}

#: The one place ``distance already travelled`` enters the decision: a bare,
#: cue-free new goal issued when the current goal is essentially reached reads
#: as a *next* goal rather than a correction. Declared here, ablated in
#: RESULTS.md, and (by construction) not exercised by the pre-registered gold
#: set, whose labels DESIGN.md defines from the utterance alone.
QUEUE_PROGRESS_THRESHOLD = 0.9

_ROUTER = DeterministicIntentRouter()


@dataclass(frozen=True)
class SteeringDecision:
    label: str
    reason: str
    features: dict

    def as_dict(self) -> dict:
        return {"label": self.label, "reason": self.reason, "features": dict(self.features)}


#: The scene's own place vocabulary. A "navigation command" for this
#: classifier is a directive that names one of these — the same test the
#: runtime applies before it will start a mission (``agent._unknown_place_
#: reply`` refuses the rest), and the AMENDMENT N4 allowlist.
KNOWN_PLACES: frozenset[str] = frozenset(
    {str(row.get("label")).lower() for row in derived_landmark_table().values() if row.get("label")}
    | {"owner"}
)


def _destination_of(text: str, *, cue_present: bool) -> tuple[str | None, str]:
    """(place, status) for one utterance residual.

    ``status`` is ``place`` (a directive naming a known landmark),
    ``unknown_place`` (a directive naming something the scene has no name
    for), or ``none`` (not a navigation directive at all).

    The verb is re-attached only when a cue ATE it. ``navigation_directive_
    from_text("go to " + anything)`` accepts almost any noun phrase, so
    re-attaching unconditionally turns "how far is the bench?" into a
    navigation command — which is exactly the ``keep`` class DESIGN.md names.
    """

    clean = " ".join(str(text).strip().split())
    if not clean:
        return None, "none"
    directive = navigation_directive_from_text(clean)
    if directive is None and cue_present:
        # The amend/queue cue strips the verb ("actually, go to the bench" ->
        # "the bench"); re-attach a neutral one, as
        # ``agent._goal_amend_without_planner`` does.
        directive = navigation_directive_from_text(f"go to {clean}")
    if directive is None:
        return None, "none"
    words = set(re.findall(r"[a-z]+", directive.lower()))
    named = sorted(words & KNOWN_PLACES)
    if named:
        return named[0], "place"
    return None, "unknown_place"


def classify(
    utterance: str,
    *,
    current_goal: str | None = None,
    progress: float = 0.0,
) -> SteeringDecision:
    """Decide what an in-flight utterance should do to the global plan queue.

    Deterministic and side-effect free. The class definitions are DESIGN.md's:
    ``keep`` = the utterance is not a navigation command, or is a
    confirmation; ``queue`` = an "after that / when you're done / then"
    directive; ``revise`` = otherwise. ``clarify`` is the fourth output the
    runtime's own amendment lane already produces (an amend cue whose
    replacement names no resolvable referent) — the pre-registered 60-case
    gold set contains no ``clarify`` rows, so emitting one there is scored as
    a miss, never as a free pass.
    """

    if not isinstance(utterance, str):
        raise TypeError("utterance must be a string")
    clean = " ".join(utterance.strip().split())
    if not clean:
        raise ValueError("utterance must not be empty")

    closed = parse_closed_intent(clean)
    amend_cue = closed is ClosedIntent.GOAL_AMEND
    queue_cue = bool(_QUEUE_CUE.search(clean))
    confirmation = bool(_CONFIRMATION.match(clean))
    frame = _ROUTER.route(clean, turn_id="ni1")

    if queue_cue:
        residual = _strip_queue_cue(clean)
    elif amend_cue:
        residual = strip_amend_prefix(clean)
    else:
        residual = clean
    place, place_status = _destination_of(residual, cue_present=queue_cue or amend_cue)
    come = parse_closed_intent(residual) is ClosedIntent.COME or closed is ClosedIntent.COME
    target = "owner" if come else place
    if come:
        place_status = "place"
    anaphoric = bool(_ANAPHORIC.search(residual)) and target is None
    conflict = bool(target and current_goal and target != str(current_goal).lower())

    features = {
        "closed_intent": None if closed is None else closed.value,
        "amend_cue": amend_cue,
        "queue_cue": queue_cue,
        "confirmation": confirmation,
        "route": frame.route,
        "speech_act": frame.speech_act,
        "matched_rule": frame.matched_rule,
        "residual": residual,
        "target": target,
        "place_status": place_status,
        "anaphoric": anaphoric,
        "conflict": conflict,
        "progress": round(float(progress), 3),
    }

    if confirmation:
        return SteeringDecision(KEEP, "confirmation", features)
    if closed in _NON_GOAL_INTENTS:
        return SteeringDecision(KEEP, f"closed_intent_not_a_goal_change:{closed.value}", features)
    if queue_cue:
        if target is not None:
            return SteeringDecision(QUEUE, "queue_cue_with_goal", features)
        if anaphoric:
            return SteeringDecision(CLARIFY, "queue_cue_anaphoric_target", features)
        if place_status == "unknown_place":
            return SteeringDecision(CLARIFY, "queue_cue_unknown_place", features)
        return SteeringDecision(KEEP, "queue_cue_without_a_goal", features)
    if amend_cue:
        if target is None:
            return SteeringDecision(
                CLARIFY,
                "amend_cue_anaphoric_target"
                if anaphoric
                else ("amend_cue_unknown_place" if place_status == "unknown_place" else
                      "amend_cue_without_a_goal"),
                features,
            )
        return SteeringDecision(REVISE, "amend_cue", features)
    if target is None:
        if place_status == "unknown_place":
            return SteeringDecision(CLARIFY, "unknown_place", features)
        return SteeringDecision(KEEP, "not_a_navigation_command", features)
    if current_goal is not None and not conflict:
        return SteeringDecision(KEEP, "restates_the_current_goal", features)
    if current_goal is not None and float(progress) >= QUEUE_PROGRESS_THRESHOLD:
        return SteeringDecision(QUEUE, "bare_goal_at_end_of_current_goal", features)
    return SteeringDecision(REVISE, "bare_new_goal", features)


# ---------------------------------------------------------------------------
# H-NI1b — the plan-queue policy
# ---------------------------------------------------------------------------


@dataclass
class QueueEntry:
    """One global plan remembered by the harness, with the text to re-issue."""

    goal_key: str
    text: str  # the text that will actually be ISSUED (queue cue stripped)
    pushed_at_s: float
    origin: str  # "displaced" | "queued" | "held_pre_runtime" | "head"
    spoken: str = ""  # what the owner actually said, kept for the record


@dataclass
class PlanQueue:
    """Push the displaced goal; on the amendment's terminal receipt, re-issue.

    The whole policy, and the whole of what the shipped stack lacks. Every
    decision is logged so the verifier can replay it without the sim.
    """

    entries: list[QueueEntry] = field(default_factory=list)
    log: list[dict] = field(default_factory=list)
    head: QueueEntry | None = None

    def _note(self, action: str, **fields: object) -> None:
        self.log.append({"action": action, **fields})

    def start_goal(self, goal_key: str, text: str, *, t: float) -> None:
        self.head = QueueEntry(goal_key, text, t, "head")
        self._note("start_goal", goal_key=goal_key, text=text, t=round(t, 3))

    def on_interrupt(
        self,
        decision: SteeringDecision,
        *,
        goal_key: str,
        text: str,
        t: float,
        displaced: bool,
    ) -> None:
        """Apply one interruption to the queue.

        ``displaced`` is the OBSERVED effect on the shipped stack, read from
        the admission receipt: True when the running goal was replaced,
        suspended or superseded. What is pushed is decided by what actually
        happened to the running goal, not by the classifier label — DESIGN.md
        says "push the suspended goal", and on this stack an interruption of
        ANY phrasing family (including the queue family) displaces it, because
        the runtime has no queue semantics to honour a "after that, …" with.
        The classifier's own label is logged beside it, so the gap between
        what a Model B would have wanted and what the stack did is visible.
        """

        if displaced:
            old = self.head
            if old is not None:
                self.entries.append(QueueEntry(old.goal_key, old.text, t, "displaced"))
            self.head = QueueEntry(goal_key, text, t, "head")
            action = (
                "revise_observed"
                if decision.label == REVISE
                else f"{decision.label}_intent_but_runtime_revised"
            )
            self._note(
                action,
                classifier_label=decision.label,
                classifier_reason=decision.reason,
                pushed=None if old is None else old.goal_key,
                new_head=goal_key,
                t=round(t, 3),
            )
            return
        if decision.label == QUEUE:
            # The cue comes OFF here for the same measured reason
            # ``hold_for_later`` strips it: the entry's ``text`` is what will be
            # issued, and the product refuses a queue-cued directive.  The
            # spoken form is kept beside it (card C7).
            residual = _strip_queue_cue(text) or text
            self.entries.append(
                QueueEntry(goal_key, residual, t, "queued", spoken=text)
            )
            self._note(
                "queue",
                classifier_label=decision.label,
                classifier_reason=decision.reason,
                queued=goal_key,
                spoken=text,
                will_issue=residual,
                t=round(t, 3),
            )
            return
        self._note(
            "no_displacement",
            classifier_label=decision.label,
            classifier_reason=decision.reason,
            t=round(t, 3),
        )

    def hold_for_later(
        self,
        decision: SteeringDecision,
        *,
        goal_key: str,
        text: str,
        t: float,
    ) -> None:
        """AMENDMENT N9 — the classifier said ``queue``, so HOLD the utterance.

        It never reaches ``handle_text`` while the current task runs. The
        running goal keeps its plan; the held text is issued as a NEW task
        once the current task_id reads succeeded/failed.
        """

        # MEASURED 2026-08-29, first tier episode: issuing the held text
        # VERBATIM fails. "after that, go to the owner" comes back from
        # handle_text as "I did not understand that command", because
        # ``navigation_directive_from_text`` does not strip a queue cue
        # (amendment N9 names exactly this). The queue therefore stores the
        # RESIDUAL the classifier already extracted and keeps the spoken form
        # beside it for the record.
        residual = _strip_queue_cue(text) or text
        self.entries.append(
            QueueEntry(goal_key, residual, t, "held_pre_runtime", spoken=text)
        )
        self._note(
            "hold_pre_runtime",
            classifier_label=decision.label,
            classifier_reason=decision.reason,
            queued=goal_key,
            spoken=text,
            will_issue=residual,
            t=round(t, 3),
        )

    def next_reissue(self, *, t: float, terminal_state: str) -> QueueEntry | None:
        """On the amended goal's terminal receipt, the next goal to RE-ISSUE.

        AMENDMENT N1: this is a re-issue of the original directive text, not a
        resume — the runtime consumed the parked ``ResumeIntent`` when the
        replacement plan committed.
        """

        if not self.entries:
            self._note("no_reissue", t=round(t, 3), terminal_state=terminal_state)
            return None
        entry = self.entries.pop(0)
        self.head = QueueEntry(entry.goal_key, entry.text, t, "head", spoken=entry.spoken)
        self._note(
            "reissue",
            goal_key=entry.goal_key,
            text=entry.text,
            spoken=entry.spoken or entry.text,
            origin=entry.origin,
            terminal_state=terminal_state,
            t=round(t, 3),
        )
        return entry

    def as_dict(self) -> dict:
        return {
            "log": list(self.log),
            "pending": [
                {
                    "goal_key": item.goal_key,
                    "text": item.text,
                    "spoken": item.spoken or item.text,
                    "origin": item.origin,
                }
                for item in self.entries
            ],
            "head": None if self.head is None else self.head.goal_key,
        }


__all__ = [
    "CLARIFY",
    "KEEP",
    "LABELS",
    "QUEUE",
    "QUEUE_PROGRESS_THRESHOLD",
    "REVISE",
    "PlanQueue",
    "QueueEntry",
    "SteeringDecision",
    "classify",
]


# ---------------------------------------------------------------------------
# classify_v2 — POST-HOC. Not the pre-registered number.
# ---------------------------------------------------------------------------
#
# :func:`classify` above is FROZEN: it is the classifier as written before the
# verifier's blind set (``gold_blind.json``, amendment N7) was opened, and the
# H-NI1c bar is read on ITS score. The version below was written afterwards,
# from the error analysis of that run, and is reported separately and labelled
# post-hoc everywhere. It is here because the errors it fixes are
# generalisation gaps with names — missing cue paraphrases, a residual that is
# a bare place noun, deictic targets — and a research note that says only
# "0.83" without saying which grammar was missing would be a worse finding.
#
# The five gaps, and the fix for each:
#   1. queue paraphrases the cue set never had: "once you get there",
#      "after the <landmark>", a bare leading "next," / "later,", a TRAILING
#      "after" ("do the tree after"), "when you reach it";
#   2. amendment cues the shipped ``_GOAL_AMEND`` regex does not carry:
#      "scratch that", "forget the <place>,", "hold on," / "wait," before a
#      directive (the shipped regex is the product's, so v2 adds its own layer
#      rather than pretending the runtime would admit these);
#   3. "no worries" parsed as the amend cue "no " — it is a confirmation;
#   4. a residual that is itself a non-goal closed intent ("no, keep going")
#      must be KEEP, not a clarification;
#   5. a motion directive whose target is deictic or unknown ("go back",
#      "go there", "go to my spot", "go back to the sofa …") is a
#      CLARIFY, not a non-command.

_QUEUE_CUE_V2_PARTS = [
    r"after\s+that",
    r"after\s+this",
    r"after\s+you(?:'re| are)?\s+done",
    r"after\s+you\s+finish(?:ed)?",
    r"after\s+you\s+get\s+there",
    r"when\s+you(?:'re| are)?\s+done",
    r"when\s+you\s+finish(?:ed)?",
    r"when\s+you\s+(?:get|reach)\s+(?:there|it)",
    r"once\s+you(?:'re| are)?\s+done",
    r"once\s+you\s+finish(?:ed)?",
    r"once\s+you\s+(?:get|reach)\s+(?:there|it)",
    r"afterwards?",
    r"and\s+then",
    r",\s*then\b",
    r"^then\b",
    r"^next\b[,]?",
    r",\s*next\b[,]?",
    r"^later\b[,]?",
    r",\s*later\b[,]?",
    r"\bafter\s*$",
]
_QUEUE_CUE_V2 = re.compile(
    r"(?:" + "|".join(_QUEUE_CUE_V2_PARTS) + r")", re.IGNORECASE
)
#: "after the lamppost, the bench" — a queue cue that names the CURRENT goal.
_QUEUE_AFTER_PLACE = re.compile(
    r"\bafter\s+(?:the\s+)?(?:" + "|".join(sorted(KNOWN_PLACES)) + r")\b\s*,?",
    re.IGNORECASE,
)
#: Amendment cues the shipped grammar does not carry.
_AMEND_CUE_V2 = re.compile(
    r"^(?:scratch\s+that|forget\s+(?:the\s+|about\s+)?[\w']+|hold\s+on|hang\s+on|wait)"
    r"\s*[,:]?\s+",
    re.IGNORECASE,
)
_DEICTIC = re.compile(
    r"\b(?:back|there|here|that\s+way|my\s+spot|my\s+place|it)\b", re.IGNORECASE
)
_MOTION_VERB = re.compile(
    r"^(?:go|head|walk|move|come|run|get|drive|take\s+me|follow)\b", re.IGNORECASE
)
_CONFIRMATION_V2 = re.compile(
    _CONFIRMATION.pattern + r"|^(?:no\s+worries|never\s+mind|no\s+problem|carry\s+on)\b",
    re.IGNORECASE,
)


def _strip_queue_cue_v2(text: str) -> str:
    residual = _QUEUE_AFTER_PLACE.sub(" ", text, count=1)
    if residual == text:
        residual = _QUEUE_CUE_V2.sub(" ", text, count=1)
    residual = re.sub(r"^[\s,;:]+", "", residual)
    residual = re.sub(r"[\s,;:]+$", "", residual)
    return " ".join(residual.split())


def classify_v2(
    utterance: str,
    *,
    current_goal: str | None = None,
    progress: float = 0.0,
) -> SteeringDecision:
    """POST-HOC classifier. Reported separately; no pre-registered bar reads on it."""

    clean = " ".join(str(utterance).strip().split())
    if not clean:
        raise ValueError("utterance must not be empty")

    closed = parse_closed_intent(clean)
    queue_cue = bool(_QUEUE_CUE_V2.search(clean) or _QUEUE_AFTER_PLACE.search(clean))
    extra_amend = bool(_AMEND_CUE_V2.match(clean))
    amend_cue = (closed is ClosedIntent.GOAL_AMEND) or extra_amend
    confirmation = bool(_CONFIRMATION_V2.match(clean))

    if queue_cue:
        residual = _strip_queue_cue_v2(clean)
    elif extra_amend:
        residual = _AMEND_CUE_V2.sub("", clean, count=1).strip()
    elif amend_cue:
        residual = strip_amend_prefix(clean)
    else:
        residual = clean

    residual_closed = parse_closed_intent(residual) if residual else None
    place, place_status = _destination_of(residual, cue_present=queue_cue or amend_cue)
    come = residual_closed is ClosedIntent.COME or closed is ClosedIntent.COME
    target = "owner" if come else place
    if come:
        place_status = "place"
    motion_shaped = bool(_MOTION_VERB.match(residual))
    deictic = bool(_DEICTIC.search(residual)) and target is None
    anaphoric = bool(_ANAPHORIC.search(residual)) and target is None
    conflict = bool(target and current_goal and target != str(current_goal).lower())

    features = {
        "version": "v2_post_hoc",
        "closed_intent": None if closed is None else closed.value,
        "residual_closed_intent": None if residual_closed is None else residual_closed.value,
        "amend_cue": amend_cue,
        "extra_amend_cue": extra_amend,
        "queue_cue": queue_cue,
        "confirmation": confirmation,
        "residual": residual,
        "target": target,
        "place_status": place_status,
        "motion_shaped": motion_shaped,
        "deictic": deictic,
        "anaphoric": anaphoric,
        "conflict": conflict,
        "progress": round(float(progress), 3),
    }

    if confirmation:
        return SteeringDecision(KEEP, "confirmation", features)
    if closed in _NON_GOAL_INTENTS:
        return SteeringDecision(KEEP, f"closed_intent_not_a_goal_change:{closed.value}", features)
    if residual_closed in _NON_GOAL_INTENTS:
        # "no, keep going" — the cue fired but what follows asks for no change.
        return SteeringDecision(
            KEEP, f"residual_is_not_a_goal_change:{residual_closed.value}", features
        )
    if queue_cue:
        if target is not None or motion_shaped:
            return SteeringDecision(QUEUE, "queue_cue_with_goal", features)
        if anaphoric or deictic:
            return SteeringDecision(CLARIFY, "queue_cue_unresolvable_target", features)
        if place_status == "unknown_place":
            return SteeringDecision(CLARIFY, "queue_cue_unknown_place", features)
        return SteeringDecision(KEEP, "queue_cue_without_a_goal", features)
    if amend_cue:
        if target is not None:
            return SteeringDecision(REVISE, "amend_cue", features)
        if anaphoric or deictic:
            return SteeringDecision(CLARIFY, "amend_cue_unresolvable_target", features)
        if place_status == "unknown_place" or motion_shaped:
            return SteeringDecision(CLARIFY, "amend_cue_unknown_place", features)
        return SteeringDecision(CLARIFY, "amend_cue_without_a_goal", features)
    if target is None:
        if place_status == "unknown_place":
            return SteeringDecision(CLARIFY, "unknown_place", features)
        if motion_shaped and (deictic or place_status == "none"):
            # "go back" / "go there" / "go to my spot" — a motion command whose
            # target names nothing this robot can ground. Ask, never guess.
            return SteeringDecision(CLARIFY, "motion_directive_without_a_place", features)
        return SteeringDecision(KEEP, "not_a_navigation_command", features)
    if current_goal is not None and not conflict:
        return SteeringDecision(KEEP, "restates_the_current_goal", features)
    if current_goal is not None and float(progress) >= QUEUE_PROGRESS_THRESHOLD:
        return SteeringDecision(QUEUE, "bare_goal_at_end_of_current_goal", features)
    return SteeringDecision(REVISE, "bare_new_goal", features)


__all__.append("classify_v2")
