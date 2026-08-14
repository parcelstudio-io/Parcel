# PS-D status — preflight, discovery, attestation

**Card:** PS-D (`README.md` §PS-D) · **Executor:** Opus · **Date:** 2026-08-13
**Base:** `dd2e857` (working tree; the board cites `406f9d6`)
**Verdict:** complete, all gates measured, **two design calls flagged for the
auditor** (§Design calls D-1, D-2). No OWNS deviation.

---

## What I built

| Path | Lines | What it is |
|---|---|---|
| `scripts/parcel_capture/preflight.py` | 2184 | The looking. Probe driver + 22 channel probes over the PS-A matrix, host/device/network/JetPack/disk observations, the `configs/robot.yaml` placeholder scan, findings, human report, CLI. |
| `scripts/parcel_capture/attest.py` | 1039 | The ruling. `HardwareAttestationV1` (complete, digest-stable, derived-answers-recomputed), the ADR-0002 firmware pin as a security control, `SessionVerdict`, `verify_mapping`, CLI. |
| `tests/test_capture_preflight.py` | 1717 | 126 cells across 13 gates; every property cell paired with a seeded-failure or refutation companion. |

Nothing else in the repo was touched. `configs/robot.yaml` is **read, never
written** — `git status --porcelain configs/robot.yaml` is empty.

### The spine, and where it actually holds

The card's requirement is *"there is NO code path to PRESENT without an
actually-received message"*. That is enforced structurally, not by convention:

* `ChannelProbe.status` and `ChannelProbe.rate_assessment` are **properties**,
  not dataclass fields. `status`'s first branch is
  `messages_received <= 0 -> ABSENT`.
* `ChannelAttestation.status` and `ChannelAttestation.origin` are properties
  too. `origin`'s only route to `EvidenceOrigin.PHYSICAL` is
  `messages_received >= 1`.
* `HardwareAttestationV1.verdict`, `.refusals`, `.degradations`, `.advisories`
  and `.physical_channels` are all derived.
* `as_dict()` writes the derived answers for a human; `from_mapping()` **throws
  them away and recomputes**, following `commissioning/record.py`'s idiom. A
  hand-edited `"origin": "physical"` changes nothing, and `verify_mapping()`
  reports the forgery instead of absorbing it.

An AST cell pins that `ProbeStatus.PRESENT` / `EvidenceOrigin.PHYSICAL` are
*produced* in exactly three places across both modules — `ChannelProbe.status`,
`ChannelAttestation.status`, `ChannelAttestation.origin` — and that every other
occurrence is inside a comparison, which cannot mint anything.

Every failure mode ends ABSENT, and each names a **different** reason, because
"absent" alone costs a session-day: `DEPENDENCY_MISSING` is a laptop problem,
`DEVICE_NODE_MISSING` is a cable, `TOOL_MISSING` is the wrong host, `TIMEOUT` is
a sensor or a network, and `PROBE_CONTRACT_VIOLATION` is our own adapter bug. A
probe that raises **discards the receipts it had already taken** — partial
evidence from a failed probe is not evidence — but keeps the count in
`receipts_discarded` so nothing vanishes silently.

### The firmware gate is a security control

`adr/0002-firmware-pin.md:11-13` treats pre-1.1.13 firmware as **RCE-capable on
the robot LAN** (CVE-2026-27509 / 27510 class). So:

* below pin ⇒ `SessionVerdict.REFUSE_CONNECT`, exit 2;
* **never read ⇒ the same verdict.** Unknown is absent, and absent does not
  clear a security pin. On this dev box that is the answer the tool gives;
* an *operator-typed* version does not clear it either — the gate accepts a
  machine read off the unit and nothing else;
* an unparseable version is a refusal, not a shrug.

The refusal message cites both CVE ids, the ADR path, the pin, and says **DO NOT
ATTACH the Orin or any host to the robot LAN** — a refusal an operator cannot
evaluate is a refusal they will override.

The attestation is still **emitted** on a refusal (with `verdict`, `refusals`
and the fields that were read), because `session/STAGE0_RUN_SHEET.md:259` says a
failing attestation is the deliverable in the DEGRADE-MMP branch.

### The three questions the card asked me to settle empirically

