#!/usr/bin/env bash
# find_dog.sh - by what route, if any, can this laptop reach the Go2 right now?
#
#   bash tools/find_dog.sh
#
# BLE provisioning exists only to put the dog on YOUR wifi. If any route below
# works, you do not need BLE at all. Read-only; changes nothing.

SN="${GO2_SN:-B42D1000Q5SD7AGE}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ok(){   printf '  \033[32mOK\033[0m   %s\n' "$*"; }
bad(){  printf '  \033[31mno\033[0m   %s\n' "$*"; }
warn(){ printf '  \033[33m??\033[0m   %s\n' "$*"; }
found_any=0

echo "Looking for Go2 $SN by every route"
echo

echo "A. The dog's OWN wifi access point"
echo "   (unprovisioned Go2 broadcasts its own SSID; join it and BLE is unnecessary)"
if command -v nmcli >/dev/null; then
  nmcli -t -f SSID,SIGNAL dev wifi list --rescan yes 2>/dev/null \
    | grep -iE "unitree|go2|${SN}" | sed 's/^/       /' > /tmp/_dogap.$$ || true
  if [ -s /tmp/_dogap.$$ ]; then
    ok "found a Unitree access point:"; cat /tmp/_dogap.$$
    echo "       -> nmcli dev wifi connect '<that SSID>'   then re-run this script"
    found_any=1
  else
    bad "no Unitree/Go2 SSID in range"
  fi
  rm -f /tmp/_dogap.$$
else
  warn "nmcli absent; scan wifi manually for a Unitree/Go2 SSID"
fi

echo
echo "B. Unitree multicast discovery on the current LAN"
if [ -f "$HERE/lan_discover_go2.py" ]; then
  out=$(timeout 25 python3 "$HERE/lan_discover_go2.py" 2>&1)
  if echo "$out" | grep -q "^FOUND"; then
    ok "dog answered multicast:"; echo "$out" | grep "^FOUND" | sed 's/^/       /'
    found_any=1
  else
    bad "no multicast answer on this LAN"
  fi
else
  warn "lan_discover_go2.py missing"
fi

echo
echo "C. Wired / known static addresses"
echo "   (Go2's internal network is 192.168.123.x; the onboard computer answers there)"
for ip in 192.168.123.161 192.168.123.18 192.168.12.1; do
  if ping -c1 -W1 "$ip" >/dev/null 2>&1; then
    ok "$ip responds to ping"
    found_any=1
  else
    bad "$ip silent"
  fi
done
echo "   If you have an ethernet cable, this is the most reliable route of all:"
echo "     sudo ip addr add 192.168.123.222/24 dev <eth-iface>"
echo "     ping 192.168.123.161"

echo
echo "D. Neighbours currently on your subnets"
ip -4 neigh show 2>/dev/null | grep -v FAILED | sed 's/^/       /' | head -15
echo

if [ "$found_any" = 1 ]; then
  echo "=> The dog is reachable. Skip BLE entirely and go straight to:"
  echo "     dimos run patsiuk-dimos.scan --robot-ip <the address above>"
else
  echo "=> No route reached the dog. That points at the dog itself, not your laptop:"
  echo "   1. Confirm it is actually ON and finished booting (lights up, motors audible,"
  echo "      it should be standing or in damping - not dark and silent)."
  echo "   2. Power-cycle it, then run tools/linux_ble_doctor.sh within ~2 min of boot."
  echo "      A Go2 that already holds wifi credentials may stop advertising BLE once"
  echo "      it has joined a network - in which case route B finds it and BLE never will."
  echo "   3. If it previously joined a network that is not present here, it may be"
  echo "      sitting there retrying. Bring up that SSID (phone hotspot with the same"
  echo "      name/password) and re-run route B."
fi
