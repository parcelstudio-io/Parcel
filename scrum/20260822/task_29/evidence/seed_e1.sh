#!/bin/bash
set -u
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
F=tools/bargein_through_air.py
BEFORE=$(sha256sum $F | cut -d' ' -f1)
cp $F /home/jaewoo-jang/.cache/parcel-finish1/bargein.py.orig
echo "sha256 before: $BEFORE"
.parcel/bin/python - <<'PY'
from pathlib import Path
p=Path("tools/bargein_through_air.py")
s=p.read_text(encoding="utf-8")
old = '        when = _parse_iso(segment.get("interrupted_at"))'
assert s.count(old)==1
s=s.replace(old,'        when = None  # SEED E1: the tee\'s own interrupt stamp goes unread')
p.write_text(s,encoding="utf-8")
PY
find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null
echo "--- SEEDED run ---"
.parcel/bin/python -m pytest -q tests/test_air1_scorecard.py 2>&1 | tail -6
cp /home/jaewoo-jang/.cache/parcel-finish1/bargein.py.orig $F
AFTER=$(sha256sum $F | cut -d' ' -f1)
[ "$BEFORE" = "$AFTER" ] && echo "RESTORE OK (byte-identical) $AFTER" || echo "RESTORE MISMATCH"
find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null
echo "--- RESTORED run ---"
.parcel/bin/python -m pytest -q tests/test_air1_scorecard.py 2>&1 | tail -2
