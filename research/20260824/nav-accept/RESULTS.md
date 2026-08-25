# NAV-ACCEPT — the M1 nav acceptance row · Opus executor · 2026-08-24

Card: NAV-ACCEPT (measurement only). Binding row, from `A2_VERDICT_FABLE.md`
§3: *"the SHIPPED configuration (commissioned inflation via the two production
owners) re-measured on this exact corpus, bar ≥ 0.80, before the first physical
point-goal session."* A2 could not measure it because the harness built arm B
through `ModelRegistry.create`, an un-commissioned caller, so arm B kept the
legacy 0.42 m inflation and was byte-identical before and after A2's fix.

Guard label `nav-accept` on every run. `git` READ-ONLY, nothing committed, zero
product-file changes, zero `noqa`, zero new ruff fingerprints, $0 hosted, the
owner's stack (`:8765`, `/tmp/parcel_sim.sock`, `:8080`,
`parcel_memory.sqlite3`) untouched. Host load 0.4–1.0 throughout.

---

## HEADLINE

| row | bar | frozen arm A | frozen arm B | **SHIPPED** |
|---|---|---|---|---|
| **N1 arrival ≤ 0.5 m** | **≥ 0.80** | 0.100 | 0.483 | **1.000  (60/60)** |
| N1′ object-class goals only | diagnostic | 0.000 | 0.417 | **1.000  (48/48)** |
| **N2 false arrivals (corpus)** | 0 | 4 | 0 | **0** |
| N3 contacts | 0 | 0 | 0 | **0** |
| **N4 typed non-arrival rate** | 1.00 | 0.88 | 0.00 | **1.00 — vacuous, see below** |
| N5 median time-to-goal (s) | reported | 46.95 | 11.20 | 14.55 |
| N5 median path/optimal | reported | 1.037 | 0.815 | 0.975 |
| episodes | 60 | 60 | 60 | 60 |

