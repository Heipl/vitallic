#!/bin/bash
# Pull the files we need out of the un-checked-out clone, without touching it.
cd /home/rjoliver/vitalik || exit 1
OUT=/mnt/c/Users/rinoa/landmine-bayes/vitalik
mkdir -p "$OUT/priority" "$OUT/main"

B=origin/cursor/robot-clearance-priority-473a
for f in build2/design/spec_clearance-priority.md build2/build_tasking.py \
         build2/fetch_tasking.py data/out/tasking.json; do
  git show "$B:$f" > "$OUT/priority/$(basename $f)" 2>/dev/null \
    && echo "priority/$(basename $f) $(wc -c < "$OUT/priority/$(basename $f)") bytes"
done

for f in robot.py field_scan.py bayes.py geo.py flagged_spots.json sim.py \
         DIMOS_PORT.md TOMORROW.md README.md \
         dimos_vitallic/vitallic_dimos/blueprint.py \
         dimos_vitallic/vitallic_dimos/precise_move.py; do
  git show "origin/main:$f" > "$OUT/main/$(basename $f)" 2>/dev/null \
    && echo "main/$(basename $f) $(wc -c < "$OUT/main/$(basename $f)") bytes"
done
