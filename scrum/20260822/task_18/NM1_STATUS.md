# NM-1 + ASK-1 — a promotion gate that tests correctness, and a question that grants nothing · status

**Card:** `README.md` · **Design:** `../WAVE2_DESIGN_FABLE.md` §1 (DW-2) ·
**Board:** `../TASK_BOARD.md` · **Pre-registration:** `NM1_PREREGISTRATION.md`
(sha256 `de2228a2af23c7b28b6620ff9f30e7426e27ddb368b7d7903ecff7ff9d3c001c`,
written before the first line of NM-1 source and before any model ran)
**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22

---

## Headline

**COMPLETE, with the card's own headline row MISSED — and the miss is a
refutation of the card's premise, measured on the evidence the card named.**

Three of the four DW-2 slices landed and are green on the product path:

* **(a)** the 10 Hz loop now **marks its own thread**, so P1-D's tripwire is
  armed on the real loop for the first time (it had zero product callers), and
  a FATAL test walks the loop's **transitive** call graph — 118 methods — for
  any model constructor, warm-up, inference, image encode, weight load or
  network call. Seeded RED at depth 1 **and** depth 2.
* **(b)** the veto is no longer computed inside a grounding call. A bounded
  worker publishes immutable verdicts carrying query / place / **place
  revision** / model / capture time / result time / expiry, and navigation
  consumes only a ready, matching, fresh one. Measured **through the product
  path** (`OnlineSemanticMap.resolve`, no monkeypatch, real Qwen3-VL-2B):
  P1-D's admissions are **preserved exactly — 5 of 7 present, 0 of 8 absent —
  while the per-resolve cost falls from 67 ms of GPU generation to 0.092 ms**,
  and the model never once answers on the caller's thread.
* **(c)** `AbstentionVerdict.as_ask()` reaches the owner through the broker.
  P1-D built that payload and could not wire it; it is wired now, and the
  question **touches no door**: 0 `navigate`, 0 `on_dispatch`, 0 supervisor
  admissions. Motion starts only when the owner confirms a token that matches a
  **freshly recompiled** verdict — no pending state is stored, so a stale token
  and an invented one fail identically. `verdict.candidate` is carried through
  unchanged; CURIO-1's `ask_about` feed and this envelope read the same field.

**(d) is the miss.** The correctness judge is built, wired, seeded and
measured — and **it does not separate on this world.** The card's premise was
that an open-vocabulary detector is an independent judge the VLM cannot collude
with. Measured: on the 21 crops the VLM named wrongly, OWLv2 scores the
**wrong** name above the true class name on **16 of those same 21 crops**
(paired medians 0.0651 vs 0.1225), and **no floor between 0.02 and 0.90 reaches
the pre-registered 0 false promotions**. The mechanism is right; the signal is not there. Why is the
useful part, and it is the same sentence P1-D wrote about the 45 %:

> The bollard **is** a yellow cylinder. A detector asked "is there a yellow
> cylinder in this crop?" answers yes — correctly, at 0.93 — while scoring
> "bollard" on the same pixels below the floor. **A perceptual judge cannot
> reject a perceptually-true name.** The ground truth in this scene is a fact
> about the renderer's *intent*, not about its appearance, and no amount of
> extra perception recovers an intent.

The gate still removes one of P1-D's two false promotions (`pole` for the
traffic light leaves `known_places()`), which is a real improvement and an
accidental one. It is reported as such, not banked.

---

## 1. What changed

| File | + | − | Note |
|---|---:|---:|---|
| **new** `src/parcel_robot/vlm_veto/judge.py` | 481 | — | the correctness judge, OWLv2 behind a lazy import |
| **new** `src/parcel_robot/vlm_veto/bureau.py` | 529 | — | the bounded worker + `PublishedVerdict` |
| **new** `tests/test_nm1_promotion_and_asks.py` | 1748 | — | 49 tests, every one naming its seed |
| `src/parcel_robot/online_map/naming.py` | 201 | 1 | the judge in the pass; `hold_at_hypothesis` |
| `src/parcel_robot/perception_abstention.py` | 94 | 3 | control-thread registry (2 marked regions); `resolve_veto` reads the board |
| `src/parcel_robot/vlm_veto/__init__.py` | 46 | 0 | exports |
| `src/parcel_robot/vlm_veto/runner.py` | 21 | 25 | the registry moved out; the four names re-exported unchanged |
| `src/parcel_robot/vlm_veto/verifier.py` | 43 | 6 | `describe(prompt=...)` + the prompt arm's sentence |
| `src/parcel_robot/runtime.py` | **174 lines in 3 marked regions** | — | thread marking; the ASK door + subject digest; the door wiring |
| `src/parcel_robot/realtime/tool_broker.py` | **200 lines in 8 marked regions** | — | `ask_place` door, the ASK arm, the one-shot confirm contract |
| `tests/test_p1d_eval_rows.py` | 22 | 0 | **declared deviation**, §6.1 |

`runtime.py` and `tool_broker.py` are being edited by OT-2 and others in the
same tree right now; the `git diff --stat` on those two files is **not** mine
and the numbers above are the line counts of the regions marked
`# ---- CARD NM-1 (task_18)` / `# ---- CARD ASK-1 (task_18)`. Every one of my
edits is inside such a region and every file was re-read immediately before
each edit.

Not touched: `online_map/` other than `naming.py`, `perception_abstention`'s
signal roster (`DEFAULT_SIGNALS` / `REGISTERED_SIGNALS` / the `SIGNAL_*`
constants are byte-unchanged), `camera_channel/ingress.py`, `reactive_safety`,
`core/hard_stop`, the e-stop latch, `pyproject.toml`, `scripts/ci_gate.py`,
`configs/**`, `docs/`, `backlog/`, `README.md`, `scrum/20260821/`, the venv.
No git write command was run. No process was killed. No socket and no port was
opened. The owner's `parcel_memory.sqlite3` was never opened.
Scratch: `/home/jaewoo-jang/.cache/parcel-nm1/`.

