"""Regenerate ``corpus.manifest.json``. Offline, no credential, no network.

WHY THIS PACK IS NOT FROZEN
---------------------------
``tests/test_ci_gate.py`` scans ``evals/`` for manifests carrying
``"frozen": true`` and pins that exact set, so that freezing a suite is always
a deliberate, reviewed act rather than a side effect. This corpus has **three
hand-authored seed fixtures and no captured threads** — the live scrape is
blocked on account credit — so freezing it now would immortalise a placeholder.
:data:`FROZEN_NOTE` says so inside the manifest itself, and
:func:`build_manifest` will not emit a ``frozen`` key at all.

Freezing is a later owner decision, taken after a real scrape lands.

USAGE
-----
Run as a module from the repository root, so that ``evals`` imports::

    .parcel/bin/python -m evals.companion.realtime_convo_v1.build_manifest [FLAG]

``--check``              recompute and diff against the committed manifest
``--print-si-digests``   the block to paste into ``prompting.SI_DIGESTS``
(no flag)                rewrite the manifest in place
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.companion.realtime_convo_v1.schema import (
    FIXTURES_DIR,
    MANIFEST_PATH,
    REPO_ROOT,
    SCENARIOS_PATH,
    SCHEMA_VERSION,
    SCRAPE_MODEL,
    SUITE_ID,
    load_fixtures,
    load_scenarios,
    sha256_file,
    sum_usage,
)
from evals.companion.realtime_convo_v1.scrape_realtime_convo import BUDGET_CEILING_USD
from parcel_robot.realtime.prompting import (
    DI_VERSION,
    SI_VERSION,
    default_prompt_library,
    render_system_instruction,
)

RUNNER_VERSION = "realtime-convo-scrape-v1"

#: How to invoke this file. ``python path/to/build_manifest.py`` puts the pack
#: directory on ``sys.path`` instead of the repository root, so ``evals`` never
#: imports; ``-m`` from the repo root is the only supported form.
MODULE_PATH = "evals.companion.realtime_convo_v1.build_manifest"

FROZEN_NOTE = (
    "Deliberately NOT frozen. The live capture landed 2026-08-18 (25/25 threads), "
    "but human review of corpus quality has not happened and the manifest says "
    "human_review_required. Freezing is an owner decision taken after that "
    "review; when taken, add the manifest to DIGEST_SENTINELS in "
    "scripts/ci_gate.py in the same commit."
)

#: The one honest record of whether the corpus was ever captured live.
SCRAPE_STATE: dict[str, Any] = {
    "status": "captured",
    "model": SCRAPE_MODEL,
    # A DATE, not a timestamp — same rule as the blocked record this replaces.
    "checked_utc_date": "2026-08-18",
    "card_date_local": "2026-08-17",
    "threads_requested": 25,
    "threads_captured": 25,
    # From the scraper's own final line ("measured spend $0.50"), which sums
    # the provider's usage blocks — measured, not the $0.60 operator estimate.
    "measured_spend_usd": 0.50,
    "note": (
        "Captured live 2026-08-18 UTC after account credit landed (third key), on the SECOND full run. The first full run was silently damaged: rate limiting closed 103/174 responses as status=failed with zero usage, and the scraper trusted response.done without checking status. Fixed with status verification + bounded retry (RESPONSE_ATTEMPTS/RETRY_BACKOFF_S); the second run captured 174/174 turns non-empty. Day spend across all attempts about $0.79. "
        "The first attempt failed on a session.update shape the GA API refuses "
        "(missing session.type; turn_detection moved under audio.input) — fixed "
        "from wire evidence, then 25/25 threads captured in one run. The 3 "
        "hand-authored seed fixtures shared thread ids with real scenarios and "
        "were OVERWRITTEN by live captures; the replay pipeline they proved is "
        "now exercised by real model output instead. Prior blocked record: "
        "429 credit_balance_exhausted, 2026-08-18 UTC, zero sockets opened."
    ),
}


def locked_files() -> list[dict[str, str]]:
    """Scenario file + every fixture, sorted, repo-relative."""

    paths = [SCENARIOS_PATH, *sorted(Path(FIXTURES_DIR).glob("*.json"))]
    return [
        {"path": path.relative_to(REPO_ROOT).as_posix(), "sha256": sha256_file(path)}
        for path in paths
    ]


def si_digests() -> dict[str, str]:
    library = default_prompt_library()
    return {
        profile.id: render_system_instruction(profile_id=profile.id, library=library).digest
        for profile in sorted(library.list_personalities(), key=lambda item: item.id)
    }


def build_manifest() -> dict[str, Any]:
    scenarios = load_scenarios()
    fixtures = load_fixtures()
    sources: dict[str, int] = {}
    for fixture in fixtures:
        sources[fixture.source] = sources.get(fixture.source, 0) + 1
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "runner_version": RUNNER_VERSION,
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozen_note": FROZEN_NOTE,
        "model": SCRAPE_MODEL,
        "si_version": SI_VERSION,
        "di_version": DI_VERSION,
        "si_digests": si_digests(),
        "scrape": dict(SCRAPE_STATE),
        "scenario_count": len(scenarios),
        "scenario_families": {
            family: sum(1 for s in scenarios if s.family == family)
            for family in sorted({s.family for s in scenarios})
        },
        "owner_turn_count": sum(s.turn_count for s in scenarios),
        "fixture_count": len(fixtures),
        "fixture_sources": dict(sorted(sources.items())),
        "usage_totals": sum_usage(fixtures),
        "budget_ceiling_usd": BUDGET_CEILING_USD,
        "human_review_required": True,
        "requires_audio": False,
        "requires_model_server": False,
        "locked_files": locked_files(),
    }
    if "frozen" in manifest:  # pragma: no cover - structural guard
        raise RuntimeError("this pack must never emit a frozen flag")
    return manifest


#: Fields a ``--check`` compares. ``generated_at_utc`` is excluded because
#: regenerating a manifest must not be able to *fail* on the clock.
CHECKED_FIELDS = (
    "schema_version",
    "suite_id",
    "runner_version",
    "model",
    "si_version",
    "di_version",
    "si_digests",
    "scenario_count",
    "scenario_families",
    "owner_turn_count",
    "fixture_count",
    "fixture_sources",
    "usage_totals",
    "budget_ceiling_usd",
    "locked_files",
)


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def diff_manifest(path: Path = MANIFEST_PATH) -> list[str]:
    """Field names where the committed manifest and the tree disagree."""

    committed = load_manifest(path)
    fresh = build_manifest()
    return [field for field in CHECKED_FIELDS if committed.get(field) != fresh.get(field)]


def write_manifest(path: Path = MANIFEST_PATH) -> Path:
    payload = build_manifest()
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return Path(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="regenerate the corpus manifest")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--print-si-digests", action="store_true")
    args = parser.parse_args(argv)

    if args.print_si_digests:
        print(f'    "{SI_VERSION}": {{')
        for profile_id, digest in si_digests().items():
            print(f'        "{profile_id}": "{digest}",')
        print("    },")
        return 0

    if args.check:
        drift = diff_manifest()
        if drift:
            print(f"manifest is stale in: {', '.join(drift)}")
            print(f"regenerate with: python -m {MODULE_PATH}")
            return 1
        print("manifest matches the tree")
        return 0

    path = write_manifest()
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
