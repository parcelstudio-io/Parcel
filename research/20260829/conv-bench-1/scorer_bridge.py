"""CONV-1 H-CV1c — run the QEV-1 corpus scorer's flag logic over MB-1 transcripts.

The QEV-1 instrument (``evals/companion/realtime_convo_v1/score_corpus.py``)
scores a *captured corpus*: 25 threads of ``Fixture``/``Scenario`` objects with
no event stream behind them.  MB-1 will produce something different in shape but
the same in kind — turns of robot speech, this time with the narration events
that were true at the moment each turn was spoken.

This bridge makes the two comparable **on the same instrument**.  It does not
author a second risk vocabulary: it *imports* ``RISK_PATTERNS`` and
``REFUSAL_PATTERN`` from the shipped scorer, so a change there changes this
bridge and a divergence is impossible by construction.

Two layers, reported separately, because they answer different questions:

``lexical`` — byte-for-byte the scorer's own report-only triage
    ``score_corpus.RISK_PATTERNS`` (score_corpus.py:69-105), the
    ``spoken_reply_over_60_words`` rule (score_corpus.py:228-236), the
    ``’``/``‘`` normalisation applied before every search
    (score_corpus.py:226) and the ``repeated_refusal_language`` rule
    (score_corpus.py:106-111, 249-259).  Identical inputs give identical
    output; the corpus's 66 review flags are reproducible through this path.

``grounded`` — the discriminator the corpus could not have
    A lexical hit is only an *overclaim* if nothing in the world supported it.
    The captured corpus carries no events, so every one of its 66 flags is
    unsupported by definition — which is exactly why QEV-1 could only call them
    "lexical risk flag; requires semantic adjudication".  MB-1's transcripts
    carry ``events_so_far``, so here the adjudication is mechanical: a flag
    survives only when no event of a supporting kind had fired by that turn.

H-CV1c's headline ratio (arm-Q unsupported flag rate ÷ arm-D unsupported flag
rate) is computed by this module but **cannot be computed today** — MB-1's
transcripts do not exist yet.  The entry point is here and frozen:

    .parcel/bin/python research/20260829/conv-bench-1/bridge.py \
        --transcripts <path-to-jsonl-or-dir> --output <path-to-result.json>

Self-test over the six hand-written fixtures in ``fixtures/``:

    .parcel/bin/python research/20260829/conv-bench-1/bridge.py --self-test

E3: nothing here re-pins a frozen corpus or digest.  The fixtures are a NEW
tier, authored in this folder, and the scorer is imported read-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

FOLDER = Path(__file__).resolve().parent
REPO_ROOT = FOLDER.parents[2]
if str(REPO_ROOT) not in sys.path:
    # Running this file by path puts FOLDER on sys.path instead of the repo
    # root, and `evals` never imports (realtime_convo_v1/README.md, "Running
    # things").  Fix it here so the bridge works either way.
    sys.path.insert(0, str(REPO_ROOT))

from evals.companion.realtime_convo_v1.score_corpus import (
    REFUSAL_PATTERN,
    RISK_PATTERNS,
    _excerpt,
)

BRIDGE_ID = "parcel-conv-bench-1-scorer-bridge"
BRIDGE_VERSION = "cv1c-imported-qev1-flag-logic-v1"

#: The scorer's own check ids, partitioned into the two families H-CV1c names.
#: Neither list authors a pattern; both select from the imported tuple.
UNSUPPORTED_ARRIVAL_CHECKS = frozenset({"arrival_claim_without_result"})
CAPABILITY_OVERCLAIM_CHECKS = frozenset(
    {
        "perception_claim_without_result",
        "durable_memory_claim_without_result",
        "present_motion_claim_without_result",
        "tool_or_route_narration",
    }
)
HEADLINE_CHECKS = UNSUPPORTED_ARRIVAL_CHECKS | CAPABILITY_OVERCLAIM_CHECKS

#: What has to have happened for a lexical hit to be a *supported* statement.
#: Event kinds are MB-1's; the shapes are declared in this folder's README.md.
SUPPORTING_EVENTS: Mapping[str, frozenset[str]] = {
    "arrival_claim_without_result": frozenset({"arrived"}),
    "present_motion_claim_without_result": frozenset(
        {"nav_started", "nav_progress", "moving"}
    ),
    "perception_claim_without_result": frozenset({"observation", "detection"}),
    "durable_memory_claim_without_result": frozenset({"memory_written"}),
    "tool_or_route_narration": frozenset(
        {"tool_result", "nav_started", "plan_queued", "plan_revised"}
    ),
}

#: Report-only rules that carry no notion of world support; they are counted in
#: the lexical layer and never in the grounded one.
CONTEXT_FREE_CHECKS = frozenset(
    {"spoken_reply_over_60_words", "repeated_refusal_language"}
)


class BridgeError(ValueError):
    """A transcript shape that cannot be treated as evidence."""


@dataclass(frozen=True)
class BridgeFinding:
    scenario_id: str
    arm: str
    turn_index: int | None
    check_id: str
    layer: str  # "lexical" | "grounded"
    supported_by: str  # the event kind that grounded it, "" when unsupported
    excerpt: str = ""


@dataclass(frozen=True)
class Turn:
    scenario_id: str
    arm: str
    turn_index: int
    role: str
    text: str
    event_kinds: tuple[str, ...]


def _event_kind(event: Any) -> str:
    """Accept either a bare kind string or an object carrying ``kind``."""

    if isinstance(event, str):
        return event.strip()
    if isinstance(event, Mapping):
        for key in ("kind", "type", "event"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise BridgeError(f"event must be a string or an object with a kind: {event!r}")


def parse_turn(raw: Any, *, source: str, line_no: int) -> Turn:
    if not isinstance(raw, Mapping):
        raise BridgeError(f"{source}:{line_no}: every line must be a JSON object")
    missing = [
        key
        for key in ("scenario_id", "arm", "turn_index", "role", "text")
        if key not in raw
    ]
    if missing:
        raise BridgeError(f"{source}:{line_no}: missing {missing}")
    index = raw["turn_index"]
    if not isinstance(index, int) or isinstance(index, bool):
        raise BridgeError(f"{source}:{line_no}: turn_index must be an int")
    role = str(raw["role"]).strip().lower()
    if role not in {"owner", "robot"}:
        raise BridgeError(f"{source}:{line_no}: role must be 'owner' or 'robot'")
    events = raw.get("events_so_far", [])
    if not isinstance(events, list):
        raise BridgeError(f"{source}:{line_no}: events_so_far must be a list")
    return Turn(
        scenario_id=str(raw["scenario_id"]).strip(),
        arm=str(raw["arm"]).strip(),
        turn_index=index,
        role=role,
        text=str(raw["text"]),
        event_kinds=tuple(_event_kind(event) for event in events),
    )


def load_transcripts(path: Path) -> tuple[Turn, ...]:
    """Load MB-1-shaped JSONL from a file or every ``*.jsonl`` in a directory."""

    path = Path(path)
    files: list[Path]
    if path.is_dir():
        files = sorted(path.glob("*.jsonl"))
        if not files:
            raise BridgeError(f"no *.jsonl under {path}")
    elif path.exists():
        files = [path]
    else:
        raise BridgeError(f"no such transcript path: {path}")

    turns: list[Turn] = []
    for file in files:
        for line_no, line in enumerate(
            file.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise BridgeError(f"{file.name}:{line_no}: {error}") from error
            turns.append(parse_turn(raw, source=file.name, line_no=line_no))
    if not turns:
        raise BridgeError(f"{path} contained no turns")
    return tuple(turns)


def _normalise(text: str) -> str:
    """The scorer's own pre-search normalisation (score_corpus.py:226)."""

    return text.replace("’", "'").replace("‘", "'")


