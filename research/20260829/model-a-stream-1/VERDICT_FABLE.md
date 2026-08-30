# MA-1 — VERDICT (Fable, the wave's designated verifier)

Verifier: Fable (parcel-0e), 2026-08-29 20:0x EDT. Design frozen 15:3x;
post-start amendments A1–A10 at 15:53 (applied: A1, A2, A3, A4, A7, A8;
A5 partial; A6, A9 not run — RESULTS §6). Executor: Opus, killed by the
spend limit after the run completed (RESULTS complete, 1,686 s wall).
Evidence tier: `desktop-sim` (headless city, kinematic, real generated MJCF
geometry variants; no audio; scripted cues). A foreign `VERDICT.md` in this
folder was written by Sol (18:02); I audited its blocking findings in the
code before writing this one.

## Independent checks (mine)

- Sol's finding 1 (oracle-derived state leaks into inputs): **confirmed** —
  `teacher.py::update_own_state` is defined (:458) and never called; the
  frame's blocked/replan channels come from `derive_event`, which is
  gold-derived.
- Finding 2 (the switch scorer can see the answer): **confirmed** —
  `GOAL_MASK_FRAMES = 5` but `SWITCH_WINDOW_FRAMES = 10` (teacher.py:287,
  :290); a bearing-follower receives the new goal inside the window.
- Finding 5 (gold band changed after prevalence): **confirmed** —
  `closed_loop_core.py:108–115` records that the 0.65 m stop band fired too
  rarely on the 600 held-out episodes and the 1.2 m slow band was used;
  RESULTS §6.2 still cites the stop band.
- The reference rows and A2's real-geometry split are as described
  (`scene_gen.build_scene` variants; manifest + checkpoint hashes in
  results.json). I did not retrain (GPU time and the wave's clock).

## Verdicts (on the numbers as printed, then on validity)

| | bar | measured (600 held-out generated layouts) | verdict |
|---|---|---|---|
| **H-MA1a** closed-loop transfer | ≥ 0.85 × teacher success; C beats STRAIGHT-TO-GOAL by ≥ 0.10 where it fails | teacher **0.045**, C **0.037** (0.82 × teacher), A′n 0.198, STRAIGHT 0.217; C − STRAIGHT = −0.18 | **REFUTED** — and the teacher itself is the finding |
| **H-MA1b** interruptions absorbed | switch ≥ 0.9 within 1 s (masked cue); queue task-stack exact ≥ 0.8 | C 0.178, A′n 0.918, teacher 0.533; task-stack exact 0.0 for every arm | **REFUTED** (and the window/mask defect means even A′n's 0.92 is optimistic) |
| **H-MA1c** narration right and on time | macro F1 ≥ 0.85; false-event ≤ 0.05 | C 0.50 (product-backed partition **0.006**, research-only 0.75; `nav.arrived` F1 0.0; every predicted terminal without a receipt), A′n 0.70 | **REFUTED**; "rules suffice for narration" (C − A′n = −0.19) |
| **H-MA1d** liveness | attend ≥ 0.8; ΔSR within 0.03 | C attend 0.93, ΔSR −0.033 | met — but on a 4 % success floor it carries no weight |
| A5 last minute | C-h60 − C-h0 ≥ 0.10 | history ablation *improved* switching (0.15 → 0.53) | "window suffices" — and the history channel carried leaked labels |
| A8 safety | raw ≤ 1 % | raw twist-while-owner-speaking **1.07 %**, into-occupied 0.27 %, post-filter 0 | marginal miss; "A runs only behind the filter" |
| M4 latency | p99 ≤ 20 ms GPU / 60 ms CPU | 2.18 ms / 15.1 ms | met (desktop, not Orin) |

**Verdict: H-MA1 REFUTED; and the run is not promotion-quality evidence for
or against a streaming Model A** (Sol's validity findings 1, 2, 5 confirmed
by me; 3, 4, 6–8 read and not disputed). What survives is negative and
useful: (i) a 4.9 M-param sequence model cloned from a teacher that succeeds
4.5 % of the time cannot beat a straight-line reference; (ii) the **shipped
navigator succeeds on only 4.5 % (strict) / 65 % (band-entry) of
procedurally generated held-out geometry** — the product's generalization
gap, measured on real MJCF variants for the first time; (iii) the
teacher's own "blocked" opinion and the oracle's disagree almost entirely
(637 oracle vs 892 navigator block edges, ~1 % mutual coverage) — the
navigator's recovery ladder calls itself blocked for reasons the geometry
does not show.

## What this means for the program

Model A cannot be cloned from this teacher on this substrate; the corrective
design (Sol's MA-2: a teacher/causality probe before any training — teacher
ceiling, oracle isolation, exact applied-action labels, real executive
admission, trace replay) is the right next step and I concur with it. The
report's R1 stands as architecture, not as evidence.

## What it does NOT prove
No physics, audio, ASR, Orin, or Go2; scripted cues; one city family.

## Erratum (21:2x EDT, from NAV-GEN-1's verification panel)

The teacher's "held-out SR 0.045" that this verdict cites is **not a
measurement of navigation success**: the A1 gold requires ≥ 5 stopped frames
inside the band (`ORACLE_SETTLE_FRAMES`, teacher.py:291), but the closed loop
breaks one frame after the navigator's own `done()` (`closed_loop_core.py:
347-349, 357-375`) — 133/133 plain held episodes with a declared arrival ended
at +1 frame and none is an oracle success; the 11 plain "successes" are
episodes a stop/owner cue froze inside the band. Plain-episode band entry is
0.775; NAV-GEN-1's single-frame predicate on MA-1's own frames gives 0.750.
What stands: C and T were scored under the same artefact, so C-vs-T remains
like-for-like, and the informative row was always band entry (C 0.087 vs
T 0.652 = 0.133×) — the refutation of H-MA1a is unchanged; the "4.5 %
teacher" framing is withdrawn. See `nav-gen-attribution-1/VERDICT.md` §5.1.
