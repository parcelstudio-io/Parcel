# P1-D — ask, don't refuse: the VLM veto and vocabulary that grows · status

**Card:** `README.md` · **Board:** `../TASK_BOARD.md` · **Pre-registration:**
`P1D_PREREGISTRATION.md` (written before the first line of P1-D source)
**Executor:** Claude Opus · **Verifier:** Fable · **Date:** 2026-08-22

---

## Headline

**COMPLETE. Four of the five pre-registered rows met; row 5 met on the shipping
path and MISSED on the arm that matters next, and the miss is the card's most
useful result.**

The state C-3 measured at **0/18 admitted** now admits **5 of 7** present
queries on a learned map with abstention ON, and **0 of 8** on the absent set —
**measured through the product path, no monkeypatch** (see §11.1; the first
version of this document had that number from a harness only).
The gate has a third answer: below the admit threshold the dog asks, and with no
model installed on the host it asks instead of refusing
(**8 asks, 0 admits, 0 wrong admits**) — which is a strictly better
failure mode than the one this card was sent to fix.

> **Read §11 first.** The verifier returned DISCREPANCIES_FOUND: the seam was
> not wired in the product, a CUDA stream-priority claim was false, and three
> counts were wrong. All are corrected there, and §11 supersedes this section
> wherever they disagree.

Qwen3-VL-2B is real and is on the GPU: **41.2 ms p50 / 44.9 ms p95** over 80
verifications, weights reused from the 2026-08-21 research cache (nothing
downloaded). It never runs in the 10 Hz loop and three independent mechanisms
say so.

**The miss, stated plainly.** Naming accuracy on 40 textured dev-scene crops is
**45.0 %**, not the 82–87 % the research predicted — and the k-gate does **not**
filter the residue, because the model's errors are *consistent*. Given a crop
large enough to name, three independent visits agreed on **"yellow cylinder"**
for a bollard and **"pole"** for a traffic light, and both were promoted into
`known_places()`. **2 promotions, 2 false.** The k-gate is not a correctness
filter; it is a consistency filter, and a systematically wrong VLM is
systematically consistent. §5.

Three refutations routed to this card (D-R3, D-5) are fixed, and D-R3 was
reproduced RED first: without this card, `"a coffee shop"` is **ADMITTED**
against a map entry labelled `shop`.

---

## 1. What changed

| File | + | − | Note |
|---|---:|---:|---|
| **new** `src/parcel_robot/vlm_veto/__init__.py` | 76 | — | public API; imports no tensor library |
| **new** `src/parcel_robot/vlm_veto/verifier.py` | 589 | — | the Qwen3-VL-2B seat, `NullVerifier`, lazy torch |
| **new** `src/parcel_robot/vlm_veto/runner.py` | 311 | — | where it may run; contention + control-thread tripwire |
| **new** `src/parcel_robot/online_map/naming.py` | 393 | — | idle-time batch naming, normalization, demotion |
| **new** `tests/test_p1d_vlm_veto.py` | 848 | — | 42 tests, every one naming its seed |
| `src/parcel_robot/perception_abstention.py` | 364 | 18 | veto signal, ADMIT/ASK/REFUSE, `ask_below_threshold` |
| `src/parcel_robot/perception_contention.py` | 115 | 15 | the veto's own budget (§4) |
| `src/parcel_robot/navigation/semantic_map.py` | 123 | 13 | **deviation** — D-R3 + D-5 (§9) |
| `configs/navigation/prototype.yaml` | 49 | 1 | `vlm_veto` + `ask_below_threshold` (+13 more in §11; the file's other hunk, +67, is P1-B's `online_map` block) |
| `tests/test_p0d_navigation_unblocks.py` | 38 | 17 | **deviation** — P0-D ratchets my roster moved (§9) |

`src/parcel_robot/online_map/**` other than `naming.py` was **read and not
modified**; P1-B's five modified files there are theirs and were left alone.
Not touched: `ingress.py`, `runtime.py`, `realtime/**`, the safety core,
`evals/**`, `configs/navigation/default.yaml`, `docs/`, `backlog/`, `README.md`,
`scrum/20260821/`, `pyproject.toml`, `scripts/ci_gate.py`. No git write command
was run. No process was killed. The MOVE-1 sim and the :8765 panel were left
alone; this card opened no socket and no port. Scratch:
`/home/jaewoo-jang/.cache/parcel-p1d/`.

**Hand-off rule honoured.** `scrum/20260822/task_5/P0E_STATUS.md` was absent at
start; the `vlm_veto/` package, the roster re-cut, `naming.py`, the overlay and
the pre-registration were all built before any `tests/` file was touched. The
coordinator lifted the hold mid-card and the test work followed it.

---

## 2. Flag-off identity

HEAD's `perception_abstention` and P1-D's, loaded side by side in one
interpreter, over 150 verdicts (50 synthetic rows × 3 entry paths), comparing
the six fields that existed before this card:

```
rows        : 150
HEAD  sha256: 68cad5448952c6fff0dfe7c44d7e627e5c65de5670e171188251b382b80c9a72
P1-D  sha256: 68cad5448952c6fff0dfe7c44d7e627e5c65de5670e171188251b382b80c9a72
IDENTICAL   : True
DEFAULT_SIGNALS equal: True        default policy fields equal: True
```

