# AUDIT — Wave 2 · Fable · 2026-08-22

**Board:** `TASK_BOARD.md` (Wave 2 row). **Design:** `WAVE2_DESIGN_FABLE.md`.
**Baseline:** `21ea2fb` (the week-1 landing). **Batch A** (dispatched 12:55
EDT): VENUE-1 (task_16), OT-2 (task_17), NM-1 + ASK-1 (task_18), DOOR-1
(task_19), DUPLEX-1 (task_26), CAP-1 (task_31). **Batch B** after A's close:
XD-1 (task_14), FZ-1 (task_13), HY-1 (task_15), GATE-0b (task_30), TRUTH-1
(task_32), ROAM-2 (task_33). **Method per card:** unchanged from week 1
(`AUDIT_WEEK1_FABLE.md` §Method) — the executor's status doc + my diff read,
then a read-only three-lens workflow with a skeptic per finding; rows reported
as reproduced-through-the-product-path, harness-only, or owner-gated.

## Verdict table

| Card | Verdict | Confirmed findings | Corrections | Owner-gated rows |
|---|---|---|---|---|
| CAP-1 | **ACCEPT** (corrected + last hop, re-verified: 24 CAP-1 / 497 across thirteen files, ruff at the pinned baseline) | 9 (the AST derivation was silently blind to a non-inline `ToolCall` — a NEW tool routed to an unadmitted mode shipped green; 3 doc-wrong; 2 refuted) | `broker_scan()` now returns typed `unreadable` sites and G1 asserts `not unreadable` **plus** a coverage pin (`BROKER_TOOLS ⊆ doors`, `MOTION_TOOLS ⊆ doors`), proved with a COUNTERFACTUAL seed table (S10 invisible pre-correction / RED after; S6 caught independently); G2 widened to bare `store` receivers; BLE001/cost/deviation-2 restated | — |
| VENUE-1 | **ACCEPT** (corrected, re-verified: 70 passed with CAP-1's suite, ruff at baseline) — **both claimed defects reproduced on the product path**; the reconcile is clean and now guards its raise window | 6 (the live detector state never reached `/api/state`; a raise window left a closed map installed; `perception.detector` silently ignored on the simulator; the row-census half of the mixing guard pinned by nothing; a cell that reddens when the D455 arrives; 6 refuted) | live merge into seam 2 (pinned against a real daemon stopping); raise-window guard; validation moved above C-1's early return; row-census cell + seed S8; `skipif`; `_venue1_state` identity-checked; **both routed handoffs taken — CAP-1's binding asserted per start, OT-2's `latest_rgb` supplied from the backend's buffers — with CAP-1's pinning test updated in the same change** | D455 live, USB webcam, a real desk clip |
| OT-2 | **ACCEPT** (corrected, re-verified: 120 passed, ruff clean, `max < 1.0` restored, degrade carries `previous.visible`) — rows now 10/10 | 8 (1 safety: the degrade deleted the owner's person clearance **and the card's own R7 test asserted `visible is False`, pinning the defect**; the raw-cosine gate still live in follow/search; R6's miss had a false cause and the target passes; the "strictly fewer" direction was backwards — measured 1,314 newly refused / 66 newly granted / 6,270 unchanged; 4 refuted) | both branches fixed + a 0.7 m degraded-owner `stopped` pin; enrollment frames excluded, pre-registered assertion restored verbatim; direction pinned as a measurement; locks fixed not declared | identity campaign; voice principal |
| NM-1 + ASK-1 | **ACCEPT** (corrected, re-verified: 54 passed, ruff back to the 7 baseline, evidence scripts clean) — **the negative result survived every attack** and the headline miss STANDS (J3 still 1 false promotion; no floor reaches 0) | 4 (major: the ASK confirmation token digested `signals` so it churned every camera frame — and the card's own tests passed against a STUB door, the CURIO-1 §9.1 class again; major: the evidence scripts would have reddened the commit gate, and §8 measured the wrong scope; 2 minor; 8 refuted) | token bound to `(query, candidate, place_id)` + evidence digest **and made single-use**; greps → behavioural assertions; LRU eviction, judge retry, floor env pinned; §3.1 restated as the paired 16/21 with its narrowing | operating point needs real camera frames |
| DOOR-1 | **ACCEPT** (corrected, re-verified: follow-bench 26 passed, 128 across planner/prototype/safety-wiring, ruff 7) | 8 (major: `search_owner.py` coupled the SHIPPED ring, putting frozen follow-bench evidence at risk; `grid_clearance_v2` 0.35 → 0.42 same class; the published boundary was 1.05 not the measured 1.0000; 4 refuted) | **scoped, never re-pinned**: `planner_coupling_ring_m = min(commissioned, per-profile legacy-equivalent)` — shipped stays 0.42, prototype gets 0.45; all 9 grid profiles pinned at exact IEEE equality; the deferral is now a value the code carries (`planner_coupling_is_deferred`, `uncapped_planner_inflation_m`); boundary numbers + assertion corrected | every physical clearance |
| DUPLEX-1 | **ACCEPT** (corrected, re-verified: 157 passed across its own + MARK-1's + TURN-1's suites) — D-2's 740 ms miss stands with the bar unmoved | 7 (**major: `duckGainFor` admitted null/[]/""/false as gain 0 — a silent mute — behind an UNFAILABLE test**; major: a pump gap split the two deciders and left a playing reply permanently ducked; `duck` feature-detected by name would have called a dB-scale sink; H-7 untested; OG commands not executable; 5 refuted) | type-check with no coercion + `MIN_DUCK_GAIN = 0.05` as a single source through controller → gateway → panel, so **nothing in the pipeline can reach zero**; the Python port re-synced line for line (it was STRICTER than the product, which is why no row caught it); `speech_ended_at <= hold.deadline` + a counted `turn_decider_disagreements`; `accepts_gain_duck` capability flag; H-7 arm binding a real `SessionAudioCapture`; 20/20 seeds with a committed transcript | through-air rows (AIR-1 session) |

## Gate risk to clear before the batch commit

**CLEARED (13:5x).** DOOR-1's correction scoped the coupling instead of
re-pinning: the shipped profile's planner keeps 0.42 (the commissioned ring is
capped at the per-profile legacy-equivalent), the prototype gets its 0.45, and
all nine grid model profiles are pinned at exact IEEE equality. I re-ran the
row that was at risk: `tests/test_follow_bench_v1.py` 26 passed. Nothing was
re-run, re-frozen or re-pinned. Original entry, for the record:

**DOOR-1 site 2 (`search_owner.py`) couples the shipped 0.65 m ring.** The
follow-bench is a hard-safety gate row and `evals/companion_nav/runner.py:213`
constructs `SearchOwnerController`, so the coupling can move frozen evidence.
The correction scopes it to commissioned-tighter-only (an un-commissioned
shipped runtime keeps 0.42). **Nothing is re-pinned or re-frozen** — the full
gate at the batch close is the authority, and if a frozen row moves I stop and
surface it to the owner rather than re-freezing.

## A disagreement, recorded rather than resolved

I passed NM-1 a verifier's note that the J5<J6 anti-correlation *reverses sign*
on the 64-px crop the map actually feeds the judge. NM-1 re-ran the full pair
at both sizes and **could not reproduce a sign reversal in any statistic**: the
paired result is identical at 16/21 at both sizes, and medians, means and
accept rates all keep their sign; what collapses is the *unpaired* margin
(0.029 → 0.004). Raw per-crop rows are committed for both sizes
(`task_18/evidence/judge_rows.json`, `judge_thumbnail64.json`) so one
comparison settles it. I accept NM-1's measurement over the note: it measured
directly and published the rows. The lesson runs both ways — a verifier's note
is a claim too, and it owes the same evidence it demands.

## Batch-A gate (18:47Z) — 9/10, and what the three reds were

**hard-safety PASS** — the question DOOR-1 raised is answered: the frozen nav
baseline (`nav-instruct-v1-baseline-v4`), the mutation panel, all **7
follow-bench rows** and walk_with_me are intact. Also green: ruff 7/baseline
7/new 0 · unitree-assets · release-parity 91 · assertion-evals · tier-coverage
**9,361 = 9,280 + 81** · model-off · release-parity-integrity ·
owner-store-isolation. `default-suite`: **9,256 passed, 3 failed** in 6:49.

The three, diagnosed rather than re-pinned:
1. `test_arrival_semantics.py::test_the_tool_schema_offers_relation_and_nothing_else_about_arrival`
   — **deterministic, and a design decision rather than a defect.** The test
   deliberately pins `navigate_to`'s schema to `{place, relation}` ("a
   parameter the model cannot send is a parameter it cannot get wrong"), and
   ASK-1 added `confirm`. **Ruling: keep the parameter, move the pin
   deliberately** — the confirm value is an opaque single-use token checked
   against a freshly recompiled revision, so an invented or stale value fails
   identically and the model cannot get it wrong in the sense the pin
   protects; the pin's real target (face / standoff / stop) stays asserted
   absent, and adding a `face` property must still redden it.
2. `test_capture_ingest.py::test_no_adapter_import_ever_installs_or_imports_a_vendor_module`
   and 3. `test_venue1_physical_venue.py::test_the_map_installer_still_imports_mujoco_and_that_is_a_handoff`
   — both **order-dependent**: each passes alone and in its own file, and
   fails only in the sweep, because an earlier test has already imported or
   hidden the module they assert about. Carded as **GREEN-1** (`task_34`):
   re-cut each to measure in a clean subprocess (the house pattern the capture
   stack already uses), never by skipping, weakening, xfail or reordering, and
   with the reproducing sweep command recorded.

**GREEN-1 corrected my diagnosis, with evidence.** Only #2 was a `sys.modules`
artefact. The VENUE-1 cell was failing on an **environment** leak:
`runtime.py:11491` sets `MUJOCO_GL=egl` process-wide when the *simulated*
ingress attaches, so a single earlier file poisons it — and, more to the point,
**that cell could never have passed under `ci_gate.py` in any order, even
alone**, because the gate's own `_base_env` does
`env.setdefault("MUJOCO_GL", "egl")` for every pytest subprocess. The clean
subprocess (with the env scrubbed) fixes the order-dependence and the
gate-dependence together. A tree-wide sweep for the same pattern found exactly
one other occurrence, which already guards itself. My suggested reproducing
commands did not reproduce, because pytest honours the file order given and I
listed the target first — the real minimal reproducer is
`pytest tests/test_capture_ingest.py tests/test_venue1_physical_venue.py`,
since the venue file calls `connected_devices()` at module scope for a
`skipif`, importing `pyrealsense2` during collection. Guard #1 came out
strictly stronger (it can now check `pyrealsense2` after the call too, which
it could not do in-process).

## Housekeeping for the owner

Five leaked `parcel_robot.sim` processes from an earlier test sweep are alive
on pytest scratch sockets (`/tmp/pytest-of-jaewoo-jang/pytest-3848/…`), pids
2447765 / 2447909 / 2448046 / 2448183 / 2448324. They are **not** on the
owner's `/tmp/parcel_sim.sock` or `:8765`. Left running per the standing rule
(never kill what you did not start); they are exactly the defect **HY-1**
(`task_15`, batch B) exists to fix, and are recorded here as its evidence.
Reap them deliberately when convenient.

* **CAP-1 → P1-B (task_7), NEW:** `test_the_runtime_region_wires_all_three_seams`
  pins "install precedes attach" via a LITERAL two-line source string whose
  suffix also forbids any card from placing anything between the attach and the
  first thread start — it broke on CAP-1's region insertion and constrained the
  remedy for VENUE-1's handoff. The property is real; the suffix
  over-specifies it. Comparing the two `runtime_src.index(...)` positions
  without the `\n            self._thread` suffix protects the same thing and
  keeps the composition root extensible. Carded for batch B.

## Cross-card findings surfaced so far (by whom → owner)

* **RESOLVED — VENUE-1 took it:** `_venue1_bind_semantic_source()` asserts the
  configured policy on every started runtime, and CAP-1's pinning test was
  updated in the same change (renamed; pins the row True after `start()`;
  keeps the guard live by rebinding under a running runtime). One hop handed
  back to CAP-1 and dispatched: `check_required_capabilities` runs one line
  BEFORE the attach, so a DECLARING profile still refuses on a venue that is
  about to bind the source. Inert today (nothing declares).
* **CAP-1 → P1-B (task_7) / VENUE-1:** the semantic-source binding is
  one-directional — a process that already bound `learned_map` starts a
  runtime whose YAML says `oracle` and keeps the learned map, because the
  installer returns before `use_semantic_source`. Same class as the
  POI-oracle startup defect, other direction. Reproduced on the product path
  (`task_31/evidence/finding_one_directional_binding.txt`). The one-line fix
  is P1-B's region; VENUE-1 is the nearest live owner — assigned to its
  correction pass.
* **CAP-1 → VENUE-1 / DUPLEX-1:** six new ruff fingerprints in
  `tests/test_venue1_physical_venue.py` and `tests/test_duplex1_rows.py`
  (incl. an unused `noqa`) mid-work; the ratchet is exactly 7 — their
  verifiers check the clean-up.
* **CAP-1 (correction pass) → the launcher, NEW:** `web_panel.build_runtime:640`
  reads `store.section("planner_model")`, a key absent from both the SHA-locked
  base config and `OVERLAY_INTRODUCIBLE_KEYS` (confirmed by me). Consequence:
  the planner LLM can never be enabled, and a profile that tries makes the whole
  config load refuse. ROAM-1 finding 6 a second time, in the product launcher —
  found only because G2 was widened. Pinned as exactly `{"planner_model"}` so a
  second instance reddens and so does the fix. Owner: whoever owns
  `web_panel.py` / the config base — carded for batch B (TRUTH-1 or CAP-1b).
* **CAP-1 → CODEBASE_INDEX.md:** stale with the new files; regenerated by the
  integrator at the batch close (it is a function of the commit).
* **RESOLVED — VENUE-1 took it:** `ingress.latest_rgb` is now supplied from
  the physical backend's own buffers, with the synchrony argument stated as a
  caller property and "carry pixels with the frame" left as handoff 10.
* **OT-2 → VENUE-1 (original):** pixels do not reach the owner tracker on a live camera
  (`CameraDetectionFrame` carries no image; the runtime duck-types
  `latest_rgb()`; the tracker degrades to `no_pixels` and the owner reads as
  a stranger). The one-line patch (OT2_STATUS §9.1) is in P1-B's `ingress.py`
  — VENUE-1's correction pass takes it.
* **RESOLVED (transient):** the unowned red
  `test_runtime.py::test_runtime_executes_bounded_owner_relative_steps_and_manual_preempts`
  now passes alone and in its file — it was mid-edit state during concurrent
  batch-A work, not a regression.
* **OT-2 → NM-1/ASK-1:** `test_arrival_semantics.py::test_the_tool_schema_offers_relation_and_nothing_else_about_arrival`
  is red from ASK-1's `CONFIRM_KEY` on `navigate_to` — its verifier checks.
* **OT-2 → DUPLEX-1:** `test_prototype_profile.py::test_realtime_prototype_example_validates_and_carries_its_departures`
  is red from DUPLEX-1's `turn_detection` key in the prototype example — its
  verifier checks (P0-A's departure pin must be updated with the key, not
  the key dropped).
