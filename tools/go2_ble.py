# Copyright 2025-2026 Dimensional Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# Vendored from dimos 0.0.14: dimos/robot/unitree/go2/cli/ble.py

"""BLE wifi-provisioning protocol for Unitree robots.

Protocol reverse-engineered by the UniPwn project (https://github.com/Bin4ry/UniPwn);
this module strips the exploit payload and keeps only the legitimate provisioning
flow used by the official Unitree app.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

UNITREE_NAME_PREFIXES = ("Go2_", "G1_", "B2_", "H1_", "X1_")

UNITREE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"

# Symmetric AES-CFB-128 key/iv burned into the firmware.
_AES_KEY = bytes.fromhex("df98b715d5c6ed2b25817b6f2554124a")
_AES_IV = bytes.fromhex("2841ae97419c2973296a0d4bdfe19a4f")

CHUNK_SIZE = 14
HANDSHAKE_CONTENT = b"unitree"

# Instruction opcodes (TX / RX use the same numbers; opcode byte differs: 0x52 / 0x51).
INST_HANDSHAKE = 1
INST_SERIAL = 2
INST_INIT_STA = 3
INST_SSID = 4
INST_PASSWORD = 5
INST_COUNTRY = 6


@dataclass
class Go2Device:
    name: str
    address: str
    serial: str | None = None


def _serial_from_manuf(manuf_data: dict[int, bytes] | None) -> str | None:
    """Recover the full 16-char serial from BLE manufacturer data.

    The Go2 packs its serial across the company-ID + payload field: the
    company-ID's little-endian bytes spell the first two ASCII chars, the
    payload spells the rest.
    """
    if not manuf_data:
        return None
    cid, payload = next(iter(manuf_data.items()))
    prefix = bytes([cid & 0xFF, (cid >> 8) & 0xFF])
    try:
        return (prefix + payload).decode("ascii")
    except UnicodeDecodeError:
        return None


def _cipher() -> Any:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    return Cipher(algorithms.AES(_AES_KEY), modes.CFB(_AES_IV))


def encrypt(data: bytes) -> bytes:
    enc = _cipher().encryptor()
    out: bytes = enc.update(data) + enc.finalize()
    return out


def decrypt(data: bytes) -> bytes:
    dec = _cipher().decryptor()
    out: bytes = dec.update(data) + dec.finalize()
    return out


def build_packet(instruction: int, payload: bytes = b"") -> bytes:
    """Build an encrypted TX packet: 0x52, length, instruction, *payload, checksum."""
    body = bytes([0x52, len(payload) + 4, instruction]) + payload
    checksum = (-sum(body)) & 0xFF
    return encrypt(body + bytes([checksum]))


def validate_response(response: bytes, expected_inst: int) -> bool:
    if len(response) < 5:
        return False
    if response[0] != 0x51:
        return False
    if len(response) != response[1]:
        return False
    if response[2] != expected_inst:
        return False
    if (-sum(response[:-1])) & 0xFF != response[-1]:
        return False
    return response[3] == 0x01


async def _stop_stale_bluez_scan() -> None:
    """Tell BlueZ to drop any leftover scan from a prior process.

    `BleakScanner.__aexit__` is what normally calls StopDiscovery. If a previous
    invocation was killed before that ran (e.g. SIGTERM from `timeout`), BlueZ
    keeps the session and the next StartDiscovery returns `InProgress`. Best-effort.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "bluetoothctl",
            "scan",
            "off",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            proc.kill()
    except (FileNotFoundError, OSError):
        pass


def _mac_from_btctl_line(line: str, name: str | None) -> str | None:
    if "Device " not in line:
        return None
    if name and name not in line:
        return None
    parts = line.replace("[NEW]", " ").replace("[CHG]", " ").split()
    for i, part in enumerate(parts):
        if part == "Device" and i + 1 < len(parts) and parts[i + 1].count(":") == 5:
            return parts[i + 1]
    return None


async def _spawn_btctl() -> asyncio.subprocess.Process:
    for argv in (["stdbuf", "-oL", "bluetoothctl"], ["bluetoothctl"]):
        try:
            return await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            continue
    raise RuntimeError("bluetoothctl not found")


