# S-1 — calibration/TF completeness gate (narrowed MR-A)

**Card:** S-1 (`REVISED_BOARD.md`) · **Date:** 2026-08-14 · **Executor:** Sol-lane agent
**Why:** the verified P0 (`AU-H_FABLE_REVIEW.md` §1) — four optical streams
recorded, `camera_info` ABSENT, `/tf` ABSENT, `/tf_static` ABSENT. A bag like
that cannot feed camera SLAM or camera–LiDAR fusion and no post-session effort
can repair it.

**OWNS (as written):** `scripts/parcel_capture/rosbag2.py`, `sidecar.py`,
`preflight.py` (support reconciliation only), `src/parcel_robot/capture/channels.py`
(support-artifact class only), `tests/test_rosbag2_sidecar.py`,
`tests/test_capture_envelope.py` (support-class pins),
`tests/test_capture_preflight.py` (reconciliation cases), `DISK_LEDGER.md`,
this file. Deviations in §5.

---

## 0 · Headline

All six board items built and gated. The P0 check that AU-H executed, re-run
against the fixed plan:

```text
$ .parcel/bin/python -c "...plan_for_session('/data/parcel/session')..."
recorded topics: 31          # was 25
  camera_info  -> PRESENT x4: ['/camera/camera/color/camera_info',
                  '/camera/camera/depth/camera_info',
                  '/camera/camera/infra1/camera_info',
                  '/camera/camera/infra2/camera_info']
  /tf          -> PRESENT
  tf_static    -> PRESENT
```

Every board-named refusal is seeded, executed, and shown to redden when its
gate is reverted (§3). The CameraInfo-missing and profile-mismatch refusals
are additionally proven against **real MCAP bytes** written by the real
rosbag2 writer in the repo's ROS 2 Jazzy sandbox (§4), and two of those real
bags are embedded (zlib+base64, digest-checked) in the test suite so the
real-bytes witness survives this desk.

