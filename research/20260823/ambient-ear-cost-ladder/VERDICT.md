# H1 — the ambient ear and the cost ladder · VERDICT (Fable) · 2026-08-24

Verifier: Fable (parcel-fb), 2026-08-24, solo — the account's weekly limit
stopped subagents at ~00:40. Basis: the executor's RESULTS.md and results/
files, the capability test(s) it added (run through the guard on this tree:
`tests/test_h3_drives.py tests/test_h4_body_intent.py
tests/test_h7_localization_contract.py tests/test_h6_noticing.py` + both DEC
ratchets = 63 passed, 1 skipped), git diff against OWNS, and DESIGN.md
byte-identity with `0ec1d7c`. Rows marked *reported* were read, not re-run;
rows marked *reproduced* were re-run here. Criterion integrity: no bar moved.

| row | criterion | executor | verifier | disposition |
|---|---|---|---|---|
| C1 | P0 $/month reported | mini $24.60 (no ambient speech) → $528 (TV 4 h/d) → $1,536 (12 h/d speech); full $90 → $1,918 → $5,576 | reported; rests on a two-point output-audio calibration (executor's own caveat) | CONFIRMED-WITH-NOTES |
| C2 | ≥ 20× uploaded-minute reduction | 69.3× | reported | CONFIRMED |
| C3 | truncation ≤ 2 % | 0 % at ≥ 500 ms pre-roll | reported | CONFIRMED |
| C4 | endpoint p50 ≤ 0.79 s | 0.520 s | reported | CONFIRMED |
| C5 | false opens ≤ 4/h on TV | 0.0/h on room noise; **960.6/h on attenuated TV speech** | reported | **REFUTED on speech** — a VAD cannot tell the television from the owner; owner-voice identity (`realtime/voice_identity.py`) + engagement triage is the missing gate (unmeasured) |
| C6 | escalation ≤ 15 % | 22.4 % | reported | REFUTED |
| C7 | pairwise delta ≥ −5 | −27.2 (hosted 108 / local 6 / tie 13, both orders) | reported | **REFUTED** — the local 26B is far below hosted mini on these turns |
| C8 | P2 ≤ $200/month | $0.53 (transcript escalation) / $6.87 (audio) mini | reported | CONFIRMED |
| C9 | ledger vs live within 20 % | 0.000 % over 34 responses | reproduced by reading `results/` live rows and the v2 ledger schema (`realtime/spend_ledger.py`, opt-in `rate_card=`) | CONFIRMED |
| C10 | ≤ $2 hosted | $0.0378 itemized (66 responses, session ids) | reproduced from the itemized rows | CONFIRMED |

**Overall: the hypothesis is REFUTED in its ladder form and CONFIRMED in its
economic form.** Two program-shaping findings, both accepted: (1) streamed
silence is NOT billed (19 input audio tokens after 63.8 s and after 3.8 s of
silence) — the "$130/month silence floor" in `research/20260823/README.md`
was wrong; cost is driven by answering; (2) the pre-H1 ledger overcharged by
+336 % and was grounding the dog ~4× early. Product path: `cost.py` /
`spend_ledger.py` are additive and opt-in; `voice/engagement.py` is unwired;
`runtime.py` still builds `SpendLedger` without a rate card — one line in
M1-1 EAR. Design consequence: online = hosted mini as the answerer (it is
cheap and far better), gated by VAD + owner voice identity + in-exchange
triage; local = the OFFLINE floor (H9), not a cost lever.
