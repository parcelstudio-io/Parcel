# DMC-1 independent verdict

Verifier: independent Sol Ultra review followed by a locally reproduced
counterexample probe, 2026-08-29.

## Verdict

**REFUTED for promotion of learned Model A; INCONCLUSIVE for end-to-end Model B
truthfulness; useful only as architectural and generator-shakeout evidence.**

The arithmetic and semantic replay are reproducible, and the artifact is
honest about having no physics/audio/hardware evidence. However, the receipt
validator and narration oracle accept malformed, out-of-order, and mismatched
claims. The supposed held-out language/action rows are substantially authored
to the test. Therefore H3/H4 do not survive independent review, while H1/H2/H5
must be read more narrowly than their automated labels.

The model-selection result is decisive without those disputed rows: A1 missed
its preregistered margin over A0 (0.01886 < 0.05), had 3,781 raw-unsafe and 296
wrong-route proposals, and lost four missions that deterministic L0 completed.
L1 matched A1's 0.3 s liveness p95 with lower mean excess hold. **Do not promote
A1; use explicit temporal logic and keep learned heads offline or shadow-only.**

## Product decision

Keep the architecture, not the experimental ledger:

- retain an independent, fast safety/controller boundary;
- let the existing `TaskExecutive` own task/revision/step/attempt state;
- use the authenticated dialogue receipt reducer for identity, TTL, sequence,
  and transition validation;
- let a trainable Model A propose bounded semantic targets or behavior vectors
  but never assert completion or bypass the arbiter/gateway;
- let Model B render only independently accepted, fully bound receipts; and
- inject change-triggered compact facts into hosted Realtime rather than raw
  10 Hz sensor streams.

The next benchmark must freeze family-disjoint manifests externally, vary
command count/timing, share exogenous latency schedules across arms, emit full
action/receipt/ledger/narration traces, and score them with a separate oracle.
It must include wrong step/attempt, illegal status order, forged identity,
expiry, replay after restart/epoch, transport loss, duplicate ID/payload, and
completion-during-barge-in cases. Compare L1/A0/A1 using real
`NavigationSnapshotV2` and product `TaskExecutive` replays.

## Mount readiness

Physical motion remains **NO-GO**. DMC-1 contains no evidence about braking,
gait/payload stability, collision geometry, camera/LiDAR perception, owner
voice/addressee detection, acoustic echo/barge-in, Orin timing/thermal power,
Starlink failure, ROS 2/SDK2 integration, stairs, crosswalks, or elevators.
Nothing in this experiment shortens the staged simulator → HIL → stationary →
tethered physical promotion ladder.
