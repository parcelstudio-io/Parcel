# AUDIT — R4-lite "the mission you can see, the session that survives" · Fable

**Date:** 2026-08-18 · **Card:** `scrum/20260818/task_1` · **Executor:** Claude Opus (agent)
**Verdict:** **ACCEPT_CLOSE** — with the card's single unmet claim (the model
*audibly* narrating a pedestrian block, live) carried forward explicitly. The
executor named that gap itself before I could; that is the standard.

## What this card fixes, in the owner's terms

"The robot is not even flinching in the simulator" was three stacked failures:
a lane that went deaf after a stall-reconnect (the model never heard the turn),
missions that ended with no visible trace (the terminal wrote a detail field
and told nobody), and obstacle chatter evicting what little evidence existed.
All three are fixed, live-proven on the executor's own :8799 stack, and pinned.

## Independently verified

1. **Fresh full gate, my own run:** `RESULT: PASS — every hard gate green.`
   `default-suite 6151 passed, 9 skipped, 42 deselected` · `ruff 7 violation(s),
   baseline 7, new 0` · hard-safety (frozen nav baseline, mutation panel,
   follow-bench) all green. Matches the executor's two runs verbatim.
2. **All 19 seeds re-run by the auditor: 19/19 RED**, harness (FIX-A style,
   mutate→run→restore in `finally` with a byte-identity assert) restored the
   tree — `git diff --stat` identical before and after. The card's four
   required seeds are covered: reconnect-deafness (S1–S6), terminal dropped
   (S7), mission_log evicted by chatter (S8/S9/S17/S18/S19), narration spam
   (S10/S11/S16).
3. **Defect A root cause confirmed in code.** `ensure_session`
   (`lane.py:508`) takes the "do I need a session?" decision under the lane's
   lock; `_connect` (`lane.py:542`) closes any transport it replaces;
   `send_text` frames are `required` (a drop raises instead of returning a
   phantom 202, `lane.py:1167`); `_responses_pending` keeps the watchdog armed
   across a tool turn's second response (`lane.py:1037`); `_tick_locked`
   recovers an armed lane whose socket died (`lane.py:770`).
   `submit_realtime_text` no longer reads `lane.active` cross-thread to decide
   (`runtime.py`, comment at the call site names the race).
4. **The race test is a real race test.** `test_a_turn_that_arrives_during_the
   _backoff_is_not_lost` runs a genuine panel thread against the injected
   backoff hook and pins the defect at its source: exactly two sockets ever
   built, no orphans, stall counters not masked, and the mid-reconnect turn
   answered. Sabotaging `ensure_session`'s lock (S1) turns exactly that test
   RED — verified.
5. **Defect B root cause confirmed in code.** `_stop_navigation_channel`
   (`runtime.py:1392`) — the choke point every non-arrival terminal passes
   through — now logs to the 20-slot `mission_log` ring, emits a panel event,
   and hands the fact to the model behind the floor gate. The blocked-row
   sub-cap (`MISSION_LOG_BLOCKED_MAX`), class-keyed edge trigger, and 10 s
   rate limit with folded counts are all as described, all seeded.
6. **The floor gate is honest.** Four independent refusals (no session,
   recovering, model speaking, response outstanding), non-blocking acquire,
   skips counted in `narrations_skipped`. Narration failure can never take
   down a terminal (`_narrate_mission` catches and emits).
7. **B22 untouched, provably.** `core/yield_policy.py` (mtime 2026-08-09) and
   `configs/personality.yaml` (2026-08-08) predate the whole realtime arc.
   `test_narration_never_shortens_the_wait` asserts `person_stop_m`, the yield
   profile, and the yield tracker are byte-identical across a recorded,
   narrated block. `test_a_proximity_stop_is_never_withheld` pins that the
   rate limiter cannot suppress a STOP (S13 RED).
8. **MUST-NOT-TOUCH sweep clean.** The executor ran ~01:11–02:21 local; every
   protected file's mtime predates that window, and this card's symbols
   (`ensure_session`, `narrate_event`, `mission_log`, `_responses_pending`,
   `_emit_proximity_change`, …) appear zero times in `protocol.py`,
   `config.py`, `memory.py`, `yield_policy.py`, `personality.yaml`. Nothing
   staged, nothing stashed, nothing committed.
9. **The ratchet regeneration is legitimate.** The
   `test_nominal_stop_wiring.py` digest change carries a dated log entry per
   the test's own procedure; only `_dispatch_active` moved (the proximity
   event emission lifted into `_emit_proximity_change`), the call site still
   advances `_proximity_state` on every transition
   (`test_proximity_transitions_still_advance_the_state`), and every stopping
   predicate digest besides it is unchanged. The frozen nav baseline and
   mutation panel — the behavioral check the ratchet backs — are green on my
   own gate run.
