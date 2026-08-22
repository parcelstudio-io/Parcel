#!/bin/bash
set -u
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
CACHE=/home/jaewoo-jang/.cache/parcel-finish1
purge() { find . -name __pycache__ -type d -not -path "./.parcel/*" -exec rm -rf {} + 2>/dev/null; }

echo "=== SEED E (post-integration): one vendored OBJ deleted"
F=third_party/unitree_mujoco/unitree_robots/go2/assets/foot.obj
B=$(sha256sum $F | cut -d' ' -f1); echo "foot.obj sha256 $B"
cp $F $CACHE/foot.obj.orig
rm $F
purge
.parcel/bin/python -m pytest -q tests/test_unitree_asset_pack.py tests/test_sim.py 2>&1 | tail -3
cp $CACHE/foot.obj.orig $F
A=$(sha256sum $F | cut -d' ' -f1)
[ "$B" = "$A" ] && echo "RESTORE OK (byte-identical)" || echo "RESTORE MISMATCH"
purge
.parcel/bin/python -m pytest -q tests/test_unitree_asset_pack.py tests/test_sim.py 2>&1 | tail -2

echo
echo "=== SEED F (post-integration): the blanket third_party/ ignore restored"
G=.gitignore
B2=$(sha256sum $G | cut -d' ' -f1); echo ".gitignore sha256 $B2"
cp $G $CACHE/gitignore.orig
.parcel/bin/python - <<'PY'
from pathlib import Path
p=Path(".gitignore"); s=p.read_text(encoding="utf-8")
old="third_party/*\n!third_party/unitree_mujoco/\n"
assert s.count(old)==1
p.write_text(s.replace(old,"third_party/\n"),encoding="utf-8")
PY
purge
.parcel/bin/python -m pytest -q tests/test_unitree_asset_pack.py -k "carve or ship" 2>&1 | tail -4
cp $CACHE/gitignore.orig $G
A2=$(sha256sum $G | cut -d' ' -f1)
[ "$B2" = "$A2" ] && echo "RESTORE OK (byte-identical)" || echo "RESTORE MISMATCH"
purge
.parcel/bin/python -m pytest -q tests/test_unitree_asset_pack.py -k "carve or ship" 2>&1 | tail -2
