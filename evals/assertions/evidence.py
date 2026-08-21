"""Load one session folder, and be honest about what is missing from it.

Card EV-1, and the single most load-bearing module in this package. The bench's
finding that produced work item 1 was not "the checks are wrong" — it was that
**every false positive in the extended checks was a ring-buffer eviction
artifact**: seventeen ``tool_provenance`` flags and several ``unanswered_turn``
flags on ``live_run_1`` were rows whose explaining event had already rolled off
the end of a 100-slot deque. The check was right; the evidence was a window.

So this module answers two questions, not one:

1. what does this session folder contain?
2. **is that the whole stream, or a window onto it?**

and every check reads the answer to (2) before it decides whether its finding is
a VERDICT or a REVIEW CANDIDATE. An eval that cannot tell those apart reports
the runtime's memory limits as the product's defects.

THE TWO SHAPES A SESSION FOLDER COMES IN
----------------------------------------
*Instrumented run folder* (``evals/20260820/**``, ``tools/run_voice_corpus.py``
output): ``ledger.json``, ``session_slices.json`` (``events`` / ``mission_log``
/ ``chat``), ``state.json``. The slices are RINGS — 100 / 20 / 80 slots.

*EV-1 session folder* (``<capture.dir>/<session_id>/``): ``events.jsonl``, the
uncapped stream, beside that session's ``owner.wav`` / ``robot.wav`` /
``index.json``. Every row that reached any of the three rings is in it, in
order, with the gaps (if any) named in the file.

Both are accepted, either may be missing pieces, and the object says which.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]

#: File names this loader knows.
LEDGER_NAME = "ledger.json"
SLICES_NAME = "session_slices.json"
STATE_NAME = "state.json"
RESULTS_NAME = "results.json"
EVENTS_JSONL_NAME = "events.jsonl"

#: Evidence-completeness classes, most complete first. These are the words the
#: matrix uses when it explains why a finding is a review candidate.
EVIDENCE_STREAM = "stream"
EVIDENCE_RING = "ring"
EVIDENCE_ABSENT = "absent"


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


@dataclass
class SessionEvidence:
    """Everything the checks are allowed to read, plus its provenance."""

    name: str
    path: Path
    ledger: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    mission_log: list[dict[str, Any]] = field(default_factory=list)
    safety_log: list[dict[str, Any]] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    results: dict[str, Any] = field(default_factory=dict)

    #: EVIDENCE_STREAM / EVIDENCE_RING / EVIDENCE_ABSENT, per stream.
    event_source: str = EVIDENCE_ABSENT
    mission_source: str = EVIDENCE_ABSENT
    safety_source: str = EVIDENCE_ABSENT
    #: Anything that makes this record less than complete, in words.
    gaps: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- accessors
    @property
    def lane(self) -> dict[str, Any]:
        """``state.realtime.lane``, or an empty mapping."""

        realtime = self.state.get("realtime")
        if isinstance(realtime, dict) and isinstance(realtime.get("lane"), dict):
            return realtime["lane"]
        return {}

    @property
    def broker(self) -> dict[str, Any]:
        realtime = self.state.get("realtime")
        if isinstance(realtime, dict) and isinstance(realtime.get("broker"), dict):
            return realtime["broker"]
        return {}

    @property
    def voice_identity(self) -> dict[str, Any]:
        """``state.realtime.gateway.voice_identity``, or an empty mapping.

        Card F1-SI. An empty mapping and ``{"enabled": false}`` mean different
        things to ``check_voice_provenance`` and must not be collapsed: the
        first is "this artifact predates the feature or has no gateway", the
        second is "the feature exists and nobody has enrolled". Both are review
        territory rather than verdicts, but only the second can be stated as a
        fact about the running product.
        """

        realtime = self.state.get("realtime")
        if not isinstance(realtime, dict):
            return {}
        gateway = realtime.get("gateway")
        if isinstance(gateway, dict) and isinstance(gateway.get("voice_identity"), dict):
            return gateway["voice_identity"]
        return {}

    @property
    def has_events(self) -> bool:
        return self.event_source != EVIDENCE_ABSENT

    @property
    def ledger_timestamped(self) -> bool:
        """Can this ledger support a TEMPORAL claim at all?

        Found live: a session folder whose collector dropped ``created_at``
        makes every "no tool event within N seconds" check fire on every row,
        because the join it needs cannot be computed. That is not a defect in
        the product and it is not a defect in the check — it is an evidence gap,
        and the honest answer is the same one a ring gets: review, not verdict.
        """

        return any(
            isinstance(row.get("created_at"), str) and row["created_at"].strip()
            for row in self.ledger
        )

    @property
    def complete(self) -> bool:
        """True only when every stream came from the uncapped log.

        Deliberately strict. "The mission log is a 20-slot ring but nothing was
        evicted from it in this session" is probably true and is not something
        an artifact can prove, so this says ``False`` and the checks downgrade
        rather than guess.
        """

        return (
            self.event_source == EVIDENCE_STREAM
            and self.mission_source in (EVIDENCE_STREAM, EVIDENCE_ABSENT)
            and self.safety_source in (EVIDENCE_STREAM, EVIDENCE_ABSENT)
            and not self.gaps
        )

    def provenance(self) -> dict[str, Any]:
        return {
            "events": self.event_source,
            "ledger_timestamped": self.ledger_timestamped,
            "mission_log": self.mission_source,
            "safety_log": self.safety_source,
            "complete": self.complete,
            "gaps": list(self.gaps),
            "ledger_rows": len(self.ledger),
            "event_rows": len(self.events),
        }


def load_session(path: str | Path, *, name: str | None = None) -> SessionEvidence:
    """Read a session folder. Missing pieces are absences, never exceptions.

    A folder with nothing in it loads to an empty ``SessionEvidence`` whose
    ``gaps`` say so. That matters: the gate must be able to tell "this session
    is clean" from "this session has no evidence", and an exception here would
    collapse the two into one red.
    """

    folder = Path(path)
    evidence = SessionEvidence(name=name or folder.name, path=folder)
    if not folder.is_dir():
        evidence.gaps.append(f"{folder} is not a directory")
        return evidence

    evidence.ledger = _rows(_load_json(folder / LEDGER_NAME))
    state = _load_json(folder / STATE_NAME)
    evidence.state = state if isinstance(state, dict) else {}
    results = _load_json(folder / RESULTS_NAME)
    evidence.results = results if isinstance(results, dict) else {}

    # The uncapped stream wins wherever it exists. Reading it is what makes a
    # provenance finding a verdict instead of a maybe.
    stream_path = folder / EVENTS_JSONL_NAME
    if stream_path.is_file():
        from parcel_robot.realtime.evidence_log import (
            STREAM_EVENT,
            STREAM_MISSION,
            STREAM_SAFETY,
            read_event_log,
            verify_event_log,
        )

        rows = read_event_log(stream_path)
        problems = verify_event_log(rows)
        evidence.gaps.extend(problems)
        evidence.events = [r for r in rows if r.get("stream") == STREAM_EVENT]
        evidence.mission_log = [r for r in rows if r.get("stream") == STREAM_MISSION]
        evidence.safety_log = [r for r in rows if r.get("stream") == STREAM_SAFETY]
        evidence.event_source = EVIDENCE_STREAM
        evidence.mission_source = EVIDENCE_STREAM if evidence.mission_log else EVIDENCE_ABSENT
        evidence.safety_source = EVIDENCE_STREAM if evidence.safety_log else EVIDENCE_ABSENT

    slices = _load_json(folder / SLICES_NAME)
    if isinstance(slices, dict):
        if evidence.event_source == EVIDENCE_ABSENT and _rows(slices.get("events")):
            evidence.events = _rows(slices["events"])
            evidence.event_source = EVIDENCE_RING
            evidence.gaps.append(
                "events came from the 100-slot ring, not the session stream: "
                "an absent tool event may be an eviction rather than a defect"
            )
        if evidence.mission_source == EVIDENCE_ABSENT and _rows(slices.get("mission_log")):
            evidence.mission_log = _rows(slices["mission_log"])
            evidence.mission_source = EVIDENCE_RING

    # R21's safety ring reaches an artifact through the state snapshot, since
    # the corpus runner's slices predate it (R21 §10 names that as its own
    # highest-value follow-up). Read it wherever it is.
    if evidence.safety_source == EVIDENCE_ABSENT:
        rows = _rows(evidence.state.get("safety_log"))
        if not rows and isinstance(slices, dict):
            rows = _rows(slices.get("safety_log"))
        if rows:
            evidence.safety_log = rows
            evidence.safety_source = EVIDENCE_RING

    if not evidence.ledger and not evidence.events:
        evidence.gaps.append("no ledger and no events: there is nothing here to assert over")
    return evidence


def discover_sessions(root: str | Path) -> list[Path]:
    """Every session folder under ``root``, sorted. A folder counts when it has
    a ledger, a slices file or an EV-1 event log."""

    base = Path(root)
    if not base.is_dir():
        return []
    found: list[Path] = []
    for candidate in sorted(base.rglob("*")):
        if not candidate.is_dir():
            continue
        if any((candidate / name).is_file() for name in (LEDGER_NAME, SLICES_NAME, EVENTS_JSONL_NAME)):
            found.append(candidate)
    return found


__all__ = [
    "EVENTS_JSONL_NAME",
    "EVIDENCE_ABSENT",
    "EVIDENCE_RING",
    "EVIDENCE_STREAM",
    "LEDGER_NAME",
    "REPO_ROOT",
    "RESULTS_NAME",
    "SLICES_NAME",
    "STATE_NAME",
    "SessionEvidence",
    "discover_sessions",
    "load_session",
]
