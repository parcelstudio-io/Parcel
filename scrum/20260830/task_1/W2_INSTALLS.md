# W2 · INSTALLS-1 — C4's plan-acceptance hook and C5's speech acts reach the product path

**Executor:** Opus · **Verifier:** Fable · **Lens:** parcel-6c · Rows inherited verbatim from `scrum/20260829/task_2/C4_WHISPER_ACCEPT.md` ("Wave-B acceptance rows") and `C5_SPEECH_ACTS.md` ("Wave-B acceptance rows") — all binding.

## Build
1. **C4 hook:** `runtime.py` `_accept_plan` — insert `self._whisper_plan_accepted(plan, validated, submission, frame)` after the "Accepted plan" emit and before `return self._plan_acknowledgement(plan)` (HEAD line 3607; the tree's line differs by the owner's +29 — locate by the anchor, not the number); the 12-line sibling from `C4_STATUS.md` §6. `mission = executive task_id` (revision-independent; never a goal label), lineage from the call site (`submit`→NEW, `replace`→REVISE, W1's queue→QUEUE), `plan_digest = ValidatedPlan.plan_sha256`. Deferred replacement fires on ACTIVATION; dropped-before-activation fires nothing (both tested). Mission-independent ceiling ≤ N reroutes/hour (state N and its $ denominator on the card: 20 missions/day × ≤ 3 = ~$4.3/month).
2. **C5 install:** `lane.py:1832` `narrate_event(text, *, critical=False, act: SpeechAct | None = None)`; `act=None` leaves line 1899 byte-identical (the flag-OFF digest proves it); with `realtime.speech_acts.enabled` and an act, render→check as ONE unit (`compose` then `check`; a REJECT falls back to the template, never speech); `_narrate_mission` (`runtime.py` ~16561) passes `decision.act`; the KIND→FACT bridge lives in the whisperer/executive (table in `C5_STATUS.md` §6c). **Voicing: item-only + local TTS for terminal facts; never a `response.create` on a fact.**
3. `places` at the call site = the learned map's known places, non-empty; empty ⇒ an error at the install point (never a silent disable); a swapped destination is refused (test).
4. `voice/amendment.py` `clarification_from_grounding` produces claim-free questions (test its corpus through `check()`), or the refusal noise is measured and reported.
5. `RealtimeConfig.as_dict()` renders `speech_acts`; TURN-1's `/api/state` key-set row (`tests/test_turn1_endpointing.py:302`, `HEAD_CONFIG_KEYS`) re-pinned in the same commit with the reason.
6. One docstring line in `narration_matcher.py` documenting the door-read-failure source delta.

## Acceptance (verbatim bars)
- MB-1's 40-scenario corpus replayed through the PRODUCT path (fake executive → receipts → `_accept_plan` hook → whisperer → lane with the flag ON, fake voice): b1 "new goal acknowledged" **75/75** from `KIND_PLAN_ACCEPTED`; narration grounding **≥ 0.98**, invented **0**, keys bar **15/15** — scored with `narration_matcher` (= MB-1's scorer, pinned).
- Flags OFF: C4's off-path digest `4e5e2e47…` and C5's `edaa32ed…` unchanged; the arm-T reproduction row still exact.
- Poisoned-slot and claim-bearing-clarification tests REJECT; swapped destination refused; empty `places` errors.
- `tests/test_realtime_*.py`, `tests/test_runtime_whisperer_wiring.py`, `tests/test_turn1_endpointing.py` (re-pinned) green through the guard; no `noqa`; `config.py` unchanged; hooks confined with the avoided dirty hunks listed.