`ci_gate --tier commit`: **RESULT: PASS — every hard gate green.**
`5114 passed, 9 skipped, 36 deselected` (opening baseline was 5,071; the +43
are this card's tests). `tests/test_no_arm_pin.py`: 72 passed, re-run alone.
Nothing armed: no publisher, no ControlManager, no lease, no motion client, no
vendor SDK, `.parcel/` untouched; the sandbox ran under
`bwrap --ro-bind … --unshare-net --unshare-pid`, created no node and published
nothing.

## 1 · What was built, per board item

1. **Support-artifact class** (`channels.py`): `SupportArtifact` +
   `SupportArtifactKind` (CAMERA_INFO / TF / TF_STATIC / CALIBRATION_DIGEST),
   `SupportNeed` (REQUIRED / SNAPSHOT_SUBSTITUTABLE / RECORDED_OPPORTUNISTIC /
   UNAVAILABLE_DOCUMENTED), `SupportScope` (PER_CHANNEL / RIG_SPATIAL), an
   8-row `SUPPORT_ARTIFACTS` table pinned by `SUPPORT_ARTIFACT_ROWS`, and
   `camera_info_topic_for()` — the derivation rule that turns an image topic
   into its `camera_info` sibling and refuses non-image leaves. NOT channels:
   no rate, no presence prior, no sequence space; ids under a `support.`
   prefix that cannot collide with channel ids (import-time invariant). The
   payload matrix stays 28 channels / 25 rows — pinned. `CHANNEL_MATRIX.md`
   (20260813, immutable) is untouched; the class docstring carries the
   cross-reference. The Go2 front camera gets an UNAVAILABLE_DOCUMENTED
   CameraInfo row: no publisher exists, so the absence is a stated dataset
   property (a `does_not_prove` line whenever the stream is in a bag), never a
   silent gap and never a refusal that would push the operator to drop the
   stream.
2. **Recording plan + preflight** (`rosbag2.py`, `preflight.py`):
   `SUPPORT_TOPICS` (4 derived camera_info + `/tf` + `/tf_static`) joins
   `RECORDED_TOPICS` (25→31 with the two `/events/*` rows). `RecordedTopic`
   gained `support_id` with the payload-XOR-support invariant. Excluding a
   REQUIRED support topic while its payload stream stays on the plan is a
   refusal (`_refuse_orphaned_payload`) — the P0 can no longer be re-created
   by hand. `preflight.reconcile_support_topics[_or_raise]()` reconciles the
   observed `ros2 topic list -t` graph: REQUIRED (and snapshot-substitutable)
   absent → refusal; type mismatch → refusal regardless of need; `/tf` absent
   → finding; unparseable line → refusal (parse failure must never impersonate
   topic-missing). Unknown = absent throughout.
3. **Sidecar GO-RECORD gate** (`sidecar.py` + stdlib CDR decoders in
   `rosbag2.py`): `assess_go_record()` embeds a `capture.go_record` block in
   every rosbag2 sidecar and `finalize_rosbag2(require_go_record=True)` raises
   `GoRecordRefusedError` and **writes nothing** when the bag cannot certify
   (the recovery pass still always writes, with the REFUSED verdict recorded).
   Refusals: (a) active optical stream with no CameraInfo; profile mismatch —
   width/height read from the bag's own Image and CameraInfo CDR bytes, never
   declared; CameraInfo count not tracking the image count (rate profile);
   (b) optical frame with no parent in the static-transform set; a frame with
   two competing parents; two disagreeing declarations of one extrinsic;
   (c) `/tf_static` neither captured nor bound as a validated machine-readable
   snapshot (`STATIC_TF_SNAPSHOT_SCHEMA`, strict: provenance, ISO time,
   non-empty transforms, unit quaternions). Calibration digest = SHA-256 over
   the canonical decoded CameraInfo set; `verify_calibration_digest()`
   re-derives from bytes.
4. **Sync binding**: `build_rosbag2_sidecar(sync_fit=…)` embeds
   `sidecar_sync_block(fit)` (digest-carrying) as `capture.sync`;
   `verify_sync_fit_binding()` re-digests a supplied fit against the recorded
   `sync_fit_sha256`. A run passing `claims_recoverable_time=True` without a
   fit, or with a non-certifiable fit, cannot certify GO-RECORD. A PHYSICAL
   bag refuses a rehearsal-origin fit outright.
5. **VENDOR_VIDEO**: `record.py` now declares modules `()` +
   executable `("ffmpeg",)` for the RTP H.264 path, with an install hint that
   forbids the motion-SDK remedy. `VENDOR_UWB` still declares `unitree_sdk2py`
   (unchanged — pinned so the fix cannot widen).
6. **Operator ledger**: `DISK_LEDGER.md` generated from the `budget.py` model
   (91.87 MiB/s / 322.98 GiB/h / 5.383 GiB/min; 185.8 GiB reserve for the
   30-min core; 256 GiB free buys **41.4 min**, not the stale 45), with an
   explicit supersession notice over the 84.60-era figures in
   `PSK_STATUS.md` M9 / `PSL_STATUS.md`. Pinned by
   `tests/test_disk_ledger_doc.py` (byte-identity, re-derived headline check,
   and the stale reconstruction shown to fail that check).

## 2 · Measured claims

| # | Claim | Command | Output |
|---|---|---|---|
| M1 | The P0 is closed in the plan | `plan_for_session(...)` topic dump | `recorded topics: 31`; camera_info PRESENT ×4, `/tf` PRESENT, `/tf_static` PRESENT (§0) |
| M2 | Gate certifies a complete real bag and refuses the three seeded real bags | `assess_go_record` over 4 sandbox-written bags | `bag_complete: GO-RECORD` (calibration sha256 `fc658526…`); `bag_missing_ci: REFUSED` (NO CameraInfo); `bag_mismatch: REFUSED` (848x480 vs 1280x720); `bag_no_tf: REFUSED` (neither captured nor snapshotted) |
| M3 | Refused finalize writes nothing; snapshot substitutes; ambiguity and time-claim refuse | driver script over the same bags | `sidecar written? False`; no-tf + snapshot → `GO-RECORD`, `snapshot_sha256 2147efc1…`; competing parents → `GoRecordRefusedError`; `claims_recoverable_time` w/o fit → refused |
| M4 | One perturbed byte inside the first CameraInfo payload fails digest verification | flip byte at payload offset 80 (file offset 14831) of `bag_complete_0.mcap` | `verify_calibration_digest → False`, `calibration digest mismatch: … fc658526… vs 81289…` (first attempt hit "plumb_bob" in the ros2msg SCHEMA text at offset 9333 and correctly did NOT fail — the digest covers calibration payloads, not schema prose) |
| M5 | CDR model verified against real rclpy bytes before any decoder was written | sandbox `serialize_message` hex dumps | empty `CameraInfo` = 309 bytes, field-by-field arithmetic exact; `Image`/`TFMessage` walked from hex; padding confirmed uninitialised (decoders skip, never read, and fixtures pad with 0xCC) |
| M6 | Preflight reconciliation refuses the P0 graph | `reconcile_support_topics` on yesterday's topic set | 4 camera_info ABSENT, all refusals; `or_raise` → `PreflightError: … reconciliation refused (…)` |
| M7 | Suites | `.parcel/bin/python -m pytest tests/test_rosbag2_sidecar.py tests/test_capture_envelope.py tests/test_capture_preflight.py tests/test_disk_ledger_doc.py -q` etc. | rosbag2 79 passed · envelope 72 passed · preflight 248 passed · ledger 4 passed · `test_no_arm_pin.py` 72 passed · adjacent capture suites 694 passed |
| M8 | Full gate | `.parcel/bin/python scripts/ci_gate.py --tier commit` | **`RESULT: PASS — every hard gate green.`** ruff 7 = baseline 7, new 0; default-suite `5114 passed, 9 skipped, 36 deselected` in 223.1s (21:10Z) |
| M9 | 3.10 grammar for everything that must run on the Orin | `ast.parse(feature_version=(3,10))` on channels/rosbag2/sidecar/preflight/record | all five parse OK (dev interpreter 3.14) |
| M10 | Ledger figures | `build_budget(RECOMMENDED_PROFILE)` | 91.87 MiB/s · 322.98 GiB/h · 5.383 GiB/min · reserve 30 min = 185.8 GiB · 256 GiB → 41.4 min · verdict THIN ×1.14 |

## 3 · Seeded failures — every gate proven load-bearing

Runtime seeded refusals (each is a test executed in the suite): profile
mismatch 848×480/1280×720 (fixture **and** real bytes), CameraInfo missing
(fixture **and** real bytes), CameraInfo rate not tracking the stream, tf
neither captured nor snapshotted, malformed snapshot (blank source / empty
transforms / wrong schema / non-unit quaternion), two competing parents, two
disagreeing extrinsic declarations, optical frame with no parent, one-byte
calibration perturbation, tampered sync digest, rehearsal fit into a PHYSICAL
sidecar, payload/support id collision, unknown support id, orphaning
exclusion, foreign/truncated CDR, unparseable topic-list line, type mismatch,
payload row handed to the reconciler.

Revert harness (`scratchpad/s1_work/revert_harness.py`; `-B`,
`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged before/after, byte-identical
restore verified by sha256):

```text
=== M1-P0-support-topics-off-the-plan:        REDDENED  3 failed, 324 passed
=== M2-profile-mismatch-check-disabled:       REDDENED  2 failed (fixture + REAL-BYTES tests)
=== M3-camera-info-missing-tolerated:         REDDENED  2 failed (fixture + REAL-BYTES tests)
=== M4-tf-static-absence-demoted-to-finding:  REDDENED  1 failed
=== M5-time-claim-without-fit-tolerated:      REDDENED  1 failed
=== M6-preflight-required-absence-demoted:    REDDENED  3 failed
=== M7-ledger-hand-edit (84.60 seeded back):  REDDENED  2 failed
restored sha256 identical=True x4 · post-restore suite: exit=0, 331 passed
```

## 4 · The real-bytes path (Jazzy sandbox)

Recipe (PSM_STATUS.md, reproduced): rootfs
`.cache/external-evals/runtime/ros-jazzy-base-sandbox`, run as

```text
bwrap --ro-bind $SB / --bind $SCRATCH/s1_work /work --dev /dev --proc /proc \
      --tmpfs /tmp --unshare-net --unshare-pid /bin/bash -c \
      'source /opt/ros/jazzy/setup.bash && python3 /work/write_gate_bags.py /work/gate_bags'
```

`write_gate_bags.py` uses `rosbag2_py.SequentialWriter` →
`librosbag2_storage_mcap.so` → libmcap, with `rclpy.serialization` CDR — no
node, no publisher, no network. Four bags: 20 real 848×480 `Image` messages
each, plus matching 848×480 `CameraInfo` + `/tf_static` (complete) / no
CameraInfo (missing_ci) / 1280×720 CameraInfo (mismatch) / no `/tf_static`
(no_tf). Verdicts in M2–M4. Three bags are embedded in
`tests/test_rosbag2_sidecar.py` (`REAL_S1_BAGS`), sha256:
`bag_complete e15540c5…`, `bag_missing_ci 53cdb8fb…`, `bag_mismatch
e0e2a21b…` — bytes no module of ours produced, decoded by the stdlib CDR
reader in every suite run.

## 5 · OWNS deviations

1. **`scripts/parcel_capture/record.py`** (17 lines): not in the OWNS list but
   explicitly named by board item 5 (`record.py:1366 area`). Change is exactly
   the `VENDOR_VIDEO` dependency tables + one `INSTALL_HINTS` entry; diff
   reviewed to contain nothing else.
2. **`tests/test_disk_ledger_doc.py`** (new file): item 6 requires "a test
   that reddens if the committed ledger diverges from the generated output";
   it did not fit the three named test files, so it follows the
   `test_bandwidth_budget_doc.py` precedent as its own module and hosts the
   generator (`--emit`) so the ledger has exactly one renderer.
3. The item-5 pin (`test_the_rtp_video_path_needs_a_media_stack_never_the_motion_sdk`)
   lives in `tests/test_rosbag2_sidecar.py` although it asserts over
   `record.py` tables — kept there rather than editing `test_capture_sidecar.py`
   (not owned). `test_capture_sidecar.py`'s existing dependency-table pins
   still pass unmodified.
4. Not done, deliberately: no CLI verb for the preflight reconciliation (the
   function API is the deliverable; the run-sheet consumes `ros2 topic list
   -t` output which H-2 produces), and `build_sidecar` (the Parcel-format
   SECONDARY path) did not gain the GO-RECORD gate — certification belongs to
   the primary rosbag2 path the session records with.

## 6 · does_not_prove

1. **Nothing here proves the D455 driver actually publishes `camera_info`
   under the derived names** — `/camera/camera/<stream>/camera_info` is
   documentation-derived from documentation-derived image names. That is
   H-2's measurement on the Orin; until it runs, every support-topic name is
   marked UNVERIFIED and the preflight reconciliation is what turns a wrong
   name into a refusal instead of a silent gap.
2. **Nothing ran on Humble or on the Orin.** All real-bytes work is ROS 2
   Jazzy (rosbag2 0.26.11 / libmcap 1.3.1) in the sandbox. The recorder argv
   and storage config remain exactly as PS-M left them; the Orin's distro is
   still unread (H-1).
3. **The CDR decoder is proven for little-endian XCDR1 as Jazzy's rclpy emits
   it**, for exactly three message types. Big-endian CDR and any other type
   are refusals by design. A Humble-era serializer is assumed, not shown, to
   produce the same layout.
4. **The embedded bags are small and their images carry no pixel data** (the
   profile fields are real; `data` is empty). They prove framing, CDR layout
   and gate logic on real writer bytes — not behavior at session scale.
5. **"Rate profile" matching is a count-tracking judgement** (10% tolerance on
   CameraInfo count vs image count), not a measured driver property. If the
   real driver publishes CameraInfo latched-once, this gate will refuse and
   the tolerance decision must be revisited **with evidence, in the open** —
   never by quietly widening the constant.
6. **The transform leg checks that each active optical frame has exactly one
   unambiguous parent** in `/tf_static` + snapshot. It does not resolve a
   chain to `base_link`, does not validate the extrinsic VALUES (that is H-3's
   tape measure + the mount-geometry block, which stays evidence-with-
   uncertainty, never calibrated TF), and proves nothing about whether the
   recorder's QoS will actually capture a transient-local `/tf_static` on the
   day — that is exactly why the snapshot path and its refusal exist.
7. **The sync binding is exercised with the syncevents selftest fit**
   (SIMULATION origin, so it can only enter a SIMULATION-declared sidecar). No
   physical sync fit exists yet; item 4 proves the wiring and the digest
   binding, not any real cross-device time recovery.
8. **The front-camera "no CameraInfo publisher exists" row is documentation**
   (vendor stream carries JPEG/H.264 only). If the unit surprises us, the row
   is falsified at preflight like any other declaration.
9. **The ledger is a model, not a measurement**: the Orin's free space and its
   sustained recorder throughput are unmeasured (TONIGHT_CHECKLIST N3/N4). The
   ledger says so in its own §5.
10. **`ros2 topic list -t` output format**: the parser matches the form the
    Jazzy sandbox prints (`/topic [pkg/msg/Type]`); Humble's format is assumed
    identical and is refused loudly, not mis-parsed, if it is not.

---

## Opus verification

**Verifier:** Opus stand-in (Cursor Grok 4.5) · **Date:** 2026-08-14 · **Scope:**
REVISED_BOARD S-1 items 1–6 against uncommitted tree; adversarial probes from
`FABLE_REVIEW_BRIEF.md` that S-1 owns; no PE-D/SG-E/IS-F; no S-2 ownership.

### Board items 1–6 — verdict

| # | Board item | Verdict | Evidence |
|---|---|---|---|
| 1 | Support-artifact class beside the 28 payload channels | **PASS** | `SUPPORT_ARTIFACT_ROWS=8`, kinds CAMERA_INFO/TF/TF_STATIC/CALIBRATION_DIGEST; `CHANNEL_MATRIX_ROWS=25` / 28 channels unchanged; `camera_info_topic_for` refuses non-image leaves |
| 2 | Recording plan + preflight reconciliation refuses missing support | **PASS** | `plan_for_session` → **31** topics (4×`camera_info`, `/tf`, `/tf_static`); P0 graph (images only) → `reconcile_support_topics` refusals=5, `ok=False` |
| 3 | Sidecar GO-RECORD refuses missing/mismatched CameraInfo, absent/ambiguous TF | **PASS** | fixture + real-bytes tests green (see probe table) |
| 4 | Sync-event fit bound into real sidecar; time-claim without fit refuses | **PASS** | `test_a_bound_sync_fit_lands_in_the_sidecar_by_digest`, `test_a_run_claiming_recoverable_time_without_a_sync_fit_cannot_certify` |
| 5 | `VENDOR_VIDEO` = media stack, not motion SDK | **PASS** | `TRANSPORT_DEPENDENCIES[VENDOR_VIDEO]=()`, `TRANSPORT_EXECUTABLES[VENDOR_VIDEO]=('ffmpeg',)`; UWB still `unitree_sdk2py`; install hint forbids motion SDK / `.parcel` |
| 6 | Operator disk ledger from current budget, not 84.60-era | **PASS** | `DISK_LEDGER.md` quotes **91.87** MiB/s; `tests/test_disk_ledger_doc.py` 4/4 including stale reconstruction reddens |

### Adversarial probes executed

```text
.parcel/bin/python -m pytest \
  tests/test_rosbag2_sidecar.py tests/test_capture_envelope.py \
  tests/test_capture_preflight.py tests/test_disk_ledger_doc.py \
  tests/test_no_arm_pin.py -q
→ 475 passed

Named probes:
  test_a_bag_with_no_camera_info_cannot_finalize_go_record              PASS
  test_a_profile_mismatch_848x480_stream_1280x720_calibration_is_refused PASS
  test_two_competing_parents_for_one_frame_are_ambiguous_and_refused   PASS
  test_tf_static_neither_captured_nor_snapshotted_is_refused           PASS
  test_a_run_claiming_recoverable_time_without_a_sync_fit_cannot_certify PASS
  test_a_bound_sync_fit_lands_in_the_sidecar_by_digest                 PASS
  test_the_rtp_video_path_needs_a_media_stack_never_the_motion_sdk     PASS
  test_the_stale_84_60_era_ledger_fails_the_headline_check             PASS
  test_no_arm_pin.py                                                   74 passed
  ast.parse(..., feature_version=(3,10)) on channels/rosbag2/sidecar/
    preflight/record                                                   all OK
```

### Code fixes this verification pass

**None.** Uncommitted S-1 implementation already satisfies board items 1–6 and
the owned brief probes. No PE-D/SG-E/IS-F work; `STAGE0_COMMAND_ADDENDUM.md` /
S-2 argv renderer left to Sol stand-in.

### Gate

Focused S-1 suites: **green** (475 passed including `test_no_arm_pin` 74).

Full `ci_gate --tier commit` under this agent runtime: **default-suite RED** on
exactly four cases, all `PermissionError: [Errno 13]` on `os.kill` /
subprocess terminate (SIGKILL rehearsal child, truncated-bag sigkill helper,
Habitat py36 bridge close). Ruff and every other hard gate **PASS** (new ruff
0). This is an agent-sandbox signal restriction, **not** an S-1 logic
regression — the same four cases do not exercise CameraInfo/TF/sync/ledger
code paths.

**AU-F / operator:** re-run
`.parcel/bin/python scripts/ci_gate.py --tier commit` in a normal (non-agent)
shell before close; prior S-1 executor recorded PASS (`5114 passed…`) on this
tree's logic. Do not treat the agent-sandbox SIGKILL red as a product defect.

### does_not_prove (verification layer)

1. Still nothing measured on the Orin / Humble (H-1 unread, H-2 NOT RUN).
2. Fixture + Jazzy-sandbox real bytes ≠ physical D455/TF publishers.
3. This verification did not re-run the revert harness in `scratchpad/s1_work/`;
   it trusts the prior REDDENED table in §3 plus the live suite pins above.
4. This agent could not obtain an unsandboxed full-gate re-run; Fable must
   confirm commit-tier green outside the agent runtime.

---

## Addendum — 2026-08-14, FX-2 (fix tranche) · two GO-RECORD legs changed

**Appended by FX-2, which owns the two named legs of `sidecar.py` for this
tranche. Nothing above this line was edited.** Full evidence and the boundary
sweep: [FX2_STATUS.md](FX2_STATUS.md).

1. **The CameraInfo rate leg no longer has a 1.0-message floor.**
   `allowance = max(1.0, image_count * tolerance)` (sidecar.py:1838 as shipped)
   only ever applied below ten images — and there it certified deficits the
   tolerance exists to refuse. Reproduced with this suite's own fixture
   encoders: `images=2, camera_infos=1` (a **50%** deficit) reached
   `GO-RECORD certified=True` through `finalize_rosbag2(require_go_record=True)`,
   as did `3/2` (33%). The allowance is proportional now, so a deficit outside
   the 10% profile is outside it at every count; `40/39` still certifies, which
   is the control. A bag with fewer than
   `CAMERA_INFO_RATE_MIN_MESSAGES = 10` images additionally carries a finding
   saying this leg proved little at that length.

2. **The calibration digest now covers every DISTINCT decoded CameraInfo in the
   collected window, not the first payload only** — and the two docstrings that
   claimed "one perturbed byte in **any** CameraInfo payload" were corrected to
   the property the code actually has. Consequence for **M4 above**: the claim
   still holds and is now strictly stronger (a perturbed byte in the *last*
   CameraInfo also fails verification, which it did not before), but the
   recorded literal digest **`fc658526…` no longer reproduces** — the canonical
   form is now `{topic: [view, …]}`, and the same `bag_complete` fixture hashes
   to `6f9b8a01…`. No frozen manifest or sentinel pins a calibration digest, so
   nothing else moved. A calibration that changes mid-stream inside the window
   is bound into the digest and reported as a named finding
   (`… published N DIFFERENT calibrations … changed field(s): d`).
   What is still NOT covered is stated on `calibration_digest_of` itself: raw
   bytes that decode identically (covered instead by the per-file `sha256`
   leg), and a calibration that first changes past the collected window.
