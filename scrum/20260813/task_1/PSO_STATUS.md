# PS-O — make the no-arm guarantee actually cover the code that touches the robot

**Card:** PS-O (FIX tranche PS-3) · **Date:** 2026-08-13 · **Executor:** Opus
**OWNS:** `tests/test_no_arm_pin.py` (new), `tests/test_capture_ingest.py`,
`scripts/parcel_capture/ingest/base.py`
**Also edited (required by task (c), declared):** `scripts/parcel_capture/ingest/dds.py`
— `_SubscribeOnlySession` only, 4 lines of state → 2 sealed closures. Nothing
else in the file moved.

**Nothing was armed.** No publisher, `ControlManager`, lease or motion client was
created. No vendor SDK was installed into `.parcel/`; `rclpy`, `unitree_sdk2py`,
`pyrealsense2` and `unilidar_sdk2` are still absent from this interpreter and
the new dynamic probe reaches them only as **fakes bolted into `sys.modules` of
a subprocess**, whose publisher- and motion-creating entry points raise.

---

## Per-finding table

| # | Finding | Reproduced | Fixed | Regression test | Evidence |
|---|---------|-----------|-------|-----------------|----------|
| 1 | No pin covers `rosbag2.py`, `budget.py`, `rehearse.py`, `scripts/parcel_capture/__init__.py` | **YES** — appended the auditor's literal `create_publisher("/cmd_vel")` + `SportClient().Move(0.5,0,0)` to all four; **795 passed rc=0**, and `ci_gate --tier commit` printed **`RESULT: PASS`** over **4878 passed** | **YES** — `tests/test_no_arm_pin.py` walks both trees **recursively** | `test_no_module_in_the_capture_stack_names_or_assembles_a_command_surface[<each of 19 files>]`, `test_the_pinned_set_contains_the_four_modules_that_were_covered_by_nothing` | §1 below |
| 2a | Pin globbed `*.py`, never descending into subdirectories | **YES** — planted `ingest/sub/armed_reader.py` (literal publisher + `SportClient().Move()`); **all 47 pin tests passed rc=0** | **YES** — `rglob`, plus a coverage self-test against an independent `os.walk` | `test_the_pin_reads_every_file_in_both_capture_trees_recursively`, `test_seeded_failure_a_non_recursive_glob_misses_a_planted_subpackage`, `test_the_tranche_wide_no_arm_pin_covers_every_file_in_this_package` | §2 below |
| 2b | Literal-symbol AST scan defeated by ordinary aliasing (6 of 7 evasions passed both halves) | **YES** — measured **7 of 8** spellings pass both halves of the old pin | **PARTLY, and scored honestly** — static half now folds constants, censuses reach builtins, bans aliasing and mangled/private reaches; a **dynamic** half was added | `test_each_auditor_evasion_is_scored_against_the_new_static_half[8]`, `test_each_auditor_evasion_is_scored_against_the_dynamic_half[8]`, `test_the_static_half_is_honest_about_what_folding_cannot_reach` | §3 below |
| 3a | `ReadOnlyHandle.__slots__` made `_target` an ordinary descriptor; `handle._target.create_publisher(...)` published | **YES** — executed, got `PUBLISHER CREATED ON /cmd_vel` | **YES** — state moved to a closure-scoped `WeakKeyDictionary`; the instance has **no data slot at all** | `test_no_reach_through_a_read_only_handle_yields_the_wrapped_object` (10 spellings + `object.__getattribute__` + write + delete) | §4 below |
| 3b | `session._SubscribeOnlySession__node` and `session._rclpy` handed out the node and the whole `rclpy` module from another module | **YES** — executed both, published via the node | **YES** — both attributes deleted; `sealed_call` binds `spin_once`/`shutdown` into closures | `test_the_dds_session_exposes_neither_the_node_nor_the_rclpy_module` | §4 below |
| 3c | `NEVER_ALLOWED` was construction-time only; one `object.__setattr__` undid it | **YES** — widened the allowlist in place and published | **YES** — checked in `__getattribute__` **ahead of** the allowlist, on every access | `test_never_allowed_is_enforced_at_access_time_not_only_at_construction` (three branches, incl. widening the closure state itself) | §4 below |
| 4 | Overstated claims at `base.py:337-339,370-371` and `test_capture_ingest.py:307-308` | n/a | **YES** — rewritten to what is now true, with the residual named | `test_the_residual_introspection_routes_are_documented_and_still_open`, `test_this_pin_is_the_one_the_capture_stack_points_at` | §5 below |

