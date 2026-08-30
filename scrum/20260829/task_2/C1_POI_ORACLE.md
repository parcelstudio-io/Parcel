# C1 · POI-ORACLE-1 — the demo POI table must never answer a scene-relative place name on a scene that does not contain it

**Executor:** Opus · **Verifier:** Fable · **Second lens:** parcel-fb · **Wave:** A

## Defect (measured, NAV-GEN-1, verified by parcel-fb and an adversarial panel)

`DirectiveNavigator.parse` (`src/parcel_robot/navigation/pipeline.py:1136-1150`) consults `PlaceGrounder.ground` BEFORE semantic search; `PlaceGrounder` (`navigation/grounder.py:11-30`) maps any directive containing one of `configs/navigation/cities/demo_pois.yaml`'s four class names ("coffee shop", "bookstore", "park", "crosswalk") to a hardcoded coordinate (`crosswalk_a` at `[3.5, -0.6]`, `demo_pois.yaml:38-46`) tagged `goal_source: known_poi`. The table is armed whenever `semantic_source == oracle` (`navigation/selection.py:182-192`), which is the shipped default (`configs/navigation/default.yaml:99`; `admission.py:917` calls it "the shipped oracle default"). On 30 procedurally generated scenes, **90/90** "go to the crosswalk" episodes ground to `crosswalk_a`; **42 are false arrivals** (`status = arrived`, body a median 3.2 m — worst 7.2 m — from any crosswalk; the POI path also carries the looser 1.5 m point-goal arrive radius), 42 stall en route to the wrong point, 6 "succeed" by accident. Evidence: `research/20260829/nav-gen-attribution-1/{VERDICT.md §1.1, §5.2; RESULTS.md §5.3}`; raw rows `~/.cache/parcel-0e/ng1/raw/rows_A0.json`.

## Build

Make the POI arm scene-aware without moving frozen evidence:
1. A POI candidate is admissible only if the loaded scene declares it — i.e. the scene's semantic instance set (the same source `HeadlessCityWorld` / the learned map expose as `legal_instance_ids`) contains an instance of that class whose geometry contains or abuts the POI coordinate (within the class's arrival band). Otherwise the grounder raises `LookupError` and the semantic ladder runs. Implement as a **leaf module** (`navigation/poi_admission.py`) called from `parse` with one line; `pipeline.py` net line count must not grow.
2. Carry the reason: `metadata['goal_source']` stays `known_poi` when admitted; when refused, `metadata['poi_refused'] = <reason>` so a harness can tell "no POI" from "POI refused".
3. (Moved to C2, which owns `headless_city.py`: logging `goal_source` in `HeadlessTaskResult`.) C1 does NOT edit `simulation/headless_city.py`; use `target_id` (already logged) for the acceptance rows.
4. Do not remove the POI table from the demo block: the frozen NAV_INSTRUCT episodes on the demo scene must keep their digests (E3). Do not touch `semantic_source`.

## Acceptance (verbatim bars)

- RED first: `env -u TMPDIR OPENBLAS_NUM_THREADS=32 .parcel/bin/python research/20260829/nav-gen-attribution-1/run.py --arms A0 --seed 20260829 --workers 16` (set `NG1_SCRATCH` to your own scratch) reproduces crosswalk `false_arrival` 42/90 and `target_id == 'crosswalk_a'` 90/90 before the fix.
- GREEN: same command after the fix — `target_id == 'crosswalk_a'` **0/90** on generated scenes, crosswalk false arrivals **0/90**, crosswalk strict success **≥ 0.60** (the four non-POI targets run 0.70–0.93), **0 collisions**, all other targets' rows **byte-identical** to the RED run (the fix must not touch them).
- Frozen block: NAV-GEN-1's 80-episode control (`--arms A0` includes it) — crosswalk on the demo block still grounds via `known_poi` (16/16) because the scene contains it; every other frozen row byte-identical.
- E3: `.parcel/bin/python scripts/ci_gate.py --tier commit` is the integrator's; the executor runs only `~/.cache/parcel-guard/pytest_guard.sh --label C1 .parcel/bin/python -m pytest tests/test_a2_navglue.py tests/test_k0_arrival_authority.py tests/test_voice_nav_e2e.py -k "crosswalk or poi or ground" -q` and the frozen-digest check `tests/test_mutation_panel_freshness.py` (expected: the pre-existing D-15 red is C0's, everything else green).
- New unit tests (table-driven): POI admitted on the demo scene; refused on a generated scene with no crosswalk near the coordinate; admitted on a generated scene whose crosswalk polygon contains the coordinate (seed 880027 is such a scene); `poi_refused` reason carried; `goal_source` logged.
- No `noqa`; `config.py` unchanged; `pipeline.py` line count not greater than before (report before/after).

## Does not prove
Off-oracle grounding (learned map / camera), physical arrival, or anything about the other three POI classes beyond the same admission rule.
