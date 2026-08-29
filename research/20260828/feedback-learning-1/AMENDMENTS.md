# FL-1 amendments — PRE-RUN (written 2026-08-28 17:57 from an independent three-lens design review, before any FL-1 headline row ran)

These amendments bind. Where they conflict with DESIGN.md, they win; DESIGN.md
stays as the record of the first draft. Every RESULTS.md section states which
amendment it applies.

## F1 — the laugh model and the regret are pre-registered
- For each owner, taste vector p_c ∈ [0.05, 0.95] per joke category c (6
  categories); per joke, owner laughs ~ Bernoulli(p_c). Owner source that
  CARRIES the verdict: the synthetic Beta-mixture prior (record its
  parameters). Jester-derived owners (HS-1 artifact, if it lands) are a
  SECONDARY slice.
- Reward per joke: +1 anticipatory chuckle on a laughed joke; −2 anticipatory
  chuckle on a not-laughed joke (the 2:1 cost); 0 otherwise. Regret =
  Σ (oracle expected reward − policy expected reward), oracle = knows p_c.
  Rows: ORACLE (ceiling), POPULATION-PRIOR-NO-ADAPTATION (floor), then each
  learner. All bars are read against those two rows, and the absolute bars
  from DESIGN.md are reported beside them.

## F2 — history channel is per-category
`hist` = for each of the 6 categories: (laughed, total) counts capped at 7
plus a recency bin (last outcome in this category: none / laughed / silent).
Policy C (FL-1's OWN retrain across ≥ 400 synthetic owners), the bandit, and
the teacher all read this same state. Ablation = per-category history vs
masked-to-none. Do NOT inherit BM-1's checkpoints (its hist_k is the last-6
global events; record that BM-1 implemented that).

## F3 — H-FL1a made non-tautological
- Ground truth = the owner actually laughed in sim; a decision counts only if
  it is timestamped before the laugh cue.
- Window: F1 over jokes 13–32 after 12 observed for that owner; each
  evaluation owner gets exactly 32 jokes, categories uniform over the 6.
- Baseline row: the bare history rule (chuckle iff laughed ≥ 2 of the last 3
  in this category). Policy C must beat it by ≥ 0.05 F1 on held-out owners,
  else the pre-registered finding is "the rule, not the model".
- Evaluation owners come from fresh seeds (base seed 20260828 + 1,000,000 + i)
  never used by BM-1; tuning owners from other fresh seeds. Record them.
- If BM-1's arm C scores < 0.85 on its in-distribution chuckle F1, H-FL1a is
  INCONCLUSIVE, not REFUTED.

## F4 — bandit threshold
Decision threshold = 2/3 (Bayes-optimal under the 2:1 cost). Report the 0.6
rule as a sensitivity row only.

## F5 — the reward is NOT clean: noisy-reward arm is the headline
Detector model on the laugh reward: false-negative 20 %, false-positive 5 %
per joke window, onset latency 0.5 s (replace with HS-1's measured operating
point if `humor-signal-1/results.json` exists when you run; say which).
Self-echo confound: with probability q ∈ {0, 0.1, 0.3} the detector fires
on the dog's own chuckle; with probability m ∈ {0, 0.3} a true laugh in the
1 s after the dog's chuckle is masked. Default decision rule: the reward
window opens only after the dog's chuckle audio ends (1.0 s), and detector
events overlapping it are discarded. HEADLINE row = q 0.1, m 0.3; clean row
= ceiling. Report regret, posterior bias (mean posterior − true p), and
false-chuckle under each (q, m).

## F6 — H-FL1c made well-posed
- Owner preference generator: preferred check-in latency L* uniform over
  {2, 4, 6, 8} s. P(reacquired ≤ 5 s | check-in at L) = 0.9 if L ≥ L*, else
  0.5. Annoyance if L < L* with probability 0.6·(L* − L)/6.
- Success = simple regret ≤ 0.1 (the chosen arm's true expected reward is
  within 0.1 of the best arm's) after N loss events; report the fraction of
  owners meeting it at N ∈ {5, 10, 15, 20, 25, 30, 40} and the median N.
- The learned quantity is a follow-skill parameter `check_in_latency_s`
  (a config value the executive owns), never an act token; state this. Its
  verdict is independent of BM-1's [3, 5] s M2(b) window.

## F7 — H-FL1d made one-sided-proof
- Product-realistic arm: trainable head masked to {<emote:chuckle>, <idle>}.
  Second row: unmasked full head (what naive online RL would do).
- Credit assignment: reward applied to the log-probs of frames in
  [punchline, laugh + 1.5 s], baseline-subtracted (running mean of the
  reward), one update per joke, lr 1e-4.
- The single regression pair that counts: compliance (c) F1 and raw M3
  extended to twist/locomotion emission by base_busy state (free/busy/
  critical) plus cmd:stop compliance; ≥ 3 seeds; the regression's bootstrap
  CI must exclude 0 to count. "Faster" = jokes-to-0.8 F1 with CIs on both
  curves.
- Online-updated weights are research artifacts under ~/.cache/parcel-0e/;
  never a product checkpoint.

## F8 — H-FL1e: explicit verbal feedback as a second reward channel
Generator: after a false chuckle the owner says a scold ("that wasn't
funny") with probability 0.3; after a hit, praise with probability 0.2.
Pseudo-counts: scold within 3 s of a chuckle = 3 negative observations +
suppression of anticipatory chuckles for the rest of the episode; praise = 2
positive. Measure jokes-to-bar and regret vs laughter-only. Also an
"owner resets the table" event at joke 30 for 20 % of owners; report
recovery (jokes to return to the bar).

## F9 — governance paragraph (RESULTS.md, no experiment)
Where the learned table lives: per-owner, under the owner model, shadow-only
until promotion (learning_loop/promotion.py is default-off), owner-readable
and resettable; the product producer for annoyance is a
SocialCueV1(kind="frustration") within 5 s of a check-in — no producer
exists today (prerequisite product change, flag OFF).
