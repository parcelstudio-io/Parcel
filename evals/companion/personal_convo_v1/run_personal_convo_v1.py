"""Run PERSONAL_CONVO_V1 — text tier (Tier T), per-commit CI (PC-1..PC-4).

The runner drives frozen multi-turn session scripts through the live text path
and scores every turn with the deterministic Tier-D bank. It mirrors
conversation_quality_v1's discipline: the manifest sha-pins every fixture and
scorer, the suite refuses to run on any edit, and results are written
immutably with a mandatory ``does_not_prove`` block.

Provider selection mirrors conversation_quality_v1's fake: the default provider
is the offline, deterministic :class:`FixtureConversationProvider`, so CI is
byte-reproducible with no model server. ``--provider live`` assembles the real
prompting stack (owner profile + weather tool + persona) around a llama.cpp
server and swaps in a live Tier-2 summarizer so summary *quality* is measured;
it is out of the CI path.

PC-4: every run re-scores the frozen known-good/known-bad calibration pack with
the local report-only judge. Drift ⇒ ``judge.status=disqualified`` and probe
judged scores are omitted (never silently shifted). Judge output never gates
``family_status`` / ``case_verdicts``.

Tier A (audio e2e on the acoustic rig) and the human-recorded corpus remain
separate owner-gated cards.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.companion.personal_convo_v1.build_memory_fixture import (
    MemoryGraph,
    build_memory,
    evidence_within_window,
    load_graph,
)
from evals.companion.personal_convo_v1.fixture_provider import (
    FixtureConversationProvider,
    TurnResult,
)
from evals.companion.personal_convo_v1.judge import (
    JUDGE_ID,
    calibrate,
    judge_probe_turns,
)
from evals.companion.personal_convo_v1.live_provider import (
    LiveConversationProvider,
    LiveSummarizer,
    measure_summarizer_quality,
)
from evals.companion.personal_convo_v1.scorers import classify_family, score_turn
from evals.companion.personal_convo_v1.session_schema import (
    PROBE_FAMILIES,
    validate_session_script,
)
from parcel_robot.dynamic_prompting import UserProfileSource, build_weather_tool
from parcel_robot.providers import LlamaCppProvider
from parcel_robot.tiered_memory import (
    TieredMemory,
    TieredMemoryConfig,
    Turn,
    null_distiller,
)

SUITE_ID = "parcel-personal-convo-v1"
MEMORY_BACKENDS = ("tiered", "recency")
RUNNER_VERSION = "personal-convo-text-tier-v1"
TIER = "T"
SUITE_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SUITE_ROOT.parents[2]
MANIFEST_PATH = SUITE_ROOT / "manifest.json"


class PersonalConvoError(ValueError):
    """The frozen suite or a requested profile is invalid."""


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PersonalConvoError(f"cannot load {path}: {error}") from error


def load_frozen_suite(manifest_path: str | Path = MANIFEST_PATH) -> dict[str, Any]:
    """Verify the manifest and every sha-pinned input; refuse to run on edits."""

    path = Path(manifest_path).resolve()
    manifest = _load_json(path)
    if not isinstance(manifest, dict):
        raise PersonalConvoError("manifest must be a JSON object")

    required = {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "tier": TIER,
        "frozen": True,
    }
    for key, expected in required.items():
        if manifest.get(key) != expected:
            raise PersonalConvoError(f"manifest {key} must equal {expected!r}")

    locked = manifest.get("locked_files")
    if not isinstance(locked, list) or not locked:
        raise PersonalConvoError("manifest locked_files must be a non-empty list")
    for item in locked:
        if not isinstance(item, dict):
            raise PersonalConvoError("locked_files entries must be objects")
        relative = item.get("path")
        expected_hash = item.get("sha256")
        if not isinstance(relative, str) or not relative or relative.startswith("/"):
            raise PersonalConvoError("locked file path must be repository-relative")
        if not isinstance(expected_hash, str) or len(expected_hash) != 64:
            raise PersonalConvoError("locked file sha256 must be a SHA-256")
        target = (REPO_ROOT / relative).resolve()
        if REPO_ROOT not in target.parents:
            raise PersonalConvoError("locked file escaped the repository")
        try:
            actual = _file_sha256(target)
        except OSError as error:
            raise PersonalConvoError(f"cannot read frozen input {target}: {error}") from error
        if actual != expected_hash:
            raise PersonalConvoError(f"{relative} does not match its frozen SHA-256")

    probe_files = manifest.get("probe_files")
    if not isinstance(probe_files, list) or not probe_files:
        raise PersonalConvoError("manifest probe_files must be a non-empty list")
    if len(probe_files) != manifest.get("scenario_count"):
        raise PersonalConvoError("probe count does not match manifest scenario_count")
    return manifest


def load_probes(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Load, validate, and order every probe named in the manifest."""

    probes: list[dict[str, Any]] = []
    families: set[str] = set()
    for relative in manifest["probe_files"]:
        script = _load_json((REPO_ROOT / str(relative)).resolve())
        if not isinstance(script, dict):
            raise PersonalConvoError(f"probe {relative} must be a JSON object")
        validate_session_script(script)
        families.add(str(script["probe_family"]))
        probes.append(script)
    missing = set(PROBE_FAMILIES) - families
    if missing:
        raise PersonalConvoError(f"probe corpus is missing families: {sorted(missing)}")
    probes.sort(key=lambda script: str(script["scenario_id"]))
    return probes


