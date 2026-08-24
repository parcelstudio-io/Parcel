"""M1 — the eight PERSONAL_CONVO_V1 families, with the H5 memory underneath.

THE THREE RECORDED BASELINES THIS IS MEASURED AGAINST
------------------------------------------------------
``evals/companion/personal_convo_v1/results/README.md``:

* 12/13 turns — fixture companion, recency window (day-one baseline)
* 13/13 turns — fixture companion, tiered memory, **deterministic** summarizer
* **3/13 turns** — live llama.cpp companion, tiered memory, **live** summarizer

The DESIGN's M1 asks for >= 13/13 "with a LIVE local summarizer+proposer". Three
arms are run so the number can be attributed rather than merely reported:

``A_fixture_deterministic``
    the stock runner, untouched. Reproduces the 13/13 row and proves the pack
    still behaves as its ledger says before anything of H5 is switched on.
``B_fixture_live_memory``
    fixture companion, **live** Tier-2 summarizer and a **live** Tier-3
    proposer through ``OwnerFactDistiller``. Everything above the memory is
    deterministic, so any delta from A is the local model's memory work and
    nothing else. This is the arm that answers "is the local model fit to
    summarize and distil".
``C_live_everything``
    live companion + live summarizer + live proposer. This is M1 as written,
    and it is also the arm that carries the recorded 3/13 confound: under the
    live companion the Tier-D bank scores free prose against word budgets and
    a conservative DialogueAct derivation.

WHAT H5 CHANGES INSIDE THE HARNESS
-----------------------------------
``run_personal_convo_v1._tiered_memory_window`` builds its ``TieredMemory`` with
``null_distiller`` — Tier 3 can never hold anything. This module replaces that
one function for the run with a version that (a) injects a real distiller, and
(b) **saves the store and retrieves from a freshly loaded copy**, so every probe
answer on arms B and C is served from persisted tiers rather than from the
process that wrote them. Nothing else about the pack is touched: the frozen
sha-pinned inputs, the scorers and the judge are the shipped ones, and
``pack_digest`` is reported so a reader can see the pack did not move.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.companion.personal_convo_v1 import run_personal_convo_v1 as runner
from evals.companion.personal_convo_v1.build_memory_fixture import MemoryGraph
from evals.companion.personal_convo_v1.fixture_provider import FixtureConversationProvider
from evals.companion.personal_convo_v1.live_provider import (
    LiveConversationProvider,
    LiveSummarizer,
    measure_summarizer_quality,
)
from parcel_robot.memory.tiered import TieredMemory, TieredMemoryConfig
from parcel_robot.owner_model.distiller import OwnerFactDistiller
from parcel_robot.providers import LlamaCppProvider

#: The GPU reasoner H2 owns. H5 uses it if ``/health`` answers.
REASONER_URL = "http://127.0.0.1:8081"
REASONER_MODEL = "gemma-4-26b-a4b"


def _h5_window_factory(
    distiller: Any, snapshot_dir: Path
) -> Callable[..., tuple[list[dict[str, str]], dict[str, Any]]]:
    """A replacement for the runner's private tiered-window builder.

    Same signature, same return shape. Two differences, both the point of the
    experiment: a real distiller instead of ``null_distiller``, and a
    save/reload round trip between the write and the read.
    """

    counter = {"n": 0}

    def build(
        graph: MemoryGraph,
        limit: int,
        *,
        summarizer: Callable[..., str] | None = None,
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        evidence = frozenset(event.content for event in graph.evidence)
        active = summarizer or runner.make_eval_summarizer(evidence)
        store = TieredMemory(
            summarizer=active,
            distiller=distiller,
            config=TieredMemoryConfig(tier1_max_turns=limit),
        )
        for event in graph.events:
            store.append(event.role, event.content, session_id=event.session or "default")

        counter["n"] += 1
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        path = store.save(snapshot_dir / f"{graph.graph_id}-{counter['n']}.json")
        reloaded = TieredMemory(
            summarizer=active,
            distiller=distiller,
            config=TieredMemoryConfig(tier1_max_turns=limit),
        )
        restored = reloaded.load(path)

        retrieval = reloaded.retrieve(graph.probe_query)
        window: list[dict[str, str]] = []
        summary_texts = [summary.text for summary in retrieval.tier2_summaries]
        for summary in retrieval.tier2_summaries:
            window.append({"role": "assistant", "content": summary.text})
        for fact in retrieval.tier3_profile:
            window.append(
                {
                    "role": "assistant",
                    "content": f"{fact.key.replace('_', ' ')}: {fact.value}",
                }
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
            "h5_snapshot_path": str(path),
            "h5_rows_restored": restored,
            "h5_tier3_keys": [fact.key for fact in reloaded.profile()],
        }
        if isinstance(active, LiveSummarizer):
            joined = " ".join(summary_texts) or active.last_summary
            meta["summarizer_quality"] = measure_summarizer_quality(
                summary_text=joined,
                used_fallback=active.used_fallback,
                call_count=active.call_count,
            )
        return window, meta

    return build


def run_probe_arm(
    *,
    arm: str,
    snapshot_dir: Path,
    live_companion: bool,
    live_memory: bool,
    base_url: str = REASONER_URL,
    model: str = REASONER_MODEL,
) -> dict[str, Any]:
    """One probe arm. Returns the runner's own result object, plus the arm id."""

    summarizer: Callable[..., str] | None = None
    provenance: dict[str, Any] = {
        "provider_kind": "live" if live_companion else "fixture",
        "base_url": base_url if (live_companion or live_memory) else "",
        "h5_arm": arm,
        "h5_live_memory": live_memory,
        "reference_note": "text tier: the transcript itself is the judged artifact",
    }

    if live_companion or live_memory:
        provenance["model"] = {"id": model}

    if live_companion:
        provider_model = LlamaCppProvider(
            base_url=base_url,
            model=model,
            timeout=120.0,
            streaming=True,
            temperature=0.25,
            top_p=0.9,
            max_tokens=384,
            enable_thinking=False,
        )
        respond = LiveConversationProvider(provider_model, retries=2).respond
        provider_id = model
    else:
        respond = FixtureConversationProvider().respond
        provider_id = FixtureConversationProvider.provider_id

    original = runner._build_memory_window
    if live_memory:
        summarizer = LiveSummarizer(
            base_url=base_url,
            model=model,
            timeout=120.0,
            max_chars=1200,
            temperature=0.2,
            top_p=0.9,
            max_tokens=512,
        )
        proposer_model = LlamaCppProvider(
            base_url=base_url,
            model=model,
            timeout=120.0,
            streaming=False,
            temperature=0.0,
            top_p=0.9,
            max_tokens=512,
            enable_thinking=False,
        )
        from parcel_robot.owner_model.distiller import LanguageModelFactProposer

        distiller = OwnerFactDistiller(proposer=LanguageModelFactProposer(model=proposer_model))
        runner._tiered_memory_window = _h5_window_factory(distiller, snapshot_dir)

    try:
        result = runner.run_pack(
            respond,
            provider_id=provider_id,
            provider_kind="live" if live_companion else "fixture",
            provenance=provenance,
            run_id=f"h5-{arm}-{datetime.now(timezone.utc):%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}",
            recorded_at_utc=datetime.now(timezone.utc).isoformat(),
            memory_backend="tiered",
            summarizer=summarizer,
        )
    finally:
        runner._build_memory_window = original
        runner._tiered_memory_window = _ORIGINAL_TIERED_WINDOW

    result["h5_arm"] = arm
    return result


