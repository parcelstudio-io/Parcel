# Card Y-4 — `pedestrian_group` infeasibility record + owner band-decision memo

**Docs only.** No code, no thresholds, no configs. Written 2026-08-11 (task_1,
Wave 3) against the design record `FOLLOWUP_DESIGNS.md` §4 and Appendix A.
Every number below is either re-measured here (marked **re-run**) or quoted
from a named prior lane with its file:line.

The one thing this memo asks the owner for: a decision on
`safety.person_slow_m` (§4). Nothing in this batch decides it, and the
`pedestrian_group >= 0.75` threshold stays honestly red until it is decided.

---

## 0. TL;DR

* `pedestrian_group` cannot reach `min_band_fraction >= 0.75` under the
  owner-authorized 2.5 m stranger band. Holding band pace needs **2.24 m** of
  stranger surface clearance; that corridor offers about **1.7 m**. This is a
  derivation from the shipped ramp, not a bench observation.
* The lateral-yield **oracle ceiling is 0.604** (**re-run**; the design record
  quoted 0.616 — see §3.2 for the discrepancy and its attribution). Either
  number is far below 0.75.
* The claim is now also **confirmed positively**: a new control cell,
  `pedestrian_group_wide` — the same controller, the same group, flankers
  pulled apart to a 5.0 m gap so the robot's clearance is ~2.3 m — measures
  **band 1.0000** with the yield flag off (**re-run**, card Y-3). Band pace is
  reachable exactly when the geometry pays the derived 2.24 m.
* The only lever that moves this is `person_slow_m`, and E5 measured its price
  in both directions. That is an owner decision (§4).

---

## 1. What `pedestrian_group` actually does (premise correction)

