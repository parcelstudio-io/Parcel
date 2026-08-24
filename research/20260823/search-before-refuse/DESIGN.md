# H8 — search before refuse · DESIGN (Fable) · 2026-08-24

## Owner's report (verbatim)
> tool navigate_to: rejected — not started: the robot's map has no place
> called 'city books'; the places it does know nearby are the crosswalk, the
> sidewalk and the planter; ask the owner which of those they mean, or which
> real place they want

Owner's direction: when asked to navigate somewhere, the dog should LOOK
AROUND for the entity rather than trusting only its map — the map is what it
has learned so far, not what exists; the navigation controller should include
this exploration.

## Hypothesis (falsifiable)
If the hosted/local `navigate_to` door admits an unknown noun as a **bounded
search mission** instead of refusing — set the detector query to the noun,
scan in place, then run the navigator's existing SearchEntity frontier ladder
within radius R / budget T, ground on detection (and on OCR for signage), and
only then refuse honestly with what was seen — then in the headless city the
dog finds ≥ 70 % of target entities that are visible from somewhere within
R = 12 m of its start (policy arm, frustum-oracle evidence), grounds on the
wrong thing ≤ 5 % of the time, never "arrives" at an absent entity, keeps 0
contacts, yields to the owner's stop within one tick, and the door reports a
typed disposition (`searching` → `found` | `not_found`) the model can narrate.

