# Task 9 — R20: Narnia is not on the map (unknown-place honesty)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** live_run_1 scoring (d): "Go to Narnia" and "Take me to the moon"
became REAL missions — "I'll go wait near narnia safely", 4.25 s and 10.7 s
of rotate-scan — while "let's go back home" correctly got the ask. R10's
place validation catches junk-ARGUMENT shapes ("with owner") but an unknown
noun sails into the semantic-search path, which happily scans for a place
that cannot exist. The ask/refusal path exists; the unknown-place class
never reaches it.
**DISPATCH GATE: after R18 closes.**

## Work

1. Root-cause the admission path: where does an unresolvable place name
   fork between "ask the owner" (home) and "scan for it" (narnia)? Likely
   the known-place list vs open semantic search.
2. Policy (deterministic, local): a place that matches neither the semantic
   map, the place graph, nor a taught name ⇒ the structured
   ask/refusal with nearest real alternatives ("I don't know a narnia —
   nearest I know are the coffee shop and the bench"), narrated. Open-ended
   search stays available EXPLICITLY ("look for a mailbox") — the card is
   about goal admission, not banning exploration; document the boundary.
3. Corpus queries 10–12 flip to expected-PASS and join the offline
   regression suite with a fake resolver.
4. Live proof: Narnia refused with alternatives; a real place still admits;
   an explicit search phrasing still searches.

OWNS: the admission-path fork (navigation/goals or router glue — map exact
files in the doc first), `runtime.py` glue, tests, `R20_STATUS.md`.
MUST NOT TOUCH: lane/broker/protocol/ingress, prompting, yield, arrival
semantics table (R10's classes stand). DoD: gate green; ≥6 seeds RED
(unknown place scans again; known place refused — the over-correction;
alternatives dropped; explicit-search phrasing blocked); live proof;
standard register.
