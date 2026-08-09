# Arbitration — task_2 (Sol REQUEST CHANGES on Opus; Opus APPROVE on Sol)

**Date:** 2026-08-06  
**Arbiter:** Fable (Claude Fable stand-in)  
**Inputs:** [SOL_REVIEW_OF_OPUS.md](SOL_REVIEW_OF_OPUS.md) (REQUEST CHANGES),
[OPUS_REVIEW_OF_SOL.md](OPUS_REVIEW_OF_SOL.md) (APPROVE),
[OPUS_STATUS.md](OPUS_STATUS.md), [docs/PAUSE_SEMANTICS.md](../../../docs/PAUSE_SEMANTICS.md);
code verification of `_brain_hold`, `preempt` / STOP vs `ResumeStore`,
`_pause_channel`, `_stop_search_channel`, `_finish_owner_search`, and closed-intent
resume.  
**Scope:** Sol must-fix on PlanIR Hold / stay settle completeness; confirmation
of Opus APPROVE on Sol proxemic lane.

## Verdict

**Uphold Sol on Opus: REQUEST CHANGES. Must-fix #1 is BINDING: FIX.**

`_brain_hold` settles locomotion via `preempt("manual")` → STOP on
follow/nav/search, but STOP never clears `_resume_store`. A prior pause
(especially search→follow) can leave a `ResumeIntent` that closed-intent /
coordinator resume later consumes — resurrecting motion after
`"Okay—I'll stay here."` That contradicts Opus’s own product claim that Hold
means settle. Clear settled-channel intents + add a regression before calling
the Hold honesty fix done.

**Opus APPROVE on Sol proxemic stands.** No dispute; no Sol must-fixes from
this arbitration.

---

## Code verification (must-fix #1 — factually true)

| Site | Behavior |
|---|---|
| `RobotRuntime._brain_hold` | `preempt("manual", reason="hold_skill", targets=("follow","navigation","spatial","search","activities"))` then control stop / zero velocity. **No** `_resume_store.clear(...)`. |
| `PreemptionTable.default()` | `manual → {follow,navigation,search}` is **STOP**. |
| `BehaviorChannelRegistry.preempt` | Records `ResumeIntent` **only** on PAUSE + pausable; STOP calls `channel.stop` and leaves the store untouched. Explicit `targets=` still STOPs listed channels even when inactive/paused. |
| Search→follow | `preempt("search", targets=("follow",))` is the one PAUSE override; stores a follow `ResumeIntent` as the sole resume path. |
| `_stop_search_channel` / `_finish_owner_search` | Abandoned / exhausted search **clears** follow intent so settle cannot be undone by leftover resume. |
| `_apply_closed_intent` (`directive.resume`) | Peeks `navigation` / `follow` / `search` and calls `_resume_from_store` when an intent is present. |
| Opus hold ack | `_plan_acknowledgement(hold)` → `"Okay—I'll stay here."`; status claims stay means settle. |

Net product effect: pause (or search→follow) → Hold/stay stops adapters and
acks settle, but a later spoken/coordinator resume can re-enable follow/nav
from the uncleared store. Opus’s follow/stay test only asserts
`follow.enabled` / idle after Hold — it never seeds a leftover intent or
asserts store emptiness / resume no-op.

Pause vs Hold is intentional asymmetry: closed `pause` must **record** intents
(K3 / PAUSE_SEMANTICS); Hold/stay is destructive settle and must **clear**
them — same family as abandoned search, not the same path as `_pause_channel`.

---

## Binding decisions

| ID | Finding | Decision |
|---|---|---|
| **M1** | `_brain_hold` STOPs channels but does not clear `ResumeIntent`s for follow/nav/search | **BINDING: FIX** |
| Sol nits (soft OR asserts, validator `distance_m` floor) | Non-blocking alone | **accept / defer** — not task_2 blockers |
| Opus **APPROVE** on Sol proxemic / admission pin | Confirmed | **stands** — no Sol must-fix |

### Sibling note (not a separate Sol must-fix for this dispute)

`set_behavior("stay")` uses the same `preempt("manual")` + `stop_motion`
pattern without clearing the resume store. Prefer clearing there too when
touching the settle path, so UI/action stay and PlanIR Hold share the
invariant — but the binding remediation for this review is `_brain_hold` +
regression as Sol stated.

---

## M1 — BINDING must-fix

**Rule:** PlanIR `Hold` / settle must leave pausable locomotion channels with
**no** pending `ResumeIntent`. After `_brain_hold` preempts, clear resume
intents for at least `follow`, `navigation`, and `search` (same clear pattern
as `_stop_search_channel` / `_finish_owner_search`).

Do **not** “fix” this by making Hold a PAUSE that records new intents —
that would redefine stay as suspend. Hold remains destructive settle; clear
is the correct counterpart to STOP when prior pause intents exist.

Spoken / closed `pause` remains the true-PAUSE path (`_pause_channel` +
store). Unchanged by this fix.

---

## Exact Opus remediation

### 1. Clear settled-channel intents in `_brain_hold` (required)

In `RobotRuntime._brain_hold`, after (or as part of) the settle preempt,
clear:

```python
self._resume_store.clear("follow")
self._resume_store.clear("navigation")
self._resume_store.clear("search")
```

(or an equivalent helper used by abandoned-search settle). Order relative to
`preempt` may vary; store must be empty for those channels when `_brain_hold`
returns.

### 2. Focused regression (required)

Add a test that:

1. Seeds a follow `ResumeIntent` (pause follow via search, or
   `_resume_store.record(...)` directly),
2. Dispatches PlanIR Hold / stay through the path that calls `_brain_hold`,
3. Asserts the store has no follow/nav/search intents,
4. Asserts a subsequent resume (closed-intent resume or `_resume_from_store`)
   does **not** re-enable follow / resurrect motion.

---

## Out of scope / confirmed non-issues

- Pedestrian-traffic e2e xfail left alone — correct.
- Fail-closed admission / heading seed / sketch `1.9 m` alignment — accepted
  as honest; not re-litigated.
- Sol proxemic scorer + NavigateTo admission pin — Opus APPROVE confirmed;
  wiring into pipeline remains a later card.
