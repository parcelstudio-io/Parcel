# HW-2 `go2-backend` — DESIGN

Card `scrum/20260822/task_40/README.md`. Design `../WAVE3_HW_DESIGN_FABLE.md`
§4 S1/S3/S4, §5.3, §5.4 (as corrected after HW-3), §6, §9 HW-2.

*267 lines, over the 150 target (grown by the correction pass: §(c) now carries the keyed-datum contract, the identity exemption and the live transport, §(h) the six standing risks): §(f) and §(g) each record a measured
obstruction the card did not anticipate (HW-6's five test assertions; no
recorded Stage-0 sample exists in the tree) and the shape chosen instead. Both
are decisions a verifier has to be able to re-derive, so they are written out.*

## (a) Purpose

`MujocoSocketBackend` is the only `SimulatorBackend`, and `observe()` is the
runtime's ONE source of pose, scan and obstacle facts (§4 S1). On the dog there
is no MuJoCo, so nothing starts. This card adds `Go2Backend`: an **eye**. It
composes the ODOM pose from `rt/sportmodestate` and the scan from HW-3's
Mid-360 band, refuses every motion method with the MOTION.md citation, and —
the part that is not a port — makes the scan carry PHYSICAL authority through a
TYPED source instead of a string, because `evidence_origin` stamps every
`SimObservation` sample SIMULATION by construction (HW-3 verdict F5).

## (b) Architecture fit — the seams, by module:symbol

| Seam | Who calls it on the product path |
|---|---|
| `backends/base.py:154 SimulatorBackend` (Protocol), `:124 SimObservation` | `runtime.py:6210,9551,10295 self.backend.observe()` |
| `backends/go2.py:Go2Backend` (NEW) | `web_panel.py:build_runtime` → `RobotRuntime(config, backend)` `runtime.py:1498` |
| `control/unitree_sport.py:20 UnitreeChannelContext`, `:73 UnitreeSportStateSource` | `Go2Backend`'s LIVE state adapter (lazy import, read-only, no lease) |
| `lidar/__init__.py:scan_from_frames / nearest_obstacle_from_scan / travel_bearing_rad / BandProfile` (HW-3) | `Go2Backend._scan()` — the seam snippet verbatim, including the `ranges_m == ()` branch |
| `core/input_health.py:CommissionedScanSource` (NEW) | `runtime.py:13799 _evaluate_dispatch_input_health`, `CARD HW-2` region |
| `bridge/timing.py` `CARD HW-2` region (NEW) | the sixth envelope term; record files `configs/envelope/*.yaml` |
| `unitree_control.py:_run_observe` `CARD HW-2` region | `python -m parcel_robot.unitree_control observe --duration` (HO-6) |

Composition with the safety core: nothing here touches `reactive_safety`,
`core/hard_stop`, the e-stop latch, `limits.py`, `lidar/` or HW-6's fence. The
backend PRODUCES the observation those consumers already read; the one new
authority path is additive and defaults to absent (see (c)).

## (c) Interfaces and contracts

**`backends/go2.py`**

* `Go2Backend(source, *, band_profile=None, clock=time.monotonic,
  session_epoch="")` — ONE source object carrying both channels (`latest()` and
  `drain()`), because they share a lifecycle and a declared origin. `name` is
  the SOURCE's (`go2_live` / `go2_stage0_replay`), and `SimObservation.backend`
  carries it as a LABEL only (§5.4 as corrected; the name is what the latch
  record publishes, so it must distinguish a recording from a robot).
  Authority comes from (d). `latest_scan_age_s(now=None)` exposes the sixth
  envelope term (f). `observe()` is serialized by a lock and **refuses with
  `Go2StateUnavailable` until the first `rt/sportmodestate` sample**: a
  defaulted `RobotPose()` is a pose at the origin under a fresh timestamp, and
  the join reads it as present and fresh.
* `scan_datum_for(observation)` — the `ScanDatum` built from the frames that
  produced THAT observation's `lidar_ranges`, identity-keyed over a bounded
  history (`GRADED_HISTORY = 8`). This is what makes (d)'s rule structural
  rather than hopeful.
