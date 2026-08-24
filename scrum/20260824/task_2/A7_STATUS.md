# A7 EAR + GOVERNOR — executor register (Opus) · 2026-08-24

**Card**: `IMPLEMENTATION_PLAN.md` lane A row A7 + the VOICE-GATE Lane-B row,
bound to **H1** (`research/20260823/ambient-ear-cost-ladder/`), **EVENT-BUDGET**
(`research/20260824/event-driven-companion-budget/` + HLD §10), and
**VOICE-GATE v2** (`research/20260824/voice-gate/`).
**Not committed. Git read-only throughout. $0 hosted — no socket was opened.**

## What shipped

| file | what |
|---|---|
| `src/parcel_robot/realtime/ear_gate.py` (new, 696) | the pre-upload gate: `EarGateConfig`, `EarAdmission`, `EarGate` (press → governor → identity/engagement → pre-roll → upload) under one **leaf `RLock`** (the relay runs on the socket-reader thread, the button on the panel thread), `enrollment_channel_matches`, and `note_owner_turn` (the `triage_in_exchange` caller) |
| `src/parcel_robot/realtime/hosted_budget.py` (new, 498) | `HostedCallGovernor`, `GovernorConfig`, `GovernorDecision`, `HostedCallRefused` (the typed refusal), `CLASS_CRITICAL` |
| `src/parcel_robot/runtime.py` (8 hunks, +217/-3) | `rate_card=` on the SpendLedger + `_realtime_rate_card`; `_build_ear_gate` / `_ear_verifier`; the gate in `_realtime_owner_audio`; press/release in `_realtime_mic_gesture`; `_require_hosted_budget` on the typed path; `note_owner_turn` on the transcript path |
| `src/parcel_robot/realtime/spend_ledger.py` (+108/-9) | `day_key`, `DayToDateSpend`, `SpendLedger.day_to_date` (durable per-day burn) and `_entry_from_line` (one row parser, shared with `_read_month`) |
| `src/parcel_robot/realtime/voice_identity.py` (+33) | `VoiceIdentityGate.score_buffer` — the one-shot, stateless scorer the pre-upload ear needs |
| `src/parcel_robot/realtime/audio_gateway.py` (1 line, 0 net) | `AUDIO_CONFIG_KEYS` gains `"ear"` |
| `tests/test_a7_ear_governor.py` (new, 43 rows) + `tests/data/a7_live_usage.jsonl` (34 recorded responses, 24 KB) | the proof |
| `tests/test_realtime_audio_gateway.py` (+6/-1) | one integration row now sends 520 ms instead of one 20 ms frame — the pre-roll is a real hold (see *Behaviour changes* below) |

`core/hard_stop.py`, `finalize_command`, `safety.py`, `core/arbiter.py`,
`audio/stop_hotword.py` and the `_stop_hotword_*` runtime methods: **untouched**,
and the untouchedness is a test, not a claim. **`src/parcel_robot/config.py` is
byte-unchanged and still exactly 1,000 lines** — the A7 block nests under the
already-exempt `audio` subtree (HW-4), so the DEC-0 ceiling was not approached.
**Zero new `# ---- CARD` markers. Zero new ruff fingerprints.** One new lock,
and it is a **leaf** inside `EarGate` — nothing of this package is called while
it is held, so it cannot enter r24's order graph (which scans
`RobotRuntime.__init__` only, and is unchanged); `SpendLedger` and
`VoiceIdentityGate` already own leaf locks on this same relay path.

## (1) The rate card, old → new

`runtime.py` built `SpendLedger(path, on_note=…)` with **no card**, so every row
this product ever wrote used `cost.ASSUMED_*` — the FULL model's TEXT rates —
for audio and text alike. Now `rate_card=self._realtime_rate_card()`.

| USD / Mtok | OLD (assumed, every modality) | NEW `gpt-realtime-2.1-mini` (as_of 2026-08-23) | NEW `gpt-realtime-2.1` |
|---|---|---|---|
| text in | 4.00 | **0.60** | 4.00 |
| text cached in | 0.40 | **0.06** | 0.40 |
| text out | 16.00 | **2.40** | 24.00 |
| audio in | 4.00 | **10.00** | 32.00 |
| audio cached in | 0.40 | **0.30** | 0.40 |
| audio out | 16.00 | **20.00** | 64.00 |

Reproduced on the recorded fixture (34 live responses, verbatim, no socket):
**$0.09035 assumed → $0.020734 published = +335.75 %**, matching H1's
`live_calibration.json` to 4 significant figures, and **row-by-row** against the
study's own per-row dollars (`abs=5e-9`). Per-row ratio spread **> 3×**, so no
fudge factor could ever have corrected it. Resolution order is
`PARCEL_REALTIME_RATE_CARD` → configured `realtime.model` → **`None` (legacy
ASSUMED, said out loud)**; an unpriced model is deliberately *not* charged at the
dearer card, which would ground the dog for an invisible reason.

