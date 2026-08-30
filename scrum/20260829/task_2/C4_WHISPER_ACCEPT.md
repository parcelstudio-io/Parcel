# C4 · WHISPER-ACCEPT-1 — a plan-acceptance whisper kind, and a decided band for `KIND_REROUTE`

**Executor:** Opus · **Verifier:** Fable · **Second lens:** parcel-6c · **Wave:** A for `realtime/whisperer.py` (not in the owner's diff) and tests; **B** for the `runtime.py` install hook

## Defect (MB-1, verified line-level by parcel-6c)

The whisperer cannot say "Sure, I'll check the sofa": `_diff` (`realtime/whisperer.py` ~1009) has no plan-acceptance class and no `nav_goal` branch; `KIND_REROUTE` (`whisperer.py:123`) is declared, sits in `CRITICAL_KINDS` (bypasses the spend caps and the monthly ceiling), and is never constructed. MB-1's b1 "new goal acknowledged" therefore has no product producer. Evidence: `model-b-narration-1/VERDICT_FABLE.md`, MB-2 `contract.py` (the ack act).

## Build (parcel-6c's three checks are acceptance rows)

1. `KIND_PLAN_ACCEPTED` fed **from the executive's admission receipt** (`ExecutiveSubmission` / the `_accept_plan` disposition), never from a `StateDigest` `nav_goal` string diff — a string diff re-creates the `nav_tick` problem and fires on re-issues. Payload: goal label, lineage (new / revise / queue — from C6 when it lands; until then `new|revise` from `submit` vs `replace`), and the receipt id. Normal band, own `min_gap_s`.
2. **Decide `KIND_REROUTE`'s band on this card before writing its constructor**, with the spend consequence written: either move it to the normal band with its own min-gap, or keep it CRITICAL and cap reroutes per mission (state the cap). Constructor fed from `SocialProgressStateV1.REROUTE`, not a new detector.
3. The `runtime.py` install (one line where the executive's submission result is available) waits for wave B; ship the whisperer side + a fake-executive test now.

## Acceptance (verbatim bars)

- Unit: a re-issue of the same goal (same task id, `replace` with identical plan) does **not** fire `KIND_PLAN_ACCEPTED`; a new goal does, once; a revise carries `lineage=revise`.
- Band: `KIND_PLAN_ACCEPTED` obeys caps/ceiling (test with the governor at $0 remaining: item is dropped, not billed); `KIND_REROUTE` behaves as decided (test the cap or the min-gap).
- MB-1 corpus replay: with the fake executive emitting receipts for the 40 scenarios, `narration_decisions` show b1 "new goal acknowledged" **75/75** from the new kind (MB-1's trigger table unchanged otherwise); the 2/min, 15 s band ledger unchanged for the other kinds.
- Off-path byte-identical: with no executive receipts, the whisperer's output over MB-1's 40 scenarios is identical to today's (pin a digest).
- `tests/test_whisperer*.py`, `tests/test_realtime_*` subsets green through the guard; no `noqa`; `config.py` unchanged.

## Does not prove
Hosted-model behaviour (no hosted calls on this card); the runtime hook (wave B).

## Wave-B acceptance rows (added 22:1x from the second lens, parcel-6c; binding for the install card)

1. The install at `runtime.py:3625` passes `mission = executive task_id` (revision-independent), lineage from the call site (`submit`→NEW, `replace`→REVISE, queue re-issue→QUEUE), `plan_digest = ValidatedPlan.plan_sha256`; never a goal label or any model-touched string.
2. A deferred replacement (`replace()` → `accepted=True, disposition "defer"`) fires `plan_accepted` **on activation** (`replacement_activated`/`queued`), not at admission; the dropped-before-activation path fires nothing — both tested.
3. A mission-independent ceiling on reroute forwards (≤ N/hour; N stated on the card with its $ denominator: 20 missions/day × ≤ 3 = ~$4.3/month) so a re-issue chain cannot walk around the per-mission cap.
4. Follow-up A1 (wave A, in progress): undeliver rewinds to the last SHARED forward; sequence test `[S1, plan_accepted, S2] → undeliver S2 → clock == t1`.
