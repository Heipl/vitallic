"""Scan for a Unitree Go2 over BLE and open a GATT connection."""
import asyncio
import sys

from bleak import BleakClient, BleakScanner

PREFIXES = ("Go2_", "G1_", "B2_", "H1_", "X1_")


async def main() -> int:
    found: dict[str, str] = {}
    others = 0
    print("Scanning BLE for 20s for Unitree dog...")

    def on_detect(device, adv) -> None:
        nonlocal others
        name = device.name or ""
        lowered = name.lower()
        is_unitree = name.startswith(PREFIXES) or "unitree" in lowered or "go2" in lowered
        if is_unitree:
            if device.address not in found:
                rssi = getattr(adv, "rssi", "?")
                print(f"FOUND name={name!r} addr={device.address} rssi={rssi}")
            found[device.address] = name or found.get(device.address, "?")
        else:
            others += 1

    async with BleakScanner(detection_callback=on_detect):
        await asyncio.sleep(20)

    print(f"Scan done. unitree={len(found)} other_adv_callbacks={others}")
    if not found:
        print("NO_DOG")
        return 1

    addr, name = next(iter(found.items()))
    print(f"Connecting GATT to {name} {addr} ...")
    last_exc: Exception | None = None
    for i in range(3):
        client = BleakClient(addr, timeout=30.0)
        try:
            await client.connect()
            print(f"CONNECTED is_connected={client.is_connected} name={name} addr={addr}")
            try:
                print("services:")
                for svc in client.services:
                    print(f"  {svc.uuid} {svc.description}")
            except Exception as exc:
                print("services_error", exc)
            await asyncio.sleep(3)
            await client.disconnect()
            print("disconnected_cleanly")
            return 0
        except Exception as exc:
            last_exc = exc
            print(f"connect attempt {i + 1}/3 failed: {exc}")
            try:
                await client.disconnect()
            except Exception:
                pass
            await asyncio.sleep(1)
    print("CONNECT_FAILED", last_exc)
    return 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
