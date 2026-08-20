# R9 — SESSION B addendum: a second executor ran this card at the same time

**Date:** 2026-08-20 · **Executor:** Claude Opus (agent), session B · **Auditor:** Fable
**Card:** `scrum/20260819/task_2/README.md`
**Companion to:** `R9_STATUS.md` (session A) — **that document is the card's
status doc and this one does not replace or contradict it.**

## Why this file exists instead of an overwritten `R9_STATUS.md`

I was launched to execute card R9 on the premise that the previous executor
"died after finishing its code but before writing anything down". That premise
was wrong. **A second R9 executor was alive and working the same card, in the
same working tree and the same scratchpad, for the whole of my session.** We
never saw each other; we discovered each other only through the damage.

I wrote my own `R9_STATUS.md`; session A overwrote it while I was doing live
proof. Rather than overwrite session A's — which is complete, careful, and
contains live evidence I cannot reproduce or verify — I preserved it and put
this session's distinct findings here.

**Everything in `R9_STATUS.md` about what shipped is accurate as far as I can
independently verify it**, and I verified quite a lot of it: I read every
changed file, re-derived the design rationale, ran an independent 18-seed
harness, and ran an independent live proof on a separate stack. This addendum
records only what session A does not have.

## Finding 1 (the important one): the concurrency corrupted seed evidence

Session A's Deviation 4 says "something else in this workspace writes these
files concurrently" and its Deviation 7 says "a third agent's stack was running
on :8844". **That "something else" and that "third agent" were me**, and I was
not a third agent — I was a *second executor of the same card*. Naming it
matters, because the fix is an orchestration fix, not a harness fix.

What it cost, measured on both sides:

| | Session A (`R9_STATUS.md`) | Session B (this file) |
| --- | --- | --- |
| Symptom | restores wrote back another writer's bytes; **a stale S3 mutation reached the working tree** (`ingress.py` left exact-only, `runtime.py` left with a demoted emit) | three **false GREEN** seeds (S6, S8, S9) that were RED when re-run alone with byte-identical inputs |
| Detected by | inspection before the final gate | a GREEN seed whose pytest run reported 36 collected cases where the mutated file yields 9 |
| Fix applied | snapshot every touched file once at startup; restore from that snapshot; repair-before-each-seed; final tree check | read the mutation BACK OFF DISK before running pytest and refuse otherwise (`WRITE-FAILED`); drop `__pycache__`; `PYTHONDONTWRITEBYTECODE=1` |

Two independent harnesses, two different corruption modes, same root cause. The
generalisable lessons:

1. **A seed harness that reads its "original" at mutation time cannot detect a
   concurrent writer** and will assert byte-identical restoration of a file it
   has just corrupted. Session A's snapshot-once fix is the right shape and
   should be the house pattern from now on.
2. **A green gate proves nothing about a tree two agents are writing.** Session
   A's stale mutation was in the tree at one point; had a gate run landed there,
   it would have reported on code neither executor wrote.
3. **Every seed table in this sprint that was produced while two executors
   shared a tree is suspect**, not just R9's.

**Recommendation, owner-gated:** one card, one tree. Either give concurrent
executors separate git worktrees, or have the launcher refuse to start a second
executor for a card that already has a scratch dir / status doc in flight. The
"prior executor died" premise should be verified (is its process alive? is its
scratch dir being written?) before a replacement is dispatched.

**Current tree state, verified after both sessions finished** — all five files
that either harness touched match session A's golden manifest:

```
636ea47c3889dc61c54ecfefeda72cb491bb39ea48980b6d38e5a15fadc79826  src/parcel_robot/realtime/ingress.py
64cc6a778fc358d64d80e4f0291c3ea440ba4890aff3eb70150f3cd0ed2e0c6f  src/parcel_robot/runtime.py
2404b48daa33b33877086afab6b9d939527b5798a0ff1a5302afef2c4fa4e7f9  src/parcel_robot/ui/index.html
c875378fd486a8f096f267bd25f42a7dc8b9f4773a4de1f5590e06543be052b5  src/parcel_robot/realtime/lane.py
0d5e324da2b67720cbe319941ef08c51b398d01c7a8dd8c89b4d002437c3db16  src/parcel_robot/voice/closed_intents.py
```

## Finding 2: an independent live proof, and it disagrees with session A's headline

Session A's verdict says the variant "Dye stop." **never latched live**, because
its transcriber returned "Dice top" / "die top" — the leading /s/ of "stop"
dropped after an /aɪ/ word, the same failure R7 measured as "Top".