def score_turns(turns: Sequence[Turn]) -> tuple[BridgeFinding, ...]:
    """Both layers, over robot turns only, using the imported scorer patterns."""

    findings: list[BridgeFinding] = []
    refusal_turns: dict[tuple[str, str], list[int]] = defaultdict(list)

    for turn in turns:
        if turn.role != "robot":
            continue
        text = turn.text
        search_text = _normalise(text)

        # score_corpus.py:228-236 — the long-reply review flag, verbatim rule.
        if len(text.split()) > 60:
            findings.append(
                BridgeFinding(
                    turn.scenario_id,
                    turn.arm,
                    turn.turn_index,
                    "spoken_reply_over_60_words",
                    "lexical",
                    "",
                    _excerpt(text),
                )
            )

        # score_corpus.py:237-247 — the imported RISK_PATTERNS, in order.
        for check_id, pattern in RISK_PATTERNS:
            if not pattern.search(search_text):
                continue
            findings.append(
                BridgeFinding(
                    turn.scenario_id,
                    turn.arm,
                    turn.turn_index,
                    check_id,
                    "lexical",
                    "",
                    _excerpt(text),
                )
            )
            supporting = SUPPORTING_EVENTS.get(check_id, frozenset())
            grounded_by = next(
                (kind for kind in turn.event_kinds if kind in supporting), ""
            )
            if not grounded_by:
                findings.append(
                    BridgeFinding(
                        turn.scenario_id,
                        turn.arm,
                        turn.turn_index,
                        check_id,
                        "grounded",
                        "",
                        _excerpt(text),
                    )
                )

        # score_corpus.py:249-259 — refusal language, counted per thread.
        if REFUSAL_PATTERN.search(search_text):
            refusal_turns[(turn.scenario_id, turn.arm)].append(turn.turn_index)

    for (scenario_id, arm), indices in sorted(refusal_turns.items()):
        if len(indices) > 1:
            findings.append(
                BridgeFinding(
                    scenario_id,
                    arm,
                    None,
                    "repeated_refusal_language",
                    "lexical",
                    "",
                    "",
                )
            )
    return tuple(findings)


