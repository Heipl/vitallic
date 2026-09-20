# Connecting the phones (the sensor)

The phones are the metal detector. Each runs phyphox, which serves its
magnetometer over HTTP; the laptop polls both and fits a dipole to the
difference. There is no wiring, no coil and nothing attached to the robot.

Every step below has a check. Do not move on from a step that has not passed —
each one failed at least once during setup, and they all look the same from
downstream (`no readings`).

---

## 1. Install phyphox

Free, on iOS and Android. Install it on **both** phones.

## 2. Open the Magnetometer experiment

Open phyphox and pick **Magnetometer** from the experiment list.

This matters more than it looks. Remote access is enabled **per experiment**,
not globally, and the buffer names the code reads (`magX`, `magY`, `magZ`) only
exist in this one. A different magnetic experiment serves different buffer names
and `phones.py` will not find them.

You must be *inside* the experiment, not on the app's home screen.

## 3. Press play

Tap **▶**. phyphox does not serve data it is not recording.

## 4. Enable remote access

**⋮** (top right) → **Allow remote access** → accept the warning.

It then shows a URL. **It must contain `:8080`.** An address with no port means
the server is not actually running.

### iOS: if there is no `:8080`

That is the Local Network permission, every time.

1. Settings → Privacy & Security → **Local Network** → enable **phyphox**
2. Force-quit phyphox (swipe up) and reopen — the permission only takes effect
   on a fresh launch
3. Magnetometer → ▶ → ⋮ → Allow remote access

### Android: if it shows TWO URLs

It lists one per interface. Use the one whose subnet matches the laptop's. On
this rig the first line was unreachable and the second (`10.31.142.9:8080`) was
the live one.

## 5. Get both phones on a network the laptop can reach

Not "the same Wi-Fi name" — actually routable to the laptop.

**Phone hotspots usually isolate their clients.** Measured on this rig: the
laptop could reach the phone *hosting* the hotspot on port 8080, but the other
phone answered ping and then **timed out on every TCP port**. ICMP passes,
TCP is dropped. Phone 2 is unreachable and nothing about phyphox is wrong.

Safest arrangement: **host the hotspot from the laptop that runs the scan.**
It is then the hub, and host→client always works.

```bash
# on the Linux laptop
nmcli device wifi hotspot ifname wlan0 ssid vitallic password vitallic123
```

Join both phones to it. Enterprise Wi-Fi (MIT SECURE and similar) works for
phones but **cannot host the robot**, which only accepts an SSID and a
passphrase.

## 6. Keep them awake

Screen timeout → **Never**, both phones. phyphox stops serving the moment the
app backgrounds or the screen locks. This will end a scan mid-run otherwise.

## 7. Check the laptop can actually read them

```bash
python phones.py http://LOW_PHONE:8080
```

If it complains about buffers:

```bash
python phones.py --config http://LOW_PHONE:8080    # lists the real buffer names
```

Expect a total field around **40–55 µT** (Earth's field) and, sitting still, a
drift figure staying inside **±0.5 µT**.

Measured on this rig: a good Android held **0.358 µT** noise. An iPhone read
**13.5 µT** total where the Android read 40.6 in the same spot, and drifted
several µT over ~10 s as iOS recalibrated.

A constant offset between the phones is harmless — the fit carries a per-phone
offset term. **Drift is not**, and it will corrupt a long scan. If you have two
Androids, use two Androids.

## 8. Prove it sees steel

Hold the phone still, bring a steel pot to 5–10 cm, then take it away.

Measured on this rig: baseline 40.97 µT, noise 0.398 µT, **peak deviation
+38.63 µT — 97× the noise**. The sign flips depending on which side you
approach from; that is real dipole behaviour, not an error.

If you get nothing here, stop. Nothing downstream can work, and no amount of
robot work will help.

## 9. Mount them

- Both **flat, screen up**, **top edge pointing forward** along the boom.
  `phone_to_arena()` assumes exactly that: `arena = [y_phone, −x_phone, z_phone]`.
- **LOW** ≈ 5 cm off the ground, **HIGH** ≈ 35 cm (`--h-low`, `--h-high`).
- Boom of wood, PVC or cardboard, ~0.65 m ahead of the dog (`--boom`).
- No metal fixings, no magnetic cases, keys out of your pockets.
- Mount them **rigidly**. Hand-held, baseline noise measured 4.1 µT against
  0.4 µT fixed — a tenfold penalty for holding them.

Check both at once, and confirm a near object hits LOW much harder than HIGH:

```bash
python phones.py http://LOW:8080 http://HIGH:8080
```

Measured with the pot near the low phone: LOW swung ±7–8 µT while HIGH stayed
within ±0.5 — about **14×**. That ratio *is* the gradiometer, and it is what
gives depth.

## 10. Run it

```bash
# stationary, spot by spot
python field_scan.py --manual --low http://LOW:8080 --high http://HIGH:8080

# or walk it
python sweep.py --low http://LOW:8080 --high http://HIGH:8080 \
    --lat 42.3601 --lon -71.0942 --heading 0
```

Live map: <http://localhost:8765/>

---

## When it stops working mid-demo

| Symptom | Cause |
|---|---|
| `did not answer` | screen locked, or phyphox backgrounded |
| reading jumps several µT and stays | the OS recalibrated. Re-baseline and rescan that spot |
| one phone reachable, the other not | hotspot client isolation — host from the laptop instead |
| URL shows no `:8080` | remote access is not on (iOS: Local Network permission) |
| buffers not found | wrong experiment — it must be **Magnetometer** |
| IP changed | DHCP renewed. Re-read the URL from the phyphox screen |
