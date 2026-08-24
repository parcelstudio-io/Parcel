# A4 SPINE — executor status (Opus) · 2026-08-24 · HEAD f1a6a92 · NOT COMMITTED

Card: `IMPLEMENTATION_PLAN.md` row A4 · HLD Gate 2
(`research/20260824/PORTABLE_LIVING_DOG_HLD.md` §4.1/§4.2, §12) · findings
implemented: EMBODIMENT-KERNEL K3/K4/K6, A2's range-convention handoff, A3's
undone runtime installer.

## 1. K-rows — before → after

`.parcel/bin/python research/20260824/embodiment-kernel-portability/audit.py --repo .`

| row | before | after | bar |
|---|---:|---:|---|
| K1 vendor SDK leaks | 0 | 0 | 0 ✔ |
| K2 high-level vendor modules | 0 | 0 | 0 ✔ |
| **K3 simulator-observation modules** | **9** | **0** | 0 ✔ — no recorded exceptions |
| **K4 `NavigationSnapshotV2` exists** | **no** | **yes** (16 modules) | yes ✔ |
| **K6 service files** | **2** (firewall only) | **7** = 5 owned + 2 firewall | five owned ✔ |

K3 is measured a second time inside the product suite
(`tests/test_a4_spine.py::test_no_product_module_outside_backends_or_simulation_imports_simobservation`,
with its seeded-red control) so it cannot regress silently between audits.

## 2. What was built

### Contracts (new leaves, frozen dataclasses, `slots=True`, pure)

| file | lines | what |
|---|---:|---|
| `contracts/evidence_header.py` | 391 | `EvidenceHeaderV1` (schema version, source id + process epoch, monotonic capture stamp + clock-map uncertainty, sequence + evidence id, frame + calibration hash, declared origin, TTL + measured transport age, confidence/covariance, health reasons, `fixture_label`), `EvidenceProfile`/`physical_profile`, `header_health_reasons`, `mixed_epoch_sources`, `contributing_epochs/calibration_hashes` |
| `contracts/navigation_snapshot_v2.py` | 581 | `NavigationSnapshotV2` + `TransformV1`, `LocalizationHealthV1`, `BaseStateV1`, `TraversabilityV1`, `ObstacleReturnV1`, `DynamicTrackV2`, `PersonProximityV1`, `OwnerBeliefV1`, `SemanticObservationV1`, `SystemHealthV1`; the three `RANGE_CONVENTION_*` constants |
| `contracts/observation_carrier.py` | 88 | `ObservationCarrierV1` — the transitional Protocol naming the simulator-shaped carrier. Not `runtime_checkable`: nothing may branch on it |

`fixture_label` on the header is deliberate reuse of the existing product
vocabulary (`core.input_health.InputEvidence.fixture_label`) rather than a new
one; it is also what makes the carrier's `backend` string round-trip exactly.

**The A2 handoff, discharged.** `TraversabilityV1.range_convention` has **no
default** — a source that will not say what its metres mean cannot publish
geometry — and `footprint_radius_m` may be non-zero only under
`RANGE_CONVENTION_BODY_SURFACE`. The runtime stamps
`body_surface_to_obstacle_surface` with the robot profile's footprint, because
that is what both product sources actually publish. `authority.CLEARANCE_CONVENTION`
(which declares `base_center_to_obstacle_surface`) and the BARN adapter were
**not** touched — see §7.

### The assembler — placement justified

`src/parcel_robot/observation/` (new package), not `core/`. `core/` is the
motion/authority kernel (arbiter, hard stop, stop ramp, input health); adding an
observation assembler there makes it the layer dumping ground M6 forbids. A
feature package also buys the property the boundary exists for: **nothing under
`observation/` imports a backend, a simulator, a vendor name or the runtime**,
asserted in `tests/test_a4_spine.py`. That is what makes the observation
boundary replaceable rather than merely renamed.

