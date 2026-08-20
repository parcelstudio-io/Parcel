# Task 1 — R12: the terminal tells the truth (e-stop reason propagation)

**Date:** 2026-08-20 · **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** owner ruling (verbatim): "rename to emergency stop" — approving
AUDIT_R9_FABLE's owner-gated finding 2. An emergency-stopped mission's
terminal currently reads `ended (idle): navigation_disabled`; it must read
`emergency_stop`.
**DISPATCH GATE: this card runs ONLY after the R10→R11→E1 chain closes**
(one card, one tree — AUDIT_R8_FABLE §collision).

## Root cause (from R9's live finding)

`runtime_channels.py:150-152` — `NavigationChannel.stop(reason)` does
`del reason`: every preempt path discards the reason it was handed, so
`_stop_navigation_channel` falls back to the `navigation_disabled` default
regardless of what actually ended the mission. The e-stop is the owner's
named case; the fix is the propagation, so every caller's real reason
(emergency_stop, manual_control, behavior_switch, owner_stop, …) survives to
the mission log, the panel event, and the narration channel.

## Work

1. Propagate `reason` through the channel stop into the terminal write.
   Verify each preempt call-site passes its true reason; e-stop paths (Space,
   "Die Stop", the panel button, `/api/action emergency_stop`) must all
   produce `ended (…): emergency_stop`.
2. The mission-log row, the panel event, AND the narrated fact all carry it
   ("the trip ended because the emergency stop was latched" — via the
   existing floor-gated channel; R8 made it audible).
3. Verify against R10's landed arrival layer — if R10 moved the terminal
   write, fix at the new choke point, not a stale line number.

## OWNS / MUST NOT TOUCH

OWNS: `runtime_channels.py`, the terminal-write glue in `runtime.py`, tests
(extend mission-log + e-stop suites), `scrum/20260820/task_1/R12_STATUS.md`.
MUST NOT TOUCH: `realtime/*` (all closed cards), `ingress.py` (R9's latch is
law), yield/person-stop, `configs/**`, `evals/**` (E1's pack is now a frozen
audit record), owner's processes. Never commit/stage/stash. Standard house
rules (gate verbatim after final edit; snapshot-restore seed harness; solo
evidence discipline).

## Definition of done

Full gate green; ≥5 seeds RED/restored (reason dropped again; e-stop
terminal reads navigation_disabled; log row loses it; narration loses it;
a non-estop preempt mislabeled AS emergency_stop — the over-correction).
Live proof: "Die Stop" during a running mission → mission log shows
`emergency_stop` end-to-end (log row + event + narrated line), then release
and a new mission admits cleanly. R12_STATUS.md standard register.
