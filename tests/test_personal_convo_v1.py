"""Offline gate for the PERSONAL_CONVO_V1 text tier (Tier T).

Fast, deterministic, no model server. Mirrors conversation_quality_v1's
integrity discipline: the manifest locks every input, tampering reddens before
any provider call, results are immutable, and the fixture provider makes the run
byte-reproducible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.companion.personal_convo_v1.build_memory_fixture import (
    build_memory,
    evidence_within_window,
    load_graph,
)
from evals.companion.personal_convo_v1.fixture_provider import (
    FixtureConversationProvider,
    looks_degraded,
)
from evals.companion.personal_convo_v1.run_personal_convo_v1 import (
    MANIFEST_PATH,
    SUITE_ROOT,
    PersonalConvoError,
    load_frozen_suite,
    load_probes,
    run_pack,
    write_result,
)
from evals.companion.personal_convo_v1.scorers import (
    classify_family,
    score_clarification,
    score_contract_parse,
    score_emote,
    score_fact_recall,
    score_truthfulness,
    score_word_budget,
)
from evals.companion.personal_convo_v1.session_schema import (
    PROBE_FAMILIES,
    SessionScriptError,
    validate_session_script,
)


def _run(memory_backend: str = "tiered") -> dict:
    provider = FixtureConversationProvider()
    return run_pack(
        provider.respond,
        provider_id=provider.provider_id,
        provider_kind="fixture",
        provenance={"provider_kind": "fixture"},
        run_id="personal-convo-test",
        recorded_at_utc="2026-08-09T00:00:00Z",
        memory_backend=memory_backend,
    )


# --- manifest / freeze integrity -------------------------------------------------


@pytest.mark.slow  # card P0-E: frozen-digest integrity is a nightly evidence ratchet
def test_manifest_locks_all_inputs_and_covers_every_family() -> None:
    manifest = load_frozen_suite()
    probes = load_probes(manifest)
    assert manifest["scenario_count"] == 8
    assert len(probes) == 8
    assert {p["probe_family"] for p in probes} == set(PROBE_FAMILIES)
    # Every locked file resolves and its hash matched (load_frozen_suite would
    # have raised otherwise); the scorer bank and fixtures are all pinned.
    locked = {item["path"] for item in manifest["locked_files"]}
    assert any(path.endswith("scorers.py") for path in locked)
    assert any(path.endswith("fixture_provider.py") for path in locked)
    assert any(path.endswith("cross_session_memory.yaml") for path in locked)


def test_manifest_tamper_reddens_before_provider(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["scenario_count"] = 7  # no longer matches probe_files
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PersonalConvoError, match="scenario_count"):
        load_frozen_suite(changed)


def test_manifest_hash_tamper_reddens(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest["locked_files"][0]["sha256"] = "0" * 64
    changed = tmp_path / "manifest.json"
    changed.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PersonalConvoError, match="frozen SHA-256"):
        load_frozen_suite(changed)


def test_result_writer_is_immutable(tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    write_result({"ok": True}, target)
    with pytest.raises(FileExistsError):
        write_result({"ok": False}, target)


# --- determinism + honest headline ----------------------------------------------


def test_fixture_run_is_deterministic() -> None:
    first = _run()
    second = _run()
    assert first["case_verdicts"] == second["case_verdicts"]
    assert first["pack_digest"] == second["pack_digest"]
    assert first["scenarios"] == second["scenarios"]
    assert first["family_status"] == second["family_status"]
    # The tiered flip touches no locked file, so the frozen pack digest is
    # unchanged from the day-one recency run.
    assert first["pack_digest"] == _run("recency")["pack_digest"]


def test_tiered_default_flips_cross_session_to_pass() -> None:
    """The gate: with the tiered store wired, all eight families pass."""

    result = _run()  # tiered is the default backend
    status = result["family_status"]
    assert {f for f, s in status.items() if s == "fail"} == set()
    assert {f for f, s in status.items() if s == "recency_window_blocked"} == set()
    assert {f for f, s in status.items() if s == "pass"} == set(PROBE_FAMILIES)
    assert result["claims"]["cross_session_recall_beyond_recency_window"] is True
    # Honesty preserved: the machine checks still do not claim quality, and the
    # summarizer-is-a-fixture caveat is recorded.
    assert result["claims"]["machine_checks_prove_conversational_quality"] is False
    assert any("summarizer" in note for note in result["does_not_prove"])


def test_tiered_recall_surfaces_the_offer_from_tier2() -> None:
    """The recalled fact is the aged-out 'offer', not a fabrication."""

    result = _run()
    scenario = next(
        sc for sc in result["scenarios"] if sc["probe_family"] == "cross_session_memory"
    )
    turn = scenario["turns"][0]
    assert turn["verdict"] == "pass"
    assert "offer" in turn["reply"].lower()
    # Truthfulness held: the recall claim is evidenced, not premature.
    truthfulness = [c for c in turn["checks"] if c["category"] == "truthfulness"]
    assert truthfulness and all(c["passed"] for c in truthfulness)
    # Surfaced from Tier 2 (a rolling summary), while Tier 1 / recency alone
    # still could not (evidence_within_recency_window stays False).
    meta = scenario["memory_fixture"]
    assert meta["tier2_summaries"] >= 1
    assert meta["evidence_within_recency_window"] is False


def test_recency_baseline_reproduces_recency_window_blocked() -> None:
    """The honest day-one finding is retained under --memory recency."""

    result = _run("recency")
    status = result["family_status"]
    assert {f for f, s in status.items() if s == "fail"} == set()
    assert {f for f, s in status.items() if s == "recency_window_blocked"} == {
        "cross_session_memory"
    }
    turn = next(
        sc["turns"][0]
        for sc in result["scenarios"]
        if sc["probe_family"] == "cross_session_memory"
    )
    assert turn["verdict"] == "fail"
    assert turn["failed_categories"] == ["fact_recall"]
    truthfulness = [c for c in turn["checks"] if c["category"] == "truthfulness"]
    assert truthfulness and all(c["passed"] for c in truthfulness)
    assert result["claims"]["cross_session_recall_beyond_recency_window"] is False


# --- memory subsystem premise ----------------------------------------------------


def test_cross_session_evidence_is_beyond_recency_window() -> None:
    graph = load_graph(SUITE_ROOT / "memory_graphs" / "cross_session_memory.yaml")
    # The honest finding rests on this: the authored distractors push evidence
    # out of recent(limit), so the memory subsystem cannot surface it.
    assert evidence_within_window(graph) is False
    window = build_memory(graph).recent(graph.recency_limit)
    assert len(window) == graph.recency_limit
    joined = " ".join(row["content"].lower() for row in window)
    assert "offer" not in joined


# --- scorer bank units -----------------------------------------------------------


def test_truthfulness_rejects_unevidenced_verified_claim() -> None:
    act = {
        "schema_version": 1,
        "turn_id": "u.t1",
        "text": "It's 22 and sunny.",
        "speech_style": "neutral",
        "acknowledgement_kind": "reply",
        "claims": [{"text": "22 and sunny", "veracity": "verified", "evidence_ref": ""}],
        "social_cues": [],
        "asks_clarification": False,
    }
    checks = score_truthfulness({"dialogue_act": {}}, "It's 22 and sunny.", act)
    assert any(c["check_id"] == "no_unevidenced_verified_claim" and not c["passed"] for c in checks)


def test_truthfulness_enforces_veracity_ceiling_on_outage() -> None:
    act = {
        "schema_version": 1,
        "turn_id": "u.t2",
        "text": "It's sunny.",
        "speech_style": "neutral",
        "acknowledgement_kind": "reply",
        "claims": [{"text": "sunny", "veracity": "verified", "evidence_ref": "tool:get_weather"}],
        "social_cues": [],
        "asks_clarification": False,
    }
    checks = score_truthfulness({"dialogue_act": {"max_veracity": "tentative"}}, "It's sunny.", act)
    assert any(c["check_id"] == "veracity_ceiling" and not c["passed"] for c in checks)


def test_truthfulness_forbids_premature_state_claim() -> None:
    act = {
        "schema_version": 1,
        "turn_id": "u.t3",
        "text": "I grabbed your phone and I'm on my way.",
        "speech_style": "neutral",
        "acknowledgement_kind": "reply",
        "claims": [],
        "social_cues": [],
        "asks_clarification": False,
    }
    contract = {"dialogue_act": {"forbidden_claim_patterns": ["on my way", "i grabbed"]}}
    checks = score_truthfulness(contract, act["text"], act)
    assert any(c["check_id"] == "no_premature_state_claim" and not c["passed"] for c in checks)


def test_fact_recall_and_confabulation_vocabulary() -> None:
    act = {"claims": []}
    good = score_fact_recall(
        {"facts_must_appear": [["friday"]], "facts_must_not_appear": ["monday"]},
        "We said Friday.",
        act,
    )
    assert all(c["passed"] for c in good)
    bad = score_fact_recall(
        {"facts_must_appear": [["friday"]], "facts_must_not_appear": ["monday"]},
        "It was Monday.",
        act,
    )
    assert any(not c["passed"] for c in bad)


def test_clarification_emote_word_and_parse_scorers() -> None:
    act = {"asks_clarification": True}
    assert score_clarification({"dialogue_act": {"asks_clarification_expected": True}}, act)["passed"]
    assert not score_clarification(
        {"dialogue_act": {"asks_clarification_expected": False}}, act
    )["passed"]
    assert score_emote({"emote": {"max_tags": 1}}, ["warmth"])["passed"]
    assert not score_emote({"emote": {"max_tags": 0}}, ["warmth"])["passed"]
    assert score_word_budget({"reply_word_budget": 5}, "one two three")["passed"]
    assert not score_word_budget({"reply_word_budget": 2}, "one two three")["passed"]
    assert not score_contract_parse({"not": "a dialogue act"})["passed"]


def test_family_classifier_distinguishes_blocked_from_fail() -> None:
    only_recall = [{"verdict": "fail", "failed_categories": ["fact_recall"]}]
    assert classify_family(only_recall) == "recency_window_blocked"
    with_fabrication = [{"verdict": "fail", "failed_categories": ["fact_recall", "truthfulness"]}]
    assert classify_family(with_fabrication) == "fail"
    clean = [{"verdict": "pass", "failed_categories": []}]
    assert classify_family(clean) == "pass"


# --- schema + degradation --------------------------------------------------------


def test_every_probe_validates_against_schema() -> None:
    for probe in sorted((SUITE_ROOT / "probes").glob("*.json")):
        validate_session_script(json.loads(probe.read_text(encoding="utf-8")))


def test_schema_rejects_unknown_family() -> None:
    with pytest.raises(SessionScriptError, match="probe_family"):
        validate_session_script(
            {
                "scenario_id": "x",
                "probe_family": "not_a_family",
                "persona_id": "gentle_companion",
                "sessions": [{"session_id": "s", "turns": [{"turn_id": "t", "user": "hi"}]}],
            }
        )


def test_asr_degradation_detection() -> None:
    assert looks_degraded("th w thr t mrrw shld i brng mbrll") is True
    assert looks_degraded("") is True
    assert looks_degraded("Sorry, will it rain in Manhattan tomorrow?") is False