10. **The live proof is real and its claims check out.** I cross-checked the
    status doc against `proof_final.txt`, the stack-side log, and the
    executor's transcript: the 202, the walk commands and constant
    `person_stop` yields, `stalls: 2 / reconnects: 2` with the lane still
    `active: true` and `dropped_sends: 0`, the structured
    `"mission accepted: sidewalk"`, and the previously-silent terminal
    (`Mission to sidewalk ended (failed): semantic_target_unreachable`,
    observed in a sample taken after the monitor window — and, in the debug
    sessions, the owner's exact silent class
    `ended (idle): navigation_disabled`, now speaking). `spend_usd: 0.011146`
    for session 3.

## The audit's own observations (none blocking)

1. **A teardown micro-race remains in `close()` vs an in-flight reconnect.**
   `close()` is deliberately lock-free; between `_reconnect`'s `_opened` check
   and `_connect()` completing, a concurrent `close()` could leave one fresh
   socket open until process exit. S6 pins the main path (close during
   backoff → abandoned); the residual window is teardown-only and costs at
   most one socket. Worth a line in a future card, not a re-open.
2. **`submit_realtime_text` still reads `lane.active` once cross-thread** —
   in the handshake-token pre-check. Worst case is a spurious *refusal*
   during a reconnect on a stack that never bound a token; every real launch
   binds one. Fail-closed, acceptable.
3. **Stray repo-root files from earlier cards:** `seed_table.md` (task_6's
   seed table) and `live_stream.json` predate this card and are untracked.
   Cleanup candidates for the next land; not this card's mess.
4. Session 1's two-minute narration-spam incident (~74 responses) is exactly
   why the card authorized debug sessions; the live-falsifies-offline lesson
   (class key, not raw note) is now a seeded regression (S17). Good use of
   paid runs.

## Carried forward / owner-gated

1. **"The model SAYS the block out loud" — unproven live.** Wired, gated,
   bounded, delivered (`narrations: 2, narrations_skipped: 0`), never heard:
   the two responses that stalled in session 3 look like the narration
   responses. One cheap follow-up: force a narration with no mission running
   and wait for the assistant turn.
2. **`stalls: 2` in two minutes of `gpt-realtime-2.1-mini` is high** and now
   *survivable* but unexplained. Provider-side behavior; future card.
3. **Yield patience is still B22** — the dog waiting out a pedestrian stream
   near the sidewalk is policy working as designed; changing how long it
   waits is the owner's call, not a defect.
4. Browser audio gateway (§A, task_6 carry-forward) remains the only gap
   between typing and speaking.
5. The 10 s blocked-row rate limit undercounts episodes by design (folded
   counts keep it honest); the 10 s entry timeout turns a bad provider day
   into a loud refusal rather than a wait. Both are documented behavior
   choices the owner may want to revisit.

## Post-close addendum (2026-08-19, auditor): two live defects the owner hit within minutes

The owner restarted onto this card's fixes and immediately surfaced two
NEW defects — both panel-side, both found by the very visibility this card
added, both fixed by the auditor in `ui/index.html` only:

1. **B14's mechanism, finally caught in the act.** `window.addEventListener
   ("blur", clearMotionInputs)` force-POSTed a zero-velocity `/api/motion`
   even when no key or button was ever held. Server-side that is not a no-op:
   `manual_motion(0,0,0)` runs `_interrupt_brain("manual", "manual stop
   acquired the base")`, which cancels the running task. The owner typed
   "Go to the sidewalk", the mission was admitted (00:21:08.43Z), they
   clicked over to the MuJoCo window to watch — and the blur killed the
   mission 0.586 s in (`ended (idle): navigation_disabled`; task state
   `cancelled`, `last_detail: "manual stop acquired the base"` — the
   mission_log ring and the executive snapshot made this diagnosable in
   minutes). The executor's live proof could not have seen it: headless
   probes, no browser, no blur. **Fix:** `clearMotionInputs` now sends the
   zero-velocity release only when an input was actually held; explicit
   stops (Space, Stop, e-stop) post `/api/action` and are untouched. The
   deeper owner-gated question stands: should a zero manual command
   interrupt the brain at all (B14 2×2)?
2. **Every sent message rendered twice.** `renderLogs` concatenated the
   server chat with the panel's optimistic `state.localChat`; the legacy
   `/api/voice/text` branch clears the optimistic row when its authoritative
   response arrives, but the realtime branch returns after its 202 and never
   clears — so the owner's line renders twice, forever, once per message.
   **Fix:** `renderLogs` prunes local rows the authoritative snapshot
   already carries (the realtime path writes the chat row before answering
   202); local-only rows such as error notices survive.

No Python changed; no test pins the panel JS; a fresh full gate over the
edits is green. Both defects predate nothing — they are old code paths the
new realtime lane was the first to exercise with a live audience.

## Restart required

None of this is hot-reloadable. The owner's stack must be relaunched
(`./scripts/launch_stack.sh --realtime`) to pick up the fixes; the executor
correctly left the owner's processes alone (their stack was already down).
