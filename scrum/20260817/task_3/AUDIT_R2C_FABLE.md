# AUDIT — R2-C SI/DI prompt plane + corpus harness · Fable

**Date:** 2026-08-18 · **Card:** task_3 R2-C · **Executor:** Claude Opus (agent)
**Verdict:** **ACCEPT_CLOSE.** Two card errors found by the executor were real,
and its handling of both was correct. One tree-state event adjudicated benign.

## Independently verified

1. **Fresh commit gate, my own shell:** PASS — 5,778 passed, every hard gate
   green, release-parity and frozen sentinels intact.
2. **All 8 seeds re-run by the auditor:** 8/8 RED with the expected first
   failures; tree restored; clean 96 green.
3. **Corpus spot-check:** 25 threads / 174 fixed owner turns; both owner
   examples verbatim; families navigation 9 / conversation 9 / punt 4 /
   perception 3; two SI profiles; six DI locations. Structure matches the card.
4. **Executor finding 1 confirmed in code:** `lane.py:299` stores
   `instructions` as a plain `str` and `:411` re-*sends* it — the card's
   "the lane re-derives at rollover" premise was wrong (my card-authoring
   error, inherited from the design's phrasing). The `InstructionSource.refresh(lane)`
   mechanism honors zero-lane-edits and is proven by the rollover test.
5. **Executor finding 2 confirmed:** the ci_gate frozen scan globs
   `manifest.json` exactly; `corpus.manifest.json` is invisible to it. The
   card's named trap was inert AS WRITTEN — the executor proved the blindness
   (seeded `frozen: true`, scan stayed green), then closed the actual gap with
   its own wider scan test rather than editing out-of-OWNS files. Correct call.
6. **Tree-state event:** HEAD moved `8473a51` → `877d9f4` mid-card —
   **committed by the owner** (author Jae), landing the entire 08-16 wave.
   Benign; the executor neither committed nor staged anything. Remaining
   uncommitted: R1.5 + R2-C + `requirements-lock.txt` (`websockets==17.0.1`,
   correct and expected).

## Adjudication of the 8 deviations

All accepted. Notable: seed fixtures carrying zero usage (inventing token
counts would be fabricated billing data — right instinct); no location
provider wired (DI says `unknown` rather than deriving a fake room from map
coordinates — honest over plausible, and the R3 handoff is explicit); the
scraper speaking raw frames rather than the lane (text modality uses events
R1's codec deliberately omits; extending the audited codec was out of OWNS).

## Standing risks the owner should keep in view

- **The scrape has never run** (429 `credit_balance_exhausted`, re-checked
  once). The corpus today is 3 hand-authored seed fixtures proving the replay
  pipeline; the 25 threads are authored scenarios awaiting credit. The
  scraper's live path is unexercised — expect one fix on first contact.
- **`expect` blocks are authored expectations, not scorers.** No judge reads
  them yet; wiring them to the AutoRater is the natural next card, and the
  AutoRater itself is uncalibrated against human preference.
- **`refresh(lane)` has no runtime caller** — nothing drives `lane.tick()`
  yet. Mechanism proven; wiring is R2/R3.

## Close

R2-C closes. The day's remaining waves per the task_2 board: W1/A1 (R1.5
gate + audit), W2 (browser audio), W3 (first live contact — still gated on
the owner adding credit).
