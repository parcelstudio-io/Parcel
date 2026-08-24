# DEC-0 — oracle & API classification registry

Program: `scrum/20260823/DECOMP_PROGRAM_FABLE.md` §3. This is the A19
registry required by `scrum/20260823/task_1/FABLE_VERDICT.md` required
change 5: **classify supported-vs-incidental pins before any runtime
extraction, not during.**

Measured on HEAD `92245a1`, 2026-08-23. Two wave-A executors (NARR-1:
`lane.py`/`driver.py`/runtime whisperer region; EAR-1: `voice_audio.py`
+ configs) were editing the tree concurrently — line numbers in
`realtime/lane.py`, `realtime/audio_gateway.py` and the runtime whisperer
region are **volatile**; every pin below is keyed by *test file:line*
(stable, since no wave-A card owns `tests/`) and names its product target
by symbol rather than by product line number wherever possible.

---

## 0. How to read this, and what a card must do with it

Every row classifies one pin into exactly one of three buckets:

| class | meaning | what a DEC card owes it |
|---|---|---|
| **SUPPORTED-CONTRACT** | pins public behavior or a real invariant the program must keep | **Keep the guarantee.** The assertion may be rewritten, the guarantee may not weaken. |
| **TRANSITIONAL** | pins the *location* of code that is about to move | **Port it in the same card** (verdict rule 5). The named porting rule is the card's obligation. |
| **INCIDENTAL** | the same guarantee is available from a behavior test | **Replace with the named behavior assertion**, then delete the source pin (N04: no test deletion without a classified replacement). |

Three findings dominate the program's risk and are called out before the
per-file tables because they change the shape of the work:

**F1 — The most dangerous pins do not redden; they go vacuously green.**
Several structural oracles scan a hard-coded path list or walk only
`class RobotRuntime` in `runtime.py`. When code moves out, the scan stops
seeing it and *passes*. A card that watches only for red will ship a
silently unguarded safety property. The affected oracles are marked
**VACUITY RISK** below; each one already carries, or needs, an
anti-vacuity floor (a "the scan matched at least N things" assertion).
The floors are what convert these from silent holes into honest reds.

**F2 — One product file must be edited by nearly every extraction card.**
`src/parcel_robot/admission.py:400-410` (`_PRODUCT_CONFIG_SOURCES`) and
`:389` (`_RUNTIME_REGION_SOURCES`) are hand-written filename rosters that
`tests/test_cap1_admission.py:267-276` checks for completeness. Any
extracted module containing `store.section(` must be added to them in the
same commit. This is the single most likely surprise-red of the program,
and it is a one-line product edit — but it means "no product-file edits"
is not achievable for extraction cards, only for DEC-0.

**F3 — The r24 lock roster is stale by one, in prose only.**
`tests/test_r24_lock_discipline.py:70` says "The seven locks"; the
`RUNTIME_LOCKS` tuple at `:93` has **eight** entries (P1-B added
`_p1b_map_lock` and updated the tuple and the changelog but not the
opening sentence). The ARCH-1 packet and the verdict both say "6 locks".
The authoritative count is **8**, asserted complete against
`RobotRuntime.__init__` at `:550`. DEC-R2 should fix the prose while it
ports the roster.

---

## 1. Ratchet baseline (measured, frozen in `tests/test_dec0_debt_ratchet.py`)

Scope: `src/parcel_robot/` + `scripts/` + `tools/`, `*.py` only — 364
files. `tests/` is deliberately excluded (test bulk is not the debt this
program retires).

| quantity | baseline | notes |
|---|---|---|
| modules > 1,000 lines | **45** | 30 in `src`, 12 in `scripts`, 3 in `tools` |
| functions > 100 lines | **153** (140 distinct leaf names) | keyed by leaf name and per-name occurrence count so debt may MOVE without reddening, but a duplicate cannot replace another offender |
| import cycles, package-edge model | **25** (largest **81**) | models real Python semantics: importing `pkg.mod` executes `pkg/__init__.py` |
| import cycles, leaf-only model | **8** (largest **4**) | barrels bypassed |
| `# ---- CARD` markers | **178** | 143 `src`, 34 `scripts`, 1 `tools` |

