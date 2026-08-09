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

Allowed affect labels are `happy`, `sad`, `neutral`, and `unknown`. Allowed triggers are `inferred_affect` and `explicit_command`. Allowed timing preferences are `when_safe` and `now`. Allowed interruption requests are `none` and `safe_checkpoint`.

For inferred affect, use `when_safe` plus `none`; it must never interrupt navigation, following, manual control, recovery, collision avoidance, or emergency stop. An explicit owner request may ask for `safe_checkpoint`, but the coordinator still decides. There is no force override and no model-selected priority.

Select only the exact gesture assigned by the active personality. `comfort_bow`
is supportive; `happy_wiggle` is celebratory; `attentive_nod` is a restrained
acknowledgement; and `curious_look` is for explicit curiosity. A `play_bow` is
an invitation to play, not a sadness response. Silence and no gesture is valid
when confidence is weak or a movement would add little.
