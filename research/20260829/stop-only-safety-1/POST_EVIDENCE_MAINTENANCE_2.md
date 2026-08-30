# SOS-1 post-evidence maintenance 2: READY/signal race repair

Written after maintenance-1 exposed the defect and after the minimal source
repair, but before any post-fix maintenance-2 execution on 2026-08-30. The
red parallel A/B evidence, green sequential C/D control, and invalid output
from the historical verifier remain immutable artifacts.

## Observed defect and repair

The supervisor emitted `READY=1` before installing the three STOP-bearing
signal handlers. Two overlapping maintenance-1 runners consistently reached
that window: SIGTERM used the default process disposition without a confirmed
gateway STOP, while the harness's immediate process-state sample also exposed
a shutdown-observation race for SIGINT. Sequential controls happened to pass.

The product repair installs SIGUSR1, SIGINT, and SIGTERM handlers before the
gateway connection loop and therefore before `READY=1`. A regression test
locks that order. This is a targeted repair validation, not an independent
discovery experiment.

## Frozen post-fix procedure

1. Freeze the post-fix source, tests, runner, this protocol, and the new strict
   verifier in a new content-addressed manifest.
2. Launch two complete SOS-1 runs concurrently. Both must pass H1-H5 and have
   identical normalized digests.
3. Launch two complete control runs sequentially. Both must pass H1-H5 and
   have identical normalized digests.
4. The strict verifier independently recomputes each gate and explicitly
   requires every gate to be true. It must require all four normalized results
   to match, verify current source hashes, reject a stale-digest tamper, and
   reject a maliciously recomputed digest whose gate claim disagrees with the
   underlying counters.
5. Retain all outputs irrespective of result. Do not replace any original or
   maintenance-1 artifact.

The post-fix maintenance verdict passes only if
`maintenance_2_strict_verification.json.pass` is true.

## Evidence ceiling

A pass establishes repeatable desktop source/fake-gateway behavior under this
specific concurrent startup stress. It does not establish hard real-time
behavior, physical E-stop independence, remote/GPIO/audio STOP wiring, Unitree
firmware response, braking distance, balance recovery, mounted compute timing,
or permission to energize actuators.
