# DMC-1 post-run integrity note

The two stored `deterministic_payload_sha256` values differ even though the
semantic results are identical.  The experiment's first implementation
mistakenly included measured JSON-encoding latency fields in the object named
“deterministic payload.”  Wall-clock latency naturally differs between runs.

`verify_results.py` therefore removes only these explicitly named measured
latency fields and the runtime metadata before comparing the runs.  The
normalized semantic projections, every episode row, split/spec digest,
aggregate count/rate, hypothesis verdict, model artifact, and source digest are
identical.  The verifier records a normalized digest.  The original files and
their differing hashes are preserved rather than rewritten after the frozen
run.

