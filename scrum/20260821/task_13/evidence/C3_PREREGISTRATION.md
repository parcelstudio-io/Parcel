# C-3 pre-registration — the cutover

**Written 2026-08-22T01:45Z, BEFORE the first line of C-3 source existed and
before any C-3 measurement was taken.** Entry gate had already returned PASS
(7,880 passed / 9 skipped, `2026-08-22T01:36:49Z`), which is C-2's exit count to
the test.

Nothing in this file may be edited after a measurement it governs. Targets that
are missed are reported as misses in `C3_STATUS.md`; targets not reached at all
are reported as NOT REACHED, in the execution order fixed in §6 below, so that
an unreached target is an ordered stop and never a cherry-pick.

---

## 1. The naming collision, resolved BEFORE any code (declared deviation D1)

The card says `perception.tier: T1` selects the learned-map candidate source.
**`T1` already exists in this tree and means something else.**
`detection_adapter/perception_chain.py` ships `REGISTERED_TIERS = ("T0", "T1")`
where `T1` is the *calibrated noise ladder over the oracle* — D455 range sigma,
range-scaled dropout, false positives, overlapping TP/FP confidences. Frozen
`nav_instruct` rows record a `tier` field; `tests/test_perception_chain.py` and
`tests/test_e4_evidence_seams.py` pin `from_tier("T1").tier.name == "T1"`; and
`tests/test_cam_foundation.py::test_tier_does_not_install_a_perception_chain` is
a HARD gate node id.

Redefining `T1` would silently change the meaning of every frozen eval row that
records it. The module's own docstring already names the tier this card is
actually building and says it does not exist:

> "Registering a real `T-CAM` tier means giving it a `NoiseTier` whose
> candidates come from rendered pixels rather than the GT oracle `_lift` reads —
> a wiring card, not a rename."

**Resolution.** The source of candidates and the noise applied to them are two
orthogonal axes and get two orthogonal keys. `perception.tier` keeps its
existing meaning, untouched. A NEW key carries this card's axis:

| card's word | key this card implements | meaning |
|---|---|---|
| `T0` | `perception.semantic_source: oracle` | **default.** MuJoCo GT oracle. Byte-identical to today. |
| `T1` | `perception.semantic_source: learned_map` | C-2's `OnlineSemanticMap` is the only candidate source. |
| `T0_shadow_T1` | `perception.semantic_source: shadow` | oracle drives; learned_map runs in parallel; divergences logged. |

Throughout `C3_STATUS.md` and this file, **"T1" means
`semantic_source: learned_map`** and **"T0" means `semantic_source: oracle`**,
which is the card's vocabulary. This is C-2's `online_map`-not-`semantic_map`
precedent applied to a config key: two axes with one name is how a later
executor sets the wrong one.

A test pins the orthogonality: `tier: T1` must NOT change the source, and
`semantic_source: learned_map` must NOT change the noise tier.

## 2. Pre-registered acceptance targets

Every number below is fixed now. `n/a` denominators are stated with the target.

### A. T0 byte-identity (HARD — a miss fails the card)

| id | target |
|---|---|
| A1 | With the new key absent, `semantic_candidates_from_observation` returns **the caller's own dict objects** for every row — object identity, not equality. |
| A2 | With `semantic_source: oracle` explicit, same as A1. |
| A3 | Full gate green with the shipped config; default-suite count = 7,880 + exactly this card's new tests, no other movement. |
| A4 | No frozen manifest digest moves. `configs/navigation/default.yaml` is not a locked input of any `DIGEST_SENTINELS` manifest (verified 2026-08-22 before editing: the embodied-plan manifest locks `configs/robot.yaml` only) — release parity is re-synced by `tools/sync_runtime_assets.py`, the sanctioned generator, never by hand. |

### B. The POI grounder (REVISION §1 — highest priority)

| id | target |
|---|---|
| B1 | Under `learned_map` and under `shadow`, `PlaceGrounder`'s POI table is **empty**, and `Mission.metadata["goal_source"]` is never `known_poi` for any directive. |
| B2 | The four `demo_pois.yaml` classes — `coffee shop`, `bookstore`, `park`, `crosswalk` — each reach the semantic path (`goal_source: semantic_search`) under T1 instead of a hardcoded coordinate. Denominator 4/4. |
| B3 | Under `oracle` the POI arm is **unchanged** — same table, same `known_poi` grounding, byte-identical mission metadata. |
| B4 | A RED seed proves the harness catches a POI-sourced pass: re-enabling the POI table under T1 must turn the live-proof harness red, not merely change a log line. |