## Why (code reading 2026-08-24)
- The refusal is the broker's, not the navigator's: `realtime/tool_broker.py:1779`
  `_navigate_to` checks the noun against `self._doors.places()` (the learned
  map's known places) and returns `STATUS_UNKNOWN_PLACE`; `realtime/config.py:697`
  `unknown_place` ∈ {refuse, ask} (P0-B). Nothing downstream ever sees the
  directive.
- The navigator already implements the ladder the owner asks for:
  `navigation/pipeline.py:3583` "Frustum → memory → ScanBehavior →
  SearchEntity → honest refusal"; `instructnav/search_entity.py:274`
  `SearchEntityPlanSpec` (budget 90 s, radius 12 m, 3 rings × 12 bearings,
  travel weight); `_step_search_entity_frontier` (`pipeline.py:4170`),
  `_select_semantic_frontier` (`:4289`). It is exercised by tests
  (`test_value_directed_search.py`, `test_v4s_search_cells.py`,
  `test_search_owner.py`) — never by the product's hosted door.
- `runtime.py:13806` `_set_camera_query_from_directive` appends the directive
  noun to the OWLv2 query batch (P0-D) — the "look for X" wiring exists.
- Signage: "city books" is a storefront NAME. The sim's fascias carry baked
  sign lettering (`scenes/city_block.xml:78-81`); `storefront/ocr.py` has
  `OcrEngine` (Paddle if installed, `FakeOcrEngine` fixtures) and
  `storefront/ingest.py` turns OCR hits into detections. A search for a name
  needs the OCR arm, not only open-vocab boxes.
- The owner-lost case already runs a system-initiated `SearchOwner` plan
  through `task_executive` (`runtime.py:5880`); entity search is the same
  shape with a different skill.

## Objective
Show that "look before you refuse" is a door-policy change on top of
machinery we already have, measure how well that machinery actually finds
things when it is allowed to, and produce the typed disposition the
conversation needs to narrate a search honestly.

## Experiment
1. **Door policy** (product seam, additive, default unchanged):
   `realtime/config.py` accepts `unknown_place: search` (validated like the
   other two; `refuse` stays the default; `configs/realtime*.yaml.example`
   document it); `tool_broker.py:_navigate_to` in `search` mode does NOT
   refuse on an unknown noun — it returns `STATUS_SEARCHING` (new status,
   tense NOT_STARTED→IN_PROGRESS mapping like the others) and passes the
   directive to the navigate door with `search_budget_s`/`search_radius_m`
   from a new `search:` config block (defaults 90 s / 12 m); `not_found`
   surfaces as a new terminal status carrying `seen: [...]` (the entities the
   search DID see — the honest refusal). Counters beside
   `unknown_place_asks` (`searches`, `found`, `not_found`).
2. **Runtime door**: if `_realtime_navigate` needs a change to pass the
   budget through to `start_navigation`, keep it to the argument plumbing
   and report the hunk; if the navigator's ladder engages with no runtime
   change, say so — that is the preferred finding. (runtime.py is otherwise
   frozen under the research wave.)
3. **Harness** in `simulation/headless_city.py`'s `HeadlessCityQualityHarness`
   with `semantic_source` that does NOT know the target a priori:
   - **arm A (policy)**: frustum-oracle evidence — an entity counts as
     detected only when inside the camera frustum and within 12 m
     (deterministic; isolates the search POLICY from detector quality);
   - **arm B (detector)**: the real OWLv2/SigLIP-2 chain on EGL renders via
     your own perception daemon on a private socket, ONLY if `nvidia-smi`
     shows ≥ 5 GB free VRAM (two GPU servers + a daemon are resident on this
     host); otherwise arm B is "not run — VRAM" and said so;
   - **arm C (signage/OCR)**: `storefront` OCR over fascia renders; Paddle if
     `paddleocr_available()`, else `FakeOcrEngine` fixtures — report which.
   Targets: 20 present entities (primitives + 4 storefront names) placed so
   each is visible from some viewpoint within 12 m but NOT from the start
   pose; 10 absent entities. Seeds fixed; 3 runs per arm. Baseline arm =
   today's `ask` behavior (0 searches).
4. **Owner interrupt**: a scripted "stop" / owner-speech event at t = 20 s in
   one run per arm; measure preemption latency and that the search ends.
5. **Dialogue**: capture the door's status sequence per episode and render
   the narration the hosted model would receive (fake transport) — the
   `searching`/`found`/`not_found` texts must never claim arrival before
   arrival (voice guardrail).

## Measurements (pre-registered)
| row | metric | criterion |
|---|---|---|
| S1 | find rate on present entities, arm A | ≥ 0.70 (report arms B, C) |
| S2 | median time-to-find, distance travelled | reported |
| S3 | wrong-grounding rate (arrived at a different entity) | ≤ 5 % |
| S4 | absent entities → `not_found` with `seen` list; false arrivals | 100 % / 0 |
| S5 | contacts; min clearance | 0; ≥ profile stop distance |
| S6 | preemption on owner stop / speech | ≤ 1 tick; search terminated |
| S7 | disposition sequence valid on every episode; no pre-arrival "arrived" text | 100 % |
| S8 | product path: `unknown_place: search` reaches the navigator's SearchEntity ladder with zero runtime.py edits | yes/no (report the hunk if no) |
| S9 | signage arm C find rate on the 4 storefront names | reported (≥ 0.5 if Paddle is available) |

## What would refute it
S1 < 0.4 in arm A ⇒ the ladder is not a search controller (report where it
stalls: ScanBehavior never fires, frontier selection degenerate, budget
exhausted) — then the milestone design owes a new exploration controller
(ring/bearing viewpoints with information gain), not a door change. S3 >
10 % ⇒ grounding needs multi-view confirmation before commit. S8 = no ⇒ the
door and the navigator disagree on the directive contract (NAV-T1's typed
goal becomes a prerequisite).

## Evidence tier / does not prove
`desktop-sim`. Proves the policy and the existing ladder's behavior with
oracle-frustum evidence, and the detector arm's behavior on renders if VRAM
allows; proves nothing about real-camera recall or real signage OCR.

## OWNS
`research/20260823/search-before-refuse/**`; `realtime/tool_broker.py`
(`_navigate_to` search mode, the two new statuses, counters);
`realtime/config.py` (`unknown_place: search`, `search:` block);
`configs/realtime.yaml.example` + `realtime.prototype.yaml.example` (docs
lines only); `tests/test_h8_search_before_refuse.py` (broker mode: unknown
noun → `searching`, budget plumbing, `not_found` carries `seen`; `refuse`
and `ask` byte-identical to today). Must not touch: `runtime.py` beyond the
argument-plumbing hunk in `_realtime_navigate` if S8 forces it (report it),
`navigation/pipeline.py` (measure it; propose changes in RESULTS), the
owner's stack, `configs/robot.yaml`, frozen NAV_INSTRUCT baselines.
