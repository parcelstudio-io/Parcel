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

Exit codes (card GATE-1, ``scrum/20260823/task_5``): ``0`` every hard gate ran
and none is red; ``1`` some hard gate is red (this wins over ``2``); ``2`` the
run is INCOMPLETE — nothing is red, but a hard gate could not run on this host
and printed a typed ``skip``. ``--json`` carries the same fact as
``"incomplete"``. Report-only gates never change the exit code; they are
printed so a human sees the trend.

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
import traceback
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
    # Previous pin: d338f3352cd9597aeb9977f75c139d926bdfba1fe1d6b036b9a3ace08a1cf114
    # Re-pinned 2026-08-24 (Lane A close, integrator Fable): DEC-FS-1 (0ec1d7c)
    # moved memory.py into memory/ and re-pinned the manifest's INNER lock on
    # build_memory_fixture.py as change_class "repin-only" (added 0 / removed 0
    # / repinned 1, freeze_provenance recorded inside the manifest itself) —
    # but this OUTER pin on the manifest file was not moved with it, so the
    # gate was red on an already-authorized two-line import diff. No eval
    # OUTPUT moved; the chain of custody is the manifest's own provenance
    # entry, verified against the previous pack_digest at the DEC-FS-1 close.
    "evals/companion/personal_convo_v1/manifest.json": "a3d6ff7287de507e74b1f44c2417ed49f153c489f79ae32a896f494563f4f2ef",
}

# ---------------------------------------------------------------------------
# (b2) UNITREE-ASSETS — card GATE-0 (scrum/20260822/task_20).
#
# Both product scenes ``<include>`` the Unitree Go2 MJCF. Until this card the
# directory was blanket-gitignored and nothing fetched it, so on a fresh clone
# the FIRST gate that opened a scene (hard-safety, via the mutation panel's live
# clean run) raised and the whole runner died ~1 s in without a summary. The
# pack is now a tracked, manifest-pinned 20-file subset at its upstream path,
# and this stage is the closure contract for it.
# ---------------------------------------------------------------------------
UNITREE_ROOT = REPO / "third_party" / "unitree_mujoco"
UNITREE_PROVENANCE = UNITREE_ROOT / "PROVENANCE.json"

#: Pinned here INDEPENDENTLY of the manifest, on purpose. A self-consistent
#: replacement pack generated at some other upstream revision validates against
#: its own manifest perfectly; this constant is the second witness that says
#: which revision Parcel actually reviewed.
UNITREE_EXPECTED_REVISION = "ae6a8403e272733e9996ef59990880330496177f"

#: Product scenes are DERIVED, never listed: every scene that includes the pack
#: is compiled, so adding one cannot silently skip coverage — and one of the two
#: is a held-out scene (``tests/test_held_out_scene.py``) that this file
#: therefore does not name.
PRODUCT_SCENE_DIR = REPO / "src" / "parcel_robot" / "scenes"
UNITREE_INCLUDE_TOKEN = "third_party/unitree_mujoco/unitree_robots/go2"


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
    A run exits ``1`` iff some ``hard`` gate is ``fail`` or ``error``, and ``2``
    when none is red but a ``hard`` gate ``skip``ped (card GATE-1: a host that
    could not run a gate is incomplete, not green — see ``gate_exit_code``).
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
    # ---- CARD XD-1 nesting mark (scrum/20260822/task_14) ----
    # Stamp every pytest the gate spawns, so a gate evaluator that runs INSIDE
    # that pytest can see it is already a child and refuse to run the whole
    # suite again. The constant and the refusal live in the XD-1 region below
    # (:data:`CI_GATE_NESTED_ENV`, :func:`evaluate_default_suite`); this is the
    # one line that has to sit in the shared driver, because the driver is what
    # creates the child. ``env_extra`` is applied after it on purpose: a test
    # that needs an unmarked child says so explicitly.
    env[CI_GATE_NESTED_ENV] = "1"
    # ---- END CARD XD-1 nesting mark ----
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


# ---- CARD XD-1 default-suite two-phase runner (scrum/20260822/task_14) ----
#
# THE DEFAULT SUITE RUNS IN PARALLEL, IN TWO PHASES, AND THE TWO ARE A
# PARTITION OF THE COMMIT TIER BY CONSTRUCTION.
#
# Five to six minutes per commit gate was the largest single drag on iteration
# in this repo. ``pytest -n auto`` runs the same suite roughly six times faster
# on this host, and P0-E measured exactly that (51.9 s vs 317 s) — but it also
# measured SEVEN tests that diverged under xdist, so the gate stayed serial.
# Divergence is the only thing that matters here: a gate that is fast and
# reports a different answer than the serial run is not a gate.
#
# The split is between tests whose subject is WALL-CLOCK DURATION and everything
# else. A wall-clock assertion cannot be measured while 191 sibling workers are
# saturating the machine — that is not an xdist defect, it is what the
# ``load_sensitive`` marker (card R26, ``scripts/load_guard.py``) already means
# — so those run afterwards, serially, in the same process budget as before.
# Every OTHER divergence was FIXED AT THE SOURCE rather than marked: marking a
# behaviour test ``load_sensitive`` would make it skippable under contention,
# which is silencing it, not fixing it.
#
# WHY THE MARKERS ARE DERIVED AND NOT WRITTEN TWICE. Both phases are built from
# ``COMMIT_MARKERS`` by :func:`default_suite_phases`, so their union is exactly
# the tier the ``tier-coverage`` gate counts and their intersection is empty --
# there is no edit that can make the two phases disagree about what the commit
# tier is, and no test can fall between them. ``tests/test_ci_gate.py`` proves
# both directions against the real function.
#
# The NIGHTLY tier's ``default-suite`` is deliberately left serial: it runs with
# ``PARCEL_LOAD_GUARD=off`` precisely so the wall-clock assertions cannot skip,
# and the nightly is the tier where wall-clock time is available and
# determinism is worth more than speed.

#: Workers for phase A. An operator on a small box, or a bisect that wants
#: determinism, pins this; otherwise the count is DERIVED and CAPPED (below).
XDIST_WORKERS_ENV = "PARCEL_XDIST_WORKERS"

#: Marks a pytest the gate itself spawned. Read on entry to
#: :func:`evaluate_default_suite`; written by :func:`run_pytest`.
CI_GATE_NESTED_ENV = "PARCEL_CI_GATE_NESTED"

#: THE CEILING, AND WHY THERE IS ONE.
#:
#: ``-n auto`` asks pytest-xdist for one worker per usable CPU. On the dev box
#: that is 192 workers at roughly a quarter of a gigabyte each, and on
#: 2026-08-22/23 that number, multiplied by concurrent runs and by a gate that
#: could re-enter itself (see :data:`CI_GATE_NESTED_ENV`), took the machine
#: down four times: python held 91-237 GB across 339-986 processes and the
#: kernel OOM-killed the editor, every agent session and the runs themselves.
#: A gate that can kill the host it is gating is not a gate.
#:
#: So the default is ``min(os.cpu_count(), XDIST_MAX_WORKERS)`` and the word
#: ``auto`` is never handed to xdist. The cap is a MAXIMUM, not a target: on
#: an 8-core Jetson Orin NX -- the Go2 EDU+'s onboard computer -- the default
#: resolves to 8, exactly as ``auto`` would have, so nothing is lost on the
#: hardware this repo is heading for; the cap only bites on a machine with
#: more cores than the suite can use, where the marginal worker buys ~nothing
#: and costs memory. The resolved number and WHERE IT CAME FROM are recorded
#: in the gate row, so no reader has to guess what ran.
XDIST_MAX_WORKERS = 16


def resolve_xdist_workers(
    explicit: str | None = None, env: dict[str, str] | None = None
) -> tuple[str, str]:
    """Return ``(workers, provenance)`` for phase A -- never ``auto``.

    ``explicit`` (the caller's argument) wins over :data:`XDIST_WORKERS_ENV`,
    which wins over the derived default. An operator's pin is HONOURED as
    written, including above the cap: the cap exists to stop an accident, not
    to overrule a person who typed a number. ``auto``/``logical`` and anything
    that is not a positive integer fall back to the default WITH A REASON that
    travels into the gate row -- silently substituting a different worker count
    is how a timing row becomes a lie.
    """

    source = os.environ if env is None else env
    raw = (explicit if explicit is not None else source.get(XDIST_WORKERS_ENV, "")) or ""
    raw = str(raw).strip()
    cpus = os.cpu_count() or 1
    default = str(min(cpus, XDIST_MAX_WORKERS))
    origin = "argument" if explicit is not None else XDIST_WORKERS_ENV
    if not raw:
        return default, f"derived min(cpu_count={cpus}, cap={XDIST_MAX_WORKERS})"
    if raw.lower() in ("auto", "logical"):
        return default, (
            f"{origin}={raw!r} REFUSED (one worker per CPU is what OOM-killed this "
            f"host); derived min(cpu_count={cpus}, cap={XDIST_MAX_WORKERS})"
        )
    if not raw.isdigit() or int(raw) < 1:
        return default, (
            f"{origin}={raw!r} is not a positive worker count; derived "
            f"min(cpu_count={cpus}, cap={XDIST_MAX_WORKERS})"
        )
    return raw, f"{origin}={raw} (honoured; cpu_count={cpus}, cap={XDIST_MAX_WORKERS})"

#: ``loadfile`` keeps every test in a file on ONE worker. Chosen over the
#: default ``load`` for a correctness reason, not a speed one: module- and
#: class-scoped fixtures (HY-1's per-file simulator census among them) are
#: written on the assumption that one file is one process, and ``load`` breaks
#: that assumption silently by scattering a file's tests across workers.
XDIST_DIST_MODE = "loadfile"


def default_suite_phases(commit_markers: str = COMMIT_MARKERS) -> tuple[str, str]:
    """The commit tier's selection, partitioned into (parallel, serial).

    Derived from one argument so the two halves cannot drift apart. The
    parenthesisation matters: ``COMMIT_MARKERS`` is an expression, and
    ``not slow and load_sensitive`` would bind differently from
    ``(not slow) and load_sensitive`` the day the tier expression grows an
    ``or``.
    """

    return (
        f"({commit_markers}) and not load_sensitive",
        f"({commit_markers}) and load_sensitive",
    )


