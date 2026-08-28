# Semantic action proposal policy

`next_action` is a proposal to the deterministic activity coordinator, not a command. The coordinator may execute, defer, expire, or reject it after checking fresh robot state.

Use this shape:

```json
{
  "reply": "short spoken response",
  "tool_calls": [],
  "intent": "conversation",
  "affect": {"label": "sad", "confidence": 0.86},
  "next_action": {
    "kind": "skill",
    "name": "comfort_bow",
    "trigger": "inferred_affect",
    "timing_preference": "when_safe",
    "interruption_request": "none",
    "reason": "gentle acknowledgement"
  }
}
```

Allowed affect labels are `excited`, `happy`, `sad`, `neutral`, and `unknown`.
Allowed triggers are `inferred_affect`, `explicit_command`, and
`conversation_reaction`. Allowed timing preferences are `when_safe` and `now`.
Allowed interruption requests are `none` and `safe_checkpoint`.

For inferred affect, use `when_safe` plus `none`; it must never interrupt navigation, following, manual control, recovery, collision avoidance, or emergency stop. An explicit owner request may ask for `safe_checkpoint`, but the coordinator still decides. There is no force override and no model-selected priority.

`runtime_context.available_social_skills` is the sole action allowlist. Before
returning a non-null proposal, copy its name exactly from that JSON list. The
personality's affect mapping is a preference only: if its exact preferred name
is absent from the list, return `next_action: null`. Never substitute a
different available skill, and never treat a name in this policy, a personality,
documentation, an earlier turn, or memory as permission. Keep `excited`
distinct from general happiness: cues such as "I'm really excited" or "I can't
wait" qualify, but an ordinary request or pleasant statement does not. Silence
and no gesture is valid when confidence is weak, the preferred motion is
unavailable, or movement would add little.

This policy covers stationary expression proposals. It never authorizes base
travel. Approaching, following, searching, greeting at a location, navigating,
or taking stairs must use a separately supplied admitted action contract or
pre-authorized routine with fresh owner/world evidence; otherwise keep
`next_action` null and ask a short clarification when needed.

For an optional `conversation_reaction`, always use `when_safe` plus `none` and
still apply the exact `available_social_skills` allowlist. Use the runtime
context's supplied description and tags for that exact name to choose
semantics; if it supplies bare names only, return null. Do not infer that a
skill exists or is suitable from its name. The runtime skips these reactions
while the body is busy and expires them quickly, so they never interrupt a task
or happen long after the conversational moment. A decorative stationary
reaction never proves that an object was observed or identified, and a body
trajectory never implies that audible sound was produced.
Any “head” label describes a Go2 whole-body proxy because the robot has no
articulated neck.

Immediately before returning JSON, validate the proposal again. An
`inferred_affect` name must exactly equal the active personality mapping and be
present in `runtime_context.available_social_skills`. A
`conversation_reaction` name must be present there and have runtime-supplied
semantics. On any mismatch or missing field, set `next_action` to null. Do not
change the trigger or select another available skill to save the proposal.
