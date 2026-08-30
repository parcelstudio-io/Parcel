# AUDIT · M1 merge (W1 + W4 onto HEAD + W2 + W3 + W6) — verifier: Fable (parcel-0e), 15:0x 08-30

**Disposition: ACCEPT.** Gate worktree `~/.cache/parcel-0e/wb/gate` at `c96ac34`: 43 tracked files +3326/−283 + 44 new files (W1 2, W2 1, W3 1, W4 32, W6 7, M1 1).

| row | executor | verifier |
|---|---|---|
| conflicts | 9, both sides preserved, table in `M1_STATUS.md`; no hunk dropped (every `+` line of the four patches accounted for) | read; the semantic resolution (`_bind_plan_lineage` returns the policy's lineage; `_accept_plan` overrides the door's lineage when the policy answered) matches both cards' contracts and is pinned by the integration test |
| proof | 671 passed / 1 xpassed / 0 failed across 26 files (`test_plan_queue` 74, `test_realtime_speech_act_install` 28 with MB-1 b1 75/75, `test_poi_admission` 27, `test_runtime` 61, `test_arrival_receipt_wiring` 7, DEC-0 8, import ratchet 15, `test_wave_b_integration` 1) | **guarded re-run in the gate worktree (ten files: integration + plan_queue + install + poi + wiring + whisperer wiring + both ratchets + K0 + turn1): 257 passed** |
| expected single red | `tests/test_ci_gate.py:327` `checked == 4` → 5 (sentinels pass) — W5's 4 → 6 bump | accepted |
| merge-created DEC-0 red | `extract_city_semantics` 97 → 103 lines (ceiling 100) → `_object_track` extracted (65 / 53), body verbatim, no baseline edit | ratchet green in my run |
| hygiene | ruff clean on 55 files; 0 `noqa`; `config.py` 1000; `pipeline.py` 7221 (+10 comment only); `runtime.py` 19027 | **ruff All checks passed; noqa added 0; config.py 1000; pipeline.py 7221** |
| integration test | one leading-cue queue admission → exactly one forwarded `plan_accepted` with the QUEUE rendering ("Okay, I'll check bench after that."); parent resume → `resume_offer`/`plan_resumed`, no third ack; KEEP fires nothing; two fixture collisions bridged (W2's fake clock vs the brain's sensor-age contract; `PLAN_ACCEPTED_MIN_GAP_S`) | green in my run |
| process fault disclosed | a measurement script ran `git stash` in pass A (comment called it a no-op), caught within one command, popped, dropped; pass B rebuilt from patches | recorded; nothing survives into the deliverable |
| C9 | five `_narrate_mission_terminal(state="arrived")` test sites now hand over a real receipt + `LegIdentity`; two were red, three silently passed on the failure branch | the right fix under W4's authority rule |

`pipeline.py` +10 (comment-only) is the wave's one departure from "net-negative or leaf" — recorded, not waived: the DEC-0 ratchet keys on new modules/functions and is green.
