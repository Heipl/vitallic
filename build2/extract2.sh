#!/bin/bash
cd /home/rjoliver/vitalik || exit 1
B=origin/cursor/robot-clearance-priority-473a
R=/mnt/c/Users/rinoa/landmine-bayes

git show "$B:mineprior/tasking.py"       > "$R/mineprior/tasking.py"
git show "$B:mineprior/test_tasking.py"  > "$R/mineprior/test_tasking.py"
git show "$B:build2/build_tasking.py"    > "$R/build/build_tasking.py"
git show "$B:build2/fetch_tasking.py"    > "$R/build/fetch_tasking.py"
git show "$B:data/out/tasking.json"      > "$R/data/out/tasking.json"
git show "$B:data/out/tasking_grid.npz"  > "$R/data/out/tasking_grid.npz"
git show "$B:dist/robot/tasking_priority.json" > "$R/dist/robot/tasking_priority.json"
git show "$B:build2/design/spec_clearance-priority.md" > "$R/build/design/spec_clearance-priority.md"

for f in "$R/mineprior/tasking.py" "$R/mineprior/test_tasking.py" \
         "$R/build/build_tasking.py" "$R/data/out/tasking.json" \
         "$R/data/out/tasking_grid.npz" "$R/dist/robot/tasking_priority.json"; do
  echo "$(wc -c < "$f") bytes  $f"
done
