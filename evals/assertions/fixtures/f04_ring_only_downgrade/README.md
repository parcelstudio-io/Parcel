# f04 — a window is not a stream

The same provenance shapes as f01, delivered only as `session_slices.json` —
the 100-slot ring. Every finding here must come back REVIEW rather than
VERDICT, because an absent tool event in a ring-sourced session is as likely
to be an eviction as a defect. This is the productionized form of the bench's
own hardest lesson: seventeen of its `live_run_1` provenance findings were
ring evictions, and a gate that scored them as defects would have been wrong
seventeen times in a row with total confidence.
