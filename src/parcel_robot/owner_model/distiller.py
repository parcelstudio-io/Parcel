"""A distiller that actually proposes facts — and a policy that decides them.

CARD P2-A, WORK ITEM 2
======================

``tiered_memory.null_distiller`` is wired at ``dynamic_prompting.py:737`` and
returns ``()`` for every summary it is ever handed. Tier 3 — the "durable
profile" tier the whole three-tier design exists to produce — has therefore
never held anything but the seeds from ``configs/robot.yaml``. The hosted model
has, per turn, an "unknown" owner name, an "unknown" location, and six lines of
history. "My sister's name is Hana" becomes row 3164 of ``messages`` and
nothing else.

This module is the missing half. It has three pieces and they are deliberately
separable:

1. **A proposer** turns text into candidate facts. Two implementations:
   :class:`DeterministicFactProposer` (offline, regex, no model — the default,
   so a stack with no model server still learns *something* and every CI row is
   reproducible) and :class:`LanguageModelFactProposer` (the real one, over the
   existing ``LanguageModel.decide`` seam, degrading to the deterministic one on
   any failure or unparseable reply).
2. **The policy** (:mod:`.policy`) decides what may be kept. The proposer never
   decides. This is HLD §8.4's rule and the reason the two are different
   objects: swapping the model must not be able to change the privacy rules.
3. **The guard** (:mod:`.guard`) decides whether this store may be distilled at
   all. It runs FIRST, before a single turn is read.

WHY THE PROPOSER IS NOT ALLOWED TO SET CONSENT
----------------------------------------------

:class:`FactCandidate` has no consent field, and that is not an oversight. If a
proposal could carry its own consent state, then "may the robot keep the owner's
medication list" would be a question answered by whatever text the model
generated — which is precisely the arrangement HLD §8.4 forbids. The candidate
carries content and confidence; :func:`~parcel_robot.owner_model.policy.decide`
supplies the verdict; :func:`distil_turns` is the only place the two meet.

TWO ENTRY POINTS, ONE PIPELINE
------------------------------

* :func:`distil_session` is the product path: point it at a
  :class:`~parcel_robot.memory.ConversationMemory` and it reads that session's
  turns, guards, proposes, decides, and writes ``owner_facts`` rows.
* :class:`OwnerFactDistiller` is the
  :class:`~parcel_robot.tiered_memory.Distiller` protocol implementation, so the
  same proposer can be dropped into ``TieredMemory`` in place of
  ``null_distiller`` and produce real Tier-3 ``ProfileFact`` rows. It shares the
  proposer and the policy with the product path; only the row type differs.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from ..tiered_memory import FactProposal, SummaryRecord
from . import policy as privacy
from .guard import assert_store_is_distillable

if TYPE_CHECKING:  # pragma: no cover - typing only, no runtime import cycle
    from ..memory import ConversationMemory
    from ..providers import LanguageModel

logger = logging.getLogger(__name__)

#: How many of a session's turns a single distillation pass will look at. A
#: bound rather than "all of them" because this runs on the write path and the
#: owner's store is 3,163 rows deep: an unbounded pass would grow without limit
#: and would re-propose the same facts from the same ancient turns forever.
DEFAULT_TURN_WINDOW = 60

#: The most facts one pass may propose. A model that returns fifty "facts" for
#: one conversation has misunderstood the job, and the store should not carry
#: the consequences.
MAX_FACTS_PER_PASS = 12

#: Below this, a candidate is dropped before the policy sees it. Confidence is
#: the proposer's own claim and is not evidence — it only ever *narrows*.
MIN_CONFIDENCE = 0.3


@dataclass(frozen=True)
class FactCandidate:
    """One proposed fact. No consent field — see the module docstring.

    ``key`` is a slug for merge/overwrite ("sister_name"); ``value`` is the
    sentence the robot would say ("your sister is called Hana"). Keeping both
    is what lets a later proposal about the same subject REPLACE rather than
    accumulate, while still rendering as prose.
    """

    key: str
    value: str
    confidence: float = 1.0
    source_turn_ids: tuple[int, ...] = ()

    def normalized(self) -> FactCandidate:
        return FactCandidate(
            key=_slug(self.key),
            value=" ".join(str(self.value).split()),
            confidence=max(0.0, min(1.0, float(self.confidence))),
            source_turn_ids=tuple(int(i) for i in self.source_turn_ids),
        )


@dataclass(frozen=True)
class DistilledFact:
    """A candidate after the policy has ruled on it. The write unit."""

    candidate: FactCandidate
    decision: privacy.PolicyDecision

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.candidate.key,
            "value": self.candidate.value,
            "confidence": self.candidate.confidence,
            "source_turn_ids": list(self.candidate.source_turn_ids),
            **self.decision.as_dict(),
        }


@dataclass
class DistillationReport:
    """What one pass did, in enough detail to answer "why is that in there".

    Returned rather than logged because the caller (a status doc, a panel, a
    test) is the thing that needs it, and because a distillation pass that
    reports nothing is indistinguishable from one that did nothing.
    """

    turns_read: int = 0
    proposed: int = 0
    kept: tuple[DistilledFact, ...] = ()
    asked: tuple[DistilledFact, ...] = ()
    refused: tuple[DistilledFact, ...] = ()
    written: int = 0
    guard: dict[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "turns_read": self.turns_read,
            "proposed": self.proposed,
            "kept": [f.as_dict() for f in self.kept],
            "asked": [f.as_dict() for f in self.asked],
            "refused": [f.as_dict() for f in self.refused],
            "written": self.written,
            "guard": dict(self.guard),
        }


@runtime_checkable
class FactProposer(Protocol):
    """Text in, candidate facts out. Never decides whether they may be kept."""

    def __call__(self, turns: Sequence[Mapping[str, Any]]) -> Sequence[FactCandidate]: ...


def _slug(text: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")
    return clean or "fact"


# --- the offline proposer -------------------------------------------------------

#: (pattern, key template, value template). Written as an ordered list rather
#: than a dict because the FIRST match wins and reordering changes behaviour.
#:
#: This is a stand-in and says so. It exists so that (a) a stack with no model
#: server still derives the handful of facts an owner most obviously states, and
#: (b) every CI row in this card measures a MECHANISM against a fixed function
#: instead of measuring a language model's mood. The card's probe rows 1 and 2 —
#: the sister's name and a stated preference — are the two shapes it must catch.
#: The lead-in of every pattern is case-INSENSITIVE (``(?i:…)``) and the value
#: group is not. That asymmetry is load-bearing for the name patterns: "my
#: sister's name is Hana" has to match whether or not the transcriber
#: capitalised the sentence, while ``Hana`` is recognised as a name precisely
#: BECAUSE it is capitalised. A blanket ``re.IGNORECASE`` would make
#: "my sister's name is hard to spell" propose a person called "hard".
_PATTERNS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"(?i:\bmy\s+(?P<subject>[a-z]+(?:[- ][a-z]+)?)(?:'s)?\s+name\s+is\s+)"
            r"(?P<value>[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)",
        ),
        "{subject}_name",
        "their {subject} is called {value}",
    ),
    (
        re.compile(
            r"(?i:\bmy\s+(?P<subject>[a-z]+(?:[- ][a-z]+)?)\s+is\s+called\s+)"
            r"(?P<value>[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)",
        ),
        "{subject}_name",
        "their {subject} is called {value}",
    ),
    (
        re.compile(r"(?i:\bi(?:'m| am)\s+called\s+)(?P<value>[A-Z][\w'-]*)"),
        "owner_name",
        "they are called {value}",
    ),
    (
        re.compile(r"(?i:\bmy\s+name\s+is\s+)(?P<value>[A-Z][\w'-]*(?:\s+[A-Z][\w'-]*)?)"),
        "owner_name",
        "they are called {value}",
    ),
    (
        re.compile(
            r"(?i:\bi\s+(?:really\s+)?(?:like|love|prefer|enjoy)\s+(?P<value>[^.!?,;]{3,120}))"
        ),
        "preference",
        "they like {value}",
    ),
    (
        re.compile(r"(?i:\bi\s+(?:really\s+)?(?:hate|dislike)\s+(?P<value>[^.!?,;]{3,120}))"),
        "dislike",
        "they do not like {value}",
    ),
    (
        re.compile(r"(?i:\bi\s+(?:always|usually)\s+(?P<value>[^.!?,;]{3,120}))"),
        "routine",
        "they usually {value}",
    ),
    (
        re.compile(r"(?i:\bi\s+live\s+in\s+(?P<value>[^.!?,;]{2,80}))"),
        "home",
        "they live in {value}",
    ),
    (
        re.compile(r"(?i:\bi\s+work\s+(?:at|for)\s+(?P<value>[^.!?,;]{2,80}))"),
        "work",
        "they work at {value}",
    ),
    # LAST, and deliberately broad: "my <thing> is <value>". Everything above
    # is a shape the policy will KEEP; this one exists so the sensitive shapes
    # get PROPOSED at all. "my blood pressure medication is amlodipine" matches
    # nothing more specific, and a proposer that never proposes it is a
    # pipeline whose consent path is never exercised on the real path. It is
    # proposed, classified ``health``, and parked as ``pending`` — which is the
    # card's "ask first", working.
    (
        re.compile(
            r"(?i:\bmy\s+(?P<subject>[a-z]+(?:\s+[a-z]+){0,2})\s+is\s+)"
            r"(?P<value>[^.!?,;]{2,80})"
        ),
        "{subject}",
        "their {subject} is {value}",
    ),
)


@dataclass(frozen=True)
class DeterministicFactProposer:
    """Regex proposals. Offline, reproducible, and openly narrow.

    It reads only the OWNER's side of the conversation. The robot's own
    sentences are excluded on purpose: a robot that distils facts from its own
    replies builds a profile of itself and calls it the owner, and every
    hallucinated "you mentioned your sister Hana" would become a durable row on
    the next pass. Only what the owner said counts as something the owner said.
    """

    #: Which speakers count as the owner. Both spellings, because the two write
    #: paths label the same person differently (``role='user'`` on the legacy
    #: path, ``speaker='owner'`` on the hosted one).
    owner_speakers: frozenset[str] = frozenset({"owner", "user"})
    confidence: float = 0.6

    def __call__(self, turns: Sequence[Mapping[str, Any]]) -> Sequence[FactCandidate]:
        out: list[FactCandidate] = []
        seen: set[str] = set()
        for turn in turns:
            speaker = str(turn.get("speaker") or turn.get("role") or "").strip().lower()
            if speaker not in self.owner_speakers:
                continue
            text = " ".join(str(turn.get("content") or turn.get("text") or "").split())
            if not text:
                continue
            turn_id = turn.get("id")
            ids = (int(turn_id),) if isinstance(turn_id, int) else ()
            # EVERY pattern is tried against every owner turn, not just the
            # first that hits. One sentence routinely carries two facts ("my
            # sister's name is Hana and I like short answers"), and a proposer
            # that stopped at the first would silently drop the second forever
            # — there is no later pass that revisits an already-read turn.
            # ``seen`` keeps the first proposal for a key, so the SPECIFIC
            # patterns above still win over the broad one at the bottom.
            for pattern, key_template, value_template in _PATTERNS:
                match = pattern.search(text)
                if match is None:
                    continue
                groups = {
                    k: " ".join(str(v or "").split()) for k, v in match.groupdict().items()
                }
                key = _slug(key_template.format(**groups))
                if key in seen:
                    continue
                value = value_template.format(**groups).rstrip(" .")
                if not value:
                    continue
                seen.add(key)
                out.append(
                    FactCandidate(
                        key=key,
                        value=value,
                        confidence=self.confidence,
                        source_turn_ids=ids,
                    )
                )
        return tuple(out[:MAX_FACTS_PER_PASS])


# --- the real proposer ----------------------------------------------------------

_LM_PROMPT = (
    "You keep a small profile of a robot dog's owner. Read the conversation "
    "turns below and list ONLY durable facts about the OWNER that they stated "
    "themselves — names, preferences, routines, places. Do not infer, do not "
    "guess, and do not include anything the robot said. If there is nothing "
    "durable, reply with an empty list.\n\n"
    'Reply with ONLY a JSON array of objects: [{"key": "sister_name", '
    '"value": "their sister is called Hana", "confidence": 0.9}]\n'
    'The "value" is the sentence the robot would say back, in the third person.\n\n'
    "Turns:\n"
)


@dataclass
class LanguageModelFactProposer:
    """The real proposer, over the ``LanguageModel.decide`` seam already wired.

    Degrades to :class:`DeterministicFactProposer` on ANY failure, on an empty
    reply, and on a reply that is not a JSON array — the same contract
    ``runtime.LLMSummarizer`` already holds on the write path next door. A
    distillation pass must never break the thing that triggered it, and an
    offline run must stay deterministic.
    """

    model: LanguageModel
    fallback: DeterministicFactProposer = field(default_factory=DeterministicFactProposer)
    owner_speakers: frozenset[str] = frozenset({"owner", "user"})

    def __call__(self, turns: Sequence[Mapping[str, Any]]) -> Sequence[FactCandidate]:
        lines: list[str] = []
        for turn in turns:
            speaker = str(turn.get("speaker") or turn.get("role") or "").strip().lower()
            text = " ".join(str(turn.get("content") or turn.get("text") or "").split())
            if not text:
                continue
            who = "owner" if speaker in self.owner_speakers else "robot"
            lines.append(f"{who}: {text}")
        if not lines:
            return ()
        try:
            decision = self.model.decide(_LM_PROMPT + "\n".join(lines), [], [])
            payload = _parse_candidates(str(decision.reply))
        except Exception as error:  # noqa: BLE001 - degrade, never break the caller
            logger.warning("owner-fact proposer failed; using the offline one: %s", error)
            return self.fallback(turns)
        if not payload:
            return self.fallback(turns)
        return payload[:MAX_FACTS_PER_PASS]


def _parse_candidates(reply: str) -> list[FactCandidate]:
    """Best-effort JSON array of candidates, or ``[]``. Never raises.

    Tolerates a model that wraps the array in prose or a code fence, because
    every one of them does at least once, and a pass that returns nothing
    because of a backtick is a pass that looks like a policy decision.
    """

    text = str(reply or "").strip()
    if not text:
        return []
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        rows = json.loads(text[start : end + 1])
    except (TypeError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    out: list[FactCandidate] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        value = " ".join(str(row.get("value", "")).split())
        if not value:
            continue
        key = str(row.get("key") or value)
        try:
            confidence = float(row.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        out.append(FactCandidate(key=key, value=value, confidence=confidence).normalized())
    return out


# --- the pipeline ---------------------------------------------------------------


def distil_turns(
    turns: Sequence[Mapping[str, Any]],
    *,
    proposer: FactProposer | None = None,
) -> DistillationReport:
    """Propose, then decide. Pure: reads no store and writes nothing.

    Split out from :func:`distil_session` so the policy half can be tested
    without a database and so a caller can preview a pass before it writes.
    """

    proposer = proposer or DeterministicFactProposer()
    raw = list(proposer(turns))
    kept: list[DistilledFact] = []
    asked: list[DistilledFact] = []
    refused: list[DistilledFact] = []
    for candidate in raw[:MAX_FACTS_PER_PASS]:
        normalized = candidate.normalized()
        if normalized.confidence < MIN_CONFIDENCE:
            refused.append(
                DistilledFact(
                    normalized,
                    privacy.PolicyDecision(
                        category=privacy.CATEGORY_OTHER,
                        disposition=privacy.DISPOSITION_REFUSE,
                        consent=privacy.CONSENT_DENIED,
                        reason=(
                            f"the proposer's own confidence {normalized.confidence:.2f} "
                            f"is below {MIN_CONFIDENCE}"
                        ),
                    ),
                )
            )
            continue
        decision = privacy.decide(normalized.value)
        row = DistilledFact(normalized, decision)
        if decision.disposition == privacy.DISPOSITION_KEEP:
            kept.append(row)
        elif decision.disposition == privacy.DISPOSITION_ASK:
            asked.append(row)
        else:
            refused.append(row)
    return DistillationReport(
        turns_read=len(turns),
        proposed=len(raw),
        kept=tuple(kept),
        asked=tuple(asked),
        refused=tuple(refused),
    )


def distil_session(
    memory: ConversationMemory,
    *,
    session_id: str | None = None,
    proposer: FactProposer | None = None,
    turn_window: int = DEFAULT_TURN_WINDOW,
    store_label: str = "",
) -> DistillationReport:
    """The product path: guard, read, propose, decide, write.

    THE GUARD RUNS FIRST AND IS NOT OPTIONAL. There is no ``force`` argument,
    no environment override and no keyword that skips it. A caller who wants to
    distil the owner's real store runs the quarantine tool; that is the whole
    design (see :mod:`.guard`).

    Rows the policy said ``ask`` about are still WRITTEN, with
    ``consent='pending'`` — the ask is a record, not a discard, so the robot can
    come back to it ("you told me about your medication; do you want me to
    remember that?"). They never render and never appear in an answer until the
    owner grants them. Rows it refused are written nowhere at all.
    """

    label = store_label or getattr(getattr(memory, "store", None), "path", "")
    survey = assert_store_is_distillable(memory.connection, store_label=str(label))

    turns = memory.conversation_turns(limit=int(turn_window))
    # ``conversation_turns`` is newest-first; a distiller reads a conversation
    # the way it happened, so the last-N window is reversed back into order.
    ordered = list(reversed(turns))
    if session_id is not None:
        ordered = [t for t in ordered if str(t.get("session_id") or "") == str(session_id)]

    report = distil_turns(ordered, proposer=proposer)
    report.guard = survey.as_dict()

    written = 0
    for row in report.kept + report.asked:
        memory.add_owner_fact(
            key=row.candidate.key,
            value=row.candidate.value,
            provenance="model_proposed",
            consent=row.decision.consent,
            category=row.decision.category,
            confidence=row.candidate.confidence,
            session_id=session_id,
            source_turn_ids=row.candidate.source_turn_ids,
            reason=row.decision.reason,
        )
        written += 1
    report.written = written
    return report


# --- the tiered-memory protocol implementation ----------------------------------


@dataclass
class OwnerFactDistiller:
    """A real :class:`~parcel_robot.tiered_memory.Distiller`.

    Drop-in for ``null_distiller``: same signature, same return type, so
    ``TieredMemory``'s Tier-2 overflow starts producing ``ProfileFact`` rows
    instead of nothing. It runs the SAME proposer and the SAME policy as the
    product path, and it emits only the ``keep`` verdicts — Tier 3 is rendered
    into prompts unconditionally by ``dynamic_prompting``, so a ``pending`` row
    reaching it would be a consent bypass through the side door.
    """

    proposer: FactProposer = field(default_factory=DeterministicFactProposer)

    def __call__(self, summary: SummaryRecord) -> Sequence[FactProposal]:
        text = " ".join(str(getattr(summary, "text", "")).split())
        if not text:
            return ()
        # A rolling summary is prose, not turns. It is presented as one owner
        # turn because that is what it summarises — the alternative is teaching
        # the proposer a second input shape for no gain.
        turns = ({"speaker": "owner", "content": text},)
        report = distil_turns(turns, proposer=self.proposer)
        return tuple(
            FactProposal(
                key=row.candidate.key,
                value=row.candidate.value,
                confidence=row.candidate.confidence,
            )
            for row in report.kept
        )


__all__ = [
    "DEFAULT_TURN_WINDOW",
    "MAX_FACTS_PER_PASS",
    "MIN_CONFIDENCE",
    "DeterministicFactProposer",
    "DistillationReport",
    "DistilledFact",
    "FactCandidate",
    "FactProposer",
    "LanguageModelFactProposer",
    "OwnerFactDistiller",
    "distil_session",
    "distil_turns",
]
