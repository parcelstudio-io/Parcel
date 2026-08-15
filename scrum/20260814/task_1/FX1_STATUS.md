# FX-1 — addendum / operator-sheet fix tranche (2026-08-14)

**Card:** FX-1 (fix tranche FX) · **Owner:** Opus executor · **Authority for the
resolution ruling:** AU-F ([AU_F_FABLE_REVIEW.md](AU_F_FABLE_REVIEW.md)) ·
**Board of record:** [REVISED_BOARD.md](REVISED_BOARD.md)

**OWNS, and nothing else was touched:**
`scripts/parcel_capture/stage0_addendum.py`,
`scripts/parcel_capture/rosbag2.py` (bootstrap lines only),
`tests/test_stage0_command_addendum.py`,
[STAGE0_COMMAND_ADDENDUM.md](STAGE0_COMMAND_ADDENDUM.md),
[STAGE0_ADDENDUM_HUMBLE.md](STAGE0_ADDENDUM_HUMBLE.md),
[STAGE0_ADDENDUM_JAZZY.md](STAGE0_ADDENDUM_JAZZY.md), this file.
`tests/test_stage0_addendum.py` needed no edit — it stayed green throughout.

Nothing here arms anything. No publisher, no motion import, no vendor lease, no
robot-LAN join, no vendor SDK into `.parcel/`. `READY_FOR_STATIONARY_STAGE0` is
**not** claimed and H-1 is still **UNREAD**: FINALIZE remains blocked.

---

## FX section — per-finding table

