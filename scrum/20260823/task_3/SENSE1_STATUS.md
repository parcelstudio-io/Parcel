# SENSE-1 — status (executor: Opus, 2026-08-23)

All five work items landed. Every defect was reproduced before it was fixed.

## What landed

**1. Per-source receipt clocks (X04).** `observe()` stamped pose and scan with
one `received_at` read at the top of the tick; both channels are BUFFERED, so a
DDS stream that had stopped and a socket that had gone quiet both looked
permanently fresh to the join's staleness branch. Now three clocks: the
assembly clock stays on `SimObservation.timestamp` (unchanged — `backends/
base.py` is not this card's OWNS, and the join reads `captured_at` off the
typed datums anyway), `PoseDatum.captured_at` is the state sample's own host
receipt (`RobotMotionState.received_at`), `ScanDatum.captured_at` is the host
clock read as the last datagram of the sweep came off the socket
(`LiveGo2Sources.last_frame_received_at`, mirrored on the replay source).
Measured: assembly 500.20 / pose 500.00 / scan 500.201 on one tick.

**2. Pose provenance seam (verdict blocking finding 4).** `CommissionedPoseSource`
is the scan seam's twin — same declared origin (live=PHYSICAL, recording=REPLAY,
by construction), same latch, same identity-re-read exemption. A live pose
ALLOWs under `requirements_requiring_physical_inputs()`; a replayed one latches
`sim_fixture_forbidden`; absence HOLDs.

