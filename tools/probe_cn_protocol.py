"""probe_cn_protocol.py - find out what framing this Go2 actually answers.

WHAT THIS IS NOT
It is not a client for Chinese-market firmware. The blocker is the AES key:

    _AES_KEY = df98b715d5c6ed2b25817b6f2554124a
    _AES_IV  = 2841ae97419c2973296a0d4bdfe19a4f

Those constants were reverse-engineered from international firmware, and both
tools/go2_ble.py and dimOS's own dimos/robot/unitree/go2/cli/ble.py hardcode the
SAME pair - they are one implementation, not two. If this robot's firmware uses a
different key, every packet we send is noise to it and it will never reply. A
128-bit key cannot be guessed, so no client can be written until it is known.

WHAT THIS IS
A systematic probe. The dog currently answers NOTHING: correct service, correct
characteristics, subscribe succeeds, the write to ffe2 succeeds, silence. This
sends the same handshake under several different framings and logs every byte
that comes back on ffe1, without assuming any of them decrypt. If ANY variant
draws a response, that identifies the protocol family and is the one piece of
information a real client would need.

If nothing answers any variant, that is also worth knowing: it means the problem
is not framing, and the remaining explanations are the key itself or a BlueZ
transport issue that a macOS/CoreBluetooth host would not have.

    python3 tools/probe_cn_protocol.py
    python3 tools/probe_cn_protocol.py --dwell 4     # wait longer per variant

Safe: sends handshakes only. Never writes wifi credentials, never pairs.
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


def _aes(key: bytes, iv: bytes, mode_name: str):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    mode = {"CFB": modes.CFB, "OFB": modes.OFB, "CBC": modes.CBC}[mode_name](iv)
    return Cipher(algorithms.AES(key), mode)


def _enc(data: bytes, key: bytes, iv: bytes, mode_name: str) -> bytes:
    # ECB and CBC are block modes and need the input padded to 16 bytes.
    # CFB and OFB are stream modes and accept any length.
    if mode_name in ("ECB", "CBC"):
        data = data + b"\x00" * ((-len(data)) % 16)
    if mode_name == "ECB":
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        e = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
        return e.update(data) + e.finalize()
    e = _aes(key, iv, mode_name).encryptor()
    return e.update(data) + e.finalize()


def build_variants(ble):
    """The same handshake body under different framings."""
    payload = bytes([0, 0]) + ble.HANDSHAKE_CONTENT
    body = bytes([0x52, len(payload) + 4, ble.INST_HANDSHAKE]) + payload
    body = body + bytes([(-sum(body)) & 0xFF])
    k, iv = ble._AES_KEY, ble._AES_IV
    zero_iv = b"\x00" * 16

    out = [
        ("stock: AES-CFB, known key/IV", ble.encrypt(body)),
        ("PLAINTEXT, no encryption", body),
        ("AES-CFB, zero IV", _enc(body, k, zero_iv, "CFB")),
        ("AES-OFB, known key/IV", _enc(body, k, iv, "OFB")),
        ("AES-CBC, known key/IV", _enc(body, k, iv, "CBC")),
        ("AES-ECB, known key", _enc(body, k, iv, "ECB")),
        ("PLAINTEXT with 0x51 prefix", bytes([0x51]) + body[1:]),
        ("raw b'unitree'", ble.HANDSHAKE_CONTENT),
    ]
    return body, out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mac", default=DEFAULT_MAC)
    ap.add_argument("--name", default=DEFAULT_NAME)
    ap.add_argument("--dwell", type=float, default=3.0, help="seconds to wait per variant")
    ap.add_argument("--timeout", type=float, default=30.0)
    a = ap.parse_args()

    from bleak import BleakClient, BleakScanner

    ble = load_ble()
    plain, variants = build_variants(ble)
    print(f"handshake body (plaintext): {plain.hex()}")
    print(f"{len(variants)} framings to try, {a.dwell}s each\n")

    dev = await BleakScanner.find_device_by_filter(
        lambda d, _adv: (d.name == a.name) or (d.address.upper() == a.mac.upper()),
        timeout=20.0,
    )
    if dev is None:
        print("NOT FOUND - run tools/ble_scan_go2.py first")
        return 1
    print(f"found {dev.name} {dev.address}")

    async with BleakClient(dev, timeout=a.timeout) as client:
        print(f"connected={client.is_connected}\n")
        heard: list[tuple[str, bytes]] = []
        current = {"label": "(before any write)"}

        def on_notify(_sender, data: bytearray):
            raw = bytes(data)
            heard.append((current["label"], raw))
            print(f"    <<< RAW  {raw.hex()}")
            try:
                dec = ble.decrypt(raw)
                printable = dec.hex()
                note = " (starts 0x51 - valid stock reply!)" if dec[:1] == b"\x51" else ""
                print(f"    <<< dec  {printable}{note}")
            except Exception:
                pass

        try:
            await client.start_notify(ble.NOTIFY_CHAR_UUID, on_notify)
            print(f"subscribed to {ble.NOTIFY_CHAR_UUID}\n")
        except Exception as exc:
            print(f"start_notify FAILED: {type(exc).__name__}: {exc}")
            return 1

        for label, packet in variants:
            current["label"] = label
            before = len(heard)
            print(f"--> {label}")
            print(f"    tx {packet.hex()}")
            try:
                await client.write_gatt_char(ble.WRITE_CHAR_UUID, packet, response=True)
            except Exception as exc:
                print(f"    write FAILED: {type(exc).__name__}: {exc}")
                continue
            await asyncio.sleep(a.dwell)
            if len(heard) == before:
                print("    (silence)")
            print()

        await client.disconnect()

    print("=" * 62)
    if heard:
        print("THE DOG REPLIED. Framings that drew a response:")
        for label in dict.fromkeys(l for l, _ in heard):
            n = sum(1 for x, _ in heard if x == label)
            print(f"  - {label}  ({n} packet(s))")
        print("\nThat identifies the protocol family. Send this output to whoever")
        print("maintains the provisioning tool - it is the missing piece.")
    else:
        print("Silence on every framing.")
        print("So the problem is NOT the packet format. What is left:")
        print("  1. a different AES key in this firmware - unguessable, and the")
        print("     reason no client can be written for it from here;")
        print("  2. a BlueZ transport issue that CoreBluetooth does not have,")
        print("     which is consistent with the other team succeeding on a Mac.")
        print("\nBoth point the same way: provision it once from the Mac, then")
        print("the dog is on your network permanently and BLE never matters again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
