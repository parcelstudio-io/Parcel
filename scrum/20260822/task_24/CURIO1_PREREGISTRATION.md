# CURIO-1 — pre-registration

**Executor:** Claude Opus · **Verifier:** Fable · **Card:** `README.md` ·
**Board:** `../TASK_BOARD.md` · **Written:** 2026-08-22, BEFORE any measurement
and before the first line of source was edited. HEAD `8862220`.

Every number below is fixed here. Anything the measurement turns up that this
file did not predict is a MISS or a declared deviation in `CURIO1_STATUS.md`,
never a retro-fitted bound.

---

## 0. The two operating points, named before they are measured

The card asks for two things that cannot both be true of one configuration:

* "Poisson gaps, **mean 4–8 min**" — the cadence a companion should have in a
  room with a person in it;
* "in a **120 s** sim roam … **3–6 unprompted utterances**" — which needs a mean
  gap near 25 s, an order of magnitude faster.

So the card describes a SHIPPING cadence and a DEMO cadence, and this
pre-registration measures both rather than quietly picking one:

| point | `whisperer.curiosity.mean_gap_s` | where it lives |
|---|---|---|
| **S — shipping** | 360.0 (6 min, the middle of the card's band) | the code default and `configs/realtime.prototype.yaml.example` |
| **R — roam arm** | 25.0 | the 120 s roam harness only, in scratch, never committed to a config |

Row 1 is scored at point **R**, because that is the row the card wrote a bound
for. Point **S** is reported alongside as an arithmetic expectation with its
measured value, so a reader can see that the shipped dog is not this chatty.

---

## 1. The rows

| # | row | bound | how it is scored |
|---|---|---|---|
| **1** | unprompted curiosity utterances in a 120 s sim roam, lane on, point **R** | **3 ≤ n ≤ 6** | forwarded curiosity decisions in `Whisperer.decisions` that the lane actually narrated (`lane.narrations` delta) |
| **2** | **hallucinated places** — a remark naming a label that is not in `known_places()` at utterance time, or whose provenance is `vlm_proposed` | **0** (HARD) | the harness samples `known_places()` once a second into a timeline; each remark's place is taken from its decision `key` and checked against the newest sample **at or before** the remark |
| **3** | remarks narrated while the owner has a turn owed or a hosted response is playing | **0** | the lane's own counters: every curiosity narration attempt is scored against `lane.snapshot()["voice_turn_owed"]` and the response state sampled in the same tick; plus a dedicated mixed-traffic rig |
| **4** | curiosity forwards inside any rolling `window_s` | **≤ `max_updates_per_minute`** (6 at the prototype overlay) and **0** curiosity kinds in `CRITICAL_KINDS` | worst window over the 120 s roam + a saturation rig that offers one candidate per second for 600 s |
| **5** | hosted spend for the whole card | **≤ $0.10** per run, and in fact **$0.00** — no provider client is opened at any point | `recordings/spend.jsonl` sha256 + row count before and after every run |
| **6** | a config written before this card | **byte-identical whisperer behaviour**; `curiosity.enabled` reads `False`, every other value at its documented default | the real validator, on the shipped `configs/realtime.yaml.example` and on a `whisperer:` block with no `curiosity:` key |
| **7** | seeds RED | **each of the four seeds turns ≥ 1 named test RED**, and the restored tree is byte-identical (sha256) and GREEN | seed → run → `sha256sum` → purge `__pycache__` → rerun |

## 2. The four seeds (fixed here, before they are written)

| seed | the plausible defect | must turn RED |
|---|---|---|
| **A** | the admission gate drops the provenance test — any name the map has a row for may be spoken | the hallucination guard test |
| **B** | the scheduler stops reading the lane's busy state — a remark goes out mid-turn | the mid-turn guard test |
| **C** | `CURIOSITY_KINDS` folded into `CRITICAL_KINDS` — remarks spend past the owner's cap | the cap test |
| **D** | `CURIOSITY_KINDS` moved from the middle band into `ALWAYS_BAND` — a curiosity event handed to bare `Whisperer.offer` is spoken without ever passing the scheduler | the middle-band-needs-a-mechanism test |

## 3. What is OWNER-GATED and will not be claimed

* **Taste.** "Does the dog say something a person would want to hear" is not
  measurable here. Listed with its exact command; scoresheet ≥ 4/5 over a week
  of felt sessions is the owner's row, not mine.
* **The live model's wording.** No hosted session is opened. Whether
  `gpt-realtime` renders `place_learned` as "there's a new plant by the window"
  or as "my online semantic map admitted a new label" is a question about the
  model, and the HINT is the only defence this card has.

## 4. Declared in advance

* NM-1 has not landed. Until it does, "admitted" means **in `known_places()`
  AND not `vlm_proposed`** — which, on today's `entries.py`, means a detector
  label or a k-promoted name. NM-1's judge replaces the provenance test at one
  named seam.
* ROAM-1 has not landed. The 120 s roam is **MOVE-1's harness**
  (`scrum/20260821/task_20/evidence`, read-only) driving `PatrolRunner`, in the
  shape P1-B's dev-scene harness already used it.
* "Idle checkpoint" (`prompts/functions/patrol.yaml`, not edited) is read as
  `ActivityCoordinator.running() is None` — the coordinator that already owns
  checkpoint semantics. That is a proxy and the status doc says so.

---

# Addendum — the correction pass (2026-08-22, after Fable's ACCEPT + one correction pass)

Written BEFORE the two-cadence change was implemented and before anything was
re-measured. §0 above is superseded by ruling 6 below; every other row stands.

## 6a. The cadence was ONE card error, ruled by the card's author

The card's "mean 4–8 min" and "3–6 per 120 s" were never one number. They are:

| cadence | governs | knob | default |
|---|---|---|---|
| **stimulus** | a curiosity class fed by an EVENT — `novel_object`, `scene_change`, `place_learned`, `ask_about` | `whisperer.curiosity.stimulus_min_gap_s` | **25.0 s**, a fixed floor |
| **idle** | chatter when nothing has happened — `idle_remark`, time-of-day coloured | `whisperer.curiosity.mean_gap_s` | **360.0 s**, the mean of a Poisson gap |

## 6b. The re-measured rows, WITH THE SHIPPED DEFAULTS

The roam arm no longer overrides the cadence. `configs/realtime.prototype.yaml.example`
is what the run loads.

| # | row | bound |
|---|---|---|
| **1′** | unprompted remarks in a 120 s roam, **shipped prototype defaults**, with the 30 s owner-owed window imposed | **3 ≤ n ≤ 6** |
| **1i** | idle-chatter remarks in that same 120 s | **0** (a 6-minute mean cannot fire in two minutes; the row exists so "0" is a prediction and not a surprise) |
| **2′** | hallucinated places | **0** (HARD, unchanged) |
| **3′** | remarks while the owner is owed an answer | **0** (unchanged) |
| **4′** | worst rolling 60 s vs the configured cap | **≤ 6** (unchanged) |
| **5′** | hosted spend | **$0.00**, no provider contacted (unchanged) |

Reproducibility: two runs. The stimulus gap is a fixed floor and carries no
randomness, so the two runs are expected to agree to within one remark; a
disagreement larger than that is a finding, not noise.

## 6c. New guards, each with a seed pre-registered here

| seed | mutation | must redden |
|---|---|---|
| **A2′** (replaces A2) | the ASK path reads the queried label instead of `verdict.candidate` | the ask-candidate test — against the PRODUCT contract (`AbstentionVerdict.candidate`), not a stub field |
| **E** | `scene_change` skips the still-admitted test | the scene-change drop test |
| **F** | `place_learned` fires for a `vlm_proposed` name | the place-learned provenance test |
| **G** | the polled conversation clock stops calling `note_turn` | the conversation-clock test |
| **H** | the stimulus gate reads `mean_gap_s` instead of `stimulus_min_gap_s` | the stimulus-cadence test |

Seeds A, B, C, D from the first pass are re-run unchanged against the FINAL
tree, and `SEEDED_RED.json`'s sha256 pair is regenerated so it covers the tree
as shipped rather than the tree as of two docstring edits earlier.
