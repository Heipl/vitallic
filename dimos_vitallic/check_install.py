"""Offline check that dimOS can find and build the vitallic blueprint.

Nothing here needs a dog or a running dimOS instance: it only proves the entry
point resolves, the module imports, and the blueprint composes. Run it after
installing and before taking the dog out.

    /root/dimensional-applications/.venv/bin/python check_install.py
"""

import sys


def check_module() -> bool:
    """The parts that do not depend on the Go2 connection stack."""
    from vitallic_dimos.precise_move import CMD_VEL_TOPIC, PreciseMove, PreciseMoveConfig

    cfg = PreciseMoveConfig()
    print(f"  cmd_vel remapped to: {CMD_VEL_TOPIC!r}  "
          "(confirm against `dimos spy` on the live robot)")
    print(f"  control rate: {cfg.rate_hz} Hz, deadman floor 5 Hz "
          "(UnitreeConnection.cmd_vel_timeout = 0.2 s)")
    if cfg.rate_hz <= 5.0:
        print("  FAIL: rate_hz is at or below the deadman floor; the dog would stutter.")
        return False
    if cfg.min_speed <= 0 or cfg.min_speed > cfg.max_speed:
        print("  FAIL: min_speed must be positive and below max_speed.")
        return False
    if not hasattr(PreciseMove, "precise_move"):
        print("  FAIL: precise_move is not exposed on the module.")
        return False
    print("  precise_move skill present")
    return True


def main() -> int:
    from dimos.robot.external_blueprints import (
        list_external_blueprint_names,
        resolve_external_blueprint_by_name,
    )

    ok = True

    print("1. entry point registered")
    names = list_external_blueprint_names()
    if "vitallic-dimos.scan" not in names:
        print(f"  FAIL: not in {names}. Install into the dimOS venv:")
        print("    VIRTUAL_ENV=/root/dimensional-applications/.venv uv pip install -e .")
        return 1
    print(f"  found: {names}")

    print("2. skill module imports")
    try:
        ok &= check_module()
    except Exception as exc:
        print(f"  FAIL: {type(exc).__name__}: {exc}")
        ok = False

    print("3. blueprint composes (needs the Go2 connection stack)")
    try:
        blueprint = resolve_external_blueprint_by_name("vitallic-dimos.scan")
        print(f"  loaded: {type(blueprint).__name__}")
    except Exception as exc:
        if "unitree_webrtc_connect" in str(exc):
            print("  FAIL: the dimos 'unitree' extra is not installed, so no Go2")
            print("        blueprint can load -- stock unitree-go2-agentic included.")
            print("        Fix with:")
            print("          VIRTUAL_ENV=/root/dimensional-applications/.venv \\")
            print('            uv pip install "dimos[unitree]"')
        else:
            print(f"  FAIL: {type(exc).__name__}: {exc}")
        ok = False

    if not ok:
        return 1

    print("\nOK. Start it with:")
    print("  dimos run vitallic-dimos.scan --robot-ip <DOG_IP>")
    print("then confirm the skill is live with:")
    print("  dimos mcp list-tools | grep precise_move")
    return 0


if __name__ == "__main__":
    sys.exit(main())