async def _linux_btctl_connect(
    address: str | None,
    name: str | None,
    timeout: float,
    on_progress: Callable[[str], None],
) -> str:
    """Scan and connect with one bluetoothctl process. Do not mix with BleakScanner."""
    await _stop_stale_bluez_scan()
    proc = await _spawn_btctl()
    assert proc.stdin is not None and proc.stdout is not None
    lines: list[str] = []

    async def pump() -> None:
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                return
            line = raw.decode("utf-8", "replace").rstrip()
            if not line:
                continue
            lines.append(line)
            on_progress(f"btctl {line}")

    async def send(cmd: str) -> None:
        on_progress(f"btctl > {cmd}")
        proc.stdin.write((cmd + "\n").encode())
        await proc.stdin.drain()

    async def wait_pred(pred: Callable[[], bool], seconds: float) -> bool:
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while loop.time() < end:
            if pred():
                return True
            await asyncio.sleep(0.12)
        return pred()

    pump_task = asyncio.create_task(pump())
    connected: str | None = None
    try:
        await send("power on")
        await send("agent on")
        await send("default-agent")
        await send("menu scan")
        await send("transport le")
        await send("back")
        await send("scan on")

        def found_mac() -> str | None:
            for line in lines:
                mac = _mac_from_btctl_line(line, name)
                if mac:
                    return mac
            return None

        if not await wait_pred(lambda: found_mac() is not None, timeout):
            raise RuntimeError(f"bluetoothctl scan missed {name or address}")

        seen = found_mac()
        assert seen is not None
        on_progress(f"seen {name} {seen}")
        await send(f"info {seen}")
        await asyncio.sleep(0.5)

        candidates: list[str] = []
        for mac in (seen, address):
            if mac and mac.upper() not in {c.upper() for c in candidates}:
                candidates.append(mac)

        for mac in candidates:
            n_before = len(lines)
            await send(f"connect {mac}")

            def ok(n: int = n_before) -> bool:
                return any(
                    "Connection successful" in line or "Connected: yes" in line
                    for line in lines[n:]
                )

            def bad(n: int = n_before) -> bool:
                return any("Failed to connect" in line for line in lines[n:])

            if await wait_pred(lambda: ok() or bad(), min(12.0, timeout)):
                if ok():
                    connected = mac
                    await send(f"trust {mac}")
                    break
            on_progress(f"connect {mac} failed")
            await send(f"pair {mac}")
            await asyncio.sleep(2.0)
            n_pair = len(lines)
            await send(f"connect {mac}")
            if await wait_pred(
                lambda: any(
                    "Connection successful" in line or "Connected: yes" in line
                    for line in lines[n_pair:]
                ),
                8.0,
            ):
                connected = mac
                await send(f"trust {mac}")
                break

        await send("scan off")
        if connected is None:
            raise RuntimeError(
                "bluetoothctl could not connect "
                f"(tried {', '.join(candidates)}). Disconnect this laptop "
                "from 2.4 GHz Wi-Fi and retry; BLE shares that radio."
            )
        return connected
    finally:
        try:
            proc.stdin.write(b"quit\n")
            await proc.stdin.drain()
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=3.0)
        except Exception:
            pass
        pump_task.cancel()


async def _connect_already(address: str, timeout: float, on_progress: Callable[[str], None]) -> Any:
    from bleak import BleakClient

    on_progress(f"attaching to existing BlueZ connection {address}")
    client = BleakClient(address, timeout=timeout)
    await asyncio.wait_for(client.connect(), timeout=timeout)
    return client


