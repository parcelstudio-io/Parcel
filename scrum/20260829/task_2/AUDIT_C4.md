# AUDIT · C4 WHISPER-ACCEPT-1 — verifier: Fable (parcel-0e), 2026-08-29 22:1x EDT

**Disposition: ACCEPT (wave A scope) — with notes.** Second lens: parcel-6c (pending, read-only).

## Re-run by the verifier (through the guard, TMPDIR unset)

| row | executor | verifier |
|---|---|---|
| `tests/test_whisperer_plan_accepted.py` + `tests/test_realtime_whisperer.py` + `tests/test_realtime_lane*.py` | 26 new green; 1245 realtime green | **186 passed in 3.47 s** on that subset |
| `whisperer.py` diff | +480/−1 | **+526/−4** by `git diff --stat` (the four deletions are the `_forward` gap lines refactored for the per-class gap — the executor's "−1" undercounts; substance as described) |
| `_diff` untouched | claimed | no hunk in `_diff` (`git diff` hunk headers) — confirmed |
| `KIND_MIN_GAP_S` semantics change scope | new class only | `KIND_MIN_GAP_S` did not exist at HEAD 704ba5c; its only member is `KIND_PLAN_ACCEPTED` → the per-class gap cannot alter any existing kind; the off-path digest (`4e5e2e47…`, pinned before the first edit, identical after) is the binding proof |
| `noqa` | 0 | **0** in both files (HEAD had 0) |
| ruff | clean | **All checks passed** |
| `KIND_REROUTE` band decision | CRITICAL + cap 3/mission, priced (~$43 → ~$4.3/month at 20 missions/day) | recorded at `whisperer.py:552-631` before the constructor; reasons (shared exempt set = ceiling set read by `runtime._narrate_mission`; the exempt-set test C4 does not own) are correct; **adopted** |

Not re-run by me: the MB-1 corpus replay rows (65 forwarded at prototype bands 6/4; 50 + 15 budget-dropped at shipped 2/15 with one other row moving to `budget_exhausted` — the cap biting, correctly reported as PARTIAL under rule 3); the $ pricing (MB-1 ledger unit price).

## parcel-6c's three checks (as written on the card)
1. Fed from a typed admission receipt, never a `nav_goal` string diff — `note_plan_accepted(receipt)` keyed by `plan_sha256`; re-issue (same task, identical plan, higher revision) does not fire at t+120 s → **holds**.
2. Band decided before the constructor, spend consequence written; constructor fed from `SocialProgressStateV1.REROUTE` → **holds**.
3. (C5's check) n/a here.

## Finding I endorse
The first implementation's own-min-gap-on-the-shared-clock silenced 10/10 block reports and clears in replay; the fix (a class in `KIND_MIN_GAP_S` is spaced against its own last forward and does not advance the shared clock; budget stays shared) is pinned by `test_the_acknowledgement_never_silences_a_block_report`. This is the kind of defect the replay row exists to catch.

## Notes carried to wave B
- Install hook: `runtime.py` `_accept_plan`, insert at line 3625 `self._whisper_plan_accepted(plan, validated, submission, frame)`; sibling written verbatim in STATUS §6. Owner-diff file — waits.
- The 10 "resumed" shortfall on the corpus is C6's `queue` lineage (declared and templated now, not producible until the executive has a queue).
- DEC-0 ratchet reds are the owner's dirty diff (`audio/voice_loop.py`, `brain/executive.py`, `bridge/protocol.py`, `control/motion_gateway.py`, long functions in `control/*`, `unitree_control.py`, `voice/`) — not C4's.

## Second lens (parcel-6c, read-only, 22:1x; `~/.cache/parcel-verify/c4-lens/NOTE.md`) — ACCEPT

- **(a) Per-class gap refactor byte-identical for every pre-existing kind on every path:** `own_gap` is False for all of them, so gap/last (`:1861-1862`) and the clock write (`:1880-1884`) reduce to the deleted lines' exact expressions; `_last_forward_at` has no other reader (`:1203/:1447/:1862/:1884`); pace_mismatch-sustained and owner_returned untouched. **One cross-class drift found:** own-gap forwards are appended to the SHARED `_forwards` deque (`:1878`, for the budget) and `undeliver`'s rewind (`:1447`) sets `_last_forward_at = _forwards[-1]` — for `[S1@t1, plan_accepted@t2, S2@t3]`, undelivering S2 rewinds the shared clock to t2 instead of t1. Safe direction (more spacing, never less), reachable only after a lane-floor refusal following a plan_accepted forward — not in the digest. **Follow-up A1 dispatched to the C4 executor:** rewind to the last SHARED forward (kind beside timestamp or a second deque), test the exact sequence, document the "late undeliver pops nothing" limit.
- **(b) Reroute cap reset** keys on `RerouteReceipt.mission` (required caller field; models never construct receipts) — unspoofable only as far as the caller's key. Wave-B rows adopted: `mission` = executive `task_id` (revision-independent; a re-issue is a NEW task and legitimately gets a fresh 3 — an owner act, already a billed turn); never derived from a goal label or any model-touched string; a mission-independent belt-and-braces ceiling (≤ N reroutes/hour); state the $4.3/month denominator (20 missions/day × ≤ 3) beside the figure.
- **(c) Receipt shape vs the working-tree executive: compatible.** Real `ExecutiveSubmission = (accepted, disposition, task_id, plan_revision, reason)` — no `plan_sha256`, no lineage; `PlanAcceptedReceipt` takes `plan_digest` from `ValidatedPlan.plan_sha256` (`validator.py:518/599`, in hand at `_accept_plan`) and lineage at the call site (`submit()`→NEW, `replace()`→REVISE, queue re-issue→QUEUE). The fake matches the real semantics where it matters. **One real behaviour the fake lacks:** `replace()` returns `accepted=True, disposition "defer"` when the replacement is parked for a checkpoint (activated later as "queued"/"replacement_activated"); `note_plan_accepted` keys on `accepted` + lineage + identity, so a DEFERRED replacement fires at admission, before activation — premature if the parked replacement is dropped. **Wave-B row adopted: fire on activation (the moment the body commits), test the deferred path explicitly.** Re-issue guard is right (same task + same digest → `RULE_PLAN_REISSUE` regardless of revision); the product's amendment-commit re-issue is a NEW task with the original content, so it WILL fire — correct: the owner should hear "back to the bench".

## Follow-up A1 (undeliver rewind) — verifier check, 22:2x

Diff shape verified: `_forwards` is now `deque[tuple[float, str]]` (`whisperer.py:1209`), appended as `(at, kind)` (`:1893`), `_spent`'s eviction reads `[0][0]` with `len()` unchanged (budget count unchanged), `undeliver`'s shared branch rewinds to `_last_shared_forward_at()` (`:1462`, defined `:1909` — scans back for the last kind not in `KIND_MIN_GAP_S`). Three tests present (`tests/test_whisperer_plan_accepted.py:879/:917/:935`); ruff clean; off-path digest `4e5e2e47…` reported identical after A1. Card total now +568/−8. Guarded test numbers pending (queued behind another executor's suite on `suite.lock`); disposition unchanged pending that row.
Follow-up A1 closed: verifier re-run through the guard — `tests/test_whisperer_plan_accepted.py` + `tests/test_realtime_whisperer.py` **123 passed in 0.34 s** (22:36). **Disposition: ACCEPT (wave A), follow-up A1 included.**
