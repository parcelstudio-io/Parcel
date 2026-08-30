# DMC-4 maintenance 1 invalid first invocation

Date: 2026-08-30 UTC  
Status: **NON-EVIDENTIARY; PRESERVED**

The first maintenance invocation wrote `maintenance_run_c.json` with the
expected normalized trace and chain roots, then the wrapper exited nonzero. The
frozen `run.py` returns `None` after successful completion; the new wrapper
incorrectly called `int(None)`, raising `TypeError` after the output write.

This invocation is inadmissible because the maintenance plan requires a
successful fresh process. Its output is retained and will not be reused as a
final C/D input. Before any replacement evidence, the wrapper will map `None`
to exit code zero, all maintenance wrappers will bind a superseding v2 source
manifest, and that manifest will be frozen. Final evidence will use distinct
`maintenance_run_e.json` and `maintenance_run_f.json` files.
