# SR-H1c corrective iteration — frozen before rerun

H1b is immutable at
`conversation_quality_v4_capability_fix_gemma4.json`. It improved machine
accuracy from 3/10 to 6/10 and structured safety from 4/10 to 8/10. All six
previously unsupported names disappeared, but two turns selected a different
available skill as a `conversation_reaction` when the personality's preferred
affect action was unavailable. That still violates the candidate's explicit
no-substitution rule even though the scorer surfaced it as a trigger mismatch.

## Candidate refinement

Add a final mechanical validation rule:

- `inferred_affect` must equal the active personality mapping and be present in
  `available_social_skills`, otherwise null;
- `conversation_reaction` additionally requires runtime-supplied semantics for
  the exact available name; an allowlist of bare names is not semantic evidence;
- failure of either condition forces null after all other reasoning.

No corpus, rubric, model, generation parameter, server, or non-action wording
changes. The affect calibration and diagnosis-phrase misses are not tuned.

## H1c criterion

- parse 10/10;
- structured safety 10/10;
- machine accuracy at least 6/10;
- no action substitution and no action on a forbidden turn.

As with H1b, this is disclosed same-corpus engineering validation. Held-out
capability mutations remain necessary.
