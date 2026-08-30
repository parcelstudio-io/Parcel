# MJLAB-1 verdict

## Decision

Adopt the official `unitree_rl_mjlab` stack—at commit `1425b15` and under
`constraints.txt`—as Parcel's candidate **lower-locomotion simulation and
training substrate**. Do not treat it as Model A, a navigation simulator, a
conversation simulator, a deployable policy, or physical mount evidence.

Strict preregistered verdict: **FAIL**, because the upstream-declared clean
install does not import on the current resolver. Practical pinned-environment
verdict: **PASS for bounded simulator plumbing**. Physical motion verdict:
**NO-GO**.

## How it should fit Parcel

Use a hierarchy:

1. Model A / the task executive proposes an interruptible semantic task and a
   bounded base-velocity or locomotion-skill request.
2. A trained and separately promoted lower policy converts that request plus
   proprioception into 12 joint targets.
3. Parcel's local ControlManager, independent safety supervisor, leases, and
   commissioned sole-writer gateway retain final authority. The hosted model and
   upstream Go2 deployment sample never receive direct motor ownership.
4. Authenticated execution receipts—not policy intent—feed Model B and the
   conversational narrator.

## Required work before this becomes useful beyond research

1. Turn `constraints.txt` into a hermetic container/lock for x86 training and a
   separately measured aarch64/AGX Orin inference image. Add a CI import/task
   smoke so upstream dependency drift fails early.
2. Train a real Go2 velocity policy and gate held-out velocity tracking, fall and
   illegal-contact rate, energy, disturbances, rough terrain, stairs, payload
   mass/inertia, actuator delay, friction, sensor noise, and recovery. The
   retained three-iteration checkpoint must never be deployed.
3. Add an explicit adapter at the Parcel motion-authority boundary. Verify joint
   order, units, limits, timestamp/lease expiry, stale-policy STOP, rate limits,
   and safe fallback before any Unitree SDK write.
4. Model the EDU+ payload, AGX Orin, camera, Mid-360, speaker/microphone, and
   mounting geometry. Benchmark the exported policy on Orin under simultaneous
   perception, audio, and logging load.
5. Keep semantic perception, pedestrian prediction, social navigation,
   interruption/resume, and conversation in Parcel's higher simulator/eval
   layers. Extend simulation with sidewalk, crosswalk, elevator, stair, lost-owner,
   dynamic-human, acoustic, and Starlink fault suites; MjLab currently supplies
   none of them.
6. Run the trained artifact through upstream's separate `unitree_mujoco`
   deployment path, then motors-disabled HIL, suspended/tethered low-speed tests,
   and measured STOP-distance/fault-injection gates. Require an independent
   safety process and physical e-stop before untethered motion.

This substrate is a strong replacement candidate for Parcel's previously
refuted toy `Go2Env`; it is one lower layer in the production stack, not the
companion robot itself.
