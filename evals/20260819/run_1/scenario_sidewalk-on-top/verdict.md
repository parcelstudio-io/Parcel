# scenario_sidewalk-on-top — **PASS**

**Claim (stated before the run):** "go to the sidewalk" terminates with the base
INSIDE the region polygon; `path.svg` shows the track ending on the region.

## What happened

The owner typed *"Go to the sidewalk."* into the live hosted session. The model
called `navigate_to` (`transcript.json` → `broker_calls[0]`, status `ok`); the
mission ran on the real sim and ended `arrived` / `arrived_verified`.

| Measurement | Value | Source |
| --- | --- | --- |
| Final base pose | `(1.3881, 2.5235)` | `events.json` → `measurements.final_xy` |
| `sidewalk` centre inside | **true** | `evals/nav_instruct/scene_truth.json` |
| `sidewalk` footprint (0.32 m) inside | **true** | same |
| `crosswalk` / `sidewalk_south` | false / false | same |
| Nav terminal | `arrived` / `arrived_verified` | `events.json` |
| Path samples | 252 at 10 Hz | `path.jsonl` |
| Max base speed from path deltas | 0.80 m/s | derived |

Containment is scored against `scene_truth.json`, the **generated geometry
table** — not `observation.semantic_regions`. R10 §5.1 records why: a robot
standing on a sidewalk usually cannot see the whole polygon, so a frustum-based
containment check returns an empty list, and an empty list is not a pass, it is
a measurement that proves nothing.

## The narration, and what the model did with it

One whisperer row forwarded, rule `critical_bypass` (a mission terminal is a
critical always-band fact):

> The robot's navigation system reports: You are now standing inside sidewalk.

The model relayed it without embellishment: *"It came back and said it's now
standing on the sidewalk."* The other 13 decision rows are all `never_band`
suppressions (`position`, `nav_tick`, `proximity_churn`) — the telemetry the
owner never hears about.

Note the arrival sentence carries **no ask-hint**: `region` is an `inside`
terminal, and the arrival table only composes an ask for the portal class. That
is the table behaving as specified, not a missing hint.

## Verdict

**PASS.** Both halves of the claim hold: the terminal is inside the polygon by
centre AND by footprint against scene truth, and `path.svg` shows the base track
ending on the `sidewalk` region with the heading spurs pointing into it.

**does_not_prove:** that a region goal is reachable when the straight
robot→point segment is occluded by a pedestrian — the live failure R10 §1
root-caused. No pedestrian stood between the robot and the sidewalk in this run,
so the in-region resampler was very likely never reached. That third tier is
pinned by unit tests (R10 S2–S5) and remains unexercised end-to-end here.
