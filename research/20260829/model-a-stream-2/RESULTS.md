# MA-2 results — P0 foundation and P1 learned challenger

Date: 2026-08-29  
P1 protocol: [`P1_DESIGN.md`](./P1_DESIGN.md)  
Evidence tier: desktop, obstacle-free, pedestrian-free kinematic simulator  
Controlling P1 status: **P1_REFUTED**  
Model-A / hardware status: **not established / physical NO-GO**

## Outcome

P0 established a valid causal teacher, action ledger, exact-target evaluator,
queue/resume transaction path, and 300-episode corpus. P1 then asked whether a
small snapshot MLP or 16-frame GRU could imitate the exact applied local command
and remain competent when whole scenes, semantic target roles, task families,
and their combinations were held out.

The answer is no for this training method. Frozen-row diagnostics were strong,
but all learned policies failed every closed-loop held mission. Three simple
non-learned controllers completed every mission. Independent verification
recomputed the negative result from retained traces and found no integrity or
safety-invariant violation.

## Frozen partition and preconditions

| split | episodes | frames | held factor |
|---|---:|---:|---|
| train | 72 | 7,272 | none; scenes 00--05, train roles/families |
| dev | 12 | 1,443 | scene 06 only |
| test-S | 36 | 3,822 | scenes 07--09 |
| test-T | 48 | 5,333 | elevator/keys roles |
| test-F | 36 | 5,215 | queue/resume family |
| test-TF | 24 | 3,957 | target + family |
| test-ST | 24 | 2,578 | scene + target |
| test-SF | 18 | 2,741 | scene + family |
| test-STF | 12 | 1,968 | scene + target + family |
| audit-only | 18 | 2,425 | scene 06 with any held factor |

All 300 episode IDs were unique across partitions. Before fitting, all five
leakage fixtures passed 40/40: scorer-only mutations and UUID/order permutations
left features identical; whole trace rows, future timestamps, and misaligned
labels were rejected. The training command exposed only train/dev shards and
recorded optimizer step zero.

## Training and determinism

Both arms used the frozen AdamW schedule for at most 5,000 steps at seeds
`20260829`, `20260830`, and `20260831`. Seed `20260829` was rerun for each arm.

| arm | parameters | best dev MSE range | repeat evidence | peak VRAM |
|---|---:|---:|---|---:|
| `S` | 21,380 | 0.000805--0.000927 | checkpoint bytes and normalized logs identical | 70,217,728 B |
| `C16` | 80,004 | 0.000839--0.000972 | checkpoint bytes and normalized logs identical | 308,764,672 B |

The fit-process access audit reported zero held-shard reads. All pre-evaluation
gates passed.

## Closed-loop results

Each row below reports success over the same 198 held episodes across all seven
test splits.

| arm / seed | exact missions | rate | interpretation |
|---|---:|---:|---|
| qualified teacher `T*` | 198 / 198 | 1.0 | champion |
| sector reflex `R` | 198 / 198 | 1.0 | slower but sufficient baseline |
| direct bearing `DIRECT` | 198 / 198 | 1.0 | sufficient snapshot baseline |
| `IDLE` | 0 / 198 | 0.0 | negative control |
| `S` / 20260829 | 0 / 198 | 0.0 | failed |
| `S` / 20260830 | 0 / 198 | 0.0 | failed |
| `S` / 20260831 | 0 / 198 | 0.0 | failed |
| `C16` / 20260829 | 0 / 198 | 0.0 | failed |
| `C16` / 20260830 | 0 / 198 | 0.0 | failed |
| `C16` / 20260831 | 0 / 198 | 0.0 | failed |

The same 0-success result held on every individual learned split, so H-P1a
failed for every seed. No learned/teacher jointly successful episode existed;
the preregistered completion-frame and path ratios were therefore undefined.
`C16` could not beat `S`, so H-P1b also failed.

Across all arms, retained evidence had zero contacts, post-gate unsafe
transitions, stale-revision commands, ineligible resumes, or unbacked terminal
receipts. The learned policies did trigger many rate/safety-gate interventions
while leaving the teacher trajectory: 199,694 across the three `S` streams and
122,879 across the three `C16` streams. These safe clamps prevented an unsafe
transition but did not recover the task.

## Open-loop diagnostics

The controlling triple holdout (`test-STF`) exposes the open/closed-loop gap.

| arm / seed | MSE | direction | stop F1 | variance-weighted R2 |
|---|---:|---:|---:|---:|
| `S` / 20260829 | 0.001425 | 0.995246 | 0.805556 | 0.992279 |
| `S` / 20260830 | 0.001330 | 0.995246 | 0.825175 | 0.992794 |
| `S` / 20260831 | 0.001673 | 0.996830 | 0.842857 | 0.990936 |
| `C16` / 20260829 | 0.001819 | 0.997887 | 0.895105 | 0.990149 |
| `C16` / 20260830 | 0.001630 | 0.995774 | 0.882759 | 0.991171 |
| `C16` / 20260831 | 0.001799 | 0.990491 | 0.888889 | 0.990254 |

Every MSE and direction clause passed, but every `C16` stop-F1 value missed the
0.90 gate. More importantly, none of these frozen-row scores predicted useful
closed-loop control.

### Post-hoc failure trace

