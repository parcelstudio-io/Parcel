# Arbitration — Phase-1 (Sol REQUEST CHANGES on Opus; Opus APPROVE on Sol)

**Date:** 2026-08-05  
**Arbiter:** Fable (Claude Fable stand-in)  
**Inputs:** [ADJUDICATION.md](ADJUDICATION.md) K3/K6,
[REVIEW_SOL_ON_OPUS_P1.md](REVIEW_SOL_ON_OPUS_P1.md) (REQUEST CHANGES),
[REVIEW_OPUS_ON_SOL_P1.md](REVIEW_OPUS_ON_SOL_P1.md) (APPROVE),
[K3_STATUS.md](K3_STATUS.md), [K6_STATUS.md](K6_STATUS.md),
[docs/PAUSE_SEMANTICS.md](../../../docs/PAUSE_SEMANTICS.md); code verification
of closed-intent pause vs `PreemptionTable` vs `_pause_channel`.  
**Scope:** Phase-1 Opus join (esp. K6↔K3) and confirmation of Sol pure P1.

## Verdict

**Uphold Sol on Opus: REQUEST CHANGES. B1 is BINDING.**

Closed spoken `pause` today calls `preempt("voice")`, and the default table
maps `voice → {navigation,follow,search,…}` to **STOP**. That destroys the
mission and never records a `ResumeIntent`. Spoken `resume` can still return
the success reply with nothing restored. This contradicts
`pause_navigation`’s own docstring, `docs/PAUSE_SEMANTICS.md`, and K3’s
suspend→resume transaction. Fix B1 + S1 before calling the Opus P1
voice↔resume seam done.

**Sol Phase-1 pure APPROVE stands.** Opus’s review of Sol pure (K4/K5/K8
generator) is confirmed; no Sol must-fixes from this arbitration.

---

## Code verification (B1 — factually true)

| Site | Behavior |
|---|---|
| `RobotRuntime._apply_closed_intent` (`directive.suspend`) | Calls `self.preempt("voice", reason="closed_intent_pause", targets=("follow","navigation","spatial","search","activities"))` |
| `PreemptionTable.default()` | Explicit loop: for `claimant in ("voice","pose","trajectory")` × active locomotion → **`PreemptionAction.STOP`** |
| `BehaviorChannelRegistry.preempt` | Records `ResumeIntent` **only** on `PAUSE` + pausable; STOP calls `channel.stop` |
| `RobotRuntime._pause_channel` / `pause_navigation` | Dedicated true-PAUSE path: `channel.pause` + `ResumeStore.record`; docstring: does **not** use `preempt("voice")` because voice→nav is STOP |
| `VOICE_INTERRUPT_POLICY` | `"closed_intent_pause"` is **not** mapped → defaults to **overlap**; executive interrupt from closed pause is a no-op on tasks while channels are destroyed |

Net product effect: closed `pause` stops locomotion destructively; store stays
empty; closed `resume` cannot restore progress. K6 tests never exercise
runtime pause→resume via closed intents, so the suite stays green.

---

## Binding decisions (Sol findings on Opus)

| ID | Finding | Decision |
|---|---|---|
| **B1** | Closed-intent `pause` uses `preempt("voice")` → STOP; no `ResumeIntent` | **BINDING must-fix** |
| **S1** | Closed-intent `resume` always returns success reply | **BINDING must-fix** (with B1) |
| **S2** | Live nav extras still lift privileged sim semantic tracks | **defer** (named follow-up; not this re-review blocker) |
| **S3** | K8 stub checks freshness *flag*, not stale-obs rejection | **accept** for P1 gate (recommended harness tighten) |
| **N1** | SearchEntity geodesic is Euclidean | **accept** |
| **N2** | Walk/catalog grammars still bypass PlanSketch | **accept** |
| **N3** | Social reaction bridge ticks but does not actuate | **accept** |
| **N4** | K8 geometric stubs teleport into goal | **accept** (`does_not_prove` / stub harness) |
| **N5** | Compose healthcheck is import-only | **accept** |

### Sol pure P1 (Opus review)

| Item | Decision |
|---|---|
| Opus verdict **APPROVE** on Sol pure | **Confirmed — stands** |
| Opus non-blocking notes (batch soft-skip, freshness caller obligation, embedding dim, `__init__` re-export, color_meta softness, absent-target GoalRegion) | **accept / defer to wiring** — not Sol pure blockers; no must-fix |

---

## B1 — BINDING must-fix

**Rule:** Closed companion `pause` must be a **true PAUSE** on pausable
channels (`navigation`, `follow`, `search`): freeze budgets, emit no motion,
and **store a `ResumeIntent`** via the same path as `pause_navigation` /
`_pause_channel` / search→follow. It must **not** go through
`preempt("voice")` for those channels.

`spatial` / `activities` remain non-pausable: STOP (or clear) is correct for
them. Spoken `stop` / `emergency_stop` stay the destructive cancel path —
unchanged.

Do **not** “fix” B1 by flipping the global `voice→nav` table row to PAUSE.
That table encodes mined stop-site semantics for other voice claimants
(poses/trajectories/legacy). Closed pause is an executive cap that must take
the dedicated pause path, exactly as `pause_navigation` already documents.

