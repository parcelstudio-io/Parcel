# FL-1 — learning "chuckle if it was funny" and "look back when lost" from the owner

Author: Fable (parcel-0e), 2026-08-28. Pre-registered before any run.
Evidence tier: `desktop-sim` (BM-1's world simulator; synthetic owners whose
humor taste is drawn from HS-1's real Jester clusters when that artifact
exists, else from BM-1's taste prior — RESULTS.md must say which).
Physical motion: **NO-GO**, unchanged. Nothing here gains authority.

## The learning problem, stated precisely

Behavior cloning (BM-1) teaches the *shape* of the behaviors. It cannot teach
*this owner's* humor, or *this owner's* tolerance for being waited on,
because those are latent per person. FL-1 asks whether the dog can acquire
them from the owner's own reactions, online, with the sample budget a real
household offers (tens of jokes, not thousands), and without a weight update
that could regress safety.

Two target behaviors, two reward signals:

- **Chuckle.** Reward = the owner laughs within 2 s after a punchline
  (HS-1's laughter detector in the product; ground truth in sim). An
  *anticipatory* chuckle that lands before the laugh on a joke the owner does
  find funny is the success; a chuckle at a joke the owner does not laugh at
  is the cost (false chuckle — reads as sycophantic, and the design treats it
  as worse than a miss: cost ratio 2:1).
- **Look back.** When the dog is ahead of the owner and loses sight, the
  owner "reward" is faster reacquisition (the owner calls or catches up
  within 5 s of the look-back) and no annoyance event (owner says "keep
  going" / "stop stopping" when the dog looks back too eagerly). Owners
  differ in the latency they want: some want the dog to check in at 2 s,
  some at 8 s. The dog must learn the owner's preferred check-in latency.

## Hypotheses (falsifiable)

**H-FL1a (in-context adaptation, no weight update).** BehaviorFormer-style
policy C from BM-1, trained across many synthetic owners *with the owner
history channel present* (`hist_k`: last K joke-category → laughed pairs),
reaches ≥ 0.80 anticipatory-chuckle F1 on a **new held-out owner** after
observing ≤ 12 jokes of that owner, with false-chuckle ≤ 0.10, purely by
reading the history tokens. Refuted if F1 < 0.60 at 12 jokes or if the
false-chuckle rate exceeds 0.20.

**H-FL1b (bandit learns as fast as the model, and is auditable).** A
contextual Thompson-sampling bandit (Beta posteriors per owner × joke
category, prior from the population taste prior; decision = anticipatory
chuckle iff P(laugh) ≥ 0.6) reaches the same bars in ≤ 20 jokes and has
cumulative regret ≤ 8 "wrong chuckles" over 60 jokes (median over 100
synthetic owners). The bandit is the safety-preferred mechanism (its state
is a table the owner can read and reset).

**H-FL1c (look-back latency is learnable in tens of losses).** A 4-arm
bandit over check-in latency {2, 4, 6, 8 s} with reward = reacquired within
5 s − 0.5·annoyance identifies the owner's preferred latency (the arm with
the highest true expected reward) in ≤ 25 loss events for ≥ 80 % of
synthetic owners.

**H-FL1d (online policy-gradient is NOT worth its risk here).** Fine-tuning
policy C's output head online with REINFORCE on the laugh reward (lr 1e-4,
one step per joke) reaches the FL1a bars no faster than the bandit and
degrades at least one BM-1 safety/compliance score by ≥ 0.05 on the frozen
split after 60 online steps. (This is the arm we expect to *lose*; a win
would change the design.)

## Measurements

- Learning curves (F1, false-chuckle, regret) vs number of jokes/losses,
  median and IQR over 100 synthetic owners drawn from the held-out taste
  profiles; bootstrap 95 % CI on the medians.
- For a: policy C with and without the `hist_k` channel (ablation).
- For d: BM-1 frozen-split M2 scores before vs after 60 online updates.
- Owner taste realism: report whether the owners came from HS-1's Jester
  clusters (real variance) or the synthetic prior.

## Success criteria (pre-registered)

a, b, c each CONFIRMED / REFUTED on their own bars. d is CONFIRMED when the
policy-gradient arm is both no faster and regresses ≥ 0.05 somewhere
(i.e., the hypothesis "not worth it" holds); if it is faster and does not
regress, d is REFUTED and the report must say online gradient learning is
back on the table.

## What it does NOT prove

The laugh reward is simulated as clean; HS-1 measures how clean it can be.
Nothing about real owners, real audio, real perception, or the robot.

## OWNS / must not touch

OWNS `research/20260828/feedback-learning-1/**`; reads BM-1's `worldsim.py`,
checkpoints under `~/.cache/parcel-0e/bm1/`, and HS-1's
`owner_taste_prior.json` if present (copy, do not modify). Must not touch
`src/`, `tests/`, other folders, git.

## Reproduction

`~/.cache/parcel-0e/venv/bin/python research/20260828/feedback-learning-1/run.py --all --seed 20260828`
→ `results.json`; RESULTS.md carries only numbers from it.
