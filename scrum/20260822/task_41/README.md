# Task 41 — HW-5: `physical-profile` — one profile for the dog that declares what it needs and exposes no truth

**Executor:** Claude Opus · **Verifier:** Fable · **Board:** `../TASK_BOARD.md`
(P0 rules + anti-crash rules; wave-3 COMMON brief). **Design:**
`../WAVE3_HW_DESIGN_FABLE.md` §4 rows S14/S15, §5.8, §9 HW-5. **Evidence:**
`config.py:109` `OVERLAY_INTRODUCIBLE_KEYS` + the profile loader (a profile
names a SIBLING file `configs/robot.<profile>.yaml`, `PARCEL_PROFILE`,
deep-merge over the SHA-locked base — `config.py:18-60, 291-313`); TRUTH-1's
`planner_model` region + `tests/test_truth1_texts.py`'s `build_runtime`
overlay tests (the pattern); HW-4's `"audio"` key (D6: a dotted key under an
exempt parent is the inert-guard anti-pattern); `admission.py:733-1012`
(`required_capabilities`, `check_required_capabilities` — inert today,
nothing declares); HW-3's handoffs (the profile expresses
`min_populated_bins`, the band, the extrinsic; and passes `venue=` at
`scripts/parcel_capture/ingest/__init__.py:117-118` so the L2 retirement
gate stops being inert); HW-2's `backend: go2` (coordinate).

## Why
CAP-1's `check_required_capabilities` runs one line before the ingress
attach so a declaring profile refuses on a venue about to bind — but
nothing declares. The dog needs exactly one profile that declares its
capabilities (D455 depth, the DDS NIC, the array), selects the physical
backend and the array gateway, carries the band/extrinsic numbers as
NUMBERS (never code), and exposes no truth/oracle field (HLD Phase 1).

## Work
1. `DESIGN.md` first: the key set (`backend`, `required_capabilities`,
   `audio` (exists), `lidar` (band z-range, `min_populated_bins`,
   extrinsic 4×4 or xyz+rpy — say which and why), `venue`), each as a new
   `OVERLAY_INTRODUCIBLE_KEYS` entry in a marked `CARD HW-5` region with a
   pin test and a misspelling refusal (TRUTH-1's pattern); the refusal
   path on the desktop (no D455/DDS) through `check_required_capabilities`
   with the exact message; what the profile must NOT contain (any field
   the runtime could read as ground truth — enumerate the forbidden names
   from `robot_profile.py`/HLD and add a test that greps the profile).
2. `configs/robot.go2_edu_plus.yaml`: the overlay (defaults OFF for every
   behaviour flag; `roam.coverage` absent; numbers marked "tune at B11").
3. `config.py` keys + pins; `ingest/__init__.py:117-118` gains the
   `venue=` injection from the active profile (marked `CARD HW-5` region;
   default unchanged when no profile — flag-off identity for every
   existing adapter; HW-3's `L2Ingest(venue="go2_edu_plus")` refusal then
   becomes reachable — prove it).
4. Tests `tests/test_hw5_physical_profile.py`: profile loads over the
   locked base; every introduced key admitted and its misspelling refused
   at `build_runtime`; `check_required_capabilities` REFUSES on this
   desktop with the D455 absent (the real function, real profile, zero
   monkeypatch — the refusal IS the proof); no oracle field; flag-off: the
   sim profile and `robot.prototype.yaml` load byte-identically to HEAD;
   seeds RED per guard on an import-verified scratch.

OWNS: `configs/robot.go2_edu_plus.yaml` (new), `config.py` `CARD HW-5`
region, `ingest/__init__.py` `CARD HW-5` region, `tests/test_hw5_*.py`,
`task_41/` docs; `tests/test_prototype_profile.py` family-enumeration
(marked, TRUTH-1/HW-4 precedent). MUST NOT TOUCH: `configs/robot.yaml` (the
SHA-locked base), `robot.prototype.yaml`, `admission.py` logic (declare,
don't change the check), other cards' regions, the safety core. Shared:
`config.py` (HW-4's region exists), `runtime.py` only if a read site is
unavoidable (mkdir-lock; HW-2 is live).

## Definition of done
Desktop refusal through CAP-1 with the real profile; pins + misspelling
refusals; `venue=` wired; flag-off identity; no oracle field; seeds RED;
`HW5_STATUS.md` with pre-registered rows.

## Hardware-compat (§e)
Class MC (S14/S15). Every number in the profile says which box-day step
measures it (B11, Q-usb, Q-wire); the desktop proves the refusal, the dog
proves the admission.
