# literature/ — verified sweep for the living-behavior-model wave (2026-08-28/29)

- `LITERATURE_REVIEW.md` — the synthesized, verdict-tagged review (§1–§9 first
  sweep, §10 gap sweep). Tags: [S] supported, [P] partially supported with
  the verifier's correction, [n/v] finder-only. Read this first.
- `sweep.json` — first sweep, 10 topics: every finding (claim, URL, numbers,
  relevance, load-bearing flag), the per-topic adversarial verification of
  the load-bearing claims (SUPPORTED / PARTIALLY_SUPPORTED / UNSUPPORTED with
  the quote and correction), the trainable-model options, and the
  completeness critic's gaps / strongest designs / risks / contradictions.
- `sweep-gaps.json` — second sweep on the critic's gaps, 7 of 9 topics with
  structured returns (4 verified); the two killed finders (owner-loss
  detection on a LiDAR quadruped; neckless gaze legibility) left only their
  notes.
- `notes/<topic>.md` (10) and `notes/gap-<topic>.md` (9) — each finder's full
  working note: every source fetched, what it says, numbers, quotes, and a
  "what this means for Parcel" section. ≈ 600 KB total.

Provenance: 21 + 16 agents (WebSearch → WebFetch every cited page → an
independent verifier re-fetching each load-bearing claim), run 17:33–18:27
on 2026-08-28; the second sweep was cut short by the account's monthly spend
limit. Nothing here is Parcel evidence; numbers are as printed by their
sources. A second human-side read (parcel-6c, 18:18) found no claim known
wrong and flagged the ten 2026-dated arXiv ids as beyond that reader's
knowledge.