**Itemization**: every hosted call lands one `parcel.realtime_spend.v2` row
carrying `split_tokens` (six modality counts), `pricing_basis`,
`rate_card_model`, `rate_card_as_of`, `estimated_usd`, `rates_are_assumed:false`
— asserted on all 34 rows, and the month total re-reads to $0.020734.

## (2)+(3) Gate order, and what it measures

`PTT press → HostedCallGovernor → local identity/engagement → pre-roll → upload.`
Ambient admission is **OFF** (`ambient: false`); with the knob on, a press is
still what admits, because no ambient arm has evidence behind it.

Proved three ways: the unit (`EarGate` returns `b""` until admission), the
**product hop** (`RobotRuntime._realtime_owner_audio` driven with a spy lane —
a refused voice produces `lane.send_audio` call count **0**), and structurally
(AST: `offer_frame` precedes `send_audio`, and runtime.py has **exactly one**
`send_audio` call site, so there is no second route to the wire).

| arm | admission code | first upload | pre-roll flushed | uploaded | seen | erased |
|---|---|---|---|---|---|---|
| PTT only (this host: no enrolled profile) | `admitted_push_to_talk` | 500 ms | **500 ms** | 192 000 B | 192 000 B | 0 |
| identity, owner scores 0.90 | `admitted_owner_voice` | 2 000 ms | **2 000 ms** | 192 000 B | 192 000 B | 0 |
| identity, speaker scores 0.20 | `not_owner` | never | — | **0 B** | 192 000 B | **192 000 B erased** |

Pre-roll is enforced as a **precondition of the first upload**, not a statistic
after it: nothing goes up until ≥ `pre_roll_ms` of audio is in hand (H1 C3: 0 %
truncation at ≥ 500 ms, non-zero below). An admitted turn loses **nothing** —
`bytes_seen == bytes_uploaded` — which is what makes the bar checkable.

**Operating point** (VOICE-GATE F1): `identity_threshold` **0.352**,
`min_speech_s` **2.0** (EER 0.000 at ≥ 2 s). Regression row: the owner's measured
room p50 of **0.47** is admitted at 0.352 and **refused at the shipped 0.55**,
uploading zero bytes — the 16.7 % recall defect, as a test.
`realtime.voice_identity.threshold` (0.55) is deliberately **left alone**: it
answers a different question (may this voice *move the robot*) with the opposite
asymmetry, and stricter belongs on the safety side. **Channel-matched enrollment
is a precondition**: with `enrollment_channel` set and the profile's `source` not
naming it, the ear does not verify at all and falls back to PTT, loudly.

**Server VAD stays ON**: the default session shape still renders
`turn_detection {"type": "server_vad"}`, and `TURN_DETECTION_TYPES` has no "off"
value, so no config can produce the manually-committed shape H1's
silence-is-not-billed finding excludes. Pinned, as the H1 second read asked.

## (4) `triage_in_exchange`, wired

`EarGate.note_owner_turn` owns the exchange clock and is called from
`submit_realtime_transcript` (anything the deterministic ingress claimed is
marked `addressed=True` rather than re-derived by grammar). Measured on the
frozen 174-turn owner corpus, **through the product caller**:

| reading | `hear_only` | `answer` | `acknowledge` |
|---|---|---|---|
| context-free `triage` | **66 / 174** | 106 | 2 |
| `note_owner_turn` (in exchange) | **8 / 174** | 164 | 2 |

