# Task 4 — P0-D: navigation & perception unblocks

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(read its standing rules first — concurrent writers, Edit-only, git read-only).

## Why

Three mechanical defects, each diagnosed to a line, each blocking a whole
class of measurement (audit §3, §6, §11 items 3, 4, 7):

* **MOVE1-D1 — compounding gate attenuation.** `runtime.py:8448`
  `velocity_smoother.force(post-gate)` resets the ramp to the already-scaled
  value, so the reactive gate rescales every tick (~2.2× slower than policy in
  the slow band; `scrum/20260821/task_20/MOVE1_STATUS.md` §5,
  `summary.json d6_compounded_share: 1.0`). Every slow-band speed number is
  wrong until fixed.
* **`ranking_margin ≡ 0.0`.** `perception_abstention.py:579-597` computes
  `(max − median) / (1.4826·MAD)` and returns 0 when MAD = 0; the map feeds a
  background of one non-zero score among zeros (`online_map.py:972-978`), so
  MAD is always 0 → `ABSTAIN_INDECISIVE_RANKING` for every query (measured
  0/6 and 0/18). Masked only by `abstention.enabled: false`.
* **`set_query` drops `person`.** A directive's
  `_set_camera_query_from_directive` (`runtime.py:557-575`) calls
  `ingress.set_query(phrase)`, which *replaces* the batch
  (`camera_channel/ingress.py:779-790`), defeating the person lease that
  `patrol/mission.py:43-48` requires.

## Deliverables

1. **MOVE1-D1 fix.** Make the smoother track the *pre-gate* policy value (or
   the gate-disposed value exactly once per tick) so a constant gate scale `s`
   yields `policy × s`, not `policy × sⁿ`. Read MOVE-1's §5 recommendation and
   `core/velocity_smoother.py:41-45` first; pick the smaller change. Test:
   seed RED with the old behaviour (n ticks at constant scale → geometric
   decay), green after. Do **not** change any gate threshold or the gate
   order.
2. **Ranking margin that can be non-zero.** Replace signal 4 with a
   *top-vs-second label-strength ratio among matching candidates* (the
   2026-08-21 retrieval bench found label-primary the only separable arm:
   corroborated entries 2.8–8.2 vs stray 0.12). Single matching candidate ⇒
   margin is strength-based, not 0. Keep the function signature and the
   `ABSTAIN_INDECISIVE_RANKING` reason code. Make the **signal set
   configurable** (`abstention.signals: [...]`, default = today's six so
   production is unchanged) and add a `configs/navigation/prototype.yaml`
   overlay (or profile keys in `default.yaml`, default-off) that enables
   abstention with `label_support + evidence_count + ranking_margin` and
   *provisional* thresholds — say "provisional, not derived on real frames" in
   the status doc. Test: the C-3 shadow corpus (`tests/test_c3_cutover.py`
   fixtures) must admit ≥ 1 place under the prototype signal set with
   `admission_flip` still 0 for absent queries; seed RED with the old formula.
3. **`set_query` unions.** `CameraIngress.set_query` keeps a pinned safety batch
   (`person` always, plus whatever `camera_ingress_queries` configured) and
   unions the directive noun; a directive can never remove `person`. Test:
   seed RED (old code drops `person`), green after; the lease test in
   `tests/test_c1_camera_stream.py` stays green.
4. **Runtime assets:** if you change `configs/navigation/default.yaml`, run
   `tools/sync_runtime_assets.py` and include the mirror; never hand-edit
   `MANIFEST.json`. Prefer the overlay file so `default.yaml` does not move.

## OWNS

`src/parcel_robot/runtime.py` **only** lines ~8396–8460 (`_dispatch_active`
smoother/gate) and ~557–575 (`_set_camera_query_from_directive`) — P0-A and
P0-B edit other regions concurrently: Edit-only, re-read first —
`src/parcel_robot/core/velocity_smoother.py`, `src/parcel_robot/perception_abstention.py`,
`src/parcel_robot/online_map/online_map.py`, `src/parcel_robot/navigation/semantic_map.py`
(only if the abstention call site needs the config plumbed),
`src/parcel_robot/camera_channel/ingress.py`, `configs/navigation/**`,
`src/parcel_robot/runtime_assets/**` (sync tool only), tests for those
modules, this folder.

## MUST NOT TOUCH

`navigation/reactive_safety.py` (semantics), `core/hard_stop.py`,
`core/arbiter.py`, `control/**`, `patrol/**` (MOVE-1 is live in the tree —
do not edit, do not kill pid ~910287, do not touch `scrum/20260821/task_20`),
`docs/**`, `backlog/**`, `README.md`, `configs/robot*.yaml`,
`realtime/**`, `evals/**` frozen rows (`nav_instruct` v4 baseline must not
move — your abstention change is config-off by default).

## Gates

* `.parcel/bin/python -m pytest -q tests/test_velocity_shaping.py tests/test_runtime.py tests/test_perception_abstention*.py tests/test_c2_online_map.py tests/test_c3_cutover.py tests/test_c1_camera_stream.py tests/test_move1_patrol.py -x` green.
* `.parcel/bin/ruff check` on OWNS, no new violations.
* Flag-off: with the default config, `perception_abstention` and the smoother
  produce byte-identical outputs on the existing fixtures (assert in a test or
  record a before/after hash in the status doc).

## Status doc

`P0D_STATUS.md`, per the board's register; include for each defect the seed-RED
output and the green output, and the provisional thresholds with the word
"provisional".
