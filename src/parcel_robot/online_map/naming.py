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

Scope note: ``online_map/`` is P1-B's package. This module is P1-D's only file
in it and it touches the rest **through the public API** —
``active_entries()``, ``propose_name()``, ``entry.note()``, ``entry.names`` —
adding no method and changing no line anywhere else in the package.
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
    "MAX_NAME_WORDS",
    "NAME_PROMOTION_VISITS",
    "NamingOutcome",
    "NamingReport",
    "demote_disagreed_names",
    "entries_needing_a_name",
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

    def as_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "proposed": self.proposed,
            "promoted": self.promoted,
            "demoted": list(self.demoted),
            "skipped": self.skipped,
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
        report.promotions += promoted
        demoted = demote_disagreed_names(entry, proposed.text, wall_s=stamp)
        report.demotions += len(demoted)
        report.outcomes.append(
            NamingOutcome(
                entry.entry_id,
                proposed=proposed.text,
                promoted=promoted,
                demoted=demoted,
            )
        )
    return report


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