async def _connect_once(
    address: str | None,
    name: str | None,
    timeout: float,
    on_progress: Callable[[str], None],
) -> Any:
    """Find the dog, then GATT-connect before BlueZ forgets the advertisement.

    BleakScanner is tried first on every platform, including Linux. Driving
    `bluetoothctl` over a pipe does NOT reliably emit "[NEW]/[CHG] Device" lines:
    its readline UI suppresses async discovery events when stdout is not a TTY,
    so _linux_btctl_connect's pump sees only the prompt and reports
    "bluetoothctl scan missed <name>" for a device that is advertising strongly.
    BleakScanner talks to BlueZ over D-Bus and is unaffected (tools/ble_scan_go2.py
    finds the dog at rssi -59 while the bluetoothctl path reports a miss).
    bluetoothctl is kept as a Linux fallback since it also does pair/trust.
    """
    from bleak import BleakClient, BleakScanner

    await _stop_stale_bluez_scan()
    found = asyncio.Event()
    box: dict[str, Any] = {}

    def on_detect(device: Any, _adv: Any) -> None:
        if "dev" in box:
            return
        if _is_target(device, address, name):
            box["dev"] = device
            found.set()

    async with BleakScanner(detection_callback=on_detect):
        try:
            await asyncio.wait_for(found.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            box.pop("dev", None)
        if "dev" in box:
            device = box["dev"]
            on_progress(f"connecting {device.name} {device.address}")
            client = BleakClient(device, timeout=timeout)
            await client.connect()
            return client

    if sys.platform.startswith("linux"):
        on_progress("BleakScanner missed it; falling back to bluetoothctl")
        mac = await _linux_btctl_connect(address, name, timeout, on_progress)
        on_progress(f"bleak attach {mac}")
        client = BleakClient(mac, timeout=timeout)
        await asyncio.wait_for(client.connect(), timeout=timeout)
        return client

    raise RuntimeError(f"scan missed {name or address}; dog on and advertising?")


async def discover_ble(
    prefixes: tuple[str, ...] = UNITREE_NAME_PREFIXES,
) -> AsyncIterator[Go2Device]:
    """Stream Unitree robots seen over BLE. Runs until the consumer stops iterating.

    Yields a device on first sighting, and again whenever a later adv packet
    upgrades a previously-unknown serial number.
    """
    from bleak import BleakScanner

    await _stop_stale_bluez_scan()

    found: dict[str, Go2Device] = {}
    queue: asyncio.Queue[Go2Device] = asyncio.Queue()

    def _on_detect(device: Any, adv: Any) -> None:
        if not device.name or not device.name.startswith(prefixes):
            return
        serial = _serial_from_manuf(getattr(adv, "manufacturer_data", None))
        existing = found.get(device.address)
        if existing is None:
            dev = Go2Device(name=device.name, address=device.address, serial=serial)
            found[device.address] = dev
            queue.put_nowait(dev)
        elif existing.serial is None and serial is not None:
            existing.serial = serial
            queue.put_nowait(existing)

    async with BleakScanner(detection_callback=_on_detect):
        while True:
            yield await queue.get()


async def find_robots(
    timeout: float = 15.0,
    prefixes: tuple[str, ...] = UNITREE_NAME_PREFIXES,
    on_device: Callable[[Go2Device], None] | None = None,
) -> list[Go2Device]:
    """One-shot BLE scan: collects devices for `timeout` seconds and returns them."""
    out: dict[str, Go2Device] = {}

    async def _collect() -> None:
        async for dev in discover_ble(prefixes=prefixes):
            out[dev.address] = dev
            if on_device is not None:
                on_device(dev)

    try:
        await asyncio.wait_for(_collect(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return list(out.values())


class _Session:
    """Internal helper that wraps a BleakClient with the unitree request/response state."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.event = asyncio.Event()
        self.last: bytes | None = None
        self.serial_chunks: dict[int, bytes] = {}
        self.serial: bytes | None = None

    def on_notify(self, _sender: Any, data: bytearray) -> None:
        packet = decrypt(bytes(data))
        if len(packet) < 5 or packet[0] != 0x51:
            return
        if packet[2] == INST_SERIAL:
            idx, total = packet[3], packet[4]
            self.serial_chunks[idx] = packet[5:-1]
            if len(self.serial_chunks) >= total:
                self.serial = b"".join(self.serial_chunks[i] for i in sorted(self.serial_chunks))
                self.event.set()
        else:
            self.last = packet
            self.event.set()

    async def write(self, packet: bytes) -> None:
        await self.client.write_gatt_char(WRITE_CHAR_UUID, packet, response=True)

    async def write_validated(
        self, packet: bytes, expected_inst: int, timeout: float = 10.0
    ) -> None:
        await self.write(packet)
        await asyncio.wait_for(self.event.wait(), timeout)
        if self.last is None or not validate_response(self.last, expected_inst):
            raise RuntimeError(f"BLE response invalid for instruction {expected_inst}")
        self.event.clear()
        self.last = None

    async def send_chunked(
        self, instruction: int, data: bytes, response_timeout: float = 10.0
    ) -> None:
        total = max(1, (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE)
        for i in range(total):
            chunk = data[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE]
            packet = build_packet(instruction, bytes([i + 1, total]) + chunk)
            await self.write(packet)
            await asyncio.sleep(0.1)
        await asyncio.wait_for(self.event.wait(), response_timeout)
        if self.last is None or not validate_response(self.last, instruction):
            raise RuntimeError(f"BLE response invalid for chunked instruction {instruction}")
        self.event.clear()
        self.last = None


def _is_target(device: Any, address: str | None, name: str | None) -> bool:
    """Match a live advertisement. Linux often shows a different MAC than Windows."""
    if name and getattr(device, "name", None) == name:
        return True
    if address and getattr(device, "address", "").upper() == address.upper():
        return True
    return False


async def _connect_with_retry(
    address: str,
    timeout: float,
    attempts: int,
    on_progress: Callable[[str], None],
    name: str | None = None,
    already_connected: bool = False,
) -> Any:
    """Scan until the dog is visible, then connect to that live Bleak device."""
    if already_connected:
        return await _connect_already(address, timeout, on_progress)
    last_exc: BaseException | None = None
    for i in range(attempts):
        try:
            return await _connect_once(address, name, timeout, on_progress)
        except Exception as e:
            last_exc = e
            on_progress(f"connect attempt {i + 1}/{attempts} failed: {type(e).__name__}: {e!r}")
            if i + 1 < attempts:
                await asyncio.sleep(1.0)
    assert last_exc is not None
    raise last_exc


async def provision_wifi(
    address: str,
    ssid: str,
    password: str,
    country_code: str = "US",
    *,
    timeout: float = 30.0,
    connect_retries: int = 3,
    on_progress: Callable[[str], None] | None = None,
    name: str | None = None,
    already_connected: bool = False,
) -> str | None:
    """Provision a Unitree robot's wifi over BLE. Returns the serial number on success.

    Retries the BLE connection step up to `connect_retries` times. Once connected,
    handshake/SSID/password/country failures are not retried — those indicate a
    protocol-level problem (or partial state on the robot) where blind retry is
    counterproductive.
    """
    progress = on_progress or (lambda _msg: None)

    client = await _connect_with_retry(
        address,
        timeout,
        connect_retries,
        progress,
        name=name,
        already_connected=already_connected,
    )
    try:
        session = _Session(client)
        try:
            await client.start_notify(NOTIFY_CHAR_UUID, session.on_notify)
        except Exception:
            # Some firmware versions only expose the raw GATT handle.
            await client.start_notify(13, session.on_notify)  # type: ignore[arg-type]

        progress("handshake")
        await session.write_validated(
            build_packet(INST_HANDSHAKE, bytes([0, 0]) + HANDSHAKE_CONTENT),
            INST_HANDSHAKE,
        )

        progress("read serial")
        await session.write(build_packet(INST_SERIAL, bytes([0])))
        try:
            await asyncio.wait_for(session.event.wait(), 2.0)
        except asyncio.TimeoutError:
            pass
        session.event.clear()

        progress("init STA mode")
        await session.write_validated(build_packet(INST_INIT_STA, bytes([2])), INST_INIT_STA)

        progress(f"set SSID: {ssid}")
        await session.send_chunked(INST_SSID, ssid.encode("utf-8"))

        progress("set password")
        await session.send_chunked(INST_PASSWORD, password.encode("utf-8"), response_timeout=5.0)

        progress(f"set country: {country_code}")
        await session.write_validated(
            build_packet(INST_COUNTRY, bytes([1]) + country_code.encode("utf-8") + b"\x00"),
            INST_COUNTRY,
        )
    finally:
        await client.disconnect()

    if session.serial:
        return session.serial.decode("utf-8", errors="replace").rstrip("\x00")
    return None


async def retry(
    fn: Callable[[], Awaitable[Any]],
    attempts: int = 3,
    delay: float = 1.0,
    on_error: Callable[[int, BaseException], None] | None = None,
) -> Any:
    """Retry an awaitable a few times. Re-raises the final exception."""
    last_exc: BaseException | None = None
    for i in range(attempts):
        try:
            return await fn()
        except Exception as e:
            last_exc = e
            if on_error:
                on_error(i + 1, e)
            if i + 1 < attempts:
                await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc
