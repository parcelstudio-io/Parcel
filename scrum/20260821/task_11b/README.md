# Task 11b — C-1: attach the eye (camera ingress into the live runtime)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence:** recon_wired.md — `runtime.attach_camera_ingress()` exists with
**zero non-test call sites**; the full pixel path (CameraIngress →
MujocoEglCameraBackend → OWLv2 detections) is built and test-proven but has
never run inside the live robot. PG-1 landed the GPU path (86 ms/query) and
the contention guard. **DISPATCH GATE: after W-1 closes** (frames from the
textured world; attaching the eye to a blind world proves plumbing only).

## Work

1. **Wire it, config-gated:** `perception.camera_ingress: true` constructs
   the ingress against the sim's EGL backend and starts frame flow at a
   configured rate (default conservative, e.g. 2 Hz — this is semantic
   perception, not the control loop). Default OFF; fail-closed validation;
   the flag-off wire trace byte-identical to today (the R1 discipline).
2. **Detections become a runtime stream:** timestamped, camera-posed
   detection records (label, score, box, back-projected world point per the
   existing metric_localizer) published into a bounded queue the runtime
   owns, with drop-and-count under pressure. Snapshot surfacing (rates,
   drops, last-detection age) + panel visibility (a small perception tile:
   what the dog currently sees, by class count).
3. **The contention guard in anger:** camera inference must register with
   PG-1's admission mechanism; person-yield and reactive safety never queue
   behind a frame (measure it: safety-path latency with ingress on vs off,
   the delta bounded and pasted).
4. **Evidence integration:** detection stream slices into EV-1's per-session
   evidence log (typed, bounded), so perception is auditable like
   everything else.
5. **Live proof on your own stack:** ingress on, robot patrols (scripted
   mission), detections flow at the configured rate with GPU residency
   within budget; ingress off → byte-identical legacy behavior.

OWNS: `runtime.py` (the attach call + config + stream + snapshot),
`camera_channel/ingress.py` glue (smallest honest touch), the panel tile,
tests, `C1_STATUS.md`.
MUST NOT TOUCH: detector internals (PG-1), lane/broker/ingress(voice),
grounding/semantic_map (C-3 owns the consumer side), yield policy, scene
assets. Standard house rules.

## Definition of done

Gate green; ≥8 seeds RED (flag-off not byte-identical; queue unbounded;
drops uncounted; safety queues behind a frame; stream absent from evidence
log). Live proof with measured rates/latency/VRAM and the safety-latency
delta. `C1_STATUS.md` standard register.
