# P1-B — the map learns from pixels · STATUS

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Executor:** Claude Opus
**Verifier:** Fable · **Date:** 2026-08-22
**Pre-registration:** `P1B_PREREGISTRATION.md` (written before the first source
edit and before any number below existed)

---

## Headline

**The online semantic map has a product writer, and what it learns survives the
process that learned it.** Before this card the map was constructed only inside
its own test file: on the real robot it was an object that never existed.

In the dev scene (`city_block`, MuJoCo, `EvidenceOrigin.SIMULATION`), driven by
MOVE-1's patrol for a 120 s budget, the runtime's own map now ends a run with
**67 entries across 8 labels**, **100 % carrying real 768-d SigLIP-2 embeddings
with their space stamped**, **98.5 % with a measured `relief_m` instead of
`relief_unverified`**, and **100 % with a bounded PNG of the pixels they were
embedded from**. It persists on `close()` — into a **self-contained store file,
WAL checkpointed** — and **a second run started knowing those 67 places**,
carried all 67 entry ids forward, and finished with 87. The reload round-trips
byte-identically: `as_dict` corpus sha256 `a2e29f01…` (run 1) and `d09854cc…`
(run 2), identical on both sides, thumbnails included.

MOVE-1's three patrol runs are the prior this is measured against: 13/51/57
entries, `relief_unverified` on **100 % of entries in all three**, no embeddings,
nothing persisted.

Four other things landed with it:

* **AU-C2-1 closed.** `MapEntry.as_dict` omitted the REVISION §6 source crop and
  `from_mapping` could not restore it, so `OnlineMapStore.save` dropped every
  thumbnail in silence. Persisted, restored, round-trip-tested, seeded RED.
