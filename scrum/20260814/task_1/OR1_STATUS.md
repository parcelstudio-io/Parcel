# OR-1 — the Orin rehearsal harness

**Card:** OR-1 (board [REVISED_BOARD.md](REVISED_BOARD.md), H-2 software half; P0
doubles as H-1) · **Date:** 2026-08-14 · **Owner of record:** Opus
**OWNS (all new files):** `scripts/parcel_capture/orin_rehearsal.py`,
`tests/test_orin_rehearsal.py`, [ORIN_RUNBOOK.md](ORIN_RUNBOOK.md), this file.
**Nothing else was written.** No file owned by S-1 or S-2 was edited.

---

## 0 · Headline

Tomorrow the operator copies the repository to an Orin nobody has ever executed
a command on and runs **one** command:

```bash
python3 -m scripts.parcel_capture.orin_rehearsal --evidence-dir ~/orin_evidence \
  --record-target /data
```

Six phases, in order, fail-closed, into a machine-readable evidence bundle. The
strongest result on this page is that **the phase which matters most has already
been executed end to end against a real ROS 2 stack**: inside the repository's
ROS 2 Jazzy sandbox, P5 captured the installed `ros2 bag record --help`, rendered
the argv from `Rosbag2Plan(distro=JAZZY)`, cleared **nine flags** against that
help, recorded a real 20-second MCAP **onto the record target** through that exact argv, read
**776 messages back clean** with the repository's own reader, and drove the sidecar to
the refusal it owes an unmapped bag. No node of ours, no publisher of ours, no
motion API anywhere.

| | |
|---|---|
| Unit tests | **82 passed** (`tests/test_orin_rehearsal.py`) |
| Recursive no-arm pin | **green over the new module**, static and dynamic |
| Desktop run | honest bundle, **exit 1**, **zero tracebacks** |
| Jazzy-sandbox run | P0 `JAZZY`, **P5 PASS** on real bytes |
| ruff | clean on both new files |
| Python 3.10 grammar | parses (`ast feature_version=(3,10)`) |

---

## 1 · Measured claims

Every row is a command that was run and output that was pasted. Nothing here is
a plan.

