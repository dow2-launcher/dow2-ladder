#!/usr/bin/env python3
"""Node quality per player, the node's side (06.11.2026): python3 gameserver/tests/test_nodeq_node.py
A relay and a UDP gateway of this checkout on random local ports. Player A plays through the gateway (DU, as Relay.dll), player B
straight over TCP; both send their peer announce (Steam id inside) and turns. B stops twice for ~1.4 s while A goes on (stalls of
his alone), and once both stop together (a stall of nobody). Then: battle_relay's "leave" lines carry each one's Steam id and his
solo stalls; the gateway's "open" / "close" carry the local port battle_relay sees A as; the collector's node script
(ladder/nodeq_collect.py) joins them into A: via udp with packets / losses, B: via tcp with 2 solo stalls; nodeq judges B bad
(stall) and A good."""
import asyncio, json, os, socket, subprocess, sys, tempfile, time, zlib
HERE = os.path.dirname(os.path.abspath(__file__)); GS = os.path.join(HERE, '..'); LAD = os.path.join(HERE, '..', '..', 'ladder')
sys.path.insert(0, GS); sys.path.insert(0, LAD)
import du_client, nodeq, nodeq_collect
SID = (424242).to_bytes(4, 'little')
SA, SB = '76561198000000011', '76561198000000022'

def free(kind):
    s = socket.socket(socket.AF_INET, kind); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p

