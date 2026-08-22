#!/bin/bash
set -u
cd /home/jaewoo-jang/Desktop/Projects/Parcel
unset TMPDIR
for i in 1 2 3; do
  echo "=== tethered run $i ==="
  .parcel/bin/python scrum/20260822/task_23/evidence/run_roam1.py \
      --budget 120 --static-city --person-stop 0.7 \
      --socket-dir /home/jaewoo-jang/.cache/parcel-finish1 \
      --out scrum/20260822/task_23/evidence/roam_static_tethered_$i \
      2>&1 | tail -40
  echo "=== run $i exit ${PIPESTATUS[0]} ==="
done
echo ALLDONE
