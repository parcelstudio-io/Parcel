#!/usr/bin/env python
"""Recover the 2026-08-29 interrupted hosted Q wave without re-billing it.

The original process kept the provider transcript in an isolated research
SQLite store but, before per-scenario checkpointing existed, died before its
in-memory ``ScenarioResult`` list was published.  This one-purpose tool maps
the ordered, isolated sessions back to the frozen Q schedule.  When an absent
provider reply makes its virtual receipt time ambiguous, it enumerates every
order-preserving assignment and stores the most pessimistic scoring assignment
plus the complete per-metric range.  It never invents a reply or a latency.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

FOLDER = Path(__file__).resolve().parent
if str(FOLDER) not in sys.path:
    sys.path.insert(0, str(FOLDER))

import events as ev
import run
import scorer as sc


@dataclass
class _TemplateBackend:
    reply: int = 0

    def open_session(self, _scenario) -> None: ...

    def inject_item(self, **_kwargs) -> int:
        return 1

    def _next(self) -> run.RobotReply:
        self.reply += 1
        return run.RobotReply(f"__possible_reply_{self.reply}__")

    def owner_turn(self, _text: str) -> run.RobotReply:
        return self._next()

    def trigger_response(self) -> run.RobotReply:
        return self._next()

    def close(self) -> None: ...


def _segments(turns: list[sc.Turn]) -> tuple[list[sc.Turn], list[list[sc.Turn]]]:
    owners: list[sc.Turn] = []
    between: list[list[sc.Turn]] = []
    current: list[sc.Turn] = []
    for turn in turns:
        if turn.role == "owner":
            if owners:
                between.append(current)
            elif current:
                raise ValueError("template unexpectedly begins with a robot turn")
            owners.append(turn)
            current = []
        else:
            current.append(turn)
    between.append(current)
    return owners, between


def _memory_segments(rows: list[sqlite3.Row]) -> tuple[list[str], list[list[str]]]:
    owners: list[str] = []
    between: list[list[str]] = []
    current: list[str] = []
    for row in rows:
        if row["speaker"] == "owner":
            if owners:
                between.append(current)
            elif current:
                raise ValueError("memory session unexpectedly begins with robot speech")
            owners.append(str(row["content"]))
            current = []
        elif row["speaker"] == "robot":
            current.append(str(row["content"]))
        else:
            raise ValueError(f"unexpected memory speaker {row['speaker']!r}")
    between.append(current)
    return owners, between


def _clone(turn: sc.Turn, *, text: str | None = None) -> sc.Turn:
    return sc.Turn(
        scenario_id=turn.scenario_id,
        arm=turn.arm,
        sample=turn.sample,
        turn_index=turn.turn_index,
        role=turn.role,
        text=turn.text if text is None else text,
        at_s=turn.at_s,
        events_so_far=[dict(event) for event in turn.events_so_far],
        trigger_event_id=turn.trigger_event_id,
        ttft_ms=None,
        total_ms=None,
        deltas=[],
    )


def _alignments(
    template: list[sc.Turn], rows: list[sqlite3.Row]
) -> list[list[sc.Turn]]:
    owners, slots = _segments(template)
    actual_owners, actual = _memory_segments(rows)
    if [turn.text for turn in owners] != actual_owners:
        raise ValueError(
            "owner transcript does not match the frozen schedule: "
            f"expected {[turn.text for turn in owners]!r}, got {actual_owners!r}"
        )
    if len(slots) != len(actual):
        raise ValueError("memory/template owner segment count mismatch")
    choices: list[list[tuple[int, ...]]] = []
    for possible, observed in zip(slots, actual, strict=True):
        if len(observed) > len(possible):
            raise ValueError("memory contains more robot replies than the harness requested")
        choices.append(list(itertools.combinations(range(len(possible)), len(observed))))

    out: list[list[sc.Turn]] = []
    for assignment in itertools.product(*choices):
        aligned: list[sc.Turn] = []
        for owner, possible, observed, selected in zip(
            owners, slots, actual, assignment, strict=True
        ):
            aligned.append(_clone(owner))
            for position, text in zip(selected, observed, strict=True):
                aligned.append(_clone(possible[position], text=text))
        aligned.sort(key=lambda turn: turn.turn_index)
        for index, turn in enumerate(aligned):
            turn.turn_index = index
        out.append(aligned)
    return out


def _result_vector(result: sc.ScenarioResult) -> tuple[int, ...]:
    bars = result.bars
    # Pessimistic, deterministic recovery: minimize desirable hits and maximize
    # premature claims.  The unrounded counts are used, not a fitted metric.
    return (
        result.grounded[0],
        result.coverage[0],
        bars["b1_new_goal_acknowledged"][0],
        bars["b2_completion_announced"][0],
        bars["b3_resume_offer"][0],
        result.keys_bar[0],
        -bars["b4_premature_claims"][0],
    )


def _uncertainty(results: list[sc.ScenarioResult]) -> dict[str, object]:
    def span(pairs: list[tuple[int, int]]) -> dict[str, object]:
        totals = sorted({total for _hit, total in pairs})
        if len(totals) != 1:
            raise ValueError(f"alignment changed a metric denominator: {totals}")
        return {"hit_min": min(hit for hit, _ in pairs),
                "hit_max": max(hit for hit, _ in pairs), "n": totals[0]}

    return {
        "alignment_count": len(results),
        "grounded": span([result.grounded for result in results]),
        "coverage": span([result.coverage for result in results]),
        "b1_ack": span([result.bars["b1_new_goal_acknowledged"] for result in results]),
        "b2_completion": span(
            [result.bars["b2_completion_announced"] for result in results]
        ),
        "b3_resume_offer": span(
            [result.bars["b3_resume_offer"] for result in results]
        ),
        "b4_premature": span(
            [result.bars["b4_premature_claims"] for result in results]
        ),
        "b5_keys": span([result.keys_bar for result in results]),
    }


def _prefix_evidence(raw_lines: list[bytes], end: int) -> dict[str, object]:
    raw = b"".join(raw_lines[:end])
    rows = [json.loads(line) for line in raw.splitlines() if line]
    return {
        "path": str(run.WAVE_LEDGER),
        "bytes": len(raw),
        "rows": len(rows),
        "estimated_usd": round(
            sum(float(row.get("estimated_usd", 0.0)) for row in rows), 8
        ),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def recover(database: Path, output: Path, *, cap_usd: float) -> dict[str, object]:
    corpus = ev.build_corpus()
    arms = ("Q", "D")
    samples = 3
    seed = 20260829
    fingerprint, config = run._hosted_fingerprint(
        corpus, seed=seed, cap_usd=cap_usd, samples=samples, arms=arms
    )
    if output.exists():
        raise FileExistsError(f"refusing to overwrite recovery checkpoint {output}")

    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    sessions = [
        str(row[0])
        for row in connection.execute(
            "select session_id from messages group by session_id order by min(id)"
        )
    ]
    if not sessions or len(sessions) > len(corpus) * samples:
        raise ValueError(
            f"expected 1..{len(corpus) * samples} interrupted Q sessions, got "
            f"{len(sessions)}"
        )

    raw_lines = run.WAVE_LEDGER.read_bytes().splitlines(keepends=True)
    ledger_rows = [json.loads(line) for line in raw_lines if line.strip()]
    by_session: dict[str, list[int]] = {}
    for index, row in enumerate(ledger_rows):
        by_session.setdefault(str(row.get("session_id", "")), []).append(index)
    missing = sorted(set(sessions) - by_session.keys())
    if missing:
        raise ValueError(f"research sessions missing from spend ledger: {missing}")
    first_indices = [by_session[session][0] for session in sessions]
    if first_indices != sorted(first_indices):
        raise ValueError("memory sessions are not in ledger order")

    bands = run._bands_from_config(run._load_realtime_config())
    registry = sc.default_registry()
    completed: list[dict[str, object]] = []
    ambiguous = 0
    uncertainty_totals: dict[str, int] = {}
    for ordinal, session in enumerate(sessions):
        sample, corpus_index = divmod(ordinal, len(corpus))
        scenario = corpus[corpus_index]
        rows = list(
            connection.execute(
                "select id,session_id,speaker,content,created_at from messages "
                "where session_id=? order by id",
                (session,),
            )
        )
        template = run.run_scenario(
            scenario,
            _TemplateBackend(),
            arm="Q",
            sample=sample,
            bands=bands,
        )
        alignments = _alignments(template, rows)
        results = [
            sc.score_scenario(scenario, turns, registry, sample=sample)
            for turns in alignments
        ]
        chosen_index = min(range(len(results)), key=lambda index: _result_vector(results[index]))
        chosen = alignments[chosen_index]
        uncertainty = _uncertainty(results)
        ambiguous += int(len(alignments) > 1)
        uncertainty_totals[str(len(alignments))] = (
            uncertainty_totals.get(str(len(alignments)), 0) + 1
        )

        indices = by_session[session]
        if indices != list(range(indices[0], indices[-1] + 1)):
            raise ValueError(f"ledger rows for {session} are not contiguous")
        entry: dict[str, object] = {
            "key": run._completed_key("Q", sample, scenario.scenario_id),
            "arm": "Q",
            "sample": sample,
            "scenario_id": scenario.scenario_id,
            "session_id": session,
            "provenance": "recovered_conservative_from_isolated_memory",
            "turns": [run._turn_as_checkpoint(turn) for turn in chosen],
            "ledger_before": _prefix_evidence(raw_lines, indices[0]),
            "ledger_after": _prefix_evidence(raw_lines, indices[-1] + 1),
            "recorded_utc": str(rows[-1]["created_at"]) + "Z",
            "recovery": {
                "memory_row_ids": [int(row["id"]) for row in rows],
                "memory_rows_sha256": run._sha256(
                    [
                        {
                            "id": row["id"],
                            "session_id": row["session_id"],
                            "speaker": row["speaker"],
                            "content": row["content"],
                            "created_at": row["created_at"],
                        }
                        for row in rows
                    ]
                ),
                "selected_alignment": chosen_index,
                "selection_rule": "lexicographically_pessimistic_unrounded_counts",
                "latency": "UNMEASURED_NOT_RECOVERED",
                "uncertainty": uncertainty,
            },
        }
        entry["entry_sha256"] = run._entry_digest(entry)
        completed.append(entry)

    opening_index = by_session[sessions[0]][0]
    checkpoint: dict[str, object] = {
        "schema": run.HOSTED_CHECKPOINT_SCHEMA,
        "fingerprint": fingerprint,
        "config": config,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ledger_before": _prefix_evidence(raw_lines, opening_index),
        "completed": completed,
        "incomplete": [],
        "recovery": {
            "method": "ordered isolated session mapping + exhaustive reply-slot alignment",
            "database": str(database),
            "database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
            "memory_sessions": len(sessions),
            "ambiguous_sessions": ambiguous,
            "alignment_count_histogram": dict(sorted(uncertainty_totals.items())),
            "next_uncompleted_key": (
                run._completed_key(
                    "Q", len(sessions) // len(corpus),
                    corpus[len(sessions) % len(corpus)].scenario_id,
                )
                if len(sessions) < len(corpus) * samples
                else run._completed_key("D", 0, corpus[0].scenario_id)
            ),
            "no_reply_or_latency_fabricated": True,
        },
    }
    run._atomic_json(output, checkpoint)
    return checkpoint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database",
        type=Path,
        default=run.CACHE / "scratch/mb1_full_memory.sqlite3",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=FOLDER / "results/hosted-QD-full.checkpoint.json",
    )
    parser.add_argument("--cap-usd", type=float, default=4.5)
    args = parser.parse_args()
    checkpoint = recover(args.database, args.output, cap_usd=args.cap_usd)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "completed": len(checkpoint["completed"]),
                "recovery": checkpoint["recovery"],
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
