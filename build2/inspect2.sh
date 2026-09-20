#!/bin/bash
cd /home/rjoliver/vitalik || exit 1
B=origin/cursor/robot-clearance-priority-473a
echo "=== full file list ==="
git ls-tree -r --name-only "$B" | grep -v '^data/' | grep -v '__pycache__'
echo
echo "=== tasking.json shape ==="
git show "$B:data/out/tasking.json" | head -c 2600
