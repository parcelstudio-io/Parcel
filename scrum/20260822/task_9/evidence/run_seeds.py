"""Seeded-RED harness: mutate one line, run the guard, restore, verify sha."""
from __future__ import annotations

import hashlib
import pathlib
import shutil
import subprocess

REPO = pathlib.Path("/home/jaewoo-jang/Desktop/Projects/Parcel")
PY_ = str(REPO / ".parcel/bin/python")

SEEDS = [
 ("mad-zero margin re-introduced", "configs/navigation/prototype.yaml",
  "ranking_margin_mode: label_strength", "ranking_margin_mode: robust_z",
  "tests/test_p1d_vlm_veto.py::test_SEED_the_mad_zero_margin_re_introduced_collapses_admission"),
 ("promotion without k agreements", "src/parcel_robot/online_map/entries.py",
  "NAME_PROMOTION_VISITS = 3", "NAME_PROMOTION_VISITS = 1",
  "tests/test_p1d_vlm_veto.py::test_SEED_a_name_promoted_without_k_agreements_is_caught"),
 ("substring match admits (D-R3)", "src/parcel_robot/navigation/semantic_map.py",
  "            return MATCH_SUBSTRING\n    if matcher is not None:", "            return MATCH_ALIAS\n    if matcher is not None:",
  "tests/test_p1d_vlm_veto.py::test_SEED_a_coffee_shop_is_not_admitted_against_a_shop tests/test_p1d_vlm_veto.py::test_a_substring_only_winner_is_downgraded_on_the_mission_path"),
 ("veto enabled without the ask posture", "src/parcel_robot/perception_abstention.py",
  "if SIGNAL_VLM_VETO in set(self.signals) and not self.ask_below_threshold:",
  "if False and SIGNAL_VLM_VETO in set(self.signals) and not self.ask_below_threshold:",
  "tests/test_p1d_vlm_veto.py::test_selecting_the_veto_without_the_ask_posture_is_a_construction_error"),
 ("unavailable veto admits", "src/parcel_robot/perception_abstention.py",
  "                if answer == VETO_UNAVAILABLE:", "                if False and answer == VETO_UNAVAILABLE:",
  "tests/test_p1d_vlm_veto.py::test_an_unavailable_veto_asks_and_never_admits_or_refuses_outright"),
 # ---- post-verification seeds ------------------------------------------
 ("the veto seam has no producer", "src/parcel_robot/perception_abstention.py",
  "                seat = veto if veto is not None else resolve_veto(active)",
  "                seat = veto",
  "tests/test_p1d_eval_rows.py::test_an_injected_present_veto_admits_through_the_product_path"),
 ("resolve_veto hands back a runner, not a callable", "src/parcel_robot/perception_abstention.py",
  "        runner = runner_for(key).veto_callable()", "        runner = runner_for(key)",
  "tests/test_p1d_eval_rows.py::test_the_resolved_seat_is_a_CALLABLE_the_gate_can_actually_invoke"),
 ("the evidence stops carrying the crop", "src/parcel_robot/online_map/online_map.py",
  "                    crop_png=entry.thumbnail,", "                    crop_png=None,",
  "tests/test_p1d_eval_rows.py::test_an_injected_present_veto_admits_through_the_product_path"),
 ("a cold seat is admitted under a lease", "src/parcel_robot/vlm_veto/runner.py",
  "            if not self._warm:\n                return COLD_SEAT_ESTIMATE_MS",
  "            if False and not self._warm:\n                return COLD_SEAT_ESTIMATE_MS",
  "tests/test_p1d_vlm_veto.py::test_SEED_a_cold_seat_is_never_admitted_under_a_held_lease"),
 ("the budget is declared, not measured", "src/parcel_robot/vlm_veto/runner.py",
  "        admission = self._guard.try_admit_veto(estimated_ms=self.estimated_ms)",
  "        admission = self._guard.try_admit_veto(estimated_ms=self._seed_estimate_ms)",
  "tests/test_p1d_vlm_veto.py::test_the_admitted_estimate_is_measured_not_declared tests/test_p1d_vlm_veto.py::test_SEED_a_cold_seat_is_never_admitted_under_a_held_lease"),
 ("warm-up loads but never generates", "src/parcel_robot/vlm_veto/runner.py",
  "        crop = warm_up_png()", "        crop = warm_up_png()\n        return self._mark_warm()",
  "tests/test_p1d_vlm_veto.py::test_warming_up_costs_one_throwaway_answer_not_just_a_load"),
 ("unavailable borrows the ranking reason", "src/parcel_robot/perception_abstention.py",
  "                        ABSTAIN_VETO_UNAVAILABLE, passed, candidate=place",
  "                        ABSTAIN_INDECISIVE_RANKING, passed, candidate=place",
  "tests/test_p1d_vlm_veto.py::test_an_unavailable_veto_asks_and_never_admits_or_refuses_outright"),
 ("the pinned fixture may drift", "tests/data/p1d_crops/MANIFEST.json",
  '"pool_sha256": "77c86e15', '"pool_sha256": "deadbeef',
  "tests/test_p1d_eval_rows.py::test_the_pinned_fixture_matches_its_recorded_digests"),
 ("absent veto ignored", "src/parcel_robot/perception_abstention.py",
  "                if answer == VETO_ABSENT:", "                if False and answer == VETO_ABSENT:",
  "tests/test_p1d_vlm_veto.py::test_an_absent_veto_refuses_a_place_every_other_gate_admitted"),
 ("veto asked per candidate", "src/parcel_robot/perception_abstention.py",
  "    for place in ranked:\n        if SIGNAL_LABEL_SUPPORT in on and (",
  "    for place in ranked:\n        _veto_answer(veto, text, place)\n        if SIGNAL_LABEL_SUPPORT in on and (",
  "tests/test_p1d_vlm_veto.py::test_the_veto_is_asked_once_per_query_not_once_per_candidate"),
 ("control-loop tripwire removed", "src/parcel_robot/vlm_veto/runner.py",
  "        if in_control_thread():\n            self._decline", "        if False and in_control_thread():\n            self._decline",
  "tests/test_p1d_vlm_veto.py::test_a_veto_requested_on_the_control_thread_raises"),
 ("veto budget may be infinite", "src/parcel_robot/perception_contention.py",
  '        for name in ("max_generation_ms_while_active", "veto_budget_ms_while_active"):',
  '        for name in ("max_generation_ms_while_active",):',
  "tests/test_p1d_vlm_veto.py::test_the_veto_budget_cannot_be_made_infinite_or_exceed_the_ttl"),
 ("demotion is a no-op", "src/parcel_robot/online_map/naming.py",
  "    if demoted:\n        entry.names = tuple(rebuilt)", "    if False and demoted:\n        entry.names = tuple(rebuilt)",
  "tests/test_p1d_vlm_veto.py::test_a_promoted_name_that_is_contradicted_leaves_known_places"),
 ("non-names may be promoted", "src/parcel_robot/online_map/naming.py",
  "    if candidate in _NON_NAMES:\n        return \"\"", "    if False and candidate in _NON_NAMES:\n        return \"\"",
  "tests/test_p1d_vlm_veto.py::test_a_proposal_is_normalized_before_the_k_gate_compares_it"),
 ("vlm_veto joins DEFAULT_SIGNALS", "src/parcel_robot/perception_abstention.py",
  "    SIGNAL_RANKING_MARGIN,\n)\n\n#: Every signal name a config may write.",
  "    SIGNAL_RANKING_MARGIN,\n    SIGNAL_VLM_VETO,\n)\n\n#: Every signal name a config may write.",
  "tests/test_p1d_vlm_veto.py::test_the_shipped_gate_is_still_two_way_and_byte_identical"),
]

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main() -> None:
    results = []
    for name, rel, old, new, tests in SEEDS:
        path = REPO / rel
        before = path.read_text(); digest = sha(path)
        if before.count(old) != 1:
            results.append((name, "ANCHOR_ERROR", before.count(old))); continue
        try:
            path.write_text(before.replace(old, new))
            for cache in REPO.rglob("__pycache__"):
                shutil.rmtree(cache, ignore_errors=True)
            out = subprocess.run(
                [PY_, "-m", "pytest", "-q", "-p", "no:randomly", *tests.split()],
                cwd=REPO, capture_output=True, text=True, timeout=300, check=False)
            red = out.returncode != 0
            tail = [ln for ln in out.stdout.splitlines() if "passed" in ln or "failed" in ln or "error" in ln]
            results.append((name, "RED" if red else "**GREEN — NOT CAUGHT**", tail[-1] if tail else ""))
        finally:
            path.write_text(before)
            assert sha(path) == digest, f"restore failed for {rel}"
            for cache in REPO.rglob("__pycache__"):
                shutil.rmtree(cache, ignore_errors=True)
    width = max(len(r[0]) for r in results)
    caught = sum(r[1] == "RED" for r in results)
    for name, verdict, detail in results:
        print(f"{name:<{width}}  {verdict:<24} {detail}")
    print(f"\n{caught}/{len(results)} seeds caught")

if __name__ == "__main__":
    main()