* `observe() -> SimObservation`: pose `x,y,z,yaw` from `RobotMotionState.position`
  + `.yaw`; `lidar_ranges`/`angle_min`/`increment`/`range_min`/`range_max` from
  `BandScan`; `nearest_obstacle_m`/`_bearing_rad` from `nearest_obstacle_from_scan`
  with `travel_bearing_rad(vx, vy)` off the state's own body velocity.
  **Left at their defaults, deliberately:** `owner` (`OwnerTrack()`, `visible=False`
  — there is no owner sensor on the dog in this card; OT-2 reads `visible` and
  degrades), `lidar_obstacles`, `nearest_person_*`, `dynamic_agents`,
  `semantic_regions`, `semantic_objects`, `collision`, `emergency_stopped`
  (`backends/base.py:124-153`). Nothing is invented: an unfilled field is a
  field this card has no sensor for.
* **`ranges_m == ()` ⇒ `lidar_ranges=()`, `nearest_obstacle_m=None`** — HW-3's
  rule. An empty `BandScan` is never copied across; `scan_present` is then False
  and the join HOLDs.
* Motion: `move`, `pose`, `trajectory`, `move_owner`, `set_owner_visible` raise
  `Go2MotionRefused(NotImplementedError)` citing `docs/MOTION.md` and §5.5.
  **`stop`/`emergency_stop`/`clear_emergency_stop`/`expression` DO NOT RAISE** —
  `control/adapters.py:55,73,87,106` calls `stop()` on its startup, stop, e-stop
  and close paths, and an eye that throws out of the stop path would convert a
  safe no-op into an exception on the safety path. They are honest no-ops: this
  backend never commanded anything, so there is nothing to stop.
* Sources are duck-typed, not vendor-typed: `latest() -> RobotMotionState |
  None` and `drain() -> Sequence[LivoxPointFrame]`, plus a DECLARED
  `origin: EvidenceOrigin`. Two ship: `RecordedStage0Source` (the fixture,
  declares REPLAY **because it reads a file**) and `LiveGo2Sources`
  (`unitree_sdk2py` + `lidar.receive_frames`, **probed lazily inside the
  constructor** via `find_spec`, refused with `Go2SdkUnavailable` naming the
  motion venv; declares PHYSICAL **because it opens a subscriber and a
  socket**). The origin is never a config value — see (d). No vendor SDK import
  at module scope anywhere, and no `parcel_robot.core`/`parcel_robot.control`
  either: importing either would drag `brain`/`instructnav`/`navigation` into
  the armed commissioning tool's chain through `backends/__init__.py` and
  redden W0-B's guard (measured during implementation). `EvidenceOrigin` comes
  from the `parcel_robot.evidence_origin` leaf; `ScanDatum`,
  `CommissionedScanSource` and `RobotMotionState` are imported inside the
  functions that use them.

