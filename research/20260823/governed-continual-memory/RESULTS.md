# H5 — governed continual memory · RESULTS (Opus) · 2026-08-23

Contract: `DESIGN.md`. No criterion was moved. Hosted spend **$0.00**.

## 0. Headline

**Scheduling and persistence are the whole gap, and closing them works.** With
`memory/scheduler.py` calling `distil_session` at session close and on an idle
tick, tiers 2/3 persisted, an episodic layer writing at session close, and the
pure `online_map/answers.py` renderer over a replayed map, **6 of the 8
pre-registered rows are MET** (M2, M4, M5, M6, M7, M8), **M1 is a MISS at 3/13**
and **M3 is a MISS at 1** — and both misses have measured causes that are not the
mechanism this experiment built.

Four defects found on the way, all in code predating this card:

1. **`distil_session(session_id=…)` always reads zero turns.** It filters on
   `turn["session_id"]`; `ConversationMemory.conversation_turns()` — the reader
   it calls — never emits that key. Any session id makes the pass a silent no-op
   on every store. The scheduler is the first caller to hit it, and works around
   it by never forwarding one (documented at the call site).
2. **`LanguageModelFactProposer` can never parse a reply.** It parses a JSON
   array out of `LanguageModel.decide(...).reply`, and the tree's only
   `LanguageModel` (`LlamaCppProvider`) pins `decide` to the AgentDecision
   schema, whose `reply` is prose. **Degrade rate 12/12 = 1.00** against the live
   reasoner: every "live" distillation is silently the regex proposer.
3. **A revoked fact comes back on the next scheduled pass.** `add_owner_fact`
   upserts on `key = ? AND deleted_at IS NULL`, so a tombstoned row is invisible
   to it and a re-read of the same turns INSERTS the fact again, `granted`.
   **3 resurfaced** across arms with the pre-H5 behaviour, **0** with the
   tombstone check.
4. **The world query refuses everything at the shipped operating point.**
   `AbstentionPolicy.ranking_margin_mode` defaults to `robust_z`, whose MAD is 0
   for any query matching under half the map: top-1 **0/20**. With
   `label_strength` — the mode P0-D added for this, one config key away — **20/20**.

## 1. Environment

* Tree at `0ec1d7c` (DEC-FS-1). Python `.parcel/bin/python`, ruff 0.16.1.
* GPU reasoner on `:8081` (gemma-4-26b-a4b, CUDA b10236) was **already up,
  started by H2's executor** (pid 1695074, log
  `research/20260823/local-cognition-gpu/logs/gemma8081.log`); `/health` answered
  `{"status":"ok"}`. H5 started no model server and stopped none.
* GPU shared throughout with H2/H6; `nvidia-smi` recorded on every live row
  (`gpu_before`/`gpu_after`). M8 **re-measured at 3 % util**
  (`results/m8_remeasure.json`): median 5.18 s, inside the 4.6–5.5 s band the
  contended runs produced.
* Owner store `parcel_memory.sqlite3`: sha256 `bc85277679250c74…`, mtime
  `2026-08-23 16:11:17` — the same before and after, and the mtime predates this
  card's first command. `PARCEL_MEMORY_PURPOSE` was never set; every store is a
  fresh sqlite under the scratch dir or `tmp_path`.

## 2. What was run

```
PYTHONPATH=src:.:research/20260823/governed-continual-memory \
  .parcel/bin/python -m harness.run_h5 --work <scratch>/work --rows all
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h5 \
  .parcel/bin/python -m pytest -q tests/test_h5_continual_memory.py
```

Corpus (`harness/histories.py`): 3 synthetic owner histories, **48 turns each**
(24 owner turns, 7 distractors), 3 sessions each, 39 ground-truth facts incl. 3
revocations, 3 corrections, 3 credentials, 10 sensitive. `cross_session_memory`
and `fact_tool_composition` are held out: nothing in the corpus was written by
looking at them or tunes anything M1 measures.

