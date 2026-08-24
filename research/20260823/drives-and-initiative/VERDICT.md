# H3 — drives and initiative · VERDICT (Fable) · 2026-08-24

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
| D1 | 3–8 initiations/h (radius-6) | 5, 5, 6 (look 8, go_check 4, remark 4; approach 0 admitted) | reported | CONFIRMED |
| D2 | admitted ≥ 0.80 | 73/81 = 0.90; the 8 refusals all `approach_no_skill_contract` | reported — the refusal is a missing APPROACH skill contract, not the gates fighting the proposer | CONFIRMED-WITH-NOTES |
| D3 | max radius ≥ 6 m | 7.16 / 1.24 / 6.01 m (2 of 3 seeds) | reported | CONFIRMED-WITH-NOTES (one seed never left; report per seed in the design) |
| D4 | 0 contacts; clearance ≥ stop distance | 1,222 contact episodes, 1,213 with the dog STATIONARY; baseline (never moves) has 0 contacts but min clearance 0.74 m | executor's mechanism F6 read and accepted: an initiated errand has no return leg — the dog stops inside a pedestrian route and `DynamicCity` agents do not avoid it | **REFUTED — with a named mechanism**: (i) initiated legs need a terminal (come home / stand aside); (ii) the `_toward` gate (±1.15 rad) misses a person closing from the side (the other 9); (iii) the venue's agents walk through a standing dog, so clearance-while-stationary is a venue property, not a policy failure |
| D5 | preemption ≤ 1 tick | 22 events, max 0 ticks, command exactly (0,0,0) | reported; `test_h3_drives.py` covers the quiet-window refusal and radius-0 | CONFIRMED |
| D6 | 0 in quiet/night | 0 and 0 (138k withheld ticks) | reported | CONFIRMED |
| D7 | radius-0 byte-identical motion | translation streams sha-identical across six runs | reported | CONFIRMED (note: today's idle dog emits 36,000 exact zeros — H4's HOLD replaces that) |
| D8 | attribution 100 % | 73/73 with decision-time features | reported | CONFIRMED |

**Overall: CONFIRMED-WITH-NOTES; D4 REFUTED with mechanism.** Product path:
`attention/drives.py` is constructed by nothing in `src/` (harness-only);
the ROAM-2 H2 fix in `patrol/coverage.py` is behind a default-preserving
flag. The design may rely on: drives produce a bounded, attributable, quiet-
and night-respecting initiative economy that yields inside a tick; it must
add a return/stand-aside terminal to every initiated leg and a side-closing
person gate before any self-initiated travel is enabled on a body.
