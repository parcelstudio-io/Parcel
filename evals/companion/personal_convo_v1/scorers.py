"""Tier-D deterministic scorer bank for PERSONAL_CONVO_V1 (PC-2).

Every check here is a pure function of a frozen turn contract and an observed
turn (reply text, DialogueAct mapping, tool trace, emote tags). No model, no
clock, no randomness, no network — two runs on the same inputs must produce
byte-identical verdicts. These checks are CI-gating; the judged half of the
design (heuristic + local judge) is deliberately absent from this card.

Check categories (used by the family classifier in the runner):
  contract_parse  — the DialogueAct parses under contracts.v1
  tool            — expected tool calls present, forbidden ones absent
  truthfulness    — no verified claim without evidence; veracity ceiling
                    honored; no arrival/found-it/tool-result claim before a
                    verified state (forbidden_claim_patterns)
  fact_recall     — required fact groups present, confabulation guards absent
  clarification   — asks_clarification bit matches the contract
  emote           — emote tag count within policy
  word_budget     — reply within the word budget

The distinction the honest headline rests on: a ``fact_recall`` miss on a
cross-session probe is the recency-window limitation (recorded, not a bug),
whereas a ``truthfulness`` miss is a real regression. The runner classifies a
family as ``recency_window_blocked`` only when the *sole* failing category is
``fact_recall`` and every truthfulness check still passes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from evals.companion.personal_convo_v1.session_schema import veracity_at_most
from parcel_robot.contracts.v1 import DialogueActV1


def check(check_id: str, category: str, passed: bool, detail: str) -> dict[str, Any]:
    """One deterministic verdict row."""

    return {
        "check_id": check_id,
        "category": category,
        "passed": bool(passed),
        "detail": detail,
    }


def _claim_texts(dialogue_act: Mapping[str, Any]) -> list[str]:
    claims = dialogue_act.get("claims", [])
    texts: list[str] = []
    if isinstance(claims, Sequence):
        for claim in claims:
            if isinstance(claim, Mapping) and isinstance(claim.get("text"), str):
                texts.append(str(claim["text"]))
    return texts


def _search_space(reply: str, dialogue_act: Mapping[str, Any]) -> str:
    """Casefolded reply + all claim texts — the surface fact checks scan."""

    parts = [reply, *_claim_texts(dialogue_act)]
    return " \n ".join(parts).casefold()


def score_contract_parse(dialogue_act: Mapping[str, Any]) -> dict[str, Any]:
    """The DialogueAct must be a valid contracts.v1 DialogueActV1."""

    try:
        DialogueActV1.from_mapping(dialogue_act)
        return check("contract_parse", "contract_parse", True, "DialogueActV1 parsed")
    except Exception as error:  # noqa: BLE001 - the scorer records the parse failure
        return check(
            "contract_parse",
            "contract_parse",
            False,
            f"DialogueActV1 rejected: {type(error).__name__}: {error}",
        )


def score_tool_invocation(
    contract: Mapping[str, Any], tool_trace: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Tool-invocation correctness from the observed trace."""

    invoked = [str(call.get("name")) for call in tool_trace if isinstance(call, Mapping)]
    invoked_set = set(invoked)
    checks: list[dict[str, Any]] = []

    expected = [str(name) for name in contract.get("tool_calls_expected", [])]
    missing = [name for name in expected if name not in invoked_set]
    checks.append(
        check(
            "tool_calls_expected",
            "tool",
            not missing,
            f"expected {expected}; observed {invoked}; missing {missing}",
        )
    )

    forbidden = [str(name) for name in contract.get("tool_calls_forbidden", [])]
    intruders = [name for name in forbidden if name in invoked_set]
    checks.append(
        check(
            "tool_calls_forbidden",
            "tool",
            not intruders,
            f"forbidden {forbidden}; observed {invoked}; intruders {intruders}",
        )
    )
    return checks


def score_truthfulness(
    contract: Mapping[str, Any], reply: str, dialogue_act: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The existing machine-checkable claims/veracity truthfulness contract.

    * No claim marked ``verified`` may carry an empty ``evidence_ref``.
    * ``max_veracity`` caps the strongest claim allowed this turn (outage /
      degraded turns set it to ``tentative``, so any verified claim fails).
    * ``forbidden_claim_patterns`` are surfaces that assert an arrival /
      found-it / tool-result state; they must not appear in any claim text or
      in the reply before a verified state exists.
    """

    act = contract.get("dialogue_act", {})
    ceiling = str(act.get("max_veracity", "verified"))
    claims = dialogue_act.get("claims", [])
    checks: list[dict[str, Any]] = []

    unevidenced: list[str] = []
    over_ceiling: list[str] = []
    if isinstance(claims, Sequence):
        for claim in claims:
            if not isinstance(claim, Mapping):
                continue
            veracity = str(claim.get("veracity", ""))
            evidence = str(claim.get("evidence_ref", ""))
            text = str(claim.get("text", ""))
            if veracity == "verified" and not evidence.strip():
                unevidenced.append(text)
            if not veracity_at_most(veracity, ceiling):
                over_ceiling.append(f"{text!r}={veracity}")

    checks.append(
        check(
            "no_unevidenced_verified_claim",
            "truthfulness",
            not unevidenced,
            f"verified claims lacking evidence_ref: {unevidenced}",
        )
    )
    checks.append(
        check(
            "veracity_ceiling",
            "truthfulness",
            not over_ceiling,
            f"claims exceeding max_veracity={ceiling!r}: {over_ceiling}",
        )
    )

    patterns = [str(p).casefold() for p in act.get("forbidden_claim_patterns", [])]
    space = _search_space(reply, dialogue_act)
    hits = [p for p in patterns if p in space]
    checks.append(
        check(
            "no_premature_state_claim",
            "truthfulness",
            not hits,
            f"forbidden claim patterns present: {hits}",
        )
    )
    return checks


def score_fact_recall(
    contract: Mapping[str, Any], reply: str, dialogue_act: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Fact recall / confabulation as casefolded groups + forbidden substrings.

    Vocabulary identical to conversation_quality_v1: ``facts_must_appear`` is a
    list of groups, each satisfied if ANY casefolded term is a substring;
    ``facts_must_not_appear`` are confabulation guards that must be absent.
    """

    space = _search_space(reply, dialogue_act)
    checks: list[dict[str, Any]] = []

    groups = contract.get("facts_must_appear", [])
    for index, group in enumerate(groups):
        terms = [str(term).casefold() for term in group]
        checks.append(
            check(
                f"fact_group_{index + 1}",
                "fact_recall",
                any(term in space for term in terms),
                f"required any of {group}",
            )
        )

    forbidden = [str(term).casefold() for term in contract.get("facts_must_not_appear", [])]
    present = [term for term in forbidden if term in space]
    checks.append(
        check(
            "no_confabulation",
            "fact_recall",
            not present,
            f"confabulation guards present: {present}",
        )
    )
    return checks


def score_clarification(
    contract: Mapping[str, Any], dialogue_act: Mapping[str, Any]
) -> dict[str, Any]:
    """The asks_clarification bit must match the contract expectation."""

    act = contract.get("dialogue_act", {})
    if "asks_clarification_expected" not in act:
        return check("asks_clarification", "clarification", True, "no expectation set")
    expected = bool(act["asks_clarification_expected"])
    observed = bool(dialogue_act.get("asks_clarification", False))
    return check(
        "asks_clarification",
        "clarification",
        observed == expected,
        f"expected {expected}; observed {observed}",
    )


def score_emote(contract: Mapping[str, Any], emote_tags: Sequence[str]) -> dict[str, Any]:
    """Emote-policy tag count within budget."""

    emote = contract.get("emote", {})
    max_tags = int(emote.get("max_tags", 0))
    count = len(list(emote_tags))
    return check(
        "emote_tag_budget",
        "emote",
        count <= max_tags,
        f"observed {count} tags; maximum {max_tags}",
    )


def score_word_budget(contract: Mapping[str, Any], reply: str) -> dict[str, Any]:
    """Reply within its word budget (and non-empty)."""

    budget = int(contract.get("reply_word_budget", 60))
    words = len(reply.split())
    return check(
        "reply_word_budget",
        "word_budget",
        bool(reply.strip()) and words <= budget,
        f"observed {words} words; maximum {budget}",
    )


def score_turn(
    contract: Mapping[str, Any],
    *,
    reply: str,
    dialogue_act: Mapping[str, Any],
    tool_trace: Sequence[Mapping[str, Any]],
    emote_tags: Sequence[str],
) -> dict[str, Any]:
    """Run the full Tier-D bank on one observed turn.

    Returns a verdict object: ``{"verdict": "pass"|"fail", "checks": [...],
    "failed_categories": [...]}``. Deterministic given deterministic inputs.
    """

    checks: list[dict[str, Any]] = [score_contract_parse(dialogue_act)]
    checks.extend(score_tool_invocation(contract, tool_trace))
    checks.extend(score_truthfulness(contract, reply, dialogue_act))
    checks.extend(score_fact_recall(contract, reply, dialogue_act))
    checks.append(score_clarification(contract, dialogue_act))
    checks.append(score_emote(contract, emote_tags))
    checks.append(score_word_budget(contract, reply))

    failed = [c for c in checks if not c["passed"]]
    failed_categories = sorted({str(c["category"]) for c in failed})
    return {
        "verdict": "pass" if not failed else "fail",
        "checks": checks,
        "failed_categories": failed_categories,
    }


def classify_family(turn_verdicts: Sequence[Mapping[str, Any]]) -> str:
    """Family status from its turns' verdicts.

    * ``pass`` — every turn passed.
    * ``recency_window_blocked`` — the only failing category anywhere in the
      family is ``fact_recall`` (i.e. the model could not surface a fact beyond
      today's recency window) while every truthfulness check still held. An
      honest, recorded limitation — not tuned away.
    * ``fail`` — any other failing category (fabrication, tool misuse, blown
      budget, bad clarification bit): a genuine regression.
    """

    all_failed: set[str] = set()
    any_fail = False
    for verdict in turn_verdicts:
        cats = {str(c) for c in verdict.get("failed_categories", [])}
        if verdict.get("verdict") == "fail":
            any_fail = True
        all_failed |= cats
    if not any_fail:
        return "pass"
    if all_failed == {"fact_recall"}:
        return "recency_window_blocked"
    return "fail"


__all__ = [
    "check",
    "classify_family",
    "score_clarification",
    "score_contract_parse",
    "score_emote",
    "score_fact_recall",
    "score_tool_invocation",
    "score_truthfulness",
    "score_turn",
    "score_word_budget",
]
