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
| **P1-A** real eyes | `task_6/` | UVC + RealSense `CameraBackend`s, `EvidenceOrigin.PHYSICAL`, out-of-process GPU detector daemon, `--camera` launcher switch | camera (owner) |
| **P1-B** the map learns | `task_7/` | SigLIP-2 `embed_fn` + depth into ingress, runtime map writer under `shadow`, persist-on-close, AU-C2-1 fix, query-batch union | none (dev scene) |
| **P1-C** which person is you | `task_8/` | person boxes → re-ID gallery → `OwnerTrackV1` via `OwnerFusionStub`; appearance enrollment | camera + enrollment (owner) |
| **P1-D** ask, don't refuse | `task_9/` | Qwen3-VL-2B veto, ADMIT/ASK/REFUSE roster on P0-D's configurable set, k-consistency naming; supersedes 20260821 task_21 | none |
| **P2-A** owner facts | `task_10/` | `owner_facts` + real distiller + `owner_notes`, `remember_fact` with consent, full-ledger replay; refuses un-quarantined synthetic rows | none |
| **P2-B** the dog notices you | `task_11/` | identity as a label per row, hosted-lane affect via `_hosted_affect`, whisperer owner-event bands, voice-tier A/B script | none |
| **P1-E** social zone is a config | `task_12/` | `SafetyEnvelope.person_social_zone_m` from config with a named hard floor; planner inflation from the same number; overlay lands 0.7 m indoor (P0-A blocker, E2-D2's cousin) | none (MOVE-1 standoff arm re-run) |

Owner actions this wave unlocks: plug in a camera (P1-A/P1-C live rows);
`tools/enroll_owner_voice.py` (1 min) and the appearance enrollment (10 s);
`tools/quarantine_synthetic_memory.py --apply` BEFORE P2-A's distiller touches
the real store; one full-size gpt-realtime session for the voice-tier A/B.