### The shape, in one paragraph each

**The judge.** `OwlV2NamingJudge` asks the shipped OWLv2 seat "where is a
`<proposed name>` in this crop?" and compares the best box score against
`JUDGE_MIN_SCORE = 0.10` — **adopted, not fitted**: it is
`detection_adapter.owlv2_onnx.DEFAULT_OWLV2_THRESHOLD`, pinned to it by a test
so the two cannot drift. The detector is built with a **zero** threshold so the
floor lives in this class and the raw strength is reportable; a gate whose
threshold hides inside a dependency is a gate nobody can sweep. It refuses the
control thread. It adds **no config key**: it is on exactly when the real
detector is on (`PARCEL_OWLV2_ONNX`), because the two blocks that could have
carried a naming key belong to other cards and both hard-error on unknown keys
(§6.2).

**Unavailable is a HOLD, never a rejection.** No judge configured ⇒
`run_naming_pass` is HEAD, byte for byte (measured, row F). A configured judge
that cannot answer holds a promotion happening *now* and **never takes standing
away from a name that already had it** — an unavailable judge that demoted
would be a silent fail-closed default every time the GPU is busy, which the
wave's standing rules forbid. A rejected name is held at `vlm_proposed` **with
every visit it earned**: a hold is not a demotion, because nothing about the
visits changed.

**The bureau.** `resolve_veto` now installs `VerdictBureau.read`. It never
blocks, never loads a model and never generates: it looks the pair up on a
bounded board and returns the published answer or `VETO_UNAVAILABLE` — which
the gate already reads as ASK — while scheduling the judgement on one bounded
worker thread. `place_revision(place)` is a digest of the evidence the answer
would be computed on (label, crop bytes, position, counts) and deliberately
**excludes `similarity`**, which moves with the query rather than the place. A
verdict whose revision no longer matches is not consumed.

**The ASK.** A new `ToolDoors.ask_place` door compiles the abstention verdict
for a place name and returns `as_ask()` plus a `revision` digest. The broker
consults it *after* `validate_place` and *before* `_validated` / `on_dispatch`
/ `navigate`. The owner's "yes" comes back as `confirm=<token>` and is compared
against a verdict compiled **right then** — so a token is only good against the
state of the world it was issued for and a token nobody issued cannot match. The
broker stores no *pending question*; after the correction pass it does keep a
bounded set of **spent** tokens, so a confirmation authorises one trip rather
than standing open. The door is deliberately **not**
wrapped in `_gate_by_voice` or `_watch_under_latch`: those exist for doors that
commit the body, and a stopped robot that will not say what it is unsure of is
a worse robot, not a safer one.

---

## 2. Work item 1 — three arms, same 40 crops, real seat

Qwen3-VL-2B on the GPU through the repo's own `vlm_veto` wrappers (not a
re-implementation), weights **found** in the 2026-08-21 research cache, nothing
downloaded. Scorer: P1-D's frozen synonym table, verbatim.
Artifact: `evidence/arms_three.json`, harness `evidence/run_arms.py`.

| Arm | Crop | Prompt | Pre-registered | Measured | |
|---|---|---|---|---|---|
| **A1 fullres** | committed 384-px PNG | `NAME_PROMPT` | 45.0 % ± 7.5 (reproduction) | **19/40 = 47.5 %** | **MET** |
| **A2 thumb64** | the 64-px crop the map STORES | `NAME_PROMPT` | < A1 and ≤ 40 % | **12/40 = 30.0 %** | **MET** |
| **A3 prompt** | committed 384-px PNG | class-anchored (pre-registered verbatim) | ≥ A1 + 5 pts | **19/40 = 47.5 % (+0.0)** | **MISSED** |
| — | any arm reaching the research's 82–87 % | | predicted: **no** | none did | **MET** |

Latency p50 40–51 ms per answer, consistent with P1-D's 41.2 ms.

**The answer to "why 45 %": resolution, not prompt.** The 64-px thumbnail the
map actually stores costs **17.5 accuracy points** against the same model on the
same objects — the shipping path is blind, exactly as P1-D suspected, and now
the size of the blindness is measured. The class-anchored prompt moved
*individual classes* (planter 0/4 → 2/4, building 3/4 → 1/4) and netted **zero**:
telling the model not to describe colour or shape does not make it know the
class. Per class, A1:

```
door 4/4   tree 4/4   bench 3/4   building 3/4   crate 2/4   lamppost 2/4
traffic light 1/4   bicycle 0/4   bollard 0/4   planter 0/4
```

`NAME_PROMPT` is unchanged and remains the only prompt any product path uses;
A3's sentence ships as a named constant used by nothing but the arm, because a
reworded prompt is an unmeasured model.

---

## 3. Work items 2–3 — the judge, and the refutation

Real OWLv2-B16, fp16, `CUDAExecutionProvider`, weights `~/.cache/parcel/owlv2-b16`.
P1-D's full-resolution k-gate arm is **replayed name-for-name** from its own
committed answers (`row4_naming.json`, deterministic decoding), so the arm the
gate is judged against is P1-D's, not a re-run that could differ.
Artifact: `evidence/judge_rows.json`, harness `evidence/run_judge.py`.

| Row | Claim | Bound | Measured | |
|---|---|---|---|---|
| **F** | flag-off identity: replay with `judge=None` | P1-D's 2 promotions, 2 false | **2 promotions, 2 false**; `known_places()` gains `pole`, `yellow cylinder` | **MET** |
| **J1** | judge on `pole` over `traffic_light_1` | REJECT | 0.522 / 0.247 / **0.065** — rejected on the view that promotes | **MET** |
| **J2** | judge on `yellow cylinder` over `bollard_1` | REJECT | 0.339 / 0.635 / **0.932** — accepted on all three | **MISSED** |
| **J3** | false promotions, judge ON | **0** | **1** (2 → 1) | **MISSED** |
| **J4** | a CORRECT k-agreed name blocked by the judge | 0 | **0** | **MET** |
| **J5** | judge recall on the true class name, 40 crops | ≥ 0.80 | **0.475** | **MISSED** |
| **J6** | judge acceptance of the VLM's WRONG names | ≤ 0.25 | **0.571** | **MISSED** |
| **J7** | judge latency, per crop, GPU | p50 ≤ 250 ms | **p50 103 ms / p95 108 ms** (n = 61) | **MET** |

