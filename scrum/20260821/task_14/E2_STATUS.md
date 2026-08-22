# E-2 — generalization, earned · status

**Card:** `scrum/20260821/task_14/README.md` (incl. the binding REVISION 2026-08-21)
**Executor:** Claude Opus · **Auditor:** Fable · **Date:** 2026-08-22 (local 2026-08-21 evening)
**Result: HALTED under chain-contract rule 3 — predecessor deliverables absent.
No run was performed. `city_block_b`'s single exposure is UNSPENT. No source
file was edited; no perception source was touched.**

> Pre-registration: `evidence/E2_PREREGISTRATION.md`, written before the entry
> survey concluded and before the exposure-spend decision. Its **Rule E** — the
> rule that decides whether the held-out exposure gets spent — was fixed in
> advance precisely so that this halt could not be a post-hoc rationalization
> for not measuring. It fired as written.

---

## 0. Entry conditions (the chain contract)

| Check | Result |
|---|---|
| Tree quiescence, measured twice | **PASS** — newest source mtime `1787365159.6050459760` (22:19:19) read at 22:29:50 local (**630.4 s** old) and **byte-identically the same value** at 22:31:27 (**727.4 s** old). Also confirmed C-3's `C3_STATUS.md` sha `cc6f8128…` **unchanged** across the same window — its 22:27:55 write was its last, not a live pen. `ps` showed no pytest, no ci_gate, no repo-writing process |
| `git status --porcelain` ⊆ predecessors' documented set | **PASS** — 17 modified = W-1's certified 7 (`city_block.xml`, `metamorphic.py`, `scene_truth.py`, `scene_truth.json`, `embodied_plan_v1/manifest.json`, `ci_gate.py`, `pyproject.toml`) + C-1's 4 (`runtime.py`, `ingress.py`, `ui/index.html`, `test_r24_lock_discipline.py`) + C-3's 5 (`semantic_map.py`, `grounder.py`, `pipeline.py`, `configs/navigation/default.yaml` + its `runtime_assets` mirror) + C-3's `runtime_assets/MANIFEST.json` (its A4 release-parity re-sync). Untracked = W-1's 5 + C-1/C-2/C-3's declared files + scrum docs. HEAD `71b39a1`, nothing staged or stashed |
| Entry gate `scripts/ci_gate.py` | **PASS** — every hard gate green, default-suite **7,934 passed / 9 skipped**, elapsed 334.8 s (`2026-08-22T02:37:30Z`). Exactly C-3's exit count |
| Predecessor deliverables present | **FAIL — see §2. This is the HALT.** |

Owner store `parcel_memory.sqlite3` SHA-16 `40506fd96fc61c34` — matches the
audit's recorded value, read-only, unchanged.

**Held-out scene, measured at entry and again at exit — identical:**

| Artifact | SHA-256 |
|---|---|
| `src/parcel_robot/scenes/city_block_b.xml` | `b218b5a4dbfb925cb3fd3a9e93a72e901c5c5fc9799cd2d031948ce33e8e317e` |
| `evals/nav_instruct/scene_truth_city_block_b.json` | `cf4098fcd3e4b12d9ae5032dcc15e424cf29d1d301bfa13b7bfdbcb9d2629a01` |

It was never loaded, never rendered, never referenced by a new file. **The one
exposure this card was budgeted is still available to a re-dispatch.** That is
the single most valuable thing this run preserved.

## 1. Headline

E-2 asks for a number that is a **difference**: `gap = score(dev) − score(held-out)`.
Both terms need the same protocol to complete: a Phase-1 exploration patrol
during which the map learns from the real detector stream, then Phase-2 corpus
queries through the real voice stack.

**No predecessor has ever completed that protocol once, in any scene.** It is
not that it was tried and scored badly — it was never reachable:

* **C-3's G1 and G2 are `NOT REACHED`** by its own status doc §7: no live voice
  stack was launched, no T1-only closed-loop mission was driven, no arrival was
  scored. C-3 states the consequence itself: *"the card's central claim — that a
  robot driven by its own map reaches the place — is UNPROVEN."*
* **C-1 §8 "Does not prove"** explicitly disclaims *"a navigation/patrol
  mission"* **and** *"fitness of this stream for C-2/C-3 authority."*
* **C-2 measured what the only real stream actually yields:** 1 map entry from
  16 frames, and that one entry a **detector false positive 3.8583 m** from the
  truth lamppost (verified by me directly against
  `task_12b/evidence/c2_replay_summary.json`: `entries_written = 1`,
  `surface_distance_m = 3.8583`). The robot's pose moved **4 cm** across the
  entire 40 s run while 160/160 motion requests were accepted.