---

## §1 — Finding 1, reproduced and closed

Mutation harness: `-B`, `PYTHONDONTWRITEBYTECODE=1`, explicit `__pycache__`
purge before and after, restore from a byte-copy backup.

**Reproduction.** Appended to all four modules:

```python
def _auditor_arm_the_dog(node):  # pragma: no cover
    from unitree_sdk2py.go2.sport.sport_client import SportClient
    publisher = node.create_publisher(object, "/cmd_vel", 10)
    publisher.publish(object())
    client = SportClient()
    client.Init()
    client.Move(0.5, 0.0, 0.0)
    return publisher
```

```
$ PYTHONDONTWRITEBYTECODE=1 .parcel/bin/python -B -m pytest -q <8 capture test files>
795 passed in 15.59s
PYTEST_RC=0

$ PYTHONDONTWRITEBYTECODE=1 .parcel/bin/python -B scripts/ci_gate.py --tier commit
[  PASS] HARD  default-suite   4878 passed, 9 skipped, 36 deselected, 5 warnings in 208.36s
RESULT: PASS — every hard gate green.
```

Both gates green with a literal motion client and a `/cmd_vel` publisher in the
module that builds the argv an operator types at the robot.

**After the fix**, with the same four mutations re-applied:

```
FAILED tests/test_no_arm_pin.py::test_no_module_...[scripts/parcel_capture/__init__.py]
FAILED tests/test_no_arm_pin.py::test_no_module_...[scripts/parcel_capture/budget.py]
FAILED tests/test_no_arm_pin.py::test_no_module_...[scripts/parcel_capture/rehearse.py]
FAILED tests/test_no_arm_pin.py::test_no_module_...[scripts/parcel_capture/rosbag2.py]
```

**Restore verified byte-identical**: the four target files `cmp`-equal to their
pre-mutation backups; `grep -rn "AUDITOR MUTANT|_auditor_arm_the_dog|AUDITOR PLANT" --include='*.py' .`
returns nothing.

Coverage the pin now reads (19 files, asserted equal to an independent
`os.walk`): `src/parcel_robot/capture/{__init__,channels,envelope}.py` and
`scripts/parcel_capture/{__init__,attest,budget,clockmap,preflight,record,rehearse,rosbag2,sidecar,syncevents}.py`
plus `scripts/parcel_capture/ingest/{__init__,base,dds,fake,l2,realsense}.py`.

## §2 — Finding 2a, the one-character bug

```
$ (planted scripts/parcel_capture/ingest/sub/armed_reader.py, literal publisher + SportClient().Move())
$ .parcel/bin/python -B -m pytest -q tests/test_capture_ingest.py
47 passed in 0.44s      PYTEST_RC=0

pin reads:                 ['__init__.py','base.py','dds.py','fake.py','l2.py','realsense.py']
really there (recursive):  [... , 'sub/__init__.py', 'sub/armed_reader.py']
```

After the fix, the same plant:

```
FAILED tests/test_no_arm_pin.py::test_no_module_...[scripts/parcel_capture/ingest/sub/armed_reader.py]
  E  assert ["symbol 'Move'", ...] == []           (8 static violations)
FAILED tests/test_no_arm_pin.py::test_importing_...[scripts/parcel_capture/ingest/sub/armed_reader.py]
  E  AssertionError: import unitree_sdk2py.go2.sport     (dynamic half, at import)
FAILED tests/test_capture_ingest.py::test_the_tranche_wide_no_arm_pin_covers_every_file_in_this_package
```

Caught by **both** halves and by the delegation test in the file that used to
miss it.

## §3 — Finding 2b, the evasions, scored

Eight spellings: the auditor's literal control, the six that passed both halves
of the old pin, and one more (`chr()` arithmetic) that no constant folder can
ever read. `OLDsym` = the old symbol/import scan; `OLDcensus` = the old
dynamic-reach census; `NEWstatic` / `NEWdynamic` = the two halves of this card.
Measured, not asserted:

