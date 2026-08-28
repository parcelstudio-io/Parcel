# Conversational embodiment · results · 2026-08-26

Evidence tier: **repository audit + authored deterministic desktop replay**.
Hosted/model spend: **$0.00**.
Robot, Orin, GPU, simulator, microphone, speaker, and network services used:
**none**.

## Headline

All four pre-registered *architecture* hypotheses passed their numerical bars
on the frozen authored semantic frames. This supports implementing a
capability-closed action envelope, explicit action/dialogue state, typed local
initiative admission, and risk-first routing. It does **not** show that a model
understands the utterances, that an owner likes the behavior, that speech is
fluid, or that any motion is safe.

The highest-value repository finding is independent of the authored labels:
only **1/9 (11.11%)** affect-action mappings across the three live personality
files exists in the effective Go2 realtime gesture enum. Eight mappings name
unavailable gestures. This is the same class of capability-grounding defect
reported in yesterday's QEV, now reproduced directly from the effective profile
and tool schema.

The machine result is `results/results.json`. Ten semantic replays produced one
digest:
`115e21ee27c777677b607683a1cb09d2e9a640e67eb93d44f7741e2d56de4bb0`.

## Reproduction

```bash
.parcel/bin/python -m json.tool \
  research/20260826/conversational-embodiment/fixtures.json >/dev/null
.parcel/bin/python -m json.tool \
  research/20260826/conversational-embodiment/SOURCES.json >/dev/null
.parcel/bin/ruff check \
  research/20260826/conversational-embodiment/experiment.py
.parcel/bin/python \
  research/20260826/conversational-embodiment/experiment.py \
  --repo . \
  --fixtures research/20260826/conversational-embodiment/fixtures.json \
  --out research/20260826/conversational-embodiment/results/results.json
```

Execution base was commit
`f3ecb5cd9e09058c7bc29ba61b63e18f92a308d8` plus concurrent uncommitted
worktree changes. The result records SHA-256 for every imported/audited source;
those hashes, rather than the commit alone, identify the run. The fixture hash
is `498c317a...e2ae48f` and experiment hash is
`70e3fce7...c62360d`.

No cases, labels, comparison arms, thresholds, or policies were changed after
the first execution. A documentation-only post-registration note was added to
`DESIGN.md` because a concurrent task introduced SI v4 between design drafting
and execution.

The close gate later required extracting the unchanged SI v4 relationship
prose into `relationship_prompt.py` to keep `prompting.py` below the existing
oversized-module debt threshold. The experiment source-hash list was extended
to include that new leaf module and the result was rerun. No experiment logic
or fixtures changed, and the ten-run semantic digest remained
`115e21ee27c777677b607683a1cb09d2e9a640e67eb93d44f7741e2d56de4bb0`.

## Static repository audit

### Effective embodiment closure

The experiment loaded `ConfigStore(configs/robot.yaml,
profile="go2_edu_plus")`, `PromptLibrary(prompts)`, and
`build_tool_specs(...)` from the current worktree.

Effective realtime gestures:

```text
bow, hello_pose, hop, look_left, look_right, paw_wave, play_bow, shake, stretch
```

Personality mappings:

| personality | affect | preferred action | in gesture enum |
|---|---|---|---|
| calm guardian | sad | `attentive_nod` | no |
| calm guardian | happy | `attentive_nod` | no |
| calm guardian | excited | `excited_paw_taps` | no |
| gentle companion | sad | `comfort_bow` | no |
| gentle companion | happy | `paw_wave` | **yes** |
| gentle companion | excited | `excited_paw_taps` | no |
| playful companion | sad | `comfort_bow` | no |
| playful companion | happy | `happy_wiggle` | no |
| playful companion | excited | `excited_paw_taps` | no |

This does not prove the model will emit those invalid names. The current tool
schema gives it the actual enum and the broker revalidates calls. It does prove
that the personality preference plane and runtime capability plane disagree,
which makes prompt behavior dependent on whether the model follows the enum or
the persona. Boot-time closure should remove that ambiguity.

### Prompt state at execution

The executed worktree rendered `si-companion-v4`, digest
`67788c6b...53abe8c`. A concurrent product task had already added explicit
friend-by-default, continuity, quiet/privacy, non-dependence, installed-gesture,
and no-inferred-travel wording. This study did not author that edit. It is a
sound prompt-level response to the owner request.

The DI remained `di-companion-v1`, with only location, time/part of day, owner,
owner notes, history digest, and scene fields. It still lacks a typed action
receipt, pending referent/action, owner-identity confidence, proactive consent,
and body-state envelope. SI prose and tool enums help inference; the local
envelope is what makes the constraint structural.

## H1 — capability-closed embodiment

The 32 authored cases include safe explicit gestures/poses/travel, unavailable
social gestures, stairs/search/approach gaps, hypothetical/negated/quoted
language, system-initiated travel, busy-body deferral, identity uncertainty,
affordance refusal, and one consented stationary proactive gesture.

| arm | exact | unavailable executions | executions on gold non-execute | safe explicit recall |
|---|---:|---:|---:|---:|
| persona-only proxy | 12/32 (37.5%) | 9 | 20 | 100% |
| **typed envelope** | **32/32 (100%)** | **0** | **0** | **100%** |

All H1 bars passed. The comparison proxy deliberately executes the authored
candidate name and is not the current model or broker. The useful result is
that exact availability, initiator, body, identity, and affordance checks can be
expressed without sacrificing any labeled safe explicit action.

