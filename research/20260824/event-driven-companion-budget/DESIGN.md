# EVENT-BUDGET — continuous local life, event-gated hosted cognition · DESIGN (Codex) · 2026-08-24

## Hypothesis

A companion can run its sensor, safety, world-model, drive and body-intent
loops continuously for 12 hours/day while keeping hosted-model spend below
**$200/month with at least 50% planning reserve**, if hosted models are never
clock-driven. They are invoked only by an admitted conversational exchange,
an ambiguous compound instruction, or a scheduled memory-consolidation job.
All reflexes, STOP/HOLD, tracking, localization, novelty scoring, drive decay,
initiative admission and continuous posture/gaze generation remain local.

This is deliberately a systems hypothesis, not a model-quality claim. It asks
whether the proposed call policy is economically robust enough that model
quality can be optimized inside a hard envelope later.

## Rationale

H1 measured the current conversation corpus and found that silence is not
billed under server VAD; responding to ambient speech is the expensive mode.
H2 refuted an LLM as the 1 Hz monologue/decision tick. H3 and H4 demonstrated
that deterministic drives and body intent can run continuously without any
model call. The remaining question is whether conversation, structured
planning and memory consolidation together still leave a credible reserve.

The rate card is the official OpenAI GPT-Realtime-2.1 mini card as of this
review: text input/cached/output = $0.60/$0.06/$2.40 per million tokens and
audio input/cached/output = $10/$0.30/$20 per million tokens:
https://developers.openai.com/api/docs/models/gpt-realtime-2.1-mini

## Model

`budget_model.py` uses the 174 empirical per-turn mini-audio costs already
recorded by H1, rather than inventing an average. It simulates 10,000
30-day months under a fixed seed, using the normal approximation to each
large monthly sum, and adds explicit text-call budgets.

Scenarios:

1. **M1 nominal:** 174 admitted owner turns/day; 4 hours/day of ambient speech
   after a gate meeting VOICE-GATE's <=4 false opens/hour; 48 structured-plan
   calls/day; 24 consolidation calls/day; proactive self-expression local.
2. **Heavy social day:** 500 admitted turns/day with the same gate, planning
   and consolidation load.
3. **Hosted-proactive stress:** nominal plus 96 hosted phrasings/day, although
   the proposed product keeps these local.
4. **Ungated-TV refuter:** nominal plus H1's measured 960.61 false opens/hour
   for four hours/day.
5. **Clock-driven-LLM refuter:** a hosted text tick at 1 Hz for 12 hours/day,
   at an intentionally small 600 input + 100 output tokens/tick.

Text-call assumptions are frozen before the run: structured plan = 1,200
input + 300 output tokens; consolidation = 2,000 input + 400 output; hosted
proactive phrase = 500 input + 80 output. No cached-input discount is assumed.

## Measurements and bars

| row | measurement | bar |
|---|---|---|
| E1 | nominal monthly p50/p95/max | p95 <= $100 |
| E2 | heavy-social monthly p95 | <= $150 |
| E3 | hosted-proactive stress p95 | <= $150 |
| E4 | ungated-TV monthly p50 | > $200 (refuter must expose the gate dependency) |
| E5 | clock-driven hosted tick deterministic monthly cost | > $200 (refuter must reject cloud-at-clock-rate) |
| E6 | hosted calls caused by continuous control/drive/body loops | exactly 0 |

## Decision rule

If E1-E3 pass and E4-E6 behave as specified, freeze the architecture as
**continuous local loops + event-gated hosted cognition**, with $150 warning
and $200 hard-stop policies. If E1 fails, reduce hosted audio/context before
considering a larger budget. If E2 fails while E1 passes, define a daily turn
allowance and degrade to text/local speech near the reserve. No further model
arm is authorized by this experiment.

## Evidence tier and limits

`replay + deterministic cost simulation`. It does not prove conversation
quality, provider billing beyond H1's sample, voice-gate accuracy, or future
prices. The production ledger must use a dated rate card and measure real
usage. Electricity, cellular and hardware costs are outside the $200 API cap.

## OWNS

Only `research/20260824/event-driven-companion-budget/**`. No product code,
network call, API key or hosted spend.