def evaluate_default_suite(
    *,
    tier: str = "commit",
    env_extra: dict[str, str] | None = None,
    timeout: int = 1800,
    workers: str | None = None,
) -> GateResult:
    """``default-suite`` as one gate row, run as two phases."""

    # THE RECURSION GUARD. ``run_pytest`` stamps CI_GATE_NESTED_ENV into every
    # child it spawns, so if this evaluator is reached from INSIDE a pytest the
    # gate started, running the whole suite again would be a fork bomb with a
    # 9,000-test fuse -- five chained levels is what put 986 python processes
    # and 237 GB on this host on 2026-08-23. Targeted ``_pytest_gate`` runs are
    # deliberately still allowed nested: they are bounded node-id lists, they
    # are what the gate's own self-tests exercise, and nothing about them grows.
    if (os.environ.get(CI_GATE_NESTED_ENV) or "").strip():
        return GateResult(
            "default-suite", tier, True, "error",
            f"refused: {CI_GATE_NESTED_ENV} is set, so this is already running "
            "inside a pytest the gate spawned. The default suite does not run "
            "itself; run `ci_gate.py --tier commit` from a shell, not from a test.",
            extra={"nested": True},
        )
    parallel_markers, serial_markers = default_suite_phases()
    resolved_workers, workers_provenance = resolve_xdist_workers(workers)
    phases: list[tuple[str, subprocess.CompletedProcess[str], float]] = []
    for label, markers, extra_args in (
        ("parallel", parallel_markers, ["-n", resolved_workers, "--dist", XDIST_DIST_MODE]),
        ("serial", serial_markers, []),
    ):
        started = time.monotonic()
        try:
            proc = run_pytest(
                (), markers=markers, env_extra=env_extra,
                extra_args=extra_args, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return GateResult(
                "default-suite", tier, True, "error",
                f"{label} phase timed out after {timeout}s",
            )
        phases.append((label, proc, time.monotonic() - started))

    summaries = []
    fails: list[str] = []
    for label, proc, elapsed in phases:
        lines = (proc.stdout or "").strip().splitlines()
        summaries.append(f"{label} ({elapsed:.1f}s): {lines[-1] if lines else '(no output)'}")
        fails.extend(ln for ln in lines if ln.startswith(("FAILED", "ERROR")))
    detail = (
        f"-n {resolved_workers} --dist {XDIST_DIST_MODE} [{workers_provenance}]; "
        + "; ".join(summaries)
    )
    codes = {label: proc.returncode for label, proc, _ in phases}
    extra = {
        "returncodes": codes,
        "workers": resolved_workers,
        "workers_provenance": workers_provenance,
        "seconds": {label: round(elapsed, 2) for label, _, elapsed in phases},
    }
    if not any(codes.values()):
        return GateResult("default-suite", tier, True, "pass", detail, extra=extra)
    if fails:
        detail += "\n    " + "\n    ".join(fails[:12])
    return GateResult("default-suite", tier, True, "fail", detail, extra=extra)


# ---- END CARD XD-1 default-suite two-phase runner --------------------------


# ---- CARD GATE-0b skip-list reporting (scrum/20260822/task_30) -------------
#
# WHAT A CLEAN CLONE USED TO SAY, AND WHAT IT SAYS NOW.
#
# `git clone` + `pip install -e '.[dev,voice]'` + `--tier commit` produced 48
# red tests on 2026-08-23, and 28 of them needed an EXTERNAL EVIDENCE ROOT that
# is deliberately not in git: the external-eval scratch under
# `.cache/external-evals` is 21 GB on the dev box, and vendoring it is not an
# option at any size. Those tests now SKIP with a named reason
# (`tests/_external_roots.py`) — and a skip nobody prints is a test that
# quietly stopped existing, which is why this stage exists.
#
# WHY IT IS A REPORT ROW AND NEVER A GATE. `hard=False`, so `GateResult
# .gating_red` is False by construction and this stage cannot change an exit
# code. It answers one question — "what did this host not run, and how would
# you get it?" — and the answer is printed on every run, green or red.
#
# WHY IT READS THE TABLE STATICALLY. `ast.literal_eval` of one assignment,
# plus a substring scan of `tests/*.py`. It does NOT import the test tree and
# it does NOT start a pytest: this file is what XD-1 taught the repo never to
# re-enter (`CI_GATE_NESTED_ENV` above), and a reporting row is the last place
# that should spawn nine thousand tests. Cost: ~10 MB of file reads.
#
# HARDWARE. A declaration is a PATH STAT or an import check, never a platform
# test, so the same `--tier commit` command gives an honest verdict on this
# x86-64 box, on the hosted `ubuntu-latest` runner (B20) and on the Go2 EDU+'s
# aarch64 Jetson Orin NX: a row that needs CUDA, an x86-only wheel or a
# generated corpus resolves to the same printed skip-with-reason on all three
# instead of to a red nobody can act on.

#: The single table of declared external roots and optional wheels. Read from
#: source rather than imported — see above.
EXTERNAL_ROOTS_TABLE = REPO / "tests" / "_external_roots.py"

#: The assignment inside it this stage reads, and the call the test tree uses.
EXTERNAL_ROOTS_SYMBOL = "EXTERNAL_ROOTS"
EXTERNAL_ROOTS_CALL = "skip_unless("


def read_external_root_declarations(
    table: Path = EXTERNAL_ROOTS_TABLE,
) -> dict[str, dict[str, str]]:
    """The declared roots, parsed out of the test tree's one table."""

    import ast

    tree = ast.parse(table.read_text(encoding="utf-8"), filename=str(table))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign):
            names = [node.target]
        elif isinstance(node, ast.Assign):
            names = list(node.targets)
        else:
            continue
        for name in names:
            if isinstance(name, ast.Name) and name.id == EXTERNAL_ROOTS_SYMBOL:
                return dict(ast.literal_eval(node.value))
    raise ValueError(f"{EXTERNAL_ROOTS_SYMBOL} not found in {table}")


def external_root_users(root: Path = REPO) -> dict[str, list[str]]:
    """name -> the test modules that carry ``@skip_unless(name)``."""

    users: dict[str, list[str]] = {}
    table = (root / "tests" / "_external_roots.py").name
    for path in sorted((root / "tests").glob("*.py")):
        # The table declares the call in its own docstring; it is not a user.
        if path.name == table:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if EXTERNAL_ROOTS_CALL not in text:
            continue
        for chunk in text.split(EXTERNAL_ROOTS_CALL)[1:]:
            quote = chunk[:1]
            if quote not in ("'", '"'):
                continue
            name = chunk[1:].split(quote, 1)[0]
            entry = users.setdefault(name, [])
            if path.name not in entry:
                entry.append(path.name)
    return users


def external_root_present(entry: dict[str, str], root: Path = REPO) -> bool:
    """Is this declaration satisfied on THIS host?"""

    if entry.get("kind") == "module":
        import importlib.util

        try:
            return importlib.util.find_spec(entry["target"]) is not None
        except (ImportError, ValueError):  # pragma: no cover - broken parent package
            return False
    return (root / entry["target"]).exists()


def evaluate_skip_list(*, tier: str = "commit", root: Path = REPO) -> GateResult:
    """The honest list of what this host did not run, and how to get it."""

    try:
        declared = read_external_root_declarations(root / "tests" / "_external_roots.py")
    except (OSError, SyntaxError, ValueError) as exc:
        return GateResult(
            "skip-list", tier, False, "error",
            f"the external-root table is unreadable: {type(exc).__name__}: {exc}",
        )
    users = external_root_users(root)
    absent: list[str] = []
    modules = 0
    lines: list[str] = []
    for name in sorted(declared):
        entry = declared[name]
        carriers = users.get(name, [])
        if external_root_present(entry, root):
            continue
        absent.append(name)
        modules += len(carriers)
        lines.append(
            f"{name}: ABSENT — {entry['target']} ({entry.get('kind', 'path')}); "
            f"{len(carriers)} module(s) skip: {', '.join(carriers) or '(none)'}"
        )
        lines.append(f"    {entry['hint']}")
    unused = sorted(set(users) - set(declared))
    detail = (
        f"{len(declared)} declared external root(s), {len(absent)} absent on this host "
        f"→ {modules} test module(s) skip with a named reason"
    )
    if lines:
        detail += "\n    " + "\n    ".join(lines)
    if unused:
        detail += f"\n    UNDECLARED name(s) used by tests: {', '.join(unused)}"
    # STATUS `pass`, NOT `report`, AND WHY. `hard=False` is what makes this row
    # unable to change an exit code (`GateResult.gating_red`); the status says
    # whether the row DID ITS JOB, and producing the list is the job. It also
    # keeps `tests/test_ci_gate.py`'s "no stage in a clean tier is anything but
    # pass" contract (card XD-1's file, closed and verified — not edited here)
    # exactly as XD-1 left it. An unreadable table returns `error` above, which
    # is visible and still non-gating.
    return GateResult(
        "skip-list", tier, False, "pass", detail,
        extra={
            "declared": sorted(declared),
            "absent": absent,
            "modules_skipped": modules,
            "undeclared_used": unused,
        },
    )


# ---- END CARD GATE-0b ------------------------------------------------------


