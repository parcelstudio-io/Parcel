# Task 33 — ROAM-2: "explore" covers the room

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** `task_23/ROAM1_STATUS.md` (handoff:
"the spread is the metric telling you there is no coverage objective … P1-B's
learned map knows which places have been seen, and `PatrolPolicy` is a pure
function that could take a least-recently-seen bearing the way it already
takes a person bearing"), `AUDIT_WEEK1_FABLE.md` §ROAM-1 (the tether; the
in-bounds qualifier; 6.54 / 6.47 / 6.56 m net in-block), `task_24/CURIO1_STATUS.md`
§9.6 (remarks ride the idle checkpoints).

## Why
ROAM-1 proved the dog goes somewhere on command and comes back. A companion
that "explores" should *cover* the room — visit what it has not seen lately —
so that CURIO-1 has something new to remark on and the learned map fills in.
Distance was the purchase input; coverage is the companion behaviour.

## Work
1. **A coverage objective from the learned map:** `online_map` exposes, under
   its existing lock, a *least-recently-seen bearing* (or a small set of
   candidate bearings with last-seen ages) from the entries P1-B keeps;
   `PatrolPolicy` takes it as an optional input beside the person bearing and
   the tether — pure function, default off (MOVE-1/ROAM-1 baselines untouched),
   `limits_from_safety` turns it on for the prototype.
2. **Yield order unchanged:** safety gates, e-stop, owner command, budget,
   freshness, tether, then coverage. A stale map (no entries, or all ages
   unknown) degrades to ROAM-1's wander, never to a stop.
3. **Idle checkpoints are where it thinks:** the policy publishes an idle
   checkpoint after each coverage leg; CURIO-1's `roam_idle_checkpoint()`
   consumer already waits for it — measure remarks per leg.
4. **Pre-register, then measure** three consecutive 120 s `--static-city`
   runs through the product runner: **coverage** = distinct map entries seen
   (within the learned map's own visibility rule) / entries known at start,
   reported with ROAM-1's path, net in-block, contacts and clearance rows;
   target **≥ 1.5× ROAM-1's tethered baseline** (measure that baseline first
   with the same definition — pre-register the number); 0 contacts; zone
   respected; second arm in the dynamic city reported, not gated.
5. Seeds RED: coverage input ignored (policy wanders as before); a stale-map
   tick that stops instead of wandering; a coverage leg that crosses the tether.

OWNS: `patrol/` (new input + tests), one `online_map` public query (+ its
test; not the writer), `runtime.py` ROAM-1 region only (marked; wire the
query), `tests/test_roam2_*.py`, `task_33/` docs. MUST NOT TOUCH:
`reactive_safety`, `core/hard_stop`, the supervisor, CURIO-1's region,
`vlm_veto/`.

## Definition of done
Pre-registered rows measured through the product runner (three runs, both
arms); the coverage number reported plainly beside ROAM-1's distance rows;
seeds RED; `ROAM2_STATUS.md`.
