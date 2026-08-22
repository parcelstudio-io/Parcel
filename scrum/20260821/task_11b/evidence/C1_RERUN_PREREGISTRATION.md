# C-1 re-dispatch — pre-registration (written BEFORE any measurement)

**Executor:** Claude Opus (re-dispatched C-1) · **Written:** 2026-08-21 ~19:35 EDT
**Tree:** HEAD `71b39a1`, working tree = the certified set named in
`AUDIT_W1_INCIDENT_FABLE.md` §"Final verification".

This file is written before one line of C-1 source is edited and before any
C-1 number is measured. Anything measured later is compared against THESE
targets. Targets are not edited after the fact; misses are recorded as misses.

## 0. Provenance of the numbers I already know

Honesty requirement: I am NOT pre-registering in ignorance. The reverted
collision-window run left a status doc (`C1_STATUS.md`, 18:40) reporting
CPU detector p50 ≈ 516 ms, publish latency p50 ≈ 552 ms against a 300 ms TTL,
and a whole-loop p99 delta of +27.209 ms against a +5 ms bound. That code is
gone from the tree; I re-derive my own implementation and my own numbers. But
I know roughly where the CPU path lands, so pre-registering a target I already
expect to miss and calling it a prediction would be theatre. Instead, where I
expect a miss I **declare the deviation here, in advance, with its mechanism**
— which is exactly what the dispatch brief asked for ("measure the latency
delta against the card's bound and either close it or pre-register it as a
deviation").

## 1. Environment, measured before targets are set

| Fact | Value |
|---|---|
| venv | `/home/jaewoo-jang/Desktop/Projects/Parcel/.parcel` |
| onnxruntime | 1.28.0 |
| available EPs | `['AzureExecutionProvider', 'CPUExecutionProvider']` |
| CUDAExecutionProvider | **ABSENT** |
| GPU present | NVIDIA RTX 5000 Ada, 32,760 MiB (used 934 MiB idle) |
| OWLv2 weights | `~/.cache/parcel/owlv2-b16/model_int8.onnx`, 163,173,570 B |
| Entry gate | PASS, 7,746 passed / 9 skipped, 336.4 s |

The absence of `CUDAExecutionProvider` in the normal `.parcel` environment is
a fact of the deployment, established before targets were chosen. It makes the
no-CUDA path the *only* measurable path here, which is why P5 below exists.

## 2. Pre-registered acceptance targets

| ID | Target | Bound | Disposition if missed |
|---|---|---|---|
| **P1** | Flag-off wire identity | OFF `/api/state` has NO `camera_ingress` key; OFF snapshot byte-identical between "key absent" and "explicit false"; ingress factory never called | Hard fail — the R1 discipline |
| **P2** | Configured-rate flow | configured 2.0 Hz; achieved ≥ 1.60 Hz | **Pre-declared deviation risk:** CPU int8 OWLv2 is ~0.5 s/inference, so a 2.0 Hz *configured* cadence is detector-bound and cannot be met by construction. Recorded as measured; the honest claim is "cadence floor respected, detector-bound rate reported truthfully" |
| **P3a** | **Safety-path latency delta (the card's bound)** — reactive-safety dispatch p99, ingress ON vs OFF | **≤ +5.0 ms** | Recorded as measured. This is the path the card actually names ("person-yield and reactive safety never queue behind a frame") |
| **P3b** | Whole control-loop `ControlLoopWork` p99, ON | **< 100 ms** (the 10 Hz deadline) | Hard requirement: exceeding it means ingress broke the control loop |
| **P3c** | Whole control-loop p99 delta ON−OFF | reported, no bound | **Pre-declared deviation:** the panel-local EGL render + CPU int8 detector run in-process and contend for CPU. I predict this delta exceeds +5 ms and I say so BEFORE measuring. The acceptance for the loop is P3b (the deadline), not a +5 ms delta; P3a is the safety claim |
| **P4** | Freshness self-report | capture-start→publish measured against `DEFAULT_DETECTION_TTL_NS` (300 ms); **every** frame's `expired_at_publish` must agree with its own clocks; snapshot must say `stale` when the newest frame is past TTL | **Pre-declared deviation:** on CPU the publish latency will exceed 300 ms, so frames WILL be expired at publish. The acceptance is that the indicator is *honest*, not that it is green. Moving receive-time after inference or widening the TTL to turn the light green is explicitly forbidden here |
| **P5** | **No-CUDA path evidence** | An explicit measured row: ORT version, available EPs, requested vs resolved provider profile, model digest, and detect latency on that provider. No GPU-residency claim may be made without process attribution | Hard: an assumption in place of a measurement is a fail |
| **P6** | **Fresh frames post-dispatch** | Every frame in the live cell has a capture wall-clock strictly AFTER this executor's run-start stamp; the evidence directory is new and empty before the run | Hard: reusing the reverted run's expired captures is a fabrication |
| **P7** | Bounded queue + drop counting | push N+k frames at capacity N ⇒ retained ≤ N, `frames_dropped == k`, and per-frame detection truncation counted separately | Hard |
| **P8** | EV-1 integration | perception rows persisted, strictly decodable, bounded per row; `verify_event_log(rows) == []`; final row `log_closed` | Hard |
| **P9** | Mutation seeds | **≥ 8** real source seeds, each RED, each byte-restored, each named test GREEN after restore; `__pycache__` purge per restore; fresh-interpreter canary; final sweep postdating the last source write; repo-root stray sweep | Hard |
| **P10** | Exit gate | `scripts/ci_gate.py` PASS, every hard gate green | Hard |

## 3. Explicit non-claims, fixed in advance

C-1 will NOT claim, regardless of what the numbers say: real D455 recognition,
detector-backed person safety, GPU residency attributed to the detector
process, a navigation/patrol mission, statistical latency equivalence, or
fitness of this stream for C-2/C-3 grounding authority. The stream is
proposal/diagnostic only and does not touch `_semantic_candidates` authority.

## 4. Method notes fixed in advance

* OFF and ON arms are **symmetric**: both build a real runtime via the same
  non-test composition path and both bind a real HTTP server, so the OFF arm
  is not accidentally cheaper by lacking a thread. (The reverted run's first
  cell got this wrong and had to be re-run; I adopt its correction up front.)
* The safety-latency cell (P3a) measures the **reactive-safety dispatch**
  specifically, not only the aggregate loop, so the card's actual claim is
  testable rather than confounded by render/detect CPU cost.
* The owner store `parcel_memory.sqlite3` is read-only throughout; its SHA is
  captured before and after and must be unchanged.
* One sequential descriptive ON/OFF pair is NOT a counterbalanced statistical
  study and will be labelled as such.