In held episode `ep-scene-07-door-plain-r0`, `C16` seed `20260829` produced the
same first prediction in the open- and closed-loop paths, as expected. The
teacher-applied first label was `(-0.12, 0.12, 0.0)` while the learned proposal
was `(0.023328, 0.150279, -0.003446)`. After that single different transition,
the learner's frame-1 proposal became `(0.220568, 0.211708, 0.144238)`, whereas
its prediction on the teacher-state frame-1 row was
`(-0.095216, 0.256295, -0.002418)`. By frame 50, exact-target distance had grown
from 3.842 m to 5.724 m; the episode ended at its 240-frame cap.

This trace is diagnostic, not a newly preregistered hypothesis. It directly
shows compounding state-distribution shift and motivates on-policy recovery
data rather than a larger offline cloning model.

## Latency

H-P1c passed on the designated desktop. Each value includes feature extraction
and batch-one inference after 500 warmups over 10,000 retained timings.

| arm | CPU p99 range | RTX 5000 Ada p99 range | frozen limits |
|---|---:|---:|---:|
| `S` | 0.155785--0.160804 ms | 0.676282--0.685037 ms | 50 / 10 ms |
| `C16` | 0.386444--0.389759 ms | 0.804646--0.834367 ms | 50 / 10 ms |

This is not an AGX Orin latency measurement.

## Independent verification and adversarial checks

The standard-library verifier independently checked source/shard/checkpoint
hashes, held-access absence, repeat determinism, checkpoint-to-trace binding,
raw-command/action-ledger equality, row chains, causal feature allow-lists,
terminal receipts, transactions, every per-episode metric, all aggregate
metrics, all hypotheses, latency percentiles, and the verdict.

| retained evidence | verified amount |
|---|---:|
| closed-loop traces / frames | 1,980 / 677,784 |
| open-loop traces / rows | 42 / 153,684 |
| raw latency samples | 120,000 |
| deliberate tamper cases rejected | 5 / 5 |

The five mutations targeted a feature timestamp, applied label, split
membership, checkpoint hash, and terminal receipt.

## Provenance and exact commands

| artifact | SHA-256 |
|---|---|
| final manifest | `1f79b8560deab92f6814b0a7e262487bed1916c033a7fca79af606d17a7d7c7f` |
| preconditions | `aa35e7f4fe45ed69f85bfcdac03a2a5a989a7021f7578d68cf08fe61e0eefb34` |
| split manifest | `f2c91e8a863a5cf5327593ce171e0acb5f06205b9c1c94d1a0539b572f53d8f1` |
| training | `5781d823b139433df29132b31425c8b2b77e4b85bc151936c31fc6c3e4779ed0` |
| results | `0bb0463ab7ac7957de3f304ceea3db29bd192af13e2ad524884fe75389ed7582` |
| verification | `dec27b7ecb80e08fa6e321ec5304e6b24aa3570ca244ae51a13d3cf3b7a98516` |
| tamper suite | `e9d958e9265111ea5b0254488b7690f715bbd3bc47927f79dd5a9823aa941c79` |
| closed-trace inventory root | `8916900b392d33352639da20418d17d5a723d96772b4a29e2d1d723cface60da` |
| open-loop inventory root | `d1daeb6cff102ef2775b0338be6152bfc69c50a2f4ea71f82705d6d53fdd0f62` |

The exact stage commands are listed in [`README.md`](./README.md) and frozen in
the final manifest where applicable. Formatting and static verification used:

```bash
.parcel/bin/ruff check research/20260829/model-a-stream-2/p1/*.py
~/.cache/parcel-0e/venv/bin/python -m compileall -q -f \
  research/20260829/model-a-stream-2/p1
```

## Execution history

Two stopped invocations are preserved, never overwritten, under `p1/aborts/`:

1. a completed old-manifest fit whose evaluator was stopped during `DIRECT`
   after exposing a frozen 2,100-versus-1,980 verifier inventory-count error;
2. a clean new-manifest fit whose evaluation exited after one teacher trace due
   to an undefined checkpoint-digest identifier introduced by verifier
   hardening.

Neither produced a result, aggregate, latency measurement, hypothesis, or
verdict. Both are explicitly non-evidentiary and documented in the two
execution amendments.

Before the final fit, a zero-optimizer integration run exercised all 1,980
closed paths, 42 open paths, 120,000 latency samples, independent verification,
and tamper 5/5. It deliberately zeroed one challenger and required the expected
`P1_REFUTED`; it passed and is retained under `p1/dryruns/`. Only the later clean
optimizer-step-zero run is the final P1 evidence.

## Limitations

- The environment has no obstacles, pedestrians, stairs, elevators, crosswalk
  semantics, localization failures, or robot dynamics.
- P1 tests only the local-control head. It does not learn task planning,
  interrupt policy, queue/resume decisions, narration, emotion, or dialogue.
- The teacher/product executive still supplies all transaction and receipt
  behavior during learned rollouts.
- The 12-episode controlling triple holdout has a wide Wilson interval.
- The test exposes behavioral-cloning covariate shift; it does not compare a
  recovery-data or online-intervention algorithm.
- Desktop latency does not establish Orin latency, end-to-end sensor latency,
  or realtime schedulability.
- Zero contacts in an open kinematic venue is an invariant, not a physical
  safety estimate.
