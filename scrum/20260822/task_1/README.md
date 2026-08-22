# Task 1 — P0-A: prototype profile & launcher

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(read its standing rules first — concurrent writers, Edit-only, git read-only).

## Why

Every relaxation the prototype needs is today a hash-locked edit to
`configs/robot.yaml` (SHA-locked by `evals/companion/embodied_plan_v1/manifest.json`,
`scripts/ci_gate.py:204-307`) or an environment incantation. The prototype needs
**one profile** that carries the relaxations without moving the production
file's hash, and **one launcher flag** that selects it.

## Deliverables

1. **`configs/robot.prototype.yaml`** — an *overlay* applied on top of
   `configs/robot.yaml` (deep-merge, overlay wins). Contents, all of which are
   keys that already exist today (grep before you write; do not invent keys
   other cards own):
   * `safety.person_stop_m: 0.7` (indoor standoff; the derived follow stand-off
     must re-derive from it — check `configs/robot.yaml:54-57` and
     `navigation/follow.py:45-60` derive, not copy).
   * voice identity: keep the gate *off* as a command gate until enrolled
     (`voice_identity.enabled: false` or the equivalent key the runtime reads at
     `runtime.py:6633-6660`), with a comment pointing at
     `tools/enroll_owner_voice.py`.
   * camera ingress **on** (see deliverable 3).
   * affect minimum confidence `0.5` (`configs/robot.yaml:218-221`).
   * anything else that is pure config and listed in audit §9 — but NOT
     abstention/navigation keys (P0-D owns `configs/navigation/*`) and NOT
     realtime keys (those live in deliverable 2).
2. **`configs/realtime.prototype.yaml.example`** — a copy of
   `configs/realtime.yaml.example` with: `idle_close_after_s` raised so the lane
   stays live while the owner is present (use the largest value the validator
   accepts today; P0-B may later add `0 = never`), narration interval loosened,
   `model: gpt-realtime-2.1` (full-size; the board's voice-tier experiment).
   Keep every comment that explains a key.
3. **One camera flag.** Today `perception.camera_ingress` (`runtime.py:1278-1358`)
   and the legacy `camera_ingress.enabled` / `PARCEL_CAMERA_INGRESS`
   (`runtime.py:9303-9340`) refuse each other (`runtime.py:1518-1523`). Collapse
   to one key that turns the stream on; keep the legacy env var as an alias that
   maps to the same key. The prototype overlay turns it on. Production default
   (flag absent) must behave exactly as today — prove with a flag-off test.
4. **Overlay loader** in `src/parcel_robot/config.py`: `PARCEL_PROFILE=prototype`
   or `--profile prototype` resolves `configs/robot.<profile>.yaml` and
   deep-merges. Unknown-key refusal stays (it is cheap and catches typos) —
   but the overlay is validated *after* the merge, against the same schema.
5. **`scripts/launch_stack.sh --prototype`**: selects the overlay, prefers
   `configs/realtime.prototype.yaml` if present (falls back to
   `configs/realtime.yaml` with a printed note), and passes the profile through
   to `parcel_robot.web_panel` / sim. Do not change the default (no-flag)
   behaviour.
6. **Release parity:** if `runtime_assets/MANIFEST.json` mirrors `configs/`,
   run `tools/sync_runtime_assets.py` and include the regenerated mirror in your
   diff. Do not hand-edit `MANIFEST.json`.
7. **Tests** (`tests/test_prototype_profile.py`, new): overlay merges and
   validates; flag-off byte-identity of the resolved config when no profile is
   given; the single camera flag on/off; the legacy env alias; launcher flag
   parse (shellcheck-free bash test via `bash -n` + a dry-run mode if the
   launcher has one — if not, a unit test of the profile resolution only).

## OWNS

`configs/robot.prototype.yaml` (new), `configs/realtime.prototype.yaml.example`
(new), `scripts/launch_stack.sh`, `src/parcel_robot/config.py`,
`src/parcel_robot/runtime.py` **only** lines ~1278–1358, ~1518–1523,
~9303–9340 (the camera-flag regions) — P0-B and P0-D edit other regions of the
same file concurrently: Edit-only, re-read first — `src/parcel_robot/runtime_assets/**`
(via the sync tool only), `tests/test_prototype_profile.py`, this folder.

## MUST NOT TOUCH

`docs/**`, `backlog/**`, `README.md`, `scrum/20260821/**`, `configs/robot.yaml`
(hash-locked; the whole point is not to move it), `configs/navigation/**`
(P0-D), `src/parcel_robot/realtime/**` (P0-B), `perception_abstention.py`,
`camera_channel/ingress.py` (P0-D), `scripts/ci_gate.py` (P0-E), any safety-core
module, `evals/**`.

## Gates

* `.parcel/bin/python -m pytest -q tests/test_prototype_profile.py tests/test_config*.py tests/test_runtime.py -x` green.
* `.parcel/bin/ruff check src/parcel_robot/config.py src/parcel_robot/runtime.py tests/test_prototype_profile.py` no new violations.
* `bash -n scripts/launch_stack.sh`.
* Flag-off proof: with no profile, the resolved config dict is byte-identical
  (JSON dump) to before your change — record the sha256 before/after.

## Status doc

`P0A_STATUS.md` in this folder, per the board's register. Include the exact
overlay contents and the resolved values for `person_stop_m`, the derived
follow stand-off, the camera flag, and the affect threshold under
`--prototype`.
