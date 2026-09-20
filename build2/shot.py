"""Write a throwaway copy of the built page with the acknowledgement modal
pre-dismissed, so a headless screenshot shows the map rather than the modal."""
import subprocess
import sys
import time
from pathlib import Path

D = Path(r"C:\Users\rinoa\landmine-bayes\dist")
src = (D / "landmine-bayes.html").read_text(encoding="utf-8")
patched = src.replace('if (!acked) $("#scrim").hidden = false;',
                      'if (false) $("#scrim").hidden = false;')
assert patched != src, "modal guard not found -- template changed?"

extra = sys.argv[1] if len(sys.argv) > 1 else ""
if extra:
    patched = patched.replace("renderDetail();\n</script>",
                              f"renderDetail();\n{extra}\n</script>")

tmp = D / "_preview.html"
tmp.write_text(patched, encoding="utf-8")

shot = D / "shot.png"
if shot.exists():
    shot.unlink()
subprocess.run([
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "--headless=new", "--disable-gpu", "--hide-scrollbars",
    "--window-size=1500,950", f"--screenshot={shot}",
    "--virtual-time-budget=9000", tmp.as_uri(),
], capture_output=True, timeout=180)
time.sleep(2)
print(f"{shot.stat().st_size:,} bytes" if shot.exists() else "no screenshot")
