#!/usr/bin/env bash
# ble_pair_with_agent.sh - retry pairing with a real BlueZ agent registered.
#
#   bash tools/ble_pair_with_agent.sh
#
# WHY: bleak does not register a pairing agent. BlueZ answers
# org.bluez.Error.AuthenticationFailed when nothing can respond to the pairing
# request, which looks identical to the peripheral refusing the bond.
# go2_ble.py's bluetoothctl path registers one (`agent on` / `default-agent`);
# the bleak path does not. This keeps a NoInputNoOutput agent alive for the
# whole attempt, which is what a Just Works bond needs.
#
# If pairing STILL fails with a live agent, the dog is refusing the bond itself
# and BLE provisioning is finished as an avenue.

set -u
MAC="${GO2_MAC:-94:BA:06:F6:D6:87}"
HERE="$(cd "$(dirname "$0")" && pwd)"
FIFO="$(mktemp -u /tmp/btagent.XXXXXX)"
BTPID=""

cleanup() {
  [ -n "$BTPID" ] && kill "$BTPID" 2>/dev/null
  exec 3>&- 2>/dev/null || true
  rm -f "$FIFO"
}
trap cleanup EXIT

echo "1. Clearing any stale bond (a mismatched one also yields AuthenticationFailed)"
bluetoothctl disconnect "$MAC" >/dev/null 2>&1
bluetoothctl remove "$MAC" >/dev/null 2>&1 && echo "   removed $MAC" || echo "   nothing to remove"

echo
echo "2. Starting a persistent NoInputNoOutput agent"
mkfifo "$FIFO"
bluetoothctl < "$FIFO" > /tmp/btagent.log 2>&1 &
BTPID=$!
exec 3> "$FIFO"
printf 'power on\nagent NoInputNoOutput\ndefault-agent\n' >&3
sleep 2
if grep -qiE "agent registered|default agent" /tmp/btagent.log; then
  echo "   agent registered (pid $BTPID)"
else
  echo "   WARNING: could not confirm registration; see /tmp/btagent.log"
  tail -5 /tmp/btagent.log | sed 's/^/     /'
fi

echo
echo "3. Pair + handshake with the agent alive"
python3 "$HERE/ble_dump_gatt.py" --pair --handshake --mac "$MAC"
rc=$?

echo
echo "=== interpretation ==="
if [ $rc -ne 0 ]; then
  echo "  tool exited $rc - see output above"
fi
cat <<'TXT'
  pair succeeded + NOTIFY lines   -> you are through; run provision_now.sh again
  pair succeeded + still silent   -> the bond was never the issue; the dog is
                                     ignoring the provisioning protocol itself
  pair still AuthenticationFailed -> the dog refuses to bond with an unknown
                                     central. BLE provisioning is done; the
                                     robot needs to be unbound by its owner.
TXT
