"""Verify we can actually talk to Go2_60658 over BLE (handshake + serial)."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

BLE_PY = Path(os.environ.get("TEMP", os.environ.get("TMP", "."))) / "go2_ble.py"
TARGET_NAME = "Go2_60658"
KNOWN_ADDR = "94:BA:06:F6:D6:87"


def load_ble():
    spec = importlib.util.spec_from_file_location("go2_ble", BLE_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {BLE_PY}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


async def main() -> int:
    ble = load_ble()
    print("scanning 12s for Go2_60658")
    devices = await ble.find_robots(
        timeout=12.0,
        on_device=lambda d: print(f"BLE {d.name} {d.address} adv_serial={d.serial}"),
    )
    target = next((d for d in devices if d.name == TARGET_NAME or d.address.upper() == KNOWN_ADDR.upper()), None)
    address = target.address if target else KNOWN_ADDR
    name = target.name if target else TARGET_NAME
    print(f"connecting name={name} addr={address}")

    client = await ble._connect_with_retry(address, 30.0, 3, print)
    session = ble._Session(client)
    try:
        print(f"gatt_connected={client.is_connected}")
        try:
            gap_name = bytes(await client.read_gatt_char("00002a00-0000-1000-8000-00805f9b34fb")).decode("utf-8", "replace")
            print(f"gap_name={gap_name!r}")
        except Exception as exc:
            print(f"gap_name_failed {exc}")
        print("characteristics:")
        for svc in client.services:
            for char in svc.characteristics:
                print(f"  {char.uuid} handle={char.handle} props={char.properties}")
        def on_raw(_sender, data: bytearray) -> None:
            print(f"NOTIFY raw n={len(data)} hex={bytes(data).hex()}")
            session.on_notify(_sender, data)

        notify_ok = False
        for notify_target in (ble.NOTIFY_CHAR_UUID, 12):
            try:
                await client.start_notify(notify_target, on_raw)
                print(f"notify_started {notify_target}")
                notify_ok = True
                break
            except Exception as exc:
                print(f"notify_failed {notify_target}: {exc}")
        if not notify_ok:
            print("NO_NOTIFY")
            return 3
        await asyncio.sleep(0.5)
        packet = ble.build_packet(ble.INST_HANDSHAKE, bytes([0, 0]) + ble.HANDSHAKE_CONTENT)
        print(f"handshake_packet n={len(packet)}")
        handshake_ok = False
        for dest, with_response in ((ble.WRITE_CHAR_UUID, True), (ble.WRITE_CHAR_UUID, False), (17, False)):
            session.event.clear()
            session.last = None
            print(f"handshake write dest={dest} response={with_response}")
            try:
                await client.write_gatt_char(dest, packet, response=with_response)
                print("write_ok")
            except Exception as exc:
                print(f"write_failed: {exc}")
                continue
            try:
                await asyncio.wait_for(session.event.wait(), 5.0)
                print(f"handshake_ok last={session.last.hex() if session.last else None}")
                handshake_ok = True
                break
            except asyncio.TimeoutError:
                print("handshake_timeout")
        if not handshake_ok:
            print("HANDSHAKE_FAILED")
            print(f"STILL_THIS_DOG name={name} addr={address} adv_serial={getattr(target, 'serial', None)}")
            return 2
        session.event.clear()
        await session.write(ble.build_packet(ble.INST_SERIAL, bytes([0])))
        try:
            await asyncio.wait_for(session.event.wait(), 5.0)
        except asyncio.TimeoutError:
            print("serial_timeout")
        if session.serial:
            serial = session.serial.decode("utf-8", errors="replace").rstrip("\x00")
            print(f"PROVED serial={serial} name={name} addr={address}")
            return 0
        print("CONNECTED_HANDSHAKE_NO_SERIAL")
        return 2
    finally:
        await client.disconnect()
        print("disconnected")


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"FAILED {type(exc).__name__}: {exc}")
        raise SystemExit(1)