# ---- CARD HW-6 stopping-envelope (scrum/20260822/task_38) ------------------
#
# THE SENTENCE THIS ROW MAKES EXECUTABLE. HLD 8.8: "'Short TTL' is an evidence
# requirement, not a convenient constant: worst-case candidate age, IPC delay,
# gateway scheduling/watchdog period, vendor braking latency, and sensor/
# localization uncertainty must fit inside the commissioned stopping envelope
# at the active speed regime."  Wave-3 design 6 turns that into a gate:  "the
# RC-4 derivation is re-run with the measured numbers before the leashed stage
# -- that re-run is a gate row, not a note."  This is the row.
#
# ONE OF HLD'S FIVE PHRASES IS AMBIGUOUS AND THIS ROW DISAMBIGUATES IT.
# "Vendor braking latency" can be read as the reaction delay before the robot
# begins to decelerate, or as the whole time to standstill.  The record's term
# is named ``stop_command_to_standstill_s`` because only the second reading is
# safe: a reaction-only number drops the deceleration distance ``v^2/(2 a_b)``
# entirely -- 22 mm at 0.25 m/s with the profile's 1.4 m/s^2, 62 mm at a
# quadruped-realistic 0.5 m/s^2, against a 330 mm envelope whose seeded margin
# is 6 mm.  BOX_DAY_INPUTS.md B2 measures it command-to-standstill.
#
# WHY IT IS SOFT ALMOST ALWAYS.  Three of the five terms cannot be measured
# without the dog.  A row that went red for a term nobody can measure yet
# would be switched off within a week, and a row that PASSED with three terms
# missing would be a lie.  So it has three states: UNMEASURED (soft, and it
# NAMES the terms), FITS (soft, with the arithmetic), and OVER -- hard-red,
# reachable only when every term is measured AND the active regime's sum does
# not fit.  On this desktop it prints UNMEASURED, forever, until a box-day
# record replaces it.
#
# WHY IT READS A FILE AND COMPUTES NOTHING ITSELF.  The arithmetic lives in
# `parcel_robot.bridge.timing` beside the RC-4 derivation it extends, so the
# gate, a commissioning check (HW-12) and a status doc all get the same
# number.  This stage is a file read plus a pure call: no subprocess, no
# pytest, no import of the test tree (card XD-1's lesson), ~2 kB of IO.
#
# CONTAINMENT ASYMMETRY, DECLARED.  `run_commit_tier`'s loop hands
# `hard=stage_name != "skip-list"` to `run_stage` -- that line is inside card
# GATE-0b's region and is not this card's to edit -- so an UNCAUGHT crash in
# this evaluator is reported as a HARD error row even though the row itself is
# soft.  Every expected failure (missing file, unreadable YAML, bad shape) is
# caught below and returned as a non-gating `error`; anything left is a defect
# in this file, and a defect in the gate SHOULD be loud.

#: Set by a test rig or a measurement run to point the row at another record;
#: the resolution order lives in `bridge/timing.py` beside the loader.
STOPPING_ENVELOPE_ROW = "stopping-envelope"


def evaluate_stopping_envelope(
    *, tier: str = "commit", root: Path = REPO, record: Path | None = None
) -> GateResult:
    """Does the measured stop chain fit the commissioned envelope? (HLD 8.8)"""

    from parcel_robot.bridge.timing import (
        derive_envelope_rows_v2,  # CARD GATE-1: six terms, not five (R09/HW-6b)
        resolve_stopping_envelope_record,
    )

    path = record if record is not None else resolve_stopping_envelope_record(root)
    try:
        inputs = load_envelope_inputs_v2(path)  # CARD GATE-1: see its own region
    except (OSError, TypeError, ValueError) as exc:
        # Non-gating on purpose (GATE-0b's trade): a broken evidence file is a
        # visible error, not a red build. `tests/test_hw6_stopping_envelope.py`
        # is what makes a broken SHIPPED record a RED somewhere.
        return GateResult(
            STOPPING_ENVELOPE_ROW, tier, False, "error",
            f"{path}: unreadable stopping-envelope record: {type(exc).__name__}: {exc}",
            extra={"record": str(path)},
        )

    rows = derive_envelope_rows_v2(inputs)  # CARD GATE-1: six-term arithmetic
    active = next(row for row in rows if row.regime == inputs.active_regime)
    lines = [
        ("ACTIVE " if row.regime == inputs.active_regime else "       ") + row.line()
        for row in rows
    ]
    extra = {
        "record": str(path),
        "host": inputs.host,
        "active_regime": inputs.active_regime,
        "state": active.state,
        "missing": list(active.missing),
        # CARD GATE-1: the sixth term's evidence pointer, so a reader can tell a
        # record that predates the term from one that carries it unmeasured.
        "scan_age_provenance": inputs.scan_age_provenance,
        "required_m": active.required_m,
        "envelope_m": active.envelope_m,
        "headroom_m": active.headroom_m,
        "regimes": {
            row.regime: {"state": row.state, "required_m": row.required_m}
            for row in rows
        },
    }
    if active.state == "OVER":
        detail = (
            f"the measured stop chain does NOT fit the commissioned envelope at the "
            f"active regime {active.regime!r}: needs {active.required_m:.3f} m, envelope "
            f"{active.envelope_m:.3f} m, over by {abs(active.headroom_m):.3f} m "
            f"(record {path.name})\n    " + "\n    ".join(lines)
        )
        return GateResult(STOPPING_ENVELOPE_ROW, tier, True, "fail", detail, extra=extra)

    if active.state == "UNMEASURED":
        head = (
            f"UNMEASURED — {', '.join(active.missing)} (record {path.name}, host "
            f"{inputs.host}); no verdict is claimed until every term is measured"
        )
    else:
        head = (
            f"fits at the active regime {active.regime!r}: needs "
            f"{active.required_m:.3f} m of {active.envelope_m:.3f} m, "
            f"{active.headroom_m:.3f} m spare (record {path.name})"
        )
    # STATUS `pass`, NOT `report`, for the same reason card GATE-0b gave: it is
    # `hard=False` that makes a row non-gating, and `tests/test_ci_gate.py`
    # (card XD-1's file, not edited here) holds every stage of a clean tier to
    # `pass`.
    return GateResult(
        STOPPING_ENVELOPE_ROW, tier, False, "pass",
        head + "\n    " + "\n    ".join(lines),
        extra=extra,
    )


# ---- END CARD HW-6 stopping-envelope ---------------------------------------


# ---- CARD GATE-1 six-term envelope read (scrum/20260823/task_5) ------------
#
# WHY THIS EXISTS. The row above was still calling the five-term V1 loader
# while the six-term V2 layer (`derive_envelope_rows_v2` /
# `load_stopping_envelope_record_v2`, landed by task_40) sat beside it unused.
# The ARCH-1 review addendum names the consequence (R09, carried as the HW-6b
# debt): on the day the five HLD 8.8 terms are all measured on the dog, the row
# would print `FITS` with the age of the Mid-360 scan silently absent from the
# sum -- and the leashed and restricted-free envelopes ARE the LiDAR ring, so a
# stale scan is travel already made against an obstacle nobody re-measured. A
# five-term FITS is the one output this row must never be able to produce.
#
# WHY THE READ IS A HELPER AND NOT THREE MORE LINES IN THE EVALUATOR. The
# evaluator's body is inside another card's fenced region; this card's rule is
# that its logic lives in its own region and the region above changes only at
# the call sites (each marked with an inline `CARD GATE-1:` comment). The
# swap is therefore two names and this function. Those inline marks are NOT
# fences: a marker-balance check like the one in `tests/test_hw7_gate_aarch64
# .py` must count the `# ---- CARD GATE-1` form, which is balanced 3 for 3.
#
# WHAT A RECORD WITHOUT THE SIXTH TERM MEANS, DECLARED. `..._v2` refuses a
# record with no top-level `scan_age:` block, because for the writer of a
# record that block is mandatory evidence. For the GATE the honest reading is
# softer and is the whole point of the sentinel: a term nobody wrote down is
# UNMEASURED, not a broken file. So a document that the V1 reader accepts and
# the V2 reader does not is loaded as five measured terms plus an UNMEASURED
# sixth, and the provenance says which record and what the V2 reader objected
# to. A document that BOTH readers refuse is still a shape error and still
# returns the evaluator's non-gating `error` row -- unchanged.
#
# The fallback cannot loosen a verdict: UNMEASURED is the state that claims
# nothing. The only thing it can do is turn an `error` row into an UNMEASURED
# row, which is strictly more informative -- the five terms are still derived,
# printed per regime, and the missing sixth is named.


def load_envelope_inputs_v2(path: Path):
    """Read one stopping-envelope record as SIX terms.

    Returns a `StoppingEnvelopeInputsV2`. Raises exactly what the V1 reader
    raises for a record neither reader can parse, so the evaluator's existing
    `except (OSError, TypeError, ValueError)` row is unchanged.
    """

    from parcel_robot.bridge.timing import (
        UNMEASURED,
        StoppingEnvelopeInputsV2,
        load_stopping_envelope_record,
        load_stopping_envelope_record_v2,
    )

    try:
        return load_stopping_envelope_record_v2(path)
    except (TypeError, ValueError) as exc:
        # Not a bare `except`: OSError (no such file, unreadable) is never a
        # sixth-term question and must reach the caller as the error row.
        base = load_stopping_envelope_record(path)
        return StoppingEnvelopeInputsV2(
            base=base,
            scan_age_s=UNMEASURED,
            scan_age_provenance=(
                f"not readable from {path.name} ({type(exc).__name__}: {exc}); the "
                "record carries the five HLD 8.8 terms only. Measured as the p99 of "
                "`backends/go2.py:Go2Backend.latest_scan_age_s()` under load with the "
                "Mid-360 publishing (box-day B11)."
            ),
        )


# ---- END CARD GATE-1 six-term envelope read --------------------------------


