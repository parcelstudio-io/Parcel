# DMC-3 amendment 1 results

## Outcome

The ordered-stream continuity defect is fixed in the pure consumer and the
amended H1-H3 corpus passes twice. H4 remains `PARTIAL_RED`, so overall
promotion remains false.

| Gate | Population | Amended result |
|---|---:|---|
| D3-H1 | 256 tasks / 1,024 events per run | PASS twice |
| D3-H2 | 256 fresh corruptions per run; 16 classes × 16 | PASS twice |
| D3-H2 continuity amendment | 16 missing-success trials per run | 16 silently consumed failures, 16 duplicate rejections, and 16 immediately following valid-task frames |
| D3-H3 | 128 trials / 1,280 events per run | PASS twice |
| D3-H4 | no runtime composition | PARTIAL/RED |
| Promotion | H1-H4 twice | FAIL / NO PROMOTION |

For H2, all 256 tested corruptions licensed zero narration frames and minted
zero false `succeeded` events. The 16 authenticated executive-converted
failures advanced sequence and task phase without a frame. Their exact replays
were rejected as `event_already_consumed`. Each next valid distinct-task event
at sequence 4 was accepted with its ordinary deterministic frame. The other
240 corruptions left consumer state byte-for-byte equivalent.

H3 again accepted 1,280 events once, rejected 1,280 exact replays, rejected 128
old-generation events after generation advance, and produced zero arrival-only
keys claims.

## Determinism

- Run A/B normalized trace SHA-256:
  `efba1973cbce534f61b0c54ee72be790ff951ab88fb8e78e2c7c8867fb3b1bee`
- Run A/B trace-chain root:
  `a0ce9f01dd2e0f83c29fadfc42240d4a127939c696cb889f706398397117d766`
- Independent verification payload SHA-256:
  `4793839852d696c726c9bc2dbe97a01ef457e5d5a2ea481b8ffb5f20512061e6`
- Run A/B files are byte-identical, SHA-256:
  `24f5bddc37b0794cec091a27f9a038c52f18eeb659e4e9031fce15e7b497201c`
- `verification_amendment1.json` file SHA-256:
  `c464cce5c3eab659c0f93d39b6471c6c866e40811ce1af291f6168b0ddd2e82a`

The stdlib-only verifier imports no bridge, executive, authenticator, consumer,
or other Parcel production code. It independently checks the silent state
advance, duplicate rejection, contiguous follow-up identity/sequence/frame,
and state neutrality of every other corruption.

## Guarded tests

- Amendment failure-path node: `1 passed in 0.20s`.
- Full DMC authority regression (`test_execution_narrative_bridge`, DMC-3
  runner/verifier, production executive, and DMC-2): `22 passed in 0.47s`.
- Python compilation: PASS.
- Provider/API calls: `0`; provider cost: `$0.00`.

## Artifact hashes

| Artifact | SHA-256 |
|---|---|
| `AMENDMENT_1_CONTINUITY.md` | `9cfd4f595b5202dd78aa7a8f8dda2ad6709fa19d8b25ee79ef2f4120647432c8` |
| `manifest.json` | `17fde93a7b3820135047d3336a11365e58da3307af0d2572a15fd920c410eab3` |
| `run.py` | `e9cb954d56c338c0b4ee24350ff64f2f2d44e7ef2eeac2f9d4d962e2e1c94817` |
| `verify_results.py` | `2da817c2a70a91e737d30919d8b68740a046cdf0e5db9097cd211a9510391e86` |
| `run_amendment1_a.json` | `24f5bddc37b0794cec091a27f9a038c52f18eeb659e4e9031fce15e7b497201c` |
| `run_amendment1_b.json` | `24f5bddc37b0794cec091a27f9a038c52f18eeb659e4e9031fce15e7b497201c` |
| `verification_amendment1.json` | `c464cce5c3eab659c0f93d39b6471c6c866e40811ce1af291f6168b0ddd2e82a` |

The original `run_a.json`, `run_b.json`, and `verification.json` remain present
at their pre-amendment hashes recorded in `AMENDMENT_1_CONTINUITY.md`.
