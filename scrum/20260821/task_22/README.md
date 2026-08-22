# Task 22 — RT-1: the decoys get a home (E2-D1)

**Executor:** Claude Opus (agent) · **Auditor:** Fable
**Evidence:** E2_STATUS §4 E2-D1; task_14 REVISION §3 (the red-team cells
E-2 is bound to score); cutover_research SYNTHESIS §7 (posters pass all
four current signals; AgentPoison/CHAI threat models); the incident
restoration removed C-2's uncertified decoy blocks from `city_block.xml`.

**DISPATCH GATE: owner chooses the venue first.** Two designs are carded;
the second moves an owner-authorized frozen digest, so the choice is not
the executor's.

* **Option A (recommended): a derived variant scene.** New file
  `city_block_redteam.xml` = the certified dev scene + the two decoys
  (person poster, place-name decal), plus its own assets with PROVENANCE
  entries. The frozen `city_block.xml` digest never moves; no re-pin; the
  embodied eval never sees the variant. E-2's red-team cells and C-2's map
  hygiene defenses run against the variant. Cost: the decoys are not
  present during ordinary dev-scene runs.
* **Option B: decoys in `city_block.xml` + R14-protocol re-pin.** Decoys
  become part of the everyday world (more realistic exposure), at the cost
  of a third re-pin this week, executed in the protocol's order (behaviour
  measured on a scratch manifest FIRST), with the owner's explicit
  authorization recorded verbatim.

## Work (either option)

1. Author the decoy assets honestly: a person-poster texture (flat, photo
   of a person) and a scene-text decal naming a place class, sized/placed
   per C-2's reverted design (REFERENCE ONLY — re-derive, re-test);
   `vis_*`-safe (contype=0 conaffinity=0 density=0), physics
   byte-equivalence measured the W-1 way.
2. PROVENANCE.json entries with derivations; asset-integrity tests extend.
3. The two scored defenses actually fire: depth-planarity rejects the
   poster as a person-place candidate; the decal does not forge a place
   admission. Both verdicts with frames, both as pinned regression tests.
4. Pre-registered acceptance, seeds RED (including "poster admitted" as a
   seeded defect), deviations declared, gate green.

OWNS: the variant scene (or the dev scene under Option B with the re-pin
chain), its assets + PROVENANCE, tests, task_22 docs. MUST NOT TOUCH: the
held-out scene, online_map internals, PG-3.

## Definition of done

Decoys exist with provenance; both defenses measured firing; E-2's
REVISION §3 cells become runnable (named in the doc); gate green; register
standard.
