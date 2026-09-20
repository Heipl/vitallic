#!/usr/bin/env bash
# linux_ble_doctor.sh - why "bluetoothctl scan missed Go2_60658" happens, on native Linux.
#
#   bash tools/linux_ble_doctor.sh
#
# Read-only except for one optional cache removal, which it asks about first.

MAC="${GO2_MAC:-94:BA:06:F6:D6:87}"
NAME="${GO2_NAME:-Go2_60658}"
ok(){ printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad(){ printf '  \033[31mFAIL\033[0m %s\n' "$*"; }
warn(){ printf '  \033[33mWARN\033[0m %s\n' "$*"; }

echo "Go2 BLE doctor - target $NAME ($MAC)"
echo

echo "1. Bluetooth stack"
if ! command -v bluetoothctl >/dev/null; then bad "bluetoothctl not installed -> sudo apt install bluez"; exit 1; fi
ok "bluetoothctl present"
systemctl is-active --quiet bluetooth && ok "bluetooth.service active" || bad "bluetooth.service dead -> sudo systemctl start bluetooth"
if command -v rfkill >/dev/null; then
  if rfkill list bluetooth | grep -qi "Soft blocked: yes"; then bad "BT soft-blocked -> sudo rfkill unblock bluetooth"; else ok "BT not soft-blocked"; fi
  if rfkill list bluetooth | grep -qi "Hard blocked: yes"; then bad "BT HARD-blocked -> laptop wireless switch/Fn key is off"; fi
fi
if bluetoothctl show 2>/dev/null | grep -q "Powered: yes"; then ok "adapter powered"; else bad "adapter off -> bluetoothctl power on"; fi

echo
echo "2. Is the dog stuck in BlueZ's cache?"
echo "   (cached device = 'scan on' emits CHG/RSSI lines with NO name in them,"
echo "    and go2_ble.py only matches a line containing the literal '$NAME')"
if bluetoothctl devices 2>/dev/null | grep -qi "$MAC"; then
  warn "$MAC IS already in the cache - this is the #1 cause of your error"
  bluetoothctl info "$MAC" 2>/dev/null | sed -n '1,12p' | sed 's/^/       /'
  echo
  read -r -p "   Remove it from the cache now? [y/N] " a
  if [ "$a" = y ] || [ "$a" = Y ]; then
    bluetoothctl remove "$MAC" >/dev/null 2>&1 && ok "removed - the next scan will re-emit a [NEW] line with the name"
  else
    echo "       skipped; use the --already-connected path below instead"
  fi
else
  ok "not cached - a fresh [NEW] line should carry the name"
fi

echo
echo "3. Radio contention (BLE and 2.4 GHz Wi-Fi share one antenna on most laptops)"
if command -v nmcli >/dev/null; then
  wifi=$(nmcli -t -f WIFI g 2>/dev/null)
  if [ "$wifi" = enabled ]; then
    band=$(nmcli -t -f IN-USE,FREQ dev wifi 2>/dev/null | grep '^\*' | cut -d: -f2)
    if [ -n "$band" ] && [ "$band" -lt 3000 ] 2>/dev/null; then
      bad "Wi-Fi is ON and associated at ${band} MHz (2.4 GHz) - this starves BLE."
      echo "       -> nmcli radio wifi off      (re-enable after provisioning)"
    else
      warn "Wi-Fi is on${band:+ at ${band} MHz}. If the scan still misses, turn it off."
    fi
  else
    ok "Wi-Fi radio off - BLE has the antenna"
  fi
fi

echo
echo "4. Is the dog actually advertising right now? (10 s passive scan)"
echo "   If this finds nothing, the dog is NOT advertising - BLE is 1:1, so the"
echo "   Unitree phone app holding a connection will silence it. Force-quit the app."
timeout 15 bluetoothctl --timeout 10 scan on 2>/dev/null \
  | grep -iE "Device .*($NAME|$MAC)" | sort -u | sed 's/^/       /' \
  || true
echo
if bluetoothctl devices 2>/dev/null | grep -qi "$MAC"; then
  ok "$MAC seen during the scan - the dog is alive and advertising"
  echo
  echo "NEXT: skip the name-matching scan entirely (you already know the MAC):"
  echo "  bluetoothctl -- connect $MAC"
  echo "  python3 tools/linux_go2_hotspot.py --already-connected --mac $MAC \\"
  echo "      --ssid '<SSID>' --password '<PASS>'"
else
  bad "$MAC never appeared. The dog is not advertising."
  echo "       - power-cycle the dog and retry within ~2 min of boot"
  echo "       - force-quit the Unitree app on every phone nearby"
  echo "       - confirm you are within a couple of metres"
fi
