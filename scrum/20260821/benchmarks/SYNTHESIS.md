# Where Parcel actually stands vs. benchmarks · Fable · 2026-08-21

Four reference sweeps (instruction/tool-calling, embodied navigation,
conversational quality, spoken-assistant & latency) in this folder, each
asked to be ruthless about comparability. They converge.

## The governing fact

**No Parcel number today survives contact with a benchmark denominator.**
Parcel has never measured task diversity and trial count at the same time:

| Artifact | Distinct tasks | Trials each |
|---|---|---|
| voice corpus (live_run_1 / replay_run_1) | 52 | **1** |
| chat-API bench | **4** cells | 6 |
| E1 recorded pack | 6 | 1 |
| spoken e-stop | **1** phrasing | 7 |

Every benchmark requires both axes. Binomial reality (Clopper-Pearson 95%):

* tool+args 6/6 → **[54%, 100%]** — rules out worse than 54%, nothing more
* nav-direct 5/5 → **[48%, 100%]**
* arrival-relation 12/12 → [74%, 100%] · self-consistency 15/15 → [78%, 100%]
  (these two are genuinely strong for their n)
* fabricated call 5/6 → [36%, 99.6%] · follow-up asked 0/6 → [0%, 46%]
* **e-stop 7/7 → rule of three: the 95% upper bound on failure rate is ~43%.**
  We cannot presently claim the spoken e-stop is reliable. It is the single
  most important number in the system and it is n=7 on one phrasing.

## Dimension by dimension

**Instruction following / tool use.** IFEval and IFBench are NOT comparable
(they measure surface-form compliance of free text; we emit tool calls).
**BFCL is the right reference and is directly relevant**: its AST-match rule
is exactly our "correct tool+args", and its *irrelevance detection* axis is
exactly our fabrication weakness (5/6 junk `navigate_to` when no suitable
tool existed). BFCL v4 weights hallucination at 10% of overall; frontier
overall sits ~75% (aggregator-sourced, treat as an anchor).
**The IFEval→IFBench lesson is the one that should worry us**: models above
80% on IFEval drop below 50% on novel constraints. Our 52-query corpus has
gold labels *we wrote*, against categories *we invented* — structurally an
IFEval. Expect a large drop on held-out phrasings authored by someone else.

**Navigation.** Zero comparability, and not because of sample size: our
navigation is a *different task*. ObjectNav/HM3D-OVON/GOAT/VLN-CE score goal
**discovery under partial observation in held-out scenes**; we do goal
**resolution against a hand-authored semantic map in one known scene**. We
designed the benchmarked problem away — which is precisely the gap the owner
has now chosen to close (perception generalization). The report is blunt:
the cheapest honest transformation "would be building a different robot."
**The one place we are not obviously behind is social navigation** — Habitat
3.0 / Social-HM3D metric definitions (PSC, H-Coll, personal-space
compliance) map onto our person-yield behavior. That is the only
"partially comparable" worth acting on in the whole navigation family, and
it must be reported with our own denominators, never placed beside Falcon's
numbers.

**Conversation.** Arena/Arena-Hard/MT-Bench: not comparable (free-form text,
aesthetic judges, saturated). The two useful anchors are **Audio
MultiChallenge** (the closest public leaderboard; its self-coherence
category is the ancestor of our consistency measure) and **τ-Voice** (the
closest published analogue to our whole propose/dispose architecture).
**The strategically important finding is about our substrate, not our code:**
on Voice Showdown, GPT Realtime sits 5th–7th — beaten by a 2024-vintage
GPT-4o Audio — and we run the *mini* 2.1 variant, below even that. We are
not being let down by an unusual model; we are running near the bottom of
the voice frontier by choice (cost). Some of what we have been fixing as
"defects" is substrate ceiling.

**Voice / latency.** Of eleven families surveyed, zero directly comparable.
Adopt **Full-Duplex-Bench v3's latency definitions wholesale** — and note
our 0.78 s is a single-turn, no-chained-call figure and is NOT comparable to
FDB-v3's task-completion-inclusive 4–10 s numbers; we must stop implying
otherwise. Cascaded and commercial full-duplex systems sit in the ~1 s band,
which is where we are. **SLURP/MAC-SLU is the cheapest path to a
benchmark-shaped number**: our 15 categories ≈ intents, our tool arguments ≈
slots, our PASS ≈ joint accuracy.

## What to run, cheapest first

1. **pass^k on the existing corpus** (k≥3) against the current build — turns
   every headline number from anecdote into an operating point. ~$3.
2. **A BFCL-style irrelevance set**: N queries needing tools we do not have;
   score abstention vs fabrication. Directly comparable, cheap, and targets
   our worst measured behavior.
3. **A held-out phrasing set authored adversarially** (not by the people who
   wrote the gold labels) — converts our IFEval into something IFBench-like.
4. **SLURP-style joint intent+slot accuracy** over the corpus.
5. **Social-HM3D metric definitions** applied to our own yield episodes.
6. **FDB-v3 latency definitions** replacing our current turn-latency claim.

None of these require new capability work; all six are measurement discipline
over artifacts we already have.

## Provenance caveat

Several 2026 leaderboard figures came from third-party aggregators that
republish vendor-claimed numbers from uninspectable harnesses; the reports
mark these ⚠️ and so do we. Primary-source numbers (arXiv, official repos,
Gorilla/Sierra) are marked ✅ in the underlying reports.