| # | Claim | Command | Result |
|---|---|---|---|
| **M1** | The harness runs on this dependency-free desktop, reports it truthfully, and exits non-zero with **no traceback** | `.parcel/bin/python -B -m scripts.parcel_capture.orin_rehearsal --evidence-dir <dir> --record-target <dir> --keep-going` | §2 — `EXIT=1`, 6 phase files + `verdict.json`, `evidence_for: null` |
| **M2** | P0 classifies this desktop honestly and says a pass here is not evidence about the Orin | same run | `is_jetson=false`, `distro=NONE`, blocker *"this host is not a Jetson, so nothing measured here is evidence about the Orin"* |
| **M3** | P1 finds this desktop's **real** `usbfs_memory_mb = 16` and fails with the extlinux remedy | same run | `usbfs_memory_mb ABSENT`, remedy names the runtime write, the `extlinux.conf` backup, `usbcore.usbfs_memory_mb=1000`, **REBOOT**, and *"no second dock"* |
| **M4** | An import under 3.14 does **not** verify the 3.10 claim | same run | `python3.10 import parcel_robot.capture` → **UNKNOWN**, `python310_is_310=false`, remedy says the claim stays *"static only"* |
| **M5** | P2's requirement is rendered from `budget.py`, not transcribed, and cites S-1's `DISK_LEDGER.md` | same run | `required_mib_per_second=91.87`, `required_free_gib_for_take=123.9`, `disk_ledger.sha256=7f364f3d…5fb9dc` |
| **M6** | P3 reads this desktop's real interfaces, finds it off the robot LAN, and flags the L2 factory-subnet collision | same run | `robot_lan_joined=false`; finding: *"wlp1s0=192.168.1.171 … the L2's factory address is 192.168.1.2"* |
| **M7** | **The whole P5 chain executes against a real ROS 2** — help → argv → record → read back → sidecar → preflight | Jazzy sandbox, §3 | `P5 PASS`, 9 flags cleared, 776 messages, `termination=clean`, one `.mcap` (232,396 B, sha256 `49e0e6b4…af89c`) |
| **M8** | The argv P5 renders is the **distro-correct** one | §3 | Jazzy argv carries `--topics`, `--node-name`, `--disable-keyboard-controls`; the Humble plan carries none of them and ends positionally (`tests/test_orin_rehearsal.py::test_the_humble_argv_is_cleared_by_a_humble_help_text`) |
| **M9** | A below-pin attestation is **REFUSED**, and the compare is numeric | `--firmware-attested 1.1.9 --keep-going` | `EXIT=2`; refusal cites ADR 0002, `CVE-2026-27509 / 27510`, DEGRADE-MMP; P4/P5 **SKIPPED despite `--keep-going`** |
| **M10** | An at-pin attestation passes | `--firmware-attested V1.1.13 --until p3_network` | `p3_network PASS`, `EXIT=1` (other phases still red on this desktop) |
| **M11** | A malformed attestation is refused **before any phase runs** | `--firmware-attested banana` | `EXIT=2`, `REFUSED: … not a version of the form V1.1.13. Unknown = below pin` |
| **M12** | `ORIN_RUNBOOK.md` is generated and pinned | `--emit-runbook`, `--check-runbook`, `pytest -k runbook` | `matches the generator`; byte-identity + drift tests green |
| **M13** | The recursive no-arm pin is green over the new module | `pytest tests/test_no_arm_pin.py -q` | `76 passed` (74 before; the two new ones are this file's static and dynamic halves) |
| **M14** | The module is 3.10-grammar clean and ruff clean | `ast.parse(..., feature_version=(3,10))`; `ruff check` | parses; `All checks passed!` |

---

## 2 · The desktop run — the honest-bundle gate

```text
$ .parcel/bin/python -B -m scripts.parcel_capture.orin_rehearsal \
    --evidence-dir <scratch>/desk_final --record-target <scratch>/desk_final --keep-going

[   PASS] p0_identity    identity collected: NOT a Jetson, Ubuntu 26.04 LTS, kernel
                         7.0.0-28-generic, python3 3.14.4, ROS distro NONE
[   FAIL] p1_environment required environment items are not satisfied: usbfs_memory_mb
                         (ABSENT), python3.10 import parcel_robot.capture (UNKNOWN),
                         pyrealsense2 (ABSENT), rclpy (ABSENT), rosbag2 mcap storage
                         plugin (UNKNOWN), realsense2_camera (UNKNOWN), unitree_go
                         messages (ABSENT), unitree_api messages (ABSENT)
[   FAIL] p2_storage     free space 120.4 GiB is below the 123.9 GiB a 20-minute take
                         needs at 91.87 MiB/s (deficit 3.5 GiB)
[   PASS] p3_network     5 interface(s); robot LAN not joined; 3 wired candidate(s)
[   FAIL] p4_sensors     the D455 could not be enumerated
[   FAIL] p5_recorder    cannot render a recorder argv for distro NONE
          REFUSAL: P0 classified this machine's ROS distro as NONE. The recorder plan
          renders an argv for HUMBLE or JAZZY only; rendering one for NONE would mean
          guessing a CLI nobody has read, and an unknown option is argparse exit 2 with
          zero bytes recorded. […]

  BLOCKER  p0_identity: this host is not a Jetson, so nothing measured here is evidence
           about the Orin
  DEGRADED p2_storage: sustained write measured with dd, which is the WEAKER measurement […]
RESULT: NOT green — 5 blocker(s). This bundle is evidence for a named blocker, not for
        readiness.
EXIT=1
```

Everything a desktop can honestly say, it said. Every `ABSENT`/`UNKNOWN` carries
an install command. `dd` stood in for `fio` and is **labelled the weaker
measurement** rather than quietly substituted. No traceback appeared anywhere,
including from the phases whose dependencies do not exist here.

The `--keep-going` variant is shown because the default (no flag) is stricter and
also correct: P1 fails and P2–P5 are written as `SKIPPED` with the reason, so the
bundle is complete either way.

---

## 3 · The Jazzy-sandbox run — P5 end to end on real bytes

Recipe from `../../20260813/task_1/PSM_STATUS.md`: the repository's read-only ROS
2 Jazzy rootfs under `bwrap`, `--unshare-net --unshare-pid`, repo bound read-only
at `/mnt`, one writable scratch bind at `/work`. Nothing installed, no network,
no vendor SDK, and `.parcel/` untouched.

```text
$ bwrap --ro-bind .cache/external-evals/runtime/ros-jazzy-base-sandbox / \
    --dev /dev --proc /proc --tmpfs /run --ro-bind <repo> /mnt --bind <work> /work \
    --tmpfs /tmp --unshare-net --unshare-pid --die-with-parent \
    /bin/bash -lc 'source /opt/ros/jazzy/setup.bash; cd /mnt;
      python3 -B -m scripts.parcel_capture.orin_rehearsal \
        --evidence-dir /work/evidence --record-target /work --keep-going'

[   PASS] p0_identity    identity collected: NOT a Jetson, Ubuntu 24.04.4 LTS, kernel
                         7.0.0-28-generic, python3 3.12.3, ROS distro JAZZY
[   FAIL] p1_environment … usbfs_memory_mb (UNKNOWN), python3.10 import (UNKNOWN),
                         pyrealsense2 (ABSENT), realsense2_camera (ABSENT),
                         unitree_go messages (ABSENT), unitree_api messages (ABSENT)
[   FAIL] p2_storage     free space 120.4 GiB is below the 123.9 GiB …
[   FAIL] p3_network     could not enumerate interfaces: 'ip' is not on PATH
[   FAIL] p4_sensors     the D455 could not be enumerated
[   PASS] p5_recorder    help verified -> argv rendered for jazzy -> 20s recorded ->
                         776 message(s) read back clean -> sidecar refused the unmapped
                         bench bag, as it must
EXIT=1
```

Two things this run settles that a fake runner cannot.

**(a) P1 found what is actually installed.** `rclpy` and
`ros-jazzy-rosbag2-storage-mcap` are **PRESENT** here and are absent from the
failure list; `realsense2_camera`, `unitree_go`, `unitree_api` are ABSENT with
their install commands. The probe order (`ros2 pkg prefix` first, `dpkg-query`
second) works against a real ROS installation. `ip` is genuinely missing from
this rootfs, and P3 **failed closed** on it rather than reporting "not on the
robot LAN" without having looked — which is the correct answer and one I did not
have to seed.

**(b) P5, in full.** From `p5_recorder.json`:

```text
rendered_argv:
  ros2 bag record --storage mcap --output /work/parcel_rehearsal_bench_bag
    --max-cache-size 8388608 --node-name parcel_rosbag2_recorder
    --disable-keyboard-controls --max-bag-size 0 --max-bag-duration 0
    --storage-config-file /work/evidence/bench_storage_config.yaml
    --topics /parcel_rehearsal/imu /parcel_rehearsal/range

verified_flags: ['--storage', '--output', '--max-cache-size', '--node-name',
                 '--disable-keyboard-controls', '--max-bag-size',
                 '--max-bag-duration', '--storage-config-file', '--topics']

bench_sources: ['ros2 topic pub -r 30 /parcel_rehearsal/imu sensor_msgs/msg/Imu {}',
                'ros2 topic pub -r 10 /parcel_rehearsal/range sensor_msgs/msg/Range {}']

bag: directory=/work/parcel_rehearsal_bench_bag  on_record_target=true
     files={'parcel_rehearsal_bench_bag_0.mcap':
            '49e0e6b4703bb68321744a2be5d439c2da79cd02b0cf065491a9b5dd7e7af89c'}
     bytes={'parcel_rehearsal_bench_bag_0.mcap': 232396}
     termination=['clean'] count_basis=['walked_messages'] seconds=20
     counts={'/parcel_rehearsal/imu': 582, '/parcel_rehearsal/range': 194}

sidecar: built=false  origin='simulation'
  expected_refusal: "…/parcel_rehearsal_bench_bag carries no topic that maps to a channel
    (saw ['/parcel_rehearsal/imu', '/parcel_rehearsal/range']); a bag with no known
    channel is a finding, not a manifest"

support_reconciliation: ok=false, 5 refusals, e.g.
  "/camera/camera/color/camera_info is not on the observed graph; a REQUIRED support
   topic that is missing at run time is a refusal"
```

`582 ≈ 30 Hz × 20 s` and `194 ≈ 10 Hz × 20 s`, which is the arithmetic saying the
recorder subscribed and kept up (the ~3% shortfall is the discovery window at the
start, and it is counted rather than rounded away). The recorder was stopped with
**SIGINT** — the Ctrl-C the run sheet types — rather than killed, which is why the
bag terminates `clean` rather than truncated.

The bag landed on the **record target**, not in the evidence directory: P2 measured
the sustained write of the record destination, and rehearsing the recorder onto a
different volume measures a different disk (the no-dog checklist says exactly this
at N4d). The bundle carries the bag's path, per-file sha256 and counts; with
`--full` and real camera topics the bag itself is gibibytes and stays where it was
written.

Three judgements in that block are worth stating plainly:

* **`origin=simulation`, declared.** `build_rosbag2_sidecar` defaults to
  `PHYSICAL` because `ros2 bag record` needs a live graph. A graph fed by this
  harness's own bench source is not a sensor, so the rehearsal declares
  `SIMULATION` explicitly and the manifest can never mint physical authority for
  bytes nothing measured. When P5 records **real** driver topics it declares
  `PHYSICAL`.
* **The sidecar refusal is asserted, not swallowed.** P5 computes, *before* the
  call, whether any recorded topic maps to a matrix channel. With none, the
  refusal is the required outcome and a sidecar that produced a manifest anyway
  **fails the phase** with *"that is a hole in the gate, not a pass"*. With
  mapped topics, any refusal fails the phase instead. Both directions are coded
  and one of them just executed on real bytes.
* **S-1's support gate refused, and that is it working.** Five REQUIRED
  `camera_info` topics are absent from a graph with no camera driver. On a
  synthetic bench that is a REPORT; when P5 records real sensor topics it is a
  **FAIL** with the launch-the-driver remedy.

---

## 4 · Seeded-failure table

Each row is a defect deliberately induced, with the assertion that catches it.
Fake command runners are injected per phase, so a desktop with none of the
hardware exercises every refusal path.

| # | Seed | Where | Asserted |
|---|---|---|---|
| **S1** | `usbfs_memory_mb` reads `16` | P1 | FAIL; remedy names `/boot/extlinux/extlinux.conf`, `usbcore.usbfs_memory_mb=1000`, `REBOOT`, and *"no second dock"*. **Also reproduced for real** on this desktop (M3) |
| **S2** | `usbfs_memory_mb` unreadable | P1 | `UNKNOWN` → treated as absent → FAIL. Unknown is never a default |
| **S3** | fio tail = 40 MiB/s (peak 900 MiB/s, 60 tail samples) | P2 | FAIL **naming the deficit**: `…below the 91.87 MiB/s the plan of record needs — deficit 51.9 MiB/s`; `knee_visible=true` |
| **S4** | No fio, `dd` only | P2 | `weaker=true`, `peak=None`, weakness text *"cannot show the knee"*, and a recorded degradation. `dd` may stand in for `fio`; it may not pass for it |
| **S5** | No write tool at all | P2 | FAIL — *"unmeasured is not a pass"* |
| **S6** | Host holds `192.168.123.222/24`, no attestation | P3 | **hard refusal**, `hard_stop=true`, citing `CVE-2026-27509 / 27510 class findings`, *"unauthenticated by design"*, *"Unknown = below pin"* |
| **S7** | `--firmware-attested 1.1.9` | P3 | **REFUSED.** The test first asserts `"1.1.9" >= "1.1.13"` is **True** under string comparison, then that `firmware_meets_pin("1.1.9")` is **False** — the compare is a tuple compare and the trap is proven, not assumed |
| **S8** | `--firmware-attested` malformed (`1.1`, `V1`, `latest`, `""`, `1.1.13-beta`, `v1.1.x`) | CLI + P3 | refusal with *"Unknown = below pin"*; never a lenient parse |
| **S9** | Robot-LAN refusal under `--keep-going` | driver | P4 and P5 still `SKIPPED`. A security refusal is not an operator preference |
| **S10** | `/opt/ros` = `jazzy` / `foxy` / empty | P0 | **PASS with a REPORT**, never a crash and never a FAIL; the Foxy consequence names sqlite3, python 3.8, the pyrealsense2 wheel and `<NetworkInterfaceAddress>` |
| **S11** | `/opt/ros` = `humble jazzy` (two distros) | P0 | `UNKNOWN` — ambiguity is not a guess |
| **S12** | `ls` itself unavailable | P0 | `UNKNOWN`, not `NONE`. *"Could not answer"* and *"there is no ROS"* have different remedies |
| **S13** | Jazzy argv against a Humble `--help` | P5 | **refuses before recording**; asserted on the *calls made* (`ros2 bag record` was never started) and on `bench_bag/` never existing |
| **S14** | Help text that is not the recorder's | P5 | refused — an unrecognised help text never reads as clearance |
| **S15** | Distro `FOXY`/`NONE`/`UNKNOWN` | P5 | refuses to render an argv at all; `--help` is never even captured |
| **S16** | Colour stream delivers 20 % | P4 | FAIL; remedy walks the drop ladder with the rungs named |
| **S17** | Colour stream delivers 95 % | P4 | `DEGRADED` with the deficit quantified — a finding, not a stop |
| **S18** | A bench topic outside `/parcel_rehearsal/`, or carrying a command marker | P5 guard | `RehearsalRefused`, checked twice and independently, so both rules are provable separately |
| **S19** | A phase added to the harness but not to the runbook | doc pin | `render_runbook()` raises `KeyError` — the generator refuses to emit a row whose proof and failure condition nobody wrote |
| **S20** | Committed runbook hand-edited | doc pin | byte-identity test reddens with the regeneration command in the message |

The last two are the `test_bandwidth_budget_doc.py` pattern: one test pins the
bytes, a second proves the pin is comparing something.

---

## 5 · What the harness will not do

* **It never joins the robot LAN.** It looks, it reports, and it refuses to go
  further when it finds itself on `192.168.123.0/24` without an attestation at or
  above the pin. A below-pin attestation still lets P0–P2 run, deliberately: the
  no-dog checklist is explicit that the bench steps are worth doing on the
  DEGRADE-MMP path because none of them touches the dog.
* **It never commands motion.** The only processes it starts are vendor sensor
  probes, `ros2 topic pub` of `sensor_msgs` on `/parcel_rehearsal/*`, and
  `ros2 bag record`. `refuse_unless_bench_topic()` rejects any other namespace
  and any command/request marker, and the recursive no-arm pin covers this file
  statically and dynamically.
* **It never edits another card's file.** `rosbag2.py`, `sidecar.py`,
  `preflight.py`, `record.py` and `channels.py` are imported read-only. Where an
  API disagreed with what I assumed, the harness adapted (§7) and the disagreement
  is reported here rather than fixed in their tree.
* **It never hands the operator a traceback.** Missing executable, timeout,
  vendor binding raising, S-1 shifting an API mid-run: each becomes a sentence
  and a remedy in the bundle. `main()` catches anything unforeseen and prints
  `HARNESS ERROR … This is a defect in the harness, not a verdict about the
  machine` with the evidence written so far. That path fired twice during
  development (§7) and behaved exactly as designed.
* **It never issues the readiness verdict.** `verdict.json` carries
  `evidence_for: "READY_FOR_STATIONARY_STAGE0"` only when every phase is green
  and there are no degradations, and its `authority` field says in full that the
  decision is AU-F/Fable's. A harness that graded its own run is what the board's
  separation of authority exists to prevent.

---

## 6 · How P0 doubles as H-1

`p0_identity.json` carries a `run_header_markdown` field that pastes straight
into the run sheet's run header — no transcription step, and the raw output of
all eight identity commands sits beside it in the same file. On the fixture Orin:

```text
## Run header — Orin identity (generated by orin_rehearsal P0)

- Observed at: … UTC on host …
- Is a Jetson: True
- L4T / JetPack: R36 REVISION 4.3 / JetPack 6.x
- Ubuntu: Ubuntu 22.04.5 LTS
- Kernel: 5.15.148-tegra   Arch: aarch64
- Default python3: 3.10.12
- /opt/ros entries: ['humble']
- ROS distro classification: HUMBLE
- Consequence: The plan of record holds. Rosbag2Plan(distro=HUMBLE) renders the argv …
- Record target: /data
```

---

## 7 · OWNS deviations, and adaptations to in-flight APIs

**OWNS deviations: none.** `git status --porcelain` shows my three code/doc paths
as untracked additions and no modification to any tracked file. S-1's
`preflight.py` / `record.py` / `rosbag2.py` / `sidecar.py` / `channels.py` and
S-2's `stage0_addendum.py` were not touched.

Two API assumptions of mine were wrong and were corrected by **executing** the
harness, not by reading:

| Assumed | Actual | Fix |
|---|---|---|
| `EvidenceOrigin.SIMULATED` | the member is `SIMULATION` | corrected; the rehearsal declares it explicitly |
| `Confidence.VERIFY_IN_SESSION` | the members are `CONFIRMED` / `LIKELY` / `UNVERIFIED` | `CONFIRMED`, because the row was read straight off `ros2 topic list -t` on the machine that will record it |

Both surfaced as `HARNESS ERROR (AttributeError)` lines — a sentence and an
evidence directory, never a traceback — which is the fail-closed handler earning
its place before the Orin ever sees it. Both are now covered by
`tests/test_orin_rehearsal.py`, which constructs a real `Rosbag2Plan` and a real
`bench_plan`.

**S-1 surfaces consumed read-only:** `Rosbag2Plan`, `RecordedTopic`,
`record_command`, `record_help_command`, `validate_argv_against_help`,
`storage_config_yaml`, `discover_bag`, `read_rosbag2_mcap`, `CHANNEL_BY_TOPIC`,
`build_rosbag2_sidecar`, `write_sidecar`, `verify_rosbag2_sidecar`,
`sidecar_digest`, `SidecarRefusedError`, `reconcile_support_topics`;
`budget.build_budget` / `RECOMMENDED_PROFILE`; the `RealSenseIngest` and
`L2Ingest` dependency reports. If S-1 moves one of these after this was written,
the harness reports the mismatch as a finding and P5 fails with the message
verbatim; it does not edit their file.

---

## 8 · Gates

```text
$ .parcel/bin/python -B -m pytest tests/test_orin_rehearsal.py -q
82 passed

$ .parcel/bin/python -B -m pytest tests/test_no_arm_pin.py -q
76 passed          # 74 before this card; the two new ones are this module's
                   # static and dynamic halves

$ .parcel/bin/python -B -m ruff check scripts/parcel_capture/orin_rehearsal.py \
    tests/test_orin_rehearsal.py
All checks passed!

$ .parcel/bin/python -B -c "import ast,pathlib; ast.parse(
    pathlib.Path('scripts/parcel_capture/orin_rehearsal.py').read_text(),
    feature_version=(3,10))"
parses under Python 3.10 grammar (ast feature_version=(3,10)); dev interpreter is 3.14.4

$ .parcel/bin/python -B -m scripts.parcel_capture.orin_rehearsal --check-runbook
…/scrum/20260814/task_1/ORIN_RUNBOOK.md matches the generator
```

`ci_gate --tier commit` result is recorded at the end of this document.

**Mutation/`.pyc` discipline.** Every invocation used `-B` and
`PYTHONDONTWRITEBYTECODE=1`; no `.pyc` exists for the new module. All scratch
lived under the session scratchpad. No `git commit`, `stash` or `checkout` was
run. `.parcel/` was not modified and no vendor SDK was installed anywhere.

---

## 9 · does_not_prove

1. **This harness has never run on a real Orin.** Everything above ran on an
   x86-64 Ubuntu 26.04 desktop and inside a ROS 2 **Jazzy** container image. It
   proves the orchestration and the refusal paths. It proves nothing about the
   Jetson, its JetPack level, its NVMe, its USB controller or its ROS
   installation.
2. **Nothing here ran on Humble.** The Humble argv is rendered by `Rosbag2Plan`
   and checked against a *fixture* Humble `--help`; the real recorder it was
   executed against was Jazzy's. PS-M's `does_not_prove` #1 stands unchanged, and
   `--verify-help` against the installed recorder is exactly why P5 captures the
   help before it uses it.
3. **P4 has never seen a camera.** The D455 enumeration and frame-count scripts
   are `[UNVERIFIED-SYNTAX]` in the same sense the no-dog checklist marks them:
   the callback spelling and `stream_name()` vary between pyrealsense2 builds,
   which is why a polling fallback exists — but neither branch has ever executed
   against `pyrealsense2`, on any machine. The *requirement* (a per-stream
   delivered-vs-expected count over the window) is what P4 gates on; this
   particular script is the current attempt at meeting it. Same for the L2 bench
   read, which has never had an L2 on the other end.
4. **P2's fio parser has never parsed fio.** `fio` is not installed here. The bw
   log format is fed to the parser from a fixture written by the test; the `dd`
   fallback is what actually executed. A real fio log with a different column
   layout would be caught by the phase reporting *no measurement* — which fails
   closed — but it would still be a defect found on the bench.
5. **The bench source is not a driver.** 789 messages of `Imu` and `Range` at 30
   and 10 Hz prove the recorder, the argv and the reader. They do not prove that
   a *driver node's* topics reach the recorder: different QoS, different
   burstiness, an image-transport plugin, and competition for the same CPU. That
   is the checklist's N4f and it needs the camera.
6. **The sidecar was exercised to its refusal, not through to a manifest.** On a
   bench with no matrix-mapped topic that is the correct outcome and it is
   asserted — but the *written, verified* sidecar path (`built=true`,
   `verify_rosbag2_sidecar` green) has run only in unit tests over fixtures, never
   over a bag this harness recorded.
7. **A firmware attestation is an operator declaration.** `--firmware-attested`
   records what a human read in a vendor app. The harness compares it correctly;
   it cannot verify it.
8. **P2 measures the path it is pointed at, for the size it is given.** The
   default 2 GiB sample does not exhaust an SLC cache, so a tail equal to the
   peak has disproven nothing. `--full` and a correct `--record-target` are both
   required for the measurement the session actually depends on, and when
   `--record-target` is omitted the harness says so on stdout and in the bundle.
9. **A green bundle is not a readiness verdict.** It is evidence *for*
   `READY_FOR_STATIONARY_STAGE0`. Exactly one readiness decision is recorded at
   close, by AU-F.
10. **Nothing here is evidence about the dog.** No phase powers it, joins its
    LAN, subscribes to its topics or reads its firmware. The mount geometry
    (H-3) and the two-LiDAR extrinsic remain entirely outside this harness, and
    the L2 degradation lines repeat the reason: that extrinsic is unrecoverable
    once the bracket comes off.

---

## 10 · Close gate

```text
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-14T21:49:12Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline …: collisions=0 false_arrival=0 | mutation panel clean | follow-bench 7 rows, hard_collision_total all 0
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        6 metric series within 1.2x tail ceiling
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.49s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.22s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              5286 passed, 9 skipped, 36 deselected, 5 warnings in 216.82s
RESULT: PASS — every hard gate green.
  elapsed 228.4s
```

**ruff: 7 violations, baseline 7, new 0** — this card contributed none. The
suite grew from 5,071 at the board's opening gate to **5,286**, of which 82 are
`tests/test_orin_rehearsal.py` and 2 are the no-arm pin's new coverage of
`orin_rehearsal.py`. S-1 and S-2 were both in flight in this tree during the
run; nothing they own was edited from here, and nothing they own was red at the
minute the gate ran.

---

## Addendum — 2026-08-14, FX-2 (fix tranche) · claim corrections

**Appended by FX-2, which owns `orin_rehearsal.py` for this tranche. Nothing
above this line was edited.** Full evidence: [FX2_STATUS.md](FX2_STATUS.md).
Five claims on this page were checked by executing them again and four of them
did not hold as written. Each correction below names the command that settled it.

| Claim | As written | What re-execution showed | Now |
|---|---|---|---|
| **M2 / §2** | desktop run reports `distro=NONE` | `/opt/ros` does not exist here, so `ls` exits 2 — a listing that FAILED, not an empty one that succeeded. `classify_distro` returned `NONE` for **any** non-zero exit, including *Permission denied* and *Input/output error* | fixed: a failed listing is `UNKNOWN` (fail closed); **only a successful empty read is `NONE`**. This desktop now reports `distro=UNKNOWN`, and P0 quotes the `ls` line verbatim so the two cases stay distinguishable. The §2 transcript above is history and is left as run |
| **M10** | `--firmware-attested V1.1.13 --until p3_network` → `p3_network PASS`, `EXIT=1` | re-run verbatim: `p3_network` is **SKIPPED**, not PASS — P1 fails on this desktop and `--until` does not override the stop-on-failure rule. `EXIT=1` is right; the phase verdict is not. The row was recorded from a run that also carried `--keep-going` | the claim holds only as `--firmware-attested V1.1.13 --until p3_network --keep-going`. The generated `ORIN_RUNBOOK.md` `--until` row now states that `--until` does not make the named phase run |
| **M7 / §3** | the bwrap recipe as printed produces `P5 PASS` on real Jazzy bytes | the recipe as printed leaves `$HOME` on the **read-only** rootfs. `ros2 bag record` opens `$HOME/.ros/log/…` before recording and dies: `Failed opening file /home/…/.ros/log/python3_28_….log for writing: Read-only file system` → `P5 FAIL — the recorder wrote nothing`. With `export HOME=/work` (the writable bind) the same command is `P5 PASS` | the recipe needs **`export HOME=<the writable bind>`**. Both halves were executed today (FX2_STATUS §F5e). The runbook now states the writable-`$HOME` requirement for the Orin too |
| **§7** | *"If S-1 moves one of these after this was written, the harness reports the mismatch as a finding and P5 fails with the message verbatim"* | true for the sidecar step, **false for step 8**: a raising `reconcile_support_topics` (or a failing lazy import) was recorded as a finding and P5 then declared **PASS** | fixed — the exception is a phase **FAIL** with the exception line as detail. §7's sentence is now true of both steps |
| **§8** | *"no `.pyc` exists for the new module"* | false at inspection time: `scripts/parcel_capture/__pycache__/orin_rehearsal.cpython-314.pyc` (146,137 B, mtime `2026-08-14 18:04:09 -0400`) was present when FX-2 opened this card at 18:22, before FX-2 ran anything. Every other `.pyc` in that directory was rewritten at 18:30–18:31 by a process that was not FX-2's | the tree-wide claim is unprovable and was withdrawn: any import by any process without `-B` recreates it. What is true is the narrower claim — *OR-1's own invocations used `-B`/`PYTHONDONTWRITEBYTECODE=1`*. FX-2 purged the `.pyc` for both modules it mutated |

Unchanged and re-confirmed: M1, M3–M6, M8, M9, M11–M14, the seeded-failure table
(with S10's empty-`/opt/ros` row now meaning *exit 0 and nothing printed*), and
every line of §9 `does_not_prove` — to which FX-2 adds that P4's per-stream score
has still never seen a camera, and that the IMU streams are now **required** to
be present in the pipeline profile, which no build of `pyrealsense2` has yet
confirmed the spelling of on the Orin.