**The shipped configuration clears the 0.80 bar on the frozen corpus: N1 =
1.000.** Every one of arm B's 31 silent stalls became an arrival; so did all 54
of arm A's non-arrivals. Zero false arrivals, zero contacts, zero
gap-translating ticks (0 / 1 200 — R1's HOLD property preserved).

**Two things the same run also measured, and they are not decoration.** Under
this same commissioned clearance the frozen refuter set produces **3/3 false
arrivals on the R4b kidnap where the legacy inflation produced none**, and R3
turns from "arrives 3/3" into a **silent 900-tick stall with no route**. Both
are direct consequences of the fix that produced the 1.000. §Stage 1 costs.

**N4 = 1.00 is vacuous and must not be read as a capability.** `bench._score`
returns `1.0` when the non-arrival set is empty (`... if non_arrivals else 1.0`),
and it is empty. It carries no evidence that the shipped shape types its
failures; the R3 refuter below is the counter-evidence, where it does not.

---

## Harness delta — the frozen evidence is byte-unchanged

**No file under `research/20260824/nav-core/` was edited.** All 21 tracked
files (harness, corpus JSONs, RESULTS/VERDICT/DESIGN/REFUTER_4B_REMEASURE)
verify against the sha manifest taken before any work:

```
sha256sum -c research/20260824/nav-accept/frozen_sha_before.txt
  → 21 OK, 0 FAILED   (manifest + result: frozen_sha_before.txt, frozen_sha_after.txt)
```

The new arm lives in **`research/20260824/nav-accept/nav_accept.py`**, which
*imports* the frozen harness rather than copying it: `bench._episode_specs`
(corpus generation), `bench.SEEDS` (101/202/303), `bench._score` (every N-row
formula), `bench._refused_row`, `bench.run_refuters` (the whole refuter driver
including R4b's one-shot operator protocol), `arms.ArmB`, `arms._Runner.run`,
`door.ask`, `room`, `world_map`. Seeds, episode set, room, door, bars and
scoring are therefore the frozen ones by construction, not by transcription.

### What "the shipped configuration" means here, mechanically

No clearance number is written in the new file. `commissioned_navigator()`
calls the **production owner's own method**:

```
DirectiveNavigator._create_navigator(model_id, arrive_radius_m)
  → _planner_gate_ring_m()            # this navigator's own collision brake
  → registry.create(..., map_gate_clearance_m=<that ring>)
  → grid_navigator._planner_coupling_ring_m(...)
  → ClearanceProfile.gate_range_ring_m   # ring restated in the planner's frame
```

Values read back **out of the constructed planner** on every episode (recorded
per row in `extra`), and both production owners read the same way:

| production owner | site | brake | ring | planner `gate_clearance_m` | planner `inflation_radius_m` |
|---|---|---|---|---|---|
| 1 — pipeline | `navigation/pipeline.py::DirectiveNavigator._create_navigator` | 0.80 | 0.80 | **1.120000** | **1.0222956** |
| 2 — search owner | `navigation/search_owner.py::SearchOwnerController` | 0.65 | 0.97 | (0.97) | (0.885381) |
| — legacy arm B | `ModelRegistry.create`, un-commissioned | — | — | 0.4601409 | 0.4200000 |

Rows 1 and 2 reproduce A2's re-freeze table rows 1 and 2 to the digit, computed
here from the product rather than quoted. **Owner 2 is recorded, not applied:**
it builds the frontier searcher, and this corpus drives the point-goal
controller owner 1 builds. Applying owner 2's 0.65 m ring instead is A2's
already-published sensitivity arm; it was NOT re-run here, because the card's
rule forbids re-running with modifications and the pre-registered shipped
configuration is owner 1's.

### The reproduction control — the delta is attributable, not assumed

The same new driver was run with the **frozen `arms.ArmB`** unmodified
(`--control`). Against `nav-core/results/corpus.json`'s arm-B rows:

```
60/60 rows compared over 18 fields (arrived, truth_distance_m, steps, path_m,
failure_type, note, status, final_health, max_jump_m, …)
  → 0 field differences;  score dict IDENTICAL (N1 0.483, N4 0.00, 31 stalls)
```

So the driver reproduces the frozen arm B exactly, and the only difference
between `legacy_b_control` and `shipped` is the commissioned ring. The
0.483 → 1.000 delta is attributable to the commissioning alone.

---

## Stage 1 — the shipped corpus row

`shipped_corpus_margin_off.json` · 60 episodes · 40.3 s · $0

* **N1 1.000 (60/60)**, at every goal (bed 12/12, desk 12/12, bowl / couch /
  counter / shelf 9/9 each) and in every layout (15/15 × 4).
* Arrival distances 0.407 / 0.461 / **0.477** / 0.490 / 0.499 m (min, Q1,
  median, Q3, max). Every arrival is inside the band, and the distribution is
  **pressed against the band's edge**: the arm declares the moment
  `p_inside_disc ≥ 0.90` at the 0.5 m disc, so it stops as soon as it is
  probably inside, not when it is close. Legitimate under the pre-registered
  scoring; thin in metric terms, and worth knowing before a physical session.
* Time-to-goal 10.1 / 14.55 / 29.9 s (min / median / max); path/optimal
  0.732 / 0.975 / 1.620 — longer than arm B's 0.815 because the body now
  detours around inflated obstacles instead of driving at them and stopping.
* 0 contacts, 0 false arrivals, 0 translating ticks in 1 200 scan-gap ticks,
  max MAP jump 0.0343 m (consistent with NAV-CORE's 0.029 m record).
* Mechanism, exactly as NAV-CORE fix 3 predicted: the legacy planner inflated
  0.42 m while the reactive gate demanded 0.752 m at cruise, so the body was
  braked dead on routes the planner still called `status=planned` and never
  replanned (31/60 for arm B). Commissioned to 1.0223 m the planner only
  proposes corridors the gate will drive, and the stall class disappears.
  Notes on the shipped rows are `grid_track … route=2 status=planned` and
  terminal `align_terminal` — the planner is routing, not falling back.

### Scope — why this room admits 1.0223 m and the city does not

The NAV-CORE room is 8 × 8 m; every place and start keeps **≥ 0.88 m**
clearance in every layout and `audit_clearances` pins reachability on a 0.1 m
grid inflated by **0.95 m**. A 1.0223 m isotropic inflation is *above* that
audit's inflation and still routes here — this geometry is generous to it. The
same number is already known not to be generally affordable: A2 measured "the
demo city admits 0.885 m, not 1.022 m" (`test_sit_next_to_the_lamppost`), and
Lane A recorded three `test_search_reground_bench` strict-xfail STOPs with the
same attribution. **N1 = 1.000 is a room-scale point-goal result, not a claim
about the city**, and the R3 refuter below shows how little clutter it takes to
break it.

### The costs this run also measured (frozen refuter set, shipped clearance)

Run through `bench.run_refuters` **unchanged** (`shipped_refuters.json`,
265.9 s), arms substituted:

| refuter | frozen arm B (0.42 m) | **shipped (1.0223 m)** | reading |
|---|---|---|---|
| R1 scan dropout | 0/3 declared, 0 gap-translating | **3/3 declared @ ≤0.48 m**, 0 gap-translating | improved; HOLD property intact |
| R2 pose DEGRADED | 3/3 declared, 0 false | **3/3 declared, 0 false** | unchanged, still no claim on unhealthy pose |
| R3 moved obstacle | 3/3 declared, **1 false** | **0/3 declared** — 900-tick `silent_stall_step_limit`, note `grid_recover_scan status=no_path`, ends 4.26–4.50 m out | **REGRESSION.** A 0.45 m box 1.1 m ahead makes the route unroutable at 1.0223 m isotropic inflation, and the give-up is SILENT, not typed |
| R4b kidnap, shipped | 0/3 declared, **0 false**, post-kidnap path 0.01–0.23 m | **3/3 declared, 3/3 FALSE ARRIVAL at 5.21–5.26 m**, conf 0.988–0.998, MAP HEALTHY 128–155 of 134–171 post-kidnap ticks, post-kidnap path 3.72–4.48 m | **the luck ran out** |
| R4b kidnap, gated (A4/A10 latch) | 3/3 latched, 0.00 m | **3/3 latched, 0.00 m, 0 false** | the modelled latch still holds |
| R4b gated + one-shot operator | 3/3 latched, 0.25–0.32 m | **3/3 latched, 0.14–0.51 m, 0 false** | one bounded re-arm, then re-latches |
| R4 place absent (door) | refuses 3/3 | **refuses 3/3** | unchanged |

**R4b is the one to carry to the owner.** NAV-CORE's own words were: *"No false
arrival occurred, but only because the brake rings stopped both arms short of
the twin — luck, not a defence."* This run spends that luck. With the planner
commissioned, the body is no longer braked short of the C2 twin: it drives
3.7–4.5 m after the kidnap and **declares arrival, at 0.988–0.998 confidence,
5.2 m from the true goal, in the wrong half of the room.** The defect is
unchanged (R4b was already REFUTED on shipped arms); what changed is that its
consequence is now a wrong answer rather than a stall. The A4/A10 latch — still
a harness model with no product installer — holds it at 0.00 m, 3/3, and is
therefore no longer redundant with the brake ring but **load-bearing**.

R3's regression is the isotropic-vs-directional inflation item A2 handed up,
now priced on a refuter instead of on a demo-city test: `inflation_radius_m` is
isotropic and non-traversable while the gate it agrees with is directional, so
worst-case-correct inflation forbids routes the gate would allow. And the
failure arrives as `silent_stall_step_limit`, i.e. **N4's silent-stall class is
alive under the shipped configuration** — the corpus simply contains no episode
tight enough to show it.

---

## Stage 2 — the `require_relocalization_margin` flag rows

`shipped_corpus_margin_on.json` (39.7 s) + the same `shipped_refuters.json`,
where the flag-ON arm ran beside the flag-OFF arm on every refuter row.

| comparison | episodes | rows differing | refusals introduced | success-rate change |
|---|---|---|---|---|
| corpus, flag OFF → ON | 60 | **0 of 60** (18 fields each) | **0** | N1 1.000 → **1.000** (identical score dict) |
| refuters, flag OFF → ON | 36 | **0 of 36** (15 fields each) | **0** | every disposition identical |

**The delta is exactly zero, and the reason is that neither scenario set can
reach the code the flag guards.** `require_relocalization_margin` gates the
commit inside `ScanMatchLocalizer._relocalize`, which is called only from
`PoseHealth.LOST`. Instrumented tick-by-tick (read-only, from the localizer's
public `diagnostics`):

| scenario set | localizer ticks | `tracked` | `no_scan` | `anchor` | `reject` | LOST | relocalizations | margins published |
|---|---|---|---|---|---|---|---|---|
| corpus (60 ep) | 9 565 | 8 305 | 1 200 | 60 | **0** | **0** | **0** | **0** |
| refuters (36 ep) | 19 664 | 18 756 | 872 | 36 | **0** | **0** | **0** | **0** |

* **The corpus genuinely cannot exercise the margin path.** It contains no
  kidnap, and its one 2.0 s scan dropout per episode is below `lost_after_s`
  3.0 s, so staleness reaches DEGRADED and never LOST; no registration ever
  failed, so `lost_failure_streak` never fired either.
* **So the NAV-CORE refuter-4b set was run instead, as the card directs — and
  it cannot exercise it either.** In the C2-aliased world the kidnap lands on a
  pose whose scan agrees with the map to 8.9e-15 m, so registration *succeeds*
  at the twin: the localizer stays HEALTHY (128–155 of 134–171 post-kidnap
  ticks) and never enters LOST. **The kidnap is invisible to the exact code
  path the flag guards** — which is the same fact R4b already reports from the
  other side.

**Decision input, stated honestly: this run does not clear the flag to ship
ON.** Zero false refusals were observed, but there were also **zero
opportunities to refuse**, so A3's stated risk — *"watching for
relocalizations that were CORRECT and are now refused (a false refusal is a dog
that will not walk)"* — is **UNMEASURED, not disproven**. The only evidence
that exists remains A3's single normal-layout kidnap-onset fixture
(reject→reject→LOST→relocalized, jump 2.6375 m, margin −0.1365, LOST under the
flag). Recommendation to the integrator: **leave it OFF**, and attach the
decision to a scenario that actually reaches `_relocalize` — the
normal-layout kidnap-onset row `REFUTER_4B_REMEASURE.md` already records as
"unexercised and now owed" and A3 adopted as an acceptance criterion. It is a
NAV-CORE v3 row, not a corpus row.

---

## Reproduction

```bash
cd /home/jaewoo-jang/Desktop/Projects/Parcel
G="env -u TMPDIR $HOME/.cache/parcel-guard/pytest_guard.sh --label nav-accept"

# frozen-evidence check (before and after)
sha256sum -c research/20260824/nav-accept/frozen_sha_before.txt

# Stage 1 — the shipped acceptance row
$G .parcel/bin/python research/20260824/nav-accept/nav_accept.py --stage corpus --margin off
# reproduction control — must equal nav-core/results/corpus.json's arm B
$G .parcel/bin/python research/20260824/nav-accept/nav_accept.py --stage corpus --control

# Stage 2 — the flag rows
$G .parcel/bin/python research/20260824/nav-accept/nav_accept.py --stage corpus --margin on
$G .parcel/bin/python research/20260824/nav-accept/nav_accept.py --stage refuters

# tree undisturbed
$G .parcel/bin/python -m pytest tests/test_dec0_debt_ratchet.py \
    tests/test_decig2_import_ratchet.py -q          # 23 passed
.parcel/bin/ruff check research/20260824/nav-accept/  # clean
```

Raw rows: `shipped_corpus_margin_off.json`, `shipped_corpus_margin_on.json`,
`legacy_b_control.json`, `shipped_refuters.json` (each carries its own
`environment` block including the commissioning table read from the product).
Live logs under `logs/`, gitignored.

## Hygiene

`git status` at close: modified `gateway/core.py` and untracked `gateway/`,
`scrum/20260824/task_3/README.md` are **a peer session's work in this shared
tree, not this card's** — this card created only
`research/20260824/nav-accept/`. `git diff -- src/` is **empty**: zero product
files changed. Both DEC ratchets pass (23). Ruff clean, zero `noqa`, no new
fingerprint. Nothing committed. Host: jaewoo-jang-parcel, python 3.14.4,
2026-08-25T00:25Z, load 0.4–1.0; wall times reported but not offered as latency
rows.

## Does not prove

Everything NAV-CORE's own "does not prove" lists, unchanged: `desktop-sim`, a
ray-engine scan, synthetic detector noise, a kinematic body, a harness-seeded
learned map, and the A4/A10 latch and whole-map margin being *models* of a
proposed policy rather than product behaviour. Additionally: nothing here is
physical; N1 = 1.000 is one 8 × 8 m room whose clearances are generous to a
1.0223 m isotropic inflation, and R3 plus A2's demo-city test plus Lane A's
three STOPs all say the same number does not survive tighter geometry; N4's
1.00 is vacuous; and the arrival distribution sits at the band's edge by
construction. The gate decision belongs to the integrator and the owner.
