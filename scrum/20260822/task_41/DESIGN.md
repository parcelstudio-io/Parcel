# HW-5 `physical-profile` — DESIGN (card `scrum/20260822/task_41`, slug hw5)

Executor: Opus · Verifier: Fable · Design: `../WAVE3_HW_DESIGN_FABLE.md` §4
S14/S15, §5.8, §9 · Board: `../TASK_BOARD.md` wave 3.

## (a) Purpose

One overlay — `configs/robot.go2_edu_plus.yaml` — that says what rig this run
is on, what it needs, and nothing about what it will find there. It selects
the venue (so HW-3's retired L2 path stops being reachable by accident), the
eye (D455), the ear (HW-4's array), the physical backend (HW-2's, by name),
and it carries the Mid-360's band numbers as NUMBERS. It declares its
`required_capabilities` where CAP-1 actually reads them. It contains no field
the runtime could read as ground truth.

## (b) Architecture fit — seams, and who calls them on the product path

| seam (module:symbol) | who calls it | what HW-5 does |
|---|---|---|
| `config.ConfigStore.__init__` :291-313 → `check_overlay_keys` :204 | every entrypoint (`web_panel.build_runtime` :700, `launch_stack.sh`) | six new `OVERLAY_INTRODUCIBLE_KEYS` entries in ONE `CARD HW-5` region |
| `config.profile_overlay_path` :71 | as above | the profile is the SIBLING `configs/robot.<profile>.yaml`; **design §5.8's `configs/profiles/go2_edu_plus.yaml` cannot load** — `_PROFILE_NAME` :25 refuses a path (F4) |
| `admission.navigation_config_mapping` :736 → `required_capabilities` :779 → `check_required_capabilities` :1035 | `runtime.RobotRuntime.start` :4373, one line before `_attach_configured_camera_ingress` :4375 | the declaration lands in the NAVIGATION file the profile selects, via the base key `navigation.config` |
| `runtime._venue1_resolve_venue` :11924 → `_venue1_attach_physical_ingress` :12035 → `_venue1_open_failure` | `start()` :4375 | `perception.camera_backend: realsense` — the desktop refusal |
| `scripts/parcel_capture/ingest/__init__.py:adapter_for` :112 | `preflight`, `record`, `orin_rehearsal` | `CARD HW-5` region injects `venue=` into the factory that accepts it → `l2.refuse_retired_venue` :128 stops being inert (HW-3 F4) |
| `web_panel._build_backend` :850 (`_BACKEND_KEYS`) -> `backends.go2.band_profile_from_config` :760 | `web_panel.build_runtime` :933, `web_panel.main` | **not touched.** HW-5 admits `backend` and writes the profile in HW-2's vocabulary; HW-2 owns both read-site validators (corrected after the HW-5 verdict, H1) |

Composition with the standing regions: TRUTH-1 owns `planner_model`, HW-4 owns
`audio`, VENUE-1 owns `perception.camera_backend`/`detector`, C-1 owns
`perception.camera_ingress*`. HW-5 adds a disjoint sixth/seventh family and
edits no other card's region. The safety core is untouched: the profile writes
no `safety.*` key at all (§g).

## (c) Interfaces — the key set, and why each is shaped the way it is

Two entries, in one `CARD HW-5` region of `OVERLAY_INTRODUCIBLE_KEYS`, and one
of each shape an introducible key can honestly have:

1. `venue` — top-level SCALAR. `go2_edu_plus`, the same string as
   `capture/channels.py:GO2_EDU_PLUS_VENUE` :1872 and `ingest/l2.py` :90. A
   scalar has no inside, so `check_overlay_keys` :234 is its whole spelling
   guard and no read site has to be remembered.
2. `backend` — ONE entry exempting a SUBTREE, in card HW-2's vocabulary:
   `kind`, `band` (`z_lo_m`, `z_hi_m`, `min_populated_bins` + five layout
   numbers left at `BandProfile`'s defaults), `interface`, `fixture`,
   `domain_id`, `session_epoch`, `max_frames_per_drain`. The loader will merge
   a typo inside it, which is legitimate ONLY because HW-2 put the guard at the
   read site twice — `web_panel._BACKEND_KEYS` for `backend.*` and
   `backends.go2.band_profile_from_config` for `backend.band.*`, both refusing
   by name. Deliberately NOT `control.controller`: that key is the WRITER axis
   and `runtime.py` :1514-1519 refuses any value but `simulator` without an
   injected `control_manager` ("configuration alone cannot arm hardware"). Not
   `motion.backend` either — that is the locomotion policy.

Extrinsic form: **xyz + rpy (6 reals), not a 4×4**. Any 6 reals are a valid
rigid transform; 9 of a 4×4's 16 numbers are a rotation under an
orthonormality constraint no YAML loader checks, so a typo'd matrix becomes a
silent shear. Six numbers are also exactly the six things a tape and a level
measure at B11. `band_profile_from_config` accepts a 4×4 today, so the profile
writes NO extrinsic at all (`BandProfile`'s identity default stands, and the
value is B11's anyway); the key name `backend.band.extrinsic_xyz_rpy` is a
handoff to HW-2, not a key this card writes ahead of its reader.

NOT introduced: `required_capabilities` at the robot-profile top level.
Measured: nothing reads it there — `required_capabilities()` :779 takes
`navigation_config_mapping()` :736, which loads the file `navigation.config`
names. A top-level entry would be HW-4's D6 in its purest form. The
declaration therefore lives in `configs/navigation/venues/go2_edu_plus.yaml`,
selected by the base key `navigation.config`, which needs no new entry at all.

NOT introduced (retracted after the verdict): `perception.lidar_band_min_m` and
its three siblings. The first pass argued that a family with no read-site
validator is only honest as flat scalars. The premise was false in this tree —
the validator exists, it is `band_profile_from_config`, and it reads
`backend.band`. Four keys nothing reads is the defect, whatever their shape.

TWO NIC KEYS, ONE READING. `backend.interface` is the NIC the product venv's
observer binds; `control.unitree_sport.interface` is the same wire as the
motion venv's commissioning writer sees it. Two keys because the two processes
must never share one (design §3: CycloneDDS is process-global), one value
because it is one cable, read once at B9. The profile writes NEITHER today (the
Orin's name is unknown) and a test pins that it writes both or neither.

## (d) Data flow and lifecycle

`PARCEL_PROFILE=go2_edu_plus` (or `--profile`) → `resolve_profile` :48 →
`ConfigStore` reads the SHA-locked base, `check_overlay_keys`, `deep_merge` →
every consumer sees the merged mapping. `RobotRuntime.start()` then:
`_p1b_install_learned_map` :4323 → `_venue1_bind_semantic_source` :4359 →
`check_required_capabilities` :4373 → `_attach_configured_camera_ingress`
:4375, where the absent D455 refuses. In the capture lane (a different venv,
different process) `adapter_for` asks `config.resolve_profile()` once per
profile and reads `venue` from the merged store; **no profile → no venue → the
adapter is constructed `factory()`, byte-identically to today.** No threads,
no locks, no files written. One `lru_cache` keyed on the profile name.

## (e) Hardware compatibility — class **MC** (S14/S15)

Nothing here is new code on the dog; it is configuration the dog needs and the
desktop cannot satisfy. Venue-independent by construction: the loader, the
merge, the spelling refusal, the `venue=` injection. Must-configure: every key
in §(c). UNKNOWN until the box: the Mid-360 extrinsic (B11 — the key is
admitted and the VALUE is deliberately absent, because an unmeasured extrinsic
written as a number IS a truth field), the Orin's robot-LAN NIC
(`control.unitree_sport.interface`, B-con/Q-wire — commented out for the same
reason), the array's PortAudio index (`audio.device`, Q-usb). Band 0.10–0.60 m
and `min_populated_bins: 1` are carried with "tune at B11".
**What the desktop proves:** the refusal (no D455), the spelling guards, the
retirement gate, flag-off identity. **What only the dog proves:** that the
admission passes — i.e. that the declared capabilities bind on aarch64/3.10
(HW-1 measured that `voice` does not install there), and every number.

## (f) Test strategy → pre-registered rows

`tests/test_hw5_physical_profile.py` (R1–R13 in `PREREGISTRATION.md`): the
profile loads over the real locked base; every new key admitted and its
misspelling refused through a REAL sibling overlay at `ConfigStore` /
`build_runtime` (TRUTH-1's pattern, no product symbol monkeypatched); the
`venue=` injection reaches `refuse_retired_venue` and every other adapter is
constructed identically; the desktop refusal quoted exactly; the CAP-1
declaration proved LIVE by a counterfactual whose only delta is
`semantic_source: oracle`; the no-oracle grep over the profile; flag-off
identity of the merged mapping for no-profile and `prototype`; the
declared-ahead-of-reader key set enumerated with its owed read site. Seeds RED
on an import-verified scratch copy. `tests/test_prototype_profile.py`'s family
enumeration gains a marked `CARD HW-5` block (TRUTH-1/HW-4 precedent).

## (g) Risks, and what this design does NOT cover

* **H1 (taken in the correction pass, 19:xx).** The first pass shipped
  `backend: go2` as a SCALAR and the LiDAR numbers under `perception.lidar_*`.
  HW-2 had already landed `web_panel._build_backend` reading `backend:` as a
  SECTION, so the profile could not be built through the product launcher at
  all, and the four lidar keys were read by nothing. Fixed: the profile speaks
  HW-2's vocabulary, the four keys are gone, and R11 is now a LAUNCHER row
  (`web_panel.build_runtime` with `$PARCEL_PROFILE`) instead of a grep for a
  literal that survived HW-2's refactor.
* **F1 (design correction owed).** `REGISTERED_CAPABILITIES` :707 has no
  hardware row — every one of the eight is about the semantic-source axis, and
  all eight BIND on this desktop (measured). So `check_required_capabilities`
  cannot express "needs a D455/DDS" and **design §4 S14, §5.8 and §9's
  acceptance row are wrong where they say the CAP-1 message is the desktop
  refusal**: that refusal is VENUE-1's. HW-5 delivers both halves honestly —
  the real refusal, and a declaration proved non-inert by counterfactual. A
  hardware capability would be an `admission.py` change, which this card is
  forbidden ("declare, don't change the check").
* **F2.** `tests/test_cap1_admission.py:769-777` asserts every
  `configs/navigation/*.yaml` declares nothing. That glob is non-recursive
  (`cities/`, `experiments/`, `models/` are already outside it), so the venue
  file goes to `configs/navigation/venues/`. This is stated, not slipped: HW-5
  adds its own guard that NO file under `configs/navigation/**` other than the
  venue file declares — strictly more coverage than CAP-1's. Handoff to CAP-1's
  owner: widen the loop's sentence rather than its glob.
* **F3.** A physical profile must never write `control.controller`,
  `control.unitree_sport.axes_commissioned`, `state_frame_commissioned`,
  `allowed_modes`, `battery.simulated_percent`, `simulation.*`, `poses`, or
  `perception.maps.enabled` — the forbidden list of §(c)'s no-oracle test.
  Each is a fact the runtime would otherwise be handed instead of sensing.
* **F2 (verifier, taken).** A profile that cannot be READ must never be
  reported as a stated gap. `active_venue()` wrapped `ProfileError` in
  `IngestRefusedError`, which `coverage()` and `preflight.default_reader_factory`
  both read as "no adapter for this transport" — so a misspelled
  `$PARCEL_PROFILE` printed `served: 0 unserved: 28` with the reason discarded.
  The refusal now propagates unchanged.
* Not covered: the `Go2Backend` itself (HW-2), the panel's mic route (HW-MIC),
  the aarch64 gate (HW-7), and any value that B11/B-con measures.
