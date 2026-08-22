# Build order — assessment of the Pre-Purchase Queue and the plan that replaces it · Fable · 2026-08-22

**Published page:** https://claude.ai/code/artifact/01deb521-023e-4bf1-90cd-4bf722c3b69c ("Parcel Build Order").

**Owner's goal (verbatim intent):** a prototype intelligent, quirky companion
dog that roams autonomously on command; talks full-duplex, bidirectional, with
endpointing and barge-in; has general perception; is continuously moving or
observing and sometimes just starts talking — a living dog friend.
**Owner's question:** what first — should buying the hardware be first?
**Hardware fact (owner, authoritative):** no robot hardware is on hand. The
only device present is the reSpeaker XVF3800 mic array (USB `2886:001a`,
ALSA card 2, 16 kHz in/out, already PipeWire's default sink and source). No
camera, no Go2, no Orin.

## The answer

**No — buying the dog is not first. Two small purchases are, and the robot
is an evidence-gated decision three weeks out.**

1. **Day 1: order one Intel RealSense D455 (~$300).** It is the only hardware
   on the critical path of work that already exists (`backends/realsense.py`,
   `pyrealsense2 2.58.3` installed; P1-A/P1-C/VENUE-1/OT-2 live rows). Do not
   buy a webcam: an RGB-only venue cannot feed the ingress today (it requires
   depth — P1-A's post-verification cell).
2. **Day 1: the 15-minute owner backlog that has waited since 08-20** —
   the XVF3800 udev rule (`configs/realtime.yaml.example:455-456`) +
   `pip install pyusb` + `doa: true`; `tools/enroll_owner_voice.py` (today
   every hosted command turn runs `verify_disabled`);
   `tools/quarantine_synthetic_memory.py --apply` (the owner-fact distiller
   refuses to run until rows 2883–3138 are quarantined). Then ~20 minutes of
   recording: 20 two-clause utterances and the 52-query corpus (`record.sh`).
3. **Week 1, no hardware: the software the goal names and does not have.**
   The broker has no `roam` tool (eight tools, `tool_broker.py:111-141`) and
   the patrol policy is never constructed in the runtime; the whisperer has
   zero perception or map kinds — the dog cannot be told to explore and
   cannot remark on what it sees. Endpointing is the provider's default
   server VAD with no knob. Every interruption truncates the reply at
   `0 ms` (the barge-in mark-integrity debt), so the model is told the owner
   heard nothing of a reply they heard — context drifts after every
   barge-in. And the gate dies in one second on a clean clone.
4. **Week 1–2, with the mic array: voice through air.** The robot's own
   voice has never reached its own mic from a speaker (the 08-20 sessions
   used headphones); hardware AEC on this array has never been measured; the
   one field failure ever recorded (the TV hijack) is an acoustics/identity
   failure. This is half the goal and the riskiest unknown, and it costs
   ~1.3 owner-hours.
5. **Week 3: the Go2 decision, on evidence.** Request the Go2 EDU Standard
   quote in week 1 (free; 2–4-week lead; firmware ≥ 1.1.13 per ADR 0002).
   Release the PO when three things hold: the owner backlog is done; ROAM-1
   reaches net displacement ≥ 1.0 m in three consecutive sim runs (MOVE-1's
   patrol moved 0.134 m); through-air false barge-in ≤ 2 % with the TV on.
   Then — and not before — start the sidecar gateway (N28) and the hardware
   composition root (CR-1) so the dog arrives to software that can command
   it. The independent hardware e-stop + watchdog `MOTION.md` requires is
   on no card; it is carded below as a decision.

**Don't buy:** Orin NX docks (the tethered RTX 5000 Ada is the compute; an
Orin hosts detector + ASR at most), EDU Plus, the L2 LiDAR (no physical scan
consumer exists), a ZED-F9P, a USB/Bluetooth speaker or headset (defeats the
array's AEC), a webcam.

## Assessment of the Pre-Purchase Queue

Method: five read-only refuters checked every codebase claim the plan makes
(43 claims: **30 confirmed, 9 stale, 4 refuted**); a voice-architecture
study grounded in file:line; three orderings argued from opposite lenses and
scored by two judges (systems-risk ranked roam-first > voice-first >
buy-first; owner-experience ranked voice-first > roam-first > buy-first; the
synthesis below takes the moves both judges converged on).

| Phase | Verdict | What changed |
|---|---|---|
| **Premise: no robot, buy at week 6** | **Right premise, wrong buy-point.** | The plan correctly refused to infer possession (the 08-13 board's "hardware is on hand" sentence was false and the owner has now said so). But a week-6 default idles Phase-4 software against a 2–4-week lead; the synthesis makes the PO an evidence-gated week-3 decision with the quote requested in week 1. |
| **Phase 0 — gate trustworthy (2–3 d)** | **Confirmed, over-estimated.** | All seven mechanisms hold: a clean clone aborts ~1 s into `hard-safety` with an unhandled `ValueError` (both product scenes `<include>` the gitignored Go2 MJCF); `evaluate_hard_safety` propagates instead of returning an error result, so `--json` never emits; `protocol.py:415` breaks exactly CPython 3.11; ruff is range-pinned; Actions never ran; `README:152`/`MOTION:374` cannot parse. Honest effort: ~1 engineer-day total, not 2–3 — and every number in the plan's Phase 0 (118/170, 2,214) is lifted from an unlogged Sol doc. `$HOME/unitree` reconciliation is refuted (that path never existed here). |
| **Phase 1 — ten owner decisions** | **Shrinks to three.** | B18 is mostly decided by tonight's rulings (consent policy, identity-as-label); B19/B5/B6/B7/B8/B23 are purchase-gated or non-blocking. What a desk prototype actually hits: **B14** (one line: does window blur cancel an admitted mission?), **B18 residuals** (retention/export), **B22 axes 1–2** (semantic acceptance from a learned map). |
| **Phase 2 — voice through air (8–13 d)** | **Half stale, the right instinct.** | The array already streams as a UAC device and the owner has spoken through it; `sounddevice` opens the native path when `scripts/env-audio.sh` is sourced (the launchers do) — U5 is refuted as written. Barge-in is implemented on the hosted lane (`lane.py:2274-2306`, 210 ms measured). What is real and never done: the udev/DoA rule, ERLE on *this* array, the mark-integrity defect, the false-interrupt rate through air, a 16 kHz-only array fed 24 kHz playback, and ch0+ch1 downmixed into the ear. Effort ≈ 4–6 d plus owner sessions. |
| **Phase 3 — Orin + rig (4–6 d)** | **Purchase-gated, and the Orin is unnecessary.** | No Orin exists to read; B9/B10/B12/U37/U38 retire if no Orin is bought. The mount sheet's 76 blank lines are ~201 slots that can only be filled at a two-person session after delivery. |
| **Phase 4 — software the robot needs (15–30 d)** | **Partly stale after tonight.** | PC-1 is closed for the MuJoCo venue by P1-B (install + drain + persist, measured) — the residual is VENUE-1. N45's reproducer is real (`semantic_arrival_verification_failed` in 45 s) **and the nightly tier is structurally broken post-R27** (every `live` case errors with `MemoryPathRefused` and leaks a sim → HY-1). N28 is ~30 % landed (N24's contract + fake + 28 tests); the remaining ~70 % is a Python-3.11 sidecar with `unitree_sdk2py` + CycloneDDS behind `bridge/protocol.py`. CR-1 confirmed: without it the input-health join latches a stop on every tick. "Roam on command" is refuted as a capability: no roam tool, no doorway, no out-of-frustum search. |
| **Phase 5 — structural (4–7 d)** | **Confirmed, smaller, with one buried defect.** | Eager barrels confirmed (0.5–1 d, IG-3's scope); `robot_profile` migration is slow not stalled (10 importers, 19 allowlisted sites under a ratchet); `snapshot()` torn read drops a poll, not a 500 (15 min); the realtime surface is ~1,480 lines and not contiguous (2–4 d, after this wave). **Underrated: the product navigator runs on a frozen clock** — `time_s` is never supplied, so tracker dt is the 0.1 literal regardless of `loop_hz` and memory/goal TTLs never advance. One line plus a paired run. |

## The voice architecture (from the design study)

Production is the hosted gpt-realtime lane; the **ear is the browser**
(`index.html:2598-2599`, `getUserMedia` with Chrome's AEC3), not the legacy
PortAudio loop; turn detection is `{"type":"server_vad"}` with no knob
(`protocol.py:128,149`); barge-in exists but truncates at 0 ms because the
browser only acks `played` when a new chunk arrives (`index.html:2574-2578`);
the closed-intent "die stop" scanner runs on the *transcription* event and is
not guaranteed to land before the model speaks; proactive speech never
overlaps anyone (`lane.narrate` skips while playing). The array gives on-chip
AEC, beamforming, DoA and VAD in hardware; its AEC reference is its own DAC
path, which is why the speaker must hang off the array.

Three architectures were costed. **(1)** array AEC + server VAD + local
cancel — small, 2–4 days, the first rung. **(2)** local semantic endpointer
with the hosted model as mouth — medium, buys endpoint speed only. **(3)**
a local duplex state machine (LISTEN / THINK / SPEAK / OVERLAP / YIELD) owning
turn-taking with provisional ducking and backchannel survival — large, and
exactly what `docs/RESEARCH_2026_ROADMAPS.md:29-75` already chose. The plan
takes (1) now and grows it into (3): MARK-1 and TURN-1 this week, AIR-1 with
the owner, DUPLEX-1 after.

## Build order

| Week | Agent-executable (Opus executes, Fable verifies) | Owner, physically | Gate / what it proves |
|---|---|---|---|
| **1** | GATE-0 hermetic gate · TURN-1 endpointing knob · MARK-1 barge-in mark integrity · ROAM-1 "go explore" + the navigator clock · CURIO-1 the dog talks about what it sees · VENUE-1 (carded) | Order the D455 (5 min). Udev + pyusb + doa (5). Enroll voice (3). Quarantine (2). Record 20 utterances + 52 queries (20). Find or buy the JST speaker, plug into the array, level low (10). Request the Go2 EDU Standard quote (30). | The first felt session in sim with roam + curiosity + the hosted lane; `ci_gate --tier commit --json` on a fresh clone. |
| **2** | AIR-1 array commissioning (ERLE, DoA, false interrupts) · DUPLEX-1 turn controller · OT-2, NM-1, DOOR-1, XD-1, HY-1 (carded) · D455 arrives → P1-A live rows, appearance enrollment with a friend as the negative | Through-air session with the tee on: 20 turns, 20 interruptions, 10 min silent while the robot talks (40). TV-on arm (10). Daily 20-min felt session with the scorecard, sim viewer visible vs hidden. | ERLE ≥ 20 dB; false barge-in ≤ 2 %; interrupt p50 ≤ 0.52 s; the body-is-load-bearing tell (viewer arm ≥ 1 point higher on "felt like a creature"). |
| **3** | Desk venue: room map from a handheld walk (P1-B physical store), "where is the couch?" from the dog's own map, greeting from real pixels · far-field/noise arm · PO-1 decision record | Far-field arm at 3 m with 60–65 dB(A) noise (30). PERSONAL_CONVO script (30). **Go2 decision.** | If the week-1 tells hold → release the PO (arrives week 5–7). If interrupt/false-barge-in collapse under noise → order immediately, move acoustics to the dog body. |
| **4–5** | N28 sidecar gateway (3.11 venv, `unitree_sdk2py` + CycloneDDS, SO_PEERCRED) against the `unitree_mujoco` DDS bridge · CR-1 composition root + physical POSE/SCAN sources · e-stop design · V-4 living-dog initiative · V-5 local hotword e-stop · first hosted Actions run | ~1 h/week | `StopMove` ≤ 350 ms p95 over 20 trials on the DDS bridge; ALLOW on ≥ 99 % of 600 ticks; hotword latch ≤ 300 ms cloud-disconnected. |
| **Dog arrives** | Stage 0 observe-only; mount sheet (two people); first armed single-axis step through the commissioning client; leashed follow; camera moves desk → dog | 6–8 h over two weeks | The first commissioned row in the register. |

## Cards (scrum/20260822/task_20 … task_27)

| Card | One line | Owner present |
|---|---|---|
| **task_20 GATE-0** | the gate tells the truth on a clean clone: vendor the 20-file Go2 MJCF @ `ae6a8403` with PROVENANCE, `.gitignore` carve-out, per-stage `except Exception → GateResult('error')` so `--json` emits on red, `ruff==0.16.1` + stamped baseline, `protocol.py:415` `default_factory`, `ci.yml` osmesa, lint `task_9/evidence` | no |
| **task_21 TURN-1** | endpointing is a knob: `turn_detection` (`server_vad`/`semantic_vad`, `eagerness`, `silence_duration_ms`, `interrupt_response`) exposed and validated; measured on the 20 recorded utterances — commit p50 ≤ 0.6 s, 0/20 mid-sentence commits, barge-in 3/3 | recording only |
| **task_22 MARK-1** | barge-in mark integrity: continuous `played` acks from the browser, `audio_end_ms` never 0 after audio played, \|truncate − heard\| ≤ 150 ms p95; the ear takes ch1 (ASR) explicitly | no |
| **task_23 ROAM-1** | "go explore" is a behavior, a tool and a closed intent: `PatrolPolicy` as a runtime behavior, `TOOL_ROAM` (owner-commanded, never proactive), `roam`/`stop roaming` intents; plus the navigator clock (`time_s` supplied); 3 × 120 s runs ≥ 5 m path and **≥ 1.0 m net displacement**, 0 contact in `--static-city` | no |
| **task_24 CURIO-1** | the dog talks about what it sees: `place_learned` / `novel_object` / `ask_about` whisperer kinds fed from the learned map and the ASK outcome, NM-1-admitted names only; 3–6 unprompted utterances per 120 s roam, 0 hallucinated places, 0 while the owner speaks | no |
| **task_25 AIR-1** | array commissioning: udev/DoA, speaker on the array's amp, ERLE ≥ 20 dB at 1 m, 0/20 false interrupts with the owner silent, 0 owner-attributed turns in a 10-min TV arm with DoA sector + enrolled profile, 16 kHz path pinned | **yes, ~1.3 h** |
| **task_26 DUPLEX-1** | the duplex turn controller (architecture 3's first slice): LISTEN/THINK/SPEAK/OVERLAP/YIELD, provisional duck ≤ 100 ms, confirm-cancel ≤ 450 ms, backchannel survival ≥ 0.9, proactive-collision 0, no owed turn unanswered in a 1-h fake-server soak | live session |
| **task_27 PO-1** | the purchase decision record: D455 now; Go2 EDU Standard quote now, PO released at the week-3 gate on the three tells; the independent e-stop/watchdog decision (remote + leash waiver for Stage 0–2 vs a battery-path relay); don't-buy list | **owner decision** |

Already carded and still correct: VENUE-1 (task_16, D455 is day-one;
RGB-only mode is a VENUE-1 decision), OT-2, NM-1, DOOR-1, FZ-1, XD-1, HY-1.
The Sol session's `INTEGRITY_GATES_TODO.md` (IG-0..4) overlaps GATE-0; its
author was not a live session tonight, so GATE-0 executes the narrowed scope
and references it.

## Method notes

* Two proposals disagreed on what to do first and agreed on eight concrete
  moves; the plan is those moves. Where the plan's own author (Opus) was
  most right — refusing to infer hardware possession — the 08-22 audit and
  this auditor were wrong first.
* Effort figures are the refuters' re-estimates against the code, not the
  plan's: Phase 0 is ~1 day, not 2–3; Phase 2's residual is ~5 days, not 13.
* Three measurements decide the robot purchase, and each has an early tell
  that says the ordering was wrong: ROAM-1 missing 1.0 m twice (the nav
  stack, not hardware, is the bottleneck); interrupt/false-barge-in
  collapsing under noise (desk acoustics don't transfer — buy now); the
  sim-viewer A/B (the body is load-bearing for the feeling — buy now).
