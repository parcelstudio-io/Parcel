#!/bin/bash
set -u
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
CACHE=/home/jaewoo-jang/.cache/parcel-finish1
F=tools/bargein_through_air.py
purge() { find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null; }
B=$(sha256sum $F|cut -d' ' -f1); cp $F $CACHE/bargein2.orig; echo "$F sha256 before: $B"

echo "=== SEED E2: CAPTURE_ONSET_KIND put back into ONSET_KINDS (the laundering path)"
.parcel/bin/python - <<'PY'
from pathlib import Path
p=Path("tools/bargein_through_air.py"); s=p.read_text(encoding="utf-8")
old='''ONSET_KINDS: frozenset[str] = frozenset(
    {"speech_started", "onset", "input_audio_buffer.speech_started"}
)'''
assert s.count(old)==1
p.write_text(s.replace(old,'''ONSET_KINDS: frozenset[str] = frozenset(
    {"speech_started", "onset", "input_audio_buffer.speech_started", CAPTURE_ONSET_KIND}
)  # SEED E2'''),encoding="utf-8")
PY
purge; .parcel/bin/python -m pytest -q tests/test_air1_scorecard.py 2>&1 | grep -E "^FAILED|passed|failed" | sed 's/ - .*//'
cp $CACHE/bargein2.orig $F

echo
echo "=== SEED E3: the onset_is_an_estimate clause deleted from verify_scorecard"
.parcel/bin/python - <<'PY'
from pathlib import Path
p=Path("tools/bargein_through_air.py"); s=p.read_text(encoding="utf-8")
start=s.index("    # ---- 7. an ESTIMATED onset may never become a pass. Correction pass 2.")
end=s.index("    return problems", start)
p.write_text(s[:start]+s[end:],encoding="utf-8")
PY
purge; .parcel/bin/python -m pytest -q tests/test_air1_scorecard.py 2>&1 | grep -E "^FAILED|passed|failed" | sed 's/ - .*//'
cp $CACHE/bargein2.orig $F
A=$(sha256sum $F|cut -d' ' -f1)
[ "$B" = "$A" ] && echo "RESTORE OK (byte-identical) $A" || echo "RESTORE MISMATCH"
purge
echo "--- RESTORED ---"
.parcel/bin/python -m pytest -q tests/test_air1_scorecard.py 2>&1 | tail -1
