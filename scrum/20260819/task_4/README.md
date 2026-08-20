# Task 4 — R11: the situational whisperer (REVISED 2026-08-20, evidence-backed)

**Date:** 2026-08-19, REVISED 2026-08-20 after the research+bench wave
· **Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence (read BEFORE the card, both reports):**
`<scratchpad>/csbench/reports/bench_whisperer.md` (policy A/B/C/D shootout,
gold-labeled stream, downstream naturalness judging) and
`<scratchpad>/csbench/reports/bench_navmodel.md` (state-injection behavior of
the actual hosted models). Scratchpad root:
`/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/799cb356-4cb4-445b-a784-306b6c6fd4a6/scratchpad`

**What the evidence changed (owner informed):** the drafted Gemma judge band
LOST the A/B test — deterministic debounce (policy B2) caught 11/12 gold
facts with 0 spam vs the judge's 8-10/12 with worse latency and
non-deterministic run-to-run behavior; judge-everything delayed an e-stop
forward by 9.8 s. **v1 ships with NO LLM in the forwarding path.** The local
model's surviving role is off-hot-path phrasing at most, behind a config
seam, default off. Every fact below cites the bench that demands it.

## Design (binding)

1. **Two bands + debounce (B2's shape).** Always-forward: safety facts,
   mission terminals, refusals, arrivals — instantly, no gate may delay them
   (C's 9.8 s e-stop delay is the disqualifying counterexample). Never-
   forward: per-tick telemetry, position/error values, proximity churn —
   unconditionally (realtime-mini babbled about injected nav state 4/4 when
   forced to respond; the only defense is that it never arrives).
2. **Three deterministic middle-band mechanisms** (replacing the judge):
   block-entry debounce ≥8 s; a block-clear forwards ONLY if its block was
   forwarded; upstream-computed semantic classes (e.g. `pace_mismatch`,
   `owner_pace_change`) emitted by the StateDigest differ so no downstream
   component ever parses raw notes. Terminal-like events (reroute,
   mission_clear) are EXEMPT from the min-gap — the shared min-gap bug
   (bench: G3 missed by both deterministic arms) must be fixed, not shipped.
3. **Hard caps and dedup OUTSIDE all bands** (unchanged from draft): per-
   minute forward budget, dedup window. Assume forward ⇒ utterance — the
   bench showed the mini speaks on ~every injected item, so the cap IS the
   politeness control.
4. **Forwarded items carry speech-act hints.** Fact-only injections produced
   inert telegram relays and 0/12 of the owner-required follow-up questions;
   with the fact, compose the intent: "…ask the owner whether to drop to a
   walk", "…tell the owner the battery figure and suggest heading back".
   Deterministic templates per class — no LLM required for v1.
5. **State injections must never start motion** (bench C1: a telemetry
   injection triggered spurious `navigate_to("picnic spot by the big oak")`
   in 2/3 forced-response trials — utterance-scoped dedup does NOT catch
   this). The lane tags responses it initiates from system items
   (`narrate_event` provenance); the broker REFUSES motion-class tools
   (navigate/pose/gesture) in system-initiated responses with a structured
   refusal. Only owner utterances may start motion. `lane.py` and
   `tool_broker.py` are OPENED NARROWLY for exactly this tag-and-refuse
   gate (R8/R9 will have closed before this card runs).
6. **StateDigest + decision log (unchanged from draft):** versioned
   dataclass, injectable clock, digest-diff defines delta; every forward AND
   every suppression logged with the rule that fired — the auditability
   requirement survives the judge's removal (and improves: rules are
   deterministic, so "why did the dog say that" always has an exact answer).
7. **Run-with-me:** `pace_intent` on follow; owner-pace watcher emits
   `pace_mismatch` (sustained window) as an always-band fact WITH the
   ask-hint. Honesty guard from the bench (the model claimed "I'm matching
   your slower pace" while state said RUN): the forwarded item states the
   CURRENT gait explicitly so the model has no room to confabulate the
   adaptation. Follow safety caps never raised by any of this.

8. **Owner cost knob (binding config surface, owner directive 2026-08-20).**
   The owner must be able to control the frequency of ALL non-owner-initiated
   hosted-model queries (every whisperer forward triggers a billed response;
   voice-command traffic is excluded). In the owner's realtime yaml:

   ```yaml
   whisperer:
     enabled: true                # false = no state updates at all;
                                  # voice-command traffic unaffected
     max_updates_per_minute: 2    # THE knob: hard cap on billed
                                  # non-voice queries; excess folds into
                                  # the next forwarded item as "+N more"
     min_gap_s: 15                # spacing inside the budget
                                  # (terminal-like events exempt, per the
                                  # bench's min-gap bug)
   ```

   CRITICAL always-band facts bypass the cap — emergency latch, a refusal
   of the owner's own command, a mission terminal — because delaying them
   failed the bench disqualifyingly and each costs tenths of a cent at
   observed rates; everything else queues and folds under the budget. The
   snapshot must expose `updates_this_minute`, `folded`, and the active
   knob values so the panel shows what the knob suppressed; fail-closed on
   malformed config exactly like the rest of the realtime yaml.

## OWNS / MUST NOT TOUCH

OWNS: new whisperer module, `runtime.py` wiring, config surface,
`lane.py` + `tool_broker.py` ONLY for the system-initiated-response
tag-and-refuse gate (design point 5 — smallest possible touch, seeded both
directions), tests, `scrum/20260819/task_4/R11_STATUS.md`.
MUST NOT TOUCH: `protocol.py`, `ingress.py`, `prompting.py`, `agent.py`,
`configs/robot.yaml`, `evals/**`, yield/person-stop policy, follow safety
caps, owner's processes. Never commit/stage/stash.

## Definition of done

Full `ci_gate --tier commit` green; ≥12 seeds RED/restored (must include:
always band gated/delayed; never band leaks; debounce removed (spam);
clear-without-forwarded-block forwards; min-gap swallows a reroute; caps
removed; dedup removed; decision log stops recording; ask-hint dropped from
pace_mismatch; system-initiated response allowed to navigate; the honesty
guard (current-gait line) removed; pace watcher raises a speed cap). Live
proof: the bench's B2 discipline reproduced on the REAL stack — a blocked
mission forwards once with debounce, telemetry forwards zero over 3+ min,
run-with-me produces the model actually ASKING about walking (transcript),
and a system-initiated response attempting motion is refused (forced test).
Costs pasted (<$1.50). R11_STATUS.md standard register + a "what the bench
predicted vs what the live stack did" section — the design is now a
falsifiable claim; treat divergence as a finding, not an embarrassment.
