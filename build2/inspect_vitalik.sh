#!/bin/bash
cd /home/rjoliver/vitalik || exit 1
for b in main master cursor/robot-clearance-priority-473a cursor/robot-acre-bfs-map-fed3; do
  echo "=== origin/$b ==="
  git log --oneline -1 "origin/$b" 2>/dev/null
  git ls-tree -r --name-only "origin/$b" 2>/dev/null | head -50
  echo
done
