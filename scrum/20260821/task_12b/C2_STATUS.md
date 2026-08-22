# C-2 — the dog's own map · status

**Card:** `scrum/20260821/task_12b/README.md` (incl. the binding REVISION 2026-08-21)
**Executor:** Claude Opus (re-dispatch) · **Date:** 2026-08-21
**Result:** **COMPLETE, with one pre-registered target MISSED, three scope
deviations declared in advance, and one blocking architectural finding reported
rather than tuned away.**

> Pre-registration: `evidence/C2_PREREGISTRATION.md`, written before the first
> line of `src/parcel_robot/online_map/` existed. Every target below was fixed
> there first. The three scope deviations in §8 were also declared there, before
> the work, not assembled afterwards to fit what got done.

## 0. Entry conditions (the chain contract)

| Check | Result |
|---|---|
| Tree quiescence, measured twice | **PASS** — newest source mtime `2026-08-21 20:35:03.829` at 20:42:55 (7m52s old) and **identical** at 20:43:42. See §0.1 for a third measurement that moved, and why it was mine |
| `git status --porcelain` matches predecessors' documented set | **PASS** — the audit's certified set (7 modified + 5 W-1 untracked) plus exactly C-1's five OWNS files, each named in `C1_STATUS.md` §3/§6. HEAD `71b39a1` |
| Entry gate `scripts/ci_gate.py` | **PASS** — every hard gate green, default-suite **7,812 passed / 9 skipped**, elapsed 333.3 s. That count is C-1's exit count to the test, which is what "the tree I inherited is the tree C-1 certified" means in numbers |
| Predecessor deliverables present | **PASS** — `task_11b/evidence/rerun_live_20260821T235718Z/summary.json` SHA-256 `1dff417b790f1dbd7b47d09deb74b0f52d9a0211e4e38760676d31bff57a6db9`, **byte-identical to the hash C-1 declared**. 16 fresh frames in `on_frames.json`; safety resolution in `deltas` (`CollisionGate_p99_ms: 0.735`). No HALT condition |

### 0.1 A quiescence measurement that moved, and the attribution

A third measurement at 20:44:42 showed the newest mtime had moved from
`20:35:03` to `20:44:37` — `evals/external/experiments/barn_sampled_predictive_tracker_v9/.../experimental_sampled_predictive_tracker.py`.

That is a source file under `evals/`, so it is inside the contract's watch set,
and a moving mtime there is exactly what the contract says to halt on. It was
**not** a foreign writer, and the evidence is positive rather than assumed:

* `ps` showed the only processes touching the repo were **my own** entry-gate
  run (pid 668395, started 20:43:56) and its pytest child (pid 669515, started
  20:44:19). The touch at 20:44:37 postdates my pytest start by 18 s.
* The file is **tracked and clean** — `git status` shows nothing, so the
  content did not change; a barn-v9 test rewrites it byte-identically.
* Measurements 1 and 2 both predate my pytest and both read `20:35:03`.

Recorded rather than waved through, because "it was probably my own test" is
the shape of the reasoning that cost this register a day. A directory mtime is
not provenance; here the process table and `git status` are.

## 1. Headline

There is now a map the robot writes itself. It has **no sidecar**: entries are
object-centric places built from detections, located by the PG-2 surface
convention, carrying evidence counts, first/last-seen, best-view embedding with
a version stamp, and the session/seat/detector that wrote them. It persists to
its **own** store — the owner's `parcel_memory.sqlite3` SHA-16 is
`40506fd96fc61c34` before and after every run in this card, unchanged — reloads
in a fresh interpreter, and answers queries through a label-primary chain that
hands PG-3 the verdict rather than making one up.

**13/13 seeds RED. Exit gate green, 7,880 passed = the 7,812 I inherited plus
exactly my 68 tests. Zero tracked files modified. `route_memory/` untouched.**

Two things did not go as hoped and are reported as failures:

1. **The live-proof corpus target missed: 0 of ≥5.** C-1's stream is the only
   real perception this card had, and it asked about two nouns from a robot
   that moved 4 cm. §4 has the mechanism, measured.
2. **PG-3's fourth signal is structurally unsatisfiable under label-primary
   retrieval.** Not a bug in this card and not tuned away — §6.

