# Task 20 — GATE-0: the gate tells the truth on a clean clone

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply: prototype not production, Edit-only, git read-only
for executors, targeted tests + ruff; only the verifier runs the full gate).
**Evidence:** `PLAN_ASSESSMENT_FABLE.md` Phase 0 (all seven mechanisms
CONFIRMED by a read-only refuter); the Sol session's
`INTEGRITY_GATES_TODO.md` IG-1/IG-2 (same scope, unexecuted, author not
live) — reference it, execute the narrowed version here.

## Why
On a fresh clone `scripts/ci_gate.py --tier commit` aborts ~1 s into
`hard-safety` with an unhandled `ValueError`: both product scenes
`<include>` `../../../third_party/unitree_mujoco/unitree_robots/go2/go2.xml`
(`city_block.xml:17`, `city_block_b.xml:28-29`), the directory is blanket-
gitignored (`.gitignore` `third_party/`), and no workflow fetches it.
`evaluate_hard_safety` propagates the exception (`ci_gate.py:682-810`, no
`except`), `run_commit_tier` is a straight-line list build, so the traceback
skips every later gate and `--json` never emits. Separately: ruff is
range-pinned (`>=0.12,<1`) and the ratchet baseline records no version, so
the verdict depends on the ruff pip resolves (7 fingerprints on 0.16.x, ~51
on 0.15.x); `realtime/protocol.py:415` (`MappingProxyType({})` default) breaks
import on exactly CPython 3.11 while `requires-python >= 3.10`; `ci.yml` sets
`MUJOCO_GL: egl` on a GPU-less runner. Nothing later is verifiable until the
gate runs where nobody has a developer cache.

## Work
1. **Vendor the Go2 MJCF subset** (the ~20 files the two scenes need, ≈28 MB)
   at its current path with a `.gitignore` carve-out and
   `third_party/unitree_mujoco/PROVENANCE.json` pinned to revision
   `ae6a8403e272733e9996ef59990880330496177f` (the revision checked out on
   this host) with per-file sha256 and the upstream license. Add a
   `unitree-assets` hard gate before `hard-safety` that checks the manifest
   closure and compiles both product scenes (geometry only — the held-out
   scene is compiled, never rendered, never run through a model; take the
   allowlist seat in `tests/test_held_out_scene.py` and grow the load-pair
   deliberately). Remove the four `skipif` guards that only covered the flat
   scene.
2. **Containment:** every evaluator in `run_commit_tier` runs under a
   per-stage wrapper — `except Exception` (never `BaseException`) →
   `GateResult(name, 'error', traceback tail)` — so the summary and `--json`
   always emit. Seeds RED: a first evaluator that raises must still yield the
   full JSON with nine named results.
3. **Pin ruff** `==0.16.1` (the lock's version) in the dev extra; stamp
   `ruff_version` into `scripts/ci_ruff_baseline.json` and refuse a baseline
   whose version differs from the running ruff; lint
   `scrum/20260822/task_9/evidence/*.py` (six new fingerprints otherwise go
   red on the next commit). Fingerprints must stay 7.
4. **`protocol.py:415`:** `field(default_factory=lambda: MappingProxyType({}))`
   + a two-instance regression test; `requires-python` wording narrowed to
   what is exercised (3.12 CI, 3.14 dev) or the 3.11 path proven —
   `~/.local/bin/python3.11 -c "import parcel_robot.realtime.protocol"` green.
5. **`ci.yml`:** `MUJOCO_GL: osmesa` on hosted runners; the commit tier
   target so that enabling Actions (B20, the owner's admin click) can yield
   a green run.
6. **Docs drift with a physical consequence:** `README.md:152` and
   `docs/MOTION.md:374` document `--vx 0.05 --duration 1 --arm`, which cannot
   parse — `docs/` and `README.md` belong to another session tonight, so
   write the corrected snippet into this card's status doc as a handoff and
   do NOT edit them.
7. Pre-register: a scratch `git clone` + `pip install -e ".[dev,voice]"` +
   `ci_gate.py --tier commit --json` produces a JSON summary (red or green)
   with no traceback; both scenes load in < 1 s without a developer cache;
   vendored tree ≤ 30 MB.

OWNS: `third_party/unitree_mujoco/unitree_robots/go2/**` (vendored subset) +
`PROVENANCE.json`, `.gitignore`, `scripts/ci_gate.py` (`run_commit_tier`
wrapper + new `unitree-assets` stage — XD-1 task_14 also owns this file:
re-read before every edit and keep to those two regions), `scripts/ci_ruff_baseline.json`,
`tests/test_ci_gate.py`, new `tests/test_unitree_asset_pack.py`,
`tests/test_held_out_scene.py` (one seat + one pair entry), `pyproject.toml`
dev extra, `src/parcel_robot/realtime/protocol.py:415` + its test,
`.github/workflows/ci.yml`, `scrum/20260822/task_9/evidence/*.py` (lint
only), `task_20/` docs. MUST NOT TOUCH: `docs/`, `README.md`, `backlog/`,
evaluator internals beyond the wrapper, frozen manifests.

## Definition of done
Clean-clone row green (the scratch clone's JSON in the status doc); seeded
raising-evaluator row; ruff pinned with 7 fingerprints on 0.16.1; 3.11
import green; `GATE0_STATUS.md` in the lightweight register.
