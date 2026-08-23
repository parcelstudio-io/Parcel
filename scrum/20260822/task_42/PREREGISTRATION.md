# HW-7 `gate-on-aarch64` — PREREGISTRATION

Card `scrum/20260822/task_42`, slug `hw7`. Written after `DESIGN.md` and
BEFORE any measurement. Every row below carries its command and its threshold
as written here; a row that misses is reported as a MISS, never re-worded.
Frozen at 2026-08-23 ~16:5x EDT.

Conventions. `PY` = `.parcel/bin/python`. `GUARD` =
`~/.cache/parcel-guard/pytest_guard.sh --label hw7`. Every pytest runs as
`env -u TMPDIR $GUARD $PY -m pytest …`; never `-n auto`; never `-n` > 8; no
background pytest. Pre-flight before any suite-scale run: `free -g` available
≥ 120 AND `ps -eo args | grep -c '^[^ ]*python[^ ]* -m pytest'` ≤ 1.
`ci_gate.py --tier` is FORBIDDEN except HW-7's declared exception: at most TWO
runs, inside the emulated aarch64 container only, through the wrapper.

## A. The probe and the typed SKIP rows (`scripts/ci_gate.py`, CARD HW-7)

| Row | Claim | Command | Threshold |
|---|---|---|---|
| **P1** | `host_capabilities()` returns every declared capability with `present`/`detail`/`unskip` and never raises on this host | `env -u TMPDIR $GUARD $PY -m pytest tests/test_hw7_gate_aarch64.py -q -k probe` | all green; the mapping's keys equal the documented set |
| **P2** | On this host `arch` reports `x86_64` and is labelled a MEASUREMENT | same file, `-k arch` | green; detail contains `x86_64` and no `OVERRIDE` |
| **P3** | `PARCEL_HOST_ARCH=aarch64` overrides the arch AND labels itself an override that names the measured value | same file, `-k override` | green; detail contains both `aarch64` and `OVERRIDE`, plus the measured `x86_64` |
| **P4** | The probe touches nothing: no subprocess, no import of `tests/`, no write under the repo | same file, `-k no_side_effects` | green (`subprocess.run`/`Popen` patched to raise during the call) |
| **P5** | `STAGE_REQUIREMENTS` names only stages that exist in `COMMIT_TIER_STAGE_NAMES`, and every requirement is a declared capability | same file, `-k requirements_are_closed` | green |
| **P6** | Every typed SKIP detail names the capability, contains `un-skip:` and a command that starts with a runnable token (`pip`, `python`, `.parcel/bin/`, `scripts/`, `apt`) | same file, `-k skip_reason` | green for EVERY stage in `STAGE_REQUIREMENTS` |
| **P7** | With every capability present the transform is the IDENTITY: same stage names, same order, same thunks | same file, `-k identity` | green; `tuple(name for name, _ in out) == tuple(name for name, _ in inp)` and each thunk is the same object |
| **P8** | The `host` row is `hard=False`, `status="pass"`, prints the arch and the absent set, and cannot change an exit code | same file, `-k host_row` | green |
| **P9** | `tests/test_ci_gate.py` is UNTOUCHED and still green with the new stage in the literal | `env -u TMPDIR $GUARD $PY -m pytest tests/test_ci_gate.py -q` | ≥ 91 passed, 0 failed; `git diff --stat -- tests/test_ci_gate.py` empty |

## B. Seeds (RED first, on a byte-identical scratch copy — never the tree)

| Row | Seed | Expected RED |
|---|---|---|
| **S1** | Hide `mujoco` from a REAL subprocess interpreter (a `sitecustomize.py` meta-path blocker on `PYTHONPATH`), then evaluate `tier-coverage` and `unitree-assets` with and without the transform | without the transform: `tier-coverage` is a hard `error` and `unitree-assets` a hard `fail`; with it: both are `skip`, exit code unchanged. Both halves recorded |
| **S2** | Delete `"mujoco"` from `STAGE_REQUIREMENTS["tier-coverage"]` on the scratch | ≥ 1 named test in `tests/test_hw7_gate_aarch64.py` FAILS |
| **S3** | Rewrite one skip detail to drop the `un-skip:` clause on the scratch | the P6 test FAILS |
| **S4** | Flip the x86_64 libdir in `scripts/env-audio.sh` to `usr/lib/aarch64-linux-gnu` on the scratch | the X1 byte-identity test FAILS |
| **S5** | Remove the `uname -m` refusal from `scripts/install_perception_jetson.sh` on the scratch | the X5 test FAILS |

Seed protocol (COMMON brief 3): `rsync -a --exclude .cache --exclude .parcel
--exclude .git` of `src/ scripts/ tools/ tests/ configs/ prompts/` into
`~/.cache/parcel-hw7/scratch`; run with `PYTHONPATH=<scratch>:<scratch>/src`;
prove the import with `python -c "import parcel_robot; print(parcel_robot.__file__)"`
resolving INSIDE the scratch; restore by sha256; purge `__pycache__`.

## C. The two shell scripts (`scripts/env-audio.sh`, `install_speech_services.sh`)

