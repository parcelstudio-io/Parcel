# TRUTH-1 · DESIGN (task_32) — remedies and reports tell the truth about this box

Card `README.md`; rows `PREREGISTRATION.md` (verbatim, sha256 `b5c8dd59…fae7`). Evidence:
`AUDIT_WEEK1_FABLE.md` §ENV-1b (SDK-REM-1), §TURN-1 (`settle_s`), §AIR-1;
`AUDIT_WAVE2_FABLE.md` "Cross-card findings" (→ R9).

## (a) Purpose

Four operator-facing texts and one config door say something false about this tree. A
remedy sends a desk operator to an Orin for a wheel `pip` already carries; a `--check`
census says "reader deps present" about a camera nobody owns; a replay report cannot tell a
wall-indexed `audio_end_ms` from an appended-audio one; a runbook names one measurement two
ways; and `web_panel` reads a config section no overlay may introduce, so the planner LLM
can never be turned on. Each costs a session morning. This card makes each text measurably
true **and pins the measurement**, so the next stale claim reddens instead of aging.

## (b) Architecture fit — the seams, by symbol

| Seam | Product caller | This card |
|---|---|---|
| `clockmap.MODULE_MISSING_REMEDIES` / `module_missing_remedies()` | `clockmap.main()` REFUSED paragraph (`--check`, exit 2) | NEW table + grouper; the paragraph prints one line per REMEDY, not one for all devices |
| `ingest/realsense.py:RealSenseIngest.requirements[0].remedy` | `ingest/base.py:IngestAdapter.probe_availability()` → `dependency_report_text()`; `IngestUnavailableError.remedy` | text only |
| `preflight.py:_TRANSPORT_MODULES["realsense"]` | `preflight` transport rows | text only |
| `record.py:INSTALL_HINTS["pyrealsense2"]` | `record.missing_dependencies()` → `dependency_report()` | text only |
| `record.device_presence()` (NEW) → `ingest.adapter_for().device_report()` | `record.dependency_report()`, `record._cli_check()` | ENV-1's `/dev`-glob seam REUSED, never re-implemented |
| `ingest.dependency_report_text()` | **had none** — a test was its only caller | `record._cli_check()` becomes its first product caller |
| `tools/replay_turn_detection.py:UtteranceResult`, `replay()`, `REPORT_SCHEMA` | the tool's own `--replay` | wall-origin columns + `settle_s`; schema v1→v2 |
| `config.OVERLAY_INTRODUCIBLE_KEYS` → `config.check_overlay_keys()` | every `ConfigStore(…, profile=…)` load | ONE entry, `planner_model` |
| `web_panel.build_runtime()` `store.section("planner_model")` | the product launcher | spelling guard AT the read site |

**Composition with batch A.** VENUE-1 owns the two `perception.camera_backend`/`detector`
entries in the same frozenset; this card appends a fifth family below them, touching no
existing entry. CAP-1's `admission.config_key_entries()` READS the frozenset and needs no
edit — its `planner_model` row flips to `admitted=True` by data, which is exactly the "the
fix reddens the pin too" signal CAP-1 pre-registered. DOOR-1/OT-2 are not on any path here;
the safety core is untouched (every edit is a string, a report field, or a set membership).
`probe_availability`, `PROBE_REQUIREMENTS`, `ingest/base.py`, `pyproject.toml`, `lane.py`
and the array's control path are MUST-NOT-TOUCH and stay byte-identical to HEAD.

**Where R9's door actually is.** The re-dispatch brief guessed `runtime.py`; the grep
decides, and it says `src/parcel_robot/config.py:109` — `runtime.py` only *documents* the
frozenset (`:5120`, `:11809`) and reads nothing from it. So **this card does not touch
`runtime.py` at all** and takes no `lock-runtime.py`. R9's four files are
`src/parcel_robot/config.py` (the entry), `src/parcel_robot/web_panel.py` (the read-site
spelling guard), `tests/test_cap1_admission.py` (CAP-1's pin, which the fix must redden and
which is updated in the same change), and `tests/test_prototype_profile.py` (the
introducible-keys pin — shared with ROAM-2, so edited in ONE pass inside a marked
`CARD TRUTH-1` region while holding `~/.cache/parcel-batchb/lock-test_prototype_profile.py`).
All four are a DECLARED deviation from the README's OWNS, pre-registered as R9.

## (c) Interfaces and contracts

* `clockmap.MODULE_MISSING_REMEDIES: Mapping[str, str]` = `{d455, go2, l2}`;
  `DEFAULT_MODULE_MISSING_REMEDY` = the Orin/ROS 2 sentence (unmeasured device ⇒ vendor
  device). `module_missing_remedies(devices)` → sorted `((remedy, names), …)`, pure, no I/O.
* `record.device_presence(entry) -> tuple[str, str]` returns `("unknown", why)` — **never
  `"attached"`** — when no adapter serves the transport: "we could not ask" must not read
  as "it is there".
