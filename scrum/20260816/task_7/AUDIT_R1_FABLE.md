# AUDIT — R1 Realtime lane core · Fable

**Date:** 2026-08-17 · **Card:** task_7 R1 · **Executor:** Claude Opus (agent)
**Verdict:** **ACCEPT_CLOSE** with two carry-forwards. No blocking findings.

## What was independently verified (not taken from the executor's report)

1. **Fresh commit gate, my own shell:** PASS — 5,658 passed (5,471 baseline
   + 187 new), ruff `new 0`, release-parity 91 green, frozen sentinels green.
2. **OWNS compliance:** `git status` net of the other sessions' known work
   shows exactly the card's OWNS set. Real runtime diff is **+171/−1** (the
   +7/−1 remainder is this session's earlier V1-A edit, correctly untouched).
   Nothing committed; HEAD still `8473a51`; `configs/robot.yaml` byte-identical
   to its re-frozen pin.
3. **All 8 seeds re-run by the auditor:** 8/8 RED with the expected first
   failures, tree restored, clean suite 187 green afterwards. S1 alone reddens
   83 tests — the punctuation constraint is load-bearing, not decorative.
4. **Live database untouched:** `parcel_memory.sqlite3` still has the
   4-column schema; the migration ran only against test databases.
5. **Binding constraint 1 is structural, not conventional:**
   `submit_voice_text` now *refuses* `origin="realtime"` with a reasoned error,
   and the ingress body reaches only the emergency latch, `_apply_closed_intent`,
   and `set_behavior` — no planner, no conversation model, no
   `DuplexVoiceSession`. S2 pins it.
6. **Phrase sets are imported, never copied** — including a drift-proof test
   (`test_a_new_router_follow_phrase_reaches_this_lane_without_an_edit`) that
   would catch the router growing a phrase this lane misses.

## Adjudication of the six declared deviations

| # | Deviation | Ruling |
| --- | --- | --- |
| 1 | `submit_voice_text` refuses realtime origin | **ACCEPT** — strengthens constraint 1 from convention to structure |
| 2 | `session_id=` kwarg on the ingress | **ACCEPT** — the ledger column needs it |
| 3 | follow/hold via `set_behavior`, not `_admit_local_sketch` | **ACCEPT** — authority parity proven: the local agent's own fast path executes exactly `ToolCall("set_behavior", {"mode": "follow"})` when no planner is wired (`agent.py:316`); the hosted ingress grants nothing a typed "follow me" doesn't already get |
| 4 | COME → `set_behavior("follow")` | **ACCEPT** — the executor is right that `_apply_closed_intent` has no COME branch; the alternative would acknowledge and do nothing |
| 5 | GOAL_AMEND excluded from the scan | **ACCEPT** — a re-plan is model/R4 territory, not a deterministic cap |
| 6 | `PARCEL_REALTIME_CONFIG` env override | **ACCEPT** — mirrors existing test practice; shipped default remains file-absent |

**On deviations 3/4, one finding worth recording:** the agent path wraps
`set_behavior` in `SafetySupervisor.validate` (e-stop refusal at
`safety.py:120-121`); the ingress calls `runtime.set_behavior` directly. The
safety property still holds — `_enable_owner_follow` re-checks
`arbiter.emergency_stopped` under the command lock (`runtime.py:2950-2951`) and
the ingress converts the `RuntimeError` into `executed=False` — so this is a
**defense-in-depth asymmetry, not a hole**. Both stop-shaped intents ("stay")
are safe under e-stop by construction.

## Carry-forwards (not blocking close)

1. **Pin the asymmetry:** add a seeded test proving `follow` via the ingress is
   refused while e-stopped (the guard exists; nothing pins it). Owner: R2/R3.
2. **R3's tool broker must route through `ToolCall` + `SafetySupervisor.validate`**
   rather than inheriting the ingress's direct-call style — uniformity matters
   more once the *model* proposes the action. Owner: R3 card.
3. The executor's own risk list is accurate and honest; its items (fake sink
   played-ms is an upper bound; `sink_factory` unwired; `speak_system`
   refusal-not-diversion; transcript-lead over-reporting on barge-in) belong in
   the R1.5/R2 card verbatim.

## does_not_prove (inherited and endorsed)

Nothing has spoken to the real OpenAI API; no audio has played on this host;
flag-on proves construction and correct refusal, not conversation; spoken stop
in this lane is cloud-dependent — the panel STOP and operator stop remain the
guarantees. The two live unblocks are owner actions: `pip install websockets`
(+ lock update) and `OPENAI_API_KEY`.