**One declared, additive difference:** `AbstentionVerdict.as_dict()` gains two
keys, `outcome` and `candidate`. Nothing in the tree asserts that dict's exact
shape (checked: only `["reason"]` / `["admitted"]` lookups), and on the shipping
path `outcome` is always `admit`/`refuse`, derived from `admitted`. It is
recorded here rather than buried because it changes a serialized surface
(`observation.extras['abstention_verdict']`).

`configs/navigation/default.yaml` is byte-unchanged, so the frozen
`nav_instruct` v4 baseline cannot have moved and no `runtime_assets` sync was
needed. `tests/test_release_parity.py`: 10 passed.

---

## 3. The five pre-registered rows

Measured once each, in the pre-registered order, on the fixtures frozen in §6.

| # | Row | Target | Result | |
|---|---|---|---|---|
| **1** | ≥ 1 ADMIT from a learned map on perfect-geometry data | ≥ 1 | **5 of 7 present admitted** | **MET** |
| **2** | absent-object set admitted | 0 / 8 | **0 / 8** | **MET** |
| **3** | ASK rate, reported | report | **0.0 %** with the seat; **53.3 %** with no seat | **MET** (reported) |
| **4** | naming accuracy, 40-entry fixture | report (82–87 % predicted) | **45.0 % (18/40)** | **MET** (reported); **prediction MISSED** |
| **5** | k-gate false promotions | **0** | **0** on the shipping 64-px path; **2 of 2** on the full-res arm | **MET / MISSED** |

### Row 1 — the 0/18 state, unblocked

Seven places built by real `MapObservation` ingest into a real
`OnlineSemanticMap` from textured `city_block` renders, plus a seeded `shop`.
Abstention ON, prototype roster, real Qwen3-VL-2B answering the veto from the
**map's own stored thumbnails**.

```
prototype_with_veto  admit 5  ask 0  refuse 10
                     present_admitted 5/7   absent_admitted 0/8
                     veto: asked 8, present 5, absent 3, unavailable 0
```

The two present places that did not admit were **vetoed** — `lamppost`
(p_yes 0.234) and `traffic light` (p_yes 0.034). Those are false vetoes: the
model looked at a 64×64 thumbnail of a real lamppost and said no. That is the
signal's measured cost, §7 risk 2.

### Row 2 — refusal preserved, and the D-R3 admission killed

**0 of 8 absent queries admitted.** Seven refuse as `no_observations` — no
candidate, nothing to ask about. The eighth is the interesting one:

```
a coffee shop   refuse   vlm_veto_absent   candidate='shop'   p_yes=0.0078
```

Without this card that row **admits** (`grounded`) — see the SEED arm in §4.
Two independent mechanisms now stop it: the veto looked at the shopfront and
said no with p_yes 0.008, and (on the mission path) a substring-only match can
no longer reach ADMIT at all.

### Row 3 — the ASK rate

| arm | admit | ask | refuse | ask rate |
|---|---:|---:|---:|---:|
| prototype, real seat | 5 | 0 | 10 | **0.0 %** |
| prototype, **no seat installed** | 0 | **8** | **7** | **53.3 %** |

(Corrected in §11.5: the eighth ask is `a coffee shop`, which has a candidate —
the `shop` entry — to ask about. The other seven absent queries have no
candidate and refuse as `no_observations`.)

The second row is the one to read. On a host without the weights the dog asks
about every place it can see and admits none — no wrong admissions, no blanket
refusals. That is the designed degradation and it is why enabling `vlm_veto`
*requires* `ask_below_threshold` as a construction invariant.

### Row 4 — naming accuracy: 45.0 %, and why

18/40 correct under the 2026-08-21 synonym table. Per class:

```
door 4/4   tree 4/4   bench 3/4   building 2/4   crate 2/4   lamppost 2/4
traffic light 1/4   bicycle 0/4   bollard 0/4   planter 0/4
```

The wrong answers are not hallucinations. They are **descriptions of geometry**:

```
bollard -> "yellow cylinder" (x4)     planter -> "grassy cylinder", "tree trunk"
bicycle -> "black rectangle"          traffic light -> "pole" (x3)
```

W-1's textures are applied to MuJoCo *primitives*, so a bollard genuinely **is**
a yellow cylinder from 0.35 m eye height. The model is answering correctly about
what it can see; the ground-truth label is a fact about the scene's *intent*.
**The 45 % is a property of the dev world, not of the seat**, and the research's
82–87 % was measured on different crops. Neither number transfers to a real
camera and this card does not claim either does.

### Row 5 — the k-gate, and the miss

Eight objects with ≥3 independent views, **of which 7 persist** as map entries,
three visits each, each visit showing a **different** view; a real map, real
`propose_name`, real `run_naming_pass`. The eighth is `bicycle`, refused by
C-2's hygiene screen as a volatile class — a bicycle can be ridden away, so it
never persists and the naming pass never sees it (§11.5).

