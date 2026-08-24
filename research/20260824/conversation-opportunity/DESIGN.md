# Local proactive-conversation opportunity gate · DESIGN · 2026-08-24

Status: **pre-registered before the harness was implemented or run**.

## Question

Can an on-body, deterministic gate identify moments when a proactive spoken
remark or question is useful, while refusing interruptions and repetitive
chatter, before any hosted model is called?

This is deliberately narrower than generating a charming sentence. It tests
whether the robot should open the expensive/nondeterministic phrasing door at
all. A hosted model may phrase an admitted opportunity; it may not override a
local refusal.

## Evidence inspected before registration

- H1 measured that VAD alone opens **960.6 times/hour** on TV speech and that a
  forwarded item is normally spoken. It reports a modelled median mini-audio
  turn of **$0.004371**. Therefore "forward" is treated as both a billed call
  and an interruption.
- H2's frozen `gold_set.json` contains 60 authored state digests: 24 `ignore`,
  12 `look`, 12 `remark`, 6 `ask`, and 6 `go_check`. It was labelled for a
  different experiment before this gate existed. The policy may read only the
  numeric/boolean digest and an opaque subject key; it may not read `case_id`,
  `family`, `gold_kind`, `why`, `rendered`, or words in the noticing label.
- H2 refuted a model on the continuous decision tick. H3 separately obtained
  5.33 bounded initiatives/hour and zero quiet/night admissions using local
  deterministic drives, but only 4 remarks across three headline hours. This
  suggests a cheap gate around sparse semantic opportunities, not a language
  model polling the world.
- The shipped Whisperer uses a 15 s minimum gap, a 90 s conversation-quiet
  interval, deduplication, and a hard cap. Its earlier bench found that a
  deterministic state machine beat a local judge on coverage, noise, emergency
  latency, and repeatability.

These are prior constraints, not results of this experiment.

## Hypothesis

Against a timer-only arm and a naive novelty arm, a local two-stage gate—hard
context vetoes followed by deterministic evidence/drive scoring—will:

1. make zero prohibited proactive-speech admissions;
2. retain at least 80% of frozen H2 `remark`/`ask` opportunities with at least
   80% precision;
3. reduce hosted calls by at least 50% versus naive novelty while meeting the
   recall bar;
4. suppress every authored cooldown/repetition refuter; and
5. decide in <= 1 ms p95 on this host, with identical decisions on repeated
   input.

Refutation of any row refutes the full hypothesis. A perfect or near-perfect
corpus score will **not** establish human naturalness: the corpus is authored
and structurally clean.

## Frozen input and provenance

Primary replay:

`research/20260823/local-cognition-gpu/results/gold_set.json`

This is preserved, authored/synthetic evidence, not a household recording and
not human-subject data. Its action labels predate this study but share Parcel's
design assumptions, so correlated-author bias remains. The file's SHA-256 is
recorded by the harness.

Secondary evidence, used only for rate/cost context rather than classification:

- `research/20260823/drives-and-initiative/results/rows.json`
- `research/20260823/drives-and-initiative/logs/ticks_radius6_seed1.jsonl.gz`
- `research/20260823/ambient-ear-cost-ladder/results/p0_hosted_always.json`

The harness will also generate an explicitly labelled **authored invariant
suite** by copying useful H2 digests and changing exactly one hard-gate field.
That suite can refute a gate implementation; it cannot validate usefulness.

## Opportunity contract

The upstream perception/world-model side supplies an `OpportunityDigest`:

- monotonic timestamp;
- verified-owner-present bit;
- owner-speaking, voice-lane-busy, quiet-hours and e-stop bits;
- ages of the last owner turn and last robot utterance;
- numeric noticing novelty and age;
- curiosity/social/vigilance drive levels;
- an opaque stable subject key for repetition control.

For this replay, H2's `owner_present` is adapted to
`verified_owner_present`. This is only a proxy: H2 has no identity confidence,
consent state, multi-person privacy state, or acoustic endpoint timing.

### Stage 1: non-negotiable vetoes

Reject before scoring when any condition holds:

- verified owner absent;
- owner currently speaking;
- output lane busy;
- quiet hours;
- e-stop latched;
- owner turn less than **15 s** ago (the existing Whisperer minimum gap);
- robot utterance less than **90 s** ago (the existing conversation-quiet
  interval, applied here as a speech cooldown);
- freshest noticing older than **30 s** (twice the existing 15 s minimum gap);
- a recent action contains a prior remark; or
- the same opaque subject was admitted within **600 s**.

