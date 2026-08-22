#!/bin/bash
set -u
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
F=src/parcel_robot/patrol/mission.py
BEFORE=$(sha256sum $F | cut -d' ' -f1)
cp $F /home/jaewoo-jang/.cache/parcel-finish1/mission.py.orig
echo "sha256 before: $BEFORE"
.parcel/bin/python - <<'PY'
from pathlib import Path
p=Path("src/parcel_robot/patrol/mission.py")
s=p.read_text(encoding="utf-8")
old="        tether_m=tether_m,\n    )"
assert s.count(old)==1
s=s.replace(old,"        tether_m=None,  # SEED S9a\n    )")
p.write_text(s,encoding="utf-8")
PY
find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null
echo "--- SEEDED run ---"
.parcel/bin/python -m pytest -q tests/test_roam1_behavior.py 2>&1 | tail -5
cp /home/jaewoo-jang/.cache/parcel-finish1/mission.py.orig $F
AFTER=$(sha256sum $F | cut -d' ' -f1)
[ "$BEFORE" = "$AFTER" ] && echo "RESTORE OK (byte-identical) $AFTER" || echo "RESTORE MISMATCH"
find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null
.parcel/bin/python -m pytest -q tests/test_roam1_behavior.py 2>&1 | tail -2
