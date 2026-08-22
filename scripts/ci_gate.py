#!/usr/bin/env python
"""Parcel CI / eval-runner gate — the per-commit + nightly promotion gate.

Why this exists
---------------
The independent verdict (``scrum/20260808/task_1/INDEPENDENT_VERDICT_FABLE.md``)
and the productionization audit (``scrum/20260809/task_1``) identified a
historical load-bearing hole: rich eval harnesses existed without an executable
runner or a versioned workflow. This module closes the runner half of that gap;
``.github/workflows/ci.yml`` now declares the hosted cadence, although hosted
execution remains unverified until a GitHub run is recorded. This module does
**not** invent new evals; it *wraps the harnesses that already exist* and turns
the aspirational promotion gates into an executable, exit-coded gate.

What it enforces (tiered by cost)
---------------------------------
``--tier commit`` (fast, offline, deterministic — no network, no model server).
Since card P0-E (``scrum/20260822/task_5``, owner directive: prototype, loosen
production fail-safe process) the commit tier is the SAFETY CORE plus the cheap
truth checks:
  * the default gate ``pytest -m "not slow"`` (latest recorded local run:
    7,970 passed on 2026-08-22);
  * ``ruff`` — ratcheted against a pinned baseline so pre-existing debt in
    modules this card does not own cannot block a commit, while any *new*
    violation reddens (see ``scripts/ci_ruff_baseline.json``);
  * HARD-SAFETY — zero hard collisions on every product artifact and no new
    false_arrival, read from the existing harness ledgers;
  * RELEASE-PARITY — every packaged runtime asset byte-identical to its
    canonical source (this caught a shipped ``max_vx`` drift once);
  * MODEL-OFF NON-INFERIORITY — the SigLIP / OWLv2(B3) / memory flag-off
    byte-equal cells, wired into one gate so Design A cannot silently rot;
  * OWNER-STORE ISOLATION (card R27) — the owner's sqlite is unreachable from
    a test;
  * ASSERTION-EVALS (card EV-1, ``scrum/20260820/task_11``) — the eleven
    programmatic session assertions over a frozen fixture set, the harness
    self-test (a null / always-claims-success / random-tool agent must FAIL
    every suite and a clean control must PASS), pass^k on the e-stop (k=1 here,
    k=3 nightly), and the pinned findings of any committed run folder that is
    present. Logic lives in ``evals/assertions/gate.py``; this file stays the
    register of WHICH gates exist;
  * TIER-COVERAGE (card R26) — no test is orphaned from both tiers.

``--tier nightly`` (slow, scheduled): everything above, plus the EVIDENCE
  RATCHETS that card P0-E moved out of the commit tier — they protect claims,
  not the robot, and reddened on doc edits and scene retunes:
  * the frozen-digest integrity tests (nav_instruct v3, embodied plan,
    conversation_quality, personal_convo) — a sha drift reddens — plus an
    independent sentinel sha over the immutable frozen manifests;
  * the mutation-panel freshness guard;
  * LATENCY-TAIL — the committed p95/p99 percentile pins and the latency
    ledger ratchet; the follow-bench jerk ratchet;
  * the held-out-scene prose scan and the retired-literal AST ratchet (marked
    ``slow`` in their test modules);
  and the slow suite (live-sim e2e + acoustic rig via ``-m slow``), the
  nav_instruct minival candidate run, every registered mutation-panel case
  (latest recorded: 7/7), and the metamorphic suite. Numeric eval outputs are
  reported unless their row is explicitly hard: candidate collisions and
  mutation survivors gate, while the candidate differential row (including
  candidate false-arrival) reports. The frozen baseline's
  no-new-false-arrival invariant remains hard separately.

Any hard gate red ==> non-zero exit. Report-only gates never change the exit
code; they are printed so a human sees the trend.

Self-test
---------
``tests/test_ci_gate.py`` seeds a regression into each hard gate's input (a
byte-changed frozen digest, an injected collision, a new false_arrival, a
latency-tail spike, a flag-off drift) and asserts the gate reddens — the same
"would the harness notice if it were wrong?" discipline as the mutation panel.

Usage::

    .parcel/bin/python scripts/ci_gate.py --tier commit
    .parcel/bin/python scripts/ci_gate.py --tier nightly
    .parcel/bin/python scripts/ci_gate.py --tier commit --json
    .parcel/bin/python scripts/ci_gate.py --update-ruff-baseline   # re-pin debt
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PYTHON = sys.executable

# ---------------------------------------------------------------------------
# Wiring: node-id selections over the EXISTING harnesses (never new evals).
# Every id here was confirmed to collect on 2026-08-09.
# ---------------------------------------------------------------------------

#: (a) MODEL-OFF NON-INFERIORITY — the flag-off byte-equal cells the SigLIP,
#: OWLv2(B3) and tiered-memory lanes already wrote, gathered into one gate.
MODEL_OFF_NODE_IDS: tuple[str, ...] = (
    # SigLIP-2 (PARCEL_SIGLIP2_ONNX, default off): fallback == pre-neural oracle
    "tests/test_siglip_real_embeddings.py::test_weights_absent_match_is_byte_identical_to_pre_neural_stub",
    "tests/test_siglip_real_embeddings.py::test_onnx_path_is_opt_in_even_when_weights_present",
    # OWLv2 / B3 (PARCEL_OWLV2_ONNX, default off): detector-off is additive
    "tests/test_owlv2_detector.py::test_default_is_detector_unavailable",
    "tests/test_owlv2_detector.py::test_missing_weights_returns_none",
    "tests/test_owlv2_detector.py::test_eval_reports_skipped_when_disabled",
    # B3 seg-truth foundation: GT/clean detections are byte-identical + no chain
    "tests/test_cam_foundation.py::test_frozen_gt_source_artifacts_are_byte_identical",
    "tests/test_cam_foundation.py::test_tier_does_not_install_a_perception_chain",
    # Cross-session / tiered memory: off by default changes nothing
    "tests/test_tiered_memory.py::test_prompting_memory_is_off_by_default_and_fails_closed_on_unknown_keys",
    "tests/test_tiered_memory.py::test_read_path_is_deterministic",
    "tests/test_tiered_memory.py::test_retrieve_never_invokes_summarizer_or_distiller",
)

#: Frozen-digest integrity — a sha drift on a frozen pack reddens.
FROZEN_DIGEST_NODE_IDS: tuple[str, ...] = (
    "tests/test_nav_instruct_episodes_v3.py::test_checked_in_v3_files_equal_a_fresh_generation",
    "tests/test_nav_instruct_episodes_v3.py::test_v3_manifest_records_the_correction_it_carries",
    "tests/test_nav_instruct_episodes_v3.py::test_frozen_ledger_prefix_is_byte_identical_after_the_v3_append",
    "tests/test_embodied_plan_eval.py::test_manifest_hash_locks_every_physical_input_and_unique_seed",
    "tests/test_conversation_quality_v1.py::test_manifest_locks_all_conversation_inputs",
    "tests/test_personal_convo_v1.py::test_manifest_locks_all_inputs_and_covers_every_family",
)

#: Release parity — packaged runtime_assets vs canonical source (N27).
#: Not listed here: tests/test_release_parity_wheel.py. Targeted node-id gates
#: run with no ``-m`` filter, so naming a slow test here would execute a wheel
#: build in the offline, 20-minute-bounded commit tier.
RELEASE_PARITY_NODE_IDS: tuple[str, ...] = (
    "tests/test_release_parity.py::test_manifest_covers_every_packaged_file",
    "tests/test_release_parity.py::test_manifest_asset_count_is_the_pinned_literal",
    "tests/test_release_parity.py::test_every_manifest_digest_matches_the_packaged_bytes",
    "tests/test_release_parity.py::test_every_mirrored_asset_is_byte_identical_to_its_source",
    "tests/test_release_parity.py::test_side_mirror_robot_yaml_is_byte_identical",
    "tests/test_release_parity.py::test_generator_reports_no_drift",
    "tests/test_release_parity.py::test_generator_is_idempotent_and_zero_diff",
    "tests/test_release_parity.py::test_ship_set_excludes_dev_only_and_ground_truth",
    "tests/test_release_parity.py::test_every_default_asset_resolves_under_the_packaged_root",
    "tests/test_release_parity.py::test_effective_config_is_equal_under_source_and_packaged_roots",
)

#: Card R26. THE MARKER EXPRESSIONS THAT DEFINE THE TIERS. These are constants
#: and not string literals at the call sites for one reason: the
#: ``tier-coverage`` gate below reads THESE, so an edit that narrows what the
#: nightly runs ("slow and not e2e", say) is compared against what the commit
#: tier deselects and reddens, instead of quietly deleting a tier.
#:
#: The full audit's finding was that the 42 tests the commit tier deselects —
#: the entire voice-to-nav e2e tier among them — had never been run by anything.
#: A tier nobody runs is not a tier; it is a directory.
COMMIT_MARKERS = "not slow"
NIGHTLY_SLOW_MARKERS = "slow"

#: Card R27 — THE OWNER'S CONVERSATION STORE IS NOT REACHABLE FROM A TEST.
#:
#: Pinned as explicit node ids, and that is the whole point of the entry rather
#: than a stylistic choice. These tests already run inside ``default-suite``, so
#: as a *behaviour* gate this is a duplicate; as a *deletion* gate it is not.
#: Deleting ``tests/test_owner_store_isolation.py`` makes ``default-suite``
#: quietly smaller and still green, while a named selection **errors** — which
#: is the difference between a guard and a guard nobody can remove.
#:
#: The trigger: 256 synthetic rows in the owner's real ``parcel_memory.sqlite3``
#: written by four consecutive card-chains, one of whose vectors
#: (``test_shipped_config_still_launches``) shipped in this repo and ran on
#: every commit gate. See ``scrum/20260821/task_9/R27_STATUS.md``.
OWNER_STORE_NODE_IDS: tuple[str, ...] = (
    "tests/test_owner_store_isolation.py::test_a_repo_root_in_process_runtime_cannot_reach_the_owner_store",
    "tests/test_owner_store_isolation.py::test_no_shipped_config_can_be_launched_onto_the_owner_store",
    "tests/test_owner_store_isolation.py::test_a_test_process_cannot_declare_itself_the_owner",
    "tests/test_owner_store_isolation.py::test_no_harness_names_the_owner_store_outside_the_allowlist",
    "tests/test_owner_store_isolation.py::test_quarantine_defaults_to_dry_run_and_never_deletes",
    "tests/test_owner_store_isolation.py::test_quarantine_apply_is_refused_against_the_owner_store",
)

#: The mutation panel's anti-rot guards (both fast enough for the commit tier).
#: The first reads the committed payload; the second re-derives its
#: safety-relevant fields from a LIVE clean run, because a committed payload
#: alone cannot tell you whether it is still true (lane E7, 2026-08-10).
MUTATION_FRESHNESS_NODE_IDS: tuple[str, ...] = (
    "tests/test_mutation_panel_freshness.py::test_committed_mutation_panel_is_on_the_current_frozen_set",
    "tests/test_mutation_panel_freshness.py::test_committed_panel_safety_fields_still_reproduce",
)

#: (b) LATENCY-TAIL — the committed p95/p99 percentile pins that exist today
#: (observability component percentiles + the beat-sync scheduling budget).
LATENCY_TAIL_NODE_IDS: tuple[str, ...] = (
    "tests/test_beat_sync.py::test_nods_land_on_accents_within_the_perceptual_budget",
    "tests/test_beat_sync.py::test_control_rate_cannot_meet_the_apex_budget",
    "tests/test_observability_planning.py",
)

#: Independent frozen-digest sentinels: a byte over any of these immutable
#: manifests moves the sha. Kept to files that are committed-clean and frozen by
#: policy (never concurrently edited), so the gate is deterministic. The
#: authoritative recompute-vs-manifest coverage is the pytest ids above; this
#: sentinel is what the self-test seeds to prove the gate is not theatre.
#:
#: EVERY manifest carrying ``"frozen": true`` belongs here. ``personal_convo_v1``
#: was NOT pinned during task_15 and that is exactly why a green gate missed its
#: pack_digest moving under card M-A (Fable audit ``AUDIT_FABLE_INDEPENDENT.md``,
#: BLOCKING 2). Adding a frozen suite without adding it here re-opens that hole,
#: so ``tests/test_ci_gate.py`` pins the set of frozen-but-unpinned manifests and
#: seeds each pin here individually to prove it reddens.
#:
#: Re-pin log — one entry per authorized movement, because a sentinel that moves
#: without a reason is a sentinel nobody trusts:
#:
#: * ``embodied_plan_v1/manifest.json`` ``33c662c8…`` -> ``22736f6e…``,
#:   2026-08-10, lane E5, EXPLICIT OWNER AUTHORIZATION ("1. person clearance.
#:   Implement your recommendation"). **Nothing about the eval changed.** The
#:   manifest SHA-locks ``configs/robot.yaml`` as an input, that file was retuned
#:   (``safety.person_stop_m`` 1.0 -> 1.2, ``person_slow_m`` 2.0 -> 2.5,
#:   ``owner_follow.owner_keepout_m`` 1.55 -> 1.75), so the lock had to be
#:   refreshed ``f6468887…`` -> ``aff69113…`` and the manifest's own sha moved
#:   MECHANICALLY with it. The suite's BEHAVIOUR is unmoved and was re-measured
#:   against a scratch copy of the manifest BEFORE the committed file was
#:   touched: 997 simulator steps, 0 collisions, 0 timeouts, minimum clearance
#:   0.883147 m, per-case 200/260/64/389/84 — bit-identical to the frozen row.
#:   Only the one ``robot_config`` sha string changed in the file; every other
#:   locked input and every byte of layout is untouched. Full 2x2 attribution in
#:   ``scrum/20260809/task_15/E5_PERSON_CLEARANCE_STATUS.md``.
#:
#: * ``embodied_plan_v1/manifest.json`` ``1725a246…`` -> ``88fa9fb5…``,
#:   2026-08-20, card R14 (``scrum/20260820/task_3``), whose work item 2
#:   instructs the packaged/digest-pinned scene change and whose DoD requires
#:   this gate green after it. The owner's explicit 2026-08-20 instruction to
#:   commit and upload the audited full wave authorizes this mechanical re-pin;
#:   the authorization is recorded in ``R14_STATUS.md``.
#:   **Nothing about the eval changed.** Identical in kind to the 2026-08-10
#:   entry above: this manifest SHA-locks
#:   ``src/parcel_robot/scenes/city_block.xml`` as ``locked_inputs.city_scene``,
#:   R14 added the block's first portal to that scene (one ``door_1`` leaf geom
#:   plus two unclassified entry-wall stubs at the north sidewalk's west end),
#:   so the lock had to be refreshed ``bbb4d6e7…`` -> ``bb7f8e02…`` and the
#:   manifest's own sha moved MECHANICALLY with it. Only that one sha string
#:   differs; every other locked input and every byte of layout is untouched.
#:   The suite's BEHAVIOUR is unmoved and was re-measured against a scratch copy
#:   of the manifest BEFORE the committed file was touched: 997 simulator steps,
#:   0 collisions, 0 timeouts, minimum clearance 0.883147 m, per-case
#:   200/260/64/389/84, 4 passed / 1 unsupported — bit-identical to the frozen
#:   row, and to the row the 2026-08-20T16:06Z pre-change gate had just proved.
#:   It is unmoved for a reason and not by luck: the leaf stands at the block's
#:   west end and no case's route, goal or frustum reaches it. Attribution in
#:   ``scrum/20260820/task_3/R14_STATUS.md`` §4.
#:
#: * ``embodied_plan_v1/manifest.json`` ``88fa9fb5…`` -> ``d251f781…``,
#:   2026-08-21, card W-1 (``scrum/20260821/task_10``), whose work item 1
#:   instructs the digest-pinned scene change and whose DoD requires this gate
#:   green after it, executing the owner's standing world-simulator decision
#:   ("texture the city now", recorded in ``AUDIT_OVERNIGHT_FABLE.md``).
#:   **Nothing about the eval changed.** Identical in kind to the two entries
#:   above: this manifest SHA-locks ``src/parcel_robot/scenes/city_block.xml``
#:   as ``locked_inputs.city_scene``, W-1 gave that scene photo textures, six
#:   storefront quads, four awnings and nine human visual meshes, so the lock
#:   had to be refreshed ``bb7f8e02…`` -> ``38d71b66…`` and the manifest's own
#:   sha moved MECHANICALLY with it. Only that one sha string differs; every
#:   other locked input and every byte of layout is untouched. The suite's
#:   BEHAVIOUR is unmoved and was re-measured against a scratch copy of the
#:   manifest BEFORE the committed file was touched: 997 simulator steps, 0
#:   collisions, 0 timeouts, minimum clearance 0.883147 m, per-case
#:   200/260/64/389/84, 4 passed / 1 unsupported — bit-identical to the frozen
#:   row. It is unmoved for a reason and not by luck: W-1 changed **no**
#:   physics. Every pre-existing geom keeps its name/type/size/pos/quat/
#:   friction/contact flags, every added geom is ``vis_*`` with
#:   ``contype=0 conaffinity=0 density=0``, and the equivalence is MEASURED —
#:   141 dynamics arrays byte-equal, the same 68 colliding geoms in the same
#:   order, and a 3,000-step rollout over 31,290 contacts with
#:   ``max |Δqpos| = 0.0``. Attribution in
#:   ``scrum/20260821/task_10/W1_STATUS.md`` §4.
#:
#: * ``embodied_plan_v1/manifest.json`` ``d251f781…`` -> ``d1bb1a8d…``,
#:   2026-08-21 (evening), incident restoration
#:   (``scrum/20260821/AUDIT_W1_INCIDENT_FABLE.md``), EXPLICIT OWNER
#:   AUTHORIZATION ("Re-pin.", 2026-08-21). **Nothing about the eval OR the
#:   scene's certified properties changed.** During the chain collision an
#:   uncertified executor added three decoy blocks to
#:   ``src/parcel_robot/scenes/city_block.xml``; the restoration removed them
#:   surgically, leaving whitespace seams, so the restored file is
#:   PROPERTY-IDENTICAL to W-1's certified scene but not byte-identical
#:   (``38d71b66…`` -> ``e89f4f12…``; W-1's exact bytes are unrecoverable —
#:   its build tooling wrote them outside any transcript). The equivalence is
#:   MEASURED, not asserted: all 31 W-1 property pins green after restore
#:   (asset digests, physics byte-equivalence of the 141 dynamics arrays,
#:   held-out isolation, zero decoy or held-out-scene references), and the
#:   suite's BEHAVIOUR was re-measured against a scratch copy of this manifest
#:   BEFORE the committed file was touched: 997 simulator steps, 0 collisions,
#:   0 timeouts, minimum clearance 0.883147 m, per-case min/median/max
#:   64/200/389 summing 997, 4 passed / 1 unsupported — bit-identical to the
#:   frozen row. Only the one ``city_scene`` sha string differs in the
#:   manifest; ``scene_truth.json``'s one ``scene.sha256`` line moved with it.
#:
#: * ``nav_instruct/episodes/v4/manifest.json`` **ADDED** (not moved) as
#:   ``b2945444…``, 2026-08-11, lane E8, EXPLICIT OWNER AUTHORIZATION (re-freeze
#:   the episodes to v4 so the follow goal radii match the retuned stand-off,
#:   keeping the pedestrian-clearance gain). **v3's pin and v3's bytes are
#:   UNCHANGED** — v3 stays frozen, so every historical row measured against it
#:   keeps meaning what it meant. v4 is a new frozen set carrying exactly one
#:   correction: the ``follow_owner`` goal radius stops being the literal 1.8 m
#:   and becomes ``(desired_distance_m + distance_deadband_m) +
#:   OWNER_STAND_OFF_MARGIN_M`` = 2.13 m, derived from the same authority terms
#:   the follow controller obeys. It is pinned here for the reason the others
#:   are: it is now the newest frozen set (``mutation_panel.py`` and the
#:   frozen-baseline ledger row both moved onto it), so a byte of it moving must
#:   be loud. Only the five ``follow_owner`` episodes' ``goal.radius_m`` and the
#:   ``shortest_path_m`` computed from it differ from v3; the robot's own arrival
#:   claims are byte-identical across the two sets. 2x2 attribution and the
#:   per-episode bridge: ``scrum/20260809/task_15/E8_V4_REFREEZE_STATUS.md``,
#:   ``evals/nav_instruct/bridge_v3_v4.py``.
DIGEST_SENTINELS: dict[str, str] = {
    "evals/nav_instruct/episodes/v3/manifest.json": "eb1289e9723e008336b33bff83f2e4c9a91e07d1e6552866f6ede52da7f57858",
    "evals/nav_instruct/episodes/v4/manifest.json": "b29454443e93b68d238c11d31298e81c2e9cae89d7669d9d6556405e9b7388ec",
    # Re-pinned 2026-08-16 (owner-authorized): the only locked input that moved
    # is configs/robot.yaml, whose speech.endpointing flipped energy->semantic.
    # No eval OUTPUT moved — this suite never constructs a MicrophoneVoiceLoop,
    # and acoustic_loop_v1 builds its endpointer from hardcoded model paths
    # rather than from robot.yaml, so its ep50/ep90 rows are untouched too.
    # Previous pin: 22736f6e0e4b106c0d130b9f7f425feca465a73b20da1431dfd5e2e3b1ce9389
    # Re-pinned 2026-08-20 (card R14): the only locked input that moved is
    # src/parcel_robot/scenes/city_block.xml, which gained the block's first
    # portal. No eval OUTPUT moved — 997/0/0/0.883147 and the per-case row are
    # bit-identical, measured on a scratch manifest before this line changed.
    # Previous pin: 1725a246dd00de63e8574d401927ba206fd48424221d98cffca40c22f721d470
    # Re-pinned 2026-08-21 (card W-1): the only locked input that moved is
    # src/parcel_robot/scenes/city_block.xml, which gained photo textures,
    # storefront/awning quads and human visual meshes. No eval OUTPUT moved —
    # 997/0/0/0.883147 and the per-case 200/260/64/389/84 row are bit-identical,
    # measured on a scratch manifest while this file was still at HEAD. The
    # scene's PHYSICS is byte-equivalent by direct measurement, not by
    # assertion: 141 dynamics arrays equal, the same 68 colliding geoms with the
    # same names, and a 3,000-step / 31,290-contact rollout with max |dqpos|=0.
    # Previous pin: 88fa9fb581d0714e725841340475eafad5ac9f8e1195c055d8e368dd7e2b02e9
    # Re-pinned 2026-08-21 evening (incident restoration, owner-authorized
    # "Re-pin."): the only locked input that moved is
    # src/parcel_robot/scenes/city_block.xml, restored after the chain
    # collision — property-identical to W-1's certified scene (31/31 pins),
    # byte-different only by whitespace seams where uncertified decoy blocks
    # were removed. No eval OUTPUT moved — 997/0/0/0.883147 and 4 passed /
    # 1 unsupported, measured on a scratch manifest before this line changed.
    # Previous pin: d251f781421e33e7b96c2e34730075d3bf4c241264fea66fdaaa4fc4fa2004b7
    "evals/companion/embodied_plan_v1/manifest.json": "d1bb1a8daed637b1620be992d5373dd67d907954b3fc73d0c08c14863519fbcb",
    "evals/companion/personal_convo_v1/manifest.json": "d338f3352cd9597aeb9977f75c139d926bdfba1fe1d6b036b9a3ace08a1cf114",
}

# ---------------------------------------------------------------------------
# (c) HARD-SAFETY — product-path artifacts and their pinned invariants.
# ---------------------------------------------------------------------------
NAV_LEDGER = REPO / "evals" / "nav_instruct" / "results" / "ledger.jsonl"
MUTATION_PANEL_JSON = REPO / "evals" / "nav_instruct" / "results" / "mutation_panel.json"
FOLLOWBENCH_LEDGER = REPO / "evals" / "companion_nav" / "results" / "ledger.jsonl"
WALK_WITH_ME_LEDGER = REPO / "evals" / "walk_with_me" / "results" / "ledger.jsonl"

#: The frozen baseline is collision-free with zero false arrivals; that is the
#: Design-A/product guarantee. Any increase is a new hazard.
PINNED_FROZEN_FALSE_ARRIVAL = 0

RUFF_BASELINE = REPO / "scripts" / "ci_ruff_baseline.json"

# Release-parity record generated by tools/sync_runtime_assets.py. One
# direction only: repo-root configs/prompts/maps/fixtures are canonical and
# runtime_assets/ is a build product. MANIFEST.json is the single file exempt
# from the completeness walk — a file cannot carry its own hash.
RELEASE_PARITY_MANIFEST = REPO / "src" / "parcel_robot" / "runtime_assets" / "MANIFEST.json"

#: Persisted product latency ledger + pinned p95/p99 baseline (N19 / C-A).
#: The percentile-pin pytest selection (``LATENCY_TAIL_NODE_IDS``) stays; this
#: is the ledger source the ratchet reads once enough rows exist.
LATENCY_LEDGER = REPO / "evals" / "latency" / "ledger.jsonl"
LATENCY_BASELINE = REPO / "evals" / "latency" / "baseline.json"

#: Latency-tail ratchet tolerance against the pinned baseline. 1.20 mirrors the
#: BARN controller-p99 ratio ceiling already in the repo.
LATENCY_TAIL_MARGIN = 1.20

#: Card J-C. Follow-bench comfort ratchet: the committed jerk baseline with its
#: three-component attribution (60ecea2 terminal-approach floor, 6bd945d P0-A
#: instant-zero, E6 dynamics x instant-zero). Deliberately reuses
#: LATENCY_TAIL_MARGIN by REFERENCE rather than introducing a second ratchet
#: tolerance — one repo-wide ratchet margin.
FOLLOWBENCH_JERK_BASELINE = REPO / "evals" / "companion_nav" / "results" / "jerk_baseline.json"
FOLLOWBENCH_JERK_FIELD = "mean_rms_commanded_jerk_mps3"


# ---------------------------------------------------------------------------
# Gate result model
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    """One gate and its verdict.

    ``status`` is one of ``pass`` / ``fail`` / ``error`` / ``skip`` / ``report``.
    A run's exit code is non-zero iff some ``hard`` gate is ``fail`` or ``error``.
    ``report`` gates (``hard=False``) are printed but never change the exit code.
    """

    name: str
    tier: str
    hard: bool
    status: str
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_red(self) -> bool:
        return self.status in {"fail", "error"}

    @property
    def gating_red(self) -> bool:
        return self.hard and self.is_red

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


_ICON = {
    "pass": "PASS",
    "fail": "FAIL",
    "error": "ERROR",
    "skip": "skip",
    "report": "report",
}


# ---------------------------------------------------------------------------
# Small IO helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


#: Card R26. Credential variables scrubbed from the OFFLINE tiers' subprocesses.
#:
#: Found by the first recorded nightly, 2026-08-21. The nightly has to load a
#: credential for EV-1's judge stage, and with one in the environment
#: ``tests/test_realtime_lane.py::test_flag_on_constructs_the_lane_and_wires_it
#: _to_the_restricted_ingress`` flipped from green to red — deterministically,
#: because ``RobotRuntime._realtime_transport_factory`` builds a live transport
#: whenever the key is non-empty, so the lane armed instead of refusing with
#: ``no_transport``. That test is fixed to state its own premise, but the class
#: is the point: this file documents the commit tier as "fast, offline,
#: deterministic", and a tier whose result depends on what the operator happens
#: to have exported in their shell is none of those things.
#:
#: The scrub is SKIPPED when ``PARCEL_REALTIME_LIVE=1`` — that is the explicit
#: opt-in for the two live-provider cells, and silently starving them of a key
#: would turn a deliberate live run into a silent skip.
CREDENTIAL_ENV_VARS: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "PARCEL_REALTIME_KEY_ENV",
)
LIVE_OPT_IN_ENV = "PARCEL_REALTIME_LIVE"


def _base_env() -> dict[str, str]:
    env = dict(os.environ)
    # MuJoCo runs headless offscreen; egl matches how the default gate is run
    # here. No network, no display, no model server needed for the commit tier.
    env.setdefault("MUJOCO_GL", "egl")
    env.setdefault("PYTHONUNBUFFERED", "1")
    if env.get(LIVE_OPT_IN_ENV, "").strip() != "1":
        # Also scrub whatever PARCEL_REALTIME_KEY_ENV was pointing at, or the
        # indirection would carry a credential straight past this list.
        indirect = (env.get("PARCEL_REALTIME_KEY_ENV") or "").strip()
        for name in (*CREDENTIAL_ENV_VARS, indirect):
            if name:
                env.pop(name, None)
    return env


# ---------------------------------------------------------------------------
# Pytest driver
# ---------------------------------------------------------------------------


def run_pytest(
    selection: list[str] | tuple[str, ...],
    *,
    markers: str | None = None,
    env_extra: dict[str, str] | None = None,
    plugins: list[str] | None = None,
    extra_args: list[str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a pytest selection in a subprocess; return the completed process."""

    cmd = [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if markers:
        cmd += ["-m", markers]
    for plugin in plugins or []:
        cmd += ["-p", plugin]
    cmd += list(extra_args or [])
    cmd += list(selection)
    env = _base_env()
    # Guarantee ``scripts.*`` (seed plugin) is importable in the subprocess.
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH", "")]))
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd,
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _pytest_gate(
    name: str,
    tier: str,
    selection: tuple[str, ...],
    *,
    hard: bool = True,
    markers: str | None = None,
    env_extra: dict[str, str] | None = None,
    timeout: int | None = None,
) -> GateResult:
    try:
        proc = run_pytest(
            selection, markers=markers, env_extra=env_extra, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return GateResult(name, tier, hard, "error", f"pytest timed out after {timeout}s")
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else ""
    if proc.returncode == 0:
        return GateResult(name, tier, hard, "pass", summary)
    # Surface the failing lines so a human sees why without a re-run.
    fails = [ln for ln in tail if ln.startswith(("FAILED", "ERROR"))]
    detail = summary + ("\n    " + "\n    ".join(fails[:12]) if fails else "")
    if not detail.strip():
        detail = (proc.stderr or "").strip().splitlines()[-1:] or ["pytest failed"]
        detail = detail[0]
    return GateResult(name, tier, hard, "fail", detail, extra={"returncode": proc.returncode})


# ---------------------------------------------------------------------------
# Pure artifact checks (seedable — the self-test feeds these corrupted inputs)
# ---------------------------------------------------------------------------


def evaluate_frozen_digest_sentinels(
    sentinels: dict[str, str], *, root: Path = REPO, tier: str = "commit"
) -> GateResult:
    """A byte-changed frozen manifest moves its sha and reddens here."""

    problems: list[str] = []
    checked = 0
    for relpath, expected in sentinels.items():
        path = root / relpath
        if not path.exists():
            problems.append(f"{relpath}: MISSING")
            continue
        actual = _sha256_file(path)
        checked += 1
        if actual != expected:
            problems.append(f"{relpath}: sha {actual[:12]} != pinned {expected[:12]}")
    if problems:
        return GateResult(
            "frozen-digest-sentinels", tier, True, "fail",
            "; ".join(problems), extra={"checked": checked},
        )
    return GateResult(
        "frozen-digest-sentinels", tier, True, "pass",
        f"{checked} immutable manifest(s) byte-identical to pin",
        extra={"checked": checked},
    )


def evaluate_release_parity(
    *, manifest: Path = RELEASE_PARITY_MANIFEST, root: Path = REPO, tier: str = "commit"
) -> GateResult:
    """Packaged assets that drift from canonical source redden here (N27).

    Deliberately re-derives digests instead of invoking the generator: a gate
    that regenerates in place and then diffs nothing is theatre.
    """

    name = "release-parity"
    if not manifest.is_file():
        return GateResult(name, tier, True, "error", f"{manifest.name}: MISSING")
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return GateResult(name, tier, True, "error", f"{manifest.name}: unparseable ({exc})")

    packaged_root = manifest.parent
    problems: list[str] = []
    checked = 0
    recorded: set[str] = set()

    for entry in payload.get("assets", []):
        relpath = entry["packaged"]
        recorded.add(relpath)
        path = packaged_root / relpath
        if not path.is_file():
            problems.append(f"{relpath}: MISSING from the packaged tree")
            continue
        actual = _sha256_file(path)
        checked += 1
        if actual != entry["sha256"]:
            problems.append(f"{relpath}: sha {actual[:12]} != manifest {entry['sha256'][:12]}")
            continue
        source = entry.get("source")
        if source is None:
            continue
        source_path = root / source
        if not source_path.is_file():
            problems.append(f"{source}: canonical source MISSING")
        elif _sha256_file(source_path) != actual:
            problems.append(f"{relpath}: packaged bytes != source {source}")

    for path in sorted(packaged_root.rglob("*")):
        if not path.is_file() or path.name == manifest.name:
            continue
        relpath = path.relative_to(packaged_root).as_posix()
        if relpath not in recorded:
            problems.append(f"{relpath}: packaged file is not in the manifest")

    for entry in payload.get("side_mirrors", []):
        target, source = root / entry["target"], root / entry["source"]
        if not target.is_file():
            problems.append(f"{entry['target']}: side mirror MISSING")
            continue
        checked += 1
        if not source.is_file() or _sha256_file(target) != _sha256_file(source):
            problems.append(f"{entry['target']}: side mirror != {entry['source']}")

    if problems:
        return GateResult(
            name, tier, True, "fail",
            "; ".join(problems), extra={"checked": checked},
        )
    return GateResult(
        name, tier, True, "pass",
        f"{checked} packaged asset(s) byte-identical to canonical source",
        extra={"checked": checked},
    )


def _latest_frozen_baseline_row(nav_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    frozen = [r for r in nav_rows if r.get("frozen_baseline") is True]
    return frozen[-1] if frozen else None


def _panel_safety_fields_live() -> dict[str, Any]:
    """Live re-derivation of the panel clean run's safety-relevant fields."""

    from scripts.mutation_panel import live_clean_safety_fields

    return live_clean_safety_fields()


def evaluate_hard_safety(
    *,
    nav_ledger: Path = NAV_LEDGER,
    mutation_panel: Path = MUTATION_PANEL_JSON,
    followbench_ledger: Path = FOLLOWBENCH_LEDGER,
    walk_with_me_ledger: Path = WALK_WITH_ME_LEDGER,
    pinned_false_arrival: int = PINNED_FROZEN_FALSE_ARRIVAL,
    reproduce_panel: Callable[[], dict[str, Any]] | None = None,
    tier: str = "commit",
) -> GateResult:
    """Zero hard collisions on every product artifact + no new false_arrival.

    Reads the existing harness ledgers. The frozen-baseline nav row and the
    mutation-panel clean run and every follow-bench row must show zero hard
    collisions; the frozen-baseline false_arrival may not exceed its pin.
    walk_with_me rows join only when they carry ``hard_collision_total`` —
    legacy stub rows without the field are skipped by field-presence.

    **Freshness (lane E7, 2026-08-10).** The mutation panel is the only input
    here that is a *derived artifact* rather than a run ledger, and this gate
    used to certify ``no_false_arrival`` straight out of it. That is a hole with
    a name: the committed payload was written at 19c9226 and a live run on the
    current tree contradicted it (``no_false_arrival`` true -> false) while the
    gate kept printing ``no_false_arrival=True``. So the committed payload's
    safety-relevant fields are now RE-DERIVED live (one clean run, ~4 s) and
    must match. A gate may read a stale artifact; it may not *certify a safety
    property* from one.

    ``reproduce_panel`` is the seam: ``None`` means "re-derive live, but only
    when reading the real committed artifact" — a synthetic ``mutation_panel``
    path (the self-tests) has no tree to reproduce from, so the comparison is
    recorded as skipped rather than silently passed.
    """

    problems: list[str] = []
    checks: list[str] = []

    nav_rows = _read_jsonl(nav_ledger)
    baseline = _latest_frozen_baseline_row(nav_rows)
    if baseline is None:
        problems.append("nav_instruct: no frozen_baseline row (missing evidence)")
    else:
        rid = baseline.get("report_id", "?")
        coll = int(baseline.get("collision_total", -1))
        fa = int(baseline.get("authority_histogram", {}).get("false_arrival", -1))
        checks.append(f"nav frozen baseline {rid}: collisions={coll} false_arrival={fa}")
        if coll != 0:
            problems.append(f"nav_instruct frozen baseline collision_total={coll} (expected 0)")
        if fa > pinned_false_arrival:
            problems.append(
                f"nav_instruct frozen baseline false_arrival={fa} > pin {pinned_false_arrival}"
            )

    if mutation_panel.exists():
        panel = json.loads(mutation_panel.read_text(encoding="utf-8"))
        clean = panel.get("clean_run", {})
        coll = int(clean.get("collisions", -1))
        no_fa = bool(panel.get("clean_checks", {}).get("no_false_arrival", False))
        checks.append(f"mutation panel clean: collisions={coll} no_false_arrival={no_fa}")
        if coll != 0:
            problems.append(f"mutation panel clean_run collisions={coll} (expected 0)")
        if not no_fa:
            problems.append("mutation panel clean run has a false arrival (no_false_arrival=false)")

        reproducer = reproduce_panel
        if reproducer is None and mutation_panel == MUTATION_PANEL_JSON:
            reproducer = _panel_safety_fields_live
        if reproducer is None:
            checks.append(
                "mutation panel freshness: skipped (synthetic artifact, no tree to reproduce)"
            )
        else:
            from scripts.mutation_panel import clean_safety_fields

            committed_fields = clean_safety_fields(panel)
            live_fields = reproducer()
            fresh = live_fields == committed_fields
            checks.append(f"mutation panel freshness: committed fields reproduce live = {fresh}")
            if not fresh:
                drift = sorted(
                    key
                    for key in set(committed_fields) | set(live_fields)
                    if committed_fields.get(key) != live_fields.get(key)
                )
                problems.append(
                    "mutation panel is STALE: a live clean run contradicts the committed "
                    f"artifact on {drift} (committed={committed_fields} live={live_fields}) "
                    "— the hard gate will not certify a safety property from it"
                )
    else:
        problems.append("mutation_panel.json missing (missing evidence)")

    fb_rows = _read_jsonl(followbench_ledger)
    if fb_rows:
        bad = [
            r.get("report_id", r.get("run_id", "?"))
            for r in fb_rows
            if int(r.get("hard_collision_total", -1)) != 0
        ]
        checks.append(f"follow-bench: {len(fb_rows)} row(s), hard_collision_total all 0 = {not bad}")
        if bad:
            problems.append(f"follow-bench rows with hard collisions: {bad}")
    else:
        checks.append("follow-bench: no rows (skipped)")

    wwm_rows = _read_jsonl(walk_with_me_ledger)
    wwm_with_field = [r for r in wwm_rows if "hard_collision_total" in r]
    if wwm_with_field:
        bad = [
            r.get("report_id", r.get("run_id", "?"))
            for r in wwm_with_field
            if int(r.get("hard_collision_total", -1)) != 0
        ]
        checks.append(
            f"walk_with_me: {len(wwm_with_field)}/{len(wwm_rows)} row(s) with "
            f"hard_collision_total, all 0 = {not bad}"
        )
        if bad:
            problems.append(f"walk_with_me rows with hard collisions: {bad}")
    else:
        checks.append(
            f"walk_with_me: {len(wwm_rows)} row(s), none carry hard_collision_total (skipped)"
        )

    detail = " | ".join(checks)
    if problems:
        return GateResult("hard-safety", tier, True, "fail", "; ".join(problems), extra={"checks": checks})
    return GateResult("hard-safety", tier, True, "pass", detail, extra={"checks": checks})


def evaluate_latency_ratchet(
    series: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    *,
    margin: float = LATENCY_TAIL_MARGIN,
    tier: str = "commit",
    name: str = "latency-tail-ratchet",
) -> GateResult:
    """Ratchet p95/p99 in ``series`` against ``baseline * margin``.

    Pure core used by the ledger source switch and by the self-test (a seeded
    spike must still redden). The commit tier also keeps the percentile-pin
    pytest selection (``LATENCY_TAIL_NODE_IDS``).
    """

    problems: list[str] = []
    for metric, base in baseline.items():
        cur = series.get(metric)
        if cur is None:
            continue
        for key in ("p95_ms", "p99_ms"):
            if key in base and key in cur:
                ceiling = base[key] * margin
                if cur[key] > ceiling:
                    problems.append(
                        f"{metric}.{key} {cur[key]:.2f} > {ceiling:.2f} (baseline {base[key]:.2f} x {margin})"
                    )
    if problems:
        return GateResult(name, tier, True, "fail", "; ".join(problems))
    return GateResult(
        name, tier, True, "pass",
        f"{len(baseline)} metric series within {margin}x tail ceiling",
    )


def evaluate_latency_ledger(
    *,
    ledger: Path = LATENCY_LEDGER,
    baseline_path: Path = LATENCY_BASELINE,
    margin: float = LATENCY_TAIL_MARGIN,
    tier: str = "commit",
) -> GateResult:
    """Point the latency-tail ratchet at ``evals/latency/ledger.jsonl``.

    While the ledger has fewer rows than the pinned ``window``, skip with a
    note (never red) — the percentile-pin pytest gate remains authoritative.
    """

    if not baseline_path.exists():
        return GateResult(
            "latency-tail-ledger", tier, True, "error",
            f"missing latency baseline at {baseline_path.name}",
        )
    try:
        doc = json.loads(baseline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return GateResult("latency-tail-ledger", tier, True, "error", f"baseline JSON: {exc}")
    window = int(doc.get("window", 5))
    baseline_metrics = doc.get("metrics") or {}
    if not isinstance(baseline_metrics, dict) or not baseline_metrics:
        return GateResult(
            "latency-tail-ledger", tier, True, "error", "baseline.metrics missing or empty"
        )

    rows = _read_jsonl(ledger)
    if len(rows) < window:
        return GateResult(
            "latency-tail-ledger",
            tier,
            True,
            "skip",
            (
                f"ledger rows={len(rows)} < window={window}; ratchet skipped "
                "(percentile-pin pytest remains authoritative)"
            ),
            extra={"rows": len(rows), "window": window},
        )

    from parcel_robot.observability import latency_tail_series

    series = latency_tail_series(rows[-1])
    result = evaluate_latency_ratchet(
        series, baseline_metrics, margin=margin, tier=tier, name="latency-tail-ledger"
    )
    if result.status == "pass":
        result.detail = (
            f"latest row {rows[-1].get('row_id', '?')}: {result.detail} "
            f"(rows={len(rows)}, window={window})"
        )
    return result


def evaluate_followbench_jerk_ratchet(
    rows: list[dict[str, Any]],
    baseline: float,
    *,
    margin: float = LATENCY_TAIL_MARGIN,
    tier: str = "commit",
) -> GateResult:
    """Ratchet the latest SHIPPED follow-bench row's mean jerk against a pin.

    Pure core, shared by the ledger source below and by the seeded-spike
    self-test. Mirrors ``evaluate_latency_ratchet``: red iff the latest shipped
    row carrying the field exceeds ``baseline * margin``; skip-with-note (never
    red) when no such row exists, because a missing measurement is not evidence
    of a regression and the immutable reports remain the escape hatch.

    The INCLUSIVE mean is gated on purpose. Gating only the nominal variant
    would blind this to a bug spraying spurious hard stops; the nominal variant
    is reported alongside so a future re-pin can attribute stop-cost separately
    from smoothness-cost (design record §3.3, "Gate only 'nominal' jerk").
    """

    shipped = [
        row
        for row in rows
        if row.get("features") == "shipped" and row.get(FOLLOWBENCH_JERK_FIELD) is not None
    ]
    if not shipped:
        return GateResult(
            "follow-bench-jerk-ratchet",
            tier,
            True,
            "skip",
            (
                f"no shipped follow-bench row carries {FOLLOWBENCH_JERK_FIELD}; "
                "ratchet skipped (immutable reports remain the record)"
            ),
            extra={"rows": len(rows)},
        )
    latest = shipped[-1]
    raw = latest[FOLLOWBENCH_JERK_FIELD]
    # A string that happens to parse as a float is malformed ledger data, not a
    # measurement: coercing it would let a mis-typed row pass as green.
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return GateResult(
            "follow-bench-jerk-ratchet", tier, True, "error",
            f"latest shipped row {FOLLOWBENCH_JERK_FIELD} is not a number: {raw!r}",
        )
    value = float(raw)
    if not math.isfinite(value):
        return GateResult(
            "follow-bench-jerk-ratchet", tier, True, "error",
            f"latest shipped row {FOLLOWBENCH_JERK_FIELD} is not finite",
        )
    ceiling = baseline * margin
    report = latest.get("report", "?")
    nominal = latest.get("mean_rms_commanded_jerk_nominal_mps3")
    note = "" if nominal is None else f", nominal {nominal}"
    if value > ceiling:
        return GateResult(
            "follow-bench-jerk-ratchet", tier, True, "fail",
            (
                f"{FOLLOWBENCH_JERK_FIELD} {value:.4f} > {ceiling:.5f} "
                f"(baseline {baseline:.4f} x {margin}) in {report}"
            ),
        )
    return GateResult(
        "follow-bench-jerk-ratchet", tier, True, "pass",
        (
            f"latest shipped row {report}: {value:.4f} <= {ceiling:.5f} "
            f"(baseline {baseline:.4f} x {margin}{note})"
        ),
    )


def evaluate_followbench_jerk_ledger(
    *,
    ledger: Path = FOLLOWBENCH_LEDGER,
    baseline_path: Path = FOLLOWBENCH_JERK_BASELINE,
    margin: float = LATENCY_TAIL_MARGIN,
    tier: str = "commit",
) -> GateResult:
    """Point the follow-bench jerk ratchet at the committed ledger."""

    if not baseline_path.exists():
        return GateResult(
            "follow-bench-jerk-ratchet", tier, True, "error",
            f"missing jerk baseline at {baseline_path.name}",
        )
    try:
        doc = json.loads(baseline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return GateResult("follow-bench-jerk-ratchet", tier, True, "error", f"baseline JSON: {exc}")
    raw = doc.get(FOLLOWBENCH_JERK_FIELD)
    if not isinstance(raw, (int, float)) or isinstance(raw, bool) or not math.isfinite(float(raw)):
        return GateResult(
            "follow-bench-jerk-ratchet", tier, True, "error",
            f"baseline.{FOLLOWBENCH_JERK_FIELD} missing or not a finite number",
        )
    if not doc.get("provenance"):
        return GateResult(
            "follow-bench-jerk-ratchet", tier, True, "error",
            "baseline carries no provenance; a re-pin without attribution is not a baseline",
        )
    return evaluate_followbench_jerk_ratchet(
        _read_jsonl(ledger), float(raw), margin=margin, tier=tier
    )


# ---------------------------------------------------------------------------
# Ruff — ratcheted against a pinned baseline of pre-existing debt
# ---------------------------------------------------------------------------


def _ruff_fingerprints(root: Path = REPO) -> tuple[list[str], subprocess.CompletedProcess[str]]:
    """Return sorted ``relpath::code`` fingerprints of current ruff violations."""

    proc = subprocess.run(
        [PYTHON, "-m", "ruff", "check", ".", "--output-format=json"],
        cwd=str(root),
        env=_base_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return [], proc
    fps: set[str] = set()
    for item in items:
        filename = item.get("filename", "")
        try:
            rel = str(Path(filename).resolve().relative_to(root))
        except ValueError:
            rel = filename
        code = item.get("code") or "UNKNOWN"
        fps.add(f"{rel}::{code}")
    return sorted(fps), proc


def evaluate_ruff(*, baseline_path: Path = RUFF_BASELINE, tier: str = "commit") -> GateResult:
    """Fail only on ruff violations whose (file, rule) is not in the baseline.

    The repo carries pre-existing ruff debt in modules this card does not own
    (storefront, uwb, route_memory, ...); a hard ``ruff check`` would block every
    commit. The ratchet keeps ruff a real per-commit gate — new code must be
    clean — while the debt is burned down separately (it is enumerated in the
    baseline file and in docs/CI.md as a handoff).
    """

    current, proc = _ruff_fingerprints()
    if proc.returncode not in (0, 1):  # 0 clean, 1 = violations found; else crash
        return GateResult("ruff", tier, True, "error", (proc.stderr or "ruff failed").strip()[:400])
    if not baseline_path.exists():
        return GateResult(
            "ruff", tier, True, "error",
            f"no ruff baseline at {baseline_path.name}; run --update-ruff-baseline",
        )
    baseline = set(json.loads(baseline_path.read_text(encoding="utf-8")).get("fingerprints", []))
    new = sorted(set(current) - baseline)
    detail = f"{len(current)} violation(s), baseline {len(baseline)}, new {len(new)}"
    if new:
        return GateResult(
            "ruff", tier, True, "fail",
            detail + " -> " + "; ".join(new[:15]), extra={"new": new},
        )
    return GateResult("ruff", tier, True, "pass", detail)


def update_ruff_baseline(*, baseline_path: Path = RUFF_BASELINE) -> int:
    current, _ = _ruff_fingerprints()
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": (
            "Pre-existing ruff debt this CI gate ratchets against. New (file, rule) "
            "fingerprints beyond this set redden scripts/ci_gate.py. Burn down toward "
            "an empty list; regenerate with `ci_gate.py --update-ruff-baseline`."
        ),
        "count": len(current),
        "fingerprints": current,
    }
    baseline_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {baseline_path} with {len(current)} fingerprint(s)")
    return 0


# ---------------------------------------------------------------------------
# Card R26 — tier coverage: every collected test belongs to a tier that RUNS it
# ---------------------------------------------------------------------------


def _collect_ids(markers: str | None, *, timeout: int = 600) -> tuple[set[str], str]:
    """Node ids pytest would select under ``markers`` (collection only)."""

    # NOT ``--collect-only -q``: ``run_pytest`` already passes ``-q``, and a
    # second one is ``-qq``, which suppresses the node-id list entirely and
    # leaves this gate parsing an empty set. Learned the hard way, 2026-08-21.
    proc = run_pytest((), markers=markers, extra_args=["--collect-only"], timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(
            f"collection under -m {markers!r} failed (rc={proc.returncode}): "
            + ((proc.stdout or "") + (proc.stderr or "")).strip()[-400:]
        )
    ids = {
        line.strip()
        for line in (proc.stdout or "").splitlines()
        if "::" in line and not line.startswith(("FAILED", "ERROR", "<"))
    }
    tail = [ln for ln in (proc.stdout or "").strip().splitlines() if "collected" in ln]
    return ids, (tail[-1] if tail else "")


def evaluate_tier_coverage(
    *,
    commit_markers: str = COMMIT_MARKERS,
    nightly_markers: str = NIGHTLY_SLOW_MARKERS,
    tier: str = "commit",
    collector: Callable[[str | None], tuple[set[str], str]] | None = None,
) -> GateResult:
    """Every collected test is run by the commit tier or by the nightly tier.

    The audit's §Tests-1 in one executable sentence. It compares three
    collections — everything, what the commit tier selects, what the nightly's
    slow selection selects — and reddens on either failure mode:

    * **orphaned**: a test in neither tier. That is the "42 deselected tests
      nothing ever runs" finding; it can reappear the moment a marker expression
      is narrowed or a third marker is invented.
    * **double-counted**: a test in both. Harmless for coverage, but it means the
      tier boundary is not a partition and the deselected count in a gate line
      stops meaning what a reader thinks it means.

    ``collector`` is the seam the self-test seeds: a narrowed nightly selection
    must redden here, which is what makes this gate more than a tautology.
    """

    name = "tier-coverage"
    collect = collector or (lambda markers: _collect_ids(markers))
    try:
        every, every_line = collect(None)
        commit_ids, _ = collect(commit_markers)
        nightly_ids, _ = collect(nightly_markers)
    except RuntimeError as exc:
        return GateResult(name, tier, True, "error", str(exc))
    if not every:
        return GateResult(name, tier, True, "error", "collection returned no node ids")

    orphaned = sorted(every - commit_ids - nightly_ids)
    doubled = sorted(commit_ids & nightly_ids)
    problems: list[str] = []
    if orphaned:
        problems.append(
            f"{len(orphaned)} test(s) run by NEITHER tier: {orphaned[:8]}"
            + (" ..." if len(orphaned) > 8 else "")
        )
    if doubled:
        problems.append(
            f"{len(doubled)} test(s) selected by BOTH tiers: {doubled[:8]}"
            + (" ..." if len(doubled) > 8 else "")
        )
    extra = {
        "collected": len(every),
        "commit_selected": len(commit_ids),
        "nightly_selected": len(nightly_ids),
        "orphaned": orphaned,
        "doubled": doubled,
        "commit_markers": commit_markers,
        "nightly_markers": nightly_markers,
        "collected_line": every_line,
    }
    if problems:
        return GateResult(name, tier, True, "fail", "; ".join(problems), extra=extra)
    return GateResult(
        name, tier, True, "pass",
        (
            f"{len(every)} collected = {len(commit_ids)} commit (-m {commit_markers!r}) "
            f"+ {len(nightly_ids)} nightly (-m {nightly_markers!r}), no orphans, no overlap"
        ),
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Nightly-only harness runs (offline, in-process where possible)
# ---------------------------------------------------------------------------


def evaluate_mutation_panel(tier: str = "nightly") -> GateResult:
    """Run every registered mutation in-process; no survivor is allowed."""

    try:
        from scripts.mutation_panel import run_panel
    except Exception as exc:  # noqa: BLE001
        return GateResult("mutation-panel", tier, True, "error", f"import failed: {exc}")
    try:
        payload = run_panel()
    except Exception as exc:  # noqa: BLE001
        return GateResult("mutation-panel", tier, True, "error", f"{type(exc).__name__}: {exc}")
    killed = [m for m in payload["mutants"] if m["verdict"] == "killed"]
    survivors = payload.get("survivors") or []
    detail = f"{len(killed)}/{len(payload['mutants'])} killed, survivors={survivors}"
    if survivors or not payload.get("passed"):
        return GateResult("mutation-panel", tier, True, "fail", detail)
    return GateResult("mutation-panel", tier, True, "pass", detail)


def evaluate_assertion_evals(*, tier: str = "commit", k: int = 1) -> GateResult:
    """Card EV-1 — the session-assertion suite, its self-test and pass^k.

    Delegates to ``evals.assertions.gate`` for the same reason
    ``evaluate_mutation_panel`` delegates to ``scripts.mutation_panel``: this
    module is the list of gates, not the place their logic lives. ``k`` is the
    only thing the two tiers disagree about — 1 here for cost, 3 nightly —
    because pass^k is fail-closed and a k it cannot afford would redden every
    commit rather than measure anything.
    """

    try:
        from evals.assertions.gate import run_assertion_gate
    except Exception as exc:  # noqa: BLE001
        return GateResult("assertion-evals", tier, True, "error", f"import failed: {exc}")
    try:
        status, detail, extra = run_assertion_gate(k=k)
    except Exception as exc:  # noqa: BLE001
        return GateResult("assertion-evals", tier, True, "error", f"{type(exc).__name__}: {exc}")
    return GateResult("assertion-evals", tier, True, status, detail, extra=extra)


def evaluate_pose_drift_arms(
    tier: str = "nightly", *, limit: int = 0
) -> list[GateResult]:
    """Card DR-2 — the standing degraded-pose arms, nightly.

    Nightly and not commit: the arms are seven full passes over the 61-cell
    long-travel substrate, which is minutes of simulation, not seconds. What the
    commit tier gets instead is the cheap half — the seed derivation, the band
    algebra, the record shape and the flag-off byte-path — as ordinary unit
    tests in ``tests/test_dr2_pose_drift_arm.py``.

    Three gates, and the split between them is the card's:

    * ``:safety`` — HARD. Zero collisions and zero false arrivals under EVERY
      profile, from day one, with no measurement grace.
    * ``:non-vacuity`` — HARD. Every episode's measured truth-vs-ODOM divergence
      inside its profile's pre-registered band, every episode on its own seed,
      the ``*_lost`` windows held AND recovered, the re-anchoring profile's MAP
      really jumped, and the tier ladder monotone at the arm mean. A drift arm
      that silently ran on truth would be green on safety and red here.
    * ``:floors`` — HARD once ``DRIFT_FLOORS`` is pinned, and an explicit
      report-only ``skip`` before that. A gate that quietly passes because
      nothing is pinned yet is worse than no gate.

    ``limit`` exists for a smoke invocation and is 0 (the whole substrate) for
    the real nightly run. A limited run truncates the substrate, so its SR is
    measured on a DIFFERENT set from the one the floors were derived on and
    cannot certify them either way — the floors gate therefore degrades to a
    loud, non-hard ``skip`` naming the limit rather than reporting a comparison
    that does not mean what it says. Safety and non-vacuity are per-episode
    properties and stay hard at any limit.
    """

    try:
        from evals.nav_instruct.run_drift_arms import (
            DRIFT_FLOORS,
            check_floors,
            hard_invariants,
            ladder_monotone,
            non_vacuity,
            run_stage,
        )
    except Exception as exc:  # noqa: BLE001
        return [GateResult("pose-drift-arms", tier, True, "error", f"import failed: {exc}")]
    try:
        payload = run_stage("b" if DRIFT_FLOORS else "a", limit=limit)
    except Exception as exc:  # noqa: BLE001
        return [
            GateResult(
                "pose-drift-arms", tier, True, "error", f"{type(exc).__name__}: {exc}"
            )
        ]
    rows = payload["arms"]
    safety = [problem for row in rows for problem in hard_invariants(row)]
    vacuity = [problem for row in rows for problem in non_vacuity(row)]
    vacuity += ladder_monotone(rows)
    floors = check_floors(rows) if DRIFT_FLOORS else []
    arms = ", ".join(
        f"{row['profile'] or 'truth'}={row['sr']:.3f}" for row in rows
    )
    banded = sum(int((row.get("pose_drift") or {}).get("episodes_banded", 0)) for row in rows)
    in_band = sum(int((row.get("pose_drift") or {}).get("episodes_in_band", 0)) for row in rows)
    results = [
        GateResult(
            "pose-drift-arms:safety", tier, True,
            "pass" if not safety else "fail",
            "; ".join(safety)
            or f"collisions=0 false_arrival=0 across {len(rows)} arm(s) on "
               f"{payload['n']} cell(s)",
        ),
        GateResult(
            "pose-drift-arms:non-vacuity", tier, True,
            "pass" if not vacuity else "fail",
            "; ".join(vacuity) or f"{in_band}/{banded} episode(s) in band; SR {arms}",
        ),
    ]
    if DRIFT_FLOORS and limit > 0:
        results.append(
            GateResult(
                "pose-drift-arms:floors", tier, False, "skip",
                f"limit={limit} truncates the substrate the floors were derived "
                f"on ({len(DRIFT_FLOORS)} arm(s) pinned); a partial run cannot "
                "certify them either way",
            )
        )
    elif DRIFT_FLOORS:
        results.append(
            GateResult(
                "pose-drift-arms:floors", tier, True,
                "pass" if not floors else "fail",
                "; ".join(floors)
                or f"{len(DRIFT_FLOORS)} arm(s) at or above their Stage-B floor",
            )
        )
    else:
        results.append(
            GateResult(
                "pose-drift-arms:floors", tier, False, "skip",
                "no Stage-B floor pinned yet (run_drift_arms.DRIFT_FLOORS is empty)",
            )
        )
    return results


def evaluate_nav_instruct_candidate(tier: str = "nightly") -> list[GateResult]:
    """Run the candidate minival; hard-gate collisions, report the rest."""

    before = {r.get("report_id") for r in _read_jsonl(NAV_LEDGER)}
    try:
        proc = subprocess.run(
            [
                PYTHON, "-m", "evals.nav_instruct.run_nav_instruct_v1",
                # v4 since the 2026-08-11 re-freeze (lane E8): the candidate arm
                # must run the same frozen set the frozen-baseline row and the
                # mutation panel are on, or the nightly comparison is between
                # two different eval regions.
                "--minival", "--mode", "candidate", "--episode-version", "v4",
            ],
            cwd=str(REPO), env=_base_env(), capture_output=True, text=True, timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [GateResult("nav-instruct-candidate", tier, True, "error", "timed out")]
    if proc.returncode != 0:
        return [GateResult("nav-instruct-candidate", tier, True, "fail", (proc.stderr or "run failed").strip()[-400:])]
    rows = _read_jsonl(NAV_LEDGER)
    new_rows = [r for r in rows if r.get("report_id") not in before]
    row = new_rows[-1] if new_rows else (rows[-1] if rows else {})
    coll = int(row.get("collision_total", -1))
    auth = row.get("authority_histogram", {})
    fa = int(auth.get("false_arrival", -1))
    sr = row.get("sr")
    results = [
        GateResult(
            "nav-instruct-candidate:collisions", tier, True,
            "pass" if coll == 0 else "fail",
            f"collision_total={coll} (report {row.get('report_id')})",
        ),
        GateResult(
            "nav-instruct-candidate:differential", tier, False, "report",
            f"sr={sr} authority={auth} false_arrival={fa}",
        ),
    ]
    return results


# ---------------------------------------------------------------------------
# Tier assembly
# ---------------------------------------------------------------------------


def run_commit_tier() -> list[GateResult]:
    tier = "commit"
    results: list[GateResult] = []
    # Card P0-E (scrum/20260822/task_5): the commit tier is the SAFETY CORE plus
    # the cheap truth checks. The evidence ratchets — frozen-digest sentinels,
    # the latency and follow-bench ledgers, frozen-digest integrity,
    # mutation-panel freshness, the latency percentile pins — moved to the
    # nightly tier, where they still gate. They protect claims, not the robot,
    # and for the prototype they reddened on doc edits and scene retunes.
    # Cheap deterministic checks first (fast-fail signal without waiting on pytest).
    results.append(evaluate_ruff(tier=tier))
    results.append(evaluate_hard_safety(tier=tier))
    results.append(evaluate_release_parity(tier=tier))
    results.append(evaluate_assertion_evals(tier=tier, k=1))
    # Card R26: cheap (three collections, no execution) and it is the only gate
    # that can see a whole tier going dark.
    results.append(evaluate_tier_coverage(tier=tier))
    # Targeted hard-gate pytest selections (small, fast).
    results.append(_pytest_gate("model-off-non-inferiority", tier, MODEL_OFF_NODE_IDS, timeout=900))
    results.append(_pytest_gate("release-parity-integrity", tier, RELEASE_PARITY_NODE_IDS, timeout=600))
    results.append(_pytest_gate("owner-store-isolation", tier, OWNER_STORE_NODE_IDS, timeout=900))
    # The full default gate last (latest recorded: 7,715 passed on 2026-08-21).
    results.append(
        _pytest_gate("default-suite", tier, (), markers="not slow", timeout=1800)
    )
    return results


#: Card R26. Environment the nightly's pytest subprocesses run under.
#: ``PARCEL_LOAD_GUARD=off`` is the other half of the load guard: the guarded
#: wall-clock tests skip under contention in the COMMIT tier and are forced to
#: run here, where load is controlled. A guard that could skip in every tier
#: would be a delete button with a friendly message.
NIGHTLY_ENV: dict[str, str] = {"PARCEL_NIGHTLY": "1", "PARCEL_LOAD_GUARD": "off"}


def run_nightly_tier() -> list[GateResult]:
    tier = "nightly"
    results: list[GateResult] = []
    # Re-run every commit hard gate (nightly is a superset).
    results.append(evaluate_ruff(tier=tier))
    results.append(evaluate_hard_safety(tier=tier))
    results.append(evaluate_frozen_digest_sentinels(DIGEST_SENTINELS, tier=tier))
    results.append(evaluate_release_parity(tier=tier))
    results.append(evaluate_latency_ledger(tier=tier))
    results.append(evaluate_followbench_jerk_ledger(tier=tier))
    # Same gate, k=3: SYNTHESIS_EVAL decision 4 asks for k>=3 wherever it can be
    # afforded, and nightly is where it can.
    results.append(evaluate_assertion_evals(tier=tier, k=3))
    results.append(_pytest_gate("model-off-non-inferiority", tier, MODEL_OFF_NODE_IDS, timeout=900))
    results.append(_pytest_gate("frozen-digest-integrity", tier, FROZEN_DIGEST_NODE_IDS, timeout=900))
    results.append(_pytest_gate("release-parity-integrity", tier, RELEASE_PARITY_NODE_IDS, timeout=600))
    results.append(_pytest_gate("mutation-panel-freshness", tier, MUTATION_FRESHNESS_NODE_IDS, timeout=600))
    results.append(_pytest_gate("latency-tail", tier, LATENCY_TAIL_NODE_IDS, timeout=600))
    results.append(_pytest_gate("owner-store-isolation", tier, OWNER_STORE_NODE_IDS, timeout=900))
    results.append(evaluate_tier_coverage(tier=tier))
    results.append(
        _pytest_gate(
            "default-suite", tier, (), markers=COMMIT_MARKERS,
            env_extra=NIGHTLY_ENV, timeout=1800,
        )
    )
    # Nightly-only: the slow harnesses.
    results.append(evaluate_mutation_panel(tier=tier))
    results.extend(evaluate_nav_instruct_candidate(tier=tier))
    # Card DR-2: the standing degraded-pose arms.
    results.extend(evaluate_pose_drift_arms(tier=tier))
    # THE DESELECTED TIER. ``NIGHTLY_SLOW_MARKERS`` rather than a literal so the
    # tier-coverage gate above and this runner cannot disagree about what the
    # nightly is for (card R26).
    results.append(
        _pytest_gate(
            "slow-suite", tier, (), markers=NIGHTLY_SLOW_MARKERS,
            env_extra=NIGHTLY_ENV, timeout=5400,
        )
    )
    # Report the metamorphic suite distinctly (already inside slow-suite).
    results.append(
        _pytest_gate(
            "metamorphic", tier, ("tests/test_nav_metamorphic.py",),
            markers=NIGHTLY_SLOW_MARKERS,
            hard=False, env_extra=NIGHTLY_ENV, timeout=1800,
        )
    )
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def summarize(results: list[GateResult], tier: str, elapsed: float) -> str:
    lines = [
        f"CI GATE — tier={tier}  ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})",
        "=" * 78,
    ]
    width = max((len(r.name) for r in results), default=20)
    for r in results:
        flag = "HARD" if r.hard else "soft"
        lines.append(f"[{_ICON.get(r.status, r.status):>6}] {flag}  {r.name:<{width}}  {r.detail}")
    lines.append("=" * 78)
    gating = [r for r in results if r.gating_red]
    soft_red = [r for r in results if r.is_red and not r.hard]
    if gating:
        lines.append(f"RESULT: FAIL — {len(gating)} hard gate(s) red: {', '.join(r.name for r in gating)}")
    else:
        lines.append("RESULT: PASS — every hard gate green.")
    if soft_red:
        lines.append(f"  (report-only red, non-gating: {', '.join(r.name for r in soft_red)})")
    lines.append(f"  elapsed {elapsed:.1f}s")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", choices=("commit", "nightly"), default="commit")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON as well")
    parser.add_argument(
        "--update-ruff-baseline", action="store_true",
        help="re-pin the ruff debt baseline to the current tree and exit",
    )
    args = parser.parse_args(argv)

    if args.update_ruff_baseline:
        return update_ruff_baseline()

    started = time.perf_counter()
    results = run_commit_tier() if args.tier == "commit" else run_nightly_tier()
    elapsed = time.perf_counter() - started

    print(summarize(results, args.tier, elapsed))
    if args.json:
        print(json.dumps(
            {"tier": args.tier, "elapsed_s": elapsed, "gates": [r.as_dict() for r in results]},
            indent=2, sort_keys=True,
        ))
    return 1 if any(r.gating_red for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
