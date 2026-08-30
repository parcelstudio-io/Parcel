# LIT-1 — VERDICT (Fable, the wave's designated verifier)

Verifier: Fable (parcel-0e), 2026-08-29 20:0x EDT. Design frozen 15:3x;
pre-run amendments L1–L10 at 15:41/15:53. The executor built the loop, ran
five seeded fake-voice runs of the scenario of record, five variants and one
hosted run, then was killed by the account spend limit (RESULTS §2–§8 are
"PENDING" stubs); every number here is read from its JSONL artifacts by my
own script (`~/.cache/parcel-0e/verify/lit1/verifier_analysis.json`). An
independent post-hoc audit by Sol (`../lit1-grounding-audit/`, 5/5 false
terminal arrival claims) is concurred with below. Evidence tier:
`desktop-sim` (MuJoCo static city through the live runtime; text utterances;
fake or hosted voice); hosted tier effectively unmeasured (see b).

## What the loop did, in the executive's own vocabulary

All five seeded fake runs and the hosted run produced the same receipt-kind
sequence: `submit(lamppost)` → `task_suspended(goal_amend)` →
`replacement_activated(bench, same task id)` → **`task_failed`**
(`semantic_target_unreachable`) → harness `re_issue(lamppost)` → `submit` →
**`task_failed`**. Run r2 carries one extra benign `ignored_stale_result`
between suspend and replacement. The variants without a mid-route amendment
(no-op, sound event, queue phrasing) reach `task_succeeded` with both
authorities agreeing on arrival; the unreachable-clarify variant suspends
and never resumes; the blocked-route variant fails like the base.

## Verdicts

| | bar | measured | verdict |
|---|---|---|---|
| **H-LIT1a** loop closes deterministically | 5/5 identical receipt-KIND sequences (L7), hops rendered | 5/5 structurally identical (4/5 byte-identical; r2 + `ignored_stale_result`); every run `ok=true`, teardown proven, 0 name-scan leaks | **CONFIRMED as a harness** — the loop, the seams, the logging and the replay work. **REFUTED as the scenario of record**: the amended goal never completes (bench unreachable from the mid-route pose in every run; DTG 3.33 m), and after the failure the robot does not move on re-issue (identical end pose on both scored legs, lamppost DTG 1.39 m). The receipt sequence that was pre-registered ends in `task_succeeded` twice; the product produces `task_failed` twice. |
| **H-LIT1b** hop latencies | switch ≤ 1.5 s (local path); TTFT ≤ 1.2 s (hosted) | utterance → cue 10.5–17 ms; cue → first executive receipt −9…−16 ms (receipt precedes the cue log line — same poll); switch (heading toward the new goal, L9 rule) **240–345 ms** across the five base runs (blocked-route variant 1,167 ms); hosted TTFT: **UNMEASURED** — the hosted run logged no `voice_turn`, and every plan-queue `whisper_injection` on the hosted lane reports `delivered: false` | local-path bar **met** (p50 ≈ 0.32 s); hosted **UNMEASURED** (LIT-1 spent $0.00 — the item-injection door did not deliver on the live lane; the ledger's $2.21 is MB-1's) |

## The two findings that matter

1. **The harness narrated a terminal that did not happen.** On every base
   run the offer line "I've reached the bench. I can't check whether your
   keys are there…" is emitted on the `task_failed` receipt (the template
   assumed success; it is labelled `grounded_in: the accepted terminal
   receipt` but the receipt says failed). Sol's audit found the same 5/5.
   This is precisely the false-terminal class the whole wave exists to
   prevent — and it was produced by *deterministic* harness code, not by a
   language model. The fix is a receipt-typed speech act (MB-1's
   recommendation: `completed` vs `failed` templates, a post-condition
   checker), which LIT-1's amendment L7 already required and the executor
   did not implement.
2. **The product cannot execute the owner's example.** "Go to A; mid-route,
   actually go to B; done; back to A" fails on the shipped stack because the
   mid-route re-target to the bench resolves `semantic_target_unreachable`
   (the same clearance-class failure NAV-QUALITY recorded for "sit next to
   the bench"), and after a failed task the navigator does not re-plan on
   re-issue. NAV-INT-1's 32-episode tier shows the same shape (amended-goal
   success 0.39 vs 0.75 from rest). The door → sofa → keys demo is
   therefore a *navigation* problem before it is a conversation problem.

## What it does NOT prove

No audio, no real owner, no hosted narration measured, demo-city landmarks
as stand-ins; the switch latency is the local text path; nothing about the
Orin or the Go2.

## Product path

Harness-only. The loop uses `handle_text` for motion (L6), a
LIT-1-owned plan-queue whisper and a labelled minimal confirm→re-issue rule;
hosted motion doors refuse without a voice binding, as pre-registered.
