# HW-5 `physical-profile` — PREREGISTRATION (task_41, slug hw5)

Written BEFORE any measurement. Rows are measured exactly as written; a miss
is a miss. `GUARD` below = `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh
--label hw5 .parcel/bin/python -m pytest`. `HW5` =
`tests/test_hw5_physical_profile.py`. No `-n auto`, no `ci_gate.py --tier`, no
background pytest, no simulator, ≤ 8 workers.

## Rows

| # | Claim | Command | Threshold |
|---|---|---|---|
| R1 | The profile loads over the SHA-locked base through the real loader | `GUARD HW5 -q -k profile_loads` | `ConfigStore(configs/robot.yaml, profile="go2_edu_plus")` raises nothing; merged mapping is a dict |
| R2 | The base file did not move | `GUARD HW5 -q -k sha_locked_base` | sha256 of `configs/robot.yaml` equals the value recorded in `evals/companion/embodied_plan_v1/manifest.json` |
| R3 | Every key the profile writes is admitted, and each NEW key is a scalar/parent entry — never a dotted child of an exempt parent | `GUARD HW5 -q -k keys_admitted` | `check_overlay_keys(base, overlay)` returns; `{venue, backend, perception.lidar_band_min_m, perception.lidar_band_max_m, perception.lidar_min_populated_bins, perception.lidar_extrinsic_xyz_rpy} ⊆ OVERLAY_INTRODUCIBLE_KEYS`; no entry starts with `venue.`, `backend.` or `perception.lidar.` |
| R4 | A one-character misspelling of each of the six new keys REFUSES by name, through a real sibling overlay on the product path | `GUARD HW5 -q -k misspelling` | 6/6 raise `ProfileError` whose message names the misspelled path; the correctly spelled twin loads |
| R5 | `venue=` is wired: the retirement gate is reachable | `GUARD HW5 -q -k venue_injection` | with `PARCEL_PROFILE=go2_edu_plus`, `adapter_for(<an l2.* channel>)` raises `IngestUnavailableError` naming `go2_edu_plus` and the Mid-360 remedy |
| R6 | Flag-off identity in the capture lane | `GUARD HW5 -q -k adapter_identity` | with NO profile, `adapter_for` returns the same adapter type and `__dict__` for all 28 matrix channels as with the injection region removed; `L2Ingest.venue == LEGACY_ADDON_L2_VENUE` |
| R7 | The desktop REFUSES with the real profile, through `RobotRuntime.start()` | `GUARD HW5 -q -k desktop_refusal` | raises; message contains `camera venue 'realsense' was selected`, `No device connected`, `Attach the D455` |
| R8 | The CAP-1 declaration is LIVE, not inert | `GUARD HW5 -q -k declaration` | (a) `required_capabilities(venue nav file)` is non-empty and every name ∈ `REGISTERED_CAPABILITIES`; (b) a copy whose ONLY delta is `perception.semantic_source: oracle` makes `RobotRuntime.start()` raise `CapabilityRefused` containing `learned_map_source` and `admission table:`; (c) the unmodified file passes that door |
| R9 | No truth/oracle field | `GUARD HW5 -q -k no_oracle` | the profile's merged-delta key paths contain none of: `simulation`, `poses`, `battery.simulated_percent`, `control.controller`, `control.unitree_sport.axes_commissioned`, `control.unitree_sport.state_frame_commissioned`, `control.unitree_sport.allowed_modes`, `perception.maps.enabled`, `perception.semantic_source`, `perception.tier` |
| R10 | Flag-off identity of the config: no profile and `prototype` are byte-identical to HEAD | `GUARD HW5 -q -k config_identity` | `yaml.safe_dump(ConfigStore(base, profile="").data)` and `profile="prototype"` sha256 equal the values recorded in this file at first measurement AND equal the same computed with the `CARD HW-5` region's keys removed from `OVERLAY_INTRODUCIBLE_KEYS` |
| R11 | Declared-ahead-of-reader keys are enumerated, not hidden | `GUARD HW5 -q -k declared_ahead` | the test's `DECLARED_AHEAD` map is exactly `{backend, perception.lidar_band_min_m, perception.lidar_band_max_m, perception.lidar_min_populated_bins, perception.lidar_extrinsic_xyz_rpy}`, each with a non-empty owed read site; a grep proves no product module reads them today |
| R12 | No other navigation file declares | `GUARD HW5 -q -k only_the_venue_file_declares` | across `configs/navigation/**/*.yaml`, exactly one file has a non-empty `required_capabilities`, and it is `venues/go2_edu_plus.yaml` |
| R13 | Neighbours stay green | `GUARD tests/test_prototype_profile.py tests/test_cap1_admission.py tests/test_capture_ingest.py tests/test_truth1_texts.py -q` | 0 failed |
| R14 | Lint | `env -u TMPDIR .parcel/bin/ruff check <OWNS>` + `ruff format --check <OWNS>` | 0 new fingerprints against `scripts/ci_ruff_baseline.json` (tree total stays 7 + other cards' in-flight); format clean; zero `noqa` in any HW-5 file |

## Seeds (each RED on a byte-identical scratch copy, never the working tree)

Scratch: `rsync -a --exclude .cache --exclude .parcel --exclude .git` of
`src/ scripts/ tools/ tests/ configs/ prompts/`; run with
`PYTHONPATH=<scratch>:<scratch>/src`; `python -c "import parcel_robot;
print(parcel_robot.__file__)"` verified INSIDE the scratch; restored by
sha256; `__pycache__` purged.

| seed | mutation | must redden |
|---|---|---|
| S1 | `adapter_for` reverted to plain `factory()` (injection removed) | R5 |
| S2 | `"venue"` deleted from `OVERLAY_INTRODUCIBLE_KEYS` | R1, R3 |
| S3 | profile's `perception.camera_backend` → `mujoco` | R7 |
| S4 | venue nav file's `required_capabilities` → `[]` | R8 |
| S5 | `battery: {simulated_percent: 100}` added to the profile | R9 |
| S6 | the four `perception.lidar_*` entries replaced by one `perception.lidar` subtree entry, profile renested | R3 (and R4's lidar arm) |
| S7 | `adapter_for` passes `venue="go2_edu_plus"` unconditionally | R6 |

## Owner-gated / not measured here

* Every number the box measures: extrinsic (B11), robot-LAN NIC (B-con),
  array PortAudio index (Q-usb), band re-derivation from real sweeps (B11).
* That the declared capabilities BIND on the Orin (aarch64 / CPython 3.10):
  first proof is box-day, not this desktop.

---

## Amendment 1 — 2026-08-23, written BEFORE measurement

Integrator decision from card HW-2's verdict (F6). The body above is unchanged;
these three rows are added and are measured exactly as written below.

`safety.require_physical_inputs` (`runtime.py:1707-1731`, default False, absent
from the SHA-locked base and not introducible) selects
`requirements_requiring_physical_inputs()`. Without it the physical profile
runs on `requirements_allowing_sim_fixtures()`, where a REPLAY scan and a
SIMULATION pose SATISFY the dispatch health join.

| # | Claim | Command | Threshold |
|---|---|---|---|
| A1 | The switch is admitted as an exact nested path, and its misspelling is refused by the LOADER | `GUARD HW5 -q -k "keys_admitted or misspelling"` | `safety.require_physical_inputs` ∈ `OVERLAY_INTRODUCIBLE_KEYS`; `check_overlay_keys(base, {"safety": {"require_physical_input": True}})` raises `ProfileError` naming it; the correct spelling merges |
| A2 | The value the profile writes ARRIVES at the runtime | `GUARD HW5 -q -k switch_reaches` | with `$PARCEL_PROFILE=go2_edu_plus`: `RobotRuntime(configs/robot.yaml, …)._require_physical_inputs is True` AND `web_panel.build_runtime(...)._require_physical_inputs is True`; with no profile, `False` |
| A3 | Under this profile a replayed scan does NOT pass the join (HW-2's B1a through HW-5's profile), and the key is what makes that true | `GUARD HW5 -q -k replayed_scan` | arm A (profile as shipped + `backend.fixture`): the verdict's faults contain `scan: sim_fixture_forbidden` and `verdict.action is HealthAction.LATCHED_STOP`; arm B (the SAME tree with that one key deleted): `sim_fixture_forbidden` absent. If `_build_backend` cannot construct HW-2's own fixture backend in this tree, the row is NOT MEASURABLE and the reason is recorded verbatim |
| A4 | The `safety:` rule is directional | `GUARD HW5 -q -k no_oracle` | the profile's `safety:` block is exactly `{"require_physical_inputs": True}` — every threshold key forbidden, and `false` forbidden too |

Seeds for the amendment: **S13** delete `"safety.require_physical_inputs"` from
`OVERLAY_INTRODUCIBLE_KEYS` → A1/A2/A3 redden; **S14** set the profile's value
to `false` → A2/A3/A4 redden; **S15** delete the key from the profile → A2/A3
redden.
