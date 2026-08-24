# H1 RESULTS — the ambient ear and the cost ladder · Opus · 2026-08-23

Tree at `0ec1d7c` (DEC-FS-1). Nothing committed. Hosted spend **$0.0378** of the
$2.00 ceiling, itemized in `results/live_calibration*.json`.

## The headline, first
**The DESIGN's central economic premise is refuted by measurement.** It assumes
an open hosted socket is billed for the silence streamed into it (600 audio
tokens/minute ⇒ ≈ $130/month on mini at 12 h/day). It is not. On
`gpt-realtime-2.1-mini` with server VAD, the *same* utterance preceded by
**63.8 s** of uploaded silence and by **3.8 s** of uploaded silence both billed
**19 input audio tokens**. Non-speech is discarded before it is tokenised. The
always-on hosted ear has no silence floor at all.

What is expensive is not listening. It is **answering** — and today's default
answers everything it hears. The P1 tape measured a VAD opening **960.6
times/hour** on a television, and each committed turn is a billed response, so a
house with a TV on 4 h/day takes hosted-always mini from $24.60/month to
**$528.46/month**. The architecture conclusion survives; the reason changed.

## Measurements against the pre-registered criteria

| row | metric | criterion | measured | met? |
|---|---|---|---|---|
| C1 | P0 $/month, 12 h/day | reported (expect > $200 mini) | mini **$24.60** (no ambient speech) → **$528.46** (TV 4 h/d) → $1536.18 (12 h/d); full **$89.63** → $1918.26 → $5575.51 | reported; **> $200 only above ≈ 1.4 h/day of ambient speech** |
| C2 | P1 uploaded/listening | ≥ 20× reduction | **69.3×** (72.84 s uploaded / 5046.85 s listened) | **YES** |
| C3 | first-word truncation | ≤ 2 % | **0 %** at pre-roll 500 ms and 800 ms (5 % at 300 ms; max loss 21.7 ms) | **YES** (pre-roll ≥ 500 ms) |
| C4 | endpoint p50 | ≤ 0.79 s | **0.520 s** p50, 0.538 s p95 (hangover 500 ms) | **YES** |
| C5 | false opens/h on TV noise | ≤ 4 (report) | non-speech room noise **0.0/h**; attenuated TV *speech* **960.6/h**, gate open 70.6 % of the hour | **split: YES on noise, NO on speech** |
| C6 | P2 escalation rate | ≤ 15 % | **22.4 %** of all 174 turns (39/174); 23.5 % of answered turns | **NO** |
| C7 | pairwise quality delta | ≥ −5 points | **−27.2 points** on the 127 locally answered turns; **−20.8** with the 39 escalated turns counted as the ties they are by construction | **NO** |
| C8 | P2 $/month | ≤ $200 (target ≈ $100) | mini **$0.53** (transcript escalation) / **$6.87** (audio escalation); full $4.62 / $24.82 | **YES** |
| C9 | ledger split-priced $ vs live usage | within 20 % | **0.000 %** over 34 live responses | **YES** |
| C10 | hosted spend | ≤ $2.00, itemized | **$0.0378** (32 + 34 responses, two runs) | **YES** |

C7 detail: `pairwise_quality@1`, Qwen3-32B-Q4_K_M judge (CPU), both
presentation orders, base = hosted capture, test = local answer, **0
abstentions in 127 pairs**. Points are declared in `score_p2.py` as
`50 × mean signed score`, so 0 is a tie and −5 points is a mean of −0.10; the
raw mean is **−0.5447**. Preferences: hosted **108**, local **6**, tie **13**.
Position bias (spread between the two orders) mean 0.244, max 1.5 — large
enough that individual pairs are noisy, far too small to explain a −0.54 mean.
By family: punt −34.9, perception −30.8, conversation −27.0, navigation −23.6
points. The local arm won 6 pairs, all of them turns where the right answer was
a short acknowledgement (*"alright go on then"*, *"come on, let's move"*).

