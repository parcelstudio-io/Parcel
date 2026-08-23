# HW-2 `go2-backend` — PREREGISTRATION

Written BEFORE any row is measured. Rows are measured exactly as written; a
miss is a miss. Every pytest runs through
`~/.cache/parcel-guard/pytest_guard.sh --label hw2 .parcel/bin/python -m pytest …`
with `env -u TMPDIR`, never `-n auto`, never `ci_gate.py --tier`, never in the
background. This card needs NO simulator: the fixture is recorded.

Shorthand used below:
`GUARD = env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label hw2 .parcel/bin/python -m pytest -q`
`T = tests/test_hw2_go2_backend.py`

## A — the backend (`backends/go2.py`)

| Row | Claim | Command | Threshold |
|---|---|---|---|
| A1 | `observe()` from the recorded fixture yields a `SimObservation` whose `scan_present` is TRUE, through the REAL `navigation.reactive_safety.scan_present` — no local copy of the predicate | `GUARD T -k scan_present_from_the_recorded_fixture` | 1 passed; `len(lidar_ranges) == 360`; `points_seen > 0` |
| A2 | `nearest_obstacle_m` / `_bearing_rad` come from HW-3's `nearest_obstacle_from_scan` with the state's own travel bearing, and `apply_reactive_safety` reads them | `GUARD T -k reactive_safety_reads_the_band` | the real `apply_reactive_safety(0.25 m/s)` returns `stopped` for a fixture wall inside `obstacle_stop_m` and `clear` for the open frame |
| A3 | An empty band (`points_seen == 0`, HW-3's `()`) ⇒ `lidar_ranges=()`, `nearest_obstacle_m=None`, `scan_present` FALSE | `GUARD T -k empty_band_is_published_as_no_scan` | `lidar_ranges == ()`; `scan_present(obs) is False`; `apply_reactive_safety` → `stopped` |
| A4 | Every motion method refuses with the MOTION.md citation | `GUARD T -k motion_is_refused` | `move`, `pose`, `trajectory`, `move_owner`, `set_owner_visible` each raise `Go2MotionRefused`, `isinstance(..., NotImplementedError)`, message contains `MOTION.md` |
| A5 | `stop` / `emergency_stop` / `clear_emergency_stop` / `expression` do NOT raise (the `control/adapters.py` safety path) | `GUARD T -k the_stop_path_never_raises` | four calls return `None`; a real `SimulatorBackendController(Go2Backend).stop("x")` and `.emergency_stop()` complete |
| A6 | No vendor SDK at module scope: importing `parcel_robot.backends.go2` leaves `unitree_sdk2py`, `mujoco`, `numpy`, `rclpy`, `socket` out of a fresh `sys.modules` | `GUARD T -k no_vendor_import_at_module_scope` (subprocess with `-I`) | all five absent |
| A7 | The live adapter refuses with a typed error naming the motion venv when the SDK is absent | `GUARD T -k the_live_adapter_names_the_venv` | `Go2SdkUnavailable` raised; message contains `unitree_sdk2py` and the venv sentence |
| A8 | `Go2Backend` satisfies the `SimulatorBackend` Protocol structurally | `GUARD T -k satisfies_the_protocol` | every method name on `backends/base.py:SimulatorBackend` is callable on the instance |

## B — physical scan authority (`core/input_health.py` + `runtime.py`)

| Row | Claim | Command | Threshold |
|---|---|---|---|
| B1 | Through a REAL runtime built by `web_panel.build_runtime` on a base+overlay tree with `backend.kind: go2` and `safety.require_physical_inputs: true`, `runtime._evaluate_dispatch_input_health(obs, now=…)` reports **NO** `scan:sim_fixture_forbidden` fault. ZERO monkeypatch of `evidence_origin`, `scan_evidence_from_observation`, `requirements_*` or the source. | `GUARD T -k the_join_no_longer_latches_the_scan` | no fault with `required_input is RequiredInput.SCAN and reason == "sim_fixture_forbidden"` |
| B2 | The same runtime shape with the SIM backend DOES latch the scan (the control) | `GUARD T -k a_sim_scan_still_latches` | a `scan:sim_fixture_forbidden` fault present, `action is LATCHED_STOP` |
| B3 | The POSE fault is unchanged and stated: the Go2 verdict is still `LATCHED_STOP`, for POSE, and `CONTROLLER_FEEDBACK` is missing | `GUARD T -k pose_authority_is_not_in_this_card` | verdict `LATCHED_STOP`; faults include `pose:sim_fixture_forbidden`; includes `controller_feedback:missing` |
| B4 | No scan (empty band) through the same real runtime ⇒ SCAN missing ⇒ recoverable HOLD, never ALLOW | `GUARD T -k an_empty_scan_holds_at_the_join` | a `scan:missing` fault whose action is `HOLD`; `translation_allowed` False |
| B5 | `CommissionedScanSource` refuses `EvidenceOrigin.UNKNOWN` and a non-`EvidenceOrigin` origin at construction | `GUARD T -k the_scan_source_refuses_an_undeclared_origin` | `ValueError` / `TypeError` |
| B6 | The ordering latch: a duplicate or regressed sequence, a receipt regression, or an epoch change makes `payload_valid` False from that tick on, on EVERY later clean tick | `GUARD T -k the_scan_source_latches_on_an_ordering_fault` | four sub-cases; after the fault, three clean data still yield `payload_valid False` → join `LATCHED_STOP` |
| B7 | A source declaring a STRING `"physical"` (not the enum) is NOT believed by the runtime read | `GUARD T -k a_string_is_not_a_declaration` | the join falls back to the observation stamp → `scan:sim_fixture_forbidden` present |
| B8 | Flag-off identity: with NO `backend` key the runtime built by `build_runtime` is a `MujocoSocketBackend` and its join verdict + fault tuple are byte-identical to the pre-card path | `GUARD T -k flag_off_identity` | `type(runtime.backend) is MujocoSocketBackend`; `getattr(backend, "scan_evidence_source", None) is None`; verdict and fault list equal to the same call with the region's effect removed |

## C — selection at `web_panel.py:~728`

| Row | Claim | Command | Threshold |
|---|---|---|---|
| C1 | `backend.kind: go2` in the resolved config ⇒ `build_runtime` returns a runtime whose `.backend` is a `Go2Backend` | `GUARD T -k build_runtime_selects_the_go2_backend` | `type(runtime.backend).__name__ == "Go2Backend"` |
| C2 | Absent section ⇒ `MujocoSocketBackend`, and no socket is opened at construction | `GUARD T -k build_runtime_default_is_unchanged` | as B8 |
| C3 | An unknown key inside `backend:` is refused BY NAME at the read site (TRUTH-1's rule) | `GUARD T -k an_unknown_backend_key_is_refused` | `ValueError` naming the key |
| C4 | An unknown `kind` is refused and names the kinds it accepts | `GUARD T -k an_unknown_backend_kind_is_refused` | `ValueError` containing `mujoco` and `go2` |
| C5 | The overlay path works when the base defines the section (proves the merge, not only the read) | `GUARD T -k the_overlay_can_select_the_backend` | `$PARCEL_PROFILE` overlay flips `mujoco` → `go2` |

## D — `observe --duration` (HO-6)

| Row | Claim | Command | Threshold |
|---|---|---|---|
| D1 | `observe --duration` is absent by default and the existing `--min-samples/--timeout` behaviour is unchanged | `GUARD T -k observe_without_duration_is_unchanged` | `args.duration is None`; one window; stdout JSON == today's `evidence.as_dict()` |
| D2 | `--duration D` runs consecutive windows until D s of wall clock and prints an aggregate naming the worst interval and the union of modes | `GUARD T -k observe_duration_runs_until_the_window_closes` | ≥ 2 windows for D = 4× the per-window cost with a fake clock; aggregate `windows ≥ 2`; `max_interval_s` == max over windows |
| D3 | A refusal in any window ends the command rc=1, as today | `GUARD T -k observe_duration_propagates_a_refusal` | rc == 1 |
| D4 | `--duration` with a non-positive value is refused by the parser | `GUARD T -k observe_duration_must_be_positive` | `SystemExit` |

## E — the sixth envelope term

| Row | Claim | Command | Threshold |
|---|---|---|---|
| E1 | `derive_envelope_v2` = `v·(age + ipc + period + braking + scan_age) + jump`, term by term | `GUARD T -k the_sixth_term_is_in_the_sum` | contributions equal the six expected products to 1e-12; `required_m` equals their `fsum` |
| E2 | An UNMEASURED `scan_age_s` poisons the verdict and names itself | `GUARD T -k an_unmeasured_scan_age_poisons_the_verdict` | `state == "UNMEASURED"`, `missing == ("scan_age_s",)`, `required_m is None` |
| E3 | Both shipped records carry `scan_age:` as UNMEASURED with a provenance that says what will measure it | `GUARD T -k the_shipped_records_carry_the_sixth_term` | both files load as V2; `scan_age_s is UNMEASURED`; provenance > 40 chars |
| E4 | HW-6's V1 shape is untouched: both records still load as V1 and `ENVELOPE_TERMS_V1` is still the five | `GUARD T -k hw6_v1_is_untouched` | `len(ENVELOPE_TERMS_V1) == 5`; V1 load of both files succeeds; dev-box `missing()` still the same three |
| E5 | HW-6's own suite still passes, unmodified | `GUARD tests/test_hw6_stopping_envelope.py` | same count as before this card (baseline recorded first) |
| E6 | The RC-4 rows are byte-identical to HEAD | `GUARD T -k the_rc4_tables_are_byte_identical` | sha256 of `render_latency_derivation_markdown()` + `render_commissioning_h2_markdown()` equal to the values HW-6's own test pins |

## F — hygiene

| Row | Claim | Command | Threshold |
|---|---|---|---|
| F1 | Ruff: exactly the 7 baseline fingerprints tree-wide from THIS card's files; no `noqa` added | `.parcel/bin/ruff check <OWNS>` and `.parcel/bin/ruff format --check <OWNS>` | 0 findings in my files; `grep -c noqa` on my files == 0 |
| F2 | Neighbours green: the suites that read the touched product files | `GUARD tests/test_hw6_stopping_envelope.py tests/test_w0a_physical_provenance.py tests/test_control.py tests/test_web_panel.py tests/test_truth1_texts.py tests/test_hw3_mid360_band.py` | all passed; counts recorded |
| F3 | `git diff --stat -- <OWNS>` shows edits ONLY inside `CARD HW-2` markers in every shared file | manual + `git diff` | every hunk in `runtime.py`, `web_panel.py`, `core/input_health.py`, `unitree_control.py`, `bridge/timing.py`, `backends/__init__.py` lies inside a `CARD HW-2` fence |
| F4 | The product imports on CPython 3.10 (HW-1's venv), with no numpy/mujoco/socket/rclpy pulled in by `backends.go2` | `~/.cache/parcel-hw1/py310/bin/python -c …` | import succeeds; the five modules absent |

## Seeds (each RED on a byte-identical scratch copy, never the working tree)

Scratch: `rsync -a --exclude .cache --exclude .parcel --exclude .git` of
`src/ scripts/ tools/ tests/ configs/ prompts/`; run with
`PYTHONPATH=<scratch>:<scratch>/src`; `parcel_robot.__file__` verified INSIDE the
scratch from inside pytest; restore by sha256; `__pycache__` purged.

| Seed | Mutation | Must redden |
|---|---|---|
| S1 | `Go2Backend` copies the empty `BandScan` across (`lidar_ranges=scan.ranges_m` unconditionally) | A3, B4 |
| S2 | The runtime region drops the `declared_origin(...) is PHYSICAL` test and believes any source | B7 |
| S3 | `CommissionedScanSource` stops latching (returns the clean datum after an ordering fault) | B6 |
| S4 | `Go2Backend.move` becomes a no-op instead of raising | A4 |
| S5 | `build_runtime` selects `Go2Backend` whenever the section resolves (ignores `kind`) | B8, C2 |
| S6 | `derive_envelope_v2` drops the `scan_age` contribution | E1 |
| S7 | The `_check_backend_section` call is deleted from `build_runtime` | C3 |

## Owner-gated / not measurable here

* The live `Go2Backend` against a real `rt/sportmodestate` and a real Mid-360 —
  Stage 0 on the box (design §7 S19). NOT claimed.
* `scan_age_s` itself: no Mid-360 on this host. Recorded UNMEASURED in both
  envelope records; the provenance names `Go2Backend`'s own scan-age reading at
  B11 as what will measure it.
* Wiring `scripts/ci_gate.py:evaluate_stopping_envelope` to the six-term rows —
  HW-7 owns that file in 3b; DESIGN §(f) records the exact change.

---

## Amendment 1 — 14:5x, BEFORE the row commands were run

The rows above are unchanged and stay verbatim. This amendment SPLITS row B1,
because the row as registered cannot be met honestly and the reason is a fact
about the tree, not about the implementation.

**What was found** (scratchpad probes `probe_join.py` / `probe_live.py`, run to
validate the design before the tests were written — they are not row
measurements and no row is claimed from them): the origin a scan carries is
declared BY THE PRODUCER, by construction. `RecordedStage0Source` reads a
FILE, so it declares `EvidenceOrigin.REPLAY`; REPLAY is in `SYNTHETIC_ORIGINS`,
so under `requirements_requiring_physical_inputs()` a replayed scan latches
`scan:sim_fixture_forbidden` — which is the CORRECT answer and the whole point
of W0-A. But `web_panel.build_runtime` on this desktop can only ever produce a
replay-fed `Go2Backend` (the live adapter refuses without the vendor SDK). So
"through `build_runtime`, the go2 scan no longer latches" is not reachable
without a config key that mints PHYSICAL for a file — which this card will not
add.

**B1 becomes two rows, both measured:**

* **B1a (through `web_panel.build_runtime`, zero monkeypatch of anything):**
  with `backend.kind: go2` + a fixture and `safety.require_physical_inputs:
  true`, the join DOES report `scan:sim_fixture_forbidden`. A recorded fixture
  does not acquire physical authority by passing through the new seam.
* **B1b (the authority row):** through the SAME constructor `build_runtime`
  calls — `RobotRuntime(config_path, backend)`, `runtime.py:1498` — with a
  `Go2Backend` over `LiveGo2Sources`, whose DDS subscriber and UDP socket are
  injected the way `UnitreeSportStateSource(subscriber_factory=…)` already
  allows: **no `scan:sim_fixture_forbidden` fault**, while B2's sim control
  still latches. The vendor transport is the only double; no evidence function,
  requirements table or origin is patched.

B3 is unchanged and still applies to both: the verdict stays `LATCHED_STOP` for
POSE and `controller_feedback:missing` HOLDs, because pose authority and the
controller are not in this card.

sha256 of this file at Amendment 1 supersedes the pre-amendment
`3aa1eacb01ea95e5e421fbad3747f22ee6d79ac8ec3c3a28f66623da50892bfe`; both are
recorded in `HW2_STATUS.md`.

---

## Amendment 2 — 2026-08-23 19:0x (host clock `Sun Aug 23 03:29:06 PM EDT 2026`), BEFORE any re-measurement of the corrected code

*(N2: stamped from `date`. The dispatch log's labels run ~3 h ahead of this host's clock; the ordering fact — this file written before the first corrected-code run — is the one that matters.)*

Written after the verifier's HOLD (`~/.cache/parcel-verify/hw2/VERDICT.md`) and
before a single row of the corrected code was run. Rows A/B/C/D/E above stay
verbatim; this amendment re-cuts **B6** and **seed S3**, and adds four rows.
The reason is one design change, not four fixes.

### The design change (H1 + H2 are the same defect)

The scan datum was a LATEST, and the join reads a PAST observation. Two
consequences the verifier reproduced through a real `RobotRuntime`:

* **H2** — `observe()` is called from the loop AND from HTTP handler threads
  (`runtime.py:6210,9551,10295`), each draining the one socket. The join could
  therefore grade observation N against sweep N+1, and — the direction that
  matters — report **no SCAN fault at all** for a scan-less observation whose
  `lidar_ranges` are `()`, where `scan_evidence_from_observation` would have
  said `missing → HOLD`. The region's claim "can only ever be stricter or
  equal" was false.
* **H1** — one corrupt Livox datagram makes `observe()` raise; the runtime keeps
  the previous observation and joins on it again; the source saw the SAME datum
  a second time and called it `sequence_duplicate` → `payload_malformed` →
  `LATCHED_STOP` on every later sweep, un-clearable (the operator's
  `clear_input_health_latch` re-joins on the same observation and re-latches).

**The fix, one change:** the datum travels WITH the observation it graded.
`Go2Backend.scan_datum_for(observation)` returns the `ScanDatum` built from the
frames that produced THAT observation's `lidar_ranges` (identity-keyed, bounded
history), `CommissionedScanSource.evidence(key)` reads it, and the runtime
region consults the source **only when the observation already carries a scan**
— the source may RE-STAMP the origin of a scan the observation has, never
supply presence it lacks. An identity re-read of the same datum is EXEMPT from
the ordering latch, exactly as `control/base.py:CommissionedStateSource`
exempts it and for the same measured reason; a DIFFERENT datum carrying a
repeated sequence still latches.

### Re-cut rows

* **B6 (re-cut).** Was: "a duplicate sequence latches". Now: *a duplicate
  sequence latches when the datum is a DIFFERENT one; re-reading the SAME datum
  (identity or field-equality) is not a fault.* Sub-cases: `sequence_duplicate`
  (different datum, repeated sequence) LATCHES; `sequence_reordered`,
  `receipt_regression`, `session_epoch_mismatch` LATCH; **identity re-read**
  (same object) and **equality re-read** (an equal rebuilt datum) do NOT.
  Threshold: after a real fault, three clean data still invalid; after an
  identity re-read, `latched_reason is None` and `payload_valid` True.
* **Seed S3 (re-cut).** Was: "the source stops latching". Now TWO seeds:
  **S3a** the ordering latch is removed entirely (must redden the four fault
  sub-cases), **S3b** the identity exemption is removed (must redden the two
  re-read sub-cases). Both RED on an import-verified scratch.

### New rows

| Row | Claim | Command | Threshold |
|---|---|---|---|
| **H1a** | One corrupt Livox datagram costs one tick, never the session: tick 1 clean → tick 2 the datagram is refused and counted (`on_refusal`), the tick still yields whatever else was in the socket → tick 3 a clean sweep grades clean. No `LATCHED_STOP` anywhere. | `GUARD T -k h1a_a_corrupt_datagram_costs_one_datagram` | `refused_datagrams == 1`; no `payload_malformed` on any tick; `latched_reason is None`; the good datagram behind the corrupt one is NOT abandoned |
| **H1b** | The operator's e-stop clear can clear. `clear_input_health_latch()` twice on ONE observation (the verifier's exact path, `runtime.py:4746→4786`) raises no new fault. | `GUARD T -k h1b_the_operator_can_clear_the_latch` | second read: `latched_reason is None`, no `scan:payload_malformed`; `_input_health_latched` False after the clear |
| **H2a** | Stricter-or-equal, enumerated. For each of the four SCAN cases — `missing`, `sim_fixture_forbidden`, `payload_malformed`, ok — the join's SCAN verdict WITH the typed source is never more permissive than WITHOUT it, with exactly ONE permitted relaxation: clearing `sim_fixture_forbidden` on an observation that ALREADY carries a scan (the card's whole purpose). A scan-less observation is `missing → HOLD` with the source and without it. | `GUARD T -k h2a_the_source_is_never_more_permissive` | the four (with, without) pairs as tabulated in the test; `missing` never cleared |
| **H2b** | Interleaving: loop observation (no sweep) + a handler `observe()` that drains a sweep → the loop's join still reports `scan:missing HOLD`. The verifier's exact reproduction. | `GUARD T -k h2b_a_later_sweep_cannot_grade_an_earlier_observation` | `scan:missing`, action HOLD; and the earlier sweep's observation still grades against ITS own datum |
| **F2a** | `observe()` never fabricates a pose. With no `rt/sportmodestate` sample yet it raises a typed `Go2StateUnavailable`; the runtime's own `except` turns that into `observation=None` → HOLD. | `GUARD T -k f2a_no_pose_is_fabricated_before_the_first_sample` | `Go2StateUnavailable` raised, message names `rt/sportmodestate`; no `RobotPose()` published; the frames are NOT consumed by the refused tick |
| **F3a** | The live scan transport exists on the product path and cannot hang. `backend.livox: {host, port}` opens a non-blocking bound UDP socket; a blocking socket is REFUSED at construction; a drain that reads nothing returns `()` within the budget. | `GUARD T -k f3a_the_live_scan_transport` | unknown `livox` key refused BY NAME; a socket whose `gettimeout()` is `None` refused; a slow socket returns within `drain_budget_s`; no-frames → `()` → HOLD |
| **F5a** | The declaration is visible in the latch record: `input_health_latch()` carries `scan_source_origin` and `scan_source_name`, and the name is the SOURCE's (`go2_live` / `go2_stage0_replay`), never the bare `go2`. | `GUARD T -k f5a_the_scan_declaration_is_visible` | both keys present; `scan_source_name == "go2_stage0_replay"` for the replay backend; `observation.backend` likewise |

### Seeds added

| Seed | Mutation | Must redden |
|---|---|---|
| S8 | the runtime region drops the `scan is not None` precondition (the source may supply presence) | H2a, H2b |
| S9 | `scan_datum_for` returns `latest_scan()` (the datum stops travelling with the observation) | H2b |
| S10 | `observe()` falls back to `RobotPose()` when `latest()` is `None` | F2a |

Rows B1a, B1b, B4 and the A/C/D/E rows are RE-RUN unchanged after the change;
any that move are reported as moved.