# ---- CARD HW-7 gate-on-aarch64 (scrum/20260822/task_42) --------------------
#
# THE QUESTION THIS ANSWERS. `--tier commit` has only ever run on this desktop
# and on nothing else. The dog's Orin NX is aarch64 with no discrete GPU, and
# three of its four venvs (perception, capture, motion) are deliberately NOT
# the product venv. Run the gate in one of those, or in a bare interpreter, and
# the rows that need something absent do not say so: `tier-coverage` RAISES out
# of `_collect_ids` and is reported as a hard ERROR by the GATE-0 wrapper, and
# `unitree-assets` returns a hard FAIL that reads "scene does not compile:
# ModuleNotFoundError". Neither sentence tells the operator what to install.
#
# WHAT THE MEASUREMENT ACTUALLY FOUND, because the card's premise was that
# CUDA, x86-only wheels and the RTX detector were the obstacle:
#
#   * NO commit-tier stage needs CUDA, a GPU, `onnxruntime` or an x86-only
#     wheel. GATE-0b's clean clone installed `-e '.[dev,voice]'` -- no
#     `perception` extra, therefore no onnxruntime-gpu and no `nvidia-*` -- and
#     reported RESULT: PASS, 10/10 hard gates (task_30/GATE0B_STATUS.md,
#     2026-08-23). Every onnxruntime / sounddevice / pyrealsense2 / cv2 / torch
#     import under `src/` is lazy, inside a function; none is module-level.
#   * MuJoCo IS on aarch64: mujoco 3.12.0 ships
#     cp310/cp312 manylinux_2_28_aarch64 wheels, and both jetson locks pin it
#     (requirements-lock-jetson{,-py312}.txt, card HW-1).
#   * `parcel_robot.runtime` imports with mujoco hidden from the interpreter
#     (measured 2026-08-23). Nine TEST modules do not: they `import mujoco` at
#     module scope with no guard, which is why a mujoco-less venv turns the two
#     collection-wide rows into red rather than into an honest skip.
#
# So the skip decision is made on CAPABILITY, never on `platform.machine()`.
# The architecture is reported because a `--json` artifact with no host line
# cannot be read six months later, not because any row branches on it.
#
# WHY A PRE-CHECK AND NOT A RESCUE. This transform decides BEFORE the evaluator
# runs, and only on an absent capability. It can therefore never turn a red
# into a green: a stage whose requirements are all present is handed through
# UNCHANGED, thunk object and all. The failure mode it must not have -- "the
# suite failed, so call it a skip" -- is structurally impossible here.
#
# WHY THE REQUIREMENTS ARE NARROW. Each entry in `STAGE_REQUIREMENTS` below is
# cited to the line that needs it. A requirement declared too broadly is a
# masking risk, so `assertion-evals` (measured: imports and runs with mujoco
# hidden) and the three node-id stages (measured: none of their six test
# modules imports mujoco) declare only what they use.
#
# CONTAINMENT ASYMMETRY, DECLARED (the same one card HW-6 records). The
# `host` row returns `hard=False` and cannot change an exit code, but the loop
# in `run_commit_tier` passes `hard=stage_name != "skip-list"` to `run_stage`
# -- GATE-0b's line, not this card's -- so an UNCAUGHT crash inside
# `evaluate_host_capabilities` would be reported as a HARD error row. Every
# expected failure below is caught and reported; anything left is a defect in
# this file, and a defect in the gate should be loud.

#: Override for the reported architecture. It exists because there is no
#: aarch64 box and no emulator on this host (measured 2026-08-23: no `docker`,
#: `podman` or `qemu-*` binary; `/proc/sys/fs/binfmt_misc` registers only
#: `python3.14`), so the only way to evaluate the row set as the Orin would see
#: it is to say so out loud. It is ALWAYS printed as an override next to the
#: measured value: an override that looked like a measurement would be worse
#: than no override at all.
HOST_ARCH_ENV = "PARCEL_HOST_ARCH"

# Imported here rather than in the shared header block at the top of the file:
# the header is not this card's to edit, and a mid-file module-level import is
# clean under this repo's ruff selection (verified: no E402 fingerprint).
import contextlib  # see _HW7Recorded below for why this card needs it

#: Where `libportaudio.so.2` may be, in the order a reader should look. The
#: private prefix is what `scripts/env-audio.sh` builds (this host has no
#: system libportaudio2 package); the multiarch directory is where a
#: `sudo apt install libportaudio2` would put it, on either architecture.
PORTAUDIO_SO_ENV = "PARCEL_PORTAUDIO_SO"
PORTAUDIO_CANDIDATE_DIRS: tuple[str, ...] = (
    "~/.local/opt/portaudio/usr/lib/{multiarch}",
    "/usr/lib/{multiarch}",
    "/usr/local/lib",
)


class _HW7Recorded(contextlib.suppress):
    """``contextlib.suppress`` that remembers what it swallowed.

    WHY NOT A ``try/except``. Card HW-4's verifier ruled that a ``# noqa`` in a
    new region is a rule violation here, and every blind ``except`` (``Exception``
    AND ``BaseException``) is BLE001 in this tree's ratchet — so a total
    fail-safe written as an ``except`` clause costs a lint fingerprint. A
    context manager is neither, and ``contextlib.suppress`` already has the
    exact semantics this card needs: swallow ``Exception``, let ``KeyboardInterrupt``
    and ``SystemExit`` through (card GATE-0's rule — an operator's Ctrl-C is not
    a gate result).

    The one thing `suppress` will not do is tell you what it swallowed, and
    card HW-7's correction pass needs precisely that: a probe that fails has to
    say WHY in the `host` row (F3 is about evidence, not conclusions). Hence
    this three-line subclass rather than a bare `contextlib.suppress(Exception)`.
    """

    def __init__(self, *exceptions: type[BaseException]) -> None:
        super().__init__(*exceptions)
        self.error: BaseException | None = None

    def __exit__(self, exctype, excinst, exctb) -> bool:  # type: ignore[override]
        handled = bool(super().__exit__(exctype, excinst, exctb))
        if handled:
            self.error = excinst
        return handled


def _hw7_find_spec(name: str) -> tuple[Any | None, BaseException | None]:
    """``importlib.util.find_spec``, TOTAL: returns ``(spec, error)``, never raises.

    `find_spec` is the same test `tests/_external_roots.py:_present` uses for an
    optional wheel, and it is the reason this probe costs microseconds and has
    no side effects. It can RAISE as well as return ``None`` — a broken parent
    package (`ImportError`), a relative name (`ValueError`), or a meta-path
    finder that refuses with anything at all. The verifier's F2 reproduction
    was exactly that last case: a `sys.meta_path` finder raising `RuntimeError`
    for `mujoco` escaped the old three-class `except` and killed
    `run_commit_tier` before row one. Nothing escapes this.
    """

    import importlib.util

    recorded = _HW7Recorded(Exception)
    spec = None
    with recorded:
        spec = importlib.util.find_spec(name)
    return spec, recorded.error


def _hw7_spec_present(name: str) -> bool:
    """The VERDICT half of the module probe. Seedable on purpose.

    Kept as its own one-line function because it is where a lying probe is
    seeded (the verifier's V1, and this card's own `test_hw7_*` seed): patch
    this, and `host_capabilities` reports the lie — while
    :func:`_hw7_spec_evidence` keeps reporting what `find_spec` ACTUALLY
    returned, so the contradiction shows up in the printed row instead of
    hiding behind it.
    """

    spec, _ = _hw7_find_spec(name)
    return spec is not None


def _hw7_spec_evidence(name: str) -> str:
    """The EVIDENCE half: what was observed, not what was concluded.

    Card HW-7's F3. "mujoco is absent" is a conclusion; on a four-venv Orin it
    cannot be told apart from "you ran the gate in a vendor venv, which is
    expected". `find_spec('mujoco') -> None` under `/usr/bin/python3.10` can.
    """

    spec, error = _hw7_find_spec(name)
    if error is not None:
        return f"importlib.util.find_spec({name!r}) raised {type(error).__name__}: {error}"
    if spec is None:
        return f"importlib.util.find_spec({name!r}) -> None"
    return f"importlib.util.find_spec({name!r}) -> spec at {getattr(spec, 'origin', None) or '(namespace)'}"


def _hw7_portaudio() -> tuple[bool, str]:
    """The PortAudio shared object, by stat. Never `ctypes.util.find_library`.

    `find_library` shells out to `gcc`/`objdump`; a probe that runs a compiler
    is not a probe. This looks where the two install paths actually put the
    file. Reported only -- no gate row depends on it, because nothing in the
    commit tier imports `sounddevice` at collection time.
    """

    import sysconfig

    recorded = _HW7Recorded(Exception)
    looked: list[str] = []
    with recorded:
        multiarch = sysconfig.get_config_var("MULTIARCH") or ""
        explicit = (os.environ.get(PORTAUDIO_SO_ENV) or "").strip()
        if explicit and Path(explicit).exists():
            return True, f"stat {explicit} -> exists (from {PORTAUDIO_SO_ENV})"
        for template in PORTAUDIO_CANDIDATE_DIRS:
            directory = Path(os.path.expanduser(template.format(multiarch=multiarch)))
            candidate = directory / "libportaudio.so.2"
            looked.append(str(candidate))
            if candidate.exists():
                return True, f"stat {candidate} -> exists"
        return False, f"stat -> absent at {len(looked)} path(s): {', '.join(looked)}"
    raised = f"{type(recorded.error).__name__}: {recorded.error}"
    return False, f"the portaudio stat probe raised {raised}"


def _hw7_cuda() -> tuple[bool, str]:
    """Evidence of a CUDA device, and an honest label on the answer.

    UNCONFIRMED ON TEGRA, deliberately. `nvidia-smi` does not ship on a Jetson,
    so `shutil.which("nvidia-smi")` reports ABSENT on the one box in this
    project that definitely has a GPU. The device nodes differ too
    (`/dev/nvidiactl` on a discrete card, `/dev/nvhost-ctrl` on Tegra). This
    returns the evidence it found and says which kind it is; NO gate row
    consumes it, because no commit-tier row needs CUDA.
    """

    import shutil

    recorded = _HW7Recorded(Exception)
    found: list[str] = []
    with recorded:
        found = [path for path in ("/dev/nvidiactl", "/dev/nvhost-ctrl") if Path(path).exists()]
        smi = shutil.which("nvidia-smi")
        if smi:
            found.append(smi)
        if found:
            return True, f"stat/which -> {', '.join(found)}"
        return False, (
            "stat -> no /dev/nvidiactl, no /dev/nvhost-ctrl; which -> no nvidia-smi "
            "(UNCONFIRMED on Tegra: a Jetson has a GPU and ships none of these)"
        )
    return False, f"the cuda probe raised {type(recorded.error).__name__}: {recorded.error}"


