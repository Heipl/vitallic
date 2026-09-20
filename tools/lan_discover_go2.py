"""Multicast-discover a Go2 on the current LAN. Stdlib only."""
import json
import socket
import struct
import sys

RECV_PORT = 10134
MULTICAST_PORT = 10131
GROUP = "231.1.1.1"
SN = "B42D1000Q5SD7AGE"


def main() -> int:
    queries = [
        json.dumps({"name": "unitree_dapengche"}).encode(),
        json.dumps({"name": "unitree_dapengche", "sn": SN}).encode(),
    ]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", RECV_PORT))
    mreq = struct.pack("4sl", socket.inet_aton(GROUP), socket.INADDR_ANY)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError as exc:
        print(f"join_failed {exc}")
    sock.settimeout(0.2)
    for _ in range(3):
        for q in queries:
            try:
                sock.sendto(q, (GROUP, MULTICAST_PORT))
            except OSError as exc:
                print(f"send_failed {exc}")
    found = {}
    sock.settimeout(4.0)
    try:
        while True:
            data, addr = sock.recvfrom(1024)
            try:
                msg = json.loads(data.decode())
            except Exception:
                continue
            sn = msg.get("sn")
            if not sn:
                continue
            ip = msg.get("ip", addr[0])
            found[sn] = ip
            print(f"FOUND {sn} {ip} from {addr}")
    except socket.timeout:
        pass
    sock.close()
    print(f"count={len(found)} {found}")
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
