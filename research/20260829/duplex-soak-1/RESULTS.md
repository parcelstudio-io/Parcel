# DSOAK-1 results

## Final measurements

| Measurement | Result |
| --- | ---: |
| Monotonic duration | 43,380.014326820965 s (12.05000398 h) |
| Primary episodes | 66,434 |
| Frozen / adversarial | 33,218 / 33,216 |
| A1 mission success | 66,116/66,434 = 0.9952132944 |
| A1 adversarial success | 33,068/33,216 = 0.9955443160 |
| A1 frozen success | 33,048/33,218 = 0.9948822927 |
| A1 candidate failures | 318 |
| Deterministic replay samples | 664 |
| Recorded replay mismatches | 0 |
| Throughput | 5,513.193 episodes/hour |
| RSS samples | 720 |
| RSS start / final / maximum | 729.703 / 751.133 / 751.133 MiB |
| Fitted RSS slope after 10 min | 0.0008174 MiB/hour |

The candidate exercised 172,427 raw-unsafe proposals, rejected 96,772 stale
actions, 84,033 stale receipts, and 199,604 duplicate receipts, and recorded
13,257 wrong-route moves. Serialized admitted-unsafe, post-STOP motion,
premature-completion, and stale-action-acceptance counts are zero. Those zeroes
are frozen-program structural invariants, not independent physical-safety
measurements: `stale_action_acceptances` is unreachable in this simulator, and
post-STOP motion and unsafe admission are coupled to same-thread checks.

The frozen narration and terminal rows report 1.0 precision/coverage. They are
not truth evidence because the underlying DMC-1 receipt/narration oracle was
independently refuted after start; running the same oracle longer cannot repair
it.

## Model-selection result

| Arm | Mission success | Raw unsafe | Wrong-route moves |
| --- | ---: | ---: | ---: |
| L0 deterministic ledger | 66,433/66,434 = 0.9999849475 | 23,309 | 0 |
| A0 snapshot MLP | 66,188/66,434 = 0.9962970768 | 11,865 | 0 |
| A1 history GRU | 66,116/66,434 = 0.9952132944 | 172,427 | 13,257 |

The soak therefore does not promote A1. L0 remains the champion for this
procedural substrate; all learned heads remain shadow-only.

## Independent monitor and verifier

The external observer retained 582 rows. It began at 8,512.470 s and episode
12,518, 2.365 hours after the reported start, and covers 0.803769768 of final
elapsed time. Observer gaps were at most 60.009 s; positive checkpoint gaps
were 59.242–61.392 s; the longest stagnant run was two rows; observer/checkpoint
span drift was 5.133 s. The final row has no live process and accepts the
checkpoint's own terminal status, so the unsigned monitor partially corroborates
late-run activity but does not authenticate process continuity or the final-file
handoff.

The post-run aggregate-consistency verifier recomputed all 17 declared gate
predicates as true from the retained counters. The combined result-plus-monitor
acceptance is true under that verifier. The mutation campaign matched all 32
expected outcomes: 14 result cases and 18 monitor cases. It does not regenerate
episode specifications/outcomes or rule out coherent replacement of the result,
verifier, and monitor artifacts.

Important artifact limits:

- `results.json` is an atomic overwrite checkpoint, not an append-only ledger;
- the monitor has no hash chain or signature and misses the first 19.62% of
  elapsed time;
- successful replay digests were not retained, so the 664 successful replay
  comparisons cannot be recomputed from the final artifact alone;
- the strict verifiers are post-hoc additions, not part of the frozen runner;
- no independently timestamped environment/preregistration manifest exists,
  and the first Git commit containing the design/runner occurred after start;
- source-drift evidence is not sticky-latched, the monitor does not bind exact
  argv/executable identity, and the DMC dependency precondition is not bound to
  a known verification-artifact hash; and
- the frozen `promotion_pass` and narration-gate booleans are procedural legacy
  fields. [`INTERPRETATION.json`](INTERPRETATION.json) is the controlling
  machine-readable scope: no promotion, semantic truth, independent safety, or
  physical-readiness claim is evaluable.

## SHA-256 manifest

| File | SHA-256 |
| --- | --- |
| `DESIGN.md` | `369fe057ef0cc86b088ea5c7ff8443bfc6967b357e3c2f3998ef0a94e4f9fb1e` |
| `run_soak.py` | `a002983b29a7e222aba7d10c73f9cecface832526fea12f19396dba0581f1b2f` |
| `results.json` | `a81d2a43d793a59064fd24f4505f28398b724d449285a3babcaaad34fc852b95` |
| `external-monitor.jsonl` | `2fcd39e0cbd9020d4df02a40b2c4bbb10e06f619fbec5cc6ffdb30258235faee` |
| `monitor_soak.py` | `232fadbebc1c53a6825fbad7e5728741910f02869ce7d3e91726928d5976efd0` |
| `verify_results.py` | `9df186a6349257c1ce3ee2818cd6365c53a92bd682c8c32a0014725c2b1fd66a` |
| `verify_monitor.py` | `5497fa0cf1e7f72af095b0809a08138468c303342c3985da4352f6757b946a35` |
| `verify_final.py` | `4f832fb07a9c9b79cf5c124368534c454958011a48e06b98e25c4afb68e821a6` |
| `verify_verifiers.py` | `cee9da34972d67ff301d1fb95c51a471330cb385333b88a994564b5e60112b62` |
| `verification.json` | `34528ce7137df77a9b702e9a6b49ad37ca7651506bc4fdc95d5f0fd5e84e01ad` |
| `monitor-verification.json` | `2e9e01c81426c30d47fee8bd36da96defa83cab62d4a9e57201b06e56ff88b1a` |
| `final-verification.json` | `5856af266d4299baf3221deefcf3bf53d683c25c02deec8f9b0be83f8e7a983f` |
| `verifier-mutation.json` | `c34c20ee8313f5f16b4d4254fa400e8abacc99a3380841f3baa55f620c5dea4f` |

These hashes identify the retained bytes at final synthesis. They do not add
an external timestamp, signer, or complete chain of custody.
