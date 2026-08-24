# H2 — local cognition on the GPU · VERDICT (Fable) · 2026-08-24 (closing per RTP-1 C4)

Run state at close: the executor died on a transient 529 while starting a
daemon for one last re-measure, AFTER writing `results/latency_rerun.json`
(04:44Z, quiet host — load ≈ 2, no judges, `nvidia-smi` snapshots embedded)
and a complete RESULTS.md. The integrator stopped the `:8081`/`:8082` model
servers and the perception daemon at 05:0xZ. No further runs; closed from
evidence on disk per the review's stop policy.

| row | criterion | contended (RESULTS) | quiet re-run (`latency_rerun.json`) | disposition |
|---|---|---|---|---|
| G1 | 8B tick ≤ 300/600 ms p50/p95 idle | 602/846 | **604/756** (26B: 453/496) | **REFUTED** — even uncontended, a full digest→decision tick is ~2× the bar; TTFT is fine (66/71 ms), the decision tokens are not |
| G2 | ≤ 450/900 under perception + 26B gen | 1054/1453 | **978/1240** (plan call p50 15.8 s contended) | **REFUTED** |
| G3 | perception p95 ≤ 150 ms during ticks | 181 | **127** (B) · 143 (C); alone 98 | CONFIRMED on the quiet host |
| G4 | VRAM ≤ 28 GB | 26.2 GB | — | CONFIRMED |
| G5 | agreement ≥ 0.80 | 8B 0.400 · 26B 0.417 | — | **REFUTED** |
| G6 | false-remark ≤ 10 % | 0 % (degenerate) | — | CONFIRMED (weak) |
| G7 | talker TTFT ≤ 150 / clause ≤ 600 ms | 126/243 | TTFT 66–71 ms | CONFIRMED |
| G8 | pairwise vs hosted | 8B −0.36 · 26B −0.61 | — | reported |

**Overall: the hypothesis is REFUTED, decisively and usefully.** An
LLM-as-monologue-tick fails on both latency (G1/G2 quiet-host) and judgment
(G5), for both the 8B and the 26B. What survives: the 8B as a *phrasing*
seat (G7) and the VRAM/co-residency table (G4, G3). **Topology decision
(final, per RTP-1 C4): deterministic drives own the tick; an LLM phrases;
the hosted model converses and compiles plans when connected.** No further
model comparisons; Orin sizing moves to the box-day co-residency soak.
Product path: `brain/monologue.py` has no product caller (harness-only);
`WorldDigestV1` is retained as the digest contract for the drives' logging.