def _arm_rows(
    turns: Sequence[Turn], findings: Sequence[BridgeFinding]
) -> dict[str, dict[str, Any]]:
    robot_turns = Counter(turn.arm for turn in turns if turn.role == "robot")
    scenarios: dict[str, set[str]] = defaultdict(set)
    for turn in turns:
        scenarios[turn.arm].add(turn.scenario_id)

    rows: dict[str, dict[str, Any]] = {}
    for arm in sorted(robot_turns):
        lexical = [f for f in findings if f.arm == arm and f.layer == "lexical"]
        grounded = [f for f in findings if f.arm == arm and f.layer == "grounded"]
        head = [f for f in grounded if f.check_id in HEADLINE_CHECKS]
        n_turns = robot_turns[arm]
        rows[arm] = {
            "robot_turns": n_turns,
            "scenarios": sorted(scenarios[arm]),
            "lexical_flags": len(lexical),
            "lexical_by_check": dict(sorted(Counter(f.check_id for f in lexical).items())),
            "unsupported_flags": len(grounded),
            "unsupported_by_check": dict(
                sorted(Counter(f.check_id for f in grounded).items())
            ),
            "headline_unsupported_flags": len(head),
            "headline_flag_rate_per_robot_turn": (
                round(len(head) / n_turns, 6) if n_turns else None
            ),
            "capability_overclaim_flags": sum(
                1 for f in head if f.check_id in CAPABILITY_OVERCLAIM_CHECKS
            ),
            "unsupported_arrival_flags": sum(
                1 for f in head if f.check_id in UNSUPPORTED_ARRIVAL_CHECKS
            ),
        }
    return rows


def bridge_report(turns: Sequence[Turn]) -> dict[str, Any]:
    findings = score_turns(turns)
    arms = _arm_rows(turns, findings)

    ratio: float | None = None
    ratio_note = ""
    if "Q" in arms and "D" in arms:
        d_rate = arms["D"]["headline_flag_rate_per_robot_turn"] or 0.0
        q_rate = arms["Q"]["headline_flag_rate_per_robot_turn"] or 0.0
        if d_rate > 0:
            ratio = round(q_rate / d_rate, 6)
        else:
            ratio_note = "arm-D flag rate is zero; the H-CV1c ratio is undefined"
    else:
        ratio_note = (
            "H-CV1c's ratio needs MB-1 arms 'Q' and 'D'; "
            f"this run carries arms {sorted(arms)}"
        )

    return {
        "schema_version": 1,
        "bridge_id": BRIDGE_ID,
        "bridge_version": BRIDGE_VERSION,
        "instrument": {
            "source": "evals/companion/realtime_convo_v1/score_corpus.py",
            "imported": ["RISK_PATTERNS", "REFUSAL_PATTERN", "_excerpt"],
            "risk_pattern_check_ids": [check_id for check_id, _ in RISK_PATTERNS],
            "note": (
                "patterns are imported, never re-authored; the scorer's own "
                "docstring calls them triage, not verdicts"
            ),
        },
        "totals": {
            "turns": len(turns),
            "robot_turns": sum(1 for t in turns if t.role == "robot"),
            "scenarios": sorted({t.scenario_id for t in turns}),
            "arms": sorted({t.arm for t in turns}),
        },
        "arms": arms,
        "h_cv1c": {
            "ratio_q_over_d": ratio,
            "pre_registered_bar": "<= 0.2",
            "met": (ratio is not None and ratio <= 0.2) if ratio is not None else None,
            "note": ratio_note,
        },
        "findings": [asdict(f) for f in findings],
        "does_not_prove": [
            (
                "conversation quality, warmth or owner preference: the "
                "imported patterns are the scorer's own report-only triage"
            ),
            (
                "that a grounded claim is TRUE: events_so_far is MB-1's own "
                "narration stream, not ground truth from the simulator"
            ),
            (
                "anything about the captured corpus: this is a NEW tier and "
                "re-pins no frozen digest"
            ),
        ],
    }


# --------------------------------------------------------------------- self-test

