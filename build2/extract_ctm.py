"""Pull the per-state contamination figures out of Mine Action Review's
'Clearing the Mines 2025'. Each country profile opens with a KEY DATA block
whose first line states the contaminated area in km2."""
import logging
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.getLogger("pypdf").setLevel(logging.ERROR)

from pypdf import PdfReader

src = Path(r"C:\Users\rinoa\landmine-bayes\data\ctm2025.pdf")
txt_path = Path(r"C:\Users\rinoa\landmine-bayes\data\ctm2025.txt")

if not txt_path.exists():
    r = PdfReader(str(src))
    pages = [f"\n===PAGE {i+1}===\n" + (p.extract_text() or "")
             for i, p in enumerate(r.pages)]
    txt_path.write_text("".join(pages), encoding="utf-8")
    print("pages:", len(r.pages), file=sys.stderr)

full = txt_path.read_text(encoding="utf-8")
print("chars:", len(full))

term = sys.argv[1] if len(sys.argv) > 1 else "KEY DATA"
hits = list(re.finditer(term, full, re.I))
print(f"matches for {term!r}: {len(hits)}")
for m in hits[:2]:
    a, b = max(0, m.start() - 300), min(len(full), m.start() + 1500)
    print("\n------------------------")
    print(full[a:b])
