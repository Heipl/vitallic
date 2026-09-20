import re
import sys

from pypdf import PdfReader

src = r"C:\Users\rinoa\.claude\projects\c--Users-rinoa\cdbe3cc9-ee66-4c79-a765-8d489a4e0a51\tool-results\webfetch-1789865406872-6d0bkq.pdf"
r = PdfReader(src)
full = "\n".join(f"\n===PAGE {i+1}===\n" + (p.extract_text() or "") for i, p in enumerate(r.pages))
open(r"C:\Users\rinoa\landmine-bayes\data\ged251_codebook.txt", "w", encoding="utf-8").write(full)
print("pages:", len(r.pages), "chars:", len(full))

term = sys.argv[1] if len(sys.argv) > 1 else "where_prec"
for m in re.finditer(term, full):
    a, b = max(0, m.start() - 200), min(len(full), m.start() + 2600)
    print("\n-------- match --------")
    print(full[a:b])
    break
