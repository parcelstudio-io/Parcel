# C-3 — the cutover · status

**Card:** `scrum/20260821/task_13/README.md` (incl. the binding REVISION 2026-08-21)
**Executor:** Claude Opus · **Date:** 2026-08-22
**Result:** **PARTIAL — the cutover's mechanism is landed, tested and
seed-pinned; the card's live proof (items 5 / REVISION §3) and the VLM work
(REVISION §2/§5) and the PG-3 re-derivation (REVISION §4) are NOT REACHED and
are reported as ordered stops, not as omissions.**

> Pre-registration: `evidence/C3_PREREGISTRATION.md`, written before the first
> line of C-3 source existed and before any C-3 measurement. Every target below
> was fixed there first, including the execution order in its §6 — so the work
> that was not reached is the *tail* of a declared order, not a selection made
> afterwards to fit what got done. The naming deviation (§1) and all four scope
> deviations (§5) were declared in advance.

## 0. Entry conditions (the chain contract)

| Check | Result |
|---|---|
| Tree quiescence, measured twice | **PASS** — newest source mtime `1787361678.228` (`evals/external/.../experimental_sampled_predictive_tracker.py`, 21:21:18) read at 01:30:23Z (9m05s old) and **byte-identically the same value** at 01:31:05Z after the wait. Newest file *this chain* wrote was `online_map/entries.py` at 21:20:30. `ps` showed no pytest, no ci_gate and no repo-writing process |
| `git status --porcelain` matches predecessors' documented set | **PASS** — 11 modified = the audit's certified 7 (W-1 keeps + the R14 re-pin) plus exactly C-1's 4 (`runtime.py`, `camera_channel/ingress.py`, `ui/index.html`, `tests/test_r24_lock_discipline.py`); untracked = W-1's 5 + C-1's `test_c1_camera_stream.py` + C-2's `online_map/`, `test_c2_online_map.py`, `data/c2_online_map_frames.json` + scrum docs. Each named in `C1_STATUS.md` §3/§6 and `C2_STATUS.md` §3/§9. HEAD `71b39a1`, nothing staged or stashed |
| Entry gate `scripts/ci_gate.py` | **PASS** — every hard gate green, default-suite **7,880 passed / 9 skipped**, elapsed 334.3 s (`2026-08-22T01:36:49Z`). That is C-2's exit count to the test |
| Predecessor deliverables present | **PASS** — C-2's `online_map/` (6 modules) imports and builds a real map; C-1's 16 real frames present; PG-3's `perception_abstention.py` present; W-1's textured scene at the re-pinned digest. No HALT condition |

Owner store `parcel_memory.sqlite3` SHA-16 `40506fd96fc61c34` — recorded before
any work and re-measured inside the replay harness after it. **Unchanged.**

## 1. Headline

`perception.semantic_source` is a real switch. At `oracle` — the shipped
default — the mission path is the pre-C-3 read and returns the caller's own
dict objects. At `learned_map` the oracle read is **never performed**: candidates
come from C-2's map, with confidences earned from evidence counts and label
purity rather than the stamped `0.98`, the scene sidecar is not consulted, and
the four hardcoded POI classes reach perception instead of a lookup table.

**15/15 seeds RED. Gate green. T0 byte-identical. 54 new tests.**

Three results are worth more than the plumbing:

1. **The POI second oracle is disabled and proven disabled** (REVISION §1's
   "highest priority"). All four `demo_pois.yaml` classes reach
   `goal_source: semantic_search` under `learned_map` and `shadow`; the table
   is length 0; and re-arming it turns the harness red (seed 6). Under `oracle`
   it is byte-identical — same table, same coordinates, same metadata.
2. **The Narnia property survives the loss of the label set, measured on C-2's
   real map class.** Corpus rows 10–13: **0 of 4 moved** across the cutover,
   verdict *and* reason. Six learned places admit 6/6. Six null controls, 0
   admitted.