## 3. The pre-registered table
| row | metric | criterion | measured | met? |
|---|---|---|---|---|
| M1 | probe pass rate, live summarizer+proposer | ≥ 13/13 | **3/13** (arm C) · 13/13 (arm B) · 13/13 (arm A) | **NO** |
| M2 | fact precision / recall vs graph | precision ≥ 0.90 | **0.96** / recall 0.86 (live chat) · 1.00 / 0.64 (deterministic) | **YES** |
| M3 | granted facts absent from the graph | 0 | **1** (live chat) · 0 (deterministic, shipped seam) | **NO** |
| M4 | revoked facts reachable in a later DI | 0 | **0** (tombstone on; 3 with it off) · 0/5 labels on the lane | **YES** |
| M5 | consent matrix (5 labels × channels) | exact | **20/20 cells**, 0 mismatches | **YES** |
| M6 | world-query top-1 present / refusal absent | ≥ 0.80 / 100 % | **1.00 (20/20) / 100 % (10/10)** at `label_strength`; 0.00 / 100 % at the shipped default | **YES** (at one of two operating points) |
| M7 | persist → reload → identical answers | byte-identical | **byte-identical** snapshot, identical retrieval, identical 30 world answers | **YES** |
| M8 | distillation wall time per session | reported | **median 4.6–5.5 s** GPU-live · **1.7 ms** deterministic (12 passes per arm) | **YES** (reported) |

### M1 — three arms, so the number can be attributed
| arm | companion | Tier-2 summarizer | Tier-3 proposer | turns | wall |
|---|---|---|---|---|---|
| A | fixture | deterministic | none | **13/13** | 0.01 s |
| B | fixture | **live** (`:8081`) | live, persisted+reloaded | **13/13** | 64 s |
| C | **live** (`:8081`) | **live** | live | **3/13** | 174 s |

Arm A reproduces the ledger's tiered baseline. **Arm B is the H5 claim and it
passes**: with a live local summarizer and every probe answer served from a
tiered store *saved to disk and loaded back*, all 8 families pass. Arm C
reproduces the recorded 3/13 live-companion row, and its failed categories are
`word_budget` 8, `clarification` 6, `fact_recall` 6, `tool` 1 — the local
**companion's prose**, not the memory, since arm B supports 13/13 on the same
window and summarizer. Live summary quality (report-only): `contains_offer` true
in both live arms, `durable_fact_coverage` **0.50** in arm B (baseline 0.25),
`used_fallback` true. Judge `qualified`; `pack_digest`
`353e2d779b…` identical on all three arms — the frozen pack did not move.

**The DESIGN's refutation clause fires, for a different reason than anticipated.**
M1 < 10/13 live while the deterministic path passes — but not because "the local
model is unfit to distil": on the probe path the proposer is never reached (§M7),
and where it *is* reached (M2) it scores 0.96 precision. Honest reading: **use
the local model for summaries now**; the proposer is blocked on a seam fix.

### M2 / M3 — five arms over the three histories
| arm | proposer | prop. precision | prop. recall | row precision | granted absent from graph |
|---|---|---|---|---|---|
| `det_norevocation` | regex | 1.000 | 0.639 | 1.000 | 0 |
| `det_revocation` | regex | 1.000 | 0.639 | 1.000 | 0 |
| `seam_revocation` | shipped `LanguageModelFactProposer` | 1.000 | 0.639 | 1.000 | 0 |
| `chat_norevocation` | research `ChatFactProposer` | 0.958 | 0.861 | 0.958 | 1 |
| `chat_revocation` | research `ChatFactProposer` | 0.957 | 0.861 | 0.957 | 1 |

`seam_revocation` produces **byte-identical rows to the deterministic arm** plus
65 s of latency — finding 2 in numbers (`degrade_rate` 1.0, 0/12 replies
parseable).

