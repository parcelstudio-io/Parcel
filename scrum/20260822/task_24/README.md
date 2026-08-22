# Task 24 — CURIO-1: the dog talks about what it sees

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** `PLAN_ASSESSMENT_FABLE.md` Phase 4
("sometimes starts talking"): P2-B gives owner-presence initiative
(`owner_appeared / owner_returned / greeting_due / question_of_the_day`) but
the whisperer's `KIND_*` vocabulary has mission/owner/battery/pace kinds and
**zero** perception or map kinds (`realtime/whisperer.py:140-260`); the
design study §D names the plug-in points (`Whisperer.offer` via
`runtime._whisper`, band tables + `HINTS` at `whisperer.py:380-428`, the 1 Hz
`_step_owner_events`).

## Why
A living dog remarks on the world. Today the dog can greet you and ask one
question a day; it cannot say "there's a new plant by the window" — the
learned map (P1-B) and the ASK outcome (P1-D) produce exactly those facts
and nothing narrates them.

## Work
1. **Kinds and bands:** `place_learned`, `novel_object`, `scene_change`,
   `ask_about` as MIDDLE-band whisperer kinds fed from P1-B's writer
   (`online_map.known_places()`, promotion events) and P1-D's ASK outcome;
   only names the NM-1 agreement gate has admitted (never a `vlm_proposed`
   name) — a hallucinated place is a seeded RED. HINT: "mention one thing
   you noticed, one sentence, no status, no sensors."
2. **Cadence:** a `ChatterScheduler` (Poisson gaps, mean 4–8 min, quiet ≥ 90 s,
   owner present, never while a turn is owed or playing — every utterance
   passes the existing no-overlap rule in `lane.narrate`), time-of-day bands
   using the `day_key` pattern, `owner_left` farewell as the falling edge of
   P2-B's watcher. Within P0-B's cap (6/min) and `min_gap_s`.
3. **Non-billed initiative:** a yip/whine sound effect or a `play_gesture`
   through `proactive_motion_tools` as the free, instant variant when the
   cap is spent.
4. **Pre-register:** in a 120 s sim roam with the lane on (ROAM-1's runs,
   or MOVE-1's harness until it lands): **3–6 unprompted utterances**, every
   one naming a label present in `known_places()` at utterance time
   (**0 hallucinated**), **0 utterances while the owner is speaking**, cost
   ≤ $0.10/run (08-20 baseline: $0.274 / 44 turns).
5. Seeds RED: narration of a label not in the map; narration mid-owner-turn;
   the cap exceeded.

OWNS: `src/parcel_robot/realtime/whisperer.py` NEW kinds/bands/HINTS (P2-B's
owner-event bands are closed — re-read first), `runtime.py` `_step_whisperer`
feed (one marked region), `realtime/config.py` `whisperer.curiosity` keys,
`configs/realtime.prototype.yaml.example`, `tests/test_curio1_*.py`,
`task_24/` docs. MUST NOT TOUCH: `online_map/` (consume the public API),
`vlm_veto/`, the broker (ROAM-1), `lane.py`.

## Definition of done
Pre-registered rows measured; seeds RED; one owner "taste" row listed
(scoresheet ≥ 4/5 over a week of felt sessions) as OWNER-GATED;
`CURIO1_STATUS.md`.