**58 owner turns recovered.** The window still expires (a marker-free sentence
past `exchange_window_s` is background again) — proven in both directions.
*Note for the verifier*: `voice/engagement.py`'s own docstring says **84** for
this row. Re-measured here through the shipping code on the frozen corpus it is
**66**; the module docstring is left untouched (not this card's OWNS) and the
discrepancy is flagged rather than silently overwritten.

## (5) The governor — seeded-red rows

Defaults are HLD §10's: **$160 envelope + $40 reserve = the owner's $200
ceiling**, warn at **$150**, daily cap **0.0 = off** (no daily bar was measured;
pacing is opt-in). Refusal is at the *envelope* — the reserve is never
automatically spent.

| seeded ledger | class | admitted | code | note |
|---|---|---|---|---|
| $30.72 (EVENT-BUDGET nominal p95) | routine | **yes** | `admitted` | no warning |
| $151.00 | routine | yes | `admitted` | warning names $150.00, emitted once |
| **$160.01** | routine | **NO** | `envelope_reached` | reason names $160.01/$160.00, the reserve, and that STOP/local are unaffected; `HostedCallRefused` raised by `require` |
| $999 (envelope 0.0) | **critical** | **yes** | `never_governed` | **the ledger reader was called 0 times** |
| day $2.25 / cap $2.00, month $4.10 | routine | NO | `day_cap_reached` | pacing, month untouched |
| unreadable | routine | NO | `ledger_unknown` | "stays local"; `refuse_when_unknown:false` restores fail-open |
| no ledger wired | routine | yes | `admitted` | not-metered ≠ unknown; pre-A7 behaviour |
| $200, through `EarGate.press()` | routine | NO | `hosted_budget_refused` | press does not open a turn; frames still go nowhere |
| $300, five presses | routine | NO ×5 | `envelope_reached` | **one** announcement, not five (dedup by text, `SpendLedger`'s own choice) |
| $500, through `_require_hosted_budget` | routine | NO | `envelope_reached` | the TYPED path; `HostedCallRefused` subclasses `RuntimeError`, so the panel already renders it as 409 + the reason |

**Safety is structurally out of the money path**: an AST test asserts that
`audio/stop_hotword.py`, `core/hard_stop.py`, `safety.py`, `core/arbiter.py`,
`core/stop_ramp.py` and `lethal_veto.py` import **neither** new module; that
`_stop_hotword_latched` / `_build_stop_hotword` / `_stop_hotword_bare_window`
mention neither `realtime_governor` nor `realtime_ear` nor
`_require_hosted_budget`; and that the governor's call sites are exactly
`{submit_realtime_text, _realtime_mic_gesture}` — a new one has to be argued for.
`CLASS_CRITICAL` is answered *before any ledger read*, belt to that braces.

## Suites

`tests/test_a7_ear_governor.py` **43 passed**. With the neighbours —
`realtime_spend_budget`, `h1_cost_ladder`, `realtime_ingress`,
`realtime_voice_identity`, `endpointing`, `realtime_lane`,
`realtime_audio_gateway`, `turn1_endpointing`, `a6_stop_local`,
`hw4_array_gateway`, `realtime_protocol`, `realtime_driver`,
`realtime_idle_hangup`, `realtime_audio_capture`, `p2b_owner_awareness` + both
DEC ratchets and `r24_lock_discipline` — **975 passed, 1 skipped** (final run,
after every edit).

**Whole-tree sweep** (`tests/`, minus the two live-hosted files, single process,
19 m 20 s): **10 369 passed, 36 skipped, 3 xfailed — 10 failed, 17 errors.**
**Every one of those 27 is PRE-EXISTING**, proved rather than asserted: the four
modified product files were restored to HEAD *and* the two new modules renamed
away (so nothing of A7 was reachable or importable), the same selection re-run,
and the result was byte-identical — `9 failed, 14 passed, 1 xfailed, 17 errors`
before and after — then everything restored by sha256. They are
`test_barn_sensor_faithful` (1, checked separately the same way),
`test_ci_gate` (2 — `evals/companion/personal_convo_v1/manifest.json` is clean in
git and its sha simply no longer matches the pin in `tests/test_ci_gate.py`),
`test_held_out_scene` (2), `test_person_cell` (1), `test_prototype_profile` (1),
`test_search_reground_bench` (3), `test_v4s_search_cells` (1) and
`test_voice_nav_e2e` (17 setup errors). None is in A7's blast radius (realtime,
audio, spend) and none is touched by this card. All runs through
`pytest_guard.sh --label a7-ear`; never `-n auto`; `ci_gate --tier` not run.

**15 seeded-RED proofs, each mutating one product fact and restoring by sha256**
(all `sha OK`, 0 failures): rate card removed from the constructor · ear hop
removed from `_realtime_owner_audio` · threshold 0.352 → 0.55 · the
below-threshold branch disabled · pre-roll 500 → 200 ms · the pre-roll hold
removed · the envelope comparison widened · a critical call made to read the
ledger · the unreadable-ledger branch disabled · `triage_in_exchange` given no
context · `note_owner_turn` removed from the transcript path · a budget import
added to `stop_hotword.py` · server VAD → semantic VAD · `split_tokens` emptied
· the day filter widened.

## The knob

`audio.ear:` — nested under the SHA-locked base's already-exempt `audio` subtree
**because `config.py` sits exactly ON the DEC-0 1,000-line ceiling and may not
grow**. Unknown keys are refused **by name** at the read site
(`EarGateConfig.from_mapping` / `GovernorConfig.from_mapping`), the
`roam`/`stop_hotword`/`planner_model` pattern. An absent block is the shipped
default in every field.

```yaml
audio:
  ear:
    ambient: false            # M1 = push-to-talk (VOICE-GATE v2)
    identity_threshold: 0.352 # VOICE-GATE F1; NOT voice_identity.threshold
    min_speech_s: 2.0         # EER 0.000 at >= 2 s
    pre_roll_ms: 500          # H1 C3
    max_turn_s: 20.0
    enrollment_channel: ""    # set it and a mismatched gallery stops verifying
    governor:
      envelope_usd: 160.0     # HLD §10
      reserve_usd: 40.0
      warn_usd: 150.0
      daily_cap_usd: 0.0      # 0 = track and report, do not refuse
      refuse_when_unknown: true
```

## Behaviour changes an operator will notice

1. **The first ~500 ms of every turn is buffered before anything is uploaded.**
   That is the card's item 3 and it is a real hold, not bookkeeping; one
   integration row in `test_realtime_audio_gateway.py` had to send 520 ms instead
   of a single 20 ms frame. Response latency is essentially unaffected (the held
   audio is flushed in one burst, far faster than real time) but the change is
   real and is stated here rather than discovered.
2. **A refused identity uploads nothing and the buffer is erased** (HLD §10:
   rejected buffers are erased).
3. **`refuse_when_unknown` defaults to `true`**, which is HLD §10's direction and
   the *opposite* of `spend_ledger`'s documented fail-OPEN. The arming gate's
   fail-open doctrine and its tests are **untouched**; this is a second,
   product-level cap whose refusal degrades to local behaviour rather than
   grounding the robot, and the knob restores the older direction. Flagged for
   the verifier as a deliberate, arguable choice.
4. Ledger rows are now `v2` and priced; the month total for the same traffic
   **falls ~4.4×**, so a stack running near the old $25 ceiling will stop being
   grounded early. `month_to_date` sums v1 and v2 together, unchanged.

## Undone, and why

* **`# noqa: BLE001` × 6** (2 in `ear_gate.py`, 3 in `hosted_budget.py`, 1 in
  `runtime.py`'s `_build_ear_gate`), each on
  a documented never-raises boundary with a reason on the line — the idiom of the
  three modules this code sits between (`spend_ledger.py`, `voice_identity.py`,
  `driver.py`). Removing them would either add a ruff fingerprint (ratchet red)
  or silently narrow a never-raises contract. **Zero new fingerprints either
  way**; flagged for the verifier since the card asked for zero `noqa`.
* **`voice_identity.DEFAULT_THRESHOLD` stays 0.55.** Recalibrating the
  *command-arming* gate needs the owner's real voice enrolled through the
  deployment channel; no owner audio exists on this host (VOICE-GATE caveat 2).
  **Box-day work**, and until then the arming gate is known to be a poor operating
  point for room audio — the pre-upload ear is what ships calibrated.
* **Nothing through air.** 0.352 was fitted on 36 owner / 31 impostor trials with
  the owner *proxied* by a prompt voice (VOICE-GATE caveats 2 and 7); it is an
  upper bound, and the shipped default is that upper bound made configurable.
  Re-measuring on the real owner through the mounted array is **box-day**.
* **Replay is an accepted indoor risk, in writing** (VOICE-GATE F2: 52.8 % at the
  usable threshold; A9 forbids any arm claiming immunity). PTT refuses replay only
  while the spoofer does not hold the button. Liveness is post-M1.
* **Constrained/boosted ASR decoding over the known vocabulary** (VOICE-GATE:
  `base.en` slots 0.850) — named on the card, **not built here**. It belongs to
  the transcriber (`realtime/whisperer.py` / `audio/stop_hotword.py`'s local
  path), not to the admission gate, and folding a decoder change into the byte
  gate would have made both un-reviewable. **Filed as a follow-up.**
* **Per-lane budgets** ($110 conversation / $20 initiative / $20 planner / $10
  memory, HLD §10) are **not** implemented: today one lane opens hosted calls, so
  per-lane pacing would be four numbers describing one thing. The envelope,
  warning line, day tracking and the optional day cap are in.
* **Provider-usage reconciliation, idempotency-key dedup and p50/p95 month-end
  projection** (HLD §10) are not built — all three need provider billing/usage
  reads, i.e. a live probe. The ledger remains a documented **lower bound**.
* **Ambient admission** ships off with no arm behind it; the upgrade is the
  box-day mounted-acoustics decision.
* **No live probe was needed and none was made.** Every dollar in this document
  comes from `tests/data/a7_live_usage.jsonl` or the study files it was cut from.
