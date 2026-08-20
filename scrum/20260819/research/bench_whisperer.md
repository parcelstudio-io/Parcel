All measurements complete. Total OpenAI spend ≈ $0.07 of the $1.50 cap. Compiling the report.

# Whisperer Policy Bench: A/B/C/D (+B2) — Results

## Methodology

- **Stream**: 287 events / 597 s synthetic stream, shapes copied verbatim from real artifacts: nav-tick reason strings, `planned|person_stop` flap rhythm, mission-log kinds and block-text from `proof_final.txt` (R4-lite live proof); battery/follow/pace/refusal field shapes from `owner_state.json`. Class mix: 152 nav_ticks, 63 follow_ticks, 12 idle_ticks, 10+8 safety slow/restore churn, 7 mission_blocked, 4 mission_clear, 1 each of reroute/refusal/battery_state/estop/estop_clear, 5 owner_pace_change (2 of them jitter-noise pairs), 2 pace_mismatch, 6 battery_pct steps, 4 lane_internal.
- **Gold labels written before any policy ran** (`gen_stream.py` emits `stream.jsonl` + `gold.json` + `labels.json` in one pass; policies read only the unlabeled stream). 12 gold facts, 10 neutral events, 259 noise events. No post-hoc label edits.
- **Judge**: real Gemma 4 26B-A4B at `:8080` (was already healthy; no relaunch needed), `reasoning_effort:"none"` (~1.5-2 s/call) because in-loop latency is part of the design; reasoning-ON sampled separately (30-49 s/call — see below).
- **B2 bonus arm**: B + tiny deterministic state machines (8 s block debounce, clear-only-after-forwarded-block, drop raw pace_change/mission_started). Coded before any scoring ran. Caveat: same author built stream and B2, and this stream's gold facts are all class-identifiable — stated bias in B2's favor.
- **Shared outer machinery for all arms**: fact-key dedup (TTL 60 s, safety 20 s) + 15 s min-gap for non-critical forwards; criticals bypass.
- **Downstream**: each policy's forwards injected as `[STATE]` system items into gpt-5-mini (`reasoning_effort:minimal`) mid-conversation with 5 scripted owner turns; owner-audible transcript rated by gpt-5.2 on a fixed JSON rubric, 3 reps each.
- **Spend**: ~**$0.072** total (gpt-5-mini ~76 k in / 2.3 k out tokens across 98 calls; gpt-5.2 ~10.2 k in / 1.3 k out across 15 calls; priced at $0.25/$2.00 and $1.75/$14.00 per 1M — re-priceable from reported tokens). Local Gemma: 80 calls, free.

## Gold-label file (inline, as written pre-run)

| Fact | Window (s) | Description |
|---|---|---|
| G1 | 47–92 | Sustained person/obstacle block en route to sidewalk; robot waiting |
| G2 | 76–105 | Way to sidewalk clear again after long block (closure) |
| G3 | 96–115 | Gave up blocked approach; rerouting another way |
| G4 | 122–145 | Arrived ON the sidewalk (terminal success) |
| G5 | 220–245 | Run-follow engaged but owner walking → mismatch, worth asking |
| G6 | 262–285 | Battery normal→low (29%) |
| G7 | 305–325 | Refusal: cannot orbit owner seated at desk (must be said aloud) |
| G8 | 352–378 | Sustained person block en route to door |
| G9 | 394–418 | Arrived near door; holding, awaiting next instruction |
| G10 | 432–448 | Emergency stop: cyclist too close (TTC 0.4 s) |
| G11 | 436–458 | E-stop clearance restored, resuming |
| G12 | 520–545 | Owner dropped to walk in run-follow (ask whether to just walk) |

Full machine-readable copy: `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/csbench/whisperer-ab/gold.json`

## Main comparison (denominators: 12 gold facts, 287 events)

| Metric | A (3-band+judge) | B (2-band table) | B2 (2-band+debounce) | C (judge-everything) | D (caps+dedup) |
|---|---|---|---|---|---|
| Forwards / 10 min | 15–16 | 20 | **14** | 12–13 | 37 |
| Gold hit | 8–10 /12 (2 runs) | 10/12 | **11/12** | 8/12 | 8/12 |
| Missed | G5,G12 (+G1,G2 in run 2) | G3,G5 | G3 | G3,G5,G11,G12 | G2,G5,G8,G11 |
| Spam (noise forwarded) | 1 | 1 | **0** | 2–3 | **25** |
| Duplicate gold mentions | 0 | 2 | 1 | 0 | 1 |
| Median gold mention lag | ~5 s | **0 s** | 0 s | ~9.9 s | 0 s |
| E-stop forward lag | 0 s | 0 s | 0 s | **+9.8 s, clear LOST** | 0 s, clear LOST |
| Judge calls × mean lat | 20 × 1.6 s (p95 2.4) | 0 | 0 | 60 × 2.0 s (p95 3.1) | 0 |
| Judge CPU duty cycle | 5% | 0 | 0 | **20%** | 0 |
| Worst 30 s burst | 3 | 3 | 2 | 2 | 3 |
| Run-to-run deterministic? | **No** (8→10 gold) | Yes | Yes | No | Yes |

**Downstream (gpt-5.2 judge, mean of 3 reps; gpt-5-mini spoke on ~every state item — 0-2 silences):**

| | A | B | B2 | C | D |
|---|---|---|---|---|---|
| Informed /10 | **9.0** | 8.3 | 8.3 | 8.0 | 8.0 |
| Calm /10 | 6.0 | 4.3 | 6.0 | 5.7 | **3.0** |
| Natural /10 | 7.0 | 6.0 | 6.7 | 7.0 | 6.0 |
| Broken flags | none | `claimed_false_ability` ×2/3 | none | none | `missed_estop` ×1/3 |

