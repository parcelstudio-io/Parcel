# Parcel backlog

The durable home for work that is **not done** — kept outside any one sprint so
it survives when `scrum/<date>/task_<n>/` folders go quiet.

| File | Holds |
|---|---|
| [UNVERIFIED.md](UNVERIFIED.md) | Things the code claims but nobody has confirmed. The register that keeps "implemented" from being read as "works". |
| [BLOCKED.md](BLOCKED.md) | Decisions/promotion/evidence waiting on an explicit owner, hardware, account, install, or external action; cards may also name internal predecessors. |
| [NEXT.md](NEXT.md) | Repository work that is ready now or sequenced only behind another `N` card, prioritized by the delivery map. |

The prioritized delivery/dependency map at the top of `NEXT.md` is the current front
door; its `B` rows are references to external gates, not duplicate task definitions.
Older detailed cards remain below it for traceability, but a card marked landed,
superseded, or moved is not active work.

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

## Task-card conventions

New `NEXT.md` cards use a stable unique ID and name:

- **Opened / priority** — when it entered the durable queue and its HLD phase.
- **Depends on** — other backlog IDs or landed contracts, never an implicit
  sequencing assumption.
- **Build** — the smallest product slice with one authority owner.
- **Tests / refutation** — executable success and seeded failure cases.
- **Exit** — the evidence that removes the card from the active board.
- **Does not prove** — the capability readers must not infer from a green card.

`NEXT.md` contains repository work that can begin without a new owner decision,
install, account, or physical device. If only the software half is unblocked, split
the physical promotion into `BLOCKED.md`. Landed and superseded cards leave the
active board; their sprint/status records remain historical evidence.

## Related

- [../docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md](../docs/CONVERSATIONAL_AUTONOMY_HIGH_LEVEL_DESIGN.md)
  — the 2026-08-22 code-grounded current/target architecture and the source for
  the HLD delivery map in `NEXT.md`.
- [../docs/archive/LEGACY_IMPLEMENTATION_STATUS_2026-08-04_TO_09.md](../docs/archive/LEGACY_IMPLEMENTATION_STATUS_2026-08-04_TO_09.md)
  — the retired August 4-9 capability matrix; the handbook is current authority.
- [../docs/RESEARCH_2026_ROADMAPS.md](../docs/RESEARCH_2026_ROADMAPS.md) —
  where the larger roadmap items come from.
- `../scrum/<date>/task_<n>/README.md` — per-sprint handoffs, the usual source of new
  UNVERIFIED entries.
