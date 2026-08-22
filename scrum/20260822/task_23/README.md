# Task 23 — ROAM-1: "go explore" is a behavior, a tool, and a closed intent

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 standing rules apply). **Evidence:** `PLAN_ASSESSMENT_FABLE.md` Phase 4
("roam on command" REFUTED as a capability): the broker's eight tools are
`get_status, recall_memory, play_gesture, set_pose, navigate_to,
circle_owner, follow_owner, remember_fact` (`realtime/tool_broker.py:111-141`)
— no roam; `PatrolPolicy` (`patrol/mission.py:173`) is never constructed in
`runtime.py` (MOVE-1 drove it from a harness); no `roam`/`stop roaming`
closed intent. Plus the buried Phase-5 defect: the product navigator runs on
a frozen clock — `time_s` is never supplied by `runtime._navigation_extras`
or `headless_city`, so tracker dt is the 0.1 literal regardless of `loop_hz`
and memory/goal TTLs never advance.

## Why
"Roam autonomously upon command" is the first line of the owner's goal and
it does not exist on the product path. MOVE-1 proved the patrol moves (5.0 m
path) and also that its net displacement was 0.134 m — the one number the
Go2 purchase gate depends on.

## Work
1. **Behavior:** wrap `PatrolPolicy` as a runtime behavior beside
   navigate/follow/search with a fixed time budget, the P1-E social zone in
   force, and the learned-map writer (P1-B) consuming its frames; the
   behavior yields to every safety gate and to any owner command.
2. **Tool:** `TOOL_ROAM` on the broker (owner-commanded only — NOT in the
   proactive-motion allowlist), structured result per P0-B's shape; `stop
   roaming` returns to idle in one tick.
3. **Closed intents:** `roam` / `go explore` / `stop roaming` in
   `realtime/ingress.py`'s closed-intent table, executed locally before the
   model speaks like the others.
4. **The clock:** supply `time_s` from the runtime's monotonic clock in
   `_navigation_extras` (and `headless_city`), so tracker dt follows
   `loop_hz` and TTLs advance; one paired `nav_instruct` run proves the
   frozen-row behaviour is unchanged at 10 Hz and a seeded `loop_hz: 20`
   shows dt moving.
5. **Pre-register:** spoken "go explore" → patrol ticking ≤ 2 s (ledger
   row); 3 consecutive 120 s runs in `--static-city` each ≥ 5.0 m path and
   **≥ 1.0 m net displacement**; "stop" latches in one tick; **0
   robot-initiated contact**; the prototype social zone (0.7 m) respected.
   Per MOVE-1's D3 the dynamic city is not a controllable denominator —
   report it as a second arm, not the gate.
6. Seeds RED: roam running past its budget; roam surviving an e-stop; roam
   reachable from a system-initiated turn; `time_s` absent again.

OWNS: new marked `runtime.py` roam region (re-read — P1-B/P2-A/P2-B regions
are elsewhere), `src/parcel_robot/patrol/` (MOVE-1's, now product),
`realtime/tool_broker.py` NEW roam region, `realtime/ingress.py` closed-intent
table, `configs/realtime.prototype.yaml.example` roam keys,
`runtime._navigation_extras` + `headless_city.py` clock line,
`tests/test_roam1_*.py`, `task_23/` docs. MUST NOT TOUCH: `reactive_safety`,
`core/hard_stop`, the whisperer (CURIO-1), `online_map/` internals.

## Definition of done
Pre-registered rows measured (3 runs); the displacement number reported
plainly — it is a Go2-purchase input; seeds RED; `ROAM1_STATUS.md`.

## Reconcile with the existing patrol function prompt (binding)

`prompts/functions/patrol.yaml` already defines a *Patrol behavior* function
prompt (`id: patrol` — "treat patrol or route completion as ongoing work;
social actions can wait until an idle checkpoint; report blockers instead of
improvising a new route"). `TOOL_ROAM` reuses that lineage — roam is patrol
on a bounded budget — extending the prompt rather than adding a parallel
function, and keeps its rule that social actions wait for idle checkpoints
(CURIO-1's remarks ride those checkpoints). The prompt file is digest-pinned
by the SI rules: a text change bumps `SI_VERSION` and registers digests per
`prompting.py`'s own rule (see OWNER_PROMPT_EDIT_PINS_FABLE.md) — prefer
config keys over prompt edits where the behaviour allows.
