"""Last-ditch Windows BLE: pair, CCCD, handshake, then hotspot STA if it works."""
from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
from pathlib import Path

BLE_PY = Path(__file__).resolve().parent / "go2_ble.py"
ADDR = "94:BA:06:F6:D6:87"
CCCD_HANDLE = 13  # notify char is handle 12; CCCD is typically +1


def load_ble():
    spec = importlib.util.spec_from_file_location("go2_ble", BLE_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def hotspot_creds() -> tuple[str, str]:
    iface = subprocess.check_output(
        ["netsh", "wlan", "show", "interfaces"], text=True, encoding="utf-8", errors="replace"
    )
    ssid = ""
    for line in iface.splitlines():
        if "SSID" in line and "BSSID" not in line:
            ssid = line.split(":", 1)[1].strip()
            break
    if not ssid:
        raise RuntimeError("not on wifi")
    prof = subprocess.check_output(
        ["netsh", "wlan", "show", "profile", f"name={ssid}", "key=clear"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    password = ""
    for line in prof.splitlines():
        if "Key Content" in line:
            password = line.split(":", 1)[1].strip()
            break
    if not password:
        raise RuntimeError("no saved hotspot password")
    return ssid, password


async def main() -> int:
    from bleak import BleakClient

    ble = load_ble()
    ssid, password = hotspot_creds()
    print(f"ssid={ssid!r} password_len={len(password)}")

    client = BleakClient(ADDR, timeout=30.0)
    await client.connect()
    print(f"connected={client.is_connected}")
    try:
        try:
            print(f"pair={await client.pair()}")
        except Exception as exc:
            print(f"pair_skip {type(exc).__name__}: {exc}")

        got = asyncio.Event()
        session = ble._Session(client)

        def on_raw(_s, data: bytearray) -> None:
            print(f"NOTIFY {bytes(data).hex()}")
            session.on_notify(_s, data)
            got.set()

        try:
            await client.write_gatt_char(CCCD_HANDLE, b"\x01\x00", response=True)
            print("cccd_write_ok")
        except Exception as exc:
            print(f"cccd_write_fail {exc}")

        await client.start_notify(ble.NOTIFY_CHAR_UUID, on_raw)
        await asyncio.sleep(0.5)
        packet = ble.build_packet(ble.INST_HANDSHAKE, bytes([0, 0]) + ble.HANDSHAKE_CONTENT)
        print(f"handshake n={len(packet)}")
        await client.write_gatt_char(ble.WRITE_CHAR_UUID, packet, response=False)
        try:
            await asyncio.wait_for(got.wait(), 8.0)
        except asyncio.TimeoutError:
            print("HANDSHAKE_TIMEOUT")
            return 2
        print("handshake_got_notify")
        serial = await ble.provision_wifi(
            ADDR, ssid, password, "US", on_progress=print
        )
        print(f"PROVISIONED serial={serial}")
        return 0
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"FAILED {type(exc).__name__}: {exc}")
        raise SystemExit(1)
