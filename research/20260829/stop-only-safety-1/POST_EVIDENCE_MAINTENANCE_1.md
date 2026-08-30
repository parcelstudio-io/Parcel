# SOS-1 post-evidence maintenance 1

Written before the additive maintenance executions on 2026-08-30. The original
`manifest.prerun.json`, runs, verification, design, and verdict remain
unchanged historical evidence.

## Question

Do the exact SOS-1 source/fake-gateway gates still pass twice against a newly
frozen manifest of the current gateway, stop-only client, supervisor, service,
packaging, and test sources after later codebase maintenance?

## Procedure and decision rule

Use the existing unmodified `freeze.py`, `run.py`, and independent `verify.py`:

1. write a new content-addressed manifest without overwriting the original;
2. run the same 256-case credential/STOP, API, lifecycle, and composition gates
   twice with distinct labels;
3. independently recompute both results, source hashes, normalized equality,
   and tamper rejection; and
4. retain the exact outputs even if red.

`maintenance_verification.json.pass` must be true for the narrow current-source
maintenance verdict to pass. The run is additive maintenance, not a new
preregistered capability hypothesis.

## Evidence ceiling

Even a pass proves only current desktop source/fake-gateway conformance of a
software stop-only principal. It does not test a real remote/GPIO/audio STOP
input, independent physical E-stop, Unitree/Orin timing, firmware, balance,
braking distance, simultaneous hardware failure, or physical motion readiness.
