# Task 5 — R16: an idle lane hangs up

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** owner session 1, F5: the lane sat open ALL NIGHT with nobody
talking, rolling over hourly (7 `[session rollover]` ledger rows 06:23→12:23)
— each rollover a fresh provider session with tail re-injection. A companion
that is not being talked to should hang up and re-open on the next owner
gesture, which the product already knows how to do (text mode opens on first
message; audio opens on the mic gesture).

## Work
1. `idle_close_after_s` in the realtime config (fail-closed validation,
   documented in the example; default generous, e.g. 600). Idle = no owner
   turn, no narration, no pending response for that long ⇒ the lane CLOSES
   cleanly (ledger note `[idle hang-up after Ns]`), driver stops pumping,
   next owner gesture re-opens exactly like a fresh session.
2. Rollover only renews a session that is NOT idle; an idle session at
   rollover time closes instead.
3. The mic gateway stays armed-but-idle (the browser affordance keeps
   working; the click re-opens). The whisperer must not KEEP the lane alive
   (a narration into a closed lane is a skip, counted — the always band's
   critical facts still latch locally regardless; state this in the doc).
4. Live proof: open a session, go quiet past the threshold (injected clock
   for the offline test, one short real wait live), watch it hang up, speak
   again, watch it re-open. Ledger rows pasted.

OWNS: `realtime/lane.py` (idle tracking + close path), `realtime/config.py`
(one additive key), `realtime/driver.py` if the pump needs the hook,
`runtime.py` glue, `configs/realtime.yaml.example`, tests, `R16_STATUS.md`.
MUST NOT TOUCH: ingress, protocol, broker, whisperer bands, prompting.
DoD: gate green; ≥6 seeds RED incl. idle detection removed, rollover
renewing an idle session, whisperer keeping the lane alive, and the
re-open-on-gesture path broken; live proof; standard register. Note the
owner's overnight config file must not be edited by the executor — the
default applies until the owner sets the key.
