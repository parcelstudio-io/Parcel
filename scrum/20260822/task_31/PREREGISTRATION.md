# CAP-1 — pre-registration of the four cross-check guards

**Written BEFORE any code.** Executor: Claude Opus (session cap-1).
Tree at write time: `git rev-parse HEAD` = `21ea2fb`, working tree dirty with
five other wave-2 cards' work under disjoint OWNS.

The rule this file exists for: a guard invented after the code it guards
proves that the code is self-consistent, not that the property is true. So the
four properties, their derivation, and the seed that must turn each one RED are
written down here first, and the status doc carries this file's sha256.

Every seed is applied to the **PRODUCT**, on a byte-identical scratch copy of
`src/` under `/home/jaewoo-jang/.cache/parcel-cap1/seed/`, never to the test.
`__pycache__` is purged before and after each seed run.

---

## The class of defect

Week 1 produced the same failure four times: a feature complete at its
mechanism and dead at its door.

| # | The door | What it refused | Found by |
|---|---|---|---|
| 1 | `safety.BEHAVIOR_MODES` | `TOOL_ROAM`'s `set_behavior(mode="roam")` — "Unknown behavior: roam" | AUDIT_WEEK1_FABLE ROAM-1 finding 1 |
| 2 | `config.OVERLAY_INTRODUCIBLE_KEYS` | the prototype overlay's `roam:` block, which `_roam_limits` reads | ROAM-1 finding 6 |
| 3 | `PROACTIVE_MOTION_ALLOWED` / `REFUSED` | nothing yet — the sets are only checked against `MOTION_TOOLS` by one card's own test | P0-B / ROAM-1 |
| 4 | the process-global semantic candidate source | nothing — it silently stays `oracle` while a YAML says otherwise | `backlog/NEXT.md` "Active worktree delta" |

Nothing in the tree checks these doors against each other or against what the
runtime was configured to run. CAP-1 builds the view and the four checks. It
adds **no new refusal at runtime** (standing rule 1): the only new fatal path
is a startup configuration-truth check that is keyed by an explicit
`required_capabilities:` declaration and is inert when nothing is declared.

---

## G1 — every behavior name the broker routes to is admitted by the supervisor

**Property.** For every `(door, behavior-name, tool)` triple that
`realtime/tool_broker.py` routes through `SafetySupervisor.validate`:

* a `set_behavior` mode is a member of `parcel_robot.safety.BEHAVIOR_MODES`;
* a `run_spatial_behavior` behavior is one of the names
  `SafetySupervisor._validate_spatial_behavior` compares against;
* and a **real, product-constructed** `SafetySupervisor` (not a stub) approves
  each `set_behavior` mode on the un-latched owner path.

**Derivation, not declaration.** The triples are read out of the broker's own
source by AST: every call `self._validated(ToolCall(<door>, {...}), <TOOL_*>)`.
A hand-written mapping would have missed ROAM-1 exactly as the card's own stub
validator did — whoever adds the tenth tool would not think to add the row.

**Seed → RED.** Delete `"roam"` from `BEHAVIOR_MODES` in the scratch copy.
Expected: G1 fails naming mode `roam`, tool `roam`, door `set_behavior`, and
the product supervisor's refusal string.

## G2 — every config section a runtime region reads is loadable by the overlay

**Property.** For every literal `X` in `self.store.section("X")` anywhere in
`runtime.py`, `X` is either a key of the SHA-locked base `configs/robot.yaml`
or a member of `config.OVERLAY_INTRODUCIBLE_KEYS`; and the shipped prototype
overlay still loads (`ConfigStore(configs/robot.yaml, profile="prototype")`
raises nothing).

**Derivation.** AST over `runtime.py` for `Attribute(store).section(<str>)`.

**Seed → RED.** Delete `"roam"` from `OVERLAY_INTRODUCIBLE_KEYS` in the scratch
copy — i.e. restore ROAM-1 finding 6 verbatim. Expected: G2 fails naming
`roam`, and the shipped prototype overlay stops loading.

## G3 — every motion tool has exactly one proactive verdict

**Property.** `set(PROACTIVE_MOTION_ALLOWED)` and
`set(PROACTIVE_MOTION_REFUSED)` are disjoint, neither tuple repeats an entry,
their union is exactly `tool_broker.MOTION_TOOLS`, and the allowed set is
exactly `tool_broker.PROACTIVE_MOTION_CEILING` — so the config-load door and
the hand-constructed-broker door cannot disagree.

**Seed → RED.** Delete `"roam"` from `PROACTIVE_MOTION_REFUSED` in the scratch
copy. Expected: G3 fails naming `roam` as a motion tool with no verdict.

## G4 — the candidate source bound at startup is the one the YAML names

**Property.** After `RobotRuntime.start()` on the product path,
`perception_source.active_semantic_source().source` equals the source named by
the navigation config the robot profile selects (`navigation.config` →
`perception.semantic_source`), and `poi_grounding_enabled` follows from it.
Measured for `learned_map` and for the shipped `oracle`.

**Seed → RED.** Delete the `use_semantic_source(policy)` line from
`RobotRuntime._p1b_install_learned_map` in the scratch copy — the backlog's
defect exactly ("a YAML value can disable the demo POI oracle while the
process-global semantic candidate source remains the default oracle").
Expected: G4 fails with configured `learned_map` vs bound `oracle`.

---

## The startup-fatal required-capabilities check (IG-3, narrowed)

**Shape.** A `required_capabilities:` list in the navigation profile — the
same file that already names `perception.semantic_source`. **Absent ⇒ nothing
is required ⇒ nothing changes for anyone who does not declare**, which is the
standing rule's "no new fail-closed defaults at runtime". Declared but unknown
capability names are refused by name at startup (a spelling check on a
declaration, not a behavioural refusal).

**Product path, three arms, all through `RobotRuntime.start()`:**

* **A (refuses).** Profile declares `required_capabilities: [learned_map_source]`
  while `perception.semantic_source` is the shipped `oracle` → `start()` raises
  `CapabilityRefused`, the message names the capability and prints the
  admission table, and the runtime is closed.
* **B (starts).** Same declaration, `perception.semantic_source: learned_map` →
  the learned source is bound and `start()` returns.
* **C (the defect, seeded in the PRODUCT).** Arm B's YAML with
  `use_semantic_source(policy)` deleted from the runtime → the process-global
  stays `oracle` while the YAML says `learned_map`; arm B must flip from
  starting to refusing. This is the row that shows the check catches the real
  startup defect rather than only a mis-declared profile.
* **D (inert).** No `required_capabilities:` anywhere → byte-identical
  behaviour; the shipped `configs/navigation/default.yaml` path starts.

## `/api/state`

`runtime.snapshot()["admission"]` carries the table (entry, admitted, reason,
source-of-truth) so an operator can see WHY a tool or behavior is unavailable;
`["curiosity"]` carries CURIO-1's `curiosity_snapshot()`, which had no product
surface at all. `curiosity` is absent — not `null` — when chatter is off, the
same discipline C-1's `camera_ingress` key follows.

## What this pre-registration does NOT claim

* No claim about hardware. No robot is on hand; nothing here starts a
  simulator, opens a socket, or spends on a hosted model.
* G1–G3 are static views over source and constants. They prove the doors agree
  with each other; only G4 and the startup arms run the product's own startup.
* The admission table is a VIEW. It changes no refusal, and a `False` row in it
  is a report, not a new gate.
