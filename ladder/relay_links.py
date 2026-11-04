#!/usr/bin/env python3
"""relay_links.py - the round trips BETWEEN our game nodes for the relay chain (04.11.2026), into /srv/ladder/data/relay_links.json.

A native automatch player who can't reach the match's node plays through his own nearest node (Relay.dll 22 "DWR4"); the node
passes him on over our UDP tunnel (DU) to the node of the session. The ladder (_best_relay, chain) counts such a player as
his ping to his node + this node -> node round trip. Measured from each node (it opens the hop), DU PING/PONG of the other
node's udp_gateway (UDP 47100), median of 10; no answer = no link (that chain is never offered).
Run as root on rts (ssh to the nodes): relay_links.py [--print]. Timer: relay-links.timer (every 30 min).
"""
import json, os, subprocess, sys, time

RELAYS = '/srv/ladder/data/relays.json'
OUT = '/srv/ladder/data/relay_links.json'
SSH = {'83.217.192.34': 'timeweb', '116.202.106.150': 'root@iggy', '15.220.68.107': 'root@polsha', '91.107.122.186': 'root@ru.pivolan.ru'}
PROBE = r'''
import json, os, socket, struct, sys, time
out = {}
for ip in sys.argv[1:]:
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); u.settimeout(1.0); r = []
    for k in range(10):
        cid = os.urandom(4); t = time.perf_counter(); u.sendto(b'DU\x06' + cid + b'links', (ip, 47100))
        try:
            while True:
                d = u.recv(64)
                if d[:3] == b'DU\x07' and d[3:7] == cid: r.append((time.perf_counter() - t) * 1000); break
        except socket.timeout: pass
        time.sleep(0.05)
    r.sort(); out[ip] = round(r[len(r) // 2], 1) if len(r) >= 5 else -1
print(json.dumps(out))
'''


def main():
    ips = [r['ip'] for r in json.load(open(RELAYS)).get('relays', []) if r.get('ip')]
    links = {}
    for a in ips:
        h = SSH.get(a)
        if not h: continue
        others = [b for b in ips if b != a]
        try:
            p = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', h, 'python3', '-', *others], input=PROBE,
                               capture_output=True, text=True, timeout=60)
            links[a] = {b: v for b, v in json.loads(p.stdout.strip().splitlines()[-1]).items() if v > 0}
        except Exception as e:
            print('%s: %r' % (a, e), file=sys.stderr)
    doc = {'v': 1, 'ts': int(time.time()), 'links': links}
    if '--print' in sys.argv: print(json.dumps(doc, indent=1)); return
    if not links: sys.exit('no node answered - %s kept' % OUT)
    tmp = OUT + '.tmp'
    with open(tmp, 'w') as f: json.dump(doc, f, indent=1)
    os.chmod(tmp, 0o644); os.replace(tmp, OUT)
    print('wrote %s: %s' % (OUT, ', '.join('%s>%s %s' % (a, b, v) for a, x in links.items() for b, v in x.items())))


if __name__ == '__main__':
    main()
