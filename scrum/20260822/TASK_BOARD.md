# Task board · 2026-08-22 · Wave P0 "Unblock" · Fable

Source: the 2026-08-22 audit ("Parcel Reality Check",
https://claude.ai/code/artifact/4f2ea598-2d09-4909-8aba-b119e02266e0).
Owner directive (2026-08-22, verbatim intent): *the goal is a prototype that is a
good companion, communicates fluidly, navigates semi-autonomously, and has
generalized perception that continuously learns about the world and the owner.
Loosen up production fail-safe logic.*

Roles: **Opus executes, Fable verifies** (fresh gate on the whole tree,
diff-vs-OWNS, independent re-run of one gate per card, adversarial refuters on
wiring cards). One card one executor; cards run in parallel in the SAME tree.

## Standing rules for this wave (supersede the 20260821 register where they differ)

1. **Prototype, not production.** Prefer ask-over-refuse. Do not add new frozen
   digests, allowlists, hash-locks, or refusal paths. Relax behavioral
   fail-closed logic where the card says so. The **physical-safety core is
   untouched**: `core/hard_stop.finalize_command`, the e-stop latch, command
   TTLs/watchdog, `reactive_safety` *semantics* (distances are config and may
   move), `SafetySupervisor.validate`.
2. **Shared tree, concurrent writers.** Another session is editing `docs/**`,
   `backlog/**`, `README.md` right now, and `scrum/20260821/task_20` (MOVE-1)
   has a live patrol sim (pid ~910287) plus a panel on :8765 / `/tmp/parcel_sim.sock`.
   Therefore: never touch `docs/`, `backlog/`, `README.md`, `scrum/20260821/`;
   never kill processes you did not start; launch sims only on a unique socket
   and port; **Edit-only on existing files (never Write a whole existing file);
   re-read before every edit** — `runtime.py` and `pyproject.toml` are edited
   by several cards in disjoint regions.
3. **Git is read-only for executors:** no `add`, `commit`, `stash`, `checkout`,
   `reset`, `restore`. Never revert a file you did not change.
4. **Gates:** run targeted `pytest` + `ruff` for your OWNS; only P0-E runs
   `scripts/ci_gate.py` (once, at its end). Fable runs the full gate on the
   audited tree.
5. **Status doc register (lightweight):** headline · what changed (`git diff
   --stat` on OWNS, insert/delete counts) · how verified (exact commands +
   results; seeded-RED for every new guard) · what it does not prove ·
   deviations from OWNS (declared, with reason) · handoffs.
6. Env: `.parcel/bin/python`, `.parcel/bin/ruff`. Scratch under
   `/home/jaewoo-jang/.cache/parcel-p0-<card>/` (not `/tmp`).

## Cards

| Card | Folder | What | OWNS (summary) |
|---|---|---|---|
| **P0-A** prototype profile & launcher | `task_1/` | `configs/robot.prototype.yaml` + `configs/realtime.prototype.yaml.example`, `--prototype` launcher, overlay loader, single camera flag | configs/*.prototype*, `scripts/launch_stack.sh`, `config.py`, `runtime.py` camera-flag regions, `runtime_assets` mirror |
| **P0-B** hosted-lane companion unlocks | `task_2/` | proactive-motion allowlist, `navigate_to` ask-not-refuse, idle stays live, narration cap, affect on the hosted lane | `realtime/tool_broker.py`, `realtime/config.py`, `realtime/whisperer.py`, `runtime.py` `submit_realtime_transcript` region, `configs/realtime.yaml.example` |
| **P0-C** GPU detector in the production venv | `task_3/` | `onnxruntime-gpu` declared + installed, fp16 artifacts, honoured CUDA provider, measured latency | `pyproject.toml` (perception extra), `scripts/fetch_*.sh`, `perception_providers.py`, `detection_adapter/owlv2_onnx.py`, `instructnav/siglip2_onnx.py` |
| **P0-D** navigation & perception unblocks | `task_4/` | MOVE1-D1 compounding smoother, `ranking_margin ≡ 0`, `set_query` person-drop | `runtime.py` 8396–8460 & 557–575 regions, `core/velocity_smoother.py`, `perception_abstention.py`, `online_map/online_map.py`, `camera_channel/ingress.py`, `configs/navigation/*` |
| **P0-E** gate tiers re-cut | `task_5/` | commit tier = safety core; evidence ratchets → nightly; held-out seat; `pytest -n auto` if xdist-clean | `scripts/ci_gate.py`, `tests/test_ci_gate.py`, `tests/test_held_out_scene.py`, `tests/test_authority_no_literal_drift.py`, `pyproject.toml` (dev extra) |

## CORRECTION 2026-08-22 (owner's statement, authoritative)

**No robot hardware is on hand.** The 'Go2 + D455 + L2 + Orin NX on the bench since 08-13' fact in the
08-22 audit (§10 Phase 4 'hardware track from day 1'; owner actions H-1 Orin identity dump, H-2, H-3)
traces to scrum/20260813/task_1/README.md and is FALSE. Only the reSpeaker XVF3800 mic array is present.
Hardware items below are PURCHASES, not owner actions; the udev rule for the XVF3800 stays real.

## After this wave (not dispatched)

Phase 1 real camera on the desk · Phase 2 owner model · Phase 3 flywheel ·
Phase 4 Go2 commissioning — see the audit artifact §10. Owner actions still
pending: enroll voice (`tools/enroll_owner_voice.py`), udev rule for XVF3800
DoA, quarantine rows 2883–3138 (`tools/quarantine_synthetic_memory.py --apply`),
H-1 Orin identity dump.

## Wave P1/P2 — "Real eyes" + "Owner model" · designed 2026-08-22 · Fable (session 799cb356)

Source: audit §10 Phases 1–2 (parallel once P0 is done). Same standing rules
as P0 (prototype not production; shared tree, disjoint OWNS; Edit-only; git
read-only for executors; targeted tests + ruff; lightweight status register)
plus each card's binding "Build on P0" section. **Host fact:** no camera is
attached (no `/dev/video*`, no RealSense on USB) — P1-A/P1-C live rows are
OWNER-GATED on plugging in the D455 or any UVC webcam; CI rows run on
recorded frames.

| Card | Folder | What | Live proof gate |
|---|---|---|---|
| **P1-A** real eyes | `task_6/` | **ACCEPT_CLOSE** — daemon ~100 ms round trip / ~1 ms boundary, cuda_fp16 honoured, server-side 16-phrase refusal; handoff's missing `origin=` fixed + pinned; RGB-only webcam cannot feed the ingress (D455 is day-one). Live rows OWNER-GATED (camera) | camera (owner) |
| **P1-B** the map learns | `task_7/` | **ACCEPT_CLOSE** — first persisted experience (run 2 from run 1's 69 places), D-R1/D-R2 closed with live proof; store now closed/checkpointed at persist; vacuous owner-store check re-measured; oracle-side union ships OFF (measured 65% truncation) | none (dev scene) |
| **P1-C** which person is you | `task_8/` | **ACCEPT_CLOSE** — uncalibrated gallery claims a stranger on occluded frames (fixed: measured boundary, refuses without a negative); 100 GPU tests; runtime still emits owner 1.0 → OT-2 | camera + enrollment (owner) |
| **P1-D** ask, don't refuse | `task_9/` | **ACCEPT_PARTIAL** — veto seam wired post-verification (product-path row 1 measured); stream-priority claim retracted, budget admission measured; k-gate promotes confident mistakes (45% naming) → NM-1; fixtures committed with CI rows | none |
| **P2-A** owner facts | `task_10/` | **ACCEPT_CLOSE** — owner_facts + distiller + remember_fact with consent; synthetic-range refusal; credential refusal (the one reasonable refusal) + replay redaction added at review; owner store untouched (02:19 write attributed to the owner's own session) | none |
| **P2-B** the dog notices you | `task_11/` | **ACCEPT_CLOSE** — identity is a label by construction (56 arming cases byte-identical), affect on the hosted lane via `_hosted_affect`, greet-on-appearance 2.0 s, storms ≤6/min, zero card spend | none |
| **P1-E** social zone is a config | `task_12/` | **ACCEPT_CLOSE** — approach to 0.71 m with zero contact (MOVE-1 pair reproduced to 0.2 mm), floor 0.68 m named + derived, safety semantics diff empty by the AST ratchet; planner/gate coupling NOT delivered → DOOR-1 | none (MOVE-1 standoff arm re-run) |
| **FZ-1** frozen historical prompts | `task_13/` | historical SI versions render from per-version frozen snapshots, not the live persona files; removes the two `xfail(strict)` markers the owner's 02:10 edit forced | none |
| **XD-1** 52-second commit tier | `task_14/` | classify P0-E's seven xdist divergences (`load_sensitive` serial phase, per-worker tmp), flip default-suite to `-n auto` | none |
| **HY-1** no test leaks a sim | `task_15/` | `test_voice_nav_e2e.py` teardown on setup error, session sim-guard, `launch_sim.sh --pidfile`, `tools/list_parcel_procs.py` | none |
| **VENUE-1** runtime opens the physical eye | `task_16/` | wire P1-A's backends/daemon into `_attach_configured_camera_ingress` (P1-A's HALT), origin= propagated (verifier's catch), MUJOCO_GL preamble skipped for physical venues | camera (owner) for live rows |
| **OT-2** robot stops believing the owner at 1.0 | `task_17/` | wire P1-C's OwnerTracker into the runtime; identity gate consumes state + calibrated margin (0.65 constant retired on the cosine scale) | camera + enrollment (owner) for live rows |
| **NM-1** promotion gate tests correctness | `task_18/` | P1-D's 45% naming / k-gate-promotes-wrong-names miss: detector agreement as an independent judge before a name enters `known_places()` | none |
| **DOOR-1** through a doorway | `task_19/` | obstacle envelope from config with a floor (P1-E pattern), planner inflation actually wired (`gate_clearance_m` has no production setter), follow standoff from config not import | none |

Owner actions this wave unlocks: plug in a camera (P1-A/P1-C live rows);
`tools/enroll_owner_voice.py` (1 min) and the appearance enrollment (10 s);
`tools/quarantine_synthetic_memory.py --apply` BEFORE P2-A's distiller touches
the real store; one full-size gpt-realtime session for the voice-tier A/B.

## Build order — designed 2026-08-22 · Fable (owner's question: what first?)

Published: https://claude.ai/code/artifact/01deb521-023e-4bf1-90cd-4bf722c3b69c
Source: `PLAN_ASSESSMENT_FABLE.md` (the Pre-Purchase Queue assessed claim by
claim: 30 confirmed / 9 stale / 4 refuted; three orderings judged). Answer:
**software and the mic array first; the D455 on day 1; the Go2 is an
evidence-gated week-3 decision.** No robot hardware is on hand.

| Card | Folder | What | Owner present |
|---|---|---|---|
| **GATE-0** the gate tells the truth on a clean clone | `task_20/` | vendor the Go2 MJCF subset @ `ae6a8403`, per-stage containment so `--json` emits on red, `ruff==0.16.1` stamped, `protocol.py:415`, osmesa; narrowed IG-1/IG-2 | no |
| **TURN-1** endpointing is a knob | `task_21/` | `turn_detection` object (server/semantic VAD, eagerness, silence, interrupt_response), payload-identity seed, measured on 20 recorded utterances | recording (10 min) |
| **MARK-1** an interruption tells the truth | `task_22/` | continuous played acks, `audio_end_ms` never 0, \|truncate − heard\| ≤ 150 ms p95, ear takes ch1, backchannel floor | no |
| **ROAM-1** "go explore" | `task_23/` | PatrolPolicy as a runtime behavior + `TOOL_ROAM` + closed intents + the navigator clock; ≥ 1.0 m net displacement ×3 — a Go2-purchase input | no |
| **CURIO-1** the dog talks about what it sees | `task_24/` | map/perception whisperer kinds, ChatterScheduler, time-of-day, farewell; 3–6 remarks per 120 s roam, 0 hallucinated | taste (week 2) |
| **AIR-1** the voice reaches its own mic | `task_25/` | xvf3800 probe, ERLE ≥ 20 dB, false barge-in ≤ 2 %, TV arm, 16 kHz pin, runbook | **yes, ~1.3 h** |
| **DUPLEX-1** "mm-hmm" survives | `task_26/` | local turn controller (LISTEN/THINK/SPEAK/OVERLAP/YIELD), duck ≤ 100 ms, cancel ≤ 450 ms, backchannel survival ≥ 0.9 — after MARK-1 + TURN-1 | live session |
| **PO-1** purchase decision record | `task_27/` | D455 now; Go2 EDU Standard quote now, PO at the week-3 gate on three tells; e-stop decision; don't-buy list | **owner decision** |
| **Wave 3 — hardware** (design in progress: `WAVE3_HW_DESIGN_FABLE.md`; design BEFORE implementation per the owner) | `task_35+` | the owner chose the **Go2 EDU Plus with Mid-360** ($17,055: Orin NX 16 GB onboard, Mid-360 + built-in LiDAR, 720p RGB front camera, Wi-Fi 6/4G) — supersedes PO-1's EDU-Standard/tethered-desktop premise; design study running (hardware facts · codebase seams · prior intent → three proposals → judges → synthesis → critic); cards follow the doc. Batch B (XD-1/FZ-1/HY-1/TRUTH-1/ROAM-2, then GATE-0b) is being re-run by the parcel-4a Fable session after two crashes; 799cb356 integrates | D455/D435i; e-stop remote; the dock's port census when the box arrives |
| **Wave 2** (design: `WAVE2_DESIGN_FABLE.md`, 12:40) — VENUE-1 `task_16`, OT-2 `task_17` (+ memory principal), NM-1 + ASK-1 `task_18`, DOOR-1 `task_19`, DUPLEX-1 `task_26` (+ RT-TURNS-1), XD-1 `task_14`, FZ-1 `task_13`, HY-1 `task_15`, **GATE-0b** `task_30` (new), **CAP-1** `task_31` (new), **TRUTH-1** `task_32` (new), **ROAM-2** `task_33` (new) | — | the Opus TODO judged card by card (adopt DW-1…DW-4 exits + IG-3 narrowed; reject the promotion freeze / Go2 HOLD-until-hosted-CI; defer DW-5); Opus executes, Fable verifies per card | raise the spend limit; B20 |
| **FINISH-1** the week-1 close — every unfinished item, one card | `task_29/` | written 12:05 after the monthly spend limit killed the ROAM-1/CURIO-1/GATE-0 correction passes and the AIR-1 re-check mid-flight: A ROAM-1 (three tethered in-block runs, restated purchase number, ledger deviation, doc), B CURIO-1 (§9.7 second shipped run), C GATE-0 (six minor items incl. the `CODEBASE_INDEX.md` seat), D MARK-1 docs, E AIR-1 `interrupted_at` seam; F integrator. Verdicts so far in `AUDIT_WEEK1_FABLE.md`: TURN-1 / MARK-1 / ENV-1b / GATE-0 ACCEPT; AIR-1, CURIO-1, ROAM-1 corrected, pending close | **raise the spend limit** |
| **ENV-1** the dev box may carry a vendor SDK | `task_28/` | seven capture-stack tests pinned "no vendor SDK installed"; P1-A's sanctioned `pyrealsense2`/`cv2` install broke the premise — re-cut to device-absent refusals + preflight-never-imports, seeded RED. **ACCEPT** (Fable 06:15, `AUDIT_WAVE_P1P2_FABLE.md` §ENV-1): found a real masked-`start()` bug; two verifier corrections landed in `clockmap.py` (the `interrogable` fold killed `--check`'s exit-0 path; the L2 gated on ttyACM); minors → **ENV-1b** (same folder, Opus, week-1 close) | no |

Dispatch: GATE-0, TURN-1, MARK-1, ROAM-1, CURIO-1 in parallel (disjoint
OWNS; `runtime.py`/`lane.py` by marked region, Edit-only); AIR-1 tools now,
session when the owner sits down; DUPLEX-1 after MARK-1 + TURN-1.

## Wave 3 — hardware, software-now rail · cut 2026-08-23 12:5x · Fable (session 31fcc2a0, parcel-6c)

Design: `WAVE3_HW_DESIGN_FABLE.md` (complete, §1–§10). Rule from batch B's
close: every pytest run goes through `~/.cache/parcel-guard/pytest_guard.sh`
(never `-n auto`; 8 workers; 40 GB cgroup) — the four crashes of 08-22/23
were kernel OOM kills, see `BATCHB_DISPATCH_FABLE_4a.md` § parcel-6c.
Roles: **Opus executes, Fable verifies.** Design-first: each card writes
`DESIGN.md` (seams, product-path caller, §e hardware-compat) before code.

| Card | Folder | What | Owner present |
|---|---|---|---|
| **HW-1** py310-clean | `task_35/` | `src/parcel_robot` imports on CPython 3.10 (12 unguarded `datetime.UTC`/`typing.Self` sites), AST guard, per-extra Python ranges, `perception-jetson` extra, jetson lock dry-run, CI 3.10 `base` job | no |
| **HW-3** mid360-band | `task_36/` | `parcel_robot/lidar/`: Livox UDP frame parser + planar band filter → `SimObservation.lidar_ranges` layout; `SourceDevice.MID360`; unilidar L2 path retired; proven on synthesised frames | no |
| **HW-4** array-gateway | `task_37/` | `ArrayAudioGateway` (XVF3800 ch1 16 kHz ↔ lane 24 kHz), `audio.gateway` key default `browser`, real-array desktop capture; through-air TV-on session owner-gated | session (1.3 h, later) |
| **HW-6** stopping-envelope | `task_38/` | `bridge/timing.py` envelope derivation with measured/UNMEASURED inputs, soft gate row hard-red on a measured over-budget sum, box-day input plan | no |
| **HW-8** box-day-runbook | `task_39/` | `docs/BOX_DAY.md` from design §7 (+ JetPack-5 branch), EDU+ Stage-0 run sheet, Unitree support ticket (owner sends), unknowns register with "blocks" | read + sign; send the ticket |
| **HW-2** go2-backend | `task_40/` | `backends/go2.py` observe-only from recorded DDS + HW-3's band; a typed physical scan-evidence source read at `_evaluate_dispatch_input_health`; scan age as the sixth envelope term; `observe --duration` | no |
| **HW-5** physical-profile | `task_41/` | `configs/robot.go2_edu_plus.yaml` declaring `required_capabilities`, `backend`, `lidar` band/extrinsic, `venue`; CAP-1 refuses on the desktop; `venue=` wired at `ingest/__init__.py:117` | no |
| **HW-7** gate-on-aarch64 | `task_42/` | host-capabilities probe + typed SKIP rows; `uname -m` branches in `env-audio.sh`/`install_speech_services.sh`; `install_perception_jetson.sh`; emulated aarch64 gate (≤ 2 runs, container only); nightly job | no |
| **HW-FW** orin-firewall | `task_43/` | `deploy/orin/nftables.conf` + service + README; structural test without nft (+ `nft -c` if present); B-fw runbook row | no |
| **HW-MIC** array-arm-route | `task_44/` | `POST /api/realtime/mic` behind `_authorize_post()` → `set_mic`; `startMic()` branches on gateway kind; real-array 10 s arm — after HW-4 closes | no |
| HW-9…HW-12 box-day rail | — | gated on delivery: first two hours (§7), LIO bake-off, native gateway on the Orin, first armed step | **yes** |

Batch B + GATE-0b (`task_13/14/15/30/32/33`): closed 09:15, six
ACCEPT-WITH-NOTES, commit tier green — staged, awaiting the owner's
"commit and upload". Owner decisions open: TRUTH-1 R3 (accept the miss),
ROAM-2 T1 ceiling + H2 (the coverage objective homes).