`known_places()` with the judge ON loses `pole` and keeps `yellow cylinder`.

### 3.1 Why it misses, stated precisely

**Corrected in the correction pass to the PAIRED statistic** — the first version
compared a 40-crop set against a 21-crop set, which is true but sloppy. The
paired form is stronger and exactly right:

> On the **21 crops where the VLM got the name wrong**, the detector scores the
> **wrong** name above the **true class name — on 16 of those same 21 crops**.
> Paired medians on that set: **0.0651 true vs 0.1225 wrong**; paired mean
> difference **+0.184** in favour of the wrong name.

The signal is not weak, it is *anti-correlated* with class correctness. The top
of the wrong-name table:

```
bollard        VLM said "yellow cylinder"  judge ACCEPT 0.932
bollard        VLM said "yellow cylinder"  judge ACCEPT 0.824
crate          VLM said "wooden wall"      judge ACCEPT 0.603
traffic light  VLM said "pole"             judge ACCEPT 0.522
bicycle        VLM said "black box"        judge ACCEPT 0.515
```

Every one of those is a **true description of the pixels**. The two seats are
not colluding — they are independently right about appearance and independently
wrong about class, because in `city_block` the class is a property of the
scene's intent. The VLM's failure mode P1-D identified (it describes geometry
when it does not know the class) is precisely the failure mode a detector
cannot see, because a description is exactly what a detector is good at
finding.

**And the narrowing this deserves, declared:** the fixture contains views in
which the ground-truth class is **not recoverable by any observer**. A 0.35 m
eye-height crop of a yellow cylindrical primitive does not contain the
information "bollard"; that word is in the scene file, not in the pixels. So
§3's numbers bound what a *perceptual* judge can do on **this** fixture, and
they do not bound what one could do on frames where the class is actually
visible. That is exactly why the D455 re-measurement (§10) is the follow-up
that matters, and why nothing here is offered as a verdict on OWLv2.