```
evasion                   OLDsym  OLDcensus |  NEWstatic  NEWdynamic  verdict
0-literal                 CAUGHT     missed |     CAUGHT      CAUGHT  armed: attribute rclpy.node.Node().create_publisher
1-alias-getattr           missed     missed |     CAUGHT      CAUGHT  armed: attribute ...create_publisher
2-operator-attrgetter     missed     missed |     CAUGHT      CAUGHT  armed: attribute ...create_publisher
3-dunder-getattribute     missed     missed |     CAUGHT      CAUGHT  armed: attribute ...create_publisher
4-vars-dict               missed     missed |     CAUGHT      CAUGHT  armed: class-dict call create_publisher
5-unmangled-raw-node      missed     missed |     CAUGHT      missed  ok
6-exec-string             missed     missed |     CAUGHT      CAUGHT  armed: attribute ...create_publisher
7-chr-arithmetic          missed     missed |     CAUGHT      CAUGHT  armed: attribute ...create_publisher

OLD pin: 7/8 passed BOTH halves      NEW pin: 0/8 pass BOTH halves
```

**I do not claim the dynamic half caught all eight.** Row 5 is `missed`
dynamically, and the reason is the honest one: the module *was* imported and its
public function *was* called (`exercised: ['import', 'call public_probe()
(refused: AttributeError)']`) — it failed because `_SubscribeOnlySession__node`
no longer exists. The `dds.py` fix removed the target; the tripwire did not
notice the attempt. If that attribute ever comes back, only the static half
stands between it and a publisher. `DYNAMIC_EVASIONS["5-unmangled-raw-node"]`
carries `False` and a test asserts the *reason* (reached, then refused) rather
than accepting silence.

What made rows 3, 4 and 7 flip from `missed` to `CAUGHT` on the dynamic half:
the fake vendor object overrides `__getattribute__` (so
`node.__getattribute__("create_publisher")` fetches and calls the wire itself)
and carries **real class-dict entries** for 21 arming names (so
`vars(type(node))["create_publisher"]` returns a live descriptor rather than
raising `KeyError` the way a bare `__getattr__` stub would). Without those two
details the dynamic half reports `ok` for reaches that would succeed against a
real `rclpy` node — measured, both before and after.

New static rules, each with its incidence measured against the clean tree before
being turned on (all but the last two fire zero times today, so none is a
tolerated-debt rule):

| Rule | Incidence on the clean stack | Catches |
|---|---|---|
| folded arming-string literals (`+`, adjacent, f-string, `"".join`, module-level tuple) | 17, all inside the `NEVER_ALLOWED` denylist assignment in `base.py`, which is the exemption — and only that assignment | evasions 1, 2, 3, 4 |
| reach-builtin **reference** without calling (aliasing) | 0 | evasion 1, evasion 6 (`_run = exec`) |
| `exec`/`eval`/`compile`/`vars`/`globals`/`locals`/`delattr`/`__import__` called at all | 0 | evasion 4, evasion 6 |
| state-reaching dunder (`__getattribute__`, `__closure__`, `__globals__`, `__subclasses__`, …) outside 3 vetted sites | 17 sites, all `object.__setattr__` in frozen-dataclass `__post_init__` plus `base.py`'s facade | evasions 3, 5, 7 |
| name-mangled attribute reach `._X__y` | 0 | evasion 5 |
| private `._x` attribute on a receiver other than `self`/`cls` | 0 | `handle._target`, `session._rclpy` |
| `getattr`/`setattr` call census, `(file, innermost function, builtin)` | 15 vetted sites, exact-match asserted both ways | any new reach |

One symbol exemption exists and is named: `publish_time` / `publish_time_ns`,
MCAP's own per-message timestamp field, which `record.py` **reads**. Exact-name
only — a real `create_publisher` in the same file is still caught. One census
entry is worth an auditor's eye:
`preflight.py:load_reader_factory` resolves an operator-supplied
`--reader-module pkg.mod:attr`. Whoever can pass that flag can already run
arbitrary code, so the reach adds no authority; it is recorded in
`VETTED_REACHES` with that reasoning rather than exempted silently. It is PS-D's
code, not PS-O's.

## §4 — Finding 3, the facade

