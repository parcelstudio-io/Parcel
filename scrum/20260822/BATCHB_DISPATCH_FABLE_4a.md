# Batch B — re-dispatch record · Fable (parcel-4a, session 888dd0b1) · 2026-08-22 16:2x EDT

**Why this file exists.** Batch B (XD-1 `task_14`, HY-1 `task_15`, FZ-1
`task_13`, TRUTH-1 `task_32`, ROAM-2 `task_33`; GATE-0b `task_30` HELD) was
dispatched by Fable 799cb356 at ~15:20 and its five executors died twice in
Cursor restarts (~15:40, ~16:10). Their partial work is in the tree (52 dirty
paths on `e15e466`; everything compiles; ruff tree-wide 14 = 7 baseline + 7
debris). Split agreed between the three live sessions at 16:15: **parcel-38
(799cb356) keeps the hardware design (`WAVE3_HW_DESIGN_FABLE.md`), PO-1 /
board / memory, and the INTEGRATOR role (full gate, commit by path list,
push); parcel-4a (this file) re-dispatches and verifies batch B; parcel-bc is
idle and hands-off.** If the environment crashes again, whoever is alive
re-reads this file and continues the same split.

**Owner's standing instruction to this session (verbatim intent):** execute
with Opus, verify with Fable; design is high quality and *becomes hardware
compatible with the Unitree Go2 EDU Plus with Mid-360 LiDAR*
(https://robostore.com/products/go2-edu-plus-with-mid-360-lidar-quadruped-robot-dog);
**always write a structured design that connects to the bigger architecture
before implementing, in today's task folder**; keep writing to disk (Cursor
keeps crashing).

**Hardware target (owner, 16:00):** Go2 EDU+ w/ Mid-360 — Jetson Orin NX
16 GB (100 TOPS) ONBOARD (aarch64, JetPack → CPython 3.10), Livox Mid-360
(Ethernet, Livox SDK2) + the built-in wide-angle head LiDAR (exact model
UNKNOWN until the box; design against the `rt/utlidar/*` topic shape),
1280×720 / 120° RGB front camera (no depth → the D455 buy stands), Wi-Fi 6 +
4G, 15 Ah / 2–4 h, 12 kg payload, 2 m/s. Two fact sheets are being produced
for the design session: `go2_eduplus_facts.md` (cited web research) and
`hardware_seams_map.md` (every seam in this tree) under this session's scratch
(`/tmp/claude-1000/-home-jaewoo-jang-Desktop-Projects-Parcel/888dd0b1-2a72-4234-a711-8747f08ff628/scratchpad/`).
Nothing in batch B is hardware-gated; each card's DESIGN.md states how its
seam survives the move to the Orin + Go2 (see §Per-card).

## Partial state found at 16:10 (read-only census; nothing reverted)

| Card | Landed before the crash (mtime) | Not yet there |
|---|---|---|
| XD-1 `task_14` | `PREREGISTRATION.md` 15:25 (scratch clone at `~/.cache/parcel-xd1/tree`); `scripts/ci_gate.py` +121 (15:33, **no marked region**); `tests/test_ci_gate.py` +156 (15:58); `tests/conftest.py` XD-1 block (imports `_repo_write_guard`, RUF100 debris at :211); `tests/_repo_write_guard.py` 282 lines (ISC004 debris at :250); `tests/test_p1b_map_learns.py` +20 (the S4/S5 over-spec removal); a comment edit in `runtime.py:4328-4334` | `XD1_STATUS.md`; the three consecutive runs; D1–D7 censuses; the marked region in `ci_gate.py` |
| HY-1 `task_15` | `PREREGISTRATION.md` 15:23; `tests/_sim_guard.py` 381; `tests/test_hy1_sim_guard.py` 638 (14 passed + 2 errors at 16:12); conftest HY-1 region (function-local `import time` ×3); `tests/test_voice_nav_e2e.py` +107; `scripts/launch_sim.sh` +54; `tools/list_parcel_procs.py` 178; `~/.cache/parcel-hy1/{evidence,shadow}` | `HY1_STATUS.md`; the 2 erroring guard tests; R10 reaping of the five orphans (pids 2447765/2447909/2448046/2448183/2448324 — re-identify before any signal) |
| FZ-1 `task_13` | `PREREGISTRATION.md` 15:25; `realtime/prompting.py` +114; `prompts/personalities/_frozen/si-companion-v{1,2,3}/` (9 files) + the `runtime_assets` mirror + `MANIFEST.json` +76; `tools/freeze_si_version.py` 260; `tests/test_fz1_frozen_si_snapshots.py` 402 (15:57); xfail removal in `test_realtime_prompting.py` / `test_realtime_corpus_replay.py`; `test_release_parity.py` +7 | `FZ1_STATUS.md`; rows 1–11 measured; seeds S1–S5 |
| TRUTH-1 `task_32` | `PREREGISTRATION.md` 15:27; `scripts/parcel_capture/{__init__,clockmap,preflight,record}.py` + `ingest/realsense.py` (15:31–15:58); `tools/replay_turn_detection.py` +117; `task_25/SESSION.md` +23; `~/.cache/parcel-truth1/new*.txt` | **`tests/test_truth1_texts.py` does not exist**; R9 (`planner_model`) untouched; `TRUTH1_STATUS.md` |
| ROAM-2 `task_33` | `online_map.py` +114; `patrol/mission.py` +178; `runtime.py` ROAM-2 regions (state at ~2010, status at ~5028, query at ~5144; mtime 16:06); `tests/test_roam2_coverage.py` 687; `evidence/` empty | **no PREREGISTRATION** (the baseline definition + number must be registered before the three runs); `ROAM2_STATUS.md` |
| GATE-0b `task_30` | nothing | HELD until XD-1's `ci_gate.py` region lands and is verified — one writer on `ci_gate.py` at a time |

Unattributed dirty paths (attribute by content; leave alone if not yours):
`tests/test_prototype_profile.py` +5, `tests/test_capture_ingest.py` +24.
`scrum/20260822/{TASK_BOARD.md,task_27/README.md,AUDIT_WAVE2_FABLE.md}` are
parcel-38's.

## COMMON brief (binding for every batch-B executor; read this before your card)

You are the EXECUTOR for one card in the Parcel repo
(`/home/jaewoo-jang/Desktop/Projects/Parcel`). HEAD is `e15e466` (batch A
landed); `git diff HEAD` shows YOUR card's partial work from a previous
executor that died mid-card PLUS four other cards' partial work. **Resume
from the tree as-is: nothing is reverted; re-read every OWNS file in full
before touching it; treat what is there as a draft you now own — fix it,
finish it, or replace it, but never `git checkout` it.**

Read, in order: (1) `CLAUDE.md`, then `CODEBASE_INDEX.md` SELECTIVELY
(`grep -n '^## \|^### ' CODEBASE_INDEX.md`; `sed -n 'A,Bp'` for your OWNS'
sections; the "Card markers" section). (2) `scrum/20260822/TASK_BOARD.md` —
the standing rules are BINDING: prototype not production (ask-over-refuse,
no new fail-closed defaults, no new hash-locks/allowlists); shared tree with
4 other batch-B executors RIGHT NOW under disjoint OWNS; EDIT-ONLY on existing
files (never Write a whole existing file); re-read before every edit; git is
READ-ONLY for you (no add/commit/stash/checkout/reset/restore); never kill
processes you did not start (exception: HY-1 R10, by its own rule); sims only
on a unique SHORT socket under `/home/jaewoo-jang/.cache/parcel-<slug>/`;
never touch `docs/`, `backlog/`, `README.md`, `scrum/20260821/`,
`reactive_safety`, `core/hard_stop`, the venv; never append to
`evals/nav_instruct/results/ledger.jsonl`. (3) Your card README — every
section — and its PREREGISTRATION.md if present (keep it VERBATIM; its sha256
goes in the status doc; rows are measured as written, misses are misses).
(4) `scrum/20260822/WAVE2_DESIGN_FABLE.md`, `AUDIT_WAVE2_FABLE.md` (esp.
"Batch-A gate", "Cross-card findings", the GREEN-1 correction) and
`AUDIT_WEEK1_FABLE.md` §Method — the verifier's method and the lessons your
card inherits: seeds prove guards, not integration; a test that passes against
a stub door is a defect; for every "cannot be tested here" first find the
engine that CAN model it.