**M3 = 1, adjudicated rather than argued away.** The three rows absent from the
graph — *"Hana lives two streets away"*, *"Biscuit is nine years old"*, *"Their
cat is entirely nocturnal"* (one `granted`, two `pending`) — are all **true**
statements the owner made that the graph does not enumerate. By the letter of the
criterion that is 1 and the row is a MISS; by inspection **zero** of the live
proposer's facts are false. The graph under-enumerates; the criterion stands.

### M4 — revocation, both halves
* **Distillation half** (`facts.py`): 3 revoked facts resurfaced with
  `respect_revocations=False` (2 deterministic, 1 live); **0** with it on, in
  every arm. The seeded RED is a flag, not a patch, and is parametrized in the
  capability test.

* **Lane half** (`consent.py`): 5 OT-2 labels × 3 sessions — store, forget, then
  a **fresh lane on the same file**. 0 of 5 carried the fact into the later
  developer instruction; the soft-deleted row survives, as P2-A designed.
* Unbudgeted finding: **forgetting by the owner's own noun misses.** "Forget
  what I told you about my medication" → the key minted was
  `blood_pressure_medication`, so `forget_owner_fact("medication")` returned **0
  rows**. The harness resolves the key by value instead; 1 of 3 nouns was the key.

### M5 — the consent matrix

20/20 cells exact, 0 mismatches, through the real `RealtimeLane` +
`FakeRealtimeServer` + `RealtimeToolBroker` + real policy, with the runtime's
OT-2 door (`admit_consent`) reproduced on the write seam. Expected values are
derived from `GRANTING_LABELS`, never a literal, so a sixth label would land in
the matrix rather than outside it. `owner`/`unenrolled` → `granted` and rendered
into the DI on all four channels; `unverified`/`not_owner`/`ungated` → `pending`
and rendered nowhere, on all four.

### M6 / M7 — the world query

Replay: the 16 archived C-1 frames (`tests/data/c2_online_map_frames.json`) —
measured to carry **one noun**, 40 `lamppost` detections — plus **84 synthesized
frames in the identical `CameraDetectionFrame` schema** carrying seven labels the
map's own `SIZE_PRIORS` screen, over 4 visits with a 37-pose patrol so
navigability is measured rather than zero. 8 entries, 12–16 evidence frames each,
navigability 0.25–0.625. The synthesized half is a fixture, labelled as such: M6
is honest as *"a map of this shape answers this well"*.

| operating point | top-1 present | refusal absent | reload identical |
|---|---|---|---|
| shipped default (`robust_z`) | **0/20** — every query `indecisive_ranking` | 10/10 | yes |
| `ranking_margin_mode="label_strength"` | **20/20** | 10/10 | yes |

Sample answers — label-primary, past tense, provenance attached, never a
present-tense presence claim:

```
the bench near here   -> I last saw a bench about 7 m away straight ahead,
                         earlier today, on 4 separate visits.
where is the fountain -> I have not seen anything like "where is the fountain"
                         anywhere I have been.
```

M7 holds on both halves: the map persists 8 entries, reloads into a fresh map and
answers all 30 questions **identically**; a `TieredMemory` snapshot round-trips
**byte-identically** (3,459 bytes; no clock in the file by construction) with
identical Tier-1/2/3 retrieval. A second, four-session case shows Tier 3 holding
2 distilled rows across the round trip — necessary, because the frozen
`cross_session_memory` graph puts every event in **one** session, so Tier 2 never
overflows and **Tier 3 is unreachable on the probe path whatever distiller is
injected** (`h5_tier3_keys: []` in every arm). That is why M1 cannot measure a
proposer.

## 4. Files
**Product — all in the DESIGN's OWNS, all flag-off or additive:**
| file | lines | what |
|---|---:|---|
| new `src/parcel_robot/memory/scheduler.py` | 496 | `ContinualMemoryScheduler` (`on_session_close`, `on_idle`), `ContinualMemoryConfig` (`memory.continual`, **default OFF**), `RevocationAwareProposer`, `revoked_fact_keys` |
| new `src/parcel_robot/memory/episodes.py` | 341 | `Episode` (frozen) + append-only `EpisodeLog`, owner-store path refused by identity |
| new `src/parcel_robot/online_map/answers.py` | 341 | pure `where_is` / `what_is_around` / `describe_*`, no clock, no I/O, no map import at runtime |
| `src/parcel_robot/memory/tiered.py` | +169/−2 | additive `snapshot()` / `save()` / `load()` / `restore()`, `TIERED_SNAPSHOT_SCHEMA` |
| new `tests/test_h5_continual_memory.py` | 401 | 10 tests, the one capability proof |

