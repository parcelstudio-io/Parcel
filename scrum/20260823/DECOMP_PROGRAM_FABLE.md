# DECOMP — the decomposition program · design (Fable) · 2026-08-23

Owner directive (supersedes tranche-2 feature waves): **decompose the
codebase first** — "the code is too cluttered and some files are too big to
even follow." Tranche-2 waves B–D are cancelled; wave A (NARR-1/EAR-1)
drains, verifies, lands, and then every executor slot belongs to this
program. Opus implements, Fable verifies.

## 1. Relationship to Sol 5.6's ARCH-1

Sol's packet (scrum/20260823/task_1/) is the accepted foundation — my
verdict (FABLE_VERDICT.md, ACCEPT_WITH_REQUIRED_CHANGES) verified its
census exactly and its D01–D25 register stands. What changes now: the
owner has re-prioritized the maintainability axis, so the god-object
splits my verdict deferred move to the FRONT, under the verdict's binding
rules (facade preservation; oracle-porting in the same card; one
runtime.py card at a time; a split must reduce state ownership or
coupling, never merely relocate lines; mirror-dict aggregation is replaced
by immutable snapshot handoff, not moved).

Verified facts that shape the order (workflow wf_39e2697d):
- The 62-module SCC exists ONLY through 39 re-exporting `__init__`
  barrels; bypassed, the largest true cycle is 4 modules. **Import
  hygiene is the cheapest, largest win and unlocks everything else.**
- `runtime.py` imports 99 of 317 intra-package modules; RobotRuntime =
  14,942 lines, 345 methods, **269 mutable attributes** in a 1,333-line
  `__init__`, 6 locks, 17 re-entry callbacks, per-tick mirror-dicts.
- 186 test modules pin source shape; `test_r24_lock_discipline` pins
  literal lock construction inside `RobotRuntime.__init__`; digest pins
  cover the stop predicates. **Extraction without oracle-porting reddens
  the safety suite; oracle-porting without classification fossilizes
  incidental pins.**
- ~993 card-history markers live in product source — the marked-region
  idiom that made shared-file work safe is ALSO the clutter the owner
  feels. Decomposition dissolves regions into owned modules; the history
  moves to scrum/ADRs, not into new files.

## 2. Best-practice methods added on top of Sol's register

Sol's DESIGN says *what* to split (state/clock/lifecycle owners). These
are the *how* rules, binding for every DEC card:

- **M1 — Leaf imports, thin barrels, enforced direction.** Two-step:
  migrate importers to leaf modules while barrels still re-export (zero
  breakage), then thin the barrels and land an import-linter-style
  forbidden-edge + no-new-cycle test. Package `__init__` may keep
  `__all__` re-exports ONLY for the public compatibility surface named in
  the API census.
- **M2 — Protocols at boundaries.** Where a collaborator is passed in,
  type it as a `typing.Protocol` (structural), not a concrete class —
  backends, sinks, providers, stores. No new ABC hierarchies; Protocols
  are checkable, minimal, and untangle import direction (the consumer
  owns the Protocol, the implementer imports nothing).
- **M3 — Frozen dataclasses for every cross-boundary handoff.** State
  crosses a seam as an immutable snapshot (`@dataclass(frozen=True,
  slots=True)`), never as a live reference or a mutated dict. This is the
  verdict's mirror-dict rule generalized: a facade serves snapshots by
  handoff or delegated read, never by per-tick copying under a lock.
- **M4 — Builders, not a service locator.** `RobotRuntime.__init__`'s
  269 attributes decompose into per-subsystem builder functions returning
  frozen service bundles; construction order becomes explicit and
  testable; the facade keeps the public methods and delegates. A builder
  takes (config, deps) and returns its bundle — no builder reaches back
  into the runtime.
