# NM-1 + ASK-1 — pre-registration

**Written BEFORE any measurement, any model load and any line of NM-1 source.**
Card: `README.md` (task_18) · design: `../WAVE2_DESIGN_FABLE.md` §1 (DW-2) ·
evidence this card exists to answer: `../task_9/P1D_STATUS.md` §3 rows 4–5.
Executor: Claude Opus · Verifier: Fable · Date: 2026-08-22.

Every number below is a commitment. A row that misses is reported as a MISS
with the measured value; no row is re-pointed after the fact, and any arm added
later is labelled POST-HOC in the status doc.

---

## 0. What is already true (the baseline this card must beat)

From P1-D, measured, committed:

* naming accuracy on the 40 textured `city_block` crops: **18/40 = 45.0 %**
  (`../task_9/evidence/row4_naming.json`), against the research's 82–87 %;
* the k-consistency gate promoted **2 names on the full-resolution arm and both
  were wrong** — `pole` for `traffic_light_1` and `yellow cylinder` for
  `bollard_1`, each with 3 independent agreeing visits
  (`../task_9/evidence/row5_kgate_fullres.json`);
* the shipping 64-px arm promoted 0 **because nothing reached k**, not because
  the gate worked ("safe because blind").

Those two false promotions are the hard evidence. **The new gate must reject
both.**

---

## 1. Work item 1 — three arms on the same 40 crops

Fixture: `tests/data/p1d_crops/` (40 PNGs, 384-px long edge, plus a 64-px
`thumbnail_b64` per crop in `MANIFEST.json`; ground truth from the scene's own
geom names). Seat: the repo's own `parcel_robot.vlm_veto.Qwen3VLVerifier`
(Qwen3-VL-2B-Instruct), weights found in the 2026-08-21 research cache.
Scorer: P1-D's frozen synonym table, verbatim, from
`/home/jaewoo-jang/.cache/parcel-p1d/scratch/run_vlm.py`.

| Arm | Crop | Prompt | Pre-registered prediction |
|---|---|---|---|
| **A1 fullres** | the committed 384-px PNG | `NAME_PROMPT`, verbatim | reproduces P1-D: **45.0 % ± 7.5 pts** (17–20 / 40) |
| **A2 thumb64** | the 64-px thumbnail the map actually stores | `NAME_PROMPT`, verbatim | **strictly lower than A1**, and ≤ 40 % |
| **A3 prompt** | the committed 384-px PNG | a class-anchored prompt (asks for the common noun; forbids a colour/shape description) | **≥ A1 + 5 pts**, and still **< 82 %** |

Reported for every arm: overall accuracy, per-class accuracy (the class
distribution arm), and the raw answer for every crop.

**Headline question, answered in advance:** does any arm reach the research's
82–87 %? Pre-registered answer: **no**. If one does, that is the finding and
the card says so.

The prompt in A3 is written into this file before it is run:

> `What kind of object is the main object in this image? Answer with the common
> noun for the object, one to three words. Do not describe its colour or shape.`

---

## 2. Work item 2 — the correctness judge

**Judge:** OWLv2-B16 open-vocabulary detector, ONNX Runtime,
`CUDAExecutionProvider`, fp16, weights `~/.cache/parcel/owlv2-b16` — the seat
the product already ships (`detection_adapter/owlv2_onnx.py`). It is an
independent judge in the sense the card requires: a different architecture,
different training data, a different question ("where is a `<name>`?") and no
shared decoder with the VLM, so a VLM that is *consistently* wrong cannot make
the judge agree with it.

