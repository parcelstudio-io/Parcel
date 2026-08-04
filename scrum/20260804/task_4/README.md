# Sprint 2026-08-04 · task_4 — attention foundations, shared execution

**Author:** Fable 5 · **Plan of record:**
[../task_3/](../task_3/) (V0–V7) + [../../../docs/ATTENTION_STEERING_DESIGN.md](../../../docs/ATTENTION_STEERING_DESIGN.md).
This sprint executes the startable slice (V0–V3) with the work **rebalanced
so Opus and Sol run in parallel all day**: the foundations refactor is
decomposed into pure decision/data modules (Sol) and repo wiring that
consumes them (Opus).

**Conflict rule (absolute):** Sol writes ONLY new files —
`src/parcel_robot/attention/*`, `src/parcel_robot/core/preemption.py`,
`src/parcel_robot/core/resume.py`, `src/parcel_robot/core/details.py`, and
their tests. Opus owns every existing file. Neither touches the other's set;
integration happens when Opus wires Sol's landed modules.

Working agreements 1–8 inherit from [../task_1/README.md](../task_1/README.md).
Every "not verified" goes to [../../../backlog/UNVERIFIED.md](../../../backlog/UNVERIFIED.md).

## Board

| ID | Card | Owner | Depends on | Maps to |
|---|---|---|---|---|
| S1 | Preemption policy table (pure): channel/source matrix + resolution | Sol | — | V1.1 |
| S2 | `ResumeIntent` + per-channel generation tokens (pure) | Sol | — | V1.4/V1.5 |
| S3 | Typed channel-detail dataclasses with `as_dict()` (pure) | Sol | — | V1.7 |
| S4 | Stimulus bus: typed ADD/REVOKE/COMMIT events + prosody/name fusion (pure) | Sol | — | V2 |
| S5 | ReactionArbiter core: tiers, tracks, Improv scoring, seeded draw, habituation (pure) | Sol | — | V3 |
| O1 | V0 hygiene: pause-semantics convention doc, Go2 spike procedure, B4 sweep prep | Opus | — | V0 |
| O2 | BehaviorChannel registry + replace the 16 stop sites with `preempt()` (consumes S1, S3) | Opus | S1 S3 | V1.1 |
| O3 | Navigator pause seam + `Mission.status` enum + watchdog freeze | Opus | O1 doc | V1.2 |
| O4 | Executive `SUSPENDED` + voice-source policy + adapter verifier table-ization (consumes S2) | Opus | S2 O3 | V1.3/V1.6 |
| — | Review at each S-card landing and at O2/O4 exit; wire-up adjudication | Fable | — | standing |

Start order: S1–S5 and O1 all start **now** (zero mutual dependencies). O3
starts after O1's convention doc (hours, not days). O2 waits only for S1+S3;
O4 for S2+O3. Sol's five cards are sized so the queue never empties while
Opus integrates.

## Hard gate (inherited, non-negotiable)

Before O2 begins: freeze the current follow-bench + embodied-plan ledger
rows. O2/O3/O4 exit only with the full suite green and those rows
**byte-identical** — a pure refactor moves no eval number.

## Contracts

Frozen interfaces for every S-card live in [S-sol-modules.md](S-sol-modules.md).
Opus builds against those signatures from the card text without waiting for
the code; mismatches are a Sol defect, not an integration negotiation.

## Handoffs

### Coordinator (Grok) — 2026-08-04 — full task_4 (Sol+Opus scopes)

Sol/Opus API limits; both scopes landed in one pass under the conflict rule
(Sol = new pure modules; Opus = existing files + docs).

**S1–S5 (Sol):**
- `core/preemption.py` + `tests/test_preemption.py` — mined matrix; search→follow=`PAUSE`; undeclared=`STOP`/`undeclared_pair`; completeness test.
- `core/resume.py` + `tests/test_resume.py` — `ResumeIntent`/`ResumeStore`/`GenerationTokens`; named bump-isolation regression.
- `core/details.py` + `tests/test_details.py` — Navigation/Spatial/Follow/Voice goldens from runtime shapes.
- `attention/stimuli.py` + `tests/test_stimuli.py` — ADD/REVOKE/COMMIT bus, prosody + name fusion.
- `attention/arbiter.py` + `tests/test_reaction_arbiter.py` — tiers/tracks/Improv/seed/habituation; 10k rate band.

**O1:** `docs/PAUSE_SEMANTICS.md`; Go2 SportClient spike procedure appended to
`task_3/A-foundations.md`; B4 list + operator command in `BLOCKED.md`; lazy
v8 shield import in `navigation/pipeline.py`.

**Hard gate:** freeze at `scrum/20260804/task_4/freeze/` (+ `verify.sh`).
Post-integration: **byte-identical**.

**O2:** `BehaviorChannelRegistry` + adapters (`core/channels.py`,
`runtime_channels.py`); `runtime.preempt()` replaces the mined stop sites;
typed details at init/snapshot edges; per-channel `GenerationTokens` alongside
legacy aggregate counter for compatibility.

**O3:** `MissionStatus` enum (incl. `PAUSED`); `DirectiveNavigator.pause/resume`
freezes tick budgets; `SearchOwnerController.pause/resume` freezes wall-clock
budget; tests in `test_navigator_pause.py` / `test_search_budget_freeze.py`.

