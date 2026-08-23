# HW-8 `box-day-runbook` — STATUS

**Card:** `README.md` (same folder) · **Executor:** Claude Opus (wave 3a,
first dispatch) · **Verifier:** Fable · **Date:** 2026-08-23, 13:0x–13:5x EDT
· **Tree at start:** HEAD `939001e` (batch B **committed**; the dispatch
record's `e15e466` is stale), four peer wave-3a executors live.
**Docs only — no product code was touched, no hardware, no pytest, no sim.**

## Headline

The four documents exist and every command in them was run on this host and
exited 0. **21 of 22 pre-registered rows MET**; the one miss (H2) is a
pre-registration defect of mine, not a finding — I wrote a threshold that a
shared working tree cannot satisfy, and the substance behind it holds.
`docs/BOX_DAY.md` is **2,136 words** (cap 2,500; ~8½ min at 250 wpm).
Owner time: **first two hours = 95 min** (cap 120), **everything the owner
must be present for = 300 min = 5.0 h** (cap 480, PO-1's 6–8 h).

**Three commands the design document spells do not exist**, and none of them
was invented into a document. They are handoffs, below.

## What changed

All five files are new; nothing tracked was modified
(`git diff --stat -- docs/ scrum/20260822/task_39/` is empty because every
path is untracked).

| New file | Lines | Work item |
|---|---:|---|
| `docs/BOX_DAY.md` | 204 | 1 |
| `scrum/20260822/task_39/DESIGN.md` | 145 | order-of-work |
| `scrum/20260822/task_39/PREREGISTRATION.md` | 68 | order-of-work |
| `scrum/20260822/task_39/STAGE0_RUN_SHEET_EDU_PLUS.md` | 824 | 2 |
| `scrum/20260822/task_39/SUPPORT_TICKET_UNITREE.md` | 123 | 3 |
| `scrum/20260822/task_39/UNKNOWNS_REGISTER.md` | 57 | 4 |

`PREREGISTRATION.md` sha256 (unchanged since it was written, before any
measurement):
`f953cf43de8ddcb9759530324a901cd5af7035c63322e26438ab12f906d441fe`.

The 08-13 sources are byte-unchanged:
`scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md` sha256
`f874ed46e7456b2f9fcf34622ea2601dc116d83e65310e79347b71021b4b3df7`;
`git status --porcelain -- scrum/20260813/ scrum/20260822/task_27/
docs/MOTION.md scrum/20260805/` is **empty**.

## How verified

### A · Command-exists rows (Work 5) — the ledger

Every invocation below was run from the repo root with `TMPDIR` unset, via
`.parcel/bin/python`, and **opened no device** (`--help` only; the XVF3800
opens only under `--rms`, which was never passed).

| Row | Command | rc | Verdict |
|---|---|---:|---|
| C1 | `-m scripts.parcel_capture.attest --help` | 0 | **MET, spelling corrected** |
| C2 | `-m scripts.parcel_capture.record --help` | 0 | **MET, spelling corrected**; `--plan` / `stage0` / `--dry-run` → 0 hits |
| C3 | `-m parcel_robot.unitree_control --help` | 0 | **MET, spelling corrected** — subcommands `{observe,run,review,apply}` |
| C3b | `-m parcel_robot.unitree_control observe --help` | 0 | MET (`--min-samples`, `--timeout`, `--out`) |
| C4 | `-c "import …preflight as p; assert callable(p.probe_builtin_lidar)"` | 0 | **MET** — and the CLI exposes `--builtin-lidar-model` (2 hits in `--help`) |
| C5 | `tools/xvf3800_probe.py --help` | 0 | **MET** — no device opened |
| C6 | `-m parcel_robot.cli --help` | 0 | MET; **not cited** in either document (no box-day step needs it) |
| C7 | `-m scripts.parcel_capture.orin_rehearsal --help` | 0 | **MET** — `--evidence-dir`, `--record-target`, `--firmware-attested`, `--until {p0_identity…p5_recorder}` all present |
| C8 | `-m scripts.parcel_capture.preflight --help` | 0 | **MET, spelling corrected** |

**Negative checks (the ones that matter):**
`grep -c 'parcel-capture *=' pyproject.toml` → **0**;
`grep -c 'parcel-commission' pyproject.toml` → **0**;
`record --help | grep -cE -- '--plan|stage0|--dry-run'` → **0**.

**Unregistered checks, declared.** Six further modules were `--help`-checked
in the same pass and all exited 0: `stage0_addendum`, `syncevents`,
`budget`, `clockmap`, `sidecar`, `rehearse`. `PREREGISTRATION.md` §A says a
command beyond C1–C8 is added to that file **before** it is checked; I
checked these first and then chose to leave the pre-registration
**byte-identical** rather than amend it after the fact. They weaken no row
and lower no threshold; they are extra evidence, and they are declared here
so the ledger and the file disagree in the open. **Recorded as deviation D3.**

### B · Cross-reference rows

| Row | Result | Evidence |
|---|---|---|
| X1 | **MET** | all 13 §7 ids present in `docs/BOX_DAY.md` (B9, B-fw, S20, Q-dev, Q-lidar, Q-wire, Q-usb, B11, B12, S19, Q-stop, Q-ort, Q-link); one added step **B0** (stand + preconditions + `mkdir -p ~/Parcel/hw`), marked as added |
| X2 | **MET** | all three §7.2 options present, "owner-decided", and the default (i if the BSP exists, else ii with perception off-dog) |
| X3 | **MET** | `scrum/20260822/task_27/README.md` cited ×2; `MOTION.md:441-442` ×2; "before any `--arm`" present; the four armed-step preconditions are their own section |
| X4 | **MET** | `0002-firmware-pin.md` cited; ≥ 1.1.13 ×3; OTA-off in the preconditions **and** in S20; CVE-2026-27509 "no known patched version" stated, with the explicit sentence that the pin is therefore **not sufficient** |
| X5 | **MET** | all five preconditions present as a hard bar, OTA-off worded "BEFORE the dock joins any network" |
| X6 | **MET** | B-fw is step 2, before any WAN step; carries default-drop forwarding, DDS multicast confined to the robot NIC, no default route, Mid-360 static `192.168.1.5` with no gateway, panel `127.0.0.1` + tailnet (ADR 0002 item 4) |
| X7 | **MET** | 9 × `[documented]`, 4 × **UNCONFIRMED**, each UNCONFIRMED naming its resolving step on the same line (JetPack→B9+ticket, M8/Mid-360 wiring→Q-wire, head model→Q-lidar, USB-C count→Q-usb) |
| X8 | **MET** | 16 rows, all 16 §8 ids, every `resolves on` and `blocks` cell non-empty (five rows say "nothing", with the reason) |
| X9 | **MET** | 18 × `<!-- HW-8: was …` comments; source byte-unchanged by sha256; link rebase declared once in the banner rather than commented 31 times |
| X10 | **MET (read the note)** | Q-jp, Q-wire, Q-fwv, Q-dev, Q-usb/Q-pwr and Q-lidar are numbered questions 1–6; the **unknown ids are in the mapping table**, not in the outgoing message — a support agent has no idea what "Q-jp" means, and putting internal ids in a customer email would be worse. Verifier may rule this a partial |
| X11 | **MET** | each of the 13 steps names exactly one result file under `hw/`; B9 names `hw/B9_identity.txt` and notes the harness *additionally* leaves `hw/p0_identity.json` |

### C · Budget and readability

| Row | Measured | Threshold | Result |
|---|---:|---|---|
| W1 | `wc -w < docs/BOX_DAY.md` = **2,136** | ≤ 2,500 | **MET** (prose count with table pipes stripped: 1,999) |
| T1 | first-two-hours sum = **95 min** | ≤ 120 | **MET** (15+10+15+10+10+10+15+10, re-summed from the rendered table by script) |
| T2 | owner-present total = **300 min (5.0 h)** | ≤ 480 | **MET** (95 first two hours + 205 later: B11 30, B12 20, S19 15, Q-stop 10, Q-link 10, Q-batt 15 attended, first armed step 45, first leashed follow 60). Q-ort and HW-10/HW-11 excluded and marked *engineer, owner not present* |

### D · Hygiene

| Row | Result |
|---|---|
| H1 | **MET** — the only paths this card created are `docs/BOX_DAY.md` and `scrum/20260822/task_39/*`; `scrum/20260813/`, `task_27/`, `docs/MOTION.md`, `scrum/20260805/` all show 0 in `git status --porcelain` |
| H2 | **MISS AS WRITTEN — pre-registration defect.** I registered "`git status --porcelain -- src/ scripts/ tools/ tests/ configs/ pyproject.toml` is empty at close". It shows 15 paths, and **every one of them belongs to a live peer**: `bridge/timing.py` + `tests/test_hw6_stopping_envelope.py` → HW-6; `src/parcel_robot/lidar/` → HW-3; `tests/test_hw1_py310_clean.py` + the eleven `datetime.UTC`/`typing.Self` sites (`runtime.py`, `camera_channel/backends/physical.py`, `online_map/store.py`, `owner_tracking/gallery.py`, `perception_daemon/{client,server}.py`, `context/{builder,models}.py`, `observability.py`, `providers.py`, `bridge/client.py`) → HW-1's sweep, exactly the design §2 item 8 list plus the "sweep needed" extras. The row was unmeasurable in a tree shared with four executors and should have read "no path this card touched". Substance holds: this card ran no command that writes under `src/`, `scripts/`, `tools/`, `tests/`, `configs/` or `pyproject.toml` |
| H3 | **MET** — `ps -eo args \| grep -c '^[^ ]*python[^ ]* -m pytest'` = **0** at close (note for the verifier: `pgrep -fc -- '-m pytest'` returns 2 and both are *this session's own bash wrappers* whose command line contains the literal string — the `ps` form is the dispatch's canonical check and is the one that means anything). This card ran **no** pytest at all, started no process, took no lock, and used git read-only (no `add`/`commit`/`stash`/`checkout`). `tools/list_parcel_procs.py`: "No parcel_robot.sim process is running on this host." |

## What this does not prove

- **Nothing about the hardware.** Every claim in the runbook that concerns
  the dog is either `[documented]` (someone else's URL) or **UNCONFIRMED**.
  This card measured *the repository*, not the robot. A verifier who reads a
  green status doc here as evidence about the Go2 has made exactly the
  batch-A mistake the audit named.
- **`--help` exiting 0 is not "the command works on the Orin."** It proves
  the spelling exists and the module imports on **this** host (x86, CPython
  3.14). Whether it runs on aarch64 CPython 3.10 is HW-1's and HW-7's
  question, and whether it reaches a device is the box-day rail's.
- **The runbook has never been walked.** Its step ordering is a design claim,
  its minute estimates are estimates by someone who has not opened the box,
  and the first real session will find something wrong with it. That is
  expected and is why every step writes a file.
- **The run sheet's budget numbers are the 08-13 desktop-dock numbers.** The
  recorder now runs on the robot's own Orin; storage, thermals and USB
  bandwidth are different quantities and are flagged in the sheet's §12 as
  needing re-measurement, not carried forward as true.

## Deviations

**D1 — the run sheet's base file.** The card says to copy
`scrum/20260813/task_1/PHYSICAL_SESSION_PLAN.md`. That file is the 08-13
*verdict on Sol 5.6 plus the day's board* — it is not a run sheet and has no
procedure to follow. The actual Stage-0 run sheet is
`scrum/20260813/task_1/session/STAGE0_RUN_SHEET.md` (727 lines: run header,
roles, stop bars, three named branches, checkbox instantiation, take script,
teardown). I based the rewrite on that, because the card's own Work-2
sentence says "Rewrite the Stage-0 run sheet" and design §7's B12 row says
"the 08-13 Stage-0 run sheet rewritten for EDU+". **Both** 08-13 files were
copied and neither was edited. Reported for the verifier to accept or send
back.

**D2 — order of work.** Work 5's command cross-check was measured **after**
`PREREGISTRATION.md` was fixed (sha above) and **before** `docs/BOX_DAY.md`
was written, rather than last. Reason: writing the runbook first would have
meant writing command lines I had not yet verified, and then editing them
out — which is how an invented command survives into a document. The rows
were pre-registered as written; only the writing and the measuring swapped
order, in the safe direction. Declared in `DESIGN.md` §8 before any
measurement ran.

**D3 — six unregistered `--help` checks.** See §A above. The
pre-registration was left byte-identical rather than amended after the fact.

**D4 — `docs/` and the batch-B COMMON brief.** That brief says executors
"never touch `docs/`". This card's OWNS explicitly names `docs/BOX_DAY.md`
(new), as does the board row and design §9. I read the standing rule as
protecting *existing* docs from drive-by edits, and created exactly one new
file there, touching no other. No existing file in `docs/` was opened for
writing (`git status --porcelain -- docs/` shows only `?? docs/BOX_DAY.md`).

## Owner-gated rows

Nothing in this card runs without the owner, and two things need the owner
*now*, before delivery:

1. **Send the ticket** — `SUPPORT_TICKET_UNITREE.md`, three bracketed fields
   to fill ([ORDER REF], [DATE], [NAME]), then write the reference in its
   log block. Five of the sixteen unknowns are answerable this way and only
   this way before the box exists.
2. **Read and sign `docs/BOX_DAY.md`** — the sign-off line is the last line
   of the file. Design §9's acceptance for this card is "owner read and
   signed; ticket reference recorded", and **both are still open**; this
   card cannot close them.

Not needed now, needed before the first armed step: **PO-1's e-stop record**
(`task_27/README.md`) with the `MOTION.md:441-442` waiver if the choice is
the remote plus a leash.

## Handoffs — commands that do not exist

| # | Command as the design spells it | Reality | Handoff |
|---|---|---|---|
| **HO-1** | `parcel-capture <anything>` | not a console script; `pyproject.toml [project.scripts]` has only `parcel-agent`, `parcel-sim`, `parcel-control`, `parcel-panel`, `parcel-unitree-control`. The tools are `python3 -m scripts.parcel_capture.<module>` | **No code needed.** Both documents use the module spelling. Design §7's table should be corrected — **owner of the fix: whoever next edits `WAVE3_HW_DESIGN_FABLE.md` §7** (Fable). If a console script is genuinely wanted, no wave-3 card owns `pyproject.toml` after HW-1 closes |
| **HO-2** | `parcel-capture record --plan stage0 --dry-run` | `record.py` has **no** `--plan`, **no** `stage0`, **no** `--dry-run`. Nearest real capability: `record --check` (per-channel live-source readiness + free space, then exit) and `record --verify <bag>.mcap` (read back), with the `ros2 bag record` argv rendered by `stage0_addendum --distro <d> --emit-distro` — the repo's single argv truth | **B12 is written entirely from what exists**, so no card is blocked. If a named stage-0 plan selector is still wanted, **no wave-3a card owns `scripts/parcel_capture/record.py`** — this needs a new card (suggest wave 3b, alongside HW-2/HW-5), and I did not invent one |
| **HO-3** | `parcel-commission observe` | does not exist in any spelling. The real command is `parcel-unitree-control observe` (`python3 -m parcel_robot.unitree_control observe`), a console script that **is** in `pyproject.toml`, with `{observe,run,review,apply}` | **No code needed** — spelling corrected in both documents. Design §7's S19 row should be corrected by the design's owner |
| **HO-4** | the run sheet's take/channel rows still carry an **add-on L2** concept in the 08-13 *sources* it links (`CHANNEL_MATRIX.md`, `TAKE_SCRIPT.md`) | those files are 08-13's and out of this card's OWNS; the rewritten sheet re-labels rows 10/11 to the Mid-360 and says so | **HW-3** owns retiring the unilidar/L2 path in `capture/channels.py`; the 08-13 *documents* stay as the historical record and are not edited |

## What the verifier should look at first

1. **D1** — whether basing the rewrite on `session/STAGE0_RUN_SHEET.md`
   instead of the file the card literally names is accepted. Everything in
   Work 2 rests on it.
2. **The negative results.** Re-run the three greps
   (`parcel-capture *=`, `parcel-commission`, `record --help | grep -E
   -- '--plan|stage0|--dry-run'`) and confirm all three are 0 — then confirm
   that **neither document contains any of those spellings outside an
   explicit "does not exist" note**. That is the single failure mode this
   card exists to prevent.
3. **X7 and the tag discipline.** Read every hardware sentence in
   `docs/BOX_DAY.md` and check that nothing tagged `inferred` in the design
   arrives here as an instruction without the word UNCONFIRMED and its
   resolving step. The M8-plug sentence is the one to press on: the runbook
   tells the owner the Mid-360 lands there, and that is inferred from
   third-party cable listings, not documented by Unitree.
4. **H2** — agree or disagree that it is a pre-registration defect rather
   than an OWNS violation. The peer attribution is spelled out above and is
   checkable file by file.
5. **T1/T2** — re-sum the two tables independently. If the runbook and this
   doc disagree on 95 or 300, one of them was hand-edited after the sum.

---

# Correction pass — 2026-08-23, 14:0x–14:4x EDT

Against verifier verdict **HOLD** (`~/.cache/parcel-verify/hw8/VERDICT.md`).
Same executor, docs only. No pytest, no hardware, no device opened, git
read-only. Every finding below was **reproduced first**, then fixed.

## Reproductions (before any edit)

| Finding | Command | Result |
|---|---|---|
| H-1 | `preflight --builtin-lidar-model L2 --json --out /dev/null --reader none` | rc=**2** `error: unrecognized arguments: --out /dev/null` |
| H-1 | same without `--operator`/`--photo` | rc=**2** `PREFLIGHT REFUSED: --builtin-lidar-model requires --operator and --photo` |
| H-2 | `-c "…probe_robot_identity()… evaluate_firmware_pin(o)"` | `EvidenceKind.ABSENT FirmwarePinState.UNVERIFIED`; evidence: *"go2: none of rclpy, unitree_sdk2py importable"* |
| H-2 | `grep -rl firmware_version scripts/parcel_capture/ingest/ \| wc -l` | **0** |
| H-3 | `grep -rli 'nftables' deploy/ configs/ scripts/ src/ tools/ \| wc -l` | **0**; `grep -ci nft task_35/DESIGN.md` → **0** |
| F-1 | `grep -n 'default=' unitree_control.py` | `--min-samples` 20, `--timeout` 5.0; `session.py:311` `while clock < deadline and len(seen) < min_samples` |

**The verifier is right on all three HOLDs.** My `--help`-exits-0 test was too
weak: it proves a spelling parses, not that the step produces its result.

## Fixes applied

| # | Item | What changed |
|---|---|---|
| 1 | **H-2 S20** | Rewritten to the tree's real route: **owner reads the version in the Unitree app** (and confirms OTA off there) → `python3 -m scripts.parcel_capture.orin_rehearsal --evidence-dir ~/Parcel/hw --until p3_network --firmware-attested V<x.y.z>` → **`hw/p3_network.json`**. The cell says in so many words that this repository has no way to read it off the robot. ADR 0002's "recorded before the dock joins any LAN" kept as the rule — which **dissolves the stop-rule-2 tension**: an app read needs no network, so "unread ⇒ nothing joins the robot LAN" is now satisfiable instead of circular. Mirrored into `UNKNOWNS_REGISTER.md` Q-fwv and, with a `was` comment, into the run sheet's **P1** row (whose inherited 08-13 text "PS-D attestation reads it off the unit" was false for this tree) |
| 2 | **H-1 Q-lidar** | `python3 -m scripts.parcel_capture.preflight --builtin-lidar-model "<label>" --operator "<your name>" --photo <id> --json > hw/Q_lidar.txt`; `--out` dropped; the step now says **photograph the label first — the photograph is the input**. Mirrored into the register's Q-lidar row |
| 3 | **H-3 B-fw** | Cell now opens `apply deploy/orin/nftables.conf` — **RULESET DOES NOT EXIST YET — card HW-FW (wave 3b), not written**, followed by the four-command minimum to type by hand (`nft add table inet parcel`; a `forward` chain with `policy drop`; an `output` chain; `oifname != "<rnic>" ip daddr 239.255.0.0/16 drop`) plus the three by-hand checks (no default route on the robot NIC; Mid-360 static `192.168.1.5` no gateway; panel `127.0.0.1` + tailnet). New handoff **HO-5** |
| 4 | **F-1 S19** | `observe --min-samples 3000 --timeout 90 --out hw/S19_stage0_01.json`, with the stop condition spelled out (first of the two, and a `NO_FEEDBACK` **refusal** below `--min-samples`, which is itself a finding worth keeping) and the arithmetic (3,000 ≈ 60 s at the *expected* ~50 Hz, expected not measured). **Chosen resolution for "10 min": ten consecutive runs**, `_01`…`_10`, keeping refusals. Duration mode handed off as **HO-6** |
| 5 | **B12** | The three real commands named in order; `--print-argv humble` chosen over `--emit-distro` **because the latter writes into the checkout** and git is read-only on the Orin (verifier N-9). One result file: **`hw/B12_record.txt`**; the bag stays on the record target, as `ORIN_RUNBOOK.md` already does with its bench bag |
| 6 | **F-2 X1** | Both added steps now carry **(added by HW-8)**: B0 and the new B-con |
| 7 | **F-7 B-con** | New step: how the owner gets a shell on the Orin with no LAN joined. The dock's documented ports include **no HDMI/DP** [documented], so: (a) laptop on a **direct Ethernet cable** to the spare RJ45, static addresses, **no gateway** — a cable between two machines is not a LAN; or (b) a **USB-serial console**. **Which works is UNCONFIRMED** — ticket Q5 / step Q-usb. Placed at step **1, not 0**: physical dependency — the dog is standed and sport mode is off (B0) *before* the dock is powered. New register row **Q-con**, marked as added |
| 8 | **F-6** | The first-two-hours table gained a **Who** column (all nine rows: owner) |
| 9 | **F-5** | Run-sheet banner line 36: the M8 plug now reads **UNCONFIRMED**, inferred from third-party cable listings, settled by Q-wire |
| 10 | **F-3** | Banner's "and nothing else was touched" replaced by an explicit **"Three changes beyond the purchase"** paragraph naming all three (§3's T1–T6 source-of-truth column; §5's PO-1/Q-stop block; row 19's XVF3800 ON HAND), each kept as an improvement and commented in place |
| 11 | **N-3, N-6, N-7, N-8, N-9** | HW-1 reworded to "must be green before the Orin runs anything"; the battery's 28–33.6 V added beside the Mid-360's 9–27 V so the reader sees both documented numbers behind the conclusion; "engineer" defined as a role; Q-batt's roam marked **remote/app-driven, never Parcel**; `--print-argv` over `--emit-distro` |
| 12 | **N-5** | Ticket: "Five questions" → six (Q6 is the head-LiDAR question) |

## One measured correction to the verifier's suggestion

The verifier's §5 table and my first draft disagreed on Q-lidar's extension; I
went to `.json` on the "JSON output ⇒ `.json`" rule, then **measured it**:

```
preflight --builtin-lidar-model L2 --operator owner --photo P02 --json --reader none > f
→ rc=1 (a NOT-READY verdict, not a parse error); f is 116,874 bytes and
  json.load(f) raises JSONDecodeError at line 1 col 1
```

`--json` prints the **human report first and the JSON block after it**, both
on stdout. So the capture is a mixed stream and `.txt` is correct — the
verifier's `> hw/Q_lidar.txt` was right and my "consistency" reasoning was
wrong. **Q-lidar stays `hw/Q_lidar.txt`**, and the cell now tells the owner
the file is report-then-JSON and to keep it whole.

## Re-run ledger — the NEW spellings

| Row | Command | rc | Note |
|---|---|---:|---|
| R1 | `orin_rehearsal` parser: `--evidence-dir … --until p3_network --firmware-attested V1.1.13` | **0** | parse-checked in process (running it would execute p0–p3 on this desktop); `evidence_dir`, `until=p3_network`, `firmware_attested=V1.1.13` all bound |
| R2 | `preflight --builtin-lidar-model "L2" --operator "owner" --photo P02 --json --reader none` | **1** | rc 1 = the NOT-READY **verdict**, not a parse error (contrast rc 2 for both pre-fix forms); 116,874 bytes of report + JSON |
| R3 | `unitree_control` parser: `observe --min-samples 3000 --timeout 90 --out …` | **0** | parse-checked in process; `min_samples=3000 timeout=90.0` bound |
| R4 | `record --check --dest <scratch>` | **3** | real run; refuses cleanly on the dev box — *"this host cannot run a live capture … the capture stack is a deploy artifact for the Orin"*. Correct fail-closed behaviour; on the Orin it does the real check |
| R5 | `record --verify /nonexistent.mcap` | **2** | flag exists; refuses on the **file**, not on an unknown option |
| R6 | `stage0_addendum --print-argv humble` | **0** | prints the `ros2 bag record` argv, writes nothing |
| R7 | `syncevents --ritual-card` | **0** | B11's clock-map ritual |

Negative greps re-run, all still **0**: `parcel-capture *=` in `pyproject.toml`;
`parcel-commission` in `pyproject.toml`; `record --help \| grep -E --
'--plan\|stage0\|--dry-run'`. The three dead spellings appear in
`docs/BOX_DAY.md` **only** inside the "Commands that do not exist yet"
section (lines 173–178) and in the run sheet only inside an HTML comment.

## Rows restated honestly

| Row | Was reported | Now | Threshold |
|---|---|---|---|
| **W1** | 2,136 words | **2,498** (prose 2,341) | ≤ 2,500 — **MET**, but the margin is 2 words. The corrections added ~550 words and I cut ~550 back out of bookkeeping prose (the "commands that do not exist" section went from 189 to ~110 words — that material is internal and belongs here, not in the owner's runbook). **Anything further added to this file pushes it over; trim before adding** |
| **T1** | 95 min | **105 min** (B-con +10) | ≤ 120 — **MET**. Re-summed by script from the rendered table |
| **T2** | 300 min | **310 min (5.2 h)** | ≤ 480 — **MET** (105 + 205) |
| **X1** | MET | **MET (now honestly)** | 13 §7 ids present; **two** added steps, B0 and B-con, both marked **(added by HW-8)**. Previously reported MET on a marker that did not exist — F-2 was a correct catch |
| **X9** | "18 comments" | **12 `<!-- HW-8: was` comments** (was 11; the P1 fix adds one), **19** `<!-- HW-8` lines in total | The registered command is `grep -c '<!-- HW-8: was'`. My 18 counted every `<!-- HW-8` line — `was` **and** `added` **and** the banner's own mention. That was a **mis-report of my own registered measurement**, and the verifier was right to call it |
| **X11** | MET | **MET (now honestly)** | One `hw/` file per step, and the extensions now match what each command actually emits: `.json` for B9 (`p0_identity.json`), S20 (`p3_network.json`), S19 (`S19_stage0_NN.json`) and Q-usb's array sidecar; `.txt` everywhere else including Q-lidar (measured: report-then-JSON) and B12 (transcript; the bag stays on the record target). Previously B12 named two files and three extensions were wrong |
| **X8** | 16 rows | **17 rows** | All 16 §8 ids still present; **Q-con** added and marked *(added by HW-8)* |

## New handoffs

| # | Thing | Handoff |
|---|---|---|
| **HO-5** | `deploy/orin/nftables.conf` — the robot-LAN firewall ruleset. **Does not exist anywhere in the tree**; design §7 says "from HW-1's DESIGN" and HW-1 is `py310-clean` with zero nft mentions | **Card HW-FW, wave 3b — not yet cut.** Needs: a checked-in `*.nft`, `nft -f`, and a `nft list ruleset` verification row. Until it lands B-fw carries the rules inline. **This is step 2 of the four that cannot be reordered, so it is the highest-value 3b card** |
| **HO-6** | a fixed-duration mode for `unitree_control observe` (`--duration <s>` that returns what it saw instead of refusing) | **HW-2 `go2-backend`**, which owns the observe path. Until then S19 is ten runs |
| **HO-7** | a live identity/firmware reader (`robot.firmware_version` over DDS) so `attest` can read the version off the unit | **No card owns it.** Wave 3b at the earliest, and it may never be worth it — ADR 0002's control is the firewall, and an app read plus `--firmware-attested` already satisfies the pin honestly |

## Still open, and what the narrow re-verify should check

- The two owner-gated items are unchanged and still open: **send the ticket**,
  **read and sign `docs/BOX_DAY.md`**.
- Re-verify targets: (1) the R1–R7 ledger above, re-run; (2) `wc -w` = 2,498;
  (3) the T1/T2 re-sum by script (105 / 310); (4) `grep -c '<!-- HW-8: was'`
  = 12; (5) the three negative greps = 0 and the dead spellings confined to
  the one section; (6) that S20 no longer claims a read this tree cannot do,
  in **all three** places it appeared (runbook, register Q-fwv, run sheet P1).
- Not fixed, and not mine: **N-4** (design §9's "0.10 m/s" is a distance per
  HW-6's F1) and **N-13** (`192.168.1.5x` vs `192.168.1.5` between design §2
  and §5.7) are the design's to correct; `docs/BOX_DAY.md` follows whatever
  §9 says and will need one edit when it changes.
- Sources still byte-unchanged: `STAGE0_RUN_SHEET.md` sha256
  `f874ed46e7456b2f9fcf34622ea2601dc116d83e65310e79347b71021b4b3df7`;
  `PREREGISTRATION.md` sha256 `f953cf43de8ddcb9759530324a901cd5af7035c63322e26438ab12f906d441fe`;
  `git status --porcelain -- scrum/20260813/ scrum/20260822/task_27/
  docs/MOTION.md scrum/20260805/` empty.

## Addendum — the commissioning band (folded in 14:5x, coordinator relay of HW-6's verdict)

**What was wrong.** Both my documents carried design §9's "one axis, 0.10 m/s"
as the first armed step's speed. Measured in the tree
(`src/parcel_robot/commissioning/limits.py`):

```
MIN_LINEAR_MPS = 0.02          MAX_LINEAR_MPS = 0.05          (:85-86)
FOOTPRINT_RADIUS_M = 0.32   → MAX_YAW_RAD_S = 0.05/0.32 = 0.15625 rad/s (:87)
DEFAULT_MAX_DURATION_S = 1.0                                    (:97)
docstring :52 — "Total commanded travel is therefore bounded by
MAX_LINEAR_MPS * (duration + stop_timeout) = 0.05 * 2.0 = 0.10 m"
```

So **0.10 is a distance in metres, not a speed**, and the band **refuses**
0.10 m/s. The "0.10 m/s / 0.25 rad/s / 2 s" triple is the 2026-08-03
`unitree_control` cap that card W0-B retired on 08-13.

**Fixed in two places** (the third does not apply):

| Where | Now reads |
|---|---|
| `docs/BOX_DAY.md:131` (first armed step) | "inside the commissioning band: linear **0.02–0.05 m/s**, yaw **≤ 0.156 rad/s**, step **≤ 1.0 s**, so one step travels **≤ 0.10 m** (`commissioning/limits.py`). The band **refuses 0.10 m/s** — that older figure is a retired 08-03 cap" |
| `UNKNOWNS_REGISTER.md:29` (Q-avoid, "resolves on") | same band, same refusal note, replacing "one axis toward a box at 0.10 m/s" |
| `STAGE0_RUN_SHEET_EDU_PLUS.md` | **no change needed and none made** — `grep -n '0\.10\|0\.25\|rad/s\|m/s'` returns **nothing**. The Stage-0 sheet authorises no motion at all, so the triple never appears in it and there is no `was` comment to add |

**New handoff.**

| # | Thing | Handoff |
|---|---|---|
| **HO-8** | `docs/MOTION.md:369` still prints the stale triple — *"linear/yaw speed at `0.10 m/s` and `0.25 rad/s`, limits each run to two seconds"* | **Not mine to edit** (`docs/MOTION.md` is in this card's MUST NOT TOUCH). Whoever owns `docs/MOTION.md` corrects it to the `limits.py` band. Until then a reader who follows MOTION.md instead of `docs/BOX_DAY.md` gets a number the code refuses |

**Word budget after the fold-in:** `wc -w docs/BOX_DAY.md` = **2,495**
(prose 2,340), still under the 2,500 cap — the band text cost ~45 words and I
cut ~55 back out of the `hw/`-convention and closing prose, including deleting
the bookkeeping line "No `hw/` directory exists in this repository today"
(true, still recorded in `DESIGN.md` §4, and not something the owner needs on
the day). T1/T2 unchanged at **105 / 310 min**, re-summed by script after the
edit. **The file now has 5 words of headroom; anything added must be traded.**

## Final residuals — 2026-08-23, 15:0x EDT (verifier FINAL = ACCEPT-WITH-NOTES)

Three one-line docs fixes from the verdict's "Re-verify" section; no code, no re-verify round. **R-1** `SUPPORT_TICKET_UNITREE.md`: B-con and register row Q-con cited "ticket Q5" for the console route, but Q5 asked only about USB ports and payload power — the ticket asked nothing about getting a shell. Added **Q5d** (serial/USB console header and its settings; what the second RJ45 is for and whether it is bridged to `192.168.123.0/24`), a `5d → Q-con` row in the mapping table, and corrected "Five questions" / "these five answers" to **six** (`grep -c '^\*\*[0-9]\.'` = 6). `docs/BOX_DAY.md`'s B-con now cites **ticket Q5d**, not Q5. **R-2** `docs/BOX_DAY.md` B-fw: added *"These rules live in the kernel, not on disk: re-type and re-check them after any reboot, and again before Q-link"* — the inline `nft add` commands are runtime-only until card HW-FW checks in a `deploy/orin/nftables.conf`, and a reboot between B-fw and Q-link would silently drop the boundary right before the first WAN traffic. **R-3** `STAGE0_RUN_SHEET_EDU_PLUS.md` T4 (line 169) still rendered the recorder argv with `--emit-distro`; the B12 fix had landed only in `docs/BOX_DAY.md`. Changed to `--print-argv humble` with a `was` comment naming the reason (`--emit-distro` writes a sheet into `scrum/20260814/task_1/` inside the checkout, and git on the Orin is read-only by this sheet's own rule). Counts after: `wc -w docs/BOX_DAY.md` = **2,491** (prose 2,336), cap 2,500 — MET with 9 words of headroom, bought back from bookkeeping prose so the R-2 clause fits; `grep -c '<!-- HW-8: was'` = **13** (was 12); T1/T2 re-summed unchanged at **105 / 310 min**; table cell counts 7×11 and 5×10, `--emit-distro` now appears in the tree only inside the R-3 `was` comment. **HW-8 CLOSED.**