Building the patrol driver, the closed-loop T1 mission, and the live-voice eval
seam is **C-1's and C-3's scope, not E-2's**. Doing it anyway is the precise
failure this chain contract exists to prevent — the register's own words: *"C-2's
executor then implemented C-1's scope out-of-OWNS plus its own."*

**And the cost of proceeding regardless is irreversible.** Row H would produce
0/N for reasons already measured twice, while permanently converting the
held-out scene into development data. A bare 0/N cannot distinguish *"does not
generalize"* from *"has never worked anywhere"* — it would look like a
generalization finding while being a plumbing finding. Rule E forbade exactly
this trade, in advance.

## 2. The dependency survey — what is present, what is absent

| E-2 needs | Owner | State |
|---|---|---|
| Held-out scene + truth artifact | W-1 | **PRESENT** (hashes above) |
| Textured dev scene at the re-pinned digest | W-1 | **PRESENT** |
| **Storefront true-positive fixture (REVISION §2)** | W-1 | **PRESENT** — `vis_shopfront_1…6`, `storefront_a…f.png`. "go to the coffee shop" is constructible |
| Camera stream → typed detections | C-1 | **PRESENT** but disclaimed for this use (§1) |
| `OnlineSemanticMap` | C-2 | **PRESENT**; fusion/retrieval sound (arm B 6/6 at 0.0000 m) |
| `semantic_source` switch, POI oracle disabled | C-3 | **PRESENT and proven** — table length 0, 4/4 POI classes reach the semantic path. My REVISION §1 probe query is constructible |
| **Person-poster decoy (REVISION §3)** | C-2 | **ABSENT** |
| **Place-name decal decoy (REVISION §3)** | C-2 | **ABSENT** |
| **Exploration-patrol capability (Phase 1)** | C-1 / C-3 | **ABSENT** — never demonstrated; 4 cm of motion is the only datum |
| **T1 closed-loop mission (Row D, the gap's minuend)** | C-3 G2 | **ABSENT — `NOT REACHED`** |
| **Live voice stack in the eval loop (Phase 2)** | C-3 G1 | **ABSENT — `NOT REACHED`** |
| PG-3 thresholds valid for textured renders | C-3 F1/F2 | **ABSENT — `NOT REACHED`**; all still the pre-W-1 untextured calibration |

### 2.1 The decoy fixtures, and why I did not simply add them

REVISION §3 is binding on me: the person poster *"must not be admitted as a
person-place"* and the decal *"must not forge an admission"*, both scored with
frames. I swept the whole scene tree — `grep -rniE "poster|decal|decoy"` over
`src/parcel_robot/scenes/` returns **zero matches**, and
`scenes/assets/textures/` contains no poster or decal asset among its 30 files.

The audit explains why: those were C-2's three decoy blocks, *"legitimate C-2
card work, correctly `vis_*`-safe, but uncertified,"* removed from
`city_block.xml` during the incident restoration.

Re-creating them would mean editing `city_block.xml` — which is (a) outside my
OWNS, (b) named in my MUST NOT TOUCH, and (c) **a frozen-digest-pinned manifest
input whose current sha `e89f4f12…` exists only because the owner personally
authorized a re-pin ("Re-pin.", 2026-08-21)**. Adding geometry would move that
digest, redden `frozen-digest-sentinels`, and require a second owner-authorized
re-pin. A scored cell is not worth spending the owner's authority on, uninvited.

## 3. Pre-registered targets — disposition

Every target is recorded as **BLOCKED (not run)**. None is recorded as passed or
failed, because measuring none of them was possible without out-of-OWNS work.
Failures are recorded as failures; *unattempted* is recorded as unattempted.

| id | Target | Disposition |
|---|---|---|
| H1–H5 | held-out map learning, nav rows, refusals, nulls, POI probe | **BLOCKED** — Rule E withheld the exposure |
| D1–D5 | the same in the dev scene | **BLOCKED** — Phase 1 has no driver (C-3 G2) |
| G1 | gap = D − H with denominators | **NOT COMPUTABLE** — neither term obtainable |
| R1 | storefront true-positive | **BLOCKED** (fixture present; protocol absent) |
| R2/R3 | poster + decal red-team cells | **BLOCKED — fixtures absent** (§2.1) |
| R4 | count-questions without map corroboration | **BLOCKED** |

## 4. Defects filed

E-2 patches nothing (the E1 discipline). These are recorded here for the board;
placing them on it is the auditor's act, not mine.

* **E2-D1 — the red-team decoys have no home.** REVISION §3 binds E-2 to score
  fixtures that no card currently owns and whose creation moves an
  owner-re-pinned frozen digest. Needs a card that OWNS `city_block.xml` plus an
  owner-authorized re-pin, executed in the R14 protocol's order (behaviour
  measured first, against a scratch manifest).
