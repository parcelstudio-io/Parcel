# v4s — the matcher arm, and two harness facts (card VS-6 cells)

Read this before pre-registering any gate on `episodes/v4s/`.

180 cells across three axes (`LA` look-around, `BB` beyond-block, `PH` phantom),
60 each, seed 20260811. Additive: they carry v4's corrections verbatim, add none
of their own, and re-freeze nothing — v1–v4 are byte-untouched.
`v4s/manifest.json` is the authority for the episode list and its sha256.

This file lives BESIDE `v4s/` rather than inside it: every episode directory's
file list is pinned byte-for-byte against a fresh generation
(`tests/test_v4s_search_cells.py::test_checked_in_v4s_files_equal_a_fresh_generation`),
so a README inside `v4s/` would fail that gate.

## The "unfindable flag-off" property is MATCHER-RELATIVE — state the arm

Added by card **AF-2** (2026-08-11); provenance
`scrum/20260811/task_1/AUDIT_WAVE2_FABLE.md`, should-fix 5 ("v4s docs must pin
the matcher arm"), on the measurement `scrum/20260811/task_1/W2_WIRE2_STATUS.md`
§10 and §14.1b reports.

These cells were built so the target is beyond the opening scan's reach, and the
property is usually quoted as "flag-off SR is 0.000, so any success is a paired
flip". **That is true of the DEFAULT matcher arm only.**

| arm | LA flag-off SR | LA authority `false_arrival` |
|---|---|---|
| default (`SigLIP2Matcher` in its string/alias fallback — every ci_gate arm, every frozen row) | **0.000** | **10** |
| real weights (`PARCEL_SIGLIP2_ONNX=1`, `~/.cache/parcel/siglip2-b16`) | **0.100** (6/60) | **0** |

`BB` and `PH` are 0.000 flag-off in both arms.

Two consequences a card pre-registering a gate on these cells must respect:

1. **Name the matcher arm in the pre-registration.** A "flag-off SR is 0.000 so
   any success is a flip" premise silently changes meaning between the two arms,
   and on `LA` it is simply false with real weights.
2. **The 10 `LA` false arrivals are a matcher artefact, not a cell property.**
   With real cosine matching they are zero: the fallback admits cross-class
   commits (the measured case is a real lamppost accepted for a "tree" query —
   `nav-object_goal-PH-31-2dab201e`, W2_WIRE1_STATUS.md §7), which is also
   owner decision-queue item 4 ("SigLIP as default-on matcher").

Independently reproduced by the Wave-2 audit (AUDIT_WAVE2_FABLE.md, should-fix
5). Cost, measured: the real-encoder arms run ~90x slower per episode (≈6 CPU
minutes vs ≈4 seconds), and the flag-OFF arm is just as slow as any flag-on one
— the cost is the grounding ingress's own per-tick `match()` calls.

## Two harness facts every per-episode claim on these cells depends on

* **The scan RNG is shared across a runner process.**
  `HeadlessCityWorld._scan_rng` is seeded once per world construction and is
  never re-seeded by `reset()` (VS-4 §5), so inside one runner process an arm
  that shortens one episode shifts the scan RNG for every LATER episode.
  Aggregates are unaffected; **a per-episode number from a multi-episode run is
  not portable** and must be re-measured with one world per episode. AF-2
  measured 4 apparent per-episode differences on a 60-cell paired arm that all
  vanished under isolation.
* **~8 m planner reach vs ~12 m sensing.** The grid planner's local costmap
  reaches ~8 m while the frustum reaches 12 m (W2_EVAL_STATUS.md §3), so on
  these cells a target can be visible and unroutable at once. The measured
  bottleneck for the ranged-search axes is planner reach, not search policy
  (W2_WIRE2_STATUS.md §7).
