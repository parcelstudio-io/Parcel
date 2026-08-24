"""Offline counterfactual candidate logging + oracle replay (C-B sol half).

Pure measurement substrate only.  No runtime, GoalArbiter, or navigation
product wiring.  Opus Wave-2b consumes these contracts at the arbitration
log site.

Frozen public surface
---------------------
- :func:`build_arbitration_log` — stamp candidates + committed choice
- :func:`replay_committed_choice` — bit-identical deterministic re-select
- :func:`counterfactual_report` — would-a-different-candidate-have-won
"""
