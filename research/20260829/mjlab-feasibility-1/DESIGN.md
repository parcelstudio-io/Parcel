# MJLAB-1: official Unitree Go2 simulator feasibility probe

**Preregistered:** 2026-08-29, before the first task import, environment reset,
or training invocation.  Repository cloning and documentation inspection had
already occurred; no simulator result had been observed.

## Question

Can the official Unitree `unitree_rl_mjlab` Go2 stack serve as a technically
real simulation substrate for Parcel's lower locomotion layer without being
mistaken for proof of companion navigation, conversation, or physical safety?

## Frozen source and isolation

- Upstream: `https://github.com/unitreerobotics/unitree_rl_mjlab.git`
- Commit: `1425b15f73bd4095f0df53709d7c389c3eb9e790`
- Upstream-declared dependencies: `mjlab==1.2.0`,
  `mujoco-warp==3.5.0`
- Python: isolated CPython 3.11 virtual environment under the task cache
- Parcel's `.parcel` environment and production configuration are not modified
- No robot, DDS interface, owner service, or live Parcel socket is contacted

The source checkout and virtual environment live outside the repository.  This
directory retains the exact commands, machine-readable measurements, and
interpretation, but not third-party packages or assets.

## Hypotheses and frozen gates

### MJF-H1 — install and task registration

**Support** only if the pinned stack installs successfully, imports without
source edits, and the registry contains exactly named `Unitree-Go2-Flat` and
`Unitree-Go2-Rough` tasks.

### MJF-H2 — headless physics execution

**Support** only if `Unitree-Go2-Flat` can be constructed headlessly with at
least 64 parallel environments, reset, and stepped for at least 256 policy
steps with:

- zero uncaught simulator errors;
- finite actor observations, rewards, and robot state at every checked step;
- action and observation dimensions recorded from the environment rather than
  assumed; and
- aggregate throughput at least 3,200 environment-steps/s (64 environments at
  50 policy steps/s), excluding one-time compilation and initialization.

The probe uses deterministic, bounded actions and a fixed seed.  A pass is a
pipeline/throughput result, not a locomotion-quality result.

### MJF-H3 — train/checkpoint pipeline

**Support** only if a deliberately tiny, fixed-seed PPO smoke run completes at
least three learning iterations on `Unitree-Go2-Flat`, writes a nonempty native
checkpoint, and its logs/configuration record the requested environment count
and iteration count.  No reward-improvement claim is permitted at this scale.

### MJF-H4 — Parcel applicability

This is an architectural assessment, not a binary runtime gate.  The stack is
considered **useful for lower-layer locomotion research** if H1–H3 pass and the
inspected Go2 model exposes the expected 12 leg joints, contact sensing,
velocity-command task, terrain/randomization hooks, and ONNX-oriented deployment
workflow.  It is explicitly **not sufficient for Model A / Model B promotion**
unless a later integration adds Parcel's camera/LiDAR/audio semantics, dynamic
humans, task ledger, interruption contracts, acoustic/network faults, and an
independent execution-receipt oracle.

## Procedure

1. Record OS, GPU/driver, Python, upstream commit, installed package versions,
   source hash, disk footprint, and install timing.
2. Import the registry and record all Unitree Go2 task IDs.
3. Instantiate the flat task headlessly, reset it, derive spaces/shapes, run a
   warm-up, then a timed 256-step deterministic-action loop.  Fail immediately
   on non-finite values or API errors.
4. Run the upstream trainer with small frozen overrides: 64 environments, three
   learning iterations, checkpoint interval one, fixed seed 42, one GPU.  Keep
   the complete stdout/stderr and hash the produced checkpoint/config files.
5. Independently verify the JSON artifact and file hashes.  Repeat the physics
   probe once in a fresh process to expose initialization-only success.

If resource contention with another preregistered experiment is present, defer
the GPU portions rather than silently reducing these gates.

## Interpretation boundary

Passing all gates establishes that the official stack is runnable on this
workstation and is a credible replacement for Parcel's already-refuted toy
`Go2Env` locomotion-training substrate.  It does not establish actuator fidelity,
Go2 EDU+ payload dynamics, Mid-360/camera calibration, real stair/elevator or
pedestrian safety, Orin performance, deployment-controller compatibility, or any
physical mount-readiness claim.
