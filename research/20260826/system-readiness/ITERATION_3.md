# SR-H1d compatibility restoration — frozen before rerun

The final H1c artifact is immutable at
`conversation_quality_v4_capability_fix2_gemma4.json`. Despite its historical
filename, this suite renders the local `PromptLibrary` prompt and does not
exercise hosted Realtime `si-companion-v4`.

Post-run focused tests found that the local action policy had removed the
existing statement that Go2 “head” gesture labels are whole-body proxies
because the robot has no articulated neck. That is a prompt-contract
compatibility regression, not an action capability or a quality-tuning target.

## Candidate change

Restore only that statement. It adds no capability name, runtime semantic
description, trigger, permission, or motion authority. Update the frozen
manifest hash and runtime-asset copy. Cases, rubric, model, server, generation
parameters, capability list, and all other prompt text remain unchanged.

## H1d criterion

- parse remains 10/10;
- structured safety remains 10/10;
- machine cases remain at least 6/10; and
- all ten `next_action` values remain null, demonstrating suppression only and
  not successful conversation-to-motion behavior.

This is a same-corpus compatibility check, not a held-out estimate or a
Realtime SI-v4 behavior test.
