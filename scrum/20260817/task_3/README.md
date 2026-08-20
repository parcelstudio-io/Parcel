# Task 3 — R2-C: SI/DI prompt architecture + conversation corpus harness

**Date:** 2026-08-17 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Owner directives (verbatim intent):** build the fully-fledged conversational
agent's prompt plane; scrape 25 multiturn threads from OpenAI mixing navigation
tasks ("I am hungry, let's go to mcdonald's", "Can you see the closest
lamppost?") and conversational tasks; SI = periodic system instruction ("You
are a conversational companion quadruped friend…"); DI = developer instructions
built AT RUNTIME from flags (location, time, owner personality, history);
**tests always use the prescraped conversations, never live calls.**

## Environment facts (verified 2026-08-17, do not re-derive)

- Key at `~/.config/parcel/realtime.env` (mode 600). Load:
  `set -a; . ~/.config/parcel/realtime.env; set +a`. Never echo/log/commit it.
- **Quota is BLOCKED: 429 `credit_balance_exhausted`** on a $0.001 chat call.
  Re-check ONCE cheaply before deciding whether to run the live scrape; if
  still blocked, land the harness + seed fixtures and record the blocked state.
  Do not retry-loop against a billing wall.
- `websockets==17.0.1` installed; `realtime/ws_transport.py` exists (R1.5,
  24 tests green, unaudited); `FakeRealtimeServer` + `RealtimeLane` are R1,
  audited — READ ONLY.

## Design constraints

1. **SI (system instruction):** rendered by a new `realtime/prompting.py` from
   `prompts/personalities/*.yaml` + companion guardrails (short sentences; no
   tool mechanics; acknowledge before acting; admit limits; never claim
   arrival — mission events do that). Selected by config (`si_profile`),
   versioned (`si_version` string in every fixture and ledger row) — "changes
   periodically" means a config change, never a silent edit.
2. **DI (developer instruction):** a dataclass of runtime flags — location
   (provider callable), local time (injectable clock), owner
   personality/profile, history digest (ledger tail) — rendered
   deterministically. **DI enters at session OPEN and at every
   rollover/reconnect** (the lane already re-derives instructions there);
   mid-session DI *changes* are NOT instruction rewrites (that busts the
   prompt cache the cost model depends on) — they ride as appended system
   conversation items at the next session boundary. Zero `lane.py` edits: the
   only runtime edit allowed is the `RealtimeLane` construction block sourcing
   `instructions=` from the new module.
3. **Corpus:** `evals/companion/realtime_convo_v1/` — 25 authored SCENARIOS
   (deterministic owner-side scripts: ≥8 navigation-flavored incl. the two
   verbatim examples, ambiguous/unreachable nav, perception probes; ≥8
   conversational incl. memory callbacks and correction turns; punt-inducing
   cases; varied DI flags per thread — different locations/times/personas).
   The scraper runs each scenario live (text modality,
   `gpt-realtime-2.1-mini`, tools DECLARED so the model emits
   `navigate_to`/`get_status`/`play_gesture` function_call proposals; the
   scraper answers tool calls with scripted synthetic world results), captures
   the full event stream per thread into JSON fixtures (turns, tool calls, DI
   snapshot, si_version, model, usage per response).
4. **Replay:** fixtures convert mechanically into `FakeRealtimeServer` scripts.
   `tests/test_realtime_corpus_replay.py` drives fixture threads through the
   real lane offline. Commit 3 HAND-AUTHORED seed fixtures now (one nav, one
   chat+memory, one punt) so replay tests are green BEFORE any live scrape;
   the scraped 25 slot in without test-code changes.
5. **Budget guard:** the scraper prints an estimate first and hard-aborts
   above $5; per-thread usage recorded. `PARCEL_REALTIME_SCRAPE=1` + key
   required; never runs in any test tier.
6. **Frozen-manifest trap:** `tests/test_ci_gate.py` scans `evals/` for
   manifests carrying `"frozen": true` and pins that set. Do NOT mark the new
   pack frozen; write `corpus.manifest.json` with digests but no frozen flag,
   and note that freezing is a later owner decision. Verify the scan stays
   green.

## OWNS

`src/parcel_robot/realtime/prompting.py` · the runtime construction block only
· `evals/companion/realtime_convo_v1/` (scenarios, scraper, schema, seed
fixtures, README, unfrozen manifest) · `tests/test_realtime_prompting.py` ·
`tests/test_realtime_corpus_replay.py` · `scrum/20260817/task_3/R2C_STATUS.md`

## MUST NOT TOUCH

`configs/robot.yaml`, `pyproject.toml`, `scripts/ci_gate.py`, existing
`evals/**` packs, `tools/`, `realtime/{lane,transport,ws_transport,protocol,
ingress,fake_server,config}.py`, anything uncommitted from other sessions.
Never commit/stage/stash. Scratch only under the session scratchpad.

## Definition of done

Full `ci_gate --tier commit` green; ≥5 seeded failures RED then restored
(SI edit without version bump caught; DI nondeterminism caught; replay fixture
digest mismatch caught; scraper without budget guard caught; frozen-scan
regression caught); status doc honest about whether the live scrape ran or is
credit-blocked.
