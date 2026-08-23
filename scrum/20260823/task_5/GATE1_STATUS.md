# GATE-1 — executor report (Opus, 2026-08-23)

Both defects from the ARCH-1 addendum are closed. Nothing was committed; the
tree is left for the integrator.

## 1. Hard-skip exit semantics (T12)

`main()` returned `1 if any(gating_red) else 0`, so a host where four HARD rows
printed `[  skip]` exited **0** — the same number a fully green run gives. The
summary sentence was already truthful (task_42 fixed that half); the exit code
was not.

Now: **0** every hard gate ran and none is red · **1** some hard gate is red ·
**2** nothing is red but a hard gate skipped. **Red takes precedence over
incomplete.** `--json` gains a top-level `"incomplete": <bool>`, emitted on
every run (a key that appears only when true cannot be told from an old gate
that never wrote it). **Summary text is unchanged, byte for byte, on both
branches** — pinned by two of the new tests.

## 2. Six-term envelope row (R09 / HW-6b)

`evaluate_stopping_envelope` now reads `load_stopping_envelope_record_v2` +
`derive_envelope_rows_v2`, so the row names `scan_age_s` and **cannot print a
five-term FITS**. On every host in the tree it prints `UNMEASURED — scan_age_s,
…` until box-day B11 measures it.

A record with no top-level `scan_age:` block (written before the term existed)
is read as five measured terms plus an UNMEASURED sixth rather than becoming an
`error` row — a term nobody wrote down is unmeasured, not a broken file. The
V2 reader's objection is kept in the new row extra `scan_age_provenance`. A
document *neither* reader accepts is still the non-gating `error` row HW-6
defined.

## Marked-region map (`scripts/ci_gate.py`)

Three NEW fenced regions, balanced 3-for-3 on the `# ---- CARD GATE-1` form:

| Lines | Region | Contents |
|---|---|---|
| 1079–1148 | `CARD GATE-1 six-term envelope read` | `load_envelope_inputs_v2` + why the fallback is UNMEASURED and not an error |
| 3022–3071 | `CARD GATE-1 incomplete exit status` | `GATE_EXIT_GREEN/RED/INCOMPLETE`, `hard_skips`, `gate_exit_code` |
| 3145–3160 | `CARD GATE-1 incomplete exit status` (inside `main`) | the `--json` field and the `return gate_exit_code(results)` |

No existing fence moved; HW-6 / HW-7 / XD-1 / GATE-0b marker balance re-checked
by `test_this_card_did_not_edit_another_cards_region` (green).

### Lines touched inside another card's region — HW-6, call sites only

Four lines inside `# ---- CARD HW-6 stopping-envelope`, each carrying an inline
`# CARD GATE-1:` comment (the protocol task_42 used for `summarize`). These
inline marks are **not** fences — a marker-balance check must count the
`# ---- CARD GATE-1` form.

- `:1005` import `derive_envelope_rows_v2` (replaces `derive_envelope_rows` and
  the now-unused `load_stopping_envelope_record`)
- `:1011` `inputs = load_envelope_inputs_v2(path)`
- `:1022` `rows = derive_envelope_rows_v2(inputs)`
- `:1034` new row extra `"scan_age_provenance"` — the sixth term's evidence
  pointer, so a reader can tell a record that predates the term from one that
  carries it unmeasured

### Unfenced shared prose corrected (both were false after this card)

- module docstring `:62` — "Any hard gate red ==> non-zero exit" replaced by the
  three-code table
- `GateResult` docstring `:437` — "exit code is non-zero iff … fail or error"

## Updated pins, each named

| File | Pin | Change |
|---|---|---|
| `tests/test_hw2_go2_backend.py` | `test_e7_the_gate_row_still_prints_the_five_term_verdict` | **deleted** — its own docstring said to delete it on this swap; a comment in its place records why |
| `tests/test_hw7_gate_aarch64.py` | `test_a_red_gate_still_reads_as_fail_whatever_else_skipped` | docstring only: it claimed "the exit code is unchanged". Its assertions are untouched and still green |
| `tests/test_hw6_stopping_envelope.py` | `VALID_RECORD` | gains `scan_age: {value: 0.0, provenance: rig}` — 0.0 leaves every sum, headroom and missing-set number in that file identical to what HW-6 pinned |
| `tests/test_hw6_stopping_envelope.py` | `test_the_shipped_records_…` (×3) | reads the record with `load_stopping_envelope_record_v2`, so "the row reports THAT record's missing terms" still means what it says |
| `tests/test_hw6_stopping_envelope.py` | same test, dev-box branch | missing set gains `scan_age_s` |
| `tests/test_hw6_stopping_envelope.py` | same test, fallback branch | `ENVELOPE_TERMS_V1` → `ENVELOPE_TERMS_V2` |
| `tests/test_hw6_stopping_envelope.py` | `test_the_row_resolves_by_hostname_…` | `len(missing) == len(ENVELOPE_TERMS_V1)` → `V2` |

All 30 of HW-6's test **functions** survive with their assertions intact; the
five lines above are the update e7's own failure message asked for. No test was
weakened, and `fast_commit_tier`'s `evaluate_default_suite` stub was not
touched.

## New capability tests (8)

`tests/test_hw7_gate_aarch64.py` — drive the real `main()` with
`run_commit_tier` replaced by a canned row set (no evaluator runs, no tier
executes):
- all-green → rc 0, `incomplete: false`, summary byte-identical
- four hard skips → **rc 2**, `incomplete: true`, summary byte-identical
- red + skips → **rc 1** (precedence), `incomplete: true`
- soft rows skipping → rc 0; the `GREEN/RED/INCOMPLETE == 0/1/2` mapping

`tests/test_hw6_stopping_envelope.py`:
- five measured terms + unmeasured scan age → UNMEASURED, never `FITS`
- a measured scan age is travel: 25 ms lands exactly on the envelope, 30 ms
  reddens the row (a row ignoring the term reports +6.25 mm in both)
- a five-term record, a malformed block → UNMEASURED with the reason kept; a
  document neither reader accepts → still the `error` row
- both shipped records name `scan_age_s` unmeasured with a real provenance (×3
  hostnames)

## Runs

All through `env -u TMPDIR ~/.cache/parcel-guard/pytest_guard.sh --label gate1`,
never `-n auto`, no tier run:

- `test_hw6_stopping_envelope.py` + `test_hw7_gate_aarch64.py` — **85 passed**
- `test_ci_gate.py` + `test_hw2_go2_backend.py` — **145 passed**
- every other module importing `scripts.ci_gate` (dr2, load_guard, nightly
  runner, unitree asset pack, v4s, eval assertions, jerk ratchet, gateway
  protocol) — **284 passed**
- `ruff check` clean on all four files; no `noqa` added (0 in the diff)

## For the integrator / verifier

- **Hosted CI now reddens on a skipping host.** `.github/workflows/ci.yml` runs
  `ci_gate.py --tier commit` and keys on the process exit code, so a runner
  missing a capability will report failure instead of success. That is the
  sanctioned behaviour ("incomplete ≠ pass"), but if the hosted job should
  tolerate it, the workflow needs `|| [ $? -eq 2 ]` — not this card's file.
- **`scripts/run_nightly.py` is deliberately unchanged.** It does not call
  `ci_gate.main()`; it computes its own `"exit_code": 1 if gating_red else 0`
  (`:343`). The same incompleteness argument applies to it, but it is outside
  this card's OWNS and is left as a named follow-up.
- Concurrent SENSE-1 edits (`backends/go2.py`, `core/input_health.py`,
  `config.py`, `lidar/`, `parcel_capture/`) are in the tree and are not mine.
