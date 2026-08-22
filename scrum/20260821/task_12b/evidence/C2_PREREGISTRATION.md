# C-2 pre-registration — targets fixed BEFORE any measurement

**Card:** `scrum/20260821/task_12b/README.md` (incl. the binding REVISION 2026-08-21)
**Executor:** Claude Opus (re-dispatch) · **Written:** 2026-08-21, before the
first line of `src/parcel_robot/semantic_map/` existed and before any map was
built.

Everything below is a commitment. A number that misses is reported as a miss
with its mechanism measured, never retuned. This is the register's rule and the
reason C-1's two misses are the most useful rows in its status doc.

---

## 0. Entry conditions (recorded, not predicted)

| Check | Evidence |
|---|---|
| Tree quiescence | measured twice, see §7 of `C2_STATUS.md` |
| `git status` matches predecessors' documented sets | W-1 certified set + C-1's five OWNS files, all named in `C1_STATUS.md` §3/§6 |
| Entry gate | `.parcel/bin/python scripts/ci_gate.py` |
| Predecessor evidence present | `task_11b/evidence/rerun_live_20260821T235718Z/summary.json`, SHA-256 must equal C-1's declared `1dff417b790f1dbd7b47d09deb74b0f52d9a0211e4e38760676d31bff57a6db9` |

## 1. What the map must do (functional, pass/fail)

| # | Property | Target |
|---|---|---|
| F1 | An object-centric entry carries class label, PG-2 surface location, best-view embedding stamp, evidence count, first/last-seen, writer provenance | every persisted entry, no exceptions |
| F2 | Re-observation strengthens; it never creates a duplicate within the fuse radius | ≥1 entry reaches evidence ≥5 from a real stream |
| F3 | Absence on re-visit decays and **marks**; nothing is deleted | entry count is monotone non-decreasing across the whole run |
| F4 | Decay-marked ⇒ **excluded from retrieval**, vocabulary and scene answer | 0 decayed entries in any query result |
| F5 | Persistence to the map's OWN store; the conversation store is never opened | owner `parcel_memory.sqlite3` SHA-16 unchanged across every run |
| F6 | Reload reconstructs the map | entry-for-entry equality after restart, including provenance and stamps |
| F7 | Volatile classes (person, vehicle, …) are observed but never persisted as places | 0 volatile entries in the store, on any input |
| F8 | Embedding version mismatch ⇒ "embedding unavailable", falls back to label/text | never a cross-space cosine; asserted structurally |
| F9 | Cosine is within-query re-ranking only and can never introduce a candidate | asserted structurally (the embedding channel receives an already-built candidate set) |
| F10 | Query API returns candidates + evidence + PG-3 abstention verdict | verdict present on every resolve, including refusals |

## 2. Live proof — the patrol (pre-registered acceptance)

A patrol in the **textured dev world** (`city_block.xml`, W-1's certified scene,
sha `e89f4f12…`), driven through the real runtime with C-1's landed camera
ingress, feeding the map.

| # | Target | Bar |
|---|---|---|
| L1 | Corpus place queries answered within PG-2 tolerance | **≥5** of the corpus classes {lamppost, tree, planter, bench, door, building} |
| L2 | PG-2 tolerance, `surface` measure | answer within **1.0 m** of the nearest polygon surface of the named truth part |
| L3 | Null controls refused | **≥5** absent nouns, **0** admitted |
| L4 | Persistence across restart | map rebuilt from disk in a **fresh interpreter**, query table reproduced exactly |
| L5 | Owner store untouched | SHA-16 identical before/after |

**L1/L2 rationale for the 1.0 m bar:** `bench_mapping.md` measured the lamppost
at 1–3 cm, but that was a hand-driven 120-frame sweep. A live CPU patrol at
~1.7 Hz with a moving robot will see most classes from fewer and worse views, so
1.0 m is the honest surface bar, not the 3 cm best case. If the measured error
is much better than 1.0 m, that is reported as measured — the bar is not
retroactively tightened.

**Known-limited in advance (declared here, before measuring):**
* **person** is excluded from L1 by construction (volatile class, F7) and
  independently by W-1's measured 0.014 person recall on this world.
