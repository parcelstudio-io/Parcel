# Verdict — LIT-1 terminal grounding

**REFUTED.** Process completion was incorrectly treated as mission completion by a
scripted narration path. Five failed navigation terminals were followed by five
arrival claims.

This is a blocking Model B design failure. A terminal callback is not enough to
authorize prose. The narration bridge must require an authenticated `succeeded`
receipt bound to task, revision, step, attempt, source epoch, and current speech
generation; `failed` must produce a failure/deviation event and never an arrival or
resume-completion offer.

Add these five traces as permanent negative regression fixtures. Also split process
health (`run completed`) from task outcome (`mission succeeded`) in every aggregate.