- **M5 — Pure functions first.** Every card extracts in the order: pure
  calculations → state owner → I/O (Sol's method §3). Module-level
  helpers trapped in god files (e.g. `scene_report`/`scene_fact_lines`,
  ~500 lines of pure rendering in runtime.py) leave first; they need no
  oracle-porting and shrink files immediately.
- **M6 — Package-by-feature, not layer dumping grounds.** Extracted code
  moves INTO its feature package (`parcel_robot/mission/`,
  `parcel_robot/interaction/`, existing `navigation/`, `realtime/`) —
  never into `utils/`, `helpers/`, or a `runtime2.py`. One module = one
  owner concept; target ≤600 lines/module for NEW modules (the accepted
  ratchet's 1,000 is the ceiling, not the target).
- **M7 — Region markers dissolve on extraction.** When a marked region
  moves into an owned module, the marker dies; the module docstring
  carries the one-line invariant (not the history — history lives in
  scrum/). Net marker count must go DOWN every card.
- **M8 — Typed events over re-entry callbacks.** Where extraction meets
  one of the 17 `on_*=self._method` wirings, prefer a bounded queue of
  frozen events drained at a named point over synchronous re-entry —
  ONLY when the existing semantics allow deferral; otherwise keep the
  callback and port the r24 roster entry.
- **M9 — Metrics per card, ratcheted.** Every DEC status doc reports:
  source-file lines before/after, facade method/attr count, module count
  touched, marker count, import fan-out of the source file, cycle count.
  A card that moves lines without reducing an ownership metric is
  rejected at verification (verdict rule 9).

## 3. The card sequence

Wave order respects: one runtime.py toucher at a time; wave-A files
(lane.py, driver.py, voice_audio.py, runtime whisperer region) are locked
until wave A lands; safety oracles green with zero unexplained re-pins.

**DEC-0 (task_14) — oracle & API classification (read-mostly, NOW).**
The A19 registry the verdict required: classify the 186 source-shape test
modules' pins into supported-contract / transitional / incidental over
the files this program will touch first (runtime.py, pipeline.py,
lane.py, audio_gateway.py, web_panel.py, agent.py, tool_broker.py,
ci_gate.py); enumerate the public import/API surface (what external
callers, configs, tests, UI actually use); land the debt-ratchet test
(no new >1,000-line module, no new >100-line function, no new cycle,
baseline = today's measured numbers). Output: DEC0_REGISTRY.md +
tests/test_dec0_debt_ratchet.py. No product-file edits.

**DEC-IG-1 (task_15) — leaf-import migration, non-locked packages (NOW).**
Migrate importers OF barrels to leaf imports in: navigation/, brain/,
online_map/, camera_channel/, detection_adapter/, instructnav/,
commissioning/, control/, backends/, lidar/, maps/, route_memory/,
scene_semantics/, city_semantics/, vlm_veto/, perception_abstention/ —
excluding runtime.py, agent.py, web_panel.py, realtime/*, voice* (locked
or next-wave). Barrels keep re-exporting (nothing breaks). Mechanical,
behavior-free; import cycles measured before/after.

**DEC-IG-2 — remaining importers + barrel thinning + the ratchet.**
After wave A lands: runtime.py/agent.py/web_panel.py/realtime imports go
leaf; barrels thin to the DEC-0 public surface; forbidden-edge +
no-new-cycle test lands (the A06 cycles — runtime↔runtime_channels,
config↔skills via barrel, camera backends 4-cycle — each either broken or
explicitly grandfathered in the baseline).

**DEC-R1 — runtime.py: the pure exodus.** M5 applied to runtime.py only:
scene report/fact rendering, config DTO helpers, pure geometry/formatting
trapped in the class file move to owned modules; zero state moves; the
file shrinks by measured thousands of lines with no oracle movement.

**DEC-R2 — runtime.py: assembly builders (D01 first half).** The
1,333-line `__init__` becomes per-subsystem builders returning frozen
bundles (M4); RobotRuntime keeps construction ORDER and the public
surface; the r24 lock roster PORTS in the same card (locks may be
constructed by builders; the oracle follows them).

**DEC-N1 — pipeline.py: DirectiveNavigator pure leaves (D05 start).**
Arrival verification, semantic resolution scoring, geometry — pure
functions out first; the 113-attr reducer split follows in DEC-N2 with
replay parity.

**DEC-L1 — lane.py reducers (D09 start)** and **DEC-A1 — audio_gateway
shared-state split (D06 start)** follow, one per wave, same method.

Further cards (mission services D03, web_panel routes D12, ci_gate D16,
tool registry D10) continue the register in dependency order; every fifth
card, CODEBASE_INDEX regenerates and the owner gets a metrics summary
(total lines in >1,000-line files, marker count, cycle count — the
"can I follow it now" numbers).

## 4. What is deliberately NOT in scope
No behavior change, no config-default change, no new features (owner
directive), no test deletion without a classified replacement (N04), no
`utils/` dumping ground, no rewrite of ControlManager (D07 post-gateway
decision stands), no touching the frozen eval baselines.

## 5. Integration handoff (2026-08-23 ~20:20)
Wave 1 (DEC-0 ACCEPT · DEC-IG-1 ACCEPT-WITH-NOTES) closed under parcel-6c;
DEC-0 committed as cf55751 by session parcel-fb, which — on the owner's
direction — now integrates the program: Opus executes DEC-IG-2 (task_16) →
DEC-R1 (task_17) → onward; parcel-fb verifies and commits. parcel-6c remains
design owner and second Fable verifier on request. Tranche-2 wave A
(NARR-1/EAR-1) never executed (executors died at dispatch) and stays
cancelled until DECOMP delivers. Verifier verdicts live in
~/.cache/parcel-verify/<card>/VERDICT.md.
