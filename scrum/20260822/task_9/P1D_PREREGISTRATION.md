# P1-D — pre-registration

**Written BEFORE any P1-D measurement was taken and before the first line of
P1-D source existed.** Card: `README.md`. Board: `../TASK_BOARD.md`.
Executor: Claude Opus. Verifier: Fable. Date: 2026-08-22.

Order of operations, fixed here: (1) this file, (2) source, (3) fixtures
rendered, (4) the five rows measured **once** each in the order below, (5)
tests, (6) status doc. A row that misses is reported as a miss. A threshold is
only allowed to move after a measurement if the move is declared as a deviation
with the number that caused it.

---

## 0. The state being replaced

C-3 measured **0/18** learned-map admissions on perfect-geometry data, every one
`indecisive_ranking` (`scrum/20260821/task_13/C3_STATUS.md` §5.2). P0-D fixed
the estimator mechanically (`label_strength_margin`) and made the signal roster
configurable. This card gives the gate its **replacement signal** (the
Qwen3-VL-2B veto) and its **new posture** (ADMIT / ASK / REFUSE).

## 1. The design, fixed before measurement

* **Roster.** `signals = [label_support, evidence_count, ranking_margin,
  vlm_veto]` in the prototype overlay. Shipping `DEFAULT_SIGNALS` does not move.
* **Three-way outcome.** `ADMIT` when every active gate passes and the veto does
  not fire. `REFUSE` reserved for (a) the veto answering *absent*, (b) zero
  evidence — `no_observations`, `no_detector_support` — and (c) `not_navigable`,
  which is a physical fact about the world and not a question. **ASK** for
  everything else below the admit threshold: `label_disagreement`,
  `insufficient_evidence`, `indecisive_ranking`.
* **A veto that cannot run is an ASK, never an ADMIT and never a blanket
  REFUSE.** Enabling `vlm_veto` therefore requires `ask_below_threshold: true`
  (a construction invariant), so "the gate is enabled but unwired" can only ever
  cost a question.
* **Veto threshold.** `p_yes < 0.5` ⇒ absent ⇒ veto. Taken verbatim from
  `bench_retrieval.md` §2 ("p_yes ≥ 0.5"); **not** re-derived here, and declared
  as inherited.
* **k-gate.** `k = 3` independent visits (C-2's `NAME_PROMOTION_VISITS`).
  Demotion on disagreement removes one supporting visit; a promoted name that
  falls below k reverts to `vlm_proposed` and leaves `known_places()`.

## 2. Fixtures, named before use

| id | what | where |
|---|---|---|
| **F-MAP** | C-2's 16 retained `CameraDetectionFrame` rows from a live run against W-1's **textured** `city_block` scene | `tests/data/c2_online_map_frames.json` |
| **F-CROP** | textured `city_block` renders at F-MAP's own robot poses, cropped to F-MAP's own detection boxes | rendered by this card, pinned by sha256 |
| **F-ABSENT** | the 8 absent-object queries | fixed in §3, row 2 |
| **F-NAME** | 40 crops with ground-truth class labels | drawn from F-CROP + the 2026-08-21 `bench-vlm` crop set, pinned by sha256 |

## 3. The five rows

Each row states its target **now**. "Report only" means no target: the number is
the deliverable.

| # | Row | Target fixed here |
|---|---|---|
| **1** | **≥ 1 ADMIT reachable from a learned map on perfect-geometry data** — the exact state that was 0/18. Abstention ON, prototype roster, veto installed and answering. | **≥ 1 admitted** out of the present-query set |
| **2** | **0/8 admitted on the absent-object set.** Queries: `Narnia`, `my office`, `the moon`, `a coffee shop`, `a fire hydrant`, `a swimming pool`, `the airport`, `a coffee shop` *matched against a `shop` entry* (the D-R3 refutation). Outcome must be REFUSE or ASK — **never ADMIT**. | **0 admitted / 8** |
| **3** | **ASK rate**, over the union of row 1's present set and row 2's absent set, reported per outcome class. | report only |
| **4** | **Naming accuracy on the 40-entry F-NAME fixture** — Qwen3-VL-2B, `Q_NAME` prompt, scored against the 2026-08-21 synonym table. | report only; the research predicts **82–87 %** |
| **5** | **The k-gate's false-promotion count** — names promoted into `known_places()` that are wrong, over a simulated 3-visit replay of F-NAME. | **0 false promotions** |

### Predictions, recorded so they can be wrong

* Row 1 will admit **2** places (`lamppost`, `tree` / `bench`), because P0-D
  already measured 2/2 admissions on this fixture without the veto, and the veto
  is subtractive — it can only take one away.
* Row 4 will land **inside 82–87 %**. If it lands above, the fixture is easier
  than the research's; if below, the crop quality or the textured scene is
  harder. Either way the number is reported as measured.
* Row 5 is the one I expect to be hardest to hold at 0, because ~1 name in 7 is
  wrong and three agreeing visits of the *same* wrong name is exactly the
  failure the k-gate cannot see. If it is non-zero, that is the finding.

## 4. Seeded RED, fixed here

Every new guard gets a seed. Two are named by the card and are mandatory:

1. **MAD-zero margin re-introduced** — force `ranking_margin_mode: robust_z` on
   the prototype roster; row 1 must collapse to 0 admitted.
2. **Promotion without k agreements** — promote a name after 1 visit; row 5's
   guard must go red.

Plus: veto disabled ⇒ an absent-object crop admits; `ask_below_threshold`
removed ⇒ ASK collapses to REFUSE and row 3's ASK count goes to 0; the D-R3
substring match ⇒ `a coffee shop` admits against a `shop` entry.

## 5. What is inherited, not derived

Declared so no reader mistakes it for this card's measurement:

* `min_ranking_margin: 1.5`, `min_evidence_frames: 3`, `min_label_purity: 0.5`,
  `STRAY_LABEL_STRENGTH: 0.12` — all P0-D's, all provisional, all read off the
  2026-08-21 retrieval bench.
* The veto's `p_yes ≥ 0.5` operating point — `bench_retrieval.md`.
* `k = 3` — C-2's `NAME_PROMOTION_VISITS`.
* Qwen3-VL-2B as the seat — `SYNTHESIS.md` decision 4.

## 6. Routed refutations accepted into this card

* **D-R3** (`WAVE_P0_VERIFICATION_FABLE.md`): `navigation/semantic_map.py`
  `_matches` admits `a coffee shop` against a `shop` entry through a substring
  fallback, on the mission path, in the **admission** direction. Fix: matching
  becomes strength-typed; a substring-only hit is **at most an ASK**. Row 2
  carries the seed.
* **D-5** (minor): `semantic_map.py` compares a bare `"label_strength"` literal
  instead of the module constant.