| arm | crop the seat sees | promotions | false | `known_places()` gained |
|---|---|---:|---:|---|
| **thumbnail64** (the shipping path) | the map's own bounded 64-px PNG | 0 | **0** | nothing |
| **fullres** (P1-A's future crop) | the render | 2 | **2** | `pole`, `yellow cylinder` |

**Target 0. Met on the shipping path, missed on the other arm — and the miss
is the finding.** The pre-registration predicted exactly this and named the
mechanism: *"three agreeing visits of the same wrong name is exactly the failure
the k-gate cannot see."* It happened. `traffic_light_1` was called "pole" by
three independent visits and `bollard_1` "yellow cylinder" by three, and both
entered the vocabulary with full rights.

The thumbnail64 arm scores 0 for the *opposite* reason, and it is not a success
to bank: at 64×64 the names are so unstable that nothing reaches k at all
(`yellow cylinder / yellow cup / yellow cylinder`). **The shipping path is safe
because it is blind, not because the gate works.** Both facts are load-bearing
for whoever wires P1-A's daemon.

---

## 4. Seeded RED — 12 of 12 caught

Harness `/home/jaewoo-jang/.cache/parcel-p1d/seeds/run_seeds.py`: one-line
mutation, `__pycache__` purged before and after, restore in a `finally` with a
sha256 check, anchor uniqueness asserted (one seed was reported not-caught on
the first pass and was **rewritten rather than dropped** — the original mutated
a line the property did not depend on).

```
mad-zero margin re-introduced         RED     <- the card names this one
promotion without k agreements        RED     <- and this one
substring match admits (D-R3)         RED
veto enabled without the ask posture  RED
unavailable veto admits               RED
absent veto ignored                   RED
veto asked per candidate              RED
control-loop tripwire removed         RED
veto budget may be infinite           RED
demotion is a no-op                   RED
non-names may be promoted             RED
vlm_veto joins DEFAULT_SIGNALS        RED
12/12 seeds caught
```

Two behavioural seeds were also run through the **measurement** harness, not
just the tests:

```
SEED_robust_z        admit 0   <- the MAD-zero margin, on the real map: 0/7 present
SEED_no_ask_no_veto  admit 8   present 7/7 and ABSENT 1/8  <- D-R3 reproduced
```

---

## 5. The mission-lease relaxation (card §9)

`perception_contention`'s docstring argues — correctly — that CUDA stream
priorities cannot order this process against the generator, *because the
generator is `llama-server` in a separate process* and cross-context work is
driver-scheduled with no user-space priority knob.

~~**The 2B veto is the case that argument excludes.** It runs in this process,
in the same CUDA context as the detector, where a low-priority stream really
does yield.~~ **FALSE — withdrawn, §11.2.** `priority_range()` returns
least-priority FIRST, so the "low" stream was priority 0 — the default stream —
with nothing below it for the detector to preempt. What survives is that the
veto is SHORT and its duration is measurable. So:

* `DEFAULT_MAX_GENERATION_MS_WHILE_ACTIVE` stays **0.0**. The llama-server
  refusal is byte-for-byte as strict as PG-1 left it. *(This bullet stands.)*
* A **second, named** budget is added — `veto_budget_ms_while_active`, default
  **120 ms** — with its own method, `try_admit_veto`, so an auditor reading call
  sites can see who bought the relaxed budget without reading arguments.
* The number was fixed **before** the measurement and is vindicated by it:
  measured p95 **44.9 ms**, well inside 120 ms and 15 % of the 300 ms detection
  TTL.
* It is validated by the same three rules as the generation budget (finite,
  non-negative, below the TTL), so it cannot become the `inf` that turns the
  module into decoration.
* A veto that IS declined degrades to `VETO_UNAVAILABLE` ⇒ **ASK**. Nothing is
  refused for contention; the detector keeps its frame budget and the owner
  still gets an answer.
* **Added in §11.2:** the declared estimate is now the seat's own measured
  latency EMA rather than a constant, and a COLD seat declares `inf` so it can
  never be admitted under a lease. Warm-up is paid at install, off any lease.

**Never in the 10 Hz loop**, three ways: an AST assert that `_dispatch_active`
and `_step_navigation` call no runner method (the C-1 way); an import-level AST
assert that `runtime.py` imports no `vlm_veto` module; and a runtime tripwire
that raises `ControlLoopViolation` on a thread that declared itself the loop.
Plus a subprocess check that importing `parcel_robot.vlm_veto` loads neither
`torch` nor `transformers`.

---

## 6. Fixtures, and one thing found while building them

**F-CROP / F-NAME are new and are TEXTURED.** The 2026-08-21 bench crops were
rendered from the **untextured** scene — verified by eye, flat-shaded primitives
— so they could not satisfy the card's "derived on textured dev-scene renders".
Rebuilt here from the current `city_block.xml`: ground truth from a MuJoCo
**segmentation** pass (geom ids → objects → the scene's own class names, no
detector involved), the 2026-08-21 bench's 42 poses plus a deterministic
standoff orbit (3.0 / 4.5 / 6.0 m × 4 bearings per object), the robot's own body
hidden, and three visibility guards (≥3000 px, ≥35 % fill, no larger rival in
the crop, box 1–35 % of frame) with 25 % context padding.

* pool: **241 crops, 18 objects, 10 classes**, `sha256 77c86e15b07df37d…`
* **F-NAME**: 40, balanced 4 per class, `sha256 162bd28bc7be2ab1…`
* **F-VETO**: the same 40 asked twice — true class (must not veto) and a fixed
  rotation decoy (must veto). Veto: kept **30/40** true, vetoed **30/40** decoys.

**Found on the way, and it is a real bug in a file I do not own:**
`OnlineSemanticMap._maybe_take_best_view` returns early when
`obs.embedding is None`, so **a bounded source crop is only ever stored when an
embedding arrives with it.** Nothing populates embeddings today, so
`entries_with_thumbnail` is **0** on every map the product builds — which means
the veto and the naming pass would both find no crop and the whole card would
degrade to ASK forever. REVISION §6 wanted that crop kept precisely so a later
model could re-embed; this is AU-C2-1's cousin, on the producing side. Handed to
P1-B (§10), worked around here with a placeholder embedding.

---

## 7. What this does NOT prove

1. **Nothing here was measured on a real camera.** Every crop is a MuJoCo
   render of a scene whose objects are textured primitives. §3 row 4 explains
   why that alone probably accounts for the naming gap. No number in this
   document transfers to a D455.
2. **The veto costs correct admissions, and the rate is not small.** 30/40 true
   crops kept on the fixture; 5/7 present places admitted on row 1, i.e. **2 of
   7 correct places were refused by the veto**. Roughly a quarter. A false veto
   is a REFUSE, not an ASK — that is what the card specified ("REFUSE reserved
   for veto or zero evidence") and it is the harshest thing in this card. It is
   the right direction to be wrong in, but it is not free.
3. **The k-gate does not filter wrong names** (§3 row 5). It filters
   *inconsistent* names. Anything a VLM is reliably wrong about walks straight
   through it. A second, independent check — the detector label, a size prior, a
   human confirmation — is what would actually filter, and none exists.
4. **`p_yes ≥ 0.5` is inherited, not derived.** Taken verbatim from
   `bench_retrieval.md`. This card did not re-derive it and did not sweep it. On
   F-VETO the errors are two-sided (10 false vetoes, 10 misses), so a threshold
   move trades one for the other rather than fixing either.
5. **Row 1's map is seven places built by this card**, not a mission. The
   prototype profile has still never been driven end to end, and no hosted
   session has seen an ASK.
6. **The ASK path is not wired to the voice.** `AbstentionVerdict.as_ask()`
   emits the payload in the shape P0-B's broker already speaks, and a test pins
   that shape — but `runtime.py` and the broker are MUST-NOT-TOUCH, so nothing
   in the product carries it yet. §10 handoff 1. This is the card's work item 4
   delivered as a seam, not as a behaviour.
7. **The fixtures are small and one-scene.** 40 crops, 8 objects, 15 queries.
   0/8 on absent queries is directional, not a false-accept rate.
8. **The `shop` entry in row 2 was seeded by me** to give D-R3 something to
   catch on. It is a fair reproduction of the refuter's probe, not a naturally
   occurring map state.

---

## 8. How it was verified

`.parcel/bin/python` / `.parcel/bin/ruff` throughout. The VLM ran in the
2026-08-21 research venv (`bench-owl/venv313`: torch 2.13+cu130, transformers
5.15.1, CUDA available) because `.parcel` carries no tensor library and this
card does not add one — but it drove **the repo's own `parcel_robot.vlm_veto`
wrappers**, not a re-implementation. Weights were **found, not downloaded**:
`…/cutover-research/bench-vlm/hf/hub/models--Qwen--Qwen3-VL-2B-Instruct`.

| Gate | Result |
|---|---|
| `pytest -q tests/test_p1d_vlm_veto.py` | **42 passed** |
| `pytest -q` over P1-D + every file that reads these surfaces (`perception_abstention`, `perception_contention`, `p0d_navigation_unblocks`, `c1_camera_stream`, `c2_online_map`, `c3_cutover`, `unknown_place_admission`, `prototype_profile`, `runtime_activation`) | **440 passed** |
| `pytest -q tests/test_instructnav_grounding.py … test_held_out_scene.py` (6 files) | **71 passed** |
| `pytest -q tests/test_release_parity.py` | **10 passed** |
| Seeded RED, 12 mutations | **12/12 RED** |
| Flag-off identity, 150 verdicts | **identical**, §2 |
| `ruff check` on OWNS (5 source + 2 test files) | **All checks passed** |
| `ruff check src/parcel_robot/` | 12 errors, **all pre-existing**, none in a file P1-D touched (same 12 P0-D recorded) |
| GPU | 30.6 GB free before the run; peak co-resident well inside it; nothing killed |

`scripts/ci_gate.py` was **not** run (P0-E owns it, and the card forbids it).
The owner store was never opened.

---

## 9. Deviations from OWNS, declared

1. **`src/parcel_robot/navigation/semantic_map.py` (+123/−13).** Not in OWNS —
   it is C-3's file. Edited on the coordinator's explicit routing of refutation
   **D-R3**, which lands in this card's ADMIT/ASK/REFUSE re-cut. Two functions:
   * `_matches` split into a one-line bool plus `_match_strength`, which reports
     `exact` / `alias` / `substring` / `none`. The candidate set it produces is
     **unchanged** — every containment that matched before still matches — and
     what changed is that the gate can now tell a spelling coincidence from a
     synonym. Determiners are stripped before the identity test so `"the bench"`
     stays EXACT and the owner's own phrasing is not demoted.
   * `_abstention_filtered` downgrades an admission whose winner matched only by
     substring to ASK (or refusal when the ask posture is off).
   The card said "keep it to `_matches`"; the second function was unavoidable
   because a strength that never reaches the gate cannot change an admission.
   **D-5** (a bare `"label_strength"` literal) is fixed in the same file, one
   line, using the module constant.
2. **`tests/test_p0d_navigation_unblocks.py` (+38/−17).** P0-D's ratchets pin
   the prototype profile's exact diff and read `prototype.signals` directly, and
   this card's chartered overlay change moved both. Neither was deleted or
   weakened: the profile pin **gained** `ask_below_threshold` and stays
   exhaustive; the three roster tests now name P0-D's three evidence signals
   through a new `_evidence_roster_policy()` helper instead of inheriting
   whatever the overlay currently lists — which is *stronger*, because it stops
   that file drifting silently every time another card edits the profile, and it
   keeps each card's acceptance measuring its own change.
3. **`configs/navigation/prototype.yaml` gains two keys** (`vlm_veto` in
   `signals`, `ask_below_threshold: true`). In OWNS ("`configs/navigation/*`
   abstention keys") and named here only because P0-D pins that file's diff.
4. **`src/parcel_robot/online_map/naming.py` writes `entry.names`.** The card
   says coordinate with P1-B "through the public API only". `propose_name()` is
   used for every promotion; **demotion has no public method** (C-2 never built
   one) so `demote_disagreed_names` rebuilds the public `entry.names` tuple with
   public `ProposedName` constructors and appends a public `entry.note()` row —
   exactly what `propose_name` itself does internally. **No line anywhere else
   in `online_map/` was changed**, and P1-B's five modified files were not
   touched.
5. **A design decision changed after a measurement, declared.** The first
   `demote_disagreed_names` penalised *every* non-agreeing name. Measured: that
   makes k=3 mean "three visits IN A ROW", and on the 8-object replay it
   promoted **nothing at all** — a vocabulary gate that cannot grow a
   vocabulary. Narrowed to names that have standing (promoted ones), which is
   what the card's "demotion on disagreement" means. The change is recorded in
   the function's docstring with the number that forced it, and it made row 5's
   full-res arm *worse* (0 false → 2 false), so it was not a change in the
   flattering direction.

---

## 10. Handoffs

1. **The ASK path needs one line in the broker, and I could not write it.**
   `AbstentionVerdict.as_ask()` returns
   `{"status": "uncertain_place", "tool": "navigate_to", "detail", "place",
   "candidate", "place_id", "valid_places", "reason"}` — P0-B's
   `unknown_place` envelope, with a different status because a place the map can
   *see* is not a place it has never heard of. `tool_broker.py` and `runtime.py`
   are MUST-NOT-TOUCH for this card. **Owner: P2-A or whoever next holds the
   broker.**
2. **P1-B — `_maybe_take_best_view` drops the crop when there is no embedding**
   (§6). Today that means **zero** map entries carry a thumbnail, so the veto and
   the naming pass both see nothing and the whole gate degrades to ASK. Your card
   lands the real `embed_fn`, which fixes it as a side effect — but the coupling
   itself is worth breaking: a thumbnail is evidence in its own right and should
   be stored whether or not a vector arrived with it.
3. **P1-A — the map's stored crop is 64×64 and that is too small to name.**
   `MapEntry` caps a thumbnail at 16 KB and `_encode_thumbnail` strides to a
   64 px edge, so the seat sees 64×64. Measured consequence: naming is unstable
   enough that nothing reaches k (safe but sterile), while a full-resolution crop
   promotes wrong names (§3 row 5). When the camera daemon lands, feed the veto a
   **fresh** crop rather than the stored one — and add a second filter before
   promoting anything, because the k-gate alone will not save you.
4. **A second D-R3-shaped site exists in `online_map.py` and is P1-B's.**
   `resolve()` matches by **token intersection**, so `"a coffee shop"` matches an
   entry labelled `shop` on `{shop}`. Measured: the `SEED_no_ask_no_veto` arm
   admits it (1/8 absent). Today only the VLM veto stops it there (p_yes 0.008).
   The mission path is fixed structurally; the map API is not.
5. **`vlm_veto` is an optional dependency and nothing declares it.**
   `pyproject.toml` was MUST-NOT-TOUCH while P0-E was closing and I did not
   revisit it. `torch`/`transformers` are absent from `.parcel`, so
   `active_verifier()` is `NullVerifier` on this host and the prototype profile
   asks rather than admits. Adding a `vlm` extra is a one-block edit.
6. **Row 4's 45 % should be re-measured on the first real camera frames.** If it
   lands near 82–87 % there, the dev scene was the problem and the k-gate's
   false-promotion rate needs re-measuring too. If it does not, the seat needs
   revisiting — `SYNTHESIS.md` decision 4's tie with the 8B was measured on
   photographs, and the 4B is still in the cache.

---

# §11 Post-verification corrections

**Verifier verdict: DISCREPANCIES_FOUND** — every measured number reproduced,
but the card's core was **not delivered in the product** and two claims were
false as written. All six items are addressed below. The headline correction:

> **Row 1 on the PRODUCT path, no monkeypatch anywhere: 5 of 7 present
> admitted, 0 of 8 absent.** Before this section that number was harness-only.

## 11.1 The seam — the veto had no producer (item 1)

**The defect.** `assess_place_query(veto=...)` existed, the roster could select
`vlm_veto`, and **nothing in the product ever passed one.** `AbstentionPolicy`
had no `veto` field, so `semantic_map`'s `veto=getattr(active, "veto", None)`
was always `None`; `online_map.py` passed nothing at all; no file outside
`vlm_veto/` referenced `VetoRunner`. With the prototype profile and a seat
installed, the product yielded **0 admit / 8 ask** — the veto answered
`unavailable` for every place, and §3 row 1's 5-of-7 came from a harness that
monkeypatched `assess_place_query`. The verifier was right to call this the
card's core.

**The fix, in four parts.**

1. **`AbstentionPolicy.veto_model`** — a validated config key naming the seat.
   The prototype overlay sets `Qwen/Qwen3-VL-2B-Instruct`; empty (the shipped
   default) means the null seat, which answers `unavailable`, which is an ASK.
2. **`perception_abstention.resolve_veto(policy)`** — the producer. Builds the
   named seat once per model id and caches it. `vlm_veto` is imported *inside*
   the function: that package imports names from this one, so a module-scope
   import is a cycle, and the gate is on the mission path while the seat can
   pull in a tensor library.
3. **The gate resolves it**, rather than each call site threading it: `veto=None`
   from a caller now means "use what the config named". There are two call sites
   today and a third is a plausible edit — a seam every caller must remember is
   a seam a new caller silently drops, which is the defect being repaired.
   `semantic_map`'s dead `getattr` line is gone, with a comment saying why.
4. **`PlaceEvidence.crop_png`** — the evidence carries the pixels, so the runner
   never has to know where places live. Populated by
   `place_evidence_from_mapping` from candidate metadata and, **one declared
   line in P1-B's `online_map.py` (~line 978)**, from `entry.thumbnail`.

**Two further defects found while re-measuring, both real:**

* **`resolve_veto` returned the `VetoRunner`, which is not callable.** Every
  invocation raised `TypeError`; the gate caught it and read it as
  "unavailable". The veto looked wired and answered nothing — the same
  end-state as the original defect, one layer down. It now returns
  `runner.veto_callable()`, and `test_the_resolved_seat_is_a_CALLABLE_the_gate_can_actually_invoke`
  is the guard.
* **The unavailable-ASK borrowed `ABSTAIN_INDECISIVE_RANKING`**, so the logs
  read `indecisive_ranking` while reporting `ranking_margin: 39.12`. A gate that
  blames the wrong signal cannot be debugged. New reason
  `ABSTAIN_VETO_UNAVAILABLE` (`vlm_veto_unavailable`), ASK-eligible.

### Row 1, both numbers, as asked

| path | veto | present admitted | absent admitted | ASK rate |
|---|---|---|---|---|
| harness (§3, monkeypatched `assess_place_query`) | real seat | 5 / 7 | 0 / 8 | 0.0 |
| **product** (`OnlineSemanticMap.resolve`, no monkeypatch) | **real seat** | **5 / 7** | **0 / 8** | **0.0** |
| product | no seat (`veto_model: ""`) | 0 / 7 | 0 / 8 | 0.533 |
| product, pre-fix | real seat, unreachable | **0 / 7** | 0 / 8 | 0.533 |

The two live arms agree, so §3's conclusions stand — but they stand for the
first time on the shipping path. Veto stats on the product run: asked 8,
present 5, absent 3, unavailable 0. `a coffee shop` refused at p_yes 0.0078;
`lamppost` (0.234) and `traffic light` (0.034) are the two false vetoes.
Artifact: `evidence/row1_product_path.json`.

## 11.2 The stream-priority claim was false (item 2)

**Withdrawn everywhere.** `torch.cuda.Stream.priority_range()` returns
**least-priority first**, so the "low priority" stream the verifier created was
`priority=0` — exactly the default stream's priority. CUDA has nothing below
default, so there was nothing for the detector to preempt and the stream bought
**nothing**. The same-context premise fails independently the moment P1-A's
out-of-process detector daemon lands. Removed from `verifier.py` (the stream is
deleted, not just the comment), `runner.py`'s docstring,
`perception_contention.py`'s constant docstring and field comment, the
`Admission` reason string, and §5 above — which should now be read with this
section.

**What replaces it: a measured budget, not a declared one.**

* `VetoRunner` keeps an **EMA of observed latency** (α = 0.25) and is admitted
  against *that*, never against a constant. A seat that gets slower closes its
  own gate instead of quietly eating the detector's frame budget.
* A **cold** seat declares `inf` and is refused under any lease — loading 4.4 GB
  is seconds, and no budget covers it.
* **Warm-up happens at install** (`runner_for`), where no lease is held, and
  `warm_up()` **refuses to run while a lease is held**.
* Warm-up takes **two** throwaway answers and seeds the EMA from the **second**.
  Measured: a load-only warm-up left early answers at 127 ms against the 120 ms
  budget — the EMA opened *above* the budget. The first generation after a load
  costs **719 ms** (kernel selection, allocator growth); the second is the seat.
  After the fix: install estimate **57.7 ms**, EMA after eight real vetoes
  **46.1 ms**, mean **46.0 ms**. Comfortably inside 120 ms, and 15 % of the
  300 ms detection TTL.

Seeded RED as instructed: `test_SEED_a_cold_seat_is_never_admitted_under_a_held_lease`,
plus `test_the_admitted_estimate_is_measured_not_declared` and
`test_warming_up_costs_one_throwaway_answer_not_just_a_load`.

## 11.3 The fixture swap, declared (item 3)

**The pre-registered F-MAP was not used for rows 1–3, and §6 did not say so.**

`P1D_PREREGISTRATION.md` §2 named **F-MAP** =
`tests/data/c2_online_map_frames.json` (C-2's 16 textured-scene frames) and
**F-CROP** = renders at F-MAP's own poses cropped to its own boxes. That was
built and it produced **40 crops that were ALL `lamppost`** — C-1's live run
used the query batch `['person', 'lamppost']` and only `lamppost` fired, so the
fixture has exactly one class and no person. A one-class fixture cannot measure
naming accuracy across classes, cannot supply a decoy for the veto, and cannot
produce a multi-place map.

So rows 1–5 ran on a **self-rendered orbit pool** instead (§6): the same
textured `city_block`, ground truth from the scene's own geom names, the
2026-08-21 bench's 42 poses **plus** a standoff orbit this card invented.

**Which pre-registered predictions were therefore about a fixture that was not
used:**

* The row 1/2/3 map is **not** C-2's 16 frames and therefore **not** literally
  "the exact state that was 0/18". It is the same scene, the same gate, the same
  estimator and the same 0/18 mechanism — but it is a map this card built.
  The 0/18 claim is reproduced in *mechanism* (`SEED_robust_z` → 0 admits) and
  not in *fixture*.
* Row 4's "40-entry fixture" is F-NAME from the orbit pool, not from F-MAP.
* Row 2's absent set is unchanged, but its eighth query needed a `shop` entry
  that **this card seeded** — already declared in §7 item 8.
* The prediction "row 1 will admit 2 places (`lamppost`, `tree`/`bench`)" was
  about the two-place C-2 fixture. It is not comparable to the 5-of-7 measured
  on a seven-place map, and is neither a hit nor a miss — it is void.

The orbit pool is a **deviation from the pre-registration**, declared here
rather than in §9 because it was found during measurement.

## 11.4 The CI eval row (item 4)

Work item 2's "pinned fixtures and a CI eval row" was only half-delivered:
nothing in-tree could re-run rows 1–5.

* **`tests/data/p1d_crops/`** — 40 PNGs (384 px longest edge), plus
  `MANIFEST.json` carrying per-crop sha256, the source `.npy` digest, the pool
  digest `77c86e15…`, the F-NAME digest `162bd28b…`, and **`thumbnail_b64`**:
  the exact bytes `MapEntry.thumbnail` would hold (`_encode_thumbnail`, 64 px,
  ≤16 KB). The thumbnails are committed because `.parcel` carries **no image
  decoder**, so without them the eval could not run on the shipping venv — and
  because they are what the shipping path actually shows the seat. 1.6 MB total.
* **`tests/test_p1d_eval_rows.py`** — 7 cells. The CPU arm runs on every commit
  with the null seat and asserts the degradation posture and row 2. The GPU arm
  (`@pytest.mark.slow`, gated on `PARCEL_P1D_GPU_EVAL=1` + resolvable weights)
  runs the real seat and asserts row 1 ≥ 1 admit, row 2 = 0/8, and D-R3.
  Both go through `OnlineSemanticMap.resolve` — **no monkeypatch**, which is
  the point of the file.
* **`scrum/20260822/task_9/evidence/`** — the renderer, the fixture builder, the
  seed harness, the flag-off script, and every result JSON including
  `row1_product_path.json`.

The GPU arm asserts **properties, not the exact counts**: a seat swap that moves
5 admits to 6 is fine; one that admits an absent query is not. That is the
llmdet lesson applied rather than quoted.

## 11.5 Counts corrected (item 5)

* **Row 3's no-seat arm is `ask 8 / refuse 7`, not `ask 7 / refuse 8`.** §3's
  row-3 table and the headline said 7 asks. The eighth ask is `a coffee shop`,
  which finds the `shop` entry by token overlap and therefore has a candidate to
  ask about; the other seven absent queries have no candidate and refuse as
  `no_observations`. Verified directly:
  `present Counter({'ask': 7})`, `absent Counter({'refuse': 7, 'ask': 1})`.
  ASK rate 8/15 = **0.533** (unchanged — only the split was wrong).
  `test_rows_1_to_3_with_no_seat_ask_and_admit_nothing_wrong` now pins the split.
* **"Eight objects" in row 5 vs `considered = 7`.** Both are right and they
  count different things: **8** objects in F-NAME have ≥3 independent views, but
  only **7** become retrievable map entries. The eighth is `bicycle`, refused by
  C-2's hygiene screen as a **volatile class** (`refused_volatile: 3` in the map
  stats) — a bicycle can be ridden away, so it never persists and the naming
  pass never sees it. That is the hygiene gate working, not a lost object. §3
  row 5 should read "8 objects, of which 7 persist".
* **`configs/navigation/prototype.yaml` numstat.** §1 credited the whole
  `+103/−1`. The file has two hunks: **P1-B's 67-line `online_map` block** at
  line 130, and **mine at line 247**. My share is **+49/−1** (it grew from the
  verifier's +36 because §11.1 added the `veto_model` block). Corrected.

## 11.6 The flag-off artifact, and the honest scope of the D-R3 claim (item 6)

* **`evidence/flag_off_identity.py`** is committed and re-runnable
  (`.parcel/bin/python scrum/20260822/task_9/evidence/flag_off_identity.py`,
  exit 0 on identity). Re-run **after** every §11 change:
  `HEAD 68cad544…` = `P1-D 68cad544…` over 150 verdicts, `DEFAULT_SIGNALS`
  equal, additive keys `['candidate', 'outcome']`.
* **"a substring match can no longer reach ADMIT" holds only with the gate ON.**
  `_abstention_filtered` returns the candidates untouched when the policy is
  disabled, and the shipped default *is* disabled — so under `robot.yaml` a
  substring match still becomes a goal, exactly as it did before this card.
  That is pre-existing behaviour and it is *required* by flag-off identity: a
  card that changed it would have moved the shipped path. §3 row 2's claim is
  scoped to a profile with abstention enabled. The unconditional half of the
  D-R3 fix is `_match_strength`, which reports the truth on every path; the
  half that acts on it is gated.

## 11.7 What changed in §11, and re-verification

| File | Δ | What |
|---|---|---|
| `perception_abstention.py` | +150 / −8 | `veto_model`, `resolve_veto`/`use_veto`/`clear_veto_cache`, `PlaceEvidence.crop_png`, `ABSTAIN_VETO_UNAVAILABLE`, the producer call |
| `vlm_veto/runner.py` | +170 / −12 | `runner_for`, latency EMA, cold-seat `inf`, `warm_up`, crop-from-evidence |
| `vlm_veto/verifier.py` | +40 / −34 | stream deleted, `warm_up_png` |
| `vlm_veto/__init__.py` | +14 / −0 | new exports |
| `perception_contention.py` | +18 / −11 | stream claim withdrawn |
| `navigation/semantic_map.py` | +6 / −1 | dead `getattr` line removed |
| `online_map/online_map.py` | +4 / −0 | **declared, P1-B's file** — `crop_png=entry.thumbnail` |
| `configs/navigation/prototype.yaml` | +13 / −0 | `veto_model` |
| `tests/test_p1d_vlm_veto.py` | +105 / −4 | 3 new cells (cold seat, measured budget, warm-up) |
| **new** `tests/test_p1d_eval_rows.py` | 330 | the CI eval row |
| **new** `tests/data/p1d_crops/**` | 41 files | the pinned fixture |
| **new** `scrum/20260822/task_9/evidence/**` | 10 files | scripts + results |

| Gate | Result |
|---|---|
| `pytest -q tests/test_p1d_vlm_veto.py tests/test_p1d_eval_rows.py` | **51 passed, 1 skipped** |
| Same, GPU arm enabled (bench venv, real seat) | **6 passed** (`test_p1d_eval_rows.py`) |
| Seeded RED, now **20** mutations incl. 8 new | **20/20 RED** |
| Flag-off identity, re-run after §11 | **identical**, `68cad544…` |
| Regression sweep (`perception_abstention`, `perception_contention`, `p0d_navigation_unblocks`, `c1_camera_stream`, `c2_online_map`, `c3_cutover`, `unknown_place_admission`, `prototype_profile`, `runtime_activation`, `release_parity` + both P1-D files) | **460 passed, 1 skipped** |
| `pytest -q` on 7 further consumers (`instructnav_grounding`, `city_semantics`, `nav_instruct_digest_recipe`, `arrival_semantics`, `e2_safety_wiring`, `nominal_stop_wiring`, `held_out_scene`) | **90 passed, 2 failed — neither mine**, §11.9 |
| `ruff check` on OWNS (9 files) | **All checks passed** |
| `ruff check src/parcel_robot/` | 12 errors, **all pre-existing**, none in a file P1-D touched |

One P0-D ratchet moved again: `test_the_prototype_profile_is_default_yaml_with_one_block_changed`
gained `perception.abstention.veto_model`, for the same reason and in the same
way as `ask_below_threshold` (§9 deviation 2) — the set stays exhaustive.

## 11.8 Deviations added by §11

1. **`src/parcel_robot/online_map/online_map.py`, one line** (`crop_png=entry.thumbnail`
   at ~978). P1-B's file, returned and closed. Declared as the coordinator
   required. Nothing else in that file was touched. Without it every veto sees
   no crop and the whole card degrades to ASK.
2. **`tests/data/p1d_crops/` is 1.6 MB of committed binary.** Justified by the
   llmdet lesson (a seat swap needs a pinned-fixture eval *in CI*), and kept as
   small as the job allows: 384 px PNGs, not the 1280×720 renders.
3. **A `pip` was bootstrapped into the 2026-08-21 research venv**
   (`ensurepip` + `pip install pytest`) so the GPU arm of the CI eval could run
   there. That venv is scratch under `/tmp`, not repo state, and `.parcel` was
   not touched.
4. **The orbit-pool fixture swap** — §11.3. A deviation from the
   pre-registration, not from OWNS.

## 11.9 Two failures observed, neither attributable to P1-D

`tests/test_held_out_scene.py` fails two cells:
`test_only_the_allowlist_names_the_held_out_scene` and
`test_no_test_outside_this_pair_loads_the_held_out_scene`. The offenders are
**`tests/test_p1b_map_learns.py`** (P1-B's, returned this wave) and
**`scrum/20260822/INTEGRITY_GATES_TODO.md`** (the peer session's). No P1-D file
names the held-out scene. Reported, not touched: reverting another executor's
work is forbidden, and the allowlist entry is theirs to justify.