| # | Sev | Reproduced (executed) | Fixed | Regression test | Reddens on the old behaviour |
|---|---|---|---|---|---|
| **F1** | MAJOR | **YES** — tokenised the three committed sheets: `humble: combined=46 per-distro=46`, `jazzy: combined=50 per-distro=50`, **both with two positional mismatches** (`/data/parcel/session` vs `/data/parcel/stage0/take01`; `/data/parcel/mcap_storage.yaml` vs `/data/parcel/stage0/mcap_storage.yaml`) | `STAGE0_COMMAND_ADDENDUM.md` regenerated as a **thin GENERATED index, zero command rows**; `render_stage0_command_addendum()` deleted; `render_addendum()` is the only command renderer; `S2_OUTPUT_DIR` / `S2_STORAGE_CONFIG_PATH` are now **aliases** of `DEFAULT_*`, so one pair of paths exists | `test_one_recorder_argv_per_distro_across_every_committed_sheet[humble\|jazzy]`, `test_the_index_carries_no_command_rows`, `test_render_addendum_is_the_only_renderer_that_emits_a_recorder_command`, `test_the_renderer_refuses_to_put_a_command_in_the_index` | **YES** — restoring the pre-fix combined sheet: **7 failed, 33 passed** |
| **F2** | MAJOR | **PARTIAL — see the honesty note below.** The stated root cause (`DEFAULT_STORAGE_CONFIG_PATH` inside `DEFAULT_OUTPUT_DIR`) was **already fixed** in the tree by AU-F's same-day disposition and did **not** reproduce. Two *other* take-losing defects in the same committed rows **did** reproduce with real `ros2` (Jazzy sandbox, exit 1 both times) | record target is now a **per-take** directory in the module default; the sheet order (T10.2 emit → T10.5 folder-absent → T10.6 record) is emitted by the one renderer for every distro; `refuse_storage_config_inside_output()` makes nesting a **construction-time refusal** in `session_plan()` and `Addendum.__post_init__` | `test_a_nested_storage_config_is_refused_at_construction`, `test_a_nested_storage_config_cannot_reach_a_plan_or_a_sheet`, `test_the_committed_sheet_emits_the_config_then_checks_the_folder_then_records[humble\|jazzy]`, `test_storage_config_path_is_outside_the_bag_output_dir` | **YES** — guard reverted to a no-op: 2 failed; storage config re-nested under the record target: **36 failed, 69 passed** (no document renders at all); record target reverted to `/data/parcel/session`: **9 failed** |
| **F3** | MAJOR | **YES** — hand-edited the committed combined sheet (`sha 48966e31…`), ran the no-arm dynamic harness + the pin in shipped order: **23 passed**, and the file came back as `sha 8960405e…` — the hand-edit was silently healed mid-suite | `emit_addendum(path)` now **requires** an explicit path (was `path=None` → wrote `addendum_path()`), so the harness's "call every zero-argument public callable" pass cannot reach it; the CLI passes `addendum_path()` explicitly | `test_emit_addendum_requires_an_explicit_path`, `test_no_zero_argument_public_callable_writes_into_the_card`, `test_a_hand_edit_survives_the_no_arm_dynamic_harness` | **YES** — default restored: **3 failed, 37 passed** |
| **F4** | MAJOR | **YES** — `python3 scripts/parcel_capture/rosbag2.py --verify-help …` from a clean cwd with no `PYTHONPATH`: `ModuleNotFoundError: No module named 'parcel_robot'` at `rosbag2.py:83`. Same for the `-m` form | 12-line `sys.path` bootstrap before the `parcel_robot` import, identical in shape to `budget.py` / `orin_rehearsal.py` / `preflight.py` | `test_rosbag2_verify_help_runs_from_a_clean_cwd_without_pythonpath`, `test_rosbag2_verify_help_still_refuses_cleanly_on_a_missing_help_file` | **YES** — bootstrap removed: **2 failed, 38 passed** |
| **F5** | MINOR | **YES** — same tokeniser, on the T7 `rs_launch.py` rows: the combined sheet's launch line **omitted** `camera_namespace:=camera`, `camera_name:=camera`, `publish_tf:=true`, `tf_publish_rate:=0.0` (18 tokens per-distro vs 14 combined) | subsumed by F1 — the index carries no launch line at all | `test_one_launch_line_per_distro_across_every_committed_sheet[humble\|jazzy]`, which also asserts the committed launch line is a superset of `realsense_launch_arguments()` | **YES** — included in F1's 7 failures |
| **F6** | MINOR | n/a (pin-preservation item) | banners and refusals re-verified after regeneration; index carries `UNREAD` / `BLOCKED ON H-1` / `not claimed` | `test_the_cli_still_refuses_an_unknown_distro[foxy\|iron\|""\|"  "\|HUMBLE2]`, `test_the_index_and_both_sheets_still_say_finalize_is_blocked`, `test_the_index_names_both_sheets_and_the_anything_else_branch`; `tests/test_stage0_addendum.py`'s own banner/distro pins untouched and green | pins carried forward |

---

## 1 · Reproductions — command and output

### F1 · two argv truths across three committed sheets

Tokeniser over the committed bytes (scratch script, pre-fix tree):

```text
=== T10 argv token counts ===
humble: combined=46 tokens  per-distro=46 tokens
  positional mismatches: [('/data/parcel/session', '/data/parcel/stage0/take01'),
                          ('/data/parcel/mcap_storage.yaml', '/data/parcel/stage0/mcap_storage.yaml')]
  EQUAL: False
jazzy:  combined=50 tokens  per-distro=50 tokens
  positional mismatches: [('/data/parcel/session', '/data/parcel/stage0/take01'),
                          ('/data/parcel/mcap_storage.yaml', '/data/parcel/stage0/mcap_storage.yaml')]
  EQUAL: False

=== T7 rs_launch.py token sets ===
humble: combined=14 tokens  per-distro=18 tokens
  only in PER-DISTRO (sibling omits): ['camera_name:=camera', 'camera_namespace:=camera',
                                       'publish_tf:=true', 'tf_publish_rate:=0.0']
  EQUAL: False
jazzy:  identical result
```

Equal token **counts**, different commands — which is why counting was never
enough, and why the fix is a tokenised equality assertion rather than a length
check. `publish_tf` / `tf_publish_rate` are load-bearing: S-1's GO-RECORD gate
refuses a bag whose optical frames have no parent, so the combined sheet's
launch line produced a session that could not certify.

