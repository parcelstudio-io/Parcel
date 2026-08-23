# Task 42 — HW-7: `gate-on-aarch64` — the same `--tier commit` gives an honest verdict on the Orin

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 rules + anti-crash rules; wave-3 COMMON brief). **Design:**
`../WAVE3_HW_DESIGN_FABLE.md` §4 rows S21/S26, §5.1 (amended: product venv
= uv CPython 3.12; 3.10 floor for vendor venvs), §5.2, §9 HW-7.
**Evidence:** GATE-0b's `skip-list` row + `tests/_external_roots.py`
(`skip_unless`, printed reasons — the pattern), HW-1's
`requirements-lock-jetson.txt` (cp310) and `requirements-lock-jetson-py312.txt`
(cp312: 17 packages, zero missing) + H3 (onnxruntime-gpu has no aarch64
wheel at any version) + `perception-jetson` extra, `scripts/env-audio.sh:58`
(`usr/lib/x86_64-linux-gnu`, amd64 .debs), `scripts/install_speech_services.sh:52`
(`piper_linux_x86_64.tar.gz`), `.github/workflows/ci.yml` (3.12 commit job;
nightly via `scripts/run_nightly.py`).

## Why
The gate's rows assume this desktop: CUDA, x86 wheels, the RTX detector,
MuJoCo. On the Orin every one of those must become a PRINTED
`skip-with-reason`, not a silent pass or a crash, so `ci_gate.py --tier
commit` prints the same row set minus the declared skips. Nobody has run
the gate on aarch64; this card proves it in an emulated aarch64 container
on the desktop (slow; nightly), not on hardware.

## Work
1. `DESIGN.md` first: the row-by-row table — for each commit-tier stage,
   what it needs (CUDA / x86 wheel / GPU / MuJoCo / external root) and its
   aarch64 disposition (runs / skip-with-reason / typed SKIP row), cited to
   the stage's code; how the skip is DECLARED (a `host_capabilities`
   probe: `platform.machine()`, CUDA present, MuJoCo importable) and where
   it is printed (GATE-0b's skip-list row shape — extend inside a NEW
   `CARD HW-7` region, never inside GATE-0b's four); the aarch64 variants
   of `env-audio.sh` / `install_speech_services.sh` selected by `uname -m`
   (PortAudio from source or the distro's aarch64 .debs; Piper's aarch64
   asset name — cite the release page; llama.cpp build flags); the
   `perception-jetson` install script (ort-gpu from the Jetson index —
   UNCONFIRMED URL → UNCONFIRMED in the script's message, refuse rather
   than guess).
2. The `host_capabilities` probe + the typed SKIP rows (marked
   `CARD HW-7` regions in `scripts/ci_gate.py`); every skipped row prints
   the reason and the command that would un-skip it.
3. `scripts/env-audio.sh`, `scripts/install_speech_services.sh`: `uname -m`
   branches (x86 path byte-identical — pin it by diffing the x86 branch
   against HEAD), aarch64 path written, dry-run mode (`--dry-run` prints
   what it would do).
4. `scripts/install_perception_jetson.sh` (new): installs the
   `perception-jetson` extra into a named venv, records the ort-gpu wheel
   provenance, refuses on x86.
5. The emulated proof: `docker run --platform linux/arm64` (qemu-user;
   check `docker` + binfmt exist — `docker run --rm --platform linux/arm64
   python:3.12 uname -m` must print `aarch64`; if not available, record
   it and fall back to a `PARCEL_HOST_ARCH=aarch64` override of the probe
   on x86 as the measured proof, clearly labelled) running `pip install
   -e '.[base]'` from the py312 jetson lock and `ci_gate.py --tier commit
   --json` through the wrapper (**rule 3 exception, like GATE-0b's: ONLY
   inside the container, ONLY through `pytest_guard.sh --label hw7`, AT
   MOST TWO runs**); the JSON diffed against the desktop's row set: the
   difference must be exactly the declared SKIP set.
6. `.github/workflows/ci.yml`: a nightly aarch64 job (emulated) — the file
   must parse; B20 stays the owner's click.
7. Tests `tests/test_hw7_gate_aarch64.py`: the probe's outputs on this
   host; each typed SKIP row's reason text pinned; x86 branches
   byte-identical; seeds RED (a row that needs CUDA and is not declared
   goes red under the aarch64 override).

OWNS: `scripts/ci_gate.py` `CARD HW-7` regions, `scripts/env-audio.sh`,
`scripts/install_speech_services.sh`, `scripts/install_perception_jetson.sh`
(new), `.github/workflows/ci.yml` one job (marked), `tests/test_hw7_*.py`,
`task_42/` docs. MUST NOT TOUCH: any hard gate's verdict logic, XD-1's
three / GATE-0b's four / HW-6's regions, `pyproject.toml` (HW-1's extras
stand), the locks, `tools/xvf3800_probe.py`.

## Definition of done
Emulated aarch64 gate JSON = desktop rows minus exactly the declared
SKIPs (or the labelled override proof with the reason); x86 scripts
byte-identical; aarch64 branches dry-run clean; seeds RED;
`HW7_STATUS.md` with pre-registered rows. Gate runs: ≤ 2, container only.

## Hardware-compat (§e)
This card IS §e for the gate: say what emulation proves (import/collect/
verdict shape) and what only the Orin proves (latency, CUDA EP, wall-clock).