def pack_digest(locked_files: Sequence[Mapping[str, Any]]) -> str:
    """Digest over the sorted locked-file hashes — stable across frozen runs."""

    joined = "\n".join(sorted(str(item["sha256"]) for item in locked_files))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _weather_mode(scenario: Mapping[str, Any], session: Mapping[str, Any]) -> str:
    session_tools = session.get("tool_fixtures") or {}
    scenario_tools = scenario.get("tool_fixtures") or {}
    weather = session_tools.get("weather") or scenario_tools.get("weather") or {}
    return str(weather.get("mode", "normal"))


def make_eval_summarizer(evidence_contents: frozenset[str]) -> Callable[..., str]:
    """A deterministic Tier-2 summarizer for the frozen cross-session fixture.

    It is a *stand-in* for a live ``summarize()`` (recorded in ``does_not_prove``,
    not proof of real summary quality). It models the one behaviour the tier must
    have: a rolling per-conversation summary that keeps the salient *setup* and
    the salient *latest update*, dropping small talk — exactly the compression a
    good companion summary performs. Salience is the event graph's own
    ``kind: evidence`` labels (its authored ground truth for "what matters"), so
    the aged-out "offer" resolution survives co-located with the "job interview
    Monday" setup in one concise, retrievable line. No clock, no RNG, no model.
    """

    buckets: dict[str, list[str]] = {}

    def summarizer(previous_summary: str, aged_turns: Sequence[Turn]) -> str:
        del previous_summary  # closure state is authoritative
        if not aged_turns:
            return "(no salient facts yet)"
        session = aged_turns[0].session_id
        bucket = buckets.setdefault(session, [])
        for turn in aged_turns:
            if turn.content in evidence_contents:
                bucket.append(turn.content)
        if not bucket:
            return "(no salient facts yet)"
        if len(bucket) == 1:
            return bucket[0]
        return f"{bucket[0]} {bucket[-1]}"

    return summarizer


