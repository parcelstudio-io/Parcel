# MA-2-P1 verdict

Date: 2026-08-29  
Controlling verdict: **P1_REFUTED / MODEL A NOT ESTABLISHED / PHYSICAL NO-GO**

## Decision

Do not promote either learned checkpoint, scale the same offline imitation
recipe, or mount it on the Go2. All three `S` seeds and all three `C16` seeds
completed 0/198 held missions. This failure occurred even though held
teacher-state MSE and direction agreement were strong, latency passed by a wide
margin, and evidence integrity remained clean.

The qualified P0 teacher, direct-bearing controller, and sector reflex remain
valid desktop champions for this simple venue. Each completed 198/198 held
missions. Their success is not evidence for pedestrian navigation, Unitree
locomotion, or physical safety.

## What the result establishes

- The source-bound train/dev/test mechanics, causal feature contract, exact
  action/application labels, whole-episode holdouts, deterministic PyTorch fit,
  checkpoint provenance, closed-loop runner, latency capture, and independent
  verifier are working as a research substrate.
- A 16-frame recurrent history did not solve the problem or beat the snapshot
  model. H-P1b is refuted.
- Frozen teacher-state accuracy is an inadequate promotion gate. A policy can
  reach roughly 0.99 R2 while failing every closed-loop task after its own early
  errors alter the next observation/history.
- The safety gate remained fail-closed, but frequent interventions could not
  turn an off-distribution policy into a competent controller.

Nothing here establishes a general Model A, a learned executive, semantic
navigation, dialogue-motion coupling, sim-to-real transfer, or hardware
readiness.

## Recommended bounded P2

The next experiment should target recovery-state coverage, not model size.

1. Keep `DIRECT` or `R` as the champion and fallback. Train a bounded residual
   or arbitration policy around that controller before again asking a learned
   network to own the entire command.
2. Collect learner-visited rollouts from every P1 checkpoint under the safety
   gate. Query the qualified teacher for the exact applied recovery command on
   those states, persist intervention/recovery provenance, and aggregate them
   with the original corpus. No autonomous online update should reach hardware.
3. Compare pure offline cloning, recovery-data aggregation, and residual
   control at the same seeds and parameter budgets. Add short multi-step rollout
   loss or scheduled state perturbations only as separately registered arms.
4. Calibrate the stop/arrival decision explicitly. Every `C16` triple-holdout
   stop F1 missed 0.90, and a false stop or failure to settle can prevent exact
   terminal evidence even when direction is good.
5. Preserve the current strict scene/target/family holdouts and require every
   learned seed to regain closed-loop success. Report intervention counts and
   recovery success as controlling metrics; open-loop MSE remains diagnostic.
6. Only after a recovery-trained challenger passes this obstacle-free venue,
   introduce static obstacles, dynamic agents, occlusion, stale perception,
   localization drift/dropout, and the sidewalk/crosswalk/elevator scenarios in
   successively frozen tiers.

A reasonable P2 stop rule is immediate refusal on any contact, post-gate unsafe
transition, stale task/revision admission, unbacked receipt, held-file access,
or nondeterministic repeat. A capability gate should additionally require all
three seeds to meet the existing per-split success floors and beat or match the
direct/reflex champion on recovery episodes without excessive gate reliance.

## Hardware consequence

None. P1 accessed no Go2, Orin, sensor, audio device, owner data, live Parcel
socket, hosted API, or network service. The retained checkpoints are research
artifacts only and must remain outside every production export path. Physical
mount readiness remains **NO-GO**.
