# LIT-1 independent grounding-audit results

The standard-library verifier checked all five frozen source hashes and parsed
4,576 JSONL rows. All five process footers say `ok=true`, but all five mission
traces provide the same counterexample:

1. the exact active revision terminates with `task_failed` and
   `semantic_target_unreachable`;
2. the separate arrival-authority row says both system and scorer arrival are
   false, with the robot 3.332–3.336 m from the bench; and
3. the harness immediately emits “I've reached the bench,” labeling it as
   grounded in the accepted terminal receipt.

Exact result: **5/5 false terminal arrival claims**. No preceding
`task_succeeded` receipt exists in any trace.

The evidence is post-hoc and the voice is scripted. It refutes the claim that this
LIT-1 path is receipt-grounded; it does not estimate the production or hosted-model
failure rate.