The previous-remark test treats H2's `recent_actions` literally as recent
because that artifact carries no action timestamps. Production must use an
age-bearing event ID rather than an unbounded text list.

### Stage 2: deterministic score

If a noticing is present, compute:

`score = novelty * (0.75 + 0.25 * max(curiosity, social, vigilance))`

All terms are clamped to `[0, 1]`. Admit at `score >= 0.35`, inheriting the
existing noticing gate's `novelty_tau=0.35`. The 75/25 split makes grounded
evidence dominant while allowing drives to rank opportunities; no corpus label
is used. Natural-language labels are opaque and never parsed.

An admission records its time and subject. The gate produces a reason and a
score, never words and never motion.

## Arms

1. **Timer-only**: admit when there has been no robot utterance for 360 s (the
   existing idle-chatter mean), or no robot utterance is recorded. It ignores
   context and content.
2. **Naive novelty**: admit when maximum novelty is >= 0.35. It ignores all
   context, cooldown and repetition.
3. **Context timer**: approximate the existing chatter scheduler: require
   owner present, lane free, non-night, owner-turn age >= 90 s, and robot
   silence >= 360 s; it does not score content. This is diagnostic, not the
   principal baseline.
4. **Opportunity gate**: the two-stage policy above.

Each frozen case is classified with fresh state so one authored snapshot cannot
change another. Stateful behavior is tested separately.

## Authored refuters and stateful sequence

For six useful H2 cases, generate one-field counterfactuals for owner absent,
owner speaking, lane busy, quiet hours, e-stop, owner-turn age 1 s,
robot-utterance age 1 s, and an existing recent remark: 48 prohibited cases,
all of which must be rejected.

Then replay one otherwise-admissible subject at t=0, 30, 90, 120 and 601 s,
plus a distinct subject at t=120 s. Required outcomes:

- first subject admitted at t=0;
- same subject refused at t=30, 90 and 120 (cooldown, then dedup);
- distinct subject admitted at t=120; and
- original subject re-admitted at t=601.

This sequence is authored directly from the rule and therefore tests
implementation/invariant preservation only, not policy quality.

## Measurements and bars

| row | measurement | acceptance bar |
|---|---|---|
| O1 | admissions with any hard prohibition | **0** on frozen replay and **0/48** refuters |
| O2 | useful (`remark` or `ask`) recall | >= 0.80 |
| O3 | useful precision | >= 0.80 |
| O4 | hosted-call reduction vs naive novelty | >= 50%, while O2 holds |
| O5 | authored stateful cooldown/dedup sequence | exact required outcomes; 0 premature repeats |
| O6 | deterministic execution | identical decision SHA over 10 repeats |
| O7 | local decision latency | p95 <= 1 ms over >= 100,000 decisions |
| O8 | cost | report calls and H1-median cost per corpus pass and per 1,000 candidates |

Precision/recall exclude the six `arguable=true` rows in the headline and are
also reported with them included. This exclusion is pre-registered because H2
itself marks those labels as contestable; no row will be added or removed after
execution.

## Cost calculation

Every arm's admitted count is multiplied by H1's frozen
`median_turn_usd_audio_modelled`. The normalized cost per 1,000 candidate
digests is `admission_fraction * 1000 * median_turn_cost`. No new hosted call
will be made.

A secondary, explicitly modelled month uses H3's measured 5.33 initiative
candidates/hour, 12 active hours/day and 30 days. This is a normalization, not
evidence of a real household opportunity rate.

## Outputs

- `opportunity_gate.py`: isolated policy and reproducible replay harness;
- `results.json`: compact canonical machine result;
- `RESULTS.md`: exact rows, failure examples and provenance;
- `VERDICT.md`: product decision and next physical refuter.

## What this cannot prove

- No microphone, owner-identity model, camera, Orin or robot is involved.
- The H2 cases are authored, balanced and unusually legible; prevalence and
  sensor errors in a house will differ.
- It does not measure whether generated wording is warm, varied, truthful or
  worth hearing.
- It does not establish multi-person privacy or whether an owner actually wants
  a remark at that moment.
- It does not validate online learning. It only provides a bounded local door
  through which a governed memory/learning system may propose a question.

The next evidence after a positive result is a mounted, consented replay with
real owner/non-owner tracks, conversation tails, AEC, TV speech, and blind human
ratings. This desk test can justify implementing that experiment; it cannot
replace it.
