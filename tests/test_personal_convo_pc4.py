"""PC-4: report-only local judge + frozen calibration (drift ⇒ disqualified)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.companion.personal_convo_v1.fixture_provider import FixtureConversationProvider
from evals.companion.personal_convo_v1.judge import (
    JUDGE_ID,
    calibrate,
    judge_probe_turns,
    load_calibration_pack,
    score_case,
)
from evals.companion.personal_convo_v1.run_personal_convo_v1 import (
    SUITE_ROOT,
    PersonalConvoError,
    load_frozen_suite,
    run_pack,
)


def _run() -> dict:
    provider = FixtureConversationProvider()
    return run_pack(
        provider.respond,
        provider_id=provider.provider_id,
        provider_kind="fixture",
        provenance={"provider_kind": "fixture"},
        run_id="personal-convo-pc4-test",
        recorded_at_utc="2026-08-09T00:00:00Z",
        memory_backend="tiered",
    )


def test_calibration_pack_loads_and_qualifies() -> None:
    pack = load_calibration_pack()
    assert pack["manifest"]["judge_id"] == JUDGE_ID
    assert pack["manifest"]["report_only"] is True
    labels = {case["label"] for case in pack["cases"]}
    assert labels == {"known_good", "known_bad"}
    report = calibrate()
    assert report["status"] == "qualified"
    assert report["scores_valid"] is True
    assert report["drift"] is False
    assert report["mismatch_count"] == 0
    assert report["report_only"] is True


def test_calibration_hash_tamper_reddens(tmp_path: Path) -> None:
    src = SUITE_ROOT / "calibration" / "pack.json"
    manifest = json.loads(src.read_text(encoding="utf-8"))
    manifest["locked_files"][0]["sha256"] = "0" * 64
    target = tmp_path / "pack.json"
    # Copy case files so relative loads still resolve from SUITE_ROOT; only the
    # manifest path is overridden — locked hashes still check suite files.
    target.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(Exception, match="frozen SHA-256"):
        load_calibration_pack(target)


def test_calibration_drift_disqualifies(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the judge silently shifts scores, calibration mismatches ⇒ disqualified."""

    from evals.companion.personal_convo_v1 import judge as judge_mod

    real_score = judge_mod.score_case

    def flipped(case):  # type: ignore[no-untyped-def]
        scored = real_score(case)
        scored["passed"] = not bool(scored["passed"])
        return scored

    monkeypatch.setattr(judge_mod, "score_case", flipped)
    report = judge_mod.calibrate()
    assert report["status"] == "disqualified"
    assert report["scores_valid"] is False
    assert report["drift"] is True
    assert report["mismatch_count"] >= 1

    omitted = judge_probe_turns(
        [
            {
                "scenario_id": "x",
                "probe_family": "persona_consistency",
                "turns": [{"turn_id": "t1", "user": "hi", "reply": "I'm glad you're here."}],
            }
        ],
        calibration=report,
    )
    assert omitted["scores_valid"] is False
    assert omitted["turn_scores"] == []
    assert omitted["aggregate"]["omitted_reason"] == "calibration_drift"


def test_known_good_and_known_bad_polarity() -> None:
    pack = load_calibration_pack()
    for case in pack["cases"]:
        scored = score_case(case)
        assert scored["passed"] is bool(case["expected_pass"]), case["case_id"]


def test_fixture_run_embeds_qualified_report_only_judge() -> None:
    result = _run()
    assert result["claims"]["judge_model_used"] is True
    assert result["claims"]["judge_report_only"] is True
    assert result["claims"]["judge_calibration_qualified"] is True
    assert result["judge"]["report_only"] is True
    assert result["judge"]["calibration"]["status"] == "qualified"
    assert result["judge"]["probe_scores"]["scores_valid"] is True
    assert result["judge"]["probe_scores"]["aggregate"]["turns_scored"] == result["aggregate"][
        "turn_count"
    ]
    # Judge must not rewrite Tier-D gates.
    assert result["family_status"]["cross_session_memory"] == "pass"
    assert any("report-only" in note.lower() or "PC-4" in note for note in result["does_not_prove"])


def test_suite_manifest_pins_judge_and_calibration() -> None:
    manifest = load_frozen_suite()
    locked = {item["path"] for item in manifest["locked_files"]}
    assert "evals/companion/personal_convo_v1/judge.py" in locked
    assert "evals/companion/personal_convo_v1/calibration/pack.json" in locked
    assert any("known_good" in path for path in locked)
    assert any("known_bad" in path for path in locked)


def test_live_provider_seam_is_importable() -> None:
    """The live seam must exist for the summarizer-quality run (not exercised offline)."""

    from evals.companion.personal_convo_v1.live_provider import (
        LiveConversationProvider,
        LiveSummarizer,
        measure_summarizer_quality,
    )
    from evals.companion.personal_convo_v1.run_personal_convo_v1 import _parser

    quality = measure_summarizer_quality(
        summary_text="Got the offer after Monday's interview on Friday.",
        used_fallback=False,
        call_count=3,
    )
    assert quality["contains_offer"] is True
    assert quality["report_only"] is True
    assert LiveConversationProvider.provider_id == "live-llamacpp"
    assert callable(LiveSummarizer)
    args = _parser().parse_args(
        [
            "--output",
            "/tmp/out.json",
            "--provider",
            "live",
            "--model",
            "gemma-4-26b-a4b",
        ]
    )
    assert args.provider == "live"


def test_live_cli_without_server_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--provider live` must not silently fall back to fixture."""

    from evals.companion.personal_convo_v1 import run_personal_convo_v1 as runner

    def boom(_args):  # type: ignore[no-untyped-def]
        raise PersonalConvoError("llama.cpp unreachable")

    monkeypatch.setattr(runner, "_live_stack", boom)
    with pytest.raises(PersonalConvoError, match="unreachable"):
        runner.main(
            [
                "--output",
                "/tmp/personal-convo-live-should-not-write.json",
                "--provider",
                "live",
                "--model",
                "gemma-4-26b-a4b",
            ]
        )