## 2. Definition-of-done register

| Requirement | Result | Exact claim |
|---|---|---|
| `OnlineSemanticMap`: object-centric entries, PG-2 surface location, embedding, evidence count, first/last-seen, writer provenance | **PASS** | Every persisted entry; round-trips byte-identically through `as_dict`/`from_mapping` |
| Incremental: re-observation strengthens, no duplicates | **PASS** | 16 detections fuse to 1 entry with `evidence_frames=16`; two same-class places 12 m apart stay two |
| Absence decays and **marks**; nothing deleted | **PASS** | Entry count monotone; decayed entry keeps its 8 evidence frames and its whole history; **no delete path exists in the package** (asserted structurally over all 6 modules) |
| Decay-marked ⇒ **excluded from retrieval** (REVISION 3(c)) | **PASS** | Excluded from `resolve`, `known_places`, `around_me`; still visible to `entries()` for audit |
| Persists to its OWN store, never the conversation store | **PASS** | Refused by filename **and** by identity against `memory_path.owner_store_paths()`; relative paths refused; no declaration ⇒ refusal, not a temp file |
| Reloads on start | **PASS** | Fresh-interpreter subprocess rebuilds the map and reports the **writing** session's provenance, not the reading one's |
| Volatile classes never persisted (REVISION 3(a)) | **PASS** | 12 person observations ⇒ 0 entries, counted as `refused_volatile`; "bike rack" / "person crossing sign" correctly NOT volatile |
| Class-conditional size + planarity gate (REVISION 3(b)) | **PASS, with the planarity half honestly bounded** | Size gate live and measured; planarity requires a measured depth patch, which C-1's record does not carry — §5 |
| Retrieval label/text-primary; cosine re-rank only (REVISION 1) | **PASS, structurally** | The re-rank function receives the candidate list and returns a permutation of it; it never sees the entry table as a search space |
| Embeddings best-view, versioned, re-derivable (REVISION 2) | **PASS** | Best-view by `inlier_pixels × score`; stored vector is byte-exactly an observed view; stamp mismatch ⇒ "unavailable", never a cross-space cosine |
| Query API: candidates + evidence + PG-3 verdict | **PASS** | `assess_place_query` is called on every resolve including refusals; verdict never synthesized locally |
| R18 scene answerability / R20 vocabulary | **PASS** | `around_me` by kind + bearing; `known_places` from the map's own admissible names |
| `route_memory/place_graph` integration | **PASS — by not editing it** | `bind_place_graph` + `semantic_labels_near` use `nearest_index` / `record_visit(semantic_labels=...)`, both existing public API. `git diff` over `route_memory/` is **empty**, asserted by a test |
| VLM naming behind a k-visit gate (REVISION 5) | **PASS (machinery); model not run — §8.3)** | 3 distinct visits promote; 6 repeats of ONE visit do not |
| ≥10 seeds RED | **PASS — 13/13** | §7 |
| Gate green | **PASS** | §9 |
| Live proof: ≥5 corpus queries within PG-2 tolerance | **MISS (0/5)** | §4 |
| Live proof: null controls | **PASS — 6 controls, 0 admitted, 0 candidates** | §4 |
| Live proof: persistence across a restart | **PASS** | §4 |

## 3. What landed

**OWNS, created (all new files; zero tracked files modified by this card):**

| Path | Lines | What |
|---|---:|---|
| `src/parcel_robot/online_map/entries.py` | 781 | `MapEntry`, `MapObservation`, `EmbeddingStamp`, `WriterProvenance`, `ProposedName` |
| `src/parcel_robot/online_map/hygiene.py` | 418 | volatile exclusion, size priors, relief, `screen_observation` |
| `src/parcel_robot/online_map/store.py` | 267 | SQLite store + R27-class path refusals |
| `src/parcel_robot/online_map/online_map.py` | 1,139 | the map: ingest, fuse, decay, name, resolve, persist |
| `src/parcel_robot/online_map/ingest.py` | 190 | the one sanctioned seam from C-1's stream |
| `src/parcel_robot/online_map/__init__.py` | 131 | exports |
| `tests/test_c2_online_map.py` | 915 | **68 cases** |
| `tests/data/c2_online_map_frames.json` | — | C-1's 16 real frames, verbatim |
| `scrum/20260821/task_12b/` | — | this doc, pre-registration, two harnesses, two result JSONs |

