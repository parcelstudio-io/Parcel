# H1 — the ambient ear and the cost ladder · DESIGN (Fable) · 2026-08-23

## Hypothesis (falsifiable)
A companion that listens 12 h/day can stay under **$200/month** hosted spend
with hosted-grade quality on the turns that matter, if and only if the
always-on ear is LOCAL and the hosted lane is opened per engaged exchange.
Concretely, replaying the same day of audio/turns through three policies:
- **P0 hosted-always** (today's prototype default: one session, server VAD,
  `idle_close_after_s: 0`) costs > $200/month on gpt-realtime-mini;
- **P1 VAD-gated hosted** (local Silero opens/closes the socket around
  speech with pre-roll) cuts uploaded audio-minutes ≥ 20× with first-word
  truncation ≤ 2 % and endpoint p50 no worse than today's 0.79 s;
- **P2 local-first ladder** (ENG-1 triage hear-only / acknowledge / answer;
  local model answers simple turns; hosted only on a typed escalation)
  escalates ≤ 15 % of turns and loses ≤ 5 points of pairwise quality vs
  hosted-only on the escalated-or-answered set — landing ≈ $100/month.
And the ledger, once it records the audio/text/cached token split at real
prices, agrees with a ≤ $2 live calibration to within 20 %.

## Why (conversation/cost survey; pricing page 2026-08-23)
- gpt-realtime-mini: audio $10/M in ($0.30 cached), $20/M out; text
  $0.60/$0.06/$2.40. Full model 3–5×. Listening = 600 audio tokens/min ⇒ a
  12 h/day open session is ≈ $130/month in silence alone before any turn.
- `realtime/cost.py:25-27` prices every token at $4/$0.40/$16 (the FULL
  model's TEXT rates) and the ledger row has no audio/text split — the
  ceiling that "enforces" `monthly_budget_usd` is wrong in both directions.
- No client-side VAD in front of `lane.send_audio` (`runtime.py:~8910`);
  endpointing is the provider's `server_vad`. The local lane already has
  Silero v6 + Smart Turn v3 (`audio/endpointing.py`).
- Corpus for $0 replay: `evals/companion/realtime_convo_v1` (25 threads /
  174 owner turns, captured against mini for $0.50, replayable through
  `FakeRealtimeServer`); acoustic WAVs in `evals/20260820/voice_corpus_v1`;
  judge framework `evals/autorater/` with `models/judge/Qwen3-32B-Q4_K_M.gguf`.
- Measured per-turn rows exist ($0.0041–$0.0099 at assumed rates; cache
  hit 77 % text / 64 % audio) — the experiment re-prices them.

## Objective
Decide the conversation architecture's economic shape with measured
numbers, and fix the instrument (the ledger) so the product can enforce the
$200 cap honestly.

## Experiment
1. **Ledger fix** (product seam, additive): `realtime/cost.py` gains a
   `RateCard(frozen)` with the real mini/full rates + `as_of` date and a
   `priced_usd(row)` that uses `input_token_details`/`output_token_details`
   (audio vs text vs cached) when present; `realtime/spend_ledger.py`
   records those details from `response.done` usage. Old rows without a
   split keep the ASSUMED path (flagged). The `monthly_budget_usd` gate
   reads the new pricing.
2. **P0 model**: from the corpus + the pricing, compute $/active-hour and
   $/silent-hour; project a 12 h/day month for mini and full.
3. **P1 harness**: Silero gate in front of a fake transport; replay the
   voice-corpus WAVs and synthetic silence/noise (TV) at the session
   boundary; measure uploaded audio-minutes / listening-minutes,
   first-word truncation (pre-roll 300/500/800 ms), endpoint p50, false
   opens per hour on TV-noise.
4. **P2 harness**: route each of the 174 owner turns through (a) ENG-1
   triage (pure `voice/engagement.py`: answer / acknowledge / hear-only —
   build it as the tranche-2 card specified), (b) a local answer arm on the
   GPU reasoner (`:8081`; start it with `scripts/launch_reasoner_gpu.sh` if
   down — H2 owns that server; coordinate by checking `/health`), (c) a
   typed escalation signal (uncertainty / needs-tool / needs-memory /
   long-form) that sends to the hosted arm (corpus replay — no live call).
   Score local-vs-hosted answers pairwise with `evals/autorater` (both
   orders, abstention ≠ tie). Compute $/month = escalated-turn cost +
   P1 listening cost.
5. **Live calibration (≤ $2.00 total, mini, `mode: text`+audio smoke)**:
   20–40 real responses through the owner's configured lane with the
   fixed ledger; compare recorded split-priced $ to the OpenAI usage the
   `response.done` payload reports. Stop at $2.00 regardless.

## Measurements (pre-registered)
| row | metric | criterion |
|---|---|---|
| C1 | P0 projected $/month (mini, full), 12 h/day | reported (expect > $200 mini) |
| C2 | P1 uploaded-minutes / listening-minutes | ≥ 20× reduction |
| C3 | P1 first-word truncation at chosen pre-roll | ≤ 2 % |
| C4 | P1 endpoint p50 | ≤ 0.79 s |
| C5 | P1 false opens/hour on TV noise | ≤ 4 (report) |
| C6 | P2 escalation rate | ≤ 15 % |
| C7 | P2 pairwise quality delta (autorater, both orders) | ≥ −5 points; abstentions reported |
| C8 | P2 projected $/month | ≤ $200 (target ≈ $100) |
| C9 | ledger split-priced $ vs live usage | within 20 % on the ≤ $2 run |
| C10 | hosted spend of this experiment | ≤ $2.00, itemized |

## What would refute it
C2/C3 cannot both hold ⇒ local VAD gating costs first words and the design
must keep a rolling pre-roll buffer in the gateway (say how big). C6 > 30 %
⇒ the local model is not a viable first rung; the ladder becomes
"hosted-when-owner-present" and the design says what "present" means. C9
off by > 20 % ⇒ the token accounting is still wrong — report which field.

## Evidence tier / does not prove
`replay` + `hosted-live` (≤ $2). Proves the economics and the triage
mechanism offline; does not prove through-air acoustics (the array
campaign is owner-gated) or that the runtime wires the gate (milestone card).

## OWNS
`research/20260823/ambient-ear-cost-ladder/**`, additive changes in
`realtime/cost.py`, `realtime/spend_ledger.py` (schema v2 rows, v1 still
readable), new pure `voice/engagement.py`, one capability test
`tests/test_h1_cost_ladder.py` (rate card prices a fixture row; v1 rows
still parse; budget gate uses split pricing). Must not touch:
`realtime/lane.py` control flow, `runtime.py`, the owner's `realtime.yaml`
(read-only), `configs/robot.yaml`. Uses `~/.config/parcel/realtime.env`
only through the existing launcher path for step 5.