**DESIGN FIRST (owner's rule).** Your FIRST act after reading is
`scrum/20260822/<folder>/DESIGN.md` (new file, ≤ 120 lines): (a) purpose in
one paragraph; (b) **architecture fit** — the named seams you touch
(module:symbol), who calls them on the product path, what reads/writes them,
and how the change composes with batch A's regions (VENUE-1/CAP-1/OT-2/DOOR-1)
and the safety core; (c) interfaces/contracts (signatures, config keys,
dataclass fields, defaults — defaults OFF for behaviour); (d) data flow and
lifecycle (locks, threads, processes, files); (e) **hardware compatibility**:
how the seam behaves unchanged when the venue is the Go2 EDU+ (Orin NX
aarch64 / CPython 3.10 onboard, D455 + Mid-360 + head LiDAR, the native
gateway process) — what is venue-independent by construction, what must be
configured, what is UNKNOWN; (f) test strategy mapped to the pre-registered
rows and the seeds; (g) risks and what the design does NOT cover. Tie every
statement to a file:symbol. Then implement against it; if implementation
forces a design change, edit DESIGN.md in the same pass and say so in the
status doc.

HARDWARE FACT (authoritative): NO robot hardware is on hand — only the
reSpeaker XVF3800 mic array (never play audio through it or write a control
command to it). Owner-gated rows are listed with their exact command, never
claimed.

OWNS discipline: edit ONLY your OWNS; a shared file is edited by MARKED
REGION (`# ---- CARD <NAME> …` / `# ---- END CARD <NAME> …`) with a re-read
before every edit; another card's region or file → HALT on that item and
report. Lint debris in YOUR files is yours to clean (ratchet: exactly the 7
baseline fingerprints in `scripts/ci_ruff_baseline.json`; add none; fix at the
source; never `noqa`; never re-pin).

Verification: targeted `pytest` + `ruff` on your OWNS only (`.parcel/bin/python`,
`.parcel/bin/ruff`; **`TMPDIR` unset**); never `scripts/ci_gate.py`'s tier or
the full suite (the integrator gates). Every new guard gets a seeded-RED proof
on the PRODUCT (seed, watch the named test fail, restore byte-identically by
sha256, purge `__pycache__`, re-run green; seeds on a byte-identical scratch
copy of `src/` are preferred while other cards edit the tree). Headline rows
run THROUGH THE PRODUCT PATH (the runtime's own loop, the lane's own ingress,
the real CLI) — say which. Owner's `parcel_memory.sqlite3` never opened
read-write; the owner's live stack on `:8765` / `/tmp/parcel_sim.sock` is
read-only; hosted spend ≤ $2 and only if the card needs a live turn.

Deliver `scrum/20260822/<folder>/<STATUS>.md` in the lightweight register:
headline · what changed (`git diff --stat HEAD -- <OWNS>` + new files) · how
verified (exact commands + results; seeded-RED per guard; product path named)
· what it does not prove · deviations · owner-gated rows with commands ·
handoffs · **"resumed from" paragraph**: what the previous executor had
landed, what you kept, changed, or discarded, and why. Your LAST act is
returning your report; nothing runs after it (stop every sim you started;
`tools/list_parcel_procs.py` before you return). Return: COMPLETE or HALTED,
status-doc path, DESIGN.md path, rows met/missed, deviations, what the
verifier must look at first.

## Per-card EXTRAS (resume facts + hardware-compat requirement for DESIGN.md §e)

**XD-1** (`task_14`, slug `xd1`, `XD1_STATUS.md`). Card + WAVE2 extras
(GATE-0's lesson: no test writes under the repo; the `_repo_write_guard`
draft is in the tree — decide ON/opt-in by the D7 rule already registered).
Resume: the `ci_gate.py` edit has NO marked region — wrap it
(`# ---- CARD XD-1 default-suite two-phase runner` … `END`) because GATE-0b
will edit the same file after you; conftest XD-1 block (`:205-…`) + HY-1's
block are separate marked regions — re-read before every edit; clean RUF100
`conftest.py:211` and ISC004 `_repo_write_guard.py:250`; the scratch clone at
`~/.cache/parcel-xd1/tree` is yours (re-verify it is at `e15e466` before
timing). Hardware-compat (§e): the two-phase gate must be correct on an
8-core aarch64 Orin (JetPack, CPython 3.10) as well as this 192-thread box —
`-n auto` derives workers from `os.cpu_count()`; record the worker count in
the gate row; no x86/CUDA assumption in the runner; the `load_sensitive`
serial phase is what keeps timing rows honest on a small CPU.

**HY-1** (`task_15`, slug `hy1`, `HY1_STATUS.md`). Card + WAVE2 extra (the
leak check names the SOCKET). Resume: `tests/test_hy1_sim_guard.py` = 14
passed + 2 errors at 16:12 — those two are your unfinished guard; the five
orphans on pytest scratch sockets (pids 2447765 2447909 2448046 2448183
2448324) are your R1 evidence and R10 targets — re-identify each with
`ps -o args= -p <pid>` immediately before any signal, never the owner's
`/tmp/parcel_sim.sock` or `:8765`, record every kill. Hardware-compat (§e):
design `_sim_guard` as a PROCESS guard with a pattern table (today
`parcel_robot.sim`; tomorrow the perception daemon and the native Go2
gateway process on the Orin) so the same seam catches a leaked gateway that
would hold the DDS participant — name the extension point, implement only the
sim pattern; `tools/list_parcel_procs.py` lists every `parcel_robot.*`
process and must run on a box without MuJoCo.

**FZ-1** (`task_13`, slug `fz1`, `FZ1_STATUS.md`). Card as written; SI v3 is
current. Resume: snapshots v1/v2/v3 + mirror + MANIFEST + tool + test file +
xfail removals are in the tree — verify each against the PREREGISTRATION rows
(byte-identity of v1/v2 to `e63be08`, v3 to live) before measuring;
`~/.cache/parcel-fz1/` has the probe and `pkg_frozen.sha256`. Hardware-compat
(§e): the frozen dir ships in `runtime_assets` (release-parity) so an
`aarch64` pip install on the Orin renders historical versions identically —
state the invariant and the test that pins it (`test_release_parity.py`);
no filesystem path may be absolute or dev-box-specific.

**TRUTH-1** (`task_32`, slug `truth1`, `TRUTH1_STATUS.md`). Card as written;
never touch `probe_availability`/`PROBE_REQUIREMENTS`, `ingest/base.py`,
`pyproject.toml`, `lane.py`. Resume: product texts edited but
`tests/test_truth1_texts.py` does NOT exist yet and R9 (`planner_model`) is
untouched — R9's files (`runtime.py` `OVERLAY_INTRODUCIBLE_KEYS` region —
ONE marked `CARD TRUTH-1` region adding the key; `web_panel.py` read site
spelling guard; `tests/test_cap1_admission.py` pin update) are a DECLARED
deviation from the README's OWNS, already pre-registered; ROAM-2 is editing
other `runtime.py` regions concurrently. Hardware-compat (§e) — this card IS
the hardware-truth card: the remedy matrix is {d455, go2 (DDS), head LiDAR
(`rt/utlidar/*`), mid360 (Livox SDK2 over Ethernet), xvf3800} × {dev box
x86_64 CPython 3.14, **Orin NX 16 GB aarch64 CPython 3.10 (JetPack)**}; the
measured wheel census already shows `pyrealsense2` cp310 `manylinux2014_aarch64`
EXISTS → the D455 remedy on the Orin is ALSO pip (say so, dated); the
go2/l2 sentence must name the real path (`unitree_sdk2py` over CycloneDDS in
a CPython 3.10 process; ROS 2 Humble only if the owner installs it) — use
only facts you can cite (the fact sheet `go2_eduplus_facts.md` in this
session's scratch, if it exists when you get there, with its CONFIRMED tags;
otherwise write UNCONFIRMED, never invent).

