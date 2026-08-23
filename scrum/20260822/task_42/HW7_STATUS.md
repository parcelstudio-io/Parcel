# HW-7 `gate-on-aarch64` — STATUS (executor: Claude Opus · 2026-08-23)

Card `scrum/20260822/task_42`. Design `DESIGN.md` (174 lines).
Pre-registration `PREREGISTRATION.md`, frozen before any measurement,
sha256 `7c6199821eb09c365a7cd9638623a5f567980b9e403bfd341beae573f885224b`.

## Headline

`ci_gate.py --tier commit` now prints a `host` row and can print a **typed
SKIP** for any stage this host cannot run — the capability, what it is for, and
the exact command that un-skips it — instead of a hard ERROR nobody can act on.
Seeded with MuJoCo genuinely hidden from a real interpreter, `unitree-assets`
goes `fail`→`skip` and `tier-coverage` `error`→`skip`, and the run's exit code
stops depending on them.

**The card's premise was three-quarters false, and the measurement says so.**
The card expected CUDA, x86-only wheels, the RTX detector and MuJoCo to be what
blocks the gate on the Orin. Measured: **no commit-tier stage needs CUDA, a
GPU, `onnxruntime` or an x86-only wheel** — GATE-0b's clean clone installed
`.[dev,voice]` (no `perception` extra, no `nvidia-*`) and passed 10/10 hard
gates, and every `onnxruntime`/`sounddevice`/`pyrealsense2`/`cv2`/`torch`
import under `src/` is lazy and inside a function — and **MuJoCo is on
aarch64** (mujoco 3.12.0 cp310/cp312 `manylinux_2_28_aarch64`, both jetson
locks). So the skip decision is made on CAPABILITY, never on
`platform.machine()`; the architecture is reported because a `--json` artifact
with no host line cannot be read six months later.

**The emulated proof did not happen and the reason is recorded, not
paraphrased.** Row E1: `docker run --rm --platform linux/arm64 python:3.12
uname -m` → `/bin/bash: line 1: docker: command not found`, rc 127. No
`docker`, `podman`, `qemu-aarch64`, `qemu-aarch64-static`, `nerdctl`,
`buildah` or `systemd-nspawn` binary exists on this host, `dpkg -l` lists no
qemu/docker package, and `/proc/sys/fs/binfmt_misc/` registers exactly one
handler (`python3.14`) — no `qemu-aarch64` interpreter. **Zero gate-tier runs
were made (the card allowed two; both were for the container).** The fallback
is row E4, and it is labelled below for what it is: a ROW-SET proof, **not an
execution proof. Nothing aarch64 executed anywhere in this card.**

## What changed

`git diff --stat -- <shared OWNS>` (index→worktree; wave-3 edits only):

```
 .github/workflows/ci.yml           | 120 ++++++   (70 mine; 50 are HW-1's, in flight)
 scripts/ci_gate.py                 | 555 +++++++   (411 mine; 144 are HW-6's, in flight)
 scripts/env-audio.sh               | 109 ++++-
 scripts/install_speech_services.sh |  83 ++++-
```

New files: `scripts/install_perception_jetson.sh` (256),
`tests/test_hw7_gate_aarch64.py` (494), `scrum/20260822/task_42/{DESIGN,
PREREGISTRATION,HW7_STATUS}.md`.

