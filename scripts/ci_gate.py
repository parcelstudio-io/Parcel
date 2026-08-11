#!/usr/bin/env python
"""Parcel CI / eval-runner gate — the per-commit + nightly promotion gate.

Why this exists
---------------
The independent verdict (``scrum/20260808/task_1/INDEPENDENT_VERDICT_FABLE.md``)
and the productionization audit (``scrum/20260809/task_1``) both flag the same
load-bearing hole: 222 test files and rich eval harnesses exist, but there is
**no runner and no scheduler** — no ``.github/workflows``, an empty crontab. So
every promotion gate is manual, and Design A's *model-off non-inferiority*
guarantee is unfalsifiable because nothing enforces it. This module is the
missing runner. It does **not** invent new evals; it *wraps the harnesses that
already exist* and turns the aspirational promotion gates into an executable,
exit-coded gate.

What it enforces (tiered by cost)
---------------------------------
``--tier commit`` (fast, offline, deterministic — no network, no model server):
  * the default gate ``pytest -m "not slow"`` (the 3097-passing suite);
  * ``ruff`` — ratcheted against a pinned baseline so pre-existing debt in
    modules this card does not own cannot block a commit, while any *new*
    violation reddens (see ``scripts/ci_ruff_baseline.json``);
  * the frozen-digest integrity tests (nav_instruct v3, embodied plan,
    conversation_quality, personal_convo) — a sha drift reddens — plus an
    independent sentinel sha over the immutable frozen manifests;
  * the mutation-panel freshness guard;
  * **the three hard regression gates the verdict demands:**
    (a) MODEL-OFF NON-INFERIORITY — the SigLIP / OWLv2(B3) / memory flag-off
        byte-equal cells, wired into one gate so Design A cannot silently rot;
    (b) LATENCY-TAIL — the committed p95/p99 percentile pins;
    (c) HARD-SAFETY — zero hard collisions on every product artifact and no new
        false_arrival, read from the existing harness ledgers.

``--tier nightly`` (slow, scheduled): everything above, plus the slow suite
  (live-sim e2e + acoustic rig via ``-m slow``), the nav_instruct minival
  candidate run, the mutation panel (6/6 kills), and the metamorphic suite.
  Numeric eval outputs are reported; only the pre-registered hard invariants
  (collisions, false_arrival, mutation survivors) gate.

Any hard gate red ==> non-zero exit. Report-only gates never change the exit
code; they are printed so a human sees the trend.

Self-test
---------
``tests/test_ci_gate.py`` seeds a regression into each hard gate's input (a
byte-changed frozen digest, an injected collision, a new false_arrival, a
latency-tail spike, a flag-off drift) and asserts the gate reddens — the same
"would the harness notice if it were wrong?" discipline as the mutation panel.

Usage::

    .parcel/bin/python scripts/ci_gate.py --tier commit
    .parcel/bin/python scripts/ci_gate.py --tier nightly
    .parcel/bin/python scripts/ci_gate.py --tier commit --json
    .parcel/bin/python scripts/ci_gate.py --update-ruff-baseline   # re-pin debt
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PYTHON = sys.executable

# ---------------------------------------------------------------------------
# Wiring: node-id selections over the EXISTING harnesses (never new evals).
# Every id here was confirmed to collect on 2026-08-09.
# ---------------------------------------------------------------------------

#: (a) MODEL-OFF NON-INFERIORITY — the flag-off byte-equal cells the SigLIP,
#: OWLv2(B3) and tiered-memory lanes already wrote, gathered into one gate.
MODEL_OFF_NODE_IDS: tuple[str, ...] = (
    # SigLIP-2 (PARCEL_SIGLIP2_ONNX, default off): fallback == pre-neural oracle
    "tests/test_siglip_real_embeddings.py::test_weights_absent_match_is_byte_identical_to_pre_neural_stub",
    "tests/test_siglip_real_embeddings.py::test_onnx_path_is_opt_in_even_when_weights_present",
    # OWLv2 / B3 (PARCEL_OWLV2_ONNX, default off): detector-off is additive
    "tests/test_owlv2_detector.py::test_default_is_detector_unavailable",
    "tests/test_owlv2_detector.py::test_missing_weights_returns_none",
    "tests/test_owlv2_detector.py::test_eval_reports_skipped_when_disabled",
    # B3 seg-truth foundation: GT/clean detections are byte-identical + no chain
    "tests/test_cam_foundation.py::test_frozen_gt_source_artifacts_are_byte_identical",
    "tests/test_cam_foundation.py::test_tier_does_not_install_a_perception_chain",
    # Cross-session / tiered memory: off by default changes nothing
    "tests/test_tiered_memory.py::test_prompting_memory_is_off_by_default_and_fails_closed_on_unknown_keys",
    "tests/test_tiered_memory.py::test_read_path_is_deterministic",
    "tests/test_tiered_memory.py::test_retrieve_never_invokes_summarizer_or_distiller",
)

#: Frozen-digest integrity — a sha drift on a frozen pack reddens.
FROZEN_DIGEST_NODE_IDS: tuple[str, ...] = (
    "tests/test_nav_instruct_episodes_v3.py::test_checked_in_v3_files_equal_a_fresh_generation",
    "tests/test_nav_instruct_episodes_v3.py::test_v3_manifest_records_the_correction_it_carries",
    "tests/test_nav_instruct_episodes_v3.py::test_frozen_ledger_prefix_is_byte_identical_after_the_v3_append",
    "tests/test_embodied_plan_eval.py::test_manifest_hash_locks_every_physical_input_and_unique_seed",
    "tests/test_conversation_quality_v1.py::test_manifest_locks_all_conversation_inputs",
    "tests/test_personal_convo_v1.py::test_manifest_locks_all_inputs_and_covers_every_family",
)

#: The mutation panel's anti-rot guards (both fast enough for the commit tier).
#: The first reads the committed payload; the second re-derives its
#: safety-relevant fields from a LIVE clean run, because a committed payload
#: alone cannot tell you whether it is still true (lane E7, 2026-08-10).
MUTATION_FRESHNESS_NODE_IDS: tuple[str, ...] = (
    "tests/test_mutation_panel_freshness.py::test_committed_mutation_panel_is_on_the_current_frozen_set",
    "tests/test_mutation_panel_freshness.py::test_committed_panel_safety_fields_still_reproduce",
)

#: (b) LATENCY-TAIL — the committed p95/p99 percentile pins that exist today
#: (observability component percentiles + the beat-sync scheduling budget).
LATENCY_TAIL_NODE_IDS: tuple[str, ...] = (
    "tests/test_beat_sync.py::test_nods_land_on_accents_within_the_perceptual_budget",
    "tests/test_beat_sync.py::test_control_rate_cannot_meet_the_apex_budget",
    "tests/test_observability_planning.py",
)

#: Independent frozen-digest sentinels: a byte over any of these immutable
#: manifests moves the sha. Kept to files that are committed-clean and frozen by
#: policy (never concurrently edited), so the gate is deterministic. The
#: authoritative recompute-vs-manifest coverage is the pytest ids above; this
#: sentinel is what the self-test seeds to prove the gate is not theatre.
#:
#: EVERY manifest carrying ``"frozen": true`` belongs here. ``personal_convo_v1``
#: was NOT pinned during task_15 and that is exactly why a green gate missed its
#: pack_digest moving under card M-A (Fable audit ``AUDIT_FABLE_INDEPENDENT.md``,
#: BLOCKING 2). Adding a frozen suite without adding it here re-opens that hole,
#: so ``tests/test_ci_gate.py`` pins the set of frozen-but-unpinned manifests and
#: seeds each pin here individually to prove it reddens.
#:
#: Re-pin log — one entry per authorized movement, because a sentinel that moves
#: without a reason is a sentinel nobody trusts:
#:
#: * ``embodied_plan_v1/manifest.json`` ``33c662c8…`` -> ``22736f6e…``,
#:   2026-08-10, lane E5, EXPLICIT OWNER AUTHORIZATION ("1. person clearance.
#:   Implement your recommendation"). **Nothing about the eval changed.** The
#:   manifest SHA-locks ``configs/robot.yaml`` as an input, that file was retuned
#:   (``safety.person_stop_m`` 1.0 -> 1.2, ``person_slow_m`` 2.0 -> 2.5,
#:   ``owner_follow.owner_keepout_m`` 1.55 -> 1.75), so the lock had to be
#:   refreshed ``f6468887…`` -> ``aff69113…`` and the manifest's own sha moved
#:   MECHANICALLY with it. The suite's BEHAVIOUR is unmoved and was re-measured
#:   against a scratch copy of the manifest BEFORE the committed file was
#:   touched: 997 simulator steps, 0 collisions, 0 timeouts, minimum clearance
#:   0.883147 m, per-case 200/260/64/389/84 — bit-identical to the frozen row.
#:   Only the one ``robot_config`` sha string changed in the file; every other
#:   locked input and every byte of layout is untouched. Full 2x2 attribution in
#:   ``scrum/20260809/task_15/E5_PERSON_CLEARANCE_STATUS.md``.
#:
#: * ``nav_instruct/episodes/v4/manifest.json`` **ADDED** (not moved) as
#:   ``b2945444…``, 2026-08-11, lane E8, EXPLICIT OWNER AUTHORIZATION (re-freeze
#:   the episodes to v4 so the follow goal radii match the retuned stand-off,
#:   keeping the pedestrian-clearance gain). **v3's pin and v3's bytes are
#:   UNCHANGED** — v3 stays frozen, so every historical row measured against it
#:   keeps meaning what it meant. v4 is a new frozen set carrying exactly one
#:   correction: the ``follow_owner`` goal radius stops being the literal 1.8 m
#:   and becomes ``(desired_distance_m + distance_deadband_m) +
#:   OWNER_STAND_OFF_MARGIN_M`` = 2.13 m, derived from the same authority terms
#:   the follow controller obeys. It is pinned here for the reason the others
#:   are: it is now the newest frozen set (``mutation_panel.py`` and the
#:   frozen-baseline ledger row both moved onto it), so a byte of it moving must
#:   be loud. Only the five ``follow_owner`` episodes' ``goal.radius_m`` and the
#:   ``shortest_path_m`` computed from it differ from v3; the robot's own arrival
#:   claims are byte-identical across the two sets. 2x2 attribution and the
#:   per-episode bridge: ``scrum/20260809/task_15/E8_V4_REFREEZE_STATUS.md``,
#:   ``evals/nav_instruct/bridge_v3_v4.py``.
DIGEST_SENTINELS: dict[str, str] = {
    "evals/nav_instruct/episodes/v3/manifest.json": "eb1289e9723e008336b33bff83f2e4c9a91e07d1e6552866f6ede52da7f57858",
    "evals/nav_instruct/episodes/v4/manifest.json": "b29454443e93b68d238c11d31298e81c2e9cae89d7669d9d6556405e9b7388ec",
    "evals/companion/embodied_plan_v1/manifest.json": "22736f6e0e4b106c0d130b9f7f425feca465a73b20da1431dfd5e2e3b1ce9389",
    "evals/companion/personal_convo_v1/manifest.json": "d338f3352cd9597aeb9977f75c139d926bdfba1fe1d6b036b9a3ace08a1cf114",
}

# ---------------------------------------------------------------------------
# (c) HARD-SAFETY — product-path artifacts and their pinned invariants.
# ---------------------------------------------------------------------------
NAV_LEDGER = REPO / "evals" / "nav_instruct" / "results" / "ledger.jsonl"
MUTATION_PANEL_JSON = REPO / "evals" / "nav_instruct" / "results" / "mutation_panel.json"
FOLLOWBENCH_LEDGER = REPO / "evals" / "companion_nav" / "results" / "ledger.jsonl"
WALK_WITH_ME_LEDGER = REPO / "evals" / "walk_with_me" / "results" / "ledger.jsonl"

#: The frozen baseline is collision-free with zero false arrivals; that is the
#: Design-A/product guarantee. Any increase is a new hazard.
PINNED_FROZEN_FALSE_ARRIVAL = 0

RUFF_BASELINE = REPO / "scripts" / "ci_ruff_baseline.json"

#: Persisted product latency ledger + pinned p95/p99 baseline (N19 / C-A).
#: The percentile-pin pytest selection (``LATENCY_TAIL_NODE_IDS``) stays; this
#: is the ledger source the ratchet reads once enough rows exist.
LATENCY_LEDGER = REPO / "evals" / "latency" / "ledger.jsonl"
LATENCY_BASELINE = REPO / "evals" / "latency" / "baseline.json"

#: Latency-tail ratchet tolerance against the pinned baseline. 1.20 mirrors the
#: BARN controller-p99 ratio ceiling already in the repo.
LATENCY_TAIL_MARGIN = 1.20


# ---------------------------------------------------------------------------
# Gate result model
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    """One gate and its verdict.

    ``status`` is one of ``pass`` / ``fail`` / ``error`` / ``skip`` / ``report``.
    A run's exit code is non-zero iff some ``hard`` gate is ``fail`` or ``error``.
    ``report`` gates (``hard=False``) are printed but never change the exit code.
    """

    name: str
    tier: str
    hard: bool
    status: str
    detail: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_red(self) -> bool:
        return self.status in {"fail", "error"}

    @property
    def gating_red(self) -> bool:
        return self.hard and self.is_red

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


_ICON = {
    "pass": "PASS",
    "fail": "FAIL",
    "error": "ERROR",
    "skip": "skip",
    "report": "report",
}


# ---------------------------------------------------------------------------
# Small IO helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _base_env() -> dict[str, str]:
    env = dict(os.environ)
    # MuJoCo runs headless offscreen; egl matches how the default gate is run
    # here. No network, no display, no model server needed for the commit tier.
    env.setdefault("MUJOCO_GL", "egl")
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


# ---------------------------------------------------------------------------
# Pytest driver
# ---------------------------------------------------------------------------


def run_pytest(
    selection: list[str] | tuple[str, ...],
    *,
    markers: str | None = None,
    env_extra: dict[str, str] | None = None,
    plugins: list[str] | None = None,
    extra_args: list[str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a pytest selection in a subprocess; return the completed process."""

    cmd = [PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if markers:
        cmd += ["-m", markers]
    for plugin in plugins or []:
        cmd += ["-p", plugin]
    cmd += list(extra_args or [])
    cmd += list(selection)
    env = _base_env()
    # Guarantee ``scripts.*`` (seed plugin) is importable in the subprocess.
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(REPO), env.get("PYTHONPATH", "")]))
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        cmd,
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _pytest_gate(
    name: str,
    tier: str,
    selection: tuple[str, ...],
    *,
    hard: bool = True,
    markers: str | None = None,
    env_extra: dict[str, str] | None = None,
    timeout: int | None = None,
) -> GateResult:
    try:
        proc = run_pytest(
            selection, markers=markers, env_extra=env_extra, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return GateResult(name, tier, hard, "error", f"pytest timed out after {timeout}s")
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else ""
    if proc.returncode == 0:
        return GateResult(name, tier, hard, "pass", summary)
    # Surface the failing lines so a human sees why without a re-run.
    fails = [ln for ln in tail if ln.startswith(("FAILED", "ERROR"))]
    detail = summary + ("\n    " + "\n    ".join(fails[:12]) if fails else "")
    if not detail.strip():
        detail = (proc.stderr or "").strip().splitlines()[-1:] or ["pytest failed"]
        detail = detail[0]
    return GateResult(name, tier, hard, "fail", detail, extra={"returncode": proc.returncode})


# ---------------------------------------------------------------------------
# Pure artifact checks (seedable — the self-test feeds these corrupted inputs)
# ---------------------------------------------------------------------------


def evaluate_frozen_digest_sentinels(
    sentinels: dict[str, str], *, root: Path = REPO, tier: str = "commit"
) -> GateResult:
    """A byte-changed frozen manifest moves its sha and reddens here."""

    problems: list[str] = []
    checked = 0
    for relpath, expected in sentinels.items():
        path = root / relpath
        if not path.exists():
            problems.append(f"{relpath}: MISSING")
            continue
        actual = _sha256_file(path)
        checked += 1
        if actual != expected:
            problems.append(f"{relpath}: sha {actual[:12]} != pinned {expected[:12]}")
    if problems:
        return GateResult(
            "frozen-digest-sentinels", tier, True, "fail",
            "; ".join(problems), extra={"checked": checked},
        )
    return GateResult(
        "frozen-digest-sentinels", tier, True, "pass",
        f"{checked} immutable manifest(s) byte-identical to pin",
        extra={"checked": checked},
    )


def _latest_frozen_baseline_row(nav_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    frozen = [r for r in nav_rows if r.get("frozen_baseline") is True]
    return frozen[-1] if frozen else None


def _panel_safety_fields_live() -> dict[str, Any]:
    """Live re-derivation of the panel clean run's safety-relevant fields."""

    from scripts.mutation_panel import live_clean_safety_fields

    return live_clean_safety_fields()


def evaluate_hard_safety(
    *,
    nav_ledger: Path = NAV_LEDGER,
    mutation_panel: Path = MUTATION_PANEL_JSON,
    followbench_ledger: Path = FOLLOWBENCH_LEDGER,
    walk_with_me_ledger: Path = WALK_WITH_ME_LEDGER,
    pinned_false_arrival: int = PINNED_FROZEN_FALSE_ARRIVAL,
    reproduce_panel: Callable[[], dict[str, Any]] | None = None,
    tier: str = "commit",
) -> GateResult:
    """Zero hard collisions on every product artifact + no new false_arrival.

    Reads the existing harness ledgers. The frozen-baseline nav row and the
    mutation-panel clean run and every follow-bench row must show zero hard
    collisions; the frozen-baseline false_arrival may not exceed its pin.
    walk_with_me rows join only when they carry ``hard_collision_total`` —
    legacy stub rows without the field are skipped by field-presence.

    **Freshness (lane E7, 2026-08-10).** The mutation panel is the only input
    here that is a *derived artifact* rather than a run ledger, and this gate
    used to certify ``no_false_arrival`` straight out of it. That is a hole with
    a name: the committed payload was written at 19c9226 and a live run on the
    current tree contradicted it (``no_false_arrival`` true -> false) while the
    gate kept printing ``no_false_arrival=True``. So the committed payload's
    safety-relevant fields are now RE-DERIVED live (one clean run, ~4 s) and
    must match. A gate may read a stale artifact; it may not *certify a safety
    property* from one.

    ``reproduce_panel`` is the seam: ``None`` means "re-derive live, but only
    when reading the real committed artifact" — a synthetic ``mutation_panel``
    path (the self-tests) has no tree to reproduce from, so the comparison is
    recorded as skipped rather than silently passed.
    """

    problems: list[str] = []
    checks: list[str] = []

    nav_rows = _read_jsonl(nav_ledger)
    baseline = _latest_frozen_baseline_row(nav_rows)
    if baseline is None:
        problems.append("nav_instruct: no frozen_baseline row (missing evidence)")
    else:
        rid = baseline.get("report_id", "?")
        coll = int(baseline.get("collision_total", -1))
        fa = int(baseline.get("authority_histogram", {}).get("false_arrival", -1))
        checks.append(f"nav frozen baseline {rid}: collisions={coll} false_arrival={fa}")
        if coll != 0:
            problems.append(f"nav_instruct frozen baseline collision_total={coll} (expected 0)")
        if fa > pinned_false_arrival:
            problems.append(
                f"nav_instruct frozen baseline false_arrival={fa} > pin {pinned_false_arrival}"
            )

    if mutation_panel.exists():
        panel = json.loads(mutation_panel.read_text(encoding="utf-8"))
        clean = panel.get("clean_run", {})
        coll = int(clean.get("collisions", -1))
        no_fa = bool(panel.get("clean_checks", {}).get("no_false_arrival", False))
        checks.append(f"mutation panel clean: collisions={coll} no_false_arrival={no_fa}")
        if coll != 0:
            problems.append(f"mutation panel clean_run collisions={coll} (expected 0)")
        if not no_fa:
            problems.append("mutation panel clean run has a false arrival (no_false_arrival=false)")

        reproducer = reproduce_panel
        if reproducer is None and mutation_panel == MUTATION_PANEL_JSON:
            reproducer = _panel_safety_fields_live
        if reproducer is None:
            checks.append(
                "mutation panel freshness: skipped (synthetic artifact, no tree to reproduce)"
            )
        else:
            from scripts.mutation_panel import clean_safety_fields

            committed_fields = clean_safety_fields(panel)
            live_fields = reproducer()
            fresh = live_fields == committed_fields
            checks.append(f"mutation panel freshness: committed fields reproduce live = {fresh}")
            if not fresh:
                drift = sorted(
                    key
                    for key in set(committed_fields) | set(live_fields)
                    if committed_fields.get(key) != live_fields.get(key)
                )
                problems.append(
                    "mutation panel is STALE: a live clean run contradicts the committed "
                    f"artifact on {drift} (committed={committed_fields} live={live_fields}) "
                    "— the hard gate will not certify a safety property from it"
                )
    else:
        problems.append("mutation_panel.json missing (missing evidence)")

    fb_rows = _read_jsonl(followbench_ledger)
    if fb_rows:
        bad = [
            r.get("report_id", r.get("run_id", "?"))
            for r in fb_rows
            if int(r.get("hard_collision_total", -1)) != 0
        ]
        checks.append(f"follow-bench: {len(fb_rows)} row(s), hard_collision_total all 0 = {not bad}")
        if bad:
            problems.append(f"follow-bench rows with hard collisions: {bad}")
    else:
        checks.append("follow-bench: no rows (skipped)")

    wwm_rows = _read_jsonl(walk_with_me_ledger)
    wwm_with_field = [r for r in wwm_rows if "hard_collision_total" in r]
    if wwm_with_field:
        bad = [
            r.get("report_id", r.get("run_id", "?"))
            for r in wwm_with_field
            if int(r.get("hard_collision_total", -1)) != 0
        ]
        checks.append(
            f"walk_with_me: {len(wwm_with_field)}/{len(wwm_rows)} row(s) with "
            f"hard_collision_total, all 0 = {not bad}"
        )
        if bad:
            problems.append(f"walk_with_me rows with hard collisions: {bad}")
    else:
        checks.append(
            f"walk_with_me: {len(wwm_rows)} row(s), none carry hard_collision_total (skipped)"
        )

    detail = " | ".join(checks)
    if problems:
        return GateResult("hard-safety", tier, True, "fail", "; ".join(problems), extra={"checks": checks})
    return GateResult("hard-safety", tier, True, "pass", detail, extra={"checks": checks})


def evaluate_latency_ratchet(
    series: dict[str, dict[str, float]],
    baseline: dict[str, dict[str, float]],
    *,
    margin: float = LATENCY_TAIL_MARGIN,
    tier: str = "commit",
    name: str = "latency-tail-ratchet",
) -> GateResult:
    """Ratchet p95/p99 in ``series`` against ``baseline * margin``.

    Pure core used by the ledger source switch and by the self-test (a seeded
    spike must still redden). The commit tier also keeps the percentile-pin
    pytest selection (``LATENCY_TAIL_NODE_IDS``).
    """

    problems: list[str] = []
    for metric, base in baseline.items():
        cur = series.get(metric)
        if cur is None:
            continue
        for key in ("p95_ms", "p99_ms"):
            if key in base and key in cur:
                ceiling = base[key] * margin
                if cur[key] > ceiling:
                    problems.append(
                        f"{metric}.{key} {cur[key]:.2f} > {ceiling:.2f} (baseline {base[key]:.2f} x {margin})"
                    )
    if problems:
        return GateResult(name, tier, True, "fail", "; ".join(problems))
    return GateResult(
        name, tier, True, "pass",
        f"{len(baseline)} metric series within {margin}x tail ceiling",
    )


def evaluate_latency_ledger(
    *,
    ledger: Path = LATENCY_LEDGER,
    baseline_path: Path = LATENCY_BASELINE,
    margin: float = LATENCY_TAIL_MARGIN,
    tier: str = "commit",
) -> GateResult:
    """Point the latency-tail ratchet at ``evals/latency/ledger.jsonl``.

    While the ledger has fewer rows than the pinned ``window``, skip with a
    note (never red) — the percentile-pin pytest gate remains authoritative.
    """

    if not baseline_path.exists():
        return GateResult(
            "latency-tail-ledger", tier, True, "error",
            f"missing latency baseline at {baseline_path.name}",
        )
    try:
        doc = json.loads(baseline_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return GateResult("latency-tail-ledger", tier, True, "error", f"baseline JSON: {exc}")
    window = int(doc.get("window", 5))
    baseline_metrics = doc.get("metrics") or {}
    if not isinstance(baseline_metrics, dict) or not baseline_metrics:
        return GateResult(
            "latency-tail-ledger", tier, True, "error", "baseline.metrics missing or empty"
        )

    rows = _read_jsonl(ledger)
    if len(rows) < window:
        return GateResult(
            "latency-tail-ledger",
            tier,
            True,
            "skip",
            (
                f"ledger rows={len(rows)} < window={window}; ratchet skipped "
                "(percentile-pin pytest remains authoritative)"
            ),
            extra={"rows": len(rows), "window": window},
        )

    from parcel_robot.observability import latency_tail_series

    series = latency_tail_series(rows[-1])
    result = evaluate_latency_ratchet(
        series, baseline_metrics, margin=margin, tier=tier, name="latency-tail-ledger"
    )
    if result.status == "pass":
        result.detail = (
            f"latest row {rows[-1].get('row_id', '?')}: {result.detail} "
            f"(rows={len(rows)}, window={window})"
        )
    return result


# ---------------------------------------------------------------------------
# Ruff — ratcheted against a pinned baseline of pre-existing debt
# ---------------------------------------------------------------------------


def _ruff_fingerprints(root: Path = REPO) -> tuple[list[str], subprocess.CompletedProcess[str]]:
    """Return sorted ``relpath::code`` fingerprints of current ruff violations."""

    proc = subprocess.run(
        [PYTHON, "-m", "ruff", "check", ".", "--output-format=json"],
        cwd=str(root),
        env=_base_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return [], proc
    fps: set[str] = set()
    for item in items:
        filename = item.get("filename", "")
        try:
            rel = str(Path(filename).resolve().relative_to(root))
        except ValueError:
            rel = filename
        code = item.get("code") or "UNKNOWN"
        fps.add(f"{rel}::{code}")
    return sorted(fps), proc


def evaluate_ruff(*, baseline_path: Path = RUFF_BASELINE, tier: str = "commit") -> GateResult:
    """Fail only on ruff violations whose (file, rule) is not in the baseline.

    The repo carries pre-existing ruff debt in modules this card does not own
    (storefront, uwb, route_memory, ...); a hard ``ruff check`` would block every
    commit. The ratchet keeps ruff a real per-commit gate — new code must be
    clean — while the debt is burned down separately (it is enumerated in the
    baseline file and in docs/CI.md as a handoff).
    """

    current, proc = _ruff_fingerprints()
    if proc.returncode not in (0, 1):  # 0 clean, 1 = violations found; else crash
        return GateResult("ruff", tier, True, "error", (proc.stderr or "ruff failed").strip()[:400])
    if not baseline_path.exists():
        return GateResult(
            "ruff", tier, True, "error",
            f"no ruff baseline at {baseline_path.name}; run --update-ruff-baseline",
        )
    baseline = set(json.loads(baseline_path.read_text(encoding="utf-8")).get("fingerprints", []))
    new = sorted(set(current) - baseline)
    detail = f"{len(current)} violation(s), baseline {len(baseline)}, new {len(new)}"
    if new:
        return GateResult(
            "ruff", tier, True, "fail",
            detail + " -> " + "; ".join(new[:15]), extra={"new": new},
        )
    return GateResult("ruff", tier, True, "pass", detail)


def update_ruff_baseline(*, baseline_path: Path = RUFF_BASELINE) -> int:
    current, _ = _ruff_fingerprints()
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": (
            "Pre-existing ruff debt this CI gate ratchets against. New (file, rule) "
            "fingerprints beyond this set redden scripts/ci_gate.py. Burn down toward "
            "an empty list; regenerate with `ci_gate.py --update-ruff-baseline`."
        ),
        "count": len(current),
        "fingerprints": current,
    }
    baseline_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {baseline_path} with {len(current)} fingerprint(s)")
    return 0


# ---------------------------------------------------------------------------
# Nightly-only harness runs (offline, in-process where possible)
# ---------------------------------------------------------------------------


def evaluate_mutation_panel(tier: str = "nightly") -> GateResult:
    """Run the mutation panel in-process: 6/6 kills, no survivors (hard)."""

    try:
        from scripts.mutation_panel import run_panel
    except Exception as exc:  # noqa: BLE001
        return GateResult("mutation-panel", tier, True, "error", f"import failed: {exc}")
    try:
        payload = run_panel()
    except Exception as exc:  # noqa: BLE001
        return GateResult("mutation-panel", tier, True, "error", f"{type(exc).__name__}: {exc}")
    killed = [m for m in payload["mutants"] if m["verdict"] == "killed"]
    survivors = payload.get("survivors") or []
    detail = f"{len(killed)}/{len(payload['mutants'])} killed, survivors={survivors}"
    if survivors or not payload.get("passed"):
        return GateResult("mutation-panel", tier, True, "fail", detail)
    return GateResult("mutation-panel", tier, True, "pass", detail)


def evaluate_nav_instruct_candidate(tier: str = "nightly") -> list[GateResult]:
    """Run the candidate minival; hard-gate collisions, report the rest."""

    before = {r.get("report_id") for r in _read_jsonl(NAV_LEDGER)}
    try:
        proc = subprocess.run(
            [
                PYTHON, "-m", "evals.nav_instruct.run_nav_instruct_v1",
                # v4 since the 2026-08-11 re-freeze (lane E8): the candidate arm
                # must run the same frozen set the frozen-baseline row and the
                # mutation panel are on, or the nightly comparison is between
                # two different eval regions.
                "--minival", "--mode", "candidate", "--episode-version", "v4",
            ],
            cwd=str(REPO), env=_base_env(), capture_output=True, text=True, timeout=1800,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [GateResult("nav-instruct-candidate", tier, True, "error", "timed out")]
    if proc.returncode != 0:
        return [GateResult("nav-instruct-candidate", tier, True, "fail", (proc.stderr or "run failed").strip()[-400:])]
    rows = _read_jsonl(NAV_LEDGER)
    new_rows = [r for r in rows if r.get("report_id") not in before]
    row = new_rows[-1] if new_rows else (rows[-1] if rows else {})
    coll = int(row.get("collision_total", -1))
    auth = row.get("authority_histogram", {})
    fa = int(auth.get("false_arrival", -1))
    sr = row.get("sr")
    results = [
        GateResult(
            "nav-instruct-candidate:collisions", tier, True,
            "pass" if coll == 0 else "fail",
            f"collision_total={coll} (report {row.get('report_id')})",
        ),
        GateResult(
            "nav-instruct-candidate:differential", tier, False, "report",
            f"sr={sr} authority={auth} false_arrival={fa}",
        ),
    ]
    return results


# ---------------------------------------------------------------------------
# Tier assembly
# ---------------------------------------------------------------------------


def run_commit_tier() -> list[GateResult]:
    tier = "commit"
    results: list[GateResult] = []
    # Cheap deterministic checks first (fast-fail signal without waiting on pytest).
    results.append(evaluate_ruff(tier=tier))
    results.append(evaluate_hard_safety(tier=tier))
    results.append(evaluate_frozen_digest_sentinels(DIGEST_SENTINELS, tier=tier))
    results.append(evaluate_latency_ledger(tier=tier))
    # Targeted hard-gate pytest selections (small, fast).
    results.append(_pytest_gate("model-off-non-inferiority", tier, MODEL_OFF_NODE_IDS, timeout=900))
    results.append(_pytest_gate("frozen-digest-integrity", tier, FROZEN_DIGEST_NODE_IDS, timeout=900))
    results.append(_pytest_gate("mutation-panel-freshness", tier, MUTATION_FRESHNESS_NODE_IDS, timeout=600))
    # Percentile-pin pytest stays; ledger source switch is evaluate_latency_ledger above.
    results.append(_pytest_gate("latency-tail", tier, LATENCY_TAIL_NODE_IDS, timeout=600))
    # The full default gate last (the 3097-passing suite).
    results.append(
        _pytest_gate("default-suite", tier, (), markers="not slow", timeout=1800)
    )
    return results


def run_nightly_tier() -> list[GateResult]:
    tier = "nightly"
    results: list[GateResult] = []
    # Re-run every commit hard gate (nightly is a superset).
    results.append(evaluate_ruff(tier=tier))
    results.append(evaluate_hard_safety(tier=tier))
    results.append(evaluate_frozen_digest_sentinels(DIGEST_SENTINELS, tier=tier))
    results.append(evaluate_latency_ledger(tier=tier))
    results.append(_pytest_gate("model-off-non-inferiority", tier, MODEL_OFF_NODE_IDS, timeout=900))
    results.append(_pytest_gate("frozen-digest-integrity", tier, FROZEN_DIGEST_NODE_IDS, timeout=900))
    results.append(_pytest_gate("mutation-panel-freshness", tier, MUTATION_FRESHNESS_NODE_IDS, timeout=600))
    results.append(_pytest_gate("latency-tail", tier, LATENCY_TAIL_NODE_IDS, timeout=600))
    results.append(_pytest_gate("default-suite", tier, (), markers="not slow", timeout=1800))
    # Nightly-only: the slow harnesses.
    results.append(evaluate_mutation_panel(tier=tier))
    results.extend(evaluate_nav_instruct_candidate(tier=tier))
    results.append(
        _pytest_gate(
            "slow-suite", tier, (), markers="slow",
            env_extra={"PARCEL_NIGHTLY": "1"}, timeout=5400,
        )
    )
    # Report the metamorphic suite distinctly (already inside slow-suite).
    results.append(
        _pytest_gate(
            "metamorphic", tier, ("tests/test_nav_metamorphic.py",), markers="slow",
            hard=False, env_extra={"PARCEL_NIGHTLY": "1"}, timeout=1800,
        )
    )
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def summarize(results: list[GateResult], tier: str, elapsed: float) -> str:
    lines = [
        f"CI GATE — tier={tier}  ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})",
        "=" * 78,
    ]
    width = max((len(r.name) for r in results), default=20)
    for r in results:
        flag = "HARD" if r.hard else "soft"
        lines.append(f"[{_ICON.get(r.status, r.status):>6}] {flag}  {r.name:<{width}}  {r.detail}")
    lines.append("=" * 78)
    gating = [r for r in results if r.gating_red]
    soft_red = [r for r in results if r.is_red and not r.hard]
    if gating:
        lines.append(f"RESULT: FAIL — {len(gating)} hard gate(s) red: {', '.join(r.name for r in gating)}")
    else:
        lines.append("RESULT: PASS — every hard gate green.")
    if soft_red:
        lines.append(f"  (report-only red, non-gating: {', '.join(r.name for r in soft_red)})")
    lines.append(f"  elapsed {elapsed:.1f}s")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tier", choices=("commit", "nightly"), default="commit")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON as well")
    parser.add_argument(
        "--update-ruff-baseline", action="store_true",
        help="re-pin the ruff debt baseline to the current tree and exit",
    )
    args = parser.parse_args(argv)

    if args.update_ruff_baseline:
        return update_ruff_baseline()

    started = time.perf_counter()
    results = run_commit_tier() if args.tier == "commit" else run_nightly_tier()
    elapsed = time.perf_counter() - started

    print(summarize(results, args.tier, elapsed))
    if args.json:
        print(json.dumps(
            {"tier": args.tier, "elapsed_s": elapsed, "gates": [r.as_dict() for r in results]},
            indent=2, sort_keys=True,
        ))
    return 1 if any(r.gating_red for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