| Row | Claim | Command | Threshold |
|---|---|---|---|
| **X1** | `env-audio.sh`'s x86_64 path is byte-identical in EFFECT to HEAD's: same libdir, same two deb names, same two shas, same exports | `git show HEAD:scripts/env-audio.sh > $S/head-env-audio.sh` then run BOTH with a pre-populated fake prefix and `--print`, `diff` the stdout+stderr | `diff` empty; exit codes equal |
| **X2** | `install_speech_services.sh`'s x86_64 pin block is byte-identical to HEAD's | `--dry-run` on both (HEAD's has none → compare the resolved PIN BLOCK by sourcing with `PARCEL_*` unset and echoing the eight pins) | all eight pins equal, `PIPER_ASSET=piper_linux_x86_64.tar.gz` |
| **X3** | `PARCEL_AUDIO_ARCH=aarch64 scripts/env-audio.sh --dry-run` prints the aarch64 libdir and the two arm64 debs and DOES NOTHING | run it | stdout names `usr/lib/aarch64-linux-gnu`, both arm64 deb names; exit 0; `~/.local/opt/portaudio` unchanged (mtime + `find` census before/after) |
| **X4** | `PARCEL_HOST_ARCH_OVERRIDE`-free `uname -m` branch in `install_speech_services.sh --dry-run` on aarch64 selects `piper_linux_aarch64.tar.gz` | `PARCEL_TARGET_ARCH=aarch64 scripts/install_speech_services.sh --dry-run` | stdout contains `piper_linux_aarch64.tar.gz`; NOTHING downloaded (no new file under `third_party/`, `models/`) |
| **X5** | `scripts/install_perception_jetson.sh` REFUSES on x86_64 with a non-zero exit and a reason | `scripts/install_perception_jetson.sh --dry-run` on this host | exit ≠ 0; message names `aarch64` and this host's `x86_64` |
| **X6** | The installer records the ort-gpu wheel provenance and says the index is UNCONFIRMED for the box's JetPack until B9 | `grep` the script | contains the measured index URL, the wheel filename, its sha256, and the word `UNCONFIRMED` next to the JetPack selection |
| **X7** | All three scripts pass `bash -n`, and `shellcheck` if it is installed | `bash -n <each>`; `command -v shellcheck && shellcheck <each>` | `bash -n` clean; shellcheck clean or recorded as NOT INSTALLED |

## D. CI and lint

| Row | Claim | Command | Threshold |
|---|---|---|---|
| **Y1** | `.github/workflows/ci.yml` parses and carries exactly one new job, fenced `CARD HW-7`, scheduled-only | `$PY -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(sorted(d['jobs']))"` | parses; the job set gains exactly one name; the new job's `if:` names `schedule` |
| **L1** | ruff ratchet unchanged: exactly the 7 baseline fingerprints, none added by this card, zero `noqa` added | `$PY -m ruff check . --output-format=json` reduced to fingerprints; `git diff -- <OWNS> | grep -c 'noqa'` | new fingerprints in HW-7 files = 0; added `noqa` lines = 0 |

## E. The emulated proof (the card's rule-3 exception)

| Row | Claim | Command | Threshold |
|---|---|---|---|
| **E1** | Is aarch64 emulation available on this host? | `docker run --rm --platform linux/arm64 python:3.12 uname -m` | prints `aarch64` → E2/E3 run. Any other outcome: the EXACT error is recorded verbatim and E4 runs instead |
| **E2** | (if E1) A container built from `requirements-lock-jetson-py312.txt` runs the commit tier | `~/.cache/parcel-guard/pytest_guard.sh --label hw7 docker run … python scripts/ci_gate.py --tier commit --json` | ≤ 2 runs total; JSON captured |
| **E3** | (if E1) The container's row set = the desktop's row names, and the status difference is EXACTLY the declared SKIP set | diff the two JSONs by `(name, status)` | difference ⊆ declared SKIPs and ⊇ nothing else |
| **E4** | (if NOT E1) `PARCEL_HOST_ARCH=aarch64` in ONE in-process evaluation of the row set (`run_commit_tier` is NOT called; the stages tuple is built and transformed, nothing is executed) | a `$PY -c` one-liner recorded verbatim in the status doc | the row NAMES equal `COMMIT_TIER_STAGE_NAMES`; the skip set equals the capabilities absent on this host; **labelled NOT AN EXECUTION PROOF** in the status doc's headline |

## F. Discipline rows

| Row | Claim | Threshold |
|---|---|---|
| **G1** | Gate runs | ≤ 2, container only; 0 if E1 fails. `grep -c ci_gate ~/.cache/parcel-guard/guard.log` for this label matches the status doc |
| **G2** | Every pytest went through the wrapper | `guard.log` `label=hw7` START/END pairs = the status doc's command ledger, no orphan START |
| **G3** | OWNS respected | `git diff --name-only` gains nothing outside: `scripts/ci_gate.py`, `scripts/env-audio.sh`, `scripts/install_speech_services.sh`, `scripts/install_perception_jetson.sh` (new), `.github/workflows/ci.yml`, `tests/test_hw7_*.py`, `scrum/20260822/task_42/*` |
| **G4** | No other card's region touched | every `scripts/ci_gate.py` hunk of mine lies outside XD-1's (551-560, 603-791, 2262-2277), GATE-0b's (794-943, 2175-2180, 2278-2283, 2287-2296) and HW-6's (946-1068, 2172-2179, 2255-2263) fences, verified by line range after the edit |
| **G5** | Nothing left running | zero pytest processes, no container, `tools/list_parcel_procs.py` clean at close |
