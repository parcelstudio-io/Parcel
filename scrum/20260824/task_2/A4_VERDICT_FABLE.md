# A4 SPINE · acceptance VERDICT (Fable) · 2026-08-24

Verification: my guard run — A4 suite + r24 + nominal-stop + dynamic_layer +
e2 safety + pose_consumers + A3 + both DEC ratchets = **202 passed**; my own
audit re-run reproduces **K3 = 0** (was 9), **K4 = exists**, **K6 = 7**;
diff scope = the nine audited modules (+387/−101) plus the new pure leaves
(contracts/evidence_header.py, contracts/navigation_snapshot_v2.py,
contracts/observation_carrier.py, observation/, localization/installer.py,
deploy/orin/services/, tests/test_a4_spine.py). The four safety-adjacent
digest re-pins were read with my own eyes: each underlying change is exactly
a type-annotation swap (`SimObservation` → `ObservationCarrierV1`) or the
additive `apply_reactive_safety_from_snapshot` wrapper whose callee body is
untouched; the three unchanged `REACTIVE_SAFETY_PIN` digests corroborate.
r24 rosters/floors, callback rosters, markers (176→176): unchanged.

## Disposition: **ACCEPTED**

- The observation boundary exists: `NavigationSnapshotV2` + `EvidenceHeaderV1`
  with fail-closed refusals (missing/stale/mixed-epoch/synthetic-origin-in-
  physical/time-window, each with a control), a lossless simulator adapter
  (22/22 carrier fields), a replay adapter that refuses origin upgrades, and
  a physical skeleton with no truth fallback. A2's range-convention handoff
  is discharged structurally: `TraversabilityV1.range_convention` has NO
  default, and `footprint_radius_m` is legal only under
  `body_surface_to_obstacle_surface`.
- A3's handoff is discharged: the installer composes the localizer, latch
  and jump journal behind the pose seam, defaults unchanged, the latch
  joining health by `max()` — stricter only.
- The five Orin service skeletons are honest (boot-disarmed, per-service
  principals, `ExecStartPre=test -x` so nothing reports active for a
  missing binary).
- Full-suite state: 10,219 passed with 8 reds proven pre-existing in a
  read-only `git archive HEAD` tree — the correct attribution method.
- The DEC-0 ratchet catching a 118-line function mid-card (split before
  delivery) is the ratchet working as designed.

Named undone, correctly assigned: native V2 reads per module (Gate 4
cutover — today's entry points re-project through `carrier_view`), the wire
codec, `WholeMapMatcher` installation (needs a `RangeTemplateSource`), real
LIO behind the commissioned localizer (Gate 5), the operator re-arm product
route, the BARN adapter convention correction and the stale
`authority.CLEARANCE_CONVENTION` string (recorded follow-ups). Does not
prove: anything physical; the spine has never carried a real sensor.
