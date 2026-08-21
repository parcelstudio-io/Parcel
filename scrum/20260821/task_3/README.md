# Task 3 — R24: the doors take the lock

**Executor:** Claude Opus (agent) · **Auditor:** Fable (deferred)
**Trigger:** full-audit CONFIRMED major (§Arch-1): the realtime motion tool
doors (`_realtime_navigate`, `_realtime_follow`, `_realtime_orbit`) mutate
VoiceAgent state **without acquiring `_agent_lock`** — cross-thread, from
the pump thread, into state the lock exists to serialize. Plus the
CONFIRMED-minor siblings: `_navigation_lock` protects only 3 of the
navigator's mutating entry points (pause/resume/stop-on-resume mutate
lock-free), and compound realtime state (`_realtime_pace_intent`,
`_realtime_last_*`) is written cross-thread outside `_lock` while read and
cleared under it.

## Work

1. **Take `_agent_lock` in the three doors** — or, if the executor's
   analysis shows the lock cannot be held across the door's full body
   without inverting the verified lock DAG (audit §Arch-healthy confirms
   the ordering is currently a DAG — DO NOT break that), narrow the
   critical section to the mutation and document the reasoning. The DAG
   property must be re-verified after the change and stated in the doc.
2. **Close the navigator's lock-free entry points** (pause/resume/
   stop-on-resume) the same way.
3. **Make compound realtime state consistent:** every write of the
   `_realtime_*` compound fields takes the same lock its readers take;
   where a field is genuinely single-writer, say so in a comment and pin
   the invariant.
4. **A lock-discipline test:** an AST/static check (the repo already has
   the `_dispatch_active` digest-pin precedent and an AST lock scanner used
   by the audit) asserting that the named mutating sites are inside their
   lock — so the next door added without it reddens.

OWNS: `runtime.py` (door bodies + navigator entry points + compound state),
`navigation/` lock plumbing if required (smallest touch, justified), tests,
`R24_STATUS.md`.
MUST NOT TOUCH: lane/protocol/ingress/broker/whisperer behavior, yield
policy, configs, evals. Standard house rules.

## Definition of done

Gate green; ≥8 seeds RED (each door's lock removed; each navigator entry
point reopened; a compound write moved outside the lock; the discipline
test deleted). **Concurrency evidence, not just tests:** a stress harness
driving the doors from the pump thread while the panel thread reads the
snapshot, run long enough to shake out a race (state the iteration count
and duration honestly), plus a re-verification that the lock ORDER graph
is still acyclic. `R24_STATUS.md` standard register.
