# AUDIT — Wave P1/P2 "Real eyes" + "Owner model" · Fable · 2026-08-22

Seven cards, seven Opus executors in ONE tree under the P0 rules (disjoint
OWNS, Edit-only, git read-only, targeted gates), dispatched 02:2x after
`5c7a2aa`, all returned by 03:0x. Audit method: one adversarial verifier per
card, read-only, instructed to refute; corrections routed back to the card's
own executor; a full gate on the audited tree before the wave commit.
Baseline for every diff: `904edd2`.

## Verdicts

| Card | Verifier | Close | What the refuter reproduced | Correction routed |
|---|---|---|---|---|
| P1-A real eyes | CLAIMS_HOLD | ACCEPT_CLOSE (corrections landed §11) | fresh daemon: cuda_fp16 honoured, client p50 99–103 ms, boundary overhead 0.5–2.4 ms, SigLIP-2 3.2 ms 768-d unit norm; server refuses 17 phrases with a bypassed client; fixture byte-identical; pyrealsense2 cp314 imports; seeds; hygiene | handoff snippet omitted `origin=` ⇒ real frames would publish `unknown`; fix + tests assert the PUBLISHED frame's origin |
| P1-B the map learns | DISCREPANCIES_FOUND (evidence-pack class) | ACCEPT_CLOSE (corrections landed §11) | run 2 genuinely started from run 1's 69 entries (ids + first_seen lineage); as_dict corpus sha recomputed; own 120 s shadow arm 69 entries / 0 errors; D-R1 probed live; the 34-phrase cap arm reproduced exactly (48 frames / 716 truncated / 0 errors); 7/7 seeds re-run on a scratch copy of the CURRENT tree; R24's one new edge read through every code path — no undeclared edge; runtime hunks attributed, none in another card's region | the runtime never closes the map store (WAL un-checkpointed ⇒ pack's store shas irreproducible) — close/checkpoint at persist, seeded; owner-store check was vacuous (non-existent path) — re-measured; overwritten oracle-arm pack re-run; §8.7 contradiction fixed; scene_id records the config stem — fixed |
| P1-C which person is you | CLAIMS_HOLD | ACCEPT_CLOSE | the stranger-claim finding on the real encoder (thr 0.9103 < stranger 0.9296 ⇒ claims on the occluded-owner frames; calibrated 0.9592 ⇒ 0); enrollment refuses without negatives; rows R1–R8; fusion +155/−0, digest recomputed | vacuous occlusion assertion (int vs str) rewritten, watched RED; real-encoder RED-2 promoted to a test — landed, 100 passed on GPU |
| P1-D ask, don't refuse | DISCREPANCIES_FOUND | ACCEPT_CLOSE, partial on naming (corrections landed §11) | rows 1–5 reproduced row-for-row on the GPU incl. veto p_yes; the MAD-zero collapse to 0/7 on the same map; 12/12 seeds on an isolated copy; D-R3 in both functions; flag-off identity over 1500 verdicts; weights from the 08-21 cache, nothing downloaded | the veto had NO product seam — row 1's 5/7 was harness-only (monkeypatched); the 'low-priority CUDA stream' claim is false (priority 0 = default; only the 120 ms budget protects, admitted on a declared estimate; cold call ~0.8 s under a held lease); pre-registered fixture swapped undeclared; row-3 counts wrong; no in-tree CI eval row — seam wired + product-path row 1 re-measured, measured-EMA admission + warm-up outside the lease, fixtures committed with CI rows, docs corrected |
| P1-E social zone is a config | DISCREPANCIES_FOUND | ACCEPT_CLOSE (corrections landed §9) | MOVE-1 pair 0.312942 / 0.843333 m (prereg 0.84258), clearance 0.71011, collisions 0; floor 0.68 = stop_distance(0.85); AST ratchet: four digests unchanged, one pin regenerated with a log; safety core zero lines; five out-of-OWNS test edits judged TIGHTER | two stated claims false: "below `__post_init__` comment-only" (three new properties, one dead) and "planner and gate agree on one envelope" (not wired; `gate_clearance_m` has no production setter) — dead code removed, doc corrected, coupling handed to DOOR-1 |
| P2-A owner facts | CLAIMS_HOLD | ACCEPT_CLOSE (corrections landed §10) | owner store byte-unchanged and its 02:19 change attributed to the OWNER's own session (writer `owner_stack`, idle hang-up == mtime); synthetic-range guard re-run raised on a fresh store; credential refusal driven through the real lane; runtime share exactly +131/−4; pass^3 | credential turns still replay via the message tail ⇒ policy filter at replay, seeded RED |
| P2-B the dog notices you | CLAIMS_HOLD | ACCEPT_CLOSE (doc fixes §9) | identity-as-label by construction (blocking label unconstructible; 56 arming byte-identity cases, not 28); `_hosted_affect` extended in place; greet 2.0 s; storms ≤6/min; seeds 26/125 from the seed tree; zero card spend (the $0.11 at 02:06 was the owner's desk session) | doc accuracy (56 not 28; `label()` impurity; numstat attribution) |

## The wave's findings (the reason to run it)

1. **An owner gallery without a non-owner crop is unsafe against the real
   encoder** (P1-C): SigLIP-2 cosines place a stranger at 0.93 against an
   owner-derived threshold of 0.91 — the robot would have claimed a stranger
   as the owner whenever the owner was occluded. The fix is structural
   (measure the boundary from a negative; refuse to enroll without one) and
   the calibrated headroom is only 0.03. OT-2 inherits the consequence:
   `OWNER_IDENTITY_CONFIDENCE_MIN = 0.65` is meaningless on a cosine scale.
2. **k-consistency promotes confident mistakes** (P1-D): three agreeing
   visits promoted "yellow cylinder" for a bollard; measured naming accuracy
   45% vs the research's 82–87%. The shipping path's zero false promotions is
   "safe because blind" (64-px thumbnails). NM-1: an independent judge
   (detector agreement) before a name enters `known_places()`.
3. **The first persisted experience** (P1-B): a second patrol started
   knowing the first's 69 places; embeddings, relief and thumbnails survive a
   reload. Also the first measured trade the prototype ruling asked for: the
   oracle-side query union ships OFF because it truncated 716/1100 detections.
4. **The social zone is a config** (P1-E) — the dog approaches to 0.71 m
   with zero contact — and the next wall is literal: doorways (DOOR-1).
5. **A camera will work the day it is plugged in** (P1-A) — daemon at
   ~100 ms with ~1 ms of process boundary — but nothing in the runtime selects
   it yet (VENUE-1), and the handoff would have stamped real frames `unknown`.
6. **The dog now keeps facts with consent, notices you, and never gates on
   identity** (P2-A/P2-B), with one gap closed at review: a spoken password
   must not replay into the next session either.
7. **Re-measurement found more than the verifiers did** — the correction
   passes were not clerical: P1-D's seam wiring exposed two further bugs (the
   veto resolver returned an object, not a callable, so every call had been
   silently "unavailable"; the unavailable-ASK borrowed the wrong reason
   constant), and its warm-up needed TWO throwaway generations (the first
   post-load call costs 719 ms). P1-B's relief row moved from 1.000 to 0.985
   on a quiet tree — one tree below the 8-sample minimum, the gate saying
   "nobody could look". P1-B also discarded packs that had overlapped a
   seeded-RED window and re-ran serially. Numbers that survive their own
   re-measurement are the only ones this register keeps.
