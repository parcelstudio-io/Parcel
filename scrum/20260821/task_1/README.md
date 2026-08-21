# Task 1 — R22: the pump that cannot die quietly

**Executor:** Claude Opus (agent) · **Auditor:** Fable (deferred — owner will
request the audit; land the work with full evidence so it audits cleanly)
**Trigger:** full-audit CONFIRMED major (AUDIT_FULL_FABLE §Safety-1), the
most dangerous finding in the codebase: the realtime driver thread dies
permanently and silently on any exception outside a four-type catch list —
and the raw-sqlite ledger write rides that same pump thread. A disk-full or
locked-DB error mid-turn kills the pump and with it **the spoken e-stop**,
the stall watchdog, rollover, and idle-close, while the mic stays open and
nothing alarms. The refuter verified the full `sqlite3.Error` MRO: it
subclasses none of the caught types.

## Work

1. **Broad-catch the loop bodies.** `driver.step()`/`_loop` and
   `lane._pump_locked`'s dispatch must survive ANY `Exception` (never
   `BaseException` — KeyboardInterrupt/SystemExit still propagate), each
   caught failure counted and recorded with its type name.
2. **The death alarm.** A pump that stops must be LOUD: a `driver.failures`
   entry is not enough — emit a safety-class runtime event, set a snapshot
   field (`driver.alive`, last-heartbeat age), and surface it in the panel
   beside the safety log. Silence is the defect.
3. **Revival, bounded.** On repeated failures the driver restarts its loop
   (bounded attempts, backoff, counted, ledgered) rather than requiring a
   fresh owner gesture that never comes mid-session.
4. **Kill the sqlite blindspot family everywhere it appears:**
   `lane._write_ledger`, `runtime._write_realtime_ledger`, the
   `_RealtimeLedgerMirror`, and `memory.write_realtime_turn` itself —
   ledger writes must be firewalled at the source (the mirror-store half
   already catches `Exception`; the primary does not). A ledger failure
   degrades to a counted note, never a thread death.
5. **ASR retention handoff** (EV-1 open risk §10.3, 3-line `_dispatch`):
   route `RetainedEvent` frames to the EV-1 evidence log's own sink —
   NOT through `_note` (that would flood the 100-slot ring EV-1 exists to
   relieve). This closes the last hole between the typed codec and the
   evidence stream.
6. **Correct the driver docstring** — its "records the failure and keeps
   going" claim is currently false outside the caught types.

OWNS: `realtime/driver.py`, `realtime/lane.py` (pump firewall + ledger
guard + the retention handoff), `runtime.py` (ledger guard, alarm event,
snapshot field), `memory.py` (write path guard only), `ui/index.html`
(alarm surfacing), tests, `R22_STATUS.md`.
MUST NOT TOUCH: ingress matcher, prompting/SI, whisperer bands, broker
tool set, yield policy, `evals/**` fixtures, configs. Standard house rules
(gate verbatim after final edit; R9 session-B seed harness + `__pycache__`
purge + fresh-interpreter canary; own-stack live proofs; never
commit/stage/stash; owner's :8765 read-only).

## Definition of done

Gate green; ≥10 seeds RED (each restored narrow catch-list; alarm removed;
revival unbounded; revival absent; ledger guard removed at each of the four
sites; retention routed through `_note`). **Live proof that matters most:**
inject a store-write failure mid-turn on your own stack and prove (a) the
pump survives, (b) the alarm fires, (c) a spoken "die stop" still latches
afterwards. Paste the transcript. `R22_STATUS.md` standard register.