3. **The shadow run reproduces C-2's blocking finding through C-3's own
   consumer, and it is the card's most important number: agreement 0.0 over
   18 comparisons (0.0 over 7 comparable), and every single one of the 18
   learned-map refusals is `indecisive_ranking`.** Details in §5 — this is
   measured, not inferred, and it is not tuned away.

## 2. Pre-registered target register

| id | Target | Result |
|---|---|---|
| A1 | source axis absent ⇒ caller's own dict objects | **PASS** |
| A2 | explicit `oracle` == absent key | **PASS** |
| A3 | gate green, default-suite = 7,880 + this card's tests only | **PASS** — 7,934 = 7,880 + 54 |
| A4 | no frozen manifest digest moves | **PASS** — 4 sentinels byte-identical; release parity re-synced by the sanctioned generator, 91 assets |
| B1 | POI table empty under `learned_map` / `shadow`; no `known_poi` | **PASS** |
| B2 | 4/4 POI classes reach the semantic path | **PASS — 4/4, both sources** |
| B3 | `oracle` POI arm unchanged | **PASS** |
| B4 | RED seed catches a POI-sourced pass | **PASS — seed 6** |
| C1 | per-class agreement table, BOTH denominators | **PASS (structural + measured)** — §5 |
| C2 | `admission_flip` on known-place rows = 0 | **PASS — 0/18** |
| C3 | no rows 10–13 refusal flip toward admission | **PASS — 0/4** |
| C4 | every divergence carries its frames | **PASS — structurally unconstructable otherwise** |
| D1 | rows 10–13 equivalent under both sources | **PASS — 4/4** |
| D2 | refusal survives loss of the label set | **PASS** |
| D3 | known places admit under T1 | **SPLIT — 6/6 at the R20 layer, 0/6 at the PG-3 layer.** §5.2 |
| E1–E4 | VLM veto, provenance lock, operating point, duty cycle | **NOT REACHED** — §7 |
| F1–F2 | PG-3 operating points re-derived on textured renders | **NOT REACHED** — §7 |
| G1 | live voice session in shadow | **NOT REACHED** — §7 |
| G2 | ≥3 T1-only closed-loop missions | **NOT REACHED** — §7 |
| G3 | safety unchanged by source | **PASS — structural, seed-pinned (4)** |
| H1 | ≥10 seeds RED | **PASS — 15/15** |

## 3. The naming collision, and why the config key is not `tier`

Declared in the pre-registration §1 **before any code**. The card says
`perception.tier: T1` selects the learned map. `T1` was already taken: it is the
calibrated D455 **noise** ladder over the oracle. Frozen `nav_instruct` rows
record a `tier` field; `tests/test_perception_chain.py` and
`tests/test_e4_evidence_seams.py` pin `from_tier("T1").tier.name == "T1"`; and
`test_cam_foundation.py::test_tier_does_not_install_a_perception_chain` is a
hard-gate node id. Redefining `T1` would have silently changed what an archived
eval row means.

So the two axes get two keys — noise stays on `perception.tier`, provenance
moves to `perception.semantic_source` — and a test pins that they are
orthogonal in both directions. `perception_chain.py`'s own docstring had already
named this exact card ("a wiring card, not a rename"). Writing `T1` under the
new key is **refused with the reason**, rather than silently selecting the
oracle-plus-noise; that refusal is seed 11.

Throughout this document "T1" means `semantic_source: learned_map` and "T0"
means `oracle`, which is the card's vocabulary.

## 4. What landed

**Created:**

| Path | Lines | What |
|---|---:|---|
| `src/parcel_robot/perception_source/selection.py` | 310 | the source axis, its implications, the POI decision, two install seams |
| `src/parcel_robot/perception_source/shadow.py` | 545 | the four-class taxonomy, sensing envelope, two-denominator agreement table |
| `src/parcel_robot/perception_source/__init__.py` | 76 | exports |
| `tests/test_c3_cutover.py` | 1,079 | **54 cases** |
| `scrum/20260821/task_13/` | — | this doc, the pre-registration, two harnesses, two result JSONs |

**Edited (all four declared in the pre-registration §5):**

* `navigation/semantic_map.py` — source selection; `learned_map_candidates`;
  `evidence_confidence`. The oracle branch is reached by the only path that ever
  existed.