## Verbatim failure examples

**Gemma judge (A) declines the real fact, forwards the jitter** — the decisive judge-band failure, reproduced with reasoning ON (33 s latency, still declines):
```
win~520 buf=[[283,'pace_mismatch']]              -> -1   (G12 missed)
win~545 buf=[[284,'owner_pace_change walk->jog']] -> 284  (noise forwarded)
win~228 buf=[[134 pace_mismatch],[133 jitter],[135 walk->run]] -> 135  (G5 missed)
```
Also observed: no-think Gemma hallucinated an id not in buffer (`pick=6`) and twice returned unparseable output in re-probes — the harness must fail closed to -1.

**C buries the reroute in telemetry and loses the e-stop-clear to single-pick windows:**
```
win~99  buf=[... 8 nav_ticks ..., [111,'reroute'] ...] -> -1        (G3 missed)
win~437 buf=[[240,'safety_estop'],[241,'safety_estop_clear'],follow_tick] -> 240  (G11 lost)
```
Downstream, C's e-stop line lands at **[442s]** — 10 s after a 0.4 s-TTC event.

**D downstream — battery nag, three questions in 16 s (plus a 4th at 560 s), telemetry narrated:**
```
[246s] parcel: Battery at sixty percent now; want to keep running or slow down for a charge?
[254s] parcel: Battery down to forty-five percent; want to keep running or pause to recharge?
[262s] parcel: Battery low at twenty-nine percent; should I keep running or head back to charge?
[277s] parcel: You're speeding up—I'm keeping pace at 1.6 meters; should I stay this close or drop back a bit?
```

**B downstream — raw pace_change forwards make the model assert wrong pacing** (judge flagged `claimed_false_ability`): `"Switching up to jog speed to keep up with you."` (owner was jittering, not jogging) and `"Matching your pace now — keeping up at 2.6 m/s."` (units read aloud).

**B2's G12 line is exactly the owner-spec behavior:** `[520s] "You're walking now, so I'll match your pace instead of running."`

**Shared min-gap bug found (B and B2):** reroute at t=96 was silently dropped because a mission_clear forwarded at t=90 held the 15 s min-gap — G3 missed by both deterministic arms. Fix: exempt reroute (it's a mini-terminal) or fold block-release+reroute into one composite event.

## What this means for the design

**The judge band does not earn its complexity; the always band does the heavy lifting.** Effect sizes on this stream:

1. **Gold coverage**: B2 92% (11/12) vs A 67–83% (8–10/12 across two runs) — the judge band is *negative* value vs. ~40 lines of debounce/closure rules (Δ +1 to +3 facts). B2's one miss (G3) is a shared cap bug, not a classification failure. C and D trail at 67%.
2. **Spam**: B2 0 vs A 1, B 1, C 3, D 25 per 10 min. D's 25 noise forwards became ~25 spoken lines (downstream calm 3.0/10) — raw forwarding is unusable regardless of caps, and gpt-5-mini essentially never chooses silence, so every forward is spoken. Whatever ships must assume forward ⇒ utterance.
3. **Timeliness**: windowing+judge adds 5–16 s to mid-band mentions (A) and, fatally in C, +9.8 s to an emergency stop with the resume-clear lost outright. Criticals must bypass any judge — the drafted always-band is validated hard by C's failure.
4. **Determinism**: A's forward set changed between identical-input runs (judge latency feeds the min-gap gate → different windows judged). Auditability of "why did the dog say that" is much worse than a table.
5. **Judge quality is the binding constraint, not judge latency**: reasoning-ON Gemma (33–49 s/call, unusable in-loop on CPU) *still* declined the pace-mismatch. The middle band's hard cases here were better solved by making upstream emit a semantic class (`pace_mismatch`) deterministically.
6. **Downstream nuance**: A still scored best on informed (9.0) because the always band carries most perceived informedness — further evidence the marginal band matters less than the always/never split.

**Recommendation**: ship B2's shape — keep the drafted always/never bands and outer dedup+caps exactly as designed; replace the Gemma middle band with three deterministic mechanisms (block debounce ≥8 s, clear-only-after-forwarded-block, upstream-computed mismatch classes); exempt reroute/terminal-like events from the min-gap. If Gemma is used at all, use it off the hot path (phrasing digests, not forwarding decisions). Reject C and D.

**Caveats**: one hand-scripted (pre-labeled) stream, n=12 gold facts; A/C sampled 2×/1× (variance shown, not fully characterized); all gold facts were class-identifiable, which structurally favors tables — a judge could still help on facts whose salience isn't expressible as a class, but no such fact occurred in this grounded scenario, and the refusal case did not discriminate (all five arms forwarded it). Downstream used one cheap model (gpt-5-mini) and one frontier judge (gpt-5.2, 3 reps, rubric shown in `downstream.py`).

**Artifacts** (all under `/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad/csbench/whisperer-ab/`): `gen_stream.py`, `stream.jsonl`, `gold.json`, `labels.json`, `turns.json`, `policies.py`, `fwd_{A,B,B2,C,D}.json` (incl. per-window judge decisions), `score.py`, `scores.json`, `downstream.py`, `transcript_*.json`, `downstream.json`, `judge_reps.json`.

**Spend**: $0.072 of $1.50 cap (OpenAI); 80 local Gemma calls (free); Gemma endpoint was already up — no relaunch needed.