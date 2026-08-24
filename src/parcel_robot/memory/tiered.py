"""Low-latency tiered conversation memory (owner's three-tier architecture).

The owner's intent, verbatim: *"the most recent conversation can be brought up
to memory while the older conversations can be summarized. And much older
conversation can be summarized as the user's personality profile."* This module
is that store, expressed as a **pure, append-only turn log with three retrieval
tiers**:

- **Tier 1 — recent (verbatim).** The last ``tier1_max_turns`` turns, kept word
  for word. Low latency, no compression, no model.
- **Tier 2 — older (rolling summaries).** When a turn ages out of Tier 1 it is
  folded into its conversation's *rolling summary* by an **injected**
  ``summarizer`` (a real ``summarize()`` at runtime; a deterministic fake in
  tests). The summary **text** is stored; nothing re-summarizes on read.
- **Tier 3 — much-older (durable profile).** When Tier 2 overflows, its oldest
  summaries are distilled by an **injected** ``distiller`` into typed
  :class:`ProfileFact` rows (``key``, ``value``, ``confidence``,
  ``last_updated_turn_id``, ``source_turn_ids``) — durable facts/traits about the
  owner. Owner-profile seeds (``home: Manhattan``) can be planted here directly.

**The read path is deterministic and model-free.** :meth:`TieredMemory.retrieve`
does list slicing plus a cheap keyword overlap; it *never* calls the summarizer
or distiller. Summarization/distillation happen only on the write path
(:meth:`append`). That is the low-latency contract: a query pulls the right tier
by lookup, never a re-scan or a re-summarize. Provenance is a logical clock
(``turn_id``), not the wall clock, so two identical write sequences produce
byte-identical state and retrievals.

Honesty boundary: the *quality* of Tier-2 summaries and Tier-3 facts is only as
good as the injected model. This module proves the **mechanism** (an aged-out
fact survives into a summary/profile and is retrievable); it does not prove a
real LLM writes good summaries — that needs a live-model eval.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: Research H5. The on-disk shape of :meth:`TieredMemory.save`. Versioned so a
#: later tier layout can refuse an older file instead of half-loading it.
TIERED_SNAPSHOT_SCHEMA = "parcel.tiered_memory.v1"

_TOKEN = re.compile(r"[a-z0-9']+")

# Function words carry no retrieval signal; drop them before scoring overlap.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "did", "do",
        "for", "get", "go", "had", "has", "have", "how", "i", "if", "in", "is",
        "it", "me", "my", "of", "on", "or", "so", "that", "the", "to", "up",
        "was", "we", "what", "when", "where", "who", "will", "with", "would",
        "you", "your", "about", "tell", "remind", "remember", "recall", "again",
        "please", "just", "really", "this", "these", "those", "am", "im",
    }
)


def _terms(text: str) -> set[str]:
    """Casefolded content tokens with function words removed."""

    return {tok for tok in _TOKEN.findall(text.lower()) if tok not in _STOPWORDS}


def keyword_overlap(query: str, text: str) -> float:
    """Cheap deterministic relevance in [0, 1]: |q ∩ t| / |q|.

    Zero when the query has no content terms. This is the only "retrieval model"
    on the read path — no embeddings required (an embedding ranker can replace it
    behind the same signature if one is present).
    """

    q_terms = _terms(query)
    if not q_terms:
        return 0.0
    t_terms = _terms(text)
    if not t_terms:
        return 0.0
    return len(q_terms & t_terms) / len(q_terms)


# --- typed rows -----------------------------------------------------------------


@dataclass(frozen=True)
class Turn:
    """One appended conversation turn (Tier 1 lives verbatim as these)."""

    turn_id: int
    session_id: str
    role: str
    content: str


@dataclass(frozen=True)
class SummaryRecord:
    """A Tier-2 rolling summary of one conversation's aged-out turns."""

    summary_id: int
    session_id: str
    text: str
    source_turn_ids: tuple[int, ...]
    updated_at_turn_id: int


@dataclass(frozen=True)
class FactProposal:
    """A distiller's output row: a durable fact proposed from a summary.

    The store attaches provenance (``source_turn_ids``, ``last_updated``); the
    distiller only proposes the semantic content and a confidence.
    """

    key: str
    value: str
    confidence: float = 1.0


@dataclass(frozen=True)
class ProfileFact:
    """A Tier-3 durable fact/trait about the owner (typed, provenanced)."""

    key: str
    value: str
    confidence: float
    last_updated_turn_id: int
    source_turn_ids: tuple[int, ...]