**ROAM-2** (`task_33`, slug `roam2`, `ROAM2_STATUS.md`). Card as written;
`runtime.py` ROAM-2 regions only (they exist — at ~2010 state, ~5028 status,
~5144 query; verify every hunk of yours is inside a marked region);
`patrol/mission.py` + `online_map.py` drafts are in the tree;
`tests/test_roam2_coverage.py` 687 lines untested since 15:58. **Write
`PREREGISTRATION.md` FIRST** (after DESIGN.md): the coverage definition
(distinct map entries seen within the learned map's own visibility rule /
entries known at start), the baseline arm (ROAM-1 tethered, same scene, same
120 s, three runs — the number registered BEFORE the coverage arm runs), the
target (≥ 1.5× baseline), contacts 0, zone respected, in-block; then measure
through the product runner (`submit_realtime_transcript('Go explore.')`,
never a harness), unique socket under `~/.cache/parcel-roam2/`, redirect
LEDGER. Hardware-compat (§e): the objective reads P1-B's learned map under
its lock (the same entries VENUE-1's physical frames write), never sim ground
truth — so the behaviour transfers to the D455/Go2 venue unchanged; the policy
stays a pure function whose output passes `limits_from_safety` → on the Go2
the same `PatrolLimits` carries the indoor speed cap; name the idle-checkpoint
seam as where a Mid-360 localization update (N31) will later land — no
implementation.

## Verification plan (mine; read-only; per card when its status doc lands)

Three-lens workflow (`verify_card_workflow.js`: seeds/weakening · product
correctness + OWNS · product-path integration; every non-note finding attacked
by a skeptic who must reproduce) on Fable; one correction pass per card on
Opus; re-verify; verdict + status-doc path sent to parcel-38, who gates and
commits. GATE-0b is dispatched only after XD-1's verdict is ACCEPT.

## Verdicts

(filled as each card closes)

## Dispatch log

* **16:17 EDT** — five Opus executors launched concurrently from session
  888dd0b1 (parcel-4a): XD-1, HY-1, FZ-1, TRUTH-1, ROAM-2; each told to read
  this file first and to write `DESIGN.md` before touching code. GATE-0b not
  dispatched. Two research agents (fact sheet; seams map) running for the
  hardware design parcel-38 owns. If this session dies: the executors die
  with it; the next session re-censuses the tree by mtime (the table above is
  the template), re-dispatches with the same briefs, and tells parcel-38.

## GATE-0b brief (HELD — dispatched only after XD-1's verdict is ACCEPT)

**GATE-0b** (`task_30`, slug `gate0b`, `GATE0B_STATUS.md`). Card as written;
the clean-clone recipe is `task_20/GATE0_STATUS.md` §R9; `scripts/ci_gate.py`
is shared with XD-1 whose two-phase runner now sits in a marked
`CARD XD-1` region — GATE-0b adds its own marked region for skip-list
reporting and never edits inside XD-1's. The clone for the PASS row is made
under `~/.cache/parcel-gate0b/` from the working tree's HEAD (tracked-only);
the gate runs INSIDE THE CLONE only. Hardware-compat (§e of its DESIGN.md):
the hosted job (B20) is x86-64 `ubuntu-latest`; the Orin is aarch64 with no
RTX — every row that needs CUDA, an x86-only wheel, a generated external root
or a GPU detector must be a `skip-with-reason` that the gate PRINTS, so the
same `--tier commit` command gives an honest verdict on the dev box, on the
hosted runner and on the Orin; the V9 mode-bit premise is decided (drop or
`chmod` in setup with a reason); the ledger guard (`--no-ledger` /
`--ledger PATH`) is the same rule on every host.

## parcel-dd take-over (session 1cc5a3) · 2026-08-22 17:55 EDT

The third crash (~17:35) killed parcel-4a (888dd0b1) with its five executors,
and parcel-bc. parcel-dd (a fresh Fable, author of this section) took batch B
by message from parcel-8a (799cb356) at 17:45. The split above is unchanged:
parcel-8a = `WAVE3_HW_DESIGN_FABLE.md` + board/PO-1/memory + INTEGRATOR
(gate, commit by path list, push); parcel-dd = batch-B re-dispatch +
verification, verdicts sent to parcel-8a; GATE-0b HELD until XD-1 is ACCEPT.

### Census at 17:42 (read-only; supersedes the 16:10 table where it differs)

- HEAD `e15e466`; 44 dirty paths; nothing reverted. Files the 16:17
  executors touched before dying: `scripts/ci_gate.py` 16:19,
  `tests/_repo_write_guard.py` 16:20, `tests/conftest.py` 16:21,
  `task_13/15/32/DESIGN.md` 16:22, `src/parcel_robot/runtime.py` 17:38
  (ROAM-2 coverage hunks at ~4850 `ROAM_CONFIG_KEYS`, ~5100 `coverage_bias`,
  ~5259 `_roam_sense` args, ~5315 `_step_roam`, ~5375 checkpoint — several
  OUTSIDE marked regions). Everything else is at its 15:2x–15:58 state. No
  `*_STATUS.md` for any batch-B card; no DESIGN/PREREG for ROAM-2; no DESIGN
  for XD-1.
- Processes: ZERO `parcel_robot.sim` (`pgrep -af`, `tools/list_parcel_procs.py`,
  `ss -xl`). The five orphans are gone. The owner's stack is DOWN
  (`/tmp/parcel_sim.sock` absent; nothing on :8765) — still hands-off.
- ruff tree-wide: 12 errors = exactly the 7 baseline fingerprints; 0 new (the
  16:17 pass cleaned the conftest RUF100 and the `_repo_write_guard` ISC004).
- The two unowned paths attributed by content: `tests/test_capture_ingest.py`
  (+24, remedy pins) → TRUTH-1; `tests/test_prototype_profile.py` (+5,
  `"coverage"`) → ROAM-2.
- Hardware facts: `go2_eduplus_facts.md` was never written; the design
  study's raw fetches are at `~/.cache/parcel-fable-design/hw-facts/{go2,mid360,l2,remote}.txt`
  (+ manuals as PDF, 16:15). Executors cite those files or write UNCONFIRMED.

### Rules added by parcel-dd

- **Shared-file lock:** `mkdir ~/.cache/parcel-batchb/lock-<basename>`
  before each editing pass on `tests/conftest.py` (XD-1, HY-1),
  `src/parcel_robot/runtime.py` (ROAM-2, TRUTH-1),
  `tests/test_prototype_profile.py` (ROAM-2, TRUTH-1), `scripts/ci_gate.py`
  (XD-1 now; GATE-0b later); `owner` file inside; `rmdir` after one short
  pass; never remove another card's lock.
- Never create `/tmp/parcel_sim.sock` or listen on :8765 as a test fixture
  (HY-1's R6 uses stand-ins).
- Status docs are written incrementally, from the first row (crash insurance).

### Dispatch log (parcel-dd)

* **17:55 EDT** — XD-1, HY-1, FZ-1, TRUTH-1 launched on Opus from session
  1cc5a3 with the COMMON brief + per-card EXTRAS above + this section's facts
  inline. ROAM-2 follows within minutes, once its coverage default is settled
  against `task_33/README.md` (the 17:38 draft sets coverage ON by default;
  the standing rule is defaults OFF with flag-off byte-identity).
* Verification: the three lenses + skeptics of `verify_card_workflow.js`,
  run as individual agents from this session; verdicts below.

### Verdicts (parcel-dd)

(filled as each card closes)
* **18:10 EDT** — parcel-8a delivered the hardware facts file
  `~/.cache/parcel-fable-design/research.json` (three lenses; `hardware`:
  26 facts tagged documented/measured/inferred + 11 open questions, each
  with a source). Citing rule: `documented` + URL ⇒ fact with the URL;
  `inferred` / open questions ⇒ UNCONFIRMED. Forwarded to the TRUTH-1
  executor with three constraints on remedy wording: the EDU dock may ship
  JetPack 5.1.1 (Py 3.8) or run 6.2.1 (the preflight L4T table at
  `preflight.py:267-276` covers only 6.0–6.2.1 — a handoff, not an edit);
  onnxruntime-gpu has no public aarch64 CUDA wheel at the pinned ≥ 1.28;
  the Mid-360 is Ethernet on the dock's M8 plug with a C++-only SDK (rclpy or
  raw UDP for Python), the head LiDAR only via DDS `rt/utlidar/*`.

## parcel-81 take-over (session 23d56828) · 2026-08-23 05:3x EDT

The fourth crash was a MACHINE REBOOT at 18:02:52 on 08-22; parcel-8a,
parcel-dd and the five executors all died. `ListAgents` today: zero peers.
**parcel-81 now holds BOTH halves of the split** — batch-B re-dispatch +
verification AND the integrator role AND `WAVE3_HW_DESIGN_FABLE.md`. All
prior rules stand (COMMON brief, per-card EXTRAS, the mkdir-lock under
`~/.cache/parcel-batchb/`, GATE-0b held until XD-1 ACCEPT).

### Census at 05:3x (read-only; supersedes 17:42 where it differs)

- HEAD `e15e466`; 55 dirty paths; nothing reverted. All four dispatched
  executors got further than the 17:42 table knew before the reboot:
  `task_14/XD1_STATUS.md` through row D1 (MET) + `DESIGN.md` 17:51 +
  `tests/test_xd1_repo_write_guard.py`; `task_15/HY1_STATUS.md` through R10
  (zero orphans; the five pids died with the reboot; nothing signalled);
  `task_13/FZ1_STATUS.md` and `task_32/TRUTH1_STATUS.md` are header stubs
  with sha256-pinned PREREGISTRATIONs; TRUTH-1's R9 landed in
  `src/parcel_robot/config.py` as ONE marked `CARD TRUTH-1` region
  (`planner_model` key) — note R9's constant lives in config.py, not
  runtime.py as the EXTRAS guessed. `task_33/DESIGN.md` (13.8 KB) exists;
  ROAM-2 still has NO PREREGISTRATION and NO status doc.
- `runtime.py`/`config.py` mtimes say 05:27 TODAY: that is Cursor's buffer
  restore when the owner reopened the editor (this session started
  05:27:40), not an edit — attribute hunks by content/markers only.
- Processes: zero `parcel_robot.*`; owner stack DOWN (`/tmp/parcel_sim.sock`
  absent, nothing on :8765) — hands-off stands. No batchb locks held.
- ruff/gate: not yet re-run this morning (integrator runs them at close).

### Dispatch log (parcel-81)

* **05:4x EDT 08-23** — all five executors launched concurrently on Opus
  (fourth resume): XD-1, HY-1, FZ-1, TRUTH-1, ROAM-2. Briefs = the COMMON
  brief + per-card EXTRAS + both take-over sections, with each card's exact
  resume point inline (XD-1 from D2; HY-1 from the two erroring guard tests;
  FZ-1 verify drafts then rows 1–11 + S1–S5; TRUTH-1 create the registered
  test file, verify R9 companions, measure all rows; ROAM-2 PREREGISTRATION
  first — baseline three runs registered before any coverage run, defaults
  OFF, wrap unmarked runtime.py hunks). GATE-0b still HELD. If this session
  dies: re-census by mtime; the executors die with it; re-dispatch only
  cards without finished status docs.
* **Design study deviation (recorded):** parcel-81 writes
  `WAVE3_HW_DESIGN_FABLE.md` directly from the finished research
  (`~/.cache/parcel-fable-design/research.json` + three lens results), in
  journaled sections, instead of re-running the proposals→judges workflow
  that died three times — five Opus executors are already concurrent and
  the spend limit killed a wave once. The critic pass survives: the draft
  gets one adversarial re-read against the research file before it is
  final.
  `~/.cache/parcel-fable-design/research.json` (three lenses; `hardware`:
  26 facts tagged documented/measured/inferred + 11 open questions, each
  with a source). Citing rule: `documented` + URL ⇒ fact with the URL;
  `inferred` / open questions ⇒ UNCONFIRMED. Forwarded to the TRUTH-1
  executor with three constraints on remedy wording: the EDU dock may ship
  JetPack 5.1.1 (Py 3.8) or run 6.2.1 (the preflight L4T table at
  `preflight.py:267-276` covers only 6.0–6.2.1 — a handoff, not an edit);
  onnxruntime-gpu has no public aarch64 CUDA wheel at the pinned ≥ 1.28;
  the Mid-360 is Ethernet on the dock's M8 plug with a C++-only SDK (rclpy or
  raw UDP for Python), the head LiDAR only via DDS `rt/utlidar/*`.

