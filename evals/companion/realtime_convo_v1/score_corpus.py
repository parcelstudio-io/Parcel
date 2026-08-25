"""Executable quality layer for the captured realtime conversation corpus.

The existing corpus replay proves transport, provenance, usage accounting and
tool-refusal behavior.  It intentionally does not score the words the model
said.  This module closes the *executable review* gap without pretending that
regular expressions are a human preference model:

* schema, scenario/fixture parity, non-empty output and tool declarations are
  hard machine contracts;
* likely capability/action overclaims and long replies are auditable risk
  flags, never silently promoted to semantic truth;
* the shipped deterministic punt rater is run over every thread; and
* an optional reviewer artifact must cover every authored expectation exactly.

One unblinded reviewer is useful evidence, but is report-only.  It does not
freeze the corpus, calibrate an AutoRater, or establish owner preference.

Usage::

    python -m evals.companion.realtime_convo_v1.score_corpus \
      --review path/to/review.json --output path/to/result.json

Exit status is 0 when hard machine contracts pass and reviewer coverage (when
required) is complete, 1 for a hard machine failure, and 2 for incomplete
required review evidence.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from evals.autorater import Response, RulePuntRater
from evals.autorater import Turn as RaterTurn

from .schema import DECLARED_TOOLS, Fixture, Scenario, load_fixtures, load_scenarios

SUITE_ID = "parcel-realtime-convo-quality-v1"
RUNNER_VERSION = "machine-contract-plus-reviewed-expectations-v1"
REVIEW_SCHEMA_VERSION = 1
REVIEW_VERDICTS = frozenset({"pass", "mixed", "fail", "unscorable"})
EXPECTATION_VERDICTS = frozenset({"pass", "fail", "unscorable"})


class QualityError(ValueError):
    """A review or corpus shape that cannot be treated as evidence."""


@dataclass(frozen=True)
class Finding:
    thread_id: str
    turn_index: int | None
    check_id: str
    severity: Literal["hard", "review"]
    detail: str
    excerpt: str = ""


# These patterns are *triage*, not verdicts.  They deliberately find phrases a
# reviewer should inspect when no tool-result or physical mission event exists
# in the captured transcript.  False positives remain report-only findings.
RISK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "arrival_claim_without_result",
        re.compile(
            r"\b(?:we(?:'re| are) (?:here|there|at (?:the )?(?:door|destination))|"
            r"i(?:'ve| have) (?:arrived|reached)|(?:we|i) (?:made it|arrived))\b",
            re.IGNORECASE,
        ),
    ),
    (
        "perception_claim_without_result",
        re.compile(r"\b(?:i can see|i see|i can (?:clearly )?(?:read|tell))\b", re.IGNORECASE),
    ),
    (
        "durable_memory_claim_without_result",
        re.compile(
            r"\b(?:i(?:'ll| will) remember|saved (?:that|it)|updated (?:my )?memory)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "tool_or_route_narration",
        re.compile(
            r"\b(?:check my status|set (?:the|a) route|route (?:request|calculation)|"
            r"what (?:the )?robot reports|tool call|session)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "present_motion_claim_without_result",
        re.compile(
            r"\b(?:i(?:'m| am)|we(?:'re| are)) (?:already )?"
            r"(?:walking|moving|heading|crossing|waiting at)\b",
            re.IGNORECASE,
        ),
    ),
)
REFUSAL_PATTERN = re.compile(
    r"\b(?:i (?:can't|cannot)|i(?:'m| am) (?:not able|unable)|"
    r"i (?:don't|do not) have (?:the )?(?:ability|capability|hardware))\b",
    re.IGNORECASE,
)


def _excerpt(text: str, *, limit: int = 180) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _fixture_map(fixtures: Sequence[Fixture]) -> dict[str, Fixture]:
    mapped = {fixture.thread_id: fixture for fixture in fixtures}
    if len(mapped) != len(fixtures):
        raise QualityError("duplicate fixture thread_id")
    return mapped


def _scenario_map(scenarios: Sequence[Scenario]) -> dict[str, Scenario]:
    mapped = {scenario.thread_id: scenario for scenario in scenarios}
    if len(mapped) != len(scenarios):
        raise QualityError("duplicate scenario thread_id")
    return mapped


def machine_findings(
    scenarios: Sequence[Scenario], fixtures: Sequence[Fixture]
) -> tuple[Finding, ...]:
    """Run hard corpus contracts and report-only conversational triage."""

    findings: list[Finding] = []
    scenario_by_id = _scenario_map(scenarios)
    fixture_by_id = _fixture_map(fixtures)
    missing = sorted(set(scenario_by_id) - set(fixture_by_id))
    extra = sorted(set(fixture_by_id) - set(scenario_by_id))
    for thread_id in missing:
        findings.append(Finding(thread_id, None, "missing_fixture", "hard", "no fixture"))
    for thread_id in extra:
        findings.append(Finding(thread_id, None, "orphan_fixture", "hard", "no scenario"))

    for thread_id in sorted(set(scenario_by_id) & set(fixture_by_id)):
        scenario = scenario_by_id[thread_id]
        fixture = fixture_by_id[thread_id]
        parity = {
            "title": (scenario.title, fixture.title),
            "family": (scenario.family, fixture.family),
            "probes": (scenario.probes, fixture.probes),
            "si_profile": (scenario.si_profile, fixture.si_profile),
            "owner_turns": (scenario.owner_turns, tuple(turn.owner_text for turn in fixture.turns)),
        }
        for field, (expected, observed) in parity.items():
            if expected != observed:
                findings.append(
                    Finding(
                        thread_id,
                        None,
                        f"scenario_fixture_{field}_mismatch",
                        "hard",
                        f"scenario {field} does not match captured fixture",
                    )
                )
        declared = set(fixture.declared_tools)
        if tuple(fixture.declared_tools) != DECLARED_TOOLS:
            findings.append(
                Finding(
                    thread_id,
                    None,
                    "declared_tool_plane_drift",
                    "hard",
                    f"expected {list(DECLARED_TOOLS)!r}; observed {list(fixture.declared_tools)!r}",
                )
            )
        for turn in fixture.turns:
            if not turn.robot_text.strip() and not turn.tool_calls:
                findings.append(
                    Finding(
                        thread_id,
                        turn.index,
                        "empty_robot_turn",
                        "hard",
                        "turn has neither robot text nor a tool proposal",
                    )
                )
            for call in turn.tool_calls:
                if call.name not in declared:
                    findings.append(
                        Finding(
                            thread_id,
                            turn.index,
                            "undeclared_tool",
                            "hard",
                            f"model proposed undeclared tool {call.name!r}",
                        )
                    )
                try:
                    arguments = json.loads(call.arguments)
                except json.JSONDecodeError as error:
                    findings.append(
                        Finding(
                            thread_id,
                            turn.index,
                            "malformed_tool_arguments",
                            "hard",
                            str(error),
                        )
                    )
                else:
                    if not isinstance(arguments, Mapping):
                        findings.append(
                            Finding(
                                thread_id,
                                turn.index,
                                "non_object_tool_arguments",
                                "hard",
                                "tool arguments must decode to a JSON object",
                            )
                        )
            text = turn.robot_text
            search_text = text.replace("’", "'").replace("‘", "'")
            if len(text.split()) > 60:
                findings.append(
                    Finding(
                        thread_id,
                        turn.index,
                        "spoken_reply_over_60_words",
                        "review",
                        f"reply has {len(text.split())} words",
                        _excerpt(text),
                    )
                )
            for check_id, pattern in RISK_PATTERNS:
                if pattern.search(search_text):
                    findings.append(
                        Finding(
                            thread_id,
                            turn.index,
                            check_id,
                            "review",
                            "lexical risk flag; requires semantic adjudication",
                            _excerpt(text),
                        )
                    )
        refusal_turns = [
            turn.index
            for turn in fixture.turns
            if REFUSAL_PATTERN.search(turn.robot_text.replace("’", "'").replace("‘", "'"))
        ]
        if len(refusal_turns) > 1:
            findings.append(
                Finding(
                    thread_id,
                    None,
                    "repeated_refusal_language",
                    "review",
                    f"refusal language appears on turns {refusal_turns}",
                )
            )
    return tuple(findings)


def _punt_rows(fixtures: Sequence[Fixture]) -> tuple[dict[str, Any], ...]:
    rater = RulePuntRater()
    rows: list[dict[str, Any]] = []
    for fixture in fixtures:
        turns: list[RaterTurn] = []
        for turn in fixture.turns:
            turns.extend((RaterTurn("owner", turn.owner_text), RaterTurn("robot", turn.robot_text)))
        metric = rater.measure(Response("test", tuple(turns)))
        rows.append(
            {
                "thread_id": fixture.thread_id,
                "value": metric.value,
                "unit": metric.unit,
                "per_turn": [dict(row) for row in metric.per_turn],
                "fingerprint": f"{metric.rater_id}@{metric.rater_version}",
            }
        )
    return tuple(rows)


def load_review(path: Path) -> Mapping[str, Any]:
    body = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(body, Mapping):
        raise QualityError("review artifact must be a JSON object")
    if body.get("schema_version") != REVIEW_SCHEMA_VERSION:
        raise QualityError(f"review schema_version must be {REVIEW_SCHEMA_VERSION}")
    return body


def validate_review(
    review: Mapping[str, Any], scenarios: Sequence[Scenario]
) -> tuple[dict[str, Any], ...]:
    reviewer = review.get("reviewer")
    if not isinstance(reviewer, Mapping) or not str(reviewer.get("id", "")).strip():
        raise QualityError("review needs reviewer.id")
    if not str(reviewer.get("kind", "")).strip():
        raise QualityError("review needs reviewer.kind (human, AI, or other provenance)")
    rows = review.get("threads")
    if not isinstance(rows, list):
        raise QualityError("review.threads must be a list")
    scenario_by_id = _scenario_map(scenarios)
    by_id: dict[str, Mapping[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise QualityError("every review thread must be an object")
        thread_id = str(raw.get("thread_id", "")).strip()
        if not thread_id or thread_id in by_id:
            raise QualityError(f"missing or duplicate review thread_id {thread_id!r}")
        by_id[thread_id] = raw
    if set(by_id) != set(scenario_by_id):
        missing = sorted(set(scenario_by_id) - set(by_id))
        extra = sorted(set(by_id) - set(scenario_by_id))
        raise QualityError(f"review coverage mismatch: missing={missing}, extra={extra}")

    normalized: list[dict[str, Any]] = []
    for scenario in scenarios:
        raw = by_id[scenario.thread_id]
        verdict = str(raw.get("verdict", "")).strip().lower()
        if verdict not in REVIEW_VERDICTS:
            raise QualityError(f"{scenario.thread_id}: invalid review verdict {verdict!r}")
        expectation_verdicts = raw.get("expectation_verdicts")
        if not isinstance(expectation_verdicts, list):
            raise QualityError(f"{scenario.thread_id}: expectation_verdicts must be a list")
        if len(expectation_verdicts) != len(scenario.expect):
            raise QualityError(
                f"{scenario.thread_id}: reviewed {len(expectation_verdicts)} of "
                f"{len(scenario.expect)} authored expectations"
            )
        cleaned_expectations: list[str] = []
        for item in expectation_verdicts:
            value = str(item).strip().lower()
            if value not in EXPECTATION_VERDICTS:
                raise QualityError(
                    f"{scenario.thread_id}: invalid expectation verdict {value!r}"
                )
            cleaned_expectations.append(value)
        expectation_set = set(cleaned_expectations)
        if verdict == "pass" and expectation_set != {"pass"}:
            raise QualityError(f"{scenario.thread_id}: PASS thread contains a non-pass expectation")
        if verdict == "mixed" and not {"pass", "fail"}.issubset(expectation_set):
            raise QualityError(
                f"{scenario.thread_id}: MIXED thread needs both pass and fail expectations"
            )
        note = str(raw.get("note", "")).strip()
        if verdict != "pass" and not note:
            raise QualityError(f"{scenario.thread_id}: {verdict} review must explain why")
        turn_indices = raw.get("turn_indices") or []
        if not isinstance(turn_indices, list) or any(
            not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < scenario.turn_count
            for index in turn_indices
        ):
            raise QualityError(f"{scenario.thread_id}: turn_indices must name captured turns")
        normalized.append(
            {
                "thread_id": scenario.thread_id,
                "family": scenario.family,
                "verdict": verdict,
                "expectation_verdicts": cleaned_expectations,
                "expectation_count": len(scenario.expect),
                "note": note,
                "turn_indices": turn_indices,
            }
        )
    return tuple(normalized)


def score_corpus(
    scenarios: Sequence[Scenario],
    fixtures: Sequence[Fixture],
    *,
    review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    findings = machine_findings(scenarios, fixtures)
    hard = [finding for finding in findings if finding.severity == "hard"]
    risk = [finding for finding in findings if finding.severity == "review"]
    punts = _punt_rows(fixtures)
    review_rows: tuple[dict[str, Any], ...] = ()
    review_error = ""
    if review is not None:
        try:
            review_rows = validate_review(review, scenarios)
        except QualityError as error:
            review_error = str(error)

    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in review_rows:
        family_counts[row["family"]][row["verdict"]] += 1
    review_counts = Counter(row["verdict"] for row in review_rows)
    expectation_counts = Counter(
        verdict for row in review_rows for verdict in row["expectation_verdicts"]
    )
    reviewer = dict(review.get("reviewer") or {}) if review is not None else {}
    review_status = "complete" if review_rows and not review_error else "incomplete"

    return {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "corpus": {
            "thread_count": len(fixtures),
            "turn_count": sum(len(fixture.turns) for fixture in fixtures),
            "families": dict(sorted(Counter(fixture.family for fixture in fixtures).items())),
            "models": sorted({fixture.model for fixture in fixtures}),
        },
        "machine": {
            "status": "pass" if not hard else "fail",
            "hard_failure_count": len(hard),
            "review_flag_count": len(risk),
            "punt_count": int(sum(row["value"] for row in punts)),
            "findings": [asdict(finding) for finding in findings],
            "punts": list(punts),
        },
        "semantic_review": {
            "status": review_status,
            "error": review_error,
            "reviewer": reviewer,
            "thread_verdicts": dict(sorted(review_counts.items())),
            "expectation_verdicts": dict(sorted(expectation_counts.items())),
            "by_family": {
                family: dict(sorted(counts.items()))
                for family, counts in sorted(family_counts.items())
            },
            "threads": list(review_rows),
            "report_only": True,
        },
        "claims": {
            "machine_checks_prove_conversation_quality": False,
            "single_unblinded_review_proves_owner_preference": False,
            "audio_evaluated": False,
            "physical_actions_executed": False,
            "tool_calls_are_proposals_only": True,
        },
        "does_not_prove": [
            "warmth, naturalness, persona quality or owner preference from machine checks",
            "blinded or inter-rater-calibrated human preference",
            "current-model quality: the fixtures are historical captured outputs",
            "tool execution or physical task success: fixture calls are proposals only",
            "speech recognition, synthesis, room acoustics, AEC or mounted audio quality",
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--require-review", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        review = load_review(args.review) if args.review else None
        report = score_corpus(load_scenarios(), load_fixtures(), review=review)
    except (OSError, json.JSONDecodeError, QualityError) as error:
        print(f"realtime_convo quality: {type(error).__name__}: {error}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "machine": report["machine"],
                "semantic_review": report["semantic_review"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if report["machine"]["status"] != "pass":
        return 1
    if args.require_review and report["semantic_review"]["status"] != "complete":
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