I ran my own live proof on my own stack and got a **different outcome from the
same input class**, which is worth having on the record because it says the
variable is the transcriber, not the latch:

* Stack `:8844`, socket `/tmp/parcel_r9b.sock`, `gpt-realtime-2.1-mini`,
  `mode: audio`, R7's headless gateway client, piper speech at 22 050 Hz
  resampled to 24 000 Hz, real-time 20 ms/960-byte frames.
* Spoken **"Die stop."** → transcribed `Die Stop!` → **LATCHED** while
  owner-follow was running (follow went `enabled: true, state: holding` →
  `enabled: false, state: idle`).
* Spoken **"Dye stop."** → transcribed **`Die Stop!`** → **LATCHED**. The
  transcriber returned the *canonical* spelling for the variant utterance, so
  this run neither confirms nor refutes variant tolerance — it just did not
  reproduce session A's dropped-/s/ failure.
* Spoken **"Let's stop by the store on the way home, okay?"** → transcribed
  verbatim → **did not latch**; the model called `navigate_to` and started a
  new mission. The strongest form of the negative: the dog did not stop, it
  took a *new job*.
* Typed **"Die stop."** → `safety error Emergency stop latched by voice: 'Die stop'`.
* Typed **"Dye stop."** → `safety error Emergency stop latched by voice: 'Dye stop'`.
  This is where the variant is proven end-to-end through the live lane.
* Typed negative → did not latch; `navigate_to` again.
* Release, four times: motion while latched → `409 {"detail":"motion is disabled
  by emergency stop"}`; `POST /api/action {clear_emergency_stop}` →
  `200 {"message":"Emergency stop cleared"}`; motion after →
  `200 {"message":"accepted manual motion"}`; follow re-enabled.

**Combined reading of both sessions:** the spoken latch fired on 2/2 of my
attempts and on 4/4 of session A's *canonical-phrase* attempts, and failed on
session A's *variant* attempts. So: **"Die Stop" as spoken by the owner is
robust; the near-homophone tolerance is insurance that has never actually been
needed live, and the second word ("stop") remains the fragile one.** Session A's
open risk about widening the second word is the right next question and should
stay owner-gated — it is the part of the grammar the ruling did not authorise.

Counters and cost, my session:

```
spend_usd : 0.076341   (session A: 0.127042 — combined ~$0.203, both under target)
gateway   : connections 3, mic_opens 3, frames_in 464, bytes_in 445440,
            frames_out 88, utterances 11, frames_dropped_backpressure 0, control_errors 0
lane      : text_turns 3, audio_frames_sent 464, usage_rows 12,
            server_errors 0, dropped_sends 0, stalls 0, reconnects 0
```

**Isolation.** The owner's stack was live on `:8765` (`launch_sim.sh --llm`,
pid 1703400) throughout and was never contacted, POSTed to, read or stopped. R5
scratch-memory recipe: `configs/robot.yaml` copied to my scratchpad with
`memory.path` — and only that — repointed at `parcel_memory_r9b.sqlite3`; the
owner's `parcel_memory.sqlite3` was never opened (mtime unchanged at
`00:23:30`). `configs/robot.yaml` byte-identical before and after
(`f7b57dcd…90d6f1`). Credential sourced with
`set -a; . ~/.config/parcel/realtime.env; set +a`, never printed. My stack was
torn down with a pattern (`parcel_r9b.sock`) that could not match session A's
(`parcel_r9.sock`); at teardown only the owner's `:8765` was listening.

## Finding 3: my seed table (18/18 RED), independent of session A's 16

Different harness, different anchors, overlapping intent. Run to completion
after hardening; all five touched files byte-identical before and after
(`<scratchpad>/r9/{pre,post}_seed_digests.txt`). The card's six named seeds are
S1, S2, S8/S9/S10, S14, S11 and S15 here.

