# LHO-1 post-audit fresh-process supplement plan

Date frozen: 2026-08-30 UTC  
Status: **FROZEN BEFORE SUPPLEMENT IMPLEMENTATION OR EVIDENCE**  
Reason: an independent post-evidence audit found that the original H5 verifier
checks normalized equality but does not prove that `run_a.json` and
`run_b.json` were created by distinct fresh processes. Supplying the same file
twice can satisfy its H5 clause.

This supplement does not edit `DESIGN.md`, its three pre-evidence amendments,
the frozen manifest/source manifest, runner, verifier, or retained A/B evidence.
It narrows an integrity gap; it does not tune the mechanism or thresholds after
seeing results. The original `verification.json` remains an honest record of the
weaker check.

## Procedure

A new standard-library launcher will start **two sequential, non-overlapping
child processes** using the frozen project Python and frozen `run.py`. Each
child writes a different new output (`run_c.json`, `run_d.json`). While the
child is alive, the launcher records:

- Linux boot ID;
- launcher PID;
- child PID and `/proc/<pid>/stat` start ticks;
- exact `/proc/<pid>/cmdline` digest and normalized command arguments;
- launcher monotonic and UTC start/end times;
- runner, design, frozen manifest, frozen source-manifest, and Python executable
  digests;
- child exit code;
- output path, inode, size, mtime-ns, SHA-256, normalized trace digest, inventory,
  and preliminary verdict.

The second child may start only after the first exits successfully. The
supplement evidence and its scripts are bound to a separate frozen source
manifest created before either child is launched.

## Independent verifier and gates

The supplement verifier may import only the original standard-library LHO
verifier, not the simulator or policy. It must independently require:

1. both child exit codes are zero and both full output files exist;
2. process identities `(boot_id, pid, proc_start_ticks)` are distinct;
3. the launches are sequential and non-overlapping, use the expected Python,
   runner, frozen manifest/source manifest, and differ only in output path;
4. output paths and inodes are distinct and each retained file matches the hash,
   size, mtime, digest, inventory, and preliminary verdict observed by the
   launcher;
5. the original independent per-run H1–H4/raw-trace verifier passes both C and D;
6. C and D have identical normalized episode digests and aggregates;
7. the normalized digest equals the retained A/B digest, providing a four-run
   replication link; and
8. deliberate mutations of process identity, output identity, chronology, and
   output hash are all rejected.

The supplement verdict is
`LHO1_MECHANISM_PASS_FRESH_PROCESS_SUPPLEMENTED` only if all eight clauses
pass. Otherwise it is `LHO1_FRESH_PROCESS_EVIDENCE_REFUTED` and the original H5
claim remains unsupported.

## Evidence ceiling

Linux process provenance is local host evidence, not remote attestation. Even a
pass supports only distinct-process reproducibility of the authored scalar
scheduling mechanism. It establishes no learned policy, 2-D/3-D navigation,
perception, social competence, quadruped dynamics, physical braking, Orin
timing, or Go2 readiness.