### F2 · the sibling T10 order, against real `ros2`

Sandbox: `bwrap --bind .cache/external-evals/runtime/ros-jazzy-base-sandbox / …
--unshare-net --unshare-pid` (PSM_STATUS M6/D10 shape, S2_STATUS B1 recipe).
Nothing installed, no network, no node.

**Honesty note, and it matters.** The finding as written says
`DEFAULT_STORAGE_CONFIG_PATH` sits inside `DEFAULT_OUTPUT_DIR`. In this tree it
does **not** — AU-F's own same-day disposition had already moved it to
`/data/parcel/mcap_storage.yaml`. I followed the committed combined sheet's T10
order verbatim and the **first** take started:

```text
$ ros2 bag record --storage mcap --output /data/parcel/session … (committed combined argv)
[INFO] [parcel_rosbag2_recorder]: Topics discovery started.
record exit=124            # 12 s timeout — it was recording
-rw-rw-r-- 1 ubuntu ubuntu 2824 session_0.mcap
```

So I am **refuting** that half of the finding rather than claiming a fix I did
not make. What **does** reproduce, twice, with real `ros2`, on the committed
combined sheet:

```text
### (a) SECOND take — the combined sheet has no folder-absent row and a REUSABLE --output:
[ERROR] [ros2bag]: Output folder '/data/parcel/session' already exists.
record exit=1

### (b) following the combined sheet's OWN PROSE, "Emit the storage config file onto the record target":
$ python3 -m scripts.parcel_capture.rosbag2 --emit-storage-config /data/parcel/session/mcap_storage.yaml
wrote /data/parcel/session/mcap_storage.yaml
[ERROR] [ros2bag]: Output folder '/data/parcel/session' already exists.
record exit=1
```

(b) is exactly AU-F's take-losing mechanism, surviving in the sheet's prose
after the constant was moved. (a) is worse in practice: `/data/parcel/session`
is a fixed name, so every take after the first — including the first re-run
after an aborted take — dies here. Both are gone because the combined sheet no
longer carries a command, and the operative per-distro sheets use a per-take
directory plus the T10.5 folder-absent gate.

**Post-fix proof — the regenerated Jazzy sheet's rows, executed in the sheet's
own order, verbatim:**

```text
### T10.1  (bare-checkout python, -S, no PYTHONPATH)
argv cleared against …/parcel_record_help.txt: 8 flag(s) all present
verify-help exit=0
### T10.2
wrote …/data/parcel/stage0/mcap_storage.yaml
### T10.5
output folder absent: OK
### T10.6  (argv extracted from the committed sheet's own markers)
[INFO] [parcel_rosbag2_recorder]: Listening for topics...
[INFO] [parcel_rosbag2_recorder]: Recording...
record exit=124            # 12 s timeout
--- bag:  metadata.yaml   take01_0.mcap
```

### F3 · the byte-identity pin, defeated by suite ordering

```text
$ python -c "…replace('--max-cache-size 8388608','--max-cache-size 999')…"
48966e31ca9fb4e4e53b3de289392ac025dc5bbd8793dd977c43064a5fcaf0d2  STAGE0_COMMAND_ADDENDUM.md   # hand-edited

$ pytest "tests/test_no_arm_pin.py::…[scripts/parcel_capture/stage0_addendum.py]" \
         tests/test_stage0_command_addendum.py -q -p no:randomly
23 passed in 0.21s

$ sha256sum STAGE0_COMMAND_ADDENDUM.md
8960405e29b7c1ab44e565d49b2eb4d940f3052e5cf77edcf462de18e50d69f1              # healed
```

The same hand-edit with **only** the pin file run reddens (`2 failed, 20
passed`). `test_no_arm_pin.py` sorts before `test_stage0_command_addendum.py`,
so in the shipped order the pin could never see a hand-edit.

**Post-fix, the same experiment at full-suite scale** — two sheets hand-edited
(the index's `FINALIZE` cell flipped to `CLEARED, go ahead`; the Jazzy argv's
`--max-cache-size` changed), then the **whole capture suite in shipped order**:

