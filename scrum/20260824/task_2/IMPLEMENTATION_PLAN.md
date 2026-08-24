# M1 implementation plan (short) · Fable · 2026-08-24 · owner-approved

Owner decisions: **Follow is IN M1** (option (a) — its blockers accepted as
schedule/BOM risk); research work and implementation START now. Governing
record: `CLAUDE_RESPONSE.md` (+ two addenda) in this folder. WIP limit: one
integration lane + one decision study at a time. Opus implements; Fable
designs/verifies; humans own residual risk (owner: Jae).

## Lane A — integration (one card active at a time)
| # | card | scope (short) | done when |
|---|---|---|---|
| A1 | **M1-0 GATEWAY** (now) | The native sole-writer gateway + co-located governor as a separate process against `bridge/protocol.py` V1: credential/epoch/lease, TTL ≤ 350 ms watchdog, clamp/veto, exact-zero on kill/stale/loss, boot- and restart-disarmed, audit ring. Bench only: `bridge/fake_sport.py` + seeded fault inventory; NO vendor SDK, NO hardware, NO runtime.py changes. Python (3.10-compatible) reference implementation; a native port is a later decision. | full seeded-fault suite green ×3; exact-zero proven for every loss class; protocol round-trip pinned |
| A2 | **C8-FIX** | Transactional goal-amend per Addendum A8 (suspend-only, atomic/rollback, `_amendment_pending` gated on quiescence, HOLD on partial failure) in `brain/executive.py` + `runtime.py`; regression observes the command stream incl. the forced-partial-failure case | regression green; r24/nominal-stop oracles unchanged |
| A3 | **STOP-LOCAL** | Local hotword STOP on the always-local lane wired to the latched stop (A9 tail bars measured with VOICE-GATE) | tail bar met on the desk array |
| A4 | **FOLLOW-COMPOSE** | Production tracker install (camera venue → `install_owner_tracker`), synchronized pixel/range association, UWB driver-or-out-of-BOM decision, follow-speed obstacle/bystander avoidance, owner-loss ⇒ HOLD | capability tests + sim follow suite green; box-day identity gate then decides ENABLE |
| A5 | **EAR + LEDGER** | H1 wiring: rate card into the runtime's `SpendLedger`, VAD gate + engagement triage + (VOICE-GATE's winning policy) in front of the hosted session; server VAD stays on | C-row regressions + config pin tests |
Then: observation spine → LIO boundary → supervised NavigateTo (per the
CLAUDE_RESPONSE build order). M1-4/M1-2 (memory fixes, mind) follow the
spine. Reconciled milestone doc: `research/20260823/MILESTONE1_DESIGN_FABLE.md`.

## Lane B — decision studies (sequential)
1. **NAV-CORE v2** (now): retain/simplify/delegate + the false-healthy
   refuter (`research/20260824/nav-core/DESIGN.md`, v2 delta applied).
2. **VOICE-GATE v2** (after NAV-CORE): consolidated pass rule, XVF3800
   speaker path, STOP-LOCAL tail bars (`research/20260824/voice-gate/DESIGN.md`).
3. **CONNECTED-PLANNER probe** (after; ≤ $1.50): gates connected compounds
   only.

## Freeze
Software architecture freezes after NAV-CORE v2 + VOICE-GATE v2 + the
milestone reconciliation (applied). Electrical/mechanical/physical freeze
waits for vendor written answers + box-day packets. No new review-card
chains; corrections batch at milestone boundaries.