**O4:** `TASK_STATES` + executive `suspended` (status≠outcome) with
`suspend_task`/`resume_task`; `VOICE_INTERRUPT_POLICY` table; adapter
skill→verifier table + terminal-state constants; ResumeStore wired through
preempt pause path.

**Verified (arbitration must-fixes):** `.parcel/bin/python -m pytest -q`
→ **1614 passed, 1 failed (habitat sidecar smoke: sandbox `PermissionError` on
`os.kill`, unrelated), 6 skipped** when sandboxed; **1612 passed, 6 skipped**
with habitat smoke file ignored; ruff clean on `src/ tests/ evals/`; ledger
freeze **byte-identical**.

**Not verified → UNVERIFIED.md:** Go2 posture-composition spike (hardware);
full live-mission NavigateTo suspend→arrive E2E (U20 blocker — unit pins for
defects 1–4 landed); attention modules not yet wired into the 10 Hz loop (V4);
`busy_reason` from registry deferred; `_behavior_generation` aggregate still
bumped alongside per-channel tokens (nav/follow/search in-flight checks now
read channel tokens).

---

## Arbitration (coordinator standing in for Fable)

Fable/Sol/Opus APIs rate-limited. Coordinator applies BINDING must-fixes below.

### Binding rulings (authoritative)

#### Sol must-fix
1. **S5 habituation decay** — Fix double-counting: decay from last-decay/post-fire baseline so τ is honored (`arbiter.py`). Add test that τ≈5 over 5s lands near e^{-1}, not compounded every tick.
2. **S5 track holders** — Consult `_track_holders` in `tick` hard filters so a held track blocks other reactions until `notify_outcome` clears it. Test two specs sharing `head_gaze`.
3. **S5 commitment bonus** — Pin soft commitment after dwell (`min_dwell_s=0`, bonus>1 prevents A↔B flicker vs bonus=1). Fix scoring if needed.
4. **S5 reset-on-disengagement** — Expose on frozen API: `notify_outcome(success=False)` resets signed weight for that key (keeps signature frozen). Documented in S-sol-modules.
5. **S2 peek** — `peek` must not return expired intents; drops/returns None when `now_s` shows expired.
6. **S1** — DEFER full 90-pair golden matrix this pass; completeness via `missing_pairs()`; expand expectations for activities↔nav/pose edges only if cheap.

#### Opus must-fix (blockers first)
1. **Executive**: `tick()` must treat `suspended` like running for skip purposes — do NOT re-dispatch. Pin: suspend → tick → still suspended, no new `DispatchRequest`.
2. **pause_navigation**: Must PAUSE not STOP. Do NOT use `preempt("voice")` for nav pause. Dedicated pause path calls `navigator.pause()` + records `ResumeIntent` without PreemptionTable STOP — matches PAUSE_SEMANTICS.md.
3. **_step_navigation**: `stop=True` with `mission_paused` / status paused must NOT clear `_navigation_directive`. Only destructive terminals clear.
4. **Voice suspend of NavigateTo**: release leases AND record `ResumeIntent`; resume-as-fresh-dispatch must work. Reconcile: suspend ≠ STOP without intent.
5. **Verifier table**: actually use `_verifier_table().get(...)` instead of discarding.
6. **GenerationTokens**: route in-flight cancellation checks through per-channel tokens (nav/follow/search wired).
7. **busy_reason from registry**: DEFER to register if large; else quick win.
8. Bump **U20** to blocker severity describing proven unit defects; strengthen unit tests for 1–4.

#### Defer
- Nested `FollowPredictionDetail.replace`, dead `kept`, docs/README index, SHA256SUMS cwd nit, spatial.stop on completion, U18/U19 unchanged.

### Review board (prior)

| Finding | Ruling | Owner |
|---|---|---|
| S5 signed decay double-counts τ | **BINDING** fix | Sol |
| S5 `_track_holders` unused in tick | **BINDING** fix | Sol |
| S5 commitment bonus untested | **BINDING** pin + fix if needed | Sol |
| S5 reset-on-disengagement API | **BINDING** — `notify_outcome(False)` clears | Sol |
| S2 peek returns expired | **BINDING** peek returns None if expired | Sol |
| S1 full 90-pair expectations | **DEFER** — completeness via `missing_pairs()` | — |
| Executive `suspended` redispatches | **BINDING** fix | Opus |
| `pause_navigation` via voice→STOP | **BINDING** dedicated pause path (not voice preempt) | Opus |
| `_step_navigation` clears paused mission | **BINDING** fix | Opus |
| Voice suspend without ResumeIntent | **BINDING** fix | Opus |
| Verifier table discarded | **BINDING** use the table | Opus |
| GenerationTokens not authoritative | **BINDING** wire in-flight checks | Opus |
| `busy_reason` not from registry | **DEFER** → register if not cheap | Opus |
| U20 understated | **BINDING** elevate to blocker + strengthen tests | Opus |
| Nested replace / dead kept / docs index / SHA cwd | **DEFER** | — |

### Must-fix order
1. Opus O3/O4 pause/suspend blockers (mission survival)
2. Sol S5 decay + tracks + commitment
3. Opus verifier + GenerationTokens
4. S2 peek; U20 rewrite

### DoD
Freeze + safety still good. Pause/suspend and S5 habituation must-fixes landed under this arbitration.