1. **Built-in LiDAR L1 vs L2.** `probe_builtin_lidar()` reads the model off the
   unit (machine read preferred; an operator label reading with a named operator
   *and* a `PHOTO_LIST.md` photo id accepted as a fallback), then rules **each
   document against the read** and records which was wrong. It will not resolve
   the contradiction from a document — unresolved stays unresolved, as a NOTE.
   Demonstrated with a reader reporting `Unitree L2 (built-in)`:
   `unitree product page … says L2 -> CONFIRMED; P5_PROCUREMENT_BOM.md optional
   item A … says L1 -> WRONG`, plus a `DOCUMENT_WRONG` finding. The symmetric
   case (`L1`) is tested too, and names the opposite document.
2. **The `configs/robot.yaml:128` placeholder.** Detected, cited by line, and
   **not trusted**. See §C7 — the scan also surfaced a second finding the card
   did not ask for.
3. **JetPack.** Read as an L4T release string verbatim, then JetPack **derived**
   through a declared table. An L4T release not in the table yields an ABSENT
   JetPack observation with the raw string retained: guessing a JetPack version
   from an unknown L4T is the permissive default board rule 3 forbids.

---

## MEASURED claims

Every row is a command that was executed and its verbatim output. The one
estimate in this document is labelled as such in §does_not_prove.

### C1 — the suite

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python -m pytest tests/test_capture_preflight.py -q
........................................................................ [ 57%]
......................................................                   [100%]
126 passed in 0.36s
```

### C2 — the card's fourth gate: a useful, honest report on this box, no hardware

```
$ .parcel/bin/python -c "<run_preflight(window_s=0.01) and tally it>"
channels probed  = 22
status tally     = {'absent': 22}
absence tally    = {'dependency_missing': 19, 'tool_missing': 1, 'device_node_missing': 1, 'not_attempted': 1}
finding severity = {'blocking': 6, 'major': 12, 'note': 6}
every absence has a remedy = True
```

Every channel ABSENT, every absence explained, every one with an actionable
remedy, and the six BLOCKING findings are exactly PS-A's six CRITICAL channels.

### C3 — exit codes and no traceback

```
$ .parcel/bin/python scripts/parcel_capture/preflight.py --window 0.05 ; echo EXIT=$?
   … full report …
   RESULT: NOT READY — 6 blocking finding(s). See scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md §6 (DEGRADE-MMP).
EXIT=1

$ .parcel/bin/python scripts/parcel_capture/attest.py --window 0.02 --session-label P5-DRY-SMOKE --attesting-operator smoke ; echo EXIT=$?
  firmware pin UNVERIFIED — firmware version is ABSENT (go2: none of rclpy, unitree_sdk2py importable in …/.parcel/bin/python)
  channels     present=0  degraded=0  absent=22
  PHYSICAL     0 channel(s) earned a PHYSICAL origin by delivering a message
  critical not PRESENT: go2.utlidar.cloud, go2.sportmodestate, go2.lowstate, l2.cloud, d455.color, d455.depth
  REFUSAL: FIRMWARE PIN NOT CLEARED (unverified): … (CVE-2026-27509 / CVE-2026-27510 class) … DO NOT ATTACH …
