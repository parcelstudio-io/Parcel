# Research program 2026-08-24 — scoped to what MOUNTS · design owner Fable (parcel-fb)

Owner directive (2026-08-24): resume the research, but **scope it to what is
mountable as a prototype**. Two additions: (1) handle compound instructions
WITHOUT the gemma-26B (an Orin cannot hold it); decide the platform — Unitree
Go2 EDU Plus vs Deep Robotics X30 Pro (AGX Orin) — including whether either
supports 5G, because Wi-Fi will not always be there; the dog must keep basic
capabilities offline, degraded but present, never "works only with internet";
(2) navigation that looks around for the entity instead of trusting the map
(the `city books` refusal) — an exploration controller.

Constraint of the moment: the account's weekly limit (resets Aug 28, 10:00
America/New_York) stopped Opus executors and a Fable verifier mid-flight at
~00:40. Until it resets or is raised, Fable works solo: verdicts from the
salvaged RESULTS, designs, decision memos, small measurements. Dispatch
resumes the moment executors can run.

## Scope rule ("mountable")
An item stays in the program only if its output runs on the mounted dog —
Orin-NX-class compute on the body, an optional desk GPU or cloud when a link
exists, and an **offline floor** (listen, answer simply, stop, follow, go to
a known place, remember) with no link at all. Everything else moves to
"after mount".

## Carry-forward from 2026-08-23 (salvaged; Fable verdicts in each folder as written)
| # | folder | state at the limit | mount relevance | disposition |
|---|---|---|---|---|
| H1 | `../20260823/ambient-ear-cost-ladder/` | executor alive; C1–C9 measured | **core** — the ear and the cost policy | VAD-gated hosted mini is the online answerer (≈ $1–7/mo on the corpus duty cycle); the local ladder is the *offline* floor, not a cost measure |
| H2 | `../20260823/local-cognition-gpu/` | executor alive; re-measuring latency | **re-scoped** → H9 (on-robot sizing) | 8B talker TTFT 126 ms is the offline floor's voice; monologue agreement 0.40 refutes the LLM-as-tick idea — the tick is deterministic drives + LLM phrasing only |
| H3 | `../20260823/drives-and-initiative/` | executor died after RESULTS | after mount (initiative policy), but D5/D6/D7 are mount-safety rows | verdict pending the D4 contact investigation |
| H4 | `../20260823/continuous-body-intent/` | executor died after RESULTS; B1–B9 met | **core** — the body contract for Go2 Sport AND the custom robot | verdict from RESULTS + tests |
| H5 | `../20260823/governed-continual-memory/` | VERDICT: REFUTED as pre-registered; 4 defects | after mount (fix the 4 defects in M1-4) | done |
| H6 | `../20260823/noticing-loop-perception/` | executor done; verifier died | **core** — freshness + the real-photo operating point; CPU-bound loop | verdict-lite from RESULTS |
| H7 | `../20260823/localization-delegation-bench/` | executor died after RESULTS; L1–L8 (L5 missed) | **core** — the MAP-role contract for the LIO on the body | verdict from RESULTS + tests; NEES miss = covariance must be calibrated before health thresholds trust it |
| H8 | `../20260823/search-before-refuse/` | DESIGN only; executor died at start | **core** (owner's ask 2) | dispatch first when executors return |

## New items
| # | folder | question | output |
|---|---|---|---|
| H9 | `offline-first-cognition/` | Without gemma-26B on the body: can a typed compound-instruction grammar + an 8B (or smaller) local model on ≤ 8 GB VRAM handle "go to X then Y / find X and come back / follow me until Z" with PlanIR validity ≥ 0.9 on a compound corpus, and what is the offline floor's full capability list, measured? | DESIGN → executor → VERDICT; the offline-floor table the milestone design commits to |
| H10 | `platform-and-connectivity/` | Go2 EDU Plus vs X30 Pro vs Go2 + compute payload; 4G/5G reality; link-loss degradation ladder | **decision memo** (desk research + power/weight/VRAM budgets + the degradation ladder); no hardware experiment is possible here |
| H8 | (above) | search before refuse | as designed |

## Output
`../20260823/MILESTONE1_DESIGN_FABLE.md` is updated in place (it remains the
milestone document); this folder's items feed its §2 topology, §4.1/4.2
(offline floor), §4.8 (exploration), and a new §2b platform decision.
