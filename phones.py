"""
phones.py - read magnetometer data from phones running phyphox.

On each phone: install phyphox -> open "Magnetometer" -> menu (three dots) ->
"Allow remote access". It shows a URL like http://192.168.43.12:8080 .
All phones and the laptop must be on the SAME hotspot.

Live test (the 10-minute hand test):
    python phones.py http://LOW_PHONE:8080 [http://HIGH_PHONE:8080]
List a phone's buffer names (if magX/magY/magZ are not found):
    python phones.py --config http://LOW_PHONE:8080
Sweep the phone over scissors / a steel pot and watch the total field change.
"""
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import numpy as np

BUFFERS = ("magX", "magY", "magZ")  # phyphox Magnetometer experiment; check /config if yours differ


class PhyphoxPhone:
    def __init__(self, url, buffers=BUFFERS, timeout=2.0):
        self.url = url.rstrip("/")
        self.buffers = buffers
        self.timeout = timeout

    def _get(self, path):
        with urllib.request.urlopen(self.url + path, timeout=self.timeout) as r:
            return json.loads(r.read().decode())

    def start(self):
        self._get("/control?cmd=start")

    def config(self):
        return self._get("/config")

    def latest(self):
        """Most recent (x, y, z) reading in uT, phone frame."""
        data = self._get("/get?" + "&".join(self.buffers))
        out = []
        for b in self.buffers:
            if b not in data.get("buffer", {}):
                raise RuntimeError(f"{self.url}: phone has no buffer '{b}'. Is the Magnetometer "
                                   f"experiment open? List buffers: python phones.py --config {self.url}")
            buf = data["buffer"][b]["buffer"]
            if not buf or buf[-1] is None:
                raise RuntimeError(f"{self.url}: no data in {b} - press play in phyphox")
            out.append(float(buf[-1]))
        return np.array(out)

    def _window_full(self, seconds):
        """Clear, record for `seconds`, fetch every sample. Returns (N,3) or None."""
        self._get("/control?cmd=clear")
        self._get("/control?cmd=start")
        time.sleep(seconds)
        data = self._get("/get?" + "&".join(f"{b}=full" for b in self.buffers))
        cols = [np.array([v for v in data["buffer"][b]["buffer"] if v is not None], float)
                for b in self.buffers]
        n = min(len(c) for c in cols)
        return np.column_stack([c[:n] for c in cols]) if n >= 5 else None

    def _window_poll(self, seconds, rate_hz=30):
        samples, t_end = [], time.time() + seconds
        while time.time() < t_end:
            try:
                samples.append(self.latest())
            except Exception:
                pass
            time.sleep(1.0 / rate_hz)
        if len(samples) < 3:
            raise RuntimeError(f"{self.url}: no samples - check hotspot / remote access")
        return np.array(samples)

    def sample(self, seconds):
        """Record for `seconds`. Returns (N,3) samples in uT."""
        try:
            s = self._window_full(seconds)
            if s is not None:
                return s
        except Exception:
            pass
        return self._window_poll(seconds)


def summarize(samples):
    """Median vector, median total field, standard error of the total (uT)."""
    totals = np.linalg.norm(samples, axis=1)
    se = np.std(totals) / np.sqrt(len(totals))
    return np.median(samples, axis=0), float(np.median(totals)), float(se)


def read_pair(phones, seconds, target_se=0.12, max_seconds=4.0):
    """Read both phones at the same time. Keeps averaging (up to max_seconds)
    until each total-field reading has standard error <= target_se uT."""
    acc = [[] for _ in phones]
    elapsed = 0.0
    with ThreadPoolExecutor(len(phones)) as pool:
        while True:
            for i, s in enumerate(pool.map(lambda p: p.sample(seconds), phones)):
                acc[i].append(s)
            elapsed += seconds
            stats = [summarize(np.vstack(a)) for a in acc]
            if max(st[2] for st in stats) <= target_se or elapsed >= max_seconds:
                return stats  # [(vec, total, se), ...] per phone


def phone_to_arena(v):
    """Phone lying flat, screen up, TOP of phone pointing forward along the boom.
    Phone axes: x=right, y=top, z=out of screen. Arena: x=forward, y=left, z=up."""
    return np.array([v[1], -v[0], v[2]])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--config":
        cfg = PhyphoxPhone(sys.argv[2]).config()
        print("buffers:", [b["name"] for b in cfg.get("buffers", [])])
        sys.exit()
    urls = sys.argv[1:] or ["http://192.168.43.12:8080"]
    phones = [PhyphoxPhone(u) for u in urls]
    for p in phones:
        p.start()
    print("Ctrl+C to stop. Columns: total field per phone (uT)" +
          (", low-minus-high gradient" if len(phones) == 2 else ""))
    base = None
    while True:
        tots = [np.linalg.norm(p.latest()) for p in phones]
        base = tots if base is None else base
        line = "  ".join(f"{t:7.2f} ({t - b:+5.2f})" for t, b in zip(tots, base))
        if len(tots) == 2:
            line += f"   grad {(tots[0] - base[0]) - (tots[1] - base[1]):+5.2f}"
        print(line, flush=True)
        time.sleep(0.2)
