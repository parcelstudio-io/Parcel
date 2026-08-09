# Sprint 2026-08-09 · task_6 — conversation_quality_v1 manifest re-pin (coordinator, owner-authorized)

**Why a frozen eval sha moved (provenance, per the frozen-number discipline):**
the concurrent gesture wave-2 work (commit 19c9226) legitimately edited two
sha-locked conversation-eval inputs — `prompts/system/action_policy.md` and
`prompts/functions/companion.yaml` — adding an `excited` affect label and a
`conversation_reaction` trigger with reviewed gesture vocabulary (head_nod,
head_shake, chuckle, shrug, confused/observing_head_tilt), including honest
discipline ("a tilt never proves an object was observed"). It did NOT re-pin
the conversation_quality_v1 manifest, so the frozen-pack integrity guard
correctly reddened 3 tests on committed main.

**Fix (owner-authorized):** verified both diffs are intended enhancements (not
corruption) and mutually consistent; the two copies of action_policy.md
(source + runtime_assets) are byte-identical; re-pinned exactly the two
`sha256` entries in `evals/companion/conversation_quality_v1/manifest.json`,
computed per named entry from disk. No scoring case changed — all 3 reds were
downstream of the sha lock, not behavior. Manifest diff = 2 lines. Full
default suite 3023 passed / 0 failed.

**The guard worked as designed** — an unreviewed change to a locked eval input
was caught rather than silently absorbed; re-pinning is the reviewed
acceptance, recorded here.
