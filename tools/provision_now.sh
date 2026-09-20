#!/usr/bin/env bash
# provision_now.sh - put the Go2 on a hotspot over BLE, without the app.
#
#   bash tools/provision_now.sh '<SSID>' '<PASSWORD>'
#
# Use when the app is unusable (robot bound to another account) and the dog has
# no wifi credentials. Runs the steps in the order that avoids the failures hit
# earlier: stale bonds, a held peripheral slot, and radio contention.

set -u
MAC="${GO2_MAC:-94:BA:06:F6:D6:87}"
NAME="${GO2_NAME:-Go2_60658}"
HERE="$(cd "$(dirname "$0")" && pwd)"
TETHER=0
if [ "${1:-}" = "--tether" ]; then TETHER=1; shift; fi
SSID="${1:-}"; PASS="${2:-}"
ok(){ printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad(){ printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33mWARN\033[0m %s\n' "$*"; }

if [ -z "$SSID" ] || [ -z "$PASS" ]; then
  echo "usage: bash tools/provision_now.sh [--tether] '<SSID>' '<PASSWORD>'"
  echo "  --tether : laptop reaches the phone's network over USB tethering, so"
  echo "             this script never touches wifi. Phone needs hotspot ON (2.4 GHz)"
  echo "             AND USB tethering ON. Frees the wifi radio entirely for BLE."
  exit 2
fi

cat <<'NOTE'
BEFORE YOU START - two things that silently break this:

  1. The hotspot MUST be 2.4 GHz. The Go2's wifi is 2.4 GHz only; a 5 GHz-only
     hotspot will accept the credentials and the dog will never appear.
     On Android: Hotspot settings -> AP Band -> 2.4 GHz.
  2. Nothing else may hold the dog's BLE slot. BLE is 1:1. Force-quit the
     Unitree app on every phone, and turn Bluetooth off on any other computer.

NOTE
read -r -p "Both done? [y/N] " a
[ "$a" = y ] || [ "$a" = Y ] || { echo "stopping"; exit 1; }

echo
echo "1. Clearing stale BLE state from earlier attempts"
pkill -f bluetoothctl >/dev/null 2>&1 && warn "killed a leftover bluetoothctl" || ok "no leftover bluetoothctl"
pkill -f linux_go2_hotspot >/dev/null 2>&1
bluetoothctl disconnect "$MAC" >/dev/null 2>&1
if bluetoothctl devices 2>/dev/null | grep -qi "$MAC"; then
  bluetoothctl remove "$MAC" >/dev/null 2>&1 && ok "removed stale bond/cache entry"
else
  ok "no stale bond"
fi
sudo systemctl restart bluetooth 2>/dev/null && sleep 2 && ok "bluetooth restarted" \
  || warn "could not restart bluetooth (no sudo?) - continuing"
bluetoothctl power on >/dev/null 2>&1

echo
echo "2. Freeing the antenna (BLE and 2.4 GHz wifi share it)"
WIFI_WAS=off
if [ "$TETHER" = 1 ]; then
  ok "tether mode: leaving wifi alone, the laptop is on the phone over USB"
  if ip -4 addr show 2>/dev/null | grep -qE 'usb|rndis|enp.*u'; then
    ok "USB tether interface is up"
  else
    warn "no obvious USB tether interface - is USB tethering enabled on the phone?"
    ip -4 -br addr show 2>/dev/null | sed 's/^/       /'
  fi
elif command -v nmcli >/dev/null && [ "$(nmcli -t -f WIFI g 2>/dev/null)" = enabled ]; then
  WIFI_WAS=on
  nmcli radio wifi off && ok "laptop wifi off (the DOG joins the hotspot, not this laptop)"
else
  ok "laptop wifi already off"
fi

echo
echo "3. Is the dog advertising?"
# Use the bleak scanner, not `bluetoothctl scan on`: bluetoothctl needs an
# explicit `transport le` to scan LE at all, and matching a fixed MAC gives a
# false negative if the dog advertises with a rotating private address.
# ble_scan_go2.py matches on the Go2_/G1_/B2_ name prefix instead.
SEEN=""
if python3 -c "import bleak" 2>/dev/null; then
  OUT="$(timeout 25 python3 "$HERE/ble_scan_go2.py" 2>&1)"
  echo "$OUT" | sed 's/^/       /'
  SEEN="$(echo "$OUT" | grep -iE "^BLE .*(${NAME}|Go2_)" | head -1)"
else
  warn "bleak not installed - falling back to bluetoothctl with LE transport"
  warn "install it for a reliable scan:  pip install bleak"
  OUT="$(printf 'menu scan
transport le
back
scan on
'         | timeout 20 bluetoothctl 2>&1 | grep -iE "Device .*(${NAME}|${MAC})" | head -5)"
  echo "$OUT" | sed 's/^/       /'
  SEEN="$OUT"
fi

if [ -n "$SEEN" ]; then
  ok "$NAME is advertising"
  ADDR="$(echo "$SEEN" | grep -oiE '[0-9A-F]{2}(:[0-9A-F]{2}){5}' | head -1)"
  if [ -n "$ADDR" ] && [ "${ADDR^^}" != "${MAC^^}" ]; then
    warn "advertised address $ADDR differs from $MAC (private/rotating address)"
    warn "using $ADDR for provisioning"
    MAC="$ADDR"
  fi
else
  bad "$NAME not seen by an LE scan."
  echo "       - power-cycle the dog, then re-run within 2 min of boot"
  echo "       - force-quit the Unitree app on EVERY phone (BLE is 1:1)"
  echo "       - turn Bluetooth off on the Windows PC"
  echo "       - stand within a couple of metres"
  [ "$WIFI_WAS" = on ] && nmcli radio wifi on
  exit 1
fi

echo
echo "4. Provisioning onto '$SSID'"
python3 "$HERE/linux_go2_hotspot.py" --ssid "$SSID" --password "$PASS" --mac "$MAC"
rc=$?
if [ $rc -ne 0 ]; then
  echo
  bad "provisioning failed (exit $rc)"
  echo "   Fallback - connect by MAC first, then attach:"
  echo "     bluetoothctl -- connect $MAC"
  echo "     python3 $HERE/linux_go2_hotspot.py --already-connected --mac $MAC \\"
  echo "         --ssid '$SSID' --password '$PASS'"
  [ "$WIFI_WAS" = on ] && nmcli radio wifi on
  exit $rc
fi

echo
echo "5. Looking for the dog on the network"
if [ "$TETHER" = 1 ]; then
  ok "tether mode: already on the phone's network, not touching wifi"
elif command -v nmcli >/dev/null; then
  nmcli radio wifi on; sleep 3
  nmcli dev wifi connect "$SSID" password "$PASS" 2>&1 | sed 's/^/       /' ||     warn "join '$SSID' manually, then re-run lan_discover_go2.py"
fi
echo "   waiting 25s for the dog to associate..."
sleep 25
python3 "$HERE/lan_discover_go2.py" && {
  echo
  ok "Dog is on the LAN. Next:"
  echo "     dimos run vitallic-dimos.scan --robot-ip <the ip above>"
  echo "     dimos spy        # confirm telemetry is actually flowing"
} || {
  echo
  bad "not on the LAN yet. Give it another 30s and re-run:"
  echo "     python3 $HERE/lan_discover_go2.py"
  echo "   Still nothing => the hotspot is almost certainly 5 GHz-only."
}
