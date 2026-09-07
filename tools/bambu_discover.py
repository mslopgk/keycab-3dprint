"""Find Bambu printers on the LAN by listening for their SSDP announcements.

    DISCOVER_SECONDS   how long to listen (default 25)

Printers announce themselves on UDP 2021 and 1990 every few seconds, carrying
their serial and current address. That is the only reliable way to find one
again after DHCP moves it: they do not answer ICMP, so a failed ping proves
nothing, and a hard-coded IP in a script silently stops working.
"""

import os
import re
import socket
import time

SECONDS = float(os.environ.get("DISCOVER_SECONDS", 25))
PORTS = (2021, 1990)

socks = []
for port in PORTS:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("", port))
    except OSError as exc:
        print(f"  cannot bind UDP {port}: {exc}")
        s.close()
        continue
    s.settimeout(1.0)
    socks.append((port, s))

if not socks:
    raise SystemExit("could not bind any SSDP port")

print(f"listening on UDP {[p for p, _ in socks]} for {SECONDS:.0f}s ...")

found = {}
deadline = time.time() + SECONDS
while time.time() < deadline:
    for port, s in socks:
        try:
            data, addr = s.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            continue
        text = data.decode("utf-8", errors="replace")
        if "bambu" not in text.lower() and "USN" not in text:
            continue
        usn = re.search(r"USN:\s*(\S+)", text)
        name = re.search(r"DevName\.bambu\.com:\s*(.+)", text)
        model = re.search(r"DevModel\.bambu\.com:\s*(\S+)", text)
        key = usn.group(1) if usn else addr[0]
        if key not in found:
            found[key] = {
                "ip": addr[0],
                "serial": usn.group(1) if usn else "?",
                "name": name.group(1).strip() if name else "?",
                "model": model.group(1) if model else "?",
                "port": port,
            }
            print(f"  found {found[key]['serial']}  {addr[0]}  "
                  f"{found[key]['name']}  ({found[key]['model']})")

for _, s in socks:
    s.close()

print()
if not found:
    print("no printers announced themselves.")
    print("That means they are off, asleep, or on a different network --")
    print("not that their address changed.")
else:
    print(f"{len(found)} printer(s):")
    for info in found.values():
        print(f"  {info['serial']}  ->  {info['ip']}")
