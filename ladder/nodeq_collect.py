#!/usr/bin/env python3
"""nodeq_collect.py - real matches into the node quality per player (ladder nodeq.py, owner 06.11.2026).

Every few minutes (nodeq-collect.timer) each game node is asked over ssh for the players who left a session since the last run:
the node's battle_relay "leave" line (Steam id from his peer announce, turns, stalls of his alone >= 1 s) joined with its UDP
gateway's "close" line of his connection by the local port (battle_relay sees a gateway connection as 127.0.0.1:<lport>): the
player's address, packets up (rx) / down (tx), holes and copies that filled one (losses up), resends (losses down), "dead" (the
connection died: 10 resends unanswered). A chain hop (the connection comes from another node of ours) is not the player's way -
skipped; a straight TCP connection (no gateway) gives only the stalls. Under 300 turns (half a minute of play) - skipped.
The samples go to the ladder: POST 127.0.0.1:8217/ladder/api/nq/match with the own_lobby token (loopback only), 100 at a time.
Run as root on rts: nodeq_collect.py [--print] [--since <unix time>]. State: /var/lib/nodeq-collect/state.json (per node: done up to).
"""
import json, os, subprocess, sys, time, urllib.request

RELAYS = '/srv/ladder/data/relays.json'
TOKEN = '/srv/ladder/data/nm_token'
STATE = os.environ.get('NODEQ_STATE', '/var/lib/nodeq-collect/state.json')
LADDER = os.environ.get('NODEQ_LADDER', 'http://127.0.0.1:8217/ladder/api/nq/match')
SSH = {'83.217.192.34': 'node-timeweb', '116.202.106.150': 'node-iggy', '15.220.68.107': 'node-polsha', '91.107.122.186': 'node-rupivolan'}  # ~/.ssh/config: User dow2deploy (no root on the nodes)
LAG = 150            # s: a leave this fresh waits for the next run (the gateway's close line comes up to ~20 s after it)
FIRST = 3 * 86400    # s back on the very first run of a node

NODE = r'''
import json, os, subprocess, sys, time
since, upto, ours = float(sys.argv[1]), float(sys.argv[2]), set(sys.argv[3].split(','))
LOG = os.environ.get('NODEQ_BLOG', '/var/lib/dow2battle/battle.jsonl')
GW = os.environ.get('NODEQ_GWLOG')                                   # tests: the gateway's lines from a file (journalctl -o short-unix shape)
leaves = []
try:
    with open(LOG, 'rb') as f:
        f.seek(0, 2); n = f.tell(); f.seek(max(0, n - (24 << 20)))
        for l in f.read().decode('utf-8', 'replace').splitlines():
            if '"leave"' not in l or '"steam"' not in l: continue
            try: e = json.loads(l)
            except Exception: continue
            if e.get('ev') == 'leave' and since < e.get('t', 0) <= upto and e.get('steam'): leaves.append(e)
except FileNotFoundError: pass
closes = {}
if leaves:
    j = open(GW).read() if GW else subprocess.run(['journalctl', '-u', 'dow2-udpgw', '--since', '@%d' % (min(e['t'] for e in leaves) - 600),
                        '--until', '@%d' % (upto + 600), '-o', 'short-unix', '--no-pager'], capture_output=True, text=True).stdout
    for line in j.splitlines():
        if ' ev=close ' not in line or ' lport=' not in line: continue
        try:
            ts = float(line.split()[0]); kv = dict(x.split('=', 1) for x in line.split() if '=' in x)
            closes.setdefault(int(kv['lport']), []).append((ts, kv))
        except Exception: continue
out = []
for e in leaves:
    if (e.get('turns') or 0) < 300: continue
    host, _, port = str(e.get('peer') or '').rpartition(':')
    s = dict(steam=e['steam'], t=e['t'], sid=e.get('sid'), ref='%s:%s:%s' % (e.get('sid'), e.get('idx'), int(e['t'])),
             solo_stalls=e.get('solo', 0), max_solo_ms=e.get('max_solo_ms', 0), turns=e.get('turns'))
    if host == '127.0.0.1':
        c = [x for x in closes.get(int(port or 0), []) if abs(x[0] - e['t']) < 180]
        if not c: continue
        ts, kv = min(c, key=lambda x: abs(x[0] - e['t']))
        if kv.get('peer') in ours: continue                          # a chain hop from another node of ours
        num = lambda k: int(float(kv.get(k, 0) or 0))
        s.update(via='udp', rx=num('rx'), tx=num('tx'), lost_in=num('lost_in'), filled=num('filled'), resent=num('resent'),
                 dead=kv.get('by') == 'dead', srtt_ms=num('srtt_ms'), secs=float(kv.get('secs', 0) or 0))
    else:
        if host in ours: continue
        s.update(via='tcp', rx=e.get('turns'), tx=e.get('turns'))
    out.append(s)
print(json.dumps(out))
'''


def load_state():
    try: return json.load(open(STATE))
    except Exception: return {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + '.tmp'; json.dump(st, open(tmp, 'w')); os.replace(tmp, STATE)


def post(samples):
    tok = open(TOKEN).read().strip(); added = 0
    for i in range(0, len(samples), 100):
        req = urllib.request.Request(LADDER, data=json.dumps({'samples': samples[i:i + 100]}).encode(),
                                     headers={'Content-Type': 'application/json', 'X-NM-Token': tok})
        added += json.load(urllib.request.urlopen(req, timeout=20)).get('added', 0)
    return added


def main():
    show = '--print' in sys.argv
    force_since = float(sys.argv[sys.argv.index('--since') + 1]) if '--since' in sys.argv else None
    ips = [r['ip'] for r in json.load(open(RELAYS)).get('relays', []) if r.get('ip')]
    st = load_state(); now = time.time(); upto = now - LAG
    for ip in ips:
        host = SSH.get(ip)
        if not host: continue
        since = force_since if force_since is not None else st.get(ip, now - FIRST)
        try:
            r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', host, 'python3', '-', str(since), str(upto), ','.join(ips)],
                               input=NODE, capture_output=True, text=True, timeout=120)
            samples = json.loads(r.stdout or 'null')
            if samples is None: raise RuntimeError((r.stderr or '').strip()[-300:])
        except Exception as e:
            print('nodeq: %s (%s): %r' % (ip, host, e), flush=True); continue
        for s in samples: s['ip'] = ip; s['ref'] = '%s:%s' % (ip, s['ref'])
        if show:
            for s in samples: print(ip, json.dumps(s))
            continue
        try: added = post(samples) if samples else 0
        except Exception as e:
            print('nodeq: %s: post: %r' % (ip, e), flush=True); continue
        st[ip] = upto
        print('nodeq: %s: %d leaves, %d new' % (ip, len(samples), added), flush=True)
    if not show: save_state(st)


if __name__ == '__main__':
    main()