The topic brief this work started from described a robot stopping in a group's
path. That is a different episode (E6 §4.3's `pedestrian_cut_in`). The measured
behaviour of `pedestrian_group`, re-run today against the committed tree
(`dd2e857`) with the archived `evidence/trace_group.py`:

| quantity | measured (re-run) | design record §4.1 |
|---|---|---|
| band fraction | **0.5840** | 0.584 ✓ |
| steps above the 3.0 m band edge | **104 / 250** | 104 ✓ |
| `proximity_state` histogram | **223 slowing, 27 clear, 0 stopped** | 223/250 slowing, 0 stops ✓ |
| minimum pedestrian surface | **1.4336 m** | 1.43 ✓ |
| controller states | 238 following, 12 holding | — |
| final robot x | **3.30 m** | 2.74 ✗ (see below) |

The robot **never stops** (zero gate stops), **never gets closer than 1.43 m**
to a pedestrian, and **never reaches the group** (ends at x = 3.30 m; the group
sits at x ≈ 4.0–5.2 m). It LAGS. Two multiplicative throttles do it:

1. **The owner's own people-list entry under the 2.5 m stranger band.** The
   two-body interlock is denied for the whole 25 s because three near-stationary
   flankers sit on the person channel, so the owner is banded as a stranger and
   the chase equilibrates at 2.77 m owner distance
   (vx 0.275 = 0.35 x 0.78, and (2.77 − 0.55 − 1.2)/1.3 = 0.785 exactly).
2. **The stranger ramp at the 3.4 m flanker gap.** Pinch clearance 1.5–1.7 m
   gives scale 0.19–0.38, cutting vx to 0.05–0.13 m/s for about ten seconds —
   which is where the 104 above-band steps come from.

**Correction to the record:** §4.1 says "ends x=2.74"; the re-run measures
**3.30**. Every other number in that paragraph reproduces exactly, on both the
committed tree and the Wave-1/Wave-2 working tree, so the trace itself is
sound; 2.74 does not reproduce and should not be cited.

---

## 2. The derived bound (why 0.75 is unreachable here)

The reactive gate's stranger ramp is linear between the stop ring and the
comfort band (`reactive_safety.py`, values from `configs/robot.yaml` via
`SafetyEnvelope`):

```
scale(clearance) = (clearance - person_stop_m) / (person_slow_m - person_stop_m)
                 = (clearance - 1.2) / 1.3
```

Band membership requires keeping up with an owner walking at ~0.28–0.30 m/s
against a controller capped at `max_vx` 0.35 m/s — i.e. a sustained speed scale
of about 0.8. Inverting the ramp:

```
scale >= 0.8  <=>  clearance >= 1.2 + 0.8 x 1.3 = 2.24 m
```

The `pedestrian_group` corridor offers **1.5–1.7 m** of surface clearance at
the flanker pinch (measured minimum over the episode: 1.4336 m). No lateral aim
offset changes the corridor's width, so no aim policy recovers band pace there.
The bound is arithmetic on the shipped ramp; it does not depend on the oracle.

**Positive control (new, card Y-3):** `pedestrian_group_wide` places the same
three-flanker geometry with a 5.0 m gap, giving the robot ~2.3 m of surface
clearance — just over the derived 2.24 m. Flag off, it measures **band 1.0000,
minimum pedestrian surface 2.0206 m, zero gate stops, zero collisions**. The
same controller that cannot hold 0.75 at 1.7 m holds 1.00 at 2.3 m. That is the
derivation confirmed from the other side.

---

## 3. The oracle upper bound

### 3.1 What the oracle is

`evidence/oracle_yield.py` (archived from Appendix A.2) emulates "the follow
controller aims at a laterally shifted lane" by giving `follow.step()` an
observation whose OWNER point is shifted perpendicular to travel, while the
dispatch gate, TTC, metrics and world all see the TRUE observation. It is an
upper bound on lateral yielding, not a shipped mechanism.

### 3.2 Re-run against the committed tree (`dd2e857`)

| cell | band (re-run) | band (design record) | min pedestrian surface (re-run) |
|---|---|---|---|
| `pedestrian_group` shift +0.00 | **0.5840** | 0.584 ✓ | 1.4336 |
| `pedestrian_group` shift +0.20 | **0.5720** | 0.568 ✗ | 1.5658 |
| `pedestrian_group` shift +0.40 | **0.5600** | 0.552 ✗ | 1.5168 |
| `pedestrian_group` shift +0.60 | **0.5440** | 0.540 ✗ | 1.4741 |
| `pedestrian_group` shift −0.30 | **0.6040** | 0.616 ✗ | 1.5286 |
| `pedestrian_cut_in` shift +0.00 | **0.5250** | 0.525 ✓ | 1.4074 |
| `pedestrian_cut_in` shift +0.40 | **0.5250** | 0.530 ✗ | 1.4309 |
| `pedestrian_cut_in` shift −0.40 | **0.5150** | 0.515 ✓ | 1.3850 |

**Reproduction verdict: PARTIAL — 3 of 8 cells reproduce exactly, 5 do not.**
This is reported as a miss, not smoothed over. What is established about it:

* The re-run is **deterministic**: identical to 4 decimal places whether the
  eight cells run in one process (as the archived script does) or one cell per
  fresh process, and identical on the committed tree `dd2e857` and on the
  Wave-1/Wave-2 working tree. So the Wave-1/2 landings did not move these cells
  either — an incidental flag-off identity datum for `pedestrian_group`.
* The differences are 1–3 steps out of 250 (±0.004 to ±0.012), i.e. the
  designer's scratch copy differed from `dd2e857` by something small. The
  original scratch tree that produced the recorded table is gone; what remains
  at that path is a copy of the current working tree, which reproduces the
  re-run numbers, not the recorded ones.
* **Every conclusion the record drew from the table survives**: positive shifts
  REGRESS the band (0.5720 / 0.5600 / 0.5440 all below 0.5840); the best cell is
  the negative shift; `pedestrian_cut_in` moves by at most 0.005. The re-run
  ceiling (**0.6040**) is LOWER than the recorded one (0.616), so the
  infeasibility argument is strengthened, not weakened, by the correction.

`does_not_prove`: the oracle emulates an owner-point shift, not the aim
rotation card Y-1 shipped; it is evidence about the SIGN and MAGNITUDE of
lateral yielding on this geometry, not about the shipped proposer.

---

## 4. The owner decision — `person_slow_m` (E5 §4.4), with its measured price

The only quantity that moves `pedestrian_group` is the stranger comfort band
itself. E5 measured its two-sided price on FOLLOW_BENCH_V1 (E5_PERSON_CLEARANCE_STATUS.md §4.4,
9-cell factorial with floors monkeypatched off in a scratch harness):

| cell | `person_stop_m` | `person_slow_m` | `follow_success` | `mean_band_fraction` | `min_pedestrian_surface_m` | dwell |
|---|---|---|---|---|---|---|
| A baseline (all old) | 1.0 | 2.0 | **9/9** | 0.74315 | 0.3566 | 3.8 |
| G stop+keepout only | 1.2 | 2.0 | **9/9** | 0.73580 | 0.3824 | 3.8 |
| E slow band only | 1.0 | **2.5** | **6/9** | 0.64901 | **0.5300** | **2.3** |
| B SHIPPED | 1.2 | **2.5** | **6/9** | 0.63986 | **0.5300** | **2.3** |

E5's reading, quoted verbatim from that lane: "**`person_slow_m` 2.0 -> 2.5 is
the whole story, in both directions.** It is the only quantity whose presence
flips 9/9 -> 6/9 (cell E, with everything else at the old values), and it is
the only quantity that moves `min_pedestrian_surface_m` 0.3566 -> 0.5300 and
the dwell 3.8 -> 2.3."

E6 then swept the OWNER-side band (the relaxation the owner gets inside the
stranger band) with the two-body interlock off — the most favourable case —
and `pedestrian_group` failed in **every** cell (E6_OWNER_BAND_STATUS.md §4.2):

| cell | owner band | `follow_success` | `mean_band_fraction` | `min_pedestrian_surface_m` | dwell | `pedestrian_group` |
|---|---|---|---|---|---|---|
| none (= E5 control) | 2.50 | 6/9 | 0.63986 | **0.5300** | 2.3 | 0.584 ✗ |
| n1.75 | 1.75 | 8/9 | 0.74136 | 0.2182 | 4.0 | 0.652 ✗ |
| derived | 1.30 | 8/9 | 0.74583 | 0.1794 | 4.1 | 0.652 ✗ |
| range interlock | 1.30 | 7/9 | 0.72974 | 0.2810 | 3.9 | 0.588 ✗ |
| SHIPPED (two-body interlock) | 1.30 | **7/9** | 0.70878 | **0.5300** | **2.3** | 0.584 ✗ |

So the owner's options, priced:

| option | `pedestrian_group` | what it costs | what it buys |
|---|---|---|---|
| **1. Leave `person_slow_m` at 2.5 and retire the 0.75 threshold for this cell** (recommended) | stays 0.584, threshold marked unreachable-by-derivation | one honest red row becomes an honest documented limit | keeps `min_pedestrian_surface_m` 0.5300 and dwell 2.3 s — the clearance E5 bought |
| **2. Lower `person_slow_m` towards 2.0** | ~0.75 becomes reachable only if clearance reaches 2.24 m; at 2.0 the ramp needs 1.0 + 0.8 x 1.0 = 1.8 m, which this corridor's 1.5–1.7 m still misses | sells back exactly what E5 bought: surface 0.5300 -> 0.3566, dwell 2.3 -> 3.8 s, and moves every frozen FOLLOW_BENCH_V1 row | `follow_success` 6/9 -> 9/9 |
| **3. Relax the OWNER band instead (E6's lever)** | 0.584 -> at best 0.652, still ✗ | interlock-off cells sell 0.5300 -> 0.1794 of stranger clearance (E6 guardrail 2) | 7/9 -> 8/9 |
| **4. Change the scenario, not the constant** | `pedestrian_group_wide` (new, Y-3) measures 1.0000 at 2.3 m of clearance | a new eval cell; the old cell stays red | proves the controller is fine and the corridor is the constraint |
| **5. Yield-aside as a band mechanism** | REFUTED by measurement, card Y-3: the rotated-aim proposer is inadmissible inside the band and regresses `pedestrian_group_wide` 1.0000 -> 0.5240 when it engages | — | — |

**Nothing here is decided.** Options 2 and 3 move frozen rows and sell measured
pedestrian clearance; both are owner calls under §8 open question 2.

### 4.1 The residual only the owner's band decision can move

Even with a perfect aim policy, the OWNER's own people-list entry under the
2.5 m stranger band throttles the chase to a 2.77 m equilibrium whenever any
stranger is perceived (§1, mechanism 1). That term is not a controller defect
and no proposer can route around it: it is the price of treating the owner as a
person while a stranger is on the channel. It is named here as the residual.

---

## 5. Reproduction

Archived verbatim from `FOLLOWUP_DESIGNS.md` Appendix A into `evidence/`
(adjudication #21 — the session-scratch originals do not survive GC). The
extracted copies were checked byte-for-byte against those originals while they
still existed: all three match.

| artifact | what it is |
|---|---|
| `evidence/trace_group.py` | `pedestrian_group` step-trace diagnostic (§1) |
| `evidence/oracle_yield.py` | lateral yield-aside oracle upper bound (§3) |
| `evidence/minival_isolation.txt` | 25-episode isolation minival, `person_stop_m` restored to 1.0 (the D-15 counterfactual arm; cited by D15_ATTRIBUTION.md) |

Both scripts carry their original session-scratch `sys.path` inserts and config
path. To re-run, repoint the two `sys.path.insert` lines and the
`FollowBenchRunner(...)` config argument at the tree under test; nothing else
changes. Both were re-run that way for §1 and §3 (scratch rsync of the tree,
main venv by absolute path, no ledger writes).

**One deliberate deviation from verbatim**, stated so nobody has to discover it:
each archived `.py` carries a four-line `# ruff: noqa` banner at the top. The
repo lint gate is a hard CI gate and these scratch diagnostics do not satisfy
it (unused imports, import order), so the banner exempts them rather than
"fixing" an artifact whose value is that it is exactly what was run. Everything
below the banner is byte-identical to the original — asserted, not assumed:
both bodies and `minival_isolation.txt` were compared byte-for-byte against the
session-scratch originals while those still existed, and all three matched.

---

## 6. `does_not_prove`

* Nothing here is a claim about **real pedestrians**: the bench's pedestrians
  are scripted capsules that never yield, never react, and are injected into
  `dynamic_agents` telemetry rather than perceived.
* Nothing here is a claim about a **real robot**: headless kinematic base,
  oracle owner track, raycast LiDAR with modeled noise, no curbs or drops.
* The oracle's **emulation fidelity** is not established: shifting the owner
  point is not the same operation as rotating the aim, and 5 of its 8 cells did
  not reproduce the recorded table (§3.2). No shipped gate depends on it.
* The 2.24 m bound assumes the **sustained** speed scale needed to hold band
  pace is ~0.8. It is derived from `max_vx` 0.35 against a 0.28–0.30 m/s owner;
  a burstier controller could in principle hold the band at a lower mean scale.
  That controller does not exist and is not proposed here.
* `pedestrian_group_wide` is a **new cell measured once**, in the additive
  yield tier's own results namespace. It is not a frozen row and nothing pins
  it.