**Deliberately NOT edited:** `route_memory/*` (integration rides existing public
API), `perception_abstention.py`, `navigation/semantic_map.py`, `camera_channel/*`,
`scenes/city_block.xml`, `scripts/ci_gate.py`, the two pinned manifests.

**The package is named `online_map`, not `semantic_map`,** because
`parcel_robot.navigation.semantic_map` already exists and is C-3's consumer-side
sidecar-backed candidate source. Two modules with one name is how a later
executor edits the wrong one.

### 3.1 A trap this module was nearly built on

`CameraDetectionRecord.sigma_range_m` is a metre-valued depth uncertainty
sitting right on the record, and it is the obvious input for a depth-planarity
gate. It is useless for that: `pixel_detections.py:557` computes it as
`D455_DEPTH_SIGMA_COEFF_PER_M * range_m ** 2` — a **modelled** sensor sigma that
is a pure function of range and contains exactly zero information about whether
a thing is flat. Wiring it in would have produced a gate that reports verdicts,
looks wired, and cannot see a poster. There is a test that goes red if a future
edit reads it.

## 4. The live proof, both arms

Harness `evidence/run_c2_replay.py`; results `evidence/c2_replay_summary.json`
SHA-256 `b080541f35ac7a0b2509a4650cb1fdf23bebb236c69dfde2292b95c5171e07a7`.

### 4.1 Arm A — the real stream

The 16 `CameraDetectionFrame` rows C-1 published from a live run of the real
stack: real MuJoCo renders of W-1's textured `city_block` (sha `e89f4f12…`),
real OWLv2-b16 int8 on CPU, real poses, real query batch `['person','lamppost']`.
Copied verbatim into `tests/data/`; the reconstructed publish-latency p50 is
**562.557 ms**, matching C-1's reported figure exactly, which is the cheapest
available proof the fixture is faithful.

| Measurement | Value |
|---|---|
| frames / observations / persisted | 16 / 40 / 16 |
| entries built | **1** (`lamppost`) |
| map position | (4.0051, 2.2148) |
| distance to `lamp_post_1` (PG-2 surface) | **3.8583 m** |
| distance to `lamp_post_2` | 11.8042 m |
| **within the 1.0 m pre-registered tolerance** | **NO — L1/L2 MISS, 0/5** |
| metric extent of the detection | **0.682 m × 2.575 m** |
| peak detector score | 0.4955 |
| navigability | **0.00** (`robot_traversal`) |
| PG-3 verdict | refused, `not_navigable` |
| null controls | **6 asked, 0 admitted, 0 candidates** |
| persistence across restart | 1 written, 1 reloaded, entry-for-entry equal |
| owner store SHA-16 | `40506fd96fc61c34`, unchanged |
| frames expired at publish | **16/16** |

**The mechanism of the miss, measured rather than guessed:**

1. **The stream is not a patrol.** The robot's recorded pose moves from
   `x=0.13` to `x=0.17` over the whole run — **4 cm**. C-1's motion requests
   were accepted (160/160) and the pose barely changed. So (a) only two nouns
   were ever asked, capping the corpus at 1 class before any map existed, and
   (b) the robot never walked near the place, so navigability is honestly 0.00
   and PG-3 refuses. **That refusal is correct behaviour**, not a defect.
2. **The one entry is a detector false positive, and the map recorded it
   faithfully.** The truth lamppost is a 0.12 m-diameter pole; the thing OWLv2
   called a lamppost back-projects to **0.68 m × 2.58 m** at its localized
   depth. The map's fuse put the entry within centimetres of where the
   detections said it was — the detections said somewhere else.
3. **My own size prior admitted it, and I am not retuning it.** The `lamppost`
   prior allows widths to 1.2 m, so 0.68 m passed. A prior derived from the
   scene's own truth geometry (0.12 m) would have refused it. I am not changing
   the number after seeing this measurement: the priors were fixed in the
   module before any map was built, and deriving them from `scene_truth.json`
   would re-introduce the sidecar this card exists to replace. Filed as a
   follow-up in §10.

