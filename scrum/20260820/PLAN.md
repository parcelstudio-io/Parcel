# 2026-08-20 — day plan: the prototype within reach

> **Historical dispatch snapshot.** This file records the board before the
> work executed; its queue labels and counts are not current status. The dated
> R10–R19 status files supersede it. The latest combined commit-tier record is
> 6,933 passed, 9 skipped, and 42 deselected with every hard gate green.

Objective framing: a highly-advanced voice companion = (1) you talk, it
understands and acts with common sense; (2) it tells you what matters,
unprompted but disciplined; (3) it can never hurt anyone and never lies
about what it did; (4) every claim above is evidenced. Today's list is
ordered by what moves the prototype most.

## Machine lane (sequential — one card, one tree)

| # | Task | What it buys the prototype | State |
|---|------|---------------------------|-------|
| 1 | **R10** arrival common sense + tool parity | "go to the sidewalk" ends ON it; door = approach-turn-ask; `circle_owner`/`follow_owner(pace)` exist so the model stops fabricating or denying; junk places refused with alternatives | **executing now** |
| 2 | **R11** situational whisperer + owner cost knob | disciplined unprompted speech (B2 policy), ask-hints, `whisperer.max_updates_per_minute`, the motion gate (state can never start motion) | queued in chain |
| 3 | **E1** eval pack `evals/20260819/run_1/` | the six-scenario auditable record: paths, transcripts, verdicts; the misses-ledger that decides the Ministral seam | queued in chain |
| 4 | verify fan-out + **Fable audits** of R10/R11/E1 | independent gate + solo seed re-runs + claim verification | after chain |
| 5 | **R12** e-stop reason propagation ("rename to emergency stop" ruling) | e-stopped missions say `emergency_stop` everywhere: log, panel, spoken | card written; **dispatch-gated on #4** |

## Owner lane (only you can do these)

| # | Task | Why it matters | Effort |
|---|------|----------------|--------|
| A | **The first spoken session** — after #4 lands: restart, `mode: audio`, mic in, talk. Ask for the sidewalk; try "circle around me"; try "run with me" and then slow down; say "Die Stop" once, release, keep going | the acceptance test nothing else substitutes for; every layer now exists and none has met a human voice | ~15 min |
| B | **Decide: land the wave.** ~15 closed+audited cards (R1–R9 + fixes) sit UNCOMMITTED in the working tree at 6,396 green tests. Two session crashes and one executor collision this week are the argument: a bad crash could cost the whole arc. Say "land it" and I stage the wave into reviewable commits | protects three weeks of work | your call |
| C | **Corpus sign-off** — human-review the 25 SI-v1 threads so the eval corpus can freeze | unblocks honest base-vs-test conversation evals | ~5 min |
| D | (optional) the `s?top` ASR widening — "Dice top" would latch; "tie-dye top" becomes a false-latch risk | spoken e-stop robustness trade | 1-word ruling |

## Deliberately NOT today

Ministral judge seam (evidence-gated on E1's misses ledger); barge-in mark
integrity (matters after A shows real interruption patterns); SI v3 (wants
R10's final tool surface + A's transcript as input); N19 latency fan-in;
local hotword hardware e-stop (owner-gated; Space remains the guarantee).

## Standing rules in force

One card, one tree (AUDIT_R8 §collision); snapshot-restore harnesses; solo
audit evidence only; owner's stack and memory DB untouchable; every live
proof cost-capped and pasted.
