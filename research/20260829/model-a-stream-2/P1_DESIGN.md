# MA-2-P1 — bounded learned local-control challenger

Status: **FROZEN DESIGN / NOT IMPLEMENTED / NOT TRAINED**  
Date: 2026-08-29  
Input evidence: the independently verified MA-2-P0 traces only  
Authority: desktop research only; no production export, socket, or hardware

## 1. Question and claim boundary

P0 established that an easy, causal demonstrator/ledger/transaction substrate
is internally consistent. P1 asks the next smallest learned question:

> Can a small causal sequence model imitate the exact applied local command and
> retain closed-loop exact-target control when scene, semantic target role, and
> transaction family combinations are held out?

P1 tests **Head 1 only**. The product executive plus the frozen P0 champion owns
task submission, interruption, queueing, exact terminal reports, and resume.
P1 does not train Head 2 or Head 3 because P0 did not persist dense champion
proposal/event labels for those heads. Calling a narration token or scripted
resume a learned executive decision is forbidden.

This remains an obstacle-free, yaw-static, scripted-cue experiment. Even a pass
is only evidence that training mechanics and the causal local-control interface
work. It cannot pass H-MA2a--e, establish generalized navigation, or authorize
physical motion.

## 2. Frozen episode partition

The split is by entire episode; no window crosses an episode. `door`, `sofa`,
and `bench` are training target roles. `elevator` and `keys` are target-role
holdouts. `plain` and `interrupt_now` are training transaction families;
`queue_resume` is the family holdout.

| split | scenes | target roles | families | episodes | frames | use |
|---|---|---|---|---:|---:|---|
| train | 00--05 | train roles | train families | 72 | 7,272 | fit |
| dev | 06 | train roles | train families | 12 | 1,443 | checkpoint/loss only |
| test-S | 07--09 | train roles | train families | 36 | 3,822 | unseen scene |
| test-T | 00--05 | held roles | train families | 48 | 5,333 | unseen target role |
| test-F | 00--05 | train roles | held family | 36 | 5,215 | unseen transaction family |
| test-TF | 00--05 | held roles | held family | 24 | 3,957 | held target + family |
| test-ST | 07--09 | held roles | train families | 24 | 2,578 | held scene + target |
| test-SF | 07--09 | train roles | held family | 18 | 2,741 | held scene + family |
| test-STF | 07--09 | held roles | held family | 12 | 1,968 | controlling triple holdout |
| audit-only | 06 | any held factor | 18 | 2,425 | never selection or headline |

The 12-episode `test-STF` denominator is small. P1 reports exact counts and
Wilson intervals and cannot use this probe for a capability-promotion claim.
The split measures invariance of local control to held semantic labels and task
transactions; it does not measure language grounding because the model never
receives role text.

Before training, a generated split manifest must prove episode disjointness,
the exact counts/frame counts above, and content hashes matching P0's final
manifest. Held traces must not be opened by the training process. The runner
stages only train/dev feature shards into its training directory and retains a
file-access log. Test inference begins only after checkpoint, source, config,
and dev-selection hashes are frozen.

## 3. Leakage-free feature/label contract

The feature extractor accepts only each row's verified `policy_input` object
and the causal frames preceding it in the same episode. It independently
rechecks the P0 allow-list and rejects any `scorer_only`, trace aggregate,
future row, terminal outcome, teacher status, actual pose, truth distance,
collision clearance, or gold event.

The model does not receive scene ID, task family, target role text, entity UUID
bytes, candidate-list index, episode ID, seed, scorer field, or absolute target
coordinate. A deterministic non-learned extractor resolves the opaque current
`mission.target_ref` inside the current semantic candidate list, then discards
both the UUID and list position. Frozen numeric inputs are:

- current target-relative estimated `(dx, dy)` and validity mask;
- robot estimated velocity, yaw, stop flag, and four covariance values;
- eight LiDAR sector ranges, freshness age/stale/missing masks;
- previous applied `(vx, vy, vyaw)` and previous gate disposition;
- mission revision/attempt normalized scalars, parent-present flag, queued-count
  scalar, and accepted-receipt age; and
- a 16-frame (1.6 s) causal history with left padding and explicit masks.

The target is exactly the current row's `actions.actuator_applied` triple. The
loader recomputes the serialized application digest and rejects a row unless
`safety_admitted == actuator_applied`, `label_apply_equal == true`, and the row
hash chain is valid. Rows after a terminal boundary never label an earlier
window. No target is derived from `teacher_requested` or a counterfactual.

Inputs are normalized using train-only statistics. Clipping constants are
written before the dev run. Missing values remain masked; zero never means
missing.

## 4. Frozen arms

| arm | definition |
|---|---|
| `T*` | qualified P0 causal teacher through the same tracker/gate/world path |
| `R` | frozen 8-bearing-sector, three-speed reflex with 0.18 m stop band |
| `DIRECT` | constant-speed estimated-bearing follower with stop band, no history |
| `IDLE` | zero command |
| `S` | current-frame MLP: two 128-unit SiLU layers, under 100k parameters |
| `C16` | one-layer GRU, hidden 128, 16 frames, MLP head, under 250k parameters |

`S` and `C16` train independently at seeds `20260829`, `20260830`, and
`20260831`. One seed (`20260829`) repeats from a clean process; checkpoint hashes
must match. P1 does not add a 60-second arm because P0's venue has no delayed
state requirement. `T*`, `R`, and `DIRECT` are run and traced, not reconstructed
from model results.

