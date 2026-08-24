"""Vocabulary that grows — idle-time VLM naming behind a k-gate (card P1-D).

The owner's directive, mechanized
---------------------------------
"Generalized perception that continuously learns about the world." The map
already remembers *places*; what it cannot do is learn what they are **called**
beyond the detector's prompt list. A place the owner has never named and the
detector has no word for is a shape at a coordinate.

``SYNTHESIS.md`` decision 5 says how to fix that safely: a small VLM names
places at roughly **82–87 % accuracy** — about one name in seven is wrong — so
names enter as *hypotheses* with ``vlm_proposed`` provenance and become
vocabulary only after **k = 3 independent-visit agreements**. Wrong names do not
survive three separate approaches; right ones do.

What is here and what is not
----------------------------
C-2 already built the k-gate itself: :class:`~.entries.ProposedName` counts
distinct visit ids, :meth:`~.online_map.OnlineSemanticMap.propose_name` records
one agreement, and ``known_places()`` serves only admissible names. **None of
that is re-implemented here.** This module is the *pass*: which entries to name,
when it is allowed to run, how a proposal is normalized before it is compared,
and — the part C-2 does not have — what happens when a later visit **disagrees**.

Demotion, and why it needs to exist
-----------------------------------
Promotion alone is a ratchet: three agreeing visits promote a name forever, even
if the next twenty visits call the place something else. That is exactly the
failure mode the accuracy number predicts, because a VLM that is wrong about an
object tends to be wrong about it *consistently from similar viewpoints* — the
same reason the gate counts visits and not frames. So a disagreeing visit takes
a supporting visit away from any name that has STANDING, and a promoted name
that falls below k reverts to ``vlm_proposed`` and **leaves** ``known_places()``
on the spot.

"Standing" means promoted. An un-promoted hypothesis is left alone, and that is
a measured decision rather than a soft one: penalising every unpromoted guess
turns k=3 into "three visits IN A ROW", and on P1-D's own 8-object replay that
reading promoted **nothing at all** — a vocabulary gate that cannot grow a
vocabulary. See ``P1D_STATUS.md``.

NEVER ON THE PATROL PATH
------------------------
Every VLM size measured breaches the 100 ms detector bound while generating.
:func:`run_naming_pass` therefore takes a wall budget, runs through
:class:`~parcel_robot.vlm_veto.VetoRunner` (which refuses to execute on the
control thread), and is meant to be called when the dog is idle — the same
contract ``propose_name``'s own docstring states.

Card NM-1: consistency is not correctness
-----------------------------------------
Everything above assumed the research's 82-87 % naming accuracy. P1-D measured
**45.0 %** on this world, and measured the shape of the residue: the wrong
answers are descriptions of geometry ("yellow cylinder" for a bollard, "pole"
for a traffic light), which a model gives *consistently*, from every angle. On
the full-resolution arm three independent visits agreed on each of those two
names and **both were promoted into** ``known_places()`` — 2 promotions, 2
false. The k-gate is a consistency filter, and a systematically wrong model is
systematically consistent.

So :func:`run_naming_pass` takes a ``judge``
(:mod:`parcel_robot.vlm_veto.judge`) — the open-vocabulary DETECTOR, an
independent seat the VLM cannot collude with — and a k-agreed name becomes
vocabulary only if the judge also fires on it over the entry's best view. A name
the judge rejects is **held at** ``vlm_proposed``: it keeps its visits, keeps
accruing evidence, and never reaches ``known_places()``.

``judge=None`` is the default and means *exactly* HEAD's behaviour, byte for
byte. That is deliberate: this is a prototype, the rule is ask-over-refuse, and
a card that made "no judge installed" mean "promote nothing" would have shipped
a new fail-closed default in the module whose entire job is to grow a
vocabulary.

Scope note: ``online_map/`` is P1-B's package. This module is P1-D's only file
in it and it touches the rest **through the public API** —
``active_entries()``, ``propose_name()``, ``entry.note()``, ``entry.names`` —
adding no method and changing no line anywhere else in the package. NM-1 keeps
that rule: the hold rewrites the public ``entry.names`` tuple with public
``ProposedName`` constructors, exactly as ``demote_disagreed_names`` already
does.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from parcel_robot.online_map.entries import (
    NAME_DETECTOR_LABEL,
    NAME_PROMOTED,
    NAME_PROMOTION_VISITS,
    NAME_VLM_PROPOSED,
    MapEntry,
    ProposedName,
    normalize_label,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_BATCH_BUDGET_S",
    "DEMOTION_EVENT",
    "HOLD_EVENT",
    "MAX_NAME_WORDS",
    "NAME_PROMOTION_VISITS",
    "NamingOutcome",
    "NamingReport",
    "demote_disagreed_names",
    "entries_needing_a_name",
    "hold_at_hypothesis",
    "normalize_proposal",
    "run_naming_pass",
]

#: Wall-clock ceiling for one idle-time pass. Not a safety bound — the runner's
#: control-thread tripwire is that — but an "idle" that runs for a minute is not
#: idle any more, and a dog that stops responding because it is busy naming a
#: planter has learned the wrong lesson.
DEFAULT_BATCH_BUDGET_S = 20.0

#: The naming prompt asks for "one to three words". Anything longer is a
#: sentence, and a sentence is not a name: the model narrated instead of
#: answering and the honest read is that it did not answer.
MAX_NAME_WORDS = 3

#: History event a demotion writes, so the audit trail says which way a name
#: moved and not just that it moved.
DEMOTION_EVENT = "name_demoted"

#: Card NM-1. History event a JUDGE-HELD name writes. Deliberately not
#: :data:`DEMOTION_EVENT`: a demotion means "later visits disagreed with this
#: name", and a hold means "k visits agreed and the independent judge did not".
#: Reading a map's history later, those are different stories about the world and
#: only one of them is about the VLM being inconsistent.
HOLD_EVENT = "name_held"

#: Words that are the model declining, dressed as an answer. A name has to name
#: something; "object", "unknown" and "thing" are what a VLM says when it does
#: not know, and promoting them three times would give the map a place called
#: "object" with full vocabulary rights.
_NON_NAMES = frozenset(
    {
        "object",
        "objects",
        "thing",
        "things",
        "unknown",
        "unclear",
        "none",
        "nothing",
        "image",
        "photo",
        "picture",
        "scene",
        "background",
        "it",
        "an object",
        "the object",
        "unidentified object",
    }
)


@dataclass(frozen=True, slots=True)
class NamingOutcome:
    """What one entry's turn in the pass produced."""

    entry_id: str
    proposed: str = ""
    promoted: bool = False
    demoted: tuple[str, ...] = ()
    skipped: str = ""
    #: Card NM-1. What the independent judge said about ``proposed`` — one of
    #: ``accept`` / ``reject`` / ``unavailable``, or ``""`` when no judge was
    #: configured or the name never reached k and so was never worth asking
    #: about. ``held`` is True when the judge is why this name is not vocabulary.
    judged: str = ""
    judge_strength: float | None = None
    held: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "proposed": self.proposed,
            "promoted": self.promoted,
            "demoted": list(self.demoted),
            "skipped": self.skipped,
            "judged": self.judged,
            "judge_strength": self.judge_strength,
            "held": self.held,
        }