Nothing else in `src/` was touched: no `runtime.py`, no realtime lane, no
`owner_model/*`, no `configs/robot.yaml`. Nothing in the product constructs the
scheduler — wiring is a milestone card, as the DESIGN says.
**Research:** `harness/*.py` (7 modules), `memory_continual_on.yaml` (the only
place the flag is switched on, read through `ContinualMemoryConfig.from_settings`),
and raw rows in `results/`: `m1_probes.json` + `m1_<arm>_full.json`,
`m2_m3_m4_m8_facts.json`, `m4_m5_consent.json`, `m6_m7_world.json`,
`m7_tiered_persistence.json`, `m8_remeasure.json` (604 KB).

## 5. Tests run
```
test_h5_continual_memory.py                                        10 passed
+ test_tiered_memory / test_p2a_owner_model / test_p2a_memory_probes
  / test_ot2_memory_principal / test_p1b_map_learns                195 passed
test_dec0_debt_ratchet / test_decig2_import_ratchet
  / test_owner_store_isolation / test_conversation_store      215 passed, 1 failed
ruff check on every file added or changed                    All checks passed!
```
Zero `noqa` in any file added or changed (the blind-`except` a background pass
needs is satisfied with `logger.exception` instead).

The one failure is **`test_decig2_import_ratchet.py::test_the_measurement_stays_cheap`**
— a wall-clock budget (`elapsed < 10.0`) measuring 13.6 s and 15.2 s on a host
running six research harnesses and two GPU servers. Both ratchet files passed
together earlier in this card when the box was quieter; the assertion is about
scan speed, not structure. **Not H5's**; flagged as load-sensitive.

## 6. Surprises
* The `session_id` no-op means P2-A's distiller has never been exercised through
  its own session filter by anything, including its tests.
* A degrade that is silent *and* total is worse than a failure: the "live" seam
  arm is indistinguishable from the offline one in every row except latency.
* `distil_session` writes `granted` rows directly and `DISTILLER_PRINCIPAL`
  (which may not grant) is applied only at the broker door, so a **scheduled**
  pass grants consent a hand-driven proposal would not. Out of OWNS, unfixed.
* The policy parks the owner's own name as `pending` — `"they are called Elena"`
  has no `NAME_SUBJECT` token, so it classifies `other` → ask.
* Given the whole window, the live chat proposer did **not** re-propose the
  revoked medication fact after reading the owner's "forget that" turn — pleasing,
  not a guarantee; the tombstone check is what makes it a property.

## 7. Cost — $0.00
No hosted API call was made; local GPU only, on a server this card did not start.

## 8. What this does not prove
* **Nothing in the runtime calls any of this.** The scheduler, episode log and
  answer renderer have no product caller; every number comes from the harness.
* **No real owner data.** Three synthetic histories, 144 turns, written by the
  same executor who wrote the scorer; real transcripts have no ground-truth graph.
* **M6's map is mostly a fixture.** 84 of 100 frames are synthesized; the real
  16 carry one noun. Nothing here says the *detector* finds benches — only that a
  map holding them answers correctly.
* **M1 arm C is one run** on a shared GPU. The live fact arms ran twice:
  precision moved 0.95→0.96 and one leak appeared in run 2's flag-off arm.
* **`label_strength` is not shipped.** M6's passing column needs a config key
  nobody has set, on a gate this card did not touch or regression-test.
* **No hosted model chose to call anything.** Every lane tool call is scripted,
  as in P2-A.
