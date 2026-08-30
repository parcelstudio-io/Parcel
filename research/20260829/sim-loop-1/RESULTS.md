# LIT-1 — RESULTS (written incrementally; no verdict here)

Author: Opus executor, 2026-08-29. Pre-registration: `DESIGN.md` +
`AMENDMENTS.md` (binding, and where they conflict with DESIGN.md they win).
Fable writes `VERDICT.md`.

**Evidence tiers, never blended.** `desktop-sim` for every body/plan row (MuJoCo
static city driven through the live `RobotRuntime.handle_text` product path);
`fake` for the scripted-lane voice rows (the product's own `RealtimeLane`
against `FakeRealtimeServer` — **no provider was contacted, no money moved**);
`hosted-live` for hosted rows with $ from the shared wave ledger. Amendment
L10's tier claim stands: **a sim harness with real-swappable hops.** No `real`
hop was recorded; `--audio real` needs the owner present and was **not run**.

> **Status:** complete. Sections 2-8 were written under card **C7**
> (`scrum/20260829/task_2/C7_HARNESS_TRUTH.md`) from the recorded artifacts —
> `results.json`, `artifacts/*.jsonl` — after the original executor was killed by
> the account spend limit with them left as `PENDING` stubs. Every number below
> is read out of a file; nothing is quoted from prose. Section 7.1 records the
> false-terminal defect Fable's verdict found and the fix, with the C7 re-run
> (`results_c7_postfix.json`, artifacts `r101`-`r105`) beside the original runs.

---

## 0. Method, and what "the loop" is

One process per episode, torn down completely:

1. MuJoCo **static city** on a unique short socket under
   `~/.cache/parcel-0e/lit1/`, inside `systemd-run --user --scope -p
   MemoryMax=12G -p MemorySwapMax=0`, leading its own process group.
