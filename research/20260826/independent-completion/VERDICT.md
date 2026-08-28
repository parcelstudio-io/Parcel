# Verdict — independent completion authority

## REFUTED

The preregistered H2 package failed its nominal-recall promotion gate:
116/120 true nominal arrivals were observed, below the required 118/120. The
candidate is therefore **not** recommended for product integration or physical
motion authority from this evidence.

## What the experiment did establish

- Five correlated arrival ticks do not repair a shared wrong MAP frame: the
  streak arm falsely arrived in 120/120 C2 alias opportunities, exactly like
  covariance-only completion.
- A fresh discriminative target/runner-up witness can be an effective
  fail-closed alias guard in this simulator: 0/120 candidate alias false
  arrivals, including 0/15 when the discontinuity detector intentionally
  missed the jump.
- Evidence expiry and a 3.5 s deadline replaced indefinite waiting with typed
  `localization_uncertain`: 152/152 unresolved alias/dropout cases were typed,
  with zero silent timeout.
- Short evidence outages recovered within the registered latency budget, and
  long outages did not get silently treated as success.

These are supported sub-findings, not a supported overall hypothesis. In all
120 alias cases the candidate abandoned rather than resumed the task.

## Root cause and recommendation

The witness answered “is this the intended physical landmark rather than its
twin?” but did not independently answer “is the body inside the exact terminal
goal region?” Its broad marker range admitted four nominal claims 0.00009--
0.01440 m beyond the scorer's 0.50 m boundary. Three were inherited from the
covariance control; holding during verification exposed one more instead of
masking it with a post-claim integration step.

Do not weaken the hold or widen the truth band after seeing this result.
Instead, preregister a new H2b with separate authorities:

1. **Identity/relocalization evidence:** use a globally discriminative place
   observation to reject an aliased MAP hypothesis and propose a pose reset.
2. **Reset verification:** require a new pose epoch plus scan/landmark residual
   agreement before locomotion re-arms; otherwise remain uncertain.
3. **Terminal geometry evidence:** independently estimate target-relative
   geometry and its covariance, then test a conservative success region. Tune
   only on a calibration split and freeze thresholds before a new scene- and
   sensor-held-out matrix.
4. **Selective evaluation:** report false-completion risk and coverage
   together, plus true recovery after localization reset. A policy that safely
   refuses every alias has solved authority safety, not navigation recovery.

The next evidence step should replace the synthetic descriptor/impulse model
with recorded camera + Mid-360 + IMU sequences, including real pickup, loop
closure, repeated furniture, texture/lighting changes and target occlusion.
Only after zero false completions and non-inferior nominal recall on that frozen
replay should the seam be considered for stationary or tethered Go2 trials.
