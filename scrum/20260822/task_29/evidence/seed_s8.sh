#!/bin/bash
set -u
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
CACHE=/home/jaewoo-jang/.cache/parcel-finish1
F=src/parcel_robot/config.py
B=$(sha256sum $F|cut -d' ' -f1); cp $F $CACHE/config.py.orig; echo "config.py sha256 before: $B"
.parcel/bin/python - <<'PY'
from pathlib import Path
p=Path("src/parcel_robot/config.py"); s=p.read_text(encoding="utf-8")
old='        "roam",\n'
assert s.count(old)==1
p.write_text(s.replace(old,'        # "roam",  # SEED S8\n'),encoding="utf-8")
PY
find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null
echo "--- SEEDED ---"
.parcel/bin/python -m pytest -q tests/test_roam1_behavior.py 2>&1 | grep -E "^FAILED|passed|failed" | sed 's/ - .*//'
cp $CACHE/config.py.orig $F; A=$(sha256sum $F|cut -d' ' -f1)
[ "$B" = "$A" ] && echo "RESTORE OK (byte-identical)" || echo "RESTORE MISMATCH"
find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null
echo "--- RESTORED ---"
.parcel/bin/python -m pytest -q tests/test_roam1_behavior.py 2>&1 | tail -1
