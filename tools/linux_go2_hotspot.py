#!/usr/bin/env python3
"""Put Go2_60658 on the phone hotspot over BLE. Native Linux + BlueZ.

Copy this file and go2_ble.py onto the Linux laptop (same folder):

    python3 -m venv .venv
    .venv/bin/pip install bleak cryptography
    .venv/bin/python linux_go2_hotspot.py --ssid 'Redmi Note 13 Pro 5G' --password 'YOUR_PASSWORD'
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import sys
from pathlib import Path

DEFAULT_MAC = "94:BA:06:F6:D6:87"
DEFAULT_NAME = "Go2_60658"


def load_ble(path: Path):
    spec = importlib.util.spec_from_file_location("go2_ble", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


async def run(args: argparse.Namespace) -> int:
    ble = load_ble(Path(args.ble_py).expanduser().resolve())

    def on_dev(d) -> None:
        print(f"  BLE {d.name} {d.address} serial={d.serial}")

    address = args.mac
    if args.scan:
        print(f"Scanning {args.timeout:.0f}s ...")
        devices = await ble.find_robots(timeout=args.timeout, on_device=on_dev)
        match = next(
            (d for d in devices if d.name == DEFAULT_NAME or d.address.upper() == DEFAULT_MAC.upper()),
            None,
        )
        if match is None:
            print("No Go2_60658 found. Dog on? Within a couple metres?", file=sys.stderr)
            return 1
        address = match.address
        print(f"using {match.name} {address}")
    else:
        print(f"using --mac {address}")

    serial = await ble.retry(
        lambda: ble.provision_wifi(
            address, args.ssid, args.password, args.country, on_progress=print
        ),
        attempts=args.retries,
        on_error=lambda i, e: print(f"  attempt {i} failed: {e}", file=sys.stderr),
    )
    print(f"OK provisioned serial={serial}")
    print("Wait ~20s, then look for a new 10.129.8.x neighbor and ping it.")
    return 0


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser()
    ap.add_argument("--ssid", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--mac", default=DEFAULT_MAC)
    ap.add_argument("--scan", action="store_true", help="scan instead of using --mac")
    ap.add_argument("--country", default="US")
    ap.add_argument("--timeout", type=float, default=12.0)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--ble-py", default=str(here / "go2_ble.py"))
    args = ap.parse_args()
    try:
        return asyncio.run(run(args))
    except Exception as exc:
        print(f"FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