### C. Shadow-mode divergence taxonomy (REVISION §3)

Every divergence is classified into exactly one of four classes; the two flip
classes are HARD gates.

| class | definition | gate |
|---|---|---|
| `benign_miss` | T1 produced no candidate, T0 did, and T0's candidate lies outside T1's sensing envelope (beyond depth range, outside frustum, or occluded). Not counted against agreement. | soft |
| `localization_delta` | both admitted the same place class; centroids differ by > 0 m. Reported as a distribution, gated at the PG-2 tolerance. | soft |
| `admission_flip` | T1 admitted where T0 refused, **or** T1 admitted a different place than T0. | **HARD: 0 tolerated on known-place corpus rows** |
| `refusal_flip` | T1 refused where T0 admitted, on a query T0's oracle could see and T1's envelope covered. | **HARD: 0 tolerated on corpus rows 10–13 in the inverse direction** — i.e. a row that must refuse must refuse under both. |

Frustum/occlusion/convention mismatches are **separated from the denominator**:
agreement is reported twice, once over all comparisons and once over the
*comparable* subset (T0 candidate inside T1's envelope). Both denominators are
printed. A single agreement number without its denominator is not a result.

| id | target |
|---|---|
| C1 | Per-query-class agreement table with BOTH denominators, ≥1 row per corpus class present in the run. |
| C2 | `admission_flip` count on known-place rows = **0**. |
| C3 | `refusal_flip` on rows 10–13 (the Narnia family) = **0** in the direction that would admit. |
| C4 | Every divergence row carries the frames that produced it (frame ids + capture timestamps), not just a count. |

### D. The Narnia property under T1 (the card's single most important assertion)

| id | target |
|---|---|
| D1 | Corpus rows 10–13 refuse under `learned_map`, with the PG-3 equivalence tests extended to T1. Denominator 4/4. |
| D2 | Refusal survives the loss of the label set: with the scene sidecar's vocabulary unavailable, rows 10–13 still refuse. |
| D3 | Known-place queries admit under T1 for every class the map has actually learned. **Denominator is the learned set, stated explicitly, not the corpus.** |

> **Known blocker, recorded before measuring.** C-2 §6 reports that PG-3's
> fourth signal (`ranking_margin`) returns exactly 0.0 under evidence-weighted
> label-primary ranking, because the background's MAD is 0.0 in both the
> query-independent and query-conditioned constructions. With
> `min_ranking_margin: 1.0` that means **D3 is unreachable without either
> editing PG-3 internals (MUST NOT TOUCH) or lowering a safety threshold to fit
> this card's own output (forbidden by house rule).** I pre-register that
> D3 is expected to MISS for that structural reason, that I will measure it
> rather than assume it, and that the VLM veto of REVISION §2 is a *refuser*
> and therefore **cannot** unblock it — a fifth signal that can only subtract
> does not make a fourth signal satisfiable. If D3 misses, the honest output is
> the measurement plus a named owner decision, not a retuned threshold.

### E. VLM veto — PG-3's fifth signal (REVISION §2)

| id | target |
|---|---|
| E1 | Qwen3-VL-2B vendored with a provenance lock: model id, revision, file digests recorded and verified before use. |
| E2 | Veto composed on top of PG-3's verdict, never forked into it: `perception_abstention.py` byte-unmodified (`git diff` over it empty, asserted by a test). |
| E3 | Veto operating point `p_yes >= 0.5` re-measured on **textured** crops, ≥8 absent and ≥5 present, reported with its confusion table. Bench numbers (0/8 absent admitted, 5/5 present) are the prior, not the claim. |
| E4 | Duty cycle: generation permitted only when stationary / between keyframes / behind PG-1's admission. Pinned by a seed that turns red if generation is attempted while moving. |

### F. Re-derived operating points on textured renders (REVISION §4)

| id | target |
|---|---|
| F1 | Every PG-3 threshold consumed under T1 re-measured on textured `city_block` renders, reported as a table of {threshold, pre-W-1 value, textured value, n}. |
| F2 | The re-derivation is a MEASUREMENT: thresholds are reported, and any that move are moved only with the measurement in the record and the direction declared here first — **no threshold is lowered to admit this card's own output.** |

### G. Live proof

| id | target |
|---|---|
| G1 | A full voice session in `shadow` on the owner's own stack: "go to the lamppost", "go to the bench", "go to narnia", "what do you see" — with the shadow-agreement table. |
| G2 | **≥3** T1-only closed-loop missions (REVISION §3 raises this from 1), each arrival scored by the PG-2 surface convention. |
| G3 | Safety stack demonstrably unchanged by source: geometry / dynamic-agent channels assert `semantic_source`-independence, and a seed goes red if safety reads the source. |

### H. Seeds

| id | target |
|---|---|
| H1 | **≥10** seeded defects, all RED, under the register's harness protocol: `__pycache__` purge per restore, fresh-interpreter canary, SHA-verified restore in a `finally`, anchor-uniqueness check, hang counts RED-by-timeout, final sweep postdating the last source write, repo-root stray sweep. |

Named seeds fixed now: (1) T1 stamps a fake confidence instead of carrying
evidence-derived confidence; (2) shadow divergence unlogged; (3) rows 10–13
admit under T1; (4) safety reads the tier/source; (5) T0 not byte-identical;
(6) POI table re-enabled under T1 (B4); (7) VLM veto bypassed; (8) VLM
generates while moving (E4); (9) divergence taxonomy collapses two classes into
one; (10) shadow agreement reported without its denominator; (11) `tier` and
`semantic_source` axes conflated; (12) PG-3 verdict synthesized locally instead
of consulted.

## 3. What would falsify this card

* T0 moves by one byte with the key absent (A1–A3).
* A `known_poi` goal source appears in any T1 or shadow run (B1).
* Any `admission_flip` on a known-place row (C2).
* Any corpus row 10–13 admitting under T1 (D1).
* A PG-3 threshold lowered after seeing this card's output (F2).
* An agreement rate reported without both denominators (C1).

## 4. Null controls

The live-proof harness carries its own falsifiability check and **exits
non-zero** when it cannot falsify its own result, per C-2 seed 7's precedent:
≥5 absent-place null controls, 0 admitted, 0 candidates, under every source
setting exercised.

## 5. Declared scope deviations (declared BEFORE the work)

* **D1 — the `tier` / `semantic_source` split.** §1 above.
* **D2 — `navigation/pipeline.py` and `navigation/grounder.py` are edited
  although the base card's OWNS list does not name them.** REVISION §1 is
  binding, supersedes on conflict, states that "NO card owned it", and assigns
  the POI disable to this card. The edit is kept surgical: source-conditional
  construction of the grounder, no change to `PlaceGrounder`'s own scoring, and
  `oracle` behaviour byte-identical (B3).
* **D3 — `perception_abstention.py` is NOT edited.** REVISION §2 calls the VLM
  veto "PG-3's FIFTH signal"; the base card says "PG-3 gate internals (consume,
  don't fork)". Both are satisfied by *composition*: PG-3 returns its verdict,
  C-3 applies the veto on top. A test asserts the file is unmodified (E2).
* **D4 — `configs/navigation/default.yaml` is edited and
  `src/parcel_robot/runtime_assets/` re-synced** by `tools/sync_runtime_assets.py`.
  Verified before editing that this file is not a locked input of any frozen
  digest sentinel, so no owner-authorized re-pin is implicated (A4).

## 6. Execution order (fixed now; an unreached target is an ordered stop)

1. POI grounder disable (B) — REVISION §1's "highest priority".
2. Source axis plumbing + T0 byte-identity (A).
3. Shadow divergence taxonomy + logging (C).
4. R20 vocabulary + R18 scene answerability under T1 (D).
5. Seeds (H).
6. VLM veto + duty cycle + vendoring (E).
7. Re-derived operating points on textured renders (F).
8. Live proof: shadow voice session, ≥3 T1-only missions (G).
9. Exit gate + `C3_STATUS.md`.

## 7. House constraints re-affirmed

Owner's `parcel_memory.sqlite3` is never opened read-write; its SHA-16 is
recorded before and after every run. The owner's live stack on :8765 gets
read-only GETs only. Nothing is staged, stashed or committed. The quarantine
patches under `scratchpad/c2_quarantine/` are reference only and are not
applied or copied.