* **E2-D2 — no exploration-patrol capability exists.** 160/160 motion requests
  accepted, 4 cm of displacement. Whether that is a C-1 harness artifact or a
  real actuator/locomotion defect is **undiagnosed**, and it is the single
  blocker that makes Phase 1 impossible in *either* scene. Highest priority of
  this list — nothing downstream of it can be measured until it is answered.
* **E2-D3 — the T1 query vocabulary is unspecified.** The only real stream asked
  two nouns (`person`, `lamppost`), capping the learnable corpus at 1 class. Under
  `learned_map` there is *no sidecar* by design, so where the patrol's detector
  query batch comes from is a genuine open design question no card has answered.
* **E2-D4 — `min_ranking_margin: 1.0` is structurally unsatisfiable, and the
  trap is currently masked.** `(top − median) / (1.4826 × MAD)` is exactly 0.0
  whenever MAD is 0.0, which every evidence-weighted background produces.
  Measured independently twice (C-2 arm B: 0/6 admitted, margin 0.0000; C-3:
  0/18, all `indecisive_ranking`). It does not bite today **only because
  `abstention.enabled: false`** — so the first card to enable abstention
  inherits universal refusal. That masking is why it deserves a card now rather
  than when it hurts.
* **E2-D5 — every learned_map threshold is fitted on an invalidated
  distribution.** C-3 F1/F2 not reached; the numbers come from the untextured
  scene W-1 superseded. C-3's own phrasing: *"any run that turns it on is using
  numbers F2 declared dead."*
* **E2-D6 — the held-out allowlist has no seat for an E-2 harness.**
  `tests/test_held_out_scene.py`'s allowlist is exhaustive *and* anti-rot (a
  stale entry reddens too). A re-dispatched E-2 must be granted a seat by
  whoever owns that test, and must plan for the allowlist entry to become stale
  the moment the run ends. Soft blocker — flagged so it is not discovered at
  run time with the exposure already committed.
* **E2-D7 — the chain contract's quiescence check is polluted by the contract's
  own mandated gate.** `evals/external/…/supervisory_gap_s2/experimental_sampled_predictive_tracker.py`
  is a **tracked** source file that the test suite **rewrites with byte-identical
  content**. I measured this directly: it read `22:19:19` before my entry gate
  and `22:32:36` after, with `git status` clean throughout. It was also C-3's
  newest-mtime file at *its* entry. So every executor's mandated gate run
  advances the "newest source mtime" the next executor must find quiet — the
  check as written measures the previous executor's *gate*, not their *edits*.
  Recommend the contract exclude test-rewritten paths, or that the rule read
  `git status` + content hashes rather than mtime. **A directory mtime is not
  provenance** — the audit's own lesson, applying now to file mtimes.

## 5. What I did not do

* Did not run either row. Did not load, render, or reference `city_block_b`.
* Did not create `evals/20260822/generalization_run_1/`. A pack laid out with no
  measurements in it would imply a run happened. There was no run, so there is
  no pack — the absence is the honest artifact.
* Did not edit any source file. `git status` is byte-for-byte what I inherited,
  plus this document and the pre-registration.
* Did not touch `perception_abstention.py`, `online_map/`, `perception_source/`,
  `city_block.xml`, any frozen manifest, or the allowlist test.
* Did not open the owner's store read-write; did not stage, commit, or stash.

## 6. What a re-dispatch needs

In order, because each gates the next:

1. **E2-D2 answered** — a patrol that moves the robot through a scene while the
   camera→detector→map loop runs. Until this exists, E-2 is not dispatchable.
2. **C-3's G2 closed in the dev scene** — ≥3 T1-only closed-loop missions with
   scored arrivals. This *is* Row D; without it the headline gap has no minuend.
3. **C-3's G1 closed** — the live voice stack in the eval loop, for Phase 2.
4. **E2-D1 resolved** — decoys owned, built, and re-pinned, or REVISION §3
   formally relaxed by the owner. Scoring cells whose fixtures do not exist is
   not something an executor may quietly drop.
5. **E2-D6 granted** — an allowlist seat, before the exposure is committed.
6. Then E-2 re-dispatches with `evidence/E2_PREREGISTRATION.md` **unchanged** —
   the protocol and its targets are already fixed, which is the point of having
   written them before the survey. The exposure is still there to spend.

## 7. The claim this card can still make

One, and it is worth stating because it was measured rather than assumed:

**The held-out scene remains held out.** W-1's isolation machinery works — the
allowlist is exhaustive and anti-rot, no product module names the scene, and it
is not the default anywhere. E-2 entered, surveyed, found the protocol
unreachable, and left the asset at the same two hashes it started at. The
generalization claim is still *available* to be earned honestly later, which it
would not have been had this run spent the exposure to re-measure a plumbing
defect two cards had already found.
