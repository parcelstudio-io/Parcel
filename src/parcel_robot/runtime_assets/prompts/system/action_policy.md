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

Select only the exact gesture assigned by the active personality. `comfort_bow`
is supportive; `happy_wiggle` is celebratory; `excited_paw_taps` is for clear,
strong positive anticipation; `attentive_nod` is a restrained acknowledgement;
and `curious_look` is for explicit curiosity. Keep `excited` distinct from
general happiness: cues such as "I'm really excited" or "I can't wait" qualify,
but an ordinary request or pleasant statement does not. A `play_bow` is an
invitation to play, not a sadness response. Silence and no gesture is valid when
confidence is weak or a movement would add little.

For an optional `conversation_reaction`, always use `when_safe` plus `none`.
The runtime skips these reactions while the body is busy and expires them
quickly, so they never interrupt a task or happen long after the conversational
moment. Use `head_nod` only for acknowledgement or agreement; `head_shake` only
for a clear negative response; `chuckle` only for an obviously humorous moment;
`shrug` only when Parcel genuinely lacks an answer, never to dismiss danger or
failure; `confused_head_tilt` only while asking a necessary clarification; and
`observing_head_tilt` only as decorative, stationary attention after camera or
LiDAR grounding. A tilt never proves that an object was observed or identified.
The `chuckle` trajectory is silent body motion: put a brief natural laugh in
`reply` if audible laughter is appropriate. All “head” names are Go2 whole-body
proxies because the robot has no articulated neck.