@dataclass(frozen=True)
class Retrieval:
    """What a query pulls back: the three tiers, by cheap lookup, model-free."""

    query: str | None
    tier1_recent: tuple[Turn, ...]
    tier2_summaries: tuple[SummaryRecord, ...]
    tier3_profile: tuple[ProfileFact, ...]


@runtime_checkable
class Summarizer(Protocol):
    """Fold newly-aged turns into a conversation's rolling summary.

    Called only on the write path. Receives the summary text so far (``""`` for a
    fresh conversation) and the turns that just aged out; returns the updated
    summary text.
    """

    def __call__(self, previous_summary: str, aged_turns: Sequence[Turn]) -> str: ...


@runtime_checkable
class Distiller(Protocol):
    """Distill one aged-out summary into durable profile facts.

    Called only on the write path (Tier-2 overflow). Returns zero or more
    :class:`FactProposal` rows.
    """

    def __call__(self, summary: SummaryRecord) -> Sequence[FactProposal]: ...


# --- configuration (fail-closed) ------------------------------------------------


@dataclass(frozen=True)
class TieredMemoryConfig:
    """Frozen, validated knobs. Invalid values fail closed at construction."""

    tier1_max_turns: int = 8
    tier2_max_summaries: int = 6
    retrieval_summaries: int = 3
    retrieval_min_overlap: float = 0.0
    retrieval_profile_facts: int = 8
    valid_roles: frozenset[str] = frozenset({"user", "assistant", "tool"})

    def __post_init__(self) -> None:
        if self.tier1_max_turns < 1:
            raise ValueError("tier1_max_turns must be at least 1")
        if self.tier2_max_summaries < 1:
            raise ValueError("tier2_max_summaries must be at least 1")
        if self.retrieval_summaries < 1:
            raise ValueError("retrieval_summaries must be at least 1")
        if self.retrieval_profile_facts < 1:
            raise ValueError("retrieval_profile_facts must be at least 1")
        if not 0.0 <= self.retrieval_min_overlap <= 1.0:
            raise ValueError("retrieval_min_overlap must be in [0, 1]")
        if not self.valid_roles:
            raise ValueError("valid_roles must be non-empty")


def _normalize_key(key: str) -> str:
    clean = "_".join(str(key).strip().lower().split())
    if not clean:
        raise ValueError("profile fact key must be non-empty")
    return clean