**What the verifiers ruled out, and what NM-1 could not rule out.** The
verification pass attacked the three hypotheses that would have made this a bug
rather than a result: two alternative prompt templates ("an image of a {}" and
the model card's "a photo of a {}") are both *worse*, with the inversion
invariant at 16/21 paired; J5/J6 were already measured on 384-px full-resolution
crops rather than the 64-px thumbnails; and the detector is built with a zero
threshold so the floor really is applied in the judge. The first floor with zero
wrong-accepts is 0.935–0.95, where true-name recall is 0.00. It is not
mis-prompted, mis-thresholded, or looking at the wrong crop.

### 3.2 The floor was not the lever (POST-HOC, declared)

Added **after** J3 missed, and labelled as such: the pre-registration fixed the
floor before any crop ran and that row is not re-pointed. The sweep answers one
question — was the number wrong, or is the signal absent?

| floor | promotions | **false** | true-name recall | wrong-name accept |
|---:|---:|---:|---:|---:|
| 0.02 | 2 | **2** | 0.750 | 0.810 |
| 0.05 | 2 | **2** | 0.625 | 0.667 |
| **0.10** (shipped) | 1 | **1** | 0.475 | 0.571 |
| 0.20 | 1 | **1** | 0.275 | 0.429 |
| 0.30 | 1 | **1** | 0.150 | 0.333 |
| 0.40 | 1 | **1** | 0.100 | 0.333 |
| 0.50 | 1 | **1** | 0.075 | 0.286 |
| 0.70 | 1 | **1** | 0.000 | 0.095 |
| 0.90 | 1 | **1** | 0.000 | 0.048 |

**There is no operating point.** At 0.90 the judge accepts nothing true at all
and *still* promotes `yellow cylinder`, because 0.932 ≥ 0.90. The wrong-name
accept rate exceeds the true-name recall at every floor. A floor tuned to kill
0.932 would be fitted on the two rows it is judged by, which is the mistake
PG-3's docstring is about and which this card did not make.

The shipping 64-px arm was measured too: **1 promotion, 1 false** — the same
residue, for the same reason.

### 3.3 The 64-px crop, measured (correction pass)

The verifiers flagged that §3.1 was measured on 384-px crops while the shipping
path feeds the judge `entry.thumbnail`, which is 64 px, and reported that the
anti-correlation **reverses sign** there. That is a real caveat to check, so
NM-1 re-ran the whole J5/J6 pair on the 64-px thumbnails
(`evidence/judge_thumbnail64.json`, harness `evidence/run_judge_thumb.py`).

**The reversal did not reproduce, and the caveat survives in a weaker form.**

| statistic | 384 px | 64 px |
|---|---:|---:|
| paired: wrong name beats true name | **16 / 21** | **16 / 21** |
| paired mean difference (wrong − true) | +0.184 | +0.089 |
| unpaired median true / wrong | 0.0931 / 0.1225 | 0.0625 / 0.0669 |
| accept rate, true names (J5) | 0.475 | 0.425 |
| accept rate, wrong names (J6) | 0.571 | 0.476 |

Every statistic keeps the same **sign** at both crop sizes; none reverses. What
*is* true, and is the honest version of the note, is that the **aggregate margin
nearly vanishes** at 64 px — the unpaired median gap collapses from 0.029 to
0.004, an order of magnitude — while the **paired** result is bit-for-bit
identical at 16/21. So: the paired inversion is crop-invariant on this fixture
and is what §3.1 should be read as claiming; any conclusion drawn from the
unpaired medians is crop-dependent and must not be generalised. Reported this
way rather than either accepting or dismissing the note, because the two
statistics genuinely behave differently and only one of them is stable. If the
verifiers measured a reversal with a different statistic, the raw per-crop rows
for both sizes are in the two evidence files and the disagreement is one
comparison away from being settled.

---

## 4. DW-2 (a) — no model on the 10 Hz thread, fatally

| Row | Claim | Bound | Measured | |
|---|---|---|---|---|
| **C1** | forbidden names reachable from `_control_loop`'s transitive call graph | 0 | **0** over **118** reachable methods | **MET** |
| **C2** | the loop marks its own thread | present | marks on entry, clears in `finally` | **MET** |
| **C3** | a veto / a judgement on a marked thread raises | raises | `ControlLoopViolation`, both seats | **MET** |
| **C4** | `runtime.py` imports no `vlm_veto`, `torch` or `transformers` | 0 | **0** | **MET** |

The forbidden set is 25 names covering constructors, warm-ups, inference,
image encode/decode, weight loads and network calls, and the check is
**transitive** over `RobotRuntime`'s `self.<method>` edges — seeded at depth 2
(a `load()` inside `_step_activities`, two hops from the loop) as well as at
depth 1, because P1-D's version listed two methods by hand and a hand-list is
exactly as good as it stays current. The walk asserts it reached more than
twenty methods, so a graph builder that silently stops walking is itself a
failure.

The registry moved from `vlm_veto/runner.py` into `perception_abstention` and
is re-exported unchanged. That move is the point: `runtime.py` may not import
`parcel_robot.vlm_veto` at any scope (P1-D's own test says so, and the rule is
right), which is *why* `mark_control_thread` had zero product callers and the
tripwire was never armed. Three tests cover marking, clearing, and clearing
after the loop raises — thread ids get recycled, and a loop that exits still
marked would make the next thread refuse legal work.

---

## 5. DW-2 (b) and (c) — measured through the product path

### 5.1 The bureau, on `OnlineSemanticMap.resolve`, real seat, no monkeypatch

`evidence/product_bureau.json`, harness `evidence/product_bureau.py`. Same
fixture, same prototype policy and the same entry point P1-D measured.

| pass | admit | ask | present admitted | absent admitted | ms per resolve | veto asked |
|---|---:|---:|---|---|---:|---:|
| 1 — cold board | 0 | 8 | 0 / 7 | 0 / 8 | **0.094** | 0 |
| 2 — published | **5** | 0 | **5 / 7** | **0 / 8** | **0.092** | 8 (mean 67.1 ms, on the worker) |

**P1-D's admissions, preserved exactly, at a fraction of a percent of the
mission-path cost.** The first question about a place is answered with a
question — which is the posture the whole wave is built on — and the answer is
there by the next one. Bureau counters over the two passes: 16 reads, 8 miss,
8 requested, 8 published, 8 hit, 0 dropped, 0 stale, 0 mismatched, 0 worker
errors.

Unit-level rows, all **MET**: 0 synchronous verifier calls on the caller's
thread (W1); missing (W2) / expired (W3) / revision-mismatched (W4) /
budget-declined (W8) all ASK; a ready-matching-fresh verdict IS consumed (W6);
the queue is bounded and overflows by dropping and counting rather than
blocking (W5, measured with a wedged worker: 12 reads, ≤ 3 requested, ≥ 1
dropped, no read blocked); `PublishedVerdict` is frozen and refuses to be built
without a query, a place and a revision (W7).

### 5.2 The ASK, through `RealtimeToolBroker.handle`

All **MET**, each with a recording `ToolDoors` that fails if anything is
touched: B1 `navigate` calls on an ASK = **0**; B2 `on_dispatch` = **0** (and
supervisor `validate` = 0, which the pre-registration did not ask for and which
is the one that actually grants motion authority); B3 the payload's
`candidate` is the verdict's own `candidate` and is asserted to DIFFER from the
query, so a build that speaks the query instead is visible rather than hidden
behind two matching strings; B4 a matching confirmation against a freshly
compiled revision starts **exactly one** trip; B5 a token whose revision has
moved re-asks with the new token and moves **nothing**; B6 an invented token
moves **nothing**. Two more beyond the pre-registration: a host that has not
wired the door behaves **byte-identically to before this card**, and a door
that throws leaves `navigate_to` working and writes a note.

---

## 6. Deviations from OWNS, declared

1. **`tests/test_p1d_eval_rows.py` (+22).** Another card's test.
   `test_rows_1_to_3_with_the_real_seat` resolves once and asserts; with the
   board reader installed that first resolve is an ASK by design, so the row
   would have failed **the moment anyone ran it with a GPU** — a landmine, not
   a passing test. It now warms the board and drains before asserting, in a
   marked region, with a comment naming NM-1 and the reason. The assertions and
   their numbers are untouched. **Re-run with the real Qwen3-VL-2B seat and
   `PARCEL_P1D_GPU_EVAL=1`: 1 passed**, and the whole P1-D pair is 53 passed
   with GPU flags on.
2. **No config key was added, and the card asked for one**
   (`configs/navigation/prototype.yaml` naming keys). Both blocks that could
   host it belong to other cards and both hard-error on unknown keys:
   `perception.online_map` is validated by `_p1b_map_settings` inside
   `runtime.py`'s P1-B region (MUST NOT TOUCH), and `perception.abstention` is
   validated by `AbstentionPolicy` **and** pinned path-by-path by P0-D's
   exhaustive profile ratchet. Adding a key there means editing another card's
   region or another card's ratchet, so per the OWNS discipline I **halted on
   that item**. The judge instead honours the switch the real detector already
   has (`PARCEL_OWLV2_ONNX`) plus `PARCEL_NM1_JUDGE_FLOOR` for a sweep, and the
   floor is a named module constant pinned to the detector's own. Handoff 3.
3. **`vlm_veto/verifier.py` gained `describe(prompt=...)`.** In OWNS
   ("`vlm_veto/` prompt/crop handling"), keyword-only, defaulting to `None`, so
   every product caller asks exactly the sentence the accuracy numbers were
   measured with. Named here because it changes a public signature.
4. **The control-thread registry moved out of `vlm_veto/runner.py` into
   `perception_abstention.py`.** The four public names are re-exported from
   `vlm_veto` and are the *same objects*, so every existing import site, test
   and P1-D seed keeps working; `perception_abstention`'s signal roster is
   byte-unchanged. The reason is in §4 and in the marked region.
5. **A bench venv was created** at `/home/jaewoo-jang/.cache/parcel-nm1/benchvenv`
   (Python 3.13, torch 2.13+cu129, transformers 5.15.1, torchvision) because
   `.parcel` carries no tensor library by design and the 2026-08-21 research
   venv P1-D used is gone from this host. **`.parcel` was not touched** and
   `pyproject.toml` was not edited. The VLM ran there; the judge, the tests and
   every gate ran in `.parcel`.
6. **Seeds ran on a byte-identical scratch copy of the repo**
   (`/home/jaewoo-jang/.cache/parcel-nm1/seedrepo`, `PYTHONPATH` ahead of the
   editable `.pth`), never on the shared tree — five other wave-2 cards are
   running tests in it right now and a seed that reddens their run has damaged
   their evidence. Restoration is still asserted by sha256 and `__pycache__` is
   purged before and after each seed.
7. **A post-hoc arm was added** (§3.2) and is labelled POST-HOC. No
   pre-registered row was re-pointed.
8. **`tests/test_arrival_semantics.py` (+34/−1).** Another card's test and
   outside this card's OWNS; edited on the coordinator's explicit written
   authorisation after the wave-2 gate, and only that one test. ASK-1's
   `confirm` property reddened a DELIBERATE absence-pin. The pin was **moved,
   not routed around and not deleted** — see the correction pass, C8.

---

## 7. Seeded RED — 28 of 28 (**39 of 39** after the correction pass)

`evidence/run_seeds.py`. One-line mutation of the PRODUCT on the scratch repo,
the named test run, restore in a `finally` with a sha256 check, `__pycache__`
purged before and after, anchor uniqueness asserted (three seeds were reported
not-caught or anchorless on the first pass and were **rewritten rather than
dropped** — one mutated a line the property did not depend on, one hit the
wrong judge class, and one failed at import instead of at the assertion).

```
promotion without the judge's agreement                        RED
the judge floor lowered so everything passes                   RED
an UNAVAILABLE judge is read as agreement                      RED
a rejected name is left promoted instead of held               RED
the hold takes a supporting visit away (a demotion, not a hold) RED
the control loop no longer marks its thread                    RED
the control loop leaves its thread marked on exit              RED
a VLM call is added to the 10 Hz loop's call graph             RED
a model load is added one hop DEEPER than the loop itself      RED
the judge may run on the control thread                        RED
a control-loop violation is softened into a hold               RED
the gate goes back to synchronous inference                    RED
a stale verdict is consumed                                    RED
a verdict about another revision of the place is consumed      RED
the place revision ignores the pixels                          RED
the worker queue is unbounded and the caller blocks            RED
a declined GPU moment is re-asked on every resolve             RED
the ASK falls through and dispatches motion                    RED
any confirmation is accepted, stale or invented                RED
the ASK speaks the query instead of the verdict's candidate    RED
the runtime stops wiring the ASK door                          RED
a broken ask door raises out of navigate_to                    RED
the model is never told how to confirm                         RED
the naming pass judges by default (flag-off identity broken)   RED
an unavailable judge reports a strength of zero                RED
a missing crop is a REJECTION rather than a hold               RED
the detector label may be held                                 RED
the runtime imports the veto package directly                  RED
28/28 seeds caught
```

---

## 8. How it was verified

`.parcel/bin/python` / `.parcel/bin/ruff`, `TMPDIR` unset, throughout.

| Gate | Result |
|---|---|
| `pytest -q tests/test_nm1_promotion_and_asks.py` | **39 passed, 1 skipped** (the OWLv2 arm) |
| the same with `PARCEL_OWLV2_ONNX=1` | **40 passed** |
| `pytest -q` over `test_p1d_vlm_veto` `test_p1d_eval_rows` `test_c2_online_map` `test_p0d_navigation_unblocks` `test_realtime_tool_broker` `test_p0b_companion_unlocks` | **248 passed, 1 skipped** |
| `pytest -q` over `test_curio1_chatter` `test_p2a_owner_model` `test_p2a_memory_probes` `test_scene_and_memory_answers` `test_c3_cutover` `test_c1_camera_stream` | **350 passed** |
| `pytest -q` over `test_runtime_activation` `test_prototype_profile` `test_release_parity` `test_p1b_map_learns` | **108 passed** |
| P1-D's pair, **real Qwen3-VL-2B seat**, `PARCEL_P1D_GPU_EVAL=1` + `PARCEL_OWLV2_ONNX=1` | **53 passed** (incl. the GPU eval row) |
| Seeded RED, 28 mutations of the product | **28/28 RED** |
| `ruff check` on every file this card touched | **All checks passed** |
| `ruff check .` — the ratchet, at the scope the gate actually uses | **7 `src/` fingerprints, exactly the baseline set**; this card adds none. (The one other finding in the tree is `tests/test_duplex1_rows.py`, DUPLEX-1's in-flight work, not mine.) |
| GPU | 31 GB free before the runs; nothing killed; the MOVE-1 sim and the `:8765` panel untouched |

`scripts/ci_gate.py` was **not** run (another card owns it). No `noqa` was
added; the ruff baseline was not regenerated.

**Correction pass, and the reason this row moved.** The first version of this
table said `ruff check src/ tests/`, which is the **wrong scope**:
`_ruff_fingerprints` runs `ruff check .` over the whole repo and ruff is the
FIRST required stage of the commit tier. My four committed evidence scripts
under `scrum/20260822/task_18/evidence/` were the tree's **only** extras over
the pinned baseline — 8 new fingerprints — so the commit tier would have gone
red on this card's own paperwork, and the narrow scope is exactly why the miss
was invisible to me. All eight were mechanical and are fixed (unused `noqa: E402`
directives, `dict()` → literals, a context-managed `json.dump`, an unused
`import time`, five unparenthesised implicit concatenations, `check=False` on
`subprocess.run`). Ten committed evidence scripts from five other cards
contribute zero: lint-clean evidence is the tree's norm and this card was the
exception.

---

## 9. What this does NOT prove

1. **Nothing here was measured on a real camera.** Every crop is a MuJoCo
   render of textured primitives, and §3.1 is precisely a statement about what
   that costs. **No number in §2 or §3 transfers to a D455.** The judge's
   operating point is unestablished, and the first real frames are the first
   place it means anything.
2. **`run_naming_pass` has no product caller.** It did not have one before this
   card either — nothing in `src/` calls it. The judge is therefore delivered
   into the only path that exists, measured on the real map with the real
   detector, and is not yet running anywhere in the robot. Wiring it is P1-B /
   ROAM-2 territory (the idle checkpoints) and out of this card's OWNS.
3. **The `known_places()` protection that IS live today is unchanged by this
   card.** `RobotRuntime._curiosity_admitted_names` already excludes every
   `vlm_proposed` name, so a held name cannot be spoken — but that gate was
   already there, and NM-1 only makes more names land in the held state.
4. **The judge halves the false promotions for an accidental reason.** `pole`
   is rejected because the *particular view* the entry carried at the promoting
   visit scored 0.065; two other views of the same object score 0.52 and 0.25.
   Do not read 2 → 1 as a gate working.
5. **The ASK is wired but has never been spoken by a hosted model.** The
   broker path, the door and the confirm contract are all tested; no live
   realtime session has issued `navigate_to` with a `confirm` token.
6. **The bureau's TTL (120 s) and backoff (5 s) are chosen, not derived.** The
   place revision is the real invalidator and it is exact; the TTL is a ceiling
   and no measurement sized it.
7. **A2's 30 % is not "the shipping path's accuracy".** It is the accuracy of
   *this* model on *this* fixture's stored thumbnails. It says the crop size is
   worth 17.5 points here; it does not say what a D455 crop is worth.
8. **The forbidden-name list is a list.** The FATAL test is transitive over
   `RobotRuntime`'s own methods and cannot see a model call that enters through
   a helper in another module. It is strictly stronger than what it replaced,
   not complete.

---

## 10. OWNER-GATED rows (listed, never claimed)

No robot hardware is on hand; only the XVF3800 mic array. **No row in this card
needed a camera and none is claimed.** What a camera would unlock, with the
command:

* **Re-measure §2 on real frames** — the single most valuable follow-up. If
  naming lands near 82–87 % on a D455 crop, the dev world was the problem and
  §3's refutation may not hold there:
  `PARCEL_VLM_WEIGHTS=<snapshot> <benchvenv>/bin/python scrum/20260822/task_18/evidence/run_arms.py`
  with `tests/data/p1d_crops` replaced by recorded D455 crops.
* **Re-measure §3 on the same frames** — the judge's true-name recall (J5) and
  wrong-name acceptance (J6) are the two numbers that decide whether a detector
  can be a correctness judge at all:
  `PARCEL_OWLV2_ONNX=1 .parcel/bin/python scrum/20260822/task_18/evidence/run_judge.py`
* **A hosted session that hears the ASK.** One `navigate_to` on an uncertain
  place, then "yes", and the transcript shows whether the model relays the
  `confirm_token` — the one thing about ASK-1 a test cannot tell you.

---

## 11. Handoffs

1. **NM-1's own conclusion, for whoever owns vocabulary next.** A detector
   cannot be the correctness judge on a synthetic world, and the reason is not
   the detector. If the D455 numbers do not rescue it, the remaining honest
   gate is **the owner**: a k-agreed name that a judge cannot confirm should
   become a question ("is that a bollard?"), not vocabulary. ASK-1's machinery
   — a compiled verdict, a revision token, a confirmation that grants exactly
   one thing — is now in the tree and is the right shape for it. That is a
   CURIO-1/ROAM-2-adjacent card, not this one.
2. **P1-B / ROAM-2: `run_naming_pass` still has no caller.** When the idle
   checkpoints get one, pass `judge=default_naming_judge()` and a per-visit
   `visit_id`; the pass is already bounded by wall clock and already refuses
   the control thread.
3. **CAP-1 / whoever next opens the config blocks:** `perception.online_map`
   (runtime P1-B region) or `perception.abstention` (`AbstentionPolicy` +
   P0-D's ratchet) should carry `naming.judge_model` and `naming.judge_floor`.
   Today the judge reads `PARCEL_OWLV2_ONNX` and `PARCEL_NM1_JUDGE_FLOOR`.
4. **P1-A / VENUE-1:** the veto and the judge both read `entry.thumbnail`,
   which is 64 px and capped at 16 KB. §2 measures that cap at **17.5 accuracy
   points**. When the camera daemon lands, feed both seats a fresh crop through
   `VetoRunner`'s `crop_source` seam rather than the stored one.
5. **The bureau is where P1-A's out-of-process daemon plugs in.** One worker,
   one board; moving the seat behind IPC is a change to `VerdictBureau._work`
   and nothing else.
6. **`pyproject.toml` still declares no `vlm` extra** (P1-D handoff 5, still
   open). `.parcel` has no tensor library, so the shipped veto seat is
   `NullVerifier` and the gate asks. NM-1 did not touch `pyproject.toml`.
7. **For the verifier:** start at §3.1 and `evidence/judge_rows.json`. The
   card's headline row is a MISS and the argument for why it is a *refutation*
   rather than a bug is the J5-vs-J6 inversion (0.093 vs 0.123 median) plus the
   floor sweep. If that argument is wrong, everything downstream of it is.

---

# Correction pass — Fable verification, 2026-08-22

**Verdict returned: ACCEPT with corrections.** The central negative result was
attacked by a 15-agent read-only workflow and **survived**: the verifiers
re-derived the strengths from `judge_rows.json` rather than from my table,
re-ran the real OWLv2 seat through the product class and reproduced it
bit-for-bit, and killed the three hypotheses that would have made it a bug —
two alternative prompt templates are both worse with the inversion invariant at
16/21 paired, J5/J6 were already on full-resolution crops, and the floor really
is applied in the judge (the detector runs at threshold 0.0). The first floor
with zero wrong-accepts is 0.935–0.95, where true-name recall is 0.00.

Everything below is this pass. Same rules: Edit-only, git read-only, `TMPDIR`
unset, a seeded RED for every new guard, seeds on a byte-identical scratch copy
of the repo.

## C1. The ruff miss (major — it blocked the commit)

Fixed, and the *method* error is the more important half: §8 measured
`ruff check src/ tests/` while the gate runs `ruff check .`. My four evidence
scripts were the tree's only extras — 8 fingerprints — and ruff is the first
required stage, so the commit tier was red as the tree stood. All eight were
mechanical (§8). **The baseline was NOT regenerated.**

```
$ .parcel/bin/ruff check .        # unique (file, rule) fingerprints
src/parcel_robot/camera_channel/__init__.py::RUF022
src/parcel_robot/camera_channel/backends/factory.py::ISC004
src/parcel_robot/camera_channel/backends/factory.py::S110
src/parcel_robot/camera_channel/channel.py::I001
src/parcel_robot/detection_adapter/noise.py::I001
src/parcel_robot/detection_adapter/sim_bridge.py::B009
src/parcel_robot/detection_adapter/sim_bridge.py::ISC004
                                        -> exactly the 7 in the baseline
(plus tests/test_duplex1_rows.py::I001 — DUPLEX-1's in-flight file, not mine)
```

## C2. The confirmation token could never be confirmed (major, product)

**The verifiers are right and this was the worst defect in the card.**
`_ask_revision` digested `verdict.as_dict()`, and that dict carries `signals` —
`evidence_frames`, `label_support`, `detection_count`, the similarity. Those
move on **every camera frame that sees the place**. So the token churned
continuously and the owner's "yes" could never arrive in time to match one: a
confirmation gate that cannot be satisfied while the robot can see the thing it
is asking about is not a gate, it is a refusal with extra steps. My own §5.2
tests all passed because they drove a *stub* door whose payload never changed —
a stub artefact, and the same class of mistake CURIO-1 §9.1 records.

The token now digests **what is being confirmed** and nothing about how sure the
robot is: `query`, `candidate`, `place_id`, the entry's `label`, its position
rounded to 0.1 m, and the sha256 of the best-view thumbnail. Two new tests, both
driven through the real `_realtime_ask_place` against a real
`OnlineSemanticMap`:

* **three more observations of the same place leave the token identical** — the
  test the verifiers asked for;
* **a new best-view crop moves it** — so it is not a constant either.

Seeded RED both ways: putting `signals` back reddens the first, dropping the
crop sha reddens the second.

**And the second half: a valid token was an unbounded standing grant.** The
verifiers drove one token three times and got three trips, because the
comparison is against a *recomputed* digest and a digest stays put while its
subject does. "Yes, go" is permission for a trip, not for a place. A token is
now **spent when it is honoured** (bounded replay memory, oldest-first), so a
replay asks again. Pinned by
`test_a_confirmation_authorises_exactly_one_trip_and_not_a_standing_grant`,
which drives the same token four times and asserts exactly one `navigate`.

Spending on acceptance rather than on a successful dispatch is deliberate: if
the supervisor then refuses the trip, the owner is asked again, which is the
right answer — a refusal is not a trip the owner already paid for.

## C3. Two source greps replaced by behavioural assertions (minor)

Both of the flagged tests passed on dead code and would have failed on a
harmless rename. Replaced:

* `"bureau_for" in inspect.getsource(resolve_veto)` → **resolve a policy and
  look at the object**: `isinstance(resolve_veto(policy).__self__, VerdictBureau)`,
  then call it. No GPU and no model — the null seat is a bureau too.
* the `'ask_place=self._realtime_ask_place,' in runtime.py` grep → **build a real
  `RobotRuntime`** (in-memory store, fake backend, navigation off, a minimal
  `realtime.yaml` via `PARCEL_REALTIME_CONFIG` so the lane actually constructs)
  and assert on the field the broker will call:
  `broker._doors.ask_place.__func__ is RobotRuntime._realtime_ask_place`. The
  test asserts the broker exists rather than skipping, so it cannot pass by
  building nothing. ~0.5 s.

A third grep found while doing this — the `uncertain_place` producer check — is
now a set assertion over `BROKER_TOOLS` rather than a substring test.

## C4. The notes

1. **`PARCEL_NM1_JUDGE_FLOOR` documented and pinned.** It is a *sweep* knob for
   §3.2, which is a negative result. It now logs a warning naming that result
   whenever it is set, the module docstring says so, and a test pins
   `configured_floor() == JUDGE_MIN_SCORE == DEFAULT_OWLV2_THRESHOLD` **and**
   greps `configs/`, `scripts/` and `src/` to prove nothing sets it. Seeded RED
   by renaming the variable.
2. **`clear_bureaus()` left a dead reader installed.** It stopped the worker and
   left `perception_abstention._VETO_RUNNERS` holding a bound `read` of it — one
   layer down from the exact defect P1-D's verifier caught. It now clears the
   veto cache. Seeded RED.
3. **`OwlV2NamingJudge.load()` latched after one failure**, so "the next pass
   tries again" was true of the ASK and false of the build: one transient
   failure retired the judge for the process and every name after it held
   forever while the log promised a retry. It now retries and warns once.
   Seeded RED.
4. **Board eviction was first-inserted, not least-recently-used** — the place the
   robot asks about every minute could be evicted by one-off queries. `read`
   now refreshes on a hit. Seeded RED.
5. **`proactive_motion_admissions` counting an ASK.** Guarded, and the guard is
   correct — but the honest finding is that the path is **unreachable**:
   `uncertain_place` has exactly one producer (`navigate_to`) and `navigate_to`
   is in `PROACTIVE_MOTION_REFUSED`, which no config can buy it out of. The test
   pins that reasoning rather than pretending to exercise the branch, and its
   seed is moving `navigate_to` into the allowlist. P0-B's `unknown_place` ask
   has the same shape and the same argument; changing that number is changing
   another card's measurement, so it is flagged here rather than edited.
6. **Three ASK-1 lines outside a marked region** — marked. A scan now reports
   **0** ASK-1 identifiers in `tool_broker.py` outside a `CARD ASK-1 (task_18)`
   region (OT-2's consent door is in that file and is untouched).
7. **The 64-px caveat: measured, and it does not reproduce as a reversal.** §3.3.
   Every statistic keeps its sign at both crop sizes and the paired result is
   identical at 16/21; what collapses is the *unpaired* margin (0.029 → 0.004).
   The caveat therefore stands in a narrower form — the paired inversion is
   crop-invariant here, the unpaired medians are not and must not be
   generalised. Raw per-crop rows for both sizes are committed so the
   disagreement is one comparison away from settled.

## C5. §3.1 strengthened and narrowed, as asked

* The claim is now the **paired** one: on the 21 crops the VLM named wrongly,
  the detector prefers the wrong name on **16 of those same 21**. Stronger than
  the 40-vs-21 comparison it replaces, and exactly true.
* Declared narrowing: **the fixture contains views in which the ground-truth
  class is not recoverable by any observer.** A 0.35 m crop of a yellow
  cylindrical primitive does not contain the word "bollard" — that is in the
  scene file. §3 therefore bounds what a perceptual judge can do on *this*
  fixture and says nothing about frames where the class is actually visible,
  which is precisely why §10's D455 re-measurement is the follow-up that
  matters.

## C6. Gates, after the correction pass

| Gate | Result |
|---|---|
| `pytest -q tests/test_nm1_promotion_and_asks.py` | **48 passed, 1 skipped** (49 passed with `PARCEL_OWLV2_ONNX=1`) |
| the 18 affected test files | **761 passed, 2 skipped** |
| P1-D's pair, real Qwen3-VL-2B, `PARCEL_P1D_GPU_EVAL=1` + `PARCEL_OWLV2_ONNX=1` | **53 passed** |
| Seeded RED, now **39** mutations of the product | **39/39 RED** |
| `.parcel/bin/ruff check .` (the gate's own scope) | **exactly the 7 baseline fingerprints**; baseline not regenerated |

New evidence: `evidence/judge_thumbnail64.json`, `evidence/run_judge_thumb.py`.
Nine seeds were added, one stale anchor was repaired after the broker edit, and
no existing seed was dropped or weakened.

## C7. What the correction pass does NOT change

The headline stands and so does the miss: **J3 is 1 false promotion, not 0**,
and no floor reaches 0. C2 makes the ASK usable by a human being, which is a
real product fix, but it is a fix to the *question*, not to the *judge* — the
correctness gate is still refuted on this fixture and still needs the D455 arm
before its operating point means anything.

## C8. The arrival-semantics pin — moved deliberately (wave-2 gate red)

The wave-2 gate came back 9/10 with one deterministic red, and it was mine:
`tests/test_arrival_semantics.py::test_the_tool_schema_offers_relation_and_nothing_else_about_arrival`
asserted `set(properties) == {"place", "relation"}` and ASK-1 had added
`confirm`. That test is a **deliberate absence-pin** — "a parameter the model
cannot send is a parameter it cannot get wrong" — and it did exactly its job:
an added schema field reddened before it could reach a body.

**Coordinator's ruling, followed: keep the parameter, move the pin, do not route
around it and do not delete the property.** The reason is recorded in the test's
own docstring, naming the card and the date: `confirm` is an **opaque,
single-use token** compared against a verdict the runtime recompiles at the
moment of the call, so an invented value, a stale value and a replayed value all
fail identically — there is nothing here for the model to get wrong in the sense
this pin protects. The pin's real target is **arrival semantics**, and
`face` / `standoff` / `stop` remain absent.

What the test asserts now:

* `{"face", "standoff", "stop"}` are absent — **by name, and FIRST**, via a new
  module constant `ARRIVAL_SEMANTICS_FIELDS`. Ordering it ahead of the set check
  is the difference between a property that survived the widening and one that
  merely happens to be implied by it: an added `face` now trips *that* assertion,
  verified in the seed's own output, and it keeps working if a later card widens
  the set again the way this one did.
* `set(properties) == {"place", "relation", "confirm"}` — still exhaustive, so a
  fourth property cannot arrive unnoticed either.
* `required == ["place"]`, plus an explicit `"confirm" not in required`.
  **`confirm` is optional**, which is what makes a model that has never seen an
  `uncertain_place` result behave byte-identically to before this card.

Two seeds added, both RED (39/39 overall):

```
an arrival-semantics FACE parameter reaches the model   RED  (trips the by-name
                                                             absence assertion)
the confirm token becomes a REQUIRED parameter          RED
```

Gates after C8: `tests/test_arrival_semantics.py` **34 passed**; the 19 affected
files **795 passed, 2 skipped**; `ruff check .` still **exactly the 7 baseline
fingerprints**. Declared as deviation 8 in §6.
