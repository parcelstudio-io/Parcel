# MB-1 — Model B: steering injection and grounded narration for the hosted voice

Author: Fable (parcel-0e), 2026-08-29. Pre-registered before any run.
Evidence tiers: `replay` (scripted event streams through local models),
`hosted-live` (OpenAI Realtime / gpt-realtime-mini text or audio through the
product's `HostedCallGovernor`, wave cap **$5.00**, every row carries $).
Physical: NO-GO.

## What Model B is, concretely

Two functions over typed inputs, sitting on the seams that exist:

1. **Steer** — owner utterance (owner-recognized) + plan queue state →
   {revise(goal), keep, queue(goal), clarify(question)} + the executive call
   that realizes it (`replace` / `suspend` + push / no-op / ask). Today the
   router + amendment do "revise"; "queue" and "clarify-with-plan-context"
   do not exist. NAV-INT-1 measures the decision; MB-1 measures the *wording*
   the hosted voice produces from it.
2. **Narrate** — Model A's narration-event stream (MA-1 vocabulary, or the
   product's receipts when A is absent) + the plan queue → the context the
   hosted voice receives (today: whisperer `StateDigest` facts + developer
   note). MB-1's candidate representation is a **plan-queue whisper**: an
   ordered list of {goal, status ∈ started/progress/blocked/done/queued/
   resumed, since_s} plus the last narration event, rendered as untrusted
   data inside the existing developer-note boundary, refreshed on every
   event and at most every 2 s.

## Hypotheses (falsifiable)

**H-MB1a (grounded narration).** On a 40-scenario scripted event corpus
(door → sofa → keys and variants: blocked, failed, queued, resumed,
clarification), the hosted voice given the plan-queue whisper produces
utterances whose claims are backed by the event stream in ≥ 0.9 of turns
(deterministic grounding check: every navigation/arrival/action claim in the
utterance maps to an event that has occurred or is queued), versus ≤ 0.6
with today's `StateDigest`-only facts (QEV-1's regime). Refuted if the
plan-queue arm is < 0.75 or does not beat the digest arm by ≥ 0.15.

**H-MB1b (right thing at the right time).** In the same corpus the voice
acknowledges a new goal within the first response after the `plan.revised`
/ `plan.queued` event (≥ 0.9), announces completion within the first
response after `nav.arrived` (≥ 0.9), and offers to resume a queued goal
after completion when one exists (≥ 0.8) — and does NOT announce arrival
before it happens (≤ 0.05 premature claims).

**H-MB1c (no invented actions).** Zero proposals of actions outside the
capability registry exposed in the session (the QEV-1 failure) across the
corpus, for both arms, measured by the `realtime_convo_v1` scorer's
capability flags.

**H-MB1d (local vs hosted).** A local 8B instruct model (Ministral-3-8B or
Qwen2.5-7B on this GPU, own server on a port this wave owns — never :8080)
given the same whisper reaches ≥ 0.8 of the hosted model's grounding score
at ≤ 400 ms TTFT; report the gap.

## Measurements

Per turn: grounding (claims ↔ events), timing (event → acknowledgement
turn index / seconds), premature-claim rate, invented-action count, reply
length, TTFT and total latency, $ per turn (hosted) from the ledger rows.
Scored by a deterministic scorer + the existing `score_corpus.py` machine
contracts; a single blinded LLM-judge pass (local model, prompt frozen in
the folder) is reported as report-only, never as the verdict.

## Arms

D: today's digest whisper (StateDigest facts only) → hosted voice.
Q: plan-queue whisper → hosted voice.
Q-local: plan-queue whisper → local 8B.
Every hosted row: `hosted-live`, through `HostedCallGovernor` with the
wave-local `realtime.yaml` (`monthly_budget_usd: 5.0`, model
`gpt-realtime-2.1-mini` or the text model the config names), n ≥ 40
turns per arm, cost recorded; if the governor refuses, the row is
UNMEASURED with the refusal recorded.

## Success criteria

a: Q ≥ 0.9 and Q − D ≥ 0.15; b: three timing bars; c: 0 invented actions
in Q; d: local ≥ 0.8 × hosted at ≤ 400 ms TTFT. CONFIRMED needs a, b, c;
d is reported.

## What it does NOT prove

Event streams are scripted (from NAV-INT-1 / MA-1 shapes), not live
sensing; no audio; the hosted model's behaviour is sampled at one date.

## OWNS / must not touch

OWNS `research/20260829/model-b-narration-1/**`, a wave-local realtime config
under `~/.cache/parcel-0e/mb1/realtime.yaml` (copied from
`configs/realtime.yaml.example`, budget 5.0), a local llama-server on
`:8093` (stop at close). Credentials are read by the product's loader from
`~/.config/parcel/realtime.env` and NEVER printed or copied. No product
edits; the developer-note boundary is used as is.

## Reproduction

`.parcel/bin/python research/20260829/model-b-narration-1/run.py --all --seed 20260829 --hosted-cap-usd 5`
