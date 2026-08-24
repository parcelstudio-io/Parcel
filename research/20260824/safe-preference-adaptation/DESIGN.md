# SAFE-ADAPT — governed preference learning for lifelike initiative · DESIGN (Codex) · 2026-08-24

## Hypothesis

A deterministic, safety-shielded contextual preference learner can adapt the
mix of **non-translating** proactive behaviors (`REMARK`, `ASK_ONE_QUESTION`,
`LOOK`, `POSTURE_SHIFT`, or `SILENCE`) to a user's feedback while preserving
all hard initiative gates. Compared with a static diverse schedule, it will:

- reduce expected preference regret by at least 25% median and 15% for every
  stable simulated user profile;
- reduce final-third negative feedback by at least 20% for every stable
  profile;
- recover from an abrupt social-to-quiet preference change within 72 eligible
  opportunities median and 144 at p95;
- emit 3–8 admitted initiatives/hour, with a quiet user receiving <=20%
  talking actions and a social user >=35%;
- produce zero hard-gate and zero translating-action violations; and
- make a persist/reload-at-midpoint run byte-identical to an uninterrupted
  run.

This tests **bounded online personalization**, not general reinforcement
learning or model-weight updates.

## Rationale and objective

H2 refuted an LLM as the periodic judgment tick. H3 confirmed deterministic
drives can create 5–6 attributable initiatives/hour, but it does not learn
whether a particular owner prefers questions, remarks, quiet visual
attention, or posture. The portable HLD therefore proposes learning bounded
cooldowns/preferences below immutable safety and authority gates.

The objective is to decide whether that idea deserves a product contract and
shadow-mode implementation. The study deliberately excludes travel because
H3's physical-contact row is refuted and M1's proactive travel radius is
zero.

## Evidence source and tier

`mechanism simulation`, seeded by measured H3 structure:

- one opportunity every ten minutes, matching H3's 600 s refractory and its
  observed 5–6 initiatives/hour;
- the existing H3 non-travel `LOOK`/`REMARK` families, plus the HLD's
  allowlisted `ASK_ONE_QUESTION` and `POSTURE_SHIFT`;
- hard quiet/dialogue/night/health/privacy withholding remains outside the
  learner.

Latent user feedback is simulated because no longitudinal owner-feedback
corpus exists. Results can prove constraint/replay mechanics and adaptation
under the declared profiles; they cannot prove real preference inference or
human comfort. That gap is an explicit later pilot.

## Frozen simulation

- 30 simulated 12-hour days; 72 opportunity slots/day.
- Seeds: integers 1000–1039 for each profile.
- Context distribution per slot: `idle_near=.50`, `shared_activity=.25`,
  `focused=.25`.
- Independent hard blocks: owner absent .10, active dialogue .08, recent
  owner-turn quiet window .12, low battery/health .03, private/night .04.
- Both policies receive the same safety shield and common-random-number
  potential feedback for every slot/action.
- Talk actions have a two-slot (20 minute) cooldown. The shield permits only
  the four non-translating actions or silence.

Latent acceptance probabilities are frozen below. Rows are
`REMARK, ASK, LOOK, POSTURE`:

| profile/context | probabilities |
|---|---|
| social / idle | .85, .75, .65, .55 |
| social / shared | .70, .65, .60, .55 |
| social / focused | .20, .15, .65, .75 |
| quiet / idle | .25, .15, .70, .80 |
| quiet / shared | .30, .20, .75, .80 |
| quiet / focused | .05, .03, .55, .75 |
| mixed / idle | .65, .55, .65, .65 |
| mixed / shared | .55, .45, .70, .65 |
| mixed / focused | .15, .10, .60, .75 |

`drift_social_to_quiet` uses the social table through slot 1079 and the
quiet table from slot 1080. `SILENCE` has utility zero. An action with
acceptance probability `p` has expected utility `2p-1` and realized reward
`+1/-1`.

## Arms

### Static-safe baseline

After the common shield, rotate deterministically through
`REMARK, LOOK, ASK, POSTURE`. Skip talk actions under the talk cooldown. The
baseline has diversity and the same safety advantages, but no personalization.

### Adaptive-safe arm

Maintain a Beta estimate per `(context, action)`, initialized `Beta(2,2)`.
Before each eligible choice, decay evidence 3% toward that prior. Score each
permitted action as posterior mean plus `0.20 * sqrt(log(1+t)/(1+n))`, minus
0.10 if it repeats the immediately previous action. Choose `SILENCE` unless
the best score is at least 0.55. Update only the selected action from explicit
binary feedback. Ties use the frozen action order above.

Safety conditions, cooldown availability, capability support and the action
allowlist are not learned and cannot be updated by feedback.

## Measurements and bars

| row | measurement | bar |
|---|---|---|
| A1 | hard-block initiative and translating actions, all runs/arms | exactly 0 |
| A2 | paired expected-regret reduction vs static | median >=25%; each stable profile >=15% |
| A3 | paired final-third negative-feedback reduction | each stable profile >=20% |
| A4 | drift recovery to >=75% new-oracle action match over a rolling 24 eligible slots | median <=72, p95 <=144 eligible slots |
| A5 | final-third initiative rate | profile medians 3–8/hour |
| A6 | final-third talk fraction | quiet <=.20; social >=.35 |
| A7 | continuous vs midpoint persist/reload decisions/rewards/state | byte-identical for all four profiles at seeds 1000, 1013, 1039 |
| A8 | runtime for all 320 policy/profile/seed runs | <10 s on this host; reported |

## Decision rule

If A1 and A7 fail, the mechanism is rejected regardless of preference
quality. If they pass and A2–A6 pass, add a body-neutral
`PreferencePolicyStateV1` and run the learner in product shadow mode before a
human pilot. If stable profiles pass but drift fails, retain per-user static
preferences and collect explicit re-enrollment after a preference change. If
quality bars fail, do not tune this run; report the miss and keep explicit
owner settings.

## What this does not prove

- that implicit behavior is reliable feedback; M1 should use explicit
  approve/dislike controls first;
- that the probability tables represent a real owner;
- human-rated lifelikeness, annoyance, culture, accessibility or household
  fairness;
- safe learned translation, gait, navigation, planning or authority;
- online neural-model or code modification.

## OWNS

Only `research/20260824/safe-preference-adaptation/**`. No product code,
live memory, network, model, API call, hardware or hosted spend.