**The live transport.** `backend.livox: {host, port}` reaches
`LiveGo2Sources.open_livox_socket`, which binds a NON-BLOCKING UDP socket
(`port` defaults to HW-3's `HOST_POINT_DATA_PORT`); an injected socket that
reports a blocking timeout is refused at construction, and `drain()` is
additionally bounded by `drain_budget_s` (default 20 ms) of wall clock, because
`observe()` runs on the control loop and a quiet sensor must never stall a
tick. A corrupt datagram is counted (`refused_datagrams`) and skipped, never
raised: one bad datagram costs one datagram.

**Selection.** `web_panel.build_runtime` reads `store.section("backend")` and
hands it to `_build_backend`: absent (today's shipped config) ⇒
`MujocoSocketBackend(socket_path)`, byte-identical to HEAD. `kind: go2` ⇒
`Go2Backend`, over `RecordedStage0Source` when `fixture:` is set and over
`LiveGo2Sources` otherwise. Both the section and its nested `band:` are
validated at the READ SITE by name (`_BACKEND_KEYS` /
`band_profile_from_config`, TRUTH-1's pattern) so a typo cannot boot at a
silent default. Keys: `kind`, `fixture`, `band` (`z_lo_m`, `z_hi_m`, `bins`,
`angle_min_rad`, `range_min_m`, `range_max_m`, `min_populated_bins`,
`corridor_half_angle_rad`, `extrinsic`), `interface`, `domain_id`,
`session_epoch`, `max_frames_per_drain`.
**Inert until HW-5:** `configs/robot.yaml` is SHA-locked and omits `backend:`, so
an overlay cannot introduce it until `"backend"` is in
`config.OVERLAY_INTRODUCIBLE_KEYS` (ONE entry, whole subtree — ROAM-1/TRUTH-1
rule). That entry and `configs/profiles/go2_edu_plus.yaml` are HW-5's; stated
here in plain words because HW-3's F4 is the same shape.

**`core/input_health.py` `CARD HW-2`**

* `ScanDatum(captured_at, frame_id, sequence, payload_valid=True,
  populated_bins=0, points_seen=0)` — one scan sample, clocks preserved.
* `CommissionedScanSource(inner, *, origin, session_epoch="")` — the scan twin of
  `control/base.py:87-153 CommissionedStateSource`, same three rules: stamps the
  commissioned `EvidenceOrigin` on the datum; preserves the producer's clock and
  sequence; **LATCHES** on an ordering violation (duplicate/regressed sequence,
  receipt regression, epoch change) by emitting `payload_valid=False` from that
  point on, which the join reads as `payload_malformed` → `LATCHED_STOP` on every
  later tick — **except an identity (or field-equality) re-read of the datum it
  already accepted**, which is exempt exactly as `CommissionedStateSource`
  exempts it and for the same measured reason: the join is a POLL and the
  runtime re-reads the previous observation after any `observe()` exception and
  on every `clear_input_health_latch`. A DIFFERENT datum under a repeated
  sequence still latches. `origin=UNKNOWN`, a `str` origin, an unlabeled
  synthetic origin and a labeled PHYSICAL one are all refused at construction.
  `evidence(key) -> InputEvidence | None`; `None` means "nothing for that one",
  which leaves the caller's own stamp in place.

**`runtime.py:_evaluate_dispatch_input_health` `CARD HW-2`** — after the existing
`scan = scan_evidence_from_observation(observation)`:

```
source = getattr(self.backend, "scan_evidence_source", None)
if scan is not None and source is not None and declared_origin(source) is PHYSICAL:
    restamped = source.evidence(observation)
    if restamped is not None:
        scan = restamped
```

Two preconditions, both load-bearing: `scan is not None` means the source may
RE-STAMP the origin of a scan the observation carries and can never supply
presence it lacks, and `evidence(observation)` is KEYED so the join cannot
grade observation N against sweep N+1 (`observe()` also runs on HTTP handler
threads). Both are proved as properties, not asserted in a comment.

`declared_origin` (`control/base.py:56`, already imported at `runtime.py:101`) is a
TYPED lookup: the string `"physical"` is not a declaration. `MujocoSocketBackend`
has no such attribute, so every existing path is byte-identical — the flag-off
identity is structural, not a config read.

## (d) What this does and does not buy at the join

Under `requirements_requiring_physical_inputs()` today, a `Go2Backend`
observation latches `SCAN: sim_fixture_forbidden` (HW-3 F5, measured). With the
typed source that SCAN fault is gone **for a source that declares PHYSICAL** —
i.e. the live adapter. A **recorded fixture still latches**, because
`RecordedStage0Source` declares REPLAY by construction and REPLAY is a
synthetic origin: there is no config key that turns a file into a sensor, and
that refusal is the safety claim, not a gap. (`PREREGISTRATION.md` Amendment 1
splits row B1 on exactly this; both halves are measured.)
**POSE still stamps SIMULATION** —
`evidence_origin` is the only stamper for pose and this card does not migrate it
— so the verdict is still `LATCHED_STOP`, now for POSE alone, and
`CONTROLLER_FEEDBACK` is missing (there is no controller: the backend is an eye).
That is the correct fail-closed state for observe-only. The claim this card
makes is exactly per-FAULT, not per-verdict, and the pre-registration says so.
Handoff: a pose-evidence source of the same shape retires the POSE fault.

## (e) Hardware compatibility — class NEW (S1, S3-ODOM)

Venue-independent by construction: the band filter, the health join, the
refusals, the fixture replay — all pure Python over stdlib, no numpy/mujoco/
rclpy/socket at import (HW-3's property, inherited). Must-configure: the profile
(`backend.kind`, the extrinsic/band, the NIC and the Livox host/port) — HW-5.
UNKNOWN until the box: whether `rt/sportmodestate` publishes at all before the
Sport service is up (§4 S6 `VERIFY_IN_SESSION`), the Mid-360's real frame
cadence, and the extrinsic B11. The desktop proves everything on the recorded
fixture; the box proves the live adapter at Stage 0 (S19).
**The desktop cannot prove:** that `unitree_sdk2py`'s `SportModeState_` fields
are what the fixture says (no SDK here), the real scan age, or that the NIC
guard in `UnitreeChannelContext` passes on the Orin.

## (f) The sixth envelope term — and why it is NOT inside HW-6's shape

Design §6: scan age is not among HLD 8.8's five terms; HW-2 adds it as a sixth
with its own provenance. **Measured obstruction:** adding `scan_age_s` to
`ENVELOPE_TERMS_V1` breaks five assertions in `tests/test_hw6_stopping_envelope.py`
(a CLOSED, verified card's test file, outside this card's OWNS) — `_inputs()` at
:303 supplies five terms, so a sixth makes every HW-6 arithmetic row UNMEASURED,
and :683 pins the dev-box record's missing set at exactly three. The card
requires both "the record files gain the key" and "HW-6's tests still pass"; only
one shape satisfies both. So the term is a strictly ADDITIVE V2 layer in a
`CARD HW-2` region placed AFTER `# ---- END CARD HW-6 ----`, with zero bytes
changed inside HW-6's fence:

* `ENVELOPE_SCAN_AGE_TERM`, `ENVELOPE_DELAY_TERMS_V2`, `ENVELOPE_TERMS_V2`;
* `StoppingEnvelopeInputsV2(base, scan_age_s, scan_age_provenance)` with V1's
  `value/provenance_of/missing/fully_measured` surface;
* `derive_envelope_v2` — `required = v·(age + ipc + period + braking + scan_age)
  + jump`, the same `math.fsum`, the same epsilon-free `<=`;
* `load_stopping_envelope_record_v2` reads V1 plus a **top-level `scan_age:`
  block**. V1's loader reads only `schema`/`measurements`/`active_regime`/`host`
  and ignores unknown top-level keys, so both shipped records stay valid V1
  records and HW-6's row is untouched.

**Declared consequence:** `scripts/ci_gate.py:evaluate_stopping_envelope` (HW-7's
file in 3b, and HW-6's region) still prints the five-term row, so the sixth term
is derivable, recorded and tested but NOT yet gate-printed. Wiring it is one
call swap plus five assertions in HW-6's test file; it needs leave from the
dispatcher. Recorded as a deviation and a handoff, not hidden.

## (g) Fixture format (defined here — none exists in the tree)

Searched: `scrum/20260813/task_1/` (16 status docs + the run sheet) records the
Stage-0 PLAN and channel matrix; no recorded `SportModeState_` sample file exists
anywhere in the tree. So the format is defined here and the fixture is
**SYNTHESISED**, and every consumer says so. `tests/data/hw2_stage0_replay.jsonl`,
one JSON object per line (`clockmap.append_sample_jsonl`'s convention):

```
{"schema":"parcel.stage0_replay.v1","synthesised":true,"note":"..."}   # line 1
{"t_s":0.00,"channel":"rt/sportmodestate","sport_mode_state":{...}}
{"t_s":0.01,"channel":"livox/mid360/points","frame_hex":"…"}
```

`sport_mode_state` uses the field names of the tree's own decoder
(`scripts/parcel_capture/ingest/dds.py:417 decode_sport_mode_state`): `stamp_ns`,
`mode`, `error_code`, `position[3]`, `velocity[3]`, `yaw_speed`, `foot_force[4]`,
`imu_state.rpy_rad[3]`. `frame_hex` is a REAL Livox SDK2 datagram built by
HW-3's `build_point_frame`, so replay runs the real `parse_point_frame` decoder,
not a shortcut.

## (h) Test strategy and risks

Rows and thresholds are in `PREREGISTRATION.md` (written before measuring).
Headline rows go through the product path: `web_panel.build_runtime` on a real
base+overlay tree with `$PARCEL_PROFILE`, then `runtime._evaluate_dispatch_input_health`
— zero monkeypatch of `evidence_origin` / `scan_evidence_from_observation` /
`requirements_*`. Seeds (RED on an import-verified scratch copy) target: the
empty-scan branch, the typed-origin check, the ordering latch, the motion
refusal, the flag-off branch.
**Risks:** (1) the fixture is synthesised — a box-day datagram falsifies it in one
frame; (2) the sixth term is not gate-wired (f); (3) POSE authority is not in
this card (d); (4) `stop()` as a no-op is a judgment call, argued in (c) — and
a motion-capable successor must not inherit it; (5) **`safety.
require_physical_inputs` is not introducible**, so no profile can put a
`Go2Backend` under the physical table on the product path: today the dog would
run the permissive `requirements_allowing_sim_fixtures()` table and only the
backend's own motion refusal stands between it and translation. Integrator /
design-owner item (verifier F6), recorded in the status doc's handoffs.
(6) `max_frames_per_drain=32` against a Mid-360 at ~2,000 datagrams/s is a
PARTIAL sweep per tick, so the socket buffer backs up and the sweep the join
grades is bounded-stale by the buffer depth while `captured_at` is a host
receipt — queueing delay is invisible to the sixth term that is meant to
measure it (verifier N5; `source_time_ns` is carried unfused, and B11 decides
accumulate-over-window vs per-tick).
