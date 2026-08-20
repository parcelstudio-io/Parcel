# R2-C — SI/DI prompt architecture + conversation corpus harness

**Date:** 2026-08-17 · **Card:** `scrum/20260817/task_3` · **Executor:** Claude Opus
**Auditor:** Fable · **Depends on:** R1 (`20260816/task_7`, ACCEPT_CLOSE), R1.5 (`20260817/task_1`, unaudited)
**Baseline:** started at `8473a51`; **HEAD moved to `877d9f4` ("Implemented voice
agent") during this card** — another actor landed the R1 realtime slice while this
was in flight. Nothing was committed, staged or stashed here; all measurements and
the final gate below are against `877d9f4` + this card's working tree.
**Venv:** `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python`

## The headline

**The live scrape did not run. The account is still out of credit.** One
minimal chat call was made to re-check, exactly once, and it returned
`HTTP 429 / code=credit_balance_exhausted / type=insufficient_quota`. No
realtime socket was opened by this card and no tokens were billed. Everything
else on the card landed: the SI/DI prompt plane, the 25 authored scenarios, the
schema, the env-gated budget-guarded scraper, three hand-authored seed fixtures,
and a replay path that drives them through the **real** `RealtimeLane` offline.

## What landed, in one paragraph

A versioned, digest-pinned prompt plane (`realtime/prompting.py`): SI is the
companion preamble + the active personality from `prompts/personalities` + the
lane's own `GUARDRAILS`, pinned per `si_version` per personality; DI is a pure,
deterministic render of a `DeveloperFlags` snapshot gathered from injected
providers — location callable, injectable clock, owner profile, ledger-tail
digest. `runtime.py`'s `RealtimeLane` construction block (the single
existing-code site the card permits) now sources `instructions=` from it. A new
eval pack `evals/companion/realtime_convo_v1/` holds 25 authored scenarios (174
fixed owner turns, both of the owner's verbatim examples), a fail-closed corpus
schema whose `fixture_to_script` converts any fixture mechanically into
`FakeRealtimeServer` steps, a live scraper that refuses to run without both an
explicit flag and a credential and hard-aborts at $5, three hand-authored seed
fixtures, and an **unfrozen** `corpus.manifest.json`. 96 new offline tests.
**No live API call, no credential in any artifact, nothing committed.**

## Files

| File | Lines | What |
| --- | --- | --- |
| `src/parcel_robot/realtime/prompting.py` | 581 | SI/DI render, digest pins, `DeveloperContext`, `InstructionSource` |
| `evals/companion/realtime_convo_v1/schema.py` | 598 | fail-closed loaders, `fixture_to_script`, `verify_prompt_plane` |
| `evals/companion/realtime_convo_v1/scrape_realtime_convo.py` | 535 | the live scraper; env gate, budget guard, tool declarations |
| `evals/companion/realtime_convo_v1/build_manifest.py` | 218 | manifest generator, `--check`, `--print-si-digests` |
| `evals/companion/realtime_convo_v1/scenarios.json` | 758 | 25 authored threads, 174 fixed owner turns |
| `evals/companion/realtime_convo_v1/README.md` | 121 | pack docs + `does_not_prove` |
| `evals/companion/realtime_convo_v1/corpus.manifest.json` | 69 | digests, versions, usage totals, blocked-scrape record. **No frozen flag** |
| `evals/companion/realtime_convo_v1/fixtures/rt-conv-001.json` | 185 | seed: navigation + two tool proposals |
| `evals/companion/realtime_convo_v1/fixtures/rt-conv-014.json` | 161 | seed: conversation + memory callback |
| `evals/companion/realtime_convo_v1/fixtures/rt-conv-022.json` | 155 | seed: punt |
| `evals/companion/realtime_convo_v1/__init__.py` | 6 | package surface |
| `tests/test_realtime_prompting.py` | 591 | 33 tests |
| `tests/test_realtime_corpus_replay.py` | 600 | 63 tests |
| `src/parcel_robot/runtime.py` | **+39 / −5** | the import line and the lane construction block, nothing else |
| `scrum/20260817/task_3/R2C_STATUS.md` | this file | |

`git diff --numstat src/parcel_robot/runtime.py` reads `39 5`. All 39/5 belong
to this card, in exactly two hunks: the `parcel_robot.realtime.lane` import
(which loses `build_instructions`, whose only call site this card replaced, and
gains the `realtime.prompting` import), and the `RealtimeLane(...)` construction
block. No other line of any pre-existing file was touched.

## The quota re-check, in full

```
$ set -a; . ~/.config/parcel/realtime.env; set +a
$ .parcel/bin/python <scratchpad>/quota_probe.py     # POST /v1/chat/completions, max_tokens=1
HTTP 429
code: credit_balance_exhausted
type: insufficient_quota
message: You have no credits remaining. Add credits to continue using the API at ...
VERDICT: BLOCKED
```

One call. No retry loop. The scrape was skipped and the state is recorded
honestly in `corpus.manifest.json` (`scrape.status = "blocked"`,
`threads_captured = 0`, `measured_spend_usd = 0.0`) and in the pack README.
Unblocking is an owner billing action.

## Frozen contract surface

**SI.** `SI_VERSION = "si-companion-v1"`. `render_system_instruction(*,
profile_id, library=None, version=SI_VERSION) -> SystemInstruction(profile_id,
version, text, .digest, .provenance())`. Text is
`COMPANION_PREAMBLE` + `\n\n` + `lane.build_instructions(personality,
reply_style, guardrails=lane.GUARDRAILS)` + `\n\n` + `COMPANION_CONTRACT`.
`SI_DIGESTS[SI_VERSION]` pins one sha256 per personality; `si_pin(profile_id,
version=...)` refuses an unregistered version or personality with
`PromptPlaneError`.

**DI.** `DI_VERSION = "di-companion-v1"`. `DeveloperFlags(location, local_time,
part_of_day, owner_name, owner_notes, history_digest)` — frozen, JSON-shaped,
`from_mapping` refuses unknown keys. `render_developer_instruction(flags,
version=DI_VERSION) -> DeveloperInstruction`, a **pure function**: no clock, no
environment, no filesystem. `DeveloperContext(*, clock, location=None,
owner_name=..., owner_notes=None, history=None, time_format="%Y-%m-%d %H:%M")`
is the only impure part and every source is injected. `time_of_day` reads a
stated table (`5→morning, 12→afternoon, 17→evening, 21→night`, wrapping to
`night` before 05:00). `history_digest_from_turns(rows, limit=6, width=120)`
turns a ledger tail into `they said:` / `you said:` one-liners.

**Session.** `render_session_instructions(*, profile_id, flags, library=None,
si_version=..., di_version=...) -> SessionInstructions` with `.text` (SI then
DI), `.digest`, `.provenance()`. `InstructionSource(*, profile_id, context,
library=None, ...)` exposes `current()` and `refresh(lane) -> bool`.

**Runtime.** `runtime.realtime_instructions: InstructionSource | None`, `None`
unless the lane was constructed. `runtime.realtime_lane.instructions` is the
session-open render.

**Corpus.** `SCHEMA_VERSION = 1`, `SUITE_ID = "parcel-realtime-convo-v1"`,
`SCRAPE_MODEL = "gpt-realtime-2.1-mini"`, `DECLARED_TOOLS = ("navigate_to",
"get_status", "play_gesture")`, `FAMILIES = {navigation, perception,
conversation, punt}`, turns per thread in `[6, 12]`. `load_scenarios()`,
`load_fixtures()`, `fixture_to_script(fixture, *, session_id="sess_replay",
synthetic_audio_ms=0)`, `verify_prompt_plane(fixture)`. Everything refuses:
unknown keys, unknown family/source/probe, filename ≠ thread_id, out-of-order
turn indices, non-JSON tool arguments, out-of-band turn counts.

**Scraper.** `SCRAPE_ENV = "PARCEL_REALTIME_SCRAPE"`, `BUDGET_CEILING_USD =
5.0`, `require_scrape_enabled(environ=None)`, `guard_budget(*, estimate_usd,
ceiling_usd=5.0, label=...)` (refuses `>=` the ceiling), `spend_usd(usage)`,
`estimate_corpus_usd(scenarios)`, `self_test()`.

## The design points, and where each is proven

### 1. SI+DI render deterministically, and both are versioned

The SI is assembled from three files — this module's preamble,
`prompts/personalities/*.yaml`, and `lane.GUARDRAILS`. Any of the three moving
silently changes what a hosted model was told, so the *rendered* digest is
pinned per version and asserted for every personality on disk
(`test_the_si_digest_is_pinned_per_personality`,
`test_every_personality_in_the_repo_is_pinned`). Bumping the version without
registering digests is itself a refusal
(`test_bumping_the_version_without_registering_digests_refuses`). Seeds S1 and
S6 are the two ways this can go wrong and both are RED.

DI determinism is pinned by a digest computed from a **fixed injected instant**
(`test_the_di_render_is_pinned_for_a_fixed_injected_instant`), which is what
makes S2 — replacing the injected clock with `datetime.now()` — redden inside
the same test run rather than at midnight some day in the future.
`test_the_di_renderer_touches_no_clock_environment_or_disk` states the same
property the other way round: it replaces `prompting.datetime` with a class
whose `now()` raises, and the DI still renders to its pin.

### 2. DI applies at session boundaries only — and the card's premise was slightly wrong

The card says "the lane already re-derives instructions [at rollover/reconnect];
you get DI refresh for free there". **It re-*sends*, it does not re-*derive*.**
`RealtimeLane.__init__` stores `instructions: str` and `_connect()` sends
`SessionUpdate(instructions=self.instructions, ...)`. A plain string captured at
construction is therefore frozen for the lifetime of the lane, and DI refresh is
not free.

With zero `lane.py` edits available, the mechanism that *does* work is
`InstructionSource.refresh(lane)`, which assigns the lane's public
`instructions` attribute from a fresh render. `_connect()` re-reads that
attribute on open, on rollover and on every reconnect, so a driver that
refreshes before each `tick()` guarantees that whatever boundary the tick takes
carries current DI — and costs one pure render per tick.

Both halves are proven end-to-end against the real lane and the scripted server:

* `test_a_rollover_carries_the_newer_developer_note` — open with
  `Location: living room`, move the flag to `front yard`, advance past
  `session_max_s`, refresh, `tick()` returns `"rollover"`, and the **second**
  `session.update` on the wire carries `Location: front yard`.
* `test_a_mid_session_di_change_is_not_an_instruction_rewrite` — the same flag
  change mid-session sends **zero** additional `session.update` frames, because
  rewriting instructions mid-conversation busts the provider's prompt cache and
  the cached-input discount is the entire cost model.

Seed S7 (DI dropped from the session text) is RED.

### 3. Fixtures round-trip: JSON → Steps → lane → ledger

`fixture_to_script` is mechanical and deterministic: one handshake `Step` plus
one `Step` per owner turn, each triggered by the `input_audio_buffer.append` the
lane emits from `send_audio`, emitting VAD markers → owner transcript → any
function-call proposals → reply transcript → `response.done` with that turn's
usage. `test_a_fixture_replays_through_the_real_lane_into_ledger_rows` drives
all three seeds through a real `RealtimeLane` with a real `ConversationMemory`
and asserts the ledger rows are exactly the fixture's turns, in order, with the
right session id and origin; zero protocol errors, zero server errors, zero
reconnects; one usage row per turn.

### 4. The tool proposal, and the refusal that answers it today

`rt-conv-001` carries two proposals — `navigate_to` (with a spoken
acknowledgement alongside it) and `get_status` (a proposal with **no** speech,
which is why that turn leaves no robot ledger row). Tools are R3;
`test_a_navigate_to_proposal_is_answered_by_the_r1_refusal_stub` asserts
`lane.refused_tool_calls == ["navigate_to", "get_status"]` and that two
`function_call_output` items went back carrying `TOOL_REFUSAL_OUTPUT`
(`{"error": "tools are not enabled in R1"}`) against the fixture's own call ids.
The assertion is documentation: the fixture captures the *proposal*, and the
refusal is today's correct behaviour, stated so that R3 changing it is a
deliberate edit to a named test.

### 5. The manifest is not frozen — and the card's trap needed a second guard

`corpus.manifest.json` carries digests, versions, usage totals and the blocked
scrape's state, plus a `frozen_note` saying in prose why freezing a
three-seed placeholder would be wrong. It has **no** `frozen` key.

**Finding worth the auditor's attention.** `test_ci_gate.py`'s scan globs
`evals/**/manifest.json` — an *exact filename*. This pack's manifest is
`corpus.manifest.json` (the card's own name), so **the ci_gate scan cannot see
it**: a `"frozen": true` sneaked in here would have been invisible to the gate,
and the card's fifth seeded failure would have been silently inert. Verified
directly:

```
# with "frozen": true seeded into corpus.manifest.json
$ pytest tests/test_ci_gate.py -q -k frozen      →  5 passed          (blind)
$ pytest tests/test_realtime_corpus_replay.py -q -k frozen
FAILED ... ::test_this_pack_is_not_frozen_and_says_why
FAILED ... ::test_no_frozen_manifest_escapes_the_wider_scan
2 failed
```

So the scan is reproduced in this card's own test file over the **wider**
pattern `evals/**/*manifest*.json`, with the frozen set pinned to the same eight
manifests ci_gate knows about, and
`test_the_ci_gate_scan_provably_cannot_see_this_manifest` asserts the blind spot
rather than leaving it as folklore. `scripts/ci_gate.py` and
`tests/test_ci_gate.py` were **not** edited (they are outside OWNS), and the
real ci_gate frozen scan is green on this tree.

### 6. The scrape is a script, gated twice, and never a test

`require_scrape_enabled` needs `PARCEL_REALTIME_SCRAPE=1` **and** a non-empty
`OPENAI_API_KEY`; neither implies the other. `guard_budget` refuses at or above
`$5.00` — `>=`, not `>`, because a run that lands exactly on the limit has no
headroom for the turn already in flight — and is called once before the first
socket opens and again after **every** response, not once per thread. The
ceiling is a module constant with no flag that can raise it.

The only things `tests/` imports from the scraper are pure functions and the
`self_test()` entry point; the run path is unreachable from pytest, and
`test_no_test_in_this_suite_can_trigger_a_live_scrape` asserts the module is
inert on import and refuses with the env unset. Seeds S4 and S8 are RED.

## Gate table

```
$ .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-18T02:28:01Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.45s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.32s
[  PASS] HARD  release-parity-integrity   10 passed in 0.71s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.25s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              5778 passed, 9 skipped, 41 deselected, 5 warnings in 230.36s (0:03:50)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 242.7s
```

## Seeded-failure table

`<scratchpad>/seed_r2c.py` (session scratchpad, never the repo) mutates one
shipped file per seed, runs the owning test file(s), and restores the original
bytes in a `finally` block. `git status --short` before and after the whole run
is byte-identical, and the clean suite is re-run at the end.

| # | Seeded defect | File | Result | First failing test |
| --- | --- | --- | --- | --- |
| S1 | SI text edited, `SI_VERSION` not bumped | `realtime/prompting.py` | **RED** 1 failed | `test_the_si_digest_is_pinned_per_personality[calm_guardian]` |
| S2 | DI render made time-dependent (`self._clock()` → `datetime.now()`) | `realtime/prompting.py` | **RED** 1 failed, 7 passed | `test_the_di_render_is_pinned_for_a_fixed_injected_instant` |
| S3 | one fixture byte edited under the manifest digest | `fixtures/rt-conv-014.json` | **RED** 1 failed, 52 passed | `test_the_manifest_digests_match_the_files_on_disk` |
| S4 | budget guard removed (early `return` before the ceiling check) | `scrape_realtime_convo.py` | **RED** 1 failed, 59 passed | `test_the_budget_guard_refuses_at_and_above_the_ceiling` |
| S5 | `"frozen": true` sneaked into the new manifest | `corpus.manifest.json` | **RED** 1 failed, 55 passed | `test_this_pack_is_not_frozen_and_says_why` |
| S6 | guardrails copied instead of imported from `lane.GUARDRAILS` | `realtime/prompting.py` | **RED** 1 failed | `test_the_si_digest_is_pinned_per_personality[calm_guardian]` |
| S7 | DI dropped from the session text entirely | `realtime/prompting.py` | **RED** 1 failed, 26 passed | `test_the_session_text_is_si_then_di_and_carries_full_provenance` |
| S8 | scrape env gate opened (`PARCEL_REALTIME_SCRAPE` no longer required) | `scrape_realtime_convo.py` | **RED** 1 failed, 58 passed | `test_the_scraper_refuses_without_both_the_flag_and_a_credential` |

8 seeds, 8 RED. `=== tree restored: YES ===`, then
`clean: PASS :: 96 passed, 2 warnings in 0.47s`.

The card asked for five; eight landed. S5 was also confirmed to redden the
**second** frozen guard (`test_no_frozen_manifest_escapes_the_wider_scan`) —
the harness runs with `-x`, so the table shows only the first failure per seed.

## Test runs

```
$ .parcel/bin/python -m pytest tests/test_realtime_prompting.py \
    tests/test_realtime_corpus_replay.py -q
96 passed, 2 warnings in 0.44s
```

```
$ .parcel/bin/python -m pytest tests/test_realtime_prompting.py \
    tests/test_realtime_corpus_replay.py tests/test_realtime_lane.py \
    tests/test_realtime_protocol.py tests/test_realtime_ingress.py \
    tests/test_realtime_ws_transport.py tests/test_ci_gate.py -q
342 passed, 2 warnings in 3.07s
```

```
$ .parcel/bin/python -m pytest tests/test_runtime.py tests/test_agent.py \
    tests/test_tiered_memory.py tests/test_closed_intent_product_path.py \
    tests/test_fixa_transcript_persistence.py tests/test_fixa_mic_arming.py \
    tests/test_duplex_integration.py tests/test_k6_voice_lanes.py -q
186 passed, 3 warnings in 11.62s
```

```
$ .parcel/bin/python -m ruff check src/parcel_robot/realtime/prompting.py \
    src/parcel_robot/runtime.py evals/companion/realtime_convo_v1/ \
    tests/test_realtime_prompting.py tests/test_realtime_corpus_replay.py
All checks passed!
```

Every new file is also `ruff format`-clean. `runtime.py` was not reformatted —
only the two hunks this card owns were touched.

```
$ .parcel/bin/python -m evals.companion.realtime_convo_v1.scrape_realtime_convo --self-test
SELF-TEST OK: budget ceiling $5.00, both refusals hold

$ .parcel/bin/python -m evals.companion.realtime_convo_v1.scrape_realtime_convo --dry-run
threads: 25  model: gpt-realtime-2.1-mini
preflight estimate: $0.60  hard ceiling: $5.00
prices are an operator ESTIMATE, not a fetched price list (in $4.0/Mtok, out $16.0/Mtok)
dry run: nothing was sent

$ .parcel/bin/python -m evals.companion.realtime_convo_v1.build_manifest --check
manifest matches the tree
```

## Corpus shape

25 threads · 174 fixed owner turns · 6–8 turns each.

| Family | Threads |
| --- | --- |
| `navigation` | 9 |
| `perception` | 3 |
| `conversation` | 9 |
| `punt` | 4 |

Navigation-flavoured (navigation + perception) = 12 ≥ 8. Conversational = 9 ≥ 8.
Six locations (`living room`, `front yard`, `sidewalk near home`, `kitchen`,
`back porch`, `hallway by the front door`), mornings and evenings and one night,
two personalities (`gentle_companion` ×14, `playful_companion` ×11). Six threads
carry a history digest referring to an earlier thread, which is what makes the
memory probes real. Both owner examples appear character-for-character and are
pinned by `test_both_owner_examples_appear_verbatim`.

## Deviations, and why

| # | Deviation | Reason |
| --- | --- | --- |
| 1 | The runtime edit is **two** hunks, not one: the `realtime.lane` import line changed too | `build_instructions` had exactly one call site — the block this card replaced — so leaving the import would be an `F401` and redden ruff. The import hunk is mechanical: drop one name, add the new module's names. |
| 2 | `InstructionSource.refresh(lane)` exists at all | The card's premise that the lane "re-derives" instructions at a boundary is not true of the code (§2). With no `lane.py` edit available, assigning the lane's public `instructions` attribute is the only mechanism, and it is proven by a real rollover test rather than asserted. |
| 3 | No location provider is wired at the runtime site | Nothing in `RobotRuntime` names a *room*. `_location_context` is map coordinates and `_scene_context` is visible semantic regions; neither is a place a companion can talk about. DI reads `Location: unknown` rather than inventing one. The seam exists and the corpus exercises six real locations. |
| 4 | A **second** frozen scan lives in this card's tests | The ci_gate scan's glob cannot see `corpus.manifest.json` (§5). `tests/test_ci_gate.py` is outside OWNS, so the guard was added where this card is allowed to add it, and the blind spot is asserted. |
| 5 | Seed fixtures carry **zero** usage everywhere | They are hand-authored, so no tokens were billed. Inventing plausible token counts would put fabricated billing data into an evidence pack. `test_hand_authored_seeds_carry_no_invented_billing_data` pins it. |
| 6 | The scraper speaks raw JSON frames instead of driving `RealtimeLane` | A text-modality scrape uses `response.output_text.*`, which R1's audited codec deliberately does not implement. Widening a frozen codec for a data-collection script would be the worse trade; the *fixture* is the contract, and `fixture_to_script` converts back into frames the real lane does drive. |
| 7 | Eight seeded failures instead of five | The card's five are S1–S5. S6–S8 cover guardrail drift, a dropped DI, and an opened env gate — each cheap and each a real way this could rot. |
| 8 | `scenarios.json` threads are 6–8 turns, not up to 12 | Authored to the band's floor. Longer threads cost more per scrape without probing anything the shorter ones miss; the schema still enforces `[6, 12]` so a future author can go longer. |

## does_not_prove

* **Nothing here has spoken to the model.** The three fixtures are hand-authored
  seeds whose robot side was written by this executor. They prove the replay
  pipeline works; they prove nothing whatsoever about `gpt-realtime-2.1-mini`'s
  behaviour, its willingness to propose `navigate_to`, its adherence to the
  guardrails, or its cost.
* **The scraper's live path has never executed.** `scrape_thread`,
  `_drain`, `_reply_text` and `_usage_from_response` are unexercised code. The
  provider's actual text-modality event names (`response.output_text.delta` vs
  `response.text.delta` — the scraper accepts both) and its `response.done`
  usage shape are **verified in documentation only**. First real run should
  expect to fix something here.
* **The assumed prices are an estimate, not a price list.** `$4/Mtok` in,
  `$16/Mtok` out, `$0.40/Mtok` cached. The $0.60 preflight figure is only as
  good as those numbers. Reported spend comes from the provider's usage block,
  but the estimate — the thing the ceiling checks *before* spending — does not.
* **`expect` blocks are authored expectations, not scorers.** No judge, no
  rubric, no pass/fail scoring exists in this pack. They are the notes a future
  scorer would be built from, and no test reads them.
* **The DI history digest is not wired to anything a person would recognise as
  memory.** It is the last six hosted turns, one line each. It does not
  summarise, does not deduplicate, and does not survive a database that has
  never seen a hosted turn (which is every database today).
* **The runtime's DI is thin in production.** With no location provider and no
  `owner_name` key in `configs/robot.yaml`, a real session's developer note
  today reads `Location: unknown` / `Owner: the owner` plus whatever the ledger
  tail holds. The prompt plane is complete; the *sources* feeding it are not.
* **`refresh(lane)` has no caller in the shipped runtime.** The runtime
  constructs the source and takes the session-open render. Nothing calls
  `refresh` on a tick loop, because nothing in the shipped runtime drives
  `lane.tick()` yet. The mechanism is proven by test; the wiring is R2/R3.
* **The corpus has never been scored, judged, or reviewed by a human for
  quality.** The scenarios are one executor's authoring against the card's
  requirements. Whether they are *good* probes is an owner/eval-designer
  judgement that has not been made.
* **No claim about prompt-cache behaviour.** §2's cost argument for not
  rewriting instructions mid-session is the design's reasoning, not a
  measurement. Nothing here has observed a cached-token discount.
* **The manifest is not byte-pinned by any gate.** It is not in
  `DIGEST_SENTINELS` and it is not frozen, deliberately. Its digests are
  asserted by this card's own tests only.

## Handoffs

* **Owner — billing.** Add credit, then:
  `set -a; . ~/.config/parcel/realtime.env; set +a; PARCEL_REALTIME_SCRAPE=1
  .parcel/bin/python -m evals.companion.realtime_convo_v1.scrape_realtime_convo`,
  then rebuild the manifest. Replace `ASSUMED_*_USD_PER_MTOK` with billed rates
  and re-run `--dry-run` first. The 25 captured fixtures land in the same
  directory and `tests/test_realtime_corpus_replay.py` needs no edit — that
  property is the point of the seed fixtures.
* **R2/R3 — a lane driver.** Whoever writes the loop that calls `lane.tick()`
  should call `runtime.realtime_instructions.refresh(lane)` immediately before
  it. That is the whole DI-at-boundaries mechanism and it is one line.
* **R3 — a place source.** Wire `DeveloperContext(location=...)` to something
  that names a room. Until then the model is told `unknown` and asks, which is
  correct but thin.
* **R3 — tools.** The corpus already captures proposals and asserts the R1
  refusal. When the broker lands, `test_a_navigate_to_proposal_is_answered_by_
  the_r1_refusal_stub` is the named test to change deliberately.
* **Owner — freezing.** If this pack is ever frozen, rename
  `corpus.manifest.json` to `manifest.json` and add it to `DIGEST_SENTINELS` at
  the same time; both scans then cover it for free and the wider scan in this
  card's tests becomes belt-and-braces.
* **`configs/robot.yaml`.** The construction block reads
  `agent.owner_name` with a fallback. The key does not exist and was **not**
  added — `robot.yaml` is hash-locked. Adding it is an owner decision with a
  re-freeze attached.

## OWNS compliance

`git status --short` after the full run:

```
 M requirements-lock.txt
 M src/parcel_robot/runtime.py
?? evals/companion/realtime_convo_v1/
?? scrum/20260817/
?? src/parcel_robot/realtime/prompting.py
?? src/parcel_robot/realtime/ws_transport.py
?? tests/test_realtime_corpus_replay.py
?? tests/test_realtime_live.py
?? tests/test_realtime_prompting.py
?? tests/test_realtime_ws_transport.py
```

From this card: ` M src/parcel_robot/runtime.py`,
`?? src/parcel_robot/realtime/prompting.py`,
`?? evals/companion/realtime_convo_v1/`,
`?? tests/test_realtime_prompting.py`,
`?? tests/test_realtime_corpus_replay.py`, and `scrum/20260817/task_3/`.

`requirements-lock.txt`, `src/parcel_robot/realtime/ws_transport.py`,
`tests/test_realtime_live.py` and `tests/test_realtime_ws_transport.py` are the
R1.5 session's work and were **not** read-modified, staged, reverted or
committed here. `scrum/20260817/task_1` and `task_2` were read only.

`git cat-file -e HEAD:<path>` confirms none of this card's new files are tracked
in `877d9f4`; that commit is another actor's R1 landing (`realtime/lane.py`,
`protocol.py`, `transport.py`, `runtime.py +180`, plus backlog/docs/ci_gate).
This card's `runtime.py` diff sits on top of it and is still exactly two hunks
(`@@ -203,7 +203,14 @@` and `@@ -1116,13 +1123,40 @@`).
`configs/robot.yaml`, `pyproject.toml`, `scripts/ci_gate.py`,
`tests/test_ci_gate.py`, `tools/` and every R1 realtime module gained **zero
bytes**. Nothing was committed, staged or stashed.