VERDICT: REFUSE_CONNECT
EXIT=2
```

`test_preflight_main_exits_non_zero_without_a_traceback` and
`test_attest_main_exits_two_and_refuses_to_connect_without_a_robot` assert
`"Traceback" not in stdout + stderr` on both paths, and six malformed-CLI cases
are asserted to refuse with exit 2 rather than raise.

### C4 — the seeded spoofed-low-firmware refusal, end to end

```
$ .parcel/bin/python -c "<run_preflight with a reader reporting firmware 1.1.9, then attest()>"
firmware_state = below_pin
verdict        = refuse_connect exit 2
refusal        = FIRMWARE PIN NOT CLEARED (below_pin): firmware '1.1.9' parses to (1, 1, 9) which is BELOW the pin 1.1.13. ADR 0002 (scrum/20260805/task_1/adr/0002-firmware-pin.md:11-13) pins supported Go2 EDU firmware at >= 1.1.13 and treats pre-pin firmware as RCE-CAPABLE on the robot LAN (CVE-2026-27509 / CVE-2026-27510 class). Unitree DDS on …
```

`raise_for_verdict()` raises `FirmwarePinRefusal` on the same object. The
edition and serial are still recorded — a refusal is evidence, not an abort.

### C5 — the refutation: the tool is not simply always-refusing

Injected readers for all six CRITICAL channels at their matrix rates, firmware
`1.1.13`, a 1 TiB budget:

```
$ .parcel/bin/python -c "<synthetic critical-channel readers + attest()>"
verdict     = go_record exit 0
PHYSICAL    = 6 of 22 channels
physical    = ['d455.color', 'd455.depth', 'go2.lowstate', 'go2.sportmodestate', 'go2.utlidar.cloud', 'l2.cloud']
firmware    = met
lidar doc   = unitree product page (cited in CHANNEL_MATRIX.md:78-80) says L2 -> CONFIRMED; scrum/20260805/task_1/P5_PROCUREMENT_BOM.md optional item A (:35 at base 406f9d6, :75 after the 2026-08-13 banner) says L1 -> WRONG
digest      = 6dbf63a0b86f9fa255e9682ec7f7875452e286dd30768acfa69c5001e0c02e23
digest again= 6dbf63a0b86f9fa255e9682ec7f7875452e286dd30768acfa69c5001e0c02e23
refusals    = ()
degrade     = ()
```

Exactly the six channels that delivered a message earned `PHYSICAL`; the other
sixteen carry `EvidenceOrigin.UNKNOWN`. Same inputs, same digest.

### C6 — nothing was installed, and a full run reaches no vendor SDK

```
$ .parcel/bin/python -c "<find_spec over the vendor set>"
rclpy: absent
cyclonedds: absent
unitree_sdk2py: absent
pyrealsense2: absent
cv2: absent
mcap: absent
zstandard: absent
unitree_lidar_sdk: absent

$ .parcel/bin/python -B -c "<run the whole attest CLI, then inspect sys.modules>"
EXIT 2
VENDOR []
```

The second command runs the *entire* preflight + attestation and then looks at
`sys.modules`: no vendor module is imported by a full run. The same measurement
runs inside the suite as
`test_a_full_preflight_run_never_imports_a_vendor_sdk`.

### C7 — the network finding, measured against the shipped config

```
$ .parcel/bin/python -c "<scan_config_scalars() + probe_network(), verbatim>"
control.unitree_sport.interface    line 128  value 'enp3s0'   comment 'replace with the dedicated robot Ethernet NIC on this host' placeholder=True
control.unitree_sport.domain_id    line 129  value '0'        comment ''                                                           placeholder=False
motion.sport.interface             line 170  value 'lo'       comment ''                                                           placeholder=False
motion.sport.domain_id             line 171  value '1'        comment ''                                                           placeholder=False
wifi_cards.simulator.interface     line 338  value 'lo'       comment ''                                                           placeholder=False
wifi_cards.simulator.ros_domain_id line 339  value '1'        comment ''                                                           placeholder=False
wifi_cards.robot.interface         line 342  value 'enp3s0'   comment ''                                                           placeholder=False
wifi_cards.robot.ros_domain_id     line 343  value '0'        comment ''                                                           placeholder=False

robot.nic              ABSENT
                         [absent] wifi_cards.robot.interface = 'enp3s0' but /sys/class/net/enp3s0 does not exist on this host
                         remedy: control/unitree_sport.py:50-53 hard-fails on exactly this; fix the interface name (or run preflight on the Orin) before the session.
robot.dds_domain       0
                         [machine_read] control.unitree_sport.domain_id, wifi_cards.robot.ros_domain_id = 0 (environment and config agree)
robot.cyclonedds_uri   ABSENT
                         [absent] CYCLONEDDS_URI is unset in this process's environment
                         remedy: unset CYCLONEDDS_URI means CycloneDDS picks an interface itself; on a multi-homed Orin that is a coin flip. Pin it before the session.