def host_capabilities(
    *, root: Path = REPO, env: dict[str, str] | None = None
) -> dict[str, dict[str, object]]:
    """What this host is and what it can run. One table, read by two callers.

    ``kind`` separates the two sorts of entry: a ``fact`` describes the host and
    is never a reason to skip anything; a ``capability`` is stat-or-spec
    checkable and MAY be named in :data:`STAGE_REQUIREMENTS`. ``unskip`` is the
    exact command a reader should run, because "absent" is only half an answer
    (`tests/_external_roots.py`'s rule, applied to the gate's own stages).

    ``evidence`` and ``probe`` are the correction pass's F3: WHAT WAS OBSERVED
    and HOW, beside the conclusion. "mujoco is absent" is a verdict; on a
    four-venv Orin it cannot be told apart from "you ran this in the perception
    venv, which is expected". ``find_spec('mujoco') -> None`` under
    ``/usr/bin/python3.10`` can be. The ``interpreter`` fact carries the second
    half of that: WHICH python was asked.
    """

    import platform
    import sys as _sys

    source = os.environ if env is None else env
    measured_arch = platform.machine()
    override = (source.get(HOST_ARCH_ENV) or "").strip()
    if override:
        arch_detail = f"{override} (OVERRIDE {HOST_ARCH_ENV}; measured {measured_arch})"
    else:
        arch_detail = f"{measured_arch} (measured)"
    libc_name, libc_version = platform.libc_ver()
    try:
        usable_cpus = len(os.sched_getaffinity(0))
    except AttributeError:  # pragma: no cover - not Linux
        usable_cpus = os.cpu_count() or 1
    portaudio_present, portaudio_evidence = _hw7_portaudio()
    cuda_present, cuda_evidence = _hw7_cuda()

    def fact(detail: str) -> dict[str, object]:
        return {"kind": "fact", "present": True, "detail": detail, "unskip": "", "evidence": ""}

    def module(name: str, detail: str, unskip: str) -> dict[str, object]:
        """A capability answered by a spec lookup. Verdict and evidence are
        taken from two independent calls ON PURPOSE: seed the verdict function
        and the evidence still reports what `find_spec` really returned, so a
        lying probe contradicts itself in the printed row (F3/F4)."""

        return {
            "kind": "capability",
            "present": _hw7_spec_present(name),
            "detail": detail,
            "unskip": unskip,
            "probe": "importlib.util.find_spec",
            "module": name,
            "evidence": _hw7_spec_evidence(name),
        }

    def measured(present: bool, detail: str, unskip: str, evidence: str) -> dict[str, object]:
        return {
            "kind": "capability",
            "present": present,
            "detail": detail,
            "unskip": unskip,
            "probe": "path stat",
            "module": "",
            "evidence": evidence,
        }

    table: dict[str, dict[str, object]] = {
        "arch": fact(arch_detail),
        "cpython": fact(f"{platform.python_implementation()} {platform.python_version()}"),
        "libc": fact(f"{libc_name or 'unknown'} {libc_version or '?'}"),
        "cpus": fact(f"{usable_cpus} usable of {os.cpu_count() or '?'}"),
        "repo": fact(str(root)),
        # WHICH python was asked. On the Orin there are four venvs and the
        # answer to "is mujoco here" is different in each; without this line a
        # `--json` artifact cannot say whether an absence was expected.
        "interpreter": fact(f"{_sys.executable} (prefix {_sys.prefix})"),
        "mujoco": module(
            "mujoco",
            "the simulator: scene compilation and the live mutation panel",
            "pip install 'mujoco>=3.3,<4'  (cp310/cp312 aarch64 wheels exist: "
            "mujoco 3.12.0 -- requirements-lock-jetson-py312.txt)",
        ),
        "pytest": module(
            "pytest",
            "every stage that runs a pytest selection or a collection",
            "pip install -e '.[dev]'",
        ),
        "xdist": module(
            "xdist",
            "the default suite's parallel phase (card XD-1)",
            "pip install -e '.[dev]'",
        ),
        "ruff": module(
            "ruff",
            "the pinned-version lint ratchet",
            "pip install -e '.[dev]'  (the version is pinned: ruff==0.16.1)",
        ),
        "portaudio": measured(
            portaudio_present,
            "REPORT ONLY -- no commit-tier row needs it",
            "scripts/env-audio.sh --install   (aarch64: the arm64 .debs, same script)",
            portaudio_evidence,
        ),
        "onnxruntime": module(
            "onnxruntime",
            "REPORT ONLY -- the detector daemon's runtime, never the gate's",
            "x86_64: pip install -e '.[perception]'; aarch64: "
            "scripts/install_perception_jetson.sh (no PyPI aarch64 wheel exists)",
        ),
        "cuda": measured(
            cuda_present,
            "REPORT ONLY -- no commit-tier row needs it",
            "(nothing to un-skip: the commit tier is CPU-only by design)",
            cuda_evidence,
        ),
    }
    return table


#: stage name -> the capabilities it cannot run without. Every entry is cited
#: to the line that needs it; a stage absent from this table is NEVER skipped.
#:
#:   ruff                      `_ruff_fingerprints` / `ruff_version` run
#:                             `[PYTHON, "-m", "ruff", ...]`.
#:   unitree-assets            `import mujoco; mujoco.MjModel.from_xml_path`
#:                             in the scene-compile loop.
#:   hard-safety               `_panel_safety_fields_live` ->
#:                             `scripts.mutation_panel.live_clean_safety_fields`
#:                             re-derives the panel's clean run in-process.
#:   tier-coverage             three `--collect-only` runs of the WHOLE tree via
#:                             `_collect_ids`, which RAISES on a collection
#:                             error; nine test modules import mujoco at module
#:                             scope (test_sim, test_mujoco_lidar,
#:                             test_raycast_lidar, test_dynamic_city,
#:                             test_city_orbit_clearance, test_city_semantics,
#:                             test_scene_assets, test_portal_world,
#:                             test_next_to_band_achievability).
#:   default-suite             the same tree, run rather than collected, in two
#:                             phases under xdist (card XD-1).
#:   the three node-id stages  pytest only. MEASURED 2026-08-23: none of their
#:                             six test modules imports mujoco.
#:
#: NOT here, and why: `assertion-evals` imports `evals.assertions.gate` and runs
#: no pytest -- measured to import and run with mujoco hidden; `release-parity`,
#: `stopping-envelope`, `skip-list` and `host` are file reads and arithmetic.
STAGE_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "ruff": ("ruff",),
    "unitree-assets": ("mujoco",),
    "hard-safety": ("mujoco",),
    "tier-coverage": ("pytest", "mujoco"),
    "model-off-non-inferiority": ("pytest",),
    "release-parity-integrity": ("pytest",),
    "owner-store-isolation": ("pytest",),
    "default-suite": ("pytest", "xdist", "mujoco"),
}


def hw7_skip_result(
    stage: str, missing: list[str], caps: dict[str, dict[str, object]], tier: str
) -> GateResult:
    """The typed SKIP row: what did not run, WHAT WAS OBSERVED, and how to fix it.

    Correction pass F3. The first version of this row printed the capability's
    PURPOSE ("mujoco is absent (the simulator: scene compilation …)"). That is
    the conclusion restated. What a reader of a `--json` artifact from a
    four-venv Orin actually needs is the observation and the interpreter it was
    made in: `find_spec('mujoco') -> None` under `/usr/bin/python3.10` is an
    expected vendor-venv run; the same line under `~/parcel-venv/bin/python` is
    a defect. Both now print, in the row and in `extra`.
    """

    parts = []
    evidence: dict[str, str] = {}
    for name in missing:
        entry = caps.get(name, {})
        observed = str(entry.get("evidence") or "(no evidence recorded)")
        evidence[name] = observed
        parts.append(
            f"{name} is absent — evidence: {observed}; needed for "
            f"{entry.get('detail', 'no detail')}; "
            f"un-skip: {entry.get('unskip', '(unknown)')}"
        )
    arch = str(caps.get("arch", {}).get("detail", "unknown"))
    interpreter = str(caps.get("interpreter", {}).get("detail", "unknown interpreter"))
    detail = f"SKIPPED on this host [{arch}; {interpreter}]: " + " | ".join(parts)
    return GateResult(
        stage, tier, True, "skip", detail,
        extra={
            "hw7_missing": list(missing),
            "hw7_arch": arch,
            "hw7_interpreter": interpreter,
            "hw7_evidence": evidence,
        },
    )


def hw7_apply_host_skips(
    stages: tuple[tuple[str, Callable[[], Any]], ...],
    *,
    tier: str,
    caps: dict[str, dict[str, object]] | None = None,
) -> tuple[tuple[str, Callable[[], Any]], ...]:
    """Replace the thunk of every stage this host cannot run with a typed SKIP.

    IDENTITY when nothing is missing -- same names, same order, same thunk
    OBJECTS -- so on a provisioned host (this desktop, `ubuntu-latest`, and the
    Orin's product venv, which installs mujoco because it is a core dependency)
    this function changes nothing at all, and `tests/test_ci_gate.py`'s
    "every stage in a clean tier is `pass`" contract is untouched.
    """

    table: dict[str, dict[str, object]] | None = caps
    if table is None:
        # THE ONE PLACE IN THIS CARD THAT IS NOT INSIDE `run_stage`. This
        # transform runs BEFORE the loop, so an exception here kills the whole
        # runner before a single row prints — card GATE-0's original disease,
        # reintroduced by a reporting feature. The first version caught four
        # named classes; the verifier (F2) drove a `sys.meta_path` finder that
        # raises `RuntimeError` for `mujoco` straight through it and the runner
        # died with no rows and no JSON. The suppression is now TOTAL over
        # `Exception` (KeyboardInterrupt and SystemExit still propagate, card
        # GATE-0's rule) and it is a context manager rather than an `except`
        # clause, so it costs no BLE001 fingerprint and needs no directive.
        #
        # A probe that cannot answer declares NOTHING: the tier runs exactly as
        # it did before this card existed. The failure is not lost — the `host`
        # row re-runs the same probe under `run_stage` and reports it as a
        # non-gating `error` carrying the exception text.
        recorded = _HW7Recorded(Exception)
        with recorded:
            table = host_capabilities()
        if recorded.error is not None or table is None:
            return tuple(stages)
    out: list[tuple[str, Callable[[], Any]]] = []
    for name, thunk in stages:
        missing = [
            required
            for required in STAGE_REQUIREMENTS.get(name, ())
            if not table.get(required, {}).get("present", False)
        ]
        if not missing:
            out.append((name, thunk))
            continue
        out.append((name, lambda n=name, m=missing: hw7_skip_result(n, m, table, tier)))
    return tuple(out)