Reproduction, executed (`repro_f3.py`, before the fix):

```
handle._target                          -> <FakeNode>          PUBLISH: PUBLISHER CREATED ON /cmd_vel
getattr(handle, '_' + 'target')         -> FakeNode
session._rclpy                          -> FakeRclpy
session._SubscribeOnlySession__node     -> FakeNode            PUBLISH: PUBLISHER CREATED ON /cmd_vel
object.__setattr__(h,'_allowed',...)    -> PUBLISH: PUBLISHER CREATED ON /cmd_vel
```

After the fix, the same script, extended to 14 reaches:

```
A. reaches THROUGH the handle object (must all be refused)
  [REFUSED] handle._target                          IngestRefusedError
  [REFUSED] getattr(handle, '_'+'target')           IngestRefusedError
  [REFUSED] getattr(handle, '_target', None)        IngestRefusedError   (the default does not swallow it)
  [REFUSED] handle.__dict__ / vars(handle)          IngestRefusedError
  [REFUSED] handle.__getattribute__('_target')      IngestRefusedError
  [REFUSED] object.__getattribute__(h,'_target')    AttributeError       (there is no slot)
  [REFUSED] operator.attrgetter('_target')(handle)  IngestRefusedError
  [REFUSED] handle.create_publisher                 IngestRefusedError
B. NEVER_ALLOWED at ACCESS time
  [REFUSED] object.__setattr__ widen then publish   AttributeError
  [REFUSED] closure-state widen then publish        IngestRefusedError
C. the DDS session
  [REFUSED] session._rclpy                          AttributeError
  [REFUSED] session._SubscribeOnlySession__node     AttributeError
  [REFUSED] session.handle._target                  IngestRefusedError
  session attribute surface: ['_shutdown', '_spin', '_subscriptions', 'handle']
== reaches through the object that still succeed: 0 of 14
```

Mechanism: `ReadOnlyHandle` is built by a factory so its `(target, allowed,
label)` record lives in a closure-scoped `WeakKeyDictionary`; the instance's
`__slots__` is `("__weakref__",)` — **no data slot exists to resolve**.
`__getattribute__` (not `__getattr__`; `__getattr__` is only consulted after
normal lookup fails, which is exactly why the slot beat it) checks
`NEVER_ALLOWED` first, then the allowlist, on every access. `sealed_call` binds
`rclpy.spin_once(node, …)` and `rclpy.shutdown(context=…)` at construction and
returns a plain function, which is how the session stopped needing to hold
either the node or the module.

The session still works — `test_the_dds_session_exposes_neither_the_node_nor_the_rclpy_module`
spins and closes it and asserts `(spun, shut) == (1, 1)`.

## §5 — Corrected claims, and the residual that stays open

| Where | Was | Now |
|---|---|---|
| `base.py:337-339` | "an adapter that holds one of these **cannot**, because the attribute does not resolve" | states what access through the object cannot do, then a paragraph naming what it does **not** close, ending "it is not a sandbox" |
| `base.py:370-371` (refusal text) | "nothing in the capture stack can reach a command surface, **by any spelling**" | "nothing reached **through this object** can be a command surface. That is a claim about this object only: see the class docstring for the introspection routes it does not close" |
| `base.py:19-21` (module docstring) | "an AST pin over this package asserts it" | names `tests/test_no_arm_pin.py`, both trees, both halves, and points at the residual |
| `test_capture_ingest.py:307-308` | node "is reachable **only from inside the class body** — not from a caller, and not from another module" | deleted; replaced by `test_the_dds_session_exposes_neither_the_node_nor_the_rclpy_module`, which asserts the stronger and now-true property that **no** slot names the node, the module or the context |

**The residual, asserted by a test so the docstring cannot drift**
(`test_the_residual_introspection_routes_are_documented_and_still_open`):

```
type(handle).__getattribute__.__closure__[0].cell_contents[handle].target  -> the vendor object
type(handle).__init__.__closure__                                          -> the same dictionary
sealed.__closure__[i].cell_contents.__self__                               -> the sealed target
```