* **Depth relief is not carried by C-1's detection record.** `sigma_range_m` is
  a *modelled* sensor sigma (`D455_DEPTH_SIGMA_COEFF_PER_M * range²`,
  `pixel_detections.py:557`) and therefore carries **zero** planarity
  information. The planarity half of the hygiene gate is exercised on fixtures
  with real depth patches; entries ingested from a record without relief
  evidence are marked `relief_unverified` and the picture-defence claim is NOT
  made for them. This is a limitation of the available stream, reported, not
  papered over.

## 3. Seeded defects — ≥10, all must go RED

Pre-named here so the harness cannot be written to fit whatever happened to
fail. Protocol per the register: `__pycache__` purged before each cell,
fresh-interpreter canary, SHA-verified restore in a `finally`, final sweep
postdating the last source write, repo-root stray sweep.

| # | Seed | Property it must break |
|---|---|---|
| 1 | decay **deletes** instead of marking | F3 — history is destroyed |
| 2 | decay-marked entries stay **retrievable** | F4 — quarantine becomes annotation |
| 3 | writer provenance dropped on persist | F1 — R27 discipline |
| 4 | store path resolves to the **conversation store** | F5 — the R27 catastrophe |
| 5 | reload skipped (start always empty) | F6 — the dog forgets yesterday |
| 6 | abstention bypassed in the query API | F10 — PG-3 becomes decoration |
| 7 | null control absent from live-proof scoring | the live proof stops being falsifiable |
| 8 | **volatile class persisted** (poster-enters-map-as-person) | F7 + REVISION 3(a) |
| 9 | metric-size gate disabled (**decal forges label agreement**) | REVISION 3(b) |
| 10 | embeddings **averaged across views** instead of best-view | REVISION 2 |
| 11 | embedding version mismatch silently cross-space cosines | F8 |
| 12 | cosine promoted to an absolute presence threshold | REVISION 1 |
| 13 | VLM-proposed name admitted without the k-visit gate | REVISION 5 |

Bar: **≥10 RED**. All 13 are attempted; any that stays GREEN is reported as a
harness failure (a property nobody is checking), exactly as C-1's seed 3 was.

## 4. Gate

`scripts/ci_gate.py` must be **green at exit**, every hard gate. Default-suite
count must move by exactly the number of tests this card adds and by nothing
else. Ruff new-violations must be **0** against baseline.

## 5. Declared scope deviations (declared BEFORE work, not after)

These are parts of the binding REVISION that this executor will **not** land,
each with the reason and what it would take:

1. **REVISION 6 — decoys in the dev scene.** Editing
   `src/parcel_robot/scenes/city_block.xml` moves the `city_scene` sha, which
   moves `evals/companion/embodied_plan_v1/manifest.json`, which is a
   **frozen digest sentinel** in `scripts/ci_gate.py`. Re-pinning it is an
   owner-authorized act under the R14 protocol (the auditor's own re-pin
   yesterday says so in the file, twice), and none of those four files is in
   C-2's OWNS. The previous C-2 run put decoy blocks in this exact file and
   that is a named part of the incident. **What lands instead:** the two
   red-team decoys as *fixtures* — a person-poster and a "coffee shop"
   scene-text decal, with real synthetic depth patches — so both required RED
   seeds (8 and 9) are pinned and the hygiene gates are genuinely exercised.
   The scene edit + re-pin is written up as a one-act owner-gated follow-up.
2. **REVISION 4 — OmDet-Turbo tiny as the async keyframe seat.** The weights
   are not in `~/.cache/parcel` (only `owlv2-b16` and `siglip2-b16`), the seat
   swap requires a pinned-fixture eval in CI *first* by the REVISION's own rule
   (the llmdet_tiny lesson), and detector internals are C-2's MUST-NOT-TOUCH.
   **What lands instead:** the seat is a first-class, named, pluggable writer
   with its own provenance row, so the map records *which* eye wrote each
   entry and a later cutover is a config change with an eval, not a rewrite.
3. **REVISION 5 — live Qwen3-VL-2B naming.** The k-consistency promotion gate,
   the `vlm_proposed` provenance and the idle-time-batch-only contract all
   land and are seed-pinned (seed 13). The 4.4 GB model is **not** loaded in
   this session; the namer is an injected callable and the live pass is
   deferred to C-3, which owns the VLM duty cycle.

---

*Nothing below this line was known when the targets above were fixed.*