@dataclass(slots=True)
class NamingReport:
    """The pass, summarized. Every number here is a count of a real event."""

    visit_id: str = ""
    considered: int = 0
    asked: int = 0
    proposals: int = 0
    promotions: int = 0
    demotions: int = 0
    rejected: int = 0
    budget_exhausted: bool = False
    #: Card NM-1. How many k-agreed names the independent judge was asked about,
    #: and how it answered. ``judge_held`` counts the names that would have
    #: entered ``known_places()`` under the k-gate alone and did not.
    judged: int = 0
    judge_accepted: int = 0
    judge_rejected: int = 0
    judge_unavailable: int = 0
    judge_held: int = 0
    outcomes: list[NamingOutcome] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "visit_id": self.visit_id,
            "considered": self.considered,
            "asked": self.asked,
            "proposals": self.proposals,
            "promotions": self.promotions,
            "demotions": self.demotions,
            "rejected": self.rejected,
            "budget_exhausted": self.budget_exhausted,
            "judged": self.judged,
            "judge_accepted": self.judge_accepted,
            "judge_rejected": self.judge_rejected,
            "judge_unavailable": self.judge_unavailable,
            "judge_held": self.judge_held,
            "outcomes": [o.as_dict() for o in self.outcomes],
        }


def normalize_proposal(text: str) -> str:
    """A raw VLM answer, reduced to a comparable name — or ``""`` for none.

    The k-gate compares names by string equality, so normalization IS the gate's
    tolerance: "a wooden bench", "Wooden bench." and "wooden bench" must be the
    same agreement or three correct visits will never agree with each other and
    nothing will ever be promoted. Kept deliberately mechanical (articles,
    punctuation, case, length, the non-name list) rather than synonym-aware — a
    synonym table here would be a closed vocabulary smuggled into the module
    whose entire purpose is to grow one.
    """

    cleaned = normalize_label(text)
    if not cleaned:
        return ""
    words = cleaned.split()
    while words and words[0] in ("a", "an", "the"):
        words = words[1:]
    if not words or len(words) > MAX_NAME_WORDS:
        return ""
    candidate = " ".join(words)
    if candidate in _NON_NAMES:
        return ""
    return candidate


