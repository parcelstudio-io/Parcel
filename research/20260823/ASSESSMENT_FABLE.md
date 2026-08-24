# Where the living-dog prototype actually stands · assessment (Fable) · 2026-08-23

Reviewed tree: `0ad83a0` on `origin/main` plus the in-flight DEC-FS-1
working-tree overlay (feature-package moves; no behavior change). Grounded
by seven independent read-only surveys of the tree (conversation/cost,
navigation+SLAM+physical path, perception, memory/learning, lifelike
behavior, portability seams, design corpus), the owner's real spend ledger,
the provider's pricing page, and this host's inventory. Every number below
has a file or a measurement behind it; where a number is an estimate it says
so. This is also the answer to Codex's PROTO-0 review request
(`scrum/20260823/task_20/README.md`) — §5 addresses its nine questions.

## 1. The one-paragraph answer

We have a **large, well-guarded, simulation-first supervisory-autonomy
codebase** (≈142k product lines, ~9,900 desktop tests green) whose safety
core is real and whose conversation plumbing is real — and **almost none of
the "living dog" behaviors exist yet as a closed loop**: nothing schedules
learning, nothing generates goals, nothing emits a continuous body intent,
no localizer exists, no photon has been perceived, and the Go2 backend
refuses all motion by design until a native sole-writer gateway exists. The
economics of the current default (an always-open hosted ear) forbid the
product outright ($200–$3,900/month) and the cost instrument under-reports.
The good news is symmetrical: the missing pieces are mostly *scheduling,
contracts, and one native process* on top of mechanisms that already exist
and are tested — which is why the research program is designed to close
them off-robot in days, not months.

## 2. Readiness, corrected

Score = "what a demanding reviewer would credit today". Sim = MuJoCo/headless
desktop; Go2 = after box-day with the hardware the owner ordered (none on
hand today); "custom" = a future body through the same seams.

| Capability | Sim | Go2 | Custom | Evidence ceiling (what the number rests on) |
|---|---|---|---|---|
| Conversation mechanics | 6 | 2 | 2 | Two lanes, four-yes arming, spend ledger, idle hang-up, duplex shadow; barge-in cancel p95 740 ms vs 450 bar (declared miss); through-air campaign never run; XVF3800 gateway exists and passes tests. |
| Interesting conversation | 3 | 1–2 | 1–2 | Best machine accuracy 0.60/10 cases, `human_review_completed: false` everywhere; live personal-convo 3/13; 25-thread hosted corpus unreviewed; autorater framework has zero recorded results. |
| Continuous listening at ≤$200/mo | 2 | 2 | 2 | Local lane already listens wake-free at $0 but answers everything; hosted ear at 600 tokens/min ⇒ ~$130/mo in silence on mini, $644+/mo on full; no local VAD before the hosted socket; shipped $25 guard ≈ 28 min/day. |
| Indoor navigation | 6 | 1 | 1 | NAV_INSTRUCT v4 SR 0.24–0.28 (25 eps, 0 collisions; failures dominated by planning); follow bench 7/9; reactive gate 0.65 m floor derived from authority; Go2 backend observe-only. |
| Outdoor navigation | 2 | 0–1 | 0–1 | City block sim + OSM fixture graph + voice-gated crossing geofence; BARN proxy 44 %; no terrain/drop-off perception; no GNSS receiver. |
| Generalized perception | 3 | 1 | 1 | OWLv2/SigLIP-2 ONNX chain on CUDA (16–83 ms/frame) but person recall **0/69 on renders vs 127/156 on photos**; 562 ms capture→publish vs 300 ms TTL; no depth ⇒ no map writes; no detector runs on an Orin (no ORT aarch64 wheel). |
| Owner/world memory | 5 | 5 | 5 | Body-agnostic. Owner facts + consent + soft delete + provenance + tiered memory + learned map with decay/naming all exist and are tested. |
| Recursive learning loop | 1 | 1 | 1 | `distil_session` has zero callers; tiers 2/3 unpersisted; no episodic layer; no person registry; no place containers; no `where_is` tool. |
| SLAM / localization | 1 | 0–1 | 0–1 | `PoseProvider` seam (MAP/ODOM, covariance, health, chance-constrained regions) with calibrated drift models; **no estimator anywhere**; `localization_jump_m` UNMEASURED. |
| Lifelike behavior | 5 | 0–1 | 0–1 | 50 Hz breathing/nods in MuJoCo; curiosity remarks (1 of 4 classes fires; 4–8 min cadence); awareness yaw ships OFF; no drives; idle = no command; Go2 expression is a no-op; head has no neck. |
| Safety / deployment | 7–8 | 2–3 | 2 | finalize_command/e-stop latch/TTL/speed caps/reactive gate real and pinned; commissioning path (single axis, 0.02–0.05 m/s, two-person attestation) exists; native gateway = contract + fake bench only; independent E-stop unowned; battery fabricated. |