def _tiered_memory_window(
    graph: MemoryGraph,
    limit: int,
    *,
    summarizer: Callable[..., str] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Replay the event graph into a TieredMemory and flatten a retrieval.

    Tier 1 mirrors the old recency window (``tier1_max_turns == recency_limit``),
    so the same eight rows that could not surface the offer still cannot — the
    flip comes from the Tier-2 rolling summary. The returned rows are what the
    live text path's recall step sees in place of ``recent(limit)``.
    """

    evidence_contents = frozenset(event.content for event in graph.evidence)
    active = summarizer or make_eval_summarizer(evidence_contents)
    store = TieredMemory(
        summarizer=active,
        distiller=null_distiller,
        config=TieredMemoryConfig(tier1_max_turns=limit),
    )
    for event in graph.events:
        store.append(event.role, event.content, session_id=event.session or "default")
    retrieval = store.retrieve(graph.probe_query)
    window: list[dict[str, str]] = []
    summary_texts = [summary.text for summary in retrieval.tier2_summaries]
    for summary in retrieval.tier2_summaries:
        window.append({"role": "assistant", "content": summary.text})
    for fact in retrieval.tier3_profile:
        window.append(
            {"role": "assistant", "content": f"{fact.key.replace('_', ' ')}: {fact.value}"}
        )
    for turn in retrieval.tier1_recent:
        window.append({"role": turn.role, "content": turn.content})
    meta: dict[str, Any] = {
        "tier1_recent": len(retrieval.tier1_recent),
        "tier2_summaries": len(retrieval.tier2_summaries),
        "tier3_profile_facts": len(retrieval.tier3_profile),
        "tier2_summary_texts": summary_texts,
        "summarizer_kind": (
            "live_llm" if isinstance(active, LiveSummarizer) else "fixture_deterministic"
        ),
    }
    if isinstance(active, LiveSummarizer):
        joined = " ".join(summary_texts) or active.last_summary
        meta["summarizer_quality"] = measure_summarizer_quality(
            summary_text=joined,
            used_fallback=active.used_fallback,
            call_count=active.call_count,
        )
    return window, meta


def _build_memory_window(
    memory_spec: Mapping[str, Any],
    memory_backend: str,
    *,
    summarizer: Callable[..., str] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Resolve a scenario's ``memory_fixture`` into (window rows, provenance).

    ``tiered`` (default) surfaces aged facts through the three-tier store;
    ``recency`` reproduces the day-one recency-window baseline (``recent(limit)``)
    for regression/comparison.
    """

    graph = load_graph((SUITE_ROOT / str(memory_spec["graph"])).resolve())
    limit = int(memory_spec.get("recency_limit", graph.recency_limit))
    meta: dict[str, Any] = {
        "graph_id": graph.graph_id,
        "backend": memory_backend,
        "recency_limit": limit,
        "total_rows": len(graph.events),
        "evidence_rows": len(graph.evidence),
        # Stays False by construction: Tier 1 / recency alone cannot surface the
        # evidence. The tiered flip is the tiers, not a widened window.
        "evidence_within_recency_window": evidence_within_window(graph),
    }
    if memory_backend == "tiered":
        window, extra = _tiered_memory_window(graph, limit, summarizer=summarizer)
    elif memory_backend == "recency":
        window = build_memory(graph).recent(limit)
        extra = {"tier1_recent": len(window), "tier2_summaries": 0, "tier3_profile_facts": 0}
    else:
        raise PersonalConvoError(f"unknown memory backend: {memory_backend!r}")
    meta.update(extra)
    meta["window_rows"] = len(window)
    return window, meta


def run_scenario(
    scenario: Mapping[str, Any],
    respond: Callable[..., TurnResult],
    *,
    memory_backend: str = "tiered",
    summarizer: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Drive one probe scenario end to end and score every turn."""

    profile = UserProfileSource(dict(scenario.get("profile_facts", {})))
    profile_facts = profile.facts()
    weather_cx = build_weather_tool(profile)

    def weather_tool(location: str) -> str:
        # Exercise the real dynamic_prompting information tool (its handler),
        # keeping the live text path's tool plumbing on the fixture run.
        return weather_cx.handler({"location": location})

    memory_spec = scenario.get("memory_fixture")
    memory_window: list[dict[str, str]] = []
    memory_meta: dict[str, Any] | None = None
    if memory_spec:
        memory_window, memory_meta = _build_memory_window(
            memory_spec, memory_backend, summarizer=summarizer
        )

    turn_records: list[dict[str, Any]] = []
    turn_verdicts: list[dict[str, Any]] = []
    live_history: list[dict[str, str]] = []
    for session in scenario["sessions"]:
        if session.get("reset_live_history", True):
            live_history = []
        mode = _weather_mode(scenario, session)
        for turn in session["turns"]:
            contract = turn.get("contract", {})
            result = respond(
                turn_id=str(turn["turn_id"]),
                persona_id=str(scenario["persona_id"]),
                user_text=str(turn["user"]),
                profile_facts=profile_facts,
                memory_window=memory_window,
                session_history=list(live_history),
                weather_tool=(weather_tool if mode == "normal" else None),
                weather_mode=mode,
            )
            verdict = score_turn(
                contract,
                reply=result.reply,
                dialogue_act=result.dialogue_act,
                tool_trace=result.tool_calls,
                emote_tags=result.emote_tags,
            )
            turn_verdicts.append(verdict)
            turn_records.append(
                {
                    "turn_id": str(turn["turn_id"]),
                    "session_id": str(session["session_id"]),
                    "user": str(turn["user"]),
                    "weather_mode": mode,
                    "intent": result.intent,
                    "reply": result.reply,
                    "dialogue_act": result.dialogue_act,
                    "tool_calls": result.tool_calls,
                    "emote_tags": result.emote_tags,
                    "verdict": verdict["verdict"],
                    "failed_categories": verdict["failed_categories"],
                    "checks": verdict["checks"],
                }
            )
            live_history.append({"role": "user", "content": str(turn["user"])})
            live_history.append({"role": "assistant", "content": result.reply})

    status = classify_family(turn_verdicts)
    return {
        "scenario_id": str(scenario["scenario_id"]),
        "probe_family": str(scenario["probe_family"]),
        "persona_id": str(scenario["persona_id"]),
        "family_status": status,
        "memory_fixture": memory_meta,
        "turns": turn_records,
    }


def run_pack(
    respond: Callable[..., TurnResult],
    *,
    provider_id: str,
    provider_kind: str,
    provenance: Mapping[str, Any],
    run_id: str,
    recorded_at_utc: str,
    memory_backend: str = "tiered",
    summarizer: Callable[..., str] | None = None,
    manifest_path: str | Path = MANIFEST_PATH,
) -> dict[str, Any]:
    """Load the frozen pack, run every scenario, and assemble the result object."""

    if memory_backend not in MEMORY_BACKENDS:
        raise PersonalConvoError(
            f"memory_backend must be one of {MEMORY_BACKENDS}, got {memory_backend!r}"
        )
    manifest = load_frozen_suite(manifest_path)
    probes = load_probes(manifest)

    scenarios = [
        run_scenario(
            scenario,
            respond,
            memory_backend=memory_backend,
            summarizer=summarizer,
        )
        for scenario in probes
    ]

    case_verdicts: dict[str, str] = {}
    for scenario in scenarios:
        for turn in scenario["turns"]:
            case_verdicts[turn["turn_id"]] = turn["verdict"]

    family_status = {
        scenario["probe_family"]: scenario["family_status"] for scenario in scenarios
    }
    passing = sorted(f for f, s in family_status.items() if s == "pass")
    blocked = sorted(f for f, s in family_status.items() if s == "recency_window_blocked")
    failing = sorted(f for f, s in family_status.items() if s == "fail")

    # PC-4: re-score frozen known-good/known-bad every run. Drift ⇒ disqualified.
    calibration = calibrate()
    judge_report = judge_probe_turns(scenarios, calibration=calibration)

    locked_files = manifest["locked_files"]
    tiered = memory_backend == "tiered"
    live_summarizer = isinstance(summarizer, LiveSummarizer)
    memory_note = (
        (
            "cross_session_memory now PASSES via the tiered store: the aged-out "
            "'offer' fact is recalled from a Tier-2 rolling summary, not Tier-1 "
            "recency. evidence_within_recency_window stays False — Tier 1 alone "
            "still cannot surface it; the flip is the tier mechanism, exercised "
            "end to end through this harness and the same Tier-D scorers."
        )
        if tiered
        else (
            "cross_session_memory is recency_window_blocked: today's "
            "ConversationMemory is a recency window, so a fact pushed past "
            "recent(limit) cannot be recalled. This is a true finding motivating "
            "a retrieval upgrade, not a scoring bug."
        )
    )
    does_not_prove = [
        (
            "Deterministic Tier-D checks measure tool correctness, the DialogueAct "
            "truthfulness contract, fact recall/confabulation, the clarification bit, "
            "emote budget, and word budgets — not warmth, naturalness, or persona style."
        ),
        memory_note,
    ]
    if tiered and not live_summarizer:
        does_not_prove.append(
            "Under the tiered backend the Tier-2 summarizer is a DETERMINISTIC "
            "fixture stand-in (evidence-aware compression), not a live model. This "
            "proves the retrieval MECHANISM — an aged fact survives into a summary "
            "and is retrievable — not that a real LLM writes good summaries; that "
            "needs a provenanced --provider live run."
        )
    if live_summarizer:
        does_not_prove.append(
            "Live Tier-2 summarizer quality is reported under "
            "scenarios[*].memory_fixture.summarizer_quality (report-only). A single "
            "provenanced run is not a non-inferiority claim across model swaps."
        )
    does_not_prove.extend(
        [
            (
                "No human-recorded audio was involved; the ~12.5% human-vs-TTS gap is not "
                "covered by this text tier."
            ),
            (
                f"PC-4 local judge ({JUDGE_ID}) is report-only; calibration "
                f"status={calibration['status']}. Drift disqualifies the judge "
                "(scores_valid=false) rather than silently shifting scores. Heuristic "
                "dimensions are not human preference."
            ),
        ]
    )
    if provider_kind == "fixture":
        does_not_prove.append(
            "Under the fixture provider Tier-D verdicts reflect a deterministic "
            "reference companion, not a live model; a live delta requires a "
            "provenanced --provider live run."
        )
    else:
        does_not_prove.append(
            "Live companion turns use a conservative DialogueAct derivation from the "
            "model reply (not the production voice-lane extractor)."
        )

    summarizer_quality = None
    for scenario in scenarios:
        meta = scenario.get("memory_fixture") or {}
        if isinstance(meta, dict) and meta.get("summarizer_quality"):
            summarizer_quality = meta["summarizer_quality"]
            break

    result = {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "tier": TIER,
        "run_id": run_id,
        "recorded_at_utc": recorded_at_utc,
        "memory_backend": memory_backend,
        "provider": {"id": provider_id, "kind": provider_kind},
        "manifest_sha256": _file_sha256(Path(manifest_path)),
        "pack_digest": pack_digest(locked_files),
        "locked_files": list(locked_files),
        "provenance": dict(provenance),
        "scenario_count": len(scenarios),
        "families": sorted(family_status),
        "family_status": family_status,
        "case_verdicts": case_verdicts,
        "aggregate": {
            "turn_count": len(case_verdicts),
            "turns_passed": sum(1 for v in case_verdicts.values() if v == "pass"),
            "families_passing": passing,
            "families_recency_window_blocked": blocked,
            "families_failing": failing,
        },
        "scenarios": scenarios,
        "judge": {
            "calibration": calibration,
            "probe_scores": judge_report,
            "report_only": True,
        },
        "summarizer_quality": summarizer_quality,
        "claims": {
            "text_tier_only": True,
            "audio_tier_executed": False,
            "human_recording_executed": False,
            "judge_model_used": True,
            "judge_report_only": True,
            "judge_calibration_qualified": calibration["status"] == "qualified",
            "machine_checks_prove_conversational_quality": False,
            "cross_session_recall_beyond_recency_window": tiered,
            "live_summarizer_measured": live_summarizer,
        },
        "does_not_prove": does_not_prove,
    }
    return result


def write_result(result: Mapping[str, Any], path: str | Path) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with target.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    return target


def _fixture_respond() -> Callable[..., TurnResult]:
    provider = FixtureConversationProvider()
    return provider.respond


def _live_stack(
    args: argparse.Namespace,
) -> tuple[Callable[..., TurnResult], LiveSummarizer, dict[str, Any]]:
    """Assemble the real llama.cpp companion + live Tier-2 summarizer (out of CI).

    DialogueAct extraction is conservative (eval-local), not the production voice
    lane. The live summarizer is the measurement target for summarizer quality.
    """

    model_id = str(args.model or "gemma-4-26b-a4b")
    model = LlamaCppProvider(
        base_url=str(args.base_url),
        model=model_id,
        timeout=float(args.timeout),
        streaming=True,
        temperature=float(args.temperature),
        top_p=float(args.top_p),
        max_tokens=max(int(args.max_tokens), 384),
        enable_thinking=False,
    )
    provider = LiveConversationProvider(model, retries=2)
    summarizer = LiveSummarizer(
        base_url=str(args.base_url),
        model=model_id,
        timeout=float(args.timeout),
        max_chars=int(args.summary_max_chars),
        temperature=min(float(args.temperature), 0.3),
        top_p=float(args.top_p),
        max_tokens=512,
    )
    extra = {
        "live_stack": {
            "companion": LiveConversationProvider.provider_id,
            "summarizer": "live_llm_freeform",
            "base_url": str(args.base_url),
            "model": model_id,
        }
    }
    return provider.respond, summarizer, extra


def _provenance(args: argparse.Namespace) -> dict[str, Any]:
    provenance: dict[str, Any] = {
        "provider_kind": args.provider,
        "base_url": args.base_url,
        "reference_note": "text tier: the transcript itself is the judged artifact",
    }
    if args.model:
        provenance["model"] = {"id": args.model}
    if args.model_artifact:
        artifact = Path(args.model_artifact).expanduser().resolve()
        if not artifact.is_file():
            raise PersonalConvoError(f"model artifact not found: {artifact}")
        digest = _file_sha256(artifact)
        if args.model_sha256 and digest != args.model_sha256.lower():
            raise PersonalConvoError("model artifact SHA-256 does not match --model-sha256")
        provenance["model"] = {
            **provenance.get("model", {}),
            "artifact_path": str(artifact),
            "artifact_sha256": digest,
        }
    if args.backend_version:
        provenance["backend_version"] = args.backend_version
    if args.device_profile:
        provenance["device_profile"] = args.device_profile
    return provenance


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--model")
    parser.add_argument("--model-artifact", type=Path)
    parser.add_argument("--model-sha256")
    parser.add_argument("--backend-version")
    parser.add_argument("--device-profile")
    parser.add_argument("--description", default="")
    parser.add_argument("--run-id")
    parser.add_argument("--temperature", type=float, default=0.25)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--summary-max-chars", type=int, default=1200)
    parser.add_argument(
        "--memory",
        choices=MEMORY_BACKENDS,
        default="tiered",
        help="memory backend: 'tiered' (default, flips cross_session) or 'recency' (baseline)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    provenance = _provenance(args)
    if args.description.strip():
        provenance["description"] = args.description.strip()

    summarizer: Callable[..., str] | None = None
    if args.provider == "live":
        respond, summarizer, extra = _live_stack(args)
        provenance.update(extra)
        provider_id = args.model or LiveConversationProvider.provider_id
    else:
        respond = _fixture_respond()
        provider_id = FixtureConversationProvider.provider_id

    run_id = args.run_id or (
        f"personal-convo-t-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%SZ')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    result = run_pack(
        respond,
        provider_id=provider_id,
        provider_kind=args.provider,
        provenance=provenance,
        run_id=run_id,
        recorded_at_utc=datetime.now(timezone.utc).isoformat(),
        memory_backend=args.memory,
        summarizer=summarizer,
    )
    path = write_result(result, args.output)
    print(
        json.dumps(
            {
                "output": str(path),
                "run_id": run_id,
                "family_status": result["family_status"],
                "aggregate": result["aggregate"],
                "pack_digest": result["pack_digest"],
                "judge_status": result["judge"]["calibration"]["status"],
                "summarizer_quality": result.get("summarizer_quality"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
