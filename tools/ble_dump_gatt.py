"""ble_dump_gatt.py - what does the Go2 actually expose over GATT, and does it notify?

The handshake times out with an empty TimeoutError: go2_ble.py connects, calls
start_notify, writes the handshake packet, and no notification ever arrives.
That has three possible causes and this tool separates them:

  1. wrong characteristics  - this firmware does not use ffe0/ffe1/ffe2, so
     start_notify(NOTIFY_CHAR_UUID) throws and the fallback to raw handle 13
     subscribes to the wrong thing (or nothing).
  2. notifications need encryption - the characteristic exists but the dog
     refuses to notify on an unauthenticated link, so a bond is required.
  3. the dog rejects the handshake payload itself - it notifies for other
     instructions but not this one.

Read-only: it enumerates, subscribes, and optionally sends ONE handshake to see
whether any notification at all comes back. It never writes wifi credentials.

    python3 tools/ble_dump_gatt.py                 # enumerate + listen
    python3 tools/ble_dump_gatt.py --handshake     # also send one handshake
    python3 tools/ble_dump_gatt.py --pair          # bond first (tests cause 2)
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

BLE_PY = Path(__file__).resolve().parent / "go2_ble.py"
DEFAULT_MAC = "94:BA:06:F6:D6:87"
DEFAULT_NAME = "Go2_60658"


def load_ble():
    spec = importlib.util.spec_from_file_location("go2_ble", BLE_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {BLE_PY}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mac", default=DEFAULT_MAC)
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--listen", type=float, default=8.0, help="seconds to wait for notifications")
    ap.add_argument("--handshake", action="store_true", help="send one handshake packet")
    ap.add_argument("--pair", action="store_true", help="bond before subscribing")
    a = ap.parse_args()

    from bleak import BleakClient, BleakScanner

    ble = load_ble()

    print(f"scanning for {a.name} / {a.mac} ...")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, _adv: (d.name == a.name) or (d.address.upper() == a.mac.upper()),
        timeout=20.0,
    )
    if dev is None:
        print("NOT FOUND - is it advertising? run tools/ble_scan_go2.py")
        return 1
    print(f"found {dev.name} {dev.address}")

    async with BleakClient(dev, timeout=a.timeout) as client:
        print(f"connected={client.is_connected}")

        if a.pair:
            try:
                print(f"pair -> {await client.pair()}")
            except Exception as exc:
                print(f"pair failed: {type(exc).__name__}: {exc}")

        print("\n=== GATT table ===")
        notify_chars = []
        write_chars = []
        for svc in client.services:
            print(f"service {svc.uuid}  (handle {svc.handle})")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                print(f"   char {ch.uuid}  handle={ch.handle}  [{props}]")
                for d in ch.descriptors:
                    print(f"      desc {d.uuid}  handle={d.handle}")
                if "notify" in ch.properties or "indicate" in ch.properties:
                    notify_chars.append(ch)
                if "write" in ch.properties or "write-without-response" in ch.properties:
                    write_chars.append(ch)

        print("\n=== what go2_ble.py expects ===")
        for label, want in (("service", ble.UNITREE_SERVICE_UUID),
                            ("notify ", ble.NOTIFY_CHAR_UUID),
                            ("write  ", ble.WRITE_CHAR_UUID)):
            uuids = [s.uuid for s in client.services] + [
                c.uuid for s in client.services for c in s.characteristics]
            mark = "PRESENT" if want.lower() in [u.lower() for u in uuids] else "*** MISSING ***"
            print(f"  {label} {want}  {mark}")

        print(f"\nnotify-capable chars: {[c.uuid for c in notify_chars]}")
        print(f"writable chars:       {[c.uuid for c in write_chars]}")

        # Subscribe to EVERY notify-capable characteristic, not just the expected
        # one, so a firmware that moved the channel still shows up.
        got: list[tuple[str, bytes]] = []

        def make_cb(uuid):
            def cb(_sender, data: bytearray):
                got.append((uuid, bytes(data)))
                print(f"  NOTIFY {uuid}: {bytes(data).hex()}")
            return cb

        print("\n=== subscribing to all notify chars ===")
        subscribed = []
        for ch in notify_chars:
            try:
                await client.start_notify(ch.uuid, make_cb(ch.uuid))
                subscribed.append(ch.uuid)
                print(f"  ok  {ch.uuid}")
            except Exception as exc:
                print(f"  FAIL {ch.uuid}: {type(exc).__name__}: {exc}")
        if not subscribed:
            print("  nothing subscribed - this alone explains the handshake timeout")

        if a.handshake and subscribed:
            print("\n=== sending ONE handshake ===")
            pkt = ble.build_packet(ble.INST_HANDSHAKE, bytes([0, 0]) + ble.HANDSHAKE_CONTENT)
            print(f"  packet: {pkt.hex()}")
            target = ble.WRITE_CHAR_UUID
            if target.lower() not in [c.uuid.lower() for c in write_chars]:
                target = write_chars[0].uuid if write_chars else None
                print(f"  expected write char missing; using {target}")
            if target:
                try:
                    await client.write_gatt_char(target, pkt, response=True)
                    print("  write ok")
                except Exception as exc:
                    print(f"  write FAILED: {type(exc).__name__}: {exc}")

        print(f"\nlistening {a.listen}s for notifications ...")
        await asyncio.sleep(a.listen)

        print("\n=== VERDICT ===")
        if got:
            print(f"  the dog DOES notify ({len(got)} packet(s)).")
            print("  So the channel works; the handshake payload or the expected")
            print("  characteristic in go2_ble.py is what is wrong.")
        elif not subscribed:
            print("  could not subscribe to any notify characteristic.")
            print("  -> retry with --pair; many peripherals refuse notifications")
            print("     on an unauthenticated link.")
        else:
            print("  subscribed fine but the dog sent NOTHING.")
            print("  -> if you used --handshake, the dog ignored it: it is likely")
            print("     refusing an unauthorised/unbound central (matches the app's")
            print("     earlier 'unauthorized'), or this firmware uses a different")
            print("     provisioning protocol than go2_ble.py implements.")
            print("  -> try --pair next.")
        await client.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
