# Parcel backlog

The durable home for work that is **not done** — kept outside any one sprint so
it survives when `scrum/<date>/` folders go quiet.

| File | Holds |
|---|---|
| [UNVERIFIED.md](UNVERIFIED.md) | Things the code claims but nobody has confirmed. The register that keeps "implemented" from being read as "works". |
| [BLOCKED.md](BLOCKED.md) | Ready work waiting on something external — an install, a package, hardware in the post. |
| [NEXT.md](NEXT.md) | Unblocked work, ranked. What to pick up when there is time. |

## Why UNVERIFIED exists

Parcel's recurring failure mode is not bad code; it is
*well-tested code nobody connected to reality*. The 2026 redesign found a
1,691-line planner unreachable from the product, a voice stack that never
produced audio, and a brain surface computed but never read — each with a
green test suite. The same shape recurred twice on 2026-08-04 alone: a
production registry built with an empty pose catalog (every safe-pose plan
silently rejected), and audio config keys mis-indented into the wrong YAML
section (device selection and endpointing settings silently ignored for a
whole sprint). Both had passing tests.

A passing test proves the code does what the test says. It does not prove the
code runs in production, that its inputs are real, or that anyone has ever
looked at the output. UNVERIFIED tracks that second question.

## Conventions

Every item carries:

- **Claim** — what someone might reasonably assume works.
- **Reality** — what has actually been exercised.
- **To verify** — the concrete command, measurement, or observation that
  closes it. If you cannot write this line, the item is too vague.
- **Risk** — what breaks, or what wrong belief propagates, while it stands.

Close an item by *doing the verification*, then delete it and record the
result where it belongs (a handoff note, a ledger row, or a doc). Do not close
an item by arguing it is probably fine.

Add an item whenever a handoff says "not verified", whenever you ship behind
a config flag you have not exercised, and whenever a test uses a stub in place
of a real dependency.

## Related

- [../docs/CURRENT_STATUS.md](../docs/CURRENT_STATUS.md) — the capability
  matrix: what is implemented vs wired vs verified *right now*. Read it first;
  this backlog is the work queue that drains it.
- [../docs/RESEARCH_2026_ROADMAPS.md](../docs/RESEARCH_2026_ROADMAPS.md) —
  where the larger roadmap items come from.
- `../scrum/<date>/README.md` — per-sprint handoffs, the usual source of new
  UNVERIFIED entries.