All three still reach. No pure-Python object can close them. What **is** closed,
and is the part that mattered: `gc.get_referents(handle)` does not contain the
target — the handle instance holds no reference to the vendor object at all, so
nothing that starts from the object an adapter was handed can get there. The
difference is that reaching a command surface now requires deliberate closure
introspection, which the static half of the pin sees and refuses
(`state-reaching dunder .__closure__`), instead of one ordinary attribute access,
which it could not.

## §6 — What changed in `tests/test_capture_ingest.py`

Three tests were **removed**, not weakened, and their coverage relocated:

| Removed | Why | Replaced by |
|---|---|---|
| `test_no_symbol_in_the_ingest_package_can_reach_a_command_surface` | globbed one directory; symbol-literal only | `test_the_tranche_wide_no_arm_pin_covers_every_file_in_this_package` (recursive, all rules) |
| `test_seeded_failure_the_read_only_pin_catches_every_named_surface` | 10 mutants against the weak checker | `test_seeded_failure_the_tranche_pin_still_catches_what_this_file_used_to` — the same 10 mutants **plus** the two the old pin missed, through the new checker |
| `test_every_dynamic_attribute_reach_in_the_package_is_one_of_two_vetted_ones` | census attributed reaches to the *outermost* enclosing function (a reach inside a closure was credited to the factory around it) and covered one directory | `test_the_reach_census_is_exact_and_not_merely_a_subset`, innermost attribution, both trees, exact-set both ways |

Net test count for the two files: **138 passed** (72 in the new pin, 66 in
`test_capture_ingest.py`).

## §7 — Gates

```
$ .parcel/bin/python -m ruff check tests/test_no_arm_pin.py tests/test_capture_ingest.py \
      scripts/parcel_capture/ingest/base.py scripts/parcel_capture/ingest/dds.py
All checks passed!

$ PYTHONDONTWRITEBYTECODE=1 .parcel/bin/python -B -m pytest -q \
    tests/test_capture_envelope.py tests/test_capture_ingest.py tests/test_capture_preflight.py \
    tests/test_capture_rehearsal.py tests/test_capture_sidecar.py tests/test_clockmap.py \
    tests/test_rosbag2_sidecar.py tests/test_syncevents.py tests/test_no_arm_pin.py
938 passed in 34.09s      # run twice back to back, identical

$ .parcel/bin/python -B -c "ast.parse(src, feature_version=(3,10))"  # Orin's Python
3.10-parseable: scripts/parcel_capture/ingest/base.py
3.10-parseable: scripts/parcel_capture/ingest/dds.py
3.10-parseable: tests/test_no_arm_pin.py
interpreter: 3.14.4
```

`ci_gate --tier commit`, run on the final tree:

```
CI GATE — tier=commit  (2026-08-13T14:15:33Z)
[  PASS] HARD  ruff              7 violation(s), baseline 7, new 0
[  PASS] HARD  hard-safety       ... collisions=0 false_arrival=0 ...
[  PASS] HARD  default-suite     5071 passed, 9 skipped, 36 deselected, 5 warnings in 218.94s
RESULT: PASS — every hard gate green.
  elapsed 230.5s
```

Two earlier runs of the same command were **red on `ruff` only**, both from
other cards' in-flight edits, and both are recorded here rather than hidden:
`ingest/__init__.py::F821` + `preflight.py::RUF100` + `test_capture_ingest.py::RUF059`
(I fixed all three — see §8), then `ingest/l2.py::RUF100`, which PS-G's owner
fixed at 10:10:35 before my final run. `default-suite` was green in **all
three**, including this card's 72 new tests.

Cost of the pin: **19.5 s** for 72 tests, of which ~18 s is the dynamic half
(one subprocess per module; `preflight.py` alone is 17 s because its probe
entry points are exercised under a 3 s repeating-alarm budget each).

## §8 — Concurrency note for the auditor

Other executors were editing this tree throughout this card, including inside my
OWNS. Observed mtimes: `budget.py` 09:30, `rosbag2.py` 09:39, `preflight.py`
09:53, `realsense.py` 10:02, `l2.py` 10:04, and `tests/test_capture_ingest.py`
at **10:05:49, two seconds before I sampled the clock** — card PS-N is adding a
fake-SDK section to the same file.

Three consequences the auditor should know:

