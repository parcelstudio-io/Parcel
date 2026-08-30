# LHO-1 fresh-process supplement results

## Outcome

The additive verifier reports
`LHO1_MECHANISM_PASS_FRESH_PROCESS_SUPPLEMENTED`. It closes the original H5
process-provenance gap without changing the frozen simulator, schedules,
thresholds, A/B evidence, or H1–H4 verifier.

One launcher created C and D in sequential, non-overlapping child processes on
the same Linux boot. The child identities were distinct:

| Run | PID | PPID | `/proc` start ticks | Runtime recorded by runner | Output inode |
| --- | ---: | ---: | ---: | ---: | ---: |
| C | 910708 | 910706 | 61672590 | 12.671767 s | 117715594 |
| D | 910924 | 910706 | 61673896 | 12.711020 s | 117715651 |

The launcher observed each child's exact command, executable, working
directory, PID, PPID, and start ticks through `/proc`; it configured a
secret-free five-key child environment and checked its own exact lexical
project Python and venv prefix. It captured source/evidence bindings before and
after both runs and output metadata after each child exited. C ended before D
started. The retained outputs have different paths, inodes, byte hashes, and
runtime metadata.

## Independent gates

All eight supplement gates passed:

1. both children exited zero and left full retained outputs;
2. boot/PID/start-tick process identities were distinct;
3. execution was sequential and non-overlapping with exact frozen bindings;
4. retained output paths, inodes, sizes, mtimes, hashes, inventories, and
   preliminary verdicts matched their live records;
5. the original trace-first verifier independently recomputed and passed H1–H4
   for C and D;
6. C and D had identical normalized episode digests and aggregates;
7. A, B, C, and D all linked to the same normalized digest; and
8. ten coherently restamped mutations—duplicate identity, PID, start ticks,
   output inode, output substitution, altered argv, cwd, frozen-source hash,
   chronology, and output hash—were all rejected.

All four outputs bind to:

```text
f5807113f297d2e1a8aa4d4831c7e0c2ddeb19dd35d39bedea92995afcf31991
```

## Provenance

- supplement source-manifest self-digest:
  `b420c9ce0a422c65d36229887617cfc590ee21f716d0071a0f742293fa59eda8`
- evidence self-digest:
  `f65fce5175da995f51af163c221ee3a538ddb768434e7416cbeb22544f708a9e`
- verification self-digest:
  `a295e3b266d20830fe46ea4e61ea127b49dc9f605cac27f177e25f18071afc13`

Controlling files are [fresh-process-source-manifest.json](fresh-process-source-manifest.json),
[run_c.json](run_c.json), [run_d.json](run_d.json),
[fresh-process-evidence.json](fresh-process-evidence.json), and
[fresh-process-verification.json](fresh-process-verification.json).

## Evidence ceiling

This is local-host provenance, not remote attestation and not protection
against a malicious local evidence editor. It supports reproducibility of the
frozen deterministic scalar scheduling/kinematic mechanism only. It does not
establish a learned policy, perception, 2-D/3-D social navigation, quadruped
dynamics, physical braking, Orin timing, or Go2 readiness.

An independent read-only post-evidence audit rechecked all 5,940 retained
traces and reconstructed both child stdout receipts. The frozen verifier stores
but only format-checks those stdout hashes, and the collector's pre-existing-
path check is not an atomic singleton lock against two concurrently started
collectors. No concurrent collector or receipt mismatch was observed here;
future provenance versions should enforce both conditions directly.
