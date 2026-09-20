import json
import sys

p = r"C:\Users\rinoa\.claude\projects\c--Users-rinoa\cdbe3cc9-ee66-4c79-a765-8d489a4e0a51\subagents\workflows\wf_81a2ff56-3b8\journal.jsonl"
want = sys.argv[1] if len(sys.argv) > 1 else None

done = []
for line in open(p, encoding="utf-8"):
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("type") in ("finished", "completed", "result", "agent_result"):
        done.append(r)

print("completed entries:", len(done))
for d in done:
    lbl = d.get("label") or d.get("agentId")
    print("  -", lbl, "| keys:", list(d.keys()))

if want:
    for d in done:
        if want in str(d.get("label", "")):
            print(json.dumps(d.get("result", d), indent=1, ensure_ascii=False)[:60000])
