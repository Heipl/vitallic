"""Write a throwaway copy of the built page with the acknowledgement modal
pre-dismissed, so a headless screenshot shows the map rather than the modal.

    python build2/shot.py [extra-js] [out.png]

`extra-js` is injected after boot, which is how a screenshot can show a state
that needs interaction to reach, e.g.:

    python build2/shot.py 'setMode("tasking");selectRegion("adm2","Bakhmutskyi")'
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

D = Path(__file__).resolve().parents[1] / "dist"

BROWSERS = [
    os.environ.get("CHROME"),
    "google-chrome", "chromium", "chromium-browser", "msedge",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser():
    for b in BROWSERS:
        if not b:
            continue
        p = shutil.which(b) or (b if Path(b).exists() else None)
        if p:
            return p
    raise SystemExit("no Chromium-family browser found; set CHROME=/path/to/chrome")


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

shot = D / (sys.argv[2] if len(sys.argv) > 2 else "shot.png")
if shot.exists():
    shot.unlink()
proc = subprocess.run([
    find_browser(),
    "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-sandbox",
    # Containers rarely have a usable /dev/shm or a writable default profile
    # directory, and Chrome hangs rather than failing when either is missing.
    "--disable-dev-shm-usage", f"--user-data-dir={Path(os.environ.get('TMPDIR', '/tmp')) / 'mp-shot-profile'}",
    "--window-size=1500,950", f"--screenshot={shot}",
    "--virtual-time-budget=9000", tmp.as_uri(),
], capture_output=True, timeout=300)
if not shot.exists():
    sys.stderr.write(proc.stderr.decode("utf-8", "replace")[-2000:])
print(f"{shot} {shot.stat().st_size:,} bytes" if shot.exists() else "no screenshot")