* `navigation/grounder.py` — `for_semantic_source` / `disabled` / `enabled`;
  a disabled arm raises the existing `LookupError` so the caller's fall-through
  is unchanged, but carries its reason.
* `navigation/pipeline.py` — `_build_grounder`, `_semantic_source_policy`, and
  `poi_grounding_disabled` on the mission metadata.
* `runtime.py` — `_learned_map_vocabulary`, `_learned_map_offer_places`,
  `_scene_learned_map`, the `_place_admission` fail-open conversion,
  `scene_report(learned_map=...)`, `SCENE_HONESTY_NOTE_LEARNED_MAP`,
  `scene_evidence_phrase`.
* `configs/navigation/default.yaml` + the generated `runtime_assets/` mirror.

**Deliberately NOT edited:** `perception_abstention.py` (PG-3 — asserted
unmodified by a test), `online_map/*` (C-2's — asserted by a test that every
line of `git status` over the package is still `??`), `goals.py`,
`camera_channel/*`, any safety module, any frozen manifest, `city_block.xml`.

### 4.1 Two design notes worth the register

**A redundant guard hid its own seed.** The first draft of
`PlaceGrounder.for_semantic_source` checked both `poi_grounding_enabled` and
`source != SOURCE_ORACLE`. Seed 6 ("the POI table is re-enabled off-oracle")
came back **GREEN**: the second guard caught the mutation and the harness could
no longer see the first one fail. Belt-and-braces that makes a defect invisible
to its own seed is worse than no redundancy, so the decision now lives in
exactly one place. The seed found this, not review.

**A soft degrade that had to stay loud in one direction.** The first exit gate
went red on
`test_barn_v8_policy_bundle.py::test_real_historical_bundle_derives_only_the_reviewed_v8_delta`:
a frozen BARN v8 bundle ships a `parcel_robot` tree predating this card —
including a `PlaceGrounder` with no `for_semantic_source` — while taking
`pipeline.py` as a *reviewed replacement source*, so the sidecar raised
`AttributeError`. The fix is asymmetric on purpose, and the asymmetry is the
incident audit's own lesson applied ("a soft-import that degrades a capability
to None turned a loud mistake into a quiet one"): on `oracle`/no-axis the
fallback is byte-identical to what the classmethod returns, so it degrades
silently; **off-oracle it raises**, because a quiet fallback there would re-arm
the second oracle this card exists to disable. Pinned by a test.

## 5. The live-ish proof: the real map class, on the real shipped path

Harness `evidence/run_c3_cutover_replay.py`; results
`evidence/c3_replay_summary.json`. It builds C-2's **real** `OnlineSemanticMap`,
installs it on the real seams, and drives the **shipped** consumers —
`RobotRuntime._place_admission`, `runtime.scene_report`, C-2's `resolve()`.
Nothing in it re-implements the code under test.

