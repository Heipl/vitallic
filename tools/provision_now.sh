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
SSID="${1:-}"; PASS="${2:-}"
ok(){ printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad(){ printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33mWARN\033[0m %s\n' "$*"; }

if [ -z "$SSID" ] || [ -z "$PASS" ]; then
  echo "usage: bash tools/provision_now.sh '<SSID>' '<PASSWORD>'"; exit 2
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
if command -v nmcli >/dev/null && [ "$(nmcli -t -f WIFI g 2>/dev/null)" = enabled ]; then
  WIFI_WAS=on
  nmcli radio wifi off && ok "laptop wifi off (the DOG joins the hotspot, not this laptop)"
else
  ok "laptop wifi already off"
fi

echo
echo "3. Is the dog advertising?"
timeout 14 bluetoothctl --timeout 10 scan on >/dev/null 2>&1
if bluetoothctl devices 2>/dev/null | grep -qi "$MAC"; then
  ok "$NAME is advertising"
else
  bad "$NAME not seen. Power-cycle the dog and re-run within 2 min of boot."
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
echo "5. Rejoining wifi and looking for the dog"
if command -v nmcli >/dev/null; then
  nmcli radio wifi on; sleep 3
  nmcli dev wifi connect "$SSID" password "$PASS" 2>&1 | sed 's/^/       /' || \
    warn "join '$SSID' manually, then re-run lan_discover_go2.py"
fi
echo "   waiting 25s for the dog to associate..."
sleep 25
python3 "$HERE/lan_discover_go2.py" && {
  echo
  ok "Dog is on the LAN. Next:"
  echo "     dimos run patsiuk-dimos.scan --robot-ip <the ip above>"
  echo "     dimos spy        # confirm telemetry is actually flowing"
} || {
  echo
  bad "not on the LAN yet. Give it another 30s and re-run:"
  echo "     python3 $HERE/lan_discover_go2.py"
  echo "   Still nothing => the hotspot is almost certainly 5 GHz-only."
}
