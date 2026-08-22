#!/bin/bash
set -u
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
CACHE=/home/jaewoo-jang/.cache/parcel-finish1
F=tools/bargein_through_air.py
purge() { find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null; }
B=$(sha256sum $F|cut -d' ' -f1); cp $F $CACHE/bargein3.orig; echo "$F sha256 before: $B"

echo "=== SEED CP3a: the missing-evidence clauses removed (back to 'only fires when present')"
.parcel/bin/python - <<'PY'
from pathlib import Path
p=Path("tools/bargein_through_air.py"); s=p.read_text(encoding="utf-8")
start=s.index('        if latency is None:\n            problems.append(\n                f"interrupt_p50_s: verdict {verdict!r} but the card carries no "')
end=s.index('        flag = latency.get("onset_is_an_estimate")')
s=s[:start]+'        if latency is None:\n            continue  # SEED CP3a\n'+s[end:]
old='''        if not isinstance(flag, bool):
            problems.append(
                f"interrupt_p50_s: verdict {verdict!r} but sources.latency."
                f"onset_is_an_estimate is {flag!r}, not a bool — a scored latency must "
                "state, explicitly and in the card, whether its onset was estimated"
            )
        elif flag and verdict == "pass":'''
assert s.count(old)==1
s=s.replace(old,'''        if False:  # SEED CP3a
            pass
        elif flag and verdict == "pass":''')
p.write_text(s,encoding="utf-8")
PY
purge; .parcel/bin/python -m pytest -q tests/test_air1_scorecard.py 2>&1 | grep -E "^FAILED|passed|failed" | sed 's/ - .*//'
cp $CACHE/bargein3.orig $F

echo
echo "=== SEED CP3b: the kinds cross-check removed (a flipped flag launders the median)"
.parcel/bin/python - <<'PY'
from pathlib import Path
p=Path("tools/bargein_through_air.py"); s=p.read_text(encoding="utf-8")
start=s.index('        elif not flag:')
end=s.index('    return problems', start)
p.write_text(s[:start]+s[end:],encoding="utf-8")
PY
purge; .parcel/bin/python -m pytest -q tests/test_air1_scorecard.py 2>&1 | grep -E "^FAILED|passed|failed" | sed 's/ - .*//'
cp $CACHE/bargein3.orig $F
A=$(sha256sum $F|cut -d' ' -f1)
[ "$B" = "$A" ] && echo "RESTORE OK (byte-identical) $A" || echo "RESTORE MISMATCH"
purge
echo "--- RESTORED ---"
.parcel/bin/python -m pytest -q tests/test_air1_scorecard.py 2>&1 | tail -1