def entries_needing_a_name(
    entries: Iterable[MapEntry], *, include_promoted: bool = False
) -> list[MapEntry]:
    """Which places this pass should look at.

    An entry needs a name when it has no *admissible* one beyond the detector
    label it was born with — i.e. the map can find it but the owner has no word
    for it that the dog will accept. With ``include_promoted`` the pass revisits
    already-promoted names too, which is what makes demotion reachable: a name
    that is never re-examined can never be found wrong.
    """

    out: list[MapEntry] = []
    for entry in entries:
        if not entry.retrievable:
            continue
        if not entry.thumbnail:
            # Nothing to look at. C-2 keeps one bounded best-view crop per entry
            # and an entry without one has never had a good view of itself.
            continue
        promoted = [n for n in entry.names if n.provenance == NAME_PROMOTED]
        if promoted and not include_promoted:
            continue
        out.append(entry)
    return out


def demote_disagreed_names(
    entry: MapEntry, agreed: str, *, wall_s: float
) -> tuple[str, ...]:
    """One visit disagreed with every name except ``agreed``. Record that.

    Returns the names that lost standing. Detector labels are never touched —
    they are the label channel, not a hypothesis, and demoting one would delete
    the map's own index. A name that drops below :data:`NAME_PROMOTION_VISITS`
    reverts to ``vlm_proposed`` and leaves ``known_places()`` in the same call.

    The mechanism is deliberately the *inverse* of promotion: promotion adds one
    supporting visit, demotion removes one. So k disagreements undo k
    agreements, and a name the world keeps contradicting decays at exactly the
    rate a name the world keeps confirming grows.
    """

    demoted: list[str] = []
    rebuilt: list[ProposedName] = []
    for name in entry.names:
        # Only names that have STANDING are demoted — the promoted ones, the
        # ones ``known_places()`` is actually serving. Three deliberate
        # exclusions:
        #
        #   the detector label   it is the label channel, not a hypothesis;
        #                        demoting it would delete the map's own index
        #   the agreed name      this visit voted FOR it
        #   an un-promoted guess a hypothesis with one or two supporting visits
        #                        has not been contradicted, it simply has not
        #                        won yet. Taking a visit off it would make k=3
        #                        mean "three visits IN A ROW", which is a much
        #                        stricter gate than the one the research sized
        #                        (~82-87 % accuracy behind k independent
        #                        agreements) and would stop the vocabulary
        #                        growing at all. Measured: with the strict
        #                        reading, 0 of 8 objects promoted anything.
        #
        # ``entry.names`` is capped at MAX_NAMES_PER_ENTRY, so hypotheses that
        # never win are bounded by the map itself rather than by this function.
        if (
            name.provenance == NAME_DETECTOR_LABEL
            or name.text == agreed
            or not name.admissible
        ):
            rebuilt.append(name)
            continue
        ids = tuple(name.supporting_visit_ids[:-1])
        provenance = name.provenance
        if provenance == NAME_PROMOTED and len(ids) < NAME_PROMOTION_VISITS:
            provenance = NAME_VLM_PROPOSED
        replacement = ProposedName(
            text=name.text,
            provenance=provenance,
            visits=len(ids),
            supporting_visit_ids=ids,
        )
        rebuilt.append(replacement)
        if not replacement.admissible:
            demoted.append(name.text)
            entry.note(wall_s, DEMOTION_EVENT, f"{name.text} (below k)")
    if demoted:
        entry.names = tuple(rebuilt)
    return tuple(demoted)