Aggregate, to be challenged: a *persuasive simulator demo* of the living
dog is ≈ **40 %** built (PROTO-0 said 55–65 %; I discount because
initiative, continuous intent, world queries and learning — the things a
reviewer *feels* — are the parts that do not exist); a *supervised
low-speed indoor Go2 prototype* ≈ **20–25 %**; the *full indoor/outdoor
objective* ≈ **10 %**.

## 3. What is genuinely strong (keep, do not re-litigate)
- The safety core and its oracles (r24 lock discipline, nominal-stop
  digests, input-health R28 table, proximity ladder, arbiter/preemption).
- The hosted lane's admission model (four yeses, spend ledger, idle
  hang-up, tool broker with a 19-field door contract, zero-hallucinated
  place gate).
- Memory governance (consent states, provenance, soft delete, isolation).
- The pose seam and the calibrated drift ladder — the right shape for a
  delegated localizer.
- The portability seams: `LocomotionController` + `RobotStateSource`, the
  registry, vendor SDKs only inside methods, a second-vendor mock that
  passes the full lifecycle.
- The capture rail (30-channel matrix, preflight, clockmap, MCAP record,
  sidecar, attest) — box-day is scripted.

## 4. The gaps that decide the milestone (each maps to a hypothesis)
1. **Economics** — the ear must be local; hosted per engagement. (H1)
2. **Compute** — the admitted GPU reasoner is not what runs; the GPU is
   94 % idle; no ambient-cognition model has been tried. (H2)
3. **Initiative** — no drive/goal generator; exploration anti-exploratory
   and off; attention core unwired. (H3)
4. **Body** — no continuous intent, no body-neutral contract, expression
   dead on the Go2. (H4)
5. **Learning** — built, never scheduled, never persisted, no episodes,
   no world queries. (H5)
6. **Perception** — zero photons; freshness violated; no novelty signal;
   RGB-only fallback unknown. (H6)
7. **Localization** — seam without a filter; consumers never drift-armed
   against a real estimator; jump term unmeasured. (H7)
8. **The native gateway** — the one blocker no experiment removes; a build
   card in the milestone design (§5 Q8).

## 5. PROTO-0's nine questions, answered
1. **Snapshot accuracy.** Materially accurate. Corrections with evidence:
   lifelike 6→5 (idle emits no command, `runtime.py:~10943`; Go2 expression
   no-op `backends/go2.py:~1173`); indoor nav 7→6 (SR 0.28 at v4); memory
   is body-agnostic (5 in every column); the table omits the *cost*
   capability, which is currently the hardest blocker for "seamless" and
   is added above. Their concerns 1–9 all confirmed against the tree
   (file pointers in the surveys behind this document).
2. **Smallest first physical outcome and ODD.** *The desk dog*: one
   private, flat, dry, mapped indoor room; operator present; independent
   E-stop in hand; speed ≤ 0.3 m/s; Go2 in Sport mode (vendor owns gait
   and balance). It listens continuously at $0, converses through the
   array with the hosted lane opened per engagement, looks around
   (body yaw + `Euler` posture primitive), remembers the owner and what it
   noticed via D455, and performs self-initiated look/approach errands
   within a 6 m radius. No stairs, no public space, no outdoor.