def evaluate_host_capabilities(*, tier: str = "commit", root: Path = REPO) -> GateResult:
    """The `host` row: which box produced this verdict, and what it can run.

    `hard=False` -- it reports, it never gates. `status="pass"` because the
    status says whether the row DID ITS JOB (producing the list is the job),
    which is also how card GATE-0b's `skip-list` row states itself and what
    keeps `tests/test_ci_gate.py`'s clean-tier contract green.
    """

    # TOTAL, and with the exception text kept. The earlier version named four
    # classes and a `RuntimeError` from a hostile meta-path finder walked past
    # it (correction pass F2). `_HW7Recorded` is `contextlib.suppress(Exception)`
    # that remembers what it swallowed: no `except` clause (so no BLE001, so no
    # directive), KeyboardInterrupt and SystemExit still propagate, and the row
    # can still say WHAT failed rather than merely THAT it did.
    recorded = _HW7Recorded(Exception)
    caps: dict[str, dict[str, object]] | None = None
    with recorded:
        caps = host_capabilities(root=root)
    if recorded.error is not None or caps is None:
        exc = recorded.error
        return GateResult(
            "host", tier, False, "error",
            "the host probe failed, so this run declared NO skips and every "
            f"stage ran as it would have without card HW-7: "
            f"{type(exc).__name__ if exc else 'no result'}: {exc if exc else '(probe returned None)'}",
            extra={"hw7_probe_error": f"{type(exc).__name__}: {exc}" if exc else "returned None"},
        )
    facts = [f"{name}={entry['detail']}" for name, entry in caps.items() if entry["kind"] == "fact"]
    absent = sorted(
        name
        for name, entry in caps.items()
        if entry["kind"] == "capability" and not entry["present"]
    )
    gating_absent = sorted(
        {name for required in STAGE_REQUIREMENTS.values() for name in required} & set(absent)
    )
    skipped = sorted(
        stage
        for stage, required in STAGE_REQUIREMENTS.items()
        if any(name in gating_absent for name in required)
    )
    detail = "; ".join(facts)
    detail += f" | capabilities absent: {', '.join(absent) if absent else 'none'}"
    detail += f" | rows this host will SKIP: {', '.join(skipped) if skipped else 'none'}"
    for name in gating_absent:
        detail += f"\n    {name}: evidence: {caps[name].get('evidence') or '(none)'}"
        detail += f"\n    {name}: un-skip: {caps[name]['unskip']}"
    return GateResult(
        "host", tier, False, "pass", detail,
        extra={
            "capabilities": caps,
            "absent": absent,
            "skipped_stages": skipped,
        },
    )


# ---- END CARD HW-7 gate-on-aarch64 -----------------------------------------


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


# === GATE-0 region (card scrum/20260822/task_20) — the unitree-assets stage ==
def _under_repo(path: Path) -> bool:
    return REPO == path or REPO in path.parents


def _repo_rel(path: Path) -> str:
    """Repo-relative posix path, or the absolute path when it is outside."""

    return path.relative_to(REPO).as_posix() if _under_repo(path) else str(path)


def _git_paths(*args: str) -> tuple[set[str], str | None]:
    """``git ls-files`` output as a set of repo-relative posix paths.

    Card GATE-0. Returns ``(paths, error)``; ``error`` is a short reason when
    git could not answer (no git binary, not a work tree — a tarball export),
    in which case the caller records the closure sub-check as SKIPPED rather
    than passing it vacuously.
    """

    try:
        proc = subprocess.run(
            ["git", *args], cwd=str(REPO), capture_output=True, check=False
        )
    except OSError as exc:  # no git binary at all
        return set(), f"{type(exc).__name__}: {exc}"
    if proc.returncode != 0:
        return set(), (proc.stderr.decode("utf-8", "replace").strip() or "git failed")[:160]
    out = proc.stdout.decode("utf-8", "replace")
    return {name for name in out.split("\0") if name}, None


def evaluate_unitree_assets(
    *,
    root: Path = UNITREE_ROOT,
    provenance: Path = UNITREE_PROVENANCE,
    expected_revision: str = UNITREE_EXPECTED_REVISION,
    scene_dir: Path = PRODUCT_SCENE_DIR,
    tier: str = "commit",
) -> GateResult:
    """The vendored Go2 MJCF pack is complete, pinned, closed, and compiles.

    Card GATE-0 (``scrum/20260822/task_20``), the narrowed execution of the Sol
    session's IG-1. Five things, in the order they can go wrong:

    1. **Pinned.** ``PROVENANCE.json.upstream_revision`` must equal
       :data:`UNITREE_EXPECTED_REVISION`, a constant this file holds
       independently — a replacement pack that is self-consistent at some other
       revision must still redden.
    2. **Safe paths.** No manifest entry may be absolute, contain ``..``, or
       carry a ``.git`` component. Checked BEFORE the path is joined to disk.
    3. **Byte-exact.** Every payload exists at its declared size and sha256.
    4. **Closed.** The set of files the parent repository would ship under
       ``third_party/`` equals the manifest plus the manifest itself — an extra
       file smuggled through the ``.gitignore`` carve-out is a hard red, and so
       is a tracked gitlink (the 76 MB nested upstream clone must never become
       a submodule pointer).
    5. **Compiles.** Every product scene that includes the pack is compiled by
       MuJoCo. GEOMETRY ONLY: ``MjModel.from_xml_path`` and nothing else — no
       renderer is constructed, no data is stepped, and no model is run over the
       pixels, because one of these scenes is held out for a generalization
       claim (``tests/test_held_out_scene.py``).

    Runs BEFORE ``hard-safety`` because ``hard-safety`` is the gate that used to
    die on a missing pack, with a traceback instead of a result.
    """

    name = "unitree-assets"
    problems: list[str] = []
    checks: list[str] = []

    if not provenance.is_file():
        return GateResult(
            name, tier, True, "fail",
            f"{_repo_rel(provenance)} is MISSING — the vendored Go2 "
            "MJCF pack is not in this checkout; both product scenes are uncompilable",
        )
    try:
        manifest = json.loads(provenance.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return GateResult(name, tier, True, "fail", f"PROVENANCE.json is unparseable: {exc}")

    revision = manifest.get("upstream_revision")
    pinned_ok = revision == expected_revision
    checks.append(f"upstream_revision {str(revision)[:12]} == pin: {pinned_ok}")
    if not pinned_ok:
        problems.append(
            f"PROVENANCE.json upstream_revision={revision!r} but this gate pins "
            f"{expected_revision!r}"
        )

    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        problems.append("PROVENANCE.json lists no payload files")
        entries = []

    declared: set[str] = set()
    total_bytes = 0
    for entry in entries:
        rel = entry.get("path") if isinstance(entry, dict) else None
        parts = rel.split("/") if isinstance(rel, str) else []
        unsafe = (
            not isinstance(rel, str)
            or not rel
            or rel.startswith("/")
            or "\\" in rel
            or ":" in rel
            or "" in parts
            or ".." in parts
            or ".git" in parts
        )
        if unsafe:
            problems.append(f"unsafe manifest path {rel!r} (absolute, '..', or .git component)")
            continue
        declared.add(rel)
        target = root / rel
        if not target.is_file():
            problems.append(f"manifest payload is missing from the checkout: {rel}")
            continue
        blob = target.read_bytes()
        total_bytes += len(blob)
        if len(blob) != entry.get("size_bytes"):
            problems.append(f"{rel}: {len(blob)} bytes on disk, manifest says {entry.get('size_bytes')}")
        digest = hashlib.sha256(blob).hexdigest()
        if digest != entry.get("sha256"):
            problems.append(
                f"{rel}: sha256 {digest[:12]}... != manifest {str(entry.get('sha256'))[:12]}..."
            )
    checks.append(
        f"payload: {len(declared)} manifest file(s), {total_bytes / 1_048_576:.1f} MiB on disk"
    )

    rel_root = _repo_rel(root) if _under_repo(root) else None
    if rel_root is None:
        # A synthetic pack under tmp (the seeded self-tests) has no parent repo
        # to be closed against. Recorded as skipped, never as passed.
        tracked = untracked = set()
        git_err: str | None = "pack root is outside the repository"
    else:
        tracked, tracked_err = _git_paths("ls-files", "-z", "--", rel_root)
        untracked, untracked_err = _git_paths(
            "ls-files", "-z", "--others", "--exclude-standard", "--", rel_root
        )
        git_err = tracked_err or untracked_err
    if git_err is not None:
        checks.append(f"shipping closure: SKIPPED ({git_err})")
    else:
        shipped = tracked | untracked
        expected = {f"{rel_root}/{rel}" for rel in declared}
        expected.add(_repo_rel(provenance))
        extra = sorted(shipped - expected)
        hidden = sorted(expected - shipped)
        checks.append(
            f"shipping closure: {len(shipped)} path(s) under {rel_root}/, "
            f"unmanifested={len(extra)} hidden={len(hidden)}"
        )
        if extra:
            problems.append(
                f"file(s) under {rel_root}/ that the manifest does not declare: {extra[:6]}"
            )
        if hidden:
            problems.append(
                f"manifest file(s) the parent repo would NOT ship (still ignored): {hidden[:6]}"
            )
        staged, staged_err = _git_paths("ls-files", "-s", "-z", "--", rel_root)
        if staged_err is None:
            links = sorted(row.split("\t", 1)[-1] for row in staged if row.startswith("160000"))
            if links:
                problems.append(f"gitlink(s) tracked under {rel_root}/ (nested repo): {links}")
            checks.append(f"gitlinks under {rel_root}/: {len(links)}")

    scenes = sorted(
        path
        for path in scene_dir.glob("*.xml")
        if UNITREE_INCLUDE_TOKEN in path.read_text(encoding="utf-8", errors="ignore")
    )
    if not scenes:
        problems.append(
            f"no scene under {_repo_rel(scene_dir)} includes the pack — "
            "this gate would be certifying nothing"
        )
    for scene in scenes:
        started = time.perf_counter()
        try:
            import mujoco

            model = mujoco.MjModel.from_xml_path(str(scene))
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            problems.append(
                f"{scene.name} does not compile: {type(exc).__name__}: "
                f"{str(exc).splitlines()[0][:200] if str(exc) else '(no message)'}"
            )
            continue
        checks.append(
            f"{scene.name}: compiled {model.ngeom} geom / {model.nmesh} mesh in "
            f"{time.perf_counter() - started:.2f}s"
        )

    detail = " | ".join(checks)
    if problems:
        return GateResult(
            name, tier, True, "fail", "; ".join(problems),
            extra={"checks": checks, "problems": problems},
        )
    return GateResult(name, tier, True, "pass", detail, extra={"checks": checks})
# === end GATE-0 region =====================================================


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


# === GATE-0 region (card scrum/20260822/task_20) — the ruff verdict is pinned =
def ruff_version(root: Path = REPO) -> str | None:
    """The version of the ruff this gate is about to run, or ``None``.

    Card GATE-0. A ratchet compares today's fingerprints against a recorded set,
    so it silently means different things under different linters: the same tree
    yields **7** fingerprints on ruff 0.16.x and roughly **51** on 0.15.x. With
    ruff range-pinned (``>=0.12,<1``) and the baseline recording no version, the
    commit verdict depended on whichever wheel pip happened to resolve. The
    version is now pinned in the dev extra AND stamped into the baseline, and a
    mismatch is an ERROR rather than a verdict.
    """

    try:
        proc = subprocess.run(
            [PYTHON, "-m", "ruff", "--version"],
            cwd=str(root), env=_base_env(), capture_output=True, text=True, check=False,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    parts = (proc.stdout or "").strip().split()
    return parts[1] if len(parts) >= 2 and parts[0] == "ruff" else None


def evaluate_ruff(*, baseline_path: Path = RUFF_BASELINE, tier: str = "commit") -> GateResult:
    """Fail only on ruff violations whose (file, rule) is not in the baseline.

    The repo carries pre-existing ruff debt in modules this card does not own
    (storefront, uwb, route_memory, ...); a hard ``ruff check`` would block every
    commit. The ratchet keeps ruff a real per-commit gate — new code must be
    clean — while the debt is burned down separately (it is enumerated in the
    baseline file and in docs/CI.md as a handoff).

    Card GATE-0: the ratchet REFUSES to render a verdict under a ruff other than
    the one its baseline was recorded on. A baseline is a set of (file, rule)
    pairs; a different linter has a different rule set, so comparing across
    versions is comparing two different questions and calling the answer green.
    """

    current, proc = _ruff_fingerprints()
    if proc.returncode not in (0, 1):  # 0 clean, 1 = violations found; else crash
        return GateResult("ruff", tier, True, "error", (proc.stderr or "ruff failed").strip()[:400])
    if not baseline_path.exists():
        return GateResult(
            "ruff", tier, True, "error",
            f"no ruff baseline at {baseline_path.name}; run --update-ruff-baseline",
        )
    doc = json.loads(baseline_path.read_text(encoding="utf-8"))
    pinned = doc.get("ruff_version")
    running = ruff_version()
    if not pinned:
        return GateResult(
            "ruff", tier, True, "error",
            f"{baseline_path.name} records no ruff_version, so its {len(doc.get('fingerprints', []))} "
            "fingerprint(s) cannot be attributed to a linter; re-pin with --update-ruff-baseline",
        )
    if running is None:
        return GateResult(
            "ruff", tier, True, "error",
            "could not read `ruff --version`; the ratchet will not render a verdict "
            f"under an unknown linter (baseline was recorded on ruff {pinned})",
        )
    if running != pinned:
        return GateResult(
            "ruff", tier, True, "error",
            f"ruff {running} is running but {baseline_path.name} was recorded on ruff "
            f"{pinned}; the rule sets differ, so the ratchet is not comparable. Install "
            f"the pinned ruff (pyproject dev extra) or re-pin with --update-ruff-baseline",
            extra={"running": running, "baseline": pinned},
        )
    baseline = set(doc.get("fingerprints", []))
    new = sorted(set(current) - baseline)
    detail = f"ruff {running}: {len(current)} violation(s), baseline {len(baseline)}, new {len(new)}"
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
            "an empty list; regenerate with `ci_gate.py --update-ruff-baseline`. "
            "ruff_version is load-bearing (card GATE-0): the same tree yields 7 "
            "fingerprints on 0.16.x and ~51 on 0.15.x, so evaluate_ruff refuses to "
            "compare across versions. Keep it equal to the pyproject dev-extra pin."
        ),
        "ruff_version": ruff_version(),
        "count": len(current),
        "fingerprints": current,
    }
    baseline_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {baseline_path} with {len(current)} fingerprint(s) on ruff {payload['ruff_version']}")
    return 0
