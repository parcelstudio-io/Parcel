# MA-2-P1 pre-implementation clarifications

Status: **FROZEN BEFORE P1 CODE, SHARDS, OR TRAINING**  
Date: 2026-08-29

1. The final feature named “accepted-receipt age” in `P1_DESIGN.md` means the
   age and presence of the most recent accepted steering event available in
   `dialogue.accepted_steering`. P0 policy payloads do not expose a narrative
   receipt in their causal history, and P1 must not read the trace-level
   `narrative_receipt` field.
2. `S` receives the 33 current-frame numeric features. `C16` receives the same
   33 features over 16 frames plus one per-frame history-valid mask channel.
   Left-padding is all-zero after normalization and carries mask `0`; observed
   frames carry mask `1`.
3. Both learned arms have a three-value bounded continuous command head and a
   separate stop logit. At inference, stop probability at least `0.5` makes the
   raw proposal exactly zero; otherwise the bounded command is proposed. The
   tracker/safety gate remains authoritative.
4. The repeat of seed `20260829` is required for both `S` and `C16`, not only
   one architecture. Equality means byte-identical custom deterministic
   checkpoint files and identical normalized training summaries.
5. Test-STF's small 12-episode gate is an observed-count feasibility rule. Its
   Wilson interval is always reported and cannot support statistical promotion.
