# DMC-4 post-evidence maintenance 1: static/type-hint hygiene

Date frozen: 2026-08-30 UTC  
Status: **FROZEN BEFORE MAINTENANCE EDITS OR MAINTENANCE EVIDENCE**

After DMC-4's evidence was retained, a final static-quality pass found one real
introspection defect and several lint-only findings. Calling
`typing.get_type_hints(ExecutiveTransitionV1)` raises `NameError` because
`VerifiedFact` is used in a postponed annotation but is absent from
`executive.py`'s runtime namespace. The experiment does not call this API, so
the retained DMC-4 traces remain valid for their exact old source hashes; the
current production source should nevertheless resolve its public type hints.

## Frozen edit allow-list

Only these edits are permitted:

1. import `VerifiedFact` from `brain.contracts` in `executive.py`;
2. replace the unused resource-conflict local with an explicit ignored binding;
3. mechanically sort imports in the new DMC-4 product/test files;
4. remove one unused test assignment; and
5. annotate the intentional thread-boundary `BaseException` capture with its
   targeted Ruff suppression.

No status mapping, journal rule, authentication rule, transition logic,
capacity, hypothesis, threshold, scenario, or oracle may change.

## Maintenance gates

- `typing.get_type_hints(ExecutiveTransitionV1)` resolves and includes
  `tuple[VerifiedFact, ...]`;
- targeted Ruff and compile checks are clean;
- the DMC-4 focused and adjacent guarded pytest selections pass;
- two fresh maintenance runs pass the original independent H1–H5-static raw
  trace verifier against a separately frozen maintenance source manifest;
- both maintenance runs have identical normalized trace/chain roots, equal to
  the original DMC-4 evidence roots; and
- the original five tamper categories still reject.

The old `source_manifest.json`, A/B runs, verification, and tamper artifacts
must not be rewritten. New maintenance wrappers, manifest, C/D runs,
verification, and tamper files remain separate. A maintenance pass is source
equivalence/regression evidence only; it adds no provider, runtime composition,
audio, hardware, navigation, or mount-readiness claim.