FINDING [major] NIC_CONFIG_PLACEHOLDER: configs/robot.yaml:128 still carries a placeholder for control.unitree_sport.interface ('enp3s0', comment 'replace with the dedicated robot Ethernet NIC on this host'). Preflight does not trust it; the NIC actually used goes in the run sheet as an observation, not as a config edit.
```

**A finding the card did not ask for, worth the auditor's attention: the NIC and
the DDS domain are each declared THREE times in `configs/robot.yaml`, on two
different domains.**

| Path | Line | NIC | Domain | Notes |
|---|---|---|---|---|
| `control.unitree_sport.*` | 128–129 | `enp3s0` | 0 | **the placeholder** |
| `motion.sport.*` | 170–171 | `lo` | 1 | `enabled: false` (`:169`) |
| `wifi_cards.robot.*` | 342–343 | `enp3s0` | 0 | no comment, looks authoritative |

Preflight only treats the first and third as robot-NIC candidates (exact dotted
strings, so `motion.sport` and `wifi_cards.simulator` can never be promoted) and
refuses both if they ever disagree (`CONFIG_AMBIGUOUS` + a
`NIC_CONFIG_DISAGREEMENT` finding) rather than silently preferring one. They
agree today. But `motion.sport` at domain **1** sitting three lines from a block
that is about the same robot is a trap for whoever edits this file on session
morning, and it is **not mine to fix** — `configs/robot.yaml` is outside my
OWNS and PS-1 does not edit config. Filing it here for the auditor.

The scan is textual, not a YAML parse, **because the placeholder marker lives in
the comment** and every YAML parser discards comments — a parse would hand back
`"enp3s0"` as though somebody had chosen it. It fails closed: a path it cannot
reconstruct simply never matches the exact strings in `ROBOT_NIC_CONFIG_PATHS`,
so a mis-scan can only *lose* a NIC, never promote `wifi_cards.simulator.interface`
(`lo`) into one. That is asserted directly.

### C8 — lint and the ruff ratchet

```
$ .parcel/bin/python -m ruff check --output-format=concise scripts/parcel_capture/preflight.py scripts/parcel_capture/attest.py tests/test_capture_preflight.py
All checks passed!

$ .parcel/bin/python -c "from scripts.ci_gate import evaluate_ruff; r=evaluate_ruff(); print(r.status.upper(), r.detail)"
PASS 7 violation(s), baseline 7, new 0
```

This card added **zero** new `(file, rule)` fingerprints to the ratchet.

### C9 — Python 3.10, verified honestly

`scripts/parcel_capture/` may assume 3.10 + Humble (board rule 4), and there is
no 3.10 interpreter on this host, so **no 3.10 process was executed**. The claim
is static and made of two checks:

```
$ .parcel/bin/python -c "<ast.parse(feature_version=(3,10)) + post-3.10 symbol scan>"
scripts/parcel_capture/preflight.py: parses under feature_version=(3,10)
   post-3.10 surface symbols: ['override']          <-- FALSE POSITIVE, see below
scripts/parcel_capture/attest.py: parses under feature_version=(3,10)
   post-3.10 surface symbols: []
tests/test_capture_preflight.py: parses under feature_version=(3,10)
   post-3.10 surface symbols: []

$ <rejection control for the same checker>
REJECTED 'type X = int\n' -> Type statement is only supported in Python 3.12 and greater
REJECTED 'def f[T](x: T) -> T:' -> Type parameter lists are only supported in Python 3.12 and greater
REJECTED 'try:\n    pass\nexcept' -> Exception groups are only supported in Python 3.11 and greater
```

The `override` hit is a **false positive of my scanner**, checked at the source:
it is the local variable `override` in `expected_rate_for` (`preflight.py:951`),
not `typing.override`.

```
$ grep -c "override" scripts/parcel_capture/preflight.py
11
```

All eleven are that local variable (`:951-966`), its docstring (`:947`), or
`parse_rate_overrides` (`:2031, :2101`). The module's only `typing` import is
`from typing import Any` (`:83`), which shipped long before 3.10. The one
3.10-boundary API used deliberately is `itertools.pairwise` (added in 3.10).

### C10 — ci_gate

```
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-13T09:42:50Z)
==============================================================================
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                nav frozen baseline nav-instruct-v1-baseline-v4-20260811T070536Z: collisions=0 false_arrival=0 | mutation panel clean: collisions=0 no_false_arrival=True | mutation panel freshness: committed fields reproduce live = True | follow-bench: 7 row(s), hard_collision_total all 0 = True | walk_with_me: 1/2 row(s) with hard_collision_total, all 0 = True
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        latest row latency-20260810T082415Z-4d83035f: 6 metric series within 1.2x tail ceiling (rows=5, window=5)
[  PASS] HARD  follow-bench-jerk-ratchet  latest shipped row follow-bench-v1-20260811023618Z-93eba090.json: 1.2187 <= 1.46244 (baseline 1.2187 x 1.2)
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.47s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.43s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.31s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.37s
[  PASS] HARD  default-suite              4492 passed, 9 skipped, 36 deselected, 5 warnings in 187.81s (0:03:07)
==============================================================================
RESULT: PASS — every hard gate green.
  elapsed 199.6s