**The local model is not close.** It is a 26B MoE with 4B active answering under
the hosted model's own prompt, and on every family it loses decisively. C6 and
C7 fail together and for the same reason, which the DESIGN anticipated only
partly: the escalation signal catches 22.4 % of turns, and the judge says a
further ~60 % of what got through should also have gone up. A ladder whose first
rung is this model needs either a better rung (Ministral/Qwen at 8-32B were not
tried here) or a much more aggressive escalation policy — and the cost headroom
for the aggressive policy is enormous (C8 is $0.53/month against a $200 cap).

## What was run

```bash
# $0 replay
PYTHONPATH=src:<repo>:. .parcel/bin/python run_p1.py       # C2 C3 C4 C5
PYTHONPATH=... .parcel/bin/python run_p2.py                # C6 C8 + the pairs
PYTHONPATH=... .parcel/bin/python run_p0.py                # C1 (reads P1 + live)
PYTHONPATH=... .parcel/bin/python score_p2.py \
    --judge-url http://127.0.0.1:8090 --offset K --stride 4  # C7, 4 workers
PYTHONPATH=... .parcel/bin/python score_p2.py --summary-only # C7 summary
# the one paid run, $2.00 ceiling checked after every response
research/20260823/ambient-ear-cost-ladder/live.sh          # C9 C10
env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label h1 \
    .parcel/bin/python -m pytest tests/test_h1_cost_ladder.py -q
```