| file | lines | what |
|---|---:|---|
| `observation/assembler.py` | 248 | `SnapshotInputs`, `SnapshotAssembler` (`assemble` / `review`), `snapshot_health_reasons` (pure), `REASON_TIME_WINDOW`, `DEFAULT_WINDOW_NS` = 100 ms |
| `observation/simulator_adapter.py` | 260 | `snapshot_from_carrier` — the complete simulator adapter |
| `observation/carrier_view.py` | 244 | the migration shim: snapshot → carrier field names |
| `observation/sources.py` | 223 | `ObservationSource` Protocol, `CarrierObservationSource`, `ReplayObservationSource`, `PhysicalObservationSource` (skeleton), `restamp_origin` |

Five refusal classes, each with its control in the suite: missing channel,
stale channel, mixed epoch, synthetic origin under a physical profile, and
capture stamps spanning more than the window. The assembler **reports** — it
returns an unhealthy snapshot rather than raising, because a body that must
HOLD has to be able to say why, and `translation_allowed` is what a refusal
actually costs.

### Adapters

* **simulator — complete.** `snapshot_from_carrier` maps all 22 carrier fields;
  round-trip through `carrier_view` is lossless **field by field**, NaN scan
  sentinels and `inf` range-max included (`test_the_simulator_adapter_maps_every_carrier_field_losslessly`
  plus its seeded-red control). It imports no backend — the carrier is
  structural — so the same function serves mujoco, go2 and the headless city.
* **replay — complete for recorded snapshots.** Re-stamps every header
  `REPLAY`; `restamp_origin` refuses to re-stamp toward `PHYSICAL` at all.
* **physical — typed skeleton, and it says so.** `PhysicalObservationSource`
  names its three missing collaborators (`sensor_hub`, `localizer`,
  `perception`), raises `PhysicalSourceNotCommissioned`, and has no
  `truth_pose` parameter and never will.

## 3. Per-module migration state (the nine)

Every module: import moved off `backends.base.SimObservation` onto
`contracts.observation_carrier.ObservationCarrierV1`; annotations migrated in
code only (comments and docstrings untouched — the tokenizer-guarded rewrite
skipped every `COMMENT`/`STRING` token); one V2 entry point added that takes a
real `NavigationSnapshotV2`.

