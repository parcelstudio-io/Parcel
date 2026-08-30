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

> **Status:** runs in flight. Sections fill in as each group lands. Anything
> still marked `PENDING` has not been measured yet.

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

`.parcel/bin/python research/20260829/sim-loop-1/selfcheck.py` — **26/26 checks
held**. Four amendments are claims about code paths, not about a robot, and this
is where they are settled in two seconds instead of two minutes.

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

**Shared vocabulary.** Every receipt KIND that maps to a status maps into the
wave's registered fact set {accepted, running, blocked, completed, failed,
cancelled, resumed}; the two harness-authored kinds (`re_issue`, `confirm`) map
to **no** product fact, which is the point — they are not receipts. Only
{`task_succeeded`, `task_failed`, `cancelled_at_checkpoint`,
`replacement_activated`} are allowed to spend a billed `response.create`.

---

## 2. H-LIT1a — does the loop close deterministically?

PENDING

## 3. H-LIT1b — per-hop latency

PENDING

## 4. Cost

PENDING

## 5. Provenance

PENDING

## 6. Motion during speech, and the arrival authority

PENDING

## 7. Findings and surprises

PENDING

## 8. What this does NOT show

PENDING
