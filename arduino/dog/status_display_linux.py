# Vitallic status display - Linux side of the Arduino UNO Q (Arduino App Lab app, optional).
# Polls the laptop running field_scan.py and forwards the state to the LED-matrix sketch.
import time
import urllib.request

from arduino.app_utils import App, Bridge

LAPTOP_STATE_URL = "http://192.168.43.100:8765/state"  # <- laptop's IP on your hotspot

CODES = {"IDLE": 0, "DONE": 0, "BASELINE": 1, "SCAN": 1, "CALIBRATION": 1,
         "MINE_SIZED": 2, "FRAGMENT": 3, "RESCAN": 4, "NO_TARGET": 5}
last = None


def loop():
    global last
    try:
        with urllib.request.urlopen(LAPTOP_STATE_URL, timeout=1) as r:
            state = r.read().decode().strip()
    except Exception:
        state = "IDLE"  # laptop unreachable -> idle, never a false "all clear"
    code = CODES.get(state, 0)
    if code != last:
        Bridge.call("show", code)
        last = code
    time.sleep(0.3)


App.run(user_loop=loop)
