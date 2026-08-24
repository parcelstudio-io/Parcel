# Research program 2026-08-23 — "the living dog" · design owner Fable (parcel-fb)

Owner directive (verbatim intent): assess progress toward a prototype that
mounts on a Unitree Go2 EDU+ — and later on our own custom robot — and
behaves like a living dog: seamless, interesting conversation; autonomous
indoor/outdoor navigation; generalized perception; recursive learning about
the owner and the world (SLAM, memory); continuous self-initiated behavior
(breathing, looking around, checking things, starting conversation) with a
motion planner that is always emitting. Hosted chat-API spend ≤ **$200/month**;
local models and the controller keep running while the dog learns and
reacts. Ideate, test hypotheses, then write the milestone-1 design.

Roles: **Fable designs (DESIGN.md) and verifies (VERDICT.md); Opus
implements (code + RESULTS.md).** Program rules: `research/README.md`.

## Grounding this program stands on (2026-08-23, HEAD d097ba7 + DEC-FS-1)
Seven read-only surveys (conversation/cost, navigation+SLAM+physical path,
perception, memory/learning, lifelike behavior, portability seams, the design
corpus) plus the owner's real spend ledger, the pricing page, and the host
inventory. The decisive facts:

1. **Money.** gpt-realtime-mini audio is $10/M tokens in (600 tokens per
   minute of listening) and $20/M out, cached audio $0.30/M. A hosted ear
   left open 12 h/day costs ≈ $130/month *in silence* — the hosted lane can
   never be the always-on ear. The owner's ledger (`recordings/spend.jsonl`,
   18 responses ≈ $0.19 at the module's ASSUMED rates) counts tokens without
   an audio/text split and prices them at the FULL model's text rates; the
   true per-turn cost is unknown until the split is recorded.
2. **Compute.** The pinned llama.cpp `b10235` binary has no CUDA device; the
   owner's `:8080` gemma-26B reasoner runs on 48 CPU threads (19.7 s median
   usable-plan latency measured; 5.66 s / 855 ms TTFT on the admitted CUDA
   `b10236` rootfs that `scripts/launch_reasoner_gpu.sh` serves on `:8081`).
   The RTX 5000 Ada (32 GB) is ~94 % idle. OWLv2 fp16 on this GPU is 16–83 ms
   per frame; SigLIP-2 4 ms. Continuous local cognition + perception on one
   GPU is a measurement away, not a purchase away.
3. **Learning is built and dormant.** Owner-fact distillation, consent, soft
   delete, provenance, the tiered memory, the learned semantic map with
   decay and k=3 naming all exist and are tested — and **nothing schedules
   distillation**, tiers 2/3 are not persisted, there is no episodic layer,
   no person registry, no place containers, and no `where_is` tool.
4. **Initiative exists as doors, not drives.** Curiosity whisperer (4–8 min
   gaps), AWARE-1 head-turn (ships OFF), ROAM (stays within ~3 m of home,
   measured), the attention arbiter (pure module, not instantiated by the
   runtime). Expression breathes/nods at 50 Hz in MuJoCo only; the Go2 path
   has no verified expression primitive. Narration blocks the 10 Hz loop.
5. **Perception has never seen a photon.** Person recall is 0/69 on MuJoCo
   renders vs 127/156 on real photos (same OWLv2) — sim recall numbers are
   uninformative. Capture→publish 562 ms against a 300 ms TTL. No depth ⇒ no
   map writes. No terrain/drop-off estimator. No detector runs on an Orin
   today (no ORT aarch64 wheel).
6. **Localization is a seam, not a filter.** `PoseProvider` (MAP/ODOM,
   covariance, health) with calibrated drift models and a chance-constrained
   region test — and no estimator anywhere. The Go2 backend refuses every
   motion method by design until a native sole-writer gateway exists (the
   contract + fake gateway exist; the process does not).
