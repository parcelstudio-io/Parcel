# A7 EAR+GOVERNOR · acceptance VERDICT (Fable) · 2026-08-24

Verification: my guard run (label `fable-a7-verify`) — A7 suite + the 15
neighbour suites + r24 + both DEC ratchets = **975 passed, 1 skipped** (the
executor's count reproduced exactly); ruff clean on all 8 touched files, zero
new fingerprints; scope = exactly 5 modified files (+364/−12) + 4 new
(ear_gate.py 696, hosted_budget.py 498, test, fixture); both new leaves and
all five diffs read line-by-line. `config.py` byte-unchanged at 1000 lines;
`core/hard_stop.py`, `safety.py`, the arbiter, `audio/stop_hotword.py` and
the `_stop_hotword_*` methods untouched (corroborated by git status and by
the card's own AST tests, which I read).

## Disposition: **ACCEPTED**

- **The gate stands before the wire, proven three ways**: unit (`b""` until
  admission), the spied product hop (refused voice ⇒ `send_audio` count 0),
  and structure (runtime.py has exactly ONE `send_audio` site and
  `offer_frame` precedes it). A refused turn's buffer is erased and counted;
  an admitted turn loses nothing (`bytes_seen == bytes_uploaded`).
- **Money can never touch safety, structurally**: six safety modules + the
  three `_stop_hotword_*` methods asserted to import/mention neither new
  module; the governor's call sites pinned to exactly
  `{submit_realtime_text, _realtime_mic_gesture}`; a critical call answered
  BEFORE any ledger read (spied: 0 reads). The governor is consulted OUTSIDE
  the frame-relay lock on press, and the new `RLock` is a verified leaf —
  nothing of the package called while held; r24's graph unchanged, and my
  run includes r24.
- **The rate card is the measured one, row-by-row**: +335.75% reproduced on
  the 34 recorded responses against H1's own per-row dollars at abs=5e-9;
  every call lands one itemized v2 row; an unpriced model deliberately falls
  back to legacy ASSUMED *said out loud* rather than a silent dearer default
  — the right refusal-visibility trade.
- **The operating point is VOICE-GATE's**: 0.352 / ≥2 s as config defaults on
  the ear; the regression pins that the owner's measured room p50 (0.47) is
  admitted at 0.352 and refused at the shipped 0.55. Channel-matched
  enrollment is a precondition (mismatch ⇒ no verification, loudly, PTT
  remains). Server VAD pinned as the session shape the billing fact scopes to.
- 15 seeded-RED proofs, sha-restored; the whole-tree sweep's 27 reds proven
  pre-existing by HEAD-revert + module-rename byte-identical re-run — the
  correct attribution method.

Register corrections, mine: the new-`noqa` count is **8, not the register's
6** — it omitted `spend_ledger.day_to_date` and `voice_identity.score_buffer`.
The deviation itself is ACCEPTED (each sits on a documented never-raises
boundary in the exact idiom of the modules this code joins; removal would
narrow a never-raises contract or add a fingerprint), with the corrected
count recorded here.

Accepted judgment calls: `refuse_when_unknown: true` (opposite of the spend
ledger's fail-open — correct, because refusal here degrades to LOCAL, the
architecture's own floor, not to a grounded robot; the knob restores the old
direction); the `engagement.py` docstring's "84" vs the re-measured 66 flagged
rather than overwritten (follow-up: fix that docstring, it is not A7's OWNS);
under a FUTURE enrolled verifier a sub-2 s utterance released before decision
is erased fail-closed and silently — deliberate and tested today (this host
ships verifier-less PTT where the edge cannot occur), follow-up: announce the
loss when identity ships; the 500 ms pre-roll ring holds unpressed audio
LOCALLY only, never uploaded.

Undone, correctly named: `voice_identity.DEFAULT_THRESHOLD` stays 0.55
(command-arming is a different question; recalibration needs the real owner
through the deployment channel — box-day); constrained/boosted ASR decoding
filed to the transcriber, not the gate; per-lane budgets deferred (one lane
opens calls today); provider reconciliation / idempotency dedup / month-end
projection need a live probe; ambient admission ships OFF with no arm behind
it; replay 52.8% accepted in writing; the ledger remains a documented lower
bound. Standing-tree note for the wave close: the 27 pre-existing reds
(incl. `test_ci_gate`'s manifest sha pin) are the integrator's item, not this
card's. Does not prove: anything through air; every dollar is from fixtures.