* `dependency_report()`'s state column: `UNAVAILABLE (missing: …)` / `NO DEVICE
  (installed: …)` / `READY (…; device attached)` / `deps present …; DEVICE NOT ATTESTABLE`.
  `--check`'s **exit code is unchanged** (still modules + space).
* `REPORT_SCHEMA = "parcel.turn1.replay.v2"`; report gains `settle_s` +
  `wall_minus_audio_ms_max`; each row gains `wall_offset_ms`, `wall_elapsed_ms`,
  `wall_minus_audio_ms`, `commits_wall_relative_ms`, `commit_latency_wall_ms`.
* `OVERLAY_INTRODUCIBLE_KEYS += {"planner_model"}` — whole subtree, ONE entry, for the
  reason ROAM-1 wrote beside `roam`: listing children would look like a spelling guard and
  be inert. `web_panel._PLANNER_MODEL_KEYS` + `_check_planner_model_section()` is the real
  guard, refusing an unknown key BY NAME (the `CameraStreamConfig.from_section` pattern).
* **Defaults OFF.** Nothing here turns anything on: `planner_model.enabled` is absent from
  the SHA-locked base, so the default stays false and only an operator who writes the block
  gets a planner.

## (d) Data flow and lifecycle

No new thread, process, lock or file. `device_presence` is a `/dev` glob per call inside
`--check`'s existing single-threaded pass, importing `ingest` LOCALLY (that package imports
`record`/`preflight`; a top-level import would close the cycle). `replay()` takes one
`time.monotonic()` at `open_session` and reads it twice per file, so the wall and audio
origins share a zero — the only reason the two hypotheses are comparable. The config guard
runs once, at `build_runtime`, before any backend or socket exists.

## (e) Hardware compatibility — the remedy matrix (the hardware-truth card)

Two hosts are now real: this dev box, and the **Jetson Orin NX 16 GB (aarch64, JetPack →
CPython 3.10)** onboard the Go2 EDU+ w/ Mid-360 the owner named at 16:00. **Citation rule
used here and in every remedy string this card writes:** a hardware statement is made only
if it comes from (i) the owner's paragraph in `BATCHB_DISPATCH_FABLE_4a.md` §"Hardware
target (owner, 16:00)", (ii) one of the vendor texts the design study fetched —
`~/.cache/parcel-fable-design/hw-facts/{go2,mid360,l2,remote}.txt`, (iii) this tree, or
(iv) a command run on this box. `go2_eduplus_facts.md` was never written. Everything else
is tagged **UNCONFIRMED** and says so in the operator text as well as here.

| Device | Dev box — x86_64, CPython 3.14 | Orin NX 16 GB — aarch64, CPython 3.10 (JetPack) |
|---|---|---|
| **D455** | `pyrealsense2` is a plain pip wheel: `.parcel/bin/pip install -e '.[camera-realsense]'`; 2.58.3.10794 cp314 `manylinux1_x86_64` INSTALLED here (measured here 2026-08-22) | **ALSO pip** — the same release ships `cp310-cp310-manylinux2014_aarch64`. Source: the **PyPI file list** for 2.58.3.10794, read 2026-08-22; it is a *file exists* fact, never a *ran on the unit* fact. aarch64 wheels exist for cp39/cp310/cp312 ONLY. **CORRECTED at implementation (2026-08-23, from `research.json`, confidence `documented`): WHICH JetPack the EDU dock boots is UNCONFIRMED** — reseller and NVIDIA-forum reports have Go2 EDU docks shipping JetPack 5.1.1 (Ubuntu 20.04, **CPython 3.8** → *no aarch64 wheel at all*) as well as being flashed to 6.2.1 (Ubuntu 22.04, CPython 3.10 → wheel). So the remedy names both branches instead of assuming 6.2.x, and librealsense's open "D455 not detected on JetPack 6.2" report is named too. Still a *file exists* fact, never a *ran on the unit* fact |
| **go2 (DDS)** | absent by design — no motion SDK in `.parcel`, the project's strongest motion guarantee | `unitree_sdk2py` over CycloneDDS in a CPython 3.10 process; ROS 2 Humble (`unitree_ros2` overlay) only if the owner installs it. Cited to **this tree**: `preflight._TRANSPORT_MODULES["dds"]` already names `rclpy`/`unitree_sdk2py`/`cyclonedds` and `record.INSTALL_HINTS` already names Humble — this card leaves all of it byte-identical. **UNCONFIRMED:** which of the two the unit ships with; `hw-facts/go2.txt` is the consumer Go2 manual V1.0 and names neither an Orin nor a DDS API |
| **head LiDAR** | absent | the built-in head unit publishes on the `rt/utlidar/*` topic shape (**this tree's** channel matrix). `hw-facts/go2.txt` L55/L112 says the standard Go2 head unit is the **4D LiDAR L1, 360°×90°**; whether the EDU+ w/ Mid-360 SKU keeps it is **UNCONFIRMED**, and the owner's 16:00 note says the exact model is unknown until the box. No code is written against it here |
| **mid360** | absent | **CONFIRMED by `hw-facts/mid360.txt`:** Livox Mid-360 talks **UDP over 100BASE-TX Ethernet** (L540, L1016) and its API is **Livox SDK2** (L121-123, L852-858) — a different vendor, protocol and transport from the add-on L2, which `hw-facts/l2.txt` puts on `unilidar_sdk` over **ENET UDP or TTL UART** (L22, L134, L449-456). So a Mid-360 does **not** belong in this tree's `l2` row; **UNCONFIRMED** which row it should get, and this card changes neither — that is a wave-3 decision |
| **xvf3800** | present, `usb_audio`, read-only here (`Errno 13`, no udev rule — `task_25/AIR1_STATUS.md`) | UNCONFIRMED: USB host power and enumeration on the Orin. Nothing in this card opens, plays through or writes to the array |

**Venue-independent by construction:** every seam here is a *string, a `/dev` glob, or a
set-membership test*. `device_presence` asks the adapter, which globs `/dev` — the same
answer on aarch64; `check_overlay_keys` is pure Python over mappings;
`module_missing_remedies` is a dict lookup. Nothing imports a vendor SDK, links a `.so`,
shells out, or assumes x86/CUDA. **Must be configured on the Orin:** a DEPLOY venv (never
`.parcel/`) carrying `pyrealsense2`, plus the vendor SDK environment for the
dds/vendor_video/vendor_uwb rows. **UNKNOWN:** every attached-camera arm, and whether
cp310 aarch64 `pyrealsense2` actually opens a D455 through the Orin's USB3 stack.

## (f) Test strategy

`tests/test_truth1_texts.py` (NEW) pins each row as a property of the PRODUCT text, not a
copy: R1 by running `clockmap.main(["--check"])` with modules hidden and reading stdout;
R2/R3/R5 by importing the live objects; R4 by running `python -m
scripts.parcel_capture.record --check` in a SUBPROCESS and grepping its own stdout; R6 by
driving the tool's own `replay()` over a two-file corpus at `settle_s=0.15` through a real
`RealtimeLane` on `transport_pair()`; R7 by a SUBPROCESS running `--arms` and reporting
`sys.modules`; R8 by reading `SESSION.md`; R9 through `check_overlay_keys`,
`admission.admitted()` and `build_runtime`'s guard. Seeds S1–S5 mutate the product, redden
the named test, and restore byte-identically by sha256. CAP-1's pin and the
introducible-keys pin (`test_prototype_profile.py`) are updated in the same change, each in
its own marked region, so a SECOND unreachable section still reddens.

## (g) Risks and what this does NOT cover

0. **Design change forced by implementation (2026-08-23).** The §(e) D455 row above
   was corrected in this pass: the drafts it produced asserted "JetPack 6.2.x CPython
   3.10" as settled, and the forwarded hardware constraint says the dock may ship
   JetPack 5.1.1 on CPython 3.8, for which this release publishes NO aarch64 wheel.
   All five remedy sites now state the ambiguity. Recorded in `TRUTH1_STATUS.md`
   §Deviations 4.
1. **R3 conflict, declared.** Registered at 15:27 as "`Orin` occurrences in the realsense
   remedy = 0"; the owner's 16:00 hardware target makes the Orin the real deploy host, so
   the truthful remedy names BOTH. Measured as written that is a MISS — number and reason
   in the status doc; the verifier decides.
2. `check_overlay_keys` exempts the whole `planner_model` subtree, so the read-site guard
   is the ONLY thing between a typo and a silent default: bypass `build_runtime` (construct
   `RobotRuntime` directly) and the typo merges silently.
3. **A retracted claim must not be quoted verbatim.** R5 greps `__init__.py` for the stale
   sentence *"there is no aarch64 build"* and requires 0 occurrences. The first executor's
   replacement retracted the claim by quoting it, which left the grep at 1 — the guard would
   have been defeated by the very paragraph that fixed it. The retraction is reworded to
   describe the claim instead of reproducing it; the same rule applies to every other
   stale-string row.
4. **A pin outside OWNS, declared.** `tests/test_capture_ingest.py` asserted `"Orin" in
   report.remedy` and `"Orin only" in ...` for all three adapters; changing the D455 remedy
   forces those two assertions to become per-module. The file is not in the README's OWNS
   list, so the edit is a DECLARED deviation — a pin the text change forced, not new scope.
5. Nothing here proves an attached camera, a hosted `--replay` number, a through-air AIR-1
   number, or one byte of Go2/Orin behaviour. No hardware is on hand but the XVF3800, never
   opened, played through or written to by this card.
