# TURN-1 — pre-registration

Written **before** any code was changed and before any number was measured.
Executor: Claude Opus. Card: `README.md`. Board: `../TASK_BOARD.md`.

Reference bytes captured from HEAD `8862220` *before* the first edit, under
`/home/jaewoo-jang/.cache/parcel-turn1/`:

| artefact | sha256 |
|---|---|
| `head_session_update.json` (`SessionUpdate(...).to_payload()`, no `turn_detection` arg) | `a87d9fac19edc5b96208fed0ae4f4194865fd2452ba2fb14aa1617a7dcfc619f` |
| `head_wire_trace.json` (every client frame across `handshake+happy_turn` and `handshake+barge_in_turn`) | `dcfa10d58a479850e21d321dd649827e393968ebdf3bb8134980a4e1591960a6` |
| `head_config_keys.json` (`RealtimeConfig().as_dict()` key set, 17 keys) | captured |

## CI rows — no owner, no hardware, no hosted spend

| id | row | target |
|---|---|---|
| **T1** | **Payload identity.** `SessionUpdate(instructions, model, voice)` with no `turn_detection` argument; with `turn_detection=TurnDetection()`; and with the `turn_detection` from `realtime_config_from_mapping({})` — all three `to_payload()` results equal HEAD's captured payload byte-for-byte (`json.dumps(..., sort_keys=False)`). | 3/3 identical |
| **T2** | **Config identity.** A `realtime.yaml` body with no `turn_detection:` key loads to a config whose `as_dict()` adds exactly one key vs HEAD's 17 and changes none of the other 16. | +1 key, 0 changed |
| **T3** | **`silence_duration_ms` range.** 200 and 800 accepted (inclusive); 199 and 801 refused with `RealtimeConfigError`. | 2 accept / 2 refuse |
| **T4** | **Enums.** `type` ∈ {`server_vad`,`semantic_vad`} accepted, anything else refused; `eagerness` ∈ {`low`,`medium`,`high`,`auto`} accepted, anything else refused. | 6 accept / 2 refuse |
| **T5** | **Cross-key.** `eagerness` under `type: server_vad` refused; each of `threshold` / `prefix_padding_ms` / `silence_duration_ms` under `type: semantic_vad` refused. A knob the provider would silently ignore is a refusal, not a default. | 4/4 refuse |
| **T6** | **Unknown key.** An unknown key inside the `turn_detection:` block refuses and names the allowed set. | 1/1 |
| **T7** | **Timing counters.** After one scripted turn carrying `response.created` and audio, `lane.snapshot()["turn_timings"]` holds one row with finite `response_created_ms` and `first_audio_ms`, `first_audio_ms >= response_created_ms >= 0`, and `turns_timed == 1`. | 1 row, both fields |
| **T8** | **Timing is a behavioural no-op.** With the timing code in place the client frames the lane sends across `handshake+happy_turn` and `handshake+barge_in_turn` are byte-identical to `head_wire_trace.json`. | sha match |
| **T9** | **Replay tool.** `tools/replay_turn_detection.py --arms` prints the 4 arms, exit 0; `--check` runs T1/T3/T4/T5/T6 as assertions, exit 0; `--replay` with no recording exits non-zero, names the owner-gated command, and opens no socket. | 3/3 |
| **T10** | **Lint.** `ruff check` clean on every file this card touches; `scripts/ci_ruff_baseline.json` still `count: 7` with the same 7 fingerprints. | clean, 7 |

## OWNER-GATED rows — need the owner's recording (~10 min) and one hosted session

Listed with their exact commands in `TURN1_STATUS.md`. Pre-registered numbers,
per the card, so the replay cannot be graded after the fact:

| id | row | target |
|---|---|---|
| **G1** | commit p50 (`speech_stopped` → `response.created`) per arm | ≤ 0.6 s |
| **G2** | mid-sentence commits on the chosen prototype arm, over the 20 utterances (each carries one ~400 ms mid-sentence pause) | 0/20 |
| **G3** | scripted barge-in during the replay still fires, with a truncation row present for each | 3/3 |

The prototype default is picked **from G1/G2 across all arms**, not before.

## Seeds RED — one per new guard (card work item 4)

| seed | injected defect | row that must go RED |
|---|---|---|
| **S1** | delete the `silence_duration_ms` 200–800 bound | T3 |
| **S2** | give `prefix_padding_ms` a non-`None` default (300) so an absent key changes the payload | T1 + T2 |
| **S3** | drop `mid_sentence_commits` from the replay tool's report schema | T9 |
| **S4** | never record `first_audio_ms` | T7 |

Each seed: inject, watch the named row fail, restore byte-identically
(`sha256sum` before/after), purge `__pycache__`, re-run green.

## Explicitly not measured by this card

Anything about how the provider actually endpoints. Every number in T1–T10 is
about **the knob**: that it exists, that it validates, that absent keys change
nothing, and that the instrument which will measure the provider works. The
endpointing behaviour itself is G1–G3 and it is owner-gated.
