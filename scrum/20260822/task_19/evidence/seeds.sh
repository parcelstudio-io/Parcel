#!/usr/bin/env bash
# DOOR-1 seeded-RED proofs. Every seed is applied to a byte-identical scratch
# copy of src/ (the repo's own src/ is never edited), the named test is watched
# to redden, the file is restored from the pristine copy and re-verified by
# sha256, __pycache__ is purged, and the test is re-run green.
set -u
REPO=/home/jaewoo-jang/Desktop/Projects/Parcel
CACHE=/home/jaewoo-jang/.cache/parcel-door1
SCRATCH=$CACHE/seedsrc
PY=$REPO/.parcel/bin/python
unset TMPDIR

rm -rf "$SCRATCH"
mkdir -p "$SCRATCH"
cp -a "$REPO/src" "$SCRATCH/src"
cp -a "$REPO/src" "$SCRATCH/pristine"
find "$SCRATCH" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null

echo "=== byte-identity of the scratch copy against the repo ==="
diff -r "$REPO/src" "$SCRATCH/pristine" >/dev/null && echo "scratch == repo src: OK"

run() {  # run <test-node-ids...>
  ( cd "$REPO" && PYTHONPATH="$SCRATCH/src" "$PY" -m pytest -q -p no:randomly "$@" 2>&1 | tail -3 )
}

seed() {  # seed <label> <relpath> <python-patch-heredoc-file> <test-node-ids...>
  local label=$1 rel=$2 patch=$3; shift 3
  echo
  echo "################ SEED $label — $rel"
  "$PY" - "$SCRATCH/src/$rel" < "$patch"
  echo "--- with the seed applied (expect RED):"
  run "$@"
  cp -a "$SCRATCH/pristine/$rel" "$SCRATCH/src/$rel"
  find "$SCRATCH" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
  local a b
  a=$(sha256sum "$SCRATCH/src/$rel" | cut -d' ' -f1)
  b=$(sha256sum "$REPO/src/$rel" | cut -d' ' -f1)
  echo "--- restored sha256 $a ; repo sha256 $b ; match=$([ "$a" = "$b" ] && echo YES || echo NO)"
  echo "--- after restore (expect GREEN):"
  run "$@"
}

cat > "$CACHE/s1.py" <<'PATCH'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
old = """        if self.obstacle_stop_floor_m + 1e-12 < OBSTACLE_STOP_FLOOR_M:"""
new = """        if False:"""
assert s.count(old) == 1, "S1 anchor not unique"
p.write_text(s.replace(old, new)); print("S1: obstacle floor check disabled")
PATCH

cat > "$CACHE/s2.py" <<'PATCH'
import pathlib, re, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
old = """                gate_clearance_m=(
                    DEFAULT_CLEARANCE_PROFILE.obstacle_ring_m
                    if map_gate_clearance_m is None
                    else float(map_gate_clearance_m)
                ),"""
new = """                gate_clearance_m=None,"""
assert s.count(old) == 1, "S2 anchor not unique"
p.write_text(s.replace(old, new)); print("S2: production site 1 back to gate_clearance_m=None")
PATCH

cat > "$CACHE/s3.py" <<'PATCH'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
old = """        return max(
            self.robot_radius_m + self.effective_hard_margin_m,
            self.gate_lateral_clearance_m,
        )"""
new = """        return self.robot_radius_m + self.effective_hard_margin_m"""
assert s.count(old) == 1, "S3 anchor not unique"
p.write_text(s.replace(old, new)); print("S3: planner inflation no longer covers the gate")
PATCH

cat > "$CACHE/s4.py" <<'PATCH'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
old = """    desired_distance_m: float | None = None"""
new = """    desired_distance_m: float | None = 1.85"""
assert s.count(old) == 1, "S4 anchor not unique"
p.write_text(s.replace(old, new)); print("S4: follow stand-off silently constant again")
PATCH

seed S1 parcel_robot/authority.py "$CACHE/s1.py" \
  tests/test_door1_doorway.py::test_an_under_floor_obstacle_ring_refuses_and_names_the_floor \
  tests/test_door1_doorway.py::test_every_envelope_construction_path_lands_on_the_obstacle_floor

seed S2 parcel_robot/navigation/grid_navigator.py "$CACHE/s2.py" \
  tests/test_door1_doorway.py::test_every_production_planner_site_passes_gate_clearance \
  tests/test_door1_doorway.py::test_the_grid_navigator_planner_is_never_built_with_none

seed S3 parcel_robot/navigation/grid_planner.py "$CACHE/s3.py" \
  tests/test_door1_doorway.py::test_a_planner_that_relaxes_the_final_gate_refuses_to_construct

seed S4 parcel_robot/navigation/follow.py "$CACHE/s4.py" \
  tests/test_door1_doorway.py::test_the_follow_stand_off_derives_from_the_instance_not_the_import \
  tests/test_door1_doorway.py::test_no_module_level_stand_off_constant_survives_in_follow

cat > "$CACHE/s5.py" <<'PATCH'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
old = """                        gate_clearance_m=self._safety_policy.clearance_profile.obstacle_ring_m,
"""
new = ""
assert s.count(old) == 1, "S5 anchor not unique"
p.write_text(s.replace(old, new)); print("S5: production site 2 no longer passes the ring")
PATCH

seed S5 parcel_robot/navigation/search_owner.py "$CACHE/s5.py" \
  tests/test_door1_doorway.py::test_every_production_planner_site_passes_gate_clearance \
  tests/test_door1_doorway.py::test_the_owner_search_planner_takes_the_runtimes_own_commissioned_ring

cat > "$CACHE/s6.py" <<'PATCH'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
old = """                        gate_clearance_m=(
                            self._safety_policy.clearance_profile.planner_coupling_ring_m
                        ),"""
new = """                        gate_clearance_m=self._safety_policy.clearance_profile.obstacle_ring_m,"""
assert s.count(old) == 1, "S6 anchor not unique"
p.write_text(s.replace(old, new)); print("S6: site 2 back to the RAW commissioned ring")
PATCH

cat > "$CACHE/s7.py" <<'PATCH'
import pathlib, sys
p = pathlib.Path(sys.argv[1]); s = p.read_text()
old = """    return ClearanceProfile(
        obstacle_ring_m=ring, planner_hard_margin_m=float(hard_margin_m)
    ).planner_coupling_ring_m"""
new = """    return ring"""
assert s.count(old) == 1, "S7 anchor not unique"
p.write_text(s.replace(old, new)); print("S7: site 1 cap removed (flat, un-scoped ring)")
PATCH

seed S6 parcel_robot/navigation/search_owner.py "$CACHE/s6.py" \
  tests/test_door1_doorway.py::test_the_owner_search_planner_keeps_its_legacy_inflation_when_shipped \
  tests/test_door1_doorway.py::test_the_coupling_is_tighter_only_and_says_when_it_is_deferred

seed S7 parcel_robot/navigation/grid_navigator.py "$CACHE/s7.py" \
  tests/test_door1_doorway.py::test_every_grid_model_profile_keeps_its_legacy_inflation

echo
echo "=== final byte-identity check of the whole scratch tree ==="
diff -r "$REPO/src" "$SCRATCH/src" >/dev/null && echo "scratch src restored == repo src: OK" || echo "MISMATCH"