## H2 — receipt- and time-aware dialogue state

The 20 authored state snapshots cover "again" before and after terminal
completion, started versus completed receipts, stale/mismatched terminals,
correction-to-hold, current status, fact update, temporal query, revocation,
non-owner provenance, multi-session lookup, and abstention.

| arm | exact | false completion | unsupported memory answer |
|---|---:|---:|---:|
| tail-only proxy | 9/20 (45%) | 3 | 3 |
| **state graph** | **20/20 (100%)** | **0** | **0** |

All H2 bars passed. These inputs already contain the intended semantic event;
the experiment does not test whether speech recognition or an LLM correctly
resolves "that," extracts a fact, or chooses a retrieval key. A future model
eval must operate on raw transcripts and score those upstream steps separately.

## H3 — typed proactive admission

The new valid set has six useful opportunities and fourteen local-drop cases
covering identity, consent, speech overlap, lane activity, quiet/private state,
E-stop, nearby non-owner, staleness, turn tails, subject dedup, novelty, and
confidence.

| arm | valid-set precision / recall | valid prohibited admissions | malformed admissions |
|---|---:|---:|---:|
| permissive-default proxy | 1.00 / 1.00 | 0 | **30/36** |
| **typed gate** | **1.00 / 1.00** | **0** | **0/36** |

All H3 bars passed. Every missing required field, string-encoded boolean,
non-finite numeric, boolean epoch, unknown version, and unknown key became
`DROP_INVALID`. This closes the exact raw-dictionary failure class from the
2026-08-24 study.

The perfect valid-set score is not a social result. The cases are highly
separable and authored by the policy designer. Proactive speech should remain
off until real owner/non-owner/audio/room traces and blinded owner-preference
labels replace these frames.

## H4 — risk-first edge/cloud routing

The 30-case authored mix contains 14 local closed/safety/initiative decisions,
ten ordinary realtime dialogue turns, and six deliberative or long-memory
turns.

| arm | route exact | hosted generations | safety local | gold hosted routes preserved |
|---|---:|---:|---:|---:|
| always realtime proxy | 10/30 (33.3%) | 30 | 0/5 | 10/16 |
| **risk-first router** | **30/30 (100%)** | **16** | **5/5** | **16/16** |

Hosted generations fell **46.67%** in this authored mix, meeting the 40% bar.
This is workload composition, not a population estimate. A real router dataset
must log upstream class, chosen tier, response quality, fallback, latency,
tokens, and owner correction, then tune only the non-safety boundary. Emergency
and action authority stay deterministic regardless of learned routing.

### Price arithmetic

At the accessed 2026-08-26 GPT-Realtime-2 list rates and official audio-token
conversion, the authored 30-case pass models as:

| arm | one fixture pass | proportional 12,000-turn month |
|---|---:|---:|
| always realtime | $0.199168 | $79.6672 |
| hybrid, local TTS | $0.148144 | $59.2576 |

The hybrid row assumes deliberative text is spoken by local TTS. It excludes
provider special tokens, context growth/cache distribution, separate
transcription/TTS charges, local energy, Starlink, and a second hosted realtime
narration after reasoning. It is not evidence that the proposed $300 realtime +
$100 text budgets will hold. The product spend ledger should enforce those
budgets from actual usage events and degrade in this order: local closed acts
remain; proactive hosted phrasing stops; deep reasoning queues/asks permission;
owner-initiated ordinary dialogue gets the reserved realtime budget.

## Local policy latency

The combined envelope + proactive gate + router ran 150,000 desktop CPython
decisions:

| median | p95 | p99 | maximum | pre-registered bar |
|---:|---:|---:|---:|---:|
| 0.003095 ms | **0.004387 ms** | 0.004817 ms | 0.174774 ms | p95 <= 1 ms |

The bar passed with substantial margin. These numbers cover only already-parsed
policy decisions. They exclude audio capture, VAD, ASR, semantic framing, model
generation, TTS, network, runtime scheduling, and motor response, and are not an
Orin benchmark.

## Relationship to yesterday's evidence

Nothing here overturns the QEV no-go. Yesterday's strongest relevant evidence
remains:

- 2/10 machine-pass and capability safety 0.20 on the live pinned local-model
  quality set;
- 3/13 passing personal-conversation turns;
- 43/76 passing semantic expectations across the captured realtime corpus; and
- four red virtual-acoustic gates, with no mounted through-air result.

This study identifies mechanisms likely to prevent several failures once real
model/audio tests are repeated. It does not repeat or supersede those tests.

The user-linked Claude artifact remained inaccessible as reviewable content.
No result here is evidence about that artifact. Committed QEV and research files
are the only reviewed record of Claude's work.

## Threats to validity

- The same researcher designed policies, fixtures, and gold labels; there are
  no independent raters and no natural base rates.
- Semantic frames bypass NLU, emotion interpretation, coreference, tool choice,
  and memory extraction—the hardest model-facing parts.
- Comparison arms are intentionally weak architecture proxies, not current
  product/model baselines.
- The capability audit tests names, not trajectory semantics or physical
  feasibility. An enum member is not a commissioned gesture.
- Price and routing results are synthetic. Provider rates can change and the
  authored mix controls the reduction.
- Desktop microseconds do not predict spoken or motor latency on AGX Orin.
- No proactive behavior was evaluated with identity dropouts, TV speech,
  overlapping people, privacy zones, or owner annoyance in a real room.
