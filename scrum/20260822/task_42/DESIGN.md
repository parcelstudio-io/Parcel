# HW-7 `gate-on-aarch64` — DESIGN

Card `scrum/20260822/task_42`. Seams §4 **S26** (`scripts/ci_gate.py`) and
**S21** (`scripts/env-audio.sh`, `install_speech_services.sh`), design §5.1
(+ amendment: product venv = uv CPython 3.12; 3.10 floor for the vendor
venvs), §5.2, §9 HW-7. Written before any code, 2026-08-23 ~16:4x EDT.

## (a) Purpose

`ci_gate.py --tier commit` must give the SAME verdict shape on the Orin as on
this desktop: the same row names, in the same order, with every row this host
could not run printed as a **typed SKIP that names its reason and the command
that un-skips it** — never a silent pass, never a red nobody can act on. The
card's premise is that CUDA, x86 wheels, the RTX detector and MuJoCo are what
stand in the way. **Three of those four are measurably false** (§ row table),
so this design says what actually differs, encodes it, and refuses to invent
skips for things that are not a problem.

## (b) Architecture fit — seams, and who calls them

* `scripts/ci_gate.py:run_commit_tier` builds a deferred `stages` tuple and
  runs each entry through `run_stage` (card GATE-0's containment). **One new
  fenced `CARD HW-7` region sits between the tuple literal and the loop** and
  transforms the tuple: `hw7_apply_host_skips(stages, tier=tier)`. It is the
  only hook that reaches EVERY stage — including `default-suite`, whose call
  site is inside card XD-1's region and therefore untouchable — without
  editing one line inside XD-1's three, GATE-0b's four or HW-6's three fences.
* `scripts/ci_gate.py:host_capabilities()` — the probe. **A stat or a
  `find_spec`, never a platform test** (GATE-0b's rule, `ci_gate.py:816-821`);
  no import of the test tree, no subprocess, no pytest (card XD-1's lesson).
* A new report row `host` is added to `COMMIT_TIER_STAGE_NAMES` inside its own
  fence — the shape GATE-0b (`skip-list`) and HW-6 (`stopping-envelope`) used
  to register a stage without editing `tests/test_ci_gate.py` (XD-1's file,
  closed). It prints LAST, beside `skip-list`: it was going to be first (a
  legend belongs above its rows) until `test_ci_gate.py:1041` proved that
  position 0 is contractually the first HARD gate — that test seeds the first
  evaluator to raise and asserts `gates[0]["status"] == "error"`.
* Product-path caller: `ci_gate.main` → `run_commit_tier` → the same
  `.parcel/bin/python scripts/ci_gate.py --tier commit` the integrator runs.
  No test-only entry point exists.
* `scripts/env-audio.sh` (sourced by the launch scripts, `env_audio_activate`)
  and `scripts/install_speech_services.sh` (`main`) gain one `uname -m` switch
  each. Their x86_64 values are unchanged BYTE FOR BYTE; the proof is a
  functional diff against `git show HEAD:<file>` (row X1/X2), not a claim.

## The row-by-row table — every commit-tier stage on aarch64

Order as `COMMIT_TIER_STAGE_NAMES`; the new `host` row is row 13, last.
"Needs" = what the stage would touch that a bare interpreter may not have.

| # | Stage | Needs (cited) | aarch64 disposition | Skips when |
|---|---|---|---|---|
| 1 | `ruff` | `PYTHON -m ruff` (`_ruff_fingerprints:1734`, `ruff_version:1768`) | **runs** — ruff 0.16.1 has a cp3x aarch64 wheel (HW-1 §Extras) | `ruff` unimportable |
| 2 | `unitree-assets` | `import mujoco` + `MjModel.from_xml_path` (`:1372`); `git ls-files` (`_git_paths:1199`) | **runs** — mujoco 3.12.0 `manylinux_2_28_aarch64` (HW-1, both jetson locks); the git sub-check already self-skips with a reason (`:1331`) | `mujoco` absent |
| 3 | `hard-safety` | ledger reads + a LIVE mutation-panel clean run (`_panel_safety_fields_live:1180` → `scripts.mutation_panel.live_clean_safety_fields`) → mujoco | **runs, slowly** — the live re-derivation is ~4 s here and is CPU-bound; on 8 Orin cores it is the second-longest row | `mujoco` absent |
| 4 | `release-parity` | file reads + sha256 only | **runs** — arch-independent by construction | never |
| 5 | `assertion-evals` | `from evals.assertions.gate import run_assertion_gate` (`:1983`) — no pytest at all | **runs** — MEASURED: imports and runs with `mujoco` hidden from the interpreter | never (declares nothing) |
| 6 | `tier-coverage` | THREE `--collect-only` runs of the whole tree (`_collect_ids:1868`), which **raises** on a collection failure | **runs** — but 9 test modules `import mujoco` at module scope with no guard (`test_sim.py:5`, `test_mujoco_lidar.py:5`, `test_raycast_lidar.py:7`, `test_dynamic_city.py:5`, `test_city_orbit_clearance.py:6`, `test_city_semantics.py:3`, `test_scene_assets.py:38`, `test_portal_world.py:32`, `test_next_to_band_achievability.py:31`), so a venv without mujoco turns this row into a hard ERROR — the exact row the probe converts | `pytest` or `mujoco` absent |
| 7 | `stopping-envelope` | one YAML read + pure arithmetic (HW-6) | **runs** | never |
| 8 | `model-off-non-inferiority` | node-id pytest over 4 modules | **runs** — MEASURED: none of the four imports mujoco at module scope | `pytest` absent |
| 9 | `release-parity-integrity` | node-id pytest | **runs** | `pytest` absent |
| 10 | `owner-store-isolation` | node-id pytest | **runs** | `pytest` absent |
| 11 | `default-suite` | two-phase xdist suite (XD-1) | **runs** — worker count is already `min(cpu_count, 16)` and honours `PARCEL_XDIST_WORKERS` (XD-1 A3), so 8 Orin cores need no change | `pytest`/`xdist`/`mujoco` absent |
| 12 | `skip-list` | static `ast` read of `tests/_external_roots.py` | **runs** — on the Orin 3 of the 4 declared roots are absent, so it prints them (its job) | never |
| 13 | `host` (NEW) | nothing | **runs** — pure stat/`find_spec`, ~2 ms | never |

**Nothing in the commit tier needs CUDA, a GPU, `onnxruntime` or an x86-only
wheel.** The decisive measurement is not mine: GATE-0b's clean clone installed
`-e '.[dev,voice]'` — no `perception` extra, therefore no onnxruntime-gpu, no
`nvidia-*` — and reported `RESULT: PASS, 10/10 hard gates` (`task_30/
GATE0B_STATUS.md`, 2026-08-23). Every `onnxruntime` / `sounddevice` /
`pyrealsense2` / `cv2` / `torch` import in `src/` is LAZY, inside a function
(census: 0 module-level, 18 in-function). So the honest aarch64 delta is
**MuJoCo-or-not**, plus wall-clock, plus the two shell scripts — and MuJoCo
*is* on aarch64. The probe is therefore built to report capability truthfully
and gate on capability, not on `platform.machine()`; the arch is PRINTED
because a JSON with no host line cannot be read six months later.

## (c) Interfaces

```python
HOST_ARCH_ENV = "PARCEL_HOST_ARCH"          # override; printed AS an override
def host_capabilities(*, root=REPO, env=None) -> dict[str, dict[str, object]]
    # name -> {"kind": "fact"|"capability", "present": bool,
    #          "detail": str, "unskip": str, "evidence": str,
    #          "probe": str, "module": str}   -- only a "capability"
    #          may be named in STAGE_REQUIREMENTS (P5).
    #          `evidence` is WHAT WAS OBSERVED ("find_spec('mujoco') -> None",
    #          or the exception it raised); `detail` is what the capability is
    #          FOR. The `interpreter` fact (sys.executable/sys.prefix) says
    #          WHICH python was asked — on a four-venv Orin that is the
    #          difference between an expected absence and a defect. [F3]
    # arch | libc | cpython | cpus | mujoco | pytest | xdist | ruff |
    # portaudio | onnxruntime | cuda  (the last three REPORT-ONLY, see (g))
STAGE_REQUIREMENTS: dict[str, tuple[str, ...]]   # the table above, executable
def evaluate_host_capabilities(*, tier="commit") -> GateResult   # row `host`
def hw7_apply_host_skips(stages, *, tier, caps=None) -> tuple[...]
class _HW7Recorded(contextlib.suppress)   # suppress(Exception) that remembers
```

`_HW7Recorded` is the correction pass's F2. The transform is the one thing in
this card that runs OUTSIDE `run_stage`'s containment, so anything it lets
escape kills the runner before row one — and a `try/except Exception` there
would cost a BLE001 fingerprint that this repo forbids suppressing. A context
manager is neither an `except` clause nor a directive; `contextlib.suppress`
already has the right semantics (swallow `Exception`, let `KeyboardInterrupt`
and `SystemExit` through, card GATE-0's rule) and this three-line subclass adds
the one thing it lacks: what it swallowed, for the `host` row to print.

**Shared code touched, with authorisation:** `summarize`'s PASS branch, inside
a `CARD HW-7` fence. A hard row can now end `skip`, which the sentence "every
hard gate green" contradicts; it now reads `RESULT: PASS — N hard gate(s)
green, M SKIPPED on this host: <names>` when and only when a hard row skipped.
No change to `gating_red`, to the exit code, or to the FAIL branch (which is
true either way).
A skipped row is `GateResult(name, tier, hard=True, status="skip", detail=...)`
— `hard` stays TRUE (it is still a hard gate; it did not run) and `status`
`skip` is already non-red by `GateResult.is_red` (`:445`), so the exit code is
unchanged and no verdict logic is edited. `detail` is always
`"SKIPPED on this host: <capability> is absent — <what it means>; un-skip: <exact command>"`.

Shell: `scripts/env-audio.sh` gains `PARCEL_AUDIO_ARCH` (default `uname -m`),
a `--dry-run` verb, and an arch table (`x86_64` → `usr/lib/x86_64-linux-gnu` +
the two amd64 shas already pinned; `aarch64` → `usr/lib/aarch64-linux-gnu` +
the two arm64 shas measured today from ports.ubuntu.com).
`scripts/install_speech_services.sh` gains `PIPER_ASSET` selection by arch and
a `--dry-run` that prints the resolved pin block and exits 0 before any fetch.
`scripts/install_perception_jetson.sh` (new) refuses on non-aarch64, requires
an explicit `--index-url` or `--jetpack {6.0,6.1,6.2}`, and prints the wheel's
recorded provenance instead of guessing one.

## (d) Data flow and lifecycle

`main` → `run_commit_tier` → build `stages` → **`hw7_apply_host_skips`** →
the GATE-0b loop → `summarize`/`--json`. No files written, no processes
started, no locks, no threads. The probe runs **twice per gate run and is not
cached** (verifier N1: an earlier draft of this paragraph said "memoised" and
was simply wrong) — once in the transform and once in the `host` row, ~2 ms
each. It stays uncached deliberately: an `lru_cache` would freeze the
`PARCEL_HOST_ARCH` override and the capability answers for the life of the
process, which is exactly wrong for a table that tests drive with different
environments.

## (e) Hardware compatibility — class **MC**, and what proves what

S26 and S21 are **MC** (must-configure): no product code changes; a host that
differs is configured, and what it cannot do it declares. What the desktop can
prove: the row set, the ordering, the skip semantics, the reason text, and
that a genuinely mujoco-less interpreter yields SKIP instead of ERROR (row
S1/S2, seeded by hiding the module from a real subprocess). What **emulation**
would prove: that aarch64 *bytes* execute — import, collect, verdict SHAPE.
What **only the Orin** proves: wall-clock (every `load_sensitive` assertion —
15 marks across 6 modules — is a CONTENTION guard, `scripts/load_guard.py:73`,
not a speed guard: on an idle-but-slow Orin the guard does NOT skip and the
thresholds are desktop-calibrated), the CUDA EP for the detector venv, whether
uv's 3.12 aarch64 build runs on L4T (Q-jp), and the suite's total wall time.

## (f) Test strategy → rows

`tests/test_hw7_gate_aarch64.py`: the probe's shape and its override (P1–P4);
`STAGE_REQUIREMENTS` covers exactly the declared stage names and no other
(P5); each SKIP row's reason text contains the capability, the word `un-skip:`
and a runnable command (P6); the transform is IDENTITY when everything is
present, so the desktop tier is unchanged (P7 — this is also what keeps
`test_ci_gate.py:933` green); x86 branch byte-identity of both shell scripts
(X1/X2); the aarch64 branches under `--dry-run` (X3/X4); the Jetson installer
refuses on x86 (X5) and names its wheel's provenance (X6); ci.yml parses (Y1).
Seeds: **S1** a stage that needs mujoco with mujoco genuinely hidden →
ERROR/FAIL today, SKIP after; **S2** drop `mujoco` from `STAGE_REQUIREMENTS`
["tier-coverage"] → the aarch64 row set no longer declares it → red; **S3**
weaken a reason to drop `un-skip:` → red; **S4** flip the x86 libdir → red.

**Changed during implementation** (COMMIT brief 2: say so). Two rows of the
table above were narrowed after measurement — `assertion-evals` runs no
pytest and needs no mujoco, and `model-off-non-inferiority` needs pytest
only — and the capability mapping gained a `kind` field so a FACT (arch,
libc, cpus) can live in the same table as a CAPABILITY without ever being
a reason to skip a row. Both changes make the declarations narrower, which
is the direction that reduces masking.

## (g) Risks and what this does NOT cover

1. **A skip is a hole.** `hw7_apply_host_skips` can only ever turn a row it
   would not have been able to run into a printed SKIP; it can never turn a
   red into a green, because it decides BEFORE the evaluator runs and only on
   an absent capability. It is still a mechanism that can hide a regression if
   a requirement is declared too broadly — which is why `cuda`, `onnxruntime`
   and `portaudio` are probed and PRINTED but gate NOTHING.
2. **`cuda` cannot be probed honestly on Tegra.** `nvidia-smi` does not ship
   on Jetson; a `which nvidia-smi` probe would report ABSENT on the very box
   that has a GPU. The row therefore reports the evidence it has
   (`/dev/nvidiactl`, `/dev/nvhost-ctrl`, `nvidia-smi`) and labels the answer
   `UNCONFIRMED-on-tegra` rather than asserting.
3. **Emulation may not exist here** (measured: no `docker`, `podman`, `qemu-*`
   binary; `/proc/sys/fs/binfmt_misc` registers only `python3.14`). The
   fallback is the `PARCEL_HOST_ARCH=aarch64` override, and it is a
   ROW-SET proof, **not an execution proof** — labelled so everywhere.
4. Not covered: the Orin's wall-clock thresholds (needs the box); JetPack 5
   (§7.2); the `default-suite` call site (XD-1's fence — this card wraps the
   thunk from outside, it does not edit that line); the nightly tier's row set
   (commit tier only — handoff).
