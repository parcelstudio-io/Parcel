# DMC-3 verdict

**H1-H3 pass twice; H4 remains partial/red; promotion fails.**

The new production seam is suitable for continued unit, simulation, and HIL
development. It is not a mount-readiness result. Autonomous physical motion
remains **NO-GO**: this experiment neither changes nor validates actuation,
navigation, perception, collision avoidance, audio, provider delivery, Orin
timing, or robot safety.

The immediate next implementation should be an authoritative transition
journal inside `TaskExecutive`, not runtime snapshot comparison:

1. Define a bounded immutable `ExecutiveTransitionV1` carrying executive
   sequence/call identity, exact pre/post task lineage, transition kind,
   disposition, and only the accepted report's verified facts/evidence.
2. Append the record under the executive's own lock at every mutation site,
   including all `tick` timeout/retry/failure, precondition wait, resource wait,
   empty-step completion, dispatch, report, replacement, interrupt, suspend,
   resume, and dispatch-failure branches.
3. Let the wrapper read the exact transition batch committed by its delegate
   call while holding the wrapper lock. Reject gaps, regressions, overflow, or
   a transition that cannot be mapped one-to-one; never reconstruct it from a
   later snapshot.
4. Only after exhaustive branch tests should `RobotRuntime` construct the
   wrapper once and route its full explicit `TaskExecutive` API through it.
   Speech generation must come from `voice_session.speech_epoch` (or `0` before
   voice construction), the queue must remain bounded with visible overflow,
   and consumed frames must remain diagnostic/narration-only.
5. Re-run H1-H4 twice plus the existing brain/runtime and mount-boundary
   guarded regressions. Promotion is allowed only if the full gate is green.

Mounting the current software because H1-H3 passed would overstate the
evidence. The correct disposition is to retain the bridge and replay corpus,
implement authoritative transition records, and keep H4 visibly red until the
runtime route and regressions are proved.