# === end GATE-0 region =====================================================


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


# === GATE-0 region (card scrum/20260822/task_20) — per-stage containment ====
#: Bounded traceback tail carried on an errored stage. Bounded because a gate
#: report is read by humans and pasted into status docs.
STAGE_TRACEBACK_TAIL_CHARS = 1400

#: The stage names ``run_commit_tier`` must produce on EVERY run, crash or not.
#: ``tests/test_ci_gate.py`` seeds the first evaluator to raise and asserts the
#: produced names still equal this tuple; that is the containment contract, and
#: this literal makes adding or dropping a stage a visible edit.
COMMIT_TIER_STAGE_NAMES: tuple[str, ...] = (
    "ruff",
    "unitree-assets",
    "hard-safety",
    "release-parity",
    "assertion-evals",
    "tier-coverage",
    # ---- CARD HW-6 stopping-envelope (scrum/20260822/task_38) -------------
    # Named here because this literal is the contract `tests/test_ci_gate.py`
    # holds `run_commit_tier` to — the shape card GATE-0b used to register a
    # stage from a helper region without editing card XD-1's test file.
    # Placed with the cheap deterministic checks, before the pytest stages,
    # because it is a 2 kB file read that can hard-fail: fast-fail signal.
    "stopping-envelope",
    # ---- END CARD HW-6 stopping-envelope -----------------------------------
    "model-off-non-inferiority",
    "release-parity-integrity",
    "owner-store-isolation",
    "default-suite",
    # ---- CARD GATE-0b skip-list reporting (scrum/20260822/task_30) --------
    # A REPORT row (hard=False), printed last so the skip list sits directly
    # above RESULT. Named here because this literal is the contract
    # `tests/test_ci_gate.py` holds `run_commit_tier` to.
    "skip-list",
    # ---- END CARD GATE-0b --------------------------------------------------
    # ---- CARD HW-7 gate-on-aarch64 (scrum/20260822/task_42) ---------------
    # LAST, beside the other report-only row, and NOT first — which is where a
    # legend belongs and where this row started. `tests/test_ci_gate.py`
    # (card XD-1's file, closed, not edited here) seeds the FIRST evaluator to
    # raise and then asserts `payload["gates"][0]["status"] == "error"`, so
    # position 0 is contractually the first HARD gate. Being second-to-last is
    # no loss: `summarize` prints every row and then RESULT, so "which box is
    # this" and "what did it not run" end up together, directly above the
    # verdict. Named here because this literal is the contract `run_commit_tier`
    # is held to — the shape cards GATE-0b and HW-6 used to register a stage
    # from a helper region without touching that test file.
    "host",
    # ---- END CARD HW-7 gate-on-aarch64 -------------------------------------
)


def run_stage(
    name: str,
    evaluate: Callable[[], GateResult | list[GateResult]],
    *,
    tier: str,
    hard: bool = True,
) -> list[GateResult]:
    """Run one gate stage so that nothing it does can end the run.

    Card GATE-0. ``run_commit_tier`` used to be a straight-line list build, so
    the first evaluator that raised took the whole runner with it: on a fresh
    clone ``evaluate_hard_safety`` hit the gitignored Go2 MJCF about a second
    in, and the traceback skipped every later gate, the summary, AND ``--json``.
    A gate that cannot report its own crash reports nothing at all, which is
    strictly worse than reporting red.

    ``Exception``, never ``BaseException``: an operator's Ctrl-C is not a gate
    result, so ``KeyboardInterrupt`` and ``SystemExit`` still propagate.

    The contained stage becomes a hard ``error`` result, so the process exit
    stays non-zero — containment reports the failure, it does not forgive it.
    """

    try:
        produced = evaluate()
    except Exception as exc:  # noqa: BLE001 - deliberate: converted, not swallowed
        message = str(exc).splitlines()[0][:200] if str(exc) else "(no message)"
        return [
            GateResult(
                name, tier, hard, "error",
                f"{type(exc).__name__}: {message} "
                "[stage contained by the GATE-0 wrapper; later gates still ran]",
                extra={"traceback_tail": traceback.format_exc()[-STAGE_TRACEBACK_TAIL_CHARS:]},
            )
        ]
    return list(produced) if isinstance(produced, list) else [produced]