7. **Portability seams are real.** `LocomotionController` + `RobotStateSource`
   (control/base.py) and `SimulatorBackend`; vendor SDKs imported only inside
   methods; `mock_vendor.py` is the worked second-vendor proof. The leak is
   the observation carrier (`SimObservation`, stamped SIMULATION by
   construction) and Go2 literals in `RobotProfile`.

## The hypotheses (each a folder; DESIGN.md is the contract)

| # | folder | hypothesis in one line | tier | headline metric |
|---|---|---|---|---|
| H1 | `ambient-ear-cost-ladder/` | A $0 local ear + local engagement triage + hosted-only-when-engaged keeps a 12 h/day companion under $200/month with hosted quality on the turns that matter | replay + hosted-live (≤ $2) | projected $/month at 3 policies; audio/text token split measured |
| H2 | `local-cognition-gpu/` | A GPU-resident local model can run a continuous inner-monologue tick (notice → decide to speak/look/ignore) at ≤ 300 ms p50 while sharing the GPU with perception | desktop | tick p50/p95 under contention; decision quality vs judge |
| H3 | `drives-and-initiative/` | A persistent drive model over the existing stimulus/attention seams produces self-initiated look/approach/remark/go-check behaviors at a tunable rate that leaves the doorstep, yields to the owner within one tick, and stays under an annoyance budget | desktop-sim | initiations/h by kind; max radius; preemption latency |
| H4 | `continuous-body-intent/` | One body-neutral `BodyIntentV1` stream (gaze, posture, breathing, locomotion, hold) at ≥ 20 Hz with jerk bounds and instant preemption can be implemented by Go2 Sport primitives *and* a fake custom quadruped from the same capability manifest | desktop-sim | emission rate; jerk; preemption; adapter LOC |
| H5 | `governed-continual-memory/` | Scheduled distillation + persisted tiers + an episodic layer + a `query_world` path raise held-out memory probes to 13/13 with a live summarizer, fact precision ≥ 0.9, zero revoked facts resurfacing, and answer "where is X" from the learned map | replay / synthetic | probe pass rate; precision; revocation leaks; world-query top-1 |
| H6 | `noticing-loop-perception/` | Continuous open-vocab noticing with novelty scoring runs ≥ 10 Hz on fp16 CUDA with ≤ 1 false noticing/min and closes the 562 ms→300 ms freshness violation; the real-photo vs render operating point is found through the repo's own detector | desktop (recorded/EGL; real webcam if present) | FPS, p95, FP/min, novelty AUC, TTL compliance |
| H7 | `localization-delegation-bench/` | A delegated scan-matching localizer (KISS-ICP class) behind `PoseProvider`'s MAP role satisfies the T_map_odom/covariance/health/jump contract on simulated Mid-360 scans, and the navigation consumers survive the calibrated drift ladder | desktop-sim | ATE/RPE vs truth; jump magnitude; SR across the pose ladder |

Deliberately NOT hypotheses (design decisions, not experiments): the native
sole-writer gateway (bench exists; build is a milestone card), box-day
bring-up (hardware), Orin deployment (aarch64 ORT is a packaging problem),
outdoor ODD (after indoor).

## Dispatch and verification protocol
- Executors start only after DEC-FS-1 lands (tree-wide import rewrites in
  flight); they read `research/README.md`, their DESIGN.md, `CLAUDE.md`.
- OWNS per hypothesis are in each DESIGN.md; they are disjoint. No full
  suites — targeted tests only (reduced testing policy). GPU experiments
  (H2, H6) record concurrent load and re-measure headline rows alone.
- Hosted spend: H1 only, capped at **$2.00** total, recorded per response
  with the audio/text split; everything else is $0.
- Verification (Fable): re-run the headline row, product-path check
  (reachable from `RobotRuntime`/the lanes, or harness-only — say which),
  refute-first read of RESULTS.md, VERDICT.md per folder.
- Output of the program: `MILESTONE1_DESIGN_FABLE.md` in this folder — the
  detailed design for the first physical prototype, grounded in the verdicts.