class TieredMemory:
    """Append-only turn log with three deterministic retrieval tiers.

    ``summarizer`` and ``distiller`` are injected and invoked *only* while
    appending. :meth:`retrieve` is a pure read: it slices Tier 1, ranks live
    Tier-2 summaries by keyword overlap, and returns the Tier-3 profile — with no
    model call, no clock, and no re-summarization.
    """

    def __init__(
        self,
        *,
        summarizer: Summarizer,
        distiller: Distiller,
        config: TieredMemoryConfig | None = None,
    ) -> None:
        if not callable(summarizer):
            raise TypeError("summarizer must be callable")
        if not callable(distiller):
            raise TypeError("distiller must be callable")
        self._config = config or TieredMemoryConfig()
        self._summarizer = summarizer
        self._distiller = distiller
        self._turns: list[Turn] = []
        # Number of leading turns that have aged out of Tier 1 (folded into Tier 2).
        self._aged_count = 0
        self._summaries: list[SummaryRecord] = []
        # session_id -> index in ``_summaries`` of its live rolling summary.
        self._summary_by_session: dict[str, int] = {}
        # Number of leading summaries that have been distilled into Tier 3.
        self._distilled_count = 0
        self._profile: dict[str, ProfileFact] = {}
        self._next_summary_id = 1

    # -- configuration / introspection ------------------------------------------

    @property
    def config(self) -> TieredMemoryConfig:
        return self._config

    def turn_count(self) -> int:
        return len(self._turns)

    def stats(self) -> dict[str, int]:
        """Cheap tier sizes, for /api/prompt or a result artifact."""

        return {
            "turns": len(self._turns),
            "tier1_recent": min(len(self._turns), self._config.tier1_max_turns),
            "tier2_summaries": len(self._summaries) - self._distilled_count,
            "tier3_profile_facts": len(self._profile),
            "summaries_distilled": self._distilled_count,
        }

    # -- write path (summarizer/distiller allowed here, never on read) ----------

    def append(self, role: str, content: str, *, session_id: str = "default") -> Turn:
        """Append one turn and age the tiers. Fail-closed on a bad role/content."""

        if role not in self._config.valid_roles:
            raise ValueError(
                f"unsupported memory role: {role!r} "
                f"(expected one of {sorted(self._config.valid_roles)})"
            )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("memory content must be a non-empty string")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be a non-empty string")
        turn = Turn(
            turn_id=len(self._turns) + 1,
            session_id=session_id,
            role=role,
            content=content,
        )
        self._turns.append(turn)
        self._age()
        return turn

    def seed_profile_facts(self, facts: dict[str, str] | Sequence[tuple[str, str]]) -> None:
        """Plant durable Tier-3 rows directly (owner-profile seeds).

        Owner facts (``home: Manhattan``) become real profile rows rather than a
        hardcoded prompt string. Seeds carry no source turns and a logical
        timestamp of 0 so a later distilled observation can override them.
        """

        items = facts.items() if isinstance(facts, dict) else facts
        for key, value in items:
            clean_value = " ".join(str(value).split())
            if not clean_value:
                raise ValueError("profile fact value must be non-empty")
            norm = _normalize_key(key)
            self._profile[norm] = ProfileFact(
                key=norm,
                value=clean_value,
                confidence=1.0,
                last_updated_turn_id=0,
                source_turn_ids=(),
            )

    def _age(self) -> None:
        boundary = max(0, len(self._turns) - self._config.tier1_max_turns)
        while self._aged_count < boundary:
            self._fold_into_summary(self._turns[self._aged_count])
            self._aged_count += 1
        self._maybe_distill()

    def _fold_into_summary(self, turn: Turn) -> None:
        index = self._summary_by_session.get(turn.session_id)
        if index is None:
            text = self._summarizer("", (turn,))
            record = SummaryRecord(
                summary_id=self._next_summary_id,
                session_id=turn.session_id,
                text=text,
                source_turn_ids=(turn.turn_id,),
                updated_at_turn_id=turn.turn_id,
            )
            self._summaries.append(record)
            self._summary_by_session[turn.session_id] = len(self._summaries) - 1
            self._next_summary_id += 1
        else:
            record = self._summaries[index]
            text = self._summarizer(record.text, (turn,))
            self._summaries[index] = SummaryRecord(
                summary_id=record.summary_id,
                session_id=record.session_id,
                text=text,
                source_turn_ids=record.source_turn_ids + (turn.turn_id,),
                updated_at_turn_id=turn.turn_id,
            )

    def _maybe_distill(self) -> None:
        while (len(self._summaries) - self._distilled_count) > self._config.tier2_max_summaries:
            record = self._summaries[self._distilled_count]
            # If this session's live rolling summary is the one aging into Tier 3,
            # forget the mapping so any later turns start a fresh Tier-2 summary.
            if self._summary_by_session.get(record.session_id) == self._distilled_count:
                del self._summary_by_session[record.session_id]
            self._distilled_count += 1
            for proposal in self._distiller(record):
                self._merge_fact(proposal, record)

    def _merge_fact(self, proposal: FactProposal, source: SummaryRecord) -> None:
        clean_value = " ".join(str(proposal.value).split())
        if not clean_value:
            return
        key = _normalize_key(proposal.key)
        existing = self._profile.get(key)
        prior_ids = existing.source_turn_ids if existing else ()
        merged_ids = tuple(sorted(set(prior_ids) | set(source.source_turn_ids)))
        last_updated = source.updated_at_turn_id
        if existing is not None:
            last_updated = max(last_updated, existing.last_updated_turn_id)
        confidence = float(proposal.confidence)
        if existing is not None:
            confidence = max(confidence, existing.confidence)
        self._profile[key] = ProfileFact(
            key=key,
            value=clean_value,
            confidence=confidence,
            last_updated_turn_id=last_updated,
            source_turn_ids=merged_ids,
        )

    # -- read path (pure; no summarizer, no distiller, no clock) ----------------

    def tier1(self) -> tuple[Turn, ...]:
        """The last ``tier1_max_turns`` turns, verbatim."""

        return tuple(self._turns[-self._config.tier1_max_turns :])

    def live_summaries(self) -> tuple[SummaryRecord, ...]:
        """Tier-2 summaries not yet distilled into Tier 3, oldest first."""

        return tuple(self._summaries[self._distilled_count :])

    def profile(self) -> tuple[ProfileFact, ...]:
        """Tier-3 durable facts, sorted by key for a stable render."""

        return tuple(sorted(self._profile.values(), key=lambda fact: fact.key))

    def retrieve(self, query: str | None = None) -> Retrieval:
        """Return {Tier 1 verbatim, relevant Tier 2, Tier 3 profile} by lookup.

        Deterministic and model-free: no summarizer/distiller is invoked, no
        wall clock is read. Ties break on descending ``summary_id`` / ascending
        key so the ordering is total and reproducible.
        """

        tier1 = self.tier1()
        live = self.live_summaries()
        has_query = bool(query and query.strip())

        if has_query:
            assert query is not None
            scored = [
                (keyword_overlap(query, summary.text), summary) for summary in live
            ]
            relevant = [
                (score, summary)
                for score, summary in scored
                if score > 0 and score >= self._config.retrieval_min_overlap
            ]
            relevant.sort(key=lambda pair: (-pair[0], -pair[1].summary_id))
            tier2 = tuple(
                summary for _, summary in relevant[: self._config.retrieval_summaries]
            )
        else:
            # No query: the most recent summaries (still relevant by recency).
            tier2 = tuple(live[-self._config.retrieval_summaries :])

        facts = list(self._profile.values())
        if has_query:
            assert query is not None
            facts.sort(
                key=lambda fact: (
                    -keyword_overlap(query, f"{fact.key} {fact.value}"),
                    fact.key,
                )
            )
        else:
            facts.sort(key=lambda fact: fact.key)
        tier3 = tuple(facts[: self._config.retrieval_profile_facts])

        return Retrieval(
            query=query,
            tier1_recent=tier1,
            tier2_summaries=tier2,
            tier3_profile=tier3,
        )


    # -- persistence (research H5) ----------------------------------------------
    #
    # WHY THIS EXISTS: every summary and every profile fact this class has ever
    # produced died with the process. The three-tier design's whole promise is
    # that "much older conversation" becomes a durable profile, and durable is
    # exactly the property it did not have — a robot restarted on Tuesday knew
    # nothing it had worked out on Monday.
    #
    # WHY JSON AND NOT A TABLE: the design offered either. JSON rows won because
    # the state is small (bounded by ``tier2_max_summaries`` and the profile
    # dict), because a snapshot is read and written whole rather than queried,
    # and because a file an owner can open in a text editor is the right shape
    # for the one artifact that says what the robot has decided to believe about
    # them. ``memory/store.py``'s sqlite is for rows nobody reads by hand.
    #
    # WHY THE TURN LOG RIDES ALONG: the design says "tiers 2/3". Tier 1 is
    # persisted too, because :meth:`retrieve` returns all three tiers and a
    # reload that dropped Tier 1 would answer the same query differently — which
    # is precisely the property (persist -> reload -> identical answers) the
    # persistence exists to provide. It is stated rather than assumed.
    #
    # NO CLOCK IN THE FILE. The module's determinism contract is a logical clock
    # (``turn_id``), so two saves of the same state are byte-identical and a diff
    # of two snapshots shows what the robot LEARNED rather than when it was
    # written down.

    def snapshot(self) -> dict[str, Any]:
        """The whole state as plain JSON-able rows, with provenance. Pure."""

        return {
            "schema": TIERED_SNAPSHOT_SCHEMA,
            "config": {
                "tier1_max_turns": self._config.tier1_max_turns,
                "tier2_max_summaries": self._config.tier2_max_summaries,
                "retrieval_summaries": self._config.retrieval_summaries,
                "retrieval_min_overlap": self._config.retrieval_min_overlap,
                "retrieval_profile_facts": self._config.retrieval_profile_facts,
            },
            "counters": {
                "aged_count": self._aged_count,
                "distilled_count": self._distilled_count,
                "next_summary_id": self._next_summary_id,
            },
            "turns": [
                {
                    "turn_id": turn.turn_id,
                    "session_id": turn.session_id,
                    "role": turn.role,
                    "content": turn.content,
                }
                for turn in self._turns
            ],
            "summaries": [
                {
                    "summary_id": record.summary_id,
                    "session_id": record.session_id,
                    "text": record.text,
                    "source_turn_ids": list(record.source_turn_ids),
                    "updated_at_turn_id": record.updated_at_turn_id,
                }
                for record in self._summaries
            ],
            "profile": [
                {
                    "key": fact.key,
                    "value": fact.value,
                    "confidence": fact.confidence,
                    "last_updated_turn_id": fact.last_updated_turn_id,
                    "source_turn_ids": list(fact.source_turn_ids),
                }
                for fact in self.profile()
            ],
        }

    def save(self, path: str | Path) -> Path:
        """Write the snapshot to ``path``. Atomic: temp file then rename.

        A half-written profile is worse than no profile — it is a set of beliefs
        with no record of what was dropped — so the rename is the commit.
        """

        target = Path(path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.snapshot(), indent=2, sort_keys=True, allow_nan=False)
        temp = target.with_name(target.name + ".partial")
        with temp.open("w", encoding="utf-8") as stream:
            stream.write(payload + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(target)
        return target

    def load(self, path: str | Path) -> int:
        """Replace this store's state from a snapshot. Returns rows restored.

        REPLACES rather than merges, deliberately: a merge would have to decide
        what to do about two profiles that disagree, and that decision belongs
        to the distiller and the policy, not to a file reader.
        """

        raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        return self.restore(raw)

    def restore(self, snapshot: Mapping[str, Any]) -> int:
        """Load an already-parsed snapshot. Refuses an unknown schema."""

        if not isinstance(snapshot, Mapping):
            raise TypeError("a tiered-memory snapshot must be a mapping")
        schema = str(snapshot.get("schema", ""))
        if schema != TIERED_SNAPSHOT_SCHEMA:
            raise ValueError(
                f"unknown tiered-memory snapshot schema {schema!r} "
                f"(this build reads {TIERED_SNAPSHOT_SCHEMA!r})"
            )
        counters = snapshot.get("counters") or {}
        self._turns = [
            Turn(
                turn_id=int(row["turn_id"]),
                session_id=str(row["session_id"]),
                role=str(row["role"]),
                content=str(row["content"]),
            )
            for row in snapshot.get("turns", ())
        ]
        self._summaries = [
            SummaryRecord(
                summary_id=int(row["summary_id"]),
                session_id=str(row["session_id"]),
                text=str(row["text"]),
                source_turn_ids=tuple(int(i) for i in row.get("source_turn_ids", ())),
                updated_at_turn_id=int(row["updated_at_turn_id"]),
            )
            for row in snapshot.get("summaries", ())
        ]
        self._profile = {
            str(row["key"]): ProfileFact(
                key=str(row["key"]),
                value=str(row["value"]),
                confidence=float(row.get("confidence", 1.0)),
                last_updated_turn_id=int(row.get("last_updated_turn_id", 0)),
                source_turn_ids=tuple(int(i) for i in row.get("source_turn_ids", ())),
            )
            for row in snapshot.get("profile", ())
        }
        self._aged_count = int(counters.get("aged_count", 0))
        self._distilled_count = int(counters.get("distilled_count", 0))
        self._next_summary_id = int(
            counters.get("next_summary_id", len(self._summaries) + 1)
        )
        # The live rolling summary per session is derived, never stored: two
        # sources for "which summary is this session's" is one source too many.
        self._summary_by_session = {
            record.session_id: index
            for index, record in enumerate(self._summaries)
            if index >= self._distilled_count
        }
        return len(self._turns) + len(self._summaries) + len(self._profile)


# --- reference deterministic summarizer/distiller (offline default) -------------


@dataclass
class ConcatSummarizer:
    """A model-free rolling summarizer: append each aged turn, bounded length.

    A safe offline default so a stack can build with no model server. It is a
    *stand-in*, not a good summarizer — it concatenates and truncates rather than
    abstracts. Swap in a real ``summarize()`` at runtime for quality.
    """

    max_chars: int = 1200
    include_roles: tuple[str, ...] = ("user", "assistant", "tool")

    def __call__(self, previous_summary: str, aged_turns: Sequence[Turn]) -> str:
        parts = [previous_summary] if previous_summary else []
        for turn in aged_turns:
            if turn.role in self.include_roles:
                parts.append(f"{turn.role}: {turn.content}")
        text = " ".join(part for part in parts if part).strip()
        if len(text) > self.max_chars:
            text = text[: self.max_chars - 1].rstrip() + "…"
        return text


def null_distiller(summary: SummaryRecord) -> Sequence[FactProposal]:
    """A distiller that proposes nothing (Tier 3 stays seed-only)."""

    del summary
    return ()


__all__ = [
    "TIERED_SNAPSHOT_SCHEMA",
    "ConcatSummarizer",
    "Distiller",
    "FactProposal",
    "ProfileFact",
    "Retrieval",
    "Summarizer",
    "SummaryRecord",
    "TieredMemory",
    "TieredMemoryConfig",
    "Turn",
    "keyword_overlap",
    "null_distiller",
]
