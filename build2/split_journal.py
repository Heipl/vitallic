import json
from pathlib import Path

src = r"C:\Users\rinoa\.claude\projects\c--Users-rinoa\cdbe3cc9-ee66-4c79-a765-8d489a4e0a51\subagents\workflows\wf_81a2ff56-3b8\journal.jsonl"
out = Path(r"C:\Users\rinoa\landmine-bayes\build\design")
out.mkdir(exist_ok=True)

labels = {}
for line in open(src, encoding="utf-8"):
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("type") == "started":
        labels[r["agentId"]] = r["label"]

n = 0
for line in open(src, encoding="utf-8"):
    try:
        r = json.loads(line)
    except Exception:
        continue
    if r.get("type") != "result":
        continue
    res = r.get("result") or {}
    key = res.get("key") or labels.get(r.get("agentId"), r.get("agentId"))
    key = str(key).replace(":", "_").replace("/", "_")
    txt = []
    txt.append("## SUMMARY\n" + str(res.get("summary", "")))
    txt.append("\n## FINDINGS")
    for f in res.get("findings", []):
        txt.append(f"\n### [{f.get('confidence')}] {f.get('topic')}\n{f.get('detail')}\n_source: {f.get('source')}_")
    txt.append("\n## RECOMMENDATIONS")
    for x in res.get("recommendations", []):
        txt.append("- " + str(x))
    txt.append("\n## PITFALLS")
    for x in res.get("pitfalls", []):
        txt.append("- " + str(x))
    body = "\n".join(txt)
    (out / f"{key}.md").write_text(body, encoding="utf-8")
    print(f"{key:28} {len(body):8,} chars")
    n += 1
print("wrote", n)