* **Refutation D-R2 (blocking for P1-A's live row) closed.** The P0-D query union
  could exceed the 16-phrase frame limit, after which *every* poll raised inside
  `poll_once` and the camera went **silently blind**. Capped at 16 with `person`
  first, counted, logged. §5 has a live run that would have been blind before it.
* **Refutation D-R1 closed.** One line at the attach site:
  `ingress.pinned_queries = tuple(config.queries)`.
* **One store, one world.** Every entry carries a typed `EvidenceOrigin`; a store
  mixing `PHYSICAL` with a synthetic origin is refused at load, and the
  observation that *would have* mixed it is refused at ingest.

**Every pre-registered row was met.** No misses. Six deviations, all declared
in §7 — the load-bearing one is that the oracle-side half of work item 4 is
delivered **off by default** because measuring it showed it truncates 62 % of
the diagnostic stream and buys no product behaviour.

> **Verification pass, 2026-08-22.** Fable's verdict was DISCREPANCIES_FOUND:
> every pre-registered row, both refutations, the seeds, the R24 edge and the
> §7.1 trade verified and several were independently reproduced — but one real
> product defect (**the store's WAL was never checkpointed, so persisted rows
> sat in a sidecar file**), one **vacuous** owner-store check, one wrong
> paragraph and one mis-stated accounting were found, plus a `scene_id` that
> recorded the config filename instead of the scene. **All are fixed and
> re-measured; §11 is the record, and every number in this document now comes
> from the four regenerated packs.** Ten seeds, not seven.

---

## 1. What changed

**P1-B's share is measured by RECONSTRUCTION, not by reading hunks.** *(Corrected
under verification: the first version of this table classified `git diff` hunks
by keyword and under-counted `runtime.py` by 70 lines, which is why the three
cards' shares did not sum to the file total.)* Every edit this card made was a
recorded exact-match replacement, so the pre-P1-B text of each file is
reconstructible by reverse-applying them in reverse order; the numbers below are
`git diff --no-index --numstat <reconstruction> <worktree>`. Script:
`/home/jaewoo-jang/.cache/parcel-p1b/unpatch.py`, reconstructions under
`…/parcel-p1b/baseline/`. File totals are `git diff --numstat` against `HEAD`
(`904edd2`, 02:33) and keep moving, because `runtime.py`,
`configs/navigation/prototype.yaml` and `tests/test_p0d_navigation_unblocks.py`
are being written by other cards right now; the P1-B column does not.

| File | P1-B + / − | file total | What |
|---|---:|---:|---|
| `src/parcel_robot/camera_channel/ingress.py` | **+655 / −6** | +655/−6 | crop embeddings + space, bounded PNG thumbnails, decimated depth patches, the query cap, frame `origin`, `load_siglip2_embed_fn` |
| `src/parcel_robot/runtime.py` | **+547 / −2** | +1052/−11 | ONE new region (462 lines) + FOUR marked blocks outside it (below) |
| `src/parcel_robot/online_map/store.py` | **+167 / −6** | +167/−6 | v1→v2 migration, origin-mix refusal at load, **WAL checkpoint on close** |
| `src/parcel_robot/online_map/entries.py` | **+158 / −3** | +158/−3 | schema v2, `origin` on `WriterProvenance`, thumbnail persistence (AU-C2-1) |
| `src/parcel_robot/online_map/online_map.py` | **+74 / −0** | +78/−0 | foreign-origin refusal, origin meta on persist, coverage stats, **`close()`** |
| `configs/navigation/prototype.yaml` | **+72 / −0** | +121/−1 | the `perception.online_map` block |
| `src/parcel_robot/online_map/ingest.py` | **+65 / −0** | +65/−0 | the record→observation payload seam, `embedding_stamp_from_record` |
| `tests/test_c3_cutover.py` | **+60 / −12** | +60/−12 | a stale ratchet converted to a structural one (§7.2) |
| `tests/test_r24_lock_discipline.py` | **+24 / −0** | +24/−0 | the new lock, its owner and its ONE edge (§4.3) |
| `src/parcel_robot/online_map/__init__.py` | **+16 / −0** | +16/−0 | exports |
| `tests/test_p0d_navigation_unblocks.py` | **+6 / −0** | +40/−17 | one path added to the prototype-config pin (§7.3) |
| `tests/test_p1b_map_learns.py` | **new** | — | 37 tests |
| `scrum/20260822/task_7/` | new | — | pre-registration, this doc, the harness + 4 run packs + the seed log + the share reconstruction |

Read the two columns together: where they differ, the gap is another card's
concurrent work in the same file, and it is visible rather than assumed —
`runtime.py` (+505/−9 not mine), `configs/navigation/prototype.yaml` (+49/−1,
P1-D's abstention keys), `tests/test_p0d_navigation_unblocks.py` (+34/−17, P1-D)
and `online_map/online_map.py` (+4, P1-D's one-line edit at ~1026). Where they
match, this card is the only writer. All numbers are from
`evidence/SHARE_RECONSTRUCTION.txt`, taken after the §11 corrections;
`entries.py`, `ingest.py` and `__init__.py` need no reconstruction because
nothing else has touched them.

Every edit to an existing file was an exact-match **single-occurrence**
replacement (the patch script refuses on 0 or >1 matches) applied to the file as
re-read at that moment. No `git add/commit/stash/checkout/reset/restore` was
run. No process I did not start was killed. Scratch lives in
`/home/jaewoo-jang/.cache/parcel-p1b/`. Nothing under `docs/`, `backlog/`,
`README.md` or `scrum/20260821/` was written; `scrum/20260821/task_20`'s harness
was imported read-only.

### The runtime region, and the FOUR marked blocks outside it

One region — `# ===== CARD P1-B — the camera -> online-map writer =====` …
`# ===== END CARD P1-B region =====` — holding eight methods. **Every** line
this card put in `runtime.py` outside that region is inside one of four blocks
carrying the card's name, so a reader can find all of P1-B by grepping `P1-B`.
Line numbers move as other cards write; the markers do not.

| Block | Lines (2026-08-22) | Size | Why there |
|---|---|---:|---|
| the region itself | 10328–10789 | 462 | the writer, the settings reader, the query batch, the snapshot |
| **init state** (`---- CARD P1-B state ----`) | 1556–1574 | 19 | eleven attributes, all `None`/zero, so every accessor is safe on a runtime whose `start()` never ran. *(Added to this accounting under verification — it was missing.)* |
| seam 1 · install (`seam 1 of 3`) | 4188–4197 | 10 | `start()`, immediately **before** `_attach_configured_camera_ingress()`: the map must exist before the first frame publishes **and** before the query batch is built, since off-oracle that batch is `known_places()` of the *reloaded* map |
| seam 3 · persist (`seam 3 of 3`) | 4305–4314 | 10 | `close()`, after the camera worker stops and before the evidence log closes: no frame can land between the last ingest and the write |
| seam 2 · feed (`seam 2 of 3`) | 10152–10157 | 6 | end of `_publish_camera_frame`: after the queue, after EV-1, **outside** `_camera_stream_lock` |
| attach block (`CARD P1-B: the encoders`) | 10283–10322 | 40 | the site the card names for work item 1 — `embed_fn` + its space, `pinned_queries` (D-R1), `origin`, `_p1b_query_batch` |

---

## 2. The pre-registered rows, measured

**All four packs below were regenerated on a quiet tree after the verification
corrections in §11, so every number in this document comes from the same code.**
The earlier packs were discarded rather than patched: they carried the vacuous
owner-store check, the `p1b` scene id, and store files whose newest rows were
still in a WAL sidecar.

| Pack | What it is |
|---|---|
| `evidence/p1b_run1_fresh/` | 120 s patrol, **fresh** store |
| `evidence/p1b_run2_reload/` | 120 s patrol, **reusing run 1's store** |
| `evidence/p1b_oracle_sidecar_batch/` | 25 s, `oracle` + the 34-phrase sidecar batch ON (§5, §7.1) |
| `evidence/p1b_flag_off/` | 25 s, shipped `configs/navigation/default.yaml` (R-8) |

Scene `city_block.xml` sha256 `e89f4f12…` in all four. Harness:
`evidence/run_p1b_dev_scene.py`. Seed log: `evidence/SEEDED_RED.txt` (harness
`evidence/seed_p1b.py`). Share reconstruction:
`evidence/reconstruct_p1b_share.py`.

| # | Row | Bound | Run 1 | Run 2 | |
|---|---|---|---|---|---|
| **R-1** | active entries / distinct labels | 10-90, >=3 | **67 / 8** | **87 / 8** | ok |
| **R-2** | fraction with a 768-d SigLIP-2 stamp | >= 0.90 | **1.000** | **1.000** | ok |
| **R-3** | fraction with measured `relief_m` | >= 0.50 (prior **0.00**) | **0.985** (66/67) | **0.989** (86/87) | ok |
| **R-4** | reload fidelity, fresh process | 100 % `as_dict` equal | **`a2e29f01…` both sides** | **`d09854cc…` both sides** | ok |
| **R-5** | thumbnails restored byte-identically | >= 0.50 | **1.000** (67/67) | **1.000** (87/87) | ok |
| **R-6** | 20-phrase request -> <=16-phrase batch, frame builds, drop counted | pass | §5 | §5 | ok |
| **R-7** | mixed-origin store refused at load | refusal names both | §6 | §6 | ok |
| **R-8** | oracle builds no map, writes no store | `None`, no file | **`learned_map_snapshot() is None`, no store file** | | ok |
| **R-9** | `pinned_queries == tuple(config.queries)` after attach | equal | pinned by test | pinned by test | ok |

**Nothing was re-cut after measuring, and there are no misses.** R-3 is 0.985 /
0.989 rather than 1.000: in each run exactly **one** entry — a `tree` in both —
carries `relief_unverified`, because every detection that created it had fewer
than the map's own 8-sample minimum of in-band depth inside its box. That is the
gate answering "nobody could look", which is the honest answer and the one this
whole field exists to distinguish from "flat".

Every entry in both runs sits in exactly one embedding space:
`siglip2-base-patch16-224@vision_model_fp16.onnx/768/resize224-rescale-meanstd`
— the **CUDA fp16** artifact P0-C installed, honoured, and measured at 4.17 ms
p50. Median thumbnail **3 912 B** / **3 877 B**, max 7 269 B (bound 16 384). Both
stores are schema `parcel.online_map.v2`, and in both packs
`wal_sidecar_present: false` — the store file is self-contained (§11.1).

Stream health, both runs: **239 frames ingested, 0 ingest errors, 0 stream
errors, 0 embed failures, 0 queries dropped**; 1 369 / 1 427 observations;
321 / 271 refused by C-2's hygiene gate and 2 / 1 refused as volatile classes.
Camera cadence 2.013 Hz against a configured 2.0.

**The owner's conversation store was not touched, and this time that is
measured.** The harness now reads `memory_path.owner_store_paths()[0]` — the same
authority the map's own R27 refusal uses — which resolves to
`<repo>/parcel_memory.sqlite3`. sha256
`0373297f818727cde96c8bf2254bd128e7bc2f829e49493d3229eb7c4e13da0d`, identical
before and after **all four runs**. See §11.2 for why the earlier claim was
worthless.

### 2.1 R-4, and the harness bug that hid it

Run 1 of the FIRST round reported `as_dict_identical: false` for all 69 rows, and
that was the harness, not the store: it diffed the live dataclass's `relief_m`
against the reloaded one, and `as_dict` rounds to 4 places (C-2's pre-existing
serialization). The harness now hashes the `as_dict()` **corpus** on both sides,
which is the right subject — each stored payload IS the writer's `as_dict()`, so
re-reading it and re-serialising is the strongest form of the row. Both
regenerated packs report it directly, with `thumbnails_identical: true`.

Recorded rather than quietly re-run, because a green number produced by fixing
the measurement deserves more scrutiny than one produced by fixing the code.

### 2.2 The row that is not on the list, and matters most

Run 2 was given run 1's store. `learned_map_snapshot()["reloaded_entries"] = 67`:
**the robot started the second patrol already knowing 67 places it had seen in
the first**, then grew to 87. That is the first parameter in this system that
persists from the robot's own experience rather than from a file a person wrote.

The lineage is checkable rather than asserted, and the verifier checked it
independently: **all 67 of run 1's `entry_id`s appear in run 2's final 87**, and
their `first_seen_wall_s` all predate run 2's start. Entry ids are
`place-<uuid4>`, minted at creation and never regenerated, so a carried id is
proof of a reloaded row and not of a coincidence — run 2 added 20 new places and
kept fusing into the 67 it already had.

---

## 3. What the map now carries, and why each field is there

| Field | Before P1-B | Now |
|---|---|---|
| `embedding` | `label_embedding(label)` — an **8-dim hash of the WORD**, containing nothing about the pixels | 768-d SigLIP-2 crop vector, cuda_fp16 |
| `embedding_stamp` | `None` (`observation_from_record` had no source) | model / **artifact filename** / dim / preprocessing |
| `relief_m` | `None` on every entry; `hygiene_note = relief_unverified` | measured p90−p10 over a decimated depth grid |
| `thumbnail` | held in memory, **dropped by the store** (AU-C2-1) | bounded PNG, persisted and restored |
| `provenance.origin` | did not exist | typed `EvidenceOrigin`, refused at load if mixed |

The **revision is the artifact filename**, not a version somebody typed: fp16 and
int8 exports of one checkpoint are close but not the same coordinate system at
the precision a cosine cares about, so two runs on two providers write two
spaces and the map declines to compare across them. That is the correct answer,
and it is a real constraint on P1-A's daemon (§9).

The JSONL evidence row stays **payload-free on purpose**, and now says so with a
test: `_offer_camera_frame_evidence`'s own contract is that raw arrays and
embeddings never reach EV-1, and 768 floats + a PNG per detection at 2 Hz would
be ~100 MB/hour of log describing pixels nobody reads back. The durable carrier
is the map's store. What the row *does* gain is three scalars —
`origin`, `embedded_detections`, `relief_measured_detections` — so an auditor
can see from the log that the payload existed. **The distinction between this and
AU-C2-1 is that this one is declared, tested and reversible; AU-C2-1 was
silent.**

---

## 4. How it was verified

### 4.1 Seeded RED — TEN guards, each restored byte-identically

Harness `evidence/seed_p1b.py`, full output `evidence/SEEDED_RED.txt` *(saved as
a file under verification — it previously existed only as a paste in this
document)*. Each seed applies one exact replacement, purges every
`__pycache__`, runs the named tests, restores the file, re-verifies its sha256,
purges again, and re-runs. **Run on a quiet tree with no evidence run in
flight**, because the harness mutates real source files and a sim starting
mid-seed would import a seeded module.

```
P1-B seeded-RED harness
repo HEAD  : 904edd24fc910bce5f160de3d2f242a03d447cd7

[OK ] S-1  AU-C2-1 returns: as_dict drops the thumbnail again          RED -> sha d866df981bf1 -> GREEN
[OK ] S-2  the store stops refusing a mixed-origin map                 RED -> sha 2197b595a99b -> GREEN
[OK ] S-3  the seam accepts an embedding with no space                 RED -> sha 03fde09773e4 -> GREEN
[OK ] S-4  D-R2 returns: the query union is uncapped                   RED -> sha 31037829658f -> GREEN
[OK ] S-5  D-R1 returns: the attach site stops pinning the batch       RED -> sha 19a0db3e3fc3 -> GREEN
[OK ] S-6  the attach site stops arming the SigLIP-2 encoder           RED -> sha 19a0db3e3fc3 -> GREEN
[OK ] S-7  the runtime stops persisting the map on close()             RED -> sha 19a0db3e3fc3 -> GREEN
[OK ] S-8  the store is never closed, rows sit in the WAL   (§11.1)    RED -> sha 3aff3d5846c6 -> GREEN
[OK ] S-9  the runtime stops closing the store after persisting (§11.1) RED -> sha 19a0db3e3fc3 -> GREEN
[OK ] S-10 scene_id falls back to the config filename       (§11.5)    RED -> sha 19a0db3e3fc3 -> GREEN

10/10 seeds went RED, restored byte-identically, and came back GREEN.
```

S-8/S-9/S-10 are the three added for the post-verification corrections. S-9 had
to be tightened after its first attempt: `learned.close()` matches twice in
`runtime.py` (the persist path and the failure-path helper), the harness refused
the ambiguous pattern rather than seeding the wrong one, and the test now pins
the exact adjacency `learned.close()` → `self._p1b_persisted = written` so the
seed cannot be satisfied by the other call site.

### 4.2 Targeted gates

```
$ .parcel/bin/python -m pytest -q -p no:randomly \
    tests/test_p1b_map_learns.py tests/test_c1_camera_stream.py \
    tests/test_c2_online_map.py tests/test_c3_cutover.py \
    tests/test_p0d_navigation_unblocks.py tests/test_runtime.py \
    tests/test_runtime_activation.py tests/test_move1_patrol.py \
    tests/test_prototype_profile.py tests/test_r24_lock_discipline.py \
    tests/test_perception_abstention.py tests/test_held_out_scene.py \
    tests/test_release_parity.py tests/test_runtime_assets.py
504 passed, 2 warnings in 16.77s

$ .parcel/bin/python -m pytest -q tests/test_p1b_map_learns.py
37 passed

$ .parcel/bin/python -m pytest -q tests/test_held_out_scene.py -m "slow or not slow"
7 passed          # the E-2 isolation scan; this card's files are off its list (§11.7)

$ .parcel/bin/ruff check src/parcel_robot/online_map/ \
    src/parcel_robot/camera_channel/ingress.py src/parcel_robot/runtime.py \
    tests/test_p1b_map_learns.py tests/test_c3_cutover.py \
    tests/test_r24_lock_discipline.py \
    scrum/20260822/task_7/evidence/run_p1b_dev_scene.py
All checks passed!
```

`scripts/ci_gate.py` was **not** run and neither was the full default suite (P0-E
owns the gate; the board reserves it).

### 4.3 R24 caught the new lock, which is the system working

`_p1b_map_lock` made `test_the_lock_roster_is_complete` fail on sight, then
`test_the_lock_order_is_the_pinned_one` failed on a real new edge. Both are
recorded in the roster with an owner and a justification rather than worked
around:

* **`_close_lock → _p1b_map_lock`** — `close()` holds `_close_lock` and the
  persist takes the map lock. It **cannot close a cycle**: `_p1b_map_lock` has
  **no outgoing edges at all** — the only two places that take it call nothing
  that takes another runtime lock, and nothing anywhere takes any runtime lock
  while holding it. `test_the_lock_order_graph_is_acyclic` is green.
* **`_camera_stream_lock → _p1b_map_lock` deliberately does NOT exist.** The
  feed runs after `_publish_camera_frame` has released the stream lock, exactly
  so the map cannot be reached while the camera's own lock is held. That is the
  same discipline C-1 used for the publish seam and R24's roster proves it held.

---

## 5. D-R2, and the run that would have been blind

The refuter's finding, reproduced and then closed. `_with_pinned` now caps the
union at `MAX_QUERY_PHRASES = 16`, keeping `person` **first** (it may arrive
anywhere in an operator's batch and it is the one phrase whose loss is a safety
property), then `pinned_queries`, then the request; the overflow is dropped,
counted in `stats.queries_dropped` / `last_dropped_queries`, and logged at
warning.

The evidence is not synthetic, and it has its own pack:
`evidence/p1b_oracle_sidecar_batch/`. Measuring the oracle arm of work item 4 —
where the batch is the scene sidecar's own `detector_query_set()` — the live
`city_block` vocabulary turns out to be **34 phrases**:

```
camera ingress query batch capped at 16 phrases; dropped 18: flower box,
front door, lamp, lamp post, park bench, pavement, plant pot, planter, pot,
safe region, seat, sidewalk, street light, street tree, streetlight, tree,
trees, zebra crossing (a batch over the cap would make every frame fail
construction and blind the detector silently)
```

That run published **48 frames / 384 retained detections / 0 errors**, with
`queries_dropped: 18` and a 16-phrase `last_query`. Under P0-D's uncapped union
those same 34 phrases would have raised inside every `_detect_and_localize`,
`poll_once` would have swallowed all 48, and the only moving number would have
been `stats.errors`. The frame-schema refusal is kept as a backstop and pinned
(`test_a_frame_over_the_cap_is_still_a_hard_refusal`).

The pack is produced by `evidence/nav_oracle_sidecar_batch.yaml`, a
**measurement-only** copy of `configs/navigation/default.yaml` with exactly one
key added (`perception.online_map.oracle_query_batch_from_scene: true`). It is
not shipped and nothing selects it; it exists so this arm can be re-run with one
key flipped and everything else identical to the shipped file — which is also
what makes §7.1's comparison a controlled one.

`clear_query()` is unchanged: the cap is not an excuse to redefine the off switch.

---

## 6. One store, one world

Both ends of one invariant, because they catch different mistakes:

* **`OnlineMapStore.load_all`** refuses a store that is *already* mixed, naming
  the counts on both sides. That is the reader's protection — a store can only
  become mixed across two runs, and the run that would be misled is the one
  loading it.
* **`OnlineSemanticMap.observe`** refuses the *observation* that would make it
  mixed, in the process that fed it, naming both origins. That is the useful one.

`unknown` is deliberately **not** a party to either: it is silent, not synthetic.
Refusing every pre-P1-B store would have made this guard the first thing a future
executor deleted.

Schema `v1 → v2` is **migrated, not refused**, because both additions are
additive and a v1 row's absence of them is the information ("this store never
recorded one"). The migration re-reads every row through `from_mapping` *before*
relabelling, so a row this build cannot parse leaves the store on v1 with a named
error instead of being silently relabelled and failing on the next load.
`migrated_from` / `migrated_rows` go into `map_meta`. An unknown schema is still
refused.

---

## 7. Deviations from OWNS, declared

1. **The oracle-side half of work item 4 ships OFF.** The card says the oracle
   batch "is `scene_semantics.detector_query_set()`". It is implemented and it is
   `false` by default (`perception.online_map.oracle_query_batch_from_scene`),
   because measuring it changed the answer: the sidecar's 34 phrases cap to 16
   and the resulting frames then run hard into
   `camera_ingress_max_detections_per_frame`. Two 25 s oracle runs, same scene,
   same budget, **differing in that one key**:

   | | batch | localized | retained | **truncated** |
   |---|---:|---:|---:|---:|
   | `p1b_oracle_sidecar_batch` (ON) | 16 of 34 | 1 016 | 384 | **632 (62.2 %)** |
   | `p1b_flag_off` (shipped) | 6 | 404 | 347 | **57 (14.1 %)** |

   Under `oracle` the camera grounds nothing — the GT oracle supplies the
   candidates — so that cost buys a longer diagnostic stream and no product
   behaviour. Off also keeps the shipped default's batch byte-identical to
   before this card. **The capability is delivered; the switch is off and the
   numbers are in the config comment.** Re-measure with a higher per-frame cap
   before turning it on.
2. **`tests/test_c3_cutover.py::test_the_online_map_package_is_not_modified_by_this_card`
   was converted to a structural pin** and renamed `…_is_consumed_never_forked`.
   It asserted every `git status --porcelain` line for `online_map/` began with
   `??`. It had stopped measuring what it meant twice over: the package was
   untracked when C-3 wrote it (so "all `??`" happened to mean "unmodified") and
   is tracked now, so the assertion had become a claim about the *working tree of
   whoever runs the suite*; and P1-B **owns** `online_map/` and was chartered to
   change it. Same treatment P0-D gave E2's abstention pin, and stronger than the
   emptiness check: C-3's five modules must not re-declare the map's types,
   schema or store path, **and** the consumer must really reach the installed map.
   Nothing was deleted or weakened; no new ratchet was added.
3. **`tests/test_p0d_navigation_unblocks.py`'s prototype-config pin gained one
   path** (`perception.online_map`), the same way P1-D added
   `perception.abstention.ask_below_threshold`. The set stays exhaustive.
4. **`tests/test_r24_lock_discipline.py` gained one lock and one edge** (§4.3).
   This is another card's ratchet; it is moved with an owner, a reason and an
   acyclicity argument, exactly as its own docstring requires.
5. **`camera_channel/ingress.py` grew a SigLIP-2 loader**
   (`load_siglip2_embed_fn`). The card's OWNS names ingress "embed/depth/
   query-batch regions"; putting the loader beside the consumer keeps `runtime.py`'s
   region to a call and keeps `instructnav/` (P0-C's) untouched — its diff is 0 lines.
6. **`CameraDetectionRecord` / `CameraDetectionFrame` gained fields.** Records
   gained four in-memory-only payload fields; frames gained three serialized
   scalars, **optional on read** so C-1's 16 archived frames still decode
   (pinned by test). Every pre-P1-B key stays mandatory.

---

## 8. What this does **not** prove

1. **No camera.** Every number is MuJoCo, `EvidenceOrigin.SIMULATION`. The
   `PHYSICAL` arm is exercised only by construction. The audit's own §1 figure —
   0/69 → 1/74 person recall in sim versus 81–93 % on real photos — applies to
   every count here. **67 entries in a renderer is not 67 places in a room.**
2. **Retrieval quality is not measured.** This card makes the map *writable,
   embedded, relief-measured and reloadable*. Whether the 768-d SigLIP-2 vectors
   retrieve better than the 8-dim label hash they replaced is a bench nobody has
   run; C-2's 0/5 live-corpus miss and the 2026-08-21 retrieval bench's
   0.049–0.135 cosine separation both stand until someone re-runs them on
   embedded entries.
3. **A measured `relief_m` on 98.5 % of entries is not "the planarity defence
   works".**
   It says the gate now has a measurement. Whether the numbers separate a door
   from a poster of a door needs a scene containing a poster, and `city_block`
   has none.
4. **The entry count is not a quality metric.** 67 and 87 entries with a 1.0 m
   fuse radius, from 239 frames of a patrol whose path length was 9.5 m and
   11.2 m: some of those are certainly the same object seen from two places and
   not fused. Nothing here measures duplicate rate, and `city_block` contains
   many near-identical windows and doors, which is the worst case for it.
5. **The two runs share a robot, a scene and a seed-free sim.** Two runs is not a
   distribution, and their spread is real: the first round of runs (same code
   path, different sim trajectories) produced 69 and 85 where these produced 67
   and 87. Run 2's 87 is 67 reloaded + 20 new, and how many of the 20 are
   genuinely new places versus fusion misses is unmeasured.
6. **`persist_on_close` has never been tested against a crash.** A `close()` that
   never runs writes nothing; there is no incremental persist and no journal.
   A run killed with `SIGKILL` loses everything it learned.
7. **The oracle path is NOT byte-identical, and the earlier wording here was
   wrong.** *(Corrected under verification — this paragraph previously claimed
   "the published frame dict … unchanged", which §3 and §7.6 of this same
   document contradict.)* With `semantic_source: oracle` the **grounding path,
   the candidate source and the map are unchanged**, and `learned_map_snapshot()`
   is `None` with no store file written (R-8, measured). Three things do change
   whenever `perception.camera_ingress` is on:
   * the published frame dict gains **three keys** — `origin`,
     `embedded_detections`, `relief_measured_detections` — so an EV-1 row from
     this build is not byte-comparable to one from before it (they are optional
     on read, so old rows still decode; §7.6);
   * the in-memory `CameraDetectionRecord`s carry payload (embedding, thumbnail,
     depth patch) that nothing on the oracle path reads;
   * the SigLIP-2 image encoder runs per crop. **That cost is cited, not
     measured here**: P0-C measured the encoder at 4.17 ms p50 / 4.60 ms p95 on
     `cuda_fp16`, and this card never isolated the per-crop cost inside a live
     poll. What it did observe is that the loop still met its cadence
     (`achieved_rate_hz` 2.03 against a configured 2.0). An honest bound on
     "what the encoder adds to a poll" needs an A/B with `embed_fn=None`, and
     nobody ran it.
8. **`MAX_QUERY_PHRASES = 16` is the schema's number, not a measured one.** It is
   `CameraDetectionFrame`'s own ceiling. Whether OWLv2's accuracy degrades before
   16 phrases is unmeasured, and a longer batch was never the alternative — the
   alternative was blindness.
9. **The migration was tested on a store this card wrote and then rewrote into v1
   shape.** No real pre-P1-B store exists on this host to migrate.
10. **`OnlineSemanticMap` has NO internal lock, and this card did not give it
    one.** *(Raised under verification; documented, not fixed.)* The map object
    is mutated only by the camera worker (through `_p1b_feed_learned_map`, which
    holds `_p1b_map_lock`) and read at teardown (same lock), so **every writer
    today is serialised** — but by the RUNTIME's lock, which lives outside the
    map. Two consequences a future caller has to know:
    * `active_entries()` / `entries()` / `stats()` build a new tuple or dict
      from `self._entries` in a single bytecode-level iteration and are
      GIL-atomic against a concurrent `observe()` — the mission-path reads
      installed by `use_learned_map` are safe as written, which is why nothing
      is broken today.
    * **`resolve()` is not.** It iterates the live `_entries` dict across
      several statements while building candidates and scoring the background.
      It has **no product caller** right now (that is the only reason this is a
      note and not a defect), but a caller added on a different thread —
      NM-1's naming pass, a VENUE-1 consumer, a panel endpoint — can hit
      `RuntimeError: dictionary changed size during iteration` mid-patrol.
      **Any such caller must take `runtime._p1b_map_lock` around the call**, or
      the map must grow its own lock. Repeated as handoff §9.8.

---

## 9. Handoffs

1. **P1-C — the `embed_fn` seam is `CameraIngress.embed_fn` + the three
   `embedding_*` strings, and `load_siglip2_embed_fn()` is how you get one.**
   That function returns `(embed_fn, model_id, revision, preprocessing)` or
   `None`. Consume it for the re-ID gallery rather than loading a second
   embedder: a second SigLIP-2 session doubles the VRAM and, more importantly,
   `EmbeddingStamp.space_key` equality is the **only licence to take a cosine**,
   so a gallery stamped differently from the map's entries cannot be compared to
   them even though the arithmetic will happily produce a number.
   `CameraDetectionRecord.embedding` already carries the per-detection vector for
   every `person` box the detector returns — the safety lease guarantees `person`
   is in the batch — so the re-ID input is on the frame you already receive, with
   no second encode. `parcel_robot.online_map.ingest.embedding_stamp_from_record`
   is the one sanctioned conversion to a typed stamp.
2. **P1-A — D-R2 is closed, which unblocks your live row**, but the cap is a
   producer-side guard. Your UVC/RealSense backends must set
   `CameraIngress.origin = EvidenceOrigin.PHYSICAL.value` **and** point
   `PARCEL_ONLINE_MAP_PATH` at a *different file* from any sim run's, or the map
   store will refuse to load (that refusal is the point). The out-of-process
   detector daemon must also carry the crop embedding and its space across the
   IPC boundary, or physical entries silently regress to no embedding — the
   record's `embedded` property is the check.
3. **P1-D — `online_map/naming.py` is yours and the rest of `online_map/` is
   mine**, per the board. The public API you need is stable:
   `MapEntry.names` / `admissible_names()` / `ProposedName`, and
   `OnlineSemanticMap.propose_name`. Note `MAP_SCHEMA` is now
   `parcel.online_map.v2` and `MIGRATABLE_SCHEMAS` is the forward-migration list —
   if naming changes a persisted meaning, bump to v3 and add v2 to that tuple
   rather than refusing existing stores.
4. **`evals/companion_nav/runner.py:608` still compounds** — P0-D's handoff 1,
   untouched by this card and still true.
5. **`_install_perception_chain` hardcodes `configs/navigation/default.yaml`**
   while this card's region resolves `navigation.config`. So a profile pointing
   at `prototype.yaml` gets the prototype's `semantic_source` and the *shipped*
   perception tier. One line, in P0-D/C-3 territory, not fixed here.
6. **`configs/navigation/prototype.yaml` still is not in
   `tools/sync_runtime_assets.py`** (P0-D's handoff 2), so the `online_map` block
   does not ship in the wheel's `runtime_assets` either.
7. **No incremental persist.** §8.6. If a run is expected to be long or to end by
   being killed, the map needs a periodic `persist()`; the method is public and
   idempotent (upsert), so this is a scheduling decision, not a design one.
8. **Any new caller of `OnlineSemanticMap.resolve()` must take
   `runtime._p1b_map_lock`** — or give the map its own lock first. §8.10 has the
   reasoning: the map has no internal lock, today's writers are serialised only
   because the runtime's lock happens to wrap them, `active_entries()` and
   friends are GIL-atomic and therefore safe, and `resolve()` — which iterates
   the live entry dict across several statements — is not. It has no product
   caller today, which is the only reason this is a handoff. **NM-1 / VENUE-1
   consumers and any panel endpoint are the ones that will trip it**, with a
   `RuntimeError: dictionary changed size during iteration` in the middle of a
   patrol. The cheap fix is a lock inside the map; the correct owner is whoever
   adds the first cross-thread reader.

---

## 10. Owner-gated rows (camera)

Nothing in this card requires the owner. These rows are **listed, not claimed** —
the same code path runs, and only the venue changes:

| Row | Command, once a camera is attached (P1-A) |
|---|---|
| the room map builds from real pixels | P1-A's `--camera` launcher + `perception.semantic_source: shadow`, `PARCEL_ONLINE_MAP_PATH=<a NEW file>` |
| entries stamp `PHYSICAL` | assert `entry.provenance.is_physical`; the mixed-store refusal (§6) is what makes a fresh file mandatory |
| relief separates a real object from a printed one | needs a scene containing a poster; `city_block` has none (§8.3) |
| SigLIP-2 retrieval beats the label hash | needs the retrieval bench re-run on embedded entries (§8.2) |

Owner actions this card does not need and does not touch: voice enrollment, the
XVF3800 udev rule, the synthetic-memory quarantine, the H-1 Orin dump.

---

## 11. Post-verification corrections (2026-08-22)

*(This is the "§9 post-verification corrections" Fable's verdict asked for; it is
numbered 11 because §9 in this document is Handoffs and §10 is the owner-gated
rows. Verdict: DISCREPANCIES_FOUND — every pre-registered row, D-R1/D-R2, the
seeds re-run on a scratch copy of the current tree, the R24 edge read from the
code paths, region hygiene and the §7.1 trade all verified, several reproduced
independently. What follows are the seven findings and what was done about
each.)*

### 11.1 PRODUCT DEFECT — the store's WAL was never checkpointed

**Found:** `OnlineMapStore.__init__` sets `journal_mode=WAL`; nothing ever called
`OnlineSemanticMap.close()` or `OnlineMapStore.close()`, and the map object was
simply dropped with the runtime. SQLite checkpoints when the **last connection
closes** — at interpreter exit — so between `persist()` and process death the
freshly written rows lived in `<store>-wal`, and a `-wal` sidecar coexisted with
the store for the whole run. Anything that read the store file in that window —
an operator, a `cp`, the evidence pack hashing it — saw fewer places than the
robot had learned. **This is the same class of defect as AU-C2-1** (the write
looked like it happened and the bytes were not where the name said), which is
why it was worth a card's attention rather than a shrug.

**Fixed:**
* `OnlineMapStore.close()` now runs `PRAGMA wal_checkpoint(TRUNCATE)` before
  closing — TRUNCATE, not PASSIVE, so it blocks until the whole WAL transfers
  and then empties it, leaving **one self-contained file** with no `-wal`/`-shm`
  companions. A checkpoint failure is logged and swallowed; the close still
  happens, and the rows are still WAL-recoverable.
* `OnlineSemanticMap.close()` is new: it releases the store and keeps the
  entries, so teardown can still read `entries()` for the snapshot, and it is
  idempotent. Persisting after closing is a `MapRefused`, not a silent no-op that
  would look exactly like a successful write.
* `_p1b_persist_learned_map` calls `learned.close()` **inside `_p1b_map_lock`,
  immediately after the write**, and the no-persist and failed-persist paths
  both release the file through `_p1b_close_learned_map` — a failed persist must
  not also leak the connection.

**Seeded RED:** S-8 (`OnlineSemanticMap.close` body removed) and S-9 (the
runtime's call removed). Both went RED, restored byte-identically, came back
GREEN. The test measures it the way a reader really does — a **second**
connection opened read-only, which before the fix saw 0 rows.

**Store-file shas: regenerated, and here is which digest is load-bearing.** With
the WAL checkpointed the `.sqlite3` is now a complete artifact, so the packs
record its sha (`62ea630b…` run 1, `6bf1a5d2…` run 2) as a fingerprint of *that
file*. It is **not** claimed to be reproducible across runs: a SQLite file
carries a change counter, page ordering and free-page state that two logically
identical runs need not share. **The reproducible digest is the `as_dict`
corpus sha256** (`a2e29f01…` / `d09854cc…`), which is over the map's own
serialization and is what R-4 is measured on. Both are in every pack, labelled.

### 11.2 The owner-store check was VACUOUS

**Found:** the harness hashed `~/.parcel/parcel_memory.sqlite3`. **That file does
not exist on this host.** All three packs therefore reported
`{before: None, after: None, unchanged: True}` — a claim that would have been
`True` with the real store on fire. Inherited from MOVE-1's harness and repeated
without checking, which is exactly how R27's original incident propagated.

**Fixed:** the harness reads `memory_path.owner_store_paths()[0]` — the same
authority the online map's own R27 refusal gate uses, so the measurement and the
guard now name one file. It resolves to `<repo>/parcel_memory.sqlite3`
(**which does exist**). The pack row gained `path` and `existed`, and
`unchanged` is now `bool(before) and before == after`, so a `None == None`
cannot ever again read as evidence.

**Re-measured, read-only** (hashed, never opened for write) across all four
regenerated runs: sha256
`0373297f818727cde96c8bf2254bd128e7bc2f829e49493d3229eb7c4e13da0d`, identical
before and after each. The pre-existing mtime `02:19:01` is untouched.

**Stated plainly: the original "the owner's store is unchanged" claim in this
document was never measured.** It is measured now.

### 11.3 The 34-phrase oracle pack had been overwritten

**Found:** the run backing §5's headline was overwritten by a second flag-off run
into the same output directory, so the pack no longer contained the arm the
prose described.

**Fixed:** the two arms are now separate packs with distinct paths and distinct
configs — `evidence/p1b_oracle_sidecar_batch/` (34-phrase batch ON) and
`evidence/p1b_flag_off/` (shipped default) — and the ON arm is driven by
`evidence/nav_oracle_sidecar_batch.yaml`, a measurement-only copy of
`default.yaml` with exactly one key added. §5 and §7.1 now quote the regenerated
numbers (632/1 016 truncated versus 57/404), and so do the config comment and
the code comment that cite them.

**The seed harness output is now a file**, `evidence/SEEDED_RED.txt`, produced by
`evidence/seed_p1b.py` (also committed to the pack). It previously existed only
as a paste in this document.

### 11.4 §8.7 was wrong, and the accounting did not reconcile

**Found (doc):** §8.7 claimed "the published frame dict … unchanged" under
`oracle`, which §3 and §7.6 of this same document contradict — the frame gained
`origin`, `embedded_detections`, `relief_measured_detections`. **Fixed:** §8.7 is
rewritten to say what actually changes, and it now marks the SigLIP-2 per-crop
cost as **cited from P0-C, not measured here** (what this card observed is only
that the loop held cadence, 2.013 Hz against 2.0).

**Found (accounting):** the three cards' shares of `runtime.py` summed to
+970/−8 against a file total of +977/−11, and the **fourth** marked block (the
19-line init state) was missing from the table.

**Fixed:** §1 no longer classifies hunks by keyword — that method is what
under-counted this card by 70 lines. P1-B's share is now measured by
**reconstruction**: every edit was a recorded exact-match replacement, so the
pre-P1-B text is rebuilt by reverse-applying them all and diffed with
`git diff --no-index`. Script and output are in the pack
(`evidence/reconstruct_p1b_share.py`, `evidence/SHARE_RECONSTRUCTION.txt`; the
replacement payloads live in this card's scratch dir). The corrected share is
**`runtime.py` +547/−2**, not +472/−2, and all four marked blocks are listed in
§1 with their line spans and sizes.

Two things the method surfaced that hunk-reading would not have: card P1-D's
one-line edit inside `online_map/online_map.py` shows up as the 4-line gap
between +74 (mine) and +78 (the file), and when P1-D later inserted a line into
the context of my `test_p0d_navigation_unblocks.py` payload the reverse-apply
**refused rather than mis-attributing**, and was re-keyed onto P1-B's own six
lines. An attribution method that breaks when a neighbour edits the same file is
not an attribution method — in this wave, concurrent writers are the normal case.

### 11.5 `scene_id` recorded the config filename, not the scene

**Found:** `WriterProvenance.scene_id` came from
`Path(self._camera_scene_path or self.store.path).stem`, and
`_camera_scene_path` is set by the camera attach — which this card deliberately
runs **after** the map install. So the fallback always won and every entry in
every run was stamped `p1b`, the stem of a throwaway harness YAML, where it meant
`city_block`. Not a safety defect (`origin` is what the store's mixing refusal
reads), but a map outlives the run that wrote it, and an entry that cannot say
which world it came from is a rumour with coordinates.

**Fixed:** `_p1b_scene_id()` resolves through `sim.resolve_scene` — the same
function the camera attach uses, so the two cannot name different worlds — and
degrades to `"unknown"` rather than to a misleading filename. The install
ordering is unchanged, because it is load-bearing for the query batch.
**Seeded RED:** S-10 restores the old derivation. Both regenerated packs now
report `scene_ids: ["city_block"]`.

### 11.6 The map has no internal lock — documented, not fixed

Raised by the verifier and correct. Today's writers are serialised, but by the
**runtime's** lock, which lives outside the map; `active_entries()` and friends
are GIL-atomic and safe as written; `resolve()` iterates the live entry dict
across several statements and is not. It has no product caller, which is the only
reason this is a note. Written up in **§8.10** with the mechanism and in
**§9.8** as the handoff: any future cross-thread caller (NM-1, VENUE-1, a panel
endpoint) must take `runtime._p1b_map_lock` or give the map its own lock.

### 11.7 The held-out scene's name was in a test file

**Found (coordinator addendum):** `tests/test_p1b_map_learns.py` used the
held-out scene's filename as an arbitrary example in the `_p1b_scene_id`
assertion, which reddened `tests/test_held_out_scene.py`'s isolation scan.

**Fixed:** replaced with an invented neutral name (`desk_room.xml` →
`desk_room`); the assertion only ever needed "an explicit path wins and keeps its
stem". **No allowlist seat was added** — the reference was gratuitous, and a seat
would have preserved it. `pytest tests/test_held_out_scene.py -m "slow or not
slow"` → **7 passed**, and no P1-B file appears on the scan's list. The held-out
scene remains unspent and unnamed by this card.

### 11.8 Re-verification after the corrections

The four evidence packs were **regenerated from scratch on a quiet tree** and the
earlier ones deleted rather than patched — they carried the vacuous owner check,
the `p1b` scene id and un-checkpointed stores, so keeping them would have left
two generations of numbers in one document.

One process note worth recording: the first regeneration attempt overlapped with
a seeded-RED run. The seed harness mutates real source files for seconds at a
time, so a simulator starting inside that window can import a seeded module.
**Those packs were discarded and both were re-run serially, alone.** No claim in
this document rests on a run that overlapped a seed.

```
$ .parcel/bin/python -m pytest -q -p no:randomly  <the §4.2 selection>
504 passed, 2 warnings in 16.77s
$ .parcel/bin/python -m pytest -q tests/test_p1b_map_learns.py
37 passed
$ .parcel/bin/python -m pytest -q tests/test_held_out_scene.py -m "slow or not slow"
7 passed
$ .parcel/bin/ruff check  <OWNS + the harness>
All checks passed!
```

Ten of ten seeds RED → byte-identical restore → GREEN
(`evidence/SEEDED_RED.txt`). `scripts/ci_gate.py` and the full default suite
were still not run: P0-E owns the gate.