```text
$ pytest tests/test_bandwidth_budget_doc.py tests/test_barn_v8_evidence_capture.py \
         tests/test_capture_envelope.py tests/test_capture_ingest.py \
         tests/test_capture_preflight.py tests/test_capture_rehearsal.py \
         tests/test_capture_sidecar.py tests/test_disk_ledger_doc.py \
         tests/test_no_arm_pin.py tests/test_rosbag2_sidecar.py \
         tests/test_stage0_addendum.py tests/test_stage0_command_addendum.py -q -p no:randomly
FAILED tests/test_stage0_addendum.py::test_committed_sheet_is_byte_identical_to_the_generator[jazzy]
FAILED tests/test_stage0_addendum.py::test_a_hand_edit_to_the_committed_sheet_reddens_the_pin[jazzy]
FAILED tests/test_stage0_addendum.py::test_the_committed_argv_equals_record_command[jazzy]
FAILED tests/test_stage0_command_addendum.py::test_committed_index_is_byte_identical_to_the_generator
FAILED tests/test_stage0_command_addendum.py::test_one_recorder_argv_per_distro_across_every_committed_sheet[jazzy]
FAILED tests/test_stage0_command_addendum.py::test_the_committed_sheet_emits_the_config_then_checks_the_folder_then_records[jazzy]
FAILED tests/test_stage0_command_addendum.py::test_the_index_and_both_sheets_still_say_finalize_is_blocked
7 failed, 873 passed, 1 warning in 32.92s

digests after the run == the hand-edited digests  (ee139568… / ff6a7369…)
```

The hand-edits survived the run — the tree is write-free — and the pins
reddened. Baseline on the clean tree: **880 passed in 33.66s**.

### F4 · `--verify-help` tracebacks on a bare checkout

```text
$ cd <scratch> && python3 /…/scripts/parcel_capture/rosbag2.py --verify-help …
Traceback (most recent call last):
  File "/…/scripts/parcel_capture/rosbag2.py", line 83, in <module>
    from parcel_robot.capture import CHANNELS, Transport
ModuleNotFoundError: No module named 'parcel_robot'

$ python3 -m scripts.parcel_capture.rosbag2 --distro jazzy --verify-help …   # from the repo root
ModuleNotFoundError: No module named 'parcel_robot'
```

After the bootstrap, from a clean cwd with no `PYTHONPATH`:

```text
argv cleared against …/record_help.txt: 8 flag(s) all present
exit=0
--- refusal path (help file absent), still an actionable refusal, no traceback:
unavailable: cannot read /nonexistent/help.txt: [Errno 2] No such file or directory
exit=3
```

The regression test runs the interpreter with **`-S`**, which is what makes it a
real test: this venv carries an editable `parcel_robot` install via a `.pth`
file, so without `-S` the import succeeds whether or not the module bootstraps.
`-S` reproduces the Orin's bare checkout. Proof it is load-bearing: with the
bootstrap removed the two F4 tests fail; with `-S` omitted they pass either way.

---

## 2 · What changed

| Path | Change |
|---|---|
| `scripts/parcel_capture/stage0_addendum.py` | `render_stage0_command_addendum()` (202 lines) **deleted** with its four combined-only helpers (`_t7_realsense_launch`, `_t8_l2_launch`, `_t9_unitree_overlay`, `_argv_block`); `render_combined_index()` added — thin index, self-checked against `_INDEX_FORBIDDEN_TOKENS`; `emit_addendum(path)` path now required; `refuse_storage_config_inside_output()` added and wired into `session_plan()` + `Addendum.__post_init__`; `DEFAULT_OUTPUT_DIR` → `/data/parcel/stage0/take01`, `DEFAULT_STORAGE_CONFIG_PATH` → `/data/parcel/stage0/mcap_storage.yaml`, `S2_*` demoted to aliases; module docstring corrected. sha256 `6183f41c…` |
| `scripts/parcel_capture/rosbag2.py` | **bootstrap lines only** — 13 lines (9 comment + 4 code) before the `parcel_robot` import. No other line touched; the rest of this file's uncommitted delta is S-1's. sha256 `edcf9746…` |
| `tests/test_stage0_command_addendum.py` | rewritten as the cross-sheet consistency pin: tokenises **every** committed sheet, asserts one recorder argv and one launch line per distro, plus the F2/F3/F4/F6 regressions. 40 tests. sha256 `ec1e5613…` |
| `STAGE0_COMMAND_ADDENDUM.md` | regenerated: 205 lines → **57**, zero command rows. sha256 `3890585e…` |
| `STAGE0_ADDENDUM_{HUMBLE,JAZZY}.md` | **byte-identical, unchanged** (`debf3ce1…` / `0da75acd…`) — the alias move was value-preserving, and `--emit-all-distros` reproduces them exactly |

