# AU-H — Fable review brief

- **Reviewer:** Fable
- **Scope:** every card attempted under `scrum/20260814/task_1`

**Authority:** review and veto only; the audit owns no product behavior.

## Questions the audit must answer

1. Does the physical recording plan now preserve profile-matched camera
   calibration and every required transform, or merely mention them in prose?
2. Is clock/sync evidence actually bound into the finalized sidecar?
3. Can a missing/mismatched `CameraInfo`, TF, calibration or profile still
   produce `GO-RECORD`?
4. Are T7–T10 executable, run-specific commands rather than free-text handoff?
5. Is the operator's disk ledger generated from the current 91.87 MiB/s model,
   with every stale 84.60 MiB/s-era fallback removed from the run-specific
   pack?
6. Does every recorder command come from the distro-aware generator after
   validation against installed help, with no Humble-incompatible flag copied
   from yesterday's sheets?
7. Did any capture change acquire a publisher, motion import, Unitree lease or
   command surface?
8. Does every hardware claim name real Orin evidence, and every absent run say
   `NOT RUN` rather than using fixture evidence?
9. Does the replay contract preserve raw fields/timing/provenance and reject
   oracle truth?
10. If SG-E changed product code, are epoch, TTL, sole-writer, stop dominance,
   disarmed restart and non-finite inputs attacked at the process boundary?
11. Did Isaac work remain a producer behind the same contract rather than
   becoming a simulator-specific product dependency?
12. Did every unfinished item move into durable backlog?
13. Did MR-C remain unexecuted today and get scheduled only as a separately
    staffed, seated/stationary session with zero stand, gait or Parcel motion?

## Required adversarial probes

- Remove or mismatch `CameraInfo`; finalization must refuse.
- Perturb one extrinsic/calibration byte; digest verification must fail.
- Disconnect one TF edge or create two competing parents; admission must
  refuse.
- Start recording after a transient-local `/tf_static` publication; either the
  snapshot is captured and verified or finalization must refuse.
- Remove the sync fit from a run claiming recoverable time; certification must
  fail.
- Substitute a wrong ROS topic name that produces zero messages; preflight
  must not call it present.
- Inject an oracle semantic ID/true pose into `SensorFrameV2`; construction or
  admission must refuse.
- Kill/freeze a fake gateway client after a nonzero command; local stop and
  disarmed restart must hold if SG-E claims that slice.
- Search all capture trees recursively for publisher/motion/lease surfaces and
  seed at least one mutant proving the pin can redden.
- Restore one stale disk-rate/fallback value in the run-specific operator pack;
  the generated-budget pin must redden.
- Inject `--disable-keyboard-controls` into a Humble run command or remove an
  installed-help flag; generation/validation must refuse before bytes are
  recorded.

## Close gate

Run:

```bash
.parcel/bin/python scripts/ci_gate.py --tier commit
```

Then issue one verdict per card:

- `CONFIRMED`
- `PARTIAL — <exact remaining gate>`
- `NOT RUN — <external blocker>`
- `REJECTED — <reproduced defect>`

The audit report must include commands/results, finding severity, refutation of
every blocking/major claim, diff-vs-OWNS attribution, and a non-empty
`does_not_prove` section. A green CI gate is necessary but does not substitute
for the review.
