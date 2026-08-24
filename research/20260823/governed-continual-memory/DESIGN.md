# H5 — governed continual memory · DESIGN (Fable) · 2026-08-23

## Hypothesis (falsifiable)
If distillation is **scheduled** (session close + idle tick), tiers 2/3 are
**persisted**, an **episodic layer** records dated events/outcomes, and a
**`query_world`** answer path reads the learned map, then on held-out probes
the dog (a) passes ≥ 13/13 of `personal_convo_v1` with a LIVE local
summarizer+proposer (recorded baselines: 12/13 deterministic fixture, 13/13
deterministic summarizer, **3/13 live summarizer**), (b) proposes facts with
precision ≥ 0.9 against the fixture graph, (c) never resurfaces a revoked
fact in a later session's DI, and (d) answers "where is X" from a replayed
learned map with top-1 ≥ 0.8 on present objects and 100 % refusal on absent
ones — all with **$0** hosted spend.

## Why (grounding — memory survey 2026-08-23)
- `distil_session` has **zero callers**; Tier 3 is `null_distiller`
  (`prompting/dynamic.py:~737`); `prompting.memory` off by default;
  `TieredMemory` has no store — every summary/fact dies with the process
  (`memory/tiered.py`). `P2A_STATUS.md:553-556` says so in prose.
- Governance is the strongest area (consent states, soft delete,
  provenance columns, ~120 pinning tests) — so the risk is not safety, it
  is that **nothing runs**. The owner's ask ("recursively learn") is
  impossible by construction today.
- The live-summarizer probe result (3/13) is the real unknown: does a local
  model summarize/propose well enough, or is the deterministic path the
  only honest one? This experiment answers that with the GPU reasoner.
- World queries: `OnlineSemanticMap.resolve` + `last_seen_wall_s` exist;
  no broker tool exposes them (`realtime/lane.py:~258 DEFAULT_ANSWER_TOOLS`).
  WORLD-1 (`scrum/20260823/TRANCHE2_MIND_DESIGN_FABLE.md`) specified the
  pure `online_map/answers.py` renderer — build it here as the harness's
  answer path (product wiring is a milestone card).

## Objective
Show that continual, governed learning is a scheduling-and-persistence
problem we can close now, and measure the local model's fitness for it.

## Experiment
1. **Isolated store**: `PARCEL_MEMORY_PATH` = a fresh sqlite under the
   experiment folder (never the owner's `parcel_memory.sqlite3`; never set
   `PARCEL_MEMORY_PURPOSE=owner`).
2. **Corpus**: `evals/companion/personal_convo_v1/build_memory_fixture.py`
   + `memory_graphs/*.yaml` — build ≥ 3 synthetic owner histories (≥ 40
   turns each) with ground-truth facts, contradictions, corrections, and
   revocations; hold out the `cross_session_memory` and
   `fact_tool_composition` probe families.
3. **Scheduler** (`memory/scheduler.py`, new leaf, flag `memory.continual`
   default OFF): `on_session_close()` and `on_idle(tick)` call
   `owner_model.distiller.distil_session` with a `LanguageModelFactProposer`
   bound to the local GPU reasoner (`:8081` via `scripts/launch_reasoner_gpu.sh`;
   if it is not up, the executor starts it on 8081 and stops it after), the
   `owner_model.guard` synthetic-range refusal preserved.
4. **Persistence** (`memory/tiered.py` gains `save(path)`/`load(path)`
   for tiers 2/3 as JSON rows with provenance; or a sqlite table in
   `memory/store.py` — executor's choice, documented).
5. **Episodic layer** (`memory/episodes.py`, new): `Episode(frozen)` =
   {started, ended, kind ∈ {conversation, mission, sighting}, summary,
   outcome, refs to turns/facts/map entries}; written at session close and
   at mission terminal events in the harness (product wiring later).
6. **World-query path** (`online_map/answers.py`, pure): render
   `resolve()`/`around_me()`/`last_seen_wall_s` into label-primary,
   past-tense-provenanced answers ("I last saw a bench about 4 m to my
   left, two visits ago"); replay archived C-1 detection streams
   (`tests/test_p1b_map_learns.py:~849` shows how) into an
   `OnlineSemanticMap` with `PARCEL_ONLINE_MAP_PATH` set; a fixed 30-question
   set with 10 absent nouns.
7. **Probes**: run the 8 probe families through the fake realtime server
   rails (`tests/test_p2a_memory_probes.py`) across ≥ 2 sessions each, with
   the five OT-2 speaker labels cycled for the revocation matrix.

## Measurements (pre-registered)
| row | metric | criterion |
|---|---|---|
| M1 | probe pass rate, live summarizer+proposer | ≥ 13/13 (report per family) |
| M2 | fact precision / recall vs graph | precision ≥ 0.90, recall reported |
| M3 | granted facts absent from the graph (confabulation) | 0 |
| M4 | revoked facts reachable in a later DI | 0 |
| M5 | consent matrix (5 labels × channels) vs `GRANTING_LABELS` | exact |
| M6 | world-query top-1 on present / refusal on absent | ≥ 0.80 / 100 % |
| M7 | persist → reload → identical answers | byte-identical |
| M8 | scheduler cost: distillation wall time per session on GPU | reported |

## What would refute it
M1 < 10/13 with the live proposer while the deterministic path passes ⇒
the local model is not fit for distillation; the design then keeps the
deterministic proposer and uses the model only for summaries (report which).

## Evidence tier / does not prove
`replay` + `desktop` (local GPU). Proves the mechanism and the local model's
fitness on synthetic histories; does not prove real-owner quality, nor that
the runtime calls the scheduler (product wiring is a milestone card).

## OWNS (disjoint from other hypotheses)
`research/20260823/governed-continual-memory/**`, new leaves
`memory/scheduler.py`, `memory/episodes.py`, `online_map/answers.py`,
additive methods in `memory/tiered.py`; one capability test
`tests/test_h5_continual_memory.py`. Must not touch: `runtime.py`,
realtime lanes, the owner's store, `owner_model/guard.py` semantics,
`configs/robot.yaml` (the flag lives in code with default OFF; an overlay
YAML under the research folder turns it on for the harness).
