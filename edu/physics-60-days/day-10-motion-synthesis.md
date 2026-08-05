# Day 10: Motion Synthesis

## Mental model

A natural-language request becomes physical motion through a chain of models. Each stage changes representation and must preserve units, frames, timestamps, authority, and uncertainty:

~~~text
utterance → task meaning → geometric goal → path → trajectory
          → bounded velocity → forces/contact → measured outcome
~~~

No single layer proves completion. A language model can interpret “away from me,” but camera/LiDAR tracking grounds where the owner is. A planner can find a path, but collision monitoring can veto it. Unitree Sport can execute body motion, but measured progress determines whether the task succeeded.

The synthesis habit is to trace one request down and one feedback path up.

## Quantities, units, and assumptions

A motion task should eventually define:

- A reference entity and frame, such as an enrolled owner track in map coordinates.
- A goal region rather than an exact point.
- A path or relationship constraint.
- Speed, acceleration, and angular-rate bounds.
- Freshness and confidence requirements.
- Safety constraints and an abort policy.
- A completion predicate based on observations.

Natural units such as “steps” are ambiguous. A system can use a documented user preference or cautious default, but it should expose the interpretation and confirm when consequences or space make ambiguity material.

## Core equations

For an owner-relative “move farther away” goal:

~~~text
r = p_dog - p_owner
r_hat = r/|r|
p_goal = p_dog + d_requested r_hat
~~~

`r_hat` is undefined when the owner-relative displacement is zero or too uncertain to establish a direction. That case must stop this calculation: use fresh scene geometry to select an explicitly safe direction or ask for clarification rather than divide by zero or reuse an old bearing.

For each short control interval:

~~~text
heading error → bounded yaw rate
path progress → bounded forward/lateral velocity
observed progress = estimated pose_now - pose_start
~~~

Completion is a predicate, not an equation:

~~~text
inside_safe_goal_region
AND measured_speed_is_settled
AND observations_are_fresh
AND no unresolved safety fault
~~~

## ASCII diagram

~~~text
 “walk away five steps”
            |
            v
 resolve owner + step meaning + safe direction
            |
            v
 safe goal region → collision-free path → turn/translate
            |                                |
            +------ replan from sensors <----+
                             |
                  completion from evidence
~~~

## Worked Parcel / Go2 example

Assume the dog is 1.0 m east of its enrolled owner in a common map frame. For illustration only, the product interprets five conversational steps as 2.5 m after checking available free space:

~~~text
p_owner = (0, 0) m
p_dog = (1, 0) m
r_hat = (1, 0)
p_goal = (1, 0) + 2.5(1, 0) = (3.5, 0) m
~~~

The planner should not simply command reverse five times. It chooses an orientation and collision-free route consistent with the semantic direction “away from owner.” If backing is locally safe and the distance is short, bounded reverse motion may be reasonable; for a longer route, turning and walking forward is normally preferred.

The 0.5 m conversational step and all motion choices are illustrative, not commissioned Go2 limits or universal interpretations. A sidewalk boundary, wall, person, or road can make the literal endpoint invalid, requiring a safer nearby region or clarification.

## Software-engineering analogy

This is a compiler pipeline. Natural language is source text, typed task intent is an intermediate representation, a path is a lower-level plan, and velocity commands are machine-level operations. Validation occurs between stages, and privileged components cannot bypass the runtime.

Completion predicates resemble postconditions checked against durable state. “Function returned” is not equivalent to “real-world side effect occurred.”

## Parcel / Go2 bridge

Parcel’s conversation brain can acknowledge and converse while a deterministic router handles urgent commands and a typed planner proposes multi-step tasks. Behavior arbitration decides whether a gesture may overlay, wait, or interrupt navigation. The control manager remains the single motion writer; safety gates and measured feedback outrank every personality or model proposal.

Companion reading: [Robotics Day 46 — Closed-Loop Task Execution](../robotics-60-days/day-46-closed-loop-task-execution.md).

## Failure and safety note

Never let an LLM emit joint targets, raw torques, or unchecked velocity. Ambiguous language must not silently choose a route through traffic, stairs, crowds, or unknown terrain. If grounding, localization, or owner identity is stale, stop or ask rather than extrapolate.

## Retrieval questions

1. Which representations lie between a voice request and physical motion?
2. Why is “five steps” not yet a metric trajectory?
3. What evidence should a completion predicate require beyond reaching a planned path index?

## Optional 10-minute exercise

Write a typed task record for “wait within one metre of the lamppost.” Include frame, goal region, semantic evidence, freshness, speed state, obstacle constraints, timeout, and success predicate. Use a sketch or simulator only.
