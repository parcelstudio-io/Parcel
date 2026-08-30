# NAV-INT-1 — VERDICT (Fable, the wave's designated verifier)

Verifier: Fable (parcel-0e), 2026-08-29 20:0x EDT. Design frozen 15:3x;
post-start amendments N1–N11 (15:41, 15:53); the blind gold set
(`gold_blind.json`, 110 cases, sha256 c253df2f…) was authored by me and
frozen before the classifier ran (hash verified in results.json). Executor:
Opus; the 40-episode tier completed (0 harness errors) and results.json was
written; the executor was killed before writing the H-NI1a/b sections,
which I wrote from the artifact (RESULTS "Stage 3 (written by the
verifier…)"). A foreign `VERDICT.md` (Sol, 17:31) exists here; its numbers
match the artifact and I concur. Evidence tier: `desktop-sim` (MuJoCo static
city through the live runtime, text commands, `use_llm=False` local sketch
lane, no reasoner).

## Verdicts

| | bar | measured | verdict |
|---|---|---|---|
| **H-NI1a** (i) admission | ≥ 0.8 | 24/32 = 0.75 [0.58, 0.87]; **amend-cue 7/14 (0.50)**, explicit-directive 14/14 | **REFUTED** — the C8 amendment path admits half of the cue-prefixed utterances; a plain second directive is admitted every time (but cancels goal 1) |
| (i) latency | ≤ 1.0 s | p50 12.4 ms, p95 22.4 ms (admission-at-any-poll, N2) | met |
| (ii) amended-goal success | Δ vs from-rest ≥ −0.10 | both authorities 11/28 = 0.39 vs 0.75 from rest, **Δ −0.36**; 7/32 interruptions refused with goal 1 continuing | **REFUTED** |
| (iii) switch window | 0 collisions / false arrivals | 0 / 0 (min clearance 0.83 m; n = 40 detects ≥ 7.5 %); but 3 false-arrival categories on final scoring | met in the window; not at the terminal |
| **H-NI1b** return | ≥ 0.9 where both goals reachable | 8/9 = 0.89 [0.57, 0.98]; all re-issued 13/34 = 0.38; 6 re-issues were triggered by a *false* `failed` | **REFUTED** at the point (CI includes the bar); the product's terminal is the confound |
| path ratio | ≤ 1.15 vs the oracle sequence | mean 1.49, p50 1.31, p95 2.25 (n = 8); the from-rest two-goal sequence completed 0/5 | **REFUTED** |
| **H-NI1c** classifier | ≥ 0.9 per class on the blind set | 0.827 [0.75, 0.89]; revise 0.90, keep 0.93, **queue 0.67, clarify 0.80**; non-adversarial 0.91, adversarial 0.68; post-hoc v2 0.97 (not the pre-registered number) | **REFUTED** on two classes |

## What the tier actually found (product facts)

1. **Amend-cue admission is 50 %.** The transactional path (`_apply_goal_amend`
   → `replace()` on the same task id) is the one the owner's example needs
   ("actually, go to the sofa"), and it admits half the time on this
   vocabulary; the bare-"actually" HOLD row shows the stall.
2. **Two live defects:** an owner-referring amendment suspends goal 1 and
   cannot admit the replacement (robot parked); a held queue utterance
   re-issued verbatim is refused (the cue must be stripped).
3. **Authority disagreement is the dominant terminal noise:** 17/80 scored
   legs (11 system-failed-but-arrived, all on the bench; 6
   system-succeeded-but-not-arrived) — the NAV-QUALITY class, reproducing
   from rest. Six of the 34 re-issues were triggered by a false `failed`.
4. **Resume is a re-issue and costs 1.3–1.5× the oracle path**; the product
   has no queue (the parked resume intent is consumed on commit).

## What this means for the program
R4/R5 in the report stand as *work items*, not as demonstrated capability:
a plan-queue seam with lineage, cue-robust amendment admission, the two
defects, and the arrival-authority fix come before any Model B can be
evaluated on the real stack. The blind classifier result says the
keep/revise/queue/clarify decision needs context features the keyword rule
lacks (the post-hoc v2 shows the headroom; it must be re-frozen and
re-tested blind).

## What it does NOT prove
Text commands, no audio, `use_llm=False`, one static city, four landmarks;
n = 40.