---

## S1 — BINDING must-fix (with B1)

Conversation truthfulness: if no channel resumes successfully (missing /
expired intent, or freshness reject), **do not** return the success reply.
Return an honest failure or clarification. Partial success may acknowledge
which channels resumed; total failure must fail closed.

---

## Exact Opus remediation

### 1. B1 — closed pause → true PAUSE + ResumeIntent (required)

In `RobotRuntime._apply_closed_intent`, replace the `directive.suspend` body
that calls `preempt("voice", targets=(…all…))` with:

1. **Pausable channels** — under `_command_lock`, for each of
   `navigation`, `follow`, `search` that is active, call
   `_pause_channel(name, reason="closed_intent_pause")`
   (or `pause_navigation` for nav). This records `ResumeIntent` and freezes
   controller budgets. Do **not** call `preempt("voice")` on these names.
2. **Non-pausable** — stop/clear `spatial` and `activities` only (targeted
   stop / `preempt("voice", targets=("spatial","activities"))` is fine;
   STOP is the correct action for non-pausable channels).
3. **Executive tasks** — suspend, do not cancel and do not no-op:
   - Either add `"closed_intent_pause": "suspend"` to
     `VOICE_INTERRUPT_POLICY`, **or** call `task_executive.suspend_task(...)`
     for each nonterminal task.
   - Keep `InterruptRequest(source="voice", …)` only if the reason maps to
     **suspend**. Today `"closed_intent_pause"` falls through to **overlap**
     — that must not remain.
4. If suspending a task would *also* trigger reconcile →
   `_pause_semantic_dispatches`, ensure the path is idempotent (double pause
   must not destroy intents). Prefer: pause channels explicitly **or** rely
   on suspend→reconcile, not STOP then pause.
5. **Tests** (required; put in `tests/test_k6_voice_lanes.py` and/or
   `tests/test_resume_transaction.py`):
   - Arm navigation (or follow) → closed `pause` → `ResumeStore.peek` has
     intent with `requires_fresh_observation` as designed → mission/channel
     detail shows paused (not stopped/idle-cleared).
   - Fresh observation → closed `resume` restores progress (nav counters /
     follow intent consumption via `_resume_from_store`).
   - Stale / `observation_fresh=False` → resume rejects; intent remains for
     retry.
   - Assert spoken pause did **not** take the STOP path (mission not
     destroyed; store non-empty).

Re-run: `tests/test_resume_transaction.py`, `tests/test_k6_voice_lanes.py`,
`tests/test_preempt_runtime.py`.

### 2. S1 — honest resume reply (required with B1)

In the `directive.resume` branch of `_apply_closed_intent`:

1. Track whether **any** channel successfully resumed via `_resume_from_store`.
2. Treat missing peek as skip; treat `RuntimeError` / freshness reject as
   failure for that channel (keep existing warning emit).
3. If **zero** successful resumes: return an honest failure/clarification
   string (not `directive.reply` success). Do not claim “resuming with a
   fresh observation” when nothing was restored.
4. Extend the B1 runtime test: pause with empty store / expired intent /
   stale obs → reply is non-success; successful fresh resume → success reply
   allowed.

### 3. S2 — defer (not this re-review blocker)

Live `_navigation_extras` / headless still publishing
`semantic_candidates_from_observation` (privileged GT labels) is a real
oracle-on-agent-path debt. **Defer** to a named K5 agent-path hardening
pass: feed noise-adapted `DetectionMsg` (or equivalent) on the default nav
extras path; keep privileged GT scorer/test-only. Status already admits the
gap — do not block B1/S1 re-review on it, and do not quote GT-grounded SR as
perception evidence.

### 4. S3 — accept (recommended, not binding)

`WalkWithMeRunner._stub_pause_resume` checking the freshness **flag** is
acceptable scaffolding for P1 with `harness_used=stub_placeholder` +
`does_not_prove`. Recommended (same pass if cheap): assert
`resume_rejection_reason(..., observation_fresh=False)` → `stale_observation`
and success only when fresh — matching K3. Not required to clear B1/S1.

### 5. Nits N1–N5 — accept

No Phase-1 Opus must-fix. Keep honesty already in status / manifests.

---

## Gate clearance

| Card / lane | This gate |
|---|---|
| **K3** | **Clear as K3** — coordinator + tests stand; **join broken by K6 closed pause** until B1 |
| **K6** | **Not clear** — B1 + S1 required for APPROVE of the voice↔resume seam |
| **K4/K5/K7/K8 Opus wiring** | **Clear for this gate** modulo deferred S2 (K5) and accepted S3 (K8) |
| **Sol pure P1** (K4 modules, K5 pure, K8 generator) | **Clear — Opus APPROVE confirmed** |

---

## Bottom line

**B1 is true and BINDING.** Closed pause must use `_pause_channel` / true
PAUSE and store `ResumeIntent`; closed resume must not lie when nothing
resumes (**S1**). Re-review Opus P1 voice↔resume only after those land with
the integration tests above. Sol’s pure Phase-1 **APPROVE stands** unchanged.
S2 deferred; S3 and nits accepted.