def fr(m): return len(m).to_bytes(2, 'big') + m
def hello(pid): return fr(b'\x15' + SID + b'\0' * 4 + pid + b'\x00')
def announce(steam, name, src):
    path = ('/steam/' + steam).encode('utf-16-le'); nm = name.encode('utf-16-le')
    blob = zlib.compress(b'\0' * 8 + (len(path) // 2).to_bytes(4, 'little') + path + b'\0' * 4 + (len(nm) // 2).to_bytes(4, 'little') + nm, 1)
    return fr(b'\x13\x00' + bytes([src]) + b'\x0f\x05' + b'\0' * 16 + b'\x78\x01' + blob[2:])
def turn(x): return fr(b'\x09\xfe\x01\x00' + x)

async def drain(r):
    try:
        while True:
            if not await r.read(65536): return
    except Exception: pass

async def play(port, gwport):
    c = await du_client.open_du('127.0.0.1', gwport)
    assert c, 'the gateway does not answer'
    ra, wa = c; wa.write(b'DWR1' + b'\0' * 6 + hello(b'A' * 8)); da = asyncio.ensure_future(drain(ra))
    await asyncio.sleep(6)                                       # A is the host (no announce within DECIDE s)
    rb, wb = await asyncio.open_connection('127.0.0.1', port, local_addr=('127.0.0.2', 0)); wb.write(b'DWR1' + b'\0' * 6 + hello(b'B' * 8))
    db = asyncio.ensure_future(drain(rb))
    wb.write(announce(SB, 'Bravo', 2)); await asyncio.sleep(1.5)  # a guest, as the game: 13 00 <his number>
    wa.write(announce(SA, 'Alpha', 1)); await asyncio.sleep(0.5)
    async def both(secs, a=True, b=True):
        t0 = time.monotonic()
        while time.monotonic() - t0 < secs:
            if a: wa.write(turn(b'a'))
            if b: wb.write(turn(b'b'))
            await asyncio.sleep(0.02)
    await both(3)
    await both(1.4, b=False)             # B stalls alone
    await both(1)
    await asyncio.sleep(1.4)             # both stop: a stall of nobody
    await both(1)
    await both(1.3, b=False)             # B stalls alone again
    await both(3)
    wa.close(); wb.close(); await asyncio.sleep(1.5); da.cancel(); db.cancel()

def main():
    tmp = tempfile.mkdtemp(prefix='nq_node_'); blog = tmp + '/battle.jsonl'; gwlog = tmp + '/gw.log'
    port, gwport = free(socket.SOCK_STREAM), free(socket.SOCK_DGRAM)
    env = dict(os.environ, RELAY_LOG=blog, RELAY_PEERS='', RELAY_STATS_EVERY='0', UDPGW_STATS_EVERY='0')
    br = subprocess.Popen([sys.executable, os.path.join(GS, 'battle_relay.py'), str(port), '127.0.0.1'], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    gw = subprocess.Popen([sys.executable, os.path.join(GS, 'udp_gateway.py'), str(gwport), '127.0.0.1:%d' % port], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    import threading
    def reader():
        for l in gw.stdout: lines.append('%.3f test python3[1]: %s' % (time.time(), l.rstrip('\n')))
    threading.Thread(target=reader, daemon=True).start()
    time.sleep(1.0)
    fails = []
    try:
        asyncio.run(play(port, gwport)); time.sleep(3)
    finally:
        br.terminate(); gw.terminate(); br.wait(5); gw.wait(5)
    time.sleep(0.3)
    open(gwlog, 'w').write('\n'.join(lines) + '\n')
    ev = [json.loads(l) for l in open(blog)]
    leaves = {e.get('steam'): e for e in ev if e.get('ev') == 'leave'}
    def check(name, ok, info=''):
        print('%-4s %s %s' % ('ok' if ok else 'FAIL', name, info)); ok or fails.append(name)
    check("relay: both leave lines carry the Steam id", set(leaves) == {SA, SB}, sorted(map(str, leaves)))
    a, b = leaves.get(SA, {}), leaves.get(SB, {})
    check("relay: B has 2 stalls of his alone, A none", (b.get('solo'), a.get('solo')) == (2, 0), (b.get('solo'), b.get('max_solo_ms'), a.get('solo')))
    check("relay: A is a gateway connection (127.0.0.1:<lport>)", str(a.get('peer', '')).startswith('127.0.0.1:'), a.get('peer'))
    lport = int(str(a.get('peer', ':0')).rpartition(':')[2] or 0)
    closes = [l for l in lines if ' ev=close ' in l and (' lport=%d ' % lport) in l]
    opens = [l for l in lines if ' ev=open ' in l and ('lport=%d' % lport) in l]
    check("gateway: open and close carry that local port", bool(closes) and bool(opens), (len(opens), len(closes)))
    r = subprocess.run([sys.executable, '-', '0', str(time.time() + 5), '1.2.3.4'], input=nodeq_collect.NODE, capture_output=True, text=True,
                       env=dict(os.environ, NODEQ_BLOG=blog, NODEQ_GWLOG=gwlog))
    try: samples = json.loads(r.stdout)
    except Exception: samples = []; print(r.stdout, r.stderr)
    by = {s['steam']: s for s in samples}
    sa, sb = by.get(SA, {}), by.get(SB, {})
    check("collector: A via udp with the gateway's numbers", sa.get('via') == 'udp' and sa.get('rx', 0) >= 300 and 'resent' in sa, {k: sa.get(k) for k in ('via', 'rx', 'tx', 'resent', 'lost_in', 'dead')})
    check("collector: B via tcp with 2 solo stalls", sb.get('via') == 'tcp' and sb.get('solo_stalls') == 2, {k: sb.get(k) for k in ('via', 'rx', 'solo_stalls', 'max_solo_ms')})
    ja, jb = nodeq.judge_match(sa), nodeq.judge_match(sb)
    check("nodeq: A good, B bad (stall)", ja and jb and (ja[0], jb[0], jb[1]) == (False, True, ['stall']), (ja, jb))
    r = subprocess.run([sys.executable, '-', '0', str(time.time() + 5), '127.0.0.1'], input=nodeq_collect.NODE, capture_output=True, text=True,
                       env=dict(os.environ, NODEQ_BLOG=blog, NODEQ_GWLOG=gwlog))
    s2 = {s['steam'] for s in json.loads(r.stdout or '[]')}
    check("collector: a connection from one of our nodes (chain hop) is skipped", s2 == {SB}, sorted(s2))
    import shutil; shutil.rmtree(tmp, ignore_errors=True)
    print('FAILED: %s' % fails if fails else 'ALL OK'); return 1 if fails else 0

if __name__ == '__main__':
    sys.exit(main())