| module | annotations | V2 entry point | note |
|---|---:|---|---|
| `brain/observations.py` | 2 | `build_observation_snapshot_from_v2` | annotation-only coupling |
| `control/base.py` | 1 | `update_sink_from_snapshot` | **refuses a PHYSICAL-origin snapshot**: the simulator-only sink rule is now enforced on evidence, not on a class name |
| `control/state.py` | 1 | `update_state_source_from_snapshot` | carries the fixture label into provenance, unchanged |
| `navigation/follow.py` | 14 | `observe_owner_from_snapshot`, `step_from_snapshot` | `OwnerBeliefV1.ambiguous/.lost` exist and are **not** consumed yet (A8's) |
| `navigation/reactive_safety.py` | 5 | `scan_evidence_from_snapshot`, `apply_reactive_safety_from_snapshot` | the behavioural one — see below |
| `navigation/search_owner.py` | 13 | `step_from_snapshot` | annotation-only |
| `navigation/semantic_map.py` | 3 | `semantic_candidates_from_snapshot`, `lidar_payload_from_snapshot` | `TYPE_CHECKING` import, now real for `carrier_view` |
| `navigation/spatial.py` | 14 | `step_from_snapshot` | annotation-only |
| `runtime.py` | 37 | `_publish_navigation_snapshot` / `navigation_snapshot()` | see §4 |

**`reactive_safety` — the SENSE-1/HW-2 semantics, preserved exactly.**
`apply_reactive_safety` is **untouched** in body: the only change to it is its
parameter annotation, and the ported digest below is the proof. The carrier
path still stamps through `evidence_origin(observation.backend)`, which returns
`SIMULATION` for every sample by construction (board D-1). What the V2 path
adds is the honest version of the same rule: `scan_evidence_from_snapshot`
reads the origin the **header declares**, so a physical LiDAR stamps PHYSICAL
without the runtime re-stamp — and it still may not invent scan presence the
snapshot lacks, which is HW-2's `scan is not None` short-circuit unchanged.
`apply_reactive_safety_from_snapshot` is a strictly-stronger wrapper: a refused
snapshot (or a latched localization) stops translation before the geometry gate
is consulted, never after.

## 4. `runtime.py` — seven hunks, and the pins they ported

Targeted edits only; the file was never rewritten and never whole-file
formatted (an earlier pass that did was reverted before any suite ran).

| # | site | what |
|---|---|---|
| 1 | import block | `+InputFault`, `+InputHealthVerdict`; `+install_localization`; `+SnapshotAssembler`, `+CarrierObservationSource`; `+NavigationSnapshotV2`, `+RANGE_CONVENTION_BODY_SURFACE`, `+ObservationCarrierV1`; **−`SimObservation`** |
| 2 | 37 signatures | annotation migration (no body changed anywhere) |
| 3 | the pose seam (`self._pose_provider = TruthPoseProvider()`) | `install_localization(store.section("navigation").get("localization"), odom_provider=…)`; the provider is replaced ONLY when a profile commissions one |
| 4 | same block | the spine's three attributes: `_snapshot_source`, `_snapshot_assembler`, `_navigation_snapshot`/`_navigation_snapshot_error` |
| 5 | new methods before `_evaluate_dispatch_input_health` | `_publish_navigation_snapshot` (never raises into the loop) and `navigation_snapshot()` |
| 6 | `_control_loop_body` | one call, placed after the OT-2 identity overlay and before the observation sink |
| 7 | `_evaluate_dispatch_input_health` tail + new `_compose_localization_latch` | A3's latch joined into the health verdict by `max(verdict.action, latch.action)` — **stricter only** |

**Ported pins** (old → new, each proved annotation-only by diffing
`ast.unparse` of the symbol against HEAD f1a6a92 — exactly one changed line
each, the `def` line):

| pin | old | new |
|---|---|---|
| `tests/test_nominal_stop_wiring.py:884` `RobotRuntime._nominal_stop_ramp_tick` | `8f8afb23…75eb` | `92a5ccdc…0d6f` |
| `tests/test_nominal_stop_wiring.py:888` `RobotRuntime._regate_nominal_stop` | `581b4141…9d0a` | `4ddc8c1a…1457` |
| `tests/test_dynamic_layer.py:904` `apply_reactive_safety` | `f52db9c5…bded` | `520211af…a484f` |
| `tests/test_dynamic_layer.py:913` `_owner_comfort_band_m` | `7d5050eb…48a9` | `b88d9f35…4d764` |

The other three `REACTIVE_SAFETY_PIN` digests (`ReactiveSafetyPolicy.__post_init__`,
`owner_slow_m`, `_owner_identity_trusted`) are **unchanged**, and that is the
evidence that nothing in the authority moved. Both re-freezes carry their cause
in a comment beside the digest. **A verifier should read these four rows
first**: they are safety-adjacent ratchets, and the card's authority to move
them rests entirely on the change being an annotation.

Constraints honoured: **no new lock** (r24 roster stays 8, floors unchanged);
**no new `on_*=self.method` or `on_*=lambda`** (`REENTRY_CALLBACKS` 17 /
`REENTRY_LAMBDAS` 4 unchanged); the nominal-stop symbols did not move, so the
digest table needed no re-keying; the nm1 `_control_loop` call graph only grew;
`# ---- CARD` markers **176 → 176** (none added anywhere in this card — the
invariants live in docstrings, per M7); no new `store.section(` name (the
literal `"navigation"` is already in `admission._RUNTIME_REGION_SOURCES`).

## 5. A3's pieces, installed

`localization/installer.py` (139 lines, pure) composes `ScanMatchLocalizer` +
`LocalizedPoseProvider` + `ArmingLatch` + `LocalizationJumpJournal` (+
`WholeMapMatcher` when a template source is supplied) from a
`navigation.localization` config section. **Defaults are unchanged**: no
section ⇒ `NOT_COMMISSIONED` ⇒ the runtime keeps `TruthPoseProvider()` and has
no latch, and `_compose_localization_latch` then returns the health verdict
byte for byte. `require_relocalization_margin` ships `False`, exactly as A3
shipped it. An unknown provider name raises rather than falling back to truth
pose.

## 6. Orin service skeletons (`deploy/orin/services/`)

Five units — `parcel-gateway`, `parcel-safety`, `parcel-lio`, `parcel-audio`,
`parcel-runtime` — plus a README. Each names its own principal (`User=parcel-*`),
boots disarmed (`Environment=PARCEL_ARMED=0` and `--disarmed`), carries an
`ExecStartPre=/usr/bin/test -x` so it can never report `active` for a binary
that does not exist, and lists its blocking TODOs by card. None has ever been
run: there is no Orin on hand and `deploy/README.md`'s "No Orin flash"
disclaimer still stands, untouched. HLD §3 splits `parcel-safety` from
`parcel-sensor-hub`; this card ships the five the A4 card names and records the
split as Gate 3 work in the README rather than shipping a sixth empty file.

## 7. Undone, with the follow-up shape

1. **The V2 entry points re-project rather than read natively.** Eight of the
   nine take a real `NavigationSnapshotV2` and pass it through `carrier_view`.
   The exception is the one that mattered: `scan_evidence_from_snapshot` reads
   the header. Cutover = a per-module rewrite behind the green round-trip test,
   HLD Gate 4. Rewriting `follow.py` (14 signatures), `spatial.py` (14) and
   `search_owner.py` (13) in the card that introduces the contract would have
   shipped an unreviewable diff.
2. **The runtime's consumers still receive the carrier.** The snapshot is
   published every tick and read by tests; no production consumer reads it yet.
   That is the same cutover as (1).
3. **No wire codec.** `EvidenceHeaderV1` has `from_mapping`/`as_dict`; the V2
   sub-records have `as_dict` only. HLD §13's schema round-trip/fuzz suite
   needs `from_mapping` on each sub-record — a mechanical follow-up, deliberately
   not bulked into this card's 581-line contract module.
4. **`WholeMapMatcher` is installable but not installed.** It needs a
   `RangeTemplateSource` answering `free()`/`template()`; the product has no map
   that can. The installer builds it only when one is supplied and names the
   gap in its reason string (`commissioned_without_map_templates`). Follow-up: a
   template adapter over the learned map (Gate 5).
5. **The commissioned localizer gets no scan.** `LocalizedPoseProvider` is
   installed with `scan_source=None`, so MAP tracks ODOM and the estimator is
   inert; the latch and the jump journal ARE fed every tick. A real LIO is
   Gate 5, and the polar-to-Cartesian scan bridge belongs with it.
6. **A3's operator re-arm has no product entry point.** `try_rearm_by_operator`
   is reachable only from tests. Follow-up: a one-shot journalled operator route
   (panel/CLI), which is where the transaction's spend semantics get exercised.
7. **The BARN adapter is not fixed and was not touched.** A2's finding stands:
   `evals/external/parcel_barn_adapter.py:151,181` publishes RAW ranges, and
   `authority.CLEARANCE_CONVENTION` still declares `base_center_to_obstacle_surface`
   while both product sources publish body-surface clearance. This card stamps
   the convention on the snapshot; correcting the adapter and the stale constant
   is a separate card with its own re-freeze.
8. **`physical_profile` is constructed nowhere in the product** — there are no
   commissioned frames or calibration hashes to fill it with. That is Gate 3's
   sensor-hub manifest, and it is why the physical-origin refusal is proved in
   the suite rather than in a running profile.
9. **No recorder writes replay snapshots.** `ReplayObservationSource` consumes
   them; producing them from a capture bag is Gate 3.
10. **`CODEBASE_INDEX.md` is STALE** (`tools/codebase_index.py --check`). It is
    a generated file and not this card's OWNS; the integrator regenerates it
    with the commit.

## 8. Suites

Guard label `a4-spine`, `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh`,
never `-n auto`, never `ci_gate --tier`. Git was read-only throughout; nothing
is committed.

### The pinned suites, targeted (all green)

| suite | result |
|---|---|
| `test_r24_lock_discipline` | pass — roster 8 locks / 17 callbacks / 4 lambda keys unchanged, floors unchanged |
| `test_nominal_stop_wiring` | pass — 2 digests re-frozen (§4), 5 unchanged |
| `test_nm1_promotion_and_asks` | pass — `_control_loop` graph and the >20 floor unchanged |
| `test_dec0_debt_ratchet` | pass — markers 176→176, no new oversized module, no new long function (it caught one: `snapshot_from_carrier` was 118 lines and was split into three helpers) |
| `test_decig2_import_ratchet` | pass — no barrel-symbol import, no `__init__` re-export, no new cycle, no forbidden reverse edge |
| `test_cap1_admission` | pass — no new config section name |
| `test_p1d_vlm_veto`, `test_ot2_identity`, `test_ot2_memory_principal`, `test_p1b_map_learns` | pass |
| `test_runtime`, `test_navigation`, `test_pose_consumers`, `test_pose_seam`, `test_e2_safety_wiring` | pass |
| `test_a2_navglue`, `test_a3_discontinuity_latch` | pass |
| `test_dynamic_layer` | pass — 2 digests re-frozen (§4), 3 unchanged |
| `test_search_owner`, `test_backends`, `test_portability_proof`, `test_h4_body_intent` | pass |
| **`tests/test_a4_spine.py` (new, 28 cells)** | **pass** |

### The one full run

```
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label a4-spine \
  .parcel/bin/python -m pytest -m 'not slow' -n 8 --dist loadfile -p no:cacheprovider -q
```

**8 failed, 10219 passed, 19 skipped, 1 xfailed in 81 s.**

All eight are pre-existing and none is attributable to this card. Method: a
pristine HEAD tree was materialised read-only (`git archive HEAD | tar -x`) and
the five suites re-run there under the same guard.

| red | verdict |
|---|---|
| `test_ci_gate::test_real_frozen_sentinels_match_the_current_tree` | **reproduces at HEAD** — `evals/companion/personal_convo_v1/manifest.json` sha drift, a file this card never touched |
| `test_ci_gate::test_each_real_sentinel_reddens_on_a_seeded_byte[...manifest.json]` | **reproduces at HEAD** — same sentinel |
| `test_v4s_search_cells::test_all_four_digest_sentinels_are_byte_identical_to_their_pins` | **reproduces at HEAD** — same manifest sentinel |
| `test_held_out_scene::test_no_test_outside_this_pair_loads_the_held_out_scene` | **reproduces at HEAD** — the offender is `tests/test_h7_localization_contract.py`, untouched here |
| `test_search_reground_bench` ×3 | **reproduce at HEAD** — `navigation_step_limit_inside_goal`, identical message |
| `test_barn_sensor_faithful::test_cached_world0_matches_live_causal_stall_signature_when_available` | **A2's declared, deliberately un-re-pinned red**, byte-identical signature: `assert 0.0 == 0.09 ± 1e-9` — the first published action's second component, exactly as `A2_STATUS.md` records it. (It SKIPS in the HEAD archive only because the pinned world cache is untracked.) This card stamps the convention that explains it and does not fix the BARN adapter — see §7.7 |

`ruff check .`: **5 fingerprints, all pre-existing, zero added** (the frozen
baseline lists 7; two of them no longer reproduce). Zero `noqa` anywhere in
this card's diff.

## 9. Scope

Product files changed: 9 migrated modules + 4 new leaves + 1 installer + 5
service units + 1 services README. Test files changed: `test_a4_spine.py`
(new) and two pin re-freezes. Nothing else. `git` was read-only; **nothing is
committed**. Safety floors, `apply_reactive_safety`'s body and
`finalize_command` are untouched; no frozen number moved; the owner's `:8765`,
`/tmp/parcel_sim.sock`, `:8080` and `parcel_memory.sqlite3` were never opened.
