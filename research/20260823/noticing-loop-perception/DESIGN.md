# H6 — the noticing loop · DESIGN (Fable) · 2026-08-23

## Hypothesis (falsifiable)
A continuous open-vocabulary **noticing loop** — OWLv2 fp16 on CUDA at
640×360 through the repo's own `perception_daemon`, SigLIP-2 crop embeddings,
and a **novelty score** (1 − max cosine against the running map) — sustains
≥ 10 Hz with detect p95 < 100 ms, produces ≤ 1 false noticing per minute,
separates new from already-seen objects with AUC ≥ 0.8, and publishes every
frame inside the 300 ms `DEFAULT_DETECTION_TTL` (today: 562 ms capture→publish,
16/16 expired). Separately: through the repo detector (not torch), a single
threshold gives real-photo person recall ≥ 0.75 at a render-side FP rate no
worse than today's int8 point.

## Why (perception survey 2026-08-23)
- "Generalized perception that keeps learning" needs a loop that *chooses
  what to look at*; today the query batch is operator-configured, ingress is
  2 Hz with a 16-phrase cap, the awareness sweep ships OFF, and there is no
  novelty/surprise signal at all.
- The freshness contract is violated by design (562 ms vs 300 ms TTL,
  `camera_channel/ingress.py:~1800`); nothing perceptual can be reactive
  until it closes. fp16 + downscale measured 15.7/18.8 ms per frame — the
  loop has never been re-measured after that.
- Every recognition number is on renders the VLM control calls "colorful
  geometric shapes"; 0/69 person recall on renders vs 127/156 on photos.
  The operating point for the real dog must come from real photos through
  the *repo's* ONNX path (torch fp16 and ONNX fp16 already disagree 49 vs
  37 TP on identical frames, `perception/providers.py:~165-180`).
- No depth ⇒ zero map writes (UVC venue publishes nothing). The RGB-only
  null result is a deliverable: it decides whether monocular depth or a
  ground-plane fallback is a milestone card.

## Objective
Measure whether continuous, novelty-driven looking is affordable on the
GPU we have (and, by ratio, on an Orin-class device), and find the real-world
detector operating point.

## Experiment
1. **Daemon on CUDA**: `PARCEL_PERCEPTION_PROVIDER=cuda_fp16`, `PARCEL_OWLV2_ONNX`
   + `PARCEL_SIGLIP2_ONNX` set, `perception_daemon` started by the harness
   on its own socket (never the owner's).
2. **Source**: if `/dev/video*` exists, `uvc` at 640×360 for a 20-minute
   desk session (record 200 hand-labelled frames); else the `recorded`
   backend over the real-photo set used by `scrum/20260821/perception/bench_detectors.md`
   (156 photos) + the 69 render frames, streamed at 10/15/20 Hz.
3. **Noticing loop** (`perception/noticing.py`, new pure module + harness
   loop): per frame → detections → crop embeddings → novelty = 1 − max
   cosine vs the running gallery/map → a `Noticing(frozen)` event when
   novelty > τ and the detection passes the abstention gates; rate-limited.
4. **Freshness**: measure capture→publish latency per frame; count frames
   published past TTL; try the fp16+640×360 path and, if needed, move
   preprocessing (73 % of latency is CPU-side) into the daemon.
5. **Operating point**: sweep `PARCEL_OWLV2_THRESHOLD` over the photo set
   and the render set through `OwlV2Detector` + `localize_frame`; report
   recall/precision per venue per threshold and the ONNX-vs-torch delta.
6. **Contention**: repeat the 10 Hz loop while the GPU reasoner (`:8081`)
   generates 256 tokens continuously (H2 shares the GPU in the real design);
   record detector p50/p95 idle vs contended and any silent CPU fallback
   (`assert_provider_honoured`).
7. **RGB-only**: run the loop with `has_depth=False`; count map writes
   (expected 0) and document what a monocular-depth fallback would need.

## Measurements (pre-registered)
| row | metric | criterion |
|---|---|---|
| P1 | sustained FPS at 640×360, GPU-util, VRAM, CPU share | ≥ 10 Hz; report |
| P2 | detect p50 / p95 | p95 < 100 ms |
| P3 | frames published past 300 ms TTL | 0 (report the latency histogram) |
| P4 | false noticings / min at τ (hand-labelled sample) | ≤ 1 |
| P5 | novelty AUC new-vs-seen | ≥ 0.8 |
| P6 | real-photo person recall at chosen threshold; render FP rate | ≥ 0.75; ≤ int8 today |
| P7 | contended p95 with reasoner generating | ≤ 150 ms, 0 past TTL |
| P8 | map writes with RGB-only | reported (expected 0) |

## What would refute it
P1/P2 fail on this GPU ⇒ continuous looking must be duty-cycled (report the
Hz that fits); P3 cannot reach 0 ⇒ the TTL or the pipeline must change and
the design says which; P6 < 0.6 at every threshold ⇒ the detector seat is
wrong for people (NanoOWL/Grounding-DINO become a milestone decision).

## Evidence tier / does not prove
`desktop` (real photos are `desktop-real-sensor` only if a webcam is
present). Proves loop cost and the operating point on this GPU; does not
prove Orin throughput, live-scene recall, or that the runtime consumes
noticings (product wiring is a milestone card).

## OWNS
`research/20260823/noticing-loop-perception/**`, new leaf
`perception/noticing.py`, additive knobs in `perception_daemon/server.py`
(preprocessing placement) behind env flags default-off, one capability
test `tests/test_h6_noticing.py`. Must not touch: `camera_channel/ingress.py`
control flow (measure it; propose changes in RESULTS), `runtime.py`,
navigation, the owner's stack.
