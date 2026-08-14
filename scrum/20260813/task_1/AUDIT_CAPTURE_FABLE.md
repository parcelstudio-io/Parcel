# Fable audit — capture stack (tranches PS-1 + PS-2), 2026-08-13

**Method:** 5 adversarial hunters with executed-repro discipline, then a
**2-refuter panel on every blocking/major finding** (upheld requires both
refuters to fail to refute). 63 agents, 4.84 M tokens, 2,274 tool calls.
**Gate at PS-2 close:** `RESULT: PASS — every hard gate green`, 4,878 passed,
elapsed 209.8 s — including `frozen-digest-sentinels` byte-identical and
`hard-safety collisions=0 false_arrival=0`, so **nothing either tranche built
moved a frozen or safety surface**.

## Verdict: NOT session-ready as audited. 10 findings upheld, 19 refuted.

29 blocking/major findings went to panel. **10 survived; 19 were refuted or
downgraded** — the panels did most of the work, and several of the loudest
claims (three "BLOCKING" sync-event defects, the "plausibility silences a
recording" claim, five run-sheet contradictions) collapsed on contact. Fix
tranche **PS-3** is dispatched against the survivors.

### Upheld — ranked

| # | Sev | Finding | Where |
|---|---|---|---|
| 1 | **BLOCKING** | `read_rosbag2_mcap()` reads the `Chunk.records` length prefix as **uint32**; the MCAP spec says **uint64**. Every uncompressed-chunked rosbag2 bag reads as CORRUPT / 0 messages — and the sidecar then stamps that verdict on a **healthy** primary recording | `rosbag2.py:792` used at `:1060` |
| 2 | **BLOCKING** | The preflight half of the ingest fix was never closed: `run_preflight` still defaults to `unavailable_reader_factory`, `main()` never passes a factory, and the refusal names a `--reader-module` flag **that does not exist**. The tool whose job is proving channels live before the session cannot reach one | `preflight.py:3283`, `:3936-3950`, msg `:2323-2327` |
| 3 | **MAJOR** | **No no-arm pin covers `rosbag2.py`, `budget.py`, `rehearse.py`, `__init__.py`.** A literal `create_publisher("/cmd_vel")` + `SportClient().Move(0.5,0,0)` appended to all four passed the entire **795-test** capture suite, rc=0 | those four files |
| 4 | **MAJOR** *(orig BLOCKING)* | `storage_config_yaml()` emits `compression: ""` and `compressionLevel: ""` for both writer profiles; `rosbag2_storage_mcap` rejects empty-string enums ⇒ `ros2 bag record` **exits 1, zero bytes recorded** | `rosbag2.py:499-500,509-510` |
| 5 | **MAJOR** *(orig BLOCKING)* | `BANDWIDTH_BUDGET.md` is **stale by 8.6%** and is the number of record on every operator sheet (doc 84.60 MiB/s vs code 91.870) | `BANDWIDTH_BUDGET.md:60,202,219-221` |
| 6 | **MAJOR** | Tonight's checklist **never installs or rehearses the ROS driver nodes** that 94% of the byte budget depends on. Its whole install inventory is `pip install pyrealsense2`, `librealsense2-utils`, `fio` — but the recorder of record records **topics**, and no topic exists without a driver publishing it | `TONIGHT_CHECKLIST.md:392-470,735-830` |
| 7 | MINOR *(orig MAJOR)* | `ReadOnlyHandle` is **not** structural incapacity: `__slots__` makes `_target` an ordinary descriptor, so `handle._target.create_publisher(...)` works; `session._rclpy` hands out the whole rclpy module; `NEVER_ALLOWED` is a construction-time check one `object.__setattr__` undoes | `ingest/base.py:342` |
| 8 | MINOR *(orig MAJOR)* | The ingest AST pin globs `*.py` — **it does not descend into subdirectories** — and is defeated by ordinary aliasing. 6 of 7 evasions passed both halves; a planted module publishing `/cmd_vel` passed all 47 pin tests | `test_capture_ingest.py:87` |
| 9 | MINOR *(orig MAJOR)* | **202 of 743 executable lines (27.2%)** in the three live adapters have never executed, while the status doc claims the decoders are exercised | `ingest/l2.py:120-191`, `realsense.py:126-152` |
| 10 | MINOR *(orig MAJOR)* | `go2.sportmodestate` is CRITICAL and its decoder emits IMU + foot-force samples, but `classify_channel()` returns `()` for it — every sample **silently discarded** by the plausibility layer | `preflight.py:571-583` |

### The two that would have cost the session outright

Findings 1 and 4 are the same story from both ends: **the primary recorder
would not have started, and if it had, we would have been told its output was
corrupt.** Both are in code written specifically to fix the previous audit's
blocking defect — which is the honest lesson of this tranche. A fix that is
never executed against a real artifact is a hypothesis. Neither of these could
be caught by any test that does not construct real MCAP bytes or validate the
emitted YAML against the plugin's actual schema, and neither tranche did.

### What the refutation panels killed

Worth recording, because acting on these would have burned session-eve hours:

- **Three sync-event "BLOCKING" claims** — confidently-wrong offsets, power-cycle
  tick re-basing, K=2 step absorption — all downgraded to MINOR/INFO. The
  mechanisms reproduce; the operational consequences did not.
- **"A plausibility refusal silences a recording"** → INFO. The guard holds.
- **Five run-sheet contradictions** (mount-before-power, circular pre-stand
  gate, FOV-gate ordering, "All 28" channel claims, stale counts) → all
  refuted. PS-F's session pack survived adversarial reading substantially
  intact, which is a real result: it is the artifact a person follows tomorrow.
- **`orin.tegrastats` has no producer** — fact upheld, severity cut to MINOR;
  the honest-refusal machinery was working as designed.

### Clean under executed attack

- **No frozen or safety surface moved** — `git diff` over `runtime.py`,
  `pose.py`, `navigation/**`, `route_memory/**`, `evals/**`, `bags/`
  implementation: empty. Confirmed independently by the gate's
  `frozen-digest-sentinels` and `hard-safety` rows.
- **No vendor SDK in `.parcel/`** — `rclpy`, `cyclonedds`, `unitree_sdk2py`,
  `pyrealsense2`, `cv2`, `mcap` all still absent. The four config-level motion
  guarantees (`runtime.py:385-391`, the factory flag gates, no production
  caller of `create_control_manager`, absent SDK) are intact; no PS card
  weakened one.
- **Per-channel sequence** does what it claims, proven against the real
  `bags.recorder` with two worlds that produce byte-identical bags.

## PS-3 closure — all 10 upheld findings fixed, and 2 more found in the fixing

**Closing gate (my run, 2026-08-13T14:22:28Z): `RESULT: PASS — every hard gate
green`, 5,071 passed, elapsed 231.7 s.** `frozen-digest-sentinels` byte-identical
and `hard-safety collisions=0 false_arrival=0` still hold.

**The fix tranche executed against reality rather than against the spec.**
PS-M found a ROS 2 Jazzy rootfs already in the repo
(`.cache/external-evals/runtime/ros-jazzy-base-sandbox`, carrying the real
`librosbag2_storage_mcap.so` and `libmcap.so`) and drove
`rosbag2_py.SequentialWriter` under `bwrap --unshare-net --unshare-pid`. So both
recorder defects were reproduced against **real bags written by libmcap 1.3.1
and the real storage-config parser** — no node, no publisher, no network, no
install. That is the standard the earlier tranches missed.

- **F1 (uint64)** proved at byte level: the chunk header declares 2402 bytes and
  `32 + len(compression) + 8 + 2362 = 2402`; a uint32 prefix balances at 2398.
  Four bytes early, the first inner record reads `opcode=0x00
  length=1301425422336`. The consequence was **worse than "stamped corrupt"** —
  the sidecar *refused to exist*. After the fix, the same bag reads
  `present, 40 of 39 expected messages`. The full width table was then walked
  magic-to-magic across opcodes 0x01–0x0F with **zero leftover bytes**: exactly
  one width was wrong, and `MCAP_INTEGER_WIDTHS` now pins the table.
- **F2 (empty-string enums)** confirmed against the real plugin, both profiles:
  `yaml-cpp: error at line 12, column 14: Failed to convert field 'compression'
  → OPEN FAILED, EXIT=1`. Two corrections to my brief: the level set includes
  `Slow` (five values, not four), and `compressionLevel: ""` is fatal
  **independently** — fixing only `compression` would still have recorded nothing.

### Two new blocking defects, found only because the fixers executed things

- **PS-M / F3 — the argv would not have parsed on Humble.** Humble's
  `ros2bag/verb/record.py` declares `topics` as **positional** and contains no
  `keyboard`: `--topics`, `--disable-keyboard-controls` and `--node-name` **do
  not exist there**, so argparse exits 2 and records zero bytes. The default is
  now `RosDistro.HUMBLE` emitting the intersection form, plus a `--verify-help`
  check that turns "discovered tomorrow morning" into a 4-second refusal.
  Related: the default `--max-bag-size` of 4 GiB splits every **48 s** at the
  budget's rate, which would have tripped the take script's "more than one
  `.mcap` ⇒ STOP" rule **37 times** inside the non-skippable core block. Now 0.
- **PS-N / F1c — a defect the fix itself introduced, caught by running it.**
  `python -m scripts.parcel_capture.preflight` executes the file as `__main__`;
  the ingest package then imports `..preflight` *by name* and gets a second
  module object with a different `SampleReceipt` class ⇒
  `probe_contract_violation`. On the Orin with rclpy sourced and the dog
  publishing, this would have turned **all 23 served channels ABSENT, naming our
  own code as the cause.** Fixed with a `sys.modules.setdefault` canonicalisation
  in the `__main__` guard, pinned by a subprocess test through the real entry point.

### Safety fix verified by me, not by report

I re-ran the auditor's exact attack against the rebuilt pin: appending a literal
`create_publisher("/cmd_vel")` + `SportClient().Move(0.5, 0.0, 0.0)` to
`rosbag2.py` — previously green across all 795 tests — now yields
`FAILED tests/test_no_arm_pin.py::test_no_module_in_the_capture_stack_names_or_assembles_a_command_surface[scripts/parcel_capture/rosbag2.py]`.
The pin globs `rglob("*.py")` and cross-checks its own coverage against an
independently computed `os.walk`. Source restored byte-identically (sha256
match, `git diff` empty).

## What this audit does not prove

It is a software audit on a machine with **no robot, no ROS, and none of the
vendor SDKs**. It cannot prove any adapter works against real hardware — 27.2%
of the live adapter code has never executed and will first run on the dog.
Every channel claim in the matrix remains **documentation-derived**; the
session's first 45 minutes exists to replace each with a measurement. And the
no-arm guarantee is now honest about being **defence in depth** — an absent
SDK plus config refusal plus a pin — rather than the structural impossibility
the code comments claimed.