def hold_at_hypothesis(
    entry: MapEntry, text: str, *, wall_s: float, reason: str = ""
) -> bool:
    """Card NM-1. Strip a name's STANDING without touching its evidence.

    The k-gate said yes; the independent judge did not. The name goes back to
    ``vlm_proposed`` — out of ``known_places()``, out of the text channel's
    admissible set — while **keeping every supporting visit id it had earned**.
    That distinction is the whole design:

    * a **demotion** (:func:`demote_disagreed_names`) takes a supporting visit
      away, because a later visit contradicted the name. Evidence changed.
    * a **hold** takes none away, because nothing about the visits changed — what
      happened is that a second, independent seat looked at the same crop and did
      not see the thing. Evidence did not change; the name simply never earned
      the right the k-gate was about to hand it.

    Keeping the visits matters. If a hold also removed one, a name the judge
    cannot check today (no weights, no GPU moment) would decay toward nothing
    just for being unverifiable, and the next pass would have to re-earn three
    visits before it could ask again. Instead the name sits at k with no
    standing, and the moment the judge agrees it is vocabulary.

    Returns whether anything changed. Detector labels are never touched: they are
    the label channel, not a hypothesis, and this function has no business in it.
    """

    wanted = normalize_label(text)
    if not wanted:
        return False
    rebuilt: list[ProposedName] = []
    changed = False
    for name in entry.names:
        if name.text != wanted or name.provenance == NAME_DETECTOR_LABEL:
            rebuilt.append(name)
            continue
        if not name.admissible:
            rebuilt.append(name)
            continue
        rebuilt.append(
            ProposedName(
                text=name.text,
                provenance=NAME_VLM_PROPOSED,
                visits=len(name.supporting_visit_ids),
                supporting_visit_ids=name.supporting_visit_ids,
            )
        )
        changed = True
        entry.note(wall_s, HOLD_EVENT, f"{name.text} ({reason or 'judge disagreed'})"[:160])
    if changed:
        entry.names = tuple(rebuilt)
    return changed


def run_naming_pass(
    online_map: Any,
    describe: Callable[[bytes | None], Any],
    *,
    visit_id: str,
    wall_s: float | None = None,
    budget_s: float = DEFAULT_BATCH_BUDGET_S,
    include_promoted: bool = True,
    limit: int = 64,
    clock: Callable[[], float] | None = None,
    judge: Any = None,
) -> NamingReport:
    """Name every unnamed place the map can show a crop of. **Idle time only.**

    ``describe`` is the seat — :meth:`parcel_robot.vlm_veto.Qwen3VLVerifier.describe`
    or anything with its shape — and is injected rather than imported so this
    module never depends on a tensor library and can be driven by a fixture.

    ``visit_id`` must be the id of the visit this pass belongs to. It is what the
    k-gate counts, and passing a fresh id per *frame* rather than per *visit*
    would let one stare promote a name in three ticks, which is precisely the
    property the gate exists to prevent. The caller owns that contract; this
    function does not invent visit ids.

    ``judge`` (card NM-1) is the independent correctness seat —
    :class:`parcel_robot.vlm_veto.judge.OwlV2NamingJudge` or anything with its
    shape, injected for the same reason ``describe`` is. It is asked about a name
    only when that name **has standing** (the k-gate has admitted it), which is
    both the cheapest place to ask and the only place it matters:

    * ``accept``      -> the name is vocabulary. Both gates agreed.
    * ``reject``      -> :func:`hold_at_hypothesis`. The name keeps its visits and
                         loses its standing; it never reaches ``known_places()``.
    * ``unavailable`` -> **nothing is taken away.** A name promoted on an earlier
                         pass keeps its standing; a name promoting on THIS pass
                         is held, because vocabulary granted on an unchecked name
                         is the thing this card exists to stop. It promotes for
                         real as soon as the judge can answer.

    ``judge=None`` is the default and reproduces HEAD exactly.
    """

    now = clock if clock is not None else time.monotonic
    stamp = float(wall_s) if wall_s is not None else time.time()
    report = NamingReport(visit_id=str(visit_id))
    started = now()
    entries = entries_needing_a_name(
        online_map.active_entries(), include_promoted=include_promoted
    )[: max(0, int(limit))]
    report.considered = len(entries)
    for entry in entries:
        if budget_s > 0.0 and (now() - started) >= budget_s:
            report.budget_exhausted = True
            break
        try:
            answer = describe(entry.thumbnail)
        except Exception as exc:  # noqa: BLE001 - a broken seat skips, never crashes a pass
            logger.warning("naming pass: describe failed for %s: %s", entry.entry_id, exc)
            report.outcomes.append(NamingOutcome(entry.entry_id, skipped=str(exc)[:80]))
            continue
        report.asked += 1
        text = normalize_proposal(getattr(answer, "text", answer))
        if not text:
            report.rejected += 1
            report.outcomes.append(
                NamingOutcome(entry.entry_id, skipped="not a name")
            )
            continue
        if text == entry.label:
            # The VLM agreed with the detector. True, and worth nothing: the
            # entry already carries that word through the label channel, and
            # recording it as a *proposal* would let the VLM promote a name it
            # did not contribute — a second vote for the detector's own answer.
            report.outcomes.append(
                NamingOutcome(entry.entry_id, proposed=text, skipped="same as label")
            )
            continue
        before = set(entry.admissible_names())
        proposed = online_map.propose_name(
            entry.entry_id, text, visit_id=str(visit_id), wall_s=stamp
        )
        report.proposals += 1
        promoted = proposed.admissible and proposed.text not in before
        # ---- CARD NM-1 — the second gate. Consistency, then correctness. ----
        #
        # Asked whenever the name HAS STANDING, not only on the promotion edge:
        # a name that was promoted on an earlier pass while the judge was
        # unavailable must be re-examined, or "unavailable once" would become
        # "vocabulary forever". Costs one detector call per admissible name per
        # idle pass, which is 43-85 ms on this host and nowhere near the loop.
        judged = ""
        strength: float | None = None
        held = False
        if judge is not None and proposed.admissible:
            verdict = _ask_the_judge(judge, proposed.text, entry)
            judged = str(getattr(verdict, "outcome", "") or "")
            strength = getattr(verdict, "strength", None)
            report.judged += 1
            if judged == "accept":
                report.judge_accepted += 1
            elif judged == "reject":
                report.judge_rejected += 1
                held = hold_at_hypothesis(
                    entry,
                    proposed.text,
                    wall_s=stamp,
                    reason=f"judge {getattr(verdict, 'model', '')} "
                    f"scored {strength} < {getattr(verdict, 'floor', '')}",
                )
            else:
                report.judge_unavailable += 1
                # Nothing is taken away from a name that already had standing;
                # only a promotion happening RIGHT NOW is withheld.
                if promoted:
                    held = hold_at_hypothesis(
                        entry,
                        proposed.text,
                        wall_s=stamp,
                        reason="judge unavailable",
                    )
            if held:
                report.judge_held += 1
                promoted = False
        # ---- END CARD NM-1 ---------------------------------------------------
        report.promotions += promoted
        demoted = demote_disagreed_names(entry, proposed.text, wall_s=stamp)
        report.demotions += len(demoted)
        report.outcomes.append(
            NamingOutcome(
                entry.entry_id,
                proposed=proposed.text,
                promoted=promoted,
                demoted=demoted,
                judged=judged,
                judge_strength=strength,
                held=held,
            )
        )
    return report


