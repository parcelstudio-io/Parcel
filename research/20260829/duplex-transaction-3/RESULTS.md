# DMC-3 results

> **Pre-amendment evidence.** The files and hashes below are intentionally
> retained, but their missing-success reducer behavior did not prove ordered
> stream continuity. See `AMENDMENT_1_CONTINUITY.md` and
> `RESULTS_AMENDMENT_1.md` for the superseding result.

## Frozen gates

| Gate | Population | Result | Evidence |
|---|---:|---|---|
| D3-H1 accepted-transition completeness | 256 tasks / 1,024 lifecycle events | PASS twice | Exact `accepted → started → progress → succeeded`; all 256 success events retained the frozen fact and all 1,024 events produced one authenticated frame |
| D3-H2 corruption silence | 256 fresh corruptions | PASS twice | 16/16 classes covered 16 times; zero false `succeeded` events and zero tested narration frames |
| D3-H3 interruption stack | 128 trials / 1,280 events | PASS twice | 1,280 accepted-once events, 1,280 replay rejections, 128 old-generation rejections; zero arrival-only keys claims |
| D3-H4 runtime composition | not completed | PARTIAL/RED | Silent authoritative `TaskExecutive.tick` mutations have no typed transition record; snapshot inference is forbidden |
| Promotion | H1-H4 twice | FAIL / NO PROMOTION | H4 is not green |

Every H2 class has exactly 16 retained trials. The six stale/unknown result
families produced 96 rejected executive reports and no event. Sixteen missing
success-fact claims became honest `failed` audit events and licensed no frame.
The remaining event-layer corruptions were rejected for authentication,
duplicate, sequence, epoch, freshness, or speech-generation mismatch.

## Determinism and verifier

- Run A normalized trace SHA-256:
  `d28625a78105f88703db7a8bd87dd4a72871ab7d92556e547101ea1882a94389`
- Run B normalized trace SHA-256: identical.
- Run A/B trace-chain root:
  `081fa416596366eb68bdd58c411e873b384c8502855fb15064e6c015b9b5759d`
- Independent verification SHA-256:
  `9de33df19f5fb4305a0fb9f9c0491e7b80f551c6ba8f14af1735f7ce165a6ded`
- Focused guarded contract/oracle tests: `9 passed in 0.27s`; the final strict
  decode, sequence-gap, tamper, and verifier-import nodes were rerun after the
  last edits: `4 passed in 0.24s`.
- Provider/API calls: `0`; provider cost: `$0.00`.

The two retained result files are byte-identical, not merely normalized-trace
identical. Their file SHA-256 is
`27e5228f35037c8bb9342e3159791b8e2eba963e8a0cdd80c1b74539305ffaa0`.

## Artifact inventory

| Artifact | SHA-256 |
|---|---|
| `DESIGN.md` | `442138c19b044196ae7fc0e0fe76b4c2bf46254d68121a188c5659f0c1e20543` |
| `manifest.json` | `17fde93a7b3820135047d3336a11365e58da3307af0d2572a15fd920c410eab3` |
| `run.py` | `6f30f0fb866b93c094e0af6ebdef015b6722158dbedceb4d153f16a2154229cd` |
| `verify_results.py` | `123a3d59ebfb235479802bd85349dde369bffc2123329c35929d17b734efab59` |
| `run_a.json` | `27e5228f35037c8bb9342e3159791b8e2eba963e8a0cdd80c1b74539305ffaa0` |
| `run_b.json` | `27e5228f35037c8bb9342e3159791b8e2eba963e8a0cdd80c1b74539305ffaa0` |
| `verification.json` | `dab4041c6fb90b2f6738e682540add0fbb4c019451c8a2e0c8a2233b32fd4908` |

These results establish only deterministic local authority and replay
behavior. They do not establish language quality, audio behavior, perception,
navigation, locomotion, real-time performance, or physical safety.
