# Wave 3 dispatch record · Fable (parcel-6c, session 31fcc2a0) · 2026-08-23

Read this first after any crash. Owner's instruction (12:4x): "Start
executing on the implementation now using opus and verify with fable."
The implementation = the software-now rail of `WAVE3_HW_DESIGN_FABLE.md`
§9. Wave 3a (now): HW-1 `task_35`, HW-3 `task_36`, HW-4 `task_37`, HW-6
`task_38`, HW-8 `task_39`. Wave 3b (after 3a verifies): HW-2, HW-5, HW-7.

## Tree state at dispatch

HEAD `e15e466`. **Batch B + GATE-0b + `CLAUDE.md` are STAGED in the index
(118 paths) and not committed** — the owner says "commit and upload" to
this session. Executors never run git write-ops (no add/commit/stash/
checkout). For shared files, `git diff HEAD -- <file>` shows batch B's
staged hunks too — attribute by `CARD` markers; `git diff -- <file>`
(index vs working tree) shows ONLY this wave's edits and is what "what
changed" in a status doc must quote. Dirty set before dispatch: exactly
the staged set (`git status --porcelain | grep -v '^[AM] '` is empty).

## COMMON brief for every wave-3 executor (binding)

1. The batch-B COMMON brief in `BATCHB_DISPATCH_FABLE_4a.md` (design-first,
   OWNS discipline, marked regions `# ---- CARD HW-n … ---- END CARD HW-n`,
   Edit-only in shared files, git read-only, TMPDIR unset, owner's
   `parcel_memory.sqlite3` never read-write, never touch
   `/tmp/parcel_sim.sock` or :8765, never kill a process you did not start,
   lint = exactly the 7 baseline fingerprints and never `noqa`) and its
   **parcel-6c anti-crash rules** (every pytest through
   `~/.cache/parcel-guard/pytest_guard.sh --label <slug>`; never `-n auto`;
   never `ci_gate.py --tier`; pre-flight `free -g` ≥ 120 and
   `ps -eo args | grep -c '^[^ ]*python[^ ]* -m pytest'` ≤ 1; no background
   pytest; exit 137 is a finding) apply verbatim.
2. Order of work: `DESIGN.md` (seams as module:symbol, the product-path
   caller, §e hardware-compat class per design §4: VI / MC / NEW / UNK, and
   what the desktop cannot prove) → `PREREGISTRATION.md` (every row with
   its command and threshold BEFORE it is measured; seeds named) → code →
   `HWn_STATUS.md` written incrementally in the lightweight register
   (headline · what changed with `git diff --stat -- <OWNS>` + new files ·
   how verified with exact commands + results · what it does not prove ·
   deviations · owner-gated rows · handoffs). DESIGN.md target ≤ 150
   lines; say why if over.
3. Seeds: every guard gets a seeded-RED proof on a byte-identical scratch
   copy (NEVER the working tree) run with `PYTHONPATH=<scratch>:<scratch>/
   src` and `python -c "import parcel_robot; print(parcel_robot.__file__)"`
   verified inside the scratch (the editable `.pth` otherwise imports the
   working tree), restored by sha256, `__pycache__` purged. Copy only
   `src/ scripts/ tools/ tests/ configs/ prompts/` (`rsync -a --exclude
   .cache --exclude .parcel --exclude .git`); never the whole repo.
4. Shared files in wave 3a and their writers: `src/parcel_robot/runtime.py`
   (HW-1 import lines at the top; HW-4 one branch at the gateway
   construction ~8230) — mkdir-lock `~/.cache/parcel-batchb/lock-runtime.py`
   (`owner` file inside, rmdir after one short Edit pass);
   `src/parcel_robot/config.py` (HW-4 one key; TRUTH-1's staged region
   stays untouched); `pyproject.toml` (HW-1 only); `scripts/ci_gate.py`
   (HW-6 only; XD-1's three and GATE-0b's regions untouched);
   `capture/channels.py` + `ingest/l2.py` (HW-3 only). Everything else is
   per-card.
5. No simulators are needed in wave 3a; do not start one. HW-4 may open
   the XVF3800 (on hand) through PortAudio; nothing opens the hosted lane
   (`PARCEL_REALTIME_KEY_ENV` unset, $0).
6. Last act = your report; `tools/list_parcel_procs.py` clean; zero pytest
   processes; no locks held. Return: COMPLETE or HALTED, rows met/missed,
   deviations, what the verifier must look at first.

## Verification (Fable)

