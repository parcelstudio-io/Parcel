# Task 2 — R13: the pace watcher never goes silent

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** E1 `run-with-me-flex` FAIL + AUDIT_R11 carry-forward: `_pace_watch`
treats `owner_speed_mps=None` (common for tens of seconds) as "still running"
and writes NO decision row — the log that exists to audit suppression has a
blind spot, and the owner's "should we just walk?" ask never fires.

## Work
1. `None` speed becomes an explicit `pace_unknown` state: counted, logged
   (every tick writes a row or a counted skip — pin that invariant), and the
   mismatch window pauses rather than resets while unknown.
2. When speed returns, the window resumes; a sustained walk still yields
   `pace_mismatch` + ask-hint. Live-verify with the E1 scenario re-run
   pattern (scripted owner run→walk), transcript pasted.
3. Owner-session evidence check: yesterday's session had follow active with
   "Keep up" — determine from the decision log whether the watcher was in
   the None-hole there too; state it.

OWNS: `realtime/whisperer.py`, `runtime.py` pace wiring, tests,
`R13_STATUS.md`. MUST NOT TOUCH: lane/broker/protocol/ingress, follow
safety caps, `configs/**`, `evals/**` (the E1 pack verdicts stay FAIL —
history is not retconned). DoD: gate green; ≥5 seeds RED incl. the None-hole
restored and the every-tick-writes invariant broken; live proof; standard
register.