**Rule:** a proposed name may become vocabulary only when
(a) k = 3 independent visits agree (unchanged, C-2's gate) **AND**
(b) the judge fires on the proposed name over the entry's best view with a
label strength at or above the floor.

**Pre-registered floor: `NM1_JUDGE_MIN_SCORE = 0.10`.** Adopted, not fitted: it
is OWLv2's own shipped `DEFAULT_OWLV2_THRESHOLD` — the score below which this
detector's boxes are not considered detections anywhere else in this codebase.
Fitting a floor on the same 40 crops the gate is then judged on would be the
mistake PG-3's docstring is about.

**Unavailable is not rejection.** No judge configured ⇒ the pass behaves
EXACTLY as HEAD does (flag-off identity, row F below). A configured judge that
cannot answer (no weights, no provider, no crop) **HOLDS** the name at
`vlm_proposed` and lets the next pass try again; it never refuses and never
admits. This is the prototype rule (ask-over-refuse, no new fail-closed
defaults) applied to a promotion: a hypothesis that cannot be checked stays a
hypothesis.

| Row | Claim | Bound |
|---|---|---|
| **J1** | judge on `pole` over `traffic_light_1`'s best view | **REJECT** |
| **J2** | judge on `yellow cylinder` over `bollard_1`'s best view | **REJECT** |
| **J3** | P1-D's full-res arm replayed through `run_naming_pass` with the judge ON — false promotions | **0** |
| **J4** | same replay — a name that is CORRECT and reached k is blocked by the judge | **0** |
| **J5** | judge recall on the 40-crop fixture: fraction of crops where the judge accepts the crop's TRUE class name | **≥ 0.80**, reported |
| **J6** | judge acceptance of the VLM's WRONG names (the crops A1 scores incorrect) | **≤ 0.25**, reported |
| **J7** | judge latency, per crop, GPU | **p50 ≤ 250 ms** |
| **F** | flag-off identity: `run_naming_pass(judge=None)` on P1-D's replay | byte-identical report to HEAD's (**2 promotions, both false**) |

J3 is the card's headline bound. J5/J6 are the judge's own operating point and
are *reported*, not tuned.

---

## 3. DW-2 (a) — no VLM on the 10 Hz control thread, FATALLY

| Row | Claim | Bound |
|---|---|---|
| **C1** | transitive call-graph reachability from `RobotRuntime._control_loop`, over every `self.<method>` edge inside `runtime.py`, reaches no name in the forbidden set (VLM/judge constructor, warm-up, inference, image-encode, model-load, network) | **0 reachable** |
| **C2** | `_control_loop` MARKS its thread, so the runtime tripwire is armed on the real loop and not only in a test | marking present |
| **C3** | the tripwire: a veto requested on a marked thread raises `ControlLoopViolation` | raises |
| **C4** | no module reachable from the loop imports `parcel_robot.vlm_veto`, `torch` or `transformers` | **0** |

Seed for C1/C2: call the veto **synchronously** from the control loop in a
byte-identical scratch copy of `src/` → the FATAL test must go RED.

---

## 4. DW-2 (b) — a bounded worker and immutable, identified verdicts

A published verdict carries, immutably: the **query**, the **place id**, a
**place revision** derived from the evidence it was computed against, the
**model identity**, the **capture time**, the **result time** and an
**expiry**. Navigation consumes a verdict only when it is *ready*, *matching*
(query + place + revision) and *fresh*.

| Row | Claim | Bound |
|---|---|---|
| **W1** | synchronous verifier invocations on the navigation caller's thread, over a full gate pass | **0** |
| **W2** | missing verdict ⇒ the gate ASKS (never admits, never refuses for it) | ASK |
| **W3** | expired verdict ⇒ ASK, and a re-computation is requested | ASK |
| **W4** | verdict whose place revision no longer matches ⇒ ASK | ASK |
| **W5** | worker queue is bounded; overflow drops and is counted, never blocks the caller | bounded, counted |
| **W6** | a ready + matching + fresh verdict IS consumed (the path is not dead) | consumed |
| **W7** | a published verdict is immutable (frozen; mutation raises) | raises |
| **W8** | budget-declined (contention) ⇒ ASK, not a synchronous run | ASK |

---

## 5. DW-2 (c) — `as_ask()` through the broker, granting nothing

| Row | Claim | Bound |
|---|---|---|
| **B1** | an ASK verdict returned through `navigate_to`: calls to the `navigate` door | **0** |
| **B2** | same: calls to `on_dispatch` (the lease/turn door) | **0** |
| **B3** | the ASK payload keeps `AbstentionVerdict.candidate` as the subject (CURIO-1's `ask_about` feed reads it) | present, equal to the verdict's `candidate` |
| **B4** | the owner confirms with the token the ASK issued, against a **newly compiled** revision that matches ⇒ exactly **1** `navigate` call | **1** |
| **B5** | the owner confirms with a STALE token (the revision moved) ⇒ **0** `navigate` calls, and a fresh ASK | **0** |
| **B6** | a confirm token that was never issued ⇒ **0** `navigate` calls | **0** |

---

## 6. Seeded RED — every new guard

At least **ten** seeds, each mutating the PRODUCT on a byte-identical scratch
copy of `src/`, each naming the test that must go RED, each restored by sha256
with `__pycache__` purged before and after. Pre-registered bound: **100 %
caught**. The seed list is fixed here:

1. promotion without the judge's agreement (the judge call deleted)
2. the judge floor lowered to 0.0 (everything passes)
3. judge UNAVAILABLE treated as agreement
4. a rejected name is left `promoted` instead of held at `vlm_proposed`
5. `_control_loop` no longer marks its thread
6. the veto called synchronously from the control loop
7. the board reader falls back to a synchronous verifier call on a miss
8. verdict expiry ignored (a stale verdict is consumed)
9. verdict place-revision match dropped (a verdict for another world is consumed)
10. the broker's ASK dispatches motion (the ASK arm falls through to `navigate`)
11. the broker accepts a stale confirm token

---

## 7. Gates

* `pytest` on `tests/test_nm1_*.py` and on every existing file that reads the
  surfaces this card moves (`test_p1d_vlm_veto.py`, `test_p1d_eval_rows.py`,
  `test_c2_online_map.py`, `test_p0d_navigation_unblocks.py`,
  `test_curio1_*.py`, the broker's own tests) — **all green**.
* `ruff check` on OWNS — **0 findings**; the fingerprint ratchet stays at
  **exactly 7**; no `noqa` added; no pin re-generated.
* `scripts/ci_gate.py` is **not** run (another card owns it).

## 8. What is OWNER-GATED and will never be claimed

Any row needing a camera. No robot hardware is on hand; only the XVF3800 mic
array. Every camera row is listed with its exact command and marked NOT RUN.
