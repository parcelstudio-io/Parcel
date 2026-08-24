# DEC-R2 — runtime.py: assembly builders + frozen bundles (D01 first half) · Fable 2026-08-23

Program: `DECOMP_PROGRAM_FABLE.md` §2 M3/M4/M7/M9, §3. Prereq: DEC-R1 landed.
Runtime-slot card (the only runtime.py toucher while it runs). Brief
(`BRIEF_FABLE.md`) is written by the integrator after DEC-R1's STATUS —
this README fixes the design so the brief only has to name files.

## Why this card is the real break-up
`RobotRuntime.__init__` is 1,393 lines assigning **288** `self` attributes;
every one of the 350 methods reads them through `self._x`. That is the god
object: one class owns every subsystem's state. This card makes each
subsystem's state live in a **frozen bundle** built by a **builder
function**, and the facade hold one attribute per bundle. Ownership moves;
behavior does not.

## Design (binding)
- **Composition root package:** `parcel_robot/assembly/` — the one place
  ARCH-1's layer list calls "application composition roots". One module per
  subsystem, `≤ 400` lines each: `assembly/audio.py`, `assembly/speech.py`
  (providers/TTS/STT stack), `assembly/memory.py`, `assembly/expression.py`,
  `assembly/perception.py` (camera ingress config, detector choice, venue),
  `assembly/navigation.py`, `assembly/brain.py`, `assembly/realtime.py`,
  `assembly/mission.py` (roam/curiosity/activities/narration state),
  `assembly/owner.py` (ot2 identity, tracker), `assembly/lifecycle.py`
  (threads, locks, clocks). Names may adjust to what `__init__` actually
  groups — the executor derives the grouping from an AST read of which
  attributes each method-prefix family touches (the integrator's prefix
  table in the DEC memory / DECR1_STATUS is the starting point).
- **Builder signature (M4):** `def build_<subsystem>(config: ConfigStore,
  deps: <Subsystem>Deps) -> <Subsystem>Bundle`. `Deps` and `Bundle` are
  `@dataclass(frozen=True, slots=True)`. A builder takes only config and
  the bundles it needs (explicit construction order = explicit dependency
  order); **no builder receives or reaches back into `RobotRuntime`**.
  Mutable runtime state that a subsystem owns (queues, counters, last-seen
  timestamps) lives in ONE mutable state object referenced from the frozen
  bundle (`bundle.state`), typed and named — never a bare dict.
- **Facade after the card:** `RobotRuntime.__init__` = parse config →
  call builders in the current order → bind `self.audio`, `self.speech`,
  … (one attribute per bundle) → wire callbacks. Method bodies are
  rewritten mechanically from `self._mic` to `self.audio.mic` (AST-driven
  rename per subsystem; the executor writes the rename map from the
  builder's field list and applies it with a uniqueness check per
  attribute). **Public methods, signatures, callback names, thread names,
  the 17 `on_*=self._method` wirings, and construction ORDER are
  unchanged.** No method moves out of the class in this card (that is
  DEC-R3+).
- **Locks (r24):** `RUNTIME_LOCKS` (8 names) may be constructed inside
  `assembly/lifecycle.py` and bound on the facade under their existing
  names, OR stay literally in `__init__` — executor's choice, but the
  choice is made ONCE and `tests/test_r24_lock_discipline.py`'s scan
  (`:550` roster, `:574` `PINNED_LOCK_ORDER`, and the `:638-:1020`
  scans with their anti-vacuity floors) is ported in the same card to
  see the new construction site. Floors end ≥ today's values. The six
  pinned lock-order edges are semantics, not shape: they must hold
  identically.
- **Mirror dicts (verdict rule 9 / M3):** if a bundle's state is today
  copied per tick into a dict under `runtime._lock` for `snapshot()`, this
  card may leave `snapshot()` alone (it is DEC-R7's subject) but must NOT
  create a second copy: the bundle IS the source and `snapshot()` reads
  it under the same lock it uses today.
- **Region markers (M7):** the 46 `# ---- CARD` regions inside `__init__`
  and the bundle-owned state die; each destination module's docstring
  carries the one-line invariant (e.g. "P1-B: the map is installed before
  the eye"). Net markers must fall by ≥ 20.

## Metrics (M9 — pass/fail)
`RobotRuntime` `self` attributes 288 → **≤ 60** (one per bundle + the
handful of genuinely facade-level fields, each listed with a reason);
`__init__` 1,393 → **≤ 300** lines; runtime.py lines down by ≥ 900 (the
`__init__` bodies move into builders — some net growth in `assembly/` is
expected and reported); method count unchanged; locks 8 (unchanged);
callbacks 17 (unchanged); markers −20 or more; both ratchets green;
r24 / nominal-stop / nm1 / ot2 / p1b oracles green with every port named.

## OWNS
`runtime.py` (`__init__`, the mechanical attribute renames in method
bodies, import block), the new `assembly/` package, the r24 port lines,
`admission._RUNTIME_REGION_SOURCES` if a builder reads a runtime region,
`tests/test_decr2_assembly.py` (each builder constructs its bundle from
the default config with fakes for hardware deps; construction order is
asserted as a list; one facade spot-check: `RobotRuntime(...)` built the
old way and the new way exposes identical public attribute NAMES for the
compatibility surface DEC-0 §11.2 lists), this folder.

## MUST NOT TOUCH
Method bodies beyond the attribute rename; `snapshot()`'s semantics;
`start()`/`close()` order; `_control_loop*`; `_dispatch_active` and the
digest-pinned stop predicates; navigation/pipeline.py; frozen baselines;
git; the owner's live stack.

## Prove
`test_r24_lock_discipline`, `test_nominal_stop_wiring`, `test_nm1_*`,
`test_ot2_identity`, `test_ot2_memory_principal`, `test_p1b_map_learns`,
`test_cap1_admission`, `test_runtime`, `test_runtime_activation`,
`test_runtime_brain_integration`, `test_realtime_pump_survival`,
`test_fixa_transcript_persistence`, `test_follow_yield_wiring`,
`test_move1_patrol`, both ratchets, the new test — then one full
`-m 'not slow' -n 8 --dist loadfile` through the guard. A byte-identical
`snapshot()` payload before/after on a fixed fake-backend boot sequence
(capture BEFORE the card, compare after) is the behavior oracle.

## After this card (sequence, one runtime toucher at a time)
DEC-R3 realtime bridge (32 methods/1,137 lines → `realtime/runtime_bridge.py`
class owning the realtime bundle; facade delegates) · DEC-R4 perception
wiring (venue1 12, p1b 8, ot2 8, camera 3 → `camera_channel/venue_ingress.py`,
`online_map/runtime_hook.py`, `owner_model/runtime_identity.py`) · DEC-R5
mission services (roam 7, curiosity 11, narrate 5, activities, dispatch
bookkeeping → `parcel_robot/mission/`) · DEC-R6 interaction (voice 6,
duplex 6, submit 7, whisper 3 → `parcel_robot/interaction/`) · DEC-R7 the
10 Hz loop + `snapshot()` (mirror dicts → frozen handoff; the hardest and
last). Each reduces methods AND attrs on the facade and ports r24/nm1.