## 5. Training protocol

- PyTorch deterministic algorithms on; TF32 off; fixed namespace-specific
  Python/NumPy/torch/data-order seeds.
- Robust Smooth-L1 `(vx, vy, vyaw)` loss plus an auxiliary stop BCE derived only
  from the exact applied label. No event/executive loss exists in P1.
- AdamW, learning rate `3e-4`, weight decay `1e-4`, batch 128 windows, gradient
  norm 1.0, maximum 5,000 optimizer steps, evaluation every 100 steps, patience
  800 steps. These values may not change after a training log exists.
- Checkpoint score: dev applied-command MSE, with direction agreement and stop
  F1 as diagnostics. Open-loop selection never sees any `test-*` shard.
- Closed-loop rollout starts from the P0 episode specifications, but the learned
  arm supplies the command proposal. Every proposal still traverses the same
  tracker, safety gate, exact action ledger, `world.apply`, evaluator, product
  executive, and receipt adapter. No teacher correction is applied.

## 6. Metrics and preregistered hypotheses

Open-loop diagnostics for every split: MSE/MAE by axis, variance-weighted R2,
nonzero direction agreement, stop precision/recall/F1, and worst target/family
stratum. They cannot pass the experiment alone.

Closed-loop metrics: exact mission success, exact target precision, frames to
completion, path length, jerk, gate interventions, contacts, post-gate unsafe
commands, exact transaction sequence, stale task/revision command admissions,
and receipt-backed terminal count. Report counts and Wilson 95% intervals.

### H-P1a — a learned causal challenger is viable

For **every** `C16` seed:

- closed-loop exact mission success is at least 0.90 on test-S, test-T, and
  test-F; at least 0.80 on test-TF, test-ST, and test-SF; and at least 0.75
  (9/12) on controlling test-STF;
- exact-target terminal precision is 1.0, with zero contacts, post-gate unsafe
  commands, stale-revision admissions, ineligible resumes, or unbacked terminal
  receipts;
- held test-STF applied-command MSE is at most `0.01`, nonzero direction
  agreement is at least 0.95, and stop F1 is at least 0.90; and
- test-STF median completion frames and path length are each no more than 1.25
  times `T*` on jointly successful episodes.

All clauses are conjunctive. Because the venue is easy and `T*`/reflex may
saturate, P1 asks the learned arm to match useful behavior, not claim novelty.

### H-P1b — temporal state earns its cost

`C16` must beat separately trained `S` by at least 0.05 absolute exact mission
success on either the combined held-family splits (`test-F`, `test-TF`,
`test-SF`, `test-STF`) or interruption resume subpopulation, without worse
safety invariants or more than 10% worse completion frames. Otherwise H-P1b is
refuted and a snapshot policy is preferred for this venue.

### H-P1c — deployment-shape latency is feasible

Feature serialization plus batch-one forward pass must have p99 at most 10 ms
on the designated RTX 5000 Ada GPU and at most 50 ms on one host CPU thread,
after 500 warmups and over 10,000 timed calls. Report p50/p95/p99, device/model
identity, parameter count, peak VRAM/RSS, power mode if observable, and host
load. This is not an AGX Orin result.

Interpretation:

- `P1_RESEARCH_CHALLENGER`: all integrity gates and H-P1a/H-P1c pass.
- `P1_SNAPSHOT_SUFFICIENT`: H-P1a/H-P1c pass but H-P1b fails.
- `P1_REFUTED`: H-P1a or H-P1c fails with valid evidence.
- `INVALID_PRECONDITION`: trace, split, held-access, causal feature, action
  alignment, replay, or provenance gate fails; no capability verdict.

No outcome authorizes a product export or physical motion.

## 7. Evidence and adversarial checks

Persist full closed-loop traces for every arm/seed/test episode with the P0 row
chain plus raw model output and checkpoint hash. An independent stdlib verifier
must recompute split membership, P0 ancestry, action alignment, causal window
boundaries, all controlling metrics, seed-wise gates, latency samples, and final
verdict. Required tamper cases change one feature timestamp, one applied label,
one split membership, one checkpoint hash, and one terminal receipt; all must
exit nonzero.

Before fitting, run two negative leakage fixtures:

1. mutate every `scorer_only` value while holding policy payloads fixed and
   prove extracted tensors/checkpoint input shards are byte-identical; and
2. permute UUID strings and semantic candidate order while preserving the exact
   pointer/relative estimate and prove extracted tensors are byte-identical.

## 8. Resource estimate and stop rules

| work | upper bound |
|---|---:|
| feature shards + leakage tests | 5--10 CPU min, under 1 GB |
| six learned runs (2 arms x 3 seeds) + one repeat | 5--20 GPU min, under 2 GB VRAM |
| all closed-loop arm/seed splits | 10--25 wall min, 10--30 CPU min |
| GPU + one-thread CPU latency | 5--10 wall min |
| trace compression + independent verification | 10--20 wall min, about 100--250 MB |
| total | about 30--60 wall min, under 0.5 GPU h |

Stop immediately on a source/manifest mismatch, any held-file read before the
checkpoint freeze, causal tensor change under the scorer-only mutation, action
label/application mismatch, nondeterministic repeated checkpoint, post-gate
unsafe command, contact, stale-revision admission, unbacked terminal receipt,
or more than 4 GB VRAM / 8 GB host RSS.

Training must not start merely because this document exists. The runner,
manifest, feature extractor, and independent verifier must be reviewed and
hashed first, and GPU work must respect other active research jobs.
