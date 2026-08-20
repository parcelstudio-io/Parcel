# Task 10 — R21: safety events don't evaporate

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Trigger:** live_run_1 scoring (a): the auditor could not PROVE which
utterance latched the emergency stop because the latch event itself was
EVICTED from the 100-deep event ring within 14 seconds — the exact failure
class R4L fixed for mission terminals, now shown for safety events, which
are strictly more important. Attribution rested on four inferences; an
accidental Space-latch could not be excluded from the artifacts.
**DISPATCH GATE: after R20 closes.**

## Work

1. **A safety log ring** (mission_log's proven pattern): every emergency
   latch (with SOURCE: spoken phrase verbatim / Space / panel button /
   API), every release, every motion-rejected-under-latch (coalesced), in
   the snapshot, eviction-proof, panel-rendered next to the mission log.
2. **Latch visibility while latched:** live_run_1 showed 84+ seconds of the
   owner commanding a latched robot unaware. Alongside R19's rejection
   narration: the panel banner already exists (R9) — verify it actually
   renders during audio-mode sessions and add the latched state to the
   whisperer's StateDigest so a status question while latched ALWAYS says
   so ("I'm emergency-stopped — release me first").
3. **Pin the substring property** the scoring flagged: "die stop" latches
   at ANY position in an utterance (eight words deep, proven live) — a
   deliberate property; make it a test so nobody "fixes" it into an
   anchored match.
4. Live proof: spoken latch → safety ring shows source verbatim; status
   question answered with the latched fact; release logged; a Space latch
   distinguishable from a spoken one in the ring.

OWNS: `runtime.py` (safety ring + digest field), `ui/index.html` (render +
audio-mode banner verification), `realtime/whisperer.py` (digest field),
`realtime/ingress.py` ONLY to attach the verbatim phrase to the latch it
already fires (no matcher changes — q34 "Dye. Stop." remains untested and
the widening remains owner-gated), tests, `R21_STATUS.md`.
MUST NOT TOUCH: the matcher's phrase set, lane/protocol/broker, prompting,
yield. DoD: gate green; ≥6 seeds RED (safety ring evicted/1-slot; source
dropped; digest field removed; status-under-latch silent; substring match
anchored); live proof; standard register.
