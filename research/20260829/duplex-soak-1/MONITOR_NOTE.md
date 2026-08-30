# DSOAK-1 external monitor note

This is post-start instrumentation, added after an audit found that the soak
checkpoint overwrites its prior state and that `run_soak.py` serializes its
current file hash rather than an internally frozen start hash. It does not
alter `DESIGN.md`, `run_soak.py`, the running process, or any preregistered
gate.

`monitor_soak.py` starts more than two hours after DSOAK-1. It therefore cannot
attest the earlier interval. From its first JSONL row onward, it independently
records the Linux boot ID, process PID and kernel start ticks, a digest of the
exact command line, runner/design hashes, and the current checkpoint digest,
status, elapsed time, episode count, and embedded PID once per minute. The
monitor is read-only with respect to the soak result.

The final verifier must still treat DSOAK-1 as procedural durability evidence
only. This monitor cannot repair the independently refuted DMC-1 receipt and
narration oracles.
