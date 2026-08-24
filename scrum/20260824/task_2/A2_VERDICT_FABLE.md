# A2 NAV-GLUE · acceptance VERDICT (Fable) · 2026-08-24

Verification: my own guard runs — the new `test_a2_navglue.py` + ported pins
+ both DEC ratchets + literal-drift + pose-archon = 111 passed; my own full
`bench.py --stage corpus` re-run reproduced the decision rows exactly
(arm A N1 0.100, 4 stand-off rows; arm B 0.483); the safety hunks read line
by line — `authority.py`/`reactive_safety.py` changes are ADDITIVE
properties restating the commissioned ring in the planner's centre frame
(`+ footprint_radius_m`), each stating "nothing here moves what
`apply_reactive_safety` enforces", and no stop-floor VALUE changed anywhere
in the diff. Product scope = exactly the six OWNS files (+420/−55).

## Disposition: **ACCEPTED — decision SIMPLIFY**, with four rulings

1. **The decision stands and is structural, not marginal.** The ladder's
   `near` stand-off terminal (1.12–1.40 m) lies outside the 0.5 m scoring
   band by construction; no tuning can close that without re-deriving the
   stand-off family. M1 ships arm B's shape (metric point-goal) + typed
   refusal; the semantic ladder returns post-M1.
2. **The 4 N2 rows are reclassified, not excused**: stand-off semantics
   scored against a point metric — each arrived inside its own committed
   band with a fresh detection. The **`near` stand-off family re-derivation
   ("what does 'arrived at the desk' mean")** is a milestone-level design
   decision, flagged to the owner with the M1 nav card.
3. **The shipped shape's true arrival rate is UNMEASURED** — arm B was
   byte-identical by design (harness builds it via `ModelRegistry.create`
   with legacy inflation; the executor said so openly). Acceptance row for
   the M1 nav card: **the shipped configuration (commissioned inflation via
   the two production owners) re-measured on this exact corpus, bar
   ≥ 0.80, before the first physical point-goal session.**
4. **The convention findings go to A4 SPINE** (correct home — the
   snapshot's evidence header): range conventions (body-surface vs
   centre-frame; the BARN adapter publishes RAW ranges) are stamped by the
   observation SOURCE; and the isotropic-planner-vs-directional-gate
   mismatch is DOOR-1 H-2's successor. The barn cached-signature STOP was
   correctly not re-pinned.

Re-freeze audited: the three commissioned inflations moved with recorded
cause; all 9 un-commissioned profiles, `DEFAULT_CLEARANCE_PROFILE`, every
pre-A2 authority property, the literal-drift allowlist, markers and
long-function counts unchanged. Attributed reds accepted: voice_nav
lamppost (pre-existing, bisected with all fixes off), R26 perf pin
(powersave, reproduces standalone). `test_sit_next_to_the_lamppost` is
A2's real cost — the demo city admits 0.885 m, not 1.022 m — priced, not
hidden, and the sensitivity run shows the decision is insensitive to that
choice. Does not prove: anything physical; arm B's harness N4 is
structurally 0; six residual arm-A stalls remain in-budget.