### 4.2 Arm B — the map path alone, detector removed

**Not a perception claim.** Arm A measures detector + localizer + map together
and the detector is the term that failed. Arm B synthesizes detections at the
surfaces `scene_truth.json` says exist (σ = 5 cm), so "the map mislocated it"
and "the detector saw something else" stop being confounded.

| Measurement | Value |
|---|---|
| entries built | 14 |
| corpus classes queried | 6 — bench, building, door, lamppost, planter, tree |
| **within the 1.0 m tolerance** | **6/6**, every one at **0.0000 m** (inside the truth surface) |
| null controls | 6 asked, **0 admitted** |
| PG-3 admitted | **0/6** — see §6 |

So the fusion, retrieval, hygiene and persistence path answers **6 of 6** corpus
place queries inside their own truth surfaces, with null controls held. What the
card asked for end-to-end on real pixels is not proven; what is proven is that
the map is not the failing term.

## 5. Where the picture-defence claim stops

REVISION §3(b) is a two-part gate and only one part has an input on this stream.

* **Metric size — live.** Computed from the detection box back-projected at the
  localized depth through the real D455 focal lengths (fx=fy=644, and the frames
  are genuinely 1280×720, checked). This is what refuses the "coffee shop"
  decal: a 0.45 m × 0.25 m painted sign is a perfect label match, a perfect
  location, and not a shop.
* **Depth planarity — needs a measurement nobody supplies.**
  `relief_from_depth_patch` is implemented and tested (a flat patch yields
  0.000, a curved one > 0.2, fewer than 8 valid samples yields `None`), but
  C-1's record carries no depth patch. So entries ingested from that stream are
  marked **`relief_unverified`** and **the picture-defence claim is not made for
  them.** The gate does not silently pass; it says which check did not run.

The poster decoy is nevertheless fully defended, because gate (a) fires first
and needs no measurement: a person is a volatile class and is refused
persistence whether or not anything measured its depth. Both required RED seeds
(8: poster-enters-map-as-person; 9: decal-forges-label-agreement) are pinned.

## 6. The blocking finding: PG-3's fourth signal cannot be satisfied by label-primary retrieval

Reported, not worked around, and not tuned.

`perception_abstention.ranking_margin` is `(top − median) / (1.4826 × MAD)` over
the map's similarity background, and it returns **exactly 0.0 when the MAD is
0.0**. It was designed for text→place **cosines**, which are continuous and
never tie — the 0.060–0.135 band `bench_retrieval.md` measured has real spread.

REVISION §1 permanently demotes cosine and makes ranking **evidence-weighted**.
An evidence-weighted background does not have that shape:

* a **query-independent** background ties across every well-observed place ⇒
  MAD 0.0 ⇒ margin 0.0;
* a **query-conditioned** background is one non-zero value among zeros ⇒
  MAD 0.0 ⇒ margin 0.0.

Both were built and measured. Arm B is the clean demonstration: 6 places with
perfect geometry, 24 evidence frames each, navigability 1.00, label purity 1.00
— and **6/6 refused with `indecisive_ranking`, margin 0.0000**. Every one of
PG-3's other three signals passes; the fourth cannot be fed.

I did not resolve this, because resolving it means either editing
`perception_abstention.py` (not C-2's OWNS, and PG-3's operating points are
already slated for re-derivation on textured renders) or shipping a policy with
`min_ranking_margin` lowered, which is tuning a safety gate to fit my own
output. Instead every `MapQueryResult` now carries
`diagnostics["ranking_background_degenerate"]` and `background_mad`, so the
refusal is legible instead of mysterious.

**The research already names the fix and it belongs to C-3:** SYNTHESIS §4 —
"VLM-verify becomes PG-3's fifth signal", and it is embedding-version-free. A
fifth signal that a label-primary map *can* feed is what makes this gate usable
again. Until then, a label-primary map cannot produce an admitted PG-3 verdict.

## 7. Seeded defects — 13/13 RED

Harness `evidence/run_c2_mutations.py`; results `evidence/c2_mutation_results.json`
SHA-256 `b1969538d0f022cf043d4a80ef9d95459c3654d5982d19ed58594eb56c7b0fc4`.

