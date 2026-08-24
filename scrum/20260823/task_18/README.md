# DEC-FS-1 — feature packages for the flat top level (Tier M-B, mechanical) · Fable 2026-08-23

Program: `scrum/20260823/DECOMP_PROGRAM_FABLE.md` §2 M6 (package-by-feature).
Owner's ask, verbatim: "Create subfolders and structure files logically so the
code is logically organized and easy to follow." Prereq: DEC-IG-2 landed
(barrels import-free, import ratchet live). Runs ALONE (it rewrites import
lines tree-wide). After it: DEC-R1 and DEC-N1 run in parallel.

## What moves (26 modules) and what stays (27) — decided, not optional

`src/parcel_robot/` today has 53 flat modules beside 40 packages. Rule:
**entry points and seams stay flat; feature implementations move into a
feature package.** Package names were chosen so a reader finds things
where they would look. Three names collide with an existing flat module
(`memory.py`, `perception.py`, `motion.py`) — the collision is resolved by
moving that module INTO the new package in the same step (a package
shadows a same-named module, so the two cannot coexist even briefly:
do each of those three as one atomic move-and-rewrite).

| from (flat) | to | note |
|---|---|---|
| `audio_io.py` | `audio/devices.py` | 70 importers — the biggest rewrite |
| `audio_arming.py` | `audio/arming.py` | |
| `voice_audio.py` | `audio/voice_loop.py` | MicrophoneVoiceLoop / SpeakerSink / AEC |
| `endpointing.py` | `audio/endpointing.py` | |
| `prosody.py` | `audio/prosody.py` | |
| `voice_pipeline.py` | `voice/pipeline.py` | `voice/` exists |
| `agent.py` | `voice/agent.py` | VoiceAgent; DEC-0 target, 1 pin (§3) |
| `dynamic_prompting.py` | `prompting/dynamic.py` | `prompting/` exists |
| `memory.py` | `memory/conversation.py` | **collision** — atomic |
| `memory_path.py` | `memory/path.py` | pinned by `tests/test_owner_store_isolation.py` (path string) |
| `tiered_memory.py` | `memory/tiered.py` | |
| `conversation_store.py` | `memory/store.py` | 4 string patch targets in tests |
| `perception.py` | `perception/contract.py` | **collision** — atomic |
| `perception_abstention.py` | `perception/abstention.py` | oversized-baseline path; 2 string targets |
| `perception_contention.py` | `perception/contention.py` | |
| `perception_providers.py` | `perception/providers.py` | 3 string targets |
| `scene_semantics.py` | `perception/scene_semantics.py` | |
| `city_semantics.py` | `perception/city_semantics.py` | literal-drift table path |
| `sim_control.py` | `simulation/control.py` | `sim.py` itself STAYS (entry point + owner's live `-m parcel_robot.sim`) |
| `sim_ipc.py` | `simulation/ipc.py` | |
| `mujoco_lidar.py` | `simulation/mujoco_lidar.py` | literal-drift table path |
| `headless_city.py` | `simulation/headless_city.py` | 5 path pins + `admission._PRODUCT_CONFIG_SOURCES` |
| `dynamic_city.py` | `simulation/dynamic_city.py` | |
| `motion.py` | `motion/router.py` | **collision** — atomic |
| `gait.py` | `motion/gait.py` | |
| `expression.py` | `motion/expression.py` | |

Stays flat, with the reason a reader will see in `CODEBASE_INDEX.md`:
entry points/apps (`runtime.py`, `runtime_channels.py`, `web_panel.py`,
`sim.py`, `cli.py`, `control_panel.py`, `unitree_control.py`,
`safety_control_smoke.py`, `ros_node.py`); seams and contracts (`config.py`,
`admission.py`, `paths.py`, `models.py`, `authority.py`, `robot_profile.py`,
`geometry.py`, `safety.py`, `pose.py`, `evidence_origin.py`, `revision.py`,
`lethal_veto.py`, `modules.py`); awaiting their own split card
(`providers.py` → a `providers/` package by class, `reasoner_gpu.py` with
it, `observability.py`, `eval_panel.py`). Do not move these.

## Build
1. For each row: filesystem `mv` (git is read-only for you; the integrator's
   commit will record the rename by similarity), then rewrite EVERY importer
   across `src/ tests/ scripts/ tools/ examples/ evals/` — all three forms:
   `from parcel_robot.x import y`, `import parcel_robot.x`, and
   `from parcel_robot import x` (the last now yields a *package* for
   memory/perception/motion — grep attribute uses and re-point them).
   Ordering with `ruff check --select I --fix`; no `ruff format` on files
   failing it at HEAD.
2. New packages get an `__init__.py` with a docstring ONLY (DEC-IG-2's
   import ratchet forbids re-export imports in barrels). No compatibility
   shim modules at the old paths: there are no external consumers, and a
   shim is a barrel in disguise. Exception: none expected — if you find a
   string reference you cannot rewrite (a config value, a subprocess
   `-m` target, a deploy file), STOP that row, leave the module flat, and
   record why.
3. Port every path-keyed pin in the same card (all mechanical string
   updates): `tests/test_dec0_debt_ratchet.py` oversized-module baseline
   paths (a rename is not new debt — re-key `agent.py`, `memory.py`,
   `perception_abstention.py`, `headless_city.py` to their new paths; the
   count stays 45); `tests/test_authority_no_literal_drift.py` table
   entries for `city_semantics.py`, `mujoco_lidar.py`, `headless_city.py`;
   `tests/test_owner_store_isolation.py` (`memory_path.py`);
   `tests/test_e2_safety_wiring.py` and `tests/test_ot2_identity.py`
   (`headless_city.py`); `admission._PRODUCT_CONFIG_SOURCES` (check
   whether it matches by basename or relative path; extend to whatever
   `test_cap1_admission.py` needs); the 15 string patch targets
   (`"parcel_robot.<old>…"` in tests — re-point each). Docs under `docs/`
   that cite a moved path: update the path (10 lines; `scrum/` history is
   NOT touched). `deploy/orin/nftables.conf` cites `web_panel.py:751` —
   unaffected (web_panel stays).
4. Extend `tests/test_decig2_import_ratchet.py`'s package roster with the
   new packages; the forbidden-edge rules keep their meaning (moved
   modules keep their role: e.g. `perception/*` and `memory/*` never
   import `runtime`, `web_panel`).
5. Regenerate `CODEBASE_INDEX.md` twice (`.parcel/bin/python
   tools/codebase_index.py`, self-referential) so the layout is visible.

## OWNS
The 26 modules (old and new paths), the new packages' `__init__.py`, import
lines tree-wide, the pins named in (3), the docs path lines, the import
ratchet's roster, `CODEBASE_INDEX.md`, this folder (`DECFS1_STATUS.md`).

## MUST NOT TOUCH
Any code line that is not an import or a path string; behavior; frozen
baselines/eval fixtures; `runtime.py` beyond its import lines; git; the
owner's live stack (`:8765`, `/tmp/parcel_sim.sock`) and memory store.

## Prove (guard wrapper `--label decfs1`; never `-n auto`; never `--tier`)
Targeted first: `tests/test_cap1_admission.py`, `test_owner_store_isolation.py`,
`test_authority_no_literal_drift.py`, `test_e2_safety_wiring.py`,
`test_ot2_identity.py`, `test_dec0_debt_ratchet.py`,
`test_decig2_import_ratchet.py`, `test_import_order_no_cycle.py`, plus one
suite per moved module (`-k` on its name). Then one full
`-m 'not slow' -n 8 --dist loadfile -p no:cacheprovider`. Known flakes:
`test_yield_policy` (order-dependent; loadfile unaffected),
`test_dynamic_costs…performance` (R26 perf pin; warm re-run). A fresh
subprocess `python -m parcel_robot.sim --help` and `-m parcel_robot.web_panel
--help` must still resolve (the owner's live processes use those names).
Ruff clean, zero `noqa`.

## STATUS register (M9)
Modules moved (26 expected; fewer = name each and why); flat top-level
module count before/after (53 → 27 expected); importer rewrites by root
dir; pins ported (file:line, old→new); ratchet numbers before/after (must be
unchanged or lower — a move is not debt); suites run with counts.
