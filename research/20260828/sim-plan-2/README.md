# Sim-plan-2

An additive, deterministic regression evaluation of goal-relevant uncertainty
attribution in `AffordancePlannerV2`. It reuses the untouched 29-mission
`SIM-PLAN-1` matrix and adds an exact observable-fact boundary.

- Method and pre-registered gates: `DESIGN.md`
- Observable-fact contract: `observability.json`
- Runner: `experiment.py`
- Results: `RESULTS.md`
- Replay and product-path verdict: `VERDICT.md`
- Canonical evidence: `results.json`
- Integrity report: `verification.json`

Evidence class: **authored symbolic regression shadow only**. This matrix
informed the V2 change and is not a fresh held-out generalization test. No
physics simulator, hardware, authenticated commissioning, or motion was used.