| # | Seeded defect | File | Result |
| --- | --- | --- | --- |
| S1 | Space reverts to the NOMINAL stop | `index.html` | RED |
| S2 | the typing-target guard removed (a space in the chat box latches) | `index.html` | RED |
| S3 | contenteditable leaves the typing guard | `index.html` | RED |
| S4 | the latched banner is never raised | `index.html` | RED |
| S5 | the banner's release button is decorative (no `data-action`) | `index.html` | RED |
| S6 | the focus caveat is dropped from the panel | `index.html` | RED |
| S7 | Space stops clearing held motion inputs | `index.html` | RED |
| S8 | variant tolerance removed — exact spelling only | `ingress.py` | RED |
| S9 | whole-utterance matching restored (R7's live defect) | `ingress.py` | RED |
| S10 | separator tolerance removed ("die-stop", "Diestop" miss) | `ingress.py` | RED |
| S11 | **the negative case latches** — the "die" prefix goes optional | `ingress.py` | RED |
| S12 | "day" admitted as a variant | `ingress.py` | RED |
| S13 | the phrase grows a second definition under `src/` (U33 shape) | `runtime.py` | RED |
| S14 | **the latch moves AFTER the cloud round-trip** | `lane.py` | RED |
| S15 | **the release path is broken — the latch is forever** | `runtime.py` | RED |
| S16 | the release forgets `agent.safety` (panel says clear, agent does not) | `runtime.py` | RED |
| S17 | the latch stops naming the words that caused it | `runtime.py` | RED |
| S18 | the emergency branch no longer latches the runtime | `runtime.py` | RED |

One seed (S7) was genuinely GREEN on the first run and the **test** was
strengthened, not the seed removed:
`test_space_latches_the_emergency_stop_and_not_the_nominal_stop` now asserts
`clearMotionInputs()` is present in the Space branch AND ordered before the
`postJson`. Without it, a latch could go up while the owner's other hand is on
an arrow key, leaving a queued velocity waiting for the release.

`lane.py` was mutated by exactly one seed (S14) and restored byte-identically;
it was never edited. Same caveat and same justification as session A's
Deviation 2 — the "latch after the cloud round-trip" ordering exists only in
`RealtimeLane.send_text`, so there is nowhere else to seed it.

## Finding 4: what neither session proves

Session A's `does_not_prove` is thorough and I endorse it. Two additions:

1. **No seed table from this card was produced under single-writer conditions
   until each harness was hardened mid-run.** The final tables on both sides are
   trustworthy; the first runs were not, and the difference was invisible
   without re-running seeds individually. Treat "18/18 RED" and "16/16 RED" as
   evidence *from the hardened runs only*.
2. **The panel pins are source pins, not browser behaviour.** Nothing in either
   session pressed a real Space bar in a real browser. They catch the defect
   class that actually occurs — a silent edit — and would not catch a browser
   that delivers `event.code` differently, a CSP change that stops the handler
   running, or a focus bug. A headless-browser panel test remains absent from
   this repo, and after this card the panel's Space bar is a safety control.

## The focus caveat, restated because it is a safety property

* Space latches the e-stop **only while the panel page has keyboard focus**.
  Click the simulator window, another tab, or the desktop, and it does nothing.
  This is B14's cousin — the browser only gets the keys it has focus for.
* **The MuJoCo window has its own separate keyboard surface** (`Controls: W/S
  A/D Q/E Space, 1=sit 2=bow`, printed at sim startup). Unchanged by this card,
  and NOT the same Space.
* Neither is a hardware e-stop. Panel button, panel Space and the spoken phrase
  all reach the same software latch through the same runtime — which is exactly
  why the always-local hotword / physical button stays owner-gated.

## Artifacts (session B)

* `tests/test_owner_estop.py` — written this session (6 tests): local-first on
  the wire, the transcript origin needing no session, latch attribution, release
  end-to-end, one latch behind two doors, and the negative at runtime level.
* `tests/test_prod_default_path.py` — four panel pins written this session
  (Space is the emergency latch and clears held inputs; the typing guard stands
  in front of it; the banner is unmissable and carries its own release; the
  focus caveat is stated in the panel).
* `<scratchpad>/r9/seed_r9.py` (hardened), `<scratchpad>/r9/seeds_final.txt`,
  `<scratchpad>/r9/{pre,post}_seed_digests.txt`.
* `<scratchpad>/r9b/live/` — `robot_r9b.yaml`, `realtime_r9b.yaml`,
  `run_stack.sh`, `drive_r9.py`, `proof_client.py`, `utt_*.raw`,
  `proof_session{1,2,3}.json`, `spend_final.json`, `stack.log`.
* `<scratchpad>/r9b/gate_final.txt` — the gate output below.

Nothing was committed, staged or stashed.

## The gate — verbatim, run after the final edit of this session

```
CI GATE — tier=commit  (2026-08-20T05:01:41Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  release-parity             91 packaged asset(s) byte-identical to canonical source
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  release-parity-integrity   10 passed in 0.75s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.54s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.32s
[  PASS] HARD  default-suite              6396 passed, 9 skipped, 42 deselected, 6 warnings in 244.67s (0:04:04)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 257.7s
```

This run is over the COMBINED tree — both executors' edits — and it is the last
gate either session ran. 6 396 tests pass (baseline at the start of my session:
6 336). The five files either harness touched match the golden manifest above,
so this gate ran on code both executors wrote and neither corrupted.