def run_commit_tier() -> list[GateResult]:
    tier = "commit"
    # Card P0-E (scrum/20260822/task_5): the commit tier is the SAFETY CORE plus
    # the cheap truth checks. The evidence ratchets — frozen-digest sentinels,
    # the latency and follow-bench ledgers, frozen-digest integrity,
    # mutation-panel freshness, the latency percentile pins — moved to the
    # nightly tier, where they still gate. They protect claims, not the robot,
    # and for the prototype they reddened on doc edits and scene retunes.
    #
    # Card GATE-0: the table below is deferred (each entry is a thunk) and every
    # entry runs under ``run_stage``, so one exploding evaluator costs exactly
    # one ERROR row and the other nine still report.
    # Cheap deterministic checks first (fast-fail signal without waiting on pytest).
    stages: tuple[tuple[str, Callable[[], GateResult | list[GateResult]]], ...] = (
        ("ruff", lambda: evaluate_ruff(tier=tier)),
        # Card GATE-0: the simulator payload, BEFORE hard-safety — hard-safety is
        # the gate that used to die on it.
        ("unitree-assets", lambda: evaluate_unitree_assets(tier=tier)),
        ("hard-safety", lambda: evaluate_hard_safety(tier=tier)),
        ("release-parity", lambda: evaluate_release_parity(tier=tier)),
        ("assertion-evals", lambda: evaluate_assertion_evals(tier=tier, k=1)),
        # Card R26: cheap (three collections, no execution) and it is the only gate
        # that can see a whole tier going dark.
        ("tier-coverage", lambda: evaluate_tier_coverage(tier=tier)),
        # ---- CARD HW-6 stopping-envelope (scrum/20260822/task_38) ---------
        # Pure: one YAML read plus arithmetic from `bridge/timing.py`. Soft in
        # both its normal states (UNMEASURED on any host that has not measured
        # the dog, FITS when it has); HARD-red only when every term is measured
        # AND the active regime's sum exceeds its envelope. It sits here, ahead
        # of the pytest stages, so an over-budget envelope is reported in the
        # first second rather than after the suite.
        ("stopping-envelope", lambda: evaluate_stopping_envelope(tier=tier)),
        # ---- END CARD HW-6 stopping-envelope -------------------------------
        # Targeted hard-gate pytest selections (small, fast).
        ("model-off-non-inferiority",
         lambda: _pytest_gate("model-off-non-inferiority", tier, MODEL_OFF_NODE_IDS, timeout=900)),
        ("release-parity-integrity",
         lambda: _pytest_gate("release-parity-integrity", tier, RELEASE_PARITY_NODE_IDS, timeout=600)),
        ("owner-store-isolation",
         lambda: _pytest_gate("owner-store-isolation", tier, OWNER_STORE_NODE_IDS, timeout=900)),
        # ---- CARD XD-1 default-suite row (scrum/20260822/task_14) ----------
        # THE THIRD AND LAST XD-1 HUNK IN THIS FILE, and the only one inside
        # GATE-0's containment region — it is a call site, so it cannot live
        # anywhere else. It changes ONE tuple: the `default-suite` stage now
        # calls the two-phase evaluator instead of `_pytest_gate`. The stage
        # NAME is unchanged, so `COMMIT_TIER_STAGE_NAMES`, `run_stage`'s
        # containment and every `--json` consumer are untouched; no other
        # stage in this tuple is XD-1's.
        #
        # Two phases, `-n min(cpu_count, XDIST_MAX_WORKERS)` then the
        # wall-clock assertions serially; see the XD-1 runner region above for
        # why the two marker expressions are derived from COMMIT_MARKERS and
        # not written out twice, and why the worker count is capped rather
        # than `auto`. (Latest recorded serial figure: 9,259 passed in 407 s.)
        ("default-suite", lambda: evaluate_default_suite(tier=tier, timeout=1800)),
        # ---- END CARD XD-1 default-suite row -------------------------------
        # ---- CARD GATE-0b skip-list reporting (scrum/20260822/task_30) -----
        # LAST, and deliberately after the suite: the reader has just seen "32
        # skipped" go by and this is the line that says which 32 and why. Pure
        # (file reads only), report-only, cannot change the exit code.
        ("skip-list", lambda: evaluate_skip_list(tier=tier)),
        # ---- END CARD GATE-0b ----------------------------------------------
        # ---- CARD HW-7 gate-on-aarch64 (scrum/20260822/task_42) -----------
        # Pure: `platform` values, a handful of `find_spec` lookups and three
        # path stats, ~2 ms. Last, with the skip list, so the bottom of a
        # `--json` artifact answers "which machine, and what did it not run"
        # in two adjacent rows. Report-only: `hard=False`, it cannot change an
        # exit code.
        ("host", lambda: evaluate_host_capabilities(tier=tier)),
        # ---- END CARD HW-7 gate-on-aarch64 ---------------------------------
    )
    # ---- CARD HW-7 gate-on-aarch64 (scrum/20260822/task_42) ---------------
    # THE ONE HOOK THAT REACHES EVERY STAGE. A stage whose declared capability
    # is absent on this host has its thunk replaced by a typed SKIP row that
    # names the capability and the command that un-skips it; a stage whose
    # requirements are all present is handed through UNCHANGED (same name, same
    # order, same thunk object), which is why this line is a no-op on this
    # desktop, on `ubuntu-latest` and on the Orin's product venv.
    #
    # It sits HERE, between the tuple and the loop, for a reason that is about
    # ownership as much as design: the individual call sites belong to other
    # closed cards — `default-suite` is inside card XD-1's fence, `skip-list`
    # inside GATE-0b's, `stopping-envelope` inside HW-6's — and wrapping them
    # one by one would mean editing three other cards' regions. One transform
    # over the whole tuple touches none of them and covers all of them.
    stages = hw7_apply_host_skips(stages, tier=tier)
    # ---- END CARD HW-7 gate-on-aarch64 -------------------------------------
    results: list[GateResult] = []
    for stage_name, evaluate in stages:
        # ---- CARD GATE-0b skip-list reporting (scrum/20260822/task_30) -----
        # `skip-list` is the one report-only row in this tier. The evaluator
        # already returns `hard=False`; this passes the same hardness to
        # `run_stage`, so a CRASH in the reporting row is contained and printed
        # WITHOUT turning a green tier red — a row that only describes what did
        # not run must not be able to fail the build.
        results.extend(
            run_stage(stage_name, evaluate, tier=tier, hard=stage_name != "skip-list")
        )
        # ---- END CARD GATE-0b ----------------------------------------------
    return results
# === end GATE-0 region =====================================================


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
    # Card GATE-0: the same simulator-payload closure the commit tier runs. The
    # superset invariant is executable (tests/test_ci_gate.py), so this is not
    # an optional echo.
    results.append(evaluate_unitree_assets(tier=tier))
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


# ---- CARD GATE-1 incomplete exit status (scrum/20260823/task_5) ------------
#
# THE DEFECT, IN ONE SENTENCE. `GateResult.is_red` is `status in {fail, error}`
# and `main()` returned `1 if any(gating_red) else 0`, so a host where a HARD
# row could not run at all -- a typed skip -- exited **0**. The rows said
# `[  skip] HARD`, the summary (fixed by task_42) said "N green, M SKIPPED on
# this host", and the exit code, the only thing an automation reads, said the
# same thing it says for a fully green run. The review addendum reproduced it
# as T12: "a CI consumer keying on the exit code reads a skipping host as
# green."
#
# WHY A THIRD CODE AND NOT A RED. A skip is not a failure: three of the dog's
# four venvs are deliberately absent on this desktop and on the Orin, and a
# card that turned "mujoco is not installed here" into a red build would be
# switched off within the week -- the same argument that made the stopping row
# soft. But it is not a pass either. Incomplete is its own answer and gets its
# own number, so a caller can choose: `rc == 0` for "everything ran and was
# green", `rc < 2` for "nothing is broken", `rc != 0` for "do not promote".
#
# PRECEDENCE, DECLARED. Red wins. A run with a red row AND a skipped row exits
# 1, because the red is the actionable fact and an operator who sees 2 would go
# looking for a missing tool instead of a broken gate.
#
# WHAT DID NOT CHANGE. `gating_red`, `is_red`, the per-row statuses, the stage
# order, and every character of `summarize`'s output. The summary sentence was
# already truthful on both branches; this is the other half of the same repair.

#: Every hard gate ran and none is red.
GATE_EXIT_GREEN = 0
#: At least one hard gate is `fail` or `error`. Takes precedence over 2.
GATE_EXIT_RED = 1
#: Nothing is red, but at least one hard gate did not run on this host.
GATE_EXIT_INCOMPLETE = 2


def hard_skips(results: list[GateResult]) -> list[GateResult]:
    """The HARD rows that did not run here -- the same set the summary names."""

    return [r for r in results if r.hard and r.status == "skip"]


def gate_exit_code(results: list[GateResult]) -> int:
    """0 green / 1 red / 2 incomplete. The one place the mapping is written."""

    if any(r.gating_red for r in results):
        return GATE_EXIT_RED
    return GATE_EXIT_INCOMPLETE if hard_skips(results) else GATE_EXIT_GREEN


# ---- END CARD GATE-1 incomplete exit status --------------------------------


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
        # ---- CARD HW-7 gate-on-aarch64 (scrum/20260822/task_42) -----------
        # THE ONE LINE AN OPERATOR READS MUST NOT LIE ON A SKIPPING HOST.
        # Until this card there was no way for a hard gate to end in any state
        # but pass/fail/error, so "every hard gate green" was true whenever
        # nothing was gating-red. A typed SKIP breaks that: on a venv without
        # mujoco this sentence used to print directly underneath four
        # `[  skip] HARD` rows (the verifier's F1 reproduction). The per-row
        # output and the JSON were already truthful; the summary was not.
        #
        # NOT verdict logic: `gating_red` is untouched, the exit code is
        # untouched, and this branch is still the PASS branch. Only the
        # sentence changes, and only when a hard row actually skipped — with no
        # skips the string is byte-identical to what it has always been, which
        # is pinned by a test on both branches. Touch authorised by the
        # integrator (parcel-6c) because `summarize` is unfenced shared
        # reporting code.
        #
        # The FAIL branch above is deliberately NOT changed: "N hard gate(s)
        # red: …" is a true sentence whether or not other rows skipped, and the
        # skips are printed above it. Only the PASS branch could state a
        # falsehood.
        hard_skipped = [r for r in results if r.hard and r.status == "skip"]
        if hard_skipped:
            green = len([r for r in results if r.hard and r.status == "pass"])
            lines.append(
                f"RESULT: PASS — {green} hard gate(s) green, "
                f"{len(hard_skipped)} SKIPPED on this host: "
                + ", ".join(r.name for r in hard_skipped)
            )
        else:
            lines.append("RESULT: PASS — every hard gate green.")
        # ---- END CARD HW-7 gate-on-aarch64 ---------------------------------
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
    # ---- CARD GATE-1 incomplete exit status (scrum/20260823/task_5) --------
    # `incomplete` is emitted on every run, true and false alike: a key that
    # appears only when it is true cannot be told apart from an old gate that
    # never wrote it, and this field exists precisely for a machine.
    if args.json:
        print(json.dumps(
            {
                "tier": args.tier,
                "elapsed_s": elapsed,
                "gates": [r.as_dict() for r in results],
                "incomplete": bool(hard_skips(results)),
            },
            indent=2, sort_keys=True,
        ))
    return gate_exit_code(results)
    # ---- END CARD GATE-1 incomplete exit status ----------------------------


if __name__ == "__main__":
    raise SystemExit(main())
