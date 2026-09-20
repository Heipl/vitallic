import asyncio
from bleak import BleakScanner

async def main() -> None:
    found: dict[str, str] = {}

    def on(device, adv) -> None:
        name = device.name or ""
        if name.startswith(("Go2_", "G1_", "B2_")):
            if device.address not in found:
                found[device.address] = name
                print(f"BLE {name} {device.address} rssi={getattr(adv, 'rssi', '?')}")

    async with BleakScanner(detection_callback=on):
        await asyncio.sleep(10)
    print(f"count={len(found)}")

asyncio.run(main())
