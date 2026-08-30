# AUDIT · W3 WORLD-IDENTITY-1 — verifier: Fable (parcel-0e), 08:4x 08-30

**Disposition: ACCEPT.** Worktree `~/.cache/parcel-0e/wb/w3` at `c96ac34` (`parcel_robot.__file__` from the worktree); 16 files, +467/−75; new leaf `navigation/world_identity.py` (156 lines, 0 `noqa`).

| row | executor | verifier |
|---|---|---|
| NAV-GEN-1 A0 rows byte-identical on every pre-existing column; `identity_source=explicit` 530/530; crosswalk_a 0/90; frozen 16/16 `known_poi` | as claimed | accepted from the register (re-run on the final tree by the executor); the 205-row drift vs C1's *published* F1 rows is the same 205 rows in `C1-F1 vs HEAD` and `C1-F1 vs HEAD+W3` — W3 adds zero; the drift is C1-F1.2 having been measured in the dirty root (`grid_planner.py` +235 / `pipeline.py` +470 on the drive path) — priced by whoever re-freezes NAV-GEN-1 |
| minival digest `021b67ab…`; panel {4, 1} | matched | accepted |
| tests | 25/54/38/19/61 | **guarded re-run in the worktree: 197 passed** (`test_poi_admission` + `test_c3_cutover` + `test_navigation` + `test_person_aware_nav` + `test_runtime`) |
| hunk adjacency | `runtime.py` `@@ -13358` / `@@ -13380` adjacent to `_attach_configured_camera_ingress`; `pipeline.py` 107/530/866/1093/1151/1172; `headless_city.py` 46/162/221/732/1079/1100 — no overlap with the root's foreign hunks | runtime hunks confirmed by `git diff`; far from W1/W2's regions |
| `pipeline.py` / `config.py` | 7211 unchanged / 1000 | **7211 / 1000** |
| ruff / noqa | clean / 0 | **All checks passed / 0** |
| `sim.py:204`, `web_panel.py:202` unchanged with reason | neither builds a navigator; the panel's explicit hand-off is at `RuntimeHTTPServer.__init__` | accepted |
| the sweep's one red | `test_person_cell::…undeclared_bystander` (`veto_fraction 0.875`) reproduces in a pure-HEAD export | pre-existing (also seen at C2 close) |

**Merge note for the owner (semantic, not a line overlap):** the dirty root wraps `pipeline.py:28`'s `from .poi_admission import …` in a BARN-bundle `try/except` whose fallback shims have the pre-W3 signatures; W3 adds no import there but `parse`'s two call sites now pass a third argument and unpack `(goal, metadata)`. When the owner's diff meets HEAD+W3, those shims need the same parameter and pair (three lines). Not in wave B's index.