```

No MUST-NOT-TOUCH surface moved: `frozen-digest-sentinels` byte-identical,
`hard-safety` green, `git status --porcelain` shows no modification to any
pre-existing tracked file.

---

## Seeded-failure table

**Shipped-module mutants** were applied to the real source on disk by a harness,
the suite re-run, the source restored, and the tree verified byte-identical.
Bytecode discipline follows PSA_STATUS.md's harness finding (`-B`,
`PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, explicit `__pycache__`
removal) — a same-size mutation otherwise defeats CPython's `(mtime, size)`
`.pyc` check. **In-test mutants** re-implement the defective rule inside the test
and show the oracle disagrees with it.

| # | Gate | Seeded fault | Proof it was caught |
|---|---|---|---|
| G1 | No PRESENT without a message | `ChannelProbe.status` loses its `messages_received <= 0` guard (M1) | 25 cells red, first `test_every_absence_reason_yields_absent_and_unknown_origin[dependency_missing]` |
| G2 | No PHYSICAL without a message | `ChannelAttestation.origin` returns PHYSICAL unconditionally (M2) | 18 cells red, first `test_every_absence_reason_yields_absent_and_unknown_origin[dependency_missing]` |
| G3 | Declared presence is not evidence | **in-test**: the defective rule "the matrix says LIVE, so call it PRESENT" run against the real 22-channel probe | 18 channels disagree; asserted exactly (`test_seeded_failure_a_probe_with_no_messages_cannot_be_talked_into_present`) |
| G4 | A failed probe discards its receipts | `probe_channel` keeps `len(receipts)` on the failure path (M3) | 6 cells red, first `test_a_probe_that_raises_is_absent_and_its_receipts_are_discarded[raised0-probe_raised]` |
| G5 | …and that discard is what prevents phantom presence | **in-test refutation**: the same 10 receipts, minus the discard rule, build a probe that is `PRESENT` / `NOMINAL` / `PHYSICAL` while the real one is `ABSENT` / `UNKNOWN` | `test_seeded_failure_keeping_the_receipts_of_a_failed_probe_would_mint_presence` |
| G6 | An unread firmware does not clear the pin | `FirmwarePinState.clears_pin` widened to "anything but BELOW_PIN" (M4) | 4 cells red, first `test_an_unread_firmware_refuses_exactly_like_a_low_one` |
| G7 | An unparseable version does not clear the pin | `evaluate_firmware_pin` falls back to `FIRMWARE_PIN` when parsing fails (M5) | 3 cells red, first `test_firmware_pin_states[1.1.13-beta-unparseable]` |
| G8 | An operator-typed version does not clear the pin | the `MACHINE_READ` requirement disabled (M14) | `test_an_operator_typed_firmware_version_does_not_clear_the_pin` |
| G9 | Firmware below pin refuses **with the CVE** | **in-test**: a reader spoofing `1.1.9` driven through `run_preflight` → `attest` | `refuse_connect`, exit 2, both CVE ids + `RCE-CAPABLE` + `DO NOT ATTACH` + the ADR path asserted in the message; `FirmwarePinRefusal` raised |
| G10 | …and the gate is not simply always-refusing | **in-test refutation**: the identical run at `1.1.13` | `firmware = met`, `refusals == ()`, verdict is `DEGRADE_MMP` not `REFUSE_CONNECT` |
| G11 | The config placeholder is not trusted | `PLACEHOLDER_MARKERS` emptied (M6) | `test_the_shipped_config_placeholder_is_detected_and_the_nic_is_not_trusted` |
| G12 | A probe may not mint presence for another channel | the receipt/channel identity check disabled (M7) | `test_a_receipt_labelled_with_another_channel_is_a_contract_violation` |
| G13 | Burst-then-silence is a stall, not a healthy channel | the stall detector disabled (`MAX_GAP_PERIODS = 1e9`, M8) | `test_seeded_failure_a_burst_then_silence_looks_nominal_by_rate_alone`; the same cell asserts the rate-only oracle would have said `PRESENT` at `observed/expected = 1.000` |
| G14 | 90% of nominal is DEGRADED (PS-B's requirement) | `RATE_DEFICIT_FLOOR` dropped to 0.50 (M9) | 2 cells red, first `test_ninety_percent_of_nominal_is_degraded_with_the_deficit_quantified`; the deficit is quantified (`0.9`) not merely named |
| G15 | An operator observation must be attributable | the operator+photo rule disabled (M10) | `test_an_operator_observation_must_name_the_operator_and_the_photograph` |
| G16 | The attestation cannot omit a required field | the completeness check removed (M11) | `test_an_incomplete_or_padded_observation_set_is_refused` — this is what stops a rig dodging the firmware gate by omitting the firmware |
| G17 | Every matrix channel must be probed | `attest()`'s coverage check removed (M12) | `test_the_attestation_covers_every_matrix_channel_in_both_directions` |
| G18 | An unknown L4T is not guessed at | `L4T_TO_JETPACK.get(release, "JetPack 6.2")` (M13) | `test_jetpack_is_derived_from_l4t_and_an_unknown_release_is_absent` |
| G19 | A forged derived answer is reported | `verify_mapping`'s comparison disabled (M15) | `test_seeded_failure_a_hand_forged_physical_origin_is_reported_not_absorbed` |
| G20 | A hand-edited `"origin": "physical"` changes nothing | **in-test**: the emitted JSON is edited to claim `origin=physical`, `status=present`, `verdict=go_record`, `physical_channels=[…]` on a channel with 0 messages | all four forgeries reported by `verify_mapping`; the rebuilt object recomputes to `UNKNOWN` / `ABSENT` / not-`GO_RECORD` / `()`, and its digest equals the honest one |
| G21 | …and the checker is not simply always unhappy | **in-test refutation**: the untouched file | `discrepancies == ()`, digest matches, `physical_channels == (CH_A,)` |
| G22 | Every field moves the digest | 8 single-field variants (firmware, a present channel, free bytes, a finding, label, operator, stamp, budget) | 9 distinct digests asserted |
| G23 | A malformed record is refused, never defaulted | 7 malformed attestations + 7 malformed receipts + 6 malformed CLI inputs + 5 malformed configured rates | each asserted to raise the right refusal type / return exit 2 with no traceback |
| G24 | The channel enumeration is PS-A's | AST scan for any non-docstring string constant equal to a channel id | `test_the_channel_enumeration_is_ps_a_s_and_this_card_keeps_no_second_list` |
| G25 | Nothing here can arm anything | AST scan for 10 motion symbols + a vendor/runtime/navigation import scan + a subprocess `sys.modules` probe over a full run | `VENDOR []`; negative control proves the scan does not fire on `wirelesscontroller` / `unilidar_sdk2` |

Harness output (all 15 shipped-module mutants caught, tree restored):

```
$ .parcel/bin/python <scratchpad>/mutate_psd.py
baseline: 125 passed in 0.59s
M1 status returns PRESENT regardless of the message count: CAUGHT | 25 failed, 100 passed
M2 origin is PHYSICAL regardless of the message count: CAUGHT | 18 failed, 107 passed
M3 a failed probe keeps the receipts it had already taken: CAUGHT | 6 failed, 119 passed
M4 an unverified firmware clears the ADR-0002 pin: CAUGHT | 4 failed, 121 passed
M5 an unparseable firmware version is treated as at the pin: CAUGHT | 3 failed, 122 passed
M6 the config placeholder marker list is emptied: CAUGHT | 1 failed, 124 passed
M7 a receipt may be labelled with another channel: CAUGHT | 1 failed, 124 passed
M8 the stall detector is disabled: CAUGHT | 1 failed, 124 passed
M9 the rate deficit floor drops below PS-B's 90% requirement: CAUGHT | 2 failed, 123 passed
M10 an operator observation no longer needs an operator or a photo: CAUGHT | 1 failed, 124 passed
M11 the attestation may omit a required observation: CAUGHT | 1 failed, 124 passed
M12 attest() no longer requires every matrix channel to be probed: CAUGHT | 1 failed, 124 passed
M13 an unknown L4T release is guessed at instead of refused: CAUGHT | 1 failed, 124 passed
M14 the firmware gate accepts an operator-typed version: CAUGHT | 1 failed, 124 passed
M15 verify_mapping stops reporting a forged derived answer: CAUGHT | 1 failed, 124 passed
tree restored byte-identical: True
survivors: []
```

(The harness ran against the 125-cell suite; the 126th cell, `test_a_major_
finding_does_not_block_but_is_never_hidden`, was added afterwards for design
call D-1 and does not weaken any row above.)

---

## OWNS: no deviation

I created and modified exactly the three paths the card names:
`scripts/parcel_capture/preflight.py`, `scripts/parcel_capture/attest.py`,
`tests/test_capture_preflight.py`. `configs/robot.yaml`,
`src/parcel_robot/capture/`, `scripts/parcel_capture/__init__.py`,
`bags/schema.py` and `evidence_origin.py` were **read only**. No vendor SDK was
installed; `.parcel/` is unchanged (C6).

## Design calls for the auditor

**D-1 — an absent IMPORTANT channel does not block GO_RECORD. Flagged.**
`SessionVerdict` is derived as: firmware refusal ⇒ `REFUSE_CONNECT`; else any
BLOCKING finding or an uncleared storage budget ⇒ `DEGRADE_MMP`; else
`GO_RECORD`. BLOCKING is mapped from **PS-A's `Criticality`**, not re-judged
here (`_CRITICALITY_SEVERITY`: CRITICAL→BLOCKING, IMPORTANT→MAJOR,
OPPORTUNISTIC→NOTE), because PS-A's own docstrings define those words and PS-D
does not get a second opinion on PS-A's table.

The consequence is visible in C5: a rig with all six CRITICAL channels live and
the other sixteen absent scores `GO_RECORD`. I think that is the right *default*
— blocking on `go2.utlidar.imu`, which `CHANNEL_MATRIX.md:26` itself hedges as
"LIVE if published", would push a good session into DEGRADE-MMP over a channel
PS-A deliberately marked `CONFIRM_ON_HAND` — but "an unrecorded channel does not
exist" cuts the other way. **Mitigation, and the thing to review:** every MAJOR
finding is surfaced as an `advisory` in the attestation JSON *and* printed under
the verdict as `ADVISORY (does not block, decide at the go/no-go)`. The decision
stays with `STAGE0_RUN_SHEET.md` §6 and the evidence is in front of the operator
rather than scored away. If the owner wants IMPORTANT absences to block, it is a
one-line change to `_CRITICALITY_SEVERITY`.

**D-2 — the run sheet's critical set and PS-A's disagree slightly. Not
reconciled by me.** `STAGE0_RUN_SHEET.md:235` names "ch.1, ch.5, ch.6, ch.12–15"
as the minimum PRESENT set; PS-A's `Criticality.CRITICAL` is
`go2.utlidar.cloud`, `go2.sportmodestate`, `go2.lowstate`, **`l2.cloud`**,
`d455.color`, `d455.depth`. The run sheet includes the D455 IR pair and IMU
(rows 14–15, which PS-A ranks IMPORTANT) and omits the add-on L2 cloud (which
PS-A ranks CRITICAL). I followed PS-A because the board makes it the machine-
readable authority and keeping a second list is the defect this tranche exists
to avoid. **One of the two documents should be edited by whoever owns it** —
neither is mine.

**D-3 — the storage budget is PS-E's and I refused to invent it.** `GO_RECORD`
requires `--required-free-gib`; without it the verdict is `DEGRADE_MMP` with the
reason "no storage budget was supplied … preflight refuses to invent a threshold
it does not own". That deliberately means preflight can never reach GO_RECORD
until PS-E's number exists. It is fail-closed and it is honest, but it is a
cross-card coupling the auditor should see.

**D-4 — `EvidenceKind` has no `DOCUMENT` member, on purpose.** A value read out
of a repo document can never become an observation; documents appear only as
claims in `BUILTIN_LIDAR_CLAIMS` to be ruled against a machine read or an
operator's eyes. That is what makes the L1/L2 resolution mean something.

---

## does_not_prove

1. **Nothing here has seen a sensor.** Every live reader is a *refusal* in this
   build (`unavailable_reader_factory`, `_unavailable_device_reader`): the DDS,
   `unilidar_sdk2`, `pyrealsense2`, vendor-video, serial, UWB, USB-audio and
   `tegrastats` readers do not exist yet, and every gate above is driven either
   by an injected fake or by the honest all-absent path. **The transport readers
   are the single largest piece of unwritten work between this card and a
   session that records anything**, and they must be wired on the Orin, not
   here. The refusal each one currently emits names exactly what is missing.
2. **A hanging reader is not interruptible.** The deadline is enforced *between*
   yields. A reader that blocks inside a C call past its window cannot be
   stopped from pure Python, so `probe_channel` cannot guarantee its own wall
   clock. The mitigation is a transport-level timeout inside each real reader —
   which does not exist yet (see 1). This is the most likely way the session-day
   preflight hangs instead of refusing.
3. **The firmware version is only as trustworthy as the unit.** The gate proves
   that *whatever the reader reported* clears ADR 0002. It does not authenticate
   the robot, and a compromised or spoofed unit can report any string. On an
   unauthenticated LAN that is a real limit, and the ADR's other controls
   (firewall the segment, tailnet-only remote, auto-update disabled) are
   **operator actions this tool does not verify** — it observes the NIC and the
   domain and nothing more.
4. **The `configs/robot.yaml` reader is a textual scan, not a YAML parser.** It
   understands `key:` nesting by indentation and ignores lists, flow mappings
   and multi-line scalars. It fails closed (a path it cannot reconstruct never
   matches `ROBOT_NIC_CONFIG_PATHS`), but a config restructured into flow style
   would silently produce "no NIC candidate" rather than an error.
5. **The L4T→JetPack table is declared knowledge, not a measurement.** Four
   entries, transcribed from vendor release notes, not verified against a
   Jetson. The raw L4T string is always recorded, and an unknown release refuses
   — but if an entry in that table is *wrong*, preflight will report a wrong
   JetPack version with `kind=DERIVED`. The first real check is running this on
   the Orin.
6. **`PRESENT` means "a message arrived during the probe window".** It does not
   mean the message carried what `CHANNEL_MATRIX.md` says it carries — the probe
   reads size and timestamps, never payload — nor that the sensor is calibrated,
   nor that the channel stays up for the recording. PS-A's `message_type` values
   remain unfalsified by this card; falsifying them needs a reader that decodes.
7. **The rate estimator is `messages / window`.** The stall detector covers the
   burst-then-silence case (G13), but a channel with a *duty cycle* — steady
   traffic with regular sub-threshold gaps — is scored NOMINAL, and jitter is
   not characterised at all. `MIN_RATE_SAMPLES = 10` and the 0.95/1.5 thresholds
   are **engineering choices with stated derivations, not measurements**; the
   0.95 floor is derived only from PS-B's "90% must be degraded" requirement,
   and 1.5 and `MAX_GAP_PERIODS = 5.0` are my judgement. The 12 s default window
   is likewise chosen so the 1 Hz voxel-map channel clears `MIN_RATE_SAMPLES`;
   whether it is long enough to catch intermittent faults is **an estimate**.
8. **The read-only pin is a static scan plus an import measurement, not a
   sandbox.** It proves no symbol names a publisher/control manager/lease, that
   no vendor, runtime or navigation module is imported, and that a full run adds
   no vendor module to `sys.modules`. It does not prove the process *cannot*
   open a socket. The stronger guarantee remains the plan's: `unitree_sdk2py` is
   absent from the venv (C6), and every refusal message in this module actively
   tells the operator not to install it.
9. **The 3.10 claim is static** (C9). No 3.10 interpreter exists on this host,
   so nothing ran under 3.10. Syntax is checked with
   `ast.parse(feature_version=(3,10))` against a demonstrated rejection control,
   but a *behavioural* 3.10/3.14 difference would not be caught. First real
   verification is `python3.10 scripts/parcel_capture/preflight.py --window 1`
   on the Orin, and it belongs on the Stage-0 sheet next to PS-A's equivalent.
10. **The digest binds the attestation to itself, not to a bag.** PS-B carries
    it into the `parcel.bag.v1` sidecar `extra`; that binding is PS-B's and is
    not exercised here. Likewise the clock map (PS-C), mount geometry (PS-F) and
    the rehearsal (PS-E) — nothing in this card speaks to any of them.
11. **`verify_mapping` detects a forged *derived* answer, not a forged raw
    count.** Editing `"messages_received": 0` to `100` produces a
    self-consistent file that recomputes to PRESENT/PHYSICAL. What stops that is
    the digest — which is exactly why PS-B must bind it — plus the fact that the
    evidence string would not match. This is a real limit and it is the reason
    the digest matters more than the checker.
12. **No claim about the session.** Whether the Orin sustains the write rate,
    how long the battery lasts, whether the dog's topics carry what we believe —
    all session measurements. What this card hands the session is a tool that
    records the evidence to settle them, and that refuses to pretend when it
    cannot.
