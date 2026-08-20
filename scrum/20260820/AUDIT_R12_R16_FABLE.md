# AUDIT — R12–R16 defect chain · Fable

**Date:** 2026-08-20 · **Cards:** `scrum/20260820/task_1..task_5` ·
**Verdict: ACCEPT_CLOSE on all five.**

## Independently verified (auditor, sole tree owner)

Fresh full gate: **PASS, 6732 passed** (6601 → 6732 across the chain, +131,
0 removed), ruff `new 0`, frozen nav baseline unmoved, sentinels/parity
byte-identical (R14's regenerated portal-world manifests included). All
five seed harnesses re-run solo against the CURRENT tree with `__pycache__`
purges between runs: **R12 17/17, R13 14/14, R14 11/11, R15 12/12,
R16 13/13 — 67/67 RED, every restore byte-identical.** Nothing staged,
nothing stashed. The read-only verifier's single BLOCKING flag (R16's
final seed sweep predating a late `runtime.py` write) is SUPERSEDED by
this re-run; its remaining findings were minor attribution drifts.

## Per-card notes

* **R12 (e-stop reason):** the reason was discarded TWICE — R9's
  `del reason` AND a teardown race where `_interrupt_brain` hardcoded
  `task_no_longer_active` before the safety preempt could speak. The
  second was invisible to every offline test (they arm missions by hand)
  and was found by the card's own live proof — the live-proof discipline
  earning its cost again. Live: "I stopped because the emergency stop was
  latched," release, clean re-admission. Scope extension into executive
  code accepted: that IS where the terminal gets written.
* **R13 (pace watcher):** banked (pausing) mismatch windows, a seven-name
  skip vocabulary with the structural invariant `ticks == logged + skips`,
  digest v2. Live: forwarded 1.1 s after measurement returned; the model
  spoke E1's missing sentence ("Want to just walk together?"). R11's six
  pace seeds re-verified RED. Honest limit stated: owner-session 1 cannot
  distinguish "engaged and blind" from "never engaged" — that blindness
  is exactly what this card removed going forward.
* **R14 (a world with a door):** portal added via the full pinned-asset
  regeneration discipline (sentinels/parity green in my gate); E1's
  door-etiquette FAIL row preserved with a dated addendum; +13 offline
  portal tests.
* **R15 (completion tense):** tense stamped at the single broker
  choke-point with an executable violation predicate (deliberately not a
  sanitizer — a scrubber would have killed its own seed); and a finding
  AGAINST the card's premise, verified: NEITHER orbit terminal narrated
  before this card — R10 built detection, not narration. Both arms wired;
  completion may now only be spoken from a terminal event.
* **R16 (idle hang-up):** conversational-silence clock (deliberately
  ignoring `send_audio` — an open mic in an empty room must not bill),
  idle-checked-before-rollover ordering, R6/R8 accounting structurally
  protected (`_idle_seconds` is None while anything is owed). Two RED gate
  runs honestly documented, one catching the executor's own design
  mistake.

## Register additions

1. **The bytecode hazard (R13's discovery, adopted as standard):** a
   same-size source mutation restored within ~1 s can leave a
   `__pycache__` entry compiled from the MUTATED source that passes every
   byte-identity check — R11's S20 poisoned R13's first live run this
   way. All harnesses and this audit now purge caches and (R13's harness)
   verify a fresh-interpreter canary. Every prior seed table that ran
   without purges carries a small theoretical taint; the auditor's
   purged re-runs are the canonical evidence from today forward.
2. Inherited flake filed: `test_runtime_streaming_text_executes_only_final
   _transcript` (6/10 in isolation, predates the chain) — candidate card.

## Owner-visible outcomes now live (after their next restart)

E-stopped missions say `emergency_stop` everywhere including out loud;
"run with me" produces the walk question; the door world exists and door
etiquette passes; "done" is only said when a thing actually finished; an
idle lane hangs up in 10 minutes instead of billing all night.