**3. Resolved-profile validation (X06).** Reproduced: the merge inherits
`battery.simulated_percent: 90.0`, `control.controller: simulator`,
`control.unitree_sport.interface: enp3s0`, `wifi_cards.robot.interface: enp3s0`
— none written by the profile. A profile that names a rig AND sets
`safety.require_physical_inputs: true` must now declare a disposition for every
premise (`physical_resolution.no_value_on_this_rig` /
`.inherited_deliberately`) or the LOAD refuses, naming the key, the inherited
value and the fix. `ConfigStore.physical_value()` is the typed refusal at USE.
The merge is unchanged (`data["battery"]` is still the base's, bit for bit).

**4. Drain bound (A23).** `drain_budget_s` was checked only BETWEEN yielded
frames, so neither unbounded shape was bounded: an all-corrupt flood never
yields (a refusal costs a datagram, not a frame slot), and a blocking `recv`
never returns. `receive_frames` now takes `max_datagrams` and `expired` (both
off by default — every existing caller is byte-identical), and `drain()`
refuses to READ a socket that reports itself blocking. Measured: flood with a
frozen clock stops at 32 datagrams; flood with a moving clock stops at 0.02 s;
a socket that went blocking is never `recv`'d and costs only the scan, not the
pose. F4's "one corrupt datagram costs one datagram" is unchanged.

**5. Mount-day preflight.** One command reports the three channels with typed
absence (`AbsenceReason`): `mid360.udp` binds the real point-data port, listens
briefly and decodes anything that arrives through `parse_point_frame`;
`d455.path` reads `RealSenseIngest.dependency_report()/device_report()`;
`xvf3800.array` reads `/proc/asound/cards` and opens nothing. On this host:
mid360 PARTIAL/`no_message`, d455 PARTIAL/`device_node_missing`, xvf3800 READY
(the array really is plugged in).

## Marked regions

| file:line | what |
|---|---|
| `src/parcel_robot/core/input_health.py:487-684` | `PoseDatum` (:526), `PoseEvidenceSource` (:550), `CommissionedPoseSource` (:568) |
| `src/parcel_robot/backends/go2.py:856-900` | `_graded_pose` + `pose_evidence_source` (:885) |
| `src/parcel_robot/backends/go2.py:943,960` | `pose_datum_for`, `_scan_receipt` |
| `src/parcel_robot/backends/go2.py:333,553,691-800` | `last_frame_received_at` (both sources), `_socket_reports_blocking`, bounded `_read_until_empty`/`drain` |
| `src/parcel_robot/lidar/livox_udp.py:443-...` | `receive_frames(max_datagrams=, expired=)` |
| `src/parcel_robot/config.py:272-285` | `OVERLAY_INTRODUCIBLE_KEYS += "physical_resolution"` |
| `src/parcel_robot/config.py:377-709` | premise table (:460), `declares_physical_rig` (:561), `validate_physical_resolution` (:587), `require_physical_value` (:669) |
| `src/parcel_robot/config.py:759,773-783,967-980` | `ConfigStore.physical_resolution`, the load-time call, `physical_value()` |
| `scripts/parcel_capture/preflight.py:3446-3900` | `MountReadiness` (:3529), `MountChannelRow` (:3544), the three probes (:3603/:3736/:3797), `probe_mount_readiness` (:3859), `format_mount_readiness` (:3883) |
| `scripts/parcel_capture/preflight.py:4140,4186,4211,4253` | report field, `to_dict`, `run_preflight` kwarg + call |
| `configs/robot.go2_edu_plus.yaml:289-345` | `physical_resolution:` with a reason per key |

## Tests

`tests/test_sense1_mount_readiness.py` — 18 cases in 14 functions, one per
behavior, no suites of combinations:

`test_x04_pose_scan_and_assembly_carry_three_different_receipts`,
`test_x04_a_buffered_pose_goes_stale_instead_of_being_restamped_fresh`,
`test_a_live_pose_passes_the_physical_requirements_table`,
`test_a_replayed_pose_still_latches_under_the_physical_table`,
`test_a_pose_the_source_has_no_datum_for_holds_and_never_stubs`,
`test_the_pose_source_latches_on_an_ordering_fault_but_not_on_a_re_read[2]`,
`test_the_pose_source_refuses_an_undeclared_or_mislabelled_origin`,
`test_an_empty_sweep_is_still_no_scan_and_still_has_a_pose`,
`test_a23_an_all_corrupt_flood_is_bounded_by_the_datagram_budget`,
`test_a23_a_flood_that_costs_time_is_bounded_by_the_wall_budget`,
`test_a23_a_socket_that_went_blocking_is_never_read_and_never_costs_the_pose`,
`test_a23_a_corrupt_datagram_still_costs_exactly_one_datagram`,
`test_x06_an_unresolved_simulator_premise_refuses_at_load_by_name[3]`,
`test_x06_the_shipped_profile_resolves_every_premise_and_still_merges_transparently`,
`test_x06_a_disowned_key_refuses_at_use_and_a_measured_one_wins`,
`test_x06_a_declaration_about_a_key_the_loader_does_not_check_is_refused`,
`test_the_mid360_row_reports_the_socket_and_the_decoder_separately`,
`test_the_d455_row_separates_a_missing_wheel_from_a_missing_camera`,
`test_the_xvf3800_row_reads_the_kernels_card_list_and_opens_nothing`,
`test_one_preflight_run_reports_all_three_mount_day_channels`.

Green through the guard wrapper (`--label sense1`, `env -u TMPDIR`, never
`-n auto`, never `--tier`): 23 own · `test_hw2_go2_backend` +
`test_hw3_mid360_band` + `test_hw5_physical_profile` 230 · the 27 files that
import any module this card touched, 1453 · `capture_envelope`/`sidecar`/
`rosbag2_sidecar`/`w0b_commissioning`/`release_parity`(+wheel)/`stage0_addendum`/
`clockmap`/`import_order_no_cycle` 566. Ruff fingerprints: exactly 7, all
pre-existing, none added; no `noqa` added.

## Deviations (three, each forced by a shipped row this card may not move)

1. **The pose seam has no product read site yet.** `runtime.py:
   _evaluate_dispatch_input_health` is where the join would read
   `pose_evidence_source`, and `runtime.py` is MUST-NOT-TOUCH. So
   `test_hw2_go2_backend.py::test_b3_pose_authority_is_not_in_this_card` still
   measures pose latching through the runtime, and it stays green. What landed
   is the seam and its proof AT THE JOIN (a live pose ALLOWs, a replayed one
   latches, absence HOLDs); wiring it in is one line in the OBS-MIN slice the
   verdict assigns that card.
2. **The X06 refusal is at load for a NAMED PHYSICAL RIG, not for any config
   with the switch set.** Both halves of `declares_physical_rig` are forced:
   `tests/test_hw2_go2_backend.py:_config_tree` writes
   `require_physical_inputs: true` into a copy of the BASE (no profile, no
   inheritance question), and `test_hw5_physical_profile.py::
   test_a_misspelling_of_each_new_key_...` loads `{safety:
   {require_physical_inputs: true}}` alone and asserts it loads. Requiring
   `venue` as well separates a rig profile from a fragment. Related: an
   explicitly SET value supersedes a stale `no_value_on_this_rig` declaration,
   because HW-5's pinned launcher row fills `backend.interface` in and nothing
   else — a loader that refused that would be refusing the fix.
3. **One line outside OWNS:** `tests/test_prototype_profile.py:398-418` — the
   `OVERLAY_INTRODUCIBLE_KEYS` roster census, which every card that adds a
   family has had to extend (VENUE-1, TRUTH-1, HW-4, HW-5 each did). Added in
   their shape, with the read-site validator named. This is the verdict's own
   oracle-porting rule; flagging it rather than assuming it.

## Notes for the integrator

* `CODEBASE_INDEX.md` is stale (this card adds
  `tests/test_sense1_mount_readiness.py`). Not regenerated here — it is a
  shared generated file and other cards are in flight; run
  `.parcel/bin/python tools/codebase_index.py` at close.
* `PreflightReport.to_dict()` gains `"mount_readiness"`. Additive under the
  unchanged `parcel.capture.preflight.v1` name; no observation key and no 29th
  channel probe, so `attest` and the matrix enumeration are untouched.
* The preflight default path BINDS UDP 56301 for ~50 ms per run. Every test
  here injects the opener; nothing binds in the suite.