def _ask_the_judge(judge: Any, name: str, entry: MapEntry) -> Any:
    """One judgement, and never a crash. A broken judge HOLDS, it never accepts.

    The failure direction is the whole point: an exception from the judge must
    not be readable as agreement, because "the check errored" and "the check
    passed" would then be the same event to the only caller that matters.
    """

    from parcel_robot.perception.abstention import ControlLoopViolation
    from parcel_robot.vlm_veto.judge import JUDGE_UNAVAILABLE, JudgeVerdict

    try:
        return judge.judge(name, entry.thumbnail, entry_id=entry.entry_id)
    except ControlLoopViolation:
        # NEVER softened. A naming pass on the 10 Hz thread is the FATAL defect
        # DW-2 (a) is about; swallowing it here would turn the loudest possible
        # signal into a quiet "unavailable" and the name would merely hold.
        raise
    except Exception as exc:  # noqa: BLE001 - a broken judge holds, never promotes
        logger.warning("naming pass: judge failed for %s: %s", entry.entry_id, exc)
        return JudgeVerdict(
            JUDGE_UNAVAILABLE, name=name, entry_id=entry.entry_id, detail=str(exc)[:120]
        )


def replay_visits(
    online_map: Any,
    describe: Callable[[bytes | None], Any],
    visit_ids: Sequence[str],
    **kwargs: Any,
) -> list[NamingReport]:
    """Run one pass per visit id. The k-gate's shape, made easy to measure.

    Exists because "does this promote after three visits and not after two" is
    the only question worth asking about a promotion gate, and asking it should
    not require the caller to remember that the ids must be distinct.
    """

    seen = list(dict.fromkeys(str(v) for v in visit_ids))
    if len(seen) != len(visit_ids):
        raise ValueError("replay_visits needs DISTINCT visit ids; k counts visits")
    return [
        run_naming_pass(online_map, describe, visit_id=vid, **kwargs) for vid in seen
    ]
