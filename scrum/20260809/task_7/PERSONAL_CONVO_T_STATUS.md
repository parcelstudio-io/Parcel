# PERSONAL_CONVO_V1 — Tier T (text transcript) STATUS

Executor: Sol 5.6 Ultra + Opus. Cards delivered: **PC-1, PC-2, PC-3** (text tier
only). Owner-approved design: `scrum/20260808/task_2/README.md`.

## Headline (honest)

Under the offline deterministic reference companion, **7 of 8 probe families pass
deterministically; 1 is recency-window-blocked; 0 fail.**

- PASS: `in_session_context`, `fact_tool_composition`, `persona_consistency`,
  `affect_handling`, `interactivity_clarification`, `adaptability_no_sycophancy`,
  `asr_robustness`.
- RECENCY-WINDOW-BLOCKED: `cross_session_memory`. The frozen event graph pushes
  the "got the offer" evidence past `recent(8)`, so today's `ConversationMemory`
  cannot surface it in a fresh later session. The provider does not fabricate to
  compensate — it says it cannot recall — so **every truthfulness check passes and
  the single failing check is `fact_recall`**. Verified in-run: `evidence_within_window`
  is `False`; the 8-row window holds only tail distractors (no "offer"). This is a
  true finding recorded in `does_not_prove`, not tuned away.
- Turn tally: **12/13 turns pass** (the one failing turn is the cross-session recall).

## Pack layout (all NEW; no existing frozen pack touched)

```
evals/companion/personal_convo_v1/
  manifest.json              sha-pins 15 files (result.schema, 4 scorer/fixture modules,
                             memory YAML, human SCRIPT.md, 8 probes); refuse-to-run on edits
  run_personal_convo_v1.py   runner: provenance CLI (--base-url/--model-artifact/--model-sha256),
                             --provider fixture (default, offline CI) | live (documented seam, raises)
  session_schema.py          PC-1 session-script schema (design "SESSION SCRIPTS" verbatim)
  scorers.py                 PC-2 Tier-D deterministic bank + family classifier
  fixture_provider.py        honest deterministic reference companion (CI fake)
  build_memory_fixture.py    PC-2 event-graph YAML -> fresh sqlite ConversationMemory
  result.schema.json         case_verdicts determinism contract + mandatory does_not_prove
  probes/*.json              PC-3 eight sha-pinned session scripts, one per family
  memory_graphs/cross_session_memory.yaml   LoCoMo-style authored evidence + distractors
  human_recording/SCRIPT.md  ~30-min read-aloud utterance list (owner-gated corpus; committed)
  results/README.md + personal-convo-t-20260809-fixture-run01.json   immutable day-one result
tests/test_personal_convo_v1.py   17 fast offline tests (collected by default suite)
scrum/20260809/task_7/PERSONAL_CONVO_T_STATUS.md   this file
```

## Tier-D scorer bank (deterministic, CI-gating) — PC-2

Per turn: tool-invocation correctness from the trace; DialogueAct truthfulness via
the existing `contracts.v1` claims contract (no verified claim without
`evidence_ref`; `max_veracity` ceiling; no arrival/found-it/tool-result surface via
`forbidden_claim_patterns`); fact recall / confabulation as casefolded
`facts_must_appear` groups + `facts_must_not_appear` substrings (conversation_quality_v1
vocabulary reused verbatim); `asks_clarification` bit; emote tag budget; reply word
budget; DialogueAct contract-parse validity. Family classifier:
`pass` | `recency_window_blocked` (only `fact_recall` failed and all truthfulness held)
| `fail` (any other failing category — fabrication/tool misuse/etc.).

Memory fixtures are AUTHORED and FROZEN in the YAML, replayed into a fresh
`ConversationMemory` per cross-session probe (empty live history), so the probe
measures the memory subsystem, not context carryover.

## Determinism proof

- Two runs under the fixture provider: identical `case_verdicts`, identical
  `pack_digest` (`7e904d5335e049ac…`), and the full result object identical minus the
  timestamp. Enforced by `test_fixture_run_is_deterministic`.
- Pack frozen digest stable across two runs (same `pack_digest`).
- No clock/RNG/network on the scoring path.

## Existing-harness discipline (GATE)

- Deterministic twice with identical `case_verdicts`: yes.
- Manifest-tamper reddens before any provider call: yes — `scenario_count` mismatch
  and corrupted locked hash both raise `PersonalConvoError`
  (`test_manifest_tamper_reddens`, `test_manifest_hash_tamper_reddens`), mirroring
  conversation_quality_v1's integrity test.
- Tier-D scorers unit-tested: yes (truthfulness unevidenced/ceiling/premature-state,
  fact recall/confabulation, clarification/emote/word/parse, family classifier).
- New pytest collected by default suite, fast + offline: yes (17 tests, 0.13 s).
- No judge model in this card (PC-4 calibration + local judge is later, report-only).

## VERIFY results

- Full default suite: **3060 passed, 7 skipped, 33 deselected, 0 failed** (95.99 s).
  The 7 skips / deselects are pre-existing and outside this pack; no red anywhere.
- `ruff check` on the new pack + test: clean.
- No existing frozen pack modified (conversation_quality_v1, acoustic_loop_v1
  untouched); only NEW files created + `tests/test_personal_convo_v1.py`.
- New pack's own frozen digest stable across two runs.

## Files touched

All NEW. `evals/companion/personal_convo_v1/**` (manifest, runner, 4 modules,
result schema, 8 probes, 1 memory YAML, human SCRIPT.md, results README + day-one
result, pack README, `__init__.py`); `tests/test_personal_convo_v1.py`; this status
file. Runner/fixtures were auto-formatted by ruff; manifest hashes regenerated to
match.

## Human-recording script

`evals/companion/personal_convo_v1/human_recording/SCRIPT.md` — ordered read-aloud
utterance list keyed to every probe turn id, with the mumble/re-ask take for ASR
and the prior/later split for cross-session. Committed and ready for the owner's
~30-min session; **no audio required by this tier**.

## Deferred (not in this card)

- **Tier A** (audio e2e on the acoustic_loop_v1 rig; frozen WAV → whisper → Gemma →
  Piper → reference-STT) — owner-gated / later card. The `--provider live` seam is
  present but raises: wiring the production voice lane's DialogueAct extraction needs
  runtime/voice changes this card must not touch (a gesture/voice session is
  committing concurrently).
- **Human-recorded corpus** — script committed; recording is owner-gated.
- **PC-4** calibration pack + local judge (report-only); **PC-5..PC-7** audio tier,
  hallucination-under-noise, and the single-delta swap comparator.
- The ~12.5% human-vs-TTS gap is not covered by this text tier (recorded in
  `does_not_prove`).
