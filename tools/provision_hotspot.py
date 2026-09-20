"""Prove BLE is the Go2, then put it on the current Windows Wi-Fi (phone hotspot)."""
from __future__ import annotations

import asyncio
import importlib.util
import subprocess
import sys
from pathlib import Path

BLE_PY = Path(__file__).resolve().parent / "go2_ble.py"
TARGET_NAME = "Go2_60658"
KNOWN_ADDR = "94:BA:06:F6:D6:87"


def load_ble():
    spec = importlib.util.spec_from_file_location("go2_ble", BLE_PY)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {BLE_PY}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def current_ssid() -> str:
    out = subprocess.check_output(["netsh", "wlan", "show", "interfaces"], text=True, encoding="utf-8", errors="replace")
    for line in out.splitlines():
        if "SSID" in line and "BSSID" not in line:
            return line.split(":", 1)[1].strip()
    raise RuntimeError("not connected to Wi-Fi")


def wifi_password(ssid: str) -> str:
    out = subprocess.check_output(
        ["netsh", "wlan", "show", "profile", f"name={ssid}", "key=clear"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in out.splitlines():
        if "Key Content" in line or "Содержимое ключа" in line:
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"no saved password for {ssid!r}")


async def handshake_and_serial(ble, address: str) -> str | None:
    """Connect, handshake, read serial. Does not send Wi-Fi creds."""
    from bleak import BleakClient

    print(f"GATT connect {address}")
    client = await ble._connect_with_retry(address, 30.0, 3, print)
    session = ble._Session(client)
    try:
        try:
            await client.start_notify(ble.NOTIFY_CHAR_UUID, session.on_notify)
        except Exception:
            await client.start_notify(13, session.on_notify)
        print("handshake")
        await session.write_validated(
            ble.build_packet(ble.INST_HANDSHAKE, bytes([0, 0]) + ble.HANDSHAKE_CONTENT),
            ble.INST_HANDSHAKE,
        )
        print("handshake_ok")
        print("read_serial")
        await session.write(ble.build_packet(ble.INST_SERIAL, bytes([0])))
        try:
            await asyncio.wait_for(session.event.wait(), 3.0)
        except asyncio.TimeoutError:
            print("serial_timeout")
        session.event.clear()
        serial = None
        if session.serial:
            serial = session.serial.decode("utf-8", errors="replace").rstrip("\x00")
            print(f"serial={serial}")
        else:
            print("serial=none")
        return serial
    finally:
        await client.disconnect()
        print("gatt_disconnected")


async def main() -> int:
    ble = load_ble()
    ssid = current_ssid()
    password = wifi_password(ssid)
    print(f"hotspot_ssid={ssid!r} password_len={len(password)}")

    print("scanning 12s")
    devices = await ble.find_robots(timeout=12.0, on_device=lambda d: print(f"BLE {d.name} {d.address} serial={d.serial}"))
    target = None
    for d in devices:
        if d.name == TARGET_NAME or d.address.upper() == KNOWN_ADDR.upper():
            target = d
            break
    if target is None and devices:
        target = devices[0]
    if target is None:
        print(f"not advertising; trying known {KNOWN_ADDR}")
        address = KNOWN_ADDR
        name = TARGET_NAME
    else:
        address = target.address
        name = target.name
    print(f"target name={name} addr={address} adv_serial={getattr(target, 'serial', None)}")

    serial = await handshake_and_serial(ble, address)
    if serial is None:
        print("HANDSHAKE_OR_SERIAL_WEAK — still attempting wifi provision")
    else:
        print(f"PROVED_UNITREE_BLE name={name} serial={serial}")

    print("provision_wifi")

    def progress(msg: str) -> None:
        print(f"  {msg}")

    device_serial = await ble.retry(
        lambda: ble.provision_wifi(address, ssid, password, "US", on_progress=progress),
        attempts=3,
        on_error=lambda i, e: print(f"  attempt {i} failed: {e}"),
    )
    print(f"PROVISIONED serial={device_serial}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except Exception as exc:
        print(f"FAILED {type(exc).__name__}: {exc}")
        raise SystemExit(1)
