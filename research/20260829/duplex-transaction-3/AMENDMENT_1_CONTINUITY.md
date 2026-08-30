# DMC-3 amendment 1 — silent-consumption continuity

**Status:** frozen before amended implementation  
**Date:** 2026-08-29  
**Scope:** D3-H2 authenticated missing-success handling only; H4 remains
`PARTIAL_RED`

## Preserved pre-amendment evidence

The original retained evidence is not overwritten:

- `run_a.json` SHA-256:
  `27e5228f35037c8bb9342e3159791b8e2eba963e8a0cdd80c1b74539305ffaa0`
- `run_b.json` SHA-256: identical.
- original normalized trace SHA-256:
  `d28625a78105f88703db7a8bd87dd4a72871ab7d92556e547101ea1882a94389`
- original trace-chain root:
  `081fa416596366eb68bdd58c411e873b384c8502855fb15064e6c015b9b5759d`
- `verification.json` SHA-256:
  `dab4041c6fb90b2f6738e682540add0fbb4c019451c8a2e0c8a2233b32fd4908`

Those artifacts remain useful evidence for the originally frozen gates, but
their missing-success consumer behavior is superseded by this amendment.

## Discovered failure

The executive correctly converted a success report without its required fact
into an authenticated `failed` event with detail
`unverified_success_claim`. The consumer returned the identical state and no
frame. Because the event was authenticated, ordered, and authoritative, not
committing its sequence left the consumer behind. The next valid event then
failed as `event_sequence_gap`, permanently stalling narration for that source
epoch.

One unit test obscured this liveness problem by discarding the preceding
`accepted` and `started` events, then testing sequence 3 against a fresh
sequence-0 consumer.

## Amended contract

For exactly an authenticated, fresh, contiguous, lineage-valid event with:

```text
status = failed
detail_code = unverified_success_claim
```

the consumer must:

1. return `accepted = true`;
2. advance `last_event_sequence`, retain `event_id`, and transition the exact
   task cursor to `failed`;
3. return `frame = null`;
4. return reason `unverified_success_claim_consumed_silently`; and
5. reject exact replay as `event_already_consumed` without another state
   change or frame.

This is **consume without narration**, not rejection and not a success claim.
It preserves the original H2 requirement of zero narration frames for the bad
success input while keeping the ordered stream live.

Authentication failure, unknown/stale lineage, duplicate, sequence regression
or gap, source-epoch mismatch, future/expired event, and old/new speech
generation continue to return the identical state and no frame.

## Amended gate

Every missing-success H2 trial must additionally prove:

- the converted failure is consumed silently exactly once;
- exact replay is rejected as already consumed; and
- the immediately following valid distinct-task event is accepted at the next
  contiguous sequence and produces its normal deterministic frame.

The independent verifier must recompute this continuity oracle without
invoking Parcel's bridge or consumer. Both full amended runs must have identical
normalized trace and chain-root digests.

## Evidence boundary

This amendment changes no motion, executive, runtime, provider, or hardware
authority. D3-H4 stays `PARTIAL_RED`; overall promotion and physical autonomous
motion remain **NO-GO**.
