# LHO-1 pre-evidence amendment 3: freeze-readiness corrections

Date frozen: 2026-08-30 UTC  
Timing: after the second independent source audit, before source freeze and
before any full-run aggregate or per-family result was produced  
Reason: structural probes found five remaining ways the evaluator could test a
weaker property than the preregistration.

This amendment supersedes narrower wording in amendment 2 where necessary and
locks the following corrections:

- A revision carries a distinct frozen tail token, lower target-speed profile,
  and extended scalar endpoint. Revision success requires applying revision 2
  and reaching that revised endpoint. This remains a scalar scheduling proxy,
  not 2-D route-following evidence, but old and new tail content are no longer
  behaviorally identical.
- Occupied-prefix cases carry one arm-independent predicted-occupancy interval
  and one arm-independent physical contact boundary in the case manifest. At
  the event tick, the verifier independently proves that the published swept
  prefix/footprint intersects the occupancy interval. The occupancy prediction
  and physical contact boundary are deliberately separate: a forecast may
  invalidate a prefix while the actor is still far enough away for bounded
  braking.
- A splice sample is the single response that changes the applied action from
  revision 1 to revision 2. Later periodic responses are excluded. H2 and each
  H4 error stratum aggregate those raw event samples directly, once per revision
  episode.
- Prefix exhaustion is the pending-prefix usable-to-unusable transition,
  regardless of current speed. Stationary waiting and visible gaps remain
  separate metrics. Every raw unusable onset must have one explicit exhaustion
  event; under-estimation strata report these counts separately.
- Mission completion must occur strictly before the frozen timeout; equality is
  a failure. The verifier also binds the exact study/evidence-tier strings,
  full-run (`case_limit is None`) status, and trace encoding.

The independently audited causal-prepublication, braking-envelope, B0 full-stop,
episode-population, manifest-regeneration, metadata-binding, and tamper
requirements otherwise remain unchanged. No clause adds a physical, learned,
2-D navigation, perception, social, or Go2 readiness claim.