1. **No edit of another card was clobbered.** My mutation harness backed up
   immediately before mutating and restored immediately after; the four F1
   targets are `cmp`-equal to those backups with mtimes intact, and
   `grep -rn "AUDITOR MUTANT|_auditor_arm_the_dog|AUDITOR PLANT" --include='*.py' .`
   is empty. The pre-ruff-fix copy of `test_capture_ingest.py` is kept at
   `scratchpad/tci_before_ruffix.py`.
2. **Two intermediate suite runs failed and both were mid-write artifacts.** A
   9-file run at 10:03 failed
   `test_the_realsense_read_loop_executes_and_never_configures_the_device`; a
   rerun two minutes later failed two *different* L2 tests and passed the
   RealSense one; the test count moved 930 → 932 → 938 between runs with no
   edit of mine. Each failing test passed in isolation. Once the file stopped
   moving, the same 9-file command produced **938 passed** twice back to back.
   These were not caused by this card: the same set without
   `tests/test_no_arm_pin.py` also moved, and re-running after the writes
   settled is green with the pin included.
3. **I fixed three ruff violations outside my OWNS to unblock the gate**, each
   strictly-correct and one line: `ingest/__init__.py` was missing
   `from typing import Any` for an annotation another card added (**F821 — a
   genuine undefined name**); `preflight.py` carried a `# noqa: BLE001` that its
   own edit had made dead; and `test_capture_ingest.py:1681` unpacked a
   `sample` it never used. If PS-G or PS-D would rather own those, they are
   trivially revertible.

**The static census in `tests/test_no_arm_pin.py` is coupled to these files.**
If PS-D or PS-E adds a `getattr` call, `VETTED_REACHES` must gain the entry —
the pin fails loudly and names the file, the innermost function and the line, so
this is a designed handshake rather than a trap.

## does_not_prove

1. **It does not prove the capture stack cannot arm the robot.** It proves that
   two specific detectors, run over 19 specific files, find nothing today. A
   determined author with commit access can defeat both — the static half by
   building a name from bytes read at runtime, the dynamic half by putting the
   arming code on a path the exercise does not walk (a function with required
   arguments, a branch behind a config flag, a thread). The auditor's own
   `_auditor_arm_the_dog(node)` mutant is exactly that shape, and I measured it
   rather than asserting it:

   ```
   static : CAUGHT ["symbol 'Move'", "symbol 'SportClient'",
                    "symbol 'create_publisher'", "symbol 'publish'"]
   dynamic: {'status': 'ok', 'exercised': ['import']}
   ```

   The dynamic half imported it and stopped — the function is private and takes
   a required argument, so the exercise never called it. For that shape, only
   the static half stands between the code and a robot.
2. **The dynamic half has never seen real `rclpy`.** Every "the live branch
   executed" claim is against a fake whose attributes are tripwires. The real
   `rclpy.Context()`/`Node()`/`spin_once` have not run on this box and cannot;
   the first real execution is tomorrow on the Orin. A shape difference between
   the fake and the real API (a keyword name, a return type, a blocking call)
   would surface there and not here.
3. **`ReadOnlyHandle` is not a capability boundary.** Three introspection routes
   to the wrapped object remain open and are asserted open in §5. Any code
   running in the same interpreter — including a future capture module, a
   plugin, or a debugger — can take them.
4. **Nothing here constrains what is *outside* the two trees.** `bags/`,
   `runtime.py`, `navigation/**` and every other package are untouched by this
   pin. A capture module that imports something outside the stack which then
   publishes is caught only if the import name matches `FORBIDDEN_IMPORTS`.
5. **The exemptions are judgement, not proof.** `publish_time`/`publish_time_ns`
   and the `NEVER_ALLOWED` denylist literals are exempted because I read them and
   decided they are reads. `preflight.load_reader_factory` is vetted on an
   argument about authority, not on a proof.
6. **The 19-file coverage number is only true of this commit.** It is asserted
   against a live `os.walk`, so it cannot silently under-count — but a new tree
   (say `scripts/parcel_capture/tools/`) is covered only if somebody adds it to
   `CAPTURE_TREES`. Nothing detects a *third* tree that should have been in
   scope.
7. **No hardware claim of any kind.** Nothing in this card was run against a
   robot, a LiDAR, or a camera, and no statement here is evidence about the Go2,
   the L2 or the D455.