2. `RobotRuntime` built exactly the way `tests/test_voice_nav_e2e.py::_LiveRuntime`
   builds it (that test is READ, never imported; the pattern is reused through
   NAV-INT-1's `harness.LiveSession`, which already is that pattern).
3. **Model B** — a plan queue in the wave's shared record schema, plus a
   `PlanQueueWhisper` that renders the queue as ONE unbilled tail conversation
   item.
4. A **Realtime lane** — the product's `RealtimeLane`, with either a
   `FakeRealtimeServer` transport (deterministic tier) or the live hosted lane.
5. A scripted owner timeline. **One authority per utterance (amendment L6):**
   motion is always `runtime.handle_text`; the voice lane receives the same
   sentence for narration only.
6. One JSONL, monotonic `t`, a `provenance` column on every row.

### Instrumentation decisions worth stating plainly

**The executive receipt tap.** Amendment L7 asks for `ReportDisposition.action`
and `last_detail` *verbatim*. `task_executive.snapshot()` carries `last_detail`
but **not** `action` — `action` exists only on the value `report()` /
`request_interrupt()` / `suspend_task()` *return* — and the suspend that
`runtime._apply_goal_amend` performs happens inside a locked transaction a
poller cannot see. NAV-INT-1, polling from outside, concluded "no suspended
state was ever observable". So LIT-1 does not poll: it wraps nine methods on the
`TaskExecutive` **instance this process built** and records the returned object,
removing the wrappers on `detach`. Nothing under `src/` is edited.

That single change is what makes the suspend receipt visible — see §7.

**"Starts turning" (amendment L9).** Heading error to the new goal falling for
≥ 3 consecutive 100 ms samples with `|vyaw| > 0.1 rad/s`, where `vyaw` is read
from `runtime._last_sent` — the `VelocityCommand` the runtime actually handed
the body lane, not a finite difference of a noisy pose. Pose and velocity are
sampled at 20 Hz; the JSONL keeps the full rate inside every cue window
(cue − 2 s to cue + 10 s) and 2 Hz outside it, so the committed artifact stays
small without thinning the window the amendment cares about.

**Owner speech has a duration.** L9 defines speech *end* as `handle_text` entry
for a text turn and leaves speech *start* undefined — with start == end the
"was the body moving while the owner spoke" row has a zero-width window and no
samples in it (the first draft measured `n=0`). The harness therefore holds each
sentence for a scripted duration (~2.9 words/s, floored at 0.8 s, capped at 6 s)
before it enters `handle_text`. It is a **model** of an owner talking, labelled
as one, and it is the only deliberate wait in the loop.

**The name scan is a positive allowlist (amendment L4).** A blocklist would have
to contain the held-out scene's name in order to look for it, which is the leak
it exists to prevent. So the gate is positive: the scenario's stand-ins plus the
demo city's own landmark vocabulary. Anything place-shaped and not on the list
is redacted in place and counted. Three words are deliberately **not** scanned —
`table`, `desk`, `chair` — because all three occur as ordinary values inside the
navigator's own mission metadata (the arrival *relation table*), and redacting
product telemetry protects nothing. The guarantee is therefore: *a positive
allowlist over the remaining place-shaped vocabulary*, stated rather than
implied.

### The swap table (amendment L10)

| hop | what ran here | what replaces it for a real row |
|---|---|---|
| mic | fake — text on the scripted timeline | real — XVF3800 array + ASR |
| voice | fake — `FakeRealtimeServer` scripted turns | hosted — the OpenAI Realtime lane |
| body lane | sim — MuJoCo velocity commands | real — gateway protocol v1 fake gateway |
| sensors | sim — MuJoCo static-city observations | real — D455 + Mid-360 |
| world | sim — the demo city | real — the owner's room |

---

## 1. What holds without a simulator (`selfcheck.py`)

`.parcel/bin/python research/20260829/sim-loop-1/selfcheck.py` — **42/42 checks
held** (26 at the time of the recorded runs; card C7 added the 16 rows of the
receipt-typed-offer rule described in section 7.1). Five amendments are claims
about code paths, not about a robot, and this is where they are settled in two
seconds instead of two minutes.

**L1 — the whisper is unbilled, tagged, and replace-not-append.** Checked at the
*wire*, against the frames the product's `RealtimeLane` actually put on a
`FakeRealtimeServer` transport:

| claim | observed |
|---|---|
| two digest refreshes send two `conversation.item.create` frames | `['conversation.item.create', 'conversation.item.create']` |
| the whisper sends **no** `response.create` | none present |
| it carries its own purpose tag | `['lit1 plan queue']` — distinct from the lane's four |
| an unchanged digest sends nothing | third refresh returned `None` |
| the replacement names what it supersedes | `supersedes: lit1_pq1`, and the item text opens `[plan-queue update lit1_pq2; this REPLACES lit1_pq1…]` |
| the rows are marked unbilled | `billed=False`, `response_create=False` |

One honest limitation: **this protocol build exposes no
`conversation.item.delete`.** "Replace-not-append" is therefore implemented at
the *source* — one live whisper slot, re-sent only when the rendered digest
changes, each new item explicitly superseding the previous one in its own first
line. The superseded item stays in the provider's transcript. That is a real gap
between the amendment's word and what the wire can do, and it is recorded here
rather than papered over.

**L7 — "yes" resumes nothing by itself.** 8/8: a bare confirmation returns
`none` with no open offer and `re_issue` only against one; the closed RESUME set
{resume, continue, keep going, carry on} returns `re_issue` unconditionally;
small talk returns `none`.

**L9 — the turn predicate.** 4/4: a real turn toward the goal fires at the first
of the three samples; a stationary body does not; `|vyaw|` below the 0.1 rad/s
floor does not; turning *away* from the goal does not.

**L4 — the name scan.** 4/4: allowlisted names pass, unadmitted ones are caught
and redacted (not dropped), and the scan walks nested structures.

**L7 / MB-1 M7 — the offer is typed by the receipt (card C7).** 16/16: an
accepted terminal keeps the scripted line verbatim; `task_failed`,
`task_cancelled` and `cancelled_at_checkpoint` each drop every arrival sentence,
open with that receipt's own kind, status and detail, and keep the capability
refusal and the offer; a missing terminal receipt says so; every terminal kind
maps into the wave's fact set and exactly one of them (`task_succeeded`) may say
arrived.

**Shared vocabulary.** Every receipt KIND that maps to a status maps into the
wave's registered fact set {accepted, running, blocked, completed, failed,
cancelled, resumed}; the two harness-authored kinds (`re_issue`, `confirm`) map
to **no** product fact, which is the point — they are not receipts. Only
{`task_succeeded`, `task_failed`, `cancelled_at_checkpoint`,
`replacement_activated`} are allowed to spend a billed `response.create`.

