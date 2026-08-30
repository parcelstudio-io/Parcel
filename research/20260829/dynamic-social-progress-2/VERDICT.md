# DSP-2 verdict

**Strict verdict: REFUTED. Do not carry S2 or S3 into a physical robot, a
motors-enabled HIL test, or a claimed safe-proximity setting.**

Both remediated arms failed the primary gate on the frozen unseen population:
S2 and S3 each had 25 contact episodes out of 145, and every contact included
an actor moving into a stationary robot. Each also accumulated hundreds of
current hard-floor ticks. This directly refutes D2-H1 and makes both arms
ineligible regardless of completion or latency.

The result is narrower—and more informative—than “prediction does not work.”
S2 and S3 had zero contacts across all 45 non-responsive episodes per arm,
including zero across the 35 otherwise-feasible non-responsive episodes. Their
25 contacts were concentrated in responsive group/overtaking and elevator
egress families. The frozen authored response law therefore exposed a failure
to reserve a complete escape/staging tube when another actor adapts around the
robot; a one-time robust candidate plus stop fallback was insufficient.

The liveness hypothesis also failed independently. Against S2, S3 increased
false-block time from 805.6 to 966.5 seconds (19.97% worse), reduced transitions
only 7.47% rather than 20%, and lowered task completion from 88.28% to 85.52%.
Its measured evidence-to-decision p95 (`0.4 s`) and decision-to-motion p95
(`0.0 s`) met their isolated bounds, but the conjunctive H3 gate was refuted.
S3 also produced 30 releases classified as based on missing/non-free evidence
on held-out episodes, refuting the missing-only clause of H4.

## Recommended next experiment

Start a separately preregistered DSP-3; do not tune DSP-2 after seeing test.
The next candidate should:

1. reserve and execute a full braking-reachable escape tube, including the
   robot's acceleration state and a protected terminal pocket, instead of
   re-solving to a stationary fallback inside an actor's swept volume;
2. model interaction topology explicitly—same-flow overtaking, two-person
   group gaps, and elevator exit streams need different right-of-way and
   staging constraints;
3. make the release certificate stateful and auditable so a missing detection
   can only reset to `BRAKE`, never contribute to a release edge;
4. add adversarial actor-response families during train/development while
   keeping new whole episodes and seeds unseen for test; and
5. repeat the contract in a responsive social simulator such as HuNavSim/ROS 2
   or an equivalent higher-fidelity environment before recorded-sensor replay
   and motors-disabled HIL.

DSP-2 establishes no safe human distance, intent-prediction validity, Go2
stopping distance, elevator behavior, crosswalk safety, or physical readiness.