**The leaf-only maximum SCC of 4 independently reproduces the verdict's
central census refinement** ("barrel-bypassed, the largest true SCC is 4
modules") from a resolver written from scratch for this card. The eight
true cycles are:

| size | cycle |
|---|---|
| 4 | `perception_abstention` ↔ `vlm_veto.{bureau,runner,verifier}` |
| 4 | `navigation` ↔ `navigation.envs` ↔ `navigation.envs.metaurban_env` ↔ `navigation.pipeline` |
| 4 | `camera_channel.backends.{physical,realsense,recorded,uvc}` |
| 4 | `commissioning` ↔ `commissioning.session` ↔ `control` ↔ `control.factory` |
| 2 | `navigation.arrival_semantics` ↔ `navigation.goals` |
| 2 | `navigation.grid_navigator` ↔ `navigation.models` |
| 2 | `owner_model` ↔ `owner_model.distiller` |
| 2 | `runtime` ↔ `runtime_channels` |

These are exactly the cycles DEC-IG-2 must "each either break or
explicitly grandfather". The package-edge model's 81-module SCC differs
from the packet's 62 because this resolver charges every *ancestor*
package on the import path, not only the directly-named barrel; the
direction and the mechanism are identical, the magnitude is
model-dependent. Both numbers are ratcheted so neither can grow.

**Marker-count reconciliation.** The verdict recorded ~993 card-history
markers (773–1,157 by pattern) and did not reproduce the packet's exact
993. That band counts a *broad* card-history comment idiom; the precise
`# ---- CARD` region-marker string appears **178** times in `.py` files
(plus 4 in `scripts/install_speech_services.sh`, out of scope). The
ratchet pins the precise idiom because it is the one M7 dissolves. A
broader "any card-history comment" count over `src/parcel_robot` is
**340** by the pattern `#.*(scrum/<date>/task_|CARD <X>-<n>)` — recorded
here so a later card can ratchet that too without re-deriving it.

---

## 2. `src/parcel_robot/runtime.py` — 16,724 lines

`RobotRuntime`: 15,195 lines, 350 methods, 275 mutable attributes in a
1,393-line `__init__`, **8** locks, 17 re-entry callbacks + 4 lambda
callback keys over 7 sites.

### 2.1 `tests/test_r24_lock_discipline.py` — the heaviest oracle

Everything in this file is scoped to `class RobotRuntime` as a **top-level
`ClassDef` in `runtime.py`**, via `LockOrderScan(RUNTIME_PATH.read_text(),
locks=RUNTIME_LOCKS, class_name="RobotRuntime")` (`:526-531`, `tree.body`
lookup at `:295-301`). That single binding is what makes the whole file
transitional.

Rosters: `RUNTIME_LOCKS` 8 (`:93`), `COMPOUND_REALTIME_FIELDS` 7 (`:125`),
`NAVIGATOR_MUTATIONS` 6 (`:143`), `PINNED_LOCK_ORDER` 6 edges (`:179`),
`CALLBACK_LOCK_ORDER` 2 (`:203`), `REENTRY_CALLBACKS` **17** (`:224`),
`REENTRY_LAMBDAS` 4 keys / 7 sites (`:256`).

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `:550` | AST | the literal set of `threading.Lock()/RLock()` assignments to `self.*` **inside `RobotRuntime.__init__`** equals `RUNTIME_LOCKS` — `assert constructed == set(RUNTIME_LOCKS)`, driven by `ast.walk(init)` at `:537-548` | **TRANSITIONAL** | **This is the verdict's named r24 pin.** When lock L moves to a builder/collaborator, `LockOrderScan` must become multi-class (one scan per owning class) and `RUNTIME_LOCKS` a `{class → locks}` map. Keep the roster; only re-point it. A pure move reddens with a *misleading* "constructs a lock this file does not order". |
| `:898` | AST + ROSTER | **the 17 re-entry callbacks**: every `on_*=self.<method>` keyword anywhere in `RobotRuntime.__init__`, mapped to `(handler, locks_reachable(handler))`, equals `REENTRY_CALLBACKS` — `assert found == REENTRY_CALLBACKS` | **TRANSITIONAL** | Built by `ast.walk(scan.methods["__init__"])` at `:882-897`; `locks_reachable` resolves only `self.<m>` edges within `RobotRuntime`. When collaborator group G's wiring moves to module M, split the roster per constructor and compute `locks_reachable` across the union of extracted classes — otherwise entries silently drop and are reported as "removed". M8 applies: prefer typed events only where deferral is semantically allowed, else keep the callback and port the row. |
| `:947` | AST + ROSTER | the lambda half: every `on_*=lambda …` **anywhere in runtime.py** (module-wide `ast.parse` at `:928`), keyed by `(keyword, sorted call targets)`, equals `REENTRY_LAMBDAS` | **TRANSITIONAL** | Scans the whole file, so it reddens the instant any `on_*=lambda` site leaves `runtime.py`. Re-key by `(module, keyword, targets)` and iterate the extracted module set. |
| `:574` | AST | lexical nesting edge set equals `PINNED_LOCK_ORDER` (6 edges) | **SUPPORTED-CONTRACT** | Invariant: lock acquisition order is a fixed, stated, acyclic DAG; extraction must not add an edge. The *scanner* is transitional (one class, one file). |
| `:562-568` | AST | `find_cycle(scan.edges() ∪ CALLBACK_LOCK_ORDER)` is empty | **SUPPORTED-CONTRACT** | Invariant: no two-lock deadlock is constructible. |
| `:595` | AST | `_agent_lock` is a source (no inbound edges); no `_agent_lock` taker holds `_command_lock`/`_navigation_lock` | **SUPPORTED-CONTRACT** | Invariant: the agent lock is outermost; a back-edge closes the R24 cycle. |
| `:611` | AST | `_realtime_navigate` / `_realtime_follow` / `_realtime_orbit` each have a body that is **one single `with self._agent_lock:`** (checker `:464-470` allows docstring + one `With`) | **SUPPORTED-CONTRACT** | Invariant: the three hosted motion doors mutate VoiceAgent state only under `_agent_lock`, whole-body, no prologue. Brittle to any re-shaping — a card that delegates the body must re-express the invariant, not drop it. |
| `:638` | AST | interprocedural `methods_reachable(door)` never reaches `set_personality`/`handle_text`/`handle_text_guarded` | **SUPPORTED-CONTRACT** — **VACUITY RISK** | Invariant: no self-deadlock on the non-reentrant `_agent_lock`. Reachability is computed only over `self.<m>()` edges within one class; extraction to `self.collaborator.m()` makes it blind → green-but-vacuous. |
| `:658` | AST | every write to the 7 `COMPOUND_REALTIME_FIELDS` outside `__init__` is lexically inside `_lock` | **SUPPORTED-CONTRACT** — **VACUITY RISK** | Invariant: compound cross-thread realtime state is written under `_lock`. |
| `:687` + `:701` | AST | every *read* of the same fields is inside `_lock`, **and** the scan matched ≥5 named fields | **SUPPORTED-CONTRACT** | Invariant: the panel cannot observe a torn/cleared compound record. The `covered >=` floor at `:701` is the anti-vacuity guard — it is what turns green into evidence. **Keep and raise floors like this one; they are the program's safety net.** |
| `:725` + `:733` | AST | `_realtime_follow` takes `_lock` exactly once, and that section assigns all three of `_realtime_pace_intent` / `_..._at_s` / `_realtime_last_pace` | **SUPPORTED-CONTRACT** | Invariant: the pace declaration and its timestamp publish as one atomic section. |
| `:758` + `:762` | AST | every call matching `NAVIGATOR_MUTATIONS` is inside `_navigation_lock`; scanner matched ≥1 `self.dog.navigate()` | **SUPPORTED-CONTRACT** (with incidental edge) | Invariant: the navigator is never mutated concurrently with `_step_navigation`. The `("navigator", …)` entries pin a **local variable name** in `_start_or_resume_navigation_locked` — that part is incidental brittleness inside a real invariant. |
| `:773-780` | ROSTER | `vars(_LockedNavigationChannel)` contains `pause`/`resume`, does **not** contain `stop` | **SUPPORTED-CONTRACT** | Invariant: pause/resume are locked at the adapter; `stop` deliberately is not (wrapping it would add a `_navigation_lock→_lock` edge). |
| `:801-807` | ROSTER (live) | `runtime._channels["navigation"]` is a `_LockedNavigationChannel` whose `._nav_lock is runtime._navigation_lock` | **SUPPORTED-CONTRACT** | Invariant: the locked adapter is actually *installed*, not merely defined. Depends on private names `_channels`/`_navigation_lock` staying on the runtime object. |
| `:908` | ROSTER | `REENTRY_CALLBACKS["on_stop"][1]` contains `_command_lock` | **SUPPORTED-CONTRACT** | Invariant: `motion.on_stop → stop_motion → _command_lock` is the edge `_stop_navigation_channel`'s safety comment rests on. |
| `:953` | AST | `_lock` has no outgoing edges — it is a sink | **SUPPORTED-CONTRACT** | Invariant: "every lambda only reaches `_lock`" is a safety argument only while `_lock` is a sink. |
| `:992` | AST | no `self.dog.stop()/emergency_stop()` under `_navigation_lock` without `_command_lock` held | **SUPPORTED-CONTRACT** — **VACUITY RISK** | Invariant: the R24 two-lock cycle stays closed. |
| `:1020` + `:1025` | AST | exactly **2** `self.dog.navigate()` sites under `_navigation_lock`, each passing literal `publish=False` | **SUPPORTED-CONTRACT**, count is **INCIDENTAL** | Invariant: a publishing navigate under `_navigation_lock` re-enters `_command_lock`. Replace the `== 2` count with: drive a navigate under the lock with a motion router that records `on_command` firings, assert zero. |
| `:1061` | AST | no call in the 6-name `reaching` set runs under `_lock` | **SUPPORTED-CONTRACT** | Invariant: `_lock → _navigation_lock` is never stated. The set hard-codes local variable names (`channel`, `channel_obj`) — incidental brittleness inside a real invariant. |
| `:1553-1554` | ROSTER (live) | every `RUNTIME_LOCKS` name is a settable/gettable attribute **on the RobotRuntime instance**, replaced by an observer wrapper | **TRANSITIONAL** | When locks move onto sub-objects, walk `(owner, name)` pairs instead of `getattr(runtime, name)`; otherwise the observation graph silently shrinks and the floors at `:1595-1603` redden. |

Not pins: `:1124-1208` (seven seeded-violation tests over the inline
`_SEED_CLEAN` string), `:1404` (live concurrency evidence).

### 2.2 `tests/test_nominal_stop_wiring.py` — the stop-predicate digests

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `:923` | DIGEST | sha256 of `ast.unparse` of **7 runtime.py symbols** — `RobotRuntime._dispatch_active` (`:868`), `._finalize_for_actuator` (`:871`), `._nominal_stop_ramp_tick` (`:874`), `._regate_nominal_stop` (`:878`), and module-level `_is_zero_command` (`:883`), `_finite_command_values` (`:886`), `_command_translates` (`:889`) — plus 5 symbols in `evals/companion_nav/runner.py`. Roster `STOPPING_PREDICATE_PIN` at `:866`; `assert not drifted` at `:923` | **TRANSITIONAL** | Symbol lookup is `for node in ast.parse(source).body` (`:784`, `:791`) — **top-level only**. Moving `RobotRuntime` under a wrapper, or the three module-level helpers to a new module, raises `AssertionError("<name> not found")` rather than a digest mismatch. Porting rule: add key `"src/parcel_robot/<M>.py"` with the **same digests** (`ast.unparse` is position-independent, so a pure move re-verifies bit-for-bit) and delete the old `runtime.py` key in the same commit. The invariant — runtime and bench replica classify stops identically — is real and must be KEPT. |
| `:948` | SOURCE-TEXT | exact substring `zero_intent = active is not None and _is_zero_command(active.command)` appears in `_dispatch_active` | **INCIDENTAL** | Replacement: dispatch a zero-*intent* whose post-chain command is non-zero, assert `NOMINAL_STOP` severity is selected (classification reads the intent, not the command). Already covered behaviourally at `:340`/`:395`. |
| `:949` | SOURCE-TEXT | substring `nominal_ramp = ` appears in `_dispatch_active` | **INCIDENTAL** | Asserts nothing about semantics. Same replacement as above. |
| `:952-956` | SOURCE-TEXT | substrings in `evals/companion_nav/runner.py::_DispatchReplica._shape_severity_split` / `._shape` | **TRANSITIONAL** | Not `runtime.py`, but the replica-parity *claim* moves with `_dispatch_active`; re-point in the same card. |

### 2.3 Control-loop and identity oracles

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_nm1_promotion_and_asks.py:394` | AST | `_control_loop` exists as a key in the call graph derived from `class RobotRuntime`; `assert "_control_loop" in edges, "the control loop was renamed; fix this test"`. Graph built `:341-370` | **TRANSITIONAL** | When the loop moves to M, `_runtime_call_graph()` must union classes across `{runtime.py, M, …}` and resolve `self.<collaborator>.<m>()` edges, or the FATAL guard below shrinks to nothing. |
| `tests/test_nm1_promotion_and_asks.py:396` | AST | anti-vacuity floor: transitive closure from `_control_loop` reaches **>20** methods | **SUPPORTED-CONTRACT** | **The row that makes extraction dangerous and honest.** Decomposition mechanically shrinks the intra-class closure, so this reddens on a behavior-identical move — and that redness is the correct signal that the guard stopped covering the loop. Do not lower the floor; extend the walker. |
| `tests/test_nm1_promotion_and_asks.py:405` | AST | no method transitively reachable from `_control_loop` makes an attribute call in `FATAL_ON_THE_LOOP` (28 names: model constructors, `warm_up`, `veto_for`, `judge`, `imencode`, `urlopen`, `from_pretrained`, …) | **SUPPORTED-CONTRACT** | Invariant DW-2a: no model inference, weight load, image encode or network call is reachable from the 10 Hz loop. Port the walker with the loop. |
| `tests/test_nm1_promotion_and_asks.py:564` | AST | runtime.py's module-wide import set contains nothing under `parcel_robot.vlm_veto`, `torch`, `transformers` | **SUPPORTED-CONTRACT** — **VACUITY RISK** | Path literal at `:550`; extracted modules are not scanned → goes vacuously green. Grow to the extracted module set or replace with a package-wide walk, in the same card. |
| `tests/test_nm1_promotion_and_asks.py:425`,`:426` | SOURCE-TEXT | `_control_loop` source contains literals `mark_control_thread()` / `clear_control_thread()` | **INCIDENTAL** | Already proved behaviourally on a live thread at `:438-442` and `:446`/`:469`. Delete the two source greps, keep the live-thread arms. |
| `tests/test_nm1_promotion_and_asks.py:1096` | ROSTER (live) | `door.__func__ is RobotRuntime._realtime_ask_place` and `door.__self__ is runtime` | **TRANSITIONAL** | Invariant kept: the ASK door is bound directly, no motion/voice-gating wrapper. Re-point at the extracted facade's unbound method — an `is`-identity check, so a re-export alias passes and a wrapper still correctly fails. |
| `tests/test_p1d_vlm_veto.py:392-399` | AST via `inspect.getsource` | no attribute-call name in `_dispatch_active` or `_step_navigation` is in `LOOP_FORBIDDEN_CALLS` | **SUPPORTED-CONTRACT** | Invariant: no VLM/model call on the 10 Hz dispatch path. Mechanism **survives** a clean move (`getsource` follows the class attribute) as long as the method stays reachable as `RobotRuntime.<name>`. NM-1 `:405` supersedes it with a whole-graph walk. |
| `tests/test_p1d_vlm_veto.py:416` | AST | runtime.py's import set contains nothing starting `parcel_robot.vlm_veto` | **SUPPORTED-CONTRACT** — **VACUITY RISK** | Path literal at `:408`; same silent-green failure mode as NM-1 `:564`. |
| `tests/test_ot2_identity.py:689`,`:693` | AST + SOURCE-TEXT | inside whichever of `_control_loop`/`_control_loop_body` contains `observation = self.backend.observe()`, the string offsets order `observe < self._ot2_apply_owner_identity(observation) < self._observation_sink` | **SUPPORTED-CONTRACT** | Invariant: the identity overlay lands between `backend.observe()` and every downstream reader — no consumer sees an un-overlaid track. Mechanism (`body.index()` on `ast.unparse` text, `:681-693`) is transitional; it already anticipates one rename via the `name in {…}` set at `:685`. |
| `tests/test_ot2_identity.py:699-700` | SOURCE-TEXT | the overlay call precedes `self.follow.observe_owner` and `self._record_owner_sighting` in the same body | **SUPPORTED-CONTRACT** | Invariant (card rule 3): follow/standoff consumers read the same measured track the gate reads. |
| `tests/test_ot2_identity.py:309-311` | ROSTER | `RobotRuntime.OT2_STATE_CONFIRMED/_AMBIGUOUS/_SEARCHING` exist as class attributes and equal the producer's constants | **TRANSITIONAL** | Invariant kept: one identity vocabulary across producer and consumer. Re-point at the extracted identity module (or keep re-exports on `RobotRuntime`). |
| `tests/test_ot2_identity.py:707` | SOURCE-TEXT | `_publish_camera_frame` contains `self._ot2_note_camera_frame(frame)` | **INCIDENTAL** | Replacement: push a frame through the live camera publish path, assert the OT-2 frame counter/last-frame stamp advanced — the file already does exactly this at `:890`. |
| `tests/test_ot2_memory_principal.py:428` | AST | whole-package walk: `set_owner_fact_consent` has exactly ONE product caller and it is literally `"runtime.py:_ot2_confirm_fact"` | **TRANSITIONAL** | The assertion string embeds the **file name**. Extracting `_ot2_confirm_fact` (runtime.py:9255) reddens with e.g. `["tools.py:_ot2_confirm_fact"]`. Port: update the expected token to `<newfile>.py:_ot2_confirm_fact`; keep the "exactly one" cardinality. |
| `tests/test_ot2_memory_principal.py:434` | AST | runtime.py parses to a `ClassDef RobotRuntime` whose `__init__` contains a `ToolDoors(…)` call wiring `remember_fact`/`confirm_fact` to `self._ot2_*` | **TRANSITIONAL** | Assumes the `ToolDoors` construction (runtime.py:2708) stays syntactically inside `RobotRuntime.__init__`. Reddens if door wiring moves to a builder (which is exactly DEC-R2's plan). Port: re-point `RUNTIME_PATH` (`:63`) and the ClassDef/`__init__` descent at the new composition site. |
| `tests/test_c1_camera_stream.py:762` | AST | `_offer_camera_pose`'s body calls none of `{set_pose,set_query,poll_once,start,stop,capture,detect}` | **SUPPORTED-CONTRACT** | Invariant: the 10 Hz loop never reaches the camera producer; safety never queues behind inference. |
| `tests/test_c1_camera_stream.py:1030` | AST | `close` calls `self._camera_ingress.stop()` before `self._session_evidence.close()` | **SUPPORTED-CONTRACT** | Invariant: the last in-flight frame reaches the evidence log. Matches attribute names inside ONE body — reddens if `close()` delegates teardown to a helper even with order preserved. |

### 2.4 Config-reachability pins (the F2 cluster)

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_cap1_admission.py:267-276` | SOURCE-TEXT | a text `rglob` of `src/parcel_robot/**/*.py` for `store.section(` yields a file set ⊆ `admission._PRODUCT_CONFIG_SOURCES` (9 filenames, `admission.py:400-410`) | **TRANSITIONAL** | **Highest-probability redden in the program.** Any extracted config-reading module reddens this until its basename is added. Port: one-line product edit to `_PRODUCT_CONFIG_SOURCES` in the extraction commit. |
| `tests/test_cap1_admission.py:196`,`:222` | ROSTER | `admission.runtime_config_sections()` contains `roam`/`navigation`; every returned name has an `admitted` row | **TRANSITIONAL** | The roster lives in the **product** (`admission._RUNTIME_REGION_SOURCES`, `admission.py:389`). Every extracted module carrying `store.section(...)` must be appended, or the guard stops covering it (silent weakening). |
| `tests/test_cap1_admission.py:183` | AST | sections found by AST-scanning `_RUNTIME_REGION_SOURCES` are in the SHA-locked base or in `OVERLAY_INTRODUCIBLE_KEYS` | **SUPPORTED-CONTRACT** | Invariant (ROAM-1 finding 6): every config knob a runtime region reads can actually be set by an operator. |
| `tests/test_cap1_admission.py:239-246` | AST | no `store.section(...)` call in runtime.py has a non-literal argument | **SUPPORTED-CONTRACT** | Invariant: no config read escapes the cross-check unnoticed. |
| `tests/test_cap1_admission.py:278-330` | AST | the wider survey finds an empty set of unreachable sections | **SUPPORTED-CONTRACT** | Invariant: no product file reads a section no overlay can introduce. |
| `tests/test_cap1_admission.py:251-253` | SOURCE-TEXT | `admission.py` literally contains `store.section(` (the "guard covers its own author" proof) | **INCIDENTAL** | Replacement: assert `"navigation" in admission.runtime_config_sections()` — already asserted at `:250`. |

### 2.5 Single-pin runtime.py modules

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_p1b_map_learns.py:503` | SOURCE-TEXT | exact two-line adjacency `"                learned.close()\n            self._p1b_persisted = written"` — **indentation-exact** (16 then 12 spaces), verified at runtime.py:13239-13240 | **TRANSITIONAL** | Any de-nesting (method → module function, extra `with`/`try`) reddens with behavior unchanged. Re-derive the literal from the moved body's real indentation. |
| `tests/test_p1b_map_learns.py:508` | SOURCE-TEXT | `_p1b_persist_learned_map` body, sliced to the next `"\n    def learned_map_snapshot"`, names `_p1b_close_learned_map` ≥3 times | **TRANSITIONAL** | The slice assumes 4-space class-method layout AND that `learned_map_snapshot` remains the next `def`. Marker and terminator must move together or the slice silently swallows the rest of the file. |
| `tests/test_p1b_map_learns.py:919` | SOURCE-TEXT | `_attach_configured_camera_ingress` body contains `pinned_queries=tuple(config.queries)`, `load_siglip2_embed_fn()`, `EvidenceOrigin.SIMULATION.value` | **TRANSITIONAL** | Same `"\n    def "` slice fragility. Source-read by necessity — the real path needs EGL+ONNX (docstring `:912-916`), so it cannot become a commit-tier behavior test. |
| `tests/test_p1b_map_learns.py:1024` | SOURCE-TEXT + ORDER | runtime.py contains all three P1-B seam calls, and `install_at < attach_at` by **byte offset** | **SUPPORTED-CONTRACT** | Invariant: the learned map is installed before the camera ingress attaches. Offsets are same-file — if install and attach land in different modules the comparison is meaningless or raises. Replace with an ordering assertion inside the single moved `start()` body, or a behavior probe on `start()`. |
| `tests/test_fixa_transcript_persistence.py:178` | SOURCE-TEXT | `RobotRuntime.__init__` source contains `submit_text=self._submit_microphone_text` | **TRANSITIONAL** | Port to whichever unit composes the mic loop; `getsource` target becomes that callable (runtime.py:1515 today). |
| `tests/test_follow_yield_wiring.py:362` | SOURCE-TEXT | runtime.py text contains the three `yield_aside` plumb lines (`pop` / `FollowYieldConfig.from_mapping` / `yield_aside=`) | **TRANSITIONAL** | Moves with the follow-config merge (runtime.py:1875). **Also uses a relative `Path("src/parcel_robot/runtime.py")`** — cwd-dependent, unlike every sibling's `REPO/…`. Fix while porting. |
| `tests/test_realtime_pump_survival.py:926` | SOURCE-TEXT | `_service_health_loop` source contains `self._watch_realtime_pump()` | **TRANSITIONAL** | The test states it is a source pin by necessity — a 10 s while-loop cannot run in the commit gate (`:913-917`). Port with `_service_health_loop` (runtime.py:10763). |
| `tests/test_realtime_spend_budget.py:848` | SIGNATURE | `RealtimeLane.narrate_event` and `RobotRuntime._narrate_mission` both accept a keyword-only `critical`, default `False` | **SUPPORTED-CONTRACT** | Invariant: the narration door and the lane agree on the keyword. A mismatch is swallowed by `_narrate_mission`'s `except (RuntimeError, TypeError, ValueError)` and the robot silently goes quiet. Survives a move if the door keeps its name; re-point the second lookup. |
| `tests/test_move1_patrol.py:516` | SOURCE-TEXT | `RobotRuntime.snapshot` source contains `'"heading": math.degrees('` | **INCIDENTAL** | Replacement: the same test already asserts the behavior at `:519-524`. Build a snapshot at yaw π/2, assert `heading == 90.0`. |
| `tests/test_e2_safety_wiring.py:494` | SOURCE-TEXT (negative) | runtime.py, in a 5-path allowlist, must not contain `person_stop_m…1.0` / `person_slow_m…2.0` literal fallbacks | **SUPPORTED-CONTRACT** — **VACUITY RISK** | Invariant: no construction path restates the retired clearance. A **negative** scan over a hard-coded path list: extraction makes it silently WEAKER, never red. The card MUST append every new module to the tuple at `:492-499`. |
| `tests/test_k6_voice_lanes.py:199` | ROSTER | `PHYSICAL_TOOL_NAMES ⊆ agent.MOTION_TOOLS` (`agent.py`) | **SUPPORTED-CONTRACT** | Invariant: every tool the safety layer calls physical is in agent's motion set. Survives a move while `MOTION_TOOLS` stays importable; only the import at `:12` needs updating. |

### 2.6 Not pins, but extraction-fragile (audit obligations, not ports)

These break or silently mislead on extraction without being shape pins:

- `tests/test_realtime_lane.py:962` — `_spy()` dispatches by
  `hasattr(runtime, name)` else `runtime.voice_session`, then
  monkeypatches (`submit_text`, `set_behavior`, `handle_text`,
  `:1078-1167`). If any of those moves onto a delegate that is **not**
  `voice_session`, the helper patches the wrong object and the spy list
  stays empty — a **silent false pass**, not a red.
- Direct private-attribute reads that break if the attribute moves onto a
  sub-object without a delegating property:
  `tests/test_hw5_physical_profile.py:898,917,951,960,967`
  (`runtime._require_physical_inputs`);
  `tests/test_prototype_profile.py:869-870,882-909`
  (`_camera_stream_enabled`, `_camera_ingress_enabled()`,
  `_camera_stream_config`, `_affect_minimum_confidence`);
  `tests/test_r24_lock_discipline.py:801` (`runtime._channels`).
- `tests/test_hw2_go2_backend.py` docstrings cite `runtime.py:1498, 4786,
  6210, 9551, 10295` and the marked region `# ---- CARD AWARE-1 … SENSE-1
  pose seam` (`:636`, `:706-709`, `:1395`, `:1456`, `:1643`). Prose only —
  no assertion — but every line number goes stale on the split.

### 2.7 Verified as carrying NO runtime.py shape pin

Of 50 scanner candidates, these were confirmed false positives — they
read `configs/*.yaml`, `ui/index.html`, `models.lock.json`, or other
packages' sources, or assert behavior only:
`test_acoustic_defects`, `test_capture_sidecar`, `test_curio1_chatter`,
`test_dynamic_layer` (pins `navigation/reactive_safety.py` +
`navigation/collision.py`), `test_follow_prediction`,
`test_hw2_go2_backend`, `test_hw5_physical_profile` (sha256 of
`configs/robot.yaml`), `test_hwmic_arm_route`, `test_motion_shaping`,
`test_owner_and_settle_plans`, `test_p0b_companion_unlocks`,
`test_p0c_flush_product_path`, `test_p0d_navigation_unblocks`,
`test_p2_dialogue`, `test_p2b_owner_awareness`, `test_p4_place_graph`,
`test_preempt_runtime`, `test_prod_default_path`,
`test_prototype_profile`, `test_realtime_idle_hangup`,
`test_realtime_voice_identity`, `test_resume_transaction`,
`test_safety_log`, `test_scene_and_memory_answers`, `test_search_owner`,
`test_superlative_directives`, `test_truth1_texts`,
`test_venue1_physical_venue`, plus the capture-package oracles
(`test_capture_envelope`, `test_no_arm_pin`, `test_syncevents`,
`test_clockmap`) which pin `src/parcel_robot/capture/` and
`scripts/parcel_capture/` only.

### 2.8 runtime.py extraction blast radius

Reddens on a **pure move with identical behavior**:

1. `tests/test_r24_lock_discipline.py` — worst case; `:550`, `:574`,
   `:898`, `:947`, `:1553` all fail, and `:638`/`:658`/`:687`/`:758`/
   `:992` go **vacuously green** instead. The anti-vacuity floors
   (`:701`, `:762`, `:1020`, `:1595-1603`) are the only thing between an
   extraction and a lost safety oracle. **Port with the card; never let
   an extraction land while the scan still points at one class.**
2. `tests/test_nominal_stop_wiring.py:923` — raises "not found", not a
   digest mismatch. Cheap to port (position-independent digests).
3. `tests/test_ot2_identity.py:681-707` — moved loop raises
   `StopIteration`; `:309-311` reddens if `OT2_STATE_*` leave the class.
4. `tests/test_nm1_promotion_and_asks.py:394`,`:396`,`:1096`.
5. `tests/test_cap1_admission.py:267-276` — until `admission.py` is edited.
6. `tests/test_p1b_map_learns.py` (all four), `test_ot2_memory_principal`
   (both), `test_fixa_transcript_persistence:178`,
   `test_follow_yield_wiring:362`, `test_realtime_pump_survival:926`,
   `test_move1_patrol:516`.

Silently **weakens** instead (audit every extraction):
`test_p1d_vlm_veto.py:416`, `test_nm1_promotion_and_asks.py:564`,
`test_e2_safety_wiring.py:494`, `admission.py:389`.

---

## 3. `src/parcel_robot/agent.py` — 1,593 lines

`VoiceAgent`: 1,476 lines, 35 methods. **Only one shape pin exists.**

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_k6_voice_lanes.py:199` | ROSTER | `PHYSICAL_TOOL_NAMES ⊆ agent.MOTION_TOOLS` | **SUPPORTED-CONTRACT** | Invariant: every tool the safety layer treats as physical is in agent's motion set. Survives relocation while `MOTION_TOOLS` stays importable; update the import at `:12`. |

`agent.py` is the least oracle-encumbered of the eight targets: it can be
decomposed on structure alone, with `MOTION_TOOLS` kept importable.

---

## 4. `src/parcel_robot/navigation/pipeline.py` — 6,604 lines

`DirectiveNavigator`: 5,764 lines, 116 methods, 113 attributes.

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_authority_no_literal_drift.py:400` (also `:425`, `:443`, `:470`; table at `:160`,`:166`,`:172`) | AST | exact float-literal counts in `navigation/pipeline.py`: `0.32`×5, `0.35`×6, `1.2`×1 | **TRANSITIONAL** | A one-way shrinking ratchet keyed by repo-relative path. Porting rule: when N literals move to module M, **lower** `("navigation/pipeline.py", v)` by N and **add** `("navigation/<M>.py", v)` with the same family/owner — otherwise the stale-entry check at `:425` reddens. A pure move with zero literal edits still breaks it. |
| `tests/test_pose_authority_archon.py:126` | AST | pipeline.py has **zero** direct `observation.position` / `.heading_deg` reads outside `SEAM_FUNCTIONS` | **SUPPORTED-CONTRACT** | Invariant: navigation reads pose only through the pose seam. Tree-wide scan — **survives a split intact.** |
| `tests/test_pose_authority_archon.py:133` | AST | every `_pose_in`/`pose_in` call in pipeline.py takes 2 args with frame in `{MAP_FRAME, ODOM_FRAME}`, and there must be **at least one** | **TRANSITIONAL** | The "makes no seam pose read at all" arm means a split that moves *all* seam reads out reddens though the invariant holds. Extend the hard-coded filename tuple at `:128`/`:135` with the new modules. |
| `tests/test_import_order_no_cycle.py:65` | ROSTER (subprocess) | 8 first-mover import orders; `from parcel_robot.navigation import pipeline; pipeline._HAS_INSTRUCTNAV is True` | **SUPPORTED-CONTRACT** | **Highest cycle risk of any pin on this file.** No import cycle may reach `navigation.pipeline` while `instructnav` is partially initialised — the guarded import swallows `ImportError` and silently degrades the ladder. Pins the module-level name `_HAS_INSTRUCTNAV` (pipeline.py:272/314); an extraction that moves the guarded import must re-export it. Directly relevant to the `navigation` 4-cycle in §1. |
| `tests/test_approach_traffic_wiring.py:199` | SOURCE-TEXT | `Path(pipeline_module.__file__).read_text()` must contain `from .traffic_aware import RampMemory` and `_HAS_TRAFFIC_AWARE` | **SUPPORTED-CONTRACT** | Invariant: pipeline.py is a v8 replacement source — the guarded import must degrade to "no ramp memory", never to `ImportError` (pipeline.py:152-157, 793). Literal grep: renaming the flag or moving the import to a submodule reddens with behavior unchanged. |
| `tests/test_perception_abstention.py:811` | AST | no file on `V8_REPLACEMENTS`/`V8_ADDITIONS` (incl. pipeline.py) imports `perception_abstention` at module scope | **SUPPORTED-CONTRACT** | Invariant: the replacement source reaches the abstention module lazily and guarded, because the frozen tree predates it. Scan follows `V8_REPLACEMENTS`, so a new module is covered only once added to that list. |
| `tests/test_barn_v8_policy_bundle.py:155` | DIGEST | `prepare_v8_candidate_bundle()` digests the **live pipeline.py bytes** into the bundle; asserts `replacements == V8_REPLACEMENTS`, `unchanged_file_count == 113`, reference files 116, bundle files 117 (`:162-163`), then builds the sidecar and calls `candidate_policy.act()` (`:204-218`) | **SUPPORTED-CONTRACT** | **Answers the digest question for the barn family:** this one digests pipeline *source bytes*, but pins no fixed hash — the hash floats. What it really pins: pipeline.py must stay a self-contained replacement whose only new intra-tree dependency is the single allowlisted addition (`experimental_all_ray_shield.py`). Every extracted module must be added to `V8_ADDITIONS` (`evals/external/barn_v8_policy_bundle.py:48`) **and** the 117 count bumped, or the sidecar smoke raises `ImportError` inside the frozen pre-seam tree. (skipif: needs the historical bundle cache.) |
| `tests/test_rm3_route_memory_arms.py:179` (asserts `:202-222`) | SOURCE-TEXT | `inspect.getsource` of six `DirectiveNavigator` methods pinning exact statements — `if self._route_memory_chain:` + `return True` within 40 chars; `self.route_memory_deferred_releases += 1` present in recovery, absent in partial/arm; `self.route_memory_routes_found += 1`; `self.route_memory_wins += 1`; `_publish_route_memory_waypoint()` | **TRANSITIONAL** | The six must stay resolvable as `DirectiveNavigator.<name>` and keep the literal counter statements. If the route-memory arm becomes a collaborator object, every string needs rewriting. **Best replaced** by a behavior test on the three counters' *units* (armings vs wins vs deferral ticks). |
| `tests/test_rm3_route_memory_arms.py:144` | SIGNATURE | `DirectiveNavigator.__init__` parameter `route_memory` default is `False` | **SUPPORTED-CONTRACT** | Invariant: the flag is default-OFF in the constructor, which is what makes every frozen eval row reproducible. Breaks if `route_memory` is folded into a config dataclass. |
| `tests/test_value_directed_search.py:985` (asserts `:1006-1015`) | SOURCE-TEXT | rebuilds the path from `DirectiveNavigator.__module__`; every line containing `.goal_arbiter.resolve(` must also contain `((` / `(proposed,)` / `(chosen,)`, and `.proposer_bus.poll(` must be **absent** | **SUPPORTED-CONTRACT** — **VACUITY RISK** | Invariant: every resolve site resolves over a freshly-built single-element tuple and the pipeline never polls the shared proposer bus, so the scan-viewpoint side channel cannot steer an evidence-free episode. Self-retargets via `__module__` but reads ONE file — move any resolve site or the bus poll to a sibling module and it goes **silently vacuous-green**, not red. |
| `tests/test_c3_cutover.py:410` | ROSTER | monkeypatches module attribute `pipeline_module.PlaceGrounder`, calls module-level `pipeline._build_grounder` | **TRANSITIONAL** | `_build_grounder` and the module-level `PlaceGrounder` name must move **together**; a re-export in pipeline.py is not enough — the patch must land in the namespace `_build_grounder` resolves from (pipeline.py:26, 460, 482). |
| `tests/test_c3_cutover.py:1163` | ROSTER (subprocess) | fresh-subprocess `import parcel_robot.navigation.pipeline` leaves `active_semantic_source() == oracle` | **SUPPORTED-CONTRACT** | Invariant: importing the pipeline installs no semantic source. Survives a split if the import path and its nil side effects survive. |
| `tests/test_rm2_route_memory_product_path.py:1359`, `:1590` | ROSTER | `DirectiveNavigator.ROUTE_MEMORY_RANGE_M` / `ROUTE_MEMORY_STALL_STEPS` / `UNROUTABLE_GOAL_STEPS` / `GRID_REPLAN_INTERVAL_STEPS` as **class** attributes (pipeline.py:4575, 4651, 4660, 4669) | **TRANSITIONAL** | Weakest pin here (attribute read, not source read) — but exactly the move a split makes. Demoting these to module constants in an extracted route-memory module breaks ~15 read sites in this file (`:265,312,561,598,658,675,684,989,1721,1738`) with zero behavior change. |
| `tests/test_dr2_pose_drift_arm.py:668` | SOURCE-TEXT | pipeline.py text contains `f'note="{POSE_LOST_HOLD_NOTE}"'` | **INCIDENTAL** | Replacement: drive a pose-lost hold through the navigator and assert the emitted command's `note` equals `POSE_LOST_HOLD_NOTE` — the enclosing class already digests real episode payloads at `:655-667`. |

**Confirmed non-pins (barn family resolved).** The `barn_*` digests do
**not** read the working tree: `test_barn_predictive_shield_v7.py` uses
frozen-bundle metadata with placeholder shas (`"b"*64`, `:74`);
`test_barn_profile_candidate_bundle.py` writes synthetic
`b"# frozen pipeline\n"` into a tmp root (`:134`) and its
`"pipeline_source_changed": False` is a manifest field of the frozen V8
archive; `test_barn_v9_policy_bundle.py` derives from the
content-addressed archive `parcel-v8-candidate-189ac31f…` (`:196-206`).
Also non-pins: `test_all_ray_yaw_swept_shield_v8.py` (runtime lidar
certificate + config YAML), `test_c3_cutover.py:991` (scans 7 safety
modules, not pipeline), `test_e4_evidence_seams.py` (signatures on
`NavInstructRunner`), `test_release_parity_wheel.py:167` (digests
*resolved effective config values*, not source),
`test_perception_abstention.py:396` (subprocess canary).

---

## 5. `src/parcel_robot/realtime/lane.py` — 4,113 lines

`RealtimeLane`: 3,146 lines, 81 methods, 133 attributes. **Line numbers
volatile (NARR-1 owns a marked region here).** Only two shape pins exist —
lane.py is far less oracle-encumbered than its size suggests.

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_realtime_spend_budget.py:833` (asserts `:848-854`) | SIGNATURE | `RealtimeLane.narrate_event`: `critical` present, KEYWORD-ONLY, default `False` — cross-checked against `RobotRuntime._narrate_mission` | **SUPPORTED-CONTRACT** | Invariant: the runtime's narration door wraps the lane call in `except (RuntimeError, TypeError, ValueError)`, so a lane that drops keyword-only `critical=False` goes **silently mute** — no exception, no counter (card R25, 21 failures). Follows the class through a move; breaks if `narrate_event` moves off `RealtimeLane` to a collaborator. |
| `tests/test_truth1_texts.py:569` (asserts `:592-597`) | ROSTER (import graph) | fresh subprocess runs `tools/replay_turn_detection.py --arms`, then asserts `'parcel_robot.realtime.lane' in sys.modules` is **True** and `'parcel_robot.realtime.ws_transport' in sys.modules` is **False** | **SUPPORTED-CONTRACT** | Invariant: the offline endpointing arms do reach the lane and never put a websocket client in the process. A split must keep `parcel_robot.realtime.lane` on the offline arms' import path (the "lane True" half breaks if the arms end up importing only an extracted submodule) and must not pull `ws_transport` transitively. |

**Confirmed non-pins.** `test_realtime_lane.py` — despite the name, all
behavior; its `:736-738` assertions are on rendered SI text, and the test
file's own *source* is pinned by `tests/test_ci_gate.py:863` and
`tests/test_owner_store_isolation.py:556` (it is a fixture for other
oracles). `test_realtime_corpus_replay.py` — the `si_digest`/`si_pin`
digests at `:340`, `:591-614` are over rendered **system-instruction
text** registered in `realtime/prompting.py:547`, plus corpus-manifest
file digests at `:568`; **nothing digests lane.py.**
`test_realtime_ws_transport.py:648` rosters `ws_transport.py`, and its
`:697` "zero edits to lane.py" is a docstring. Also non-pins:
`test_duplex1_rows`, `test_hw4_array_gateway` (pins `ui/index.html`),
`test_p0b_companion_unlocks`, `test_p2b_owner_awareness`,
`test_realtime_idle_hangup`, `test_realtime_pump_survival` (its
`getsource` at `:926` is `RobotRuntime._service_health_loop`),
`test_scene_and_memory_answers`, `test_turn1_endpointing`.

---

## 6. `src/parcel_robot/realtime/audio_gateway.py` — 3,539 lines

**Exactly one shape pin.** This file is the least pinned of the eight
relative to its size — the D06 shared-state split is constrained by
behavior tests, not by structural oracles.

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_hw4_array_gateway.py:892` (assert `:896-898`) | ROSTER | `callable(getattr(kind, name))` for `("bind_token","start","stop","close_mic","snapshot")` on **both** `BrowserAudioGateway` and `ArrayAudioGateway` | **SUPPORTED-CONTRACT** | Invariant: both implementations expose the same five-method surface `RobotRuntime` calls — "or array mode dies at the first idle hang-up rather than at boot". Follows the classes through a move; breaks only if a method is delegated away with no forwarding attribute. **This roster is the natural seed for an M2 `Protocol`**: the five names are already the structural contract. *Stale label (like F3): the test is named `..._the_four_methods_...` but asserts **five** — a fifth name was added without renaming. Fix while porting.* |

**Confirmed non-pins — and the trap this file sets.** Six blocks that
*look* like audio_gateway source pins are all reading the HTML panel:
`test_realtime_audio_gateway.py:574-640` (`PANEL` at `:568` is
`src/parcel_robot/ui/index.html`), `test_duplex1_panel_duck.py:37`,
`test_mark1_browser_ear.py:45`. `test_hwmic_arm_route.py` reads
`web_panel.py` (`:555`) and sha256s three `ui/index.html` functions
(`:645-648`). Also non-pins: `test_air1_scorecard`,
`test_duplex1_rows`/`_turn_controller` (capture index JSON),
`test_prototype_profile` (digests `configs/robot.yaml`),
`test_realtime_audio_capture`, `test_realtime_voice_identity`
(`models/speaker_id/models.lock.json`).

---

## 7. `src/parcel_robot/realtime/tool_broker.py` — 2,666 lines

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_cap1_admission.py:60` (asserts `:69-88`; also `:129`, `:156`, `:363`) | AST | `admission.broker_scan()` AST-parses the **literal path** `"realtime/tool_broker.py"` (`admission._BROKER_SOURCE`, `src/parcel_robot/admission.py:254`, parsed at `:273`) to **derive** every behavior route the broker sends the supervisor; asserts routes non-empty, `scan.unreadable == []`, and coverage over `BROKER_TOOLS`/`MOTION_TOOLS` | **SUPPORTED-CONTRACT** — **VACUITY RISK** | Invariant (ROAM-1 finding 1): every behavior the broker routes to is in the supervisor's allowlist, **derived not restated**. **Highest-risk pin on this file** — a product-side single-file AST scan, so routes moved to an extracted module become invisible (vacuous-green for those tools, while `:363` reddens). Extraction must widen `_BROKER_SOURCE` to a tuple in `admission.py` **first**. `:77` also requires each door call and its `_validated(call, TOOL_X)` to be readable in ONE statement — de-inlining a route reddens. |
| `tests/test_nm1_promotion_and_asks.py:1296` (assert `:1330-1336`) | SOURCE-TEXT | `inspect.getsource(getattr(RealtimeToolBroker, f"_{tool}", lambda: None))` for every tool in `BROKER_TOOLS`; `STATUS_UNCERTAIN_PLACE` must appear in exactly `[TOOL_NAVIGATE_TO]` | **SUPPORTED-CONTRACT** (mechanism INCIDENTAL) | Invariant: "uncertain_place" has exactly one producer, which is what makes `navigate_to ∈ PROACTIVE_MOTION_REFUSED` a proof rather than a coincidence. Also pins the convention that every `BROKER_TOOLS` entry has a method `RealtimeToolBroker._<tool>`. The `lambda: None` fallback means a **moved handler drops out silently** — extraction degrades this to vacuous-green. Replacement: call each tool through the broker and assert only `navigate_to` returns `status == "uncertain_place"`. |
| `tests/test_ot2_memory_principal.py:431` (asserts `:434-456`) | AST | parses runtime.py, locates the `ToolDoors(...)` call inside `RobotRuntime.__init__`, asserts keywords `remember_fact == "self._ot2_remember_fact"` and `confirm_fact == "self._ot2_confirm_fact"` | **TRANSITIONAL** | `ToolDoors` is defined in `tool_broker.py:979`, so this pins its keyword-argument names by AST **from the caller side**. Porting rule: the field names must survive verbatim AND `ToolDoors` must stay a bare `ast.Name` call in `RobotRuntime.__init__` — an aliased import or a factory reddens with no behavior change. Couples DEC-R2 (builders) to any tool_broker card. |

**Marker load.** `tool_broker.py` carries **16** `# ---- CARD` markers —
the largest concentration in the package after `runtime.py`. M7 requires
these dissolved into module docstrings on extraction, never copied.

**Confirmed non-pins.** `test_capture_envelope` (targets
`src/parcel_robot/capture/`), `test_p0b_companion_unlocks` (config
example), `test_scene_and_memory_answers` (`build_tool_specs()` returns
spec dicts — behavior). Note `test_ot2_memory_principal.py:407` names
`runtime.py` only, but **a broker extraction that absorbs the OT-2
confirm door would redden it**.

---

## 8. `# ---- CARD` marker load per target file

The ratchet's 178-marker budget, distributed over the eight targets
(101 of 178 live in these files — decomposing them is most of M7's win):

| file | markers |
|---|---|
| `runtime.py` | 46 |
| `scripts/ci_gate.py` | 19 |
| `realtime/tool_broker.py` | 16 |
| `realtime/audio_gateway.py` | 8 |
| `web_panel.py` | 7 |
| `realtime/lane.py` | 5 |
| `navigation/pipeline.py` | 0 |
| `agent.py` | 0 |
| **total in targets** | **101** |

---

## 9. `src/parcel_robot/web_panel.py` — 1,077 lines

**Only one test reads `web_panel.py`'s text.** Everything else in the
candidate set pins a *symbol roster* imported from the module, a
*filename* in another module's table, or the *page copy* in
`src/parcel_robot/ui/*.html` — a sibling asset, not this file. Route pins
and copy pins therefore port completely differently.

### 9.1 Route-registration pins (source text of the handler)

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_hwmic_arm_route.py:547` | SOURCE-TEXT | regex `path == "…"` literals sliced out of `RuntimeRequestHandler.do_POST`/`do_GET`; the POST set must equal the 13 HEAD routes + `/api/realtime/mic`, GET count must equal 8 | **SUPPORTED-CONTRACT** | Invariant: the panel's served HTTP surface is exactly that route set — no route added or dropped silently (unprovable behaviourally in the negative, so this pin cannot simply be deleted). Slice anchors are `"    def do_POST(self) -> None:"`, `"    def do_GET(self) -> None:"` and the comment `# ------------------- card R7`. A split must re-implement `_route_literals` (`:542`) as a **union scan over every module that keeps a `do_GET`/`do_POST` branch**, or the pin silently measures a shrunken handler. |

`tests/test_web_panel.py` (311 lines, zero source/roster/marker asserts)
is the pure-HTTP behavior suite for these routes and is **the natural
replacement oracle** for any route-behavior claim a card wants to retire.

### 9.2 Symbol-roster pins (private allowlists imported from `web_panel`)

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_hw5_physical_profile.py:183` | ROSTER | `set(configs/robot.go2_edu_plus.yaml backend) <= set(web_panel._BACKEND_KEYS)` | **SUPPORTED-CONTRACT** | Invariant: every key the shipped physical profile writes under `backend:` is admitted by the launcher's read-site allowlist — the overlay loader exempts the whole subtree, so this is the only spelling guard. |
| `tests/test_hw5_physical_profile.py:238` | ROSTER | `{"kind","band","interface"} <= set(web_panel._BACKEND_KEYS)` | **SUPPORTED-CONTRACT** | Same invariant, minimum-vocabulary half. Both rows need `_BACKEND_KEYS` importable from `parcel_robot.web_panel` (re-export, or re-point the imports at `:181`/`:229`). |
| `tests/test_truth1_texts.py:741`, `:748` | ROSTER + foreign SOURCE-TEXT | `web_panel._PLANNER_MODEL_KEYS` equals the set of `config.get("…")` keys scraped from `providers.py`'s `from_config` body, plus exactly `{"enabled"}` | **SUPPORTED-CONTRACT** | Invariant: the planner allowlist is the provider's own vocabulary, never a hand-kept copy. **Two** moves break it — `_PLANNER_MODEL_KEYS` leaving `web_panel`, or `providers.from_config` being reshaped. |

### 9.3 Filename-in-a-table pins (break on file layout, not symbol location)

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_cap1_admission.py:256` | SOURCE-TEXT/ROSTER | greps every `src/parcel_robot/**/*.py` for `store.section(`, asserts ⊆ `admission._PRODUCT_CONFIG_SOURCES` — a hand-written tuple containing `"web_panel.py"` (`admission.py:400-410`) | **SUPPORTED-CONTRACT** | **The loudest web_panel decomposition tripwire.** Entries resolve via `_PACKAGE_DIR.joinpath(*relative.split("/"))` (`admission.py:219`), so a package split must register `"web_panel/<mod>.py"` paths. Same F2 obligation as runtime.py. |
| `tests/test_cap1_admission.py:227` | AST/ROSTER | AST-parses every entry of `_PRODUCT_CONFIG_SOURCES`/`_RUNTIME_REGION_SOURCES`, asserts no unresolvable `store.section(...)` site | **SUPPORTED-CONTRACT** — **VACUITY RISK** | **Hazard:** `admission._tree()` returns `None` for a missing path and the scan skips it *silently*. If `web_panel.py` disappears from the tree this test stays green with coverage lost — only `:256` catches the replacements. |

### 9.4 Page-copy pins — subject is `ui/*.html`, **not** `web_panel.py`

These port with the served asset and the `# ---- CARD` fences inside it,
**not** with a Python split — but `web_panel.py:26-30` owns the
`UI_PATH`/`VIEWER_UI_PATH`/`EVALS_UI_PATH` constants they reach through.

| pin | kind | what it pins | class | note |
|---|---|---|---|---|
| `tests/test_hwmic_arm_route.py:637` | DIGEST + MARKER | strips every `---- CARD HW-MIC … ---- END CARD HW-MIC` fence from `ui/index.html`, then sha256s three JS functions against HEAD pins (`:66-80`) | **TRANSITIONAL** | Ports with the asset; re-baseline only when the fenced copy legitimately changes — never as collateral of a Python move. |
| `tests/test_hwmic_arm_route.py:651` | MARKER | exactly 4 `CARD HW-MIC` regions in `ui/index.html`; combined text contains the route, `state.arrayMic`, the busy guard, the `mic_open===false` correction, and none of `getUserMedia`/`openAudioSocket`/`AudioContext` | **TRANSITIONAL** | Copy pin; no JS engine runs in this suite, so it cannot be replaced by behavior in-repo. |
| `tests/test_realtime_audio_gateway.py:592` | SOURCE-TEXT | `` `parcel-csrf.${CSRF_TOKEN}` `` present; `audio?token=` and `"<gateway>?` absent | **SUPPORTED-CONTRACT** | **Security invariant:** the panel token never reaches a URL (request lines are logged). |
| `tests/test_realtime_audio_gateway.py:571`, `:601`, `:620`, `:629`, `:639` | SOURCE-TEXT | verbatim mic-button wiring + `hidden = realtime.mode !== "audio"`; one-and-only-one arming frame and its `.index()` ordering vs `hello`; the barge-in `stopPlayback` block; `onaudioprocess` free of `playAt`/`sources`; the `encodeMicFrame(samples, fromRate, toRate)` header and rate default | **TRANSITIONAL** | Five browser-half copy pins; move with `ui/index.html`. |
| `tests/test_viewer_panel.py:60` | SOURCE-TEXT | `ui/viewer.html` references no `https?://`, no external `src`/`href`, inlines `<style>`/`<script>` | **SUPPORTED-CONTRACT** | Self-containment invariant of the served viewer page. |
| `tests/test_eval_panel_voice_mode.py:238` | SOURCE-TEXT | `ui/evals.html` carries `id="voiceMode"` and is not pre-checked | **INCIDENTAL** | Replaceable by behavior already in the same file: `POST /api/evals/run` with no mode runs headless and `/api/evals/status` reports the mode (`:225-235`). |

**Confirmed non-pins.** `test_fail_closed_limits` (behavior via
`build_runtime`), `test_hw2_go2_backend` (its `dir()` roster at `:544` is
over `SimulatorBackend`; `web_panel.py` line refs are docstrings only),
`test_owner_store_isolation` (its AST sweep at `:484` names neither
target), `test_prototype_profile` (imports `_build_backend`/
`_check_planner_model_section` but only *calls* them; its sha256 at
`:133` is over `configs/robot.yaml`).

---

## 10. `scripts/ci_gate.py` — 3,164 lines

### 10.1 Tier table / check roster — the decomposition blockers

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_ci_gate.py:772` | SOURCE-TEXT (`inspect.getsource(run_commit_tier)` / `run_nightly_tier`) | 10 literal commit-required entries must appear in the commit tier's source and in nightly's; 6 nightly-only entries must appear in nightly and **not** in commit | **SUPPORTED-CONTRACT** | Invariant: the commit tier never loses a hard gate, and nightly evidence ratchets never migrate into commit. `getsource` sees one function body — if the stage table moves to a submodule or evaluators are called through an indirection (`checks.ruff.evaluate`), the substrings vanish and it reddens. **Re-express against the composed stage table (names + resolved callables), not text.** |
| `tests/test_ci_gate.py:937` (also `:992`, `:1038`, `:1320`, `:1358`) | ROSTER | produced row names `== COMMIT_TIER_STAGE_NAMES` (`ci_gate.py:2772`), on a clean run and on every crash-seeded run | **SUPPORTED-CONTRACT** | Invariant: the tier reports the full declared row set whatever explodes; the literal tuple makes adding/dropping a stage a visible edit. Must stay **one importable tuple**. |
| `tests/test_ci_gate.py:942` | ROSTER (order) | `unitree-assets` before `hard-safety` | **SUPPORTED-CONTRACT** | The payload check must speak before the gate that dies on a missing MJCF. |
| `tests/test_hw7_gate_aarch64.py:143` | ROSTER (cross-table) | every key of `STAGE_REQUIREMENTS` is in `COMMIT_TIER_STAGE_NAMES`; every value names a declared capability, never a FACT | **SUPPORTED-CONTRACT** | Invariant: no skip declaration names a stage or capability that does not exist. |
| `tests/test_hw7_gate_aarch64.py:179` | ROSTER | `STAGE_REQUIREMENTS == PINNED_REQUIREMENTS` — the full 8-entry literal table | **SUPPORTED-CONTRACT** | Invariant: the aarch64 skip set is exactly what HW-7 measured; changing it is a deliberate paired edit. |
| `tests/test_hw7_gate_aarch64.py:208` | ROSTER + foreign source scan | while any `tests/test_*.py` imports mujoco unguarded, `tier-coverage` and `default-suite` must declare `mujoco` | **SUPPORTED-CONTRACT** | Invariant: a collect-everything stage declares what collection needs, or a mujoco-less host gets a hard ERROR instead of a typed SKIP. |
| `tests/test_hw7_gate_aarch64.py:300` (helper `:317`) | ROSTER (order + hard/soft split) | `[0]=="ruff"`, `[-2]=="skip-list"`, `[-1]=="host"`; `soft = {"stopping-envelope","skip-list","host"}` | **SUPPORTED-CONTRACT** | Position 0 belongs to the first HARD gate — a contract `test_ci_gate.py` relies on (`payload["gates"][0]["status"]=="error"`) — and the two report-only rows sit above RESULT. |
| `tests/test_hw6_stopping_envelope.py:744` | ROSTER | `"stopping-envelope" in COMMIT_TIER_STAGE_NAMES`, before `"default-suite"` | **SUPPORTED-CONTRACT** | A cheap hard-failing file read must precede the 400 s suite. |
| `tests/test_ci_gate.py:606` | ROSTER (literal command list) | `--collect-only` over `MODEL_OFF_NODE_IDS` returns 0 | **SUPPORTED-CONTRACT** | Invariant: the gate's pytest selections still resolve to real tests. **Coverage gap worth recording:** only `MODEL_OFF_NODE_IDS` is covered — `FROZEN_DIGEST_`, `RELEASE_PARITY_`, `OWNER_STORE_`, `MUTATION_FRESHNESS_`, `LATENCY_TAIL_NODE_IDS` (`ci_gate.py:132-208`) have no such pin. |
| `tests/test_ci_gate.py:327` | ROSTER (cardinality) | `evaluate_frozen_digest_sentinels(DIGEST_SENTINELS).extra["checked"] == 4`, deliberately literal | **SUPPORTED-CONTRACT** | Deriving it from `len(DIGEST_SENTINELS)` would be vacuous; a dropped sentinel must be a visible edit. |
| `tests/test_ci_gate.py:413` | ROSTER (completeness) | `{frozen manifests under evals/} - set(DIGEST_SENTINELS) == known_unpinned` | **SUPPORTED-CONTRACT** | Invariant: no frozen manifest escapes the sentinel table unnoticed. |
| `tests/test_ci_gate.py:958`, `:967` | ROSTER (internal helpers + fan-out) | `EXPLODING_VICTIMS` names `evaluate_ruff`, `evaluate_hard_safety`, `_pytest_gate`, `evaluate_default_suite` as attributes of `scripts.ci_gate`, and pins how many rows each backs (1/1/3/1) | **TRANSITIONAL** | `monkey.setattr(module, victim, boom)` requires the name to stay an attribute of the module `run_commit_tier` resolves it from. After a split, patch the module the stage table imports it *into*, and re-derive the counts. |
| `tests/test_v4s_search_cells.py:136` | ROSTER (cardinality) | second copy of `checked == 4` plus one `DIGEST_SENTINELS[...]` entry equal to the local v4 pin | **INCIDENTAL** | Duplicate of `test_ci_gate.py:327`; keep whichever survives the split. |

### 10.2 Literal call-site pins on the tier bodies

| pin | kind | what it pins | class | porting rule / replacement |
|---|---|---|---|---|
| `tests/test_eval_assertions.py:1216` | SOURCE-TEXT | `ci_gate.py` must contain verbatim `("assertion-evals", lambda: evaluate_assertion_evals(tier=tier, k=1)),` and `results.append(evaluate_assertion_evals(tier=tier, k=3))` | **SUPPORTED-CONTRACT** | Invariant worth keeping: commit runs the assertion gate at k=1, nightly at k=3. **Mechanism is the most brittle in the repo — it pins lambda text.** Re-express as an assertion over the stage table's bound `k`. |
| `tests/test_hw6_stopping_envelope.py:750-751` | SOURCE-TEXT | slices `ci_gate.py` on `def run_commit_tier(` … `results: list[GateResult]`, requires the exact line `("stopping-envelope", lambda: evaluate_stopping_envelope(tier=tier)),` | **TRANSITIONAL** | Ports with whatever module holds the commit stage tuple; both slice anchors must be re-chosen. |
| `tests/test_ci_gate.py:1256-1258` | SOURCE-TEXT (`getsource(run_nightly_tier)`) | must **not** contain `evaluate_default_suite`; must contain literal `markers=COMMIT_MARKERS` | **TRANSITIONAL** | The nightly tier is never executed in tests, so there is no cheap behavior substitute — re-point `getsource` at whatever composes the nightly tier. |
| `tests/test_dr2_pose_drift_arm.py:1138`, `:1148` | SOURCE-TEXT (`getsource`) | `evaluate_pose_drift_arms` present in `run_nightly_tier`, absent from `run_commit_tier` | **TRANSITIONAL** | Same porting rule; protects the cadence invariant (nightly arms, commit unit-tests only). |
| `tests/test_nightly_runner.py:189` | SOURCE-TEXT (`getsource(run_nightly_tier)`) | must contain `NIGHTLY_SLOW_MARKERS` and `"slow-suite"` | **TRANSITIONAL** | Invariant: the nightly selects the deselected tier through the same constant the tier-coverage gate reads. |
| `tests/test_ci_gate.py:1237` | SOURCE-TEXT (`getsource(run_commit_tier)`) | contains `evaluate_default_suite` and `default-suite` | **INCIDENTAL** | `fast_commit_tier` already runs the real tier — assert the `default-suite` row was produced by a sentinel-patched `evaluate_default_suite` (the pattern at `:1385`). |
| `tests/test_ci_gate_jerk_ratchet.py:103` | ROSTER (`dir(ci_gate)`) | the only `*_MARGIN` float attribute of the module is `LATENCY_TAIL_MARGIN` | **SUPPORTED-CONTRACT** | Invariant: one repo-wide tolerance constant, not a second per ratchet. After a split, `dir()` on one module no longer sees the package — re-point at the package namespace. |
| `tests/test_ci_gate_jerk_ratchet.py:105` | SOURCE-TEXT | `"FOLLOWBENCH_JERK_MARGIN" not in ci_gate.py` | **INCIDENTAL** — **VACUITY RISK** | After a split this becomes vacuously true wherever the constant lands. Replace with a package-wide scan, or delete alongside the `dir()` row above. |

### 10.3 `# ---- CARD` marker pins (ownership hygiene)

| pin | kind | what it pins | class | note |
|---|---|---|---|---|
| `tests/test_hw7_gate_aarch64.py:692-700` | MARKER | in `ci_gate.py`, the `CARD HW-7`/`XD-1`/`GATE-0b`/`HW-6` fences each satisfy `opens == closes > 0`; and `"CARD HW-7"` is absent from `tests/test_ci_gate.py` | **INCIDENTAL** | **Blocks any split that moves a fenced region out of `ci_gate.py`** — the `> 0` arm fails at zero. Cards are closed; replacement is a package-wide fence-balance scan, or drop it. Directly conflicts with M7, which requires these markers to dissolve. |
| `tests/test_hw6_stopping_envelope.py:753-758` | MARKER | `# ---- CARD HW-6 stopping-envelope` counted exactly 3 open / 3 close in `ci_gate.py`; no `HW-6` text inside any `CARD XD-1`/`GATE-0b` region | **INCIDENTAL** | Same conflict with M7. (`ci_gate.py:1097` notes `CARD GATE-1` is likewise "balanced 3 for 3" — no test enforces that one.) |

**These two rows are the only place in the repo where an oracle actively
forbids M7's marker dissolution.** Any ci_gate card (D16) must retire them
first, with the package-wide replacement named above.

**Confirmed non-pins.** Docstring/comment mentions only:
`test_bandwidth_budget_doc`, `test_e4_evidence_seams`,
`test_future_clock_guard`, `test_no_arm_pin`, `test_prox1_proximity_profiles`,
`test_nav_instruct_ledger_guard`, `test_mutation_panel_freshness`,
`test_hw2_go2_backend:1362`. Also `test_held_out_scene:64` (the path
appears inside an assertion *message*), `test_realtime_corpus_replay`
(re-implements the frozen-manifest scan; never imports `ci_gate`),
`test_release_parity:32`, `test_unitree_asset_pack` (behavior over
`evaluate_unitree_assets`' verdict). Note `tests/test_ci_gate.py:863`
reads **`tests/test_realtime_lane.py`** source — a real shape pin, but on
a *test* file.

---

## 11. Public surface per file

"External" = importers outside `src/parcel_robot/`. All counts from an
AST sweep (parenthesized multi-line imports included), excluding
`.parcel/`, `build/`, `tmp_ci/`, `third_party/`.

### 11.1 Barrel status — DEC-IG-1/IG-2's actual worklist

`src/parcel_robot/__init__.py` defines only `__version__`; there is **no
top-level barrel**, so `from parcel_robot import runtime` is a submodule
import, not a re-export.

| file | barrel | migration owed |
|---|---|---|
| `navigation/pipeline.py` | **live** — `parcel_robot.navigation` re-exports `DirectiveNavigator` | **12 repository modules use navigation barrel symbols** (verified by AST): `examples/nav_city_smoke.py`, `src/parcel_robot/skills/api.py:146`, and tests `test_arrival_etiquette_pipeline:23`, `test_k4_opus_wiring:27`, `test_navigation:8`, `test_portal_world:36`, `test_pose_consumers:14`, `test_runtime:25`, `test_semantic_navigation_regressions:7`, `test_superlative_directives:29`, `test_value_directed_search:31`, `test_ve_detection_lock_on:27`. 43 importers already use the leaf path. Tests/examples are public-surface consumers, not automatically migration debt. |
| `realtime/lane.py` | `realtime/__init__.py` re-exports 8 lane symbols (`GUARDRAILS`, `TOOL_REFUSAL_OUTPUT`, `RealtimeArmingDecision`, `RealtimeLane`, `RealtimeLaneError`, `SinkOwnershipError`, `build_instructions`, `decide_realtime_arming`) and **zero repository modules import any of them via the barrel** | **No internal migration is owed. Preserve the public exports** unless a later card explicitly approves a compatibility break; zero repository callers is not proof of zero external callers. All current repository `from parcel_robot.realtime import X` traffic is submodule names (`driver`, `protocol`, `voice_identity`, `lane`, `ingress`). |
| `runtime.py`, `web_panel.py`, `agent.py`, `realtime/audio_gateway.py`, `realtime/tool_broker.py` | **no barrel** | none — every importer is already leaf. |

**For these eight target modules, navigation is the only barrel with
repository symbol consumers.** This is a public-surface census, not the full
DEC-IG-1 worklist across the other packages named by that card.

### 11.2 Per-file surface

| file | external / internal importers | headline symbols | config keys owned | endpoints / CLI |
|---|---|---|---|---|
| `runtime.py` | **78** / 2 (`runtime_channels.py`, `web_panel.py`) | `RobotRuntime` (72 tests); `scene_report`, `CameraStreamConfig`, `TRANSCRIPT_ORIGIN_MIC`, `_PANEL`, `SCENE_HONESTY_NOTE` + ~40 single-test constants; privates `_RealtimeLedgerMirror`, `_LockedNavigationChannel`, `_camera_query_from_directive` | 23 top-level sections (`agent, audio, awareness, battery, camera_ingress, control, duplex, expression, memory, metrics, modules, motion, navigation, owner_follow, owner_search, perception, prompting, query_context, roam, robot, safety, spatial_behaviors, speech`) + 12 `PARCEL_*` env vars + `MUJOCO_GL` | **none** — no argparse, no `__main__`, no routes |
| `navigation/pipeline.py` | **30** / 6 | `DirectiveNavigator`; private `_build_grounder` (1 test); `soft_import_health` | owns `configs/navigation/default.yaml` (not `robot.yaml`); `from_config(**overrides)` accepts 15 shadowing kwargs | none |
| `realtime/lane.py` | **26** / 3 | `RealtimeLane` (22 tests), `RealtimeLaneError`, `TOOL_REFUSAL_OUTPUT`, `decide_realtime_arming`, `build_instructions` + ~22 constants; `__all__` = 54 | none from `robot.yaml`; reads `RealtimeConfig` attrs. **The 36-kwarg constructor signature is itself the public contract.** | none |
| `realtime/audio_gateway.py` | **13** / 2 | `BrowserAudioGateway` (11 tests), `SessionAudioCapture`, `ArrayAudioGateway`, `CAPTURE_INDEX_NAME`, `serve_websocket`; `__all__` = 32 | owns `audio:` — `AUDIO_CONFIG_KEYS = {"device","gateway"}`, `audio.gateway ∈ {browser, array}`; hardware constants `ARRAY_USB_ID="2886:001a"`, `ARRAY_UDEV_RULE_PATH` | **owns the websocket contract** served by web_panel: `GATEWAY_PATH="/api/realtime/audio"`, `SUBPROTOCOL_AUDIO="parcel-audio"`, `CSRF_SUBPROTOCOL_PREFIX="parcel-csrf."`, capture-index file contract `index.json`. No CLI. |
| `web_panel.py` | **20** (8 are scrum docs) / **0** — nothing inside the package imports it; it is the top of the graph | `build_runtime`, `RuntimeHTTPServer`; privates `_build_backend`, `_check_planner_model_section`, `_PLANNER_MODEL_KEYS`, `_BACKEND_KEYS` | `planner_model` (18-key allowlist), `backend` (`_BACKEND_KEYS`, `_BACKEND_KINDS=("mujoco","go2")`), `language_model.enabled` | **owns the whole HTTP surface**: 8 GET pages/APIs, 1 WS upgrade (`/api/realtime/audio`), 13 POST routes, OPTIONS on `/api/state`. CLI `parcel-panel`: `--config --socket --host --port(8765) --llm/--no-llm --no-browser --browser-path --pose-review`; `MAX_REQUEST_BYTES=65_536`, loopback Host check. |
| `agent.py` | **8** / 4 (`cli.py`, `ros_node.py`, `runtime.py`, `voice_pipeline.py`) | `VoiceAgent`, `EMERGENCY_STOP_PHRASES`, `MOTION_TOOLS` | **none read directly** — all config arrives as 30 constructor kwargs; `runtime.py` maps `agent.*` onto them | none |
| `realtime/tool_broker.py` | **15** / 3 (`admission.py`, `realtime/lane.py`, `runtime.py`) | `STATUS_OK` (12 tests), `RealtimeToolBroker`, `ToolDoors`, `BROKER_TOOLS`, `MOTION_TOOLS`, `build_tool_specs`; `__all__` = 59 | none from `robot.yaml`; `realtime.yaml` keys `proactive_motion_tools`, `unknown_place` | no HTTP/CLI, but **owns the model-facing tool-name vocabulary** (a wire contract): `get_status, recall_memory, remember_fact, play_gesture, set_pose, navigate_to, circle_owner, follow_owner, roam` |
| `scripts/ci_gate.py` | **11** (10 tests + `scripts/run_nightly.py`) | `GateResult`, `COMMIT_TIER_STAGE_NAMES`, `run_commit_tier`, `run_nightly_tier`, 14 `evaluate_*`, ~45 single-test constants; privates `_base_env`, `_git_paths`, `_panel_safety_fields_live`, `_pytest_gate`, `_ruff_fingerprints` | no YAML; owns env vars (`PARCEL_XDIST_WORKERS`, `PARCEL_CI_GATE_NESTED`, `PARCEL_HOST_ARCH`, `NIGHTLY_ENV`, `CREDENTIAL_ENV_VARS`) and path constants | CLI is tiny: `--tier {commit,nightly}`, `--json`, `--update-ruff-baseline`. **Exit codes are contract**: `GREEN=0, RED=1, INCOMPLETE=2`. 13 commit stage names in `COMMIT_TIER_STAGE_NAMES` (`ci_gate.py:2772`). |

### 11.3 `ToolDoors` — the 19-field structural contract

`ToolDoors` (`tool_broker.py:979`) is a 19-field callable dataclass —
`validate, status, recall, gesture, pose, navigate, gesture_names,
pose_names, on_dispatch, note, places, ask_place, orbit, follow, roam,
remember_fact, forget_fact, known_facts, confirm_fact` — constructed at
`runtime.py:2708` and in **7 test modules**. Moving or reordering fields
breaks all of them, and `tests/test_ot2_memory_principal.py:434` pins two
of the keyword names by AST from the caller side. **M3 (frozen
dataclasses) is already satisfied here; treat this as a fixed seam, not a
refactor target.**

---

## 12. Cross-cutting risks

1. **Namespace monkeypatching requires imported names to stay in the
   file's module dict.** `runtime.py`: `explicit_affect_from_text` (3),
   `http_service_health` (2), `finalize_command` (2), `time` (2),
   `AWARENESS_TICK_S`, `build_speech_stack`, plus direct assignment of
   `runtime_module.apply_reactive_safety` and
   `runtime_module.time_to_collision_verdict`. `ci_gate.py`: **14**
   patched names. `web_panel.py`: `RobotRuntime`, `MujocoSocketBackend`.
   A "move the import to the new module" refactor breaks these with no
   shape pin firing.
2. **Two import spellings for `ci_gate` must both keep working** —
   `from scripts.ci_gate import …` and bare `from ci_gate import …`
   (`tests/test_ci_gate_jerk_ratchet.py:22,95`, relying on `scripts/` on
   `sys.path`).
3. **Private symbols cross the boundary** and must be re-exported or
   re-pointed: `runtime._RealtimeLedgerMirror`, `_LockedNavigationChannel`,
   `_camera_query_from_directive`; `pipeline._build_grounder`;
   `web_panel._build_backend`, `_check_planner_model_section`,
   `_PLANNER_MODEL_KEYS`, `_BACKEND_KEYS`; `ci_gate._base_env`,
   `_git_paths`, `_panel_safety_fields_live`, `_pytest_gate`,
   `_ruff_fingerprints`.
4. **Source-text/AST assertions are the largest silent-breakage class:**
   11 test modules read `runtime.py` as raw text, 5 read `pipeline.py`,
   4 read `ci_gate.py`, 2 read `web_panel.py`.
5. **`deploy/orin/nftables.conf` cites `web_panel.py:751` by line
   number**, and `CODEBASE_INDEX.md` records exact line counts per file —
   regenerate with `tools/codebase_index.py` after any split.
6. **M7 vs. two ci_gate oracles.** `tests/test_hw7_gate_aarch64.py:692-700`
   and `tests/test_hw6_stopping_envelope.py:753-758` assert `opens ==
   closes > 0` for named `# ---- CARD` fences *inside `ci_gate.py`*. M7
   requires those markers to dissolve. The D16 card must retire both
   (package-wide fence-balance scan) before it can shrink the file.