Protocol: fresh-interpreter canary (tests **and** the replay harness's own
self-check) before seeding; `__pycache__` purged before every cell; restore in a
`finally` and SHA-verified against pre-seed bytes (C-1's seed-8 lesson); hang
counts RED-by-timeout; anchor uniqueness checked so a seed cannot silently fail
to apply; final sweep after the last source write; repo-root stray sweep.

**Final: 13/13 RED · 13/13 byte-restored · final sweep 68 passed · no seed
remains applied · repo-root strays none · 34.4 s.**

| # | Seed | Property it breaks | RED by |
|---|---|---|---|
| 1 | decay deletes instead of marking | the map can no longer say what it stopped believing | assertion |
| 2 | decay-marked stays retrievable | quarantine degrades to annotation | assertion |
| 3 | writer provenance dropped on persist | R27 discipline | assertion |
| 4 | owner's conversation store accepted as a map store | the R27 catastrophe, re-armed | assertion |
| 5 | reload skipped | the dog forgets yesterday | assertion |
| 6 | abstention bypassed in the query API | PG-3 becomes decoration | assertion |
| 7 | null controls removed from live-proof scoring | the live proof stops being falsifiable | harness self-check |
| 8 | volatile exclusion disabled | poster enters the map as a person | assertion |
| 9 | metric-size gate disabled | decal forges label agreement | assertion |
| 10 | embeddings averaged across views | REVISION 2 — vector describes no real view | assertion |
| 11 | version mismatch cross-space cosines | REVISION 2 | assertion |
| 12 | cosine promoted to an absolute threshold | REVISION 1 | assertion |
| 13 | VLM name admitted without the k-gate | REVISION 5 | assertion |

Seed 7 is the one worth naming: the live-proof harness carries its own
falsifiability check (≥5 null controls, 0 admitted, 0 candidates, both arms) and
**exits non-zero** when it cannot falsify its own result. Emptying
`NULL_CONTROLS` turns the harness red, which is the only way "the null control
is present" is a property rather than a habit.

## 8. Declared scope deviations

All three were written into `evidence/C2_PREREGISTRATION.md` §5 **before** the
work, with their reasons. None is a discovery made at the end.

### 8.1 REVISION §6 — decoys in the dev scene: NOT LANDED

Editing `src/parcel_robot/scenes/city_block.xml` moves the `city_scene` sha,
which moves `evals/companion/embodied_plan_v1/manifest.json`, which is a
**frozen digest sentinel** in `scripts/ci_gate.py`. Re-pinning it is an
owner-authorized act under the R14 protocol — the file says so twice in its own
comments, including for yesterday's incident restoration — and none of those
four files is in C-2's OWNS. The previous C-2 run put decoy blocks in this exact
file and it is a named part of the incident.

**Landed instead:** both decoys as fixtures with real synthetic depth patches,
exercising the gates for real, with both required RED seeds pinned.

**What the follow-up needs, as one owner-authorized act:** add the two
`vis_*`-safe decoy blocks via the scene tooling; measure behaviour FIRST against
a scratch manifest per the R14 order; then re-pin the sentinel, `scene_truth.json`
and the embodied-plan manifest, with the movement attributed in the re-pin log.
The held-out scene stays untouched, and the isolation test that caught both the
previous C-2 run and the auditor must stay green.

### 8.2 REVISION §4 — OmDet-Turbo tiny async keyframe seat: NOT WIRED

The weights are not in `~/.cache/parcel` (only `owlv2-b16` and `siglip2-b16`);
REVISION §4's own rule requires a pinned-fixture eval in CI **before** any seat
swap (the llmdet_tiny silent-collapse lesson); and detector internals are C-2's
MUST-NOT-TOUCH.

**Landed instead:** `seat` is a first-class field on `WriterProvenance`, written
per entry. The map already records which eye wrote each place, so a later
cutover can ask "which of these did the new detector actually write?" instead of
assuming the map is homogeneous — and arm B demonstrates it, writing under
`seat="async_keyframe_map"`.

### 8.3 REVISION §5 — live Qwen3-VL-2B naming: MODEL NOT RUN

The k-consistency gate, the `vlm_proposed` provenance, the promotion path and
the idle-time-batch-only contract all landed and are seed-pinned (13). The
4.4 GB model was not loaded; the namer is an injected call and the live pass
belongs to C-3, which owns the VLM duty cycle.

## 9. Gate

**Exit gate: PASS — every hard gate green** (`2026-08-22T01:26:11Z`, elapsed
338.4 s).

* default-suite **7,880 passed / 9 skipped** / 42 deselected — exactly **+68**
  over the entry run's 7,812, which is this card's test file and nothing else.
* tier-coverage 7,931 collected = 7,889 commit + 42 nightly, no orphans, no overlap.
* ruff 7 violations against baseline 7 — **new 0**.
* frozen-digest-sentinels: 4 immutable manifests byte-identical to pin.
* owner-store-isolation green; owner store SHA-16 `40506fd96fc61c34` unchanged
  across every run in this card.

**One gate failure on the way, on the record.** The first exit gate went red
three ways, all mine: 4 new ruff violations in my evidence harnesses, and
`test_no_harness_names_the_owner_store_outside_the_allowlist` — because my own
test wrote `tmp_path / "parcel_memory.sqlite3"` as a literal while testing that
the map refuses the owner's store. The isolation test caught the card whose
entire §7 seed 4 is about that store. It now reads the filename from
`memory_path.OWNER_STORE_NAME` rather than typing a second copy, which is the
thing the gate was asking for. Fixed, re-run, green.

**Working tree at return:** the inherited certified set (7 modified + 5 W-1
untracked + scrum docs) plus exactly this card's OWNS —
`src/parcel_robot/online_map/`, `tests/test_c2_online_map.py`,
`tests/data/c2_online_map_frames.json`, `scrum/20260821/task_12b/`. **Zero
tracked files modified by this card.** `git diff` over `route_memory/` is empty.
Nothing staged, nothing stashed, nothing committed — landing is the owner's act.

## 10. Residual risks and next owners

1. **No admitted PG-3 verdict is reachable from a label-primary map** until the
   fifth signal lands (§6). Any consumer that gates on `verdict.admitted` will
   see universal abstention. C-3 owns the fix; the diagnostics needed to see it
   are already on every result.
2. **The size priors are hand-written and one of them is too loose.** The
   `lamppost` prior admitted a 0.68 m-wide false positive. Deriving priors from
   the scene's truth geometry would reintroduce the sidecar; deriving them from
   the map's own accumulated extents across many sessions would not, and is the
   honest next design.
3. **Planarity is unexercised on real data** (§5). It needs the depth crop under
   the box, which lives in the ingress — a `depth_patches` argument is already
   accepted by `observations_from_frame`, so this is a producer change, not a
   map change.
4. **No live patrol was run by this card.** A real proof of the ≥5-corpus target
   needs a run with a wider query batch and a robot that actually moves; C-1's
   `run_c1_rerun_live.py` is the right starting point and the map's ingest seam
   is already frame-shaped.
5. **Navigability is my definition, not PG-3's.** PG-3 means "depth returns near
   the ground band"; the map means "the robot's own body has stood here". Both
   are honest measurements of different things and every entry records which
   source it used. They should be reconciled before either is trusted as one
   number.
6. Long-horizon decay behaviour is untested beyond a handful of visits; store
   growth past a few hundred entries is bounded by `MAX_ENTRIES` but unprofiled.

## 11. Does not prove

Real D455 mapping · any perception claim from arm B · detector-backed person
safety (persons are refused persistence by design) · that the map answers ≥5
corpus queries from real pixels · picture-defence via depth relief on real data
· OmDet-Turbo or Qwen3-VL behaviour · VLM naming accuracy · that PG-3 can admit
anything from this map · long-duration or large-map stability.

What it does prove: the robot can build a map of places it saw, keep it across
sessions in a store that structurally cannot be the owner's conversation
database, refuse to write down the things that move and the things that are
pictures, decay what it stops seeing without ever destroying the record, answer
by label and by learned name rather than by a cosine it cannot calibrate, and
hand a query to the shipped abstention gate instead of grading its own homework.
