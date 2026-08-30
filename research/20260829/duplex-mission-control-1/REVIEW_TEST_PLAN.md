# DMC-1 post-run adversarial review test plan

Frozen after `results.json`; this is an explicitly post-hoc validity audit and
cannot change DMC-1's preregistration.

The independent reviewer identified that the experiment's receipt ledger and
narration oracle may accept claims that the design says must be rejected. The
probe will construct three counterexamples without changing DMC-1 sources:

1. submit a terminal receipt with the correct task/revision but the wrong
   `step_id` and `attempt`;
2. submit a non-terminal `started` receipt after an accepted terminal receipt;
3. validate a fabricated task/revision completion narration carrying an
   unrelated but previously trusted terminal receipt ID.

Expected secure behavior is rejection for all three. Any acceptance invalidates
the corresponding DMC-1 H3/H4 evidence, even if aggregate counters remain
unchanged. The probe records exact booleans and a SHA-256 digest. It is a unit
counterexample, not a frequency estimate.