8. **Hardware premise corrected by the owner mid-wave:** no robot hardware is
   on hand (no Go2, D455, L2 or Orin; only the XVF3800 mic array). The
   "on the bench since 08-13" sentence in `scrum/20260813/task_1/README.md`
   was a card's assertion, never the owner's; it propagated into the 08-22
   audit and into this auditor's first plan reply. Corrected in the board,
   the four camera-dependent cards, the memory notes, and the republished
   audit artifact. Possession is an owner fact, never a document inference.

## Contract and method notes

* Concurrency held: seven writers in one tree, zero double-claimed paths
  (parcel-1e's attribution), every out-of-OWNS edit declared, `runtime.py`'s
  ~980-line diff attributable hunk-by-hunk to P1-B/P1-C/P2-A/P2-B/P1-E.
* Verifiers reproduced numbers rather than re-reading them: the MOVE-1
  pair, the daemon latencies, the stranger claim, the store provenance — all
  re-measured. No pre-registered NUMBER was refuted. Four claims were: two
  on description (P1-E's diff summary and envelope coupling), two on
  wiring (P1-D's veto had no product seam — its headline admissions were
  harness-only; P1-B's runtime never closes the map store). Both wiring
  defects were found by refuters reading code paths, not by any test —
  the seeded-RED discipline proves guards, not integration; the wave's
  integration proof is the full gate plus the product-path re-runs the
  corrections demanded.
* The held-out scene was never loaded by any card. Two gratuitous NAME
  mentions appeared during the wave (a P1-B test string — renamed; a Sol
  session's INTEGRITY_GATES_TODO.md checklist — seated as scrum prose with
  its provenance) and the isolation scan caught both.

## Owner actions this wave unlocked

1. Acquire a depth camera (the code targets the RealSense D455; NONE is on
   hand — the owner has no robot hardware) ⇒ P1-A's L1–L3 and P1-C's live
   rows run by the commands in their status docs (VENUE-1 first). **Not a plain webcam:**
   P1-A's post-verification cell showed an RGB-only UVC venue cannot feed
   the ingress today (it requires depth) — the day-one device is the D455
   until VENUE-1 adds an explicit RGB-only mode.
2. `PARCEL_MEMORY_PURPOSE=owner .parcel/bin/python tools/quarantine_synthetic_memory.py --apply`
   — until then the owner-fact distiller refuses to run on your store (by
   design).
3. `tools/enroll_owner_voice.py` (1 min) and `tools/enroll_owner_appearance.py`
   (10 s, needs the camera; refuses without one non-owner crop).
4. One full-size gpt-realtime session via `tools/voice_tier_ab.py`.

## ENV-1 verification (Fable, 05:44–06:15 EDT)

**Verdict: ACCEPT with two corrections landed and a small follow-up carded
(ENV-1b).** Verified by my own diff read + targeted runs and by a 10-agent
read-only workflow (three lenses — weakened properties, product correctness,
product-path integration — each finding then attacked by a skeptic): 4
confirmed, 3 refuted (two of the refutations were the skeptics seeing my
correction already in the tree).

* **Weakened-property lens: nothing dropped or relaxed.** All seven re-cut
  tests keep their old assertions verbatim (`VENDOR []`, the eight refusal
  assertions, `satisfied is False` for GO2/D455/L2, every motion-SDK name) or
  replace them with strictly stronger ones (three-state report; per-row
  `device_node_missing` + never `probe_raised`; device-present arms). The only
  absences dropped are `pyrealsense2` and `cv2`, both declared, both still
  covered by the never-imported guards (rehearsal subprocess, preflight VENDOR
  set, the AST forbidden-import scans). No new test is tautological.
* **Product lens: the four changes are correct.** `require_device()` precedes
  the only `importlib.import_module("pyrealsense2")` on every path
  (`open_pipeline`, `stream_selection`, `read_frames` all route through
  `_module`); the old unconditional `finally: handle.stop()` genuinely masked a
  failed `start()` by exception replacement — **a real bug found by this card**
  — and the `started` flag calls `stop()` exactly when `start()` succeeded
  (including early generator close); the `query_devices` ReadOnlyHandle needs no
  `VETTED_REACHES` entry (`test_no_arm_pin` 76/76); the `/dev` census cannot
  traceback; NOT_ATTESTABLE is not refused; the only new top-level import is
  `pathlib`.
* **Integration lens: PASS through the real callers.** `preflight --window
  0.01`, `attest.py`, `clockmap --check`, and the documented
  `dependency_report_text` one-liner were re-run as the owner would: six d455
  rows `device_node_missing` with the USB-3 (BLUE) remedy and zero
  `probe_raised`; `go2.lowstate` `dependency_missing — rclpy`; `VENDOR []` in
  two clean subprocesses plus an `-X importtime` cross-check; the old
  `stop() cannot be called before start()` reproduced and explained against
  real librealsense (`finally`-stop masked `start()`'s "No device connected").
  Exit codes and summary lines unchanged on this box; no consumer outside the
  five files depends on the changed strings.
* **Correction 1 — deviation 4 ruled WRONG (major, confirmed by an Orin
  simulation).** Folding `interrogable` into `probe_availability`'s
  `satisfied` made the Go2 read ABSENT on every host, so `clockmap --check`
  could never exit 0 — a fully equipped Orin included — printed the dog as
  both `[ RITUAL]` and `[ ABSENT]`, and handed the Orin operator a remedy
  ("run this on the Orin…") that cannot apply. The Go2's modules are what it
  takes to *receive* its messages (its own `ProbeRequirement.note`). Fix: the
  `interrogable` term removed (two conditions: module + device node). Guard
  `test_a_non_interrogable_device_is_a_ritual_not_a_missing_probe` models the
  Orin arm and pins the `OK:` exit-0 path. Seeded RED against the executor's
  rule: `assert (False, ('rclpy',)) == (True, ('rclpy',))`; GREEN after. This
  box's rows are unchanged (rclpy is absent here).
* **Correction 2 — the L2 `ProbeRequirement` gated on `/dev/ttyACM*` (major).**
  The add-on L2 is `unilidar_sdk2` over UDP *or* ttyACM (the requirement's own
  note), and `L2Ingest` declares no device node (NOT_ATTESTABLE) — so clockmap
  would have read the L2 ABSENT on the planned Ethernet wiring with the binding
  present. Fix: `device_nodes` removed from the L2 requirement to match the
  ingest side; pinned in the same guard.
* **Carded as ENV-1b (minor ×2 + notes, Opus, verified at the week-1 close):**
  six assertions hard-require the `pyrealsense2` wheel that the `dev` extra
  does not carry (a fresh `.[dev]` venv fails 6 — reproduced with a scratch
  `find_spec` shim) → branch on the wheel the way the rehearsal test already
  does, never by adding the SDK to `dev` (no aarch64 wheel); the `--check`
  REFUSED paragraph gives the module-only remedy for a device-arm refusal;
  stale dead-premise docstrings in `scripts/parcel_capture/{__init__,preflight}.py`;
  the preflight guard pins four of six d455 rows; `_require_enumerated_device`
  is fail-open when the SDK build exposes no `rs.context`; Orin-day notes
  (uvcvideo must bind the D455 for the `/dev/video*` census; P1-A's daemon
  tests bind a socket inside `tmp_path` and break under any long TMPDIR).
* **Refuted:** `rs.context()` construction outside the `try` (package-wide
  pattern, not ENV-1's).
* **Not a tree defect — a verifier environment defect.** The first final gate
  run (05:45) went red on `default-suite` with 7 failures + 13 errors, all
  unix-socket tests (`test_sim::test_socket_publish_and_poll`, all of
  `test_p1a_perception_daemon.py`, `test_gateway_process::test_sigkill_*`),
  every one `OSError: AF_UNIX path too long`: my
  `TMPDIR=~/.cache/parcel-fable-gate` plus pytest's `tmp_path` nesting
  exceeded the 108-byte socket-path limit. Under the default `/tmp` all 37
  pass; the gates below ran with TMPDIR unset.
* **Not proven here (as declared):** no camera was opened; `/dev/video*` is a
  proxy and the `rs.context().query_devices()` gate ran against a double and
  once against the real SDK with no device; the Orin path is simulated, not
  measured; `cv2` is now unpinned by any test.

## Final gate on the audited tree

**First run (08:09Z, after a 60 s content-hash quiescence check on
src/tests/configs/evals/scripts/tools — 121 paths unchanged): 2 hard gates
red, everything else green** (tier-coverage 8,701 collected = 8,620 commit +
81 nightly; assertion-evals, release-parity, owner-store-isolation,
model-off all PASS; default-suite 8,594 passed / 7 failed in 26 min under
the assessment workflow's load).

* **ruff** — every new fingerprint was in P1-D's three evidence scripts
  (`task_9/evidence/`: `C408` ×5, one `exec`, unused imports, a stale
  `noqa`, an unchecked `subprocess.run`). The verifier had predicted it.
  Auditor hygiene: linted by hand back to the exact 7-entry baseline.
* **default-suite, 7 failed** — all capture-stack tests asserting the 08-13
  invariant "this hardwareless dev box has no vendor SDK" (`pyrealsense2`,
  `cv2` …). P1-A's sanctioned install of `pyrealsense2` and
  `opencv-python-headless` for the desk venue made that premise false; the
  properties behind the tests (refuse with a named remedy when no DEVICE is
  present; a preflight never imports a vendor SDK) are still right and are
  being re-cut by card **ENV-1** (`task_28`) — device-absent arms, lazy SDK
  import if the preflight property broke, seeded RED.

**Final run (10:08Z, TMPDIR unset, tree quiescent — ENV-1 + both verifier
corrections in): PASS — every hard gate green.** ruff 7 violations = baseline
7, new 0 · hard-safety (frozen nav baseline v4: collisions 0, false_arrival 0;
mutation panel clean and fresh; follow-bench 7 rows all 0; walk_with_me 0) ·
release-parity 91 assets byte-identical · assertion-evals 5 fixtures / 20
pinned findings / harness self-test 4/4 · tier-coverage 8,706 = 8,625 commit +
81 nightly · model-off 23 · release-parity-integrity 10 · owner-store-isolation
6 · default-suite **8,606 passed, 16 skipped, 3 xfailed in 5:11**. Elapsed
331 s. (An intermediate run at 09:54Z, before correction 2, was also PASS with
identical counts; the 09:51Z red was the verifier's long TMPDIR — see §ENV-1.)