## parcel-6c take-over (session 31fcc2a0) · 2026-08-23 06:1x EDT

parcel-81 (23d56828) died at **05:38:42** with its five executors. `ListAgents`:
zero live peers. parcel-6c holds both halves of the split (batch-B
re-dispatch + verification, integrator, `WAVE3_HW_DESIGN_FABLE.md`). All prior
rules stand. Owner's instruction: "proceed execution and make sure not to
crash; implement with Opus and verify with claude".

### Why every session died — CORRECTED (supersedes "machine reboot")

All four deaths (08-22 15:36, 16:23, 17:58; 08-23 05:38) are kernel **OOM
kills** in `journalctl -k`. The host is 246 GB / 192 cores. Each time python
held 91–237 GB across 339–986 processes: **pytest-xdist workers** — `-n auto`
is 192 workers here, ~0.25 GB each. The kernel kills Cursor's renderer first
(`oom_score_adj` 300 vs python's 100), so every session in the window and
every subagent dies in the same second. Multipliers: (a) several executors
running `-n auto` suites at once (15:36 = 3 runs ≈ 580 procs); (b) from
16:19 on, XD-1's uncommitted `ci_gate.py` routes the `default-suite` row
through a new `evaluate_default_suite` that `tests/test_ci_gate.py`'s
`fast_commit_tier` fixture does NOT stub (it stubs `_pytest_gate`, the old
path), so ~8 gate tests launch the whole suite at `-n auto` from inside a
test, and under xdist that nests: five chained runs ~29 s apart at 05:38 =
986 procs / 237 GB. Memory note: `parcel-oom-crash-cause-2026-08-23`.

### Guards installed 06:14 (outside the repo; nothing in the tree changed)

- `~/.cache/parcel-guard/pytest_guard.sh` — mandatory wrapper for EVERY
  pytest run: refuses `-n auto`, caps `-n` at 8, runs the command in a
  `systemd-run --user --scope` cgroup with `MemoryMax=40G` / swap off
  (self-tested: a 1 GB alloc in a 512 M scope dies with 137), one flock for
  suite-scale runs across all executors, exports `PARCEL_XDIST_WORKERS=8`
  and `PARCEL_PYTEST_GUARD=1`, 30-min `timeout`. Log: `guard.log`.
- A log-only memory monitor in this session (`memwatch.log`, 5 s cadence)
  wakes parcel-6c below 90 GB available. A detached killing watchdog was
  proposed and BLOCKED by the auto-mode classifier; not worked around.
- The recursion itself is fixed by XD-1 (addendum rows A1–A4 below), not
  by the integrator.

### Census at 06:1x (read-only)

HEAD `e15e466`; 55 dirty paths, same set as 05:3x; compiles; no batchb
locks; zero `parcel_robot`/pytest processes; 12 GB used. 41 tracked files
carry mtime 06:04 (Cursor buffer restore at this session's start) and are
git-clean — attribute by content only. HY-1's in-flight restore of
`tests/test_voice_nav_e2e.py` completed (sha `7ee66b03…` = its `.orig`).
Resume points: XD-1 from D2 (+ addendum A1–A4); HY-1 from R5 (R4 MET
05:38:44, R10 none-to-reap); FZ-1 from row 6 (row 5 MET 05:38:05); TRUTH-1
all rows (header stub); ROAM-2 PREREGISTRATION first, then runs, then
status doc. `WAVE3_HW_DESIGN_FABLE.md` stands at §3 (117 lines; §4+ and the
critic pass still owed).

### Anti-crash rules (binding on every executor from this dispatch on)

1. Every pytest invocation goes through `pytest_guard.sh --label <slug>`;
   scripts that run pytest are themselves run under the wrapper.
2. Never `-n auto` / `-n logical` / `-n` > 8 — in commands, scripts, docs,
   or ci_gate defaults.
3. Never `scripts/ci_gate.py --tier …` (any tier, any tree). The commit
   tier is the integrator's, once, at close, tree quiescent.
4. Before a suite-scale run: `free -g` available ≥ 120 and
   `pgrep -fc -- '-m pytest'` ≤ 1, else wait 60 s.
5. Exit 137 / "Killed" = your run exceeded 40 GB: report it, never retry
   bigger. No background pytest (`&`, nohup, run_in_background).

### XD-1 addendum (owner-mandated; PREREGISTRATION.md stays byte-identical)

A1 `fast_commit_tier` stubs `evaluate_default_suite` too; a test proves the
hole (record-and-raise `run_pytest` without the stub) and its closure.
A2 nesting guard: `run_pytest` sets `PARCEL_CI_GATE_NESTED=1` in the child
env; `evaluate_default_suite` refuses (status `error`, detail names the
nesting) when it is set on entry; `_pytest_gate`'s targeted runs stay
allowed nested. A3 worker default `min(cpu_count, XDIST_MAX_WORKERS=16)`,
never `auto`; explicit `PARCEL_XDIST_WORKERS` honoured and logged in the
row detail. A4 D2–D7 run as `-n 8` under the wrapper; each row says so and
wall-clock rows are marked not comparable to P0-E's 51.9 s; a row whose
meaning needs `auto` is NOT MEASURED with the reason.

### Dispatch log (parcel-6c)

* **06:22 EDT 08-23** — all five executors launched concurrently on Opus
  (fifth resume): XD-1 (A1–A4 addendum first, then D2–D7 at `-n 8`), HY-1
  (R1–R3, R5–R9; ≤ 2 sims), FZ-1 (rows 6–11, S1–S5), TRUTH-1 (all rows +
  wheel census), ROAM-2 (PREREGISTRATION → baseline ×3 → coverage; one sim
  at a time in a 12 GB scope). Briefs = the prior fourth-resume briefs +
  the anti-crash rules + each card's exact resume point; saved in this
  session's scratchpad `briefs/*_v5.md`. Verification: one `claude`
  subagent per card as its status doc lands (product-path method, audit of
  `~/.cache/parcel-guard/guard.log` against the status doc's command list).
  GATE-0b still HELD until XD-1 ACCEPT. Memory at dispatch: 12 GB used /
  234 GB available; zero pytest or sim processes.

### Verdicts (parcel-6c)

(filled as each card closes; each entry = verifier VERDICT · status-doc
path · `~/.cache/parcel-verify/<slug>/VERDICT.md` · correction pass if any)
* **06:44 EDT** — FZ-1 executor returned COMPLETE: 11/11 rows MET, S1–S5
  RED→green on a scratch tree, `task_13/FZ1_STATUS.md` 762 lines,
  PREREGISTRATION sha unchanged; 14/14 guarded runs, one suite-scale
  (row 9, 354 passed), no `-n`, nothing left behind. Flags for the
  verifier: S2 reddens as a YAML parse error (S2b added for the digest
  assertion); row 11's 91→100 vs `EXPECTED_ASSET_COUNT` 90→99; §e claim
  is same-arch. Handoff: tree-wide ruff 18 (7 baseline + other cards'
  in-flight debris, zero in FZ-1 OWNS). Rule-4 note: `pgrep -fc -- '-m
  pytest'` counts this session's memwatch monitor; use
  `ps -eo args | grep -c '^[^ ]*python[^ ]* -m pytest'` instead.
  Verifier (claude) dispatched 06:45.
* **FZ-1 — ACCEPT-WITH-NOTES** (verifier `claude`, 06:45–07:00; record
  `~/.cache/parcel-verify/fz1/VERDICT.md`; status doc
  `task_13/FZ1_STATUS.md`). All 11 rows and S1–S5 reproduced by the
  verifier on the product path (`InstructionSource(...).current().si`,
  `PARCEL_ROOT` seam, zero monkeypatch); v1/v2 snapshots byte-identical to
  `e63be08`, v3 to live; no hunk outside OWNS; no re-pin; the +9 packaged
  files are exactly the nine frozen YAMLs; 20/20 verifier runs and 14/14
  executor runs through the wrapper. One docs-only FIX (F1: DESIGN.md §b
  named `schema.py:466`/`build_manifest.py:109` as the historical
  branch's product path — only `freeze_si_version.py --check` calls it)
  + F4 (status doc said one suite-scale run; there were two). Correction
  pass sent to the FZ-1 executor 06:5x (F1, F4 only; F2 markers declined
  — no concurrent writer). Integrator note: S2-as-registered reddens as a
  YAML parse error (loader, not digest); S2b is the digest proof.
* **06:5x EDT** — HY-1 executor returned COMPLETE: 12/12 rows MET,
  `task_15/HY1_STATUS.md` 766 lines, 33 evidence files; R2/R3 measured
  against a real MuJoCo sim on a `git archive HEAD` scratch (741 MB orphan
  pre-fix, 0 survivors post-fix); R6 strengthened with live-process tests
  after seed S3 showed the hand-built owner test was vacuous; setup error
  injected by env only (`PARCEL_MEMORY_PATH` relative). Cross-card
  findings forwarded 06:5x: XD-1's `_repo_write_guard.Recorder._record`
  abspath bug + I001 fingerprint → XD-1 executor; PLW1510 in
  `test_truth1_texts.py` → TRUTH-1 executor. Integrator: conftest.py has
  two marked regions and imports `_repo_write_guard` at module scope —
  XD-1's region and `tests/_repo_write_guard.py` land together or
  collection breaks. Verifier (claude) dispatched.
* **FZ-1 CLOSED 06:58** — correction pass applied (F1: DESIGN.md §b now
  names `freeze_si_version.py --check → rendered_digests:114 →
  frozen_prompt_library` as the only non-test caller, `schema.py:473`
  stays current-only deliberately; F4: status doc says two suite-scale
  runs, 14/14 guarded). No product/test/snapshot byte moved
  (`prompting.py` f5bb7d1a…, `freeze_si_version.py` 64126b53…,
  PREREGISTRATION 8f0e19ee… unchanged). DESIGN.md is 137 lines vs the
  COMMON brief's ≤120 cap (was already 126 before the fix; declared).
  Final: **ACCEPT-WITH-NOTES**, ready for the integrator.
* **07:0x EDT** — TRUTH-1 executor returned COMPLETE: 8/9 rows MET, **R3
  MISS reported as a miss** (registered 0 `Orin` mentions in the realsense
  remedy, measured 1 — pre-declared in DESIGN §(g)1 after the 16:00
  decision made the Orin the deploy host); `task_32/TRUTH1_STATUS.md`
  560 lines; `tests/test_truth1_texts.py` created (15 tests); five seeds
  (seven arms) RED→green; PLW1510 fixed before the note arrived; seven
  suite-scale guarded runs; no sim, no process signalled; a 70 GB scratch
  tree created and removed. Five files outside the README OWNS (claimed
  pre-registered/forced) — verifier checks each. **Standing rule added
  (TRUTH-1 finding):** a byte-identical scratch copy still imports
  `parcel_robot` from the working tree through the editable `.pth`; any
  `src/` seed in a scratch tree must run with `PYTHONPATH=<scratch>/src`
  and verify `parcel_robot.__file__` is inside the scratch (FZ-1's
  verifier did exactly this; TRUTH-1 ran S4/S5 in the working tree inside
  the flock instead — its verifier confirms the byte-identical restore).
  Verifier (claude) dispatched.
* **07:1x EDT** — ROAM-2 executor returned COMPLETE: `task_33/
  PREREGISTRATION.md` written first (baseline registered before any
  coverage run; ceiling §6.1a registered before either arm), then 3+3
  product-path runs (`submit_realtime_transcript('Go explore.')`, one sim
  at a time in the 12 GB scope, ledger redirected, owner store sha
  unchanged 10/10). **T1 (≥1.5× baseline) MISSED — CEILING:** C1 = 1.0
  (50/50) in all six runs because every learned-map entry lies within
  7.1 m of home and the map's visibility rule is 8.0 m. T2–T6, R6, R7
  MET; coverage legs 7/8/7 vs 0/0/0. Product finding (handoff H2): the
  objective costs travel (net in-block 1.4–1.8 m vs 3.6–6.5 m baseline)
  — `exclude_visible` leaves zero candidates in 351/468 samples and
  least-recently-seen becomes a homing signal on a home-clustered map.
  Inherited draft had coverage ON by default at two layers; now OFF at
  all three (arm A: `coverage.enabled` true in 0/468 samples). All hunks
  inside marked regions. Seeds valid only under `PYTHONPATH=<scratch>/src`
  (stated, verified). Verifier (claude) dispatched.
* **07:2x EDT** — XD-1 executor returned COMPLETE: addendum **A1/A2/A3
  MET** (fixture stubs `evaluate_default_suite`; `run_pytest` sets
  `PARCEL_CI_GATE_NESTED=1` and `evaluate_default_suite` refuses inside
  it; workers = `min(cpu_count, 16)`, never `auto`), A1's seeded-RED
  caught the exact crash launch (`-n 8 --dist loadfile`, whole suite,
  from inside a test) without paying for it; W1 385.3 s serial, **W2
  75.3 s (≤ 90) MET**, **W3 5.11× (≥ 4.5) MET** at `-n 8` (not comparable
  to P0-E's 51.9 s), **W4 NOT MEASURED** (rule 3); D2–D5 MET (zero
  divergence ×3 runs, serial, shuffled); D6/D7 published (guard ships
  OPT-IN per the pre-registered rule; pre-fix census withdrawn after the
  `_repo_write_guard` dir_fd/symlink fix HY-1 reported); L1 7/7
  fingerprints; S1–S5 as registered; ten seeded-RED proofs.
  `task_14/XD1_STATUS.md` 763 lines; PREREGISTRATION sha unchanged; 13
  suite-scale guarded runs tabled. Cross-card: `test_ci_gate.py:649`
  literal 91 → RED (FZ-1's +9) — routed to the FZ-1 executor as a two-line
  fix (→ 100). Integrator musts: `tests/conftest.py` +
  `tests/_repo_write_guard.py` land in ONE commit; both `ci_gate.py` hunks
  in marked regions → **GATE-0b unblocked pending XD-1's verdict**.
  Verifier (claude) dispatched.
* **07:1x EDT — FZ-1 parity literal fixed:** `tests/test_ci_gate.py:648-649`
  (91 → 100, comment attributes FZ-1's nine frozen snapshots); 11 passed
  through the wrapper (07:10:19–21); premise confirmed red first
  (`assert 100 == 91`). Declared as FZ-1 deviation 8 (XD-1's file, two
  lines, on integrator instruction, no concurrent writer). Integrator:
  the hunk is FZ-1's but lives in XD-1's file — commit with XD-1's.
  Row 11 gap on record: the gate's own `extra["checked"]` was a third
  literal pinning the same fact and row 11's table missed it. Tree-wide
  ruff now 12 (XD-1 cleaned its 6). FZ-1 guard ledger 16/16. **FZ-1
  fully closed.**
* **HY-1 — ACCEPT-WITH-NOTES** (verifier `claude`, ~07:00–07:18; record
  `~/.cache/parcel-verify/hy1/VERDICT.md` + `seeds/W1..W14.txt`,
  `lens3_*`). No HOLD, no FIX. All 12 rows reproduced on the product
  path: R2 pre-fix fixture on a scratch leaves one real MuJoCo survivor
  (733 MB, reparented to systemd); R2c the shipped guard names
  test/pid/socket and reaps it; R3 zero survivors; R8 real
  `launch_sim.sh --pidfile` lifecycle in a 12 G scope; R11 HY-1 conftest
  region sha `259937b0…` re-derived before and after XD-1's 07:03 edit.
  Adversarial ownership probe: four stand-ins launched outside pytest
  (pre-session stranger, owner-argv decoy, foreign socket, basetemp
  socket) — only the last was reaped, attributed by time window; the
  decoy cannot create the owner socket or listen on :8765. 14 seeds RED
  on scratch; W1 confirms S3 (only the live-scan test catches deletion
  of the owner check). Bonus: a leaky module at `-n 2` is caught inside
  worker gw0. Notes N1–N9 docs-level; correction pass (ledger row, R9
  refresh, N2/N3 wording) sent to the HY-1 executor 07:2x.
* **TRUTH-1 — ACCEPT-WITH-NOTES, correction pass required (6 FIX, 0
  HOLD)** (verifier `claude`, ~07:05–07:22; record
  `~/.cache/parcel-verify/truth1/VERDICT.md`). R1/R2/R4–R9 re-measured
  MET with the registered commands (R4 exit 3, 7 "NO DEVICE (installed:
  pyrealsense2)"; R6 02 diverges 172.4 ms; R7 lane True / ws False; R9
  through `ConfigStore` + `build_runtime` with a real overlay, zero
  monkeypatch, `plan_timeoutt` refused by name); **R3 MISS (1 vs 0)
  stands**; working tree's seven seeded files restored byte-identically;
  S4 + S2c re-run on an import-verified scratch. FIX: F1 `probe_d455`
  (`preflight.py:3259-3267`, on the product path via `run_preflight:3717`)
  still tells an installed box to install pyrealsense2 — unmeasured
  second remedy; F2 the R9 typo guard is pinned as a function, not as
  wired into `build_runtime`; F3 `ingest/realsense.py:271-272` comment
  quotes the stale strings; F4 `preflight.py:68` "no aarch64 build" is
  false; F5 `clockmap.py:2601-2602` JetPack-6 claim unsupported and
  contradicts `record.py:1397`/`dds.py:731`; F6 handoff 4 lacks
  file:line. **R3 owner decision (verifier + integrator recommend):
  accept the miss with the reason** — the Orin is the real second host,
  the count is pinned at exactly 1, 0 is reachable only by synonym.
  Correction pass (F1–F6 + wrap the `build_runtime` hunk) sent to the
  TRUTH-1 executor 07:2x; re-verify F1/F2 narrowly after.
* **HY-1 CLOSED 07:19** — correction pass applied, docs only (N1 ledger
  row; N4 R9 rewritten as three dated ruff measurements, 07:16 = exactly
  the 7 baseline fingerprints; N2 scope note: fixture + two log hooks,
  DESIGN §(b) supersedes README's "one autouse fixture"; N3 declined as
  code, fixed in DESIGN §e with the two prose lines `_sim_guard.py:385,
  387` on the future pattern-table card's checklist). Five code/tool
  files at their measured hashes; guard ledger 36 lines, none new.
  Integrator budget note: the guard costs ≈ 2 s wall at `-n 8`. Final:
  **ACCEPT-WITH-NOTES**, ready for the integrator.
* **07:3x EDT — TRUTH-1 correction pass COMPLETE:** F1 `probe_d455` now
  two branch-specific remedies via `_unavailable_device_reader(
  remedy_when_present=…)` (default unchanged for go2/l2/uwb), pinned +
  seed S6 RED; F2 two `build_runtime`-level overlay tests (env-var
  monkeypatch only), seed S7 (= verifier's S5b) RED; F3/F4 stale
  strings → 0; F5 `_ORIN_ROS2_REMEDY` reworded UNCONFIRMED; F6 handoff
  table with file:line; `build_runtime` hunk fenced. 392 passed (one
  suite-scale guarded run; pre-flight 233 GB / 0 roots); ruff clean on
  twelve files, tree-wide 12 (none TRUTH-1's). Seeds S6/S7 on an
  import-verified scratch (`seeds2.sh` refuses to seed unless
  `web_panel.__file__`/`preflight.__file__` are inside it) — executor
  corrects its earlier "clone finding": the failure was cwd-only, not a
  property of clones. R3 remains a MISS (1 vs 0), reason recorded.
  Narrow re-verify of F1/F2 sent to the TRUTH-1 verifier 07:3x.
* **XD-1 — ACCEPT-WITH-NOTES** (verifier `claude`, ~07:25–07:43; record
  `~/.cache/parcel-verify/xd1/VERDICT.md`). **Recursion closed by
  construction:** A1 `test_ci_gate.py:924-928` (fixture stubs
  `evaluate_default_suite`; stub deleted → tripwire recorded the exact
  crash launch `-n 8 --dist loadfile`, whole suite, RED in 0.18 s with
  no suite started); A2 `ci_gate.py:559` stamp + `:739-747` refusal
  (hard `error` row before any subprocess); A3 `:662`
  `XDIST_MAX_WORKERS = 16` + `:665-699` (default never `auto`; explicit
  `PARCEL_XDIST_WORKERS=auto` → 16 and logged; only an explicit integer
  exceeds 16). Product path: no env → `-n 16`; `=8` → 8; nested →
  refused. D1 re-run 9325+10, A∩B=∅; W/D rows re-derived from the rig's
  evidence (W2 75.3/74.8/77.1 s at 8 workers; zero diffs over 9329 ids);
  L1 7/7; HY-1 region sha intact; 36 xd1 wrapper runs, zero `-n` on any
  command line. **Bounded claim:** non-divergence proved at 8 workers;
  the gate's default here is 16, unmeasured. FIX: F1 a THIRD `ci_gate.py`
  hunk (`run_commit_tier` default-suite row `:1971-1977`) is unmarked —
  mark it; F2 `.hypothesis` in `_HOT_SKIP` is red on a fresh clone until
  hypothesis writes its own ignore file — one root `.gitignore` line
  (integrator-authorised); F3/F4 docs. Correction pass sent 07:44;
  **GATE-0b dispatches when it returns** (both edit `ci_gate.py`).
* **ROAM-2 — ACCEPT-WITH-NOTES** (verifier `claude`, ~07:15–07:45;
  record `~/.cache/parcel-verify/roam2/VERDICT.md`). **T1 stays MISSED —
  CEILING, genuine:** seed map `46d3c465…` 50 entries, farthest 7.09 m;
  `DEFAULT_VISIBILITY_RANGE_M = 8.0` (`online_map.py:99`, applied
  `:771-778`); `city_block.xml` has all 74 bodies within 8.7 m of the
  origin — no seed map or scene in the tree gives headroom. Registration
  integrity proven from the executor transcript (§6.1/6.1a filled 14 s
  before A1, §6.2 11 s before B1; no re-cut). Defaults OFF at all three
  layers proven against HEAD (identical command sequences, 5 scenarios ×
  400 ticks). Verifier's own runs: VA net 6.489 m, `enabled` 0/468; VB
  net 2.166 m, `enabled` 468/468, zero-candidate 288/468. **Owner
  finding:** with the objective on the dog never exceeds 2.45–3.16 m
  from home (baseline reaches the 10 m tether); attributed to
  `exclude_visible` (`online_map.py:1151,1161` → `runtime.py:5196-5210`
  → `mission.py:586-627`); re-sighting fraction identical in both arms
  (0.88 vs 0.84). FIX: F1 README's dynamic-city arm never run; F2
  `runtime.py:5212` `# noqa: BLE001` violates the never-noqa rule.
  Correction pass (3 × dynamic-city runs reported not gated as §6.5;
  narrow the except, no noqa) sent 07:46.
* **TRUTH-1 CLOSED 07:5x — FINAL ACCEPT-WITH-NOTES** (re-verify appended
  to `~/.cache/parcel-verify/truth1/VERDICT.md`, 218 lines). F1 both
  preflight branches rendered through the real `main()`, stale string
  0/0, the 41 non-D455 remedy lines identical to HEAD's rendering, S6
  RED→green on an import-verified scratch; F2 S5b now reddens the
  `build_runtime` overlay test; F3–F6 closed; ruff clean, no noqa, 392
  passed. New non-blocking NOTEs N10 (`preflight.py:3284-3285` comment
  quotes the retired sentence split across lines) and N11 (five
  `preflight.py` hunks attributed by inline comments, not fenced — no
  concurrent writer). **Owner decision pending: R3 MISS (1 vs 0)** —
  verifier + integrator recommend accept-the-miss-with-the-reason.
* **XD-1 CLOSED 07:50 — ACCEPT-WITH-NOTES.** Correction pass: F1 third
  hunk fenced (`CARD XD-1` markers at 551/560, 603/791, 1971/1986);
  F2 `.hypothesis/` in root `.gitignore` (own comment line — a trailing
  `#` is not a comment in `.gitignore`, caught by the seed staying RED),
  integrator-authorised deviation; F3 D2 now says: clean at `-n 8`,
  default here 16 unmeasured, 8 is the Orin's default; F4 stale comment
  fixed. 114 passed (91 + 23). Tree 60 dirty paths. **GATE-0b dispatched
  07:5x** on Opus with its own exception to rule 3: the gate runs only in
  its clean clone, only through the wrapper (8 workers, 40 GB cgroup,
  flock), at most three times.
* **08:0x EDT — ROAM-2 correction pass COMPLETE.** F1 §6.5 dynamic city
  (registered after the static rows, §1–§6.4 unchanged): coverage-true
  ×3 net 0.215/1.219/2.004 m, legs 2/3/7, **contacts 37/15/21, clearance
  0.0**, max radius 1.16–2.04 m; coverage-false control ×3 contacts
  14/12/6, 0 legs, `enabled` 0/468, max radius 2.53–2.62 m; ROAM-1's own
  dynamic run had 24 contacts / 0.0 clearance — contacts are a
  dynamic-city property predating the card; higher median with coverage
  on (21 vs 12) recorded as an open question on a bimodal input. F2
  `noqa` removed: `except (ArithmeticError, AttributeError, LookupError,
  OSError, RuntimeError, TypeError, ValueError)` — the shape of the
  control thread's own boundary at `runtime.py:10254`; `_step_roam`
  (`:10347`) sits outside that boundary so an escaping exception would
  kill the 10 Hz thread. 26 + 268 passed; zero suppression directives
  added by the card; 16 sim runs total, one at a time, owner store and
  nav ledger sha unchanged 16/16. Narrow re-verify of the except
  coverage + §6.5 sent to the ROAM-2 verifier.
* **ROAM-2 CLOSED 08:0x — FINAL ACCEPT-WITH-NOTES** (re-verify appended
  to `~/.cache/parcel-verify/roam2/VERDICT.md`, 153 lines). The except
  tuple covers every exception the in-memory query path can raise under
  `_p1b_map_lock` (`runtime.py:5197-5211`, `online_map.py:1102-1200`) and
  is a strict superset of the control thread's own boundary (now
  `:10296`; `_step_roam` at `:10387` outside it; `_control_loop` :10203
  `try/finally`, no except); no `noqa` in any ROAM-2 hunk (file count
  back to HEAD's 63); §6.5 registered 07:47 after both dynamic batches,
  §1–§8 byte-identical to the first-pass sha save the requested F15
  sentence; 26 passed. NOTE for a future store-backed query: add
  `sqlite3.Error` to the tuple. Open (non-blocking, handoffs): H2 the
  homing objective; T1 measurability (scene or re-sighting metric); H4
  CURIO-1 remarks per leg.

**Batch B status 08:0x:** FZ-1, HY-1, TRUTH-1, XD-1, ROAM-2 all
ACCEPT-WITH-NOTES and closed. Owner decisions pending: TRUTH-1 R3 (accept
the miss); ROAM-2 T1 ceiling + the travel-cost finding (H2). GATE-0b
running.
* **08:3x EDT** — GATE-0b executor returned COMPLETE: clean clone
  (`e15e466` + all dirty paths committed in the stage only, re-cloned,
  CPython 3.12.13, `pip install -e '.[dev,voice]'`) → **R2 `RESULT:
  PASS`, 10/10 hard gates, 86.6 s, skip-list row prints 4 declared
  external roots absent → 16 modules skip with a named reason** — run
  through the wrapper **under `taskset -c 0-7`**. R1 (same clone,
  unconstrained, 192 threads) = FAIL on one test,
  `test_dynamic_costs.py::test_cost_field_vectorization_performance`
  (R26's documented open risk; fails on HEAD standalone; skips wherever
  the load ceiling is reachable — hosted runner, Orin, or 8 CPUs).
  Baseline re-count 48 (not 51; pre-registered as possible) → 1. V9
  decision: mode-bit requirement dropped for the TRACKED manifest
  (sha256 is the stronger pin), kept for generated corpora. Seeds S1/S2
  RED→green on the clone. Exactly 3 gate runs, 39 guarded runs, no
  `-n auto`, no 137. Deviations (8): files outside OWNS (`generate_…
  v9_training.py`, `scripts/future_clock.py` — inoperative on 3.12 in
  two ways (H5), three non-external test files, **TRUTH-1's
  `test_truth1_texts.py`**, new `tests/_external_roots.py` with 17
  importers); FOUR `ci_gate.py` hunks not one; DESIGN.md 165 lines.
  Tree now 91 dirty paths (11 evidence files un-ignored — integrator
  must `git add` them with the two `.gitignore`s). Verifier (claude)
  dispatched.
* **GATE-0b — ACCEPT-WITH-NOTES, correction pass (2 docs FIX)** (verifier
  `claude`, ~08:35–09:00; record `~/.cache/parcel-verify/gate0b/
  VERDICT.md`). Registration 26 s before R0; 48-row table re-derived
  from R0 outputs (51 − 6 + 2 + 1); V9 sha256 pin present, no frozen
  manifest byte changed; seeds S1/S2 RED→green on a scratch clone; CLI
  arms A–F as designed (default unchanged; `--no-ledger` appends
  nothing; pytest guard withholds by name); 39 guarded runs, exactly 3
  gate runs, all in the clone. **Decision 1: PASS-under-affinity is
  honest** — the skip is the load guard's own rule (`sched_getaffinity`)
  and fires the same way on `ubuntu-latest`/Orin; R1/R2 side by side in
  §5; H1 attributed to R26 — but the headline omits the `taskset`
  qualifier (F1). Decision 2: the edit to TRUTH-1's closed file is three
  bare skip lines, every pin intact (18/18) — NOTE, but the "fenced"
  claim is false (F2). Verifier's own constrained gate run: FAIL on one
  row — `tests/test_realtime_ws_transport.py:220-241`, a **pre-existing
  HEAD flake under 8-CPU contention** (failed 1 of 2 re-runs; 6/6
  standalone; absent from R2) — handoff N6, not GATE-0b's. Integrator
  list in the VERDICT: 11 evidence files (64 KB) + the two `.gitignore`s
  in one commit; `tests/_external_roots.py` + 16 importers; never add
  `.cache/external-evals`, `results/runs/`, `latest_report.json`, the
  ledger, any `.venv`. Correction pass sent 09:0x.
* **GATE-0b CLOSED 09:1x — ACCEPT-WITH-NOTES.** Correction pass: headline
  carries `taskset -c 0-7` in the first sentence with R1's FAIL block
  beside R2; TRUTH-1's three skip lines fenced (18 passed, `ast.dump`
  identical); N3/N4 wording; N5 marker; H9 = the `ws_transport` loopback
  flake (`SETTLE_S = 5.0`, R1.5/TURN-1–DUPLEX-1 area, `ubuntu-latest`
  2–4 vCPU risk). 92 dirty paths before and after. **Batch B + GATE-0b:
  six cards, six ACCEPT-WITH-NOTES, zero HOLD.**

### Integrator close (parcel-6c)

* **09:1x** — tree quiescent (all agents returned; zero pytest/sim
  processes; no batchb locks). Commit path list (116 files, no
  pycache/venv/ledger) and message drafted in the session scratchpad.
  Running the commit tier ONCE in the working tree through the wrapper
  (`PARCEL_XDIST_WORKERS=8`, 40 GB cgroup, TMPDIR unset).
* **09:13 — COMMIT TIER GREEN in the working tree.** `scripts/ci_gate.py
  --tier commit --json` through the wrapper: **10/10 HARD PASS, rc 0,
  92 s** — ruff 7/7 baseline new 0; unitree-assets pin ae6a8403e272;
  hard-safety (nav baseline v4 collisions 0, mutation panel clean,
  follow-bench 7 rows all 0); release-parity 100 assets; assertion-evals
  20 pinned findings; tier-coverage 9512 = 9431 + 81; model-off 23;
  parity-integrity 10; owner-store-isolation 6; **default-suite `-n 8
  --dist loadfile [PARCEL_XDIST_WORKERS=8 (honoured; cpu_count=192,
  cap=16)]` parallel 63.0 s 9403 passed / 17 skipped / 1 xfailed, serial
  8.2 s 9 passed**; soft skip-list: 4 roots declared, 0 absent here.
  Host never below 228 GB available all morning. JSON copied to
  `task_30/evidence_integrator_gate_20260823T0912.json`.
* **Ready to commit, waiting for the owner's word** ("commit and upload"
  goes to this session): 116 paths (list in the session scratchpad,
  `commit_paths.txt`; no pycache/venv/ledger/`.cache`), message drafted
  (`commit_message.txt`); after the commit: `tools/codebase_index.py`
  (index is STALE by `--check`) → amend or second commit → push.
  Owner decisions that do not block the commit: TRUTH-1 R3 (accept the
  miss, recommended), ROAM-2 T1 ceiling + travel-cost finding (H2), the
  board rows for the six cards (GATE-0b's qualified row text is in its
  status doc §11).