---

## 2. H-LIT1a — does the loop close deterministically?

Two run sets, both in `artifacts/`, both `--scenario door_sofa_keys --voice fake
--seed 20260829 --runs 5`: the recorded set **r1–r5** (16:25–16:35, `results.json`)
and the **C7 re-run r101–r105** (21:50–22:00, `results_c7_postfix.json`), made
after the receipt-typed-offer fix in §7.1. The re-run exists to prove the fix
changed only what is *said*.

| | r1–r5 (recorded) | r101–r105 (C7 re-run) |
|---|---|---|
| runs / ok | 5 / 5 | 5 / 5 |
| identical receipt-KIND sequences | **5/5** | **5/5** |
| distinct sequences | 1 | 1 |
| teardown clean (`pgrep`, amendment L3) | 5/5 | 5/5 |
| `name_scan_leaks` (amendment L4) | 0 | 0 |
| spend | $0.00 | $0.00 |

**The one sequence, in both sets, in the executive's own vocabulary:**

```
submit → task_suspended → replacement_activated → task_failed
       → re_issue(harness) → submit → task_failed
```

The pre-registered sequence (`scenarios/door_sofa_keys.json` →
`expected_receipt_kinds`) ends in `task_succeeded` twice. The product produces
`task_failed` twice, both `semantic_target_unreachable`. So:

* **as a harness, H-LIT1a holds** — the loop closes, the seams hold, the receipt
  sequence is deterministic across ten runs on two days' code;
* **as the scenario of record it is refuted** — the amended goal never completes
  and the re-issue does not move the body (§6).

Below the compared KIND set (`SEQUENCE_KINDS`), the full receipt stream carries
one extra benign kind in some runs: `ignored_stale_result` between
`task_suspended` and `replacement_activated` — 1/5 of r1–r5 (r2) and 2/5 of
r101–r105 (r101, r102). It is the executive discarding the suspended task's own
late result; it maps to no wave fact and is deliberately outside the compared
sequence, so "5/5 identical" is 5/5 on the KINDS that mean something and 4/5 (or
3/5) byte-identical on the raw stream.

### The variants (one run each, `--merge`)

| variant | receipt KIND sequence | reading |
|---|---|---|
| `amend_clean` (the same amendment, purpose clause removed) | `submit, task_suspended, replacement_activated, task_failed, re_issue, submit, task_failed` | identical to the base — **the purpose clause is not the cause**; the bench is unreachable either way |
| `blocked_route` (goal on top of an obstacle) | `submit, task_suspended, replacement_activated, task_failed, re_issue, submit, task_failed` | same shape; the switch takes 1 167 ms instead of ~320 ms |
| `unreachable_clarify` ("go to the other one") | `submit, task_suspended` | the anaphoric replacement resolves nothing, the amendment lane refuses to the planner — and the original goal is left **suspended and never resumed**. No terminal at all. |
| `queue_phrasing` ("after that, go to the bench") | `submit, task_succeeded` | the pre-registered PREDICTION (revise immediately) is itself refuted: nothing was queued and nothing was revised — the first goal simply finished |
| `sound_event` ("hey, what was that noise?") | `submit, task_succeeded` | a liveness utterance changes no plan, as designed |
| `no_op` ("nice weather today") | `submit, task_succeeded` | small talk changes no plan, as designed |

Every variant without a mid-route amendment reaches `task_succeeded`. Every
variant with one ends `task_failed`, or (the anaphoric one) never ends at all.

