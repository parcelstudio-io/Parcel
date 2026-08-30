# LHO-1 pre-evidence amendment 2: causal prefix and oracle hardening

Date frozen: 2026-08-29  
Timing: after a source-code audit, before source freeze and before any aggregate
or per-family evidence result was produced  
Reason: the first implementation draft exposed ambiguities that could have
made the test reward a prefix created after an instruction revision, or let the
evaluator trust policy-authored collision and boundary flags.

This amendment fixes the following semantics before the test set is opened:

- Each tracker tick first publishes or retains exactly one bounded, braking-safe
  controller prefix from the then-current plan. Only after that publication are
  planner responses and exogenous revision/STOP/occupancy events consumed. A
  revision freezes that already-published prefix; it may not create or extend an
  old-plan prefix using knowledge of the revision.
- Prefix run time is quantized to tracker ticks. The G0 run window is the smaller
  of the ceiling of estimated latency plus margin and the floor of the validated
  corridor cap. The prefix endpoint additionally contains the complete bounded
  braking distance. Expiry commands zero soon enough to remain inside that
  endpoint.
- Every trace carries the authoritative/action revision, published prefix,
  request/response/exhaustion events, pending-request count, and prefix-record
  count. Queue and prefix bounds are therefore trace-verifiable rather than
  asserted from an aggregate.
- The independent verifier derives stale distance from segment geometry and the
  frozen prefix. For occupied-prefix cases it reconstructs the obstacle from the
  pre-event state and independently checks continuous one-dimensional swept
  segments. It does not accept policy-authored collision or stale flags as the
  oracle.
- H4 passes only if every observed under-estimation stall has an explicit
  exhaustion event, all error strata retain H2/H3 safety properties, and both
  pending-request and prefix-record maxima are at most one.

The scalar path coordinate remains a transaction/scheduling surrogate. Route
family curvature changes the splice-load proxy, but this is not a 2-D route,
perception, social-navigation, quadruped-dynamics, or physical-braking test.
The original hypothesis bars and all non-claims remain unchanged.
