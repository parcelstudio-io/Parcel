# MA-1 amendments — POST-START (15:53 08-29, from a three-lens code-verified design review; the executor had begun the teacher). Report every amended row beside the original; no frozen data regenerated except as A2 says.

## A1 — gold comes from the truth oracle, not the teacher; label-copy channels are masked (BLOCKING)
Closed-loop gold is defined from `headless_city.py`'s truth: `nav.arrived` =
truth pose inside the goal region (the harness's own region predicate) AND
stopped ≥ 5 frames; `nav.blocked` = truth minimum clearance below the
reactive-safety stop band for ≥ 5 frames; `plan.revised/queued/resumed`
anchored to the cue frame; `nav.failed` on the step limit. Publish the EXACT
channel list available at closed-loop eval; any channel that is a copy of a
label (plan step kind, blocked class, replan count) must be A's OWN state
(computed from its past outputs/frames) or dropped — never a teacher-side
value. Report A′n's narration F1 as the floor; the clause "C − A′n ≥ 0.10 on
narration F1" or the finding is "rules suffice for narration".

## A2 — held-out GEOMETRY, not held-out labels (BLOCKING)
`apply_placement_overrides` moves semantic specs only ("geometry in MuJoCo
stays put"), so jittered landmarks/added "obstacles" are invisible to the
free-space channels and collisions. Generate real MJCF variants with
`evals/nav_instruct/scene_gen.build_scene(seed, scratch_dir)` on MA-1's own
seed range (disjoint from the val_unseen manifests' seeds; never the named
held-out scene) and load them with `HeadlessCityWorld(scene=path)`; split by
geometry seed (train/dev/held-out disjoint); hash the layout manifest and the
frozen checkpoint into results.json. Add the criterion: on held-out layouts
where the STRAIGHT-TO-GOAL-BEARING reference fails, C beats it by ≥ 0.10
success; report the fraction of held-out layouts where straight-line
succeeds and declare the split uninformative if > 0.7. If scene generation
cannot be added mid-run, rename the claim to "held-out start/goal placements
on one map" and cap the verdict at PARTIAL.

## A3 — time-to-switch is anchored and the queue check is task-stack exact
Anchor the switch to the DETECTED cue frame; measure heading toward the new
goal from the truth pose; mask/delay the goal channel for N = 5 frames after
the cue so a bearing-follower cannot score from the input alone. For queue
cues require truth-oracle arrival at goal 2 followed by arrival at goal 1,
with `plan.queued` / `plan.resumed` each within 1.0 s of the corresponding
oracle event. The "sequence model earns its place" clause is read on (a)
and (c), and on (b) only under the mask.

## A4 — event counting, reference rows, one dev metric (BM-1 A4 verbatim)
An emission = rising edge of a token run; at most one TP per gold event in
the CAUSAL window [t_gold, t_gold + 1.0 s]; extra in-window emissions are FP;
false-event rate = FP / emitted events; report ALWAYS-NONE and
EVENT-EVERY-FRAME rows; ≥ 200 held-out events per class (generate more
held-out seeds if short). Dev-selection metric = harmonic mean of dev
closed-loop success and dev narration F1; dev layout count fixed; the
checkpoint hash is frozen before any held-out run. Latency rows record
load/co-tenants (BM-1 A6).

## A5 — the last minute, explicitly
Add per-class last-60-s channels with age bins (time since: last blocked,
last replan, last cmd/steer, last sound, owner last seen; counts over 60 s:
replans, blocks) beside the K = 6 event tokens. Ablation arms C-h0 (no
history channels) and C-h60; "the last minute earns its place" = C-h60 beats
C-h0 by ≥ 0.10 on time-to-switch success or blocked-recovery success on the
held-out slice, else record "window suffices".

## A6 — proposals vs witnessed narration
Split the second head: witnessed `narr.*` (as designed) and proposal
`prop.*` (`prop.replan`, `prop.resume_queued`, `prop.abandon`,
`prop.clarify`); gold for `prop.*` = the teacher's next decision at t + Δ;
score proposals raw and as "accepted by the executive" precision (DMC-1's
raw-vs-admitted split); name the realization doors (`request_interrupt` /
`replace` / re-issue).

## A7 — witness table and vocabulary partition
Publish token → headless witness → live-runtime receipt equivalent.
Product-backed: `nav.arrived ↔ mission_arrived`, `nav.failed ↔
mission_ended`, `nav.replan ↔ reroute`, `nav.blocked ↔ mission_blocked`
(8 s debounce). Research-only: `nav.start`, `nav.progress` (INTERNAL-ONLY —
never a narration claim; it is the whisperer's NEVER band), `plan.*`,
`attend.*` (authored gold, bounded by the awareness-sweep yaw limits).
Report H-MA1c per partition. The teacher's "receipts" are derived from
`mission.status` / `command.note` / mission-block notes; if executive
receipts are wanted, host a `TaskExecutive` in the harness and say so. Run
≥ 20 scripted episodes through both the headless teacher and NAV-INT-1's
live path and show the event sequences agree under one shared schema
(event, task_id, revision, since_s).

## A8 — safety row
Add `cmd:stop` and `owner_speaking` cues in ≥ 10 % of episodes. Score RAW
non-idle-after-stop, RAW twist into an occupied sector, RAW twist while
owner speaking (before any filter) and post-filter rates (must be 0);
raw ≤ 1 % is the bar, else the finding is "A runs only behind the
deterministic filter"; stop is a held state until a new directive.

## A9 — cue-duplex, stated
A v0 is CUE-duplex (router cue tokens at 10 Hz; no audio/ASR/jitter); DS-1
(20260828) is the speech-duplex follow-up. Add ASR-timing rows: cues at
end-of-utterance only, and partial cue at the first content word with 10 %
retractions — report time-to-switch and false-switch rate.

## A10 — no authority
Terminal tokens (`nav.arrived`, `nav.failed`) are PREDICTIONS scored against
gold, never receipts; rename the false-event rate "predicted terminal with
no backing receipt"; add to "What it does NOT prove": "A's narration tokens
carry no authority; no consumer may narrate a terminal from them."