One `claude` subagent per card (inherits this session's model — Fable):
three lenses (seeds/weakening · product correctness + OWNS · product-path
integration) + skeptic + a `guard.log` audit against the status doc's
command ledger; verdict to `~/.cache/parcel-verify/<slug>/VERDICT.md`;
correction pass on the same Opus executor; narrow re-verify when product
code moved. Then parcel-6c's own read of the verdicts before the wave-3b
dispatch.

## Dispatch log

* **12:5x EDT** — wave 3a launched concurrently on Opus: HW-1 (task_35),
  HW-3 (task_36), HW-4 (task_37), HW-6 (task_38), HW-8 (task_39). Memory
  at dispatch 233 GB available; zero pytest/sim processes; batch B staged.
* **13:1x EDT** — HW-8 executor returned COMPLETE (docs only): 21/22 rows
  MET; the miss (H2 "tree clean at close") is a pre-registration defect
  on a shared tree, not an OWNS violation. `docs/BOX_DAY.md` 204 lines /
  2,136 words; first-two-hours 95 min; owner-present 5.0 h; EDU+ Stage-0
  run sheet rewritten from `scrum/20260813/task_1/session/
  STAGE0_RUN_SHEET.md` (D1: the README named the wrong source file) with
  18 `was` comments; support ticket (unsent); unknowns register ×16.
  Handoffs to the DESIGN (mine): HO-1 `parcel-capture` is not a console
  script → `python3 -m scripts.parcel_capture.<module>`; HO-3
  `parcel-commission observe` → `parcel-unitree-control observe` (§7
  S19); HO-2 `record --plan stage0 --dry-run` does not exist (a plan
  selector would be a new 3b card). Verifier (Fable) dispatched.
* **13:2x EDT** — HW-6 executor returned COMPLETE: 24/24 rows; formula
  `required = v·(age + ipc + period + braking) + jump_m` pinned in
  `bridge/timing.py:derive_envelope` (pure; RC-4 rows byte-identical);
  regimes one_axis 0.05 m/s / 0.050 m, leashed 0.15 / 0.330,
  restricted_free 0.25 / 0.330 (cites `limits.py:78`, `obstacle_stop_m
  − footprint`); soft gate row `stopping-envelope` registered GATE-0b's
  way (stage list + `run_commit_tier`, own fences; `test_ci_gate.py`
  untouched, 91/91); dev-box floors measured through the real N24 path
  (ipc p99 329 µs, candidate age p99 1.8 µs); seed +50 ms reddens by
  6.25 mm; 23 guarded runs, 233 passed. **F1 for the design (mine):**
  "one-axis 0.10 m/s" is a DISTANCE in `limits.py:52` (0.05 m/s × 2 s);
  the band refuses > 0.05 m/s — owner/PO-1 decision + §6/§9 correction.
  H2 (not HW-6's): `tests/test_hw3_mid360_band.py` failed to collect
  mid-flight (HW-3 in progress). Verifier (Fable) dispatched.
* **13:3x EDT** — HW-1 executor returned COMPLETE: 13/13 rows; census 12
  findings (5 `datetime.UTC`, 7 `typing.Self`, one already guarded), 0
  unguarded after; `UTC` → re-exported `timezone.utc` (same singleton),
  `Self` → `TYPE_CHECKING` (annotations stay the string `'Self'`);
  **real CPython 3.10.21 (uv, outside the repo) imports
  `parcel_robot.runtime`; 312/315 modules import** (3 = websockets/evals,
  not in `base`); 656 targeted tests green; `requirements-lock-jetson.txt`:
  `base` resolves fully on cp310 aarch64 (numpy 2.2.6 is the last cp310,
  mujoco 3.12.0, pyrealsense2 2.58.3.10794). **H2 (design-level):**
  `voice` is NOT installable on 3.10 — websockets 17.x requires ≥ 3.11
  (highest cp310 = 16.1.1), so `realtime/{audio_gateway,ws_transport}.py`
  do not import on a 3.10 product venv → §5.1 vs §5.6 conflict; decision
  owed by the design owner (parcel-6c) before HW-4/HW-5/HW-7 close.
  `perception`: onnxruntime-gpu has no aarch64 wheel at any version
  (`perception-jetson` extra unpinned, for HW-7). H1
  `conversation_store.py:747` `fromisoformat` drops a trailing `Z` on
  3.10 (behaviour, handoff). 32 guarded runs; ruff 0 new (tree-wide 13 =
  7 + HW-3's in-flight 6). Verifier (Fable) dispatched.
* **14:0x EDT** — HW-8 verifier: **HOLD** (docs-only): three of thirteen
  §7 steps carry commands that fail or cannot do the step (Q-lidar
  `--out` does not exist and the label path needs `--operator/--photo`;
  S20 `attest` has no live identity reader — the real route is app read
  + `orin_rehearsal --firmware-attested`; B-fw: no nftables ruleset
  exists anywhere, no owner card); S19 `observe` has no duration mode;
  X1/X9/X11 mis-measured (11 `was` comments not 18; three non-purchase
  run-sheet changes unlisted); no "who" column; no step 0 for getting a
  shell on the Orin. Registration, sums (95 min / 5.0 h), D1, H2, ticket,
  register all hold. Correction pass sent 14:0x; **design §7 corrected
  by parcel-6c** (11 replacements + §7.3) from the verifier's table;
  **new wave-3b card HW-FW `orin-firewall`** owns `deploy/orin/
  nftables.conf`.
* **14:1x EDT** — HW-3 executor returned COMPLETE: R1–R9 MET; 144 new
  tests; neighbours 1053 passed; 20,064 points → ranges 6.15 ms; 5 seeds
  RED on an import-verified scratch; imports and runs on the 3.10 venv
  with numpy/mujoco/socket/rclpy absent from `sys.modules`. Decoded:
  SDK2 header fields + data types 1 (14 B mm) and 2 (8 B cm); refused:
  types 0/3/0x11, crc32 unverified, `tag` bits UNCONFIRMED; recorded the
  SDK-1 vs SDK-2 point-size contradiction in `livox_ros_driver2/comm.h`.
  Seam: `parcel_robot.lidar:scan_from_frames / nearest_obstacle_from_scan
  / travel_bearing_rad / BandProfile`. Findings: (1) **design §4 S1 is
  wrong** — `core/input_health.py:114-134 evidence_origin` returns
  SIMULATION for every `SimObservation`; physical origin is HW-2's via
  `control/base.py:CommissionedStateSource(origin=PHYSICAL)`; (2) empty
  bins are **NaN**, not `range_max` (a non-repetitive frame cannot assert
  free space) — safety-relevant, verifier rules; (3) the capture matrix
  is pinned at 28 (`test_capture_envelope.py:149,160,1489`), so
  `SourceDevice.MID360` + two rows landed beside it as `MID360_CHANNELS`;
  L2 retirement venue-gated (`venue="go2_edu_plus"`). DESIGN.md 234
  lines. Verifier (Fable) dispatched.
* **HW-6 — ACCEPT-WITH-NOTES** (verifier Fable, ~13:30–13:45; record
  `~/.cache/parcel-verify/hw6/VERDICT.md`). Braking term = command →
  standstill everywhere it is defined (`timing.py:200-215`, DESIGN §(c),
  BOX_DAY_INPUTS B2, `default.yaml`), so `v·t_braking` is a rigorous
  upper bound for any v(t) ≤ v (under-counts only under overshoot);
  regimes re-derived 0.050 / 0.330 / 0.330; RC-4 rows byte-identical;
  seeds RED→green; 27 + 115 + 92 passed; all hunks fenced and disjoint
  from XD-1/GATE-0b. FIX: F1 `test_hw6…:638` pins THIS host's missing
  set — would red the hosted gate on first push; F2 the field lacks the
  command→standstill definition at the point of use (rename to
  `stop_command_to_standstill_s`). **Design corrected by parcel-6c:**
  "one-axis 0.10 m/s / 0.25 rad/s / 2 s" was the 2026-08-03
  `unitree_control` cap that W0-B retired on 08-13; the band is
  0.02–0.05 m/s, yaw ≤ 0.156, step ≤ 1.0 s (§5.5, §6, §8, §9 fixed;
  `docs/MOTION.md:369` stale — handoff). Correction pass sent 14:2x.
* **14:3x EDT — HW-8 correction pass COMPLETE:** S20/Q-lidar/B-fw/S19/B12
  rewritten to the measured spellings (Q-lidar stays `.txt`: `--json`
  prints the human report then the JSON block on one stdout; rc=1 is
  NOT-READY); steps B0 (preconditions) and B-con (shell on the Orin —
  UNCONFIRMED which port, ticket Q5) added; "who" column; T1 105 min,
  owner-present 310 min = 5.2 h; 2,495 words; 12 `was` comments; band
  numbers fixed at `BOX_DAY.md:131` and the register. New handoffs: HO-5
  `deploy/orin/nftables.conf` → card HW-FW (3b, highest value — it is
  step 3 of the four that cannot be reordered); HO-6 `observe` duration
  mode → HW-2; HO-7 live firmware reader (unowned); HO-8
  `docs/MOTION.md:369` stale triple (owner of MOTION.md). Narrow
  re-verify sent to the HW-8 verifier 14:3x.
* **HW-1 — ACCEPT-WITH-NOTES** (verifier Fable, ~13:35–14:00; record
  `~/.cache/parcel-verify/hw1/VERDICT.md`). `UTC` re-export is the same
  singleton on both interpreters; annotations stay the string `'Self'`;
  all 12 diffs = one import line + one fenced block; `requires-python`
  ≥ 3.10 unchanged; locks byte-identical; jetson lock reproduces (11
  wheels); CI yaml parses; seeds S1–S4 RED on 3.10 AND 3.14; product
  paths identical across interpreters (SI pins, `InstructionSource`
  digest 7340c722…, `ConfigStore` shas). FIX: F1 `task_35/evidence/*.py`
  add 4 ruff fingerprints (gate-blocking); F2 the guard credits `if not
  TYPE_CHECKING`/`else` arms (two mutants). **H2 decided (design §5.1
  amendment):** Orin product venv = uv-provisioned CPython 3.12; 3.10
  stays the floor for the perception/capture/motion venvs (websockets
  16.1.1 on 3.10 also passes 68/68 — the fallback if uv's build fails on
  L4T). Correction pass sent 14:4x.
* **HW-3 — HOLD** (verifier Fable, ~14:15–14:40; record
  `~/.cache/parcel-verify/hw3/VERDICT.md`). Everything claimed
  reproduces (protocol byte-correct against a hand-built frame from
  `livox_lidar_def.h`; registration before measurement; 144 + 341 green;
  OWNS/MUST-NOT-TOUCH clean; 3.10 import clean; 6.4–7.3 ms). **F1 HOLD
  (safety channel, inside HW-3's OWNS):** a silent sensor →
  `scan_from_frames([])` → 360×NaN → `scan_present` is `bool(tuple)` →
  True → `apply_reactive_safety(0.3 m/s)` → "clear"; the `()` no-scan
  value → "stopped". Fix: `ranges_m=()` when `points_seen == 0` +
  `min_populated_bins` knob. F2 layout tests self-referential (a CW
  mirror passes 144/144) → absolute index pins from `mujoco_lidar`. F3
  two refusal reasons false (spherical units and double-echo ARE
  documented) + `time_type` GPS=2 missing. F4 the L2 retirement gate is
  inert (no caller passes `venue=`; injection point
  `ingest/__init__.py:117` → HW-5). NaN as the per-bin sentinel is
  RIGHT (every consumer traced fail-closed; `range_max` would carve
  20,342 free cells on no evidence). **Design corrected by parcel-6c:**
  §4 S1 first-proof, §5.4 physical-authority seam (a typed scan-evidence
  source + `_evaluate_dispatch_input_health`), §9 HW-3 row. Correction
  pass sent 14:5x; narrow re-verify on F1/F2 after.
* **HW-6 correction pass COMPLETE 14:5x:** F1 hostname-independent test
  (three hostnames + the default resolver path), S1 re-proved on a
  scratch; F2 RENAME `braking_latency_s` → `stop_command_to_standstill_s`
  everywhere (grep 0), `#:` definitions on all five fields, the
  cost-of-a-reaction-only-number paragraph in the `ci_gate.py` region
  header; N3/N6/N7/N8 applied; 30 + 91 passed; additive-only hunks.
  Integrator: `configs/envelope/` lands in the same commit as the two
  shared-file hunks. Narrow re-verify sent.
* **15:0x EDT** — HW-4 executor returned COMPLETE: 26 rows MET (A1–A17,
  S1–S7, H1, H2); chunk contract pinned off both sources (browser: mono
  PCM16 LE 24 kHz, `max_frame_bytes` 32768, 2,048-byte frames;
  `ArrayAudioGateway` at `frame_ms=40` → 1,920 B = exactly 40 ms, column
  1 of a TWO-channel open); flag-off identity through the real
  `web_panel.build_runtime` (seed S5); config entry is `"audio"` (dotted
  form would be the inert-guard anti-pattern, D6). **H3 MISSED — the
  XVF3800 does not stream on this host:** enumerates 2886:001a, opens,
  `stream.active == True`, then `Input/output error` on the first read
  (arecord hw/plughw, pw-record, sounddevice ×3 device ids, the card's
  own probe) — zero frames in 30 s; permissions, holders, mixer,
  PipeWire profile, sandbox all ruled out; both endpoints SYNC — the
  "capture clocked off playback" hypothesis recorded, NOT tested
  (executor declined to drive the DAC). Nobody has ever streamed from
  this array on this host (AIR-1's rate pin was a format query). Added
  `_check_deaf` (an armed-but-deaf gateway now says so once, naming the
  `arecord` line). Deviations: D1 a 14-line marked region in
  `tests/test_prototype_profile.py` (outside OWNS; TRUTH-1 precedent);
  **D2 ran `tests/test_voice_nav_e2e.py` — starts a sim, harness
  backgrounded it, killed — one guard START without END (anti-crash
  rule 6 deviation, declared)**; D3 `_check_deaf` + S8 post-hoc. **H-1
  blocking handoff:** `web_panel.py:493` arms the websocket only for
  `BrowserAudioGateway` — the array ear is unreachable from the product.
  Verifier (Fable) dispatched with leave to test the playback-clocking
  hypothesis with SILENCE.
* **HW-8 CLOSED 15:1x — ACCEPT-WITH-NOTES.** Residuals R-1 (ticket Q5d +
  six questions), R-2 (nft rules runtime-only, re-check after reboot and
  before Q-link), R-3 (run-sheet T4 `--print-argv humble`) applied;
  2,491 words; 13 `was` comments; 105 / 310 min. Design §7/§8 mirrored
  by parcel-6c (B0, B-con, S19 ten-run, B12 result, Q-con). Open, not
  HW-8's: HO-8 `docs/MOTION.md:369` stale triple (MOTION.md owner).
  Owner: read + sign `docs/BOX_DAY.md`; send the ticket.
* **HW-6 FINAL — ACCEPT-WITH-NOTES (15:1x).** Re-verify: rename complete
  (0 hits outside the frozen PREREGISTRATION/STATUS), field docstring
  command→standstill, parametrised test holds on a fourth hostname with
  `default.yaml` complete-and-empty, RC-4 byte-identical (table shas
  466cad1f…/2a2927d5…), hunks additive and fenced (946–1068, 2172–2179,
  2255–2263), `test_ci_gate.py` untouched 91 passed. N11/N12 docs sent
  to the executor (no round). Integrator: `configs/envelope/` + the test
  + `task_38/` in the same commit as the two shared-file hunks.
  Design-owner notes N4/N5: `one_axis` carries `localization_jump_m`;
  scan age is not among HLD's five terms — recorded for §6.
* **HW-6 CLOSED 15:2x** (N11 five quoted outputs updated; N12
  `fictional-orin-host`; 30 passed; 29 guarded runs total).
* **15:3x EDT — HW-1 correction pass COMPLETE:** F1 evidence scripts
  ruff-cleaned (a `# noqa` was hiding in `import_sweep.py` — now a named
  tuple), in-process ratchet 7 / 7 / new []; F2 guard credits only the
  `TYPE_CHECKING` body and `version_info` arms; V1/V2 + S1–S4 RED on both
  interpreters (30 / 27+3 control); N1/N3/N4/N5 applied; **H11:
  `requirements-lock-jetson-py312.txt` delivered — base+voice+camera+
  camera-realsense resolve on cp312 aarch64, 17 packages, zero missing**
  (the §5.1 amendment now has its lock); twelve product files
  byte-identical to the verified state; 52 guarded runs. Narrow
  re-verify sent.
* **15:4x EDT — HW-3 correction pass COMPLETE:** F1 `min_populated_bins`
  (default 1, "tune at B11"), `ranges_m=()` below it, seam snippet
  never copies an empty scan, test reproduces the verifier's path →
  "stopped" with the NaN counterfactual kept live, seed C1 2 failed;
  F2 literal pins from the sim (ahead 180, LEFT 270 @ +π/2, RIGHT 90,
  behind 0, ±0.2 m → 186/174) + a derivation test; the CCW test
  rewritten (its first version compared the two returns to each other);
  seeds: `angle_min→0` 6 failed, three-site mirror 3 failed; F3 "documented,
  not decoded" + `LivoxTimeType.GPS=2`; F4 inertness stated in code and
  DESIGN (injection point `ingest/__init__.py:117-118` → HW-5). 156
  tests; neighbours 1065; 3.10 empty sweep → `()`; 26 guarded runs.
  Narrow re-verify sent.
* **HW-1 CLOSED 15:5x — FINAL ACCEPT-WITH-NOTES.** Re-verify: product
  files unchanged since pass 1; guard 30 / 27+3 through the wrapper;
  V1–V4 RED on both interpreters (V3 compound `TYPE_CHECKING and …`, V4
  `version_info` with the import in the else); ratchet 7/7 in-process;
  zero `noqa` directives in any `.py` under task_35; py312 lock
  reproduced 17/17. N7 (optional 3b): `if sys.version_info >= (3, 10):
  from typing import Self` is still credited — require the tuple ≥
  (3, 11). Handoffs H1 (`fromisoformat` drops a trailing `Z` on 3.10),
  H9 (`tests/`/`tools/` 3.10 idioms) stand.
* **HW-3 CLOSED 16:0x — FINAL ACCEPT-WITH-NOTES.** Re-verify in-process
  on the working tree: empty / 1-point / same-bin / all-out-of-band /
  below-range_min sweeps → `()` → "stopped"; at the floor the 360-tuple
  keeps NaN as the per-bin sentinel and the gate reads the obstacle;
  seeds vs the new tests: `angle_min→0` 9 failed, mirror 3, bearing-only
  sign swap 5, coverage gate removed 2; sim literals confirmed from
  `mujoco_lidar.py:488-491`; stdlib-only imports; GPS=2. Design
  sentences (§4 S1, §5.4, §9 row) already applied by parcel-6c. HW-2
  musts: branch on empty `ranges_m`; a typed scan-evidence source for
  physical authority; scan age as a sixth envelope term. HW-5 musts:
  profile expresses `min_populated_bins`/band/extrinsic and passes
  `venue=` at `ingest/__init__.py:117-118`.
* **HW-4 — HOLD** (verifier Fable, ~15:05–16:05; record
  `~/.cache/parcel-verify/hw4/VERDICT.md`). All 26 code rows reproduce;
  resamplers exact (peak 1000.0000 Hz, −88/−92 dB OOB, DC gain 1.0,
  numpy-only, runs on 3.10 + numpy 2.2.6); flag-off identity real;
  misspelling refused at boot. **THE ARRAY IS NOT BROKEN — its capture
  endpoint is clocked off playback:** capture alone → EIO / 0 frames;
  with a silent playback stream open → exact 16 kHz (duplex 124 blocks /
  5 s; `aplay /dev/zero` + `arecord` 3.00 s; the unmodified product
  gateway delivered 124 × 1,920 B frames in 5.0 s, −45.6 dBFS, 0
  errors). Only zeros reached the DAC; nothing persistent touched. FIX:
  F1 (HOLD) open playback with input, never lazily; F2 reader-thread
  race (open slower than 50 ms kills the loop; `_check_deaf` unreachable);
  F3 13 `# noqa: BLE001` in the region (rule); F4 `ruff format --check`
  fails though A17 said MET; F5 `set_mic(True)` opens the billed hosted
  session before the device; F6 the owner addendum's check fails by
  design; F7 D2 declared. **H-1 (3b panel card):** nothing in the product
  calls `ArrayAudioGateway.set_mic(True)` — minimal change `POST
  /api/realtime/mic {"open": bool}` behind `_authorize_post()`,
  `startMic()` branches on `realtime.gateway.kind`. Correction pass sent
  16:1x; narrow re-verify after (product moves).

## Wave 3b

Cut 16:2x from the 3a verdicts: HW-2 `task_40`, HW-5 `task_41`, HW-7
`task_42`, HW-FW `task_43` (from HW-8's HO-5), HW-MIC `task_44` (from
HW-4's H-1). Shared files and their writers in 3b: `web_panel.py` (HW-2
branch at ~728; HW-MIC route region) — mkdir-lock; `runtime.py` (HW-2
region at `_evaluate_dispatch_input_health`; HW-5 only if unavoidable);
`config.py` (HW-5); `bridge/timing.py` + `configs/envelope/` (HW-2, outside
HW-6's fence); `scripts/ci_gate.py` (HW-7 only; XD-1/GATE-0b/HW-6 regions
untouched); `ingest/__init__.py` (HW-5). HW-7 has GATE-0b's rule-3
exception (gate only in its emulated container, through the wrapper, ≤ 2
runs). HW-MIC dispatches after HW-4's re-verify (its `set_mic` ordering
changes under F5).

### Dispatch log (3b)

* **16:3x EDT** — wave 3b launched on Opus: HW-2 (task_40), HW-5
  (task_41), HW-7 (task_42, GATE-0b-style rule-3 exception: gate only in
  an emulated aarch64 container, ≤ 2 runs), HW-FW (task_43). HW-MIC
  (task_44) held until HW-4's re-verify closes. Memory 231 GB available;
  zero pytest/sim processes at dispatch. HW-4 correction pass still
  running.
* **16:5x EDT — HW-4 correction pass COMPLETE; H3/H4 now MET on the real
  array:** duplex open (playback first = the capture clock); 751 × 1,920 B
  frames, 30.04 s @ 24 kHz, raw ch1 30.04 s @ 16 kHz, ratio 1.500000, 0
  errors/overflows/drops, `bytes_sent_to_dac 0`; ch1 −42.54 dBFS vs ch0
  −55.68 (13 dB gap = the ASR beam); fixtures sha 4e9cc71a… /
  b4806c06…. F2 reader race fixed (seed S9 RED→green, thread alive); F5
  device before session; F3 13 `noqa` → 0; F4 format clean (one stray
  reflow reverted); F6 duplex check everywhere the owner reads. 30 + 520
  passed; 12 seeds RED; 17/16 guard ledger (the declared 13:33 orphan).
  28 rows MET; O1 owner-gated, blocked on HW-MIC not on hardware. Narrow
  re-verify sent; HW-MIC dispatches on its ACCEPT.
* **17:0x EDT** — HW-FW executor returned COMPLETE: 27/27 rows;
  `deploy/orin/{nftables.conf (182 lines), nftables.service,
  containers.conf, README.md}`; `tests/test_hwfw_nftables.py` (19 tests,
  stdlib tokenizer); `nft` v1.1.6 present — unprivileged `nft -c -f`
  parses fully and fails only at netlink cache init, so N1 asserts zero
  `file:line:col` diagnostics (characterised on four deliberate mistakes:
  catches syntax/undefined vars/unknown hooks/bad CIDRs, not kernel-side
  checks). Policy: input drop (lo; panel 8765 dropped off-lo above every
  accept; ssh on wan/lte/con/ts never on `$rnic`; tailscale; DHCP; DDS
  7400–7500 only on `$rnic`; Livox only on `$lnic`; counted drop for DDS
  elsewhere); forward drop, zero accepts; output accept with multicast/
  unicast DDS + Livox confined; `bridge parcel_l2` forward drop;
  `containers.conf` not included by default. Seeds S1–S3 RED. **Key
  finding: `nft -c` accepts a ruleset that forwards the robot LAN onto
  Wi-Fi — only the structural test objects.** `docs/BOX_DAY.md` B-fw row
  + one bullet updated (2,494 words). Verifier (Fable) dispatched.
* **HW-4 CLOSED 17:1x — FINAL ACCEPT-WITH-NOTES.** Verifier's own probe:
  124 frames / 5.0 s from the real array through the corrected product
  gateway (−36.2 dBFS, DAC stream = the array's `hw:1,0`, 0 bytes out);
  open order playback → input → reader; every failure path closes both;
  slow-open fake 10/10; F5 through the real `build_runtime`: typed
  `ArrayDeviceError`, `lane.session_id None`, no spend; 0 `noqa`; A10
  pins `_voice_identity` + `_on_event`. One-line final note (teardown
  should also catch `PortAudioError`) sent to the executor. **Wave 3a:
  five of five closed.** O1 (through-air session) owner-gated on HW-MIC.
* **17:1x EDT** — HW-MIC (task_44) launched on Opus (mkdir-lock on
  `web_panel.py`; HW-2's region there is live).
* **HW-4 final note applied 17:2x:** `_teardown_errors()` widens the named
  tuple by PortAudio's class at the two close paths (an unplug-time
  `PortAudioError` would also have escaped `runtime._realtime_idle_hangup`'s
  `except (OSError, RuntimeError, TypeError, ValueError)`); two guards; seed
  S13 RED; 32 passed; 522 related; 0 `noqa`. Status doc now attributes by
  fence (shared files carry HW-2/HW-5/HW-7 regions too).
* **17:3x EDT** — HW-5 executor returned COMPLETE: R1–R12 MET, R13 MET
  (one failure attributed to HW-7's in-flight `ci_gate.py`), R14
  half-met (`ruff format --check` was never clean tree-wide — a
  pre-registration defect); six flat scalars admitted (`venue`,
  `backend`, `perception.lidar_band_min_m/_max_m`,
  `perception.lidar_min_populated_bins`,
  `perception.lidar_extrinsic_xyz_rpy`); `configs/robot.go2_edu_plus.yaml`
  + `configs/navigation/venues/go2_edu_plus.yaml`; `venue=` wired —
  under the profile `adapter_for` moves exactly `l2.cloud`/`l2.imu` to
  unserved with HW-3's remedy (HW-3 F4 closed); seven seeds RED; 1,179
  passed. **F1 (design, confirmed by parcel-6c against
  `admission.py:707-716`): CAP-1 has no hardware capability — all eight
  names are semantic-source and bind here; the desktop refusal is
  VENUE-1's `RealSenseUnavailable … No device connected`; the declaration
  is proved by the `semantic_source: oracle` counterfactual.** Design §4
  S14, §5.8, §9 corrected. F2: declaration in
  `configs/navigation/venues/` (CAP-1's top-level glob pins
  non-declaring). HW-2 owes five read sites (`DECLARED_AHEAD`). Verifier
  (Fable) dispatched.
* **HW-FW — HOLD** (verifier Fable, ~17:05–17:45; record
  `~/.cache/parcel-verify/hwfw/VERDICT.md`). Load-bearing parts right
  (forward drop, zero accepts; bridge twin drop; DDS confined; panel
  lo-only; registration before measurement; S2 reproduced; two verifier
  seeds RED). **H1 lockout:** research fact 18 puts the dock's RJ45s on
  192.168.123.0/24 — a laptop cable behind the robot NIC puts B-con's ssh
  SYN on `$rnic`, excluded by design → dropped; nothing reads the shell's
  interface before `nft -f`. **H2 fail-open boot:** one atomic batch; a
  missing `CONFIG_NF_TABLES_BRIDGE` or any error → unit failed, zero
  tables (verifier read `libnftables.c`: root `-c` does catch it; boot
  does not recover). F1 N1 is vacuous (anchors `^nftables\.conf:`; nft
  prints the path as passed). F2 three lockout-class seeds pass green
  (established/related, output policy, ND). F3 ssh on `$lteif`/`$wanif`
  vs ADR 0002 tailnet-only. F4 dead-man timer leaves the unit enabled.
  F5 Docker bridge traffic. Correction pass sent 17:5x.
* **18:0x EDT** — HW-7 executor returned COMPLETE: P/S/X/Y/L/G rows MET;
  **E1 emulation MISSED** (no docker/podman/qemu/nspawn on this host;
  binfmt has only python3.14) → E2/E3 not measurable; E4 = a ROW-SET
  proof under `PARCEL_HOST_ARCH=aarch64`, labelled not-an-execution-
  proof; **zero `--tier` runs made**. 13 rows both ways; architecture
  alone changes no row; vendor-venv picture (no mujoco) flips exactly
  `unitree-assets`, `hard-safety`, `tier-coverage`, `default-suite` to
  typed SKIP (seed S1 with mujoco hidden from a live interpreter). Premise
  correction: no commit-tier stage needs CUDA/GPU/ort/x86 wheel; MuJoCo
  is on aarch64; skips gate on capability (a test forbids
  `cuda`/`onnxruntime`/`portaudio` from the requirement table). **Design
  corrected (parcel-6c):** §5.2 Jetson wheel = `pypi.jetson-ai-lab.io`,
  1.24.0 cp310, cu126 = cu128 wheel; §4 S26; H3 (`load_guard` guards
  contention not speed) noted before §6. `ci_gate.py` +398 (HW-6's 144
  lines untouched); `ci.yml` +70 fenced schedule-only job; arm64 PortAudio
  .deb pins hashed; `piper_linux_aarch64.tar.gz` exists at the pinned tag;
  `install_perception_jetson.sh`; 35 tests; D5 the `host` row is LAST
  (XD-1's test owns position 0). Verifier (Fable) dispatched.
* **18:1x EDT** — HW-MIC executor returned COMPLETE: 15/15 rows; `POST
  /api/realtime/mic {"open": bool}` (200 the state that now holds; 400
  non-boolean; 403 `_authorize_post`; 404 no ear; 409 browser ear /
  gateway not running; 503 `ArrayDeviceError` verbatim); the `:494`
  gate's 404 TEXT names the fitted kind, condition unchanged; UI
  `startMic()` branches on kind, "ear: array"; browser path byte-
  identical (three function hashes = HEAD; seed S7). **R12 on hardware
  through the real handler + real `build_runtime` + real gateway + real
  array (only `lane.ensure_session` stubbed, $0): arm 200 in 19.9 ms;
  250 × 1,920 B = 10.000 s @ 24 kHz; 0 errors; 0 bytes to the amp;
  `ensure_session` once, AFTER the input stream — HW-4's F5 ordering
  proved on hardware.** D1 first R4 was self-satisfying (seed S3 passed
  against it; fixed to one shared event log, then RED). 139 neighbours;
  0 `noqa`; 14/14 guard ledger. **HW-4's O1 (through-air session) is now
  unblocked — owner-gated.** Verifier (Fable) dispatched.
* **18:2x EDT** — HW-2 executor returned COMPLETE: all rows MET (A–F),
  45/45 new tests, 561 + 360 neighbours, 7 seeds RED. Typed source
  `core/input_health:CommissionedScanSource` (+ `ScanDatum`,
  `ScanEvidenceSource`) — the scan twin of `CommissionedStateSource`,
  latches on duplicate/regressed sequence or epoch change; read site
  `runtime.py:13822` in `_evaluate_dispatch_input_health` (after
  `scan_evidence_from_observation`; only when the backend's source
  declares PHYSICAL). **Amendment 1 (honest):** a replay-fed backend
  declares REPLAY (synthetic ⇒ latches); only `LiveGo2Sources` (DDS/UDP
  transports) declares PHYSICAL — no config value can mint it (the W0-A
  defect); B1 split into B1a (through `build_runtime`: replay still
  latches) and B1b (`RobotRuntime(config, backend)` with the vendor
  transports injected: no SCAN fault; POSE still latches — not migrated,
  pinned). Fixture `tests/data/hw2_stage0_replay.jsonl` synthesised
  (header says so; real SDK2 datagrams from HW-3's builder). **D1:** the
  sixth envelope term is an additive V2 layer after HW-6's fence
  (`ENVELOPE_TERMS_V2`, `derive_envelope_v2`, a top-level `scan_age:`
  block V1 ignores) — NOT gate-printed (wiring needs HW-7's `ci_gate.py`
  + five HW-6 assertions; test e7 pins the gap). D2 `backend:` inert
  until HW-5's key (landed). D5 `backends/__init__` export dragged
  `brain`/`instructnav` into the commissioning import chain (W0-B) —
  fixed at source. `--duration` on `observe`. Verifier (Fable)
  dispatched.
* **HW-5 — HOLD** (verifier Fable, ~17:35–18:35; record
  `~/.cache/parcel-verify/hw5/VERDICT.md`). Everything registered
  reproduces (R1–R13; seeds; locked base byte-identical; no truth field;
  F1 right — all eight capabilities bind here; oracle counterfactual
  clean; `venues/` placement LEGITIMATE — CAP-1's loop guards "no new
  fail-closed default", R12 pins one declaring file tree-wide). **H1:
  the profile does not load through the launcher** — HW-2's
  `_build_backend(store.section("backend"))` wants a SECTION
  (`kind/fixture/band{…}/interface`); HW-5 shipped `backend: go2` + four
  orphaned `perception.lidar_*` scalars → `TypeError: configuration
  section 'backend' must be a mapping`; R11's pin was inert (the literal
  survives inside `_build_backend`). F1 own-line format; F2 a misspelled
  `PARCEL_PROFILE` degrades to 0/28 silently in the capture lane.
  **Design decisions (parcel-6c, §5.8):** backend subtree in HW-2's
  vocabulary; lidar scalars go; extrinsic = six reals `xyz_rpy` (HW-2
  converts); both NIC keys stay, set from one B9 read, pinned equal.
  Correction pass sent 19:0x (omit the extrinsic until HW-2 accepts
  `xyz_rpy`).
* **19:1x EDT — HW-FW correction pass COMPLETE:** H1 README §0.5 reads
  the shell's interface before any load; if `$rnic`, STOP with two
  recorded routes (serial/tailnet, or ONE dated template rule for the
  laptop's /32 above the DDS rules, removed with B-con); `$rnic` = "the
  NIC holding 192.168.123.18". H2 three files — inet, bridge (tolerated
  `ExecStart=-`), and a variable-free address-based lockdown loaded by
  `OnFailure=` (no `[Install]`). F1 live (`dropp` copy → diagnostic at
  :77); P17–P19 + seeds; F3 ssh `{conif, tsif}` + RFC1918 `$wanif`;
  F4 dead-man disables the unit; F5 docker bridge accept. 24 tests; 15
  seeds each RED; 2,493 words. Narrow re-verify sent.
* **HW-FW FINAL — ACCEPT-WITH-NOTES (19:2x).** Re-verify: 24 passed;
  `nft -c -f` zero diagnostics on all three files, one on the broken
  copy; both units pass `systemd-analyze verify`; rule-walks hold (route
  2 template accepts .99/tcp-22 only; DDS off-`$rnic` still drops;
  `$lteif` ssh drops); lockdown has its own pins (P16b RED on two
  seeds). Required doc fix R2-F1 sent (route-2 owners have no shell
  under lockdown — keep serial). Double failure stated: main + lockdown
  both failing = zero tables, fail-open; the only fail-closed escalation
  (`nmcli networking off`) is an owner decision — recorded for §7.

### Tree-state change noticed 19:3x (parcel-6c)

The OWNER committed from their side: `939001e` (12:49:44, "feat: land
wave 2 batch B reliability and coverage work") = exactly the 117 paths
parcel-6c had staged (batch B + GATE-0b + the integrator gate evidence),
and `0ce1c5f` (14:32, "docs: update hardware transition status and
roadmap") = the owner's own edits to `docs/CONVERSATIONAL_AUTONOMY_HIGH_
LEVEL_DESIGN.md` and `docs/ROBOT_ENGINEERING_EXECUTIVE_SUMMARY.md`.
Nothing was lost; `CLAUDE.md` (the anti-crash rule) is the one path still
staged; wave 3's edits are unstaged on top. `CODEBASE_INDEX.md` was not
regenerated with those commits — the integrator regenerates it at the
wave-3 close. Also: the HW-7 verifier's scratch cleanup deleted this
session's `commit_paths.txt`/`commit_message.txt` (regenerable; no tree
effect).
* **HW-FW CLOSED 19:3x** — R2-F1 both halves (README §0.5 route-2 blind
  spot + §2 item 5; the lockdown file carries the same commented `/32`
  template, P16b pins `/32`-only — seeds `/24` and no-saddr RED); notes
  N2/N3/N4/N6 applied; 24 passed; `nft -c` clean on all three files.
* **HW-MIC — ACCEPT-WITH-NOTES, one FIX** (verifier Fable, ~18:15–19:35;
  record `~/.cache/parcel-verify/hwmic/VERDICT.md`). All 15 rows, seeds
  (S3 with D1's fix, S7, auth-skip, 409→200), OWNS (fences 348–437 and
  585–605; HW-2's 806–902/932–934 intact; `:494` logic unchanged; UI
  hashes = HEAD) reproduce; verifier's own arm on the real array: 200 in
  17.9 ms, 124 × 1,920 B in 5.0 s, 0 errors, 0 bytes out, event log
  output → input → `ensure_session` once; no-key path = `CODE_NO_TRANSPORT`
  → 200 `{"open": false}`, no network. **F1 (on hardware):** two
  simultaneous arms → first 200, second 503 (EBUSY) whose failure path
  clobbered `_mic_open` → a billed, "Listening", DEAF ear for 2 s (a
  double-click). Fix: lock around `set_mic` in the route + UI re-entry
  guard + race row/seed; in-gateway "opening" guard → HW-4's owner.
  Correction pass sent 19:4x; narrow re-verify after.
* **HW-2 — HOLD** (verifier Fable, ~18:25–19:45; record
  `~/.cache/parcel-verify/hw2/VERDICT.md`). Authority seam sound
  (Amendment 1 honest and pre-measurement; B1a latches through
  `build_runtime` with HW-5's key, zero patches; B1b with only the vendor
  transports faked → no SCAN fault; no config mints PHYSICAL; fences and
  MUST-NOT-TOUCH clean; HW-6's fence byte-identical; `--duration` real;
  W0-B 75 green). **H1:** `CommissionedScanSource` latches on an
  IDENTITY re-read (the sibling `CommissionedStateSource` exempts it) —
  one corrupt Livox datagram → `observe()` raises → the loop re-joins on
  the retained observation → permanent `payload_malformed` LATCHED_STOP
  the e-stop clear cannot clear (reproduced through `RobotRuntime`).
  **H2:** the evidence is not bound to the observation graded (two
  threads on one socket) — "stricter or equal" is false. F1–F7 incl.
  F3 (no live scan transport on the product path; a blocking socket
  would hang `observe()`), F2 (fabricated pose before the first sample),
  F5 (origin not visible in the latch record; `name` bare `go2`), F6
  (`safety.require_physical_inputs` not introducible → HW-5 addendum).
  Correction pass sent 19:5x (datum travels with its observation;
  identity re-read exempt; Amendment 2 before re-measurement).
* **19:5x — HW-5 correction pass COMPLETE:** `backend:` now in HW-2's
  vocabulary (`kind: go2`, `band: {0.10, 0.60, 1}`, `interface` a B9
  read; extrinsic omitted until HW-2 accepts `xyz_rpy`); the four lidar
  scalars gone; launcher rows measured (NIC key → SDK not importable →
  D455 only where the backend builds; `backend.kin` refused by name);
  S8 (the H1 defect restored) → 9 failed; F2 `ProfileError` propagates
  in the capture lane; 868 passed across eleven files incl. HW-2's 45;
  `DECLARED_AHEAD = {}`. Design §5.8/§9 refusal order corrected by
  parcel-6c. Addendum re-sent: admit `safety.require_physical_inputs`.
* **20:0x — HW-MIC correction pass COMPLETE:** route-level
  `_ARRAY_MIC_ROUTE_LOCK` around the whole `set_mic` (open and close) +
  UI re-entry guard; **race row on the real array: two simultaneous arms
  → 200 ×2, one device open, `device_refusals 0`, 49 frames in the next
  2 s (was 0)**; R12 re-run 249 frames / 9.96 s, 0 bytes out; seeds S8
  (drop the lock → `assert 2 == 1`), S9, S10, S7 RED; 16 + 140 passed;
  0 `noqa`; lock ledger kept. In-gateway "opening" guard → HW-4's owner
  (HO-5). Narrow re-verify sent.
* **20:1x — HW-7 correction pass COMPLETE:** `summarize` (fenced; the
  integrator-authorised touch) prints `RESULT: PASS — N hard gate(s)
  green, M SKIPPED on this host: …` when any hard row is skipped; the
  no-skip and FAIL branches byte-identical to the index's. F2 total
  fail-safe via a `contextlib.suppress` subclass (no except clause):
  a refusing finder → skips with `raised …` evidence; a probe that
  cannot answer → `host` error, zero skips (declares nothing); four
  exception types. F3 interpreter + per-capability evidence in every
  skip row (two independent `find_spec` calls, so a lying probe
  contradicts itself in print). F4 probe-truth test (lying probe → 1
  failed in HW-7's own file). F5 D8; F6 `pipefail` + the py312 lock (pip
  rejects `-e .` as a constraint — stripped). 45 + 91 passed; 7/7/0;
  `ci_gate.py` +738/−1. Narrow re-verify sent.
* **HW-MIC CLOSED 20:2x — FINAL ACCEPT-WITH-NOTES.** Verifier's own
  probes on the real array: double arm → 200/200, one device open, 50
  frames / 2 s; double disarm → 200/200, streams closed; arm+disarm
  together → serialised, consistent. Lock read: non-reentrant, `with`-
  scoped, no re-entry path, different gateway from the browser path.
  **HO-5 (real, HW-4's file):** `close_mic`/`stop()` from `runtime.py`
  bypass the route lock — a hang-up inside an arm's window leaves
  `mic_open True` with no streams and a dead reader (fake device);
  bounded pass sent to HW-4's executor 20:2x (gateway-level lock over
  `set_mic`/`close_mic`/`stop`).

### Noticed 20:3x (parcel-6c): a Codex review packet

`scrum/20260823/task_1/` (README, DESIGN, PREREGISTRATION, SYMBOL_CENSUS,
CURRENT_STRUCTURE_AUDIT, TEST_AND_EVAL_PLAN, FABLE_REVIEW_BRIEF; 15:29–15:40
local) — "ARCH-1 boundary-first codebase decomposition", author Codex,
**REVIEW-ONLY · NOT DISPATCHED**, required reviewer Fable. Not part of the
owner's standing instruction to this session; untouched; reported to the
owner in the close-out. Wave 3 continues.
* **20:3x — HW-5 addendum COMPLETE:** `safety.require_physical_inputs`
  admitted (the profile's `safety:` block pinned as exactly that one key,
  `true`; the six thresholds still refused; `false` refused); switch
  reaches `RobotRuntime._require_physical_inputs`; **two-arm launcher
  proof through `build_runtime` with HW-2's fixture: key present →
  LATCHED_STOP (pose + scan `sim_fixture_forbidden`), key deleted → HOLD
  with both passing** — the defect reproduced, not described; seeds
  S13/S14/S15 RED; 132 passed; PREREGISTRATION amended before
  measurement. Narrow re-verify sent.
* **HW-7 CLOSED 20:4x — FINAL ACCEPT-WITH-NOTES.** `summarize` side by
  side with the index's: identical on no-skip and on one-red; vendor-venv
  → `PASS — 6 hard gate(s) green, 4 SKIPPED on this host: …`; F2 seeds
  through the real tier (refusing finder → skips with `raised …`; probe
  raising → `host` error, 0 skips; KeyError finder → 8 skips, headline
  names all); lying probe → the printed row contradicts itself and HW-7's
  own test reds; five HW-7 fences, others byte-identical; `ci.yml` gate
  step `pipefail` + 17 constraints, 0 editable; 136 passed. Optional
  N7: treat a RAISED probe as unprobeable (non-gating `host` error)
  rather than absent — a capable host with broken import machinery would
  otherwise exit 0 on hard SKIPs.
* **20:5x — HW-4 HO-5 closed:** `_mic_lock` (RLock) across
  `set_mic/close_mic/stop` (never the callback-side `_lock`; strict lock
  order); re-entrancy handled by a post-open consistency check;
  `mic_open` = flag ∧ both streams; three race tests (one pins the
  serialisation itself), seed S14 RED; real-array phases A/B/C all
  self-consistent (hang-up 5 ms behind an arm → serialised, shut; clean
  5 s arm 124 frames; stop consistent). 35 + 16 + 541 passed. Last
  narrow re-verify sent.
* **HW-5 CLOSED 21:0x — FINAL ACCEPT-WITH-NOTES.** Verifier by hand:
  launcher refusal chain (NIC → SDK → `backend.kin` by a dynamic
  allow-list that tracks HW-2's growth); the two-arm switch proof (key
  true → LATCHED_STOP with pose+scan forbidden; deleted → HOLD, the
  defect; `false` refused by the directional rule); seeded threshold
  reddens the exact-block pin; F2 `ProfileError` live; 140/140 across
  four suites incl. HW-2's 55. Design §5.8/§9 final-shape text corrected
  by parcel-6c. Non-blocking: N8 (a dated Amendment 2 for the
  correction-pass rows) left with the executor's docs; N10 A3 hatch =
  stop signal if it fires in CI.

## Integrator close — 2026-08-23 (host ~16:1x–16:2x EDT)

**Final verdicts logged after the owner's pause lifted:**

- **HW-4 (task_37) — FINAL ACCEPT-WITH-NOTES.** HO-5 `_mic_lock` serialisation
  verified by audit, race probes, re-entrant probe, S14 RED. The verifier's
  note that the real-array re-arm was "skipped at the owner's refusal" is its
  own framing of the pause; no such refusal occurred — the through-air O1
  session remains an open owner decision.
- **HW-2 (task_40) — HOLD → correction → FINAL ACCEPT-WITH-NOTES.** The full
  verdict (`~/.cache/parcel-verify/hw2/VERDICT.md`) found two product defects:
  H1 (CommissionedScanSource latched on identity re-reads — the product
  re-reads on observe() failure and on e-stop clear, so one corrupt Livox
  datagram or one operator clear bricked the join until restart) and H2 (scan
  evidence not bound to the observation being graded — a spatial-thread
  observe() could remove a SCAN fault the loop's observation warranted).
  Correction (same executor, Amendment 2 stamped 15:29:06 before first
  re-measurement): ScanDatum travels with its observation
  (`scan_datum_for(observation)`, identity-keyed, GRADED_HISTORY=8), identity
  re-read exempt exactly as CommissionedStateSource, a DIFFERENT datum under a
  repeated sequence still latches; `receive_frames(on_refusal=…)` makes a
  corrupt datagram cost one datagram, not the tick; F2 no fabricated pose
  (typed refusal until first state sample); F3 configured nonblocking Mid-360
  socket opened from `_build_backend` (live transport now exists on the
  product path — never exercised on a real NIC/sensor); F5
  scan_source_origin/name published in input_health_latch(); F7 fixture
  generator takes --out. Final re-verify: both HOLD reproductions re-run green
  through a real RobotRuntime, S8/S3b RED, 160 through the wrapper, fences
  byte-identical (HW-6 sha cbd37558…), ratchet 7/7/0, ledger 50/50.
  Residuals (non-blocking): stop-path "must not inherit" comment lives in
  DESIGN not go2.py; superseded HW-5 handoff bullet above the F6 entry;
  drain_budget_s unenforced under a pathological all-corrupt flood.
- **Carried to the design owner / integrator (from HW-2 F6/N1):**
  `safety.require_physical_inputs` base-vs-introducible admission is landed
  via HW-5; **HW-6b** (wire V2 envelope loader so the gate row names
  scan_age_s instead of silently reading V1) remains an accepted open debt.

**Close gate.** First commit-tier run (16:17:46, guard label
`integrator-close-w3`): RED — `default-suite` 2 failures, both dispositioned
NOT wave-3 regressions: `test_dynamic_costs.py::test_cost_field_vectorization_performance`
is the documented R26 powersave-governor perf-pin noise on a module untouched
since e5d4956 (fails 15/15 on an idle host by R26's own measurement; 0.0034 s
vs 0.002 pin reproduced standalone); `test_hw7_gate_aarch64.py::test_a_hostile_meta_path_finder_is_absence_not_a_crash`
transient under xdist worker interference — passes standalone and 45/45 with
its module. Second run: see RESULT line below (committed only on green).

**Tree at close:** HEAD e15e466 → this commit; owner had already committed
batch B as 939001e and docs as 0ce1c5f. ~65 paths staged by explicit list.
Immediately after this commit the owner redirected the program: conversational
companion-dog prototype, decomposition-first (ARCH-1 review), reduced testing
policy. See scrum/20260823/.

**Integrator close repair (recorded, not a card).** The second gate run
isolated the hw7 red to a determinism defect in the wave-3 test itself:
`test_a_hostile_meta_path_finder_is_absence_not_a_crash` assumed a fresh
interpreter, but `importlib.util.find_spec` returns `sys.modules[m].__spec__`
without consulting `sys.meta_path` when the module is already imported — and
under `--dist loadfile` the file shares a worker with sim tests that import
mujoco. Reproduced deterministically (`import mujoco` then run the test →
`assert True is False` at :399). Repair: the test now pops `mujoco*` from
`sys.modules` for its duration and restores in `finally` (comment states the
constraint). 45/45 with mujoco pre-imported; ruff clean; third gate run green
(RESULT line below). This is the integrator's close-time repair inside HW-7's
OWNS, the same class as a merge-conflict resolution.

**Third gate run (16:2x, label `integrator-close-w3`): PASS — every hard gate
green.** default-suite parallel 9813 passed / 17 skipped / 1 xfailed in 64.0s,
serial confirm 9 passed. ruff 7/7/0. This is the wave-3 integrated close.