### Claims corrected rather than left overstated

1. Module docstring said *"Two renderers, deliberately … Both read the same
   plan, so they cannot disagree about the argv."* They did disagree. The
   section is now "Exactly one command renderer" and states what went wrong.
2. `DEFAULT_OUTPUT_DIR`'s comment said *"Matches the `rosbag2` CLI `--output`
   default."* It no longer does (that default is still `/data/parcel/session`),
   and the comment now says so and says why they need not agree.
3. The combined sheet claimed *"This file supersedes them for the four missing
   command rows"* while carrying a second copy of those rows. The index now
   says the per-distro pair supersedes them, and carries no rows.
4. AU-F's finding text for F2 named a root cause that is no longer present in
   the tree. Recorded above as a refutation with the executed evidence, not
   quietly re-labelled as fixed.

---

## 3 · Seeded reverts — mutation discipline

Harness `scratchpad/fx1/seeded.py`: one defect on disk at a time, `-B` +
`PYTHONDONTWRITEBYTECODE=1`, `__pycache__` purged before and after, original
bytes held in memory, sha256 verified on restore.

| Seed | Result | Restored |
|---|---|---|
| pre-fix combined command sheet restored | **7 failed, 33 passed** — byte-identity, index-has-no-commands, argv equality ×2, launch equality ×2, index links | `identical=True 3890585e…` |
| `emit_addendum` default target restored | **3 failed, 37 passed** | `identical=True 6183f41c…` |
| nesting guard reverted to a no-op | **2 failed, 38 passed** | `identical=True 6183f41c…` |
| storage config re-nested under the record target | **36 failed, 69 passed** — no document renders at all; fail closed, not fail quiet | `identical=True 6183f41c…` |
| record target back to `/data/parcel/session` | **9 failed, 96 passed** | `identical=True 6183f41c…` |
| `rosbag2` bootstrap removed | **2 failed, 38 passed** | `identical=True 27d06a1a…` |

---

## 4 · Suites

```text
$ .parcel/bin/python -m pytest tests/test_stage0_command_addendum.py tests/test_stage0_addendum.py -q -p no:randomly
105 passed in 0.90s

$ .parcel/bin/python -m pytest tests/test_no_arm_pin.py -q
76 passed in 20.13s
   (committed sheet digests identical before and after: debf3ce1… / 0da75acd… / 3890585e…)

$ .parcel/bin/python -m ruff check scripts/parcel_capture/stage0_addendum.py \
      scripts/parcel_capture/rosbag2.py tests/test_stage0_command_addendum.py
All checks passed!

$ .parcel/bin/python -m scripts.parcel_capture.stage0_addendum --distro foxy --emit-distro
refused: unknown ROS distro 'foxy'; … BOTH variants are VOID: take REVISED_BOARD.md
H-1's 'anything else' branch, STOP, and report the exact output. …
rc=2
```

Gate: see §6.

---

## 5 · does_not_prove

1. **Nothing here ran on the Orin.** H-1 is still UNREAD; the distro is an
   assertion. Both sheets stay DRAFT and FINALIZE stays BLOCKED.
