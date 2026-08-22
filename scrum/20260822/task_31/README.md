# Task 31 — CAP-1: what the product admits, in one place

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply: prototype not production — this card makes admission
*explicit and consistent*, it does not add refusals). **Evidence:**
`AUDIT_WEEK1_FABLE.md` (ROAM-1 finding 1: `TOOL_ROAM` rejected by the
supervisor's `BEHAVIOR_MODES`; finding 6: the prototype overlay loader refused
the `roam:` block; MARK-1: knobs with no config key or runtime caller),
`backlog/NEXT.md` "Active worktree delta" (a YAML can disable the POI oracle
while the process-global candidate source stays the oracle — "a startup defect
to close, not a shadow mode"), `INTEGRITY_GATES_TODO.md` IG-3 (the narrowed
part: startup-fatal admission of required capabilities).

## Why
Four times this week a feature was complete at its mechanism and dead at the
door: the safety supervisor's allowlist, the overlay loader's key set, the
proactive-motion sets, the default candidate source. Each door is right to
exist; what is wrong is that nothing checks the doors against each other or
against what the runtime was configured to run.

## Work
1. **One admission table.** A module (`parcel_robot/admission.py` or the
   existing config package — read first) that *reads* the existing sources of
   truth — `safety.BEHAVIOR_MODES`, the broker's tool table and its
   `ALLOWED/REFUSED` proactive sets, `OVERLAY_INTRODUCIBLE_KEYS`, the
   navigation source selection (oracle / learned / shadow) — and exposes
   `admitted()` with a reason per entry. No new gate; a view.
2. **Cross-check tests that would have caught the week-1 defects:** every
   broker tool that maps to a behavior name is in `BEHAVIOR_MODES`; every
   config key a runtime region reads is loadable by the prototype overlay;
   every proactive-motion tool is in exactly one of ALLOWED/REFUSED; the
   candidate source actually bound at startup equals the one the YAML names
   (the POI-oracle defect) — seeded RED each.
3. **Startup-fatal required capabilities** (IG-3, narrowed): a prototype
   profile declares which capabilities are *required* (e.g. learned-map source
   when `oracle: false`); `RobotRuntime` refuses to start — with the admission
   table printed — when a required capability is not bound, instead of running
   with the oracle by default. Ask-over-refuse still governs at runtime; this is
   a configuration-truth check at startup only, and it is seeded.
4. **`/api/state` exposes the admission table** so an operator can see why a
   tool or behavior is unavailable (CURIO-1's `curiosity_snapshot()` had no
   surface either — route it here).

OWNS: the new admission module, `tests/test_cap1_*.py`, one marked region in
`runtime.py` (startup check + `/api/state` key; re-read: VENUE-1/OT-2/DOOR-1
regions are elsewhere), `configs/*.prototype*` one `required_capabilities:`
block, `task_31/` docs. MUST NOT TOUCH: `reactive_safety`, `core/hard_stop`,
the supervisor's semantics (read it, never change what it refuses), the
broker's tool bodies.

## Definition of done
Four cross-check guards seeded RED; the startup check demonstrated on the
POI-oracle defect (YAML says no oracle → startup refuses with the table) and
on the week-1 cases (a broker tool absent from `BEHAVIOR_MODES` is caught at
test time); `CAP1_STATUS.md`.
