#!/bin/bash
set -u
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
CACHE=/home/jaewoo-jang/.cache/parcel-finish1
purge() { find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null; }

seed_run() {  # $1 file  $2 python-seed-heredoc-file  $3 pytest args  $4 label
  local F="$1" SEEDPY="$2" PYTEST="$3" LABEL="$4"
  local BEFORE AFTER
  BEFORE=$(sha256sum "$F" | cut -d' ' -f1)
  cp "$F" "$CACHE/$(basename $F).orig"
  echo "=== $LABEL   ($F sha256 $BEFORE)"
  .parcel/bin/python "$SEEDPY"
  purge
  echo "--- SEEDED ---"
  .parcel/bin/python -m pytest -q $PYTEST 2>&1 | tail -4
  cp "$CACHE/$(basename $F).orig" "$F"
  AFTER=$(sha256sum "$F" | cut -d' ' -f1)
  [ "$BEFORE" = "$AFTER" ] && echo "RESTORE OK (byte-identical)" || echo "RESTORE MISMATCH"
  purge
  echo "--- RESTORED ---"
  .parcel/bin/python -m pytest -q $PYTEST 2>&1 | tail -2
  echo
}

cat > $CACHE/g1.py <<'PY'
from pathlib import Path
p=Path("scripts/ci_gate.py"); s=p.read_text(encoding="utf-8")
old="        extra = sorted(shipped - expected)"
assert s.count(old)==1
p.write_text(s.replace(old,"        extra = []  # SEED G1: the closure stops reporting extras"),encoding="utf-8")
PY
seed_run scripts/ci_gate.py $CACHE/g1.py "tests/test_unitree_asset_pack.py" "G1 closure stops reporting unmanifested files"

cat > $CACHE/g6.py <<'PY'
from pathlib import Path
import re
p=Path("tests/test_held_out_scene.py"); s=p.read_text(encoding="utf-8")
start=s.index('    "CODEBASE_INDEX.md": (')
end=s.index('    "scrum/20260821/task_20/MOVE1_STATUS.md": (')
p.write_text(s[:start]+s[end:],encoding="utf-8")
PY
seed_run tests/test_held_out_scene.py $CACHE/g6.py "tests/test_held_out_scene.py" "G6 the CODEBASE_INDEX.md seat removed"

cat > $CACHE/g7.py <<'PY'
from pathlib import Path
p=Path("scripts/ci_gate.py"); s=p.read_text(encoding="utf-8")
old='        ("hard-safety", lambda: evaluate_hard_safety(tier=tier)),'
if s.count(old)!=1:
    import re
    m=[l for l in s.splitlines() if "hard-safety" in l and "lambda" in l]
    raise SystemExit("anchor not found: %r" % m)
p.write_text(s.replace(old,'        ("hard-safety", lambda: evaluate_ruff(tier=tier)),  # SEED G7'),encoding="utf-8")
PY
seed_run scripts/ci_gate.py $CACHE/g7.py "tests/test_ci_gate.py -k exploding" "G7 two stages backed by one evaluator"
