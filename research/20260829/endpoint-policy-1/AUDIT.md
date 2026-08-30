# Endpoint-policy independent audit

The pre-run audit found off-by-one timing, missing-case, invalid-percentile,
resampling, precision, parity, provenance, and post-selection risks. The runner
was rewritten before either retained execution.

The post-run read-only audit found no defect that invalidates the negative
sweep, but required these corrections before retention:

- separate pre-commit acknowledgement cancellation from a committed response
  later contradicted by resumed speech;
- call the grid declared and exploratory, not preregistered;
- describe conditional latency percentiles as survivor-biased diagnostics;
- rename the one-shot SmartTurn and incomplete-fixture-label diagnostics;
- record the installed `onnxruntime-gpu` distribution and provider; and
- strengthen baseline comparison across all 13 cases.

The auditor also drove all 52 default direct-frame cells through the actual
`MicrophoneVoiceLoop`, real Silero, and production `TurnEndpointer` and found
zero sample-clock differences from the duplicate state machine. That finding
was then reproduced twice by a source-pinned retained parity runner: 52/52
cells match at the exact 30 ms frame index. This validates the direct runner's
state-machine transcription; it does not repair the red PipeWire parity gate.

Supportable conclusion: no tested direct-replay setting meets both semantic
integrity and latency. A frozen human/AEC/room-noise holdout is required; no
production, provisional-response, or mount-readiness claim is supported.