**Its limits, stated first.** The robot does not move. There is no simulator, no
detector, no voice, no arrival. Detections are synthesised at the surfaces
`scene_truth.json` declares (C-2's arm-B pattern), which deliberately removes
the detector as a confound and is therefore **not a perception claim**. This is
evidence that the cutover's plumbing answers correctly on a real map. It is not
evidence that a T1-driven robot arrives anywhere — that is §7.

Map built: **14 entries, 6 learned classes** (bench, building, door, lamppost,
planter, tree), 24 evidence frames each, navigability measured by walking.

### 5.1 What passed

| Measurement | Value |
|---|---|
| corpus rows 10–13, verdict+reason moved across the cutover | **0 / 4** |
| known-place admission at the R20 layer | **6 / 6** |
| null controls | **6 asked, 0 admitted** |
| POI-sourced goals under T1 | **0** (table size 0) |
| `admission_flip` | **0 / 18** |
| owner store SHA-16 before → after | `40506fd96fc61c34` → `40506fd96fc61c34` |
| R18 scene under T1 | 4 places named with distance + bearing; note no longer denies the robot has eyes |

Row 13 ("Let's go back home.") is `not_a_navigation_directive` under **both**
sources — the destination grammar does not call it a directive, so R20 has no
jurisdiction and another layer answers. The first draft of the test asserted
"refuses" and went red; asserting **equivalence** is the correct property and
pinning "refuses" would have frozen a behaviour this gate never had.

### 5.2 What failed, and the mechanism

**Shadow agreement: 0.0 over 18 comparisons; 0.0 over 7 comparable.**

| class | agree (all) | n | agree (comparable) | n | benign_miss | loc_delta | admission_flip | refusal_flip |
|---|---|---:|---|---:|---:|---:|---:|---:|
| bench | 0.0 | 3 | 0.0 | 2 | 1 | 0 | 0 | 2 |
| building | 0.0 | 3 | 0.0 | 1 | 2 | 0 | 0 | 1 |
| door | 0.0 | 3 | — | 0 | 3 | 0 | 0 | 0 |
| lamppost | 0.0 | 3 | 0.0 | 2 | 1 | 0 | 0 | 2 |
| planter | 0.0 | 3 | 0.0 | 1 | 2 | 0 | 0 | 1 |
| tree | 0.0 | 3 | 0.0 | 1 | 2 | 0 | 0 | 1 |

**Every one of the 18 learned-map answers refused, and every refusal reason is
`indecisive_ranking`.** That is C-2 §6's blocking finding, reproduced through
C-3's own consumer on a map with perfect geometry: `ranking_margin` is
`(top − median) / (1.4826 × MAD)` and returns exactly 0.0 when the MAD is 0.0,
which is what an evidence-weighted background always produces. With
`min_ranking_margin: 1.0`, **no admitted PG-3 verdict is reachable from a
label-primary map**, so D3 splits: the R20 vocabulary layer admits 6/6 while
the PG-3 layer admits 0/6.

I did not resolve it, and the pre-registration says why I predicted I could
not: REVISION §2's VLM veto is a **refuser**, and a fifth signal that can only
subtract cannot make a fourth signal satisfiable. The only two ways to admit are
editing `perception_abstention.py` (MUST NOT TOUCH) or lowering
`min_ranking_margin` after seeing my own output (forbidden, and the exact move
C-2 refused). **This is an owner decision and it is now measured twice,
independently, by two cards.**

**An honest limit of this shadow table.** Because a single systematic refusal
mode dominates, the comparable/non-comparable split (7 vs 11) is doing envelope
bookkeeping, not mechanism discrimination — all 18 rows share one cause. The
taxonomy is exercised and correct, but this run does not demonstrate that it
*separates* real divergence from structural mismatch, because there is no real
divergence in it to separate. That demonstration needs the live run in §7.

## 6. Seeded defects — 15/15 RED

Harness `evidence/run_c3_mutations.py`; results `evidence/c3_mutation_results.json`.
Protocol: fresh-interpreter canary before seeding; `__pycache__` purged before
every cell; anchor uniqueness checked (two seeds were reported `anchor_error`
on the first pass and rewritten rather than dropped); restore in a `finally`,
SHA-verified against pre-seed bytes; hang counts RED-by-timeout; final sweep
postdating the last source write; repo-root stray sweep.

**Final: 15/15 RED · 15/15 byte-restored · final sweep 54 passed · no seed
remains applied · repo-root strays none.**

| # | Seed | Property it breaks |
|---|---|---|
| 1 | T1 stamps a fake confidence | the 0.98-by-fiat returns under a new name |
| 2 | shadow divergence unlogged | the migration instrument records nothing |
| 3 | empty learned map fails open | "go to Narnia" returns the moment the label set is gone |
| 4 | safety imports the semantic source | the tier moves the safety envelope |
| 5 | oracle routed through the map arm | T0 stops being byte-identical |
| 6 | POI table re-enabled off-oracle | a T1 mission can pass via a lookup table |
| 7 | disabled POI arm still grounds | the disable is a log line, not a mechanism |
| 8 | taxonomy collapses two classes | an admission flip and a benign miss become one event |
| 9 | agreement reported without denominators | a rate with no n re-enters the record |
| 10 | divergence accepted without frames | divergence stops being re-examinable |
| 11 | `T1` accepted as a source spelling | the two axes are conflated |
| 12 | unestablished envelope counts comparable | a forgetful harness inflates its own denominator |
| 13 | learned map silently falls back to the oracle | the cutover reports success while GT answers |
| 14 | empty agreement class reports 1.0 | n=0 flatters instead of abstaining |
| 15 | scene note keeps denying the robot has eyes | F12: the hosted model is told to deny a real capability |

## 7. NOT REACHED — the ordered tail, and what each needs

These are the tail of the pre-registration's §6 execution order. None was
attempted-and-hidden; each is untouched, and **nothing in the tree claims
otherwise.**

1. **REVISION §2/§5 — the Qwen3-VL-2B veto, its provenance lock and the duty
   cycle (E1–E4).** Not started. Weights exist only in a scratch bench cache
   (`scratchpad/cutover-research/bench-vlm/hf/hub/models--Qwen--Qwen3-VL-2B-Instruct`),
   never vendored. **Consequence:** PG-3 has four signals, not five, and §5.2's
   universal abstention has no proposed remedy in the tree. Note that the veto
   would not have fixed §5.2 anyway (it subtracts).
2. **REVISION §4 — re-deriving PG-3's operating points on textured renders
   (F1–F2).** Not started. **Consequence: every threshold this card's
   `learned_map` path consumes is still the pre-W-1 calibration, fitted on the
   invalidated untextured distribution.** This is the most load-bearing gap:
   the abstention block ships `enabled: false`, so nothing is currently gated by
   those numbers, but any run that turns it on is using numbers F2 declared
   dead. Treat `min_ranking_margin: 1.0` in particular as unfitted.
3. **Item 5 / REVISION §3 — the live voice session and ≥3 T1-only closed-loop
   missions (G1–G2).** Not started. No live stack was launched, no mission was
   driven, no arrival was scored. **Consequence: the card's central claim — that
   a robot driven by its own map reaches the place — is UNPROVEN.** The shadow
   table in §5.2 structurally cannot substitute for it, which is precisely why
   the REVISION raised the mission count from 1 to 3.

## 8. What T1 cannot yet do (the card asks for this explicitly)

* **It cannot get a place admitted through PG-3 at all** (§5.2). Any consumer
  gating on `verdict.admitted` sees universal abstention.
* **It knows only classes the map has learned.** Six here, and only because
  arm B synthesised them. On C-1's real stream C-2 measured **one** entry, and
  that one was a detector false positive 3.86 m from the truth lamppost.
* **It has never been tested under a lighting or viewpoint change.** MuJoCo
  renders one fixed lighting; the map's positions are facade-derived and its
  envelope is a ~6 m depth band against the oracle's 12 m through walls.
* **Everything is oracle-pose-conditioned** (F6). The map fuses at known pose.
  Drift, relocalization and day/night revisit are entirely outside this surface.
* **Persons are not in it, by design.** C-2 refuses volatile classes
  persistence, so person-yield and keepout still ride the GT dynamic-agent
  channel — asserted by seed 4 and the structural safety test, and this card
  does **not** move the person channel (F8).
* **The scene answer is object-centric only.** Region vocabulary is empty under
  T1 because C-2's map has no regions; "the sidewalk" is not answerable from the
  learned map.
* **No decoys were exercised.** The poster / scene-text red-team props are still
  not in the dev scene (C-2 §8.1 declined it as an owner-authorized re-pin), so
  map poisoning remains unexercised end-to-end.

## 9. Gate

**Exit gate: PASS — every hard gate green** (see §9.1 for the red run that
preceded it and was fixed, not shrugged at).

* default-suite **7,934 passed / 9 skipped** — exactly **+54** over the entry
  run's 7,880, which is this card's test file and nothing else.
* tier-coverage 7,985 collected = 7,943 commit + 42 nightly, no orphans, no
  overlap (entry: 7,931 = 7,889 + 42).
* ruff 7 violations against baseline 7 — **new 0**.
* frozen-digest-sentinels: 4 immutable manifests byte-identical to pin.
* release-parity: 91 packaged assets byte-identical to canonical source, after
  a `tools/sync_runtime_assets.py --write` re-sync (2 files written, 0 removed).
* owner-store-isolation green; owner store SHA-16 unchanged across every run.

### 9.1 The gate failure on the way, on the record

The first exit gate was **RED**: `default-suite`, one test,
`test_barn_v8_policy_bundle.py::test_real_historical_bundle_derives_only_the_reviewed_v8_delta`.
Cause and fix are in §4.1. It is recorded here rather than only there because
the useful part is that it was a *category* of mistake this repo has a rule
for — `semantic_map.py`'s own docstring already warned that the module "is
reachable from a v8 replacement source" — and I read that warning, applied it to
`semantic_map.py`, and did not apply it to `pipeline.py`, which is the file the
bundle actually replaced.

## 10. Working tree at return

The inherited certified set (7 modified + 5 W-1 untracked + scrum docs), plus
C-1's 4 modified + 1 untracked, plus C-2's untracked `online_map/` set, plus
exactly this card's:

* modified: `configs/navigation/default.yaml`,
  `src/parcel_robot/runtime_assets/configs/navigation/default.yaml`,
  `src/parcel_robot/runtime_assets/MANIFEST.json`,
  `src/parcel_robot/navigation/{semantic_map,grounder,pipeline}.py`,
  `src/parcel_robot/runtime.py` (also C-1's — this card appended, it did not
  revert C-1's edits)
* untracked: `src/parcel_robot/perception_source/`, `tests/test_c3_cutover.py`,
  `scrum/20260821/task_13/`

`git diff` over `src/parcel_robot/perception_abstention.py` is **empty**;
`git status` over `src/parcel_robot/online_map/` is all `??`. Both asserted by
tests, not by this paragraph. Nothing staged, nothing stashed, nothing
committed — landing is the owner's act.

## 11. Residual risks and next owners

1. **PG-3's fourth signal blocks the whole cutover** (§5.2). Two cards have now
   measured it independently. It needs an owner decision: re-shape
   `ranking_margin` for evidence-weighted backgrounds, or replace the signal.
   Neither is inside any current card's OWNS.
2. **Every PG-3 threshold under T1 is uncalibrated for the textured world**
   (§7.2). Highest-value unowned work in this chain.
3. **The card's central claim is unproven** (§7.3). E-2 must not treat C-3 as
   closed; a generalization eval built on an unproven cutover measures the
   cutover, not the generalization.
4. **The shadow taxonomy is exercised but not yet discriminating** (§5.2 end).
   Its separation power is untested until there is a run with more than one
   divergence mechanism in it.
5. **`SCENE_HONESTY_NOTE` now has two versions and only one can be right per
   run.** If a future path renders a scene block without passing `learned_map`
   while the source is `learned_map`, the robot will deny having eyes while
   using them. Only `_realtime_scene_report` is wired today; a second caller
   would need the same wiring.
6. **`evidence_confidence` is my definition.** It is monotone, bounded and
   evidence-derived, but it is not calibrated against any measured
   detection-correctness curve. It should not be read as a probability.

## 12. Does not prove

A T1-driven mission · any arrival · any live voice session · any perception
claim (arm B removes the detector deliberately) · that PG-3 can admit anything
from a learned map (it measurably cannot, today) · Qwen3-VL-2B behaviour of any
kind · the duty-cycle policy · that any PG-3 threshold is correct on textured
renders · lighting/viewpoint robustness · person-channel behaviour · map
poisoning defence end-to-end · anything about odometry drift.

What it does prove: the switch exists and is real; the shipping default did not
move by a byte; the POI second oracle is off off-oracle and its re-arming is
caught; the robot refuses Narnia without a label set and admits what it has
actually learned; the scene answer describes detections with the uncertainty
each has earned and stops claiming the robot is blind; divergence has a
taxonomy with denominators that cannot be dropped; and the reason none of this
can yet drive a robot is a measured, named, single blocking signal rather than
a mystery.
