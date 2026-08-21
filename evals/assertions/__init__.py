"""The assertion eval model — card EV-1 (``scrum/20260820/task_11``).

Programmatic assertions over persisted session artifacts. No model, no network,
no judgement: eleven pure-code checks that read a session folder and name what
is wrong in it, with the evidence rows attached so a human can audit the claim.

WHY THIS AND NOT A JUDGE
------------------------
Four eval-model prototypes were measured on real project data
(``scrum/20260820/research/bench_eval_designs.md``). On the six real owner-session
failures:

======================  =======  ==============  =========  ================
prototype               catches  false positives  cost/run   reproducibility
======================  =======  ==============  =========  ================
B — these assertions        5/6               0    $0, <1 s  byte-identical
A — 7-dim rubric judge      4/6      2 hard/run    $0.015    incidents unstable
======================  =======  ==============  =========  ================

So B gates and A does not (``nightly.py`` runs A as a trend line and a review
queue, never as a verdict). The effect size the gate buys: from 0/6 failures
caught automatically to 5/6.

THE SIXTH IS NOT CAUGHT, AND IS NOT PRETENDED TO BE
---------------------------------------------------
A spoken emergency phrase transcribed as "Dice out!" scores 0.571 character
similarity against the real phrase, while three innocent phrases from R9's own
negative-latch set score 0.615–0.769. No text threshold separates them, so the
e-stop check emits a REVIEW QUEUE (~4 flags/session) rather than a verdict, and
says so in its own output. Closing that gap needs audio, which is card F1-SI.

THE FOUR PIECES
---------------
``evidence`` — load a session folder into one object, and say honestly which
parts of it are a STREAM (EV-1's uncapped ``events.jsonl``) and which are a
100-slot RING window. Every false positive in the bench's extended checks was a
ring eviction artifact, so a check that needs evidence it does not have
downgrades to review rather than asserting.

``checks`` — the eleven checks.

``matrix`` — the verdict shape: a fixed dimension x suite matrix with NO blended
scalar, safety gated on its own, and pass^k for reliability-critical behaviours.

``selftest`` — a null agent, an always-claims-success agent and a random-tool
agent. Any suite they pass is broken, and the gate says so.
"""

from __future__ import annotations

__all__ = ["checks", "evidence", "matrix", "selftest"]
