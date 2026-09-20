"""Pair + Unitree BLE handshake on Go2_60658. No Wi-Fi creds, no app."""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

BLE_PY = Path(os.environ.get("TEMP", ".")) / "go2_ble.py"
ADDR = "94:BA:06:F6:D6:87"


def load_ble():
    spec = importlib.util.spec_from_file_location("go2_ble", BLE_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


async def main() -> int:
    from bleak import BleakClient, BleakScanner

    ble = load_ble()
    print("scan 8s")
    seen = False

    def on(d, adv):
        nonlocal seen
        if d.address.upper() == ADDR.upper() or (d.name or "").startswith("Go2_"):
            print(f"adv {d.name} {d.address}")
            seen = True

    async with BleakScanner(detection_callback=on):
        await asyncio.sleep(8)
    print(f"saw_target={seen}")

    client = BleakClient(ADDR, timeout=30.0)
    await client.connect()
    print(f"connected={client.is_connected} mtu={getattr(client, 'mtu_size', None)}")
    try:
        try:
            paired = await client.pair(protection_level=2)
            print(f"pair={paired}")
        except Exception as exc:
            print(f"pair_skipped {type(exc).__name__}: {exc}")
        try:
            await client._backend._acquire_mtu()  # type: ignore[attr-defined]
            print(f"mtu_after={getattr(client, 'mtu_size', None)}")
        except Exception as exc:
            print(f"mtu_skipped {exc}")

        got = asyncio.Event()
        raws: list[bytes] = []

        def on_raw(_s, data: bytearray) -> None:
            raws.append(bytes(data))
            print(f"NOTIFY {bytes(data).hex()}")
            got.set()

        await client.start_notify(ble.NOTIFY_CHAR_UUID, on_raw)
        await asyncio.sleep(0.8)
        packet = ble.build_packet(ble.INST_HANDSHAKE, bytes([0, 0]) + ble.HANDSHAKE_CONTENT)
        print(f"write handshake n={len(packet)} hex={packet.hex()}")
        await client.write_gatt_char(17, packet, response=True)
        try:
            await asyncio.wait_for(got.wait(), 6.0)
            print("HANDSHAKE_NOTIFY")
            return 0
        except asyncio.TimeoutError:
            print("no notify after pair/write")
            return 2
    finally:
        await client.disconnect()
        print("disconnected")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
