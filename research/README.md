# research/ — hypothesis-driven experiments toward the living-dog prototype

Owner directive (2026-08-23): a prototype that mounts on a Unitree Go2 EDU+
(and later on our own custom quadruped) and behaves like a living dog with an
amicable personality — seamless, interesting, interruptible conversation;
autonomous indoor/outdoor navigation; generalized perception; recursive
(governed) learning about the owner and the world; continuous self-initiated
behavior (breathing, looking, checking things, starting conversations) with a
motion planner that is always emitting a safe intent. The current hosted
envelopes are **≤ $300/month for Realtime conversation** and **≤ $100/month
for deliberative text**; local models run continuously, and the controller
keeps running while the dog learns and REACTS. Provider use must remain in
separate measured ledgers rather than borrowing silently across envelopes.

## Layout — one folder per hypothesis
```
research/YYYYMMDD/<hypothesis-slug>/
  DESIGN.md      Fable — hypothesis (falsifiable), rationale, objective, what
                 would refute it, the measurement, the success criterion,
                 evidence tier, what it does NOT prove, OWNS / must-not-touch
  <code>         Opus — the experiment (harness, scripts, small product seams
                 only where DESIGN.md names them), reproducible from the repo
  RESULTS.md     Opus — what was run, raw numbers, pre-registered criterion
                 met / not met, surprises, cost in tokens/$ if any hosted call
  VERDICT.md     Fable — independent re-run or re-measure of the headline row,
                 product-path check (is it reachable from the runtime, or
                 harness-only?), CONFIRMED / REFUTED / INCONCLUSIVE, follow-up
```
Roles: **Fable designs and verifies; Opus implements.** A result without a
VERDICT.md is a claim, not a finding.

## Rules every experiment follows
- **Pre-register the criterion** in DESIGN.md before any run; RESULTS.md may
  not move it. A missed criterion is a finding (write it down), not a failure.
- **Evidence tiers are labeled, never blended:** `desktop-sim` (MuJoCo /
  headless city), `desktop-real-sensor` (this host's XVF3800 array, a real
  camera if one exists), `replay` (recorded corpora), `hosted-live` (a paid
  API call, with the $ recorded), `on-robot` (none exist yet — no robot
  hardware is on hand as of 2026-08-23; only the mic array).
- **Cost is measured, not assumed:** any hosted call goes through the spend
  ledger or logs its token counts; RESULTS.md carries the $ figure and the
  extrapolation to a 30-day month at the assumed duty cycle.
- **Safety core untouched:** finalize_command, e-stop latch, TTL watchdog,
  speed caps, reactive gate. Experiments propose; they never gain authority.
- **Host discipline:** every pytest through `~/.cache/parcel-guard/pytest_guard.sh`
  (never `-n auto`); never `ci_gate.py --tier`; the owner's live stack on
  `:8765` / `/tmp/parcel_sim.sock` and `parcel_memory.sqlite3` are never
  touched; experiments that need a model server start their own on a port
  they own and stop it when done.
- **Reduced testing policy:** an experiment ships a harness + one
  capability-proof test if it adds a product seam; no combinatorial suites.
- **Package hygiene:** experiment code lives under `research/`; product seams
  it needs land as small, leaf-imported modules in their feature package
  (never `utils/`), behind a flag that defaults OFF, and pass the DEC
  ratchets (`tests/test_dec0_debt_ratchet.py`, `tests/test_decig2_import_ratchet.py`).

## Index

- `20260823/` — first program: see `20260823/README.md`.
- `20260824/` — mountability decisions, Codex cross-review and the proposed
  portable living-dog HLD: see `20260824/README.md`.
- `20260826/` — generalized conversational/navigation research, companion
  prompt v4, simulator-learning architecture, dynamic social-progress and
  pedestrian-stall research, research data plane, and the current motion
  `NO-GO`: see `20260826/README.md`.
- `20260828/` — generalized agency/movement architecture, V1/V2 bounded
  planning evidence, the refuted 2/9 current-RL-environment readiness audit,
  adaptive-locomotion and terrain-planning eval designs, and a 30/60/90-day
  simulator path; physical motion remains `NO-GO`: see `20260828/README.md`.
- `20260828/LIVING_BEHAVIOR_MODEL_REPORT.md` — trainable full-duplex behavior model wave (BM-1/FL-1/HS-1/DS-1, verified literature review, SIM_TRAINING_PLAN); see `20260828/README.md`.
