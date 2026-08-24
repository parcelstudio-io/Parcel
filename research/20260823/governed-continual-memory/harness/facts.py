"""Scheduled distillation over the synthetic histories: M2, M3, M4, M8.

One arm = one proposer x one revocation policy, run over all three histories,
three sessions each, with an idle pass at the end of every history.

WHAT AN ARM DOES, IN ORDER
--------------------------
1. Fresh sqlite under ``PARCEL_MEMORY_PATH`` (never the owner's store; the
   process also never sets ``PARCEL_MEMORY_PURPOSE``, so ``memory.path``
   resolves ``purpose=test`` and would refuse the owner's file if it were named).
2. For each session: write its turns, then ``scheduler.on_session_close`` —
   which is the whole point of the experiment, since nothing in the tree calls
   ``distil_session`` today.
3. Apply that session's revocations through ``forget_owner_fact`` (the same door
   ``remember_fact``'s ``forget`` action reaches).
4. After the last session, one ``on_idle`` pass over the FULL turn window. This
   is the pass that can resurrect a revoked fact, because it re-reads the
   sentence the owner revoked rather than only the newest session.
5. Score: every candidate the pipeline proposed against the authored graph, and
   every surviving row against it too.

WHY BOTH A PROPOSAL-LEVEL AND A ROW-LEVEL SCORE
------------------------------------------------
``owner_facts`` upserts by key and the deterministic proposer's key vocabulary
is small (``preference``, ``routine``, ``home``, ``work``, ``<subject>_name``,
...), so three preferences stated over three sessions leave ONE row. Scoring
only rows would report that as two missed facts when the pipeline proposed all
three; scoring only proposals would hide that the profile the model actually
reads holds one. Both are measured and both are reported.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from parcel_robot.memory.conversation import ConversationMemory
from parcel_robot.memory.episodes import EpisodeLog
from parcel_robot.memory.scheduler import (
    ContinualMemoryConfig,
    ContinualMemoryScheduler,
    revoked_fact_keys,
)
from parcel_robot.owner_model.notes import owner_notes_from_facts
from parcel_robot.owner_model.policy import CONSENT_GRANTED

from .histories import HISTORIES, GroundFact, OwnerHistory

#: The overlay that switches ``memory.continual`` on for this experiment. The
#: flag defaults OFF in code and ``configs/robot.yaml`` is untouched.
OVERLAY = Path(__file__).resolve().parent.parent / "memory_continual_on.yaml"


def overlay_config() -> ContinualMemoryConfig:
    """Read the overlay through the product's own settings reader.

    Going through ``from_settings`` rather than constructing the dataclass by
    hand is the point: it exercises the config path, including its refusal of an
    unknown key, so "the flag is readable from configuration" is measured rather
    than asserted.
    """

    return ContinualMemoryConfig.from_settings(
        yaml.safe_load(OVERLAY.read_text(encoding="utf-8"))
    )


@dataclass
class ArmResult:
    """Everything one (proposer, revocation-policy) arm measured."""

    arm: str
    proposer: str
    respect_revocations: bool
    proposals: list[dict[str, Any]] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    passes: list[dict[str, Any]] = field(default_factory=list)
    revocation_leaks: list[dict[str, Any]] = field(default_factory=list)
    episodes: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # -- M2 / M3 -------------------------------------------------------------

    def _matched(self, rows: Sequence[dict[str, Any]]) -> tuple[int, int, set[str]]:
        hits = 0
        misses = 0
        covered: set[str] = set()
        for row in rows:
            if row["matched_fact_id"]:
                hits += 1
                covered.add(row["matched_fact_id"])
            else:
                misses += 1
        return hits, misses, covered

    def scores(self) -> dict[str, Any]:
        all_facts = [f for h in HISTORIES for f in h.facts]
        proposable = [f for f in all_facts if f.disposition != "refuse"]
        unique = list(
            {
                (row["history"], row["key"], row["value"]): row for row in self.proposals
            }.values()
        )
        p_hits, p_misses, p_covered = self._matched(unique)
        r_hits, r_misses, r_covered = self._matched(self.rows)
        granted = [r for r in self.rows if r["consent"] == CONSENT_GRANTED]
        g_hits, g_misses, _ = self._matched(granted)
        return {
            "proposal_precision": _ratio(p_hits, p_hits + p_misses),
            "proposal_recall": _ratio(len(p_covered), len(proposable)),
            "proposals_total": len(self.proposals),
            "proposals_unique": len(unique),
            "proposals_unmatched": p_misses,
            "row_precision": _ratio(r_hits, r_hits + r_misses),
            "row_recall": _ratio(len(r_covered), len(proposable)),
            "rows_total": len(self.rows),
            "rows_unmatched": r_misses,
            "granted_rows": len(granted),
            "granted_absent_from_graph": g_misses,
            "granted_matched": g_hits,
            "ground_truth_facts": len(all_facts),
            "ground_truth_proposable": len(proposable),
            "uncovered_fact_ids": sorted(
                f.fact_id for f in proposable if f.fact_id not in p_covered
            ),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "proposer": self.proposer,
            "respect_revocations": self.respect_revocations,
            "scores": self.scores(),
            "revocation_leaks": self.revocation_leaks,
            "passes": self.passes,
            "episodes": self.episodes,
            "proposals": self.proposals,
            "rows": self.rows,
            "errors": self.errors,
        }


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _match(value: str, facts: Sequence[GroundFact]) -> str:
    for fact in facts:
        if fact.matches(value):
            return fact.fact_id
    return ""


def run_arm(
    *,
    arm: str,
    store_dir: Path,
    proposer: Any,
    proposer_id: str,
    respect_revocations: bool,
    histories: Sequence[OwnerHistory] = HISTORIES,
) -> ArmResult:
    """One arm, all histories. Returns the measured rows."""

    result = ArmResult(arm=arm, proposer=proposer_id, respect_revocations=respect_revocations)
    store_dir.mkdir(parents=True, exist_ok=True)
    for history in histories:
        _run_history(result, history, store_dir, proposer, respect_revocations)
    return result


def _run_history(
    result: ArmResult,
    history: OwnerHistory,
    store_dir: Path,
    proposer: Any,
    respect_revocations: bool,
) -> None:
    store_path = store_dir / f"{result.arm}_{history.history_id}.sqlite3"
    if store_path.exists():
        store_path.unlink()
    memory = ConversationMemory(store_path)
    # The episode log is append-only and ``episode_id`` is UNIQUE, so a re-run of
    # the same arm on a surviving file is refused by the store — correctly. A
    # harness re-run is a NEW day, not a retry of the old one, so the file goes.
    episode_path = store_dir / f"{result.arm}_{history.history_id}_episodes.sqlite3"
    if episode_path.exists():
        episode_path.unlink()
    episodes = EpisodeLog(episode_path)
    scheduler = ContinualMemoryScheduler(
        memory=memory,
        config=dataclasses.replace(
            overlay_config(), respect_revocations=respect_revocations
        ),
        proposer=proposer,
        episodes=episodes,
    )
    revocations = {session: (fact_id, noun) for fact_id, session, noun in history.revocations}
    by_id = {fact.fact_id: fact for fact in history.facts}

    for session_id in history.sessions:
        for turn in history.turns_for(session_id):
            memory.add(turn.speaker, turn.text)
            scheduler.note_turn()
        started = time.perf_counter()
        run = scheduler.on_session_close(session_id, outcome="closed")
        elapsed = time.perf_counter() - started
        _record_pass(result, history, run, elapsed, session_id)
        if session_id in revocations:
            fact_id, noun = revocations[session_id]
            # What the owner SAYS first: "forget the medication thing". The
            # distiller minted ``blood_pressure_medication`` from the broad
            # pattern, so a forget on the owner's own noun hits nothing — that
            # gap is measured rather than routed around.
            by_noun = memory.forget_owner_fact(noun)
            fact = by_id[fact_id]
            resolved = [
                str(row["key"])
                for row in memory.owner_facts()
                if fact.matches(str(row["value"]))
            ]
            by_value = sum(memory.forget_owner_fact(key) for key in resolved)
            result.passes.append(
                {
                    "history": history.history_id,
                    "session": session_id,
                    "trigger": "revocation",
                    "fact_id": fact_id,
                    "owner_noun": noun,
                    "rows_forgotten_by_noun": by_noun,
                    "resolved_keys": resolved,
                    "rows_forgotten_by_value": by_value,
                }
            )

    # The idle pass: the whole history back in one window.
    scheduler.note_turn(10)
    started = time.perf_counter()
    idle = scheduler.on_idle(now=1e9)
    elapsed = time.perf_counter() - started
    _record_pass(result, history, idle, elapsed, "idle")

    _score_store(result, history, memory, scheduler)
    for episode in episodes.recent(limit=20):
        payload = episode.as_dict()
        payload["history"] = history.history_id
        result.episodes.append(payload)
    episodes.close()
    memory.connection.close()


def _record_pass(
    result: ArmResult,
    history: OwnerHistory,
    run: Any,
    elapsed: float,
    session_id: str,
) -> None:
    if run.report is not None:
        for row in run.report.kept + run.report.asked:
            result.proposals.append(
                {
                    "history": history.history_id,
                    "session": session_id,
                    "key": row.candidate.key,
                    "value": row.candidate.value,
                    "confidence": row.candidate.confidence,
                    "category": row.decision.category,
                    "disposition": row.decision.disposition,
                    "consent": row.decision.consent,
                    "matched_fact_id": _match(row.candidate.value, history.facts),
                }
            )
        for row in run.report.refused:
            result.proposals.append(
                {
                    "history": history.history_id,
                    "session": session_id,
                    "key": row.candidate.key,
                    "value": row.candidate.value,
                    "confidence": row.candidate.confidence,
                    "category": row.decision.category,
                    "disposition": row.decision.disposition,
                    "consent": row.decision.consent,
                    "matched_fact_id": _match(row.candidate.value, history.facts),
                }
            )
    result.passes.append(
        {
            "history": history.history_id,
            "session": session_id,
            "trigger": run.trigger,
            "ran": run.ran,
            "written": run.written,
            "wall_s": round(elapsed, 4),
            "turns_read": run.report.turns_read if run.report is not None else 0,
            "proposed": run.report.proposed if run.report is not None else 0,
            "detail": run.detail,
        }
    )
    if run.detail:
        result.errors.append(f"{history.history_id}/{session_id}: {run.detail}")


def _score_store(
    result: ArmResult,
    history: OwnerHistory,
    memory: ConversationMemory,
    scheduler: ContinualMemoryScheduler,
) -> None:
    """Rows that survive, and whether a revoked fact came back."""

    del scheduler
    granted_rows = memory.owner_facts(consent=CONSENT_GRANTED)
    notes = owner_notes_from_facts(granted_rows, limit=32)
    revoked_keys = revoked_fact_keys(memory)
    for row in memory.owner_facts():
        result.rows.append(
            {
                "history": history.history_id,
                "key": str(row["key"]),
                "value": str(row["value"]),
                "consent": str(row["consent"]),
                "category": str(row["category"] or ""),
                "provenance": str(row["provenance"]),
                "matched_fact_id": _match(str(row["value"]), history.facts),
            }
        )
    for fact in history.facts:
        if not fact.revoked:
            continue
        in_rows = any(fact.matches(str(r["value"])) for r in memory.owner_facts())
        in_granted = any(fact.matches(str(r["value"])) for r in granted_rows)
        in_notes = any(fact.matches(note) for note in notes)
        if in_rows or in_granted or in_notes:
            result.revocation_leaks.append(
                {
                    "history": history.history_id,
                    "fact_id": fact.fact_id,
                    "in_any_live_row": in_rows,
                    "in_granted_rows": in_granted,
                    "in_developer_instruction": in_notes,
                    "tombstoned_keys": sorted(revoked_keys),
                }
            )


__all__ = ["OVERLAY", "ArmResult", "overlay_config", "run_arm"]