_ORIGINAL_TIERED_WINDOW = runner._tiered_memory_window


def summarize_arm(result: dict[str, Any]) -> dict[str, Any]:
    """The few numbers M1 is about, out of the runner's large result object."""

    aggregate = result["aggregate"]
    failed_categories: dict[str, int] = {}
    for scenario in result["scenarios"]:
        for turn in scenario["turns"]:
            for category in turn["failed_categories"]:
                failed_categories[category] = failed_categories.get(category, 0) + 1
    return {
        "arm": result.get("h5_arm", ""),
        "turns_passed": aggregate["turns_passed"],
        "turn_count": aggregate["turn_count"],
        "families_passing": aggregate["families_passing"],
        "families_recency_window_blocked": aggregate["families_recency_window_blocked"],
        "families_failing": aggregate["families_failing"],
        "family_status": result["family_status"],
        "failed_check_categories": failed_categories,
        "pack_digest": result["pack_digest"],
        "judge_calibration": result["judge"]["calibration"]["status"],
        "summarizer_quality": result.get("summarizer_quality"),
    }


def arms() -> Sequence[tuple[str, bool, bool]]:
    """``(arm id, live companion, live memory)`` — fixed before the first run."""

    return (
        ("A_fixture_deterministic", False, False),
        ("B_fixture_live_memory", False, True),
        ("C_live_everything", True, True),
    )


__all__ = ["REASONER_MODEL", "REASONER_URL", "arms", "run_probe_arm", "summarize_arm"]
