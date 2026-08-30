# AUDIT · C5 SPEECH-ACTS-1 — verifier: Fable (parcel-0e), 2026-08-29 22:0x EDT

**Disposition: ACCEPT (wave A scope) — with notes.** Second lens: parcel-6c (pending, read-only).

## Re-run by the verifier (through the guard, TMPDIR unset)

| row | executor | verifier |
|---|---|---|
| card test command `tests/test_speech_acts.py tests/test_narration_matcher.py tests/test_realtime_lane*.py -q` | 91 passed | **91 passed in 3.72 s** |
| files touched | 6 named | `git status`: exactly those (whisperer.py's ` M` is C4's concurrent work, not C5's) |
| `noqa` in the four owned files | 0 | **0** (grep) |
| `config.py` line count | 1000 untouched | **1000** |
| `realtime/config.py` additive | +85/−0 | **+85/−0** |
| no research import from `src/` | subprocess proof | no `from/import` of research names in the two modules; the test's subprocess check is the binding proof |
| ruff on the five files | clean | **All checks passed** |
| flag default OFF, malformed values raise | tests | `SpeechActsConfig` at `realtime/config.py:665`; covered by the test file |

Not re-run by me: the arm-T reproduction row's numbers (the test asserts equality with MB-2's `results.json` `arm_T` — 180 / 1.0 / 0.9688 / 0 — and passed in my run, so it is re-run by construction); the pre-edit off-path digest `edaa32ed…` (computed by the executor before its first edit at HEAD 704ba5c; the flag-OFF test re-derives it and passed).

## What the register does well
- Three independent pins on the port (file sha256, regex/vocabulary object-by-object, 180 paired turn verdicts) — the "same matcher" claim cannot drift silently.
- The wave-B install point is exact (`lane.py:1832` `narrate_event(act=…)`, `runtime.py:16630 → :16561 → :16599`) and the KIND→FACT bridge is placed in the whisperer/executive, not in the contract.

## Notes carried to wave B (not defects)
1. `RealtimeConfig.as_dict()` does not render the new block, to avoid re-pinning TURN-1's frozen `/api/state` key-set row (`tests/test_turn1_endpointing.py:302`) — correct for wave A; **wave B adds the row and re-pins with TURN-1's reviewer.**
2. Open design question, flagged not resolved: how the contract's sentence is voiced (a `response.create` that pays the model to re-say a final sentence — the step MB-1 measured at 0.61–0.73 — vs item-only with local TTS). My recommendation for wave B: **item-only + local TTS for terminal facts; never a `response.create` on a fact**. MB-2's evidence constrains the facts, not the voicing.
3. The DEC-0 ratchet rows (`test_no_new_oversized_module` / `test_no_new_long_function`) are red on the owner's dirty diff (`audio/voice_loop.py`, `brain/executive.py`, `bridge/protocol.py`, `control/motion_gateway.py`) — measured by the executor with its modules moved out of the tree; not C5's.

## Second lens (parcel-6c, read-only, 22:1x; `~/.cache/parcel-verify/c5-lens/NOTE.md`) — ACCEPT

- **Faithful port, mechanically diffed** with comments/docstrings stripped: `CLAIM_PATTERNS` (2,710 chars), `HEDGES`, `OFFER`, `INABILITY` and the 14-entry invented-action tuple (1,464 chars) IDENTICAL to MB-1's `scorer.py`; `extract_claims` 0 diff lines; `normalise` / `find_invented_actions` differ only in docstring/comments. `contextlib.suppress(Exception)` at `narration_matcher.py:376` replaces `scorer.py:294-299`'s try/except around the live door read — same boundary. Informational delta: on a door-read FAILURE the scorer wrote `source = "…door read failed (<ExcType>)"` while the matcher leaves the pre-block source, so a failed read reads like "no doors" — a branch MB-1 never took (`runtime=None`); one docstring line to add. `_lexical_flags` deliberately not ported (no `evals/` import in `src`).
- **Inert, yaml-only:** `speech_acts` accepted at `realtime/config.py:104`; default OFF, absent ⇒ OFF, block validated (`:1668-1690`, wired `:1730`); `as_dict` omits it (`:823-830`) so TURN-1's `/api/state` pin stands; NO reader of `SpeechActsConfig` anywhere in `src` — inert by construction; no env/CLI path.
- **Templates cannot claim beyond their slots; slot VALUES can, and only `check()` stops them.** `render()` (`:250`) is a fixed f-string chain and every act with benign slots renders claims ⊆ `LICENSED_CLAIMS[act]` (one dependency: the queued ack renders claim class `queued`, admitted via `_QUEUED_EXTRA` `:605-608`, same as MB-2's `contract.py:391-393` — any vocabulary pin must include that rule). But `goal` is `str(slots["goal"])` with NO sanitisation (`:242-244`) and `ask_clarify`'s `question` is free text — both render verbatim and are caught only by `check()` → REJECT. **The contract's guarantee is render→check as one unit.**

Three acceptance rows carried to the WAVE-B install card (adopted, appended to `C5_SPEECH_ACTS.md`): (a) the product never speaks a `render()` output that has not passed `check()`; (b) `places` at the call site is the learned map's known places, non-empty (an empty sequence silently disables the swapped-destination rule), with a test that a swapped destination is refused; (c) the clarification composer (`voice/amendment.py` `clarification_from_grounding`) must produce claim-free questions, or the refusal fires on legitimate ones — fail-closed but noisy.
