# H5 — governed continual memory · VERDICT (Fable) · 2026-08-23

Verifier: Fable, slug `h5`. Tree HEAD `cd1e584` + uncommitted research wave.
Scratch: `…/scratchpad/verify-h5/` (`rerun_cpu.json`, `rerun_gpu.json`, `m8_chat.json`,
`m1_*_full.json`, `m5_consent.json`). GPU `:8081` (gemma-4-26b-a4b, pid 1695074, H2's) answered
`/health`; nothing started or stopped. Load avg 105 on 192 cores; GPU 1–2 % util before my runs.

## Disposition

| row | criterion | executor | verifier re-run | disposition |
|---|---|---|---|---|
| M1 | ≥ 13/13 live summarizer+proposer | 3/13 (C) · 13/13 (B) · 13/13 (A) | **4/13 (C) · 12/13 (B) · 13/13 (A)** | **REFUTED** |
| M2 | precision ≥ 0.90 | 0.96/0.86 chat · 1.00/0.64 det | 0.969/0.861 chat · 1.00/0.639 det | CONFIRMED-WITH-NOTES (chat arm is harness-only) |
| M3 | granted absent from graph = 0 | 1 chat · 0 det | 1 chat · 0 det | **REFUTED** by the letter (the 1 is a true owner sentence) |
| M4 | revoked fact in later DI = 0 | 0 on / 3 off; lane 0/5 | 0 on / 2 off (corpus, all `pending`); keep-fact DI: leaks off, holds on; lane 0/5 | CONFIRMED-WITH-NOTES (the 0 is the new scheduler leaf's tombstone check) |
| M5 | consent matrix exact | 20/20 | 20/20, 0 mismatches, DI rendering exact | CONFIRMED |
| M6 | top-1 ≥ 0.80 / refusal 100 % | 20/20 · 10/10 at `label_strength`; 0/20 shipped | identical (answers byte-equal to executor's) | CONFIRMED-WITH-NOTES (only at a mode nothing shipped selects; set is easy) |
| M7 | persist → reload byte-identical | yes (3,459 B) | yes (3,459 B; tier-3 case and 30 map answers identical) | CONFIRMED |
| M8 | GPU distillation wall (reported) | median 4.6–5.5 s; 5.18 s quiet | **median 5.07 s** (3.49–6.67), GPU 2 % → 76 % (my load) | CONFIRMED (reported, harness-only) |
| **overall** | conjunction (a)–(d) | "6 of 8 MET" | (a) missed twice, (b)'s M3 missed twice; refutation clause fires | **REFUTED as pre-registered**; mechanism rows CONFIRMED-WITH-NOTES, all harness-only |

The DESIGN's refutation clause ("M1 < 10/13 live while deterministic passes ⇒ keep the
deterministic proposer, model for summaries only") fires on both the executor's run and mine.
My arm B (fixture companion, live summarizer) scored 12/13, so "summaries only" is not yet a
measured win either: the pack's own deterministic path is 13/13.

## 1. Re-runs (commands: harness functions called directly, outputs to scratch, never `results/`)
* **M1** (`probes.run_probe_arm`, all three arms, one run each): A 13/13 · B 12/13 · C 4/13.
  Arm B's miss is `cross_session_memory.s_later.t1 fact_recall`: the Tier-2 summary served from
  the reloaded snapshot reads *"…They are moving assistant: Nice — a tidy kitchen…"* — a
  `ConcatSummarizer` fragment, i.e. the live summarizer fell back (`used_fallback: true` in
  both my run and the executor's; `live_provider.py:137,142` set it on any exception or empty
  reply and the count of fallbacks among the 8 calls is not recorded). Arm C's failures are
  `clarification` 6, `word_budget` 7, `fact_recall` 3, `tool` 1 (theirs 6/8/6/1).
  Tolerance: the live arms are temperature 0.2/0.25 single runs; B moved 13→12, C 3→4.
* **M2/M3/M8** (`facts.run_arm` chat_revocation): precision 0.9688 / recall 0.8611, granted-absent
  1 (same row: *"Hana lives two streets away"*), 0 leaks, 12/12 replies parsed, median 5.07 s.
* **M4** (`facts.run_arm` det ×2 + a keep-fact DI case, see §4) and **M5** (`consent.*`): above.
* **M6/M7** (`run_h5.run_world`, `run_h5.run_persistence`): every one of the 60 answer strings
  equals the executor's at both operating points; snapshot 3,459 B byte-identical twice.

## 2. Product-path check — every capability is harness-only
* No file in `src/parcel_robot` constructs `ContinualMemoryScheduler`, `EpisodeLog`, or calls
  `online_map.answers.where_is` (grep; only the three leaves, `tests/test_h5_*`, harness).
* `TieredMemory.save/load` (`memory/tiered.py:+169`) has no product caller;
  `prompting/dynamic.py:737` still builds `TieredMemory(... distiller=null_distiller)`.
* `distil_session` still has zero product callers (`runtime.py:9060` is a docstring mention).
* Flag: `ContinualMemoryConfig.enabled = False` (`memory/scheduler.py:111`); no `continual` key in
  `configs/`; the only ON is `research/…/memory_continual_on.yaml`. Capability test passes
  (10/10 through the guard). M5's OT-2 door is the harness's 3-line copy (`consent.py:152-168`)
  of `runtime.py:9184+` (`admit_consent` at +22) — same call, not the runtime object.
* M6's answer path is `harness/world.py` → `OnlineSemanticMap.resolve` (product) →
  `answers.where_is` (new leaf); no broker tool exposes it (DESIGN said so; unchanged).

## 3. Refute-first on the met rows
* **M6 is trivially answerable as a retrieval test.** The map's 8 active labels (`awning, bench,
  door, fire hydrant, lamppost, planter, trash can, tree`) are exactly the 8 nouns in the 20
  present queries; `resolve` (`online_map.py:836-880`) is token overlap on the label, so top-1
  is guaranteed once the gate admits — the row measures the gate and the renderer. The 10
  absent nouns share no token with any label and were never in `queries`, so all 10 refusals
  are `no_detector_support` (asked=False), the trivial case; synonyms (`seat, bin, streetlight,
  lamp`) refuse for the same trivial reason. **Partial tokens are answered**: `"fire"`,
  `"where is the fire"` → *"I last saw a fire hydrant…"*; `"can"`, `"trash"` → trash can
  (`rerun_cpu.json: m6_extra_probes`). 84/100 frames are synthesized (`world.py:158-223`).
  Downgrade to WITH-NOTES; the numbers stand.
* **M4's corpus number is vacuous for the DI.** The three corpus revocations are all
  ask-category (`amlodipine`/health, `divorce`/third_party_secret, `therapist`/health,
  `histories.py:217,303,388`), so the resurrected rows are `pending` and never render:
  `in_developer_instruction=False` on every leak in the executor's file and mine. By the letter
  of M4 the flag-OFF arm also scores 0. The non-vacuous evidence is a keep-category fact
  (`sister_name`, granted): scheduler with `respect_revocations=False` → forget → idle pass →
  **Hana back in the developer instruction**; `True` → stays out (`rerun_cpu.json:
  m4_keep_fact_DI`; same shape as `tests/test_h5_continual_memory.py:231-261`). The 0 therefore
  comes from `RevocationAwareProposer` (`scheduler.py:194-223`, applied at 361-364) — a new
  H5 leaf inside OWNS, so a legitimate mechanism result, but any caller of `distil_session`
  that is not the scheduler still resurrects (§4.3).
* **M1's attribution is half measured.** Arms B/C differ only in the companion, so arm C's
  `word_budget`/`clarification` failures are the companion's — measured. But the "live
  proposer" in every arm is the regex proposer (§4.2), Tier 3 is empty on the probe path
  (`h5_tier3_keys: []` everywhere; `cross_session_memory` is one session so Tier 2 never
  overflows), and my arm B lost a `fact_recall` turn to the live *summarizer* — so "not the
  memory" is asserted for the summarizer and unmeasurable for the proposer.
* **M2/M3 gold is generous by construction**: `GroundFact.matches` is token containment
  (`histories.py:70-72`) authored by the harness author with the regex vocabulary in view;
  deterministic precision 1.00 is partly gold-to-output. The chat arm's 0.96 is real but
  reached through a harness bypass (§4.2).
* **M7 is byte-identical by construction** (no clock, `sort_keys`); the main case persists an
  empty Tier 3; the 4-session case holds 2 rows. Fine as pre-registered.

## 4. Defect claims — all four VERIFIED at file:line
1. **`distil_session(session_id=…)` reads zero turns.** `owner_model/distiller.py:486-492`
   filters `t.get("session_id")`; `memory/conversation.py:630-669` builds rows with keys
   `id, speaker, content, created_at, origin` only (655-661). Repro: 3 turns via `add()`,
   `distil_session(mem, session_id="s1")` → `turns_read 0, written 0`; `session_id=None` →
   3 / 2. Also `messages.session_id` is NULL for `add()` rows (`conversation.py:447`), and no
   caller in `src/` or `tests/` passes a session id (`test_p2a_owner_model.py:481-571`), so the
   filter has never been exercised. Scheduler works around it (`scheduler.py:379-395`).
2. **`LanguageModelFactProposer` never parses.** `distiller.py:360` → `providers.py:168-214`
   pins `response_format` to `_decision_response_schema` (`providers.py:205-208, 415+`; `reply`
   is `{"type":"string","maxLength":500}`) under a system prompt that frames the call as
   Parcel's conversational turn (`providers.py:173-177`). Repro (1 live call): reply = *"I have
   noted that your sister's name is Hana, she lives two streets away…"*, `_parse_candidates` →
   `[]`, and `LanguageModelFactProposer(turns) == DeterministicFactProposer(turns)`. Executor
   0/12 parseable; mine 0/1. Refinement: not structurally impossible (a JSON array is a legal
   string inside `reply`), but total in 13/13 measured calls. **The M2 "live chat proposer" is
   `harness/live_proposer.py:92-208` `ChatFactProposer`** — a direct POST to
   `/v1/chat/completions` with its own `RESPONSE_SCHEMA` (70-88), bypassing `LlamaCppProvider`
   entirely; it reuses the product's `_parse_candidates` and `FactProposer` protocol. A harness
   bypass, declared as one (`live_proposer.py:29-32`). No product path produces 0.96.
3. **`add_owner_fact` upserts past tombstones.** `conversation.py:843-847` selects
   `key = ? AND deleted_at IS NULL`, else INSERTs (870-889). Repro: add → forget (1) → add →
   new row id 2, 1 live / 2 incl. deleted; `distil_session` twice around a `forget` → the fact
   is back (`rerun_cpu.json: defect3_via_distil_session`). Fix exists only in the scheduler.
4. **`resolve` refuses everything at `robust_z` when < half the map matches.**
   `perception/abstention.py:566` default `robust_z`; `ranking_margin` (1181-1200) returns 0.0
   for MAD ≤ 0; `online_map.py:1016-1026` builds the background as one score plus 0.0 per
   non-matching entry. Repro: `ranking_margin([5.2]+[0.0]*7) == 0.0` vs `MIN_RANKING_MARGIN 1.0`
   (`label_strength_margin` → 43.3); 4-of-8 matching → 1.124, so the executor's scoping is
   exact. Shipped: `_ACTIVE_POLICY = AbstentionPolicy()` (`abstention.py:727`), the runtime
   passes no policy (`runtime.py:13036-13040`), and `configs/robot.prototype.yaml:216-226`
   deliberately does not select `configs/navigation/prototype.yaml` (which sets
   `label_strength` at :306). Not H5's to fix; one config line away, as claimed.

## 5. Criterion integrity — clean
`git diff 0ec1d7c -- …/DESIGN.md` is empty (file tracked, byte-identical). No bar moved; the
executor reports M1 and M3 as MISS.

## 6. Scope / OWNS — clean for H5
H5-attributable tree changes: new `memory/scheduler.py`, `memory/episodes.py`,
`online_map/answers.py`; `memory/tiered.py` +169/−2 (the −2 widen two import lines; methods
additive; `null_distiller` untouched); `tests/test_h5_continual_memory.py`; the research folder
(`fixtures/` is empty). All inside OWNS; `runtime.py`, realtime lanes, `owner_model/guard.py`,
`configs/robot.yaml` untouched. Other working-tree diffs (`pyproject.toml` → H7 by its own
comment; `realtime/cost.py`, `spend_ledger.py` → H1; untracked H1–H4/H6/H7 leaves and tests)
are other folders' OWNS in the shared tree. Ruff clean on every H5 file. DEC ratchets: 32
passed, 1 failed — `test_decig2_import_ratchet.py::test_the_measurement_stays_cheap` (20.6 s vs
10 s budget at load avg 105); wall-clock, not structural, same as the executor saw.

## 7. Cost — $0.00
No hosted call: harness grep for API hosts is empty; the probe judge is
`personal-convo-local-judge-v1`, `heuristic_local`, report-only. Local GPU only, on a server
this card did not start. Contention: M8 measured with the GPU at 2 % util before the arm; my
median 5.07 s sits inside the executor's contended and quiet bands, so contention does not
explain any gap.

## 8. What the milestone design may rely on
Measured: a scheduler that calls `distil_session` at session close and on idle, tiers 1–3 that
persist and reload byte-identically, an append-only episode log, and a past-tense world-answer
renderer all work over synthetic stores and a mostly synthesized map — but only from the
harness, with the flag OFF, with `distil_session`'s session filter broken and the shipped
`robust_z` gate refusing every single-match query. Measured too: the local model reached through
a direct chat completion proposes facts at ≈0.96 precision in ≈5 s per pass, while the product
seam degrades to the regex proposer 100 % of the time and the live summarizer silently falls
back to concatenation at least once per pack, so no number here says the *shipped* live path
distils anything. Still assumed: real-owner quality (three authored histories, gold by the same
hand), keep-category revocation on real transcripts beyond one keep fact, synonym/partial-token
behaviour of world answers, and that any runtime will ever construct these leaves.

## Codex cross-review for Fable · 2026-08-24

**KEEP the overall REFUTED status.** The append-only log, tiers and consent
ideas are useful primitives, but four product-path failures remain material:
session filtering reads zero turns, the product proposer silently degrades,
tombstones can resurrect outside the scheduler, and a single-label world
query is refused. The scheduler, episode log and world-answer path are not
wired into the runtime.

M1 should promise **governed accumulation and retrieval**, not recursive
model-weight learning. Ship explicit remember/forget plus deterministic,
provenance-bearing candidates first. No model writes facts, code or weights
directly. Automatic consolidation is promoted only after a product-path test
proves consent, revocation, restart persistence and zero tombstone
resurrection.
