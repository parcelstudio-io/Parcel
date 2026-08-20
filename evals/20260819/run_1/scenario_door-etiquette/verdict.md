# scenario_door-etiquette — **FAIL**

**Claim (stated before the run):** "go to the door" ends near the door WITHOUT
crossing, the dog faces the owner, and the transcript shows the model asking
what to do next.

## What happened

The owner typed *"Go to the door."* into the live hosted session. The model
called `navigate_to` with status `ok` — the broker admitted it, because R10
deviation 4 deliberately admits an *unknown place* and lets it fail honestly at
grounding rather than giving the hosted lane a stricter private grammar than the
typed panel path. The mission then ended:

```
nav_state  failed
nav_reason semantic_target_not_found
nav_goal   door
```

There is no door to end near. `events.json → measurements` records the whole
place vocabulary the runtime offered — 7 region aliases, 20 object aliases —
and `door_in_vocabulary: false`. Independently: `scene_truth.json` derives
3 regions and 13 objects for `city_block` and none of them is a portal, and
`configs/scenes/city_block.semantics.yaml` declares no `door` prefix.

**The geometry half of this claim is not provable in any shipped scene.** Not
"was not proved today" — there is no scene in the repo that contains the class
the claim is about.

## The half that did hold

The narration channel was driven on the shipping path. `runtime._arrival_fact_for("the door")`
composes the portal row of the arrival table, and that fact was offered to the
**real** whisperer, which forwarded it (`critical_bypass`) into the **real**
hosted session. It appears in `whisperer_log.jsonl` under the deliberately
self-identifying key `mission_arrived:the door (E1 injected arrival)`:

> The robot's navigation system reports: You have stopped just short of the
> door, without going through it. You are turned back to face your owner. Now
> ask the owner what they would like to do next.

The model answered:

> "I stopped just short of the door, turned to face you, and I'm ready. What
> would you like to do next—try again with a different door, or pick a new spot
> altogether?"

Against the bench baseline for that question — **0/12 chat, 0/6 injected**
(`bench_navmodel.md`) — the ask arrived first try. The model also narrated the
real failure honestly, unprompted:

> "It tried to go to the door, but it wasn't found as a valid target. I stopped
> because there's no clear door object for navigation. What would you like me to
> go to instead…"

**Read the injected turn carefully.** The model says "I stopped just short of
the door, turned to face you" and the body did no such thing — it had stopped
because the target did not exist. The false sentence is faithful to the *fact it
was handed*; the fact was injected by this harness, not produced by the runtime.
Nothing in the shipping path can emit that fact without a portal arrival having
actually happened. It is recorded here because an auditor reading the transcript
alone would otherwise read it as the robot lying.

## Verdict

**FAIL.** The scenario claim has three parts; one passes and two are
unmeasurable in this repo:

| Part of the claim | Result |
| --- | --- |
| ends near the door WITHOUT crossing | **not provable** — no door exists |
| dog faces the owner | **not provable** — same |
| transcript shows the model asking what to do next | **PASS** (both on the real failure and on the injected portal arrival) |

## Defect note for tomorrow

**No shipped scene contains a portal, so R10's door etiquette — `near` +
`do_not_cross` + face-the-owner + the ask-hint — has never executed end to end.**
The policy is pinned at three levels (the arrival table, the planner guard in
`tests/test_arrival_etiquette_pipeline.py`, and R10 seeds S6/S7/S9) and the
sentence it generates is proved to work on the live model here, but the geometry
between them is untested against a real threshold: nothing has ever refused a
pose *inside* a doorway or oriented a terminal back at the owner in a scene
where doing so was possible. The fix is a scene, not a code change — add a
portal instance to `city_block` (or a second scene) with a `door_` geom prefix
in the semantics sidecar, regenerate `scene_truth.json`, and re-run this
scenario. Note the cost of the change: `scene_truth.json` is a generated,
digest-pinned artifact and the MJCF is a packaged asset, so this touches the
release-parity set and is a card of its own. This is already R10 open risk 1 and
owner-gated item 3; this run is the evidence that it blocks a claim the day's
work was supposed to make.
