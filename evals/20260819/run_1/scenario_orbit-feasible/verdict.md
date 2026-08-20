# scenario_orbit-feasible — **PASS**

**Claim (stated before the run):** "circle around me" with the owner in open
space produces a full orbit in the path record.

## What happened

The owner typed *"Circle around me, please."* into the live hosted session. The
model called **`circle_owner`** — the tool R10 declared to close the
tool-surface hole — with status `ok`, and said:

> "I started a clockwise circle for one normal lap around you."

The body then walked the lap on the real sim.

| Measurement | Value | Source |
| --- | --- | --- |
| Bearing swept around the owner | **−354.7°** (clockwise) | derived from `path.jsonl` |
| Ring radius (min / max over the window) | 1.545 m / 3.124 m | derived |
| Commanded orbit radius | 1.6 m | `events.json` → `spatial_detail` |
| Terminal | `completed` / `orbit_complete` / progress **1.0** | `events.json` |
| Path samples | 560 at 10 Hz | `path.jsonl` |
| Whisperer forwards | 0 (47 `never_band` suppressions) | `whisperer_log.jsonl` |

The 3.124 m maximum radius is the **approach** phase — the base begins the
scenario where the previous one left it and closes to the ring before orbiting;
`path.svg` shows the approach as the run-in and then a clean circle. The 354.7°
rather than a round 360° is the 10 Hz sampler: the controller reports
`progress: 1.0` and stops, and the last few degrees close between two samples.

The direction was the model's choice — the owner said only "circle around me",
and `circle_owner` was called with `direction: clockwise`. That is the model
filling an unspecified argument, not a mismatch.

## Why this is the interesting result

The bench baseline for this exact request was realtime-mini **falsely denying
the ability** ("I can't do a full circle around you") in 2 of 3 trials, because
no orbit tool existed and the model was guessing at its own body
(`bench_navmodel.md` §6/A3). Here the tool exists, the model found it **from the
schema alone** — SI v2 still does not mention `circle_owner` (R10 open risk 5) —
and the geometry validator admitted the orbit rather than refusing it.

Zero whisperer forwards is also the correct answer: an orbit is a spatial
behaviour, not a mission, so it produces no `mission_arrived` terminal. The 47
suppressed rows are all `position` and `proximity_churn` — the base moving in a
circle is exactly the per-tick churn the never band exists to swallow.

## Verdict

**PASS.** A full revolution is in the path record, the controller reports
`orbit_complete` at progress 1.0, and the route from owner sentence to body
motion ran through the shipping tool surface.

**does_not_prove:** that the mid-orbit abort works. Nothing entered the annulus
during the lap, so `_lookahead_feasibility` never had a reason to fire; that arm
is covered by R10 seeds S18/S20 and by scenario_orbit-refused's admission-time
half only.