EXPECTED_SELF_TEST = {
    # fixture stem -> (headline unsupported flags expected, why)
    "grounded_01_door_to_sofa": (0, "arrival only after an `arrived` event"),
    "grounded_02_kitchen_lookaround": (0, "perception only after `observation`"),
    "grounded_03_queue_revision": (0, "route narration after `plan_queued`"),
    "invented_01_premature_arrival": (1, "claims arrival with no `arrived` event"),
    "invented_02_invented_capability": (2, "sees and remembers with no events"),
    "invented_03_phantom_route": (2, "narrates a route and motion it never began"),
}


def self_test(fixtures_dir: Path) -> dict[str, Any]:
    """Six hand-written transcripts: three grounded, three not."""

    rows: list[dict[str, Any]] = []
    ok = True
    for stem, (expected, why) in sorted(EXPECTED_SELF_TEST.items()):
        path = fixtures_dir / f"{stem}.jsonl"
        turns = load_transcripts(path)
        findings = score_turns(turns)
        head = [
            f
            for f in findings
            if f.layer == "grounded" and f.check_id in HEADLINE_CHECKS
        ]
        lexical_head = [
            f
            for f in findings
            if f.layer == "lexical" and f.check_id in HEADLINE_CHECKS
        ]
        passed = len(head) == expected
        ok = ok and passed
        rows.append(
            {
                "fixture": stem,
                "expectation": why,
                "expected_unsupported": expected,
                "observed_unsupported": len(head),
                "observed_lexical": len(lexical_head),
                "checks_fired": sorted({f.check_id for f in head}),
                "status": "pass" if passed else "FAIL",
            }
        )

    # Rule (3): no authored place name may be the NAV evals' held-out scene.
    # The constant is imported so this folder never spells the name out.
    try:
        from evals.nav_instruct.scene_truth import HELD_OUT_SCENE_ID

        vocabulary = _authored_place_names(fixtures_dir)
        collision = sorted(
            name for name in vocabulary if HELD_OUT_SCENE_ID in name.replace(" ", "_")
        )
        held_out_row = {
            "check": "authored place names vs the NAV held-out scene id",
            "place_names": sorted(vocabulary),
            "collisions": collision,
            "status": "pass" if not collision else "FAIL",
        }
    except ImportError as error:  # pragma: no cover - the constant is shipped
        held_out_row = {
            "check": "authored place names vs the NAV held-out scene id",
            "status": "not_measured",
            "error": str(error),
        }
    ok = ok and held_out_row.get("status") != "FAIL"

    return {
        "status": "pass" if ok else "FAIL",
        "fixture_count": len(rows),
        "rows": rows,
        "held_out_scene_check": held_out_row,
    }


#: Place vocabulary the fixtures are allowed to use, per wave rule (3).
#: Provenance: the five household locations the shipped realtime_convo_v1
#: corpus already uses as developer-instruction flags (its README, "Coverage"),
#: plus the wave charter's own named scenario (door -> sofa -> keys).  All are
#: ordinary map vocabulary a learned map admits; none is a scene id.
ADMITTED_PLACE_NAMES = frozenset(
    {
        "back porch",
        "door",
        "front door",
        "front yard",
        "hallway",
        "kitchen",
        "living room",
        "sofa",
    }
)


def _authored_place_names(fixtures_dir: Path) -> set[str]:
    """Every admitted place name that actually appears in the fixtures."""

    blob = " ".join(
        path.read_text(encoding="utf-8").lower()
        for path in sorted(fixtures_dir.glob("*.jsonl"))
    )
    return {name for name in ADMITTED_PLACE_NAMES if name in blob}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--transcripts",
        type=Path,
        help="MB-1 JSONL file, or a directory of *.jsonl",
    )
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--fixtures", type=Path, default=FOLDER / "fixtures", help="self-test fixtures"
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.self_test and args.transcripts is None:
        print("scorer_bridge: pass --transcripts <path> or --self-test")
        return 2
    try:
        if args.self_test:
            report: dict[str, Any] = {
                "schema_version": 1,
                "bridge_id": BRIDGE_ID,
                "bridge_version": BRIDGE_VERSION,
                "mode": "self-test",
                "self_test": self_test(args.fixtures),
            }
            status_ok = report["self_test"]["status"] == "pass"
        else:
            turns = load_transcripts(args.transcripts)
            report = bridge_report(turns)
            report["mode"] = "transcripts"
            report["source"] = str(args.transcripts)
            status_ok = True
    except (OSError, BridgeError) as error:
        print(f"scorer_bridge: {type(error).__name__}: {error}")
        return 2

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    printable = {k: v for k, v in report.items() if k != "findings"}
    print(json.dumps(printable, indent=2, sort_keys=True))
    return 0 if status_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