## 3. H-LIT1b — per-hop latency

`p95` is withheld wherever n < 20 (amendment L9); with five runs of one scenario
every hop is n = 5, so **no p95 is reported here** and the bar is read on p50.

### Base tier, r1–r5 (ms)

| hop | n | p50 | min | max |
|---|---|---|---|---|
| `handle_text` in→out | 5 | 12.2 | 9.9 | 16.5 |
| utterance → cue | 5 | 11.8 | 10.5 | 16.6 |
| speech end → first executive receipt | 5 | 0.5 | 0.1 | 1.0 |
| cue → receipt | 5 | **−11.6** | −16.1 | −9.5 |
| **switch** (owner's sentence → body turning toward the new goal, L9) | 5 | **324.6** | 239.5 | 339.6 |

The C7 re-run reproduces every row: `handle_text` p50 11.1 (9.4–13.9), utterance
→ cue 10.9 (9.1–14.3), speech-end → receipt 0.5 (0.0–0.8), cue → receipt −10.7
(−13.6 to −8.9), **switch p50 309.4 ms (306.7–338.8)**.

**The negative row is not a bug and is not a latency.** The cue is read off
`agent.last_brain_metrics` when `handle_text` *returns*, and the executive
receipt is recorded by the tap *inside* that same call — so the receipt is
timestamped a few ms before the cue log line. It is reported as measured rather
than clipped to zero.

| variant | switch (ms) |
|---|---|
| base (p50 of 5) | 324.6 |
| `amend_clean` | 248.1 |
| `queue_phrasing` | 520.8 |
| `blocked_route` | **1 167.0** |

**H-LIT1b, local path: MET.** The pre-registered bar is ≤ 1.5 s to switch;
p50 ≈ 0.32 s and the worst single observation across every fake run is 1.17 s
(the blocked-route variant).

**H-LIT1b, hosted path: UNMEASURED.** The hosted episode logged **no
`voice_turn` at all**: all three owner turns came back as typed refusals
(`voice_turn_refused`, `billed: false`) — *"Realtime lane not armed: no transport
is configured. R1 ships the in-process fake transport only; the live WebSocket
transport is R1.5 and needs `websockets` plus a key."* `credential_present:
false` in the run's environment block. There is no TTFT to report, and a refusal
is not a latency.

## 4. Cost

| | |
|---|---|
| LIT-1 spend, every tier, every run | **$0.000000** |
| LIT-1 sub-cap inside the wave's $5.00 | $2.00 |
| shared wave ledger at the time `results.json` was written | $0.793583 (**MB-1's**, not LIT-1's) |
| billed `response.create` calls on the hosted lane | 0 |
| hosted turns refused before a socket was opened | 3 |

The fake tier contacts no provider by construction. The hosted tier spent $0
because the lane could not arm; the governor snapshot was taken before the
episode and the ledger did not move on LIT-1's account. Per-run notes record the
ledger *delta* during each run ($0.022–$0.069) and say explicitly that it is
MB-1's concurrent hosted traffic and **not** this run's cost — spend is
attributed by `session_id`, and the fake lane never has one.

## 5. Provenance

Every JSONL row carries a `provenance` column; the counts are per run group.

| group | `sim` | `harness` | `fake` | `hosted` |
|---|---|---|---|---|
| base, fake (5 runs) | 4 426 | 75 | 70 | 0 |
| `amend_clean` | 643 | 15 | 14 | 0 |
| `blocked_route` | 913 | 15 | 14 | 0 |
| `unreachable_clarify` | 1 040 | 8 | 7 | 0 |
| `queue_phrasing` | 478 | 8 | 8 | 0 |
| `sound_event` | 512 | 9 | 7 | 0 |
| `no_op` | 468 | 9 | 7 | 0 |
| base, hosted (1 run) | 893 | 15 | 6 | 9 |

`real` is **0 everywhere**: no audio device, no camera, no robot. The hosted
group's six `fake` rows are the plan-queue whisper's own bookkeeping, which does
not change tier with the transport.

**Borrowed modules actually loaded** (`providers` in every run header):

| slot | module that ran |
|---|---|
| session / sim launcher | `nav-interrupt-1/harness.py::LiveSession` |
| queue policy vocabulary | `nav-interrupt-1/queue_policy.py` |
| steering, recorded beside LIT-1's own rule | `model-b-narration-1/steer.py` |
| narration reference | `model-b-narration-1/narrate.py` |

One correction to the module docstring: `sim_loop.py` says LIT-1's confirm rule
is "shipped because `model-b-narration-1/steer.py` does not exist at run time".
It **does** exist and it **was** loaded — every `steering_decision` row carries
`mb1_steer` beside LIT-1's own verdict. LIT-1's rule is the authority for the
reason amendment L7 gives (it fixes the semantics), not for want of MB-1's.

## 6. Motion during speech, and the arrival authority

### Was the body moving while the owner was talking? (amendment L9)

Sampled at 20 Hz over each sentence's scripted duration, base tier, all five runs:

| utterance | n samples | moving fraction | max speed (m/s) | yielded |
|---|---|---|---|---|
| `goal_a` "go to the lamppost" | 27 | 0.00 | 0.000 | yes (nothing to yield — the body is at rest) |
| `amend` "actually, go back to the bench…" | 89–90 | **1.00** | 0.538–0.705 | **no** |
| `confirm` "yes" | 16 | 0.00 | 0.000 | yes |
| `confirm:reissue` "go to the lamppost" | 27–28 | 0.00 | 0.000 | yes |

**The robot walks through the owner's whole sentence.** That is the honest
reading of the `amend` row: 89 of 89 samples in motion, at up to 0.70 m/s, for
the entire ~3 s the owner is speaking. Nothing in the shipped stack slows or
stops for a voice that has started; the plan changes only when the sentence
lands in `handle_text`. Whether that is a defect or the desired behaviour is a
design question this experiment does not answer — but it is a fact about the
substrate a full-duplex behaviour model has to work with.

### The differential arrival authority (NAV-INT-1's K0 region on the final pose)

| run | leg | goal | `system_arrival` | `scorer_arrival` | category | DTG (m) |
|---|---|---|---|---|---|---|
| r1–r5 | `confirm` (the amended goal) | bench | false | false | **agreement** | 3.332–3.336 |
| r1–r5 | `final` (the re-issued goal) | lamppost | false | false | **agreement** | 1.385–1.393 |

**Zero authority disagreements in ten scored legs** — and that is the bad news,
not the good news: the two authorities agree because the robot really is 3.3 m
from the bench and 1.4 m from the lamppost. Compare NAV-INT-1's tier, where 17
of 80 legs disagreed. Here the failure is unambiguous.

The DTG spread across five runs is 4 mm on the bench leg and 8 mm on the
lamppost leg: **the re-issue does not move the body.** The end pose after
`re_issue → submit → task_failed` is the same pose the robot was already
standing in — the second failure is a re-plan that never produced motion, not a
second trip.

## 7. Findings and surprises

### 7.1 The harness narrated a terminal that did not happen — and it is fixed

On all five recorded base runs the post-terminal offer line *"I've reached the
bench. I can't check whether your keys are there…"* was emitted on a
**`task_failed`** receipt and labelled `grounded_in: the accepted terminal
receipt (MB-1 M7)`. The narration path was already honest ("Okay — bench is
failed."); the *scripted offer* was emitted unconditionally, by deterministic
harness code — the exact false-terminal class this wave exists to prevent, with
no language model anywhere near it. Sol's independent audit
(`../lit1-grounding-audit/`) found the same 5/5, and Fable's `VERDICT_FABLE.md`
made it finding 1.

Fixed under card **C7**: `offer_for_terminal()` types the offer by the receipt.
Only `task_succeeded` may carry an arrival phrase; on a failed / blocked /
cancelled / missing terminal the line opens with that receipt's own kind and
detail, the scripted arrival sentence is dropped (and recorded in
`dropped_sentences`), and the capability refusal and the offer question are kept
verbatim so the L7 confirm→re-issue rule keeps its referent.

| | r1–r5 (before) | r101–r105 (after) |
|---|---|---|
| terminal receipts per run | `task_failed`, `task_failed` | `task_failed`, `task_failed` |
| lines matching an arrival phrase | **2 per run, 10/10** | **0 per run, 0/10** |
| receipt-KIND sequence | 5/5 identical | 5/5 identical, **the same sequence** |

What is now said on a failed terminal:

> My task executive reports the task for the bench as failed (receipt:
> task_failed, detail: semantic_target_unreachable), so the trip did not finish.
> I can't check whether your keys are there — I have no camera, so I can't look
> for objects. Do you want me to head back to the lamppost?

`selfcheck.py` carries the rule as five deterministic rows (42/42 checks hold).

### 7.2 The product cannot execute the owner's example

"Go to A; mid-route, actually go to B; done; back to A" fails on the shipped
stack, twice, in every run: the mid-route re-target resolves
`semantic_target_unreachable` (the same clearance-class failure NAV-QUALITY
recorded), and after a failed task the navigator does not re-plan on re-issue
(§6: identical end pose on both scored legs). The `amend_clean` variant rules
out the purpose clause. The door → sofa → keys demo is a **navigation** problem
before it is a conversation problem.

### 7.3 The suspended goal that never resumes

`unreachable_clarify` is the sharpest row in the set: an anaphoric amendment
("actually, go to the other one instead") makes the amendment lane refuse to the
planner — correctly — but the original goal is left `task_suspended` and **no
terminal receipt is ever produced**. The robot is parked by a question. This is
the same defect NAV-INT-1 recorded as its first live defect and card C6 owns.

### 7.4 A record-hygiene defect in this experiment's own scorer

`grounding_check` reports `passes: false` on every base run with
`invented_result_claims: ["your keys are"]`. It is a **substring artefact**: the
honest sentence *"I can't check whether **your keys are** there"* contains the
banned phrase. The three honest markers are all found (`no camera`, `can't
look`, `can't check`) and `offered_return` is true, so the intended reading is a
pass. The check is left exactly as it was — it is a pre-registered scorer and no
number moves under this card — and the artefact is recorded here instead.
Any re-use of `expected_honest_keys_response.must_not_contain_any` should match
on whole claims, not substrings.

### 7.5 The whisper cannot delete, only supersede

Recorded in §1 and repeated here because it is a limit, not a detail: this
protocol build exposes no `conversation.item.delete`, so "replace-not-append" is
implemented at the source (one live slot, re-sent only when the digest changes,
each item naming what it supersedes). The superseded item stays in the
provider's transcript.

## 8. What this does NOT show

1. **No audio.** Every owner turn is text on a scripted timeline with a modelled
   speaking duration. The XVF3800 was never opened; `--audio real` needs the
   owner present and was not run.
2. **No hosted narration.** The hosted tier is UNMEASURED: the lane could not
   arm (`no_transport`, no credential in this session), so there is no TTFT, no
   model sentence, and no evidence about what a real Realtime voice would say on
   a `task_failed` receipt. Every honest-narration row in the fake tier is a
   fixture **this experiment wrote**; it proves the scenario is honest and the
   loop carries it, never that a model would produce it.
3. **No robot, no room.** MuJoCo demo city, four landmark stand-ins behind an
   alias table; `bench`/`lamppost`/`sidewalk` are not a sofa, a door and a
   hallway. Physical motion stays **NO-GO**.
4. **One scenario, one seed, ten runs.** Determinism across ten runs of one
   scripted timeline is not generalisation; the variants are one run each.
5. **The switch latency is the local text path** — utterance to body turn
   through `handle_text`. It contains no ASR, no endpointing, no network.
6. **Nothing about the Orin or the Go2**, and nothing about power, thermals or
   real-time margins.
7. **The plan queue and the confirm rule are LIT-1's own**, labelled as harness
   logic. Neither is a product seam; neither is reachable from the shipped
   runtime today.