3. **Tasks 17–19.** DEC-FS-1 (task_18): COMPLETE_NOW — in flight,
   mechanical, makes the tree followable for every card after it. DEC-R1
   (task_17): COMPLETE_NOW — cheap, and every physical card must edit
   `runtime.py`; a 16.7k-line file is a tax on all of them. DEC-N1
   (task_19): DEFER — `pipeline.py` is not on the physical critical path
   and its leaves will move again when the localizer lands. DEC-R2
   (task_21, builders): COMPLETE after R1 — it is where the observation
   spine (a `NavigationSnapshotV2` assembler) gets a home.
4. **Observation spine vs native gateway split.** Yes: the spine is
   read-only (capture/contracts/core OWNS), the gateway is the sole writer
   (bridge/native OWNS); they meet only at the frozen `bridge/protocol.py`
   DTOs. Parallel work is safe; the double-writer window (verdict finding
   2) is closed by the gateway owning the credential from first boot.
5. **SLAM provider, selection criteria first.** Criteria: native Mid-360
   support; IMU coupling; runs in the capture (rclpy) venv as a separate
   process; publishes `T_map_odom` + covariance + health + jump; loop
   closure/relocalization story; CPU budget on an Orin NX; ATE/RPE on
   *our* bags. Evaluate in this order: **FAST-LIO2** (Livox-native,
   mature), **Point-LIO** (better under aggressive motion; the CMU
   `autonomy_stack_go2` reference uses it), **KISS-ICP** (LiDAR-only,
   dependency-free baseline and the off-robot proxy H7 uses now). Parcel
   owns the contract, never the filter.
6. **Gates.** First pulse: box-day preflight READY×3, clockmap recorded,
   firmware attested, `unitree_control run --arm` single-axis with
   second-person review. First translation: native gateway bench green on
   the Orin against fake Sport, independent E-stop measured, six stopping
   envelope terms measured (GATE-1 stops printing UNMEASURED). First
   autonomous indoor run: localizer health/jump measured on real bags,
   ≥ 10 leashed runs with 0 contacts, through-air person-stop verified.
   First outdoor: after repeated indoor success, plus terrain/drop-off
   perception, GNSS, and a written outdoor ODD.
7. **Retained unchanged vs scaffolds.** Retained: the safety core, grid
   planner + reactive gate, expression engine (as the posture/gaze
   *source*), memory governance, both voice lanes and the tool broker,
   capture rail. Scaffolds that must not count as physical progress:
   every MuJoCo perception number, `semantic_source: oracle`,
   `TruthPoseProvider`, the `SimObservation` carrier, sim teleports,
   `motion.backend: rl` (an intent recorder), BARN scores.
8. **Single next implementation card with the largest physical gain:**
   the **native sole-writer gateway + co-located governor** (Python 3.10
   vendor venv, `unitree_sdk2py`, `bridge/protocol.py` V1, fake-Sport
   bench → Orin), because every physical capability sits behind
   "`Go2Backend` refuses motion". Not created here.
9. **Limits.** WIP: one `runtime.py` toucher + one disjoint product lane +
   research executors confined to harness code and named leaf seams; full
   suites only at integration, `--dist loadfile -n 8` through the guard;
   hosted spend ≤ $2 per research card and ≤ $200/mo in product policy;
   one STATUS + one VERDICT per card, follow-ups batched per wave.

## 6. Does not prove
This assessment proves no target installation, no acoustic quality, no
localization accuracy, no stopping distance, no conversation quality to a
human, no memory quality on a real owner, no autonomous-navigation success
outside MuJoCo, and no readiness to move a Unitree. The research program
that follows is designed to convert several of these from "unknown" to
"measured off-robot"; the rest are on-robot by nature and are gated in §5.6.
