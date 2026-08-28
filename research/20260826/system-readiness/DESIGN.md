# System-readiness remeasurement — preregistration

Date: 2026-08-26
Owner: Sol (`/root`)
Evidence class: desktop GPU, deterministic headless simulation, and offline
replay only. No robot, ROS graph, acoustic room, Unitree transport, or physical
motion is exercised.

## Question

Does the current checkout, including the new `si-companion-v4` continuing-friend
contract and capability-grounded action policy, preserve the known conversation
contract while exposing the same navigation-generalization blockers reported on
2026-08-24? Which evidence can legitimately affect Go2 mount readiness?

## Frozen-before-run hypotheses and criteria

### SR-H1 — current local conversation boundary

Run the frozen 10-case `conversation_quality_v1` suite with the repository's
admitted Gemma 4 26B-A4B Q4 model and pinned CUDA llama.cpp runtime on a private
loopback port. This suite renders the local `PromptLibrary` system/action
prompt; it does **not** render or evaluate the separately versioned hosted
Realtime `si-companion-v4` instruction.

Pass criteria:

- provider parse success: 10/10;
- structured-safety category: 10/10;
- machine case accuracy: at least the prior admitted Gemma result (6/10);
- no result is described as human conversational quality;
- latency is recorded as this RTX 5000 Ada desktop profile, never as AGX Orin
  latency.

The local structured prompt update is rejected for product use if parse or
structured safety regresses. A machine-score tie is only non-regression, not
proof that the separate Realtime relationship behavior improved.

### SR-H2 — historical hosted conversation evidence

Replay and re-score all 25 captured `realtime_convo_v1` threads offline against
their frozen SI-v1 provenance and the checked-in unblinded review.

Pass criteria:

- all fixtures replay and their prompt provenance verifies;
- reviewer coverage is complete;
- the semantic headline remains explicitly separated from the new SI-v4 local
  run and from blinded human review.

This is a provenance/replay check, not an A/B test of v4.

### SR-H3 — current navigation generalization

Re-run the exact 2026-08-24 NAV_INSTRUCT v4 recipe (`seed=20260804`,
`scaled-path-v1`, `max_steps=200`) as a 25-episode minival and 125-episode full
matrix, always `--no-ledger`, writing only under this research directory. Also
run the frozen walk-with-me headless pack and companion-follow/yield benches.

Minimum mount-relevant criteria (all required):

- NAV_INSTRUCT full success rate at least 0.80 and SPL at least 0.60;
- zero false arrivals and zero collisions;
- every instruction family and tier has nonzero success;
- walk-with-me headless success at least 8/10;
- follow/yield dynamic safety has zero collision or safety-veto violations.

These thresholds are prospective readiness floors, not prior baselines. A red
result does not authorize tuning after seeing the matrix; it becomes a
diagnostic for the simulator-learning backlog.

### SR-H4 — boundary and evaluator integrity

Run the brain-v1 and embodied-plan-v1 boundaries, navigation mutation panel,
metamorphic navigation tests, voice-to-navigation tests, and relevant prompt,
freeze, package-parity, and eval-manifest checks.

Pass criteria:

- all deterministic contract suites pass their frozen expectations;
- the mutation panel kills every registered mutant;
- metamorphic tests pass under the nightly setting;
- no tracked evaluation ledger is modified;
- no simulator-only or fixture-only pass is reported as physical evidence.

## Confounds and invalid claims

- The local conversation runner uses the JSON conversation path, whereas the
  captured hosted corpus uses the Realtime lane. Scores are not directly
  comparable.
- Prompt cases use machine heuristics; warmth, naturalness, attachment, and
  cultural fit still require blinded human review.
- Headless city integration uses deterministic kinematics and simulator truth
  only in the evaluator. It does not test Go2 dynamics, actuator delay,
  vibration, sensor extrinsics, stairs contact, stopping distance, or wireless
  loss.
- Re-running a fixed corpus measures regression, not broad generalization.
- The Claude artifact URL returned a Claude “Page not found” response on
  2026-08-26; no claim about unseen artifact contents is permitted.

## Operational controls

- Local model port: `127.0.0.1:18081`; no API key and no provider spend.
- Do not contact the live simulator socket or port 8765.
- Every pytest command uses the host guard with `TMPDIR` unset.
- Navigation runs use `--no-ledger`; pre/post SHA-256 hashes of the tracked
  navigation ledger and frozen inputs are recorded.
- Raw outputs, command log, environment summary, and computed report live under
  `research/20260826/system-readiness/`.
