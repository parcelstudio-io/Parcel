# AUDIT — R17–R21 chain · Fable · 2026-08-21

**Cards:** `scrum/20260820/task_6,8,7,9,10` · **Verdict: ACCEPT_CLOSE on all
five.** Landmark alongside: the owner personally landed the wave
(`2c27496`, 2026-08-20 17:58) mid-chain — the full audit's P0 is resolved;
only the later cards' post-commit work remains for the next land.

## Independently verified (auditor, sole tree owner)

Fresh full gate: **PASS, 7018 passed** (6732 → 7018 across the chain,
+286, 0 removed), every hard gate green. All five harnesses re-run solo
with `__pycache__` purges: **R17 16/16 · R19 23/23 · R18 26/26 ·
R20 15/15 · R21 20/20 — 100/100 RED**, whole-tree repair checks all
byte-identical. Nothing staged or stashed. The verifier's three minors
resolve: R20's S12 is RED on the current tree in my run (the saved GREEN
artifact reflected the disclosed regex-cache non-event, since fixed); the
example-file mtime was the owner's landing process; the owner-DB write was
their own stack's hourly rollover pair.

## Per-card highlights

* **R17:** capture + the UI-mounted runner are real products — a full
  52-query replay of record with three latches asserted AND released, the
  tee proven byte-exact against the gateway's own counters (0 drops over
  18 min), a SIGKILL-survivable index (its own live-found defect, fixed
  and re-proven), and a turn cut into a standalone WAV fixture — the first
  owner-audio fixture pipeline. Two harness honesty notes to standard
  (RED-by-hang named; a GREEN traced to mutating a docstring not the
  field).
* **R19:** the card's hypothesis was WRONG and the executor proved it
  before fixing — the receipt-tool set never drifted; four distinct
  mechanisms made the silence (a beat rule that never says "speak the
  figure"; filler buying suppression; `response.create` racing the open
  carrying response and leaking `_responses_pending` — which also explains
  the stall AND the unnarrated e-stop refusals; plus one more). The
  live_run_1 scoring's headline is corrected on the record. This is the
  register's root-cause-before-fix discipline at its best.
* **R18:** scene in `get_status` (LiDAR named by kind, never given a class
  it lacks — seeded), recall across both origins with provenance, the
  owner's remembered facts finally spoken.
* **R20:** the fork wasn't where the card guessed — "home" never reached
  goal admission (the deterministic ask-path had to be BUILT), "narnia"
  passed through two layers each deferring to the other; one policy seam
  (`admit_navigation_place`) now serves both lanes, and the whisperer-ack
  defect died by construction (nothing admitted ⇒ nothing acked).
* **R21:** the 24-slot safety ring with refusals capped at half — the
  cause can never be evicted by its consequences — six doors declaring
  origin+phrase+rule, status-under-latch in the digest, the panel Safety
  log; `ingress.py` untouched (byte-identical), q34 still owner-gated.

## New candidate cards from the chain's own live evidence

1. **Dead-lane replay:** R17's run of record lost the hosted lane at q30
   (stalls 5, `conversation_already_has_active_response`) — partially
   explained and fixed by R19's leak repair, but a dedicated
   lane-death-mid-batch recovery proof is owed.
2. The latch-contradiction line ("there's no 'stop' command in the tools,
   so we're still moving" — spoken one second AFTER latching) is field
   evidence R21's status-under-latch digest now prevents; verify in the
   next live session.

## Pipeline

Go-flag released: EV-1 → F1-SI proceed on this audited tree.
