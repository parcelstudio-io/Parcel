# DMC-2 results

## Outcome

The seam-level gate passed and the architecture-level gate did not.

| seam | cases/run | valid controls | corruptions | independently correct |
|---|---:|---:|---:|---:|
| `TaskExecutive.report` | 2,048 | 256 | 1,792 | 2,048 / 2,048 |
| `apply_action_receipt` | 2,816 | 256 | 2,560 | 2,816 / 2,816 |
| `license_terminal_claim` | 3,584 | 256 | 3,328 | 3,584 / 3,584 |
| **total** | **8,448** | **768** | **7,680** | **8,448 / 8,448** |

Both runs had exactly those counts. Both normalized to trace digest
`e388cd60e4260919ffd2a6839625709d5cf451700dceebfb543d14c4dd48ebe5`
and chain root
`eb4b95e768859b45863cedd875da0b5e32d0b3b37f2ee7241250ef352ed760a8`.
The independent verifier reported no errors.

### H1 — executive result integrity: PASS

- 256 exact verified successes became `task_succeeded`.
- 256 missing-fact successes were consumed fail-closed as `task_failed`,
  never success.
- 1,280 wrong revision/step/attempt/state or post-terminal reports were
  ignored as stale, and 256 unknown-task results were ignored.
- Every ignored result left the task snapshot byte-equivalent under canonical
  serialization.

### H2 — authenticated receipt integrity: PASS

- 256 valid `started -> succeeded` sequences completed.
- All 2,560 corruptions were rejected: raw/wrong-channel (512), action
  mismatch, premature terminal, duplicate, sequence regression, timestamp
  regression, future, expired, and post-terminal (256 each).
- Every rejected receipt left the dialogue state byte-equivalent under
  canonical serialization.

### H3 — terminal narration-evidence integrity: PASS

- 256 exact fresh terminal claims were licensed and converted to verified
  dialogue claims.
- All 3,328 corruptions were refused, including the DMC-1 counterexample class
  that reuses an unrelated valid receipt for a fabricated action identity.
- Licensing never mutated dialogue state.

### H4 — determinism and independent verification: PASS

- Complete runs: two.
- Case inventory per run: 8,448 unique IDs, no missing/extra/duplicate rows.
- Normalized trace digests: identical.
- Hash chains, state hashes, source hashes, result hashes, raw aggregates, and
  exact case outcomes: independently recomputed.
- The verifier imports no Parcel product reducer and runner traces contain no
  expected label or self-verdict.

## Controlling limitation

This is not an end-to-end Model-B proof. The test uses a contract-valid
pending dialogue fixture to reach the receipt reducer; it does not exercise
`begin_admitted_action`. More importantly, the runtime currently does not
turn a `TaskExecutive.report` result into an authenticated receipt. The two
passing seams can therefore still be composed incorrectly or not composed at
all.

The current `ActionReceiptV1` also cannot bind:

- executive task ID, plan revision, step ID, or attempt;
- source process/epoch or restart identity;
- speech generation across barge-in;
- typed progress, blocked, replanned, suspended, or resumed events; or
- a stack/queue of multiple pending dialogue actions.

The architecture gate is consequently **NOT EVALUABLE / RED**. These results
do not overturn the physical **NO-GO**.

## Run metadata

- Frozen seed: `20260829`.
- Manifest SHA-256:
  `f0bccf7a67e03d1fc85bd553da45d8a37e5bc19a9cada96c7e224a83934923fe`.
- Run durations: 2.315898 s and 2.248793 s.
- Raw result SHA-256 files:
  - run 1: `575644767cc990398ba642ff6013e6edb5b01a01946ac5600be1f91bab75dcc4`
  - run 2: `a65ea195cde2359b72bf1fa34af5907a60235ad4c36b9088cd635a90e78770b6`
- Verification file SHA-256:
  `0f35f972179ce89403f3f93a20dc1052bdaddaaa410febca025f3f5e1f7b66af`.
