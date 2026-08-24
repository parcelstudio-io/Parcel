"""Produce every pre-registered H5 row and write the raw artifacts.

    PYTHONPATH=src:.:research/20260823/governed-continual-memory \\
      .parcel/bin/python -m harness.run_h5 --rows all

Rows and where each is produced:

===  =========================================  =========================
row  what                                       module
===  =========================================  =========================
M1   probe pass rate, live summarizer+proposer  ``probes.py`` (3 arms)
M2   fact precision / recall vs the graph       ``facts.py``
M3   granted facts absent from the graph        ``facts.py``
M4   revoked facts reachable in a later DI      ``facts.py`` + ``consent.py``
M5   consent matrix vs ``GRANTING_LABELS``      ``consent.py``
M6   world-query top-1 / refusal                ``world.py``
M7   persist -> reload -> identical answers     here
M8   distillation wall time per session         ``facts.py`` pass records
===  =========================================  =========================

Every store this writes is a fresh sqlite under ``--work``; the owner's
``parcel_memory.sqlite3`` is never opened and ``PARCEL_MEMORY_PURPOSE`` is never
set, so ``memory.path`` resolves ``purpose=test`` for this whole process.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from parcel_robot.memory.tiered import TieredMemory, TieredMemoryConfig
from parcel_robot.online_map.entries import WriterProvenance
from parcel_robot.online_map.online_map import OnlineSemanticMap
from parcel_robot.online_map.store import OnlineMapStore
from parcel_robot.owner_model.distiller import (
    DeterministicFactProposer,
    LanguageModelFactProposer,
    OwnerFactDistiller,
)
from parcel_robot.perception.abstention import (
    RANKING_MARGIN_LABEL_STRENGTH,
    AbstentionPolicy,
)
from parcel_robot.providers import LlamaCppProvider

from . import consent, facts, probes, world
from .histories import corpus_summary
from .live_proposer import ChatFactProposer, InstrumentedSeamProposer

logger = logging.getLogger(__name__)

RESULTS = Path(__file__).resolve().parent.parent / "results"
NOW_WALL_S = 1_787_380_000.0


def gpu_snapshot() -> dict[str, Any]:
    """``nvidia-smi`` at the moment of a headline measurement. GPU is shared."""

    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        used, total, util = (v.strip() for v in out.stdout.strip().split(","))
        return {"memory_used_mib": int(used), "memory_total_mib": int(total), "gpu_util_pct": int(util)}
    except Exception as error:
        # A host with no GPU (or an nvidia-smi that changed its output) is a
        # fact to record, not a reason to lose a measurement run.
        logger.exception("nvidia-smi snapshot failed")
        return {"error": str(error)}


def _proposer(kind: str) -> tuple[Any, str]:
    """One of the three proposers under test. See ``live_proposer.py`` for why
    there are two live ones."""

    if kind == "deterministic":
        return DeterministicFactProposer(), "DeterministicFactProposer (regex, offline)"
    if kind == "seam":
        model = LlamaCppProvider(
            base_url=probes.REASONER_URL,
            model=probes.REASONER_MODEL,
            timeout=180.0,
            streaming=False,
            temperature=0.0,
            top_p=0.9,
            max_tokens=512,
            enable_thinking=False,
        )
        return (
            InstrumentedSeamProposer(inner=LanguageModelFactProposer(model=model)),
            (
                f"LanguageModelFactProposer as shipped ({probes.REASONER_MODEL} @ "
                f"{probes.REASONER_URL}, LanguageModel.decide seam)"
            ),
        )
    return (
        ChatFactProposer(
            base_url=probes.REASONER_URL, model=probes.REASONER_MODEL, constrained=True
        ),
        (
            f"ChatFactProposer research control ({probes.REASONER_MODEL} @ "
            f"{probes.REASONER_URL}, constrained chat completion)"
        ),
    )


# --------------------------------------------------------------------------
# M2 / M3 / M4 / M8
# --------------------------------------------------------------------------
def run_facts(work: Path) -> dict[str, Any]:
    arms = (
        ("det_norevocation", "deterministic", False),
        ("det_revocation", "deterministic", True),
        ("seam_revocation", "seam", True),
        ("chat_norevocation", "chat", False),
        ("chat_revocation", "chat", True),
    )
    out: dict[str, Any] = {"corpus": corpus_summary(), "arms": {}}
    for arm, kind, respect in arms:
        proposer, proposer_id = _proposer(kind)
        started = time.perf_counter()
        live = kind in {"seam", "chat"}
        gpu_before = gpu_snapshot() if live else {}
        result = facts.run_arm(
            arm=arm,
            store_dir=work / "facts",
            proposer=proposer,
            proposer_id=proposer_id,
            respect_revocations=respect,
        )
        payload = result.as_dict()
        payload["wall_s"] = round(time.perf_counter() - started, 3)
        payload["gpu_before"] = gpu_before
        payload["gpu_after"] = gpu_snapshot() if live else {}
        if hasattr(proposer, "stats"):
            payload["proposer_stats"] = proposer.stats()
        distil = [p for p in payload["passes"] if p.get("trigger") in {"session_close", "idle"}]
        times = sorted(p["wall_s"] for p in distil if p.get("ran"))
        payload["m8_distillation_wall_s"] = {
            "passes": len(times),
            "min": times[0] if times else None,
            "median": times[len(times) // 2] if times else None,
            "max": times[-1] if times else None,
            "total": round(sum(times), 3),
        }
        out["arms"][arm] = payload
    return out


# --------------------------------------------------------------------------
# M6 (+ the map half of M7)
# --------------------------------------------------------------------------
def run_world(work: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"operating_points": {}}
    points = (
        ("shipped_robust_z", None),
        (
            "label_strength",
            AbstentionPolicy(ranking_margin_mode=RANKING_MARGIN_LABEL_STRENGTH),
        ),
    )
    for name, policy in points:
        store_path = work / "map" / f"{name}.sqlite3"
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(store_path) + suffix)
            if candidate.exists():
                candidate.unlink()
        store_path.parent.mkdir(parents=True, exist_ok=True)
        semantic_map, counts = world.build_map(str(store_path), policy=policy)
        answers = world.ask_all(semantic_map, now_wall_s=NOW_WALL_S)
        present = answers[: len(world.PRESENT_QUERIES)]
        absent = answers[len(world.PRESENT_QUERIES) :]
        persisted = semantic_map.persist()
        semantic_map.close()

        reloaded_store = OnlineMapStore(str(store_path))
        reloaded = OnlineSemanticMap(
            reloaded_store,
            provenance=WriterProvenance(
                session_id="h5-world-reload",
                seat="runtime_camera",
                detector_name="owlv2-b16",
                scene_id="city_block",
                origin="unknown",
            ),
            reload=True,
            policy=policy,
        )
        for pose in world.patrol_path():
            reloaded.note_pose(*pose)
        for query in world.PRESENT_QUERIES + world.ABSENT_QUERIES:
            reloaded.note_frame(queries=(query,))
        reloaded_answers = world.ask_all(reloaded, now_wall_s=NOW_WALL_S)
        reloaded.close()

        before = json.dumps([a["text"] for a in answers], sort_keys=True)
        after = json.dumps([a["text"] for a in reloaded_answers], sort_keys=True)
        out["operating_points"][name] = {
            "map": counts,
            "entries_persisted": persisted,
            "present_questions": len(present),
            "present_top1_correct": sum(1 for a in present if a["top1_correct"]),
            "present_top1_rate": round(
                sum(1 for a in present if a["top1_correct"]) / len(present), 4
            ),
            "absent_questions": len(absent),
            "absent_refused": sum(1 for a in absent if not a["answered"]),
            "absent_refusal_rate": round(
                sum(1 for a in absent if not a["answered"]) / len(absent), 4
            ),
            "reload_answers_identical": before == after,
            "answers": answers,
            "reloaded_answers": reloaded_answers,
        }
    return out


# --------------------------------------------------------------------------
# M7 — the tiered-memory half
# --------------------------------------------------------------------------
def run_persistence(work: Path) -> dict[str, Any]:
    """Write a tiered store, reload it, and compare snapshot bytes and answers."""

    from evals.companion.personal_convo_v1.build_memory_fixture import load_graph
    from evals.companion.personal_convo_v1.run_personal_convo_v1 import (
        SUITE_ROOT,
        make_eval_summarizer,
    )

    graph = load_graph(SUITE_ROOT / "memory_graphs" / "cross_session_memory.yaml")
    evidence = frozenset(event.content for event in graph.evidence)
    summarizer = make_eval_summarizer(evidence)
    distiller = OwnerFactDistiller(proposer=DeterministicFactProposer())
    config = TieredMemoryConfig(tier1_max_turns=graph.recency_limit, tier2_max_summaries=1)

    store = TieredMemory(summarizer=summarizer, distiller=distiller, config=config)
    for event in graph.events:
        store.append(event.role, event.content, session_id=event.session or "default")

    work.mkdir(parents=True, exist_ok=True)
    first = store.save(work / "tiered_first.json")
    reloaded = TieredMemory(
        summarizer=make_eval_summarizer(evidence), distiller=distiller, config=config
    )
    restored = reloaded.load(first)
    second = reloaded.save(work / "tiered_second.json")

    before = _render(store.retrieve(graph.probe_query))
    after = _render(reloaded.retrieve(graph.probe_query))
    return {
        "tier3_case": _tier3_case(work),
        "graph_id": graph.graph_id,
        "rows_restored": restored,
        "snapshot_bytes": first.stat().st_size,
        "snapshot_bytes_identical": first.read_bytes() == second.read_bytes(),
        "answers_identical": before == after,
        "tier2_summaries": len(store.live_summaries()),
        "tier3_profile_keys": [fact.key for fact in store.profile()],
        "retrieval_before": before,
        "retrieval_after": after,
        "stats": store.stats(),
    }


def _tier3_case(work: Path) -> dict[str, Any]:
    """Tier 3 actually holding something, persisted and reloaded.

    The frozen ``cross_session_memory`` graph puts every event in ONE session,
    so its Tier-2 rolling summary never overflows and Tier 3 is unreachable on
    that path whatever distiller is injected — measured, and reported in
    RESULTS.md rather than worked around. This case supplies the several
    sessions the overflow needs, so the durable-profile half of the persistence
    claim is a measurement instead of an empty list.
    """

    config = TieredMemoryConfig(tier1_max_turns=2, tier2_max_summaries=1)
    distiller = OwnerFactDistiller(proposer=DeterministicFactProposer())
    store = TieredMemory(
        summarizer=lambda previous, aged: " ".join(
            [previous] + [t.content for t in aged]
        ).strip(),
        distiller=distiller,
        config=config,
    )
    scripts = (
        ("s1", "My sister's name is Hana and she lives nearby."),
        ("s2", "I like short answers before coffee."),
        ("s3", "I usually walk to the park at seven."),
        ("s4", "I live in Brooklyn now."),
    )
    for session_id, text in scripts:
        store.append("user", text, session_id=session_id)
        store.append("assistant", "Noted.", session_id=session_id)

    path = store.save(work / "tiered_tier3.json")
    reloaded = TieredMemory(
        summarizer=lambda previous, aged: previous, distiller=distiller, config=config
    )
    reloaded.load(path)
    again = reloaded.save(work / "tiered_tier3_again.json")
    return {
        "profile_before": [
            {"key": f.key, "value": f.value, "confidence": f.confidence}
            for f in store.profile()
        ],
        "profile_after": [
            {"key": f.key, "value": f.value, "confidence": f.confidence}
            for f in reloaded.profile()
        ],
        "profile_identical": store.profile() == reloaded.profile(),
        "snapshot_bytes_identical": path.read_bytes() == again.read_bytes(),
        "stats_before": store.stats(),
        "stats_after": reloaded.stats(),
    }


def _render(retrieval: Any) -> list[str]:
    rows = [f"T2:{s.text}" for s in retrieval.tier2_summaries]
    rows += [f"T3:{f.key}={f.value}" for f in retrieval.tier3_profile]
    rows += [f"T1:{t.role}:{t.content}" for t in retrieval.tier1_recent]
    return rows


# --------------------------------------------------------------------------
# M1
# --------------------------------------------------------------------------
def run_probes(work: Path, only: Sequence[str] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {"arms": {}}
    for arm, live_companion, live_memory in probes.arms():
        if only and arm not in only:
            continue
        started = time.perf_counter()
        gpu_before = gpu_snapshot() if (live_companion or live_memory) else {}
        result = probes.run_probe_arm(
            arm=arm,
            snapshot_dir=work / "snapshots" / arm,
            live_companion=live_companion,
            live_memory=live_memory,
        )
        summary = probes.summarize_arm(result)
        summary["wall_s"] = round(time.perf_counter() - started, 2)
        summary["gpu_before"] = gpu_before
        summary["gpu_after"] = gpu_snapshot() if (live_companion or live_memory) else {}
        out["arms"][arm] = summary
        (RESULTS / f"m1_{arm}_full.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
        )
    return out


# --------------------------------------------------------------------------
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument(
        "--rows",
        default="all",
        help="comma-separated subset of {probes,facts,world,persistence} or 'all'",
    )
    parser.add_argument("--probe-arms", default="", help="comma-separated probe arm ids")
    args = parser.parse_args(argv)
    wanted = (
        {"probes", "facts", "world", "persistence"}
        if args.rows == "all"
        else {r.strip() for r in args.rows.split(",") if r.strip()}
    )
    only_arms = tuple(a.strip() for a in args.probe_arms.split(",") if a.strip())

    RESULTS.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()

    if "facts" in wanted:
        payload = run_facts(args.work)
        payload["recorded_at_utc"] = stamp
        _write("m2_m3_m4_m8_facts.json", payload)
    if "consent" in wanted or "facts" in wanted:
        payload = {
            "recorded_at_utc": stamp,
            "consent_matrix": consent.consent_matrix(args.work / "consent"),
            "revocation_matrix": consent.revocation_matrix(args.work / "consent"),
        }
        _write("m4_m5_consent.json", payload)
    if "world" in wanted:
        payload = run_world(args.work)
        payload["recorded_at_utc"] = stamp
        _write("m6_m7_world.json", payload)
    if "persistence" in wanted:
        payload = run_persistence(args.work / "persistence")
        payload["recorded_at_utc"] = stamp
        _write("m7_tiered_persistence.json", payload)
    if "probes" in wanted:
        payload = run_probes(args.work, only=only_arms)
        payload["recorded_at_utc"] = stamp
        _write("m1_probes.json", payload)
    return 0


def _write(name: str, payload: dict[str, Any]) -> None:
    path = RESULTS / name
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    print(f"wrote {path}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
