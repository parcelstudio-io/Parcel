# Task 21 — PG-4: an abstention gate that can say yes (E2-D4 + E2-D5 + AU-C2-1)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence:** C2_STATUS §6 and C3_STATUS §headline — the same structural
fact measured independently twice: `ranking_margin = (top − median) /
(1.4826 × MAD)` is exactly 0.0 whenever MAD = 0.0, which every
evidence-weighted label-primary background produces; C-3: 18/18 learned-map
answers refused `indecisive_ranking` on perfect-geometry data. E2-D5: every
learned_map operating point was fitted on the untextured distribution F2
declared dead. AU-C2-1 (audit refutation): MapEntry's bounded source crop
is dropped by `as_dict()`/`from_mapping`, so re-embedding evidence does not
survive a store reload.

**DISPATCH GATE: OWNER AUTHORIZATION REQUIRED.** This card edits
`perception_abstention.py` (PG-3 internals), MUST NOT TOUCH for every
chain card, and re-derives shipped operating points. It also lands the
AU-C2-1 persistence fix inside online_map's store layer. Nothing here
dispatches until the owner says so.

## Work (proposed; the owner may amend)

1. **Replace the dead fourth signal, don't tune it.** The margin signal is
   architecturally incompatible with label-primary retrieval (the score
   distribution it measures dispersion over no longer exists). The cutover
   research already names the successor: the Qwen3-VL-2B verification veto
   (REVISION §2 of task_13) becomes the fourth signal; navigability,
   detector-label agreement, and evidence remain. `min_ranking_margin`
   retires with a tombstone comment, not a threshold of 0.
2. **Re-derive every operating point on textured renders** (C-3's F2 tail):
   pre-registered per-class thresholds from dev-scene measurement, pinned
   fixtures, and a CI eval (the llmdet lesson: no seat change without a
   pinned-fixture eval).
3. **AU-C2-1 fix:** persist and restore the bounded thumbnail bytes in the
   online_map store (schema bump with migration), with a round-trip test
   that would have caught the drop.
4. **The un-masking decision, measured:** `abstention.enabled` ships false
   today, which is the only reason E2-D4 doesn't bite. This card measures
   the gate end-to-end enabled in shadow (C-3's taxonomy) and reports the
   admission/refusal rates the owner needs to decide when to flip it.
5. Acceptance pre-registered before measurement, including: ≥1 admitted
   verdict reachable from a learned map on perfect-geometry data (the
   exact state that today yields 0/18), and refusal preserved on the
   absent-object set (0/8 admitted stays 0/8).

OWNS: perception_abstention.py, online_map/store.py + entries.py (the
persistence fix only), configs for the new signal, tests, task_21 docs.
MUST NOT TOUCH: frozen evals/, scene digests, the held-out scene, C-3's
semantic_source axis semantics.

## Definition of done

The five acceptance rows measured; seeds RED including a seed that
re-introduces the MAD-zero margin (must be caught by the new tests); gate
green; PG-3's card-level docs updated so the signal roster matches the
shipped code.