Four fenced `CARD HW-7` regions in `scripts/ci_gate.py`, lines
**1071–1444** (the probe, the requirement table, the transform, the `host`
evaluator), **2566–2578** (`"host"` in `COMMIT_TIER_STAGE_NAMES`),
**2682–2689** (the stage tuple entry) and **2691–2706** (the one call:
`stages = hw7_apply_host_skips(stages, tier=tier)`, between the tuple literal
and GATE-0b's loop). Re-derive with `grep -n '# ---- \(END \)\?CARD' scripts/ci_gate.py`.

Why the transform sits there rather than at each call site: `default-suite` is
inside card XD-1's fence, `skip-list` inside GATE-0b's and `stopping-envelope`
inside HW-6's. One transform over the whole tuple covers every stage and edits
none of their regions.

## How verified (every command run through `~/.cache/parcel-guard/pytest_guard.sh --label hw7`, `env -u TMPDIR`)

**Product path.** There is no test-only entry point: `main` →
`run_commit_tier` → the same `.parcel/bin/python scripts/ci_gate.py --tier
commit` the integrator runs. The transform is called from inside
`run_commit_tier`, so nothing is proved through a harness that the product
does not use.

| Row | Result |
|---|---|
| **P1–P8** | MET. `pytest tests/test_hw7_gate_aarch64.py -q` → **35 passed**. Probe shape, arch-as-measurement, the override labelling itself, no-subprocess, requirement closure, skip-reason text (parametrised over all 8 declared stages), identity, the `host` row's `hard=False`/`status=pass`, and — added after a self-review — that a BROKEN probe costs the tier nothing. |
| **P9** | MET. `tests/test_ci_gate.py` **UNTOUCHED** (`git diff --stat -- tests/test_ci_gate.py` empty) and green: **91 passed**; with this card's file **126 passed** in 13.7 s; with HW-6's file as well, **155 passed**. |
| **S1** | MET (headline seed). `PARCEL_HIDE_MODULES=mujoco PYTHONPATH=<blocker>` on a real interpreter, against the REAL tree (the seed is an absent module — nothing on disk was edited): *without* the transform `unitree-assets` = `fail`/`gating_red=True` ("city_block.xml does not compile: ImportError"), `tier-coverage` = `error`/`gating_red=True` ("collection under -m None failed (rc=2)"); *with* it both are `skip`/`gating_red=False` carrying `un-skip: pip install 'mujoco>=3.3,<4' …`. |
| **S2** | MET. On the scratch, dropping `"mujoco"` from `STAGE_REQUIREMENTS["tier-coverage"]` → **2 failed** (the literal pin AND the derived test that counts the nine unguarded `import mujoco` test modules). The first run of this seed passed 34/34 — the derived and pinned tests were ADDED because of it. |
| **S3** | MET. Dropping the `un-skip:` clause from the typed SKIP → **8 failed**. |
| **S4** | MET. Flipping `env-audio.sh`'s x86_64 branch to the aarch64 multiarch dir → **1 failed**. |
| **S5** | MET. Removing `refuse_unless_aarch64` from the Jetson installer → **1 failed**. |
| **X1** | MET. `git show HEAD:scripts/env-audio.sh` and the new script, **co-located** in one scratch dir and run against a pre-populated prefix: `--print` stdout+stderr+rc **byte-identical**; and the resolved x86_64 variables (`PARCEL_AUDIO_LIBDIR`, the two package names, both shas, `PARCEL_PORTAUDIO_SO`) **identical**. |
| **X2** | MET. Both scripts' PIN BLOCKs dumped by replacing `main "$@"` with a variable echo: **17 pins identical**, `PIPER_ASSET=piper_linux_x86_64.tar.gz` unchanged. |
| **X3** | MET. `PARCEL_AUDIO_ARCH=aarch64 … --dry-run` names `usr/lib/aarch64-linux-gnu` and both arm64 shas, exit 0, and a `find` census of the prefix before/after is **identical**. `riscv64` gets a libdir, no snapshot, and says so ("NONE for riscv64"). |
| **X4** | MET. `PARCEL_TARGET_ARCH=aarch64 … --dry-run` → `piper_linux_aarch64.tar.gz` at the tag already pinned; `third_party/` census unchanged. |
| **X5** | **MISS as registered — see D8** (behaviour kept, row re-worded; the verifier caught this and it was NOT a MISS in the first delivery, it was a re-wording). What the delivered code does: `install_perception_jetson.sh --jetpack 6.1` on this host → **rc 2**, "REFUSED on x86_64", naming the desktop's own `.[perception]` command. Under a stubbed `uname` reporting aarch64: no index → refuses to guess (rc 1, printing both measured indexes); `--jetpack 5.1` → refused; `--python python3` → refused (CPython 3.14, "the index publishes cp310 ONLY"); **no venv created in any case**. |
| **X6** | MET. The script carries the wheel name, its sha256, both index URLs, the measurement date and `UNCONFIRMED`; `--dry-run --jetpack 6.2` prints them. |
| **X7** | MET/partial. `bash -n` clean on all three scripts. **`shellcheck` is NOT INSTALLED on this host** — recorded as the pre-registration allows, not claimed. |
| **Y1** | MET. `yaml.safe_load('.github/workflows/ci.yml')` parses; jobs = `aarch64-nightly, commit-gate, nightly-gate, py310-base` (exactly one added); the new job is schedule/dispatch-only, `continue-on-error: true`, 5 steps, fenced. |
| **L1** | MET. In-process ratchet: **8 fingerprints, 1 new vs the 7-entry baseline — `src/parcel_robot/backends/go2.py::I001`, which is HW-2's in-flight file. Zero in any HW-7 file. Zero `noqa` directives added** (one was written and then removed — see D2). |
| **E1** | **MISS (recorded).** No emulator on this host; exact error above. E2/E3 NOT MEASURED. |
| **E4** | MET, **and labelled: NOT AN EXECUTION PROOF.** One in-process evaluation of the row set with stub thunks — `run_commit_tier` never called, no stage evaluated, no pytest spawned. Output below. |
| **G1** | MET. **Zero** `ci_gate.py --tier` runs under `label=hw7` (`grep '--tier' guard.log` shows only gate0b's, its verifier's and the integrator's from this morning). |
| **G2** | MET. `guard.log`: **19 START / 19 END** for `label=hw7`, no orphan, **no rc 137**, no `-n` flag anywhere. Seven runs ended non-zero: the five seeded REDs (S1–S5), the first `test_ci_gate.py` run (which found D5) and the first scratch control (which found D1). Every one is accounted for above. |
| **G3/G4** | MET. See "Ownership, proved" below. |
| **G5** | MET. Zero pytest processes and no container at close. |

### Row E4 — the row-set proof (NOT an execution proof)

```
(a) THIS DESKTOP, measured
  arch reported : x86_64 (measured)
  rows          : 13   names == COMMIT_TIER_STAGE_NAMES: True
  absent caps   : none          SKIP rows : none

(b) PARCEL_HOST_ARCH=aarch64 — the same host, relabelled
  arch reported : aarch64 (OVERRIDE PARCEL_HOST_ARCH; measured x86_64)
  rows          : 13   names == COMMIT_TIER_STAGE_NAMES: True
  absent caps   : none          SKIP rows : none

(c) an Orin VENDOR venv (perception/capture/motion: no mujoco)
  arch reported : aarch64 (OVERRIDE PARCEL_HOST_ARCH; measured x86_64)
  rows          : 13   names == COMMIT_TIER_STAGE_NAMES: True
  absent caps   : ['mujoco']
  SKIP rows     : ['unitree-assets', 'hard-safety', 'tier-coverage', 'default-suite']

DIFF (a) vs (b): none — the architecture ALONE changes no row.
DIFF (a) vs (c): unitree-assets, hard-safety, tier-coverage, default-suite: pass → skip
```

Read (b) carefully: it is the honest answer, not a null result. **Every
requirement is a capability, so relabelling the architecture changes nothing** —
which is precisely why this card does not gate on `platform.machine()`. The
Orin's PRODUCT venv installs mujoco (it is a core dependency, not an extra), so
its row set should equal (a); it is the three VENDOR venvs, and any host where
`pip install -e '.[dev]'` has not run, that get (c).

### Ownership, proved

* Fences in `scripts/ci_gate.py`, computed from the file: `HW-7
  [(1071,1444),(2566,2578),(2682,2689),(2691,2706)]` against XD-1's three,
  GATE-0b's four and HW-6's three — **overlaps: NONE** (checked
  programmatically, both before and after the final edit).
* The worktree diff of `ci_gate.py` has **0 deleted lines**: purely additive.
* Stronger: delete HW-7's four regions from the current file and diff the
  result against the INDEX copy — the difference is **144 added lines at
  946 / 2174 / 2257 and zero deletions**, i.e. exactly HW-6's three in-flight
  regions, untouched by this card.
* `tests/test_ci_gate.py`, `tests/_external_roots.py`, `pyproject.toml`, both
  locks, `tools/xvf3800_probe.py`: not modified (`git status` clean for each).

### The one thing that is not inside `run_stage`

`hw7_apply_host_skips` runs BEFORE the loop, so an exception in it would kill
the whole runner before a single row printed — card GATE-0's original disease,
reintroduced by a reporting feature. It is fail-safe: a probe that cannot
answer declares NOTHING and the tier runs exactly as it did before this card
(`test_a_broken_probe_costs_the_tier_nothing`, seeded with the probe raising
`OSError`). The `host` row then reports the same failure as a non-gating
`error` under `run_stage`, where it is loud.

## What it does not prove

1. **Nothing aarch64 executed.** Not one instruction. Every aarch64 fact here
   is a wheel resolution (HW-1's), a `.deb` fetched and hashed on x86_64, an
   HTTP index listing, or a release asset list. Whether these wheels import on
   the dock's actual L4T is box-day read B9.
2. **Wall-clock is untouched and is the real aarch64 risk.** `load_sensitive`
   (15 marks across 6 modules) is a CONTENTION guard — `scripts/load_guard.py`
   compares 1-minute load against `max(cpus × 0.30, 1.5)`. On an **idle but
   slow** 8-core Orin it does NOT skip, and the thresholds were calibrated on a
   192-thread desktop. This card cannot make that honest; only the box can.
3. The emulated container (E2/E3) and therefore the real claim "the same
   `--tier commit` produces this row set when aarch64 bytes run".
4. The `default-suite` call site stays XD-1's; this card wraps the thunk from
   outside and never edits that line.
5. The nightly tier has no `host` row — commit tier only (handoff H4).
6. `install_speech_services.sh`'s aarch64 path is **planned, never executed**:
   nothing was downloaded on any architecture. Same for the Jetson installer's
   install path — only its refusals ran.

## Deviations

* **D1 — the scratch copy carries `.github/` too.** The COMMON brief's rsync
  list is `src/ scripts/ tools/ tests/ configs/ prompts/`; one of this card's
  OWNS files is `.github/workflows/ci.yml`, and without it the control run on
  the scratch failed one test for a reason that had nothing to do with the
  seed. Declared, additive, no other change to the protocol.
* **D2 — a `# noqa: BLE001` was written and then removed.** The first draft of
  `evaluate_host_capabilities` caught `Exception` with a directive. Card HW-4's
  verifier ruled (F3) that a suppression in a new region is a rule violation;
  removing it added a real fingerprint (`scripts/ci_gate.py::BLE001`), so the
  except was NARROWED instead, to `(OSError, ValueError, AttributeError,
  ImportError)` with each one's cause named. Ratchet back to 0 new.
* **D3 — seed S5 created `$HOME/parcel-perception-venv` on its first run.**
  Removing the arch refusal let the seeded script reach `python3 -m venv`
  (this host has a uv `python3.10` at `~/.local/bin`). It got pip + setuptools
  (22 MB) and no wheel; **it was deleted**, `$HOME` is clean, nothing in the
  repo or the owner's venv was touched. The test was then made hermetic
  (`PARCEL_PERCEPTION_VENV` redirected into `tmp_path`) and S5 re-run: same
  RED, 0.34 s, no side effect. A seed that needs manual cleanup is a seed
  nobody re-runs.
* **D4 — two DESIGN.md rows narrowed during implementation** (recorded in
  DESIGN.md itself, as the brief requires): `assertion-evals` declares NOTHING
  (measured: `evals.assertions.gate` imports and runs with mujoco hidden — it
  runs no pytest at all), and `model-off-non-inferiority` declares `pytest`
  only (measured: none of its four test modules imports mujoco at module
  scope). Both changes make the declaration NARROWER, which is the direction
  that reduces masking. The capability mapping also gained a `kind` field so a
  FACT can share the table without ever being a reason to skip.
* **D5 — the `host` row is LAST, not first.** It was designed to print first,
  as the legend for the rows under it. `tests/test_ci_gate.py:1041` (card
  XD-1's file, closed, not editable by this card) seeds the FIRST evaluator to
  raise and asserts `payload["gates"][0]["status"] == "error"`, so position 0
  is contractually the first HARD gate. The row now sits beside `skip-list`
  directly above RESULT. Pinned by a test so a merge cannot move it back.
* **D6 — DESIGN.md is 201 lines against the brief's ≤150 target** (174 at
  first delivery; the correction pass added F2's and F3's contracts). The
  overrun is the card's own Work item 1: the 14-row table of every commit-tier
  stage with its cited requirement and aarch64 disposition is 16 lines, and the
  §(g) risk section carries the three refusals a reader has to be able to
  audit.
* **D8 — PREREGISTRATION row X5 was re-worded, not reported (correction pass
  F5).** Registered: `scripts/install_perception_jetson.sh --dry-run` on this
  host → **exit ≠ 0** with a message naming aarch64 and x86_64. Delivered:
  `--dry-run` prints `NOTE: on x86_64 a real run REFUSES (exit 2)`, prints the
  plan, and exits **0**; the refusal itself (rc 2) is on the REAL path
  (`--jetpack 6.1`), which is the command the status doc quoted under X5. The
  behaviour is deliberate and is kept — an operator on the desktop must be able
  to READ the aarch64 plan, and a dry run that exits non-zero is a dry run
  people stop running — but the row as registered is a MISS, and the doc's own
  rule is "a row that misses is reported as a MISS, never re-worded". Recorded
  here rather than fixed in `PREREGISTRATION.md`, which stays byte-identical
  (sha `7c619982…`).
* **D7 — network reads.** Five HTTPS GETs to public endpoints to turn guesses
  into measurements: the piper release asset list, `packages.ubuntu.com` for
  the two arm64 versions, `ports.ubuntu.com` for the two `.deb`s (fetched and
  hashed, 344 KB total, into the session scratchpad — not the repo), and the
  two Jetson index pages plus one HEAD for the wheel's size. No credentials, no
  writes, no hosted-model spend ($0).

## Owner-gated rows

None. B20 (the hosted CI click) stays the owner's; the new `aarch64-nightly`
job is `continue-on-error: true` until a run is recorded, and the line comes
off in the commit that records one.

## Handoffs

* **H1 (integrator).** Commit `scripts/install_perception_jetson.sh`,
  `tests/test_hw7_gate_aarch64.py` and `scrum/20260822/task_42/` together with
  the four `ci_gate.py` hunks, the two shell scripts and the `ci.yml` job.
  `CODEBASE_INDEX.md` goes stale (three new tracked files).
* **H2 (design owner, §5.2).** The design records the Jetson wheel as
  `onnxruntime_gpu-1.23.0-cp310-linux_aarch64` from `pypi.jetson-ai-lab.dev`.
  **Measured 2026-08-23: that host does not resolve (DNS), the live index is
  `pypi.jetson-ai-lab.io`, and the version is 1.24.0.** Both `jp6/cu126` and
  `jp6/cu128` answer 200 and serve the SAME wheel (identical sha256
  `d980b934…`, 73,617,978 B), cp310 only. §5.2 should carry the corrected
  host, version and the "the CUDA path does not change this wheel today"
  sentence.
* **H3 (wave 3c or the box).** The commit tier's wall-clock rows are the only
  aarch64 risk this card could not close. The load guard measures contention,
  not speed; a slow idle box runs every `load_sensitive` assertion at
  desktop-calibrated thresholds. Options: a per-host budget multiplier, or the
  guard learning a machine-class floor. Needs the Orin to calibrate.
* **H4 (whoever owns the nightly).** `run_nightly_tier` has no `host` row; the
  same three lines would give the nightly artifact the same legend.
* **H5 (toolchain, this host).** `install_speech_services.sh --dry-run` reports
  **cmake MISSING and curl MISSING** on this desktop: the whisper-from-source
  half of the speech stack cannot be installed here today (wget covers the
  downloads; `--piper-only` still works). Not this card's to fix.
* **H6 (aarch64 STT).** `--piper-only`'s toolchain-free fallback is the
  prebuilt `whisper-bin-ubuntu-x64`; the pinned release publishes no arm64
  equivalent, so on the dog the whisper half needs the from-source build. Named
  in the script, unsolved.
* **H7 (`ruff format`).** `ruff format --check` fails on 609 of 1806 files
  repo-wide, including `scripts/ci_gate.py` at HEAD. It is NOT a gate row
  (`evaluate_ruff` runs `ruff check` only). Stated so nobody re-derives it as
  an HW-7 regression.

## What the verifier should look at first

1. **The transform's masking surface** — `hw7_apply_host_skips` (inside the
   1071–1444 region). It decides BEFORE the thunk runs and only on an absent capability,
   so it structurally cannot turn a red into a green
   (`test_the_transform_cannot_turn_a_red_into_a_green`); check that argument,
   and check `STAGE_REQUIREMENTS` for any requirement declared too broadly.
   The three report-only capabilities (`portaudio`, `onnxruntime`, `cuda`) gate
   NOTHING, and a test forbids them from ever appearing in the table.
2. **S1**, the only seed that runs the real evaluators, and whether hiding a
   module with a meta-path blocker is a faithful stand-in for a venv that never
   installed it.
3. **X1's identity argument** — the functional half is in this doc, the durable
   half is a value pin in the test file, and the reason the obvious
   `git show HEAD:` diff was NOT used (it evaporates on commit) is in the test
   module's docstring.
4. **E4's label.** If any sentence in this doc reads as though aarch64 code ran,
   it is wrong and should be flagged.

---

# Correction pass (2026-08-23 19:xx) — verifier verdict ACCEPT-WITH-NOTES, 6 FIX, 0 HOLD

Record: `~/.cache/parcel-verify/hw7/VERDICT.md`. Tree moved under this card
(the owner committed batch B and pushed; HEAD is now `0ce1c5f`), so
`git diff HEAD -- <file>` shows only wave-3 edits and the numbers below are
re-derived against it. Every command through
`pytest_guard.sh --label hw7`, `env -u TMPDIR`; **zero `--tier` runs** (still
0 for this card, total); guard ledger **28 START / 28 END**, no orphan, no
rc 137, no `-n`.

## F1 — the RESULT line no longer lies on a skipping host

`summarize`'s PASS branch, inside a new `CARD HW-7` fence (shared reporting
code; touch authorised by the integrator). It is not verdict logic: `gating_red`
, the exit code and the FAIL branch are untouched — the FAIL branch says
"N hard gate(s) red: …", which is true whether or not other rows skipped, and
only the PASS branch could state a falsehood.

**The new line, from the vendor-venv picture, produced by the real
`run_commit_tier` with real hardness (`stopping-envelope` is HW-6's soft row,
so 6 not 7):**

```
RESULT: PASS — 6 hard gate(s) green, 4 SKIPPED on this host: unitree-assets, hard-safety, tier-coverage, default-suite
```

**Byte-identity pin.** The index's `summarize` and the new one were loaded side
by side (`importlib.util.spec_from_file_location`) and given this host's real
row set:

| picture | index | new | identical |
|---|---|---|---|
| every hard gate green (this host) | `RESULT: PASS — every hard gate green.` | same | **yes** |
| one gating red | `RESULT: FAIL — 1 hard gate(s) red: ruff` | same | **yes** |
| four hard rows skipped | `RESULT: PASS — every hard gate green.` ← the lie | the line above | (the fix) |

Both branches are pinned by tests
(`test_the_result_line_is_unchanged_when_nothing_skipped`,
`test_the_result_line_says_so_when_a_hard_gate_skipped`,
`test_a_red_gate_still_reads_as_fail_whatever_else_skipped`).

## F2 — the fail-safe is now total, and it costs no directive

`_HW7Recorded(contextlib.suppress)` — a three-line subclass that remembers what
it swallowed. Not an `except` clause, so no BLE001 and no `# noqa` (measured:
ruff reports BLE001 for `except Exception` **and** for `except BaseException`;
`contextlib.suppress(Exception)` and this subclass are clean). `KeyboardInterrupt`
and `SystemExit` still propagate, per card GATE-0's rule. Used in
`_hw7_find_spec`, `_hw7_portaudio`, `_hw7_cuda`, `hw7_apply_host_skips` and
`evaluate_host_capabilities`. `import contextlib` sits at the top of the region
(measured: no E402 fingerprint under this repo's ruff selection).

**Seeds, all through the REAL `run_commit_tier` with the evaluators stubbed the
way `fast_commit_tier` stubs them (no pytest spawned, no stage run):**

| seed | rows | `host` row | hard rows skipped | RESULT line |
|---|---|---|---|---|
| control | 13, names == `COMMIT_TIER_STAGE_NAMES` | `pass` | none | `PASS — every hard gate green.` |
| **`sys.meta_path` finder raising `RuntimeError` for `mujoco`** (the verifier's own reproduction, which used to kill the runner) | **13** | `pass`, evidence `find_spec('mujoco') raised RuntimeError: seeded: this finder refuses mujoco` | 4 | `PASS — 6 hard gate(s) green, 4 SKIPPED on this host: …` |
| `host_capabilities()` itself raises `RuntimeError` | **13** | **`error`**, `hard=False`, text names `RuntimeError` and says the run declared NO skips | **none** (identity) | `PASS — every hard gate green.` + `(report-only red, non-gating: host)` |
| a finder raising `KeyError` for EVERY module | 13 | `pass` | 8 | `PASS — 2 hard gate(s) green, 8 SKIPPED …` |

Nothing died; no gating red in any of them; no masking (the identity case
declares nothing at all). The distinction the verdict's wording merged is worth
keeping: a finder that REFUSES a module is the strongest possible evidence of
absence, so it produces skips with `raised …` as the evidence; only a probe
that cannot answer AT ALL produces `host = error`, and then it declares nothing.
Parametrised over `RuntimeError`/`KeyError`/`ValueError`/`OSError` in
`test_no_exception_from_the_probe_can_kill_the_runner`.

## F3 — evidence, not conclusions

* New fact **`interpreter`** = `sys.executable (prefix sys.prefix)`. On the
  Orin there are four venvs and "mujoco is absent" means something different in
  each; this is the line that tells them apart.
* New per-capability **`evidence`** and **`probe`** fields:
  `importlib.util.find_spec('mujoco') -> None`, `-> spec at <origin>`, or
  `raised <Type>: <message>`; `stat <path> -> exists`, `stat -> absent at N
  path(s): …`. Printed in every skip row's detail, in the `host` row's detail
  (one line per gating-absent capability), and in `host.extra.capabilities.<name>`
  plus `extra.hw7_evidence` / `extra.hw7_interpreter` on each skip row.
* Verdict and evidence come from **two independent `find_spec` calls on
  purpose**: seed the verdict function and the evidence still reports what
  `find_spec` really returned, so a lying probe contradicts itself in the
  printed row instead of hiding behind it.

A skip row now reads:

Produced on this host with `PARCEL_HOST_ARCH=aarch64` and `mujoco` marked
absent (the interpreter is this desktop's, because that is the one that ran;
on the dog it would be the venv's own path, which is the whole point):

```
SKIPPED on this host [aarch64 (OVERRIDE PARCEL_HOST_ARCH; measured x86_64);
/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel/bin/python (prefix …/.parcel)]:
mujoco is absent — evidence: importlib.util.find_spec('mujoco') -> None; needed for
the simulator: scene compilation and the live mutation panel; un-skip: pip install
'mujoco>=3.3,<4'  (cp310/cp312 aarch64 wheels exist: mujoco 3.12.0 --
requirements-lock-jetson-py312.txt)
```

## F4 — the probe is pinned to an independent truth

`test_the_probe_agrees_with_a_real_import_on_this_host`: for every capability
whose `probe` is `importlib.util.find_spec` (mujoco, pytest, xdist, ruff,
onnxruntime — 5 checked, asserted `>= 5`), `present` must equal whether
`importlib.import_module(module)` actually succeeds in this interpreter, with
the failure message naming both sides.

**Lying-probe seed, on the import-verified scratch** (`_hw7_spec_present`
returns `False` for `mujoco` on a host that has it):

* before the correction pass: **35 passed, 0 failed** in HW-7's own file (the
  verifier's F4 — only XD-1's file caught it, and only on a fully provisioned host)
* after: **1 failed, 44 passed** —
  `test_the_probe_agrees_with_a_real_import_on_this_host`, `assert False is True`,
  message: *"the probe says mujoco present=False with evidence
  'importlib.util.find_spec(\'mujoco\') -> spec at …/site-packages/mujoco/__init__.py',
  but `import mujoco` succeeds in …/.parcel/bin/python"* — the contradiction F3
  was designed to expose.

Scratch restored by sha256 (`OK`), `__pycache__` purged.

## F5 — X5 recorded as a deviation

D8 above. Behaviour unchanged; `PREREGISTRATION.md` untouched
(sha `7c619982…`).

## F6 — the nightly step can fail, and installs from the registered lock

`set -e` → **`set -eo pipefail`** (the gate is piped into `tee`, so the step was
exiting with `tee`'s status — harmless only while `continue-on-error: true` is
above it), and the install is constrained to HW-1's measured lock.

**Measured while applying it:** `pip install -c requirements-lock-jetson-py312.txt`
is **rejected** — the lock's line 44 is `-e .` and pip answers `ERROR: Editable
requirements are not allowed as constraints`. The step therefore strips that one
line first (`grep -v "^-e " … > /tmp/jetson-constraints.txt`), which is recorded
in the job's comment. Constraints pin what they list and say nothing about the
rest, so `dev` (pytest, xdist, ruff — absent from that lock) still resolves
normally. `yaml.safe_load` parses; jobs unchanged
(`aarch64-nightly, commit-gate, nightly-gate, py310-base`); **0 deleted lines**
in `ci.yml` vs HEAD, so the three existing jobs are byte-identical.

## N1, N2

* N1: DESIGN §(d)'s "memoised for the run" was false and is corrected — the
  probe runs twice per gate run, uncached, ~2 ms each, and stays uncached
  deliberately (an `lru_cache` would freeze the `PARCEL_HOST_ARCH` override).
* N2: stat line corrected. **HW-7's fenced total is now 594 lines** (411 at the
  verifier's reading, before this pass); `git diff HEAD --numstat` on
  `ci_gate.py` = **738 added / 1 deleted**, of which 144 added are HW-6's
  in-flight region. **The single deletion is the authorised F1 line** —
  `lines.append("RESULT: PASS — every hard gate green.")` — which now lives
  inside the HW-7 fence at `ci_gate.py:2987`. Subtracting the HW-7 fences from
  the current file leaves exactly HW-6's `+144 / -0` against HEAD. Guard ledger
  **28/28**.

## Verification after the pass

| check | result |
|---|---|
| HW-7's own file | **45 passed** (was 35; +10: three RESULT-line branches, four parametrised fail-safe classes, the hostile finder, the evidence pair, the probe-truth pin) |
| with `tests/test_ci_gate.py` (**still untouched**, `git diff` empty) | **136 passed** (45 + 91) |
| ruff ratchet | **7 baseline, 0 new**, `ruff check` clean on `ci_gate.py` and the test file |
| `noqa` directives in HW-7 regions | **0**. The one greppable hit inside a fence (`ci_gate.py:1152`) is prose in a docstring *about* the rule; the other nine in the file are pre-existing lines outside every HW-7 fence |
| `ruff format` | the new test file is now **fully formatted** (it is 100 % this card's). In `ci_gate.py`, 3 hunks remain inside HW-7 fences and all three are the file's own compact `GateResult(name, tier, hard, status, detail,` house style — 42 such call sites exist, 29 in exactly that shape — so reformatting mine alone would make them the odd ones out. A 4th reported hunk (`:2952`) is HEAD's untouched FAIL-branch line, merely adjacent to the fence. `ruff format` is not a gate row and fails on 609 of 1806 files repo-wide, `ci_gate.py` at HEAD included. |
| observed flake | one run of `tests/test_ci_gate.py::test_tier_coverage_is_green_against_the_real_tree` failed mid-pass and passed on two immediate re-runs (alone, and in the pair). It collects the WHOLE tree, and three wave-3b cards are writing test files in this worktree right now; same class as the wave-3a log's "`test_hw3_mid360_band.py` failed to collect mid-flight". Recorded, not attributed to this card. |

`git status --porcelain` of this card's files — **before** and **after** this
pass, identical set:

```
 M .github/workflows/ci.yml          M .github/workflows/ci.yml
 M scripts/ci_gate.py                M scripts/ci_gate.py
 M scripts/env-audio.sh              M scripts/env-audio.sh
 M scripts/install_speech_services.sh   M scripts/install_speech_services.sh
?? scripts/install_perception_jetson.sh ?? scripts/install_perception_jetson.sh
?? scrum/20260822/task_42/            ?? scrum/20260822/task_42/
?? tests/test_hw7_gate_aarch64.py     ?? tests/test_hw7_gate_aarch64.py
```

Nothing outside OWNS moved; `scripts/env-audio.sh`,
`scripts/install_speech_services.sh` and `scripts/install_perception_jetson.sh`
were not touched by this pass at all.
