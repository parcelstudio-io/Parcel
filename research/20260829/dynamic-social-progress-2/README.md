# DSP-2 — robust staging, evasion, and fast safe resume

DSP-2 is a frozen, deterministic 2-D algorithmic study of social-navigation
stall recovery. The held-out result is negative: all four hypotheses were
refuted, and neither S2 nor S3 is eligible for carry-forward. This is useful
simulation evidence about failure modes, but it is not camera/LiDAR, ROS,
quadruped-dynamics, human-comfort, or physical-safety evidence.

The test population contains 29 unseen whole-episode families, five sensor
seeds per family, and four arms: 580 episodes total. S0 is the prior A3 semantic
lattice; S1 adds robust candidate MPC; S2 adds context staging; S3 adds the
explicit `BRAKE -> YIELD_ESCAPE / CLEAR_CONFIRM -> CREEP -> GO` liveness state.

## Frozen outcome

- Freeze SHA-256: `6b1a5785d62c61c2dc29b8ee86117674091a699451eb6335b31e8fd9e4819185`
- Normalized test digest: `8537c48a8a89fc32f0477e14565e67e252ae70491fa1b642042b8715c228da3c`
- S2: 25/145 contact episodes, all 25 actor-into-stationary; 128/145 task successes.
- S3: 25/145 contact episodes, all 25 actor-into-stationary; 124/145 task successes.
- H1, H2, H3, and H4: `REFUTED`.
- The two fresh-process digest files are byte-identical. Both full traces passed
  the independent verifier; action, actor-trajectory, and semantic-phase
  tampering were all rejected.

See [RESULTS.md](RESULTS.md) for denominators and [VERDICT.md](VERDICT.md) for
the carry-forward decision.

## Files

- `DESIGN.md` — preregistered question, arms, gates, and claim boundary.
- `DEVELOPMENT_DECISIONS.md` — pre-test development history and parameter choices.
- `fixtures.json` — frozen parameters, disjoint splits, families, and seeds.
- `episode_manifest.json` — explicit scenario/actor lineage and 784 all-split episode keys.
- `FROZEN_MANIFEST.json` — hashes of every source and fixture used by test.
- `experiment.py` — stdlib simulator, sensor mutations, policies, scorer, and CLI.
- `verify_results.py` — independent stdlib verifier; it never imports the policy implementation.
- `freeze_manifest.py` — one-way pre-test freeze helper.
- `evidence/pass-{1,2}.json` — full tick traces and aggregate results.
- `evidence/pass-{1,2}.digests.json` — normalized episode digests.
- `evidence/pass-{1,2}.verification.json` — verifier reports.
- `evidence/pass-{1,2}.{stdout,stderr}` — raw command and `/usr/bin/time -v` logs.

## Reproduce

From the repository root, validate a frozen evidence file:

```bash
python3 research/20260829/dynamic-social-progress-2/verify_results.py \
  research/20260829/dynamic-social-progress-2/evidence/pass-1.json \
  --frozen-manifest research/20260829/dynamic-social-progress-2/FROZEN_MANIFEST.json \
  --tamper-self-test
```

Re-running the test is guarded by the source freeze:

```bash
python3 research/20260829/dynamic-social-progress-2/experiment.py \
  --split test \
  --frozen-manifest research/20260829/dynamic-social-progress-2/FROZEN_MANIFEST.json \
  --output /tmp/dsp2-rerun.json \
  --digest-output /tmp/dsp2-rerun.digests.json
```

Any change to a frozen source or fixture makes that command fail. A revised
algorithm must use a new study/freeze rather than overwrite this evidence.