Environment: `:8081` gemma-4-26b-a4b CUDA (started by H2's executor at 22:13,
left running — H1 used it, did not start or stop it). Judges: `:8090`
Qwen3-32B CPU (another session's, already bound at 22:32 — used for the first
29 pairs, not started by H1); `:8092` Qwen3-32B CPU (**H1's**, 23:25–00:21,
`--threads 48`, stopped on the integrator's one-judge rule); then ONE capped
judge on `:8090` (`--threads 48 --threads-batch 48`, 00:21–00:32) for the last
21 pairs, **stopped**. No judge server is running now.

Host load while measuring (1-min `uptime`): P1 and P0 ran before any judge
existed; P2's local-arm latency ran at GPU 100 % with H2 and H6 resident; the
C7 batch spanned load 171 down to 17. **Every H1 headline row is a token count
or a dollar figure computed from one — none of them is a stopwatch reading, so
host load does not move any pre-registered number.** The one latency figure
here (local-arm p50/p95) is explicitly reported as contended and is not an H1
criterion. The owner's `:8080` and `:8765` were never touched; the owner's
`recordings/spend.jsonl` was never written (this run's ledgers are in
`results/`).

## The instrument, fixed (DESIGN step 1)

`realtime/cost.py` gains `RateCard(frozen)` — six published rates and an
`as_of` — with cards for `gpt-realtime-2.1-mini` (text $0.60/$0.06/$2.40, audio
$10/$0.30/$20 per Mtok) and `gpt-realtime-2.1` (text $4/$0.40/$24, audio
$32/$0.40/$64), both `as_of 2026-08-23`. `RateCard.price(row)` reads
`input_token_details`/`output_token_details` when present (`basis: split`), and
otherwise apportions the lane's single flattened `cached_tokens` across audio and
text by input share (`basis: split_apportioned`). A row with no split at all —
every ledger row written before today — keeps the ASSUMED path and says so.

`realtime/spend_ledger.py` writes `parcel.realtime_spend.v2` rows carrying the
six token counts, the basis, the card and its date, **only when a rate card is
supplied**; with none it is byte-identical to yesterday. The switch is
`SpendLedger(rate_card=…)` or `PARCEL_REALTIME_RATE_CARD=<model id>` — off by
default, and an unknown id stays off rather than silently pricing at the dearer
card. `month_to_date` totals v1 and v2 rows together and reports
`rates_are_assumed=True` if *any* row in the month was assumed.

How wrong the old instrument was, measured on the live run: **+335.8 %** across
34 responses (**$0.0904 assumed vs $0.0207 published**). The error is not a
constant — **6.7×** on a text row (the assumed rates *are* the full model's text
rates) and **1.59×** on an audio row — so it could not have been corrected by a
fudge factor. `tests/test_h1_cost_ladder.py` pins the consequence: 60 of the
live audio responses cross a $0.40 ceiling under the old arithmetic and do not
under the new one, on identical traffic.

## P0 — hosted-always (C1)

Listening floor: **$0.00/month, measured** (the $129.60 mini / $414.72 full
projection is reported in `results/p0_hosted_always.json` as
`floor_usd_per_month_assumed_refuted`). Conversation, on the pre-registered day
of 174 owner turns:

* **text modality, fully measured** from the corpus's own usage rows:
  $0.0753/day ⇒ $2.26/month mini, $19.56/month full.
* **audio modality, modelled**: $0.8199/day ⇒ **$24.60/month** mini,
  $89.63/month full. The model is calibrated on the live run — output audio
  tokens are **1.54×** output text tokens (measured 1.373 and 1.708), owner
  speech runs at **4.578 words/s** (measured on `acoustic_loop_v1`), and audio
  already in the conversation is re-read as input on later turns (measured: a
  second audio turn billed 37 input audio tokens where the first billed 19).
* **ambient speech** is the whole cost: at the measured 960.6 VAD opens/hour and
  a median modelled audio turn of $0.004371, break-even against $200/month
  arrives at **≈ 1.4 hours/day** of audible speech that is not the owner's.

## P1 — the local VAD gate (C2–C5)

Streaming Silero v6 (the repo's own `audio/endpointing.SileroVad`, int16 512-
sample frames) over 84.1 minutes of tape carrying the 20 speech fixtures of
`acoustic_loop_v1` at the day's rate (14.5 turns/h), plus one hour each of
non-speech noise and of 20 dB-attenuated speech. Sweep at hangover ×
pre-roll ∈ {300, 500, 800} ms; headline operating point **hangover 500 ms,
pre-roll 500 ms**:

| hangover | pre-roll | reduction | truncation | endpoint p50 | split turns |
|---|---|---|---|---|---|
| 300 | 500 | 73.0× | 0 % | 0.296 s | 5/20 |
| **500** | **500** | **69.3×** | **0 %** | **0.520 s** | **3/20** |
| 800 | 500 | 63.5× | 0 % | 0.808 s | 3/20 |

Truncation is measured against the EARLIER of two independent onsets — the
corpus's Silero ground truth and an energy-only witness computed here — so the
gate is not credited by a witness that shares its own model. Zero utterances
were missed at any setting.

Two findings the criteria did not ask for:

* **3 of 20 utterances SPLIT** at 500 ms hangover (5 at 300 ms): the gate closes
  inside the corpus's deliberate 0.75 s mid-sentence pause and reopens. In
  production that is two hosted responses and half an answer. `Smart Turn v3` is
  already in `audio/endpointing.py` and is the named fix; it was not wired here.
* **A pure VAD cannot gate a room with a television in it.** 0.0 opens/hour on
  non-speech noise, **960.6/hour** on attenuated speech with the gate open 70.6 %
  of the hour. The gate answers "is this speech", and the question the product
  needs answered is "is this *my owner*". The repo already has the missing half
  (`realtime/voice_identity.py`, TitaNet embeddings + DOA); H1 did not measure it.

## P2 — the local-first ladder (C6–C8)

ENG-1 shipped as pure `voice/engagement.py` (answer / acknowledge / hear-only,
plus typed escalation). Two triages were run on all 174 turns:

| triage | answer | acknowledge | hear-only |
|---|---|---|---|
| context-free (`triage`, the card's literal function) | 106 | 2 | **66** |
| exchange-aware (`triage_in_exchange`) | 166 | 2 | 6 |

**The context-free function calls 66 of 174 owner-addressed turns "hear-only".**
Mid-conversation replies — *"yes that one"*, *"the one by the petrol station"* —
carry no second-person marker, and a dog that ignores 38 % of what its owner says
is a worse product than one that answers the television. That is why
`triage_in_exchange` exists: one extra argument (seconds since the dog was last
addressed, 45 s window), still pure, no clock owned. The ladder uses it.

Routing under the exchange-aware triage: 127 answered locally by
gemma-4-26b-a4b on `:8081` under the *same rendered session instructions* the
hosted capture used, 39 escalated, 8 silent. Escalations: needs_tool 16,
uncertainty 15, needs_memory 8 — **22.4 %**, over C6's 15 % but under the 30 %
the DESIGN names as its refutation threshold. So C6's *stated* refutation does
not fire — but C7 refutes the same rung by a different route: the escalation
policy is not too aggressive, it is nowhere near aggressive enough, because the
turns it let through are the ones the judge says should have gone up too.
Local latency p50 **1.048 s**, p95 **14.86 s**, measured while H2 and
H6 were saturating the same GPU (100 % utilisation, 31 GB of 32 GB resident);
the p95 is a contention artefact and not an H1 row.

Cost (C8), mini: escalated turns $0.0177/day ⇒ **$0.53/month** with transcript
escalation, or $6.87/month if the escalation carries audio and a gated hosted ear
is billed for its 633.7 uploaded seconds a day. Full model: $4.62 / $24.82.
Every variant is two orders of magnitude under the $200 cap.

## Surprises

1. **Silence is free** (above). It moves the whole argument from "the ear is
   expensive" to "the mouth is expensive".
2. **The old ledger overcharged, it did not undercharge.** The pre-H1 ceiling
   was grounding the dog ~4× earlier than the invoice justified.
3. **A one-sentence engagement classifier is not a mechanism**, it is a
   fragment of one (66/174 above).
4. **The local model's failure mode is confident invention, not refusal.**
   Sampled locals: *"The wheels are turning. We're moving now."*, *"The side
   gate is the only other way out."* — both fabricated, both fluent, neither
   caught by the hedging detector that produced the 15 uncertainty escalations.
   The judge caught them; the ladder did not.

## Does not prove

* **No air.** Every P1 number is synthetic silence and Piper speech played
  digitally. A real room's noise floor is what sets a VAD's false-open rate, and
  it has not been measured. The "TV" is attenuated Piper, not a television.
* **The audio-modality P0 and P2 figures are MODELLED.** Only the text rows are
  measured end to end; the audio model's output-audio ratio is calibrated on
  **two** live audio responses (1.373 and 1.708) — a two-point calibration, and
  the single widest crack in the C1 and C8 audio figures.
* **The corpus is one day, authored, and 100 % owner-addressed.** It cannot
  exercise hear-only honestly, and the ambient rates come from the P1 tape.
* **No product path.** The gate is harness-only; `lane.send_audio` is unchanged.
  `voice/engagement.py` has no call site — the tranche-2 card owns wiring it into
  the voice pipeline. The rate card is opt-in and `runtime.py` still constructs
  `SpendLedger` without one, so the owner's live ceiling is still the old number
  until one line changes.
* **C7's judge is a CPU Qwen3-32B at temperature 0 on 127 pairs**, not a human.
  Position bias is reported per pair in `results/p2_quality.jsonl`.
* **It does not prove the ladder is wrong, only that THIS rung is.** One local
  model was tried, at temperature 0, with no retrieval and no tools.

## Raw files

`results/p0_hosted_always.json` · `p1_vad_gate.json` (per-utterance rows) ·
`p2_ladder.json` (per-turn routing + both local and hosted text) ·
`p2_quality.jsonl` + `p2_quality_summary.json` (127 rows, 0 abstentions; an
earlier batch of 99 abstentions caused by stopping a judge server mid-run was
purged and re-scored, so the file holds only adjudicated pairs) ·
`per_turn_prices.json` ·
`live_calibration.json` + `live_calibration_run1.json` ·
`live_spend_v1.jsonl` / `live_spend_v2.jsonl` (the same 34 responses under both
pricings) · `logs/` (judge + worker logs).