2. Every `ros2` execution in this card was **ROS 2 Jazzy in the repo's sandbox**
   (rosbag2 0.26.11). The Orin is expected to be Humble. The Humble recorder's
   own `--help` has still never been read off an installed binary, so the
   Humble argv clearance remains desk evidence (B-M2's provenance, unchanged).
3. The recording proved in §1 recorded **zero messages from real sensors** — no
   node, no publisher, no camera, no LiDAR. It proves the recorder *starts* and
   creates a bag under the sheet's row order. It proves nothing about topic
   names, rates, QoS, sustained write rate, or bag contents.
4. `publish_tf:=true` / `tf_publish_rate:=0.0` being *present* in the launch
   line does not prove the installed `realsense2_camera` accepts those spellings
   (U37/N2e — `--show-args` on the Orin is still the gate), nor that the driver
   publishes the derived `camera_info` topic names.
5. The F2 refutation is about **this tree**. It does not prove the AU-F finding
   was wrong when it was written; it proves the stated root cause is not present
   now, and that two *different* take-losing defects were.
6. `-S` reproduces "bare checkout, nothing installed" for `parcel_robot`. It
   does not prove the Orin's Python 3.10 runs this module — only that the
   `sys.path` bootstrap is what the import needed. Python 3.10 **grammar** is
   pinned (`ast.parse(feature_version=(3,10))`); the 3.10 **runtime** is not
   exercised here.
7. Cross-sheet token equality is asserted over the sheets in
   `scrum/20260814/task_1/`. It says nothing about the historical 20260813
   sheets, which stay as provenance and are deliberately not edited.
8. A green pin does not prove an operator will follow the sheet. It proves that
   if they follow it, the tokens they type are the ones the plan generated.
9. Nothing here touches mount geometry, FOV overlap, firmware pin, robot LAN,
   stand, gait, or any Parcel-driven motion. None were authorized or executed.
10. The commit gate result in §6 includes files owned by other FX cards that
    were being edited concurrently; see the note there.

---

## 6 · Commit gate

```text
$ cd /home/jaewoo-jang/Desktop/Projects/Parcel && .parcel/bin/python scripts/ci_gate.py --tier commit
CI GATE — tier=commit  (2026-08-14T22:45:10Z)
[  PASS] HARD  ruff                       7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety                … collisions=0 …
[  PASS] HARD  frozen-digest-sentinels    4 immutable manifest(s) byte-identical to pin
[  PASS] HARD  latency-tail-ledger        …
[  PASS] HARD  follow-bench-jerk-ratchet  1.2187 <= 1.46244
[  PASS] HARD  model-off-non-inferiority  23 passed in 0.49s
[  PASS] HARD  frozen-digest-integrity    6 passed, 1 warning in 0.33s
[  PASS] HARD  mutation-panel-freshness   2 passed, 3 warnings in 4.31s
[  PASS] HARD  latency-tail               6 passed, 2 warnings in 0.29s
[  PASS] HARD  default-suite              5347 passed, 9 skipped, 36 deselected, 5 warnings in 223.06s
RESULT: PASS — every hard gate green.
  elapsed 234.6s
```

Committed-sheet digests are unchanged by the gate run: `debf3ce1…` /
`0da75acd…` / `3890585e…`.

**One earlier gate attempt (22:37:45Z) was red** — `ruff` +2
(`scripts/parcel_capture/sidecar.py::RUF046`,
`tests/test_orin_rehearsal.py::PIE804`) and three failures in
`tests/test_orin_rehearsal.py`. None of those files belong to FX-1;
`tests/test_orin_rehearsal.py`'s mtime (18:36:18 local) falls **inside** that
gate's own run window, i.e. another executor was writing it mid-run. The three
tests passed on immediate re-run (`10 passed in 0.41s`), and the 22:45:10Z gate
above is clean. `orin_rehearsal.py` carries its own identical `sys.path`
bootstrap (lines 113-115), so FX-1's `rosbag2.py` change is a no-op there.

*End of FX-1 status.*
